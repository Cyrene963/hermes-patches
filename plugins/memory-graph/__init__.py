"""Memory Graph multi-user namespace isolation + auto-recall plugin.

Three functions:
1. on_session_start: injects user_id/chat_id as namespace + auto-onboard new users
2. pre_llm_call: auto-searches Memory Graph with user message keywords,
   injects relevant memories as ephemeral context (like Hindsight but structured)
3. Auto-creates memory_graph accounts for new users with default password = platform_id
"""

import logging
import threading
import json
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local storage for current namespace context
_context = threading.local()

# Admin platform IDs — users who get admin role in Memory Graph
# Read from config.yaml memory_graph.admin_platform_ids, fallback to first user
_MG_USERS_FILE = Path.home() / ".hermes" / "memory_graph_users.json"
_MG_CONFIG_KEY = "memory_graph"

def _get_admin_ids() -> set:
    """Get admin platform IDs from config. Returns set of 'platform:id' strings."""
    try:
        config_path = Path.home() / ".hermes" / "config.yaml"
        if config_path.exists():
            import yaml
            cfg = yaml.safe_load(config_path.read_text()) or {}
            mg_cfg = cfg.get(_MG_CONFIG_KEY, {})
            admin_ids = mg_cfg.get("admin_platform_ids", [])
            if admin_ids:
                return set(admin_ids)
    except Exception:
        pass
    # No hardcoded owner/admin fallback. Operators should configure
    # memory_graph.admin_platform_ids in config.yaml.
    return set()


def _load_plugin_config() -> dict:
    """Load generic Memory Graph plugin policy from config.yaml.

    The defaults are conservative and deployment-agnostic. Operators can tune
    recall breadth without changing code.
    """
    defaults = {
        "auto_recall_max_query_chars": 320,
        "auto_recall_max_tokens": 12,
        "auto_recall_max_results": 5,
        "auto_recall_context_chars": 1200,
        "auto_recall_min_message_chars": 5,
    }
    try:
        config_path = Path.home() / ".hermes" / "config.yaml"
        if not config_path.exists():
            return defaults
        import yaml
        cfg = yaml.safe_load(config_path.read_text()) or {}
        mg_cfg = cfg.get(_MG_CONFIG_KEY, {}) or {}
        merged = dict(defaults)
        for key in defaults:
            if key in mg_cfg and mg_cfg[key] is not None:
                merged[key] = mg_cfg[key]
        return merged
    except Exception:
        return defaults


