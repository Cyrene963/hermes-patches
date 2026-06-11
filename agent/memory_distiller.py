"""Deterministic fact distiller for Memory OS write candidates.

The extractor used to store the RAW user message as the memory object, so a
shadow-log audit found 68% of candidates were "raw truncated copies" — useless,
unsearchable noise. This module distills the atomic FACT from the message:

  "记住：我的部署命令是 pm2 reload all"  → "我的部署命令是 pm2 reload all"
  "纠正一下，我住在深圳不是广州"          → "我住在深圳不是广州"
  "[Replying to: <quote>] 实测结果是X"   → "实测结果是X"

It is conservative: if it cannot confidently produce a short, single-clause fact
(e.g. a long multi-topic ramble), it returns ok=False so the candidate falls to
the hygiene gate / review instead of fabricating a misleading "fact".

Pure & deterministic — no LLM, no I/O — so it is unit-testable and adds no latency.
An LLM distiller can later replace `distill_fact` behind the same signature.
"""
from __future__ import annotations

import re
from typing import Tuple

# Reply/quote blocks carry no durable fact — drop them entirely.
_REPLY_BLOCK_RE = re.compile(r"\[(?:Replying to|回复)[:：].*?\]", re.S)

# Leading memory-signal markers to strip (longest-first within each scan).
_LEADING_MARKERS = [
    "记住这个", "记下这个", "记一下", "记住", "记下", "记录", "保存", "记得", "别忘了",
    "提醒我", "麻烦记一下", "帮我记住",
    "纠正一下", "更正一下", "纠正", "更正", "澄清一下",
    "我想说的是", "我的意思是", "我之前说的是", "我说过",
    "其实是", "其实", "应该是", "正确的是", "准确说",
    "note that", "please remember", "just remember", "remember that", "remember",
    "for the record", "fyi", "actually", "correction", "to clarify", "i meant",
]

# Trailing politeness / filler to strip.
_TRAILING_FILLER = [
    "谢谢你", "谢谢了", "谢谢", "辛苦了", "拜托了", "拜托", "麻烦了", "麻烦你了",
    "好吗", "好吧", "可以吗", "行吗", "哈", "哈哈", "嗯",
    "thanks", "thank you", "please", "ok", "okay",
]

# Sentence boundaries (CJK + ASCII).
_SENT_SPLIT_RE = re.compile(r"[。！？!?\n]+|(?<=[一-鿿])，(?=.{12,})")

_LEADING_PUNCT_RE = re.compile(r"^[\s：:，,、。.!！?？\-—]+")
_TRAILING_PUNCT_RE = re.compile(r"[\s：:，,、。.!！?？\-—]+$")


def _strip_leading_markers(text: str) -> str:
    changed = True
    while changed:
        changed = False
        t = _LEADING_PUNCT_RE.sub("", text)
        low = t.lower()
        for m in _LEADING_MARKERS:
            if low.startswith(m.lower()):
                t = t[len(m):]
                t = _LEADING_PUNCT_RE.sub("", t)
                text = t
                changed = True
                break
        else:
            text = t
    return text


def _strip_trailing_filler(text: str) -> str:
    changed = True
    while changed:
        changed = False
        t = _TRAILING_PUNCT_RE.sub("", text)
        low = t.lower()
        for f in _TRAILING_FILLER:
            if low.endswith(f.lower()):
                t = t[: len(t) - len(f)]
                t = _TRAILING_PUNCT_RE.sub("", t)
                text = t
                changed = True
                break
        else:
            text = t
    return text


def distill_fact(text: str, *, max_len: int = 200) -> Tuple[str, bool]:
    """Distill an atomic fact from a user message.

    Returns (fact, ok). ok=False means a confident single-clause fact could not be
    produced (caller should NOT treat the result as a clean memory).
    """
    if not text or not text.strip():
        return "", False

    # 1) drop reply/quote blocks (closed form first, then any unclosed remainder:
    #    shadow logs truncate messages, so "[Replying to: <quote>" often loses its
    #    closing "]" — strip from the marker to end so the quote can't pose as a fact)
    t = _REPLY_BLOCK_RE.sub(" ", text)
    _m = re.search(r"\[(?:Replying to|回复)[:：]", t)
    if _m:
        t = t[: _m.start()]
    # 2) collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # 3) strip leading markers + trailing filler
    t = _strip_leading_markers(t)
    t = _strip_trailing_filler(t)
    t = t.strip()
    if not t:
        return "", False

    # 4) split into sentences/clauses to judge atomicity
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(t) if s and s.strip()]
    n = len(sentences)

    if n <= 1:
        # single statement: a fact iff it fits and isn't a fragment
        if 4 <= len(t) <= max_len:
            return t, True
        return t[:max_len], False

    # multi-statement: the first clause is the candidate fact, but 3+ sentences is
    # a multi-topic ramble — keep the first clause yet flag it low-confidence so it
    # won't be trusted as an atomic fact.
    first = sentences[0]
    if not (4 <= len(first) <= max_len):
        return first[:max_len], False
    return first, (n <= 2)
