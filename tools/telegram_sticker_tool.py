"""Telegram sticker tools.

Provides a first-class Telegram sticker output path. This borrows the useful
shape from Smart_Group_Bot: use a semantic query when possible, allow exact
file_id when known, and suppress text follow-up when a sticker is the whole
reaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from agent.redact import redact_sensitive_text
from tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


def _clean_text(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return " ".join(text.split())[:max_len]


def _check_telegram_sticker() -> bool:
    if os.environ.get("HERMES_KANBAN_TASK"):
        return True
    try:
        from gateway.session_context import get_session_env
        platform = get_session_env("HERMES_SESSION_PLATFORM", "")
        if platform == "telegram":
            return True
    except Exception:
        pass
    try:
        from gateway.status import is_gateway_running
        return is_gateway_running()
    except Exception:
        return False


def _resolve_current_telegram_target(chat_id: str = "", thread_id: str = "") -> tuple[str, str | None]:
    chat_id = _clean_text(chat_id, max_len=80)
    thread_id = _clean_text(thread_id, max_len=80)
    if chat_id:
        return chat_id, thread_id or None
    try:
        from gateway.session_context import get_session_env
        platform = get_session_env("HERMES_SESSION_PLATFORM", "")
        if platform and platform != "telegram":
            raise ValueError(f"Current session platform is {platform!r}, not telegram")
        env_chat_id = get_session_env("HERMES_SESSION_CHAT_ID", "")
        env_thread_id = get_session_env("HERMES_SESSION_THREAD_ID", "")
        if env_chat_id:
            return str(env_chat_id), str(env_thread_id) if env_thread_id else None
    except ValueError:
        raise
    except Exception:
        pass
    raise ValueError("chat_id is required outside a Telegram gateway session")


async def _send_sticker_via_live_adapter(chat_id: str, sticker: str, *, thread_id: str | None = None):
    try:
        from gateway.config import Platform
        from gateway.run import _gateway_runner_ref
    except Exception:
        return None

    runner = _gateway_runner_ref()
    if runner is None:
        return None
    adapter = runner.adapters.get(Platform.TELEGRAM)
    if adapter is None or not hasattr(adapter, "send_sticker"):
        return None
    metadata = {"thread_id": thread_id} if thread_id else None
    return await adapter.send_sticker(chat_id=chat_id, sticker=sticker, metadata=metadata)


async def _send_sticker_standalone(chat_id: str, sticker: str, *, thread_id: str | None = None) -> dict[str, Any]:
    try:
        from hermes_constants import get_hermes_home
        from telegram import Bot
        from gateway.config import load_gateway_config, Platform
        from gateway.platforms.base import resolve_proxy_url
        from gateway.platforms.telegram import TelegramAdapter
    except ImportError as exc:
        return {"error": f"Telegram sticker send requires python-telegram-bot: {exc}"}

    env_path = get_hermes_home() / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path, override=False)
        except Exception:
            pass

    config = load_gateway_config()
    pconfig = config.platforms.get(Platform.TELEGRAM)
    if not pconfig or not pconfig.token:
        return {"error": "Telegram bot token is not configured"}

    try:
        proxy = resolve_proxy_url("TELEGRAM_PROXY", target_hosts=["api.telegram.org"])
    except Exception:
        proxy = None
    if proxy:
        try:
            from telegram.request import HTTPXRequest
            bot = Bot(
                token=pconfig.token,
                request=HTTPXRequest(proxy=proxy),
                get_updates_request=HTTPXRequest(proxy=proxy),
            )
        except Exception:
            bot = Bot(token=pconfig.token)
    else:
        bot = Bot(token=pconfig.token)

    thread_kwargs = {}
    if thread_id:
        try:
            effective_thread_id = TelegramAdapter._message_thread_id_for_send(str(thread_id))
        except Exception:
            effective_thread_id = None if str(thread_id) == "1" else int(thread_id)
        if effective_thread_id is not None:
            thread_kwargs["message_thread_id"] = effective_thread_id

    try:
        msg = await bot.send_sticker(chat_id=int(chat_id), sticker=sticker, **thread_kwargs)
        return {
            "success": True,
            "platform": "telegram",
            "chat_id": chat_id,
            "message_id": str(msg.message_id),
        }
    except Exception as exc:
        return {"error": f"Telegram sticker send failed: {redact_sensitive_text(str(exc))}"}


async def _send_sticker(chat_id: str, sticker: str, *, thread_id: str | None = None) -> dict[str, Any]:
    live_result = await _send_sticker_via_live_adapter(chat_id, sticker, thread_id=thread_id)
    if live_result is not None and getattr(live_result, "success", False):
        return {
            "success": True,
            "platform": "telegram",
            "chat_id": chat_id,
            "message_id": getattr(live_result, "message_id", None),
        }
    standalone_result = await _send_sticker_standalone(chat_id, sticker, thread_id=thread_id)
    if standalone_result.get("error") and live_result is not None:
        live_error = getattr(live_result, "error", "Telegram adapter sticker send failed")
        standalone_result["live_adapter_error"] = redact_sensitive_text(str(live_error))
    return standalone_result


async def telegram_send_sticker_tool(args, **kw):
    action = _clean_text(args.get("action", "send"), max_len=20).lower() or "send"
    chat_id_arg = _clean_text(args.get("chat_id", ""), max_len=80)
    thread_id_arg = _clean_text(args.get("thread_id", ""), max_len=80)

    if action == "learn":
        from gateway.telegram_sticker_library import add_configured_sticker
        learned = add_configured_sticker(
            file_id=_clean_text(args.get("sticker_file_id", ""), max_len=512),
            description=_clean_text(args.get("description", ""), max_len=200),
            emoji=_clean_text(args.get("emoji", ""), max_len=32),
            set_name=_clean_text(args.get("set_name", ""), max_len=120),
            aliases=[_clean_text(item, max_len=80) for item in args.get("aliases", []) if _clean_text(item, max_len=80)],
            chat_id=chat_id_arg or None,
        )
        if not learned:
            return tool_error("sticker_file_id is required for action='learn'")
        return tool_result(success=True, action="learn", sticker=learned)

    if action == "list":
        from gateway.telegram_sticker_library import list_stickers
        limit = args.get("limit", 20)
        try:
            safe_limit = max(1, min(int(limit), 50))
        except Exception:
            safe_limit = 20
        return tool_result(stickers=list_stickers(chat_id_arg or None, limit=safe_limit))

    if action != "send":
        return tool_error("action must be one of: send, list, learn")

    try:
        chat_id, thread_id = _resolve_current_telegram_target(chat_id_arg, thread_id_arg)
    except ValueError as exc:
        return tool_error(str(exc))

    from gateway.telegram_sticker_library import mark_sent, pick_sticker

    sticker_file_id = _clean_text(args.get("sticker_file_id", ""), max_len=512)
    query = _clean_text(args.get("query", ""), max_len=200)
    picked = None
    if not sticker_file_id:
        picked = pick_sticker(query=query, chat_id=chat_id)
        sticker_file_id = picked.file_id
    if not sticker_file_id:
        return tool_error(
            "No sticker available. Send a Telegram sticker to Hermes first, or call action='learn' with sticker_file_id."
        )

    result = await _send_sticker(chat_id, sticker_file_id, thread_id=thread_id)
    if result.get("error"):
        return tool_result(result)
    mark_sent(chat_id, sticker_file_id)
    if picked is not None:
        result.update({
            "picked_source": picked.source,
            "picked_score": picked.score,
            "description": picked.description,
            "emoji": picked.emoji,
            "set_name": picked.set_name,
        })
    return tool_result(result)


TELEGRAM_SEND_STICKER_SCHEMA = {
    "name": "telegram_send_sticker",
    "description": (
        "Send, list, or learn Telegram stickers. Use this for short emotional reactions, "
        "meme pickup, comfort, celebration, teasing, agreement, being cute, exasperation, "
        "or spectating moments. Be conservative: do not use stickers for serious warnings, "
        "technical troubleshooting, long informational answers, or explicit refusals. When "
        "you have already sent a sticker as the whole reaction, do not add extra text like "
        "'I sent a sticker'. Prefer query over exact sticker_file_id unless you know the ID."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "list", "learn"],
                "description": "send sends a sticker; list shows learned stickers; learn stores a known sticker_file_id.",
            },
            "query": {
                "type": "string",
                "description": "Short emotion/scene description for semantic selection, e.g. 'comforting hug', 'speechless', 'celebration'.",
            },
            "sticker_file_id": {
                "type": "string",
                "description": "Exact Telegram sticker file_id to send or learn. Prefer query unless the ID is known.",
            },
            "chat_id": {
                "type": "string",
                "description": "Optional Telegram chat_id. Omit in a Telegram session to use the current chat.",
            },
            "thread_id": {
                "type": "string",
                "description": "Optional Telegram topic/thread id. Omit to use the current Telegram thread when available.",
            },
            "description": {
                "type": "string",
                "description": "For action='learn': semantic description of the sticker.",
            },
            "emoji": {
                "type": "string",
                "description": "For action='learn': associated emoji.",
            },
            "set_name": {
                "type": "string",
                "description": "For action='learn': Telegram sticker set name.",
            },
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "For action='learn': extra semantic aliases.",
            },
            "limit": {
                "type": "integer",
                "description": "For action='list': maximum stickers to return.",
            },
        },
        "required": [],
    },
}


registry.register(
    name="telegram_send_sticker",
    toolset="messaging",
    schema=TELEGRAM_SEND_STICKER_SCHEMA,
    handler=telegram_send_sticker_tool,
    check_fn=_check_telegram_sticker,
    is_async=True,
    emoji="🎭",
)