def _coerce_text(value) -> str:
    """Best-effort hook payload normalizer.

    Plugin hooks can receive OpenAI-style content arrays or message lists during
    compression/tool turns. Treating them as strings caused repeated
    pre_llm_call/post_llm_call crashes (`list` has no `.strip()`, list+str).
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("message") or ""
                if isinstance(text, (list, dict)):
                    text = _coerce_text(text)
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(value, dict):
        text = value.get("text") or value.get("content") or value.get("message") or ""
        if text:
            return _coerce_text(text)
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _is_high_signal_short_message(text: str) -> bool:
    """Return True for short messages that still require memory recall.

    Short Chinese turns like “继续”, “去修”, “错错错”, and “有必要吗”
    are often contextual references to an active workstream or a stored user
    correction. A pure length gate made these behave like stateless chat.
    """
    compact = _coerce_text(text).strip().lower()
    if not compact:
        return False
    high_signal = {
        "继续", "接着", "去修", "修", "做", "开干", "错", "错错错",
        "不对", "不是", "有必要吗", "必要吗", "太气人", "记住", "记得",
    }
    return compact in high_signal or any(marker in compact for marker in ("之前", "刚才", "你错", "又没", "不记得"))


def _resolve_runtime_namespace(kwargs: dict | None = None) -> str:
    """Resolve namespace for plugin hooks, including CLI default-terminal fallback."""
    kwargs = kwargs or {}
    _apply_turn_namespace_from_kwargs(kwargs)
    ns = get_current_namespace()
    if ns:
        return ns
    try:
        from agent.request_context import get_namespace as _rc_get_ns
        ns = _rc_get_ns()
        if ns:
            set_current_namespace(ns)
            return ns
    except Exception:
        pass
    # CLI sessions often have no chat_id/user_id in hook kwargs. Use the same
    # default_terminal_user fallback as Memory Graph tools so shadow logs and
    # read/write gates do not degrade to namespace="" for the owner's terminal.
    platform = str(kwargs.get("platform") or "").strip().lower()
    if platform in {"", "cli", "terminal"}:
        try:
            import yaml
            cfg_path = Path.home() / ".hermes" / "config.yaml"
            if cfg_path.exists():
                cfg = yaml.safe_load(cfg_path.read_text()) or {}
                default_user = str((cfg.get("memory_graph") or {}).get("default_terminal_user") or "").strip()
                if default_user:
                    ns = f"telegram:{default_user}"
                    set_current_namespace(ns)
                    return ns
        except Exception:
            pass
    return ""


def _build_recall_queries(user_message: str, max_chars: int = 320, max_tokens: int = 12) -> list[str]:
    """Build language-agnostic recall queries from the live user message.

    This avoids the old failure mode where only the first few short CJK bigrams
    were searched. The full truncated message preserves multi-facet intent, and
    longest tokens provide targeted fallbacks. Search ranking and namespace
    scoping decide relevance; no user-specific keyword lists are embedded here.
    """
    import re

    msg = _coerce_text(user_message).strip()[:max_chars]
    if not msg:
        return []

    token_re = r"[A-Za-z0-9_]{3,}|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af]{2,}"
    tokens = re.findall(token_re, msg)
    ranked = sorted({t.strip().lower() for t in tokens if t.strip()}, key=lambda s: (-len(s), s))

    queries = [msg]
    if ranked:
        queries.append(" ".join(ranked[:max_tokens]))
        queries.extend(ranked[: min(5, max_tokens)])

    seen = set()
    deduped = []
    for query in queries:
        query = query.strip()
        if query and query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def _context_budget(default: int = 1200) -> int:
    try:
        return int(os.environ.get("HERMES_MEMORY_GRAPH_RECALL_CONTEXT_CHARS", "") or default)
    except Exception:
        return default


def _parse_uri(uri: str) -> tuple[str, str]:
    if not uri or "://" not in uri:
        return "core", uri or ""
    domain, path = uri.split("://", 1)
    return domain or "core", path


async def _hydrate_recall_content(items: list[dict], namespace: str = "") -> list[dict]:
    """Best-effort fill of full memory content for search hits.

    Search snippets are intentionally compact, but operational memories often
    need exact commands/headers. Hydrate only the already-selected hits and only
    within the same namespace/core scope used for the search.
    """
    if not items:
        return items
    from agent.memory_graph.services.graph import GraphService
    gs = GraphService()
    hydrated = []
    for item in items:
        merged = dict(item)
        if not merged.get("content"):
            uri = str(merged.get("uri") or "")
            domain, path = _parse_uri(uri)
            namespaces = [namespace] if namespace else []
            if "" not in namespaces:
                namespaces.append("")
            for ns in namespaces:
                try:
                    full = await gs.get_memory_by_path(path=path, domain=domain, namespace=ns)
                except Exception:
                    full = None
                if full and full.get("content"):
                    merged.update(full)
                    break
        hydrated.append(merged)
    return hydrated


def _ensure_mg_user(platform: str, platform_id: str, display_name: str = ""):
    """Auto-create Memory Graph user if not exists. Returns user dict."""
    if not platform_id:
        return None

    try:
        from agent.memory_graph.auth import (
            _load_users, _save_users, hash_password, create_user, authenticate
        )

        users = _load_users()

        # Check if user already exists by platform_id
        for uname, udata in users.items():
            if udata.get("platform") == platform and udata.get("platform_id") == platform_id:
                return udata  # Already exists

        # New user — create account
        username = platform_id  # Use platform_id as username
        if username in users:
            username = f"{platform}_{platform_id}"

        # Determine role
        admin_ids = _get_admin_ids()
        is_admin = f"{platform}:{platform_id}" in admin_ids
        role = "admin" if is_admin else "user"

        # Admin keeps admin permissions but still uses an explicit personal
        # namespace by default. Empty namespace means shared/core visibility, not
        # "the admin user's private space".
        namespace = f"{platform}:{platform_id}"

        # Default password = platform_id (user can change via dashboard)
        default_password = platform_id

        user = create_user(
            username=username,
            password=default_password,
            namespace=namespace,
            display_name=display_name or username,
            platform=platform,
            platform_id=platform_id,
        )

        # Set role if admin
        if is_admin:
            users = _load_users()
            if username in users:
                users[username]["role"] = "admin"
                _save_users(users)

        logger.info(
            "Memory Graph auto-onboarded user: %s (%s) role=%s",
            username, display_name or platform_id, role
        )
        return user

    except Exception as e:
        logger.warning("Memory Graph auto-onboarding failed for %s:%s: %s",
                       platform, platform_id, e)
        return None


def get_current_namespace() -> str:
    """Get the current user's namespace. Called by tool handlers."""
    return getattr(_context, "namespace", "")


