# Status & Verification

This project labels capabilities by **evidence**, not aspiration. "File exists" is
never reported as "feature works." Labels: ✅ verified by execution · ⚠️ partial /
needs per-deployment verification · ⏸ wired but gated · ⚪ deliberately unproven.

For the design rationale and the convergence plan, see
[`MEMORY_OS_CONVERGENCE_PLAN.md`](MEMORY_OS_CONVERGENCE_PLAN.md).

## Memory OS capability matrix

| Cognitive step | Status | Reproducible evidence |
|---|---|---|
| Recall, top-1 semantically correct | ✅ verified | `tests/memory_os/semantic_recall_eval.py` → 11 PASS / 0 FAIL / 1 SKIP; top-1 asserted by node identity + real prompt-carriage |
| Namespace isolation — READ (no cross-user leak) | ✅ DB-enforced (hard) | Postgres RLS (`mg_app` non-superuser + `set_app_context`); a query scoped to ns X returns only X + shared(''), never another user's ns; eval case 6 |
| Namespace attribution — WRITE (subject routing) | ✅ verified (best-effort) | A durable fact ABOUT another person is never auto-written into the speaker's ns; routed to a registered user's ns (`user_registry`) or to review. Semantic (depends on the LLM classifier tagging subject); covers the auto-write loop |
| Pre-action gate (anti-recurrence) | ✅ live | `tool_executor` checks args before dispatch; `MEDIA:` / `linux.do` blocked, `.json` allowed |
| Write hygiene + secret redaction | ✅ verified | hygiene gate drops truncated-copy / question / secret candidates; shadow logs redact secrets before disk |
| Fact distillation (store the fact, not the raw message) | ✅ verified | 7-day real shadow logs: hard-garbage 78.5% → 43%; ~56% distill to a clean atomic fact |
| Semantic vector recall | ✅ present (Hindsight) | Hindsight (vectorize.io) does embedding recall + rerank; Jina `jina-embeddings-v3` endpoint healthy |
| **Autonomous write (the learning loop)** | ⏸ on by default, LLM-gated, fail-closed | LLM classifies the full user message (precision **1.000** / 0 false positives on a 20-case mixed set; 0/16 on real messages) → readback → private namespace. End-to-end verified: a durable preference is written + retrievable; junk is ignored. Fires only when the LLM endpoint is reachable (fail-closed otherwise) |

## Verification evidence (dogfood)

> **Multi-user isolation model (read honestly).** Two distinct layers:
> 1. **Read = hard.** Postgres RLS guarantees one user cannot read another's private
>    namespace. This was never broken.
> 2. **Write attribution = best-effort.** Historically the system filed every fact under
>    the *speaker's* namespace with no notion of *whose* fact it is — so facts a user
>    mentioned *about a contact* accumulated in the speaker's own memory (a real,
>    generic mis-attribution defect, not a read leak). Now the LLM classifier tags the
>    *subject*; a fact about another person is never auto-written to the speaker's ns —
>    it routes to a registered user's ns (`user_registry`) or to review. This is a
>    semantic mitigation (depends on classifier accuracy) covering the auto-write loop;
>    it is not a cryptographic guarantee, and it does not constrain deliberate agent
>    tool-writes. Read-isolation remains the hard guarantee.


| Surface | Evidence label | Basis |
|---|---|---|
| overlay-first installer | ✅ verified | `install.sh` on a clean upstream worktree (Hermes Agent v0.16.0 / `v2026.6.5`); py_compile/import/tool-registration smoke; focused regression after re-overlay |
| Memory Graph tools (14) | ✅ verified | 14 tools registered; real create → search top hit → delete; deleted URI no longer returned |
| Memory Preflight Gate | ✅ verified | `web_extract`/`send_message`/`terminal` blocked for known-bad patterns; GitHub URL allowed |
| Search-as-Code / deep_research | ✅ verified | `deep_research(mode="code_plan"|"auto")` → `overall_status=Verified working`; run_dir/manifest/evidence produced |
| session_search | ✅ verified | returns session_id/results by query; per-platform user/source scope still to verify per entrypoint |
| Gateway loaded state | ✅ verified | local gateway restarted after re-overlay, new process active; external installers must restart their own gateway to load Python changes |
| WebUI source / build / browser | ⚠️ partial | the live WebUI is a separate tree; if you enable the dashboard overlay, verify by clean build, served-bundle hash, browser smoke, protected-API probe |
| ReviewProposal / Memory Graph review loop | ✅ for current slice | `/review` shows Approval eligibility / Readback / Rollback; approve/reject/readback/rollback have focused tests + live smoke |

## How close to a "digital twin / external brain"?

The perceive → recall → pre-action-gate → act → **learn (write)** loop is now live and
verified. The learning loop was historically inert (0 autonomous writes); it now fires
for durable, user-originated facts through an LLM precision gate + readback, writing
clean atomic facts to a private, RLS-isolated namespace, and is fail-closed when the LLM
endpoint is unavailable (it pauses rather than polluting).

Honest remaining gaps (operational, not missing features):
- **LLM/embedding endpoint stability** — the learning loop and semantic recall both
  depend on the configured endpoints; when they flap, the system degrades safely to
  lexical fallback / paused writes.
- **WebUI codebase drift** — the deployed WebUI and the repo's `standalone-memory-graph-webui`
  are different trees; they should be unified.
- **God-files** — `memory_write_pipeline.py` / `memory_metacognition.py` are large and
  would benefit from splitting.

This is not "100% perfect" (an open-ended reliability goal), but the core capabilities are
live and independently reproducible via the commands in
[`MEMORY_OS_CONVERGENCE_PLAN.md`](MEMORY_OS_CONVERGENCE_PLAN.md) §run-book.
