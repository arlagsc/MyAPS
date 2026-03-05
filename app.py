from flask import Flask, render_template, request, jsonify, redirect, url_for
from database import init_db, reset_db, get_db_connection
from scheduler import run_advanced_scheduling
from scheduler_core import GreedyScheduler, GeneticScheduler, SimulatedAnnealingScheduler
from api.routes import api_bp
import datetime

app = Flask(__name__)
init_db()

# 注册 API 蓝图
app.register_blueprint(api_bp)

# 1. 修改 index 路由：获取 resources 并传给模板
@app.route('/')
def index():
    conn = get_db_connection()
    # 获取所有产线，传给前端做下拉框
    resources = conn.execute("SELECT * FROM resources").fetchall()
    conn.close()
    return render_template('index.html', resources=resources)

@app.route('/manage')
def manage():
    conn = get_db_connection()
    resources = conn.execute("SELECT * FROM resources").fetchall()
    # 按照模拟/正式分开显示
    orders = conn.execute("""
        SELECT * FROM work_orders 
        ORDER BY plan_type DESC, priority ASC
    """).fetchall()
    conn.close()
    return render_template('manage.html', resources=resources, orders=orders)

# --- API ---
# app.py

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
    conn.close()
    
    items = []
    for row in orders:
        # === 变量初始化 ===
        is_time_insufficient = False
        duration_min = 0
        std_time = 0
        
        # 安全获取标准工时
        try:
            if row['std_time']:
                std_time = float(row['std_time'])
        except:
            std_time = 0
        
        # === 核心修复：修复 datetime 引用错误 ===
        if row['planned_start'] and row['planned_end']:
            try:
                # 1. 格式清洗：同时兼容 '/' 和 '-'，去掉 'T'
                s_str = str(row['planned_start']).replace('T', ' ').replace('/', '-').strip()
                e_str = str(row['planned_end']).replace('T', ' ').replace('/', '-').strip()
                
                # 2. 解析开始时间 (使用 datetime.datetime.strptime)
                try: 
                    s_dt = datetime.datetime.strptime(s_str, '%Y-%m-%d %H:%M')
                except: 
                    s_dt = datetime.datetime.strptime(s_str, '%Y-%m-%d %H:%M:%S')
                    
                # 3. 解析结束时间
                try: 
                    e_dt = datetime.datetime.strptime(e_str, '%Y-%m-%d %H:%M')
                except: 
                    e_dt = datetime.datetime.strptime(e_str, '%Y-%m-%d %H:%M:%S')
                
                # 4. 计算分钟差
                duration_min = (e_dt - s_dt).total_seconds() / 60
                
                # 5. 判定异常
                if std_time > 0 and duration_min < (std_time - 1):
                    is_time_insufficient = True
                    
                # --- 临时 Debug (确认修复后可删除) ---
                # if row['task_id'] == 'WO-WaitMat-01':
                #     print(f"DEBUG {row['task_id']}: 计划={duration_min}m, 标准={std_time}m, 结果={is_time_insufficient}")
                    
            except Exception as e:
                # 打印详细错误堆栈，帮助定位 import 问题
                import traceback
                print(f"后端时间计算错误 Task {row['task_id']}: {e}")
                # traceback.print_exc() 

        # === 样式优先级判定 ===
        
        className = 'vis-item-blue' # 默认
        
        # 优先级 1: 时间不足 -> 警告 (最优先)
        if is_time_insufficient:
            className = 'vis-item-warning'
            
        # 优先级 2: 延期 -> 红色
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']:
            className = 'vis-item-red'

        # 优先级 3: 锁定 -> 深色
        elif row['is_locked']:
            className = 'vis-item-dark'

        # 优先级 4: 模拟 -> 条纹
        elif row['plan_type'] == 'SIMULATION':
            className = 'vis-item-striped'
            
        # ==========================================

        # 内容显示优化
        content_html = row['task_id']
        if is_time_insufficient:
            content_html = f"⚠️ {row['task_id']} <small>({int(duration_min)}/{int(std_time)}m)</small>"

        # ================== DEBUG 代码开始 ==================
        # 请把 'WO-WaitMat-01' 换成您当前出现问题的那个任务ID
        if row['task_id'] == 'WO-WaitMat-01': 
            print("\n" + "="*30)
            print(f"正在调试任务: {row['task_id']}")
            print(f"1. 原始开始时间: '{row['planned_start']}' (类型: {type(row['planned_start'])})")
            print(f"2. 原始结束时间: '{row['planned_end']}' (类型: {type(row['planned_end'])})")
            print(f"3. 标准工时(std_time): {std_time} (类型: {type(std_time)})")
            
            # 打印中间计算变量
            try:
                # 重新模拟一下解析过程看看会不会报错
                s_str_debug = str(row['planned_start']).replace('T', ' ').replace('/', '-').strip()
                e_str_debug = str(row['planned_end']).replace('T', ' ').replace('/', '-').strip()
                print(f"4. 清洗后时间字符串: Start='{s_str_debug}', End='{e_str_debug}'")
                
                # 打印计算结果
                print(f"5. 计算出的时长(duration_min): {duration_min}")
                print(f"6. 判定条件: {duration_min} < {std_time - 1}")
                print(f"7. 判定结果(is_time_insufficient): {is_time_insufficient}")
                print(f"8. 最终分配的颜色类(className): {className}")
            except Exception as e:
                print(f"!!! 调试过程中发现异常: {e}")
            print("="*30 + "\n")
        # ================== DEBUG 代码结束 ==================

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

