"""Production namespace drift guard for the standalone Memory Graph WebUI.

Public/shared Memory Graph visibility is represented by the empty namespace
(``''``).  The URI domain may be ``core://...``, but the database namespace must
not be the literal string ``'core'``.  A historical drift put public rows in
``namespace='core'`` while the WebUI queried ``namespace=''``, making the public
memory browser appear empty.

Run: pytest tests/test_public_namespace_drift.py -q
"""

import subprocess


def sql(query: str) -> str:
    result = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-d", "hindsight", "-t", "-A", "-c", query],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(f"SQL failed ({result.returncode}): {result.stderr.strip()}\nQuery: {query}")
    return result.stdout.strip()


def test_public_rows_use_empty_namespace_not_core_literal():
    core_literal_paths = int(sql("SELECT COUNT(*) FROM mg_paths WHERE namespace='core'"))
    assert core_literal_paths == 0


def test_public_namespace_has_browsable_root_rows():
    public_root_rows = int(
        sql("""
        SELECT COUNT(*)
        FROM mg_paths p
        JOIN mg_memories m ON m.node_uuid = p.node_uuid
        WHERE coalesce(p.namespace, '') = ''
          AND coalesce(m.security_level, 'public') = 'public'
          AND p.path NOT LIKE '%/%'
        """)
    )
    assert public_root_rows > 0


def test_search_documents_do_not_use_core_literal_namespace():
    core_literal_docs = int(sql("SELECT COUNT(*) FROM mg_search_documents WHERE namespace='core'"))
    assert core_literal_docs == 0
