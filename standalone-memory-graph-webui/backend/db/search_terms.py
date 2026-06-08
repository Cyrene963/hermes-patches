import re
from threading import Lock
from typing import Iterable, List

import jieba


class SearchTokenizer:
    """
    Encapsulates tokenization logic for full-text search, handling text normalization,
    CJK character segmentation (via jieba), and custom glossary registration.
    """

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
    SEPARATOR_RE = re.compile(r"[:/.\-]+")

    _jieba_lock = Lock()
    _registered_words: set[str] = set()

    @staticmethod
    def dedupe(tokens: Iterable[str]) -> List[str]:
        """Remove duplicates from a list of tokens while preserving order."""
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
        """Register custom words into jieba's dictionary in a thread-safe manner."""
        with cls._jieba_lock:
            for token in tokens:
                if token in cls._registered_words or not cls.CJK_RUN_RE.fullmatch(token):
                    continue
                jieba.add_word(token)
                cls._registered_words.add(token)

    @classmethod
    def _segment_cjk(cls, text: str) -> List[str]:
        """Segment a CJK string into words using jieba."""
        words = [word.strip() for word in jieba.cut_for_search(text) if word.strip()]
        return cls.dedupe(words or [text])

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """
        Normalize and split text into a deduplicated list of tokens,
        applying CJK segmentation where necessary.
        """
        # Inline normalization: replaces separators with spaces and strips
        normalized = cls.SEPARATOR_RE.sub(" ", text).strip()
        if not normalized:
            return []

        tokens: List[str] = []
        for part in normalized.split():
            for token in cls.TOKEN_RE.findall(part):
                if cls.CJK_RUN_RE.fullmatch(token):
                    tokens.extend(cls._segment_cjk(token))
                else:
                    tokens.append(token)
        return cls.dedupe(tokens)


# --- Public API for external consumers ---

def expand_query_terms(query: str) -> str:
    """Normalize query text into jieba-segmented tokens for FTS parsers."""
    return " ".join(SearchTokenizer.tokenize(query))


def build_document_search_terms(
    path: str,
    uri: str,
    content: str,
    disclosure: str | None,
    glossary_text: str,
) -> str:
    """
    Build auxiliary search terms for languages without whitespace segmentation.

    The returned text is appended to the derived search document and indexed by
    SQLite FTS5 / PostgreSQL tsvector. Chinese text is segmented with jieba at
    the application layer before entering the database index.
    """
    glossary_tokens = [token for token in glossary_text.split() if token]
    SearchTokenizer.register_custom_words(glossary_tokens)

    tokens = list(glossary_tokens)
    for value in (path, uri, content, disclosure or "", glossary_text):
        tokens.extend(SearchTokenizer.tokenize(value))
        
    return " ".join(SearchTokenizer.dedupe(tokens))
