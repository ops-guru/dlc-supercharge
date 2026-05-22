"""Shared fixtures + helpers for the FR-19 parity gate suite.

The parity tests are tagged with ``@pytest.mark.parity`` (declared in
``pyproject.toml``) and can be selected via ``pytest -m parity``.

Cross-language tests rely on a PowerShell host being available — either
``pwsh`` (PowerShell 7+) or ``powershell.exe`` (Windows PowerShell 5.1). When
neither is present (typical on Linux/macOS GitHub Actions runners), tests that
require PS execution are skipped via :func:`require_powershell`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


# Fields that legitimately differ between Python v2.0 and PS v1.1 and that the
# parity tests therefore exclude from byte-equality comparison.
EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {
        # Timestamps — Python and PS both emit ISO-8601 UTC but the actual
        # second is captured at run-time and will not match.
        "startedAt",
        "endedAt",
        "heartbeatAt",
        "completedAt",
        "Last updated",
        "started",
        "completed",
        # Process identity — varies per spawn.
        "jobId",
        "pid",
        # Prompt digest — depends on absolute paths in the prompt.
        "promptDigest",
        # Cache-version stamp — v1.1 caches have no such field; v2.0 always emits it.
        "cache_version",
    }
)


def find_powershell() -> str | None:
    """Return the path of an available PowerShell host (``pwsh`` preferred) or ``None``.

    The order matches v1.1's preference: cross-platform ``pwsh`` first, then
    ``powershell.exe`` (Windows 5.1) as a fallback.
    """
    for exe in ("pwsh", "powershell.exe", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def have_powershell() -> bool:
    return find_powershell() is not None


# pytest's ``skipif`` decorator wants a boolean *condition*, so we compute the
# absence once at import time (avoids recomputation per test).
_POWERSHELL_PATH = find_powershell()
require_powershell = pytest.mark.skipif(
    _POWERSHELL_PATH is None,
    reason="cross-language parity test requires powershell.exe or pwsh",
)


def run_powershell(args: list[str], *, cwd: Path | None = None,
                   check: bool = True, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Invoke ``powershell.exe`` (or ``pwsh``) with v1.1-style flags.

    Returns a :class:`subprocess.CompletedProcess`. ``check=True`` raises
    :class:`subprocess.CalledProcessError` on non-zero exit.

    Decodes child stdout/stderr with ``errors='replace'`` because v1.1
    PowerShell 5.1 emits console output in the active code page (often
    Windows-1252 on en-US), not UTF-8. Strict decoding would explode on
    log lines containing curly-quotes / em-dashes. Replace-on-error keeps
    the JSON envelope intact (JSON is ASCII-safe) while tolerating
    log-line garbage.
    """
    ps = _POWERSHELL_PATH
    if ps is None:
        raise RuntimeError("PowerShell not available — guard with require_powershell")
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", *args]
    cp = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        timeout=timeout,
        check=check,
    )
    # Decode with lenient errors=replace.
    stdout = cp.stdout.decode("utf-8", errors="replace") if cp.stdout else ""
    stderr = cp.stderr.decode("utf-8", errors="replace") if cp.stderr else ""
    # Re-wrap as a text CompletedProcess (preserve returncode etc.).
    return subprocess.CompletedProcess(
        args=cp.args, returncode=cp.returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture(scope="session")
def parity_root() -> Path:
    """Root of the parity test data (goldens + fixtures)."""
    return Path(__file__).parent


@pytest.fixture(scope="session")
def goldens_root() -> Path:
    """``tests/goldens/v1_1/`` — committed goldens (real or hand-constructed)."""
    return Path(__file__).parent.parent / "goldens" / "v1_1"


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    """``tests/fixtures/`` — canonical input fixtures."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root (so tests can invoke `uv run dlc-bridge` and the v1.1 PS scripts)."""
    return Path(__file__).parent.parent.parent


def normalize_eol(text: str) -> str:
    """Normalize CRLF/CR to LF — Python and PS sometimes disagree on EOL writes."""
    return text.replace("\r\n", "\n").replace("\r", "\n")
