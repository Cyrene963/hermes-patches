# Design Discussion: Multi-tenant Memory OS Acceptance Layer

## Problem

Long-term memory systems often fail after accumulating real usage data. The failure mode is usually not storage capacity, but operational reliability:

- Agents cannot explain what they remember
- Current facts conflict with older facts
- Stale or duplicate memories accumulate
- Multi-user deployments risk cross-tenant memory leakage
- Memory behavior is hard to regression-test
- Diagnostics, inventory, and rollback are often missing

## Proposal

This proposal introduces an **optional** Memory OS acceptance layer for long-term MCP memory systems.

It adds reusable primitives for:

1. **Multi-tenant memory isolation** — namespace guard + evidence store + rule store
2. **Memory inventory** — agent self-awareness of what it remembers
3. **Memory diagnostics** — health checks for stale/crowded/orphan nodes
4. **Canonical fact metadata** — structured, version-aware long-term memories
5. **Regression test framework** — continuous verification of memory behavior
6. **Evidence/rule store adapters** — pluggable backends for evidence and rules
7. **Tenant onboarding** — bootstrap new tenants with directory structure

## Design Principles

- **Optional**: All features are backward-compatible with free-form memories
- **Adapter-based**: Evidence stores, rule stores, and policies are pluggable interfaces
- **No private data**: Only demo fixtures (Alice/Bob/ProjectX/CommonRule) are included
- **Test-first**: Namespace isolation is validated by a 19-test suite
- **Defense-in-depth**: Three independent isolation layers (graph namespace, evidence store, rule store)

## Validation

The design was validated in a production-style deployment with:

- Graph namespace isolation
- Evidence store isolation
- Per-user rule store isolation
- Tenant onboarding
- Admin path protection
- Empty namespace does not imply admin access

**19/19 strong namespace isolation tests passed** with `namespace_leak_count = 0`.

## Compatibility

This proposal does not require existing memories to be rewritten.

- Canonical metadata is **optional** — free-form memories continue to work
- Namespace isolation is **opt-in** — single-tenant deployments are unaffected
- Evidence and rule stores are **adapter-based** — any backend can be used
- No private user data is included
- Demo fixtures use only Alice/Bob/ProjectX/CommonRule

## Proposed PR Breakdown

| PR | Content | Risk |
|----|---------|------|
| PR1 | Namespace isolation test suite | Low — tests only |
| PR2 | Diagnostic + inventory APIs | Low — additive |
| PR3 | Canonical fact metadata (optional) | Low — optional schema |
| PR4 | Regression + nightly maintenance | Low — scripts only |
| PR5 | Tenant/evidence/rule adapters | Medium — interfaces |
| PR6 | Review/rollback enhancement | High — core model |

## Non-Goals

This proposal does **not** include:

- Any specific evidence backend (Hindsight, etc.)
- Any specific platform integration (Telegram, Discord, etc.)
- Any private user data or project data
- Any hardcoded local paths or credentials
- A mandatory replacement of existing memory models

## Module Structure

```
memory_os/
├── __init__.py
├── tenant.py              # MemoryTenant + TenantResolver
├── namespace_guard.py     # NamespaceGuard (permission checks)
├── evidence_adapter.py    # EvidenceStoreAdapter (abstract)
├── rule_store.py          # RuleStoreAdapter (abstract)
├── schema.py              # CanonicalFact (optional metadata)
├── diagnostic.py          # MemoryDiagnostic (abstract)
├── inventory.py           # MemoryInventory (abstract)
├── regression.py          # RegressionTestRunner (abstract)
└── onboarding.py          # TenantOnboarding (abstract)

tests/
└── fixtures/
    └── tenant_fixtures.py # Alice/Bob/Core demo data
```

## Next Steps

1. Open this design discussion for feedback
2. Submit PR1: Namespace isolation test suite
3. Iterate based on maintainer feedback
4. Submit subsequent PRs incrementally
