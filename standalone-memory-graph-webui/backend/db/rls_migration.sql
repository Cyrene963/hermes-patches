-- Row-Level Security for Memory Graph multi-tenant isolation
-- Run once: psql -f db/rls_migration.sql

-- 1. Enable RLS on mg_paths
ALTER TABLE mg_paths ENABLE ROW LEVEL SECURITY;

-- 2. Policy: users can only see their own namespace + core
CREATE POLICY mg_paths_isolation ON mg_paths
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR namespace = current_setting('app.current_namespace', true)
        OR namespace = ''
        OR namespace IS NULL
    )
    WITH CHECK (
        current_setting('app.is_admin', true) = 'true'
        OR namespace = current_setting('app.current_namespace', true)
        OR namespace = ''
        OR namespace IS NULL
    );

-- 3. Enable RLS on mg_memories
ALTER TABLE mg_memories ENABLE ROW LEVEL SECURITY;

-- 4. Policy: memories inherit namespace from their node
CREATE POLICY mg_memories_isolation ON mg_memories
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR node_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );

-- 5. Enable RLS on mg_edges
ALTER TABLE mg_edges ENABLE ROW LEVEL SECURITY;

-- 6. Policy: edges inherit namespace
CREATE POLICY mg_edges_isolation ON mg_edges
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR parent_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );

-- 7. Enable RLS on mg_glossary_keywords
ALTER TABLE mg_glossary_keywords ENABLE ROW LEVEL SECURITY;

-- 8. Policy: glossary keywords isolated by namespace
CREATE POLICY mg_glossary_isolation ON mg_glossary_keywords
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR namespace = current_setting('app.current_namespace', true)
        OR namespace = ''
        OR namespace IS NULL
    );

-- 9. Enable RLS on mg_search_documents
ALTER TABLE mg_search_documents ENABLE ROW LEVEL SECURITY;

-- 10. Policy: search documents isolated by namespace
CREATE POLICY mg_search_docs_isolation ON mg_search_documents
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR namespace = current_setting('app.current_namespace', true)
        OR namespace = ''
        OR namespace IS NULL
    );

-- 11. Set app context function
CREATE OR REPLACE FUNCTION set_app_context(p_namespace text, p_is_admin boolean)
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.current_namespace', p_namespace, true);
    PERFORM set_config('app.is_admin', p_is_admin::text, true);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_app_context IS 'Set app context for RLS. Call at start of each request.';

-- 12. Node visibility is derived from reachable paths, but new graph writes must
-- be able to insert the node before its path row exists. Keep reads and
-- mutations path-scoped, and allow ordinary inserts so the follow-up mg_paths
-- WITH CHECK remains the namespace ownership gate.
ALTER TABLE mg_nodes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mg_nodes_isolation ON mg_nodes;
DROP POLICY IF EXISTS mg_nodes_select_isolation ON mg_nodes;
DROP POLICY IF EXISTS mg_nodes_insert_isolation ON mg_nodes;
DROP POLICY IF EXISTS mg_nodes_update_isolation ON mg_nodes;
DROP POLICY IF EXISTS mg_nodes_delete_isolation ON mg_nodes;
CREATE POLICY mg_nodes_select_isolation ON mg_nodes
    FOR SELECT
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );
CREATE POLICY mg_nodes_insert_isolation ON mg_nodes
    FOR INSERT
    WITH CHECK (true);
CREATE POLICY mg_nodes_update_isolation ON mg_nodes
    FOR UPDATE
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    )
    WITH CHECK (
        current_setting('app.is_admin', true) = 'true'
        OR uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );
CREATE POLICY mg_nodes_delete_isolation ON mg_nodes
    FOR DELETE
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );
