# DLC SuperCharge v2.0.0 — Fresh-VM Smoke Test Checklist (WI-23)

**Purpose**: end-to-end verification of the v2.0.0 install flow on a fresh OS. Run this **before** tagging the `v2.0.0` release. The automated parity suite (74 tests under `tests/parity/`) and the cross-platform CI matrix (`[windows, macos, ubuntu] × [3.11, 3.12]`) cover the automatable surface; this checklist verifies the human-observable install + first-fire behaviour that CI cannot reach.

**Audience**: human maintainer running on a clean VM (or fresh container) without `uv`, without Python, and without prior DLC SuperCharge state.

**Time budget**: ~15 minutes per OS leg.

**Date executed**: _______________  **Operator**: _______________  **OS**: _______________

---

## 0. Pre-test setup

- [ ] Fresh VM / container, no prior dlc-supercharge state
- [ ] No `uv` installed (`uv --version` returns "not found" or equivalent)
- [ ] No Python 3.11+ installed system-wide (uv will manage it)
- [ ] `claude` CLI installed and `claude --version` exits 0
- [ ] `/dlc:` plugin cache present: `ls ~/.claude/plugins/cache/dlc-automation/dlc/*/skills/` returns paths
- [ ] DLC SuperCharge Power bundle accessible (local clone OR git URL ready)
- [ ] Test workspace cloned to a clean directory (`mkdir smoke && cd smoke && git init`)

---

## 1. Bootstrap end-to-end — default flow (uv auto-install)

```powershell
# Windows
cd <power-bundle-root>
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap.ps1 -Into <smoke-workspace>
```

```bash
# POSIX
cd <power-bundle-root>
bash bootstrap.sh --into <smoke-workspace>
```

Verify each phase prints its banner and exits successfully:

- [ ] **Phase 1** — Resolve target. Banner: `Phase 1: Resolve target`. Target path printed.
- [ ] **Phase 1.5** — Detect uv (Astral). Banner: `Phase 1.5: Detect uv (Astral Python launcher)`. Detection prints `uv not found; installing via Astral` (or similar). Install URL fetched and executed. `uv --version` after this phase returns a version string.
- [ ] **Phase 2** — Prereqs. All PASS or only WARN entries. No FAIL.
- [ ] **Phase 3** — Idempotency. Either fresh install or "already installed; refreshing" path.
- [ ] **Phase 4** — File copy. ~28–39 files copied (hooks, agents, templates, steering).
- [ ] **Phase 4.5** — Sync Python env with uv. Banner: `Phase 4.5: Sync Python environment with uv`. `uv sync` resolves dependencies; first run installs Python 3.11+ + dependencies (~10–60 s on a warm Astral mirror).
- [ ] **Phase 5** — Optional `.dlc.config.json` (if invoked with `--with-dlc-config`).
- [ ] **Phase 6** — Smoke tests. Banner: `Phase 6: Embedded smoke tests`. Output includes `uv run dlc-bridge help` invocation (PYTHON path preferred, v1.1 fallback no longer reachable since v1.1 scripts are deleted). Final line: `Smoke tests: 3/3 PASS` (or similar).
- [ ] **Phase 7** — Playbook print. Lists 14 hooks + verb invocation examples.
- [ ] Exit code: **0**
- [ ] Total elapsed (cold cache): ____ s (target: < 90 s on a fast network; uv+Python install dominates)
- [ ] Total elapsed (warm cache, re-run): ____ s (target: < 15 s)

---

## 2. Verb-help sanity (`uv run dlc-bridge help`)

```sh
cd <smoke-workspace>
uv run dlc-bridge help
```

- [ ] Exit code: 0
- [ ] Output lists 12 user-facing verbs + 4 review-* verbs = 16 total
- [ ] Each verb has a one-line description
- [ ] Output ends with usage block: `Usage: dlc-bridge <verb> [options]`

---

## 3. Hook dry-run (`check-dlc-job`)

```sh
cd <smoke-workspace>
uv run python -m dlc_bridge.hooks.check_dlc_job --slug test --dry-run
```

(Or: `uv run dlc-bridge check-dlc-job --slug test --dry-run` if exposed via the CLI verb dispatch.)

- [ ] Exit code: 0
- [ ] Stdout contains the `HOOK_DONE` terminal marker
- [ ] Stdout contains structured `KEY=value` markers: `NO_JOBS=<reason>` when the bridge has never been invoked on this workspace, OR `JOB=id=...|verb=...|status=...|started=...|ended=...|exit=...|pid=...|log=...` rows followed by `COUNT_RUNNING=N`, `COUNT_COMPLETE=N`, `COUNT_CACHE_HIT=N`, `COUNT_ERROR=N`, `COUNT_CANCELLED=N`, `TOTAL_REPORTED=N` when jobs exist. (The hook does NOT emit JSON; it emits a `KEY=value` stream the calling Kiro agent renders into a markdown table — see [`check_dlc_job.py`](../src/dlc_bridge/hooks/check_dlc_job.py) module docstring.)
- [ ] Stderr is either empty or contains only structured KEY=value log lines (no Python traceback)

