# -*- coding: utf-8 -*-
"""
模拟 MES/SAP 服务器
生成随机测试数据
"""
from flask import Flask, jsonify, request
import random
from datetime import datetime, timedelta
import uuid

app = Flask(__name__)

# ==========================================
# 模拟数据生成器
# ==========================================

def random_time():
    """随机时间"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def random_date():
    """随机日期"""
    days = random.randint(0, 30)
    return (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

# 产线列表
SMT_LINES = [f'S{i:02d}' for i in range(1, 50)]
DIP_LINES = [f'D{i:02d}' for i in range(1, 23)]
ALL_LINES = SMT_LINES + DIP_LINES

# 产品列表
PRODUCTS = [
    'TV-32', 'TV-40', 'TV-42', 'TV-50', 'TV-55', 'TV-65', 'TV-75', 'TV-85',
    'PCBA-Advanced', 'PCBA-Simple', 'PCBA-Complex'
]

# 物料组
MATERIAL_GROUPS = ['511', '513', '514', '515', '534', '535', '523', '555']

# 客户列表
CUSTOMERS = ['客户A', '客户B', '客户C', '中兴', '烽火', '华为', '海信', 'TCL']


# ==========================================
# MES 接口模拟
# ==========================================

@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'service': 'MES Simulator'})


@app.route('/api/capacity', methods=['GET'])
def get_capacity():
    """
    获取标产数据
    参数: line_id, product_code(可选)
    """
    line_id = request.args.get('line_id', 'S01')
    product_code = request.args.get('product_code', 'TV-55')
    
    # 随机生成标产数据
    std_capacity = random.randint(300, 1000)
    std_time = random.randint(60, 240)  # 分钟
    
    return jsonify({
        'line_id': line_id,
        'product_code': product_code,
        'std_capacity': std_capacity,
        'std_time': std_time,
        'unit': 'PCS',
        'update_time': random_time(),
        'source': 'MES',
        'status': 'success'
    })


@app.route('/api/all_capacity', methods=['GET'])
def get_all_capacity():
    """获取所有产线的标产数据"""
    data = []
    for line in ALL_LINES[:20]:  # 只返回前20条
        data.append({
            'line_id': line,
            'line_type': 'SMT' if line.startswith('S') else 'DIP',
            'std_capacity': random.randint(300, 1000),
            'std_time': random.randint(60, 240),
            'unit': 'PCS',
            'update_time': random_time()
        })
    return jsonify(data)


@app.route('/api/progress/<order_id>', methods=['GET'])
def get_production_progress(order_id):
    """获取生产进度"""
    progress = random.randint(0, 100)
    output_qty = random.randint(0, 1000)
    target_qty = 1000
    
    stations = ['A面', 'B面', '组装', '测试', '包装', '入库']
    
    return jsonify({
        'order_id': order_id,
        'progress': progress,
        'status': '生产中' if progress < 100 else '已完成',
        'current_station': random.choice(stations),
        'output_qty': output_qty,
        'target_qty': target_qty,
        'start_time': (datetime.now() - timedelta(hours=random.randint(1, 24))).strftime('%Y-%m-%d %H:%M:%S'),
        'update_time': random_time(),
        'source': 'MES'
    })


@app.route('/api/realtime_output', methods=['GET'])
def get_realtime_output():
    """获取实时产出"""
    line_id = request.args.get('line_id', 'S01')
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    return jsonify({
        'line_id': line_id,
        'date': date,
        'output_qty': random.randint(100, 800),
        'qualified_qty': random.randint(90, 150),
        'defect_qty': random.randint(0, 10),
        'update_time': random_time()
    })


# ==========================================
# SAP 接口模拟
# ==========================================

@app.route('/sap/health', methods=['GET'])
def sap_health():
    """SAP 健康检查"""
    return jsonify({'status': 'ok', 'service': 'SAP Simulator'})


@app.route('/sap/api/orders', methods=['GET'])
def get_sap_orders():
    """获取 ZPP008 订单数据"""
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'))
    
    orders = []
    for i in range(20):  # 生成20个订单
        orders.append({
            'sales_order': f'SO-{random.randint(10000, 99999)}',
            'item': f'{random.randint(10, 90)}',
            'product_code': random.choice(PRODUCTS),
            'material_group': random.choice(MATERIAL_GROUPS),
            'qty': random.randint(50, 500),
            'demand_date': random_date(),
            'priority': random.randint(1, 10),
            'customer': random.choice(CUSTOMERS),
            'company_code': random.choice(['1010', '1000', '1050']),
            'created_at': random_time()
        })
    
    return jsonify({
        'success': True,
        'count': len(orders),
        'data': orders
    })


@app.route('/sap/api/material_delivery', methods=['GET'])
def get_material_delivery():
    """获取物料交期"""
    material_code = request.args.get('material_code', 'MAT-001')
    
    return jsonify({
        'material_code': material_code,
        'delivery_date': random_date(),
        'supplier': random.choice(['供应商A', '供应商B', '供应商C']),
        'qty': random.randint(100, 1000),
        'status': '已确认',
        'update_time': random_time()
    })


@app.route('/sap/api/demand_time', methods=['GET'])
def get_demand_time():
    """获取客户需求时间"""
    sales_order = request.args.get('sales_order', 'SO-12345')
    item = request.args.get('item', '10')
    
    return jsonify({
        'sales_order': sales_order,
        'item': item,
        'demand_date': random_date(),
        'priority': random.randint(1, 10),
        'customer': random.choice(CUSTOMERS),
        'update_time': random_time()
    })


@app.route('/sap/api/product_info/<product_code>', methods=['GET'])
def get_product_info(product_code):
    """获取产品主数据"""
    return jsonify({
        'product_code': product_code,
        'material_group': random.choice(MATERIAL_GROUPS),
        'description': f'产品 {product_code}',
        'unit': 'PCS',
        'weight': random.randint(5, 50),
        'product_type': random.choice(['TV', 'PCBA', 'Monitor']),
        'std_time': random.randint(60, 180),
        'source': 'SAP'
    })


# ==========================================
# 批量数据接口
# ==========================================

@app.route('/api/batch_orders', methods=['GET'])
def get_batch_orders():
    """批量生成工单数据（用于测试排产）"""
    orders = []
    for i in range(50):
        product = random.choice(PRODUCTS)
        orders.append({
            'task_id': f'WO-MES-{i+1:03d}',
            'job_id': f'JOB-{random.randint(1000, 9999)}',
            'product_code': product,
            'resource_id': 'AUTO',
            'qty': random.randint(50, 500),
            'std_time': random.randint(60, 240),
            'priority': random.randint(1, 10),
            'material_time': (datetime.now() + timedelta(days=random.randint(-1, 3))).strftime('%Y-%m-%d %H:%M'),
            'software_time': (datetime.now() + timedelta(days=random.randint(0, 5))).strftime('%Y-%m-%d %H:%M'),
            'deadline': random_date(),
            'smt_side': random.choice(['A', 'B', 'AB']),
            'process_req': 'NORMAL',
            'status': 'Pending'
        })
    
    return jsonify({
        'success': True,
        'count': len(orders),
        'data': orders
    })



# Component info mapping
COMPONENT_INFO = {
    "TV-32": {"code": "C32-001", "desc": "32寸LED液晶面板"},
    "TV-40": {"code": "C40-001", "desc": "40寸LED液晶面板"},
    "TV-55": {"code": "C55-001", "desc": "55寸LED液晶面板"},
    "TV-65": {"code": "C65-001", "desc": "65寸LED液晶面板"},
    "PCBA-Simple": {"code": "PCBA-SIM", "desc": "简易PCBA主板"},
}

@app.route("/api/mes/orders", methods=["GET"])
def get_mes_orders_api():
    workshop = request.args.get("workshop", "ALL")
    orders = []
    parent_orders = [f"PO-SMT-{i:03d}" for i in range(1, 21)]
    parent_orders += [f"PO-DIP-{i:03d}" for i in range(1, 11)]
    parent_orders += [f"PO-ASM-{i:03d}" for i in range(1, 11)]
    
    for parent_order in parent_orders:
        if "SMT" in parent_order:
            ws, products = "SMT", ["TV-32", "TV-40", "TV-55", "TV-65"]
        elif "DIP" in parent_order:
            ws, products = "DIP", ["TV-42", "TV-50", "PCBA-Simple"]
        else:
            ws, products = "ASSEMBLY", ["TV-55", "TV-65", "TV-75"]
        
        if workshop != "ALL" and ws != workshop:
            continue
        
        product = random.choice(products)
        total_qty = random.randint(100, 500)
        completed_qty = random.randint(0, total_qty)
        comp = COMPONENT_INFO.get(product, {"code": "C-UNK", "desc": "未知组件"})
        
        orders.append({
            "task_id": f"WO-{ws[:3]}-{parent_order.split('-')[1]}-{int(parent_order.split('-')[2]):03d}",
            "parent_order": parent_order, "workshop": ws,
            "job_id": f"JOB-{parent_order.split('-')[1]}{parent_order.split('-')[2]}",
            "component_code": comp["code"], "component_desc": comp["desc"],
            "product_code": product, "total_qty": total_qty,
            "completed_qty": completed_qty, "remaining_qty": total_qty - completed_qty,
            "status": "Completed" if completed_qty >= total_qty else "In Progress" if completed_qty > 0 else "Pending",
            "progress": int(completed_qty / total_qty * 100),
        })
    
    return jsonify({"success": True, "count": len(orders), "data": orders})


@app.route("/api/mes/orders/<parent_order>", methods=["GET"])
def get_mes_order_detail_api(parent_order):
    orders = []
    for i in range(random.randint(2, 5)):
        product = random.choice(["TV-32", "TV-40", "TV-55", "TV-65"])
        total_qty = random.randint(50, 200)
        completed_qty = random.randint(0, total_qty)
        comp = COMPONENT_INFO.get(product, {"code": "C-UNK", "desc": "未知组件"})
        
        orders.append({
            "parent_order": parent_order, "work_order": f"WO-{parent_order}-{i+1:02d}",
            "component_code": comp["code"], "component_desc": comp["desc"],
            "total_qty": total_qty, "completed_qty": completed_qty,
            "remaining_qty": total_qty - completed_qty,
            "status": "Completed" if completed_qty >= total_qty else "In Progress" if completed_qty > 0 else "Pending",
        })
    
    return jsonify({"success": True, "parent_order": parent_order, "data": orders})


if __name__ == '__main__':
    print("=" * 50)
    print("  模拟 MES/SAP 服务器")
    print("  端口: 8080")
    print("  健康检查: http://localhost:8080/health")
    print("=" * 50)
    app.run(debug=False, port=8080, host='0.0.0.0')
