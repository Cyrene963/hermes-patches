# Patch Inventory

This document is the public audit map for the Hermes patches repository. It separates targeted git patches, full-file overlays, standalone modules, service/config assets, and verification gates so maintainers can reason about drift, rollback, and upstream merge state without reading every file.

Evidence labels used here match the README:

- `Verified working`: proved on the real or clean-smoke runtime path.
- `Partially verified`: lower layers pass, but a platform/browser/gateway E2E path still needs confirmation.
- `Code present only`: files exist, but runtime wiring has not been proven for the current release.
- `Risk`: credible failure mode remains.

## Installer Model

The installer is overlay-first with targeted patch support:

1. Run `scripts/hermes-patch-env-preflight.py` against the target Hermes checkout/profile.
2. Install through the default maintained path: apply every `patches/*.patch` with `git apply --check` first, then copy maintained overlays from `agent/`, `tools/`, `cron/`, `hermes_cli/`, `standalone-memory-graph-webui/`, config templates, scripts, and systemd units.
3. Keep the legacy `combined-final-v*.patch` as a maintainer/debug path only; set `HERMES_APPLY_COMBINED_PATCH=1` when explicitly testing it.
4. Apply `individual/*.patch` by default as public feature extensions; incompatible or already-applied patches are reported and skipped. Set `HERMES_APPLY_INDIVIDUAL_PATCHES=0` to disable them, or use `HERMES_INDIVIDUAL_PATCH_ALLOWLIST` to install only selected patches.
5. Stale gateway full-file overlays remain opt-in via `HERMES_APPLY_STALE_GATEWAY_OVERLAYS=1` because they can overwrite newer upstream gateway behavior.
6. Remove stale `.pyc` files, install scripts/config defaults, and run guard/smoke checks where available.

Rollback baseline: if the target checkout was clean before install, run `cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD` or reset to the desired upstream commit, then restart long-running gateway/services only if they loaded patched Python code.

## Targeted Git Patches

| Patch | Surface | Purpose | Evidence | Rollback |
|---|---|---|---|---|
| `patches/0003-preserve-provider-header-metadata.patch` | provider/runtime routing | Preserve custom provider default headers across main, auxiliary, fallback, and switch paths. | Focused provider route regression should pass; gateway reload required for live path. | `git apply -R` if applied, or reset touched files. |
| `patches/0004-telegram-chat-send-lock.patch` | Telegram gateway send path | Serialize send/edit operations per chat to reduce flood-control bursts while keeping different chats concurrent. | Gateway-focused tests and post-restart log watch when deployed. | `git apply -R` if applied, or reset touched files. |
| `patches/0005-fix-kanban-pid-tests-live-system-guard.patch` | official Kanban support surface | Guard patch-chain tests from live PID/system side effects. Kanban itself is upstream, not a patch claim. | Focused tests plus no live process mutation during clean smoke. | `git apply -R` if applied. |
| `patches/0006-dashboard-session-source-filter.patch` | dashboard/session API | Preserve source filtering behavior for dashboard sessions where applicable. | Partially verified; current upstream dashboard changes require browser/API smoke before promotion. | `git apply -R` if applied. |
| `patches/deep-research-toolset-registration.patch` | tool registration | Ensure `deep_research` is available through the expected toolsets/core route. | Toolset registration smoke checks `deep_research` in core/web tool surfaces. | `git apply -R` if applied. |
| `patches/gateway-api-memory-namespace.patch` | API server memory routing | Preserve Telegram Memory Graph namespace for `/v1/chat/completions` requests that provide `X-Hermes-Session-Key` while keeping `platform=api_server`. | Focused API server + Hindsight prefetch tests pass; live `/v1/chat/completions` memory-only canary returned the Memory Graph anchor after gateway restart. | `git apply -R` if applied. |
| `patches/model-switch-custom-provider-switch.patch` | model/provider switching | Keep custom-provider route metadata coherent when switching models/providers. | Focused route-state regression should pass. | `git apply -R` if applied. |
| `patches/post-update-local-patch-hook.patch` | update/install lifecycle | Reapply local patch installer after `hermes update` in installed-hook environments. | Clean update-path smoke and README remote readback. | `git apply -R` if applied. |
| `patches/search-routing-guidance.patch` | prompt/tool guidance | Route current research through stronger search/deep-research lanes when needed. | Prompt/import smoke; behavior depends on model/tool choice. | `git apply -R` if applied. |
| `individual/0007-telegram-visible-ignored-group-context.patch` | Telegram gateway context | Default feature patch: cache visible-but-ignored delivered group messages for later mention-triggered context. | Gateway tests cover delivered-message cache boundaries; Telegram Bot API cannot backfill undelivered history. | `git apply -R` if applied. |
| `individual/0010-feat-image-edit-tool.patch` | image tool surface | Default feature patch: add image edit dispatch support where provider capabilities allow it. | Focused image tool dispatch tests; provider-specific runtime still needs capability smoke. | `git apply -R` if applied. |
| `individual/0011-feat-gpmode-group-reply-mode.patch` | Telegram gateway reply gate | Default feature patch: `/gpmode status\|mention\|free\|auto` per-chat group reply mode, persisted to `~/.hermes/gateway_group_modes.json`. `mention`=reply only when addressed; `free`=reply to all allowed group messages; `auto`=smart-observe (mention-dispatch today, semantic auto-reply not yet enabled). DMs unaffected. Backward compatible: a chat with no `/gpmode` override keeps the operator's configured `require_mention` behavior. | Partially verified: 49 gateway gpmode/gating tests pass; store round-trip + thread inheritance + backward-compat default proven. Live Telegram E2E pending gateway restart. | `git apply -R` if applied. |

