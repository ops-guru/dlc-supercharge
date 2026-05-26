# dlc-supercharge

A Kiro Power that bridges the `/dlc:` Claude Code plugin into Kiro IDE's AIDLC workflow. Adds 14 hooks, 8 subagents, and a state-coordinated D-minus integration pattern with one-command install.

**v2.0.0** ships the runtime as a single Python 3.11+ codebase under `src/dlc_bridge/`. The v1.1 PowerShell + POSIX bash dual-stack has been replaced. See `CHANGELOG.md` for the full BREAKING-changes manifest.

## Install

### Option 1 — Kiro "Add Power from GitHub" (one-click; recommended for end users)

Most ergonomic path. Uses Kiro's native Power import UI:

1. In Kiro IDE → **Settings → Powers → Add a custom Kiro power → Import power from GitHub**.
2. Paste the repo URL: `https://github.com/ops-guru/kiro-bridge-poc` (or your fork).
3. Kiro caches `POWER.md`, `mcp.json`, and `steering/` into `~/.kiro/powers/installed/dlc-supercharge/` and registers the Power in `~/.kiro/powers/installed.json` + `~/.kiro/powers/registries/user-added.json`.
4. On first `/dlc:` keyword in a workspace, Kiro loads [`steering/dlc-supercharge-onboarding.md`](steering/dlc-supercharge-onboarding.md). The agent runs prereq checks, `git clone`s the repo into a scratch path, executes `bootstrap.{ps1,sh} --no-register-kiro-power` (Kiro has already handled the user-scoped registration), runs the 3 embedded smoke tests, then routes to normal operation.

The agent does not require user intervention beyond approving the bootstrap bash call. If a prereq is missing (no `claude` / `uv` / `gh` / `git`), the agent surfaces the install pointer and stops.

### Option 2 — Local clone + bootstrap (CI / fleet deploys)

```powershell
# Windows
git clone https://github.com/ops-guru/kiro-bridge-poc dlc-supercharge
powershell -NoProfile -ExecutionPolicy Bypass -File dlc-supercharge\bootstrap.ps1 -Into .
```

```bash
# POSIX
git clone https://github.com/ops-guru/kiro-bridge-poc dlc-supercharge
bash dlc-supercharge/bootstrap.sh --into .
```

### Option 3 — Direct from git URL

```powershell
powershell -File dlc-supercharge\bootstrap.ps1 -FromGit https://github.com/ops-guru/kiro-bridge-poc -Into .
```

```bash
bash dlc-supercharge/bootstrap.sh --from-git https://github.com/ops-guru/kiro-bridge-poc --into .
```

The `--from-git` flag clones the Power into a temp dir, runs install, cleans up on success.

### Option 4 — Manual file copy

Copy bundle contents into target workspace:
- `dist/hooks/*.kiro.hook` → `<workspace>/.kiro/hooks/`
- `dist/agents/*.md` → `<workspace>/.kiro/agents/`
- `dist/templates/verb-tasks/*.txt` → `<workspace>/.kiro/powers/dlc-supercharge/templates/verb-tasks/`
- `dist/templates/state.md.template` → `<workspace>/.kiro/powers/dlc-supercharge/templates/`
- `steering/dlc-augment.md` → `<workspace>/.kiro/steering/`

After copying, run `uv sync` from the workspace root to install the Python runtime (or let `bootstrap.{ps1,sh}` Phase 4.5 do it).

### Prerequisites

The installer checks:
- `claude` CLI on PATH (`claude --version` exits 0)
- `/dlc:` plugin loaded (`~/.claude/plugins/cache/dlc-automation/dlc/<version>/skills/`)
- **`uv` (Astral) launcher** — auto-installed by bootstrap Phase 1.5 unless `-NoAutoInstallUv` / `--no-auto-install-uv` is passed. Opt-out flow exits with code 9 and the manual-install URL.
- **Python 3.11+** — uv-managed; `uv python install` runs on first `uv sync` if not already present.
- PowerShell execution policy (Windows): RemoteSigned, Unrestricted, or Bypass
- `gh` CLI on PATH (warn only — needed for `babysit-pr`, `hotfix-revert`)
- Anthropic auth: `ANTHROPIC_API_KEY` env var OR `~/.claude/credentials`
- Free disk space ≥ 100 MB

Fail-stop on any required prereq. Warn-only for optional ones.

## Architecture

The runtime is a Python package under `src/dlc_bridge/`:

