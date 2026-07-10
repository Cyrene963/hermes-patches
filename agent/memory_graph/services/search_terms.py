"""CJK-aware search tokenization for Memory Graph.

Designed for prompt-time recall: deterministic, fast, and no runtime dictionary
load on the hot path. Jieba is optional only for registering glossary words when
already available; CJK query/document tokenization preserves full runs and
2-8-character compounds.
"""

import re
from threading import Lock
from typing import Iterable, List

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


class SearchTokenizer:
    """Tokenization with CJK segmentation support."""

    CJK_CHAR_CLASS = (
        "\u3400-\u4dbf"
        "\u4e00-\u9fff"
        "\uf900-\ufaff"
        "\u3040-\u30ff"
        "\u31f0-\u31ff"
        "\uac00-\ud7af"
    )

    CJK_RUN_RE = re.compile(f"[{CJK_CHAR_CLASS}]+")
    TOKEN_RE = re.compile(rf"[A-Za-z0-9_]+|[{CJK_CHAR_CLASS}]+")
    SEPARATOR_RE = re.compile(r"[:/.\\-]+")

    _jieba_lock = Lock()
    _registered_words: set = set()

    @staticmethod
    def dedupe(tokens: Iterable[str]) -> List[str]:
        """Remove duplicates while preserving order."""
        seen = set()
        ordered = []
        for token in tokens:
            if not token or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        return ordered

    @classmethod
    def register_custom_words(cls, tokens: Iterable[str]) -> None:
        """Register custom words into jieba's dictionary."""
        if not _HAS_JIEBA:
            return
        with cls._jieba_lock:
            for token in tokens:
                if token in cls._registered_words or not cls.CJK_RUN_RE.fullmatch(token):
                    continue
                jieba.add_word(token)
                cls._registered_words.add(token)

    @classmethod
    def _segment_cjk(cls, text: str) -> List[str]:
        """Segment a CJK string without runtime dictionary loading.

        Jieba's first-use dictionary/cache load can block prompt-time recall on
        small servers or when /tmp cache is stale. For Memory Graph search we
        prefer deterministic, fast recall tokens over perfect linguistic
        segmentation: preserve the full run and all 2-8 char compounds.
        """
        text = (text or "").strip()
        if not text:
            return []
        tokens: List[str] = [text]
        tokens.extend(cls._preserve_compound_cjk_terms(text))
        return cls.dedupe(tokens)

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """Normalize and split text into tokens, applying CJK segmentation."""
        normalized = cls.SEPARATOR_RE.sub(" ", text).strip()
        if not normalized:
            return []

        tokens: List[str] = []
        for part in normalized.split():
            for token in cls.TOKEN_RE.findall(part):
                if cls.CJK_RUN_RE.fullmatch(token):
                    tokens.extend(cls._segment_cjk(token))
                else:
                    tokens.append(token.lower())
        return cls.dedupe(tokens)


    @staticmethod
    def _preserve_compound_cjk_terms(text: str) -> List[str]:
        """Keep long CJK compounds alongside jieba segments.

        Some Memory Graph paths/titles are meaningful compounds (e.g. 误差以内,
        未来伴侣, 宏观理性). Jieba can split them into common words, which makes
        broad OR recall overmatch. Preserving 2-8 char sliding compounds gives
        exact title/path hits enough score to beat generic memories.
        """
        terms: List[str] = []
        for run in SearchTokenizer.CJK_RUN_RE.findall(text or ""):
            n = len(run)
            for size in range(min(8, n), 1, -1):
                for i in range(0, n - size + 1):
                    terms.append(run[i:i + size])
        return terms


_QUERY_SYNONYM_GROUPS = (
    ("preference", "prefer", "偏好", "喜欢", "标准"),
    ("verify", "verification", "evidence", "验收", "验证", "证据", "回读"),
    ("complete", "completion", "completed", "finished", "done", "完成", "结束"),
    ("privacy", "private", "personal", "shared memory", "memory space", "tenant scope", "isolation", "namespace", "隐私", "私人", "共享记忆", "隔离", "命名空间"),
    ("writing", "draft", "coverage", "写作", "动笔", "要点", "覆盖"),
    ("transactional writing", "task-based", "paper 2", "bullet point", "事务写作", "任务型写作", "要点覆盖"),
    ("frontend", "web app", "browser", "device", "网页", "前端", "浏览器", "设备"),
    ("web app", "public url", "real device", "safari", "browser path", "公网", "真机", "真实路径"),
    ("evidence", "implementation", "file exists", "runtime", "artifact", "readback", "clean install", "真实运行", "实现文件", "产物", "回读", "全新安装"),
    ("memory", "recall", "correction", "regression", "记忆", "召回", "纠错", "防复发"),
    ("one-off note", "procedural guard", "root cause", "recurrence", "一次性笔记", "程序性规则", "根因", "防复发"),
    ("continue", "remaining", "checkpoint", "继续", "剩余", "检查点", "阶段"),
)


def expand_query_terms(query: str) -> str:
    """Normalize query and add generic cross-language intent synonyms."""
    tokens = SearchTokenizer.tokenize(query)
    tokens.extend(SearchTokenizer._preserve_compound_cjk_terms(query))
    lowered = (query or "").casefold()
    for group in _QUERY_SYNONYM_GROUPS:
        if any(term.casefold() in lowered for term in group):
            for term in group:
                tokens.extend(SearchTokenizer.tokenize(term))
    return " ".join(SearchTokenizer.dedupe(tokens))


def build_document_search_terms(
    path: str,
    uri: str,
    content: str,
    disclosure: str | None,
    glossary_text: str,
) -> str:
    """Build search terms with CJK segmentation for indexing."""
    glossary_tokens = [token for token in glossary_text.split() if token]
    SearchTokenizer.register_custom_words(glossary_tokens)

    tokens = list(glossary_tokens)
    for value in (path, uri, content, disclosure or "", glossary_text):
        tokens.extend(SearchTokenizer.tokenize(value))

    return " ".join(SearchTokenizer.dedupe(tokens))
