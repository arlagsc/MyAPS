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
    """从数据库加载产品-产线映射规则 (兜底配置)"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from database_extend import get_db_connection
        
        mapping = {}
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM product_line_mapping").fetchall()
            for row in rows:
                key = (str(row['company_code']), str(row['material_group']))
                if key not in mapping:
                    mapping[key] = []
                
                lines = [row[f'line_id_{i}'] for i in range(1, 11) if row[f'line_id_{i}']]
                mapping[key].append({
                    'lines': lines,
                    'range_condition': row['range_condition'],
                    'line_type': row['line_type']
                })
        return mapping
    except Exception as e:
        logger.error(f"加载产品-产线映射失败: {e}")
        return {}

##防抖判定规则
def apply_debounce_rules(order, current_calc_start, schedule_baseline):
    """
    【核心防抖引擎】
    输入：订单原数据, 算法初步算出的开始时间, 本次排产的基准时间(T+1)
    输出：(修正后的开始时间, 是否严重违规)
    """
    orig_start_str = order.get('planned_start')
    # 如果是第一次排产（没有原计划），直接放行
    if not orig_start_str or str(orig_start_str) in ('None', 'null', ''):
        return current_calc_start, False
    
    try:
        orig_start = datetime.strptime(str(orig_start_str)[:16].replace('T', ' '), '%Y-%m-%d %H:%M')
        # 计算原计划属于第几天（相对 T+1）
        days_diff = (orig_start.date() - schedule_baseline.date()).days
        
        min_start, max_start = None, None
        
        # 规则 1：第 3-7 天，调整不可超过 3 天
        if 3 <= days_diff <= 7:
            min_start = orig_start - timedelta(days=3)
            max_start = orig_start + timedelta(days=3)
        # 规则 2：第 8-15 天，调整不可超过 7 天
        elif 8 <= days_diff <= 15:
            min_start = orig_start - timedelta(days=7)
            max_start = orig_start + timedelta(days=7)
        else:
            return current_calc_start, False # 不在防抖保护区间（比如 0-2天已被冻结）
            
        # --- 强制约束判定 ---
        if current_calc_start < min_start:
            # 算得太早了！强行压制，不允许过度提前，以免打乱近期物料计划
            return min_start, False
        elif current_calc_start > max_start:
            # 算得太晚了！(产能实在排不开被挤爆了)，此时只能违背约束，但必须向上层报警！
            return current_calc_start, True
        else:
            # 在合理浮动区间内，完美放行
            return current_calc_start, False
            
    except Exception:
        return current_calc_start, False
    
# ================= 基础调度父类 =================
class BaseScheduler:    
    def __init__(self, orders, resources):
        self.orders = orders
        self.resources = resources
        
        # [核心修改]：T+1 排产逻辑，将所有产线的初始可用时间设为明天 08:00
        tomorrow = datetime.now() + timedelta(days=1)
        schedule_start = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
        
        # === 【紧急修复】将基准时间存入 self，供防抖引擎调用 ===
        self.schedule_start = schedule_start 
        # ===================================================
        
        self.resource_free_time = {r['id']: schedule_start for r in resources}
        self.product_line_mapping = load_product_line_mapping()
        self.scheduled_timings = {}

    # =========================================================
    # === 【紧急补全】产线筛选引擎 (包含 PRD 强弱约束规则) ===
    # =========================================================
    def get_allowed_resources(self, order):
        allowed = []
        workshop = order.get('workshop')
        product_code = order.get('product_code')
        smt_side = order.get('smt_side', '-')

        for r in self.resources:
            # 1. 基础约束：车间必须匹配 (SMT单找SMT线，DIP找DIP线)
            if workshop and r.get('workshop') and r['workshop'] != workshop:
                continue
                
            # 2. 强绑定约束：检查产品是否有专属绑定的产线
            if product_code in self.product_line_mapping:
                if r['id'] not in self.product_line_mapping[product_code]:
                    continue
                    
            # 3. 工艺约束 (PRD落地)：S27-S30 专做 B 面
            if r['id'] in ['S27', 'S28', 'S29', 'S30']:
                if smt_side not in ['B', 'B面', 'Back']:
                    continue
                    
            allowed.append(r)
            
        return allowed
    # =========================================================

    def calculate_makespan(self, schedule):
        """计算完工时间 (越小越好)"""
        if not schedule: 
            return 0
        return max(item['planned_end'] for item in schedule).timestamp()

    def _extract_material_group(self, task):
        """提取物料组"""
        product_code = str(task.get('product_code', ''))
        import re
        match = re.search(r'(\d+)', product_code)
        if match:
            num = match.group(1)
            mappings = {'32': '511', '40': '511', '42': '511', '50': '513', '55': '515', '65': '514', '75': '514'}
            return mappings.get(num, num)
        return ''

    def _evaluate_smt_rules(self, task, material_group):
        """
        [PRD 核心规则] SMT 设备限制规则解析
        """
        smt_side = task.get('smt_side', '')
        qty = int(task.get('qty', 0))
        company = task.get('company_code', '')
        desc = str(task.get('component_desc', ''))

        # 规则 4: 27, 28, 29, 30 为B面优先排产线体
        if smt_side in ['B', 'B面', 'Back']:
            return ['S27', 'S28', 'S29', 'S30']

        # 规则 6: 10, 13, 14做电源板，工艺不同需要锁定线体
        if '电源' in desc or material_group == '514':
            return ['S10', 'S13', 'S14']

        # 规则 3: 5070工厂订单9线专用
        if company == '5070':
            return ['S09']

        # 规则 1: 1, 2, 3, 5 为优先排产AV附板(非515)及515且QTY<=5000
        is_av = 'AV' in desc
        if (is_av and not str(product_code).startswith('515')) or (material_group == '515' and qty <= 5000):
            return ['S01', 'S02', 'S03', 'S05']

        # 规则 2: 4, 6, 8, 9 晶显专用
        if '晶显' in desc or material_group == '534':
            return ['S04', 'S06', 'S08', 'S09']

        # 规则 5: 11, 12, 16, 17, 18, 10线体优先排产TV 511按键板, 513, 515小单
        if material_group in ['511', '513', '515'] and qty <= 3000:
            return ['S11', 'S12', 'S16', 'S17', 'S18', 'S10']

        # 规则 7: 515的A面及TV的515排剩余线体 (此处以S19-S26模拟剩余线体)
        if material_group == '515' and smt_side in ['A', 'A面']:
            return ['S19', 'S20', 'S21', 'S22', 'S23', 'S24', 'S25', 'S26']

        return []

    def _evaluate_dip_rules(self, task, material_group):
        """
        [PRD 核心规则] DIP 设备限制规则解析
        """
        desc = str(task.get('component_desc', ''))
        
        # 规则 1: 514电源板专线
        if '电源' in desc or material_group == '514':
            if '大功率' in desc: return ['D18']  # 手插大功率
            elif '小功率' in desc: return ['D20'] # 自动小功率
            else: return ['D21', 'D22']          # 自动中功率

        # 规则 2: TV 515 解码板线
        if '解码' in desc or material_group == '515':
            if '手动' in desc: return ['D12']
            else: return ['D01', 'D02']

        # 规则 3: TV 511 小板线
        if material_group == '511':
            return ['D17']

        # 规则 4: 534 晶显专线
        if '晶显' in desc or material_group == '534':
            return ['D16']

        # 规则 5: AV 自动化/手动线
        if 'AV' in desc:
            if '自动' in desc: return ['D03', 'D04', 'D05', 'D06', 'D07', 'D09']
            else: return ['D08', 'D10', 'D11', 'D14']

        return []

    def find_valid_resources(self, task):
        """查找符合条件的产线资源 (融合硬约束与软映射)"""
        workshop = task.get('workshop', 'SMT')
        material_group = self._extract_material_group(task)
        
        valid_res_ids = []

        # 1. 尝试使用硬编码 PRD 规则
        if workshop == 'SMT':
            valid_res_ids = self._evaluate_smt_rules(task, material_group)
        elif workshop == 'DIP':
            valid_res_ids = self._evaluate_dip_rules(task, material_group)

        # 2. 如果无硬约束命中，使用数据库动态映射
        if not valid_res_ids:
            company = task.get('company_code', '1010')
            rules = self.product_line_mapping.get((company, material_group), [])
            for rule in rules:
                if rule.get('line_type') == workshop:
                    valid_res_ids.extend(rule['lines'])

        # 3. 终极兜底：同车间的所有产线
        if not valid_res_ids:
            for r in self.resources:
                if r.get('type') == workshop:
                    valid_res_ids.append(r['id'])

        return list(set(valid_res_ids))

    def find_best_resource(self, valid_res_ids, free_time):
        """负载均衡：选择最早空闲的优选产线"""
        if not valid_res_ids:
            return None
        return min(valid_res_ids, key=lambda rid: free_time.get(rid, datetime.min))

    def calculate_task_timing(self, task, resource_id, free_time):
        """
        [PRD 核心规则] 时间与联动计算 
        包含 B->A 面间距，SMT->DIP 间距
        """
        std_time = float(task.get('std_time', 60) or 60)
        now = datetime.now()
        
        machine_free_time = free_time.get(resource_id, now)
        
        # --- 强健的时间解析逻辑 (防崩溃) ---
        def parse_time(t_str):
            if not t_str or str(t_str).strip() in ['', '0', 'None']:
                return now
            try:
                # 截取前16位，兼容各种日期格式
                return datetime.strptime(str(t_str).strip()[:16], '%Y-%m-%d %H:%M')
            except Exception:
                return now

        mat_time = parse_time(task.get('material_time'))
        soft_time = parse_time(task.get('software_time'))
        
        # 基础约束
        start_time = max(now, machine_free_time, mat_time, soft_time)
        
        # 【联动约束解析】
        depends_on = task.get('depends_on')
        if depends_on and depends_on in self.scheduled_timings:
            parent_end = self.scheduled_timings[depends_on]['end_time']
            workshop = task.get('workshop', 'SMT')
            side = task.get('side', '')
            priority = int(task.get('priority', 5))

            min_gap_mins = 0
            # DIP排产SMT必须有产出，正常间隔24h，紧急8h
            if workshop == 'DIP':
                min_gap_mins = 8 * 60 if priority <= 3 else 24 * 60
            # B面排产后，A面可立即或随后上
            elif side in ['A', 'A面']:
                min_gap_mins = 0 
                
            # 更新最早开始时间
            start_time = max(start_time, parent_end + timedelta(minutes=min_gap_mins))

        end_time = start_time + timedelta(minutes=std_time)
        
        delay_reason = "正常"
        if start_time == mat_time and mat_time > machine_free_time:
            delay_reason = "等料"
        elif depends_on and start_time == parent_end + timedelta(minutes=min_gap_mins):
            delay_reason = "等前置工序"
            
        return {
            'start_time': start_time,
            'end_time': end_time,
            'std_time': std_time,
            'delay_reason': delay_reason
        }
    
    def decode_schedule(self, task_sequence):
        """解码器：转化为具体时间表"""
        free_time = self.resource_free_time.copy()
        schedule_result = []
        self.scheduled_timings.clear()

        for task_id in task_sequence:
            task = next((t for t in self.orders if t['task_id'] == task_id), None)
            if not task: continue
            
            res_id = task.get('resource_id')
            if res_id in ['AUTO', None, '']:
                valid_res_ids = self.find_valid_resources(task)
                res_id = self.find_best_resource(valid_res_ids, free_time)
                if not res_id: continue
            
            timing = self.calculate_task_timing(task, res_id, free_time)
            
            free_time[res_id] = timing['end_time']
            self.scheduled_timings[task_id] = timing  # 记录供后置任务查询依赖
            
            schedule_result.append({
                'task_id': task_id,
                'planned_start': timing['start_time'],
                'planned_end': timing['end_time'],
                'resource_id': res_id,
                'delay_reason': timing['delay_reason']
            })
            
        return schedule_result

# ================= 后续算法类 (Greedy, SA, GA 等) 保持原样 =================
class GreedyScheduler(BaseScheduler):
    def run(self):
        schedule_result = []
        # 按优先级和交期初步排序
        sorted_orders = sorted(self.orders, key=lambda x: (x.get('priority', 5), x.get('deadline', '9999-12-31')))
        
        for order in sorted_orders:
            # 1. 处理级联依赖 (B面 -> A面 -> DIP)
            dep_end_time = self.schedule_start
            if order.get('depends_on'):
                dep_id = order['depends_on']
                if dep_id in self.scheduled_timings:
                    dep_end_time = self.scheduled_timings[dep_id]
            
            # 2. 筛选可用产线
            allowed_resources = self.get_allowed_resources(order)
            if not allowed_resources: continue
                
            best_resource = None
            best_start = None
            best_end = None
            is_violated = False
            
            # 3. 寻找最优产线并【过防抖引擎】
            for res in allowed_resources:
                res_id = res['id']
                calc_start = max(self.resource_free_time.get(res_id, self.schedule_start), dep_end_time)
                
                # ==== 调用防抖引擎 ====
                adjusted_start, violated = apply_debounce_rules(order, calc_start, self.schedule_start)
                
                if best_start is None or adjusted_start < best_start:
                    best_start = adjusted_start
                    best_resource = res_id
                    is_violated = violated
                    
            # 4. 锁定排产结果
            if best_resource:
                std_time_mins = float(order.get('std_time', 60))
                best_end = best_start + timedelta(minutes=std_time_mins)
                
                self.resource_free_time[best_resource] = best_end
                self.scheduled_timings[order['task_id']] = best_end
                
                schedule_result.append({
                    'task_id': order['task_id'],
                    'resource_id': best_resource,
                    'planned_start': best_start,
                    'planned_end': best_end,
                    'violated': is_violated # 传出防抖违规报警
                })
                
        return schedule_result

class SimulatedAnnealingScheduler(BaseScheduler):
    def run(self, initial_temp=1000, cooling_rate=0.95, min_temp=1, max_iterations=1000):
        current_seq = [o['task_id'] for o in self.orders]
        random.shuffle(current_seq)
        current_schedule = self.decode_schedule(current_seq)
        current_fitness = self.calculate_makespan(current_schedule)
        best_seq, best_fitness = current_seq[:], current_fitness
        temp, iteration = initial_temp, 0
        
        while temp > min_temp and iteration < max_iterations:
            iteration += 1
            new_seq = current_seq[:]
            idx1, idx2 = random.sample(range(len(new_seq)), 2)
            new_seq[idx1], new_seq[idx2] = new_seq[idx2], new_seq[idx1]
            new_schedule = self.decode_schedule(new_seq)
            new_fitness = self.calculate_makespan(new_schedule)
            
            if new_fitness < current_fitness or random.random() < math.exp(-(new_fitness - current_fitness) / temp):
                current_seq, current_fitness = new_seq, new_fitness
                if current_fitness < best_fitness:
                    best_fitness, best_seq = current_fitness, current_seq[:]
            temp *= cooling_rate
        return self.decode_schedule(best_seq)

class GeneticScheduler(BaseScheduler):
    def run(self, pop_size=50, generations=50, mutation_rate=0.1):
        base_ids = [o['task_id'] for o in self.orders]
        population = [random.sample(base_ids, len(base_ids)) for _ in range(pop_size)]
        
        for gen in range(generations):
            scored_pop = sorted([(self.calculate_makespan(self.decode_schedule(ind)), ind) for ind in population], key=lambda x: x[0])
            new_pop = [x[1] for x in scored_pop[:max(1, int(pop_size * 0.2))]]
            while len(new_pop) < pop_size:
                child = random.choice(scored_pop[:max(1, int(pop_size * 0.5))])[1][:]
                if random.random() < mutation_rate:
                    i1, i2 = random.sample(range(len(child)), 2)
                    child[i1], child[i2] = child[i2], child[i1]
                new_pop.append(child)
            population = new_pop
        return self.decode_schedule(population[0])