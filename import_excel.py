# -*- coding: utf-8 -*-
"""
从 Excel 导入产品-产线配置
"""
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

def import_product_line_mapping_from_excel(excel_path):
    """从 Excel 导入产品-产线配置"""
    
    xl = pd.ExcelFile(excel_path, engine='openpyxl')
    df = pd.read_excel(xl, sheet_name=0)
    
    results = []
    current_company = None
    
    for idx, row in df.iterrows():
        # Skip header rows
        if pd.isna(row.get('公司')) and pd.isna(row.get('物料组分类')):
            continue
        
        company_val = row.get('公司')
        if pd.notna(company_val):
            # Check if it's a valid company code
            try:
                if str(company_val).isdigit() or (isinstance(company_val, (int, float)) and not pd.isna(company_val)):
                    current_company = int(company_val) if not pd.isna(company_val) else None
                elif '重点' in str(company_val) or 'DIP' in str(company_val):
                    continue
            except:
                if str(company_val) not in ['公司', '重点注意']:
                    current_company = str(company_val)
        
        material_group = row.get('物料组分类')
        if pd.isna(material_group):
            continue
        
        # Skip special rows
        if '可自动' in str(material_group) or '配置' in str(material_group):
            continue
            
        # Collect line IDs
        lines = []
        for i in range(1, 11):
            col = f'适合排查线体{i}'
            if col in row and pd.notna(row[col]):
                lines.append(str(row[col]))
        
        if lines:
            range_condition = row.get('范围(配置）')
            results.append({
                'company_code': current_company,
                'material_group': str(material_group),
                'range_condition': str(range_condition) if pd.notna(range_condition) else '所有',
                'lines': ','.join(lines),
                'line_type': 'SMT' if lines[0].startswith('S') else 'DIP'
            })
    
    return results


if __name__ == '__main__':
    results = import_product_line_mapping_from_excel('C:/Users/mtc/.openclaw/workspace/自动排程表格.xlsx')
    print(f'Imported {len(results)} records:')
    for r in results[:15]:
        print(r)