## Full-File Runtime Overlays

These files are copied by `install.sh`. They are higher drift risk than targeted patches because upstream changes can be overwritten if the overlay is stale. Keep them surgically rebased and covered by focused import/tests.

| Overlay group | Representative files | Purpose | Evidence / required smoke |
|---|---|---|---|
| Agent runtime hooks | `agent/agent_runtime_helpers.py`, `agent/tool_executor.py`, `agent/conversation_loop.py`, `agent/system_prompt.py`, `agent/prompt_builder.py`, `agent/agent_init.py`, `agent/auxiliary_client.py` | Memory preflight gate, shadow write hook, memory index injection, search routing guidance, provider/default-header route preservation. | `python -m py_compile` on touched files; focused preflight/provider/prompt-builder tests; gateway restart for live state. |
| Memory OS modules | `agent/memory_metacognition.py`, `agent/memory_write_pipeline.py`, `agent/memory_semantic_classifier.py`, `agent/shadow_write_logger.py`, `agent/memory_review_proposals.py` | Query expansion, tool preflight policies, semantic write/review pipeline, shadow logging, review proposals. | Focused memory write/classifier/review tests; shadow/review readback for live claims. |
| Skill routing | `agent/skill_router.py`, `agent/prompt_builder.py` | Metadata-first mandatory skill routing and memory index/context construction. | `tests/agent/test_skill_router*.py`, `tests/agent/test_prompt_builder.py`. |
| Memory Graph package | `agent/memory_graph/**`, `tools/memory_graph_tool.py`, `toolsets.py` | Structured memory graph service, RLS-aware DB/services, 14 registered tools, toolset/core wiring. | Tool registration smoke plus create → search top hit → delete canary. |
| Research/search tools | `tools/deep_research_tool.py`, `tools/web_tools.py`, `scripts/hermes_search_as_code_research.py`, `scripts/hermes_deep_research_orchestrator.py` | Search-as-Code evidence lane and unified deep-research orchestration. | `tests/tools/test_deep_research_unified_orchestrator.py`; live web dogfood only when network/provider credentials exist. |
| Session/cron/image tools | `tools/session_search_tool.py`, `tools/cronjob_tools.py`, `tools/image_generation_tool.py`, `cron/jobs.py` | Scoped session recall, cron schema/read compatibility, image dispatch capability. | Focused tool tests; platform-specific E2E for delivery/cron/image providers. |
| CLI/provider helpers | `hermes_cli/runtime_provider.py`, `hermes_cli/config.py`, `hermes_cli/web_server.py` | Runtime provider configuration, custom-provider compatibility, dashboard/server fixes where maintained. | CLI import/config smoke; dashboard browser/API smoke before UI claims. |

