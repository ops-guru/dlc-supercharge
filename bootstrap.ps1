#Requires -Version 5.1
<#
.SYNOPSIS
    Install DLC SuperCharge into a target Kiro workspace.

.DESCRIPTION
    Copies POWER.md, mcp.json, steering, hooks, agents, scripts, and templates from this
    Power bundle into <target>/.kiro/. Runs prereq checks, idempotency check, file copy,
    optional .dlc.config.json, embedded smoke tests, and prints a hackathon playbook.

    Exit codes:
      0   Success (or already-installed, idempotent re-run)
      8   Smoke test failure on freshly-installed bundle
      9   Prerequisite check failure (claude missing, plugin not loaded, etc.)
     10   File copy conflict: pre-existing modified DLC file without -Force

.PARAMETER Into
    Target workspace directory. Defaults to current working directory.

.PARAMETER Force
    Overwrite pre-existing files even if they differ from the bundle.

.PARAMETER WithDlcConfig
    Write .dlc.config.json at workspace root from the bundled template.

.PARAMETER NoSmokeTests
    Skip Phase 6 smoke tests. Useful for CI installs where you'll run your own verification.

.PARAMETER Quiet
    Suppress non-error output and the post-install playbook.

.PARAMETER NoAutoInstallUv
    Skip Phase 1.5 auto-install of `uv` (Astral Python launcher). If `uv` is
    not already on PATH, the bootstrap exits 9 with a manual-install URL.
    Use this in corporate environments that prohibit `irm | iex`-style
    installer scripts (per NFR-8).

.EXAMPLE
    .\bootstrap.ps1
    Install into the current directory.

.EXAMPLE
    .\bootstrap.ps1 -Into C:\projects\my-repo -WithDlcConfig
    Install into a specific workspace, also writing .dlc.config.json.

.EXAMPLE
    .\bootstrap.ps1 -Force
    Re-install over existing files, overwriting any user modifications to DLC files.

.EXAMPLE
    .\bootstrap.ps1 -NoAutoInstallUv
    Install without attempting to auto-install `uv` if missing (corp policy mode).
#>
[CmdletBinding()]
param(
    [string]$Into = (Get-Location).Path,
    [string]$FromGit = '',
    [switch]$Force,
    [switch]$WithDlcConfig,
    [switch]$NoSmokeTests,
    [switch]$Quiet,
    [switch]$NoRegisterKiroPower,
    [switch]$NoAutoInstallUv
)

$ErrorActionPreference = 'Stop'
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:CloneDir = $null

# If --from-git, clone the Power into a temp dir and reset $BundleRoot.
if (-not [string]::IsNullOrEmpty($FromGit)) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "[bootstrap] ERROR: -FromGit requires `git` on PATH" -ForegroundColor Red
        exit 9
    }
    $Script:CloneDir = Join-Path $env:TEMP "dlc-sc-clone-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    Write-Host "[bootstrap] Cloning $FromGit into $($Script:CloneDir) ..." -ForegroundColor Cyan
    & git clone --depth 1 $FromGit $Script:CloneDir 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[bootstrap] ERROR: git clone failed (exit $LASTEXITCODE). Clone preserved at $($Script:CloneDir) for debugging." -ForegroundColor Red
        exit 9
    }
    $BundleRoot = $Script:CloneDir
    Write-Host "[bootstrap] OK: Using cloned bundle at $BundleRoot" -ForegroundColor Green
}

# === Output helpers ===
function Write-Step($msg) { if (-not $Quiet) { Write-Host "[bootstrap] $msg" -ForegroundColor Cyan } }
function Write-Warn($msg) { Write-Host "[bootstrap] WARN: $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[bootstrap] ERROR: $msg" -ForegroundColor Red }
function Write-Ok($msg)   { if (-not $Quiet) { Write-Host "[bootstrap] OK: $msg" -ForegroundColor Green } }

