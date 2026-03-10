from flask import Flask, render_template, request, jsonify, redirect, url_for
from database import init_db, reset_db, get_db_connection
from scheduler import run_advanced_scheduling
from scheduler_core import GreedyScheduler, GeneticScheduler, SimulatedAnnealingScheduler
from api.routes import api_bp
from api.mes_orders import mes_api_bp
import datetime

app = Flask(__name__)
init_db()

app.register_blueprint(api_bp)
app.register_blueprint(mes_api_bp)

@app.route('/')
def index():
    conn = get_db_connection()
    resources = conn.execute("SELECT * FROM resources").fetchall()
    conn.close()
    return render_template('index.html', resources=resources)

@app.route('/manage')
def manage():
    conn = get_db_connection()
    resources = conn.execute("SELECT * FROM resources").fetchall()
    orders = conn.execute("""
        SELECT * FROM work_orders 
        ORDER BY plan_type DESC, priority ASC
    """).fetchall()
    conn.close()
    return render_template('manage.html', resources=resources, orders=orders)

@app.route('/api/schedule_data')
def get_gantt_data():
    conn = get_db_connection()
    
    # 1. 获取资源组
    resources = conn.execute("SELECT * FROM resources ORDER BY id").fetchall()
    groups = []
    for r in resources:
        groups.append({
            "id": r['id'],
            "content": f"<span style='font-weight:bold;'>{r['name']}</span>",
            "value": r['id']
        })

    # 2. 获取任务数据
    orders = conn.execute("""
        SELECT w.*, r.name as res_name 
        FROM work_orders w
        JOIN resources r ON w.resource_id = r.id
        WHERE w.status IN ('Scheduled', 'Delayed') 
           OR w.status LIKE 'Scheduled%' 
           OR w.status LIKE 'Delayed%'
    """).fetchall()
    
    # --- [阶段四核心] 预处理：记录所有 B 面的结束时间，用于校验 48 小时规则 ---
    b_side_ends = {}
    for row in orders:
        if row['smt_side'] in ['B', 'B面', 'Back'] and row['planned_end']:
            try:
                e_str = str(row['planned_end']).replace('T', ' ').replace('/', '-').strip()
                e_dt = datetime.datetime.strptime(e_str, '%Y-%m-%d %H:%M') if len(e_str) <= 16 else datetime.datetime.strptime(e_str, '%Y-%m-%d %H:%M:%S')
                b_side_ends[row['job_id']] = e_dt
            except:
                pass

    items = []
    
    # --- [阶段四核心] 渲染设备保养阴影块 ---
    try:
        maints = conn.execute("SELECT * FROM equipment_maintenance").fetchall()
        for m in maints:
            items.append({
                "id": f"maint_{m['id']}",
                "group": m['line_id'],
                "start": m['start_time'].replace(' ', 'T'),
                "end": m['end_time'].replace(' ', 'T'),
                "type": "background",
                "className": "vis-item-maintenance",
                "title": f"【{m['type']}】 {m['reason']}"
            })
    except Exception as e:
        print(f"读取保养记录失败: {e}")

    conn.close()

    for row in orders:
        is_time_insufficient = False
        is_ab_violation = False
        duration_min = 0
        std_time = float(row['std_time']) if row['std_time'] else 0
        
        s_dt, e_dt = None, None
        
        if row['planned_start'] and row['planned_end']:
            try:
                s_str = str(row['planned_start']).replace('T', ' ').replace('/', '-').strip()
                e_str = str(row['planned_end']).replace('T', ' ').replace('/', '-').strip()
                
                s_dt = datetime.datetime.strptime(s_str, '%Y-%m-%d %H:%M') if len(s_str) <= 16 else datetime.datetime.strptime(s_str, '%Y-%m-%d %H:%M:%S')
                e_dt = datetime.datetime.strptime(e_str, '%Y-%m-%d %H:%M') if len(e_str) <= 16 else datetime.datetime.strptime(e_str, '%Y-%m-%d %H:%M:%S')
                
                duration_min = (e_dt - s_dt).total_seconds() / 60
                
                if std_time > 0 and duration_min < (std_time - 1):
                    is_time_insufficient = True
                    
                # --- [阶段四核心] 校验 A 面是否超过 B 面产出 48 小时 ---
                if row['smt_side'] in ['A', 'A面', 'Front'] and row['job_id'] in b_side_ends:
                    b_end = b_side_ends[row['job_id']]
                    gap_hours = (s_dt - b_end).total_seconds() / 3600
                    if gap_hours > 48:
                        is_ab_violation = True
            except:
                pass 

        className = 'vis-item-blue'
        content_html = row['task_id']

        # 样式优先级判定 (报警优先)
        if is_ab_violation:
            className = 'vis-item-error'
            content_html = f"🚨 {row['task_id']} <small>(>48h违反!)</small>"
        elif is_time_insufficient:
            className = 'vis-item-warning'
            content_html = f"⚠️ {row['task_id']} <small>({int(duration_min)}/{int(std_time)}m)</small>"
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']:
            className = 'vis-item-red'
        elif row['is_locked']:
            className = 'vis-item-dark'
        elif row['plan_type'] == 'SIMULATION':
            className = 'vis-item-striped'

        items.append({
            "id": row['task_id'],
            "group": row['resource_id'],
            "content": content_html, 
            "start": row['planned_start'].replace(' ', 'T'),
            "end": row['planned_end'].replace(' ', 'T'),
            "className": className,
            "title": f"任务: {row['task_id']}<br>标准: {int(std_time)}m | 计划: {int(duration_min)}m",
            "data": {
                "name": row['task_id'],
                "resource_id": row['resource_id'],
                "is_locked": row['is_locked'],
                "std_time": std_time, 
                "status": row['status']
            }
        })
        
    return jsonify({"groups": groups, "items": items})

