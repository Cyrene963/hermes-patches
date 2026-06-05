-- Memory Graph schema initialization
-- Run against your PostgreSQL database (e.g., hindsight)

-- Core tables
CREATE TABLE IF NOT EXISTS mg_nodes (
    uuid VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_accessed_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS mg_memories (
    id SERIAL PRIMARY KEY,
    node_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    content TEXT NOT NULL,
    deprecated BOOLEAN DEFAULT FALSE,
    migrated_to INTEGER REFERENCES mg_memories(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_mg_memories_node ON mg_memories(node_uuid);
CREATE INDEX IF NOT EXISTS ix_mg_memories_deprecated ON mg_memories(deprecated);

CREATE TABLE IF NOT EXISTS mg_edges (
    id SERIAL PRIMARY KEY,
    parent_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    child_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    name VARCHAR(256) NOT NULL,
    priority INTEGER DEFAULT 0,
    disclosure TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(parent_uuid, child_uuid)
);
CREATE INDEX IF NOT EXISTS ix_mg_edges_parent ON mg_edges(parent_uuid);
CREATE INDEX IF NOT EXISTS ix_mg_edges_child ON mg_edges(child_uuid);

CREATE TABLE IF NOT EXISTS mg_paths (
    namespace VARCHAR(64) DEFAULT '',
    domain VARCHAR(64) DEFAULT 'core',
    path VARCHAR(512),
    edge_id INTEGER NOT NULL REFERENCES mg_edges(id) ON DELETE CASCADE,
    node_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (namespace, domain, path)
);
CREATE INDEX IF NOT EXISTS ix_mg_paths_node ON mg_paths(node_uuid);

-- Auxiliary tables
CREATE TABLE IF NOT EXISTS mg_glossary_keywords (
    id SERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    node_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    namespace VARCHAR(64) DEFAULT '' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(keyword, node_uuid, namespace)
);
CREATE INDEX IF NOT EXISTS ix_mg_glossary_ns ON mg_glossary_keywords(namespace);

CREATE TABLE IF NOT EXISTS mg_search_documents (
    namespace VARCHAR(64) DEFAULT '',
    domain VARCHAR(64) DEFAULT 'core',
    path VARCHAR(512),
    node_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    memory_id INTEGER REFERENCES mg_memories(id) ON DELETE CASCADE,
    uri TEXT NOT NULL,
    content TEXT NOT NULL,
    disclosure TEXT,
    search_terms TEXT DEFAULT '',
    priority INTEGER DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    search_vector TEXT,
    PRIMARY KEY (namespace, domain, path)
);
CREATE INDEX IF NOT EXISTS ix_mg_search_node ON mg_search_documents(node_uuid);

CREATE TABLE IF NOT EXISTS mg_access_logs (
    id SERIAL PRIMARY KEY,
    node_uuid VARCHAR(36) NOT NULL REFERENCES mg_nodes(uuid) ON DELETE CASCADE,
    namespace VARCHAR(64) DEFAULT '' NOT NULL,
    accessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    context VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS ix_mg_access_node ON mg_access_logs(node_uuid);

CREATE TABLE IF NOT EXISTS mg_snapshots (
    id SERIAL PRIMARY KEY,
    namespace VARCHAR(64) DEFAULT '' NOT NULL,
    node_uuid VARCHAR(36) NOT NULL,
    uri TEXT NOT NULL,
    action VARCHAR(32) NOT NULL,
    before_content TEXT,
    after_content TEXT,
    before_meta TEXT,
    after_meta TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    approved BOOLEAN
);
CREATE INDEX IF NOT EXISTS ix_mg_snapshots_ns ON mg_snapshots(namespace);
CREATE INDEX IF NOT EXISTS ix_mg_snapshots_node ON mg_snapshots(node_uuid);

-- Ensure root node exists
INSERT INTO mg_nodes (uuid) VALUES ('00000000-0000-0000-0000-000000000000') ON CONFLICT DO NOTHING;