# === Phase 1: Resolve target workspace ===
function Resolve-Target {
    Write-Step "Phase 1: Resolve target workspace"
    if (-not (Test-Path $Into)) {
        Write-Err "Target directory does not exist: $Into"
        exit 9
    }
    $Script:Target = (Resolve-Path $Into).Path
    Write-Ok "Target: $Script:Target"

    $gitDir = Join-Path $Script:Target '.git'
    if (-not (Test-Path $gitDir)) {
        if ($Force) {
            Write-Warn "No .git/ at target; proceeding because -Force was passed"
        } else {
            Write-Warn "No .git/ at target. DLC SuperCharge is typically installed into a git repo; use -Force to install anyway."
            # Don't fail - just warn. The user may legitimately install outside a repo.
        }
    }
}

# === Phase 2: Prerequisite checks (FR-29) ===
function Test-Prereq {
    param([string]$Name, [scriptblock]$Check, [string]$Severity, [string]$Remediation)
    try {
        $result = & $Check
        if ($result) {
            return @{ Name = $Name; Status = 'pass'; Detail = $result }
        }
    } catch {
        # fall through to fail/warn
    }
    return @{ Name = $Name; Status = $Severity; Detail = ''; Remediation = $Remediation }
}

function Test-Prereqs {
    Write-Step "Phase 2: Prerequisite checks"

    $checks = @(
        Test-Prereq -Name 'claude CLI on PATH' -Severity 'fail' `
            -Check { (Get-Command claude -ErrorAction Stop) | Out-Null; 'present' } `
            -Remediation 'Install Claude Code from https://docs.claude.com/claude-code'

        Test-Prereq -Name 'claude supports --append-system-prompt' -Severity 'fail' `
            -Check {
                $help = & claude --help 2>&1 | Out-String
                # Older claude help showed --append-system-prompt-file; newer just --append-system-prompt.
                # Either form satisfies the bridge's invocation.
                if ($help -match 'append-system-prompt') { 'present' } else { $null }
            } `
            -Remediation 'Claude Code version too old; run `claude --version` and upgrade if <2.0'

        Test-Prereq -Name '/dlc: plugin cache present' -Severity 'fail' `
            -Check {
                $cacheRoot = Join-Path $env:USERPROFILE '.claude\plugins\cache\dlc-automation\dlc'
                if (-not (Test-Path $cacheRoot)) { return $null }
                $versions = @(Get-ChildItem -Directory -Path $cacheRoot -ErrorAction SilentlyContinue |
                              Where-Object { Test-Path (Join-Path $_.FullName 'skills') })
                if ($versions.Count -gt 0) { "found $($versions.Count) version(s)" } else { $null }
            } `
            -Remediation 'Install the /dlc: plugin from the Claude Code plugin registry'

        Test-Prereq -Name 'PowerShell execution policy' -Severity 'fail' `
            -Check {
                # Use effective policy (no -Scope) which respects Process-level overrides,
                # MachinePolicy/UserPolicy/CurrentUser/LocalMachine cascade automatically.
                $effective = Get-ExecutionPolicy
                if ($effective -in @('RemoteSigned','Unrestricted','Bypass')) {
                    return "effective: $effective"
                }
                return $null
            } `
            -Remediation 'Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` or invoke scripts with -ExecutionPolicy Bypass'

        Test-Prereq -Name 'gh CLI on PATH' -Severity 'warn' `
            -Check { (Get-Command gh -ErrorAction Stop) | Out-Null; 'present' } `
            -Remediation 'Install GitHub CLI from https://cli.github.com (needed for babysit-pr, hotfix-revert verbs)'

        Test-Prereq -Name 'Anthropic auth configured' -Severity 'warn' `
            -Check {
                if ($env:ANTHROPIC_API_KEY) { return 'ANTHROPIC_API_KEY set' }
                $credPath = Join-Path $env:USERPROFILE '.claude\credentials'
                if (Test-Path $credPath) { return '~/.claude/credentials present' }
                return $null
            } `
            -Remediation 'Set ANTHROPIC_API_KEY or run `claude login`'

        Test-Prereq -Name 'Free disk space >= 100 MB' -Severity 'fail' `
            -Check {
                $drive = (Get-Item $Script:Target).PSDrive
                if (-not $drive) { return $null }
                $freeMb = [Math]::Round($drive.Free / 1MB, 1)
                if ($freeMb -ge 100) { "$freeMb MB free" } else { $null }
            } `
            -Remediation 'Free up disk space at target'
    )

    $failCount = 0
    foreach ($c in $checks) {
        if ($c.Status -eq 'pass') {
            Write-Ok ("  [{0,-4}] {1} ({2})" -f 'PASS', $c.Name, $c.Detail)
        } elseif ($c.Status -eq 'warn') {
            Write-Warn ("  [{0,-4}] {1} - {2}" -f 'WARN', $c.Name, $c.Remediation)
        } else {
            Write-Err ("  [{0,-4}] {1} - {2}" -f 'FAIL', $c.Name, $c.Remediation)
            $failCount++
        }
    }

    if ($failCount -gt 0) {
        Write-Err "Prereq checks failed ($failCount). Resolve the FAIL items above and re-run."
        exit 9
    }
    Write-Ok "Prereq checks passed"
}

