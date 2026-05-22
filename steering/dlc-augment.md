---
inclusion: always
description: "DLC SuperCharge - augments Kiro's native AIDLC workflow with /dlc: plugin capabilities (legacy-code KB, requirements gap analysis, multi-dim review, CI babysit)"
---

# DLC SuperCharge — Augmenting Kiro's AIDLC

You (Kiro main agent) have access to two parallel execution lanes for SDLC work. Use them together.

## Lane 1 — Kiro-native (subagents)

Custom subagents in `.kiro/agents/`:

| Subagent | Use when |
|---|---|
| `dlc-explore-fast` | Need a fast, breadth-first scan of unfamiliar code (Haiku-tier; cheap; parallel-safe) |
| `dlc-reviewer-security` | Reviewing a design.md, requirements.md, or finished implementation for security concerns (auth, data handling, PII, IAM, secrets) |
| `dlc-reviewer-ux` | Reviewing a design for UX coherence; should be invoked when design touches user-facing UI |
| `dlc-reviewer-a11y` | WCAG-flavored quick scan; invoke for any user-facing UI change |
| `dlc-reviewer-perf` | Performance review across 5 domains (Core Web Vitals, backend latency, algorithmic complexity, frontend bundle, memory/resource lifecycle) |
| `dlc-deep-analyst` | Cross-cutting synthesis: comparing architectures, weighing trade-offs, resolving conflicting requirements (Opus-tier) |
| `dlc-test-writer` | Generate unit tests matching the project's existing framework + naming + assertion conventions; iterate until green |
| `dlc-doc-writer` | Update README, generate CHANGELOG entries from git history, sync docs to code while preserving the project's voice |

Invoke a subagent the standard Kiro way (via Chat or by triggering a hook).

## Lane 2 — DLC plugin bridge (hooks)

Hooks in `.kiro/hooks/` shell out to Claude Code headless and run the actual `/dlc:` plugin skills:

| Hook | Verb | When to use |
|---|---|---|
| `reverse-engineer-kb` | `/dlc:reverse-engineer-kb` | Onboarding a legacy codebase. Produces `.dlc/kb/` (index + per-module markdown + architecture synthesis) |
| `kb-gap-analysis` | `/dlc:kb-gap-analysis` | When the user has a requirements doc (xlsx/csv/md-table) and wants to classify rows against the KB as COVERED/PARTIAL/NOT_COVERED |
| `map-codebase` | `/dlc:map` | Fast architectural map of a subsystem (alternative to `dlc-explore-fast` when the work is bigger than a single chat round) |
| `babysit-pr` | `/dlc:babysit` | After a PR is opened. Auto-loop until merge-ready with bounded retry budgets |
| `hotfix-revert` | `/dlc:hotfix` | Emergency PR revert with safety confirmation; dispatches the bridge in `--mode revert` |
| `check-dlc-job` | (local) | List active and recent bridge jobs from `.dlc/_bridge-jobs/` as a markdown table |
| `on-design-saved` | `/dlc:design` + 4 reviewers | Auto-fires on Kiro `design.md` saves; preserved inline security-review + tech-design enrichment + 4-dim review + WI-x ID propagation |
| `on-requirements-saved` | `/dlc:analyze-requirements` + reviewers | Auto-fires on Kiro `requirements.md` saves; Phase 1->2c chain |
| `on-tasks-saved` | `/dlc:plan` | Auto-fires on Kiro `tasks.md` saves; Phase 3 planning chain |
| `on-pr-opened` | `/dlc:babysit` (background) | User-triggered after opening a PR; polished PR description + babysit launch |
| `on-pr-merged` | `/dlc:finalize-sdlc` | User-triggered after a PR is merged; finalize + cleanup state.md |
| `resume-dlc-sdlc` | (dispatcher) | User-triggered to pick up an interrupted SDLC at the last recorded phase |
| `on-task-complete` | (subagent: dlc-test-writer) | postTaskExecution coverage gate per task |
| `on-task-polish` | (subagent: dlc-doc-writer) | postTaskExecution docstring/comment alignment |

Hooks are listed in the Agent Hooks panel; the user can fire them manually or they fire on the documented event.

## Lane selection — when to use which

