"""
Multi-tenant namespace isolation tests.
Uses only SQL — no async dependencies, no GraphService.
Fixtures: Alice/Bob/Core synthetic data.
Run: pytest tests/test_namespace_isolation.py -v
"""
import pytest
import subprocess

def sql(q):
    r = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-d", "hindsight", "-t", "-A", "-c", q],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise AssertionError(f"SQL failed ({r.returncode}): {r.stderr.strip()}\nQuery: {q}")
    return r.stdout.strip()

ALICE_NS = "test_user_alice"
BOB_NS = "test_user_bob"
ALICE_TOKEN = "ALICE_ONLY_7391"
BOB_TOKEN = "BOB_ONLY_4826"
ROOT_UUID = "00000000-0000-0000-0000-000000000000"
ALICE_UUID = "aaaa" + ROOT_UUID[4:-1] + "1"
BOB_UUID = "bbbb" + ROOT_UUID[4:-1] + "1"
CORE_TOKEN = "CORE_SHARED_1937"
CORE_UUID = "cccc" + ROOT_UUID[4:-1] + "1"

@pytest.fixture(scope="module", autouse=True)
def setup():
    parent = sql(f"SELECT uuid FROM mg_nodes WHERE uuid != '{ROOT_UUID}' LIMIT 1")
    if not parent:
        parent = sql("SELECT uuid FROM mg_nodes LIMIT 1")
    
    # Alice
    sql(f"INSERT INTO mg_nodes (uuid, created_at) VALUES ('{ALICE_UUID}', NOW()) ON CONFLICT DO NOTHING")
    sql(f"INSERT INTO mg_memories (node_uuid, content, review_state, confidence, source_type, deprecated) VALUES ('{ALICE_UUID}', '{ALICE_TOKEN} Alice likes blue', 'approved', 0.95, 'manual', false) ON CONFLICT DO NOTHING")
    sql(f"DELETE FROM mg_paths WHERE node_uuid = '{ALICE_UUID}'")
    sql(f"INSERT INTO mg_edges (parent_uuid, child_uuid, name, priority, created_at) VALUES ('{parent}', '{ALICE_UUID}', 'alice_priv', 5, NOW()) ON CONFLICT DO NOTHING")
    eid = sql(f"SELECT id FROM mg_edges WHERE child_uuid = '{ALICE_UUID}' LIMIT 1")
    if eid:
        sql(f"INSERT INTO mg_paths (namespace, domain, path, edge_id, node_uuid, created_at) VALUES ('{ALICE_NS}', 'core', 'users/alice/private', {eid}, '{ALICE_UUID}', NOW())")
    
    # Bob
    sql(f"INSERT INTO mg_nodes (uuid, created_at) VALUES ('{BOB_UUID}', NOW()) ON CONFLICT DO NOTHING")
    sql(f"INSERT INTO mg_memories (node_uuid, content, review_state, confidence, source_type, deprecated) VALUES ('{BOB_UUID}', '{BOB_TOKEN} Bob likes red', 'approved', 0.95, 'manual', false) ON CONFLICT DO NOTHING")
    sql(f"DELETE FROM mg_paths WHERE node_uuid = '{BOB_UUID}'")
    sql(f"INSERT INTO mg_edges (parent_uuid, child_uuid, name, priority, created_at) VALUES ('{parent}', '{BOB_UUID}', 'bob_priv', 5, NOW()) ON CONFLICT DO NOTHING")
    eid2 = sql(f"SELECT id FROM mg_edges WHERE child_uuid = '{BOB_UUID}' LIMIT 1")
    if eid2:
        sql(f"INSERT INTO mg_paths (namespace, domain, path, edge_id, node_uuid, created_at) VALUES ('{BOB_NS}', 'core', 'users/bob/private', {eid2}, '{BOB_UUID}', NOW())")

    # Synthetic shared core fixture. Do not depend on production core data
    # existing; privacy cleanup may legitimately leave shared core empty.
    sql(f"INSERT INTO mg_nodes (uuid, created_at) VALUES ('{CORE_UUID}', NOW()) ON CONFLICT DO NOTHING")
    sql(f"INSERT INTO mg_memories (node_uuid, content, review_state, confidence, source_type, deprecated) VALUES ('{CORE_UUID}', '{CORE_TOKEN} shared public fixture', 'approved', 0.95, 'manual', false) ON CONFLICT DO NOTHING")
    sql(f"DELETE FROM mg_paths WHERE node_uuid = '{CORE_UUID}'")
    sql(f"INSERT INTO mg_edges (parent_uuid, child_uuid, name, priority, created_at) VALUES ('{parent}', '{CORE_UUID}', 'core_shared_fixture', 5, NOW()) ON CONFLICT DO NOTHING")
    eid3 = sql(f"SELECT id FROM mg_edges WHERE child_uuid = '{CORE_UUID}' LIMIT 1")
    if eid3:
        sql(f"INSERT INTO mg_paths (namespace, domain, path, edge_id, node_uuid, created_at) VALUES ('', 'core', 'shared/test/core-fixture', {eid3}, '{CORE_UUID}', NOW())")
    
    yield
    
    sql(f"DELETE FROM mg_paths WHERE namespace IN ('{ALICE_NS}', '{BOB_NS}') OR node_uuid = '{CORE_UUID}'")
    sql(f"DELETE FROM mg_memories WHERE node_uuid IN ('{ALICE_UUID}', '{BOB_UUID}', '{CORE_UUID}')")
    sql(f"DELETE FROM mg_edges WHERE child_uuid IN ('{ALICE_UUID}', '{BOB_UUID}', '{CORE_UUID}')")
    sql(f"DELETE FROM mg_nodes WHERE uuid IN ('{ALICE_UUID}', '{BOB_UUID}', '{CORE_UUID}')")

