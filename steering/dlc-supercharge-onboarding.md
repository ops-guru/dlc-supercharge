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

If **any** prerequisite is missing, STOP. Print a clear install pointer and ask the user to install it before retrying:

| Missing | Install pointer |
|---|---|
| `claude` | https://docs.claude.com/claude-code |
| `uv` | `irm https://astral.sh/uv/install.ps1 \| iex` (Windows) or `curl -LsSf https://astral.sh/uv/install.sh \| sh` (POSIX) |
| `gh` | https://cli.github.com |
| `git` | https://git-scm.com/downloads |

Do NOT attempt to install prerequisites silently. The user must have already approved their installation, and on Windows specifically the elevation prompts can hang a non-interactive shell.

---

## Install path A — workspace IS the dlc-supercharge source repo

If the user invoked Kiro inside the `kiro-bridge-poc` (or fork) repo itself, `bootstrap.{ps1,sh}` is already on disk. Just run it from `<workspace>/dlc-supercharge/`:

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File dlc-supercharge/bootstrap.ps1
```

```bash
# POSIX
bash dlc-supercharge/bootstrap.sh
```

Detect this case by:

```bash
test -f dlc-supercharge/bootstrap.sh && test -f dlc-supercharge/bootstrap.ps1
```

Skip install path B if this matches.

---

## Install path B — workspace is somewhere else (typical Kiro install)

Kiro's native installer has cached `POWER.md` + `steering/` at `~/.kiro/powers/installed/dlc-supercharge/`, but `bootstrap.{ps1,sh}` and `dist/` are not in that cache. Clone the source repo to a scratch path and run bootstrap from there. Bootstrap copies what it needs into `<workspace>/.kiro/` and exits — the clone is throw-away.

```bash
SCRATCH=$(mktemp -d 2>/dev/null || powershell -NoProfile -Command "[System.IO.Path]::GetTempPath() + [System.IO.Path]::GetRandomFileName()")
git clone --depth 1 https://github.com/ops-guru/kiro-bridge-poc "$SCRATCH"
```

Then run bootstrap from `$SCRATCH/dlc-supercharge/`:

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File "$SCRATCH/dlc-supercharge/bootstrap.ps1"
```

```bash
# POSIX
bash "$SCRATCH/dlc-supercharge/bootstrap.sh"
```

After bootstrap exits with status 0, the scratch clone can be removed:

```bash
rm -rf "$SCRATCH"  # or Remove-Item -Recurse -Force on Windows
```

---

## What bootstrap actually does (informational — for the agent's mental model)

1. **Prereq checks** (re-runs the checks above, defensively).
2. **Detects existing install** — idempotent re-run. If a current install is detected, prints "already installed, skipping" and exits 0.
3. **Workspace install**: copies `dist/hooks/*.kiro.hook` → `<workspace>/.kiro/hooks/`, `dist/agents/*.md` → `<workspace>/.kiro/agents/`, `dist/scripts/*` → `<workspace>/.kiro/scripts/`, `dist/templates/verb-tasks/*.txt` → `<workspace>/.kiro/powers/dlc-supercharge/templates/verb-tasks/`, `steering/dlc-augment.md` → `<workspace>/.kiro/steering/dlc-augment.md`.
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
| Smoke test 2 fails with "dlc_bridge module not found" | `uv sync` didn't run, or the venv is stale | `cd <workspace>/dlc-supercharge && uv sync` then retry |
| Hooks don't appear in Kiro's Agent Hooks panel after install | Kiro didn't refresh `.kiro/` | Tell user to reload the `.kiro/` folder in Kiro IDE (right-click → Refresh) |

---

## After install

Route to [dlc-augment.md](dlc-augment.md) for normal operation — that's the always-loaded steering file that teaches the Kiro main agent which Lane (subagent vs bridge) to use for which task type. The onboarding flow is one-shot; it does not need to load again unless `.kiro/hooks/check-dlc-job.kiro.hook` is later deleted.
