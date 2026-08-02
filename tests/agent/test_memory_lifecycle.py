from agent.memory_lifecycle import DeleteGrantAuthority, MemoryLifecycleManager, bind_delete_turn, decide_delete_intent


def request(**overrides):
    data = {"uri":"core://neutral/item","namespace":"test:private","source":"user_direct","explicit_user_authorization":True,"candidate_count":1,"is_leaf":True,"authorization_evidence":"forget exact neutral item"}
    data.update(overrides); return data


def test_delete_policy_executes_only_exact_private_leaf():
    assert decide_delete_intent(request()).action == "execute"


def test_delete_policy_archives_maintenance_candidates():
    assert decide_delete_intent(request(source="maintenance", explicit_user_authorization=False)).action == "archive"


def test_delete_policy_refuses_subtree_and_missing_namespace():
    assert decide_delete_intent(request(is_leaf=False)).action == "refuse"
    assert decide_delete_intent(request(namespace="")).action == "refuse"


def test_delete_policy_clarifies_ambiguous_or_inferred_requests():
    assert decide_delete_intent(request(candidate_count=2)).action == "clarify"
    assert decide_delete_intent(request(source="agent_inference", explicit_user_authorization=False)).action == "clarify"


def manager(tmp_path):
    store = {"core://neutral/item":{"content":"neutral value","priority":2}}
    def read(uri, ns): return store.get(uri)
    def children(uri, ns): return []
    def delete(uri, ns): return store.pop(uri, None) is not None
    def create(domain, parent, title, content, priority):
        uri=f"{domain}://{parent + '/' if parent else ''}{title}";store[uri]={"content":content,"priority":priority};return {"uri":uri}
    def update(uri, ns, content, priority): store[uri]={"content":content,"priority":priority};return {"uri":uri,"updated":True}
    return MemoryLifecycleManager(read=read,children=children,delete=delete,create=create,update=update,journal_root=tmp_path),store


def test_delete_readback_and_idempotent_rollback(tmp_path):
    mgr, store = manager(tmp_path)
    result = mgr.delete_leaf(request())
    changeset = next(tmp_path.rglob("*.json"))
    assert changeset.stat().st_mode & 0o777 == 0o600
    assert changeset.parent.stat().st_mode & 0o777 == 0o700
    assert result["ok"] and result["readback_absent"] and not store
    restored = mgr.rollback(changeset_id=result["changeset_id"],namespace="test:private")
    assert restored["ok"] and restored["readback_restored"]
    again = mgr.rollback(changeset_id=result["changeset_id"],namespace="test:private")
    assert again == {"ok":True,"already_restored":True,"uri":"core://neutral/item"}


def test_delete_refuses_non_leaf_without_calling_delete(tmp_path):
    called=[]
    mgr=MemoryLifecycleManager(read=lambda *_:{"content":"x"},children=lambda *_:[{"uri":"child"}],delete=lambda *_:called.append(1),create=lambda *_:{},journal_root=tmp_path)
    result=mgr.delete_leaf(request())
    assert not result["ok"] and result["decision"]["action"]=="refuse" and not called


def test_namespace_mismatch_cannot_rollback(tmp_path):
    mgr,_=manager(tmp_path);result=mgr.delete_leaf(request())
    assert mgr.rollback(changeset_id=result["changeset_id"],namespace="other:private")["error"]=="changeset_not_found"


def test_create_and_update_changesets_rollback_idempotently(tmp_path):
    mgr,store=manager(tmp_path)
    create_id=mgr.record_create(uri="core://neutral/item",namespace="test:private",after=store["core://neutral/item"])
    removed=mgr.rollback(changeset_id=create_id,namespace="test:private")
    assert removed["ok"] and removed["readback_absent"] and not store
    assert mgr.rollback(changeset_id=create_id,namespace="test:private")["already_rolled_back"]

    store["core://neutral/item"]={"content":"before","priority":1}
    before=dict(store["core://neutral/item"]);store["core://neutral/item"]={"content":"after","priority":2}
    update_id=mgr.record_update(uri="core://neutral/item",namespace="test:private",before=before,after=store["core://neutral/item"])
    restored=mgr.rollback(changeset_id=update_id,namespace="test:private")
    assert restored["ok"] and restored["readback_restored"] and store["core://neutral/item"]==before
    assert mgr.rollback(changeset_id=update_id,namespace="test:private")["already_restored"]


