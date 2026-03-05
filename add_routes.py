import os

# Read the current routes.py
with open('C:/Users/mtc/Desktop/MyAPS/api/routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# New routes to add
new_routes = '''

# 订单拆分 API
@api_bp.route('/orders/split', methods=['POST'])
def split_orders():
    data = request.json
    split_mode = data.get('mode', 'workshop')
    try:
        from order_split import import_and_split_orders
        from database import get_db_connection
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM work_orders WHERE plan_type='OFFICIAL'").fetchall()
            orders = [dict(r) for r in rows]
        if orders:
            count = import_and_split_orders(orders, split_mode)
            return jsonify({'success': True, 'message': f'拆分完成 {count} 个工单', 'count': count})
        return jsonify({'success': False, 'message': '无订单'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/orders/by_workshop/<workshop>', methods=['GET'])
def get_orders_by_workshop(workshop):
    from database import get_db_connection
    with get_db_connection() as conn:
        if workshop == 'ALL':
            rows = conn.execute('SELECT * FROM work_orders').fetchall()
        else:
            rows = conn.execute('SELECT * FROM work_orders WHERE workshop = ?', (workshop,)).fetchall()
    return jsonify([dict(r) for r in rows])

@api_bp.route('/orders/dependencies', methods=['GET'])
def get_order_dependencies():
    from database import get_db_connection
    with get_db_connection() as conn:
        rows = conn.execute('SELECT task_id, side, side_sequence, depends_on FROM work_orders WHERE side IN ("A","B") OR depends_on IS NOT NULL').fetchall()
    return jsonify([dict(r) for r in rows])
'''

# Append to the file
with open('C:/Users/mtc/Desktop/MyAPS/api/routes.py', 'a', encoding='utf-8') as f:
    f.write(new_routes)

print('Routes added successfully!')
