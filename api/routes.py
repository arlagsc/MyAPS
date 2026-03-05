# -*- coding: utf-8 -*-
"""
API 路由 - 产线配置、标产数据、接口管理
"""
from flask import Blueprint, jsonify, request
from database_extend import (
    ProductLineMappingDAO, CapacityStandardsDAO, LineConfigDAO,
    APILogDAO, get_db_connection
)
from adapters.base import AdapterFactory
from datetime import datetime
import logging
import json
import time
import sys

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ==========================================
# 产线配置管理
# ==========================================

@api_bp.route('/line_config', methods=['GET'])
def get_line_config():
    """获取所有产线配置"""
    line_type = request.args.get('type')
    if line_type:
        lines = LineConfigDAO.get_by_type(line_type)
    else:
        lines = LineConfigDAO.get_all()
    return jsonify(lines)


@api_bp.route('/line_config', methods=['POST'])
def add_line_config():
    """添加产线配置"""
    data = request.json
    try:
        line_id = LineConfigDAO.insert(data)
        return jsonify({'success': True, 'id': line_id})
    except Exception as e:
        logger.error(f"添加产线配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400


# ==========================================
# 产品-产线映射管理
# ==========================================

@api_bp.route('/product_line_mapping', methods=['GET'])
def get_product_line_mapping():
    """获取产品-产线映射"""
    company = request.args.get('company')
    material_group = request.args.get('material_group')
    
    if company:
        mappings = ProductLineMappingDAO.get_by_company(company)
    elif material_group:
        mappings = ProductLineMappingDAO.get_by_material_group(material_group, company)
    else:
        mappings = ProductLineMappingDAO.get_all()
    
    return jsonify(mappings)


@api_bp.route('/product_line_mapping/query_lines', methods=['GET'])
def query_available_lines():
    """查询可用的产线 - 根据公司和物料组"""
    company = request.args.get('company')
    material_group = request.args.get('material_group')
    
    if not material_group:
        return jsonify({'error': '需要提供 material_group 参数'}), 400
    
    # 查询匹配的映射
    if company:
        mappings = ProductLineMappingDAO.get_by_material_group(material_group, company)
    else:
        mappings = ProductLineMappingDAO.get_by_material_group(material_group)
    
    # 提取所有可用产线
    available_lines = []
    for m in mappings:
        for i in range(1, 11):
            line_id = m.get(f'line_id_{i}')
            if line_id and line_id not in available_lines:
                available_lines.append(line_id)
    
    return jsonify({
        'company': company,
        'material_group': material_group,
        'available_lines': available_lines,
        'count': len(available_lines)
    })


@api_bp.route('/product_line_mapping', methods=['POST'])
def add_product_line_mapping():
    """添加产品-产线映射"""
    data = request.json
    try:
        mapping_id = ProductLineMappingDAO.insert(data)
        return jsonify({'success': True, 'id': mapping_id})
    except Exception as e:
        logger.error(f"添加映射失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400


@api_bp.route('/product_line_mapping/<int:id>', methods=['PUT'])
def update_product_line_mapping(id):
    """更新产品-产线映射"""
    data = request.json
    try:
        ProductLineMappingDAO.update(id, data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@api_bp.route('/product_line_mapping/<int:id>', methods=['DELETE'])
def delete_product_line_mapping(id):
    """删除产品-产线映射"""
    try:
        ProductLineMappingDAO.delete(id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@api_bp.route('/product_line_mapping/import_excel', methods=['POST'])
def import_product_line_mapping():
    """从 Excel 导入产品-产线映射"""
    # TODO: 实现 Excel 导入
    return jsonify({'success': False, 'message': '待实现'})


# ==========================================
# 标产数据管理
# ==========================================

@api_bp.route('/capacity_standards', methods=['GET'])
def get_capacity_standards():
    """获取标产数据"""
    line_id = request.args.get('line_id')
    product_code = request.args.get('product_code')
    
    if line_id and product_code:
        data = CapacityStandardsDAO.get_by_product(line_id, product_code)
        return jsonify(data if data else {})
    elif line_id:
        data = CapacityStandardsDAO.get_by_line(line_id)
    else:
        data = CapacityStandardsDAO.get_all()
    
    return jsonify(data)


@api_bp.route('/capacity_standards', methods=['POST'])
def add_capacity_standard():
    """添加标产数据"""
    data = request.json
    try:
        capacity_id = CapacityStandardsDAO.insert(data)
        return jsonify({'success': True, 'id': capacity_id})
    except Exception as e:
        logger.error(f"添加标产数据失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400


@api_bp.route('/capacity_standards/batch', methods=['POST'])
def batch_add_capacity_standards():
    """批量添加标产数据"""
    data_list = request.json
    if not isinstance(data_list, list):
        return jsonify({'success': False, 'message': '数据必须是数组'}), 400
    
    try:
        count = CapacityStandardsDAO.batch_insert(data_list)
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        logger.error(f"批量添加标产数据失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400


# ==========================================
# MES/SAP 接口
# ==========================================

@api_bp.route('/mes/test', methods=['GET'])
def test_mes_connection():
    """测试 MES 连接"""
    start_time = time.time()
    
    # 每次都重新加载配置
    AdapterFactory.reload_config()
    mes = AdapterFactory.get_mes_adapter()
    
    try:
        result = mes.test_connection()
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('MES', 'test_connection', '', json.dumps({'result': result}),
                     200 if result else 500, '', elapsed)
        
        return jsonify({
            'success': result,
            'message': 'MES 连接成功' if result else 'MES 连接失败'
        })
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('MES', 'test_connection', '', '', 500, str(e), elapsed)
        return jsonify({'success': False, 'message': str(e)}), 500


@api_bp.route('/mes/capacity', methods=['GET'])
def get_mes_capacity():
    """从 MES 获取标产数据"""
    line_id = request.args.get('line_id')
    product_code = request.args.get('product_code')
    
    start_time = time.time()
    mes = AdapterFactory.get_mes_adapter()
    
    try:
        data = mes.get_capacity_data(line_id, product_code)
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('MES', 'get_capacity_data', 
                     json.dumps({'line_id': line_id, 'product_code': product_code}),
                     json.dumps(data), 200, '', elapsed)
        
        return jsonify(data)
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('MES', 'get_capacity_data', 
                     json.dumps({'line_id': line_id}), '', 500, str(e), elapsed)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/mes/progress/<order_id>', methods=['GET'])
def get_mes_production_progress(order_id):
    """从 MES 获取生产进度"""
    start_time = time.time()
    mes = AdapterFactory.get_mes_adapter()
    
    try:
        data = mes.get_production_progress(order_id)
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('MES', 'get_production_progress', order_id,
                     json.dumps(data), 200, '', elapsed)
        
        return jsonify(data)
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('MES', 'get_production_progress', order_id, '', 500, str(e), elapsed)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/sap/test', methods=['GET'])
def test_sap_connection():
    """测试 SAP 连接"""
    start_time = time.time()
    sap = AdapterFactory.get_sap_adapter()
    
    try:
        result = sap.test_connection()
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('SAP', 'test_connection', '', json.dumps({'result': result}),
                     200 if result else 500, '', elapsed)
        
        return jsonify({
            'success': result,
            'message': 'SAP 连接成功' if result else 'SAP 连接失败'
        })
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('SAP', 'test_connection', '', '', 500, str(e), elapsed)
        return jsonify({'success': False, 'message': str(e)}), 500


@api_bp.route('/sap/orders', methods=['GET'])
def get_sap_orders():
    """从 SAP 获取订单数据 (ZPP008)"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    start_time = time.time()
    sap = AdapterFactory.get_sap_adapter()
    
    try:
        orders = sap.get_orders_from_zpp008(start_date, end_date)
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('SAP', 'get_orders_from_zpp008', 
                     json.dumps({'start_date': start_date, 'end_date': end_date}),
                     json.dumps(orders), 200, '', elapsed)
        
        return jsonify(orders)
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('SAP', 'get_orders_from_zpp008', 
                     json.dumps({'start_date': start_date}), '', 500, str(e), elapsed)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/sap/material_delivery', methods=['GET'])
def get_sap_material_delivery():
    """从 SAP 获取物料交期"""
    material_code = request.args.get('material_code')
    
    if not material_code:
        return jsonify({'error': '缺少 material_code 参数'}), 400
    
    start_time = time.time()
    sap = AdapterFactory.get_sap_adapter()
    
    try:
        delivery_date = sap.get_material_delivery_date(material_code)
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('SAP', 'get_material_delivery_date', material_code,
                     json.dumps({'delivery_date': delivery_date}), 200, '', elapsed)
        
        return jsonify({'material_code': material_code, 'delivery_date': delivery_date})
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('SAP', 'get_material_delivery_date', material_code, '', 500, str(e), elapsed)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/sap/demand_time', methods=['GET'])
def get_sap_demand_time():
    """从 SAP 获取客户需求时间"""
    sales_order = request.args.get('sales_order')
    item = request.args.get('item', '')
    
    if not sales_order:
        return jsonify({'error': '缺少 sales_order 参数'}), 400
    
    start_time = time.time()
    sap = AdapterFactory.get_sap_adapter()
    
    try:
        demand_date = sap.get_order_demand_time(sales_order, item)
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('SAP', 'get_order_demand_time', 
                     json.dumps({'sales_order': sales_order, 'item': item}),
                     json.dumps({'demand_date': demand_date}), 200, '', elapsed)
        
        return jsonify({'sales_order': sales_order, 'item': item, 'demand_date': demand_date})
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('SAP', 'get_order_demand_time', 
                     json.dumps({'sales_order': sales_order}), '', 500, str(e), elapsed)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/sap/product_info/<product_code>', methods=['GET'])
def get_sap_product_info(product_code):
    """从 SAP 获取产品主数据"""
    start_time = time.time()
    sap = AdapterFactory.get_sap_adapter()
    
    try:
        info = sap.get_product_info(product_code)
        elapsed = int((time.time() - start_time) * 1000)
        
        APILogDAO.log('SAP', 'get_product_info', product_code,
                     json.dumps(info), 200, '', elapsed)
        
        return jsonify(info)
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        APILogDAO.log('SAP', 'get_product_info', product_code, '', 500, str(e), elapsed)
        return jsonify({'error': str(e)}), 500


# ==========================================
# 接口日志
# ==========================================

@api_bp.route('/api_logs', methods=['GET'])
def get_api_logs():
    """获取接口日志"""
    limit = request.args.get('limit', 100, type=int)
    logs = APILogDAO.get_recent(limit)
    return jsonify(logs)


# ==========================================
# 同步接口
# ==========================================

@api_bp.route('/sync/import_all', methods=['POST'])
def sync_import_all():
    """从 MES/SAP 同步所有数据到本地数据库"""
    from database import get_db_connection
    
    mes = AdapterFactory.get_mes_adapter()
    sap = AdapterFactory.get_sap_adapter()
    
    results = {
        'capacity': 0,
        'orders': 0,
        'products': 0
    }
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. 同步标产数据 (从 MES)
        all_capacity = mes.get_all_capacity_data()
        for cap in all_capacity:
            try:
                CapacityStandardsDAO.insert({
                    'line_id': cap.get('line_id'),
                    'line_name': cap.get('line_id'),
                    'capacity_type': cap.get('line_type', 'DEFAULT'),
                    'product_code': None,  # 通用标产，无特定产品
                    'std_capacity': cap.get('std_capacity', 0),
                    'std_time': cap.get('std_time', 0),
                    'unit': cap.get('unit', 'PCS'),
                    'source': 'MES',
                    'effective_date': datetime.now().strftime('%Y-%m-%d')
                })
                results['capacity'] += 1
            except Exception as e:
                print(f"导入标产失败: {e}")
                pass
        
        # 2. 同步订单数据 (从 SAP)
        sap_orders = sap.get_orders_from_zpp008()
        for order in sap_orders:
            task_id = f"WO-SAP-{order.get('sales_order', '')}-{order.get('item', '')}"
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO work_orders (
                        task_id, job_id, product_code, resource_id, qty, std_time, priority,
                        deadline, status, plan_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task_id,
                    order.get('sales_order'),
                    order.get('product_code'),
                    'AUTO',
                    order.get('qty', 0),
                    120,  # 默认工时
                    order.get('priority', 5),
                    order.get('demand_date'),
                    'Pending',
                    'OFFICIAL'
                ))
                results['orders'] += 1
            except Exception as e:
                print(f"导入订单失败: {e}")
        
        # 3. 同步产品主数据 (从 SAP)
        products = ['TV-32', 'TV-40', 'TV-42', 'TV-50', 'TV-55', 'TV-65', 'TV-75', 'TV-85']
        for product_code in products:
            info = sap.get_product_info(product_code)
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO products (product_code, screen_size, platform)
                    VALUES (?, ?, ?)
                ''', (
                    product_code,
                    int(product_code.split('-')[1]) if '-' in product_code else 0,
                    info.get('product_type', '')
                ))
                results['products'] += 1
            except:
                pass
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'导入完成! 标产:{results["capacity"]}条, 订单:{results["orders"]}条, 产品:{results["products"]}条',
            'details': results
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()


@api_bp.route('/sync/mes_capacity', methods=['POST'])
def sync_mes_capacity():
    """从 MES 同步标产数据到本地数据库"""
    mes = AdapterFactory.get_mes_adapter()
    
    try:
        # 获取所有产线的标产数据
        lines = LineConfigDAO.get_all()
        synced_count = 0
        
        for line in lines:
            data = mes.get_capacity_data(line['line_id'])
            if data.get('std_time', 0) > 0:
                CapacityStandardsDAO.insert({
                    'line_id': line['line_id'],
                    'line_name': line['line_name'],
                    'capacity_type': data.get('capacity_type', 'DEFAULT'),
                    'product_code': data.get('product_code'),
                    'std_capacity': data.get('std_capacity', 0),
                    'std_time': data.get('std_time', 0),
                    'unit': data.get('unit', 'PCS'),
                    'source': 'MES',
                    'effective_date': datetime.now().strftime('%Y-%m-%d')
                })
                synced_count += 1
        
        return jsonify({'success': True, 'synced_count': synced_count})
    except Exception as e:
        logger.error(f"同步 MES 标产数据失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@api_bp.route('/sync/sap_orders', methods=['POST'])
def sync_sap_orders():
    """从 SAP 同步订单数据"""
    sap = AdapterFactory.get_sap_adapter()
    
    try:
        orders = sap.get_orders_from_zpp008()
        # TODO: 将订单数据保存到 work_orders 表
        return jsonify({'success': True, 'count': len(orders), 'orders': orders})
    except Exception as e:
        logger.error(f"同步 SAP 订单失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@api_bp.route('/sync/product_line_mapping', methods=['POST'])
def sync_product_line_mapping():
    """从 Excel 导入产品-产线映射配置"""
    import os
    
    # Excel 文件路径
    excel_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        'workspace', '自动排程表格.xlsx'
    )
    
    if not os.path.exists(excel_path):
        # 尝试工作区路径
        excel_path = 'C:/Users/mtc/.openclaw/workspace/自动排程表格.xlsx'
    
    if not os.path.exists(excel_path):
        return jsonify({'success': False, 'message': 'Excel文件未找到'}), 404
    
    try:
        # 导入解析函数
        sys.path.insert(0, os.path.dirname(__file__))
        from import_excel import import_product_line_mapping_from_excel
        
        # 解析 Excel
        mappings = import_product_line_mapping_from_excel(excel_path)
        
        # 保存到数据库
        from database_extend import ProductLineMappingDAO
        
        # 清空旧数据
        with get_db_connection() as conn:
            conn.execute('DELETE FROM product_line_mapping')
        
        # 插入新数据
        saved_count = 0
        for m in mappings:
            try:
                ProductLineMappingDAO.insert({
                    'company_code': m.get('company_code'),
                    'material_group': m.get('material_group'),
                    'range_condition': m.get('range_condition'),
                    'line_id_1': m.get('lines', '').split(',')[0] if m.get('lines') else None,
                    'line_id_2': m.get('lines', '').split(',')[1] if len(m.get('lines', '').split(',')) > 1 else None,
                    'line_id_3': m.get('lines', '').split(',')[2] if len(m.get('lines', '').split(',')) > 2 else None,
                    'line_id_4': m.get('lines', '').split(',')[3] if len(m.get('lines', '').split(',')) > 3 else None,
                    'line_id_5': m.get('lines', '').split(',')[4] if len(m.get('lines', '').split(',')) > 4 else None,
                    'line_id_6': m.get('lines', '').split(',')[5] if len(m.get('lines', '').split(',')) > 5 else None,
                    'line_id_7': m.get('lines', '').split(',')[6] if len(m.get('lines', '').split(',')) > 6 else None,
                    'line_id_8': m.get('lines', '').split(',')[7] if len(m.get('lines', '').split(',')) > 7 else None,
                    'line_id_9': m.get('lines', '').split(',')[8] if len(m.get('lines', '').split(',')) > 8 else None,
                    'line_id_10': m.get('lines', '').split(',')[9] if len(m.get('lines', '').split(',')) > 9 else None,
                    'line_type': m.get('line_type'),
                    'notes': m.get('lines', '')
                })
                saved_count += 1
            except Exception as e:
                logger.error(f"保存映射失败: {e}")
        
        return jsonify({
            'success': True, 
            'message': f'导入完成! 共 {saved_count} 条配置',
            'count': saved_count
        })
        
    except Exception as e:
        logger.error(f"导入产品-产线映射失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
