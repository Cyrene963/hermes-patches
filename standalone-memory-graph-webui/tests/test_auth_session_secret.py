import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _reload_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.modules.pop("auth", None)
    return importlib.import_module("auth")


def test_session_secret_prefers_explicit_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_GRAPH_SESSION_SECRET", "explicit-secret")
    auth = _reload_auth(monkeypatch, tmp_path)

    assert auth.SESSION_SECRET == "explicit-secret"
    assert not (tmp_path / ".hermes" / "memory_graph_session_secret").exists()


def test_session_secret_is_generated_persisted_and_reused(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMORY_GRAPH_SESSION_SECRET", raising=False)
    monkeypatch.delenv("MG_SESSION_SECRET", raising=False)
    auth = _reload_auth(monkeypatch, tmp_path)
    secret_path = tmp_path / ".hermes" / "memory_graph_session_secret"

    assert auth.SESSION_SECRET
    assert auth.SESSION_SECRET != "mg-default-change-me-in-prod"
    assert secret_path.read_text(encoding="utf-8").strip() == auth.SESSION_SECRET
    assert secret_path.stat().st_mode & 0o777 == 0o600

    sys.modules.pop("auth", None)
    auth_reloaded = importlib.import_module("auth")
    assert auth_reloaded.SESSION_SECRET == auth.SESSION_SECRET
