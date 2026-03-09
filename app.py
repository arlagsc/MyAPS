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

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0', threaded=True)