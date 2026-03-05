# -*- coding: utf-8 -*-
"""
数据库扩展模块
新增产线配置表、标产数据表、产品-产线映射表
"""
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_FILE = 'tv_aps_pro_v3.db'


@contextmanager
def get_db_connection():
    """数据库连接上下文管理器"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode("utf-8", "ignore")
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"数据库错误: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def migrate_extend_tables():
    """扩展数据库表结构"""
    logger.info("开始数据库迁移...")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. 公司表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS companies (
                company_code TEXT PRIMARY KEY,
                company_name TEXT,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 2. 物料组表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS material_groups (
                group_code TEXT PRIMARY KEY,
                group_name TEXT,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 3. 产品-产线配置表（核心）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS product_line_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_code TEXT,
                material_group TEXT,
                product_code TEXT,
                range_condition TEXT,
                line_id_1 TEXT,
                line_id_2 TEXT,
                line_id_3 TEXT,
                line_id_4 TEXT,
                line_id_5 TEXT,
                line_id_6 TEXT,
                line_id_7 TEXT,
                line_id_8 TEXT,
                line_id_9 TEXT,
                line_id_10 TEXT,
                line_type TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_code) REFERENCES companies(company_code)
            )
        ''')
        
        # 4. 标产数据表（标准产能）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS capacity_standards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_id TEXT NOT NULL,
                line_name TEXT,
                capacity_type TEXT,
                product_code TEXT,
                std_capacity INTEGER,
                std_time INTEGER,
                setup_time INTEGER DEFAULT 0,
                unit TEXT DEFAULT 'PCS',
                effective_date TEXT,
                is_active INTEGER DEFAULT 1,
                source TEXT DEFAULT 'MANUAL',
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 5. 产线扩展信息表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS line_config (
                line_id TEXT PRIMARY KEY,
                line_name TEXT,
                line_type TEXT,
                company_code TEXT,
                work_hours REAL DEFAULT 24.0,
                capacity_ratio REAL DEFAULT 1.0,
                min_size INTEGER,
                max_size INTEGER,
                support_dip INTEGER DEFAULT 0,
                support_smt INTEGER DEFAULT 0,
                capability_config TEXT,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 6. 接口配置表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_type TEXT NOT NULL,
                config_key TEXT NOT NULL,
                config_value TEXT,
                description TEXT,
                is_encrypted INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 7. 接口日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_type TEXT NOT NULL,
                method TEXT,
                request_data TEXT,
                response_data TEXT,
                status_code INTEGER,
                error_message TEXT,
                execution_time_ms INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 8. 订单扩展信息（对接 MES/SAP 数据）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_extensions (
                order_id TEXT PRIMARY KEY,
                sales_order TEXT,
                sales_item TEXT,
                customer_name TEXT,
                material_delivery_date TEXT,
                demand_date TEXT,
                production_progress INTEGER DEFAULT 0,
                current_station TEXT,
                output_qty INTEGER DEFAULT 0,
                mes_status TEXT,
                sap_status TEXT,
                last_sync_time TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES work_orders(task_id)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mapping_company ON product_line_mapping(company_code)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mapping_material ON product_line_mapping(material_group)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_capacity_line ON capacity_standards(line_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_capacity_product ON capacity_standards(product_code)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_line_config_type ON line_config(line_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_logs_type ON api_logs(api_type)')
        
        # 7. 日历表 - 支持不同车间
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS calendars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workshop_code TEXT NOT NULL,
                workshop_name TEXT,
                calendar_date TEXT NOT NULL,
                is_workday INTEGER DEFAULT 1,
                shift_type TEXT DEFAULT 'FULL',
                work_start_time TEXT DEFAULT '08:00',
                work_end_time TEXT DEFAULT '20:00',
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(workshop_code, calendar_date)
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_calendar_workshop ON calendars(workshop_code)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendars(calendar_date)')
        
    logger.info("数据库迁移完成")


# ==========================================
# 数据操作接口
# ==========================================

class ProductLineMappingDAO:
    """产品-产线映射 DAO"""
    
    @staticmethod
    def get_all() -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM product_line_mapping ORDER BY company_code, material_group").fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_company(company_code: str) -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM product_line_mapping WHERE company_code = ?", 
                (company_code,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_material_group(material_group: str, company_code: Optional[str] = None) -> List[Dict]:
        with get_db_connection() as conn:
            if company_code:
                rows = conn.execute(
                    """SELECT * FROM product_line_mapping 
                       WHERE material_group = ? AND company_code = ?""", 
                    (material_group, company_code)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM product_line_mapping WHERE material_group = ?", 
                    (material_group,)
                ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def insert(data: Dict) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO product_line_mapping (
                    company_code, material_group, product_code, range_condition,
                    line_id_1, line_id_2, line_id_3, line_id_4, line_id_5,
                    line_id_6, line_id_7, line_id_8, line_id_9, line_id_10,
                    line_type, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('company_code'), data.get('material_group'), data.get('product_code'),
                data.get('range_condition'), data.get('line_id_1'), data.get('line_id_2'),
                data.get('line_id_3'), data.get('line_id_4'), data.get('line_id_5'),
                data.get('line_id_6'), data.get('line_id_7'), data.get('line_id_8'),
                data.get('line_id_9'), data.get('line_id_10'), data.get('line_type'), data.get('notes')
            ))
            return cursor.lastrowid
    
    @staticmethod
    def update(id: int, data: Dict) -> bool:
        with get_db_connection() as conn:
            conn.execute('''
                UPDATE product_line_mapping SET
                    company_code = ?, material_group = ?, product_code = ?, range_condition = ?,
                    line_id_1 = ?, line_id_2 = ?, line_id_3 = ?, line_id_4 = ?, line_id_5 = ?,
                    line_id_6 = ?, line_id_7 = ?, line_id_8 = ?, line_id_9 = ?, line_id_10 = ?,
                    line_type = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                data.get('company_code'), data.get('material_group'), data.get('product_code'),
                data.get('range_condition'), data.get('line_id_1'), data.get('line_id_2'),
                data.get('line_id_3'), data.get('line_id_4'), data.get('line_id_5'),
                data.get('line_id_6'), data.get('line_id_7'), data.get('line_id_8'),
                data.get('line_id_9'), data.get('line_id_10'), data.get('line_type'), 
                data.get('notes'), id
            ))
            return True
    
    @staticmethod
    def delete(id: int) -> bool:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM product_line_mapping WHERE id = ?", (id,))
            return True


class CapacityStandardsDAO:
    """标产数据 DAO"""
    
    @staticmethod
    def get_all() -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM capacity_standards WHERE is_active = 1 ORDER BY line_id, capacity_type"
            ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_line(line_id: str) -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM capacity_standards 
                   WHERE line_id = ? AND is_active = 1 
                   ORDER BY capacity_type""", 
                (line_id,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_product(line_id: str, product_code: str) -> Optional[Dict]:
        with get_db_connection() as conn:
            row = conn.execute(
                """SELECT * FROM capacity_standards 
                   WHERE line_id = ? AND product_code = ? AND is_active = 1""", 
                (line_id, product_code)
            ).fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def insert(data: Dict) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO capacity_standards (
                    line_id, line_name, capacity_type, product_code,
                    std_capacity, std_time, setup_time, unit,
                    effective_date, source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('line_id'), data.get('line_name'), data.get('capacity_type'),
                data.get('product_code'), data.get('std_capacity'), data.get('std_time'),
                data.get('setup_time', 0), data.get('unit', 'PCS'),
                data.get('effective_date'), data.get('source', 'MANUAL'), data.get('notes')
            ))
            return cursor.lastrowid
    
    @staticmethod
    def batch_insert(data_list: List[Dict]) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO capacity_standards (
                    line_id, line_name, capacity_type, product_code,
                    std_capacity, std_time, setup_time, unit,
                    effective_date, source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [(d.get('line_id'), d.get('line_name'), d.get('capacity_type'),
                   d.get('product_code'), d.get('std_capacity'), d.get('std_time'),
                   d.get('setup_time', 0), d.get('unit', 'PCS'),
                   d.get('effective_date'), d.get('source', 'MANUAL'), d.get('notes'))
                  for d in data_list])
            return cursor.rowcount


