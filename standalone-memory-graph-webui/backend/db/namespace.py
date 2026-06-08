"""
Namespace context for multi-agent memory isolation.

Uses contextvars to pass namespace/admin state implicitly through async call
chains. For HTTP mode, NamespaceMiddleware sets both values per request from
the authenticated user plus optional admin namespace override.
"""

import contextvars
import os

_namespace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "namespace", default=os.getenv("NAMESPACE", "")
)
_is_admin: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "is_admin", default=os.getenv("MG_IS_ADMIN", "false").lower() == "true"
)


def get_namespace() -> str:
    return _namespace.get()


def set_namespace(ns: str) -> contextvars.Token[str]:
    return _namespace.set(ns)


def reset_namespace(token: contextvars.Token[str]) -> None:
    _namespace.reset(token)


def get_is_admin() -> bool:
    return _is_admin.get()


def set_is_admin(value: bool) -> contextvars.Token[bool]:
    return _is_admin.set(bool(value))


def reset_is_admin(token: contextvars.Token[bool]) -> None:
    _is_admin.reset(token)