def set_current_namespace(namespace: str):
    """Set the current user's namespace."""
    _context.namespace = namespace


def _is_shared_chat(chat_type: str = "", user_id: str = "", chat_id: str = "") -> bool:
    """Return True for group/channel/thread contexts.

    Important privacy boundary: sender identity (user_id) is not memory scope in
    shared chats. Shared chats get their own namespace.
    """
    ct = (chat_type or "").strip().lower()
    if ct and ct != "dm":
        return True
    # Telegram/Discord group IDs often differ from sender IDs even if chat_type
    # is missing from an older gateway hook payload.
    return bool(user_id and chat_id and str(user_id) != str(chat_id))


def _resolve_namespace(user_id: str = "", chat_id: str = "",
                        platform: str = "", chat_type: str = "",
                        thread_id: str = "", **kwargs) -> str:
    uid = (user_id or "").strip()
    cid = (chat_id or "").strip()
    plat = (platform or "").strip()
    tid = (thread_id or kwargs.get("thread_id") or "").strip()
    if _is_shared_chat(chat_type=chat_type or kwargs.get("chat_type", ""), user_id=uid, chat_id=cid):
        parts = [plat or "chat", "group"]
        if cid:
            parts.append(cid)
        if tid:
            parts.append(tid)
        return ":".join(parts)
    identifier = uid or cid or ""
    if not identifier:
        # Terminal session: try to find user from config
        try:
            import yaml
            cfg_path = Path.home() / ".hermes" / "config.yaml"
            if cfg_path.exists():
                cfg = yaml.safe_load(cfg_path.read_text()) or {}
                mg_cfg = cfg.get("memory_graph", {})
                default_user = mg_cfg.get("default_terminal_user", "")
                if default_user:
                    return f"telegram:{default_user}"
        except Exception:
            pass
        return ""
    if plat:
        return f"{plat}:{identifier}"
    return identifier


