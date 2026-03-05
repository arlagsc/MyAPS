# -*- coding: utf-8 -*-
import pandas as pd
import json
import logging
from datetime import datetime, timedelta
from database import get_db_connection

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= 辅助函数 =================
def find_best_resource(task_row, resources_df, machine_state, start_base):
    """根据任务要求找到最佳产线资源"""
    try:
        smt_side = str(task_row.get('smt_side', '') or '')
        req_type = 'SMT' if smt_side in ['A', 'B', 'A面', 'B面', 'Front', 'Back'] or 'PCBA' in str(task_row.get('product_code', '')) else 'Production'
        
        # 屏幕尺寸约束
        screen_size = task_row.get('screen_size', 0)
        req_dip = (task_row.get('process_req', '') == 'DIP_REQUIRED')
        
        candidates = []
        for _, res in resources_df.iterrows():
            r_type = str(res.get('type', 'Production'))
            
            # 类型筛选
            if req_type == 'SMT' and r_type != 'SMT':
                continue
            if req_type == 'Production' and r_type == 'SMT':
                continue
            
            # 能力配置检查
            try:
                config = json.loads(res['capability_config']) if res.get('capability_config') else {}
            except:
                config = {}
            
            if req_type == 'Production' and screen_size > 0:
                min_size = config.get('min_size', 0)
                max_size = config.get('max_size', 999)
                if not (min_size <= screen_size <= max_size):
                    continue
                    
            if req_type == 'SMT' and req_dip and not config.get('support_dip', False):
                continue
                
            candidates.append(res['id'])
        
        if not candidates:
            return None, f"无合适产线 (类型:{req_type}, 尺寸:{screen_size})"
        
        # 选择最早空闲的产线
        best_res = None
        min_finish_time = None
        for res_id in candidates:
            finish_time = machine_state.get(res_id, start_base)
            if min_finish_time is None or finish_time < min_finish_time:
                min_finish_time = finish_time
                best_res = res_id
                
        return best_res, None
        
    except Exception as e:
        logger.error(f"资源匹配错误: {e}")
        return None, str(e)

# ================= 核心排产逻辑 =================
def run_advanced_scheduling(mode='OFFICIAL'):
    """
    执行高级排产调度
    
    Args:
        mode: 'OFFICIAL' 正式排产, 'SIMULATION' 模拟排产
    
    Returns:
        str: 排产结果消息
    """
    logger.info(f"开始排产... 模式: {mode}")
    
    try:
        conn = get_db_connection()
        
        # 查询条件
        if mode == 'SIMULATION':
            where_clause = "status != 'Done'"
        else:
            where_clause = "plan_type = 'OFFICIAL' AND status != 'Done'"
        
        sql = f"""
            SELECT w.*, p.screen_size 
            FROM work_orders w 
            LEFT JOIN products p ON w.product_code = p.product_code
            WHERE {where_clause}
        """
        df_orders = pd.read_sql(sql, conn)
        df_resources = pd.read_sql("SELECT * FROM resources", conn)
        conn.close()
        
        if df_orders.empty:
            logger.info("没有待排产任务")
            return "没有可排产的任务"
        
        logger.info(f"待排产任务: {len(df_orders)} 个, 资源: {len(df_resources)} 条")
        
        # 初始化机器状态（考虑锁定任务）
        machine_state = {} 
        locked_df = df_orders[df_orders.get('is_locked', 0) == 1]
        for _, row in locked_df.iterrows():
            if row.get('planned_end'):
                try:
                    p_end = datetime.strptime(str(row['planned_end']), '%Y-%m-%d %H:%M')
                    rid = row.get('resource_id')
                    if rid:
                        machine_state[rid] = max(machine_state.get(rid, datetime.min), p_end)
                except Exception as e:
                    logger.warning(f"解析锁定任务时间失败: {e}")
        
        # 基准时间
        start_base = datetime.now().replace(minute=0, second=0, microsecond=0)
        
        # 待排任务筛选
        pending_df = df_orders[df_orders.get('is_locked', 0) != 1].copy()
        
        # 排序：先处理模拟单，再按优先级
        pending_df['sim_score'] = pending_df.get('plan_type', 'OFFICIAL').apply(lambda x: 100 if x == 'SIMULATION' else 0)
        pending_df = pending_df.sort_values(
            by=['sim_score', 'priority', 'job_id'],
            ascending=[False, True, True]
        )
        
        results = []
        skipped_tasks = []

        for _, row in pending_df.iterrows():
            task_id = row.get('task_id')
            target_res = row.get('resource_id')
            
            # 自动选线
            if target_res in ['AUTO', None, '']:
                selected_res, error = find_best_resource(row, df_resources, machine_state, start_base)
                if not selected_res:
                    skipped_tasks.append((f"匹配失败: {error}", task_id))
                    logger.warning(f"任务 {task_id} 匹配失败: {error}")
                    continue
                target_res = selected_res
            
            # 获取约束时间
            machine_free_time = machine_state.get(target_res, start_base)
            
            # 物料时间
            mat_time = start_base
            if row.get('material_time'):
                try:
                    mat_time = datetime.strptime(str(row['material_time']), '%Y-%m-%d %H:%M')
                except:
                    pass
            
            # 软件时间
            soft_time = start_base
            if row.get('software_time'):
                try:
                    soft_time = datetime.strptime(str(row['software_time']), '%Y-%m-%d %H:%M')
                except:
                    pass
            
            # 计算开始时间（取最大）
            final_start = max(machine_free_time, mat_time, soft_time)
            
            # 延迟原因
            delay_reason = ""
            if final_start == mat_time and mat_time > machine_free_time:
                delay_reason = "等料"
            elif final_start == soft_time and soft_time > machine_free_time:
                delay_reason = "等软件"
            
            # 计算结束时间
            try:
                duration = int(row.get('std_time', 60) or 60)
            except:
                duration = 60
                
            final_end = final_start + timedelta(minutes=duration)
            
            # 更新状态
            machine_state[target_res] = final_end
            
            # 状态文本
            status_text = 'Scheduled' + (f" ({delay_reason})" if delay_reason else "")
            
            results.append((
                final_start.strftime('%Y-%m-%d %H:%M'),
                final_end.strftime('%Y-%m-%d %H:%M'),
                target_res,
                status_text,
                task_id
            ))

        # 回写数据库
        if results:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.executemany('''
                UPDATE work_orders 
                SET planned_start = ?, planned_end = ?, resource_id = ?, status = ?
                WHERE task_id = ?
            ''', results)
            
            # 更新失败任务状态
            if skipped_tasks:
                for _, task_id in skipped_tasks:
                    cursor.execute(
                        "UPDATE work_orders SET status = ? WHERE task_id = ?",
                        ('匹配失败', task_id)
                    )
            
            conn.commit()
            conn.close()
        
        success_count = len(results)
        fail_count = len(skipped_tasks)
        
        msg = f"排产完成: 成功 {success_count} 个"
        if fail_count > 0:
            msg += f", 失败 {fail_count} 个"
        
        logger.info(msg)
        return msg
        
    except Exception as e:
        logger.error(f"排产执行失败: {e}")
        import traceback
        traceback.print_exc()
        return f"排产失败: {str(e)}"