---

## 4. First Kiro hook fire (`on-requirements-saved` end-to-end)

Pre-step: install Kiro IDE on the smoke VM if not present; open `<smoke-workspace>` as a Kiro workspace.

- [ ] Create `.kiro/specs/smoke-test/requirements.md` with placeholder content (`# Smoke Test\n\nA test requirements doc.`).
- [ ] Save the file inside Kiro (Cmd/Ctrl+S, NOT external save — `fileEdited` event must fire).
- [ ] Confirm `on-requirements-saved` hook fires (visible in Kiro chat panel or Kiro logs).
- [ ] Bridge invocation visible: `uv run python -m dlc_bridge.hooks.on_requirements_saved .kiro/specs/smoke-test/requirements.md`.
- [ ] Hook completes (claude call exits, status file finalized).
- [ ] Artifact produced: `.dlc/smoke-test/requirements.prd.md` exists and parses as Markdown.
- [ ] `.dlc/smoke-test/state.md` initialized with `Current phase: 1 — Requirements` and the smoke-test slug.
- [ ] Status file at `.dlc/_bridge-jobs/<jobId>.status.json` shows `status: complete`, has non-null `endedAt`, exit code 0.

---

## 5. Cache-hit on re-save (FR-8/9/10)

Without modifying the requirements.md content, save it again in Kiro (Ctrl+S on the unchanged buffer).

- [ ] Second hook invocation visible.
- [ ] **Second invocation elapsed time: ____ ms** (target: < 1500 ms per NFR-1).
- [ ] Stdout contains the `BRIDGE_CACHED=` marker (rather than `BRIDGE_OK=`).
- [ ] `.dlc/smoke-test/requirements.prd.md` mtime did NOT change (cache returned the existing artifact path).
- [ ] No second `claude` API call was made (verify via Anthropic billing dashboard or `~/.claude/logs/` if available).

---

## 6. `-NoAutoInstallUv` / `--no-auto-install-uv` opt-out

Reset the VM (or use a second fresh VM): uninstall uv (`rm -rf ~/.local/share/uv ~/.local/bin/uv`).

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap.ps1 -Into <smoke-workspace-2> -NoAutoInstallUv
```

```bash
# POSIX
bash bootstrap.sh --into <smoke-workspace-2> --no-auto-install-uv
```

- [ ] Exit code: **9** (per the bootstrap exit-code contract).
- [ ] Stderr contains the manual-install URL: `https://astral.sh/uv/install.{ps1,sh}` (or the appropriate Astral docs URL).
- [ ] No partial install state in `<smoke-workspace-2>` (or a clean rollback message printed).

---

## 7. POSIX leg (macOS or Linux VM)

Repeat steps 1–6 on a separate macOS or Linux VM:

- [ ] Section 1 passes on macOS (or Linux).
- [ ] Section 2 passes.
- [ ] Section 3 passes.
- [ ] Section 4 — if Kiro IDE is available on POSIX, run the full flow; otherwise dry-run the hook module via `uv run python -m dlc_bridge.hooks.on_requirements_saved <path>` directly and verify artifact production.
- [ ] Section 5 passes.
- [ ] Section 6 — `bash bootstrap.sh --no-auto-install-uv` exits 9.

---

## 8. Sign-off

- [ ] All sections green OR documented exception below
- [ ] Total elapsed across all OS legs: ____ min
- [ ] Maintainer confidence (1-5, where 5 = ready for v2.0.0 tag): ___
- [ ] Operator: _______________  Date: _______________

### Notes / exceptions

(Use this space to capture any deviations, errors, or improvements for the next release-candidate.)

---

## What this checklist does NOT cover (covered elsewhere)

- **Verb correctness** (does `map-codebase` produce a correct map for a given target?) — covered by Lane 1 integration tests + the parity suite for the bridge-level dispatch shape.
- **Hash-cache byte-equivalence with v1.1** — covered by `tests/parity/test_hash_parity.py` (12 cases, runs on every CI leg).
- **State.md / id-propagate / epic-inject byte-equivalence with v1.1** — covered by `tests/parity/test_state_parity.py`, `test_id_propagate_parity.py`, `test_epic_inject_parity.py` (15 cross-language + regression cases; run on Windows CI leg).
- **CLI-level injection negative tests** — covered by `tests/integration/test_cli_injection.py`.
- **Cross-platform Python smoke** — covered by the CI matrix (`[windows, macos, ubuntu] × [3.11, 3.12]`).

This checklist focuses on the **fresh-VM install** experience and the **first hook fire** end-to-end, which require a human at a keyboard and cannot be staged in CI.
