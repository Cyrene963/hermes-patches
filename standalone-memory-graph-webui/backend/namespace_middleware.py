"""
ASGI middleware for namespace extraction.

Integrates with session-based auth: admin users get namespace="" (see all),
regular users get their configured namespace.

Priority: session user namespace > X-Namespace header > namespace query param > default "".
"""

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from db.namespace import set_namespace, set_is_admin

from auth import verify_session_token, get_user

_COOKIE_NAME = "mg_session"
_RESERVED_NAMESPACES = frozenset({"_ns_default_0x7f3a9e"})


def _validate_namespace(ns: str) -> str | None:
    """Return an error message if *ns* is reserved, else None."""
    if ns in _RESERVED_NAMESPACES:
        return f"Namespace '{ns}' is reserved and cannot be used."
    return None


async def _send_400(send, detail: str) -> None:
    import json
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": 400, "headers": [
        [b"content-type", b"application/json"],
        [b"content-length", str(len(body)).encode()],
    ]})
    await send({"type": "http.response.body", "body": body})


async def _send_403(send, detail: str) -> None:
    import json
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": 403, "headers": [
        [b"content-type", b"application/json"],
        [b"content-length", str(len(body)).encode()],
    ]})
    await send({"type": "http.response.body", "body": body})


class NamespaceMiddleware:
    """ASGI middleware that extracts the namespace from auth context or request.

    For authenticated users: admin gets namespace="" (sees all), regular users
    get their configured namespace.
    Falls back to header/query param for unauthenticated requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)

        # Resolve namespace from authenticated user and optional override.
        # Important: admin is a permission bit, not the default browsing scope.
        # Default browsing must mean shared public namespace ("") so the UI's
        # "(default)" selector never silently shows a user's private graph.
        ns = ""
        is_admin = False
        token = request.cookies.get(_COOKIE_NAME)
        if token:
            username = verify_session_token(token)
            if username:
                user = get_user(username)
                if user:
                    user_is_admin = user.get("role") == "admin" or user.get("username") == "admin"
                    override_ns = request.headers.get("x-namespace") or request.query_params.get("namespace")
                    if override_ns is not None:
                        # Explicit namespace selection. Admin may use the reserved
                        # maintenance scope "__all__"; normal reads stay scoped.
                        if user_is_admin and override_ns == "__all__":
                            ns = ""
                            is_admin = True
                        elif user_is_admin:
                            ns = override_ns
                            is_admin = False
                        else:
                            # Regular users may browse shared public ("") or their own
                            # namespace only. Never let a client-controlled header or
                            # localStorage-selected namespace jump into another user's
                            # private graph.
                            own_ns = user.get("namespace", "")
                            if override_ns not in {"", own_ns}:
                                await _send_403(send, "Namespace override is outside current user's scope.")
                                return
                            ns = override_ns or own_ns
                            is_admin = False
                    elif not user_is_admin:
                        # Regular users default to their own namespace.
                        ns = user.get("namespace", "")
                        is_admin = False
                    else:
                        # Admin default is shared public, not private and not all.
                        ns = ""
                        is_admin = False

        # Fallback to header/query param if no auth-based namespace
        if not ns and not token:
            ns = request.headers.get("x-namespace", "")
        if not ns and not token:
            ns = request.query_params.get("namespace", "")

        if err := _validate_namespace(ns):
            await _send_400(send, err)
            return

        set_namespace(ns)
        set_is_admin(is_admin)
        await self.app(scope, receive, send)