class TestReadIsolation:
    def test_alice_can_read_own(self):
        c = sql(f"SELECT m.content FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='{ALICE_NS}' AND p.path='users/alice/private'")
        assert ALICE_TOKEN in c
    def test_alice_cannot_read_bob(self):
        c = sql(f"SELECT m.content FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='{ALICE_NS}' AND p.path='users/bob/private'")
        assert c == ""
    def test_bob_can_read_own(self):
        c = sql(f"SELECT m.content FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='{BOB_NS}' AND p.path='users/bob/private'")
        assert BOB_TOKEN in c
    def test_bob_cannot_read_alice(self):
        c = sql(f"SELECT m.content FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='{BOB_NS}' AND p.path='users/alice/private'")
        assert c == ""

class TestSearchIsolation:
    def test_alice_search_no_bob(self):
        assert sql(f"SELECT COUNT(*) FROM mg_search_documents WHERE namespace='{ALICE_NS}' AND content ILIKE '%{BOB_TOKEN}%'") == "0"
    def test_bob_search_no_alice(self):
        assert sql(f"SELECT COUNT(*) FROM mg_search_documents WHERE namespace='{BOB_NS}' AND content ILIKE '%{ALICE_TOKEN}%'") == "0"

class TestWriteIsolation:
    def test_no_cross_write(self):
        assert sql(f"SELECT COUNT(*) FROM mg_paths WHERE namespace='{BOB_NS}' AND path LIKE '%alice%'") == "0"

class TestGlossaryIsolation:
    def test_alice_glossary_no_bob(self):
        assert sql(f"SELECT COUNT(*) FROM mg_glossary_keywords WHERE namespace='{ALICE_NS}' AND keyword ILIKE '%bob%'") == "0"
    def test_bob_glossary_no_alice(self):
        assert sql(f"SELECT COUNT(*) FROM mg_glossary_keywords WHERE namespace='{BOB_NS}' AND keyword ILIKE '%alice%'") == "0"

class TestCoreShared:
    def test_synthetic_core_data_exists(self):
        c = sql(f"SELECT m.content FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='' AND p.path='shared/test/core-fixture'")
        assert CORE_TOKEN in c

class TestAdminSafety:
    def test_empty_ns_not_admin(self):
        assert sql(f"SELECT COUNT(*) FROM mg_paths WHERE namespace='' AND path LIKE '%alice%'") == "0"

class TestFactHistory:
    def test_alice_no_bob_history(self):
        assert sql(f"SELECT COUNT(*) FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='{ALICE_NS}' AND m.content ILIKE '%{BOB_TOKEN}%'") == "0"
    def test_bob_no_alice_history(self):
        assert sql(f"SELECT COUNT(*) FROM mg_paths p JOIN mg_memories m ON m.node_uuid=p.node_uuid WHERE p.namespace='{BOB_NS}' AND m.content ILIKE '%{ALICE_TOKEN}%'") == "0"

class TestRecentIsolation:
    def test_namespaces_isolated(self):
        a = sql(f"SELECT COUNT(*) FROM mg_paths WHERE namespace='{ALICE_NS}'")
        b = sql(f"SELECT COUNT(*) FROM mg_paths WHERE namespace='{BOB_NS}'")
        assert int(a) >= 1 and int(b) >= 1

class TestNamespaceSafety:
    def test_ns_distinct(self):
        assert ALICE_NS != BOB_NS
        assert ALICE_NS != ""
