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
NO_AUTO_INSTALL_UV=0
NO_AUTO_INSTALL_PLUGIN=0
QUIET=0
CLONE_DIR=""

usage() {
    cat <<'EOF'
Install DLC SuperCharge into a target Kiro workspace.

Usage: bootstrap.sh [options]

Options:
  --into <path>             Target workspace directory (default: current dir)
  --from-git <url>          Clone the Power from a git URL, install, then clean up
  --force                   Overwrite pre-existing DLC files
  --with-dlc-config         Write .dlc.config.json from template
  --no-smoke-tests          Skip Phase 6 smoke tests
  --no-register-kiro-power  Skip Phase 6.5 Kiro Powers registration
  --no-auto-install-uv      Skip Phase 1.5 auto-install of uv (Astral Python launcher).
                            If uv is missing, exit 9 with manual-install URL.
                            Use in corporate envs that prohibit curl|sh installers (NFR-8).
  --no-auto-install-plugin  Skip Phase 2.5 auto-install of /dlc: Claude Code plugin.
                            If plugin cache is missing, exit 9 with manual install commands.
  --quiet                   Suppress non-error output and playbook
  -h, --help                Show this help

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
        --no-auto-install-uv) NO_AUTO_INSTALL_UV=1; shift;;
        --no-auto-install-plugin) NO_AUTO_INSTALL_PLUGIN=1; shift;;
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

# === Phase 1.5: uv detection + auto-install (FR-20, NFR-8) ===
phase1_5_resolve_uv() {
    log "Phase 1.5: Detect uv (Astral Python launcher)"
    if command -v uv >/dev/null 2>&1; then
        ok "  uv on PATH: $(command -v uv)"
        return
    fi
    # Common post-install location on POSIX systems
    local user_bin="$HOME/.local/bin/uv"
    if [ -x "$user_bin" ]; then
        warn "  uv found at $user_bin but not on PATH"
        warn "  Re-open terminal (and Kiro) after install; using session-local PATH for now"
        export PATH="$HOME/.local/bin:$PATH"
        return
    fi
    if [ "$NO_AUTO_INSTALL_UV" -eq 1 ]; then
        err "uv not found and --no-auto-install-uv set. Install manually:"
        err "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        err "  https://docs.astral.sh/uv/getting-started/installation/"
        exit 9
    fi
    log "  uv not found; auto-installing via https://astral.sh/uv/install.sh"
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        err "  uv install failed"
        err "  Install manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 9
    fi
    # Refresh PATH to pick up new install
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        err "  uv installed but not on PATH; re-open terminal and re-run bootstrap"
        exit 9
    fi
    ok "  uv installed at $(command -v uv)"
}

