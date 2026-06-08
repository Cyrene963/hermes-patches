"""QueryPlanner — entity-anchored query decomposition with intent-aware ranking."""

import re
from typing import List, Dict, Any

_ENTITIES = {
    'user-a': ['user-a', 'Nitrogen', 'nitrogen'],
    'Steven': ['Steven', 'steven', 'STEVEN'],
    'focus-app': ['focus-app', 'focus-app', 'focus-app'],
    'DSE': ['DSE', 'dse'],
    'Telegram': ['Telegram', 'telegram', 'TG'],
    'Hermes': ['Hermes', 'hermes'],
    'Memory Graph': ['Memory Graph', 'memory graph'],
    'Hindsight': ['Hindsight', 'hindsight'],
}

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
    for entity, aliases in _ENTITIES.items():
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
    """Return the canonical path prefix for an entity."""
    paths = {
        'user-a': '用户档案/user-a详细档案',
        'Steven': '用户档案/Steven详细档案',
        'focus-app': '项目/focus-app',
        'DSE': '用户档案/学习状态',
        'Telegram': '系统架构/Telegram配置',
        'Hermes': '项目/hermes-agent',
        'Memory Graph': '项目/memory-graph',
        'Hindsight': '系统架构/Hindsight运维',
    }
    return paths.get(entity, '')

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