# === Phase 1.5: uv detection + auto-install (FR-20, NFR-8) ===
function Resolve-Uv {
    Write-Step "Phase 1.5: Detect uv (Astral Python launcher)"
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Ok "  uv on PATH: $((Get-Command uv).Source)"
        return
    }
    # Common post-install location
    $userBin = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path $userBin) {
        Write-Warn "  uv found at $userBin but not on PATH"
        Write-Warn "  Re-open the terminal (and Kiro) after install to pick it up; absolute path will be used in this session"
        $env:PATH = "$(Split-Path $userBin);" + $env:PATH
        return
    }
    if ($NoAutoInstallUv) {
        Write-Err "uv not found and -NoAutoInstallUv set. Install manually:"
        Write-Err "  irm https://astral.sh/uv/install.ps1 | iex"
        Write-Err "  https://docs.astral.sh/uv/getting-started/installation/"
        exit 9
    }
    Write-Step "  uv not found; auto-installing via https://astral.sh/uv/install.ps1"
    try {
        irm https://astral.sh/uv/install.ps1 | iex
    } catch {
        Write-Err "  uv install failed: $($_.Exception.Message)"
        Write-Err "  Install manually: irm https://astral.sh/uv/install.ps1 | iex"
        exit 9
    }
    # Re-check PATH (installer mutates user-level PATH but current session needs refresh)
    $env:PATH = "$(Join-Path $env:USERPROFILE '.local\bin');" + $env:PATH
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Err "  uv installed but not on PATH; re-open terminal and re-run bootstrap"
        exit 9
    }
    Write-Ok "  uv installed at $((Get-Command uv).Source)"
}

# === Phase 3: Idempotency check ===
function Test-Idempotent {
    Write-Step "Phase 3: Idempotency check"
    $powerMd = Join-Path $Script:Target '.kiro\powers\dlc-supercharge\POWER.md'
    if (-not (Test-Path $powerMd)) {
        Write-Ok "Fresh install"
        return $false
    }
    if ($Force) {
        Write-Warn "DLC SuperCharge already installed at target; -Force passed, overwriting"
        return $true
    }
    Write-Ok "Already installed at $powerMd. Use -Force to overwrite. Exiting."
    exit 0
}