- `cli.py` — entry point for `uv run dlc-bridge <verb> ...`; argument validation, hash-cache check, retry-wrapped `claude -p` invocation, foreground/background dispatch.
- `verbs.py` — verb → skill-path resolver and prompt assembly.
- `cache.py` — FR-8/9/10 hash-cache with `cache_version: 2`.
- `status.py` — FR-6 status-file lifecycle (`running` → `complete`/`error`/`cancelled`) at `.dlc/_bridge-jobs/<jobId>.status.json`.
- `retry.py` — FR-7 exponential backoff (3 attempts, 2s/8s/32s) on 429/5xx/timeout/connection-reset.
- `background_runner.py` — FR-4 detached-child wrapper (Windows `DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP`; POSIX `start_new_session=True`).
- `util/` — `encoding`, `hash`, `slug`, `mode`, `emit`, `state`, `id_propagate`, `epic_inject`, `debounce`, `power`.
- `hooks/` — 14 hook modules (one per `.kiro.hook` JSON), invokable as `uv run python -m dlc_bridge.hooks.<name>`.

`tests/` holds the pytest suite (`unit/`, `integration/`, `parity/`) with `--cov-fail-under=80` gating.

## Verbs

The bridge supports 12 user-facing verbs (plus 4 review-* internal dispatches), each routing to a `/dlc:` skill:

| Verb | Skill | Purpose |
|---|---|---|
| `reverse-engineer-kb` | `/dlc:reverse-engineer-kb` | 3-pass KB build from legacy codebase |
| `kb-gap-analysis` | `/dlc:kb-gap-analysis` | Classify requirements vs KB |
| `map-codebase` | `/dlc:map` | 4-parallel-agent architectural map |
| `babysit-pr` | `/dlc:babysit` | CI stabilization + comment triage |
| `hotfix` | `/dlc:hotfix` | Emergency revert / narrow fix |
| `analyze-requirements` | `/dlc:analyze-requirements` | Enriched PRD from requirements doc |
| `produce-tech-design` | `/dlc:produce-tech-design` | Tech design with WI-x/D-x/R-x IDs |
| `plan-implementation` | `/dlc:plan-implementation` | Epic-level implementation plan |
| `discover` | `/dlc:discover` | Discovery brief |
| `finalize-sdlc` | `/dlc:finalize-sdlc` | Post-merge finalization |
| `review-pr` | `/dlc:review-pr` | Standalone PR review |
| `stabilize-pr` | `/dlc:stabilize-pr` | CI triage without full review |

Invoke via the console-script entry:

```sh
uv run dlc-bridge <verb> --target <path> [--dry-run] [--background] [--max-budget-usd 5]
```

Or fire the matching Kiro hook from the Agent Hooks panel (each hook prompt assembles the bridge invocation and surfaces JSON output back to chat). The hooks invoke either `uv run dlc-bridge ...` or `uv run python -m dlc_bridge.hooks.<name> ...`.

## Test

```sh
uv run pytest tests/ --cov=src/dlc_bridge
```

Runs the full unit + integration + parity suite (~501 tests, ~37 s on a warm cache). Parity tests under `tests/parity/` cross-validate against v1.1 PS where `powershell.exe` / `pwsh` is on PATH (skip cleanly elsewhere). Coverage gate is 80%.

`uv run pytest tests/ -m parity` runs only the FR-19 parity suite.

## Configuration

Optional `<workspace>/.dlc.config.json` (template at `dist/config/dlc.config.json.template`):

```json
{
  "version": "1.0.0",
  "defaults": {
    "maxBudgetUsd": 5,
    "mode": "default",
    "maxFiles": 500,
    "aidlcDepth": "medium"
  },
  "verbs": {}
}
```

`defaults.aidlcDepth` maps to interaction mode (read by `dlc_bridge.util.mode`):
- `light` → `interactive` (more user confirmation)
- `medium` → `confident` (default)
- `deep` → `autopilot` (minimal interruption)

If `.dlc.config.json` is absent, `confident` is the default.

## Troubleshooting

See `.kiro/DLC-SUPERCHARGE-README.md` (workspace-side, installed by bootstrap) for the full troubleshooting guide.

See `SMOKE-TEST-CHECKLIST.md` for the fresh-VM verification flow that maintainers should run before tagging a release.

## License

MIT. See `LICENSE` in this directory (or root of the Power-bundle repo).

## More

* Hackathon dress rehearsal: `HACKATHON-DRESS-REHEARSAL.md` (v2.0 addendum at top)
* Tech design: `.dlc/dlc-supercharge-python-migration/designs/tech-design.md` (the v1.1 → v2.0 migration plan)
* PRD: `.dlc/dlc-supercharge-python-migration/requirements.prd.md`
