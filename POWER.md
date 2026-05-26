---
name: "dlc-supercharge"
version: "2.1.0"
displayName: "DLC SuperCharge"
description: "Augments Kiro's AIDLC workflow with /dlc plugin capabilities — legacy-code KB build, requirements gap analysis, multi-dim review (security, ux, a11y, performance), CI babysit, hotfix revert. Two execution lanes (Kiro-native subagents and a headless bridge) coordinated through .dlc/<slug>/ artifacts."
keywords: ["dlc", "supercharge", "kb", "reverse-engineer", "gap-analysis", "babysit", "aidlc", "sdlc", "review", "hotfix"]
author: "alex.michel@equivant.com"
---

# DLC SuperCharge

Augments Kiro's native AIDLC workflow with the capabilities of the `/dlc:` Claude Code plugin. Bridges Kiro Spec mode into DLC's 10-phase SDLC orchestration so a single workspace can run both: Kiro for the user-facing Spec authoring experience, DLC for the heavyweight orchestration (legacy-code KB build, multi-pass codebase mapping, CI babysit loops, etc.).

Two execution lanes work in parallel:

- **Lane 1 — Kiro-native subagents** for in-IDE reviews, fast scans, and synthesis. Cheap, parallel-safe, no subprocess.
- **Lane 2 — Headless bridge to `claude -p`** for heavyweight `/dlc:` skills that already have orchestration code. Runs in the background; status surfaced via the `check-dlc-job` hook.

State coordination happens through `.dlc/<slug>/state.md` — the same file DLC's terminal `/dlc:run` produces, so terminal-side `/dlc:next` resumes from where Kiro left off.

## What's in this Power

### Lane 1 — Subagents (`dist/agents/`)

| Agent | Purpose |
|---|---|
| `dlc-explore-fast` | Fast breadth-first scan (Haiku-tier, parallel-safe) |
| `dlc-reviewer-security` | Security review (auth, PII, IAM, OWASP) — 5 domains |
| `dlc-reviewer-ux` | UX critique (clarity, error/empty/loading states, hierarchy) |
| `dlc-reviewer-a11y` | WCAG 2.2 AA quick scan |
| `dlc-reviewer-perf` | Performance review (CWV, backend latency, complexity, bundle, memory) |
| `dlc-deep-analyst` | Cross-cutting synthesis (Opus-tier) |
| `dlc-test-writer` | Test generation matching project conventions |
| `dlc-doc-writer` | Doc sync (README, CHANGELOG) with voice preservation |

### Lane 2 — Hooks (`dist/hooks/`)

| Hook | Trigger | Purpose |
|---|---|---|
| `reverse-engineer-kb` | userTriggered | Build `.dlc/kb/` from a legacy codebase |
| `kb-gap-analysis` | userTriggered | Classify requirements vs the KB |
| `map-codebase` | userTriggered | Fast 4-parallel-agent map of a subsystem |
| `babysit-pr` | userTriggered | CI stabilization + comment triage loop until merge-ready |
| `hotfix-revert` | userTriggered | Emergency PR revert with safety confirmation |
| `check-dlc-job` | userTriggered | List active and recent bridge jobs from `.dlc/_bridge-jobs/` |
| `on-design-saved` | fileEdited | D-minus Phase 2c→3 chain: security review + tech-design enrichment + 4-dim review + WI-x ID propagation |
| `on-requirements-saved` | fileEdited | D-minus Phase 1→2c chain: analyze-requirements + trigger scan + conditional reviews + FR-x ID propagation |
| `on-tasks-saved` | fileEdited | D-minus Phase 3 chain: plan-implementation + Epic markers + _iteration-state.md init |
| `on-pr-opened` | userTriggered | D-minus Phase 4→5: polished PR description + babysit-pr launch |
| `on-pr-merged` | userTriggered | D-minus Phase 7→8: finalize-sdlc + state.md cleanup |
| `resume-dlc-sdlc` | userTriggered | Pick up interrupted SDLC at recorded phase from `.dlc/<slug>/state.md` |
| `on-task-complete` | postTaskExecution | Per-task coverage gate via dlc-test-writer |
| `on-task-polish` | postTaskExecution | Per-task docstring/comment alignment via dlc-doc-writer |

### Scripts (`dist/scripts/`)

| Script | Role |
|---|---|
| `dlc-bridge.{ps1,sh}` | Main entry; wraps `claude -p --append-system-prompt-file <SKILL.md>` |
| `dlc-bridge-verbs.{ps1,sh}` | Verb-to-skill-path resolver + task-template loader |
| `dlc-bridge-retry.{ps1,sh}` | Exponential-backoff retry (2s/8s/32s) on 429/5xx/timeout |
| `dlc-bridge-status.{ps1,sh}` | Status-file lifecycle (`running` → `complete`/`error`/`cancelled`) |
| `state-update.{ps1,sh}` | Atomic state.md transitions (init/advance/skip/record_pr/escalate/finalize) |
| `slug-derive.{ps1,sh}` | Extract `<slug>` from `.kiro/specs/<slug>/<artifact>.md` |
| `mode-resolve.{ps1,sh}` | Read `.dlc.config.json` `aidlcDepth` → interactive/confident/autopilot |
| `debounce-check.{ps1,sh}` | 30s fire-suppression for fileEdited hooks (NFR-14) |
| `id-propagate.{ps1,sh}` | Jaccard match + idempotent HTML-comment injection of FR/NFR/WI IDs |