class LineConfigDAO:
    """产线配置 DAO"""
    
    @staticmethod
    def get_all() -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM line_config WHERE is_active = 1 ORDER BY line_id"
            ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_type(line_type: str) -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM line_config WHERE line_type = ? AND is_active = 1 ORDER BY line_id",
                (line_type,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def insert(data: Dict) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO line_config (
                    line_id, line_name, line_type, company_code,
                    work_hours, capacity_ratio, min_size, max_size,
                    support_dip, support_smt, capability_config, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('line_id'), data.get('line_name'), data.get('line_type'),
                data.get('company_code'), data.get('work_hours', 24.0),
                data.get('capacity_ratio', 1.0), data.get('min_size'),
                data.get('max_size'), data.get('support_dip', 0),
                data.get('support_smt', 0), data.get('capability_config'), data.get('description')
            ))
            return cursor.lastrowid


class APILogDAO:
    """接口日志 DAO"""
    
    @staticmethod
    def log(api_type: str, method: str, request_data: str, 
            response_data: str, status_code: int, error_message: str,
            execution_time_ms: int):
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO api_logs (
                    api_type, method, request_data, response_data,
                    status_code, error_message, execution_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (api_type, method, request_data, response_data, 
                  status_code, error_message, execution_time_ms))
    
    @staticmethod
    def get_recent(limit: int = 100) -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM api_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]


