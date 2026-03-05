# -*- coding: utf-8 -*-
"""
订单拆分工具
支持父工单/子工单拆分和A/B面拆分
"""
import sys
sys.path.insert(0, 'C:/Users/mtc/Desktop/MyAPS')
from database import get_db_connection
from database_extend import get_db_connection as get_extend_db
import random


def split_order_by_workshop(order_data, workshop_lines):
    """
    按车间拆分订单
    
    Args:
        order_data: 原始订单数据
        workshop_lines: 各车间可用产线
    
    Returns:
        list of work orders
    """
    work_orders = []
    
    # 确定需要拆分的车间
    workshops = []
    for ws, lines in workshop_lines.items():
        if lines:
            workshops.append(ws)
    
    if not workshops:
        return [create_work_order(order_data, None, None, None)]
    
    # 按车间数量拆分数量
    total_qty = order_data.get('qty', 100)
    qty_per_workshop = total_qty // len(workshops)
    remainder = total_qty % len(workshops)
    
    for i, ws in enumerate(workshops):
        qty = qty_per_workshop + (1 if i < remainder else 0)
        if qty > 0:
            wo = create_work_order(
                order_data, 
                f"{order_data['task_id']}_{ws}",
                ws,
                workshop_lines.get(ws, []),
                qty
            )
            work_orders.append(wo)
    
    return work_orders


def split_order_by_ab_side(order_data, gap_minutes=180):
    """
    按A/B面拆分订单
    
    Args:
        order_data: 原始订单数据
        gap_minutes: A面与B面之间的时间间隔（默认3小时）
    
    Returns:
        list of work orders (B first, then A)
    """
    product_code = str(order_data.get('product_code', ''))
    qty = order_data.get('qty', 100)
    
    # 判断是否需要A/B面拆分
    # 规则1: 电视产品需要A/B面
    # 规则2: 指定了smt_side为AB
    needs_ab = False
    if 'TV' in product_code:
        needs_ab = True
    if order_data.get('smt_side') in ['AB', 'A,B', 'A+B']:
        needs_ab = True
    
    if not needs_ab:
        return [create_work_order(order_data, None, None, None, side='single')]
    
    # A/B面拆分
    # B面先做，A面后做，间隔3小时
    b_qty = qty // 2
    a_qty = qty - b_qty
    
    base_id = order_data.get('task_id', 'WO')
    
    # 创建B面工单
    b_order = create_work_order(
        order_data,
        f"{base_id}_B",
        None, None,
        b_qty,
        side='B',
        side_sequence=1  # 先做B面
    )
    
    # 创建A面工单
    a_order = create_work_order(
        order_data,
        f"{base_id}_A",
        None, None,
        a_qty,
        side='A',
        side_sequence=2,  # 后做A面
        depends_on=f"{base_id}_B",  # 依赖B面
        side_gap_minutes=gap_minutes
    )
    
    return [b_order, a_order]


def create_work_order(base_data, wo_id, workshop, lines, qty=None, side=None, 
                      side_sequence=0, depends_on=None, side_gap_minutes=180):
    """创建工单"""
    return {
        'task_id': wo_id or base_data.get('task_id', 'WO'),
        'job_id': base_data.get('job_id', ''),
        'product_code': base_data.get('product_code', ''),
        'resource_id': 'AUTO',
        'qty': qty or base_data.get('qty', 100),
        'std_time': base_data.get('std_time', 120),
        'priority': base_data.get('priority', 5),
        'material_time': base_data.get('material_time'),
        'software_time': base_data.get('software_time'),
        'deadline': base_data.get('deadline'),
        'smt_side': base_data.get('smt_side', ''),
        'process_req': base_data.get('process_req', ''),
        'status': 'Pending',
        'plan_type': base_data.get('plan_type', 'OFFICIAL'),
        
        # 新增字段
        'workshop': workshop,
        'assigned_lines': ','.join(lines) if lines else '',
        'side': side or 'single',
        'side_sequence': side_sequence,
        'depends_on': depends_on,
        'side_gap_minutes': side_gap_minutes,
        'is_parent': 0,
        'parent_order_id': None,
    }


