"""RequestContext — thread/coroutine-safe context for namespace propagation.

Uses Python contextvars to ensure namespace is available throughout the
entire request lifecycle without explicit parameter passing.

Zero-default principle: if namespace is empty when writing user data,
the write is REJECTED, not silently written to core.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

@dataclass
class RequestContext:
    """Immutable request context bound to current thread/coroutine."""
    user_id: str = ""
    chat_id: str = ""
    platform: str = ""
    namespace: str = ""
    session_id: str = ""
    is_admin: bool = False

    @property
    def effective_namespace(self) -> str:
        """Get the namespace to use for writes. Never returns empty for user data."""
        return self.namespace


# Context variable — bound to current thread/coroutine
_ctx: ContextVar[Optional[RequestContext]] = ContextVar('request_context', default=None)

# Paths that are considered user-private (require non-empty namespace)
USER_PRIVATE_PREFIXES = (
    "用户档案/",
    "user_profile/",
    "个人/",
    "偏好/",
    "成绩/",
    "家庭/",
    "学习状态/",
    "考试/",
)


def set_context(ctx: RequestContext) -> None:
    """Set the request context for current thread/coroutine."""
    _ctx.set(ctx)


def get_context() -> Optional[RequestContext]:
    """Get the current request context. Returns None if not set."""
    return _ctx.get()


def get_namespace() -> str:
    """Get current namespace. Returns empty string if no context."""
    ctx = _ctx.get()
    return ctx.effective_namespace if ctx else ""


def is_user_private_path(path: str) -> bool:
    """Check if a path contains user-private data."""
    return any(path.startswith(p) for p in USER_PRIVATE_PREFIXES)


def require_namespace_for_path(path: str) -> str:
    """Get namespace for a path, raising if user data has no namespace.

    Zero-default principle: user data MUST have namespace.
    """
    if is_user_private_path(path):
        ns = get_namespace()
        if not ns:
            raise ValueError(
                f"Cannot write user data to path '{path}': no namespace set. "
                f"User data requires namespace (e.g. 'telegram:<chat_id>'). "
                f"Configure default_terminal_user in config.yaml."
            )
        return ns
    return get_namespace()  # Non-user paths can be empty (core)


def reset_context() -> None:
    """Reset context (for testing or session end)."""
    _ctx.set(None)
