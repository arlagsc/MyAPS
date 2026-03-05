# -*- coding: utf-8 -*-
import random
import math
import logging
from datetime import datetime, timedelta
import sys
import os

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= 辅助函数：加载产品-产线映射 =================
def load_product_line_mapping():
    """从数据库加载产品-产线映射规则"""
    try:
        # 添加路径以便导入
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from database_extend import get_db_connection
        
        mapping = {}
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM product_line_mapping").fetchall()
            for row in rows:
                key = (str(row['company_code']), str(row['material_group']))
                if key not in mapping:
                    mapping[key] = []
                
                # 收集所有产线
                lines = []
                for i in range(1, 11):
                    line = row[f'line_id_{i}']
                    if line:
                        lines.append(line)
                
                mapping[key].append({
                    'lines': lines,
                    'range_condition': row['range_condition'],
                    'line_type': row['line_type']
                })
        
        logger.info(f"加载了 {len(mapping)} 条产品-产线映射规则")
        return mapping
    except Exception as e:
        logger.error(f"加载产品-产线映射失败: {e}")
        return {}


# ================= 基础调度父类 =================
class BaseScheduler:
    def __init__(self, orders, resources):
        self.orders = orders        # 任务列表
        self.resources = resources  # 资源列表
        # 建立资源空闲时间表
        self.resource_free_time = {r['id']: datetime.now() for r in resources}
        
        # 加载产品-产线映射规则
        self.product_line_mapping = load_product_line_mapping()
        
        logger.info(f"调度器初始化: {len(orders)} 个任务, {len(resources)} 个资源, {len(self.product_line_mapping)} 条映射规则")

    def calculate_makespan(self, schedule):
        """计算完工时间 (越小越好)"""
        if not schedule: 
            return 0
        return max(item['planned_end'] for item in schedule).timestamp()

    def is_smt_task(self, task):
        """判断是否为SMT任务"""
        prod_code = str(task.get('product_code', '') or '')
        task_name = str(task.get('task_id', '') or '')
        smt_side = str(task.get('smt_side', '') or '')
        
        return ('PCBA' in prod_code or 'PCBA' in task_name or 
                smt_side in ['A', 'B', 'A面', 'B面', 'Front', 'Back'])

    def find_valid_resources(self, task):
        """查找符合条件的产线资源 - 使用产品-产线映射规则"""
        prod_code = str(task.get('product_code', '') or '')
        job_id = str(task.get('job_id', '') or '')
        task_name = str(task.get('task_id', '') or '')
        is_smt = self.is_smt_task(task)
        
        # 尝试从产品编码提取物料组
        material_group = self._extract_material_group(prod_code)
        
        # 优先使用映射规则
        valid_res_ids = []
        
        # 遍历所有映射规则，查找匹配的
        for (company, mat_group), rules in self.product_line_mapping.items():
            # 匹配物料组 (更宽松的匹配)
            mat_group_str = str(mat_group)
            
            # 检查是否匹配
            matched = False
            if material_group and material_group in mat_group_str:
                matched = True
            elif material_group == mat_group_str:
                matched = True
            elif any(mg in prod_code for mg in [mat_group_str]):
                matched = True
            
            if matched:
                for rule in rules:
                    line_type = rule.get('line_type', '')
                    if is_smt and line_type == 'SMT':
                        valid_res_ids.extend(rule['lines'])
                    elif not is_smt and line_type != 'SMT':
                        valid_res_ids.extend(rule['lines'])
        
        # 兜底：使用类型匹配
        if not valid_res_ids:
            for r in self.resources:
                r_type = r.get('type', 'Production')
                
                if is_smt:
                    if r_type == 'SMT':
                        valid_res_ids.append(r['id'])
                else:
                    if r_type != 'SMT':
                        valid_res_ids.append(r['id'])
        
        # 最终兜底：所有产线
        if not valid_res_ids:
            logger.warning(f"任务 {task.get('task_id')} 找不到匹配产线，使用所有产线")
            valid_res_ids = [r['id'] for r in self.resources]
        
        # 去重
        valid_res_ids = list(set(valid_res_ids))
        
        return valid_res_ids

    def _extract_material_group(self, product_code):
        """从产品编码提取物料组"""
        import re
        pc = str(product_code)
        
        # 尝试提取数字
        match = re.search(r'(\d+)', pc)
        if match:
            num = match.group(1)
            # TV-55 -> 55 -> 尝试映射到物料组
            # 建立常见映射
            mappings = {
                '32': '511', '40': '511', '42': '511', '50': '513', 
                '55': '515', '65': '514', '75': '514', '85': '535'
            }
            if num in mappings:
                return mappings[num]
            return num
        
        # PCBA 类型
        if 'Advanced' in pc or 'Complex' in pc:
            return '515'
        if 'Simple' in pc:
            return '513'
        
        return ''

    def find_best_resource(self, valid_res_ids, free_time, task):
        """负载均衡：选择最优产线"""
        if not valid_res_ids:
            return None
            
        best_res = min(valid_res_ids, key=lambda rid: free_time.get(rid, datetime.min))
        return best_res

    def calculate_task_timing(self, task, resource_id, free_time):
        """计算任务时间安排"""
        try:
            std_time = float(task.get('std_time', 60) or 60)
        except (ValueError, TypeError):
            logger.warning(f"任务 {task.get('task_id')} std_time 异常，使用默认值60")
            std_time = 60
        
        # 获取各种约束时间
        now = datetime.now()
        machine_free_time = free_time.get(resource_id, now)
        
        # 物料时间约束
        mat_time = task.get('material_time')
        if mat_time:
            try:
                mat_time = datetime.strptime(str(mat_time), '%Y-%m-%d %H:%M')
            except ValueError:
                mat_time = now
        else:
            mat_time = now
        
        # 软件时间约束
        soft_time = task.get('software_time')
        if soft_time:
            try:
                soft_time = datetime.strptime(str(soft_time), '%Y-%m-%d %H:%M')
            except ValueError:
                soft_time = now
        else:
            soft_time = now
        
        # 约束时间：必须同时满足机器空闲、物料到达、软件发布
        start_time = max(now, machine_free_time, mat_time, soft_time)
        end_time = start_time + timedelta(minutes=std_time)
        
        # 计算延迟原因
        delay_reason = ""
        if start_time == mat_time and mat_time > machine_free_time:
            delay_reason = "等料"
        elif start_time == soft_time and soft_time > machine_free_time:
            delay_reason = "等软件"
        
        return {
            'start_time': start_time,
            'end_time': end_time,
            'std_time': std_time,
            'delay_reason': delay_reason
        }

    def decode_schedule(self, task_sequence):
        """解码器：将任务顺序转化为具体时间表 (核心逻辑)"""
        free_time = self.resource_free_time.copy()
        schedule_result = []
        failed_tasks = []

        for task_id in task_sequence:
            try:
                # 找到任务对象
                task = next((t for t in self.orders if t['task_id'] == task_id), None)
                if not task:
                    logger.warning(f"找不到任务: {task_id}")
                    failed_tasks.append(task_id)
                    continue
                
                res_id = task.get('resource_id')
                
                # 自动分配资源
                if res_id == 'AUTO' or res_id is None or res_id == '':
                    valid_res_ids = self.find_valid_resources(task)
                    res_id = self.find_best_resource(valid_res_ids, free_time, task)
                    
                    if not res_id:
                        logger.error(f"无法分配资源给任务: {task_id}")
                        failed_tasks.append(task_id)
                        continue
                
                # 再次检查资源有效性
                if res_id not in free_time:
                    logger.warning(f"资源 {res_id} 不存在，使用第一个可用资源")
                    res_id = list(free_time.keys())[0] if free_time else None
                    if not res_id:
                        continue
                
                # 计算时间安排
                timing = self.calculate_task_timing(task, res_id, free_time)
                
                # 更新资源空闲时间
                free_time[res_id] = timing['end_time']
                
                schedule_result.append({
                    'task_id': task_id,
                    'planned_start': timing['start_time'],
                    'planned_end': timing['end_time'],
                    'resource_id': res_id,
                    'delay_reason': timing['delay_reason']
                })
                
            except Exception as e:
                logger.error(f"处理任务 {task_id} 时出错: {str(e)}")
                failed_tasks.append(task_id)
                continue
        
        if failed_tasks:
            logger.warning(f"失败任务数: {len(failed_tasks)}")
        
        logger.info(f"排产完成: 成功 {len(schedule_result)}, 失败 {len(failed_tasks)}")
        return schedule_result


