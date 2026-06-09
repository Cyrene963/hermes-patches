import importlib
import pathlib
import sys

from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _load_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_SESSION_SECRET", "test-session-secret")
    for name in [
        "auth",
        "namespace_middleware",
        "main",
    ]:
        sys.modules.pop(name, None)
    auth = importlib.import_module("auth")
    auth.create_user("admin", "secret", namespace="", display_name="Admin")
    auth.create_user("alice", "secret", namespace="telegram:alice", display_name="Alice")
    main = importlib.import_module("main")
    return main, auth


def test_protected_api_requires_login(monkeypatch, tmp_path):
    main, _auth = _load_app(monkeypatch, tmp_path)
    client = TestClient(main.app)

    assert client.get("/api/browse/search?q=test").status_code == 401
    assert client.get("/api/browse/namespaces").status_code == 401
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings", json={"auto_open_browser": False}).status_code == 401
    assert client.get("/api/maintenance/access-logs/stats").status_code == 401
    assert client.request("DELETE", "/api/maintenance/access-logs", json={"keep_days": 0}).status_code == 401


def test_invalid_session_fails_closed(monkeypatch, tmp_path):
    main, _auth = _load_app(monkeypatch, tmp_path)
    client = TestClient(main.app)

    response = client.get("/api/browse/search?q=test", cookies={"mg_session": "not-a-valid-session"})

    assert response.status_code == 403
    assert "Invalid or expired session" in response.text


def test_invalid_session_does_not_block_public_shell(monkeypatch, tmp_path):
    main, _auth = _load_app(monkeypatch, tmp_path)
    client = TestClient(main.app)

    shell = client.get("/", cookies={"mg_session": "not-a-valid-session"})
    auth_probe = client.get("/api/auth/me", cookies={"mg_session": "not-a-valid-session"})

    assert shell.status_code == 200
    assert "text/html" in shell.headers.get("content-type", "")
    assert auth_probe.status_code == 200
    assert auth_probe.json() == {"authenticated": False}


def test_settings_requires_admin(monkeypatch, tmp_path):
    main, auth = _load_app(monkeypatch, tmp_path)
    client = TestClient(main.app)
    alice_cookie = {"mg_session": auth.create_session_token("alice")}
    admin_cookie = {"mg_session": auth.create_session_token("admin")}

    assert client.get("/api/settings", cookies=alice_cookie).status_code == 403
    assert client.put("/api/settings", json={"auto_open_browser": False}, cookies=alice_cookie).status_code == 403

    response = client.get("/api/settings", cookies=admin_cookie)
    assert response.status_code == 200
    assert "settings" in response.json()


def test_regular_user_namespaces_are_not_enumerated(monkeypatch, tmp_path):
    main, auth = _load_app(monkeypatch, tmp_path)
    client = TestClient(main.app)
    alice_cookie = {"mg_session": auth.create_session_token("alice")}

    response = client.get("/api/browse/namespaces", cookies=alice_cookie)

    assert response.status_code == 200
    assert response.json() == ["", "telegram:alice"]
