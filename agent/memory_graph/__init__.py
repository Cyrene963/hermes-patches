"""Memory Graph — URI-tree memory system for Hermes Agent.

Ported from Nocturne Memory (https://github.com/Dataojitori/nocturne_memory)
and adapted for Hermes Agent's PostgreSQL + Hindsight architecture.

Architecture:
  Node (UUID) ──< Memory (content versions, 1:N)
     │
     ├──< Edge (parent→child, carries priority + disclosure)
     │      └──< Path (URI routing: domain://path → edge)
     │
     └──< GlossaryKeyword (trigger word bindings)

Services:
  - GraphService: CRUD, traversal, path management
  - SearchIndexer: FTS search across memory content
  - GlossaryService: keyword bindings + Aho-Corasick scanning
  - ChangesetStore: row-level before/after state for review

Tools:
  - memory_graph_read/create/update/delete/list/search/alias
  - memory_graph_glossary_add/scan
"""

__version__ = "0.1.0"