## Service, Config, and Audit Assets

| Asset | Purpose | Evidence / guard |
|---|---|---|
| `memory_policy.default.yaml`, `memory_write_config.yaml` | Default Memory OS preflight/write policy templates. | Policy positive-control tests should prove known blocked cases really block. |
| `db/rls_migration.sql`, `db/security_level_migration.sql` | Memory Graph least-privileged namespace/security hardening. | Verify with a non-superuser DB role; superuser bypass is not proof. |
| `systemd/hermes-memory-graph*.service`, `systemd/hermes-memory-stack*.target`, watchdog units | Persistent Memory Graph/Hindsight service ownership and health recovery. | Health probes plus duplicate-owner guard; clean-smoke must skip systemd by default. |
| `scripts/hermes-patch-chain-guard.sh` | Deterministic patch-chain verification gate. | Should check patch/runtime/tool registration/health/privacy surfaces without mutating live state unexpectedly. |
| `scripts/hermes-public-patch-privacy-guard.sh`, `ast-grep-rules/*` | Public repo privacy/structure scanning. | CI runs the privacy guard on full history; ast-grep warnings are triaged before hard-fail. |
| `.github/workflows/privacy-guard.yml` | Existing privacy CI. | Runs on push, PR, and manual dispatch. |
| `.github/workflows/patch-verification.yml` | Clean install/import/test inventory CI. | Runs no-systemd/no-DB installer smoke and focused pytest where dependencies allow. |

## Verification Commands

Use these before publishing patch-stack changes. Compile overlay files in the patch repo, then run tests from a full Hermes checkout after applying the installer:

```bash
cd ~/.hermes/patches
bash scripts/hermes-public-patch-privacy-guard.sh "$PWD"
python3 -m py_compile agent/system_prompt.py agent/agent_runtime_helpers.py agent/conversation_loop.py tools/memory_graph_tool.py tools/session_search_tool.py

cd ~/.hermes/hermes-agent
bash ~/.hermes/patches/install.sh
python3 -m pytest -q tests/agent/test_prompt_builder.py tests/agent/test_skill_router.py tests/run_agent/test_memory_preflight_dispatch.py tests/tools/test_memory_graph_tool.py
```

Clean upstream installer smoke:

```bash
BASE="${TMPDIR:-/tmp}/hermes-patch-smoke-$(date +%Y%m%d_%H%M%S)"
git clone --depth 1 https://github.com/NousResearch/hermes-agent.git "$BASE/hermes-agent"
HERMES_HOME="$BASE/hermes-agent" HERMES_PROFILE_DIR="$BASE/profile" HERMES_INSTALL_SYSTEMD=0 HERMES_INSTALL_DB=0 bash ~/.hermes/patches/install.sh
cd "$BASE/hermes-agent"
python3 -m py_compile agent/system_prompt.py agent/agent_runtime_helpers.py agent/conversation_loop.py tools/memory_graph_tool.py tools/session_search_tool.py toolsets.py
python3 - <<'PY'
from toolsets import TOOLSETS, _HERMES_CORE_TOOLS
assert len(TOOLSETS.get('memory_graph', {}).get('tools', [])) == 14
assert 'memory_graph_search' in _HERMES_CORE_TOOLS
assert 'session_search' in _HERMES_CORE_TOOLS
assert 'deep_research' in _HERMES_CORE_TOOLS
print('tool registration smoke ok')
PY
```

## Promotion Checklist

Before moving a claim to `Verified working` in README/docs:

1. File exists and imports without errors.
2. Runtime wiring exists in the actual dispatch/toolset/callback path.
3. Positive-control tests prove the intended behavior, not only that a function returns something.
4. Clean install or installed-hook update path reproduces the behavior.
5. Long-running gateway/service state is restarted or explicitly labeled as not yet loaded.
6. Public privacy guard passes on current tree and history.