def _on_session_start(session_id="", user_id="", chat_id="", platform="",
                       display_name="", chat_type="", thread_id="", **kwargs):
    """Hook: set namespace at session start + auto-onboard new users."""
    logger.info("Memory Graph _on_session_start: session=%s, user=%s, chat=%s, platform=%s, chat_type=%s",
                session_id, user_id, chat_id, platform, chat_type)
    ns = _resolve_namespace(user_id=user_id, chat_id=chat_id, platform=platform,
                            chat_type=chat_type, thread_id=thread_id)
    if ns:
        set_current_namespace(ns)
        logger.info("Memory Graph namespace set to: %s", ns)
    else:
        set_current_namespace("")
        logger.info("Memory Graph: no user context, using default namespace")
    
    # Set RequestContext for zero-default namespace propagation
    try:
        from agent.request_context import RequestContext, set_context
        admin_ids = _get_admin_ids()
        is_admin = f"{platform}:{user_id or chat_id}" in admin_ids and not _is_shared_chat(chat_type=chat_type, user_id=str(user_id or ""), chat_id=str(chat_id or ""))
        set_context(RequestContext(
            user_id=user_id or "",
            chat_id=chat_id or "",
            platform=platform or "",
            namespace=ns,
            session_id=session_id or "",
            is_admin=is_admin,
        ))
    except Exception as e:
        logger.debug("RequestContext setup failed: %s", e)

    # Auto-onboard: create Memory Graph account if user doesn't exist yet.
    # Shared chats are namespaces, not users; do not create/login as sender here.
    identifier = user_id or chat_id
    if platform and identifier and not _is_shared_chat(chat_type=chat_type, user_id=str(user_id or ""), chat_id=str(chat_id or "")):
        try:
            _ensure_mg_user(
                platform=platform,
                platform_id=str(identifier),
                display_name=display_name or "",
            )
        except Exception as e:
            logger.debug("Memory Graph onboarding skipped: %s", e)

    # Reset protocol turn counter for new session
    global _protocol_turn_count
    _protocol_turn_count = 0


def _apply_turn_namespace_from_kwargs(kwargs: dict):
    """Refresh thread-local namespace on every hook call.

    Gateway may reuse plugin modules across conversations; relying only on
    on_session_start is unsafe when context is compressed or sessions continue.
    """
    platform = (kwargs.get("platform") or "").strip()
    user_id = str(kwargs.get("user_id") or kwargs.get("sender_id") or "").strip()
    chat_id = str(kwargs.get("chat_id") or "").strip()
    chat_type = str(kwargs.get("chat_type") or "").strip()
    thread_id = str(kwargs.get("thread_id") or "").strip()
    if platform or user_id or chat_id:
        ns = _resolve_namespace(user_id=user_id, chat_id=chat_id, platform=platform,
                                chat_type=chat_type, thread_id=thread_id)
        set_current_namespace(ns)


# Protocol injection: first N turns get a brief auto-store reminder
_protocol_turn_count = 0
_PROTOCOL_MAX_TURNS = 8  # Inject for first 8 turns, then stop