# ================= 1. 贪婪算法 =================
class GreedyScheduler(BaseScheduler):
    """贪心算法：按标准工时排序"""
    def run(self):
        logger.info("使用贪心算法进行排产")
        # 按优先级和工时排序
        sorted_orders = sorted(
            self.orders, 
            key=lambda x: (x.get('priority', 0), x.get('std_time', 0))
        )
        task_sequence = [o['task_id'] for o in sorted_orders]
        return self.decode_schedule(task_sequence)


# ================= 2. 模拟退火算法 =================
class SimulatedAnnealingScheduler(BaseScheduler):
    """模拟退火算法"""
    def run(self, initial_temp=1000, cooling_rate=0.95, min_temp=1, max_iterations=1000):
        logger.info(f"使用模拟退火算法进行排产 (初始温度={initial_temp})")
        
        # 初始化随机序列
        current_seq = [o['task_id'] for o in self.orders]
        random.shuffle(current_seq)
        
        current_schedule = self.decode_schedule(current_seq)
        current_fitness = self.calculate_makespan(current_schedule)
        
        best_seq = current_seq[:]
        best_fitness = current_fitness
        
        temp = initial_temp
        iteration = 0
        
        while temp > min_temp and iteration < max_iterations:
            iteration += 1
            
            # 随机交换两个任务
            new_seq = current_seq[:]
            idx1, idx2 = random.sample(range(len(new_seq)), 2)
            new_seq[idx1], new_seq[idx2] = new_seq[idx2], new_seq[idx1]
            
            new_schedule = self.decode_schedule(new_seq)
            new_fitness = self.calculate_makespan(new_schedule)
            
            # 接受准则
            if new_fitness < current_fitness:
                accept = True
            else:
                delta = new_fitness - current_fitness
                probability = math.exp(-delta / temp)
                accept = random.random() < probability
            
            if accept:
                current_seq = new_seq
                current_fitness = new_fitness
                if current_fitness < best_fitness:
                    best_fitness = current_fitness
                    best_seq = current_seq[:]
            
            temp *= cooling_rate
        
        logger.info(f"模拟退火完成: 迭代 {iteration} 次, 最终适应度 {best_fitness}")
        return self.decode_schedule(best_seq)