'''
# 2. 修改 get_gantt_data：增加对时间不足的检测和显示
@app.route('/api/schedule_data')
def get_gantt_data():
    conn = get_db_connection()
    
    # 1. 资源组
    resources = conn.execute("SELECT * FROM resources ORDER BY id").fetchall()
    groups = [{"id": r['id'], "content": f"<span style='font-weight:bold;'>{r['name']}</span>", "value": r['id']} for r in resources]

    # 2. 任务数据
    orders = conn.execute("""
        SELECT w.*, r.name as res_name 
        FROM work_orders w
        JOIN resources r ON w.resource_id = r.id
        WHERE w.status IN ('Scheduled', 'Delayed') 
           OR w.status LIKE 'Scheduled%' 
           OR w.status LIKE 'Delayed%'
    """).fetchall()
    conn.close()
    
    items = []
    for row in orders:
        # 基础数据处理
        std_time = float(row['std_time']) if row['std_time'] else 0
        duration_min = 0
        is_time_insufficient = False
        
        # 后端预计算（用于初始加载）
        if row['planned_start'] and row['planned_end']:
            try:
                s_str = row['planned_start'].replace('T', ' ').strip()
                e_str = row['planned_end'].replace('T', ' ').strip()
                # 兼容秒
                try: s_dt = datetime.strptime(s_str, '%Y-%m-%d %H:%M')
                except: s_dt = datetime.strptime(s_str, '%Y-%m-%d %H:%M:%S')
                try: e_dt = datetime.strptime(e_str, '%Y-%m-%d %H:%M')
                except: e_dt = datetime.strptime(e_str, '%Y-%m-%d %H:%M:%S')
                
                duration_min = (e_dt - s_dt).total_seconds() / 60
                if duration_min < (std_time - 1): # 允许1分钟误差
                    is_time_insufficient = True
            except: pass

        # 样式判定
        className = 'vis-item-blue'
        if row['plan_type'] == 'SIMULATION': className = 'vis-item-striped'
        elif is_time_insufficient: className = 'vis-item-warning' # 优先显示警告
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']: className = 'vis-item-red'
        elif row['is_locked']: className = 'vis-item-dark'

        # 内容显示
        content_html = row['task_id']
        if is_time_insufficient:
            content_html = f"⚠️ {row['task_id']} <small>({int(duration_min)}/{int(std_time)}m)</small>"

        items.append({
            "id": row['task_id'],
            "group": row['resource_id'],
            "content": content_html, 
            "start": row['planned_start'].replace(' ', 'T'),
            "end": row['planned_end'].replace(' ', 'T'),
            "className": className,
            "title": f"任务: {row['task_id']}<br>标准: {int(std_time)}m | 计划: {int(duration_min)}m",
            # === 关键新增：把 std_time 传给前端 ===
            "data": {
                "name": row['task_id'],
                "resource_id": row['resource_id'],
                "is_locked": row['is_locked'],
                "std_time": std_time,  # <--- 前端计算需要这个
                "status": row['status']
            }
        })
        
    return jsonify({"groups": groups, "items": items})


@app.route('/api/schedule_data')
def get_gantt_data():
    conn = get_db_connection()
    
    # 1. 获取所有资源 (作为甘特图的 Groups / Y轴行)
    resources = conn.execute("SELECT * FROM resources ORDER BY id").fetchall()
    
    # 构建 Groups 数据
    groups = []
    for r in resources:
        groups.append({
            "id": r['id'],
            "content": f"<span style='font-weight:bold;'>{r['name']}</span>", # 支持HTML
            "value": r['id'] # 用于排序
        })

    # 2. 获取所有任务 (作为甘特图的 Items)
    orders = conn.execute("""
        SELECT w.*, r.name as res_name 
        FROM work_orders w
        JOIN resources r ON w.resource_id = r.id
        WHERE w.status IN ('Scheduled', 'Delayed') 
           OR w.status LIKE 'Scheduled%' 
           OR w.status LIKE 'Delayed%'
    """).fetchall()
    conn.close()
    
    items = []
    for row in orders:
        # 颜色样式映射
        className = 'vis-item-blue' # 默认
        if row['plan_type'] == 'SIMULATION':
            className = 'vis-item-striped'
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']:
            className = 'vis-item-red'
        elif row['is_locked']:
            className = 'vis-item-dark'
        else:
            # 根据产线ID的哈希值或最后一位数字来定色，或者直接用蓝色
            pass 

        # 构建 Item 数据
        items.append({
            "id": row['task_id'],
            "group": row['resource_id'], # 关键：指定它属于哪一行
            "content": row['task_id'],   # 显示在条块上的文字
            "start": row['planned_start'].replace(' ', 'T'),
            "end": row['planned_end'].replace(' ', 'T'),
            "className": className,
            "title": f"任务: {row['task_id']}<br>产线: {row['res_name']}<br>时间: {row['planned_start']} - {row['planned_end']}", # Tooltip
            
            # 附带的业务数据，供前端修改使用
            "data": {
                "name": row['task_id'],
                "resource_id": row['resource_id'],
                "is_locked": row['is_locked'],
                "status": row['status']
            }
        })
        
    # 返回 {groups, items} 结构
    return jsonify({"groups": groups, "items": items})


# 2. 修改 get_gantt_data：在返回的数据中增加 resource_id
@app.route('/api/schedule_data')
def get_gantt_data():
    conn = get_db_connection()
    
    # 1. 先查出所有产线，并建立一个 "ID -> 索引" 的映射字典
    # 例如: {'Line-01': 0, 'Line-02': 1, 'SMT-01': 2 ...}
    all_resources = conn.execute("SELECT id FROM resources ORDER BY id").fetchall()
    res_index_map = {row['id']: i for i, row in enumerate(all_resources)}
    
    # 2. 查询任务数据
    orders = conn.execute("""
        SELECT w.*, r.name as res_name 
        FROM work_orders w
        JOIN resources r ON w.resource_id = r.id
        WHERE w.status IN ('Scheduled', 'Delayed') 
           OR w.status LIKE 'Scheduled%' 
           OR w.status LIKE 'Delayed%'
        ORDER BY w.resource_id ASC, w.planned_start ASC
    """).fetchall()
    conn.close()
    
    data = []
    for row in orders:
        # === 颜色逻辑核心修改 ===
        
        # 优先级 1: 模拟订单 (条纹)
        if row['plan_type'] == 'SIMULATION':
            custom_class = 'bar-striped'
            
        # 优先级 2: 延期/警告 (红色 - 最需要注意)
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']:
            custom_class = 'bar-red'
            
        # 优先级 3: 已锁定 (深灰色 - 表示不可动)
        elif row['is_locked']:
            custom_class = 'bar-dark'
            
        # 优先级 4: 正常任务 -> 使用产线专属色
        else:
            # 获取该产线的索引，如果找不到默认用 0
            idx = res_index_map.get(row['resource_id'], 0)
            # 取模运算 (idx % 6)，确保颜色在 0-5 之间循环，即使产线很多也不会报错
            custom_class = f'bar-line-{idx % 6}'

        # -----------------------

        name_label = f"[{row['resource_id']}] {row['task_id']}"
        if row['is_locked']: name_label = "🔒 " + name_label
        if row['plan_type'] == 'SIMULATION': name_label = "[模拟] " + name_label

        data.append({
            "id": row['task_id'],
            "name": name_label,
            "resource": row['res_name'],
            "resource_id": row['resource_id'],
            "start": row['planned_start'],
            "end": row['planned_end'],
            "custom_class": custom_class,
            "is_locked": row['is_locked'],
            "status": row['status']
        })
    return jsonify(data)

# 2. 修改 get_gantt_data：增加 ORDER BY 确保同产线任务聚在一起
@app.route('/api/schedule_data')
def get_gantt_data():
    conn = get_db_connection()
    
    # --- 修复核心：增加了 ORDER BY w.resource_id ASC ---
    # 这样所有属于 Line-01 的会在最上面，Line-04 的会聚在一起
    orders = conn.execute("""
        SELECT w.*, r.name as res_name 
        FROM work_orders w
        JOIN resources r ON w.resource_id = r.id
        WHERE w.status IN ('Scheduled', 'Delayed') 
           OR w.status LIKE 'Scheduled%' 
           OR w.status LIKE 'Delayed%'
        ORDER BY w.resource_id ASC, w.planned_start ASC
    """).fetchall()
    conn.close()
    
    data = []
    for row in orders:
        custom_class = 'bar-blue'
        if row['plan_type'] == 'SIMULATION':
            custom_class = 'bar-striped'
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']:
            custom_class = 'bar-red'
        elif row['is_locked']:
            custom_class = 'bar-dark'

        name_label = f"[{row['resource_id']}] {row['task_id']}"
        if row['is_locked']: name_label = "🔒 " + name_label
        if row['plan_type'] == 'SIMULATION': name_label = "[模拟] " + name_label

        data.append({
            "id": row['task_id'],
            "name": name_label,
            "resource": row['res_name'],
            "resource_id": row['resource_id'],
            "start": row['planned_start'],
            "end": row['planned_end'],
            "custom_class": custom_class,
            "is_locked": row['is_locked'],
            "status": row['status']
        })
    return jsonify(data)

@app.route('/api/schedule_data')
def get_gantt_data():
    conn = get_db_connection()
    # 获取所有已排产或已延期的任务
    orders = conn.execute("""
        SELECT w.*, r.name as res_name 
        FROM work_orders w
        JOIN resources r ON w.resource_id = r.id
        WHERE w.status IN ('Scheduled', 'Delayed') OR w.status LIKE 'Scheduled%' OR w.status LIKE 'Delayed%'
    """).fetchall()
    conn.close()
    
    data = []
    for row in orders:
        # 样式处理
        custom_class = 'bar-blue'
        if row['plan_type'] == 'SIMULATION':
            custom_class = 'bar-striped' # 模拟单用条纹
        elif row['status'].startswith('Delayed') or '⚠️' in row['status']:
            custom_class = 'bar-red' # 延期或警告用红色
        elif row['is_locked']:
            custom_class = 'bar-dark' # 锁定用深色

        name_label = f"[{row['resource_id']}] {row['task_id']}"
        if row['is_locked']: name_label = "🔒 " + name_label
        if row['plan_type'] == 'SIMULATION': name_label = "[模拟] " + name_label

        data.append({
            "id": row['task_id'],
            "name": name_label,
            "resource": row['res_name'],
            "start": row['planned_start'],
            "end": row['planned_end'],
            "custom_class": custom_class,
            # 将一些元数据传给前端，方便点击锁定
            "is_locked": row['is_locked'],
            "status": row['status']
        })
    return jsonify(data)
'''
# 核心：排产接口（新增算法选择参数）
# app.py