# === Phase 2.5: /dlc: plugin auto-install (K4 fix) ===
phase2_5_resolve_dlc_plugin() {
    log "Phase 2.5: Detect /dlc: Claude Code plugin"
    CACHE_ROOT="$HOME/.claude/plugins/cache/dlc-automation/dlc"
    has_cache() {
        [ -d "$CACHE_ROOT" ] || return 1
        for v in "$CACHE_ROOT"/*/; do
            [ -d "${v}skills" ] && return 0
        done
        return 1
    }
    if has_cache; then
        ok "  /dlc: plugin cache present at $CACHE_ROOT"
        return
    fi
    if [ "$NO_AUTO_INSTALL_PLUGIN" -eq 1 ]; then
        err "  /dlc: plugin not installed and --no-auto-install-plugin set. Install manually:"
        err "    claude plugin marketplace add ops-guru/dlc-plugin"
        err "    claude plugin install dlc@dlc-automation"
        exit 9
    fi
    log "  /dlc: plugin cache missing; installing via Claude plugin registry"
    # Step 1: marketplace add (idempotent — only run if absent)
    if ! claude plugin marketplace list 2>&1 | grep -q 'dlc-automation'; then
        log "    Adding marketplace: ops-guru/dlc-plugin"
        if ! claude plugin marketplace add ops-guru/dlc-plugin; then
            err "  claude plugin marketplace add failed. Install manually:"
            err "    claude plugin marketplace add ops-guru/dlc-plugin"
            err "    claude plugin install dlc@dlc-automation"
            exit 9
        fi
    else
        ok "    Marketplace dlc-automation already configured"
    fi
    # Step 2: install plugin
    log "    Installing plugin: dlc@dlc-automation"
    if ! claude plugin install dlc@dlc-automation; then
        err "  claude plugin install failed. Install manually:"
        err "    claude plugin install dlc@dlc-automation"
        exit 9
    fi
    # Step 3: re-check cache
    if ! has_cache; then
        err "  Plugin install reported success but cache still missing at $CACHE_ROOT"
        err "  File an issue at https://github.com/ops-guru/dlc-supercharge/issues"
        exit 9
    fi
    ok "  /dlc: plugin installed (auto) at $CACHE_ROOT"
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

    # K5 fix: vendor the bridge runtime so target workspaces have it locally.
    log "Phase 4 (continued): vendor bridge runtime"
    local runtime_src="$BUNDLE_ROOT/src/dlc_bridge"
    local runtime_dst="$TARGET/.kiro/powers/dlc-supercharge/runtime/src/dlc_bridge"
    if [ ! -d "$runtime_src" ]; then
        err "  Bridge runtime source missing at $runtime_src — Power bundle integrity error"
        exit 9
    fi
    mkdir -p "$runtime_dst"
    # rsync if available (handles excludes cleanly); fall back to find+cp.
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude='__pycache__' --exclude='*.pyc' "$runtime_src/" "$runtime_dst/"
    else
        (
            cd "$runtime_src" && find . -type f \
                -not -path './__pycache__/*' \
                -not -path '*/__pycache__/*' \
                -not -name '*.pyc' \
                -print0 | while IFS= read -r -d '' f; do
                    parent=$(dirname "$runtime_dst/$f")
                    [ -d "$parent" ] || mkdir -p "$parent"
                    cp "$f" "$runtime_dst/$f"
                done
        )
    fi
    local runtime_file_count
    runtime_file_count=$(find "$runtime_dst" -type f | wc -l | tr -d ' ')
    ok "  Vendored bridge runtime: $runtime_file_count file(s) at $runtime_dst"

    # Copy pyproject.toml + uv.lock + README.md alongside the vendored package so uv can install it.
    # README.md is required because pyproject.toml declares `readme = "README.md"` and hatchling
    # validates the file's existence during wheel build.
    copy_if_different "$BUNDLE_ROOT/pyproject.toml" "$TARGET/.kiro/powers/dlc-supercharge/runtime/pyproject.toml"
    if [ -f "$BUNDLE_ROOT/uv.lock" ]; then
        copy_if_different "$BUNDLE_ROOT/uv.lock" "$TARGET/.kiro/powers/dlc-supercharge/runtime/uv.lock"
    fi
    if [ -f "$BUNDLE_ROOT/README.md" ]; then
        copy_if_different "$BUNDLE_ROOT/README.md" "$TARGET/.kiro/powers/dlc-supercharge/runtime/README.md"
    fi
    ok "  Vendored runtime pyproject.toml + uv.lock + README.md"
}

# === Phase 4.5: target-workspace uv sync against vendored bridge runtime (K5 fix) ===
phase4_5_uv_sync() {
    log "Phase 4.5: Sync target workspace Python env (vendored bridge runtime)"

    local vendored_runtime="$TARGET/.kiro/powers/dlc-supercharge/runtime"
    if [ ! -f "$vendored_runtime/src/dlc_bridge/__init__.py" ]; then
        err "  Vendored runtime missing at $vendored_runtime — Phase 4 should have placed it"
        exit 9
    fi

    local target_pyproject="$TARGET/pyproject.toml"
    if [ -f "$target_pyproject" ]; then
        # Option A (per tech-design § 4.5): warn + manual instructions, do NOT clobber.
        warn "  Target workspace already has pyproject.toml at $target_pyproject"
        warn "  Add this to install the bridge runtime, then re-run bootstrap:"
        warn "    [project] dependencies = ['dlc-bridge']"
        warn "    [tool.uv.sources] dlc-bridge = { path = '.kiro/powers/dlc-supercharge/runtime', editable = false }"
        warn "  Skipping write to avoid clobbering user content; bridge hooks will fail until merged."
        return
    fi

    local template="$BUNDLE_ROOT/dist/config/target-workspace-pyproject.toml.template"
    if [ ! -f "$template" ]; then
        err "  Target-workspace pyproject template missing at $template — Power bundle integrity error"
        exit 9
    fi
    cp "$template" "$target_pyproject"
    ok "  Wrote $target_pyproject (target-workspace pyproject)"

    # Clear inherited VIRTUAL_ENV inside the subshell so uv resolves the
    # workspace venv from $PWD instead of an unrelated project's venv.
    (
        unset VIRTUAL_ENV
        cd "$TARGET" && uv sync 2>&1 | sed 's/^/  /'
        exit ${PIPESTATUS[0]}
    )
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        err "  uv sync failed (exit $rc) at $TARGET"
        err "  Check Python availability: uv python install 3.11"
        exit 9
    fi
    ok "  uv sync complete (target=$TARGET)"

    # Verify import (K5 acceptance).
    local verify
    verify=$( (unset VIRTUAL_ENV; cd "$TARGET" && uv run python -c "import dlc_bridge; print('OK')" 2>&1) )
    if [ "$?" -ne 0 ] || ! echo "$verify" | grep -q 'OK'; then
        err "  Bridge runtime sync succeeded but import failed:"
        err "  $verify"
        exit 9
    fi
    ok "  Bridge runtime importable: dlc_bridge resolved from $vendored_runtime"
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

    # Test 2: bridge dry-run via the v2.0 Python bridge. The v1.1 PS/bash
    # bridge fallback was removed in the v2.0.1 dist sync — those scripts
    # no longer ship in dist/scripts/.
    if command -v uv >/dev/null 2>&1; then
        local py_out py_exit
        py_out=$(uv run dlc-bridge help 2>&1)
        py_exit=$?
        if [ "$py_exit" -eq 0 ] && echo "$py_out" | grep -q 'DLC SuperCharge bridge'; then
            ok "  Python bridge smoke: exit 0, 'DLC SuperCharge bridge' detected"
        else
            err "  Python bridge smoke failed: exit=$py_exit"
            err "  Output: $(echo "$py_out" | head -1)"
            failures=$((failures+1))
        fi
    else
        err "  Bridge dry-run skipped: uv not on PATH (Python bridge unavailable)"
        failures=$((failures+1))
    fi

    # Test 3: POWER.md frontmatter has the required keys.
    # Validate key presence (not a hard count) so optional fields like `author` don't break smoke.
    local power_md="$TARGET/.kiro/powers/dlc-supercharge/POWER.md"
    if [ -f "$power_md" ]; then
        local keys missing
        keys=$(awk '/^---$/{c++; next} c==1 && /^[a-zA-Z]+:/{sub(":.*", ""); print}' "$power_md" | tr '\n' ' ')
        missing=""
        for req in name version displayName description keywords; do
            if ! echo " $keys " | grep -q " $req "; then
                missing="$missing $req"
            fi
        done
        if [ -z "$missing" ]; then
            ok "  POWER.md frontmatter: required keys present ($(echo $keys | wc -w) total)"
        else
            err "  POWER.md frontmatter: missing required keys:$missing. Got: $keys"
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
phase1_5_resolve_uv
phase2_5_resolve_dlc_plugin
phase2_prereqs
phase3_idempotent
phase4_copy
phase4_5_uv_sync
phase5_config
phase6_smoke
phase6_5_register_kiro_power
phase7_playbook

exit 0