# === Phase 4: File copy (FR-27, FR-28) ===
function Get-FileSha256 {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

function Copy-IfDifferent {
    param([string]$Source, [string]$Dest)
    $parent = Split-Path -Parent $Dest
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (-not (Test-Path $Dest)) {
        Copy-Item -Path $Source -Destination $Dest -Force
        return 'added'
    }
    $sHash = Get-FileSha256 -Path $Source
    $dHash = Get-FileSha256 -Path $Dest
    if ($sHash -eq $dHash) { return 'identical' }
    if ($Force) {
        Copy-Item -Path $Source -Destination $Dest -Force
        return 'overwritten'
    }
    return 'skipped-differs'
}

function Copy-Bundle {
    Write-Step "Phase 4: Copy bundle into target"
    $stats = @{ added = 0; identical = 0; overwritten = 0; 'skipped-differs' = 0 }

    # Map: source path -> array of destinations
    $manifest = @()
    $manifest += @{ Src = (Join-Path $BundleRoot 'POWER.md'); Dst = (Join-Path $Script:Target '.kiro\powers\dlc-supercharge\POWER.md') }
    $manifest += @{ Src = (Join-Path $BundleRoot 'mcp.json'); Dst = (Join-Path $Script:Target '.kiro\powers\dlc-supercharge\mcp.json') }
    # Steering goes to BOTH locations (D-504)
    $steeringSrc = Join-Path $BundleRoot 'steering\dlc-augment.md'
    $manifest += @{ Src = $steeringSrc; Dst = (Join-Path $Script:Target '.kiro\powers\dlc-supercharge\steering\dlc-augment.md') }
    $manifest += @{ Src = $steeringSrc; Dst = (Join-Path $Script:Target '.kiro\steering\dlc-augment.md') }

    # dist/hooks -> .kiro/hooks
    foreach ($f in (Get-ChildItem -Path (Join-Path $BundleRoot 'dist\hooks') -Filter '*.kiro.hook')) {
        $manifest += @{ Src = $f.FullName; Dst = (Join-Path $Script:Target ".kiro\hooks\$($f.Name)") }
    }
    # dist/agents -> .kiro/agents
    foreach ($f in (Get-ChildItem -Path (Join-Path $BundleRoot 'dist\agents') -Filter '*.md')) {
        $manifest += @{ Src = $f.FullName; Dst = (Join-Path $Script:Target ".kiro\agents\$($f.Name)") }
    }
    # dist/scripts -> .kiro/scripts
    foreach ($f in (Get-ChildItem -Path (Join-Path $BundleRoot 'dist\scripts'))) {
        $manifest += @{ Src = $f.FullName; Dst = (Join-Path $Script:Target ".kiro\scripts\$($f.Name)") }
    }
    # dist/templates/verb-tasks -> .kiro/powers/dlc-supercharge/templates/verb-tasks
    foreach ($f in (Get-ChildItem -Path (Join-Path $BundleRoot 'dist\templates\verb-tasks') -Filter '*.txt')) {
        $manifest += @{ Src = $f.FullName; Dst = (Join-Path $Script:Target ".kiro\powers\dlc-supercharge\templates\verb-tasks\$($f.Name)") }
    }
    # dist/templates/state.md.template -> .kiro/powers/dlc-supercharge/templates/state.md.template
    $stateTmpl = Join-Path $BundleRoot 'dist\templates\state.md.template'
    if (Test-Path $stateTmpl) {
        $manifest += @{ Src = $stateTmpl; Dst = (Join-Path $Script:Target '.kiro\powers\dlc-supercharge\templates\state.md.template') }
    }

    foreach ($entry in $manifest) {
        $result = Copy-IfDifferent -Source $entry.Src -Dest $entry.Dst
        $stats[$result]++
        if ($result -eq 'skipped-differs' -and -not $Quiet) {
            Write-Warn "differs (skipped): $($entry.Dst). Use -Force to overwrite."
        }
    }

    $total = ($stats.Values | Measure-Object -Sum).Sum
    Write-Ok "Copied $total file(s): $($stats.added) added, $($stats.identical) unchanged, $($stats.overwritten) overwritten, $($stats['skipped-differs']) skipped"

    if ($stats['skipped-differs'] -gt 0 -and -not $Force) {
        Write-Warn "$($stats['skipped-differs']) file(s) differ from bundle but were preserved. Use -Force to overwrite them."
    }
}

# === Phase 4.5: uv sync (FR-20) ===
function Invoke-UvSync {
    Write-Step "Phase 4.5: Sync Python environment with uv"
    # If the target has a pyproject.toml, sync there; otherwise sync from the bundle root.
    $syncRoot = if (Test-Path (Join-Path $Script:Target 'pyproject.toml')) {
        $Script:Target
    } else {
        $BundleRoot
    }
    if (-not (Test-Path (Join-Path $syncRoot 'pyproject.toml'))) {
        Write-Warn "  No pyproject.toml at $syncRoot; skipping uv sync (will be needed once the Python bridge bundle ships)"
        return
    }
    Push-Location $syncRoot
    try {
        & uv sync 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Err "  uv sync failed (exit $LASTEXITCODE) at $syncRoot"
            Write-Err "  Check Python availability: uv python install 3.11"
            exit 9
        }
        Write-Ok "  uv sync complete ($syncRoot)"
    } finally {
        Pop-Location
    }
}