@app.route('/api/run', methods=['POST'])
def run_schedule():
    data = request.json
    mode = data.get('mode', 'SIMULATION')
    algo = data.get('algorithm', 'greedy')
    
    conn = get_db_connection()
    try:
        # === 核心修复 1：查询逻辑优化 ===
        # 1. 移除 JOIN，避免 'AUTO' 订单因为匹配不到资源而被过滤掉
        # 2. 增加 is_locked IS NULL 的判断，防止旧数据因为字段为空被漏掉
        orders_db = conn.execute("""
            SELECT * FROM work_orders 
            WHERE status IN ('Pending', 'Scheduled') 
            AND (is_locked = 0 OR is_locked IS NULL)
        """).fetchall()
        
        resources_db = conn.execute("SELECT * FROM resources").fetchall()
        
        orders_list = [dict(row) for row in orders_db]
        resources_list = [dict(row) for row in resources_db]

        if not orders_list:
             return jsonify({'success': True, 'message': '没有可排产的任务'})

        print(f"[Schedule] 启动排产... 模式:{mode}, 算法:{algo}, 任务数:{len(orders_list)}")
        
        # 启动调度器
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

        # === 核心修复 2：保存计算结果 ===
        # 确保将算法计算出的 resource_id (可能是自动分配后的 Line-XX) 写回数据库
        for item in best_schedule:
            s_str = item['planned_start'].strftime('%Y-%m-%d %H:%M')
            e_str = item['planned_end'].strftime('%Y-%m-%d %H:%M')
            
            # 只有正式排产才修改状态，模拟排产只修改 plan_type
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