class CalendarDAO:
    """日历 DAO"""
    
    # 车间类型
    WORKSHOP_TYPES = {
        'SMT': 'SMT车间',
        'DIP': 'DIP车间',
        'ASSEMBLY': '总装车间',
        'WAREHOUSE': '仓库'
    }
    
    @staticmethod
    def get_workshops() -> List[Dict]:
        """获取所有车间"""
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT workshop_code, workshop_name, COUNT(*) as days_count,
                       SUM(CASE WHEN is_workday = 1 THEN 1 ELSE 0 END) as workdays
                FROM calendars 
                GROUP BY workshop_code, workshop_name
            """).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_all(workshop_code: str = None, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取日历数据"""
        with get_db_connection() as conn:
            query = "SELECT * FROM calendars WHERE 1=1"
            params = []
            
            if workshop_code:
                query += " AND workshop_code = ?"
                params.append(workshop_code)
            if start_date:
                query += " AND calendar_date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND calendar_date <= ?"
                params.append(end_date)
            
            query += " ORDER BY workshop_code, calendar_date"
            
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def import_batch(data_list: List[Dict]) -> int:
        """批量导入日历"""
        count = 0
        with get_db_connection() as conn:
            for data in data_list:
                try:
                    conn.execute('''
                        INSERT OR REPLACE INTO calendars (
                            workshop_code, workshop_name, calendar_date, 
                            is_workday, shift_type, work_start_time, work_end_time, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        data.get('workshop_code'),
                        data.get('workshop_name'),
                        data.get('calendar_date'),
                        data.get('is_workday', 1),
                        data.get('shift_type', 'FULL'),
                        data.get('work_start_time', '08:00'),
                        data.get('work_end_time', '20:00'),
                        data.get('notes')
                    ))
                    count += 1
                except Exception as e:
                    logging.warning(f"导入日历失败: {e}")
        return count
    
    @staticmethod
    def export(workshop_code: str = None, start_date: str = None, end_date: str = None) -> List[Dict]:
        """导出日历数据"""
        return CalendarDAO.get_all(workshop_code, start_date, end_date)
    
    @staticmethod
    def delete(workshop_code: str = None) -> int:
        """删除日历数据"""
        with get_db_connection() as conn:
            if workshop_code:
                conn.execute("DELETE FROM calendars WHERE workshop_code = ?", (workshop_code,))
            else:
                conn.execute("DELETE FROM calendars")
            return conn.total_changes


# ==========================================
# 初始化数据
# ==========================================

def init_extend_data():
    """初始化扩展数据"""
    logger.info("初始化扩展数据...")
    
    with get_db_connection() as conn:
        # 检查是否已有数据
        count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        if count > 0:
            logger.info("扩展数据已存在，跳过初始化")
            return
    
    # 初始化公司数据
    companies = [
        ('1010', '公司1010', 'SMT产线'),
        ('1000', '公司1000', '主要产线'),
        ('1050', '公司1050', 'DIP产线'),
        ('5070', '公司5070', '特殊产线'),
    ]
    with get_db_connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO companies (company_code, company_name, description) VALUES (?, ?, ?)",
            companies
        )
    
    # 初始化物料组
    material_groups = [
        ('511', '物料组511', 'A类产品'),
        ('513', '物料组513', 'B类产品'),
        ('514', '物料组514', 'C类产品'),
        ('515', '物料组515', 'D类产品'),
        ('534', '物料组534', '单箱体'),
        ('535', '物料组535', '特殊产品'),
        ('523', '物料组523', '双箱体'),
        ('555', '物料组555', '特殊配置'),
    ]
    with get_db_connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO material_groups (group_code, group_name, description) VALUES (?, ?, ?)",
            material_groups
        )
    
    # 初始化产线配置（从 Excel 提取的线体）
    smt_lines = [f'S{i:02d}' for i in list(range(1, 50)) + [98, 99]]
    dip_lines = [f'D{i:02d}' for i in range(1, 23)]
    
    line_configs = []
    for line in smt_lines:
        line_configs.append((line, f'SMT-{line}', 'SMT', '1010', 24.0, 1.0, None, None, 0, 1, '', f'SMT产线{line}'))
    for line in dip_lines:
        line_configs.append((line, f'DIP-{line}', 'DIP', '1000', 24.0, 1.0, None, None, 1, 0, '', f'DIP产线{line}'))
    
    with get_db_connection() as conn:
        conn.executemany('''
            INSERT OR IGNORE INTO line_config (
                line_id, line_name, line_type, company_code,
                work_hours, capacity_ratio, min_size, max_size,
                support_dip, support_smt, capability_config, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', line_configs)
    
    logger.info("扩展数据初始化完成")


if __name__ == '__main__':
    migrate_extend_tables()
    init_extend_data()
    print("数据库扩展完成！")
