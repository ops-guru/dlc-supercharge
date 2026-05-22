# dlc-supercharge

A Kiro Power that bridges the `/dlc:` Claude Code plugin into Kiro IDE's AIDLC workflow. Adds 14 hooks, 8 subagents, and a state-coordinated D-minus integration pattern with one-command install.

## Install

### Option 1 — Local clone + bootstrap (recommended)

```powershell
# Windows
git clone <power-url> dlc-supercharge
powershell -NoProfile -ExecutionPolicy Bypass -File dlc-supercharge\bootstrap.ps1 -Into .
```

```bash
# POSIX
git clone <power-url> dlc-supercharge
bash dlc-supercharge/bootstrap.sh --into .
```

### Option 2 — Direct from git URL

```powershell
powershell -File dlc-supercharge\bootstrap.ps1 -FromGit https://github.com/<owner>/dlc-supercharge -Into .
```

```bash
bash dlc-supercharge/bootstrap.sh --from-git https://github.com/<owner>/dlc-supercharge --into .
```

The `--from-git` flag clones the Power into a temp dir, runs install, cleans up on success.

### Option 3 — Manual file copy

Copy bundle contents into target workspace:
- `dist/hooks/*.kiro.hook` → `<workspace>/.kiro/hooks/`
- `dist/agents/*.md` → `<workspace>/.kiro/agents/`
- `dist/scripts/*` → `<workspace>/.kiro/scripts/`
- `dist/templates/verb-tasks/*.txt` → `<workspace>/.kiro/powers/dlc-supercharge/templates/verb-tasks/`
- `dist/templates/state.md.template` → `<workspace>/.kiro/powers/dlc-supercharge/templates/`
- `steering/dlc-augment.md` → `<workspace>/.kiro/steering/`

### Prerequisites

The installer checks:
- `claude` CLI on PATH (`claude --version` exits 0)
- `/dlc:` plugin loaded (`~/.claude/plugins/cache/dlc-automation/dlc/<version>/skills/`)
- PowerShell execution policy (Windows): RemoteSigned, Unrestricted, or Bypass
- `gh` CLI on PATH (warn only — needed for `babysit-pr`, `hotfix-revert`)
- Anthropic auth: `ANTHROPIC_API_KEY` env var OR `~/.claude/credentials`
- Free disk space ≥ 100 MB

Fail-stop on any required prereq. Warn-only for optional ones.

## Verbs

The bridge supports 12 verbs, each routing to a `/dlc:` skill:

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

Invoke via bridge:
```powershell
.kiro\scripts\dlc-bridge.ps1 <verb> -Target <path> [-DryRun] [-Background] [-MaxBudgetUsd 5]
```

Or fire the matching Kiro hook from the Agent Hooks panel (each hook prompt assembles the bridge invocation and surfaces JSON output back to chat).

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

`defaults.aidlcDepth` maps to interaction mode (read by `mode-resolve.{ps1,sh}` helper):
- `light` → `interactive` (more user confirmation)
- `medium` → `confident` (default)
- `deep` → `autopilot` (minimal interruption)

If `.dlc.config.json` is absent, `confident` is the default.

## Troubleshooting

See `.kiro/DLC-SUPERCHARGE-README.md` (workspace-side, installed by bootstrap) for the full troubleshooting guide.

## License

MIT. See `LICENSE` in this directory (or root of the Power-bundle repo).

## Architecture

Two execution lanes coordinated through `.dlc/<slug>/state.md`. Full design at the source project's `.dlc/designs/2026-05-19-dlc-supercharge.md`. Hackathon dress rehearsal at `HACKATHON-DRESS-REHEARSAL.md`.
