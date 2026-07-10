import json

from scripts.memory_os_controller_lease import acquire, release, validate_handoff


def test_single_writer_and_release(monkeypatch, tmp_path):
    import scripts.memory_os_controller_lease as lease
    monkeypatch.setattr(lease, "LOCK_DIR", tmp_path / "lock")
    assert acquire("a", ttl=300)["acquired"]
    blocked = acquire("b", ttl=300)
    assert blocked["acquired"] is False
    assert blocked["holder"] == "a"
    assert release("b")["released"] is False
    assert release("a")["released"] is True
    assert acquire("b", ttl=300)["acquired"]


def test_expired_lease_is_reclaimed(monkeypatch, tmp_path):
    import scripts.memory_os_controller_lease as lease
    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "lease.json").write_text(json.dumps({"owner": "dead", "expires_at": 1}))
    monkeypatch.setattr(lease, "LOCK_DIR", lock)
    assert acquire("new", ttl=300)["acquired"]
    assert json.loads((lock / "lease.json").read_text())["owner"] == "new"


def test_handoff_requires_all_verification_fields(tmp_path):
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps({"commit": "abc", "tests_passed": True}))
    assert validate_handoff(path)["valid"] is False
    path.write_text(json.dumps({
        "commit": "abc",
        "tests_passed": True,
        "fresh_replay_passed": True,
        "remote_parity": True,
        "live_restart_required": True,
    }))
    assert validate_handoff(path)["valid"] is True