"""
# 核心：排产接口
@app.route('/api/run', methods=['POST'])
def run_schedule():
    mode = request.json.get('mode', 'OFFICIAL') # 获取前端传来的模式
    msg = run_advanced_scheduling(mode)
    return jsonify({"message": msg})
"""
# 核心：锁定/解锁接口
@app.route('/api/toggle_lock', methods=['POST'])
def toggle_lock():
    task_id = request.json.get('id')
    conn = get_db_connection()
    # 查当前状态并取反
    curr = conn.execute("SELECT is_locked FROM work_orders WHERE task_id=?", (task_id,)).fetchone()
    if curr:
        new_val = 0 if curr['is_locked'] else 1
        conn.execute("UPDATE work_orders SET is_locked=? WHERE task_id=?", (new_val, task_id))
        conn.commit()
    conn.close()
    return jsonify({"success": True})

# app.py 中的 add_order 函数

@app.route('/manage/add', methods=['POST'])
def add_order():
    conn = get_db_connection()
    try:
        # 1. 获取表单数据
        task_id = request.form['task_id'].strip()
        
        # 2. 【关键修复】检查 ID 是否已存在
        exist = conn.execute("SELECT 1 FROM work_orders WHERE task_id = ?", (task_id,)).fetchone()
        if exist:
            # 如果存在，返回一段 JS 脚本弹窗提示，并返回上一页
            return f"""
            <script>
                alert('添加失败：任务ID [{task_id}] 已存在！\\n请使用唯一的ID。');
                history.back();
            </script>
            """

        # 3. 处理数据
        plan_type = 'SIMULATION' if 'is_sim' in request.form else 'OFFICIAL'
        
        # 处理时间输入：HTML5 datetime-local 传过来是 "2023-10-01T10:00"，需要替换T
        mat_time = request.form.get('material_time', '').replace('T', ' ')
        soft_time = request.form.get('software_time', '').replace('T', ' ')
        deadline = request.form.get('deadline', '').replace('T', ' ')

        # 4. 执行插入
        conn.execute('''
            INSERT INTO work_orders (
                task_id, job_id, product_code, resource_id, qty, std_time, priority, 
                material_time, software_time, deadline, plan_type, 
                smt_side, process_req
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            task_id, 
            request.form['job_id'], 
            request.form['product_code'],
            request.form['resource_id'], 
            request.form['qty'], 
            request.form['std_time'],
            request.form['priority'], 
            mat_time, 
            soft_time, 
            deadline, 
            plan_type,
            request.form.get('smt_side', ''), 
            request.form.get('process_req', 'NORMAL')
        ))
        
        conn.commit()
        return redirect(url_for('manage'))

    except Exception as e:
        # 捕获其他未知错误，防止网页崩溃
        import traceback
        traceback.print_exc()
        return f"""
        <script>
            alert('系统错误：{str(e)}');
            history.back();
        </script>
        """
    finally:
        conn.close()

"""
@app.route('/manage/add', methods=['POST'])
def add_order():
    conn = get_db_connection()
    # 处理模拟单标记
    plan_type = 'OFFICIAL'
    if 'is_sim' in request.form:
        plan_type = 'SIMULATION'

    conn.execute('''
        INSERT INTO work_orders (
            task_id, job_id, product_code, resource_id, qty, std_time, priority, 
            material_status, software_status, deadline, plan_type
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        request.form['task_id'], request.form['job_id'], request.form['product_code'],
        request.form['resource_id'], request.form['qty'], request.form['std_time'],
        request.form['priority'], request.form['material_status'], 
        request.form['software_status'], request.form['deadline'], plan_type
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('manage'))
"""

@app.route('/manage/reset', methods=['POST'])
def reset_data():
    reset_db()
    return redirect(url_for('manage'))

@app.route('/api/update_order_manual', methods=['POST'])
def update_order_manual():
    data = request.json
    task_id = data.get('task_id')
    start_str = data.get('planned_start')
    end_str = data.get('planned_end')
    is_locked = data.get('is_locked')
    resource_id = data.get('resource_id') # 前端可能不传这个字段

    if start_str: start_str = start_str.replace('T', ' ')
    if end_str: end_str = end_str.replace('T', ' ')

    conn = get_db_connection()
    new_status = 'Scheduled' if (start_str and end_str) else 'Pending'
    
    # === 优化逻辑：如果前端没传 resource_id，就不更新这个字段 ===
    if resource_id:
        # 前端传了产线，全量更新
        conn.execute('''
            UPDATE work_orders 
            SET planned_start = ?, planned_end = ?, is_locked = ?, status = ?, resource_id = ?
            WHERE task_id = ?
        ''', (start_str, end_str, is_locked, new_status, resource_id, task_id))
    else:
        # 前端没传产线（比如从甘特图弹窗保存），只更新时间和锁，保留原产线
        conn.execute('''
            UPDATE work_orders 
            SET planned_start = ?, planned_end = ?, is_locked = ?, status = ?
            WHERE task_id = ?
        ''', (start_str, end_str, is_locked, new_status, task_id))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"任务 {task_id} 已更新"})

"""
# --- app.py 新增部分 ---
@app.route('/api/update_order_manual', methods=['POST'])
def update_order_manual():
    data = request.json
    task_id = data.get('task_id')
    start_str = data.get('planned_start') # 格式: 2023-10-27T10:00 (HTML5格式)
    end_str = data.get('planned_end')
    is_locked = data.get('is_locked')     # 1 或 0
    
    # --- 新增：接收 resource_id ---
    resource_id = data.get('resource_id')

    # 格式转换: HTML5 input 传过来的是 'T' 分隔，数据库我们要存空格分隔
    if start_str: start_str = start_str.replace('T', ' ')
    if end_str: end_str = end_str.replace('T', ' ')

    conn = get_db_connection()
    
    # 如果用户手动填了时间，状态自动变为 Scheduled，否则保持原样或 Pending
    new_status = 'Scheduled' if (start_str and end_str) else 'Pending'
    
    # --- 修改 SQL：增加 resource_id 字段更新 ---
    conn.execute('''
        UPDATE work_orders 
        SET planned_start = ?, planned_end = ?, is_locked = ?, status = ?, resource_id = ?
        WHERE task_id = ?
    ''', (start_str, end_str, is_locked, new_status, resource_id, task_id))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"任务 {task_id} 已更新"})
