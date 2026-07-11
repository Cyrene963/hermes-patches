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
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local storage for current namespace context
_context = threading.local()
_contract_lock = threading.Lock()
_turn_contracts: dict[str, object] = {}
_turn_tool_events: dict[str, list[dict]] = {}
_turn_contract_verdicts: dict[str, dict] = {}
_turn_repair_fingerprints: dict[str, list[str]] = {}

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
    planned_queries = _build_semantic_recall_plan_queries(msg)
    queries.extend(planned_queries)
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


def _build_semantic_recall_plan_queries(user_message: str) -> list[str]:
    """Build generic intent/metadata recall queries for high-signal turns.

    The durable fix is not one branch per event class. High-value memories should
    carry when-to-recall semantics: user intent, applicable domains, target
    functions, disclosure triggers, reject gates, counterexamples, and readback
    queries. Until those fields are first-class indexed metadata, this planner
    approximates the same behavior by deriving a small intent plan from the live
    turn and searching for those generic metadata concepts plus message facets.
    """
    import re

    text = _coerce_text(user_message).strip()
    if not text:
        return []
    lowered = text.lower()

    signal_patterns = {
        "continuation": ("继续", "接着", "之前", "刚才", "上次", "换窗口", "换上下文", "where we left", "previous"),
        "correction": ("不对", "不是", "错", "错错错", "你又", "别再", "纠正", "扣分", "犯", "wrong", "mistake"),
        "memory_failure": ("不记得", "忘", "记忆", "外置大脑", "数字替身", "recall", "memory"),
        "evaluation": ("分数", "扣分", "评估", "预估", "前五", "标准", "验收", "quality", "score", "rubric"),
        "implementation": ("去做", "去修", "修复", "代码", "架构", "补丁", "测试", "验证", "实现", "deploy", "patch", "test"),
        "creation": ("写作", "作文", "文章", "小说", "图片", "设计", "表达", "writing", "draft"),
    }
    intents = [name for name, markers in signal_patterns.items() if any(marker in lowered for marker in markers)]
    high_signal = bool(intents) or _is_high_signal_short_message(text)
    if not high_signal:
        return []

    token_re = r"[A-Za-z0-9_]{3,}|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,}"
    tokens = re.findall(token_re, text)
    facets = sorted({t.strip().lower() for t in tokens if t.strip()}, key=lambda s: (-len(s), s))[:8]
    facet_text = " ".join(facets)

    metadata_terms = [
        "适用场景 触发语义 用户意图 目标函数 readback disclosure when to recall",
        "执行标准 反例 reject gate 验证方法 future recall",
    ]
    intent_terms = {
        "continuation": "active workstream previous context continuity handoff",
        "correction": "用户纠正 防复发 错误模式 reject gate",
        "memory_failure": "主动召回 自动按需存取 记忆失败 readback 路由验证",
        "evaluation": "评分标准 rubric 质量标准 目标函数 验收",
        "implementation": "通用方案 架构修复 测试验证 patch workflow",
        "creation": "创作标准 写作方法论 表达偏好 target function",
    }

    queries = []
    if facet_text:
        queries.append(f"{facet_text} {' '.join(intents)} target function disclosure readback")
        queries.extend(f"{facet_text} {term}" for term in metadata_terms)
        queries.extend(f"{facet_text} {intent_terms[name]}" for name in intents if name in intent_terms)
    else:
        queries.extend(metadata_terms)
        queries.extend(intent_terms[name] for name in intents if name in intent_terms)

    return queries[:6]


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
    # A personal_group is a Telegram group used as one authorized user's
    # private multi-window. The gateway rewrites chat_id to that user's id and
    # keeps the physical group in thread_id=group:<id>, so it must share the DM
    # namespace rather than becoming a shared group memory scope.
    if ct == "personal_group":
        return False
    if ct and ct != "dm":
        return True
    # Telegram/Discord group IDs often differ from sender IDs even if chat_type
    # is missing from an older gateway hook payload.
    return bool(user_id and chat_id and str(user_id) != str(chat_id))


def _default_terminal_user() -> str:
    try:
        import yaml
        cfg_path = Path.home() / ".hermes" / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            return str((cfg.get("memory_graph") or {}).get("default_terminal_user") or "").strip()
    except Exception:
        pass
    return ""


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
    default_user = _default_terminal_user()
    if plat.lower() in {"cli", "terminal"} and default_user:
        if not identifier or identifier == default_user:
            return f"telegram:{default_user}"
    if not identifier:
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


