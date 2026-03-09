# -*- coding: utf-8 -*-
"""
数据库扩展模块
新增产线配置表、标产数据表、产品-产线映射表、设备异常保养表
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
        
        # 1-8. 维持原有的 companies, material_groups, product_line_mapping, capacity_standards, 
        # line_config, api_configs, api_logs, order_extensions, calendars 表...
        # (为了篇幅省略建表语句，请保留您原来文件中的表结构，我们追加第9个表)
        
        # 9. [新增] 设备异常与保养计划表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equipment_maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                type TEXT DEFAULT 'MAINTENANCE', -- MAINTENANCE(保养), EXCEPTION(异常)
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_equip_maint_line ON equipment_maintenance(line_id)')
        
    logger.info("数据库迁移完成")


# ==========================================
# 数据操作接口 (保留原有的 DAO，追加以下 DAO)
# ==========================================

# ... 保留原有的 ProductLineMappingDAO, CapacityStandardsDAO, LineConfigDAO, APILogDAO, CalendarDAO ...

class EquipmentMaintenanceDAO:
    """设备异常与保养计划 DAO"""
    
    @staticmethod
    def get_by_line(line_id: str) -> List[Dict]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM equipment_maintenance WHERE line_id = ? ORDER BY start_time", 
                (line_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def insert(data: Dict) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO equipment_maintenance (
                    line_id, start_time, end_time, type, reason
                ) VALUES (?, ?, ?, ?, ?)
            ''', (
                data.get('line_id'), data.get('start_time'), 
                data.get('end_time'), data.get('type', 'MAINTENANCE'), data.get('reason')
            ))
            return cursor.lastrowid

    @staticmethod
    def delete(id: int) -> bool:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM equipment_maintenance WHERE id = ?", (id,))
            return True


# ==========================================
# 初始化数据
# ==========================================

def init_extend_data():
    """初始化扩展数据"""
    logger.info("初始化扩展数据...")
    
    with get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM line_config").fetchone()[0]
        if count > 0:
            logger.info("扩展数据已存在，跳过初始化")
            return
            
    # 初始化公司和物料组数据逻辑保留...
    
    # [核心修改]: 初始化产线配置，精准适配导图日历要求
    smt_lines = [f'S{i:02d}' for i in list(range(1, 50)) + [98, 99]]
    dip_lines = [f'D{i:02d}' for i in range(1, 23)]
    
    line_configs = []
    # 导图要求：SMT 每天按 23 小时排产
    for line in smt_lines:
        line_configs.append((line, f'SMT-{line}', 'SMT', '1010', 23.0, 1.0, None, None, 0, 1, '', f'SMT产线{line}'))
        
    # 导图要求：DIP 每天按 12 小时排产
    for line in dip_lines:
        line_configs.append((line, f'DIP-{line}', 'DIP', '1000', 12.0, 1.0, None, None, 1, 0, '', f'DIP产线{line}'))
    
    with get_db_connection() as conn:
        conn.executemany('''
            INSERT OR IGNORE INTO line_config (
                line_id, line_name, line_type, company_code,
                work_hours, capacity_ratio, min_size, max_size,
                support_dip, support_smt, capability_config, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', line_configs)
    
    logger.info("扩展数据初始化完成 (已应用 SMT:23h, DIP:12h 配置)")

if __name__ == '__main__':
    migrate_extend_tables()
    init_extend_data()
    print("数据库扩展完成！")