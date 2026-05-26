---
inclusion: conditional
description: "First-use install + smoke-test for DLC SuperCharge. Triggered when the user invokes a /dlc:* keyword and the workspace has no .kiro/hooks/dlc-supercharge marker yet."
---

# DLC SuperCharge — Onboarding (first-use install)

**Read this file ONLY when the workspace is not yet set up.** Detect non-install with this single check:

```bash
test -f .kiro/hooks/check-dlc-job.kiro.hook
```

- **Exists** → DLC SuperCharge workspace install is in place. Stop reading this file; route to `dlc-augment.md` for normal operation.
- **Missing** → continue with this onboarding flow.

---

## Why a separate install step exists

DLC SuperCharge ships **far more than the canonical Kiro Power layout**. Kiro's native "Add Power from GitHub" installer caches `POWER.md`, `mcp.json`, and `steering/*` under `~/.kiro/powers/installed/dlc-supercharge/` — and that's all it touches. But this Power also ships:

- **14 hooks** that must land at `<workspace>/.kiro/hooks/*.kiro.hook` for Kiro's runtime to fire them on `fileEdited` / `userTriggered` / `postTaskExecution` events.
- **8 subagents** at `<workspace>/.kiro/agents/*.md`.
- **A Python bridge** (`src/dlc_bridge/`) the hooks invoke via `uv run python -m dlc_bridge.hooks.<name>`.
- **Verb-task templates** and **config templates** under `<workspace>/.kiro/powers/dlc-supercharge/`.

Kiro's native installer cannot place these — the bundled `bootstrap.{ps1,sh}` installer does that. This onboarding flow runs it on the user's behalf so they never have to leave Kiro.

---

## Prerequisite checks (read-only)

Before running bootstrap, surface a clear go/no-go to the user. Run these in parallel via Bash:

```bash
# Claude Code CLI (the bridge's worker)
command -v claude && claude --version

# uv (Astral Python launcher — bridge runtime)
command -v uv && uv --version

# GitHub CLI (used by some hooks)
command -v gh && gh --version

# git (used to clone the Power source for bootstrap)
command -v git && git --version
```

If **any** of these system tools is missing, STOP. Print a clear install pointer and ask the user to install it before retrying:

| Missing | Install pointer |
|---|---|
| `claude` | https://docs.claude.com/claude-code |
| `uv` | `irm https://astral.sh/uv/install.ps1 \| iex` (Windows) or `curl -LsSf https://astral.sh/uv/install.sh \| sh` (POSIX) |
| `gh` | https://cli.github.com |
| `git` | https://git-scm.com/downloads |

Do NOT attempt to install these system tools silently — the user must approve their installation, and on Windows the elevation prompts can hang a non-interactive shell. (`uv` is the one exception: bootstrap Phase 1.5 auto-installs it via the Astral script unless `-NoAutoInstallUv` is passed.)

**Do NOT check for, or ask the user to install, the `/dlc:` Claude Code plugin here.** Bootstrap Phase 2.5 auto-installs it (`claude plugin marketplace add ops-guru/dlc-plugin` + `claude plugin install dlc@dlc-automation`) when `claude` is authenticated — no API key required, `claude login` auth is sufficient. Let bootstrap handle it; surfacing a manual plugin-install step here is a known anti-pattern (it pre-empts the auto-install).

---

## Install path A — workspace IS the dlc-supercharge source repo

If the user invoked Kiro inside the `dlc-supercharge` repo itself (or a fork), `bootstrap.{ps1,sh}` is already on disk at the **repo root**. Just run it:

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap.ps1
```

```bash
# POSIX
bash bootstrap.sh
```

Detect this case by:

```bash
test -f bootstrap.sh && test -f bootstrap.ps1 && test -f POWER.md
```

Skip install path B if this matches.

---

## Install path B — workspace is somewhere else (typical Kiro install)

Kiro's native installer has cached `POWER.md` + `steering/` at `~/.kiro/powers/installed/dlc-supercharge/`, but `bootstrap.{ps1,sh}`, `dist/`, and the `src/dlc_bridge/` runtime are not in that cache. Clone the source repo to a scratch path and run bootstrap from there. Bootstrap copies what it needs (including the vendored bridge runtime) into `<workspace>/.kiro/` and exits — the clone is throw-away.

```bash
SCRATCH=$(mktemp -d 2>/dev/null || powershell -NoProfile -Command "[System.IO.Path]::GetTempPath() + [System.IO.Path]::GetRandomFileName()")
git clone --depth 1 https://github.com/ops-guru/dlc-supercharge "$SCRATCH"
```

Then run bootstrap from the clone **root** (the Power bundle lives at the repo root, not a subdir):

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File "$SCRATCH/bootstrap.ps1"
```

```bash
# POSIX
bash "$SCRATCH/bootstrap.sh"
```

After bootstrap exits with status 0, the scratch clone can be removed:

```bash
rm -rf "$SCRATCH"  # or Remove-Item -Recurse -Force on Windows
```

---

## What bootstrap actually does (informational — for the agent's mental model)