def _merge_contract_evidence(contract_results, recall_results, limit=12):
    """Merge bounded evidence lanes without letting one hide the other."""
    merged = []
    seen = set()
    for item in list(contract_results or []) + list(recall_results or []):
        uri = str(item.get("uri") or "")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


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
        contract_queries = []
        try:
            from agent.memory_task_contract import build_contract_recall_queries

            contract_queries = build_contract_recall_queries(user_text)
        except Exception:
            logger.debug("Memory contract query planning failed", exc_info=True)
        if not recall_queries and not contract_queries:
            return None

        # Search with whole-message and longest-token fallback queries. This is
        # generic semantic-recall plumbing, not keyword-specific routing.
        seen_uris = set()
        all_results = []
        ns = _resolve_runtime_namespace(kwargs)
        chat_type = str(kwargs.get("chat_type") or "").strip().lower()
        shared_scope = ns.split(":")[1:2] == ["group"] or chat_type in {
            "group", "supergroup", "channel", "thread",
        }
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
        # Contract evidence has its own small lane. It must run even when normal
        # recall already filled max_results, otherwise relation/preference queries
        # are generated but silently skipped by the early break above.
        contract_results = []
        contract_seen = set()
        for query in contract_queries:
            try:
                if loop2 and loop2.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        lane = pool.submit(
                            asyncio.run,
                            _async_scoped_search(
                                query, namespace=ns, include_core=True,
                                shared_scope=shared_scope, limit=5,
                            ),
                        ).result(timeout=3)
                else:
                    lane = asyncio.run(_async_scoped_search(
                        query, namespace=ns, include_core=True,
                        shared_scope=shared_scope, limit=5,
                    ))
                for item in lane:
                    uri = item.get("uri", "")
                    if uri and uri not in contract_seen:
                        contract_seen.add(uri)
                        contract_results.append(item)
            except Exception:
                logger.debug("Memory contract evidence query failed: %s", query, exc_info=True)

        if results or contract_results:
            try:
                hydrate_targets = results + [
                    item for item in contract_results
                    if item.get("uri") not in {row.get("uri") for row in results}
                ]
                if loop2 and loop2.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        hydrated = pool.submit(asyncio.run, _hydrate_recall_content(hydrate_targets, namespace=ns)).result(timeout=3)
                else:
                    hydrated = asyncio.run(_hydrate_recall_content(hydrate_targets, namespace=ns))
                hydrated_by_uri = {item.get("uri"): item for item in hydrated}
                results = [hydrated_by_uri.get(item.get("uri"), item) for item in results]
                contract_results = [hydrated_by_uri.get(item.get("uri"), item) for item in contract_results]
            except Exception as e:
                logger.debug("Memory Graph content hydration failed: %s", e)

        continuity_prompt = ""
        try:
            from agent.active_workstream import resolve_active_workstream

            workstream = resolve_active_workstream(
                user_text,
                user_id=str(kwargs.get("user_id") or kwargs.get("sender_id") or ""),
                current_session_id=str(kwargs.get("session_id") or ""),
                source=str(kwargs.get("platform") or "") or None,
            )
            continuity_prompt = workstream.to_prompt()
        except Exception:
            logger.debug("Active workstream recovery failed", exc_info=True)

        if not results and not contract_results and not continuity_prompt:
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

        if continuity_prompt:
            parts.append(continuity_prompt)
            total_len += len(continuity_prompt)

        if parts:
            context = "\n".join(parts)
            delete_prompt = ""
            try:
                strong_delete = re.search(
                    r"(?:忘记|删除|移除|清除|forget|delete|remove)\s*(?:这条|this memory|memory)?",
                    user_text,
                    re.I,
                )
                explicit_uris = re.findall(r"[A-Za-z0-9_.-]+://[^\s，。！？,;]+", user_text)
                if strong_delete and len(explicit_uris) == 1 and ns and not shared_scope:
                    from tools import memory_graph_tool
                    from agent.memory_lifecycle import load_delete_grant_authority

                    uri = explicit_uris[0].rstrip(".?!")
                    node = json.loads(memory_graph_tool._read({"uri": uri, "namespace": ns}))
                    children = json.loads(memory_graph_tool._list({"uri": uri, "namespace": ns}))
                    if not node.get("error") and not children.get("error") and not children.get("children"):
                        grant = load_delete_grant_authority().issue(
                            uri=uri, namespace=ns, user_message=user_text,
                        )
                        delete_prompt = (
                            "[Authorized memory deletion: the host verified one exact private leaf URI "
                            f"from this user turn. Call memory_lifecycle_delete with uri={uri!r}, "
                            f"namespace={ns!r}, candidate_count=1, delete_grant={grant!r}. "
                            "Do not expose or reuse this grant. Verify deletion readback before claiming completion.]"
                        )
            except Exception:
                logger.debug("Delete-grant planning failed", exc_info=True)
            if delete_prompt:
                context = context + "\n\n" + delete_prompt
            try:
                from agent.memory_task_contract import build_task_memory_contract

                contract_evidence = _merge_contract_evidence(contract_results, results)
                contract = build_task_memory_contract(
                    user_text,
                    contract_evidence,
                    namespace=ns,
                )
                contract_prompt = contract.to_prompt()
                proactive_prompt = ""
                try:
                    from agent.proactive_need import decide_proactive_need

                    proactive = decide_proactive_need(
                        user_text,
                        obligations=contract.obligations,
                        active_todos=kwargs.get("active_todos") or [],
                        evidence_uris=contract.evidence_uris,
                        task_verified_complete=bool(kwargs.get("task_verified_complete", False)),
                    )
                    if proactive.action == "act":
                        proactive_prompt = (
                            "[Proactive action policy: Evidence supports acting now. "
                            f"Next bounded step: {proactive.next_step}. Execute it through the normal tool safety and verification gates.]"
                        )
                    elif proactive.action == "diagnose":
                        proactive_prompt = (
                            "[Proactive action policy: Perform bounded read-only diagnosis now. "
                            "Do not mutate state unless the user separately authorizes the write scope.]"
                        )
                    elif proactive.action == "clarify":
                        proactive_prompt = (
                            "[Proactive action policy: The next step has material side effects and lacks scoped authorization. "
                            "Ask only for the target/scope needed before acting.]"
                        )
                except Exception:
                    logger.debug("Proactive need policy failed", exc_info=True)
                session_id = str(kwargs.get("session_id") or "")
                if session_id:
                    with _contract_lock:
                        _turn_contracts[session_id] = contract
                        _turn_tool_events[session_id] = []
                        _turn_repair_fingerprints[session_id] = []
                if contract_prompt:
                    context = context + "\n\n" + contract_prompt
                if proactive_prompt:
                    context = context + "\n\n" + proactive_prompt
            except Exception as contract_exc:
                logger.debug("Memory task contract compilation failed: %s", contract_exc)
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