| Situation | Lane | Why |
|---|---|---|
| User asks for a security/UX/a11y review of a small artifact (design.md, single file) | Lane 1 — subagent | Fast, in-IDE, no subprocess |
| User asks to onboard a legacy codebase | Lane 2 — `reverse-engineer-kb` hook | DLC's 3-pass scan is hours of orchestration code; reproducing it Kiro-natively is wasteful |
| User asks to classify requirements vs a KB | Lane 2 — `kb-gap-analysis` hook | Same — DLC has the orchestration |
| User asks to map a small subsystem | Lane 1 — `dlc-explore-fast` subagent | One-shot scan, no need for DLC's full multi-pass |
| User asks to map an unfamiliar large codebase | Lane 2 — `map-codebase` hook | DLC dispatches 4 parallel explore-fasts; faster and more thorough |
| Discovery brief (early-stage ideation) | Inline (this conversation) | You have the discovery skill knowledge from this steering; produce a structured brief directly |
| Cross-cutting analysis or synthesis | Lane 1 — `dlc-deep-analyst` subagent | Needs Opus reasoning, not a subprocess |
| Babysit a PR through CI | Lane 2 — `babysit-pr` hook | DLC has the bounded-retry semantics |
| Hotfix prod | Lane 2 — `hotfix` hook | DLC has the workflow |

When in doubt, prefer Lane 1 (Kiro-native) for speed; escalate to Lane 2 for capabilities Kiro doesn't have built-in.

## Flow Orchestration

This steering teaches you (Kiro main agent) the dispatcher pattern that DLC SuperCharge mirrors inside Kiro Spec mode. When a user works on a Kiro Spec, DLC SuperCharge orchestrates DLC's 10-phase SDLC in parallel via `.dlc/<slug>/state.md`. Each Spec phase save fires a hook that advances state.md and runs the corresponding DLC phase chain.

### The phase model

| Kiro action | DLC phase | Hook | Status |
|---|---|---|---|
| Edit `requirements.md` | 1 → 2a → 2b → 2c | `on-requirements-saved` | live |
| Edit `design.md` | 2c → 3 | `on-design-saved` | live |
| Edit `tasks.md` | 3 (planning) | `on-tasks-saved` | live |
| Open PR | 4 → 5 | `on-pr-opened` | live |
| Merge PR | 7 → 8 | `on-pr-merged` | live |
| Resume any phase | (varies) | `resume-dlc-sdlc` | live |
| Task complete | per-task coverage | `on-task-complete` | live |
| Task complete | per-task polish | `on-task-polish` | live |

All phase hooks fire on the documented Kiro events. The on-design-saved chain also preserves the simpler Phase 1 inline security-review behavior as Step 3a (backward compatible).

### When invoking subagents within hooks

Hooks use `askAgent` action type, which passes a prompt to YOU (Kiro main agent). When a hook prompt instructs you to "dispatch `dlc-reviewer-security` in parallel with `dlc-reviewer-ux`", use Kiro's parallel-subagent mechanism (Task tool) to spawn them concurrently. Each subagent writes its own output file under `.dlc/<slug>/analysis_output/` — collect the file paths and surface a summary back to the user, do NOT inline the subagent reports.

### When shelling out to the bridge

Hook prompts that say "Use Bash to run `.kiro/scripts/dlc-bridge.ps1 ...`" are invoking Lane 2. The bridge spawns Claude Code headless via `claude -p --append-system-prompt-file <SKILL.md>`. For synchronous verbs (e.g., `map-codebase`, `hotfix`), wait for the bridge to return and surface the JSON output. For long-running verbs (`reverse-engineer-kb`, `babysit-pr`), the bridge defaults to background mode and returns a `jobId` + `statusFile` immediately — do NOT block on background jobs. Tell the user to fire `check-dlc-job` to monitor.

The bridge has a documented exit-code contract (0/2/3/4/5/6/7). Don't retry on exit 4 (bad input — user mistake) or exit 5 (retries already exhausted). Surface the exit code verbatim.

### State.md mechanics

`.dlc/<slug>/state.md` is the SSOT for which DLC phase the project is in. It mirrors what `/dlc:run` produces, so terminal-side `/dlc:next` resumes from the same record. Read it on every phase-hook invocation. Write it atomically (temp + rename). Append Decisions Log entries for every autopilot decision per `qa-protocol.md` template.

State.md template + atomic-write/ID-propagate/debounce helpers are produced in Epic 7. Until then, the pattern is documented here so you understand the protocol even before the helpers ship.

