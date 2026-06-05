"""Intent-aware reranking for Hindsight recall results."""

import re

# Memory type weights by intent
_TYPE_WEIGHTS = {
    'fact_lookup': {
        'user_profile': 2.0,
        'project_fact': 1.8,
        'rule': 1.5,
        'conversation_event': 1.0,
        'lesson': 0.8,
        'debug_log': 0.3,
        'tool_error': 0.3,
        'cron': 0.3,
    },
    'history_search': {
        'conversation_event': 2.0,
        'lesson': 1.8,
        'system_architecture': 1.5,
        'user_profile': 0.8,
        'debug_log': 0.5,
    },
    'operation_rule': {
        'rule': 2.0,
        'tool_config': 1.8,
        'user_profile': 1.0,
        'debug_log': 0.3,
    },
    'compound_intent': {
        'rule': 1.8,
        'user_profile': 1.5,
        'tool_config': 1.5,
        'debug_log': 0.3,
    },
}

# Patterns to detect memory type from text
_TYPE_PATTERNS = [
    (r'(debug|DEBUG|error|ERROR|traceback|Traceback|exception)', 'debug_log'),
    (r'(cron|job|scheduled|定时|任务)', 'cron'),
    (r'(tool.*error|tool.*fail|工具.*错误)', 'tool_error'),
    (r'(用户|user|profile|preference|age|年龄|家庭|偏好)', 'user_profile'),
    (r'(项目|project|部署|技术栈|architecture)', 'project_fact'),
    (r'(规则|rule|format|格式|注意|MEDIA)', 'rule'),
    (r'(对话|聊过|讨论|conversation|session)', 'conversation_event'),
    (r'(教训|经验|lesson|learned|发现)', 'lesson'),
]

def detect_memory_type(text: str) -> str:
    """Detect memory type from text content."""
    text_lower = text.lower()
    for pattern, mtype in _TYPE_PATTERNS:
        if re.search(pattern, text_lower):
            return mtype
    return 'unknown'

def rerank_results(results: list, intent: str = 'fact_lookup') -> list:
    """Rerank Hindsight recall results based on intent and memory type."""
    if not results:
        return results

    weights = _TYPE_WEIGHTS.get(intent, _TYPE_WEIGHTS['fact_lookup'])

    for r in results:
        text = r.get('text', '') if isinstance(r, dict) else getattr(r, 'text', '')
        mtype = detect_memory_type(text)
        weight = weights.get(mtype, 1.0)

        # Store original score if available
        if isinstance(r, dict):
            original_score = r.get('score', 1.0)
            r['_rerank_score'] = original_score * weight
            r['_memory_type'] = mtype
        else:
            # For object results, add attributes
            if not hasattr(r, '_original_score'):
                r._original_score = getattr(r, 'score', 1.0)
            r.score = r._original_score * weight

    # Sort by rerank score
    if isinstance(results[0], dict):
        results.sort(key=lambda r: r.get('_rerank_score', 0), reverse=True)
    else:
        results.sort(key=lambda r: getattr(r, 'score', 0), reverse=True)

    return results