def _post_llm_call(user_message="", assistant_response="", platform="", **kwargs):
    """Post-turn plugin hook.

    Durable writes are owned exclusively by the full MemoryWritePipeline in
    conversation_loop. Keeping a second keyword-based Graph writer here caused
    duplicate raw conversation snippets, assistant-text pollution, and writes
    without classification/readback/changesets.
    """
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


def _safe_tool_result_summary(result) -> dict:
    """Keep compliance evidence bounded and avoid persisting raw tool payloads."""
    if isinstance(result, dict):
        summary = {
            key: result.get(key)
            for key in ("success", "exit_code", "status", "message_id", "error")
            if key in result
        }
        output = result.get("output") or result.get("content") or ""
        if output:
            summary["output"] = str(output)[:500]
        return summary
    return {"output": str(result or "")[:500]}


def _post_tool_call(tool_name="", args=None, result=None, session_id="", **kwargs):
    session_key = str(session_id or kwargs.get("task_id") or "")
    if not session_key:
        return None
    with _contract_lock:
        if session_key not in _turn_contracts:
            return None
        events = _turn_tool_events.setdefault(session_key, [])
        events.append({
            "tool_name": str(tool_name or ""),
            "result": _safe_tool_result_summary(result),
        })
        del events[:-40]
        # Any new tool evidence invalidates a verdict cached by an earlier
        # completion attempt in this same turn.
        _turn_contract_verdicts.pop(session_key, None)
    return None


