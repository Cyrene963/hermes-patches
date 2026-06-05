"""Multi-user authentication for Memory Graph dashboard.

User store: ~/.hermes/memory_graph_users.json
Session: signed cookies via itsdangerous
"""
import json
import os
import secrets
from pathlib import Path
from typing import Optional

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature

USERS_FILE = Path.home() / ".hermes" / "memory_graph_users.json"
SESSION_SECRET = os.environ.get("MG_SESSION_SECRET", "mg-default-change-me-in-prod")
SESSION_MAX_AGE = 86400 * 7  # 7 days

_serializer = URLSafeTimedSerializer(SESSION_SECRET)


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text())


def _save_users(data: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_user(username: str, password: str, namespace: str,
                display_name: str = "", platform: str = "", platform_id: str = "") -> dict:
    """Create a new user. Returns user dict or raises ValueError."""
    users = _load_users()
    if username in users:
        raise ValueError(f"User '{username}' already exists")
    user = {
        "username": username,
        "password_hash": hash_password(password),
        "namespace": namespace,
        "display_name": display_name or username,
        "platform": platform,
        "platform_id": platform_id,
    }
    users[username] = user
    _save_users(users)
    return {k: v for k, v in user.items() if k != "password_hash"}


def authenticate(username: str, password: str) -> Optional[dict]:
    """Verify credentials. Returns user dict (without hash) or None."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_user(username: str) -> Optional[dict]:
    """Get user by username (without hash)."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def list_users() -> list:
    """List all users (without hashes)."""
    users = _load_users()
    return [{k: v for k, v in u.items() if k != "password_hash"} for u in users.values()]


def delete_user(username: str) -> bool:
    users = _load_users()
    if username not in users:
        return False
    del users[username]
    _save_users(users)
    return True


def change_password(username: str, new_password: str) -> bool:
    users = _load_users()
    if username not in users:
        return False
    users[username]["password_hash"] = hash_password(new_password)
    _save_users(users)
    return True


def create_session_token(username: str) -> str:
    return _serializer.dumps(username)


def verify_session_token(token: str) -> Optional[str]:
    """Returns username if valid, None if expired/invalid."""
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
