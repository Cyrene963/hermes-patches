-- Row-Level Security for Memory Graph multi-tenant isolation
-- Run once: psql -f db/rls_migration.sql

-- 1. Enable RLS on mg_paths
ALTER TABLE mg_paths ENABLE ROW LEVEL SECURITY;

-- 2. Policy: users can only see their own namespace + core
DROP POLICY IF EXISTS mg_paths_isolation ON mg_paths;
CREATE POLICY mg_paths_isolation ON mg_paths
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR namespace = current_setting('app.current_namespace', true)
        OR namespace = ''
        OR namespace IS NULL
    )
    WITH CHECK (
        namespace = current_setting('app.current_namespace', true)
        OR (
            -- Admin can write to core
            current_setting('app.is_admin', true) = 'true'
            AND (namespace = '' OR namespace IS NULL)
        )
    );

-- 3. Enable RLS on mg_memories
ALTER TABLE mg_memories ENABLE ROW LEVEL SECURITY;

-- 4. Policy: memories inherit namespace from their node
DROP POLICY IF EXISTS mg_memories_isolation ON mg_memories;
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

-- 5. Enable RLS on mg_edges as a defense-in-depth guard. Edges do not carry
-- namespace directly, so visibility is derived from the parent path. Root/shared
-- edges remain visible through namespace='', while private namespace edges are
-- hidden unless the request context matches or is admin.
ALTER TABLE mg_edges ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mg_edges_isolation ON mg_edges;
CREATE POLICY mg_edges_isolation ON mg_edges
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR parent_uuid = '00000000-0000-0000-0000-000000000000'
        OR parent_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    )
    WITH CHECK (
        current_setting('app.is_admin', true) = 'true'
        OR parent_uuid = '00000000-0000-0000-0000-000000000000'
        OR parent_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );

-- 6. RLS on mg_edges must not be disabled by installers; use mg_app smoke tests
-- with set_app_context(...) to catch regressions.

-- 7. Enable RLS on mg_glossary_keywords
ALTER TABLE mg_glossary_keywords ENABLE ROW LEVEL SECURITY;

-- 8. Policy: glossary keywords isolated by namespace
DROP POLICY IF EXISTS mg_glossary_isolation ON mg_glossary_keywords;
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
DROP POLICY IF EXISTS mg_search_docs_isolation ON mg_search_documents;
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