def _pre_verify_contract(session_id="", attempt=0, final_response="", **kwargs):
    """Keep the live tool loop running while required memory obligations fail."""
    session_key = str(session_id or "")
    if not session_key:
        return None
    with _contract_lock:
        contract = _turn_contracts.get(session_key)
        events = list(_turn_tool_events.get(session_key, []))
    if contract is None:
        return None
    try:
        from agent.memory_task_contract import evaluate_contract, plan_contract_repair

        verdict = evaluate_contract(
            contract,
            events,
            active_todos=kwargs.get("active_todos") or [],
        )
        with _contract_lock:
            prior_repairs = list(_turn_repair_fingerprints.get(session_key, []))
        repair = plan_contract_repair(verdict, prior_fingerprints=prior_repairs)
    except Exception:
        logger.debug("Memory contract pre_verify evaluation failed", exc_info=True)
        return None
    if verdict.get("passed"):
        return None
    failures = []
    for item in verdict.get("obligations", []):
        if not item.get("passed"):
            failures.append(f"{item.get('id')}: {', '.join(item.get('missing', []))}")
    if not failures:
        return None
    if repair.get("action") == "block":
        return {
            "action": "continue",
            "message": (
                "[System: Bounded contract repair is exhausted for the unchanged failure "
                f"fingerprint `{repair.get('fingerprint')}`. Do not repeat the same tool action. "
                "State the concrete external blocker and preserve the NOT VERIFIED status.]"
            ),
        }
    fingerprint = str(repair.get("fingerprint") or "")
    if fingerprint:
        with _contract_lock:
            history = _turn_repair_fingerprints.setdefault(session_key, [])
            history.append(fingerprint)
            del history[:-8]
    actions = list(repair.get("actions") or [])
    return {
        "action": "continue",
        "message": (
            "[System: Do not stop or ask whether to continue. The current task's "
            "evidence-backed memory contract is still incomplete. Execute this bounded "
            f"repair plan (attempt {repair.get('attempt', 1)}/2) now:\n- "
            + "\n- ".join(actions or failures)
            + "\nAfter each action, inspect the real result. Do not repeat an unchanged failed action.]"
        ),
    }


def _write_contract_audit(session_id: str, contract, verdict: dict) -> None:
    try:
        log_dir = Path.home() / ".hermes" / "logs" / "memory_contracts"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": session_id,
            "namespace": getattr(contract, "namespace", ""),
            "query": getattr(contract, "query", "")[:500],
            "contract": contract.to_dict(),
            "verdict": verdict,
        }
        with (log_dir / "contracts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        logger.debug("Memory task contract audit write failed", exc_info=True)


def _post_llm_contract_verdict(session_id="", assistant_response="", **kwargs):
    """Evaluate obligations against actual tool evidence and persist the verdict."""
    session_key = str(session_id or "")
    if not session_key:
        return None
    with _contract_lock:
        contract = _turn_contracts.pop(session_key, None)
        events = _turn_tool_events.pop(session_key, [])
        prior_verdict = _turn_contract_verdicts.pop(session_key, None)
        _turn_repair_fingerprints.pop(session_key, None)
    if contract is None:
        return None
    try:
        from agent.memory_task_contract import evaluate_contract

        verdict = prior_verdict or evaluate_contract(contract, events)
        _write_contract_audit(session_key, contract, verdict)
        if not verdict.get("passed"):
            logger.warning(
                "Memory task contract unmet for session=%s obligations=%s",
                session_key,
                [item.get("id") for item in verdict.get("obligations", []) if not item.get("passed")],
            )
    except Exception:
        logger.debug("Memory task contract evaluation failed", exc_info=True)
    return None


def _transform_contract_output(response_text="", session_id="", **kwargs):
    """Prevent a clean-completion claim when required memory obligations failed."""
    session_key = str(session_id or "")
    if not session_key:
        return None
    with _contract_lock:
        verdict = _turn_contract_verdicts.get(session_key)
        contract = _turn_contracts.get(session_key)
        events = list(_turn_tool_events.get(session_key, []))
    # transform_llm_output fires before post_llm_call, so evaluate here when the
    # post-turn observer has not run yet. post_llm_call will consume and audit.
    if verdict is None and contract is not None:
        try:
            from agent.memory_task_contract import evaluate_contract

            verdict = evaluate_contract(contract, events)
            with _contract_lock:
                _turn_contract_verdicts[session_key] = verdict
        except Exception:
            logger.debug("Memory contract output gate evaluation failed", exc_info=True)
            return None
    if not verdict or verdict.get("passed"):
        return None
    failures = []
    for item in verdict.get("obligations", []):
        if item.get("passed"):
            continue
        missing = ", ".join(str(value) for value in item.get("missing", []))
        failures.append(f"- {item.get('id')}: {missing or 'required evidence missing'}")
    if not failures:
        return None
    footer = (
        "[Memory contract: NOT VERIFIED]\n"
        + "\n".join(failures)
        + "\nThe response above must not be treated as a fully verified completion claim."
    )
    return str(response_text or "").rstrip() + "\n\n" + footer


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
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("pre_verify", _pre_verify_contract)
    ctx.register_hook("transform_llm_output", _transform_contract_output)
    # Keep automatic storage and behavioral verdicting as separate observers.
    ctx.register_hook("post_llm_call", _post_llm_call)
    ctx.register_hook("post_llm_call", _post_llm_contract_verdict)
    logger.info("Memory Graph plugin registered (namespace isolation + auto-recall + task contracts + auto-store)")
