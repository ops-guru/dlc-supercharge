# Changelog

All notable changes to DLC SuperCharge are documented in this file. Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.2] - 2026-05-26 — dist/ sync with v2.0 runtime

The v2.0.0 Python migration updated this repo's **workspace** state (`.kiro/hooks/*` invoke `uv run python -m dlc_bridge.hooks.<name>`; `.kiro/scripts/*.ps1/sh` removed) but never updated the `dlc-supercharge/dist/` bundle that `bootstrap.{ps1,sh}` ships to fresh installs. Result: any user who installed via the bootstrap or "Add Power from GitHub" since v2.0.0 was actually getting the **v1.x runtime** — v1.x hook prompts → v1.x PS/bash scripts → direct `claude -p` invocation, with the v2.0 Python package at `src/dlc_bridge/` not in the call graph at all.

This release brings the dist/ bundle into alignment with the v2.0 runtime. No source code under `src/dlc_bridge/` changes — only bundled artifacts and the docs/steering that describe them.

### Changed

- **`dlc-supercharge/dist/hooks/*.kiro.hook` (14 files)** — synced from this repo's workspace `.kiro/hooks/`. All 14 now invoke `uv run python -m dlc_bridge.hooks.<name>` instead of `.kiro/scripts/dlc-bridge.{ps1,sh}`. Includes the four v2.0.1 patches (heading-format tolerance, BRIDGE_PROGRESS heartbeats, pre-flight chat notice, self-fire suppression).
- **`dlc-supercharge/steering/dlc-augment.md` + workspace mirror** — replaced `.kiro/scripts/dlc-bridge.ps1` references with the Python wrapper invocation pattern. Added a parenthetical historical note pointing to v2.0 retirement of the PS/bash scripts.
- **`.kiro/DLC-SUPERCHARGE-README.md` (workspace docs)** — Lane 2 ASCII diagram and troubleshooting section updated to the Python wrapper invocation. The exit-code-contract pointer now points to `uv run dlc-bridge help` instead of the dead PS script's help text.

### Removed

- **`dlc-supercharge/dist/scripts/{dlc-bridge,dlc-bridge-retry,dlc-bridge-status,dlc-bridge-verbs,debounce-check,id-propagate,mode-resolve,slug-derive,state-update}.{ps1,sh}` (18 files)** — all retired in v2.0.0 (replaced by `src/dlc_bridge/`) but the `dist/` copies were never deleted. Only `register-kiro-power.{ps1,sh}` remains in `dist/scripts/` (still live — Kiro registry registration has no Python equivalent yet).
- **`bootstrap.{ps1,sh}` v1.1 fallback smoke-test path** — bootstrap's "Test 2: bridge dry-run" no longer falls back to `.kiro/scripts/dlc-bridge.{ps1,sh}` when the Python bridge fails. Those scripts no longer ship; the fallback was unreachable. Failure of the Python bridge smoke now fails the install (was: warned then attempted fallback).

### Migration

- Existing installs that used the workspace path (this repo cloned + bootstrap run, then v2.0.0 in-place migration) are unaffected — those already have v2.0 hooks at `<workspace>/.kiro/hooks/` and the Python bridge under `src/dlc_bridge/`.
- Existing installs that used the bootstrap-from-source-bundle path on a different workspace **and were last installed at any v2.0.x ≤ 2.0.1** should re-run `bootstrap.{ps1,sh}` to pick up the v2.0 hook bodies and remove the orphan `.kiro/scripts/*.ps1/sh` files. Bootstrap is idempotent and the file-copy logic will overwrite stale dist content.

### Validated

