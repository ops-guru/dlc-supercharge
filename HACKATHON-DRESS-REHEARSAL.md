# DLC SuperCharge — Hackathon Dress Rehearsal Checklist

Print this. Check boxes as you go. Target: complete T+0..T+120 in under 130 minutes. Sign-off at bottom.

**Date:** _______________  **Operator:** _______________

---

## Prerequisites (T-30 min, before the rehearsal starts)

- [ ] `claude --version` exits 0 and reports >= 2.0
- [ ] `claude --help` mentions `--append-system-prompt` (or `-file` variant)
- [ ] `/dlc:` plugin cache present: `ls ~/.claude/plugins/cache/dlc-automation/dlc/*/skills/` returns paths
- [ ] `gh --version` exits 0 (needed for `babysit-pr`, `hotfix-revert`)
- [ ] Anthropic budget set: ≥ $30 available (typical full rehearsal: $10-15)
- [ ] Fresh sandbox repo cloned to a clean workspace (NOT the DLC SuperCharge dev workspace)
- [ ] Kiro IDE installed and running; can open the workspace
- [ ] DLC SuperCharge Power bundle accessible (local clone OR git URL ready)

---

## T+0 to T+5 — Install

- [ ] `cd <sandbox-workspace>`
- [ ] Run installer: `powershell -NoProfile -ExecutionPolicy Bypass -File <power-path>\bootstrap.ps1 -Into .` (or bash equivalent)
- [ ] Confirm Phase 1 (resolve target) succeeds
- [ ] Confirm Phase 2 (prereqs) shows all PASS or only WARN entries
- [ ] Confirm Phase 4 (file copy) reports ~28-39 files copied
- [ ] Confirm Phase 6 (smoke tests) shows: **3/3 PASS** (schema validation, bridge dry-run, POWER.md frontmatter)
- [ ] Phase 7 playbook prints in the terminal
- [ ] Total elapsed: ____ s (target: < 30 s)

---

## T+5 to T+25 — Reverse-engineer-kb (background)

- [ ] Open Kiro Agent Hooks panel
- [ ] Confirm all 14 hooks visible
- [ ] Click `reverse-engineer-kb`
- [ ] Provide `target` = path to a small-to-medium legacy codebase (e.g., 50-200 files)
- [ ] Confirm Kiro chat shows: "KB build started — job <jobId>"
- [ ] (Optional) Tail log: `Get-Content .dlc\_bridge-logs\<jobId>.log -Wait`
- [ ] Job ID recorded: _______________

---

## T+25 to T+40 — In parallel: map-codebase (foreground)

- [ ] In Kiro chat, click `map-codebase` (or fire from hooks panel)
- [ ] Provide `target` = a known subsystem path (e.g., `src/auth/`)
- [ ] Wait for completion (~3 min target)
- [ ] Confirm artifact at `.dlc/maps/<sanitized-target>.map.md` exists
- [ ] Open the file; verify it has Components / Dependencies / Conventions / Tests sections
- [ ] Total elapsed for map-codebase: ____ min (target: < 5)

---

## T+40 to T+50 — KB inspection

- [ ] Fire `check-dlc-job` hook → confirm `reverse-engineer-kb` job status
- [ ] Wait for status to flip to `complete`
- [ ] Confirm `.dlc/kb/index.json` exists and parses
- [ ] Confirm `.dlc/kb/architecture.md` exists with intro + module list
- [ ] Confirm `.dlc/kb/modules/MOD-*.md` files exist (typically 5-20)
- [ ] Spot-check one MOD file: has Purpose / Interface / Dependencies / Tests sections

---

## T+50 to T+70 — kb-gap-analysis

- [ ] Drop a sample `requirements.xlsx` or `requirements.csv` at workspace root
- [ ] Click `kb-gap-analysis` hook
- [ ] Provide `source` = path to that file; `kb` = `.dlc/kb`
- [ ] Wait for completion
- [ ] Confirm output: `<source>_with_gap.xlsx` and/or `.dlc/<slug>/gap-analysis/aggregated.json`
- [ ] Confirm rows classified as COVERED / PARTIAL / NOT_COVERED

---

## T+70 to T+90 — Save Kiro Spec design.md (D-minus auto-fire)

- [ ] In Kiro, create or open a Spec: `.kiro/specs/<slug>/design.md`
- [ ] Edit and SAVE the file (must save inside Kiro for fileEdited to fire)
- [ ] Confirm `on-design-saved` hook fires (visible in Kiro chat)
- [ ] Confirm `dlc-reviewer-security` subagent dispatches inline (Phase 1 step preserved)
- [ ] Confirm bridge invokes `produce-tech-design` (Step 3b)
- [ ] Confirm 4-dim review fires (Step 3d): security/ux/a11y/perf reviewers
- [ ] Confirm `.dlc/<slug>/designs/tech-design.md` produced with WI-x IDs
- [ ] Confirm `<!-- WI-x -->` comments inserted into Kiro `design.md` (ID propagation, Step 3e)
- [ ] Confirm `.dlc/<slug>/state.md` advanced to Phase 3 (read the file; `**Current phase:** 3`)

---

## T+90 to T+110 — Open a PR, fire on-pr-opened

- [ ] In the sandbox repo, make a small commit and push
- [ ] Open a PR via `gh pr create` or the GitHub UI
- [ ] Note PR number: _______________
- [ ] Click `on-pr-opened` hook
- [ ] Provide PR number when prompted
- [ ] Confirm Kiro chat shows: "PR #<N> now under DLC babysit (job <jobId>)"
- [ ] (Optional) PR description was updated via `gh pr edit` — check PR body
- [ ] State.md PR number recorded: read `.dlc/<slug>/state.md`, verify `**PR number:** #<N>`

---

## T+110 to T+120 — Demonstrate hotfix-revert (optional, if time)

- [ ] Click `hotfix-revert` hook
- [ ] Provide a PR number (real or test)
- [ ] Confirm Step 0 "confirm revert vs roll-forward" prompt appears
- [ ] Confirm Step 1 dispatches bridge with `--mode revert`
- [ ] Confirm flow either produces a revert PR OR surfaces error verbatim (graceful failure)

---

## Sign-off

- [ ] All checks above are green OR documented exception
- [ ] Total elapsed: ____ min (target: < 130)
- [ ] Demo confidence (1-5, where 5 = ready for client): ___
- [ ] Operator: _______________  Date: _______________

### Notes / exceptions

(Use this space for anything that didn't go as expected, errors observed, or improvements for next run.)

---

## Post-rehearsal cleanup

After the rehearsal:
- [ ] Delete sandbox workspace (or git stash + reset for next run)
- [ ] Note jobIds for any background jobs still active; either let them finish or kill them
- [ ] If smoke install state is dirty, `bootstrap.ps1 -Force` to refresh
- [ ] Update this checklist with any new steps needed for the next rehearsal
