"""Telegram sticker library and semantic selection helpers.

Keeps a small profile-local catalogue of sticker file_ids learned from
Telegram sticker messages or configured manually. The selection logic is
intentionally lightweight and conservative, inspired by Smart_Group_Bot's
sticker library: exact ids win, semantic queries pick the best known sticker,
and random fallback favors recently/commonly seen stickers.
"""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from hermes_cli.config import get_hermes_home

_LIBRARY_PATH = get_hermes_home() / "telegram_sticker_library.json"
_SPACE_RE = re.compile(r"\s+")
_MAX_STICKERS_PER_CHAT = 120
_INVALID_VISION_MARKERS = {"NO_VALID_IMAGE_CONTENT", "NO_VALID_IMAGE"}


@dataclass(slots=True)
class StickerPick:
    file_id: str = ""
    score: int = 0
    source: str = "none"
    description: str = ""
    emoji: str = ""
    set_name: str = ""


def _now() -> float:
    return time.time()


def _normalize(text: str) -> str:
    return _SPACE_RE.sub("", (text or "").lower().strip())


def _clean(text: Any, *, max_len: int = 240) -> str:
    cleaned = str(text or "").replace("\x00", "").strip()
    cleaned = _SPACE_RE.sub(" ", cleaned)
    return cleaned[:max_len]


def _load() -> dict[str, Any]:
    if not _LIBRARY_PATH.exists():
        return {"version": 1, "chats": {}}
    try:
        data = json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "chats": {}}
    if not isinstance(data, dict):
        return {"version": 1, "chats": {}}
    chats = data.get("chats")
    if not isinstance(chats, dict):
        data["chats"] = {}
    data.setdefault("version", 1)
    return data