# ================= 3. 遗传算法 =================
class GeneticScheduler(BaseScheduler):
    """遗传算法"""
    def run(self, pop_size=50, generations=50, mutation_rate=0.1):
        logger.info(f"使用遗传算法进行排产 (种群={pop_size}, 迭代={generations})")
        
        base_ids = [o['task_id'] for o in self.orders]
        
        # 初始化种群
        population = []
        for _ in range(pop_size):
            ind = base_ids[:]
            random.shuffle(ind)
            population.append(ind)
        
        for gen in range(generations):
            # 评估适应度
            scored_pop = []
            for ind in population:
                sched = self.decode_schedule(ind)
                score = self.calculate_makespan(sched)
                scored_pop.append((score, ind))
            
            # 排序
            scored_pop.sort(key=lambda x: x[0])
            
            # 精英保留
            new_pop = [x[1] for x in scored_pop[:max(1, int(pop_size * 0.2))]]
            
            # 生成新个体
            while len(new_pop) < pop_size:
                # 选择父代
                parent = random.choice(scored_pop[:max(1, int(pop_size * 0.5))])[1]
                child = parent[:]
                
                # 变异
                if random.random() < mutation_rate:
                    i1, i2 = random.sample(range(len(child)), 2)
                    child[i1], child[i2] = child[i2], child[i1]
                
                new_pop.append(child)
            
            population = new_pop
            
            if gen % 10 == 0:
                logger.info(f"遗传算法迭代 {gen}/{generations}, 最优适应度: {scored_pop[0][0]}")
        
        best_ind = population[0]
        logger.info(f"遗传算法完成")
        return self.decode_schedule(best_ind)


# ================= 4. 优先级算法 =================
class PriorityScheduler(BaseScheduler):
    """优先级调度算法：考虑紧急程度和交付时间"""
    def run(self):
        logger.info("使用优先级算法进行排产")
        
        # 按优先级（数字越小越优先）、交付时间排序
        sorted_orders = sorted(
            self.orders,
            key=lambda x: (
                x.get('priority', 999),
                x.get('deadline', '9999-12-31')
            )
        )
        task_sequence = [o['task_id'] for o in sorted_orders]
        return self.decode_schedule(task_sequence)


# ================= 5. 最短作业优先算法 =================
class SJFScheduler(BaseScheduler):
    """最短作业优先算法"""
    def run(self):
        logger.info("使用SJF算法进行排产")
        sorted_orders = sorted(
            self.orders,
            key=lambda x: float(x.get('std_time', 0) or 0)
        )
        task_sequence = [o['task_id'] for o in sorted_orders]
        return self.decode_schedule(task_sequence)