def _pre_llm_call(user_message="", **kwargs):
    """Hook: auto-search Memory Graph before each LLM call.

    Extracts keywords from user message, searches Memory Graph,
    and returns relevant memories as injected context.
    Also injects auto-store protocol reminder for first N turns.
    """
    global _protocol_turn_count
    _apply_turn_namespace_from_kwargs(kwargs)
    user_text = _coerce_text(user_message)
    if not user_text or (len(user_text.strip()) < 5 and not _is_high_signal_short_message(user_text)):
        return None

    try:
        import asyncio

        cfg = _load_plugin_config()
        min_chars = int(cfg.get("auto_recall_min_message_chars", 5))
        if len(user_text.strip()) < min_chars and not _is_high_signal_short_message(user_text):
            return None

        recall_queries = _build_recall_queries(
            user_text,
            max_chars=int(cfg.get("auto_recall_max_query_chars", 320)),
            max_tokens=int(cfg.get("auto_recall_max_tokens", 12)),
        )
        if not recall_queries:
            return None

        # Search with whole-message and longest-token fallback queries. This is
        # generic semantic-recall plumbing, not keyword-specific routing.
        seen_uris = set()
        all_results = []
        ns = _resolve_runtime_namespace(kwargs)
        shared_scope = ns.split(":")[1:2] == ["group"] or bool(kwargs.get("chat_type") and kwargs.get("chat_type") != "dm")
        max_results = int(cfg.get("auto_recall_max_results", 5))
        for query in recall_queries:
            try:
                loop2 = asyncio.get_running_loop()
            except RuntimeError:
                loop2 = None
            if loop2 and loop2.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    r = pool.submit(asyncio.run, _async_scoped_search(query, namespace=ns, include_core=True, shared_scope=shared_scope, limit=max_results)).result(timeout=3)
            else:
                r = asyncio.run(_async_scoped_search(query, namespace=ns, include_core=True, shared_scope=shared_scope, limit=max_results))
            for item in r:
                uri = item.get("uri", "")
                if uri and uri not in seen_uris:
                    seen_uris.add(uri)
                    all_results.append(item)
            if len(all_results) >= max_results:
                break

        results = all_results

        if results:
            try:
                if loop2 and loop2.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        results = pool.submit(asyncio.run, _hydrate_recall_content(results, namespace=ns)).result(timeout=3)
                else:
                    results = asyncio.run(_hydrate_recall_content(results, namespace=ns))
            except Exception as e:
                logger.debug("Memory Graph content hydration failed: %s", e)

        if not results:
            return None

        # Format results as context within a configurable budget.
        # Important: snippets are often too short for operational memories
        # (credentials/tool routes, exact command shapes, beta headers). If the
        # search result exposes content, include as much as budget permits;
        # otherwise fall back to the snippet. This is generic and avoids
        # deployment-specific keyword routing.
        parts = []
        total_len = 0
        budget = int(cfg.get("auto_recall_context_chars", _context_budget()))
        for r in results[:max_results]:
            uri = r.get("uri", "")
            content = _coerce_text(r.get("content") or r.get("text") or "").strip()
            snippet = _coerce_text(r.get("snippet") or "").strip()
            body = content or snippet
            if not body:
                continue
            remaining = max(0, budget - total_len - len(uri) - 32)
            if remaining <= 80:
                break
            body = body[:remaining]
            line = f"[Memory Graph] {uri}: {body}"
            if total_len + len(line) > budget:
                break
            parts.append(line)
            total_len += len(line)

        if parts:
            context = "\n".join(parts)
            logger.debug("Memory Graph auto-recall: %d results", len(parts))
            return {"context": context}

    except Exception as e:
        logger.debug("Memory Graph pre_llm_call failed: %s", e)

    # Inject protocol reminder for first N turns of each session
    if _protocol_turn_count < _PROTOCOL_MAX_TURNS:
        _protocol_turn_count += 1
        return {"context": (
            "[Memory Graph Protocol] 你有结构化长期记忆系统(Memory Graph)。"
            "主动存储触发条件：1)用户透露新个人信息/偏好 2)技术结论 3)情感事件 "
            "4)发现过时记忆 5)想说'我理解了'时先memory_graph_create。"
            "用户纠正你=纠偏信号，立刻memory_graph_update。"
            "完整协议见 skill: memory-graph-protocol。"
        )}

    return None


_db_ready = False


# Keywords that signal memorable content worth storing
_MEMORABLE_KEYWORDS_CN = {
    "记住", "喜欢", "不喜欢", "讨厌", "偏好", "密码", "重要",
    "生日", "地址", "电话", "家人", "孩子", "老公", "老婆",
    "医院", "药", "病", "预约", "考试", "成绩",
}
_MEMORABLE_KEYWORDS_EN = {
    "remember", "prefer", "important", "birthday", "password",
    "address", "phone", "doctor", "appointment", "exam",
}