### Verb templates (`dist/templates/verb-tasks/`)

12 task-template files, one per supported verb: `reverse-engineer-kb`, `kb-gap-analysis`, `map-codebase`, `babysit-pr`, `hotfix`, `analyze-requirements`, `produce-tech-design`, `plan-implementation`, `discover`, `finalize-sdlc`, `review-pr`, `stabilize-pr`.

### Config (`dist/config/`)

`dlc.config.json.template` — empty-defaults template the installer optionally copies to `<workspace>/.dlc.config.json` for per-workspace tuning.

## When to load steering files

Kiro evaluates installed Powers' steering files dynamically based on conversation context. For DLC SuperCharge:

| User intent | Steering file to load |
|---|---|
| **First-time install** — workspace has no `.kiro/hooks/check-dlc-job.kiro.hook` yet | [`steering/dlc-supercharge-onboarding.md`](steering/dlc-supercharge-onboarding.md) — runs bootstrap + prereq checks + smoke tests on the user's behalf |
| **Normal operation** — any `/dlc:` keyword after install is complete | [`steering/dlc-augment.md`](steering/dlc-augment.md) — two-lane dispatcher (Kiro-native subagents vs headless bridge) + Flow Orchestration phase mapping |

If both apply, read `dlc-supercharge-onboarding.md` FIRST and only proceed to normal operation once bootstrap has exited 0 and the smoke tests pass.

## Installation

Two paths — pick whichever fits the user's environment:

### Path A — Kiro "Add Power from GitHub" (recommended)

1. In Kiro IDE: **Settings → Powers → Add a custom Kiro power → Import power from GitHub**.
2. Paste the repo URL: `https://github.com/ops-guru/kiro-bridge-poc`.
3. Kiro caches `POWER.md`, `mcp.json`, and `steering/` under `~/.kiro/powers/installed/dlc-supercharge/` and auto-registers in `~/.kiro/powers/installed.json`.
4. On first invocation of any `/dlc:` keyword in a workspace, Kiro loads [`steering/dlc-supercharge-onboarding.md`](steering/dlc-supercharge-onboarding.md) — the agent runs prereq checks, clones the repo into a scratch path, executes `bootstrap.{ps1,sh} --no-register-kiro-power` (Kiro already did the user-scoped registration), runs smoke tests, then routes to normal operation.

### Path B — clone + run bootstrap manually (CI / fleet deploys)

```powershell
# Windows
git clone https://github.com/ops-guru/kiro-bridge-poc
powershell -NoProfile -ExecutionPolicy Bypass -File kiro-bridge-poc/dlc-supercharge/bootstrap.ps1
```

```bash
# POSIX
git clone https://github.com/ops-guru/kiro-bridge-poc
bash kiro-bridge-poc/dlc-supercharge/bootstrap.sh
```

Bootstrap is idempotent — safe to re-run for upgrades. See [`steering/dlc-supercharge-onboarding.md`](steering/dlc-supercharge-onboarding.md) for the full step-by-step bootstrap does, prereqs (`claude`, `uv`, `gh`, `git`), and failure-mode triage.

## Quick start

After install (either path), verify by triggering the simplest hook from Kiro's Agent Hooks panel:

1. Fire `check-dlc-job` (read-only — lists bridge jobs, no API spend).
2. Expect: `NO_JOBS=no .dlc/_bridge-jobs/ directory` on a fresh workspace, terminal `HOOK_DONE`.
3. Then try `map-codebase` against a target subsystem path (e.g., `src/auth/`); wait for `.dlc/maps/<sanitized-target>.map.md` to appear (~3 min, ~$0.50 API spend).

If both produce expected output, the bridge + plugin + Kiro hook chain is healthy.

## Architecture

Full design in [`.dlc/designs/2026-05-19-dlc-supercharge.md`](../.dlc/designs/2026-05-19-dlc-supercharge.md). Highlights:

- **Bridge invocation pattern** (Phase 0 validated): `claude -p --append-system-prompt-file <SKILL.md> --permission-mode bypassPermissions --max-budget-usd 5 "<task>"`. Slash commands don't execute in `-p` mode; the workaround is loading the skill as a system prompt and passing the task as the user message.
- **Two-lane dispatcher pattern** documented in the bundled `steering/dlc-augment.md`. Teach the Kiro main agent which lane to use for which task type.
- **State coordination** through `.dlc/<slug>/state.md` (template produced in Epic 7 of the SuperCharge build).
- **Status-file lifecycle** at `.dlc/_bridge-jobs/<job-id>.status.json` for background-job visibility via `check-dlc-job`.