- All 353 unit tests still pass (no `src/` changes).
- 14 dist/hooks/*.kiro.hook files parse as valid JSON.
- `grep -rE "\.kiro/scripts/(dlc-bridge|debounce|id-propagate|mode-resolve|slug-derive|state-update)" dlc-supercharge/ .kiro/` returns no results in tracked files (one intentional historical reference remains in `dlc-supercharge/HACKATHON-DRESS-REHEARSAL.md` § 4).

## [2.0.1] - 2026-05-25 — feedback-collector e2e fixes

Four patches discovered empirically by running a real Kiro Spec end-to-end (a tiny FastAPI feedback-collector app) through the full DLC SuperCharge flow. Each fix addresses a distinct class of bug that synthetic-fixture unit tests cannot surface. Full retrospective: [E2E-RETRO-2026-05-25.md](E2E-RETRO-2026-05-25.md).

### Fixed

- **`id_propagate` heading-format drift** ([#5](https://github.com/ops-guru/kiro-bridge-poc/pull/5)). The live `/dlc:analyze-requirements` skill emits `### FR-1 — Title` (h3 + em-dash U+2014); the parser regex literally required `#### FR-1 - Title` (h4 + ASCII hyphen). Zero FR/NFR markers had ever been injected into any Kiro spec. Regex relaxed to `#{3,4}` + `[-–—]`; bounded so h2 and h5 remain rejected. New `tests/fixtures/id-prop/real-plugin-output/` captures actual plugin output for regression coverage. New `_common.emit_propagate_outcome()` helper distinguishes `ID_PROPAGATED` / `ID_PROPAGATE_ZERO_MATCHES` / `ID_PROPAGATE_NO_ENTRIES` — the prior happy-path marker silently conflated all three.

- **Premature state finalize on long bridge verbs** ([#6](https://github.com/ops-guru/kiro-bridge-poc/pull/6)). `produce-tech-design` (7m38s wall clock) was being killed by Kiro's host bash inactivity-timeout at ~3-4 minutes — the bridge's `subprocess.run(claude.exe, capture_output=True)` is silent for the whole duration, looks hung. Agent then ran `finalize`, advancing state to Phase 3 before the artifact existed. `_common.invoke_bridge()` now spawns a daemon thread emitting `BRIDGE_PROGRESS=verb=<v> elapsed=<N>s` to the wrapper's *own* stdout every 30s (configurable via `heartbeat_interval`, opt out with `None`). Stops cleanly when the subprocess returns. Validated empirically: a 27-min `plan-implementation` survived the bash intact.

- **Visibility gap during long hook runs** ([#7](https://github.com/ops-guru/kiro-bridge-poc/pull/7)). Heartbeats from #6 defeat the timeout but stay invisible to the user — Kiro chat does not stream a running bash's stdout. Users see an idle chat and assume the task is done, then re-prompt. Each long-running hook prompt (`on-requirements-saved`, `on-design-saved`, `on-tasks-saved`) now starts with an explicit **Step 0** instructing the agent to surface `⏳ DLC: starting <verb> in the background — typically 5–10 minutes. Don't re-prompt; I will surface results when the bridge completes.` as plain chat text BEFORE running any Bash. `on-requirements-saved` gets a second mid-flight notice before Step 3 (review dispatch).

- **Self-fire loops from DLC's own writes** ([#9](https://github.com/ops-guru/kiro-bridge-poc/pull/9), closes [#8](https://github.com/ops-guru/kiro-bridge-poc/issues/8)). When `id_propagate` injects `<!-- FR-1 -->` / `<!-- WI-1 -->` / `<!-- TC-1 -->` comments — or `epic_inject` appends Epic markers — Kiro detects the mtime change as a `fileEdited` event and re-fires the same hook. The 30s debounce expires; the bridge cache misses (different source-content hash). Three self-fire loops observed in the e2e, ~\$2-3 wasted API spend per fire. New `dlc_bridge.util.self_writes` module: per-slug SHA-256 registry at `.dlc/<slug>/_self-writes.json`, last-10-entries-with-TTL, `filelock`-protected, fail-open. After successful init pipeline, wrapper records `sha256(trigger_file)`. At init entry (after debounce, before `invoke_bridge`), wrapper compares current hash against registry; on match within 10-min TTL → emit `PROBE_SELF_FIRE` + `HOOK_INIT_SKIPPED`, return 0 without touching the bridge. Applied uniformly to all three save-hooks. Bonus cleanup: removed redundant "Step 2 Epic markers" from `.kiro/hooks/on-tasks-saved.kiro.hook` prompt — the Python wrapper's `epic_inject` already handles this idempotently and the agent's manual edit was duplicating work AND was a primary self-fire trigger.

### Added

- `dlc-supercharge/E2E-RETRO-2026-05-25.md` — complete retrospective of the feedback-collector e2e session: timeline, four bug classes with root cause and fix details, things that worked, things to add next, and a reproducer.
- `src/dlc_bridge/util/self_writes.py` — content-hash registry module with `record()`, `is_self_fire()`, `sha256_of_file()` API. `filelock`-protected, TTL-evicted, capped at 10 entries per file.
- New markers: `BRIDGE_PROGRESS=verb=<v> elapsed=<N>s`, `PROBE_SELF_FIRE=<path>`, `SELF_WRITE_RECORDED=<file> sha256=<16-hex-prefix>`, `ID_PROPAGATE_ZERO_MATCHES=…`, `ID_PROPAGATE_NO_ENTRIES=…`. New terminal: `HOOK_INIT_SKIPPED` (also emitted by self-fire path, in addition to the existing design-skeleton path).

### Tests

- 353 passing (was 334 → +19): 17 new `tests/unit/test_self_writes.py`, 6 new `tests/unit/test_id_propagate.py::TestRealPluginHeadingFormat`, 6 new `tests/unit/hooks/test_common.py::TestInvokeBridgeHeartbeat` + 3 `TestEmitPropagateOutcome`, 2 new `tests/unit/hooks/test_on_tasks_saved.py` self-fire integration. Zero regressions in existing hook tests despite the new code path — `is_self_fire()` fail-opens when registry absent (every test uses fresh `tmp_path`).

### Known follow-ups (not in scope)

- Switch `produce-tech-design` + `plan-implementation` to default `--background` mode + `check-dlc-job` polling for id-propagate. Architectural fix; defeats both inactivity AND wall-clock timeouts. ~6-7 files. See E2E-RETRO § "Things to add next".
- Captured-real-plugin-output fixtures for `produce-tech-design` and `plan-implementation` (analogous to the `analyze-requirements` fixture added in #5).
- State-aware suppression ("phase 3 with plan exists AND no `--force` ⇒ skip") to catch the broader pattern of Kiro itself fire-triggering on `tasks.md` checkboxes during impl phase, beyond the DLC-self-write loop #9 already addresses.

## [2.0.0] - 2026-05-22 — Python runtime migration (BREAKING)

Big-bang cutover from the v1.1 PowerShell + POSIX bash dual-stack to a single Python 3.11+ codebase. Gated by a 74-test golden-artifact parity suite (FR-19) cross-validated against v1.1 PS 5.1.

### BREAKING CHANGES

- **Drops the PowerShell + POSIX bash dual-runtime.** All 49 `.kiro/scripts/*.ps1` and `*.sh` files have been replaced with a single Python 3.11+ codebase under `src/dlc_bridge/`.
- **Requires `uv` (Astral) launcher and Python 3.11+.** Bootstrap auto-installs `uv` via `irm https://astral.sh/uv/install.ps1 | iex` (Windows) or `curl -LsSf https://astral.sh/uv/install.sh | sh` (POSIX). Opt out with `-NoAutoInstallUv` / `--no-auto-install-uv`.
- **Invalidates the bridge hash cache.** New `cache_version: 2` top-level field is required; v1 cache entries are silently treated as misses. First invocation per `(slug, verb)` after upgrade re-runs the bridge.
- **Test runner changed**: `uv run pytest tests/` replaces the v1.1 PS+bash hand-rolled Assert harness under `.dlc/dlc-supercharge/tests/`.

### Added

- `src/dlc_bridge/` — single Python package replacing the v1.1 runtime (24 modules: `cli.py`, `verbs.py`, `cache.py`, `status.py`, `retry.py`, `background_runner.py`, `exceptions.py`, plus `util/` (encoding, hash, slug, mode, emit, state, id_propagate, epic_inject, debounce, power) and `hooks/` (14 hook modules + `_common.py`)).
- `tests/parity/` — golden-artifact parity gate (FR-19). 74 parity tests: 12 hash + 13 slug + 6 state + 5 id-propagate + 4 epic-inject + 2 help + 32 dry-run. Embedded-constant cases run on every CI leg; cross-language live PS tests run when `powershell.exe` / `pwsh` is on PATH.
- `tests/{unit,integration,parity}/` — pytest suite with `--cov-fail-under=80` gate. Current coverage: **89.58%** line+branch on `src/dlc_bridge/`.
- `.github/workflows/test.yml` — cross-platform CI matrix (`[windows-latest, macos-latest, ubuntu-latest] × [3.11, 3.12]` = 6 legs) using `astral-sh/setup-uv@v3` with `uv.lock` caching.
- `dlc-supercharge/bootstrap.{ps1,sh}` Phase 1.5 (uv check + auto-install) and Phase 4.5 (uv sync).
- `--no-auto-install-uv` / `-NoAutoInstallUv` bootstrap flag (NFR-8) — exits 9 with the manual-install URL when uv is missing.
- `dlc-supercharge/SMOKE-TEST-CHECKLIST.md` — fresh-VM verification flow for maintainers (WI-23).
- `tests/parity/capture_goldens.py` — utility script that re-captures goldens from v1.1 PS sources; idempotent with `--force`.

### Fixed

- Eliminates the v1.1 bug class around UTF-8 codepage fallback, BOM-on-`Set-Content -Encoding utf8`, CRLF/LF normalization, and em-dash mangling in PS 5.1 sources: Python defaults (`encoding='utf-8'`, `newline='\n'`, `path.write_bytes()`) are correct everywhere.
- Background subprocess on Windows uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` (D-11), making parent-exit safe (probe-validated; closes R-9).
- Atomic writes via `os.replace(tmp, dest)` everywhere (D-5) — replaces v1.1's `Move-Item -Force`.
- `state.md` writes no longer emit a UTF-8 BOM (NFR-3). The parity comparator strips BOM before comparing — this is the intentional behavioral fix vs v1.1, documented in `_strip_bom`.

### Removed

- `.kiro/scripts/*.ps1` (25 files) — replaced by `src/dlc_bridge/`.
- `.kiro/scripts/*.sh` (24 files) — replaced by `src/dlc_bridge/`.
- `.dlc/dlc-supercharge/tests/*.ps1` + `*.sh` (hand-rolled Assert harness) — replaced by the `tests/` pytest suite.
- `.dlc/dlc-supercharge/tests/fixtures/` — superseded by `tests/fixtures/`.

### Intentional behavioral changes from v1.1

At runtime contract level, none: same 16 verbs, same exit codes (0, 2, 3, 4, 5, 6, 7), same JSON schemas (status file fields, dry-run envelope), same stdout markers (`BRIDGE_OK`, `BRIDGE_CACHED`, `BRIDGE_FAILED`, `BACKGROUND_JOB_ID`, `HOOK_DONE`, etc.). The only user-visible contract change is the `cache_version: 2` schema field on hash-cache writes.

### Migration

- **Run `dlc-supercharge/bootstrap.ps1`** (Windows) or `bash dlc-supercharge/bootstrap.sh` (POSIX) to upgrade in place. Bootstrap is idempotent.
- Existing `.kiro/hooks/*.kiro.hook` files were rewritten in this PR to invoke `uv run python -m dlc_bridge.hooks.<name>`.
- See `dlc-supercharge/SMOKE-TEST-CHECKLIST.md` for the fresh-VM verification flow.

### Rollback

- Tag `v1.1.0-pre-cutover` preserves the v1.1 PS+bash runtime. To roll back: `git checkout v1.1.0-pre-cutover && powershell -File dlc-supercharge\bootstrap.ps1 -Force -Into .`.

## [1.0.1] - 2026-05-20

Same-day post-1.0.0 patch — discovered during live install-test in Kiro IDE: Power didn't appear in Kiro's Powers panel after `bootstrap` install.

### Fixed

- **Kiro Powers panel visibility**: v1.0.0 bootstrap installed workspace-scoped files only (`.kiro/hooks/`, `.kiro/agents/`, `.kiro/scripts/`) but never registered the Power with Kiro's user-scoped registry at `~/.kiro/powers/`. Kiro Powers panel reads `~/.kiro/powers/installed.json` and `~/.kiro/powers/registries/user-added.json` exclusively — workspace paths are ignored for Powers UI. Result: hooks/agents loaded fine but the Power was invisible in the Powers panel.
- **PS 5.1 UTF-8 BOM regression in JSON writes**: `Set-Content -Encoding utf8` writes UTF-8 WITH BOM by default. Kiro's JSON parser rejects BOM-prefixed input (`[error] [Powers] Failed to list powers: Unexpected token '﻿', "..." is not valid JSON`). All JSON writes that Kiro consumes now use `[System.IO.File]::WriteAllText` with `UTF8Encoding($false)`.
- **`bootstrap.{ps1,sh}` installer missing state.md.template**: v1.0.0 installer's file-copy manifest never included Epic 7's `dist/templates/state.md.template`. Added explicit copy step.

### Added

- **Phase 6.5 in `bootstrap.{ps1,sh}`**: after workspace install, automatically invoke `register-kiro-power.{ps1,sh}` to register the Power in Kiro's user-scoped registry. Adds the entry to `installed.json` + `registries/user-added.json` + copies POWER.md/mcp.json/steering/ to `~/.kiro/powers/installed/<name>/`. Bypass with `-NoRegisterKiroPower` / `--no-register-kiro-power`.
- **`register-kiro-power.{ps1,sh}` helper script** (under `dist/scripts/`): standalone Kiro-registry registration. Used by Phase 6.5; can also be invoked manually if needed.
- **Test isolation**: all test scripts that invoke `bootstrap` now pass `--no-register-kiro-power` to avoid corrupting the user's real Powers registry during regression runs.

### Documentation

- Memory entry `kiro_power_install_arch.md` documents the 2-layer Power install model (workspace + user-scoped) so the reverse-engineered protocol survives session compactions.

## [1.0.0] - 2026-05-20

Initial hackathon release. Built across 8 Epics over 2 days, May 19-20, 2026.

### Added

**Lane 1 — Kiro-native subagents** (8 total under `dist/agents/`):
- `dlc-explore-fast` — Haiku-tier breadth-first code scanner
- `dlc-reviewer-security` — 5-domain OWASP review (PII, compliance, auth, injection, IAM)
- `dlc-reviewer-ux` — UX heuristic review with clarity/consistency/states checks
- `dlc-reviewer-a11y` — WCAG 2.2 AA-flavored quick scan
- `dlc-reviewer-perf` — 5-domain performance review (Core Web Vitals, backend latency, complexity, bundle, memory)
- `dlc-deep-analyst` — Opus-tier cross-cutting synthesis
- `dlc-test-writer` — generates tests matching project framework + conventions
- `dlc-doc-writer` — syncs docs to code while preserving project voice

**Lane 2 — Hook surface** (14 total under `dist/hooks/`):
- User-triggered: `reverse-engineer-kb`, `kb-gap-analysis`, `map-codebase`, `babysit-pr`, `hotfix-revert`, `check-dlc-job`, `on-pr-opened`, `on-pr-merged`, `resume-dlc-sdlc`
- File-edited (auto-fire on Kiro Spec saves): `on-requirements-saved`, `on-design-saved`, `on-tasks-saved`
- Per-task (postTaskExecution): `on-task-complete` (coverage gate via dlc-test-writer), `on-task-polish` (docstring alignment via dlc-doc-writer)

**Bridge scripts** (18 files under `dist/scripts/`, PS + bash parity):
- `dlc-bridge.{ps1,sh}` — main entry; wraps `claude -p --append-system-prompt-file <SKILL.md> --permission-mode bypassPermissions`
- `dlc-bridge-verbs.{ps1,sh}` — verb-to-skill-path resolver + task-template loader
- `dlc-bridge-retry.{ps1,sh}` — exponential-backoff retry (2s/8s/32s) on 429/5xx/timeout/connection-reset
- `dlc-bridge-status.{ps1,sh}` — status-file lifecycle (running → complete/error/cancelled) at `.dlc/_bridge-jobs/<jobId>.status.json`
- `state-update.{ps1,sh}` — atomic state.md transitions (init/advance/skip/record_pr/escalate/finalize)
- `slug-derive.{ps1,sh}` — `.kiro/specs/<slug>/<artifact>.md` → `<slug>`
- `mode-resolve.{ps1,sh}` — read `.dlc.config.json` `aidlcDepth` → interactive/confident/autopilot
- `debounce-check.{ps1,sh}` — 30s fire-suppression with file-lock (prevents 4-fires-per-save cost spikes)
- `id-propagate.{ps1,sh}` — Jaccard similarity match + idempotent `<!-- FR-x -->` / `<!-- WI-x -->` HTML-comment injection

**Templates** (under `dist/templates/`):
- `state.md.template` — DLC-orchestrator-compatible state schema
- `verb-tasks/*.txt` — 12 verb-task templates (one per supported verb)

**Power packaging** (root):
- `POWER.md` — Kiro Power frontmatter (5 fields per Phase 0 spec)
- `mcp.json` — empty object (forward-compat per D-3)
- `steering/dlc-augment.md` — lane-selection guide + Flow Orchestration section + state.md mechanics

**Installer** (root):
- `bootstrap.ps1` — Windows installer, 7 phases (resolve target → prereqs → idempotency → file copy → optional config → embedded smoke tests → playbook print)
- `bootstrap.sh` — POSIX parity
- Exit codes: 0 success, 8 smoke fail, 9 prereq fail, 10 file conflict
- Flags: `--into <path>`, `--force`, `--with-dlc-config`, `--no-smoke-tests`, `--quiet`, `--from-git <url>`

**Bridge enhancements** (Epic 2-3):
- Defense-in-depth input validation: path traversal blocked, integer ranges enforced, enum mode validated
- Argument sanitization: array passing in PS, `--` separator in bash; injection negative tests pass
- Exit-code contract documented: 0 success, 2 no-claude, 3 no-plugin, 4 invalid-input, 5 retries-exhausted, 6 skill-error, 7 cancelled
- Signal handling: Ctrl+C / SIGTERM marks status file `cancelled`, exit 7
- `outputManifest` field populated for synchronous runs (best-effort regex scan of stdout)

**State coordination** (Epic 7):
- `.dlc/<slug>/state.md` mirrors DLC's terminal `/dlc:run` orchestrator state
- Atomic transitions via temp + rename
- Decisions Log appended on every phase advance
- Phase status table tracks 1, 2a, 2b, 2c, 3, 4, 5, 6, 7, 8 with started/completed timestamps

**Test suite** (16 test files per shell, 31 total under `.dlc/dlc-supercharge/tests/`):
- `test-schemas` — canonical .kiro.hook schema validation (14 hooks)
- `test-bridge-dryrun` — 12 verbs × dry-run JSON output
- `test-injection` — 5 sanitization scenarios (PS + bash)
- `test-validation` — 9 input-validation negative cases
- `test-retry` — transient detection + exhaustion logic
- `test-status-file` — status lifecycle (running/complete/error/cancelled)
- `test-signal` — bash signal-trap (Ctrl+C → exit 7, status marked cancelled)
- `test-power-manifest` — byte-identity check between workspace and bundle (68 assertions)
- `test-install` — end-to-end install into temp workspace
- `test-docs-drift` — POWER.md + steering inventory match actual files
- `test-integration` — sandbox-repo install + 3-verb dry-run (optional --live flag)
- `test-logging` — 5 rapid invocations produce 5 unique status files (FR-39)
- `test-state-update` — atomic state.md transitions, 19 assertions
- `test-debounce` — 30s window + parallel-invocation safety
- `test-id-propagate` — Jaccard match + idempotency
- `test-slug-mode-resolve` — slug extraction + mode resolution
- `test-id-stability` — cross-shell idempotency
- `test-manual-dlc-compat` — install doesn't modify `~/.claude/plugins/cache/dlc-automation/`

**Documentation**:
- `POWER.md` (this Power's metadata)
- `README.md` (this file's home, install + verb reference)
- `HACKATHON-DRESS-REHEARSAL.md` (T+0..T+120 sign-off checklist)
- Workspace `.kiro/DLC-SUPERCHARGE-README.md` (D-minus narrative + troubleshooting)
- 8 Epic plans under workspace `.dlc/dlc-supercharge/plans/`
- PRD v3 (locked) + tech design v1 (locked) under workspace `.dlc/`

### Notes

This is a hackathon-track release. v1.0.0 is the initial production-quality cut. Future revisions may add:
- Kiro marketplace publish path (FR-26 path 3 — needs Kiro docs)
- Per-verb `outputManifest` pattern config (currently uses 5-pattern regex)
- Bridge log rotation policy (currently unbounded, user's responsibility)
- Additional verbs as `/dlc:` plugin grows
