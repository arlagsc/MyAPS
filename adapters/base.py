# -*- coding: utf-8 -*-
"""
MES/SAP 接口适配器框架
用于从 MES 和 SAP 系统获取排产所需数据
"""
import requests
import json
import logging
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==========================================
# 抽象基类 & MES 适配器 (保持原样)
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
        pass

class MESAdapter(BaseAdapter):
    """MES (制造执行系统) 数据适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get('api_key', '')
    
    def test_connection(self) -> bool:
        if not self.enabled: return False
        try:
            response = requests.get(f"{self.base_url}/health", timeout=self.timeout, headers=self._get_headers())
            return response.status_code == 200
        except Exception: return False
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.api_key: headers['X-API-Key'] = self.api_key
        return headers
    
    def get_capacity_data(self, line_id: str, product_code: Optional[str] = None) -> Dict[str, Any]:
        # 省略部分重复代码，保持原样
        return {"line_id": line_id, "std_capacity": 500, "std_time": 120, "unit": "PCS"}
    
    def get_all_capacity_data(self) -> List[Dict[str, Any]]:
        return []
    
    def get_production_progress(self, order_id: str) -> Dict[str, Any]:
        return {"order_id": order_id, "progress": 0, "status": "未开始"}
    
    def get_real_time_output(self, line_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        return {"line_id": line_id, "output_qty": 0}


# ==========================================
# SAP 适配器 (核心强化区)
# ==========================================

class SAPAdapter(BaseAdapter):
    """SAP 数据适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client = config.get('client', '100')
        self.sysid = config.get('sysid', 'PRD')
    
    def test_connection(self) -> bool:
        if not self.enabled: return False
        try:
            response = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            return response.status_code == 200
        except Exception: return False
    
    # ------------------- 预排交期评估接口 (核心新增) -------------------
    
    def evaluate_pre_schedule_delivery(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        [PRD 核心规则] 预排交期窗口评估
        一周内(T+1~T+6): 强依赖SRM回复交期/库存
        一周外(T+7外): 不看材料，只看下单时间是否满足15天生产周期
        """
        logger.info(f"[SAP] 评估订单预排交期: {order_data.get('sales_order')}")
        
        create_date_str = order_data.get('create_date', datetime.now().strftime('%Y-%m-%d'))
        demand_date_str = order_data.get('demand_date')
        
        create_date = datetime.strptime(create_date_str, '%Y-%m-%d')
        demand_date = datetime.strptime(demand_date_str, '%Y-%m-%d') if demand_date_str else create_date + timedelta(days=20)
        
        days_to_demand = (demand_date - datetime.now()).days
        material_ready_level = order_data.get('material_ready_level', 'STOCK_READY')
        
        eval_result = {
            "sales_order": order_data.get('sales_order'),
            "is_feasible": True,
            "risk_level": "LOW",
            "suggestion": "正常排产"
        }
        
        # 规则 1：一周外 (T+7以后)，评估粗能力
        if days_to_demand >= 7:
            total_cycle_days = (demand_date - create_date).days
            if total_cycle_days < 15:
                eval_result["is_feasible"] = False
                eval_result["risk_level"] = "HIGH"
                eval_result["suggestion"] = "交期距下单不足15天，需业务重新评审交期"
            else:
                eval_result["suggestion"] = "满足15天周期，暂无需考虑材料齐套，直接粗排"
                
        # 规则 2：一周内 (T+1 ~ T+6)，强依赖物料
        else:
            if material_ready_level == 'SHORTAGE':
                eval_result["is_feasible"] = False
                eval_result["risk_level"] = "HIGH"
                eval_result["suggestion"] = "一周内急单，缺料状态，驳回排产"
            elif material_ready_level == 'SRM_TRANSIT':
                srm_reply_date_str = order_data.get('srm_reply_date')
                if not srm_reply_date_str:
                    eval_result["is_feasible"] = False
                    eval_result["suggestion"] = "一周内订单，SRM无交期回复，无法排产"
                else:
                    srm_reply_date = datetime.strptime(srm_reply_date_str, '%Y-%m-%d')
                    if srm_reply_date > demand_date:
                        eval_result["is_feasible"] = False
                        eval_result["risk_level"] = "HIGH"
                        eval_result["suggestion"] = f"SRM交期({srm_reply_date_str})晚于需求日，存在断线风险"
            else:
                eval_result["suggestion"] = "库存满足，可立即锁定排程"

        return eval_result

    # ------------------- 工艺路线二次识别 (核心新增) -------------------

    def _determine_workshop_type(self, workshop_code: str, product_code: str, desc: str) -> str:
        """
        [PRD 核心规则] 解决 1010SC03 SMT/DIP 混杂问题
        """
        # 1000工厂特征明确
        if workshop_code in ['1000SC09', '1000SC10', '1000SC12', '1000SC13']:
            return 'SMT'
        if workshop_code == '1000SC11':
            return 'DIP'
            
        # 1010工厂特征模糊，需要结合产品信息二次判断
        if workshop_code == '1010SC03':
            # 模拟查询 SAP 工艺路线或特征识别
            if 'SMT' in desc or '贴片' in desc or 'A面' in desc or 'B面' in desc:
                return 'SMT'
            if 'DIP' in desc or '插件' in desc or '手插' in desc:
                return 'DIP'
            # 默认兜底策略：带主板芯片通常走SMT，否则DIP（根据实际业务调整）
            return 'SMT' if '板' in desc else 'ASSEMBLY'
            
        return 'UNKNOWN'

    # ------------------- 订单数据 (ZPP008) -------------------
    
    def get_orders_from_zpp008(self, start_date: Optional[str] = None, 
                                end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """从 SAP ZPP008 获取排产订单，并进行车间分离"""
        logger.info(f"[SAP] 获取ZPP008订单: {start_date} ~ {end_date}")
        
        try:
            url = f"{self.base_url}/api/orders"
            params = {}
            if start_date: params['start_date'] = start_date
            if end_date: params['end_date'] = end_date
            
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json().get('data', [])
                
                # [核心注入]: 遍历清洗数据，识别真实车间
                for order in data:
                    ws_code = order.get('workshop_code', '')
                    p_code = order.get('product_code', '')
                    desc = order.get('component_desc', '')
                    
                    # 进行工艺路线二次判定
                    real_workshop = self._determine_workshop_type(ws_code, p_code, desc)
                    order['workshop'] = real_workshop
                    
                return data
        except Exception as e:
            logger.error(f"SAP API 调用失败: {e}")
        
        return []

    # 其他原有的 SAP 接口 (get_material_delivery_date 等) 保持省略或原样...
    def get_material_delivery_date(self, material_code: str) -> Optional[str]:
        return None
    def get_order_demand_time(self, sales_order: str, item: str = "") -> Optional[str]:
        return None
    def get_product_info(self, product_code: str) -> Dict[str, Any]:
        return {"product_code": product_code}


# ==========================================
# 适配器工厂与配置管理 (保持原样)
# ==========================================
class AdapterFactory:
    _instances = {'mes': None, 'sap': None}
    
    @classmethod
    def get_mes_adapter(cls, config: Optional[Dict] = None) -> MESAdapter:
        if cls._instances['mes'] is None:
            cls._instances['mes'] = MESAdapter(config or cls._load_config('mes'))
        return cls._instances['mes']
    
    @classmethod
    def get_sap_adapter(cls, config: Optional[Dict] = None) -> SAPAdapter:
        if cls._instances['sap'] is None:
            cls._instances['sap'] = SAPAdapter(config or cls._load_config('sap'))
        return cls._instances['sap']
    
    @classmethod
    def _load_config(cls, adapter_type: str) -> Dict:
        """从配置文件加载配置"""
        import os
        import json
        # 定位到项目根目录下的 api_config.json
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'api_config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get(adapter_type, {})
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            return {'enabled': False}
        
    @classmethod
    def reload_config(cls):
        cls._instances['mes'] = None
        cls._instances['sap'] = None

DEFAULT_CONFIG = {
    "mes": {"enabled": False, "base_url": "http://mes-server:8080/api", "api_key": "", "timeout": 30},
    "sap": {"enabled": False, "base_url": "http://sap-server:8000/sap/bc/rest", "client": "100", "sysid": "PRD", "timeout": 30}
}