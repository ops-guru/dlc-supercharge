#!/usr/bin/env bash
# Install DLC SuperCharge into a target Kiro workspace (POSIX parity for bootstrap.ps1).
#
# Usage:
#   bash bootstrap.sh [--into <path>] [--force] [--with-dlc-config] [--no-smoke-tests] [--quiet] [--help]
#
# Exit codes:
#   0   Success (or already-installed, idempotent re-run)
#   8   Smoke test failure on freshly-installed bundle
#   9   Prerequisite check failure
#  10   File copy conflict: pre-existing modified DLC file without --force

set -u

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTO=""
FROM_GIT=""
FORCE=0
WITH_DLC_CONFIG=0
NO_SMOKE_TESTS=0
NO_REGISTER_KIRO_POWER=0
QUIET=0
CLONE_DIR=""

usage() {
    cat <<'EOF'
Install DLC SuperCharge into a target Kiro workspace.

Usage: bootstrap.sh [options]

Options:
  --into <path>           Target workspace directory (default: current dir)
  --from-git <url>        Clone the Power from a git URL, install, then clean up
  --force                 Overwrite pre-existing DLC files
  --with-dlc-config       Write .dlc.config.json from template
  --no-smoke-tests        Skip Phase 6 smoke tests
  --quiet                 Suppress non-error output and playbook
  -h, --help              Show this help

Exit codes: 0 success, 8 smoke fail, 9 prereq fail, 10 file conflict
EOF
}

# Parse args
while [ "$#" -gt 0 ]; do
    case "$1" in
        --into)            INTO="$2"; shift 2;;
        --from-git)        FROM_GIT="$2"; shift 2;;
        --force)           FORCE=1; shift;;
        --with-dlc-config) WITH_DLC_CONFIG=1; shift;;
        --no-smoke-tests)  NO_SMOKE_TESTS=1; shift;;
        --no-register-kiro-power) NO_REGISTER_KIRO_POWER=1; shift;;
        --quiet)           QUIET=1; shift;;
        -h|--help)         usage; exit 0;;
        *) printf '[bootstrap] ERROR: unknown option: %s\n' "$1" >&2; usage; exit 9;;
    esac
done

[ -z "$INTO" ] && INTO="$(pwd)"

# If --from-git, clone the Power into a temp dir and reset BUNDLE_ROOT.
if [ -n "$FROM_GIT" ]; then
    if ! command -v git >/dev/null 2>&1; then
        printf '[bootstrap] ERROR: --from-git requires `git` on PATH\n' >&2
        exit 9
    fi
    CLONE_DIR=$(mktemp -d "/tmp/dlc-sc-clone-XXXXXX")
    printf '[bootstrap] Cloning %s into %s ...\n' "$FROM_GIT" "$CLONE_DIR"
    if ! git clone --depth 1 "$FROM_GIT" "$CLONE_DIR" 2>&1; then
        printf '[bootstrap] ERROR: git clone failed. Clone preserved at %s for debugging.\n' "$CLONE_DIR" >&2
        exit 9
    fi
    BUNDLE_ROOT="$CLONE_DIR"
    printf '[bootstrap] OK: Using cloned bundle at %s\n' "$BUNDLE_ROOT"
fi

# Cleanup clone on exit (success only — preserve on failure)
trap '[ -n "$CLONE_DIR" ] && [ "$?" -eq 0 ] && rm -rf "$CLONE_DIR" 2>/dev/null' EXIT

# Output helpers
log()  { [ "$QUIET" -eq 0 ] && printf '[bootstrap] %s\n' "$*" || true; }
warn() { printf '[bootstrap] WARN: %s\n' "$*" >&2; }
err()  { printf '[bootstrap] ERROR: %s\n' "$*" >&2; }
ok()   { [ "$QUIET" -eq 0 ] && printf '[bootstrap] OK: %s\n' "$*" || true; }

# === Phase 1: Resolve target workspace ===
phase1_resolve() {
    log "Phase 1: Resolve target workspace"
    if [ ! -d "$INTO" ]; then
        err "Target directory does not exist: $INTO"
        exit 9
    fi
    TARGET="$(cd "$INTO" && pwd)"
    ok "Target: $TARGET"

    if [ ! -d "$TARGET/.git" ]; then
        if [ "$FORCE" -eq 1 ]; then
            warn "No .git/ at target; proceeding because --force was passed"
        else
            warn "No .git/ at target. DLC SuperCharge is typically installed into a git repo; --force to install anyway."
        fi
    fi
}

# === Phase 2: Prerequisite checks (FR-29) ===
PREREQ_FAILS=0

prereq_check() {
    local name="$1" severity="$2" remediation="$3"
    # Caller passes status via global $PREREQ_RESULT
    if [ "$PREREQ_RESULT" = "pass" ]; then
        ok "  [PASS] $name${PREREQ_DETAIL:+ ($PREREQ_DETAIL)}"
    elif [ "$severity" = "warn" ]; then
        warn "  [WARN] $name - $remediation"
    else
        err "  [FAIL] $name - $remediation"
        PREREQ_FAILS=$((PREREQ_FAILS+1))
    fi
}

phase2_prereqs() {
    log "Phase 2: Prerequisite checks"

    # claude CLI on PATH
    PREREQ_RESULT="fail"; PREREQ_DETAIL=""
    if command -v claude >/dev/null 2>&1; then
        PREREQ_RESULT="pass"; PREREQ_DETAIL="present"
    fi
    prereq_check 'claude CLI on PATH' 'fail' 'Install Claude Code from https://docs.claude.com/claude-code'

    # claude supports --append-system-prompt
    PREREQ_RESULT="fail"; PREREQ_DETAIL=""
    if command -v claude >/dev/null 2>&1; then
        if claude --help 2>&1 | grep -q 'append-system-prompt'; then
            PREREQ_RESULT="pass"; PREREQ_DETAIL="present"
        fi
    fi
    prereq_check 'claude supports --append-system-prompt' 'fail' 'Claude Code version too old; run claude --version and upgrade if <2.0'

    # /dlc: plugin cache present
    PREREQ_RESULT="fail"; PREREQ_DETAIL=""
    CACHE_ROOT="$HOME/.claude/plugins/cache/dlc-automation/dlc"
    if [ -d "$CACHE_ROOT" ]; then
        # Count subdirs containing 'skills'
        count=0
        for v in "$CACHE_ROOT"/*/; do
            [ -d "${v}skills" ] && count=$((count+1))
        done
        if [ "$count" -gt 0 ]; then
            PREREQ_RESULT="pass"; PREREQ_DETAIL="found $count version(s)"
        fi
    fi
    prereq_check '/dlc: plugin cache present' 'fail' 'Install the /dlc: plugin from the Claude Code plugin registry'

    # PowerShell execution policy - POSIX skips this check (informational pass)
    PREREQ_RESULT="pass"; PREREQ_DETAIL="N/A on POSIX"
    prereq_check 'PowerShell execution policy' 'fail' '(skipped on POSIX)'

    # gh CLI on PATH (warn only)
    PREREQ_RESULT="fail"; PREREQ_DETAIL=""
    if command -v gh >/dev/null 2>&1; then
        PREREQ_RESULT="pass"; PREREQ_DETAIL="present"
    fi
    prereq_check 'gh CLI on PATH' 'warn' 'Install GitHub CLI from https://cli.github.com (needed for babysit-pr, hotfix-revert verbs)'

    # Anthropic auth (warn only)
    PREREQ_RESULT="fail"; PREREQ_DETAIL=""
    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        PREREQ_RESULT="pass"; PREREQ_DETAIL="ANTHROPIC_API_KEY set"
    elif [ -f "$HOME/.claude/credentials" ]; then
        PREREQ_RESULT="pass"; PREREQ_DETAIL="~/.claude/credentials present"
    fi
    prereq_check 'Anthropic auth configured' 'warn' 'Set ANTHROPIC_API_KEY or run claude login'

    # Disk space >= 100 MB
    PREREQ_RESULT="fail"; PREREQ_DETAIL=""
    if command -v df >/dev/null 2>&1; then
        # df -k returns 1KB blocks; need >= 102400
        avail_kb=$(df -k "$TARGET" 2>/dev/null | awk 'NR==2 {print $4}')
        if [ -n "$avail_kb" ] && [ "$avail_kb" -ge 102400 ]; then
            free_mb=$((avail_kb / 1024))
            PREREQ_RESULT="pass"; PREREQ_DETAIL="$free_mb MB free"
        fi
    fi
    prereq_check 'Free disk space >= 100 MB' 'fail' 'Free up disk space at target'

    if [ "$PREREQ_FAILS" -gt 0 ]; then
        err "Prereq checks failed ($PREREQ_FAILS). Resolve the FAIL items above and re-run."
        exit 9
    fi
    ok "Prereq checks passed"
}

# === Phase 3: Idempotency check ===
phase3_idempotent() {
    log "Phase 3: Idempotency check"
    local power_md="$TARGET/.kiro/powers/dlc-supercharge/POWER.md"
    if [ ! -f "$power_md" ]; then
        ok "Fresh install"
        return
    fi
    if [ "$FORCE" -eq 1 ]; then
        warn "DLC SuperCharge already installed at target; --force passed, overwriting"
        return
    fi
    ok "Already installed at $power_md. Use --force to overwrite. Exiting."
    exit 0
}

# === Phase 4: File copy (FR-27, FR-28) ===
file_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" 2>/dev/null | awk '{print $1}'
    else
        shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
    fi
}

# Side effect: increments STAT_<action>; returns nothing meaningful
copy_if_different() {
    local src="$1" dst="$2"
    local parent
    parent=$(dirname "$dst")
    [ ! -d "$parent" ] && mkdir -p "$parent"
    if [ ! -f "$dst" ]; then
        cp "$src" "$dst"
        STAT_ADDED=$((STAT_ADDED+1)); return
    fi
    local s_hash d_hash
    s_hash=$(file_sha256 "$src")
    d_hash=$(file_sha256 "$dst")
    if [ "$s_hash" = "$d_hash" ]; then
        STAT_IDENTICAL=$((STAT_IDENTICAL+1)); return
    fi
    if [ "$FORCE" -eq 1 ]; then
        cp -f "$src" "$dst"
        STAT_OVERWRITTEN=$((STAT_OVERWRITTEN+1)); return
    fi
    STAT_SKIPPED=$((STAT_SKIPPED+1))
    [ "$QUIET" -eq 0 ] && warn "differs (skipped): $dst. Use --force to overwrite."
}

phase4_copy() {
    log "Phase 4: Copy bundle into target"
    STAT_ADDED=0; STAT_IDENTICAL=0; STAT_OVERWRITTEN=0; STAT_SKIPPED=0

    copy_if_different "$BUNDLE_ROOT/POWER.md" "$TARGET/.kiro/powers/dlc-supercharge/POWER.md"
    copy_if_different "$BUNDLE_ROOT/mcp.json" "$TARGET/.kiro/powers/dlc-supercharge/mcp.json"
    # Steering goes to BOTH locations (D-504)
    copy_if_different "$BUNDLE_ROOT/steering/dlc-augment.md" "$TARGET/.kiro/powers/dlc-supercharge/steering/dlc-augment.md"
    copy_if_different "$BUNDLE_ROOT/steering/dlc-augment.md" "$TARGET/.kiro/steering/dlc-augment.md"

    for f in "$BUNDLE_ROOT/dist/hooks/"*.kiro.hook; do
        [ -e "$f" ] && copy_if_different "$f" "$TARGET/.kiro/hooks/$(basename "$f")"
    done
    for f in "$BUNDLE_ROOT/dist/agents/"*.md; do
        [ -e "$f" ] && copy_if_different "$f" "$TARGET/.kiro/agents/$(basename "$f")"
    done
    for f in "$BUNDLE_ROOT/dist/scripts/"*; do
        [ -e "$f" ] && copy_if_different "$f" "$TARGET/.kiro/scripts/$(basename "$f")"
    done
    for f in "$BUNDLE_ROOT/dist/templates/verb-tasks/"*.txt; do
        [ -e "$f" ] && copy_if_different "$f" "$TARGET/.kiro/powers/dlc-supercharge/templates/verb-tasks/$(basename "$f")"
    done
    # state.md.template -> .kiro/powers/dlc-supercharge/templates/state.md.template
    if [ -f "$BUNDLE_ROOT/dist/templates/state.md.template" ]; then
        copy_if_different "$BUNDLE_ROOT/dist/templates/state.md.template" "$TARGET/.kiro/powers/dlc-supercharge/templates/state.md.template"
    fi

    local total=$((STAT_ADDED + STAT_IDENTICAL + STAT_OVERWRITTEN + STAT_SKIPPED))
    ok "Copied $total file(s): $STAT_ADDED added, $STAT_IDENTICAL unchanged, $STAT_OVERWRITTEN overwritten, $STAT_SKIPPED skipped"

    if [ "$STAT_SKIPPED" -gt 0 ] && [ "$FORCE" -eq 0 ]; then
        warn "$STAT_SKIPPED file(s) differ from bundle but were preserved. Use --force to overwrite them."
    fi
}

# === Phase 5: Optional .dlc.config.json (FR-19) ===
phase5_config() {
    log "Phase 5: Optional .dlc.config.json"
    local tgt_config="$TARGET/.dlc.config.json"
    if [ -f "$tgt_config" ]; then
        ok "Pre-existing .dlc.config.json detected; preserving (non-destructive per FR-28)"
        return
    fi
    if [ "$WITH_DLC_CONFIG" -eq 0 ]; then
        log "  --with-dlc-config not passed; skipping (re-run with --with-dlc-config to write the template)"
        return
    fi
    cp "$BUNDLE_ROOT/dist/config/dlc.config.json.template" "$tgt_config"
    ok "Wrote $tgt_config from template"
}

# === Phase 6: Embedded smoke tests (FR-31) ===
phase6_smoke() {
    if [ "$NO_SMOKE_TESTS" -eq 1 ]; then
        log "Phase 6: skipped (--no-smoke-tests)"
        return
    fi
    log "Phase 6: Smoke tests"
    local failures=0

    # Test 1: hooks parse + have required fields (inline schema check)
    local hook_pass=0 hook_fail=0
    local valid_when='fileEdited|fileCreated|fileDeleted|userTriggered|promptSubmit|agentStop|preToolUse|postToolUse|preTaskExecution|postTaskExecution|sessionStart'
    local valid_then='askAgent|runCommand'
    for hf in "$TARGET/.kiro/hooks/"*.kiro.hook; do
        [ ! -f "$hf" ] && continue
        local name; name=$(basename "$hf")
        local content; content=$(tr -d '\n\r' < "$hf")
        local ok=1
        for field in '"version"' '"enabled"' '"name"' '"description"' '"when"' '"then"'; do
            echo "$content" | grep -qF "$field" || { err "  hook $name: missing field $field"; ok=0; break; }
        done
        # Type checks (very loose - just enum membership)
        if [ "$ok" -eq 1 ]; then
            local when_type; when_type=$(echo "$content" | grep -oE '"when":[[:space:]]*\{[^}]*"type":[[:space:]]*"[^"]+"' | grep -oE '"type":[[:space:]]*"[^"]+"' | tail -n1 | sed -E 's/.*"([^"]+)"$/\1/')
            if ! echo "$when_type" | grep -qE "^(${valid_when})$"; then
                err "  hook $name: when.type '$when_type' invalid"; ok=0
            fi
        fi
        if [ "$ok" -eq 1 ]; then
            local then_type; then_type=$(echo "$content" | grep -oE '"then":[[:space:]]*\{[^}]*"type":[[:space:]]*"[^"]+"' | grep -oE '"type":[[:space:]]*"[^"]+"' | tail -n1 | sed -E 's/.*"([^"]+)"$/\1/')
            if ! echo "$then_type" | grep -qE "^(${valid_then})$"; then
                err "  hook $name: then.type '$then_type' invalid"; ok=0
            fi
        fi
        if [ "$ok" -eq 1 ]; then hook_pass=$((hook_pass+1)); else hook_fail=$((hook_fail+1)); fi
    done
    if [ "$hook_fail" -eq 0 ]; then
        ok "  Schema validation: $hook_pass/$hook_pass hook(s) valid"
    else
        err "  Schema validation: $hook_pass pass, $hook_fail fail"
        failures=$((failures+1))
    fi

    # Test 2: bridge dry-run
    local bridge_path="$TARGET/.kiro/scripts/dlc-bridge.sh"
    if [ -f "$bridge_path" ]; then
        local out
        out=$(cd "$TARGET" && bash "$bridge_path" map-codebase --target . --dry-run 2>&1)
        local exit_code=$?
        if [ "$exit_code" -eq 0 ] && echo "$out" | grep -qE '"status":[[:space:]]*"dry-run"'; then
            ok "  Bridge dry-run: exit 0, JSON returned"
        else
            err "  Bridge dry-run: exit=$exit_code, JSON detected=$(echo "$out" | grep -cE '"status":[[:space:]]*"dry-run"')"
            failures=$((failures+1))
        fi
    else
        err "  Bridge dry-run: bridge script not at $bridge_path"
        failures=$((failures+1))
    fi

    # Test 3: POWER.md frontmatter has 5 keys
    local power_md="$TARGET/.kiro/powers/dlc-supercharge/POWER.md"
    if [ -f "$power_md" ]; then
        local key_count
        key_count=$(awk '/^---$/{c++; next} c==1 && /^[a-zA-Z]+:/{print $1}' "$power_md" | wc -l)
        if [ "$key_count" -eq 5 ]; then
            ok "  POWER.md frontmatter: 5 keys"
        else
            err "  POWER.md frontmatter: expected 5 keys, got $key_count"
            failures=$((failures+1))
        fi
    else
        err "  POWER.md not found at $power_md"
        failures=$((failures+1))
    fi

    if [ "$failures" -gt 0 ]; then
        err "Smoke tests failed: $failures test(s)"
        exit 8
    fi
    ok "Smoke tests: 3/3 PASS"
}

# === Phase 7: Playbook print (FR-30) ===
phase7_playbook() {
    [ "$QUIET" -eq 1 ] && return
    cat <<'EOF'

+==================================================================+
|  DLC SuperCharge installed successfully.                         |
|                                                                  |
|  T+0   ->  T+5    Smoke check passed. Bridge ready.              |
|  T+5   ->  T+25   Run reverse-engineer-kb on a legacy repo:      |
|                     Click 'reverse-engineer-kb' in Hooks panel   |
|                     Provide target path                          |
|                     Background; check progress via check-dlc-job |
|  T+25  ->  T+40   In parallel, map a known subsystem:            |
|                     Click 'map-codebase'                         |
|                     ~3 min foreground; check .dlc/maps/          |
|  T+40  ->  T+50   Inspect .dlc/kb/ for the legacy-repo KB        |
|  T+50  ->  T+70   Drop requirements.xlsx; trigger kb-gap-analysis|
|  T+70  ->  T+90   Open a Kiro Spec; save design.md (auto-review) |
|  T+90  ->  T+110  Open a PR; trigger babysit-pr                  |
|  T+110 ->  T+120  Demonstrate hotfix-revert if time permits      |
|                                                                  |
|  Monitor any background job: 'check-dlc-job' hook                |
|  Full docs: .kiro/powers/dlc-supercharge/POWER.md                |
+==================================================================+
EOF
}

phase6_5_register_kiro_power() {
    if [ "$NO_REGISTER_KIRO_POWER" -eq 1 ]; then
        log "Phase 6.5: Kiro Power registration (skipped via --no-register-kiro-power)"
        return
    fi
    log "Phase 6.5: Register dlc-supercharge with Kiro user-scoped Powers registry"
    local register_script="$TARGET/.kiro/scripts/register-kiro-power.sh"
    if [ ! -f "$register_script" ]; then
        echo "  WARN: register-kiro-power.sh not in target; skipping Power registration" >&2
        return
    fi
    if bash "$register_script" --bundle-path "$BUNDLE_ROOT" 2>&1 | sed 's/^/  /'; then
        ok "Power registered. Reload Kiro window (Ctrl+Shift+P -> 'Developer: Reload Window') to see it in the Powers panel."
    else
        echo "  WARN: Power registration failed; workspace install still functional, Powers panel will not show the entry." >&2
    fi
}

# === Main ===
phase1_resolve
phase2_prereqs
phase3_idempotent
phase4_copy
phase5_config
phase6_smoke
phase6_5_register_kiro_power
phase7_playbook

exit 0