@app.route('/api/run', methods=['POST'])
def run_schedule():
    data = request.json
    mode = data.get('mode', 'SIMULATION')
    algo = data.get('algorithm', 'greedy')
    
    conn = get_db_connection()
    try:
        orders_db = conn.execute("SELECT * FROM work_orders WHERE status IN ('Pending', 'Scheduled') AND (is_locked = 0 OR is_locked IS NULL)").fetchall()
        resources_db = conn.execute("SELECT * FROM resources").fetchall()
        
        orders_list = [dict(row) for row in orders_db]
        resources_list = [dict(row) for row in resources_db]

        if not orders_list:
             return jsonify({'success': True, 'message': '没有可排产的任务'})
        
        scheduler = None
        if algo == 'ga':
            scheduler = GeneticScheduler(orders_list, resources_list)
            best_schedule = scheduler.run(pop_size=50, generations=30)
        elif algo == 'sa':
            scheduler = SimulatedAnnealingScheduler(orders_list, resources_list)
            best_schedule = scheduler.run(initial_temp=10000)
        else:
            scheduler = GreedyScheduler(orders_list, resources_list)
            best_schedule = scheduler.run()

        for item in best_schedule:
            s_str = item['planned_start'].strftime('%Y-%m-%d %H:%M')
            e_str = item['planned_end'].strftime('%Y-%m-%d %H:%M')
            status = 'Scheduled'
            
            conn.execute("""
                UPDATE work_orders 
                SET planned_start = ?, planned_end = ?, status = ?, plan_type = ?, resource_id = ?
                WHERE task_id = ?
            """, (s_str, e_str, status, mode, item['resource_id'], item['task_id']))

        conn.commit()
        return jsonify({'success': True, 'message': f'排产完成！已调度 {len(best_schedule)} 个任务'})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/update_order_manual', methods=['POST'])
def update_order_manual():
    data = request.json
    task_id = data.get('task_id')
    start_str = data.get('planned_start')
    end_str = data.get('planned_end')
    is_locked = data.get('is_locked')
    resource_id = data.get('resource_id')

    if start_str: start_str = start_str.replace('T', ' ')
    if end_str: end_str = end_str.replace('T', ' ')

    conn = get_db_connection()
    new_status = 'Scheduled' if (start_str and end_str) else 'Pending'
    
    if resource_id:
        conn.execute('''UPDATE work_orders SET planned_start = ?, planned_end = ?, is_locked = ?, status = ?, resource_id = ? WHERE task_id = ?''', (start_str, end_str, is_locked, new_status, resource_id, task_id))
    else:
        conn.execute('''UPDATE work_orders SET planned_start = ?, planned_end = ?, is_locked = ?, status = ? WHERE task_id = ?''', (start_str, end_str, is_locked, new_status, task_id))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"任务 {task_id} 已更新"})

