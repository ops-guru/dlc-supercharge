<#
.SYNOPSIS
    Register a DLC SuperCharge Power with Kiro's user-scoped Powers registry (v1.0.1 fix for Powers-panel visibility).

.DESCRIPTION
    Kiro's "Power" install is a 2-layer concept:
      1. Workspace-scoped: hooks/agents/scripts at <workspace>/.kiro/ — installed by bootstrap.{ps1,sh}
      2. User-scoped: POWER.md + mcp.json + steering/ at ~/.kiro/powers/installed/<name>/ + registry entries
         — what makes the Power appear in Kiro's Powers panel

    This script handles layer 2. It mirrors Kiro's own `addCustomPowerByFolder` flow:
      - Copies POWER.md, mcp.json, steering/ to ~/.kiro/powers/installed/<powerName>/
      - Appends an entry to ~/.kiro/powers/registries/user-added.json
      - Appends an entry to ~/.kiro/powers/installed.json

    Critical: all JSON files written WITHOUT UTF-8 BOM (PS 5.1's `Set-Content -Encoding utf8`
    writes WITH BOM by default; Kiro's JSON parser rejects BOM-prefixed input).

.PARAMETER BundlePath
    Absolute path to the Power bundle folder (must contain POWER.md).

.PARAMETER PowerName
    Power name (slug). Defaults to bundle folder basename lowercased + sanitized.

.EXAMPLE
    .\register-kiro-power.ps1 -BundlePath c:\path\to\dlc-supercharge
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BundlePath,
    [string]$PowerName
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path (Join-Path $BundlePath 'POWER.md'))) {
    Write-Host "ERROR: $BundlePath does not contain POWER.md" -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrEmpty($PowerName)) {
    $PowerName = ((Split-Path -Leaf $BundlePath).ToLower() -replace '[^a-z0-9-]','-')
}

$powersHome    = Join-Path $env:USERPROFILE '.kiro\powers'
$installedDir  = Join-Path $powersHome "installed\$PowerName"
$registriesDir = Join-Path $powersHome 'registries'
$userAddedPath = Join-Path $registriesDir 'user-added.json'
$installedJson = Join-Path $powersHome 'installed.json'

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-JsonNoBom {
    param([string]$Path, [object]$Object)
    $json = $Object | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

# 1. Copy POWER.md + mcp.json + steering/ (Kiro's ALLOWED_FILES/ALLOWED_DIRS)
Write-Host "[register-power] Copy Power files to $installedDir"
New-Item -ItemType Directory -Force -Path $installedDir | Out-Null
Copy-Item -Force -Path (Join-Path $BundlePath 'POWER.md') -Destination $installedDir
if (Test-Path (Join-Path $BundlePath 'mcp.json')) {
    Copy-Item -Force -Path (Join-Path $BundlePath 'mcp.json') -Destination $installedDir
}
$steeringSrc = Join-Path $BundlePath 'steering'
if (Test-Path $steeringSrc) {
    $steeringDst = Join-Path $installedDir 'steering'
    New-Item -ItemType Directory -Force -Path $steeringDst | Out-Null
    Copy-Item -Force -Recurse -Path (Join-Path $steeringSrc '*') -Destination $steeringDst
}

# 2. Update user-added.json (the user-added registry)
Write-Host "[register-power] Update $userAddedPath"
New-Item -ItemType Directory -Force -Path $registriesDir | Out-Null
$userAdded = if (Test-Path $userAddedPath) {
    try { Get-Content -Raw $userAddedPath | ConvertFrom-Json } catch { $null }
} else { $null }
if (-not $userAdded) {
    $userAdded = [PSCustomObject]@{ powers = @() }
}
$powersList = @($userAdded.powers | Where-Object { $_.name -ne $PowerName })
$entry = [PSCustomObject]@{
    name = $PowerName
    description = "Custom power from $BundlePath"
    source = [PSCustomObject]@{ type = 'local'; path = $BundlePath }
}
$powersList = @($powersList) + $entry
$userAdded = [PSCustomObject]@{ powers = $powersList }
Write-JsonNoBom -Path $userAddedPath -Object $userAdded

# 3. Update installed.json (the master installed-Powers list)
Write-Host "[register-power] Update $installedJson"
$inst = if (Test-Path $installedJson) {
    try { Get-Content -Raw $installedJson | ConvertFrom-Json } catch { $null }
} else { $null }
if (-not $inst) {
    $inst = [PSCustomObject]@{
        version = '1.0.0'
        installedPowers = @()
        dismissedAutoInstalls = @()
    }
}
$installedList = @($inst.installedPowers | Where-Object { $_.name -ne $PowerName })
$installedList = @($installedList) + ([PSCustomObject]@{ name = $PowerName; registryId = 'user-added' })
$inst.installedPowers = $installedList
Write-JsonNoBom -Path $installedJson -Object $inst

Write-Host ""
Write-Host "[register-power] OK: $PowerName registered with Kiro user-scoped registry" -ForegroundColor Green
Write-Host "[register-power] Run 'Developer: Reload Window' in Kiro (Ctrl+Shift+P) to refresh the Powers panel." -ForegroundColor Yellow
