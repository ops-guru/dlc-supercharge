"""WI-11 bootstrap edit verification.

Static (parse-only + marker-presence) checks for the two bootstrap scripts.

These tests do NOT execute the bootstrap scripts (they would side-effect the
user's machine: install uv, write files, register with Kiro Powers). They only:

1. Parse-check each script so syntax errors are caught.
2. Assert the required v2.0 markers are present:
   * ``-NoAutoInstallUv`` / ``--no-auto-install-uv``
   * "Phase 1.5" and "Phase 4.5" comments
   * uv install URLs (Astral)
3. The PS parser uses ``[System.Management.Automation.Language.Parser]::ParseFile``
   which returns ``$null`` for $errors when the script is syntactically valid.

Skipped on environments without ``powershell.exe`` / ``pwsh`` (PS test) or
without ``bash`` (sh test).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_PS1 = REPO_ROOT / "dlc-supercharge" / "bootstrap.ps1"
BOOTSTRAP_SH = REPO_ROOT / "dlc-supercharge" / "bootstrap.sh"


def _find_powershell() -> str | None:
    for exe in ("pwsh", "powershell.exe", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def _find_bash() -> str | None:
    return shutil.which("bash")


_HAS_PS = _find_powershell() is not None
_HAS_BASH = _find_bash() is not None


@pytest.mark.skipif(not _HAS_PS, reason="bootstrap.ps1 parse-check requires PowerShell")
class TestBootstrapPs1:
    def test_file_exists(self) -> None:
        assert BOOTSTRAP_PS1.is_file(), f"bootstrap.ps1 missing at {BOOTSTRAP_PS1}"

    def test_parses_cleanly(self) -> None:
        """PowerShell parser reports zero syntax errors."""
        ps = _find_powershell()
        assert ps is not None
        # Pipe the parse-error count to stdout; non-zero count means failure.
        cmd = (
            f"$errors = $null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{BOOTSTRAP_PS1.as_posix()}', [ref]$null, [ref]$errors) | Out-Null; "
            f"Write-Output $errors.Count"
        )
        cp = subprocess.run(
            [ps, "-NoProfile", "-Command", cmd],
            capture_output=True, check=True, timeout=15.0,
        )
        out = cp.stdout.decode("utf-8", errors="replace").strip()
        # Output may have warnings before — last non-empty line is the count.
        lines = [ln for ln in out.splitlines() if ln.strip()]
        count = int(lines[-1]) if lines else -1
        assert count == 0, f"bootstrap.ps1 has {count} parse errors"

    def test_contains_no_auto_install_uv_switch(self) -> None:
        content = BOOTSTRAP_PS1.read_text(encoding="utf-8", errors="replace")
        assert "$NoAutoInstallUv" in content, "Missing -NoAutoInstallUv switch"
        # The param block declaration should mention it
        assert "[switch]$NoAutoInstallUv" in content

    def test_contains_phase_1_5_resolve_uv(self) -> None:
        content = BOOTSTRAP_PS1.read_text(encoding="utf-8", errors="replace")
        assert "Phase 1.5" in content
        assert "Resolve-Uv" in content
        assert "astral.sh/uv/install.ps1" in content

    def test_contains_phase_4_5_uv_sync(self) -> None:
        content = BOOTSTRAP_PS1.read_text(encoding="utf-8", errors="replace")
        assert "Phase 4.5" in content
        assert "Invoke-UvSync" in content
        assert "uv sync" in content

    def test_python_bridge_smoke_preferred(self) -> None:
        """Phase 6 smoke now tries `uv run dlc-bridge help` before v1.1 PS."""
        content = BOOTSTRAP_PS1.read_text(encoding="utf-8", errors="replace")
        assert "uv run dlc-bridge" in content
        assert "Python bridge smoke" in content


@pytest.mark.skipif(not _HAS_BASH, reason="bootstrap.sh parse-check requires bash")
class TestBootstrapSh:
    def test_file_exists(self) -> None:
        assert BOOTSTRAP_SH.is_file(), f"bootstrap.sh missing at {BOOTSTRAP_SH}"

    def test_parses_cleanly(self) -> None:
        """bash -n parse-only mode reports no syntax errors."""
        bash = _find_bash()
        assert bash is not None
        cp = subprocess.run(
            [bash, "-n", str(BOOTSTRAP_SH)],
            capture_output=True, check=False, timeout=15.0,
        )
        assert cp.returncode == 0, (
            f"bootstrap.sh failed bash -n parse-check:\n"
            f"stdout: {cp.stdout!r}\nstderr: {cp.stderr!r}"
        )

    def test_contains_no_auto_install_uv_flag(self) -> None:
        content = BOOTSTRAP_SH.read_text(encoding="utf-8", errors="replace")
        assert "--no-auto-install-uv" in content
        assert "NO_AUTO_INSTALL_UV" in content

    def test_contains_phase_1_5_resolve_uv(self) -> None:
        content = BOOTSTRAP_SH.read_text(encoding="utf-8", errors="replace")
        assert "Phase 1.5" in content
        assert "phase1_5_resolve_uv" in content
        assert "astral.sh/uv/install.sh" in content

    def test_contains_phase_4_5_uv_sync(self) -> None:
        content = BOOTSTRAP_SH.read_text(encoding="utf-8", errors="replace")
        assert "Phase 4.5" in content
        assert "phase4_5_uv_sync" in content
        assert "uv sync" in content

    def test_python_bridge_smoke_preferred(self) -> None:
        """Phase 6 smoke now tries `uv run dlc-bridge help` before v1.1 bash."""
        content = BOOTSTRAP_SH.read_text(encoding="utf-8", errors="replace")
        assert "uv run dlc-bridge" in content
        assert "Python bridge smoke" in content


@pytest.mark.skipif(not _HAS_PS, reason="requires PowerShell for invocation")
def test_bootstrap_ps1_param_block_parses(tmp_path: Path) -> None:
    """Parse the script via the PS AST and confirm the param block declares NoAutoInstallUv.

    Walks the parsed AST to find ParamBlockAst, then asserts a parameter
    named ``NoAutoInstallUv`` exists. This is stronger than a simple string
    match because it verifies the declaration is in the actual param block,
    not just a comment.
    """
    ps = _find_powershell()
    assert ps is not None
    cmd = (
        f"$errors = $null; "
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{BOOTSTRAP_PS1.as_posix()}', [ref]$null, [ref]$errors); "
        f"$params = $ast.ParamBlock.Parameters | ForEach-Object {{ $_.Name.VariablePath.UserPath }}; "
        f"$params -join ','"
    )
    cp = subprocess.run(
        [ps, "-NoProfile", "-Command", cmd],
        capture_output=True, check=True, timeout=15.0,
    )
    out = cp.stdout.decode("utf-8", errors="replace").strip()
    params = {p.strip() for p in out.split(",") if p.strip()}
    assert "NoAutoInstallUv" in params, (
        f"PS AST did not surface NoAutoInstallUv in param block; found: {params!r}"
    )