"""

# ==========================================
# 新增功能：产线资源管理
# ==========================================

# 1. 页面路由
@app.route('/resources')
def resources_page():
    return render_template('resources.html')

@app.route('/config')
def config_page():
    """配置管理中心"""
    return render_template('config.html')

# 2. 数据管理 API
@app.route('/api/resource_manage', methods=['GET', 'POST', 'DELETE'])
def resource_manage():
    conn = get_db_connection()
    
    # [查询] 获取产线列表
    if request.method == 'GET':
        rows = conn.execute("SELECT * FROM resources ORDER BY id").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    
    # [保存] 新增或更新产线
    if request.method == 'POST':
        data = request.json
        try:
            # 检查 ID 是否存在
            exist = conn.execute("SELECT 1 FROM resources WHERE id = ?", (data['id'],)).fetchone()
            
            if exist:
                # 更新：只更新界面上有的字段，保留 type/capability_config 不变
                conn.execute("""
                    UPDATE resources 
                    SET name=?, work_hours=?, capacity_ratio=?, description=?
                    WHERE id=?
                """, (data['name'], data['work_hours'], data['capacity_ratio'], data.get('desc',''), data['id']))
                msg = "更新成功"
            else:
                # 新增：给 type 和 capability_config 赋默认值
                conn.execute("""
                    INSERT INTO resources (id, name, work_hours, capacity_ratio, description, type, capability_config)
                    VALUES (?, ?, ?, ?, ?, 'Production', '')
                """, (data['id'], data['name'], data['work_hours'], data['capacity_ratio'], data.get('desc','')))
                msg = "添加成功"
                
            conn.commit()
            return jsonify({'success': True, 'message': msg})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
        finally:
            conn.close()

    # [删除] 删除产线
    if request.method == 'DELETE':
        res_id = request.args.get('id')
        try:
            # 完整性检查：如果产线还有订单，禁止删除
            count = conn.execute("SELECT count(*) FROM work_orders WHERE resource_id = ?", (res_id,)).fetchone()[0]
            if count > 0:
                return jsonify({'success': False, 'message': f'无法删除：该产线下仍有 {count} 个关联订单，请先在订单管理中处理。'})
            
            conn.execute("DELETE FROM resources WHERE id = ?", (res_id,))
            conn.commit()
            return jsonify({'success': True, 'message': '产线已删除'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
        finally:
            conn.close()

# app.py

# ... (其他的路由代码) ...

# === 🛠️ 临时修复工具：强制修正产线类型 ===
@app.route('/fix_db_types')
def fix_db_types():
    conn = get_db_connection()
    try:
        # 1. 把所有带 SMT 名字的线，类型强制改为 SMT
        conn.execute("UPDATE resources SET type='SMT' WHERE id LIKE '%SMT%' OR name LIKE '%SMT%'")
        # 2. 把其他的线，类型强制改为 Production
        conn.execute("UPDATE resources SET type='Production' WHERE (id NOT LIKE '%SMT%' AND name NOT LIKE '%SMT%')")
        conn.commit()
        return "<h3>✅ 修复成功！SMT产线类型已修正。请返回订单中心重新排产。</h3><a href='/manage'>返回订单管理</a>"
    except Exception as e:
        return f"修复失败: {str(e)}"
    finally:
        conn.close()

if __name__ == '__main__':
    # 远程连接 + 自动重载
    app.run(debug=True, port=5000, host='0.0.0.0', threaded=True)