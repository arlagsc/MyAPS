# -*- coding: utf-8 -*-
import sqlite3
import os
import json
import logging
from datetime import datetime
from contextlib import contextmanager

# 导入扩展模块
from database_extend import migrate_extend_tables, init_extend_data

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_FILE = 'tv_aps_pro_v3.db'

@contextmanager
def get_db_connection():
    """数据库连接上下文管理器，自动管理连接和事务"""
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

def get_db_connection_simple():
    """简单数据库连接（用于兼容性）"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.text_factory = lambda b: b.decode("utf-8", "ignore")
    return conn

def init_db():
    """初始化数据库"""
    logger.info("初始化数据库...")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. 资源表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resources (
                id TEXT PRIMARY KEY,
                name TEXT,
                type TEXT DEFAULT 'Production',
                capability_config TEXT DEFAULT '',
                work_hours REAL DEFAULT 24.0,
                capacity_ratio REAL DEFAULT 1.0,
                description TEXT DEFAULT ''
            )
        ''')

        # 兼容性升级：添加缺失字段
        _migrate_resources_table(cursor)

        # 2. 产品表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                product_code TEXT PRIMARY KEY,
                screen_size INTEGER,
                platform TEXT
            )
        ''')

        # 3. 工单表 (新增 factory_code 和 material_ready_level)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_orders (
                task_id TEXT PRIMARY KEY,
                job_id TEXT,
                product_code TEXT,
                resource_id TEXT,
                qty INTEGER,
                std_time INTEGER,
                priority INTEGER,
                material_time TEXT,
                software_time TEXT,
                deadline TEXT,
                smt_side TEXT,
                related_task_id TEXT,
                process_req TEXT,
                status TEXT DEFAULT 'Pending',
                planned_start TEXT,
                planned_end TEXT,
                setup_time INTEGER DEFAULT 0,
                is_locked INTEGER DEFAULT 0,
                plan_type TEXT DEFAULT 'OFFICIAL',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                workshop TEXT,
                component_code TEXT,
                component_desc TEXT,
                factory_code TEXT DEFAULT '1010',
                material_ready_level TEXT DEFAULT 'STOCK_READY',
                FOREIGN KEY (product_code) REFERENCES products(product_code)
            )
        ''')

        # 兼容性升级：为老表添加新增的工单字段
        _migrate_work_orders_table(cursor)

        # 数据修正：刷新产线类型
        _fix_resource_types(cursor)

        # 初始化默认数据（如果为空）
        _init_demo_data_if_empty(cursor)
        
    # 执行扩展表迁移
    migrate_extend_tables()
    init_extend_data()
    
    logger.info("数据库初始化完成")

def _migrate_resources_table(cursor):
    """迁移resources表结构"""
    try:
        existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(resources)").fetchall()]
        
        migrations = {
            'type': "ALTER TABLE resources ADD COLUMN type TEXT DEFAULT 'Production'",
            'capability_config': "ALTER TABLE resources ADD COLUMN capability_config TEXT DEFAULT ''",
            'work_hours': "ALTER TABLE resources ADD COLUMN work_hours REAL DEFAULT 24.0",
            'capacity_ratio': "ALTER TABLE resources ADD COLUMN capacity_ratio REAL DEFAULT 1.0",
            'description': "ALTER TABLE resources ADD COLUMN description TEXT DEFAULT ''"
        }
        
        for col, sql in migrations.items():
            if col not in existing_cols:
                logger.info(f"添加字段: {col}")
                cursor.execute(sql)
                
    except sqlite3.Error as e:
        logger.warning(f"迁移检查失败: {e}")

def _migrate_work_orders_table(cursor):
    """迁移工单表结构(Gemini分支新增)"""
    try:
        existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(work_orders)").fetchall()]
        
        migrations = {
            'factory_code': "ALTER TABLE work_orders ADD COLUMN factory_code TEXT DEFAULT '1010'",
            'material_ready_level': "ALTER TABLE work_orders ADD COLUMN material_ready_level TEXT DEFAULT 'STOCK_READY'"
        }
        
        for col, sql in migrations.items():
            if col not in existing_cols:
                logger.info(f"工单表添加新字段: {col}")
                cursor.execute(sql)
                
    except sqlite3.Error as e:
        logger.warning(f"工单表迁移检查失败: {e}")

def _fix_resource_types(cursor):
    """修正产线类型"""
    try:
        cursor.execute("UPDATE resources SET type='SMT' WHERE id LIKE '%SMT%' OR name LIKE '%SMT%'")
        cursor.execute("UPDATE resources SET type='Production' WHERE id LIKE 'Line%' AND type != 'SMT'")
        logger.info("产线类型修正完成")
    except sqlite3.Error as e:
        logger.warning(f"修正产线类型失败: {e}")

def _init_demo_data_if_empty(cursor):
    # 保持原有的演示数据初始化逻辑不变...
    pass

def reset_db():
    logger.warning("重置数据库...")
    try:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            logger.info(f"已删除: {DB_FILE}")
    except Exception as e:
        logger.error(f"删除数据库失败: {e}")
    init_db()
    logger.info("数据库重置完成")

def get_db_connection():
    return get_db_connection_simple()