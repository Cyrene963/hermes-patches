# Hermes Memory OS — Convergence Plan & Verified State

> Single source of truth. Supersedes the scattered `/root/*_report_*.md`.
> Evidence is cited as `file:line` against runtime `~/.hermes/hermes-agent`
> and repo `~/.hermes/patches`. Status labels: ✅ verified by execution,
> ⚠️ partial, ❌ open, ⚪ deliberately unproven (SKIP, not faked).

## 0. Repo topology (avoid the stale-clone trap)
- `/root/hermes-patches` — STALE clone, do not use.
- `~/.hermes/patches` — current public repo (origin/main). **SoT.**
- `~/.hermes/hermes-agent` — live runtime. **Behavioral SoT.** Gateway runs here.
- A parallel actor ("Nitrogen") also commits here; `git clean` has wiped untracked
  files once. **Commit work to a branch to protect it.**

## 1. Verified state (semantic eval, run against live runtime)
`tests/memory_os/semantic_recall_eval.py` → **PASS=11 FAIL=0 SKIP=1**. Top-1 is asserted
by node-uuid identity + real prompt-carriage via the live provider's prefetch method.

| # | case | status | note |
|---|---|---|---|
| 1 | user preference recall | ✅ | top1+anchor+carriage |
| 2 | explicit correction | ✅ | fixed by namespace-rank rerank |
| 3 | project convention | ✅ | fixed by namespace-rank rerank |
| 4 | obsolete not used | ✅ | current outranks obsolete |
| 5 | namespace isolation | ✅ | own ns finds own fact |
| 6 | cross-user no leak | ✅ | **DB-enforced (Postgres RLS)** |
| 7 | top-1 among siblings | ✅ | exact sibling ranks #1 |
| 8 | Hindsight masks MG failure | ⚪ SKIP | needs MG-outage injection in CI; not faked on live |
| 9 | preflight block | ✅ | MEDIA: blocked |
| 10 | preflight allow | ✅ | plain text passes |
| 11 | skill routing | ✅ | debugging → systematic-debugging skill |
| 12 | extractor precision (post-gate) | ✅ | fp=0 after hygiene gate |

## 2. Fixes landed this session (runtime + repo, kept in sync)
| Fix | File(s) | Effect | Verified |
|---|---|---|---|
| Namespace-rank rerank | `agent/memory_graph/services/search.py` | private memory outranks shared-area nodes (was: long shared notes buried private facts) | ✅ eval 2/3 |
| Hygiene gate on write candidates | `agent/memory_write_pipeline.py` + `agent/memory_write_earn.py` | drops raw-truncated-copy / secret / question / too-short candidates before review/write | ✅ eval 12, 12 unit tests |
| Shadow-log secret redaction | `agent/shadow_write_logger.py` | masks `sk-/ghp_/JWT…` before disk write (audit found 19 leaked) | ✅ self-test |
| Typed/readback/quarantine gates | `agent/memory_write_earn.py` (+tests) | the safe "earn a write" mechanism; `enable_auto=False` default | ✅ 12 unit tests |
| De-hardcode identities | `query_planner.py`, `identity_config.py`, `search.py`, `cronjob_tools.py` | real names → gitignored `~/.hermes/memory_identity.local.yaml`; repo neutral | ✅ import |
| Privacy guard names | `scripts/hermes-public-patch-privacy-guard.sh` | flags CJK personal names (will correctly FAIL on history until scrubbed) | ⚠️ |
| WebUI resilience | `frontend/src/App.jsx` | removed dead state; `RouteErrorBoundary` (no blank screen) | needs `npm run build` |

## 3. Hard truths (verified numbers)
- **Write loop is inert AND dirty.** Real shadow logs (7 days, 948 candidates): only
  **1** actual auto-write; **88.4%** of candidates carry ≥1 garbage flag; **68%** are
  raw truncated copies of the user message; **19** leaked secrets. → Auto-write must
  stay OFF until the hygiene gate + a labeled precision ≥0.95 (`shadow_precision_audit.py --score`).
- **Isolation is strong.** Cross-user no-leak is enforced at the Postgres RLS layer
  (`mg_app` non-superuser + `set_app_context`), not just app code.
- **mg.bz9.me 403** is Cloudflare edge bot-protection, not the app/nginx (clean proxy
  to :8233, local curl = 200). Confirm: `curl -sI https://mg.bz9.me/ | grep -i cf-ray`.

## 4. Run book
```bash
P=~/.hermes/patches; V=~/.hermes/hermes-agent/venv/bin/python
$V -m pytest $P/tests/agent/test_memory_write_earn.py -q                         # 12 pass
HERMES_DIR=~/.hermes/hermes-agent $V $P/tests/memory_os/semantic_recall_eval.py  # 11 pass / 1 skip
$V $P/scripts/shadow_precision_audit.py --days 7 --sample 60                     # real garbage rate + sample
$V $P/scripts/shadow_precision_audit.py --score ~/.hermes/shadow_audit/to_label.jsonl  # true precision after labeling
```

## 5. Still open (next levers, ranked)
1. **Enable typed auto-write** — only after labeling the audit sample shows clean-subset
   precision ≥0.95. Then wire `memory_write_earn.decide(..., enable_auto=True)` into the
   pipeline for `{correction,preference,decision}` only. ❌
2. **Replace the extractor** — `auto_store_heuristic` sets object=raw message; the hygiene
   gate is a band-aid. A distillation step (extract the FACT, not the message) raises the
   clean rate from 11.6% upward. ❌
3. **case 8** — add a CI test with a stubbed MG to prove Hindsight fallback labels its
   answers "unverified" instead of asserting them as truth. ⚪
4. **WebUI** — `npm run build` to ship the ErrorBoundary; then namespace-switch without
   full reload; i18n the hardcoded `共享公开区/我的私有记忆`. ⚠️
5. **Maintainer-only** — rotate the leaked GitHub PAT; scrub personal names from public
   git history (`git filter-repo` + force-push). ❌
