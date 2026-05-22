# Changelog

All notable changes to DLC SuperCharge are documented in this file. Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
