# -*- coding: utf-8 -*-
"""
MES/SAP 接口适配器框架
用于从 MES 和 SAP 系统获取排产所需数据
"""
import requests
import json
import logging
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==========================================
# 抽象基类
# ==========================================

class BaseAdapter(ABC):
    """接口适配器基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', False)
        self.base_url = config.get('base_url', '')
        self.timeout = config.get('timeout', 30)
    
    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接"""
        pass


# ==========================================
# MES 适配器
# ==========================================

class MESAdapter(BaseAdapter):
    """MES (制造执行系统) 数据适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get('api_key', '')
    
    def test_connection(self) -> bool:
        """测试 MES 连接"""
        if not self.enabled:
            logger.info("MES 适配器未启用")
            return False
        
        try:
            # 实际对接时替换为真实的健康检查接口
            response = requests.get(
                f"{self.base_url}/health",
                timeout=self.timeout,
                headers=self._get_headers()
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"MES 连接测试失败: {e}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        return headers
    
    # ------------------- 标产数据 -------------------
    
    def get_capacity_data(self, line_id: str, product_code: Optional[str] = None) -> Dict[str, Any]:
        """
        获取标产数据（标准产能）
        
        Args:
            line_id: 产线ID (如 S01, D01)
            product_code: 产品品号（可选）
        
        Returns:
            {
                "line_id": "S01",
                "product_code": "TV-32",
                "std_capacity": 500,  # 标准产能（台/班）
                "std_time": 120,       # 标准工时（分钟）
                "unit": "PCS",         # 单位
                "update_time": "2026-03-05 10:00:00"
            }
        """
        logger.info(f"[MES] 获取标产数据: line={line_id}, product={product_code}")
        
        # 调用 MES API
        try:
            url = f"{self.base_url}/api/capacity"
            params = {'line_id': line_id}
            if product_code:
                params['product_code'] = product_code
            
            response = requests.get(url, params=params, timeout=self.timeout, headers=self._get_headers())
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"MES API 调用失败: {e}")
        
        # 失败返回空数据
        return {
            "line_id": line_id,
            "product_code": product_code,
            "std_capacity": 0,
            "std_time": 0,
            "unit": "PCS",
            "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "source": "MES",
            "status": "error"
        }
    
    def get_all_capacity_data(self) -> List[Dict[str, Any]]:
        """获取所有标产数据"""
        logger.info("[MES] 获取所有标产数据")
        
        try:
            url = f"{self.base_url}/api/all_capacity"
            response = requests.get(url, timeout=self.timeout, headers=self._get_headers())
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"MES API 调用失败: {e}")
        
        return []
    
    # ------------------- 生产进度 -------------------
    
    def get_production_progress(self, order_id: str) -> Dict[str, Any]:
        """
        获取生产进度
        
        Args:
            order_id: 工单ID
        
        Returns:
            {
                "order_id": "WO-001",
                "progress": 65,        # 进度百分比
                "status": "生产中",
                "current_station": "A面",
                "output_qty": 650,
                "target_qty": 1000,
                "start_time": "2026-03-05 08:00:00",
                "update_time": "2026-03-05 10:30:00"
            }
        """
        logger.info(f"[MES] 获取生产进度: order={order_id}")
        
        try:
            url = f"{self.base_url}/api/progress/{order_id}"
            response = requests.get(url, timeout=self.timeout, headers=self._get_headers())
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"MES API 调用失败: {e}")
        
        return {
            "order_id": order_id,
            "progress": 0,
            "status": "未开始",
            "current_station": "",
            "output_qty": 0,
            "target_qty": 0,
            "start_time": "",
            "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "source": "MES"
        }
    
    # ------------------- 实时产出 -------------------
    
    def get_real_time_output(self, line_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取产线实时产出
        
        Args:
            line_id: 产线ID
            date: 日期（默认今天）
        """
        logger.info(f"[MES] 获取实时产出: line={line_id}, date={date}")
        
        # TODO: 实际对接
        return {
            "line_id": line_id,
            "date": date or datetime.now().strftime('%Y-%m-%d'),
            "output_qty": 0,
            "qualified_qty": 0,
            "defect_qty": 0,
            "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


# ==========================================
# SAP 适配器
# ==========================================

class SAPAdapter(BaseAdapter):
    """SAP 数据适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client = config.get('client', '100')
        self.sysid = config.get('sysid', 'PRD')
    
    def test_connection(self) -> bool:
        """测试 SAP 连接"""
        if not self.enabled:
            logger.info("SAP 适配器未启用")
            return False
        
        try:
            # 调用 SAP 健康检查接口
            response = requests.get(
                f"{self.base_url}/health",
                timeout=self.timeout
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"SAP 连接测试失败: {e}")
            return False
    
    # ------------------- 物料交期 -------------------
    
    def get_material_delivery_date(self, material_code: str) -> Optional[str]:
        """
        获取物料交期
        
        Args:
            material_code: 物料编号
        
        Returns:
            交期日期字符串 "YYYY-MM-DD" 或 None
        """
        logger.info(f"[SAP] 获取物料交期: {material_code}")
        
        try:
            url = f"{self.base_url}/api/material_delivery"
            params = {'material_code': material_code}
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                return data.get('delivery_date')
        except Exception as e:
            logger.error(f"SAP API 调用失败: {e}")
        
        return None
    
    def get_material_delivery_batch(self, material_codes: List[str]) -> Dict[str, str]:
        """批量获取物料交期"""
        results = {}
        for code in material_codes:
            results[code] = self.get_material_delivery_date(code)
        return results
    
    # ------------------- 客户需求时间 -------------------
    
    def get_order_demand_time(self, sales_order: str, item: str = "") -> Optional[str]:
        """
        获取客户需求时间
        
        Args:
            sales_order: 销售订单号
            item: 订单行项目（可选）
        
        Returns:
            需求日期 "YYYY-MM-DD" 或 None
        """
        logger.info(f"[SAP] 获取需求时间: {sales_order}/{item}")
        
        try:
            url = f"{self.base_url}/api/demand_time"
            params = {'sales_order': sales_order}
            if item:
                params['item'] = item
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                return data.get('demand_date')
        except Exception as e:
            logger.error(f"SAP API 调用失败: {e}")
        
        return None
    
    # ------------------- 订单数据 (ZPP008) -------------------
    
    def get_orders_from_zpp008(self, start_date: Optional[str] = None, 
                                end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        从 SAP ZPP008 获取排产订单
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            订单列表
        """
        logger.info(f"[SAP] 获取ZPP008订单: {start_date} ~ {end_date}")
        
        try:
            url = f"{self.base_url}/api/orders"
            params = {}
            if start_date:
                params['start_date'] = start_date
            if end_date:
                params['end_date'] = end_date
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                return data.get('data', [])
        except Exception as e:
            logger.error(f"SAP API 调用失败: {e}")
        
        return []
    
    # ------------------- 物料主数据 -------------------
    
    def get_product_info(self, product_code: str) -> Dict[str, Any]:
        """
        获取产品主数据
        
        Args:
            product_code: 产品编号
        
        Returns:
            产品主数据
        """
        logger.info(f"[SAP] 获取产品主数据: {product_code}")
        
        try:
            url = f"{self.base_url}/api/product_info/{product_code}"
            response = requests.get(url, timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"SAP API 调用失败: {e}")
        
        return {
            "product_code": product_code,
            "material_group": "",
            "description": "",
            "unit": "PCS",
            "weight": 0,
            "product_type": "",
            "source": "SAP"
        }


# ==========================================
# 适配器工厂
# ==========================================

class AdapterFactory:
    """适配器工厂"""
    
    _instances = {
        'mes': None,
        'sap': None
    }
    
    @classmethod
    def get_mes_adapter(cls, config: Optional[Dict] = None) -> MESAdapter:
        """获取 MES 适配器实例"""
        if cls._instances['mes'] is None:
            if config is None:
                # 从配置文件加载
                config = cls._load_config('mes')
            cls._instances['mes'] = MESAdapter(config)
        return cls._instances['mes']
    
    @classmethod
    def get_sap_adapter(cls, config: Optional[Dict] = None) -> SAPAdapter:
        """获取 SAP 适配器实例"""
        if cls._instances['sap'] is None:
            if config is None:
                config = cls._load_config('sap')
            cls._instances['sap'] = SAPAdapter(config)
        return cls._instances['sap']
    
    @classmethod
    def _load_config(cls, adapter_type: str) -> Dict:
        """从配置文件加载配置"""
        import os
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'api_config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get(adapter_type, {})
        except FileNotFoundError:
            return {'enabled': False}
    
    @classmethod
    def reload_config(cls):
        """重新加载配置"""
        cls._instances['mes'] = None
        cls._instances['sap'] = None


# ==========================================
# 配置管理
# ==========================================

DEFAULT_CONFIG = {
    "mes": {
        "enabled": False,
        "base_url": "http://mes-server:8080/api",
        "api_key": "",
        "timeout": 30
    },
    "sap": {
        "enabled": False,
        "base_url": "http://sap-server:8000/sap/bc/rest",
        "client": "100",
        "sysid": "PRD",
        "timeout": 30
    }
}

def save_default_config():
    """保存默认配置"""
    with open('api_config.json', 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    logger.info("默认配置文件已创建: api_config.json")


if __name__ == '__main__':
    # 测试
    print("=== MES 适配器测试 ===")
    mes = MESAdapter({'enabled': False, 'base_url': 'http://localhost:8080'})
    print(f"连接状态: {mes.test_connection()}")
    print(f"标产数据: {mes.get_capacity_data('S01')}")
    
    print("\n=== SAP 适配器测试 ===")
    sap = SAPAdapter({'enabled': False, 'client': '100'})
    print(f"连接状态: {sap.test_connection()}")
    print(f"订单数据: {sap.get_orders_from_zpp008()}")