def _post_llm_call(user_message="", assistant_response="", platform="", **kwargs):
    """Hook: auto-store memorable conversations to Memory Graph.

    Lightweight keyword detection — if the user's message or the assistant's
    response contains memorable keywords, store a summary to MG.
    This ensures WeChat (and other platforms) retain key information even
    without Hindsight.
    """
    ns = get_current_namespace()
    if not ns:
        _apply_turn_namespace_from_kwargs(kwargs)
        ns = get_current_namespace()
    if not ns:
        return None

    # Only auto-store if memorable keywords are present
    user_text = _coerce_text(user_message)
    assistant_text = _coerce_text(assistant_response)
    combined = (user_text + " " + assistant_text).lower()
    has_memorable = False
    for kw in _MEMORABLE_KEYWORDS_CN | _MEMORABLE_KEYWORDS_EN:
        if kw in combined:
            has_memorable = True
            break
    if not has_memorable:
        return None

    try:
        import asyncio
        from agent.memory_graph.services.graph import GraphService

        # Build a concise memory snippet
        user_short = user_text[:150].strip()
        resp_short = assistant_text[:150].strip()
        content = f"用户: {user_short}\n回复: {resp_short}"

        async def _store():
            global _db_ready
            if not _db_ready:
                from agent.memory_graph.db import init_db
                await init_db()
                _db_ready = True
            gs = GraphService()
            try:
                await gs.create_memory(
                    parent_path="对话记录",
                    content=content,
                    priority=1,
                    title=f"对话 {user_short[:20]}",
                    domain="core",
                    namespace=ns,
                    auto_create_parents=True,
                )
                logger.debug("MG auto-stored conversation snippet for ns=%s", ns)
            except Exception as e:
                logger.debug("MG auto-store failed: %s", e)

        # Run in existing event loop or create one
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_store())
        except RuntimeError:
            asyncio.run(_store())

    except Exception as e:
        logger.debug("Memory Graph post_llm_call failed: %s", e)

    return None


async def _async_search(query: str):
    """Async search wrapper retained for direct callers; scoped to current namespace."""
    return await _async_scoped_search(query, namespace=get_current_namespace(), include_core=True)


async def _async_scoped_search(query: str, namespace: str = "", include_core: bool = True,
                               shared_scope: bool = False, limit: int = 3):
    """Search only the active namespace plus safe shared core.

    Never call SearchIndexer.search() without namespace here: that searches every
    namespace and caused private user memories to be injected in group chats.
    """
    global _db_ready
    from agent.memory_graph.services.search import SearchIndexer
    if not _db_ready:
        from agent.memory_graph.db import init_db
        await init_db()
        _db_ready = True
    si = SearchIndexer()
    merged = []
    seen = set()
    search_namespaces = []
    if namespace:
        search_namespaces.append(namespace)
    # Shared chats must never receive global core auto-recall. Even "public"
    # operational memories can contain stale or misclassified private snippets;
    # the agent can still explicitly call memory tools when needed.
    if include_core and not shared_scope:
        search_namespaces.append("")
    for ns in search_namespaces:
        for item in await si.search(query, namespace=ns, limit=limit):
            if shared_scope and ns == "" and not _core_item_safe_for_shared_chat(item):
                continue
            uri = item.get("uri") or f"{item.get('domain','core')}://{item.get('path','')}"
            key = (ns, uri)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def _core_item_safe_for_shared_chat(item: dict) -> bool:
    """Allow only public operational core memories into group-chat prompts."""
    path = str(item.get("path") or item.get("uri") or "")
    content = str(item.get("snippet") or item.get("content") or "")
    blocked_path_prefixes = ("用户档案/", "对话记录/", "hindsight/")
    if path.startswith(blocked_path_prefixes) or "用户档案/" in path:
        return False
    private_markers = (
        # Generic privacy markers only. Deployment-specific names/IDs belong in
        # config or private memory, never in the shared patch repository.
        "家庭", "父亲", "母亲", "爸爸", "妈妈", "妹妹", "姐姐", "哥哥", "弟弟",
        "经济", "收入", "生日", "学校", "地址", "电话", "身份证", "护照",
        "password", "token", "api key", "secret", "github_pat_", "ghp_", "sk-",
    )
    hay = path + "\n" + content
    return not any(marker in hay for marker in private_markers)


def register(ctx):
    """Plugin registration entry point."""
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("post_llm_call", _post_llm_call)
    logger.info("Memory Graph plugin registered (namespace isolation + auto-recall + auto-store)")