# === Phase 5: Optional .dlc.config.json (FR-19) ===
function Write-DlcConfig {
    Write-Step "Phase 5: Optional .dlc.config.json"
    $tgtConfig = Join-Path $Script:Target '.dlc.config.json'
    if (Test-Path $tgtConfig) {
        Write-Ok "Pre-existing .dlc.config.json detected; preserving (non-destructive per FR-28)"
        return
    }
    if (-not $WithDlcConfig) {
        Write-Step "  -WithDlcConfig not passed; skipping (re-run with -WithDlcConfig to write the template)"
        return
    }
    $tmplPath = Join-Path $BundleRoot 'dist\config\dlc.config.json.template'
    Copy-Item -Path $tmplPath -Destination $tgtConfig -Force
    Write-Ok "Wrote $tgtConfig from template"
}

# === Phase 6: Embedded smoke tests (FR-31) ===
function Invoke-SmokeTests {
    if ($NoSmokeTests) {
        Write-Step "Phase 6: skipped (-NoSmokeTests)"
        return
    }
    Write-Step "Phase 6: Smoke tests"
    $failures = 0

    # Test 1: hooks parse + have required fields
    $hookDir = Join-Path $Script:Target '.kiro\hooks'
    $validWhenTypes = @('fileEdited','fileCreated','fileDeleted','userTriggered',
                        'promptSubmit','agentStop','preToolUse','postToolUse',
                        'preTaskExecution','postTaskExecution','sessionStart')
    $validThenTypes = @('askAgent','runCommand')
    $hookFiles = @(Get-ChildItem -Path $hookDir -Filter '*.kiro.hook' -ErrorAction SilentlyContinue)
    $hookPass = 0; $hookFail = 0
    foreach ($f in $hookFiles) {
        try {
            $h = Get-Content -Raw $f.FullName | ConvertFrom-Json
            $required = @('version','enabled','name','description','when','then') |
                Where-Object { $null -eq $h.$_ }
            if ($required.Count -gt 0) {
                Write-Err "  hook $($f.Name): missing fields: $($required -join ', ')"
                $hookFail++; continue
            }
            if ($h.when.type -notin $validWhenTypes) {
                Write-Err "  hook $($f.Name): when.type '$($h.when.type)' invalid"; $hookFail++; continue
            }
            if ($h.then.type -notin $validThenTypes) {
                Write-Err "  hook $($f.Name): then.type '$($h.then.type)' invalid"; $hookFail++; continue
            }
            $hookPass++
        } catch {
            Write-Err "  hook $($f.Name): parse error: $($_.Exception.Message)"; $hookFail++
        }
    }
    if ($hookFail -eq 0) {
        Write-Ok "  Schema validation: $hookPass/$hookPass hook(s) valid"
    } else {
        Write-Err "  Schema validation: $hookPass pass, $hookFail fail"
        $failures++
    }

    # Test 2: bridge dry-run via the v2.0 Python bridge. The v1.1 PS/bash
    # bridge fallback was removed in the v2.0.1 dist sync — those scripts
    # no longer ship in dist/scripts/.
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        try {
            $out = & uv run dlc-bridge help 2>&1
            $exit = $LASTEXITCODE
            if ($exit -eq 0 -and ($out -join "`n") -match 'DLC SuperCharge bridge') {
                Write-Ok "  Python bridge smoke: exit 0, 'DLC SuperCharge bridge' detected"
            } else {
                Write-Err "  Python bridge smoke failed: exit=$exit"
                Write-Err "  Output: $($out -join ' ' | Select-Object -First 1)"
                $failures++
            }
        } catch {
            Write-Err "  Python bridge smoke failed: $($_.Exception.Message)"
            $failures++
        }
    } else {
        Write-Err "  Bridge dry-run skipped: uv not on PATH (Python bridge unavailable)"
        $failures++
    }

    # Test 3: POWER.md frontmatter has 5 keys
    $powerMd = Join-Path $Script:Target '.kiro\powers\dlc-supercharge\POWER.md'
    if (Test-Path $powerMd) {
        $lines = Get-Content $powerMd
        $inFM = $false; $keyCount = 0
        foreach ($line in $lines) {
            if ($line -eq '---') { if ($inFM) { break } else { $inFM = $true; continue } }
            if ($inFM -and $line -match '^[a-zA-Z]+:') { $keyCount++ }
        }
        if ($keyCount -eq 5) {
            Write-Ok "  POWER.md frontmatter: 5 keys"
        } else {
            Write-Err "  POWER.md frontmatter: expected 5 keys, got $keyCount"
            $failures++
        }
    } else {
        Write-Err "  POWER.md not found at $powerMd"
        $failures++
    }

    if ($failures -gt 0) {
        Write-Err "Smoke tests failed: $failures test(s)"
        exit 8
    }
    Write-Ok "Smoke tests: 3/3 PASS"
}