def test_stale_leaf_archive_and_rollback_are_namespace_safe(tmp_path):
    mgr, store = manager(tmp_path)
    result = mgr.archive_stale_leaf(
        uri="core://neutral/item", namespace="test:private", stale_days=91,
        threshold_days=90, last_accessed_at="2026-01-01T00:00:00+00:00",
    )
    assert result["ok"] and result["readback_archived"]
    assert "core://neutral/item" not in store
    assert store["archive://core/neutral/item"]["content"] == "neutral value"
    changeset = next(tmp_path.rglob("*.json"))
    assert changeset.stat().st_mode & 0o777 == 0o600
    assert mgr.rollback(changeset_id=result["changeset_id"], namespace="other:private")["error"] == "changeset_not_found"
    restored = mgr.rollback(changeset_id=result["changeset_id"], namespace="test:private")
    assert restored["ok"] and restored["readback_restored"]
    assert "archive://core/neutral/item" not in store
    assert mgr.rollback(changeset_id=result["changeset_id"], namespace="test:private")["already_restored"]


def test_archive_abstains_without_access_evidence_or_for_non_leaf(tmp_path):
    mgr, store = manager(tmp_path)
    missing = mgr.archive_stale_leaf(
        uri="core://neutral/item", namespace="test:private", stale_days=100,
        threshold_days=90, last_accessed_at=None,
    )
    assert missing["error"] == "access_evidence_required" and "core://neutral/item" in store
    mgr.children = lambda *_: [{"uri": "core://neutral/item/child"}]
    non_leaf = mgr.archive_stale_leaf(
        uri="core://neutral/item", namespace="test:private", stale_days=100,
        threshold_days=90, last_accessed_at="2026-01-01T00:00:00+00:00",
    )
    assert non_leaf["error"] == "archive_requires_leaf" and "core://neutral/item" in store


def test_delete_grant_is_scoped_signed_expiring_and_single_use(tmp_path):
    now=[1000]
    authority=DeleteGrantAuthority(b"neutral-secret",now=lambda:now[0],consumed_dir=tmp_path)
    bind_delete_turn(user_message="forget exact neutral item", session_id="session-a")
    token=authority.issue(uri="core://neutral/item",namespace="test:private",user_message="forget exact neutral item",session_id="session-a",ttl_seconds=10)
    assert authority.consume(token,uri="core://neutral/other",namespace="test:private")["error"]=="delete_grant_scope_mismatch"
    bind_delete_turn(user_message="different message", session_id="session-a")
    assert authority.consume(token,uri="core://neutral/item",namespace="test:private")["error"]=="delete_grant_message_mismatch"
    bind_delete_turn(user_message="forget exact neutral item", session_id="session-a")
    first=authority.consume(token,uri="core://neutral/item",namespace="test:private")
    assert first["ok"] and len(first["message_sha256"])==64
    assert authority.consume(token,uri="core://neutral/item",namespace="test:private")["error"]=="delete_grant_replayed"
    bind_delete_turn(user_message="forget", session_id="session-a")
    other=authority.issue(uri="core://neutral/item",namespace="test:private",user_message="forget",session_id="session-a",ttl_seconds=1)
    now[0]=1002
    assert authority.consume(other,uri="core://neutral/item",namespace="test:private")["error"]=="delete_grant_expired"
    tampered=token[:-1]+("0" if token[-1]!="0" else "1")
    assert authority.consume(tampered,uri="core://neutral/item",namespace="test:private")["error"]=="invalid_delete_grant"
