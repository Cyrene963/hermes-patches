-- Add security_level to mg_memories for explicit access control
-- Run once: psql -f db/security_level_migration.sql

-- 1. Add security_level column
ALTER TABLE mg_memories ADD COLUMN IF NOT EXISTS security_level text DEFAULT 'public';
ALTER TABLE mg_memories ADD CONSTRAINT security_level_check 
    CHECK (security_level IN ('public', 'private', 'sensitive', 'admin_only'));

-- 2. Create index for fast filtering
CREATE INDEX IF NOT EXISTS idx_memories_security_level ON mg_memories(security_level);

-- 3. Migrate existing data based on content analysis
UPDATE mg_memories SET security_level = 'private'
WHERE node_uuid IN (
    SELECT node_uuid FROM mg_paths 
    WHERE namespace != '' AND namespace IS NOT NULL
);

UPDATE mg_memories SET security_level = 'sensitive'
WHERE content ILIKE '%token%' 
   OR content ILIKE '%password%' 
   OR content ILIKE '%key%'
   OR content ILIKE '%secret%'
   OR content ~* 'github[_ -]?pat|personal access token';

UPDATE mg_memories SET security_level = 'admin_only'
WHERE content ~* 'database password|postgres password|github[_ -]?pat|personal access token';

-- 4. Update RLS policy to use security_level
DROP POLICY IF EXISTS mg_memories_isolation ON mg_memories;

CREATE POLICY mg_memories_isolation ON mg_memories
    FOR ALL
    USING (
        -- Admin can inspect all namespaces during explicit maintenance.
        current_setting('app.is_admin', true) = 'true'
        -- Public: everyone can see.
        OR security_level = 'public'
        -- Private/sensitive: only the owner namespace; the empty shared namespace is NOT an owner bypass.
        OR (security_level IN ('private', 'sensitive') AND node_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
              AND current_setting('app.current_namespace', true) <> ''
        ))
        -- Admin only: only admin.
        OR (security_level = 'admin_only' AND current_setting('app.is_admin', true) = 'true')
    );

-- 5. Verify
SELECT security_level, COUNT(*) FROM mg_memories GROUP BY security_level;
