"""QueryPlanner — entity-anchored query decomposition with intent-aware ranking.

Entities and their canonical paths are NOT hardcoded here — they load from a
deployment-local file via identity_config (neutral fixtures by default). This
keeps the public repo free of real names. See identity_config.py.
"""

import re
from typing import List, Dict, Any

from identity_config import get_entities, get_entity_paths

_FACETS = [
    '家庭', '家庭情况', '父母', '家人', '学校', '成绩', '分数', '考试', 'mock',
    '备考', '学习', '技术栈', '架构', '部署', '配置', '服务器', '端口',
    '数学', '英文', '物理', '经济', '中文', '错题', '题库', '真题', '解析',
    '发送', '文件', '规则', '格式', '偏好', '年龄', '几岁', '生日',
    '项目', '代码', '数据库', 'API', 'cron', 'job',
]

_OP_KEYWORDS = ['注意', '规则', '怎么发', '怎么用', '如何配置', '应该', '需要', '发文件', '发给', '帮我发', '走什么']

_INVENTORY_PATTERNS = ['记得哪些', '记得什么', '有哪些记忆', '知道哪些', '记忆类别', '关于.*记得', '关于.*资料', '关于.*知道']

def extract_entities(query: str) -> List[str]:
    found = []
    q_lower = query.lower()
    for entity, aliases in get_entities().items():
        for alias in aliases:
            if alias.lower() in q_lower:
                found.append(entity)
                break
    return found

def extract_facets(query: str) -> List[str]:
    return [f for f in _FACETS if f in query]

def is_operation_query(query: str) -> bool:
    return any(kw in query for kw in _OP_KEYWORDS)

def is_inventory_query(query: str) -> bool:
    return any(re.search(p, query) for p in _INVENTORY_PATTERNS)

def get_entity_path(entity: str) -> str:
    """Return the canonical path prefix for an entity (from deployment config)."""
    return get_entity_paths().get(entity, '')

def plan_query(query: str) -> Dict[str, Any]:
    entities = extract_entities(query)
    facets = extract_facets(query)
    is_op = is_operation_query(query)
    is_inv = is_inventory_query(query)
    
    if is_inv and entities:
        return {
            'mode': 'inventory_query',
            'entities': entities,
            'search_queries': [],
            'action': 'inventory'
        }
    
    if entities and facets:
        entity_path = get_entity_path(entities[0])
        return {
            'mode': 'entity_anchored_facet',
            'entities': entities,
            'facets': facets,
            'entity_path': entity_path,
            'search_queries': [
                entities[0] + ' ' + ' '.join(facets[:2]),
                entities[0],
            ],
            'filter_path': entity_path,
        }
    elif entities:
        entity_path = get_entity_path(entities[0])
        return {
            'mode': 'entity_search',
            'entities': entities,
            'entity_path': entity_path,
            'search_queries': [entities[0]],
            'filter_path': entity_path,
        }
    elif facets:
        return {
            'mode': 'facet_search',
            'facets': facets,
            'search_queries': [' '.join(facets)],
        }
    elif is_op:
        return {
            'mode': 'operation_search',
            'search_queries': [query],
        }
    else:
        return {
            'mode': 'global_search',
            'search_queries': [query],
        }
