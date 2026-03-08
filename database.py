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

        # 3. 工单表
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
                FOREIGN KEY (product_code) REFERENCES products(product_code)
            )
        ''')

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

def _fix_resource_types(cursor):
    """修正产线类型"""
    try:
        # SMT产线
        cursor.execute("UPDATE resources SET type='SMT' WHERE id LIKE '%SMT%' OR name LIKE '%SMT%'")
        # 组装产线
        cursor.execute("UPDATE resources SET type='Production' WHERE id LIKE 'Line%' AND type != 'SMT'")
        logger.info("产线类型修正完成")
    except sqlite3.Error as e:
        logger.warning(f"修正产线类型失败: {e}")

def _init_demo_data_if_empty(cursor):
    """初始化演示数据"""
    try:
        check = cursor.execute("SELECT count(*) FROM resources").fetchone()[0]
    except:
        check = 0

    if check > 0:
        logger.info("数据库已有数据，跳过初始化")
        return
    
    logger.info("初始化演示数据...")
    
    # A. 资源数据
    resources_data = [
        ('Line-01', 'Line-01 小尺寸线(32-50)', 'Production', '{"min_size": 32, "max_size": 50}'),
        ('Line-02', 'Line-02 大尺寸线(50-85)', 'Production', '{"min_size": 50, "max_size": 85}'),
        ('Line-03', 'Line-03 万能组装线(32-85)', 'Production', '{"min_size": 32, "max_size": 85}'),
        ('Line-04', 'Line-04 备用组装线(32-85)', 'Production', '{"min_size": 32, "max_size": 85}'),
        ('Line-05', 'Line-05 备用组装线(32-85)', 'Production', '{"min_size": 32, "max_size": 85}'),
        ('Line-06', 'Line-06 大尺寸组装线(50-85)', 'Production', '{"min_size": 50, "max_size": 85}'),
        ('Line-07', 'Line-07 小尺寸组装线(32-50)', 'Production', '{"min_size": 32, "max_size": 50}'),
        ('Line-08', 'Line-08 大尺寸组装线(50-85)', 'Production', '{"min_size": 50, "max_size": 85}'),
        ('Line-09', 'Line-09 万能组装线(32-85)', 'Production', '{"min_size": 32, "max_size": 85}'),
        ('Line-10', 'Line-10 万能组装线(32-85)', 'Production', '{"min_size": 32, "max_size": 85}'),
        ('SMT-01', 'SMT-01 SMT线(无DIP)', 'SMT', '{"support_dip": false}'),
        ('SMT-02', 'SMT-02 SMT线(含DIP)', 'SMT', '{"support_dip": true}'),
        ('SMT-03', 'SMT-03 高速SMT线(无DIP)', 'SMT', '{"support_dip": false}'),
        ('SMT-04', 'SMT-04 多功能SMT线(含DIP)', 'SMT', '{"support_dip": true}'),
        ('SMT-05', 'SMT-05 多功能SMT线(含DIP)', 'SMT', '{"support_dip": true}'),
    ]
    cursor.executemany(
        'INSERT OR IGNORE INTO resources (id, name, type, capability_config) VALUES (?,?,?,?)', 
        resources_data
    )

    # B. 产品数据
    products_data = [
        ('TV-32', 32, 'MTK'), 
        ('TV-55', 55, 'MTK'),
        ('TV-65', 65, 'MTK'),
        ('TV-75', 75, 'RTK'),
        ('TV-85', 85, 'MTK'),
        ('TV-42', 42, 'RTK'),
        ('TV-50', 50, 'RTK'),
        ('TV-40', 40, 'RTK'),
        ('PCBA-Advanced', 0, None),
        ('PCBA-Simple', 0, None), 
        ('PCBA-Complex', 0, None)
    ]
    cursor.executemany('INSERT OR IGNORE INTO products VALUES (?,?,?)', products_data)

    # C. 工单数据
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    tomorrow = (datetime.now().replace(hour=9, minute=0) + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    day_after = (datetime.now().replace(hour=14, minute=0) + __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
    
    orders = [
        ('WO-Normal-01', 'JOB-A', 'TV-32', 'AUTO', 100, 120, 1, '', '', 'A', 'NORMAL', 'OFFICIAL'),
        ('WO-WaitMat-01', 'JOB-B', 'TV-75', 'AUTO', 100, 200, 1, tomorrow, '', '', 'NORMAL', 'OFFICIAL'),
        ('WO-WaitSoft-01', 'JOB-C', 'TV-32', 'AUTO', 100, 100, 1, '', day_after, '', 'NORMAL', 'OFFICIAL'),
        ('WO-WaitBoth-01', 'JOB-D', 'TV-55', 'AUTO', 100, 150, 1, tomorrow, day_after, '', 'NORMAL', 'OFFICIAL'),
        ('WO-Urgent-01', 'JOB-E', 'TV-42', 'AUTO', 50, 80, 10, '', '', '', 'NORMAL', 'OFFICIAL'),
        ('WO-Normal-02', 'JOB-F', 'TV-65', 'AUTO', 80, 130, 2, '', '', '', 'NORMAL', 'OFFICIAL'),
        ('WO-PCBA-01', 'JOB-J', 'PCBA-Advanced', 'AUTO', 200, 180, 1, '', '', 'A', 'NORMAL', 'OFFICIAL'),
        ('WO-PCBA-02', 'JOB-K', 'PCBA-Simple', 'AUTO', 150, 120, 1, '', '', 'B', 'NORMAL', 'OFFICIAL'),
    ]
    
    cursor.executemany('''
        INSERT OR IGNORE INTO work_orders (
            task_id, job_id, product_code, resource_id, qty, std_time, priority, 
            material_time, software_time, smt_side, process_req, plan_type
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    ''', orders)
    
    logger.info("演示数据初始化完成")

def reset_db():
    """重置数据库"""
    logger.warning("重置数据库...")
    try:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            logger.info(f"已删除: {DB_FILE}")
    except Exception as e:
        logger.error(f"删除数据库失败: {e}")
    init_db()
    logger.info("数据库重置完成")

# 保持向后兼容
def get_db_connection():
    return get_db_connection_simple()