# === Phase 7: Playbook print (FR-30) ===
function Write-Playbook {
    if ($Quiet) { return }
    Write-Host ""
    $playbook = @'
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
'@
    Write-Host $playbook -ForegroundColor Cyan
}

# === Phase 6.5: Register with Kiro user-scoped Powers registry (v1.0.1) ===
function Register-KiroPower {
    if ($NoRegisterKiroPower) {
        Write-Step "Phase 6.5: Kiro Power registration (skipped via -NoRegisterKiroPower)"
        return
    }
    Write-Step "Phase 6.5: Register dlc-supercharge with Kiro user-scoped Powers registry"
    # The register-kiro-power helper lives in the workspace .kiro/scripts/ (we just installed it)
    $registerScript = Join-Path $Script:Target '.kiro\scripts\register-kiro-power.ps1'
    if (-not (Test-Path $registerScript)) {
        Write-Warn "  register-kiro-power.ps1 not in target; skipping Power registration"
        return
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $registerScript -BundlePath $BundleRoot 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Power registered. Reload Kiro window (Ctrl+Shift+P -> 'Developer: Reload Window') to see it in the Powers panel."
    } else {
        Write-Warn "Power registration failed (exit $LASTEXITCODE); workspace install still functional, Powers panel will not show the entry."
    }
}

# === Main ===
try {
    Resolve-Target
    Test-Prereqs
    Resolve-Uv
    Test-Idempotent | Out-Null
    Copy-Bundle
    Invoke-UvSync
    Write-DlcConfig
    Invoke-SmokeTests
    Register-KiroPower
    Write-Playbook
} finally {
    # Cleanup --from-git temp clone on success; preserve on failure for debugging.
    if ($Script:CloneDir -and (Test-Path $Script:CloneDir) -and $? -eq $true) {
        Remove-Item -Recurse -Force $Script:CloneDir -ErrorAction SilentlyContinue
    }
}

exit 0