## AIDLC stage augmentation

Map DLC's value-adds onto Kiro's native Spec stages:

### Pre-Spec: Discovery (NEW)

Kiro's Spec mode jumps straight to requirements. For fuzzy ideas, run a discovery pass first.

When the user describes a vague product idea, write a discovery brief to `.dlc/discovery/<date>-<slug>.discovery.md` containing:

1. **Problem statement** (1-3 sentences)
2. **JTBD statements** — "When [situation], I want [motivation], so I can [outcome]" (3-7 statements)
3. **Lean Canvas** — Problem / Customer Segments / Unique Value Prop / Solution / Channels / Revenue / Costs / Key Metrics / Unfair Advantage
4. **MoSCoW backlog** — FR-x and NFR-x entries with priority + acceptance hint
5. **RAID** — Risks, Assumptions, Issues, Decisions
6. **Scope clusters** — proposed PRD groupings for the actual Spec phase

If the user says "discover", treat this as the trigger.

### Spec: Requirements (Kiro native, enhanced)

When Kiro Spec generates `requirements.md`, also:
- Convert MoSCoW priorities from any preceding discovery brief into the EARS notation
- Cross-reference any `.dlc/kb/` modules that already cover requirements (mark them COVERED in the spec)
- If a gap-analysis xlsx is present, ensure NOT_COVERED rows are all reflected

### Spec: Design (Kiro native, enhanced)

When Kiro Spec generates `design.md`:
- **The `on-design-saved` hook fires automatically** and invokes `dlc-reviewer-security` to produce `.dlc/analysis_output/security-review.md`
- For user-facing changes, also offer to invoke `dlc-reviewer-ux` and `dlc-reviewer-a11y`

### Spec: Tasks → Implementation (Kiro native)

No DLC augmentation needed here — Kiro's parallel-task execution is strong. Subagents in `.kiro/agents/` are available if the main agent wants to dispatch breadth-first work.

### Post-PR: Babysit (NEW)

When Kiro's autonomous GitHub agent opens a PR, surface a one-click option:
> "Want me to babysit PR #N until merge-ready?"

If yes, fire the `babysit-pr` hook.

### Hotfix (NEW)

For any "rollback PR #N" or "hotfix prod" request, fire the `hotfix` hook.

## Vocabulary translation (AIDLC ↔ DLC)

When talking to clients, use AIDLC vocabulary (they came for AIDLC). Internally, the mapping is:

| AIDLC term | DLC equivalent |
|---|---|
| Inception | Phase 1 Requirements + Phase 2c Design |
| Construction | Phase 3 Implementation |
| Operations | Phase 7-8 Finalize (DLC stops here; AIDLC defers Ops to a future phase) |
| Bolt | Epic (DLC's planning unit) |
| Unit of Work | Epic (same thing) |
| Mob Elaboration | DLC's Phase 1+2c with Q&A protocol |
| Mob Construction | DLC's Phase 3 with code review loop |

## Artifact roots

- **Kiro Spec artifacts**: `.kiro/specs/<feature>/{requirements,design,tasks}.md`
- **DLC artifacts**: `.dlc/{discovery,kb,plans,designs,analysis_output}/`
- **AIDLC artifacts** (if `awslabs/aidlc-workflows` is also installed): `aidlc-docs/{aidlc-state,audit,requirements,execution-plan}.md`

The three coexist. Kiro Spec is the user-visible source of truth for the current feature; `.dlc/` holds the augmented artifacts (KB, gap analysis, review reports, discovery briefs); `aidlc-docs/` is the cross-agent methodology trail if used.

## Bridge invocation

Hooks in Lane 2 call `.kiro/scripts/dlc-bridge.ps1` (or `dlc-bridge.sh` on POSIX). The bridge wraps Claude Code headless mode. The bridge script must be on the PATH or invoked with a full path from the hook.

If a hook fails because the bridge is missing or Claude Code isn't installed, surface a clear error: "DLC SuperCharge bridge missing. See `.kiro/DLC-SUPERCHARGE-README.md` for setup."

## Demos and clients

When demoing to a client, narrate the lane switches explicitly. Clients appreciate seeing the tool boundaries: "this part is Kiro-native, this part is my DLC plugin running headless." Don't hide the augmentation — it's part of the story.