@app.route('/manage/reset', methods=['GET', 'POST'])
def reset_data():
    """重置系统：清空旧数据，并从接口获取 MES 已经拆分好的工单数据"""
    from database import get_db_connection
    from datetime import datetime
    from flask import redirect, url_for
    import traceback
    
    try:
        # 1. 清空旧工单
        conn = get_db_connection()
        conn.execute('DELETE FROM work_orders')
        conn.commit()
        
        # 2. 从模拟 MES/SAP 接口同步已拆分好的工序级工单
        from adapters.base import AdapterFactory
        sap = AdapterFactory.get_sap_adapter()
        orders = sap.get_orders_from_zpp008() # 现在拿到的是直接可以排产的子任务
        now = datetime.now().isoformat()
        
        saved = 0
        for order in orders:
            # 3. 直接将接口传来的明细无脑入库，彻底实现系统解耦
            conn.execute("""
                INSERT INTO work_orders (
                    task_id, job_id, product_code, resource_id, qty, std_time,
                    priority, material_time, software_time, deadline, smt_side,
                    related_task_id, process_req, status, planned_start, planned_end,
                    setup_time, is_locked, plan_type, created_at, updated_at,
                    workshop, component_code, component_desc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.get('task_id'), order.get('job_id'), order.get('product_code'), None, 
                order.get('qty'), order.get('std_time'), order.get('priority'), 
                '', '', order.get('demand_date'), order.get('smt_side'), 
                order.get('related_task_id'), None, 'Pending', None, None, 
                10, 0, 'OFFICIAL', now, now,
                order.get('workshop'), order.get('component_code'), order.get('component_desc')
            ))
            saved += 1
        
        conn.commit()
        conn.close()
        return redirect(url_for('config_page') + '?reset=ok&count=' + str(saved))
        
    except Exception as e:
        traceback.print_exc()
        return redirect(url_for('config_page') + '?reset=fail&msg=' + str(e))
    
# --- [阶段四核心] 新增设备保养 API ---
@app.route('/api/maintenance', methods=['POST'])
def add_maintenance():
    data = request.json
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO equipment_maintenance (line_id, start_time, end_time, type, reason)
            VALUES (?, ?, ?, ?, ?)
        ''', (data['line_id'], data['start_time'].replace('T', ' '), data['end_time'].replace('T', ' '), data['type'], data['reason']))
        conn.commit()
        return jsonify({"success": True, "message": "已添加设备停机时间！"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
    finally:
        conn.close()

# 其余页面路由保持极简结构（为节省篇幅省略未修改部分，确保核心调度 API 完整）
@app.route('/resources')
def resources_page(): return render_template('resources.html')
@app.route('/config')
def config_page(): return render_template('config.html')
@app.route('/dashboard/<workshop>')
def dashboard_workshop(workshop): return render_template('dashboard_workshop.html', workshop_code=workshop.upper(), workshop_name=workshop.upper())

# === 🛠️ 终极修复工具：同步真实的 SMT/DIP 产线基础数据 ===
@app.route('/fix_resources')
def fix_resources():
    conn = get_db_connection()
    try:
        # 1. 清空旧的无效演示资源
        conn.execute("DELETE FROM resources")
        
        # 2. 按照 PRD 生成所有真实的 SMT 线体
        smt_lines = [f'S{i:02d}' for i in list(range(1, 50)) + [98, 99]]
        for line in smt_lines:
            conn.execute("INSERT INTO resources (id, name, type) VALUES (?, ?, ?)", 
                         (line, f'SMT线-{line}', 'SMT'))
            
        # 3. 按照 PRD 生成所有真实的 DIP 线体
        dip_lines = [f'D{i:02d}' for i in range(1, 23)]
        for line in dip_lines:
            conn.execute("INSERT INTO resources (id, name, type) VALUES (?, ?, ?)", 
                         (line, f'DIP线-{line}', 'DIP'))
            
        conn.commit()
        return "<h3>✅ 产线资源修复成功！已自动生成真实的 S01-S49 及 D01-D22 线体。</h3><a href='/manage'>👉 点击这里返回数据管理中心</a>"
    except Exception as e:
        return f"修复失败: {e}"
    finally:
        conn.close()

# === 新增：车间日排产计划矩阵 API (类 Excel 视图) ===
@app.route('/api/schedule_matrix/<workshop>')
def schedule_matrix(workshop):
    from datetime import datetime, timedelta
    conn = get_db_connection()
    
    # 筛选该车间已排产的任务
    if workshop == 'ALL':
        orders = conn.execute("SELECT * FROM work_orders WHERE planned_start IS NOT NULL AND status != 'Pending' ORDER BY resource_id, planned_start").fetchall()
    else:
        orders = conn.execute("SELECT * FROM work_orders WHERE workshop=? AND planned_start IS NOT NULL AND status != 'Pending' ORDER BY resource_id, planned_start", (workshop,)).fetchall()
    conn.close()

    # 构建日期表头：从今天开始的 15 天
    #today = datetime.now().date()
    #date_list = [(today + timedelta(days=i)) for i in range(15)]
    #date_strs = [d.strftime('%Y-%m-%d') for d in date_list]

    # 构建日期表头：从明天开始的 15 天
    tomorrow = datetime.now().date() + timedelta(days=1)
    date_list = [(tomorrow + timedelta(days=i)) for i in range(15)]
    date_strs = [d.strftime('%Y-%m-%d') for d in date_list]

    matrix_data = []
    for row in orders:
        try:
            # 【修复核心】: 将 sqlite3.Row 转换为标准字典，防止 .get() 方法报错
            row_dict = dict(row) 
            
            # 解析时间
            start_dt = datetime.strptime(str(row_dict['planned_start'])[:16].replace('T', ' '), '%Y-%m-%d %H:%M')
            end_dt = datetime.strptime(str(row_dict['planned_end'])[:16].replace('T', ' '), '%Y-%m-%d %H:%M')

            # 计算总耗时 (分钟) 和总数量
            total_mins = max(1.0, (end_dt - start_dt).total_seconds() / 60.0)
            qty = float(row_dict['qty'] or 0)

            daily_dist = {}
            if qty > 0:
                d = start_dt.date()
                end_day = end_dt.date()

                # 将数量按天拆分
                while d <= end_day:
                    d_str = d.strftime('%Y-%m-%d')
                    day_start = datetime.combine(d, datetime.min.time())
                    day_end = day_start + timedelta(days=1)

                    # 计算当前日期的重叠时间
                    overlap_start = max(start_dt, day_start)
                    overlap_end = min(end_dt, day_end)
                    overlap_mins = max(0, (overlap_end - overlap_start).total_seconds() / 60.0)

                    if overlap_mins > 0:
                        # 按时间比例分配当天的排产数量
                        daily_qty = int(round(qty * (overlap_mins / total_mins)))
                        daily_dist[d_str] = daily_qty

                    d += timedelta(days=1)

            matrix_data.append({
                'task_id': row_dict['task_id'],
                'job_id': row_dict['job_id'],
                'product_code': row_dict['product_code'],
                'component_desc': row_dict['component_desc'] or '-',
                'resource_id': row_dict['resource_id'] or 'AUTO',
                'smt_side': row_dict.get('smt_side') or '-',
                'qty': int(qty),
                'planned_start': str(row_dict['planned_start'])[:16].replace('T', ' '),
                'status': row_dict['status'],
                'daily_dist': daily_dist
            })
        except Exception as e:
            import traceback
            traceback.print_exc() # 在后台打印具体的错误，防止死静
            continue

    return jsonify({
        'dates': date_strs,
        'orders': matrix_data
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0', threaded=True)