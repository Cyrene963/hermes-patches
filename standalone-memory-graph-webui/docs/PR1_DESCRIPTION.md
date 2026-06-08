# PR1: Add multi-tenant namespace isolation tests with Alice/Bob/Core fixtures

## What this PR adds

This PR adds a multi-tenant namespace isolation test suite using neutral Alice/Bob/Core fixtures.

The tests verify that private memories from one tenant cannot be read, searched, listed, diagnosed, or retrieved through glossary/history/recent-update paths by another tenant.

## Why

Long-term memory servers are increasingly used in multi-user or multi-agent deployments. Namespace support is not enough unless all read, search, diagnostic, recent, glossary, and history paths consistently enforce tenant boundaries.

This PR adds a reusable safety test suite for that behavior.

## Test fixture

The fixture uses only demo data:

- Alice private token: `ALICE_ONLY_7391`
- Bob private token: `BOB_ONLY_4826`
- Core public token: `COMMON_RULE_0001`

No private user data is included.

## Covered paths (19 tests)

| # | Test | Description |
|---|------|-------------|
| 1 | read_own | Alice can read her own data |
| 2 | read_cross_blocked | Alice cannot read Bob's data |
| 3 | bob_read_own | Bob can read his own data |
| 4 | bob_cross_blocked | Bob cannot read Alice's data |
| 5 | search_no_bob | Alice search excludes Bob's data |
| 6 | search_no_alice | Bob search excludes Alice's data |
| 7 | alice_read_core | Alice can read shared core rules |
| 8 | bob_read_core | Bob can read shared core rules |
| 9 | glossary_no_cross | Glossary scan is namespace-scoped |
| 10 | hindsight_health | Evidence store is reachable |
| 11 | empty_ns_not_admin | Empty namespace does not imply admin |
| 12 | per_user_files | Per-user rule files exist |
| 13 | diagnostic_no_cross | Diagnostic is namespace-scoped |
| 14 | write_cross | Alice cannot write to Bob's namespace |
| 15 | fact_history_blocked | Fact history is namespace-scoped |
| 16 | recent_isolation | Recent updates are namespace-scoped |
| 17 | admin_auth | Admin requires authenticated context |
| 18 | ns_no_escalation | Empty namespace does not escalate to admin |
| 19 | symlink_safe | Per-user directories exist and are isolated |

## Files included

- `memory_os/tenant.py` — MemoryTenant dataclass + TenantResolver ABC
- `memory_os/namespace_guard.py` — NamespaceGuard (stateless permission checks)
- `tests/fixtures/tenant_fixtures.py` — Alice/Bob/Core demo data
- `docs/namespace_isolation.md` — Architecture documentation

## Compatibility

This PR is test-focused and does not change existing memory behavior except where namespace enforcement fixes are required.

- Backward compatible with single-tenant deployments
- Namespace is optional — default namespace "" works for single-user
- No changes to existing memory content
- No private user data included
- Demo fixtures use only synthetic Alice/Bob/ProjectX data

## Test results

```
PASS  1  read_own: Alice reads own data
PASS  2  read_cross_blocked: Alice blocked from Bob
PASS  3  bob_read_own: Bob reads own data
PASS  4  bob_cross_blocked: Bob blocked from Alice
PASS  5  search_no_bob: Bob not in Alice search
PASS  6  search_no_alice: Alice not in Bob search
PASS  7  alice_read_core: Alice reads core rules
PASS  8  bob_read_core: Bob reads core rules
PASS  9  glossary_no_cross: Glossary namespace-scoped
PASS 10  hindsight_health: Evidence store reachable
PASS 11  empty_ns_not_admin: Empty ns not admin
PASS 12  per_user_files: Per-user dirs exist
PASS 13  diagnostic_no_cross: Diagnostic namespace-scoped
PASS 14  write_cross: Cross-namespace write blocked
PASS 15  fact_history_blocked: History namespace-scoped
PASS 16  recent_isolation: Recent namespace-scoped
PASS 17  admin_auth: Admin requires auth
PASS 18  ns_no_escalation: No escalation
PASS 19  symlink_safe: Per-user dirs isolated

19/19 passed, namespace_leak_count = 0
```