def import_and_split_orders(orders_data, split_mode='workshop'):
    """
    导入并拆分订单
    
    Args:
        orders_data: 原始订单列表
        split_mode: 拆分模式
            - 'workshop': 按车间拆分
            - 'ab_side': 按A/B面拆分
            - 'both': 既按车间又按A/B面拆分
    """
    import sys
    sys.path.insert(0, 'C:/Users/mtc/Desktop/MyAPS')
    from database import get_db_connection
    
    # 获取各车间的产线配置
    workshop_lines = get_workshop_lines()
    
    results = []
    
    for order in orders_data:
        if split_mode == 'workshop':
            # 按车间拆分
            wos = split_order_by_workshop(order, workshop_lines)
        elif split_mode == 'ab_side':
            # 按A/B面拆分
            wos = split_order_by_ab_side(order)
        elif split_mode == 'both':
            # 先按车间拆分，再按A/B面拆分
            wos = []
            workshop_wos = split_order_by_workshop(order, workshop_lines)
            for wwo in workshop_wos:
                # 进一步按A/B面拆分
                ab_wos = split_order_by_ab_side(wwo)
                wos.extend(ab_wos)
        else:
            wos = [create_work_order(order, None, None, None)]
        
        results.extend(wos)
    
    # 保存到数据库
    saved_count = 0
    with get_db_connection() as conn:
        for wo in results:
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO work_orders (
                        task_id, job_id, product_code, resource_id, qty, std_time,
                        priority, material_time, software_time, deadline, smt_side,
                        process_req, status, plan_type,
                        workshop, side, side_sequence, depends_on, side_gap_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    wo['task_id'], wo['job_id'], wo['product_code'], wo['resource_id'],
                    wo['qty'], wo['std_time'], wo['priority'], wo['material_time'],
                    wo['software_time'], wo['deadline'], wo['smt_side'], wo['process_req'],
                    wo['status'], wo['plan_type'],
                    wo.get('workshop'), wo.get('side'), wo.get('side_sequence'),
                    wo.get('depends_on'), wo.get('side_gap_minutes', 180)
                ))
                saved_count += 1
            except Exception as e:
                print(f"保存工单失败: {wo['task_id']}, {e}")
    
    return saved_count


def get_workshop_lines():
    """获取各车间的产线配置"""
    import sys
    sys.path.insert(0, 'C:/Users/mtc/Desktop/MyAPS')
    from database_extend import get_db_connection
    
    workshop_lines = {
        'SMT': [],
        'DIP': [],
        'ASSEMBLY': []
    }
    
    with get_db_connection() as conn:
        # 获取SMT产线
        rows = conn.execute("SELECT line_id FROM line_config WHERE line_type='SMT'").fetchall()
        workshop_lines['SMT'] = [r[0] for r in rows]
        
        # 获取DIP产线
        rows = conn.execute("SELECT line_id FROM line_config WHERE line_type='DIP'").fetchall()
        workshop_lines['DIP'] = [r[0] for r in rows]
        
        # 总装使用所有产线
        rows = conn.execute("SELECT line_id FROM line_config").fetchall()
        workshop_lines['ASSEMBLY'] = [r[0] for r in rows]
    
    return workshop_lines


if __name__ == '__main__':
    # 测试
    test_order = {
        'task_id': 'WO-TEST-001',
        'product_code': 'TV-55',
        'qty': 500,
        'std_time': 120,
        'priority': 5
    }
    
    print("按A/B面拆分测试:")
    wos = split_order_by_ab_side(test_order)
    for wo in wos:
        print(f"  {wo['task_id']}: side={wo['side']}, sequence={wo['side_sequence']}, gap={wo.get('side_gap_minutes')}")