1. **Phase 1.5 — uv detection** (auto-installs uv if missing, unless `-NoAutoInstallUv`).
2. **Phase 2.5 — /dlc: plugin auto-install** (K4): `claude plugin marketplace add ops-guru/dlc-plugin` + `claude plugin install dlc@dlc-automation` if the plugin cache is missing. Works with `claude login` auth — no ANTHROPIC_API_KEY needed. Opt out with `-NoAutoInstallPlugin`.
3. **Phase 2 — prereq checks** (claude, uv, gh, disk).
4. **Detects existing install** — idempotent re-run. If a current install is detected, prints "already installed, skipping" and exits 0.
5. **Workspace install**: copies `dist/hooks/*.kiro.hook` → `<workspace>/.kiro/hooks/`, `dist/agents/*.md` → `<workspace>/.kiro/agents/`, `dist/scripts/*` → `<workspace>/.kiro/scripts/`, `dist/templates/verb-tasks/*.txt` → `<workspace>/.kiro/powers/dlc-supercharge/templates/verb-tasks/`, `steering/dlc-augment.md` → `<workspace>/.kiro/steering/dlc-augment.md`.
6. **Vendors the Python bridge runtime** (K5): copies `src/dlc_bridge/` + `pyproject.toml` + `uv.lock` + `README.md` → `<workspace>/.kiro/powers/dlc-supercharge/runtime/`, writes a target `<workspace>/pyproject.toml` (uv path-dep on the vendored runtime), runs `uv sync`, and verifies `import dlc_bridge` succeeds. This is what lets the hooks' `uv run python -m dlc_bridge.hooks.<name>` resolve in any workspace.
4. **User-scoped registration** (Phase 6.5): invokes `register-kiro-power.{ps1,sh}` to register the Power in `~/.kiro/powers/installed.json` + `~/.kiro/powers/registries/user-added.json` and copy POWER.md/mcp.json/steering/ to `~/.kiro/powers/installed/dlc-supercharge/`. **Bypass with `-NoRegisterKiroPower` / `--no-register-kiro-power` when installing via Kiro's native "Add Power from GitHub" UI**, because Kiro itself has already done this step.
5. **3 embedded smoke tests**: schema validation on the installed hook JSON files, bridge dry-run (`uv run python -m dlc_bridge map-codebase --dry-run`), and POWER.md frontmatter parse.
6. **Prints the T+0..T+120 hackathon playbook** (informational).

Total wall clock: ~30 seconds on a clean install.

---

## Smoke test (post-install verification)

After bootstrap completes, verify by triggering the simplest hook:

1. In Kiro's Agent Hooks panel, the user should see all 14 DLC SuperCharge hooks listed and enabled. Tell them to look for: `reverse-engineer-kb`, `map-codebase`, `babysit-pr`, `check-dlc-job`, `on-design-saved`, etc.
2. Fire `check-dlc-job` (it's read-only — lists existing bridge jobs, no API spend).
3. Expect output of the form: `NO_JOBS=no .dlc/_bridge-jobs/ directory` on a fresh workspace (this is correct), or a table of recent jobs otherwise. Terminal `HOOK_DONE`.

If `check-dlc-job` exits non-zero or the hooks don't appear, run `<workspace>/.kiro/hooks/*` listing manually and surface the diagnostic to the user.

---

## Failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| `claude: command not found` during bootstrap | Claude Code CLI not installed | Tell user to install per https://docs.claude.com/claude-code, retry |
| `uv: command not found` during bootstrap | uv launcher missing | Tell user to install per the Astral instructions above, retry |
| Bootstrap exits non-zero in Phase 6.5 | Kiro registry write conflict (e.g., another DLC SuperCharge install is in progress) | Wait 30s, retry; or pass `--no-register-kiro-power` to skip user-scoped registration |
| Smoke test 2 fails with "dlc_bridge module not found" | `uv sync` didn't run, or the venv is stale, or an inherited `VIRTUAL_ENV` env var points elsewhere | From `<workspace>`: `unset VIRTUAL_ENV` (POSIX) / `Remove-Item Env:VIRTUAL_ENV` (PS), then `uv sync`, then retry. Confirm the vendored runtime exists at `<workspace>/.kiro/powers/dlc-supercharge/runtime/src/dlc_bridge/`. |
| Bootstrap stops at "Install the /dlc: plugin" instead of auto-installing | Running an OLD bootstrap (pre-K4), or `claude` not authenticated | Ensure you cloned `ops-guru/dlc-supercharge` (not the legacy `kiro-bridge-poc`) and ran `bootstrap` from the repo ROOT. Confirm `claude` is logged in (`claude login`). |
| Hooks don't appear in Kiro's Agent Hooks panel after install | Kiro didn't refresh `.kiro/` | Tell user to reload the `.kiro/` folder in Kiro IDE (right-click → Refresh) |

---

## After install

Route to [dlc-augment.md](dlc-augment.md) for normal operation — that's the always-loaded steering file that teaches the Kiro main agent which Lane (subagent vs bridge) to use for which task type. The onboarding flow is one-shot; it does not need to load again unless `.kiro/hooks/check-dlc-job.kiro.hook` is later deleted.