def _save(data: dict[str, Any]) -> None:
    _LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(_LIBRARY_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, _LIBRARY_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _chat_key(chat_id: str | int | None) -> str:
    return str(chat_id or "global")


def _is_valid_description(text: str) -> bool:
    normalized = _clean(text)
    return bool(normalized) and all(marker not in normalized for marker in _INVALID_VISION_MARKERS)


def _auto_description(emoji: str = "", set_name: str = "", description: str = "") -> str:
    desc = _clean(description, max_len=160)
    if _is_valid_description(desc):
        return desc
    if emoji and set_name:
        return f"sticker {emoji} from {set_name}"
    if emoji:
        return f"sticker {emoji}"
    if set_name:
        return f"sticker from {set_name}"
    return "telegram sticker"


def _record_text(record: dict[str, Any]) -> str:
    aliases = record.get("aliases") if isinstance(record.get("aliases"), list) else []
    parts = [
        record.get("description", ""),
        record.get("emoji", ""),
        record.get("set_name", ""),
        " ".join(str(alias) for alias in aliases),
    ]
    return _clean(" ".join(str(part or "") for part in parts), max_len=800)


def _score(query: str, target: str) -> int:
    q = _normalize(query)
    t = _normalize(target)
    if not q or not t:
        return 0
    ratio = int(SequenceMatcher(None, q, t).ratio() * 100)
    substring_bonus = 25 if q in t else 0
    overlap_bonus = len(set(q) & set(t))
    return ratio + substring_bonus + overlap_bonus


def _trim(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) <= _MAX_STICKERS_PER_CHAT:
        return records
    return sorted(
        records,
        key=lambda item: (
            float(item.get("last_seen_at") or 0),
            float(item.get("last_sent_at") or 0),
            int(item.get("sent_count") or 0),
            int(item.get("seen_count") or 0),
        ),
        reverse=True,
    )[:_MAX_STICKERS_PER_CHAT]


def learn_sticker(
    chat_id: str | int | None,
    file_id: str,
    *,
    emoji: str = "",
    set_name: str = "",
    description: str = "",
    aliases: list[str] | None = None,
    source: str = "telegram_message",
) -> dict[str, Any] | None:
    file_id = _clean(file_id, max_len=512)
    if not file_id:
        return None
    data = _load()
    key = _chat_key(chat_id)
    records = data.setdefault("chats", {}).setdefault(key, [])
    if not isinstance(records, list):
        records = []
        data["chats"][key] = records

    now = _now()
    record = next((item for item in records if item.get("file_id") == file_id), None)
    desc = _auto_description(emoji, set_name, description)
    clean_aliases = [_clean(alias, max_len=80) for alias in (aliases or []) if _clean(alias, max_len=80)]
    if record is None:
        record = {
            "file_id": file_id,
            "emoji": _clean(emoji, max_len=32),
            "set_name": _clean(set_name, max_len=120),
            "description": desc,
            "aliases": clean_aliases,
            "seen_count": 1,
            "sent_count": 0,
            "source": _clean(source, max_len=80) or "telegram_message",
            "created_at": now,
            "last_seen_at": now,
            "last_sent_at": 0,
        }
        records.append(record)
    else:
        record["emoji"] = _clean(emoji, max_len=32) or record.get("emoji", "")
        record["set_name"] = _clean(set_name, max_len=120) or record.get("set_name", "")
        old_desc = _clean(record.get("description", ""), max_len=160)
        if desc and desc != old_desc:
            existing_aliases = record.get("aliases") if isinstance(record.get("aliases"), list) else []
            if old_desc and old_desc not in existing_aliases:
                existing_aliases.append(old_desc)
            for alias in clean_aliases:
                if alias not in existing_aliases:
                    existing_aliases.append(alias)
            record["aliases"] = existing_aliases[:20]
            record["description"] = desc
        record["seen_count"] = int(record.get("seen_count") or 0) + 1
        record["last_seen_at"] = now

    data["chats"][key] = _trim(records)
    _save(data)
    return dict(record)


def add_configured_sticker(
    *,
    file_id: str,
    description: str = "",
    emoji: str = "",
    set_name: str = "",
    aliases: list[str] | None = None,
    chat_id: str | int | None = None,
) -> dict[str, Any] | None:
    return learn_sticker(
        chat_id,
        file_id,
        emoji=emoji,
        set_name=set_name,
        description=description or "configured sticker",
        aliases=aliases,
        source="configured",
    )


def mark_sent(chat_id: str | int | None, file_id: str) -> None:
    file_id = _clean(file_id, max_len=512)
    if not file_id:
        return
    data = _load()
    key = _chat_key(chat_id)
    records = data.setdefault("chats", {}).setdefault(key, [])
    if not isinstance(records, list):
        records = []
        data["chats"][key] = records
    now = _now()
    record = next((item for item in records if item.get("file_id") == file_id), None)
    if record is None:
        record = {
            "file_id": file_id,
            "emoji": "",
            "set_name": "",
            "description": "sent sticker",
            "aliases": [],
            "seen_count": 0,
            "sent_count": 1,
            "source": "sent_explicit",
            "created_at": now,
            "last_seen_at": 0,
            "last_sent_at": now,
        }
        records.append(record)
    else:
        record["sent_count"] = int(record.get("sent_count") or 0) + 1
        record["last_sent_at"] = now
    data["chats"][key] = _trim(records)
    _save(data)


def list_stickers(chat_id: str | int | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    data = _load()
    chats = data.get("chats", {}) if isinstance(data.get("chats"), dict) else {}
    keys = [_chat_key(chat_id)] if chat_id is not None else list(chats.keys())
    records: list[dict[str, Any]] = []
    for key in keys:
        rows = chats.get(key, [])
        if isinstance(rows, list):
            records.extend(row for row in rows if isinstance(row, dict))
    records.sort(
        key=lambda item: (
            int(item.get("sent_count") or 0),
            int(item.get("seen_count") or 0),
            float(item.get("last_sent_at") or 0),
            float(item.get("last_seen_at") or 0),
        ),
        reverse=True,
    )
    safe_limit = max(1, min(int(limit or 20), 100))
    return [dict(item) for item in records[:safe_limit]]


def pick_sticker(
    *,
    query: str = "",
    chat_id: str | int | None = None,
    fallback_file_ids: list[str] | None = None,
) -> StickerPick:
    query = _clean(query, max_len=200)
    candidates = list_stickers(chat_id, limit=100)
    fallback = [_clean(item, max_len=512) for item in (fallback_file_ids or []) if _clean(item, max_len=512)]

    if candidates and query:
        best_score = -1
        best: dict[str, Any] | None = None
        for record in candidates:
            score = _score(query, _record_text(record))
            if score > best_score:
                best_score = score
                best = record
        if best and best_score >= 25:
            return StickerPick(
                file_id=str(best.get("file_id") or ""),
                score=best_score,
                source="library_match",
                description=str(best.get("description") or ""),
                emoji=str(best.get("emoji") or ""),
                set_name=str(best.get("set_name") or ""),
            )

    if candidates:
        top = candidates[: min(8, len(candidates))]
        chosen = random.choice(top)
        return StickerPick(
            file_id=str(chosen.get("file_id") or ""),
            source="library_recent",
            description=str(chosen.get("description") or ""),
            emoji=str(chosen.get("emoji") or ""),
            set_name=str(chosen.get("set_name") or ""),
        )

    if fallback:
        return StickerPick(file_id=random.choice(fallback), source="fallback_pool")

    return StickerPick()
