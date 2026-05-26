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


# Repo root resolved once at import (so legacy-script presence checks are cheap).
_REPO_ROOT = Path(__file__).parent.parent.parent
_LEGACY_SCRIPTS_DIR = _REPO_ROOT / ".kiro" / "scripts"


def have_legacy_scripts() -> bool:
    """Return True iff the v1.1 PS bridge scripts still live under ``.kiro/scripts/``.

    After the Epic 5 cutover (WI-15), this directory is deleted entirely; cross-
    language parity tests that subprocess into ``state-update.ps1`` /
    ``dlc-bridge.ps1`` / ``id-propagate.ps1`` / ``epic-inject.ps1`` will then
    skip cleanly rather than fail with FileNotFoundError.

    The check is intentionally narrow — a single representative script
    (``dlc-bridge.ps1``) — because Epic 5 deletes ALL v1.1 scripts at once.
    """
    return (_LEGACY_SCRIPTS_DIR / "dlc-bridge.ps1").exists()


require_legacy_scripts = pytest.mark.skipif(
    not have_legacy_scripts(),
    reason="v1.1 .kiro/scripts/*.ps1 removed post-Epic-5 cutover (parity goldens remain authoritative)",
)


# Composite gate used by cross-language parity tests that subprocess into a
# v1.1 PS script. Both conditions must hold for the test to run.
require_powershell_and_legacy = pytest.mark.skipif(
    _POWERSHELL_PATH is None or not have_legacy_scripts(),
    reason=(
        "cross-language parity test requires powershell.exe/pwsh AND the v1.1 "
        ".kiro/scripts/*.ps1 sources (removed in Epic 5 cutover; goldens under "
        "tests/goldens/v1_1/ remain authoritative)"
    ),
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


@pytest.fixture(scope="session", autouse=True)
def _stage_verb_task_templates():
    """Stage verb-task templates at the bridge's runtime resolution path.

    The bridge resolves verb-task templates from
    ``<cwd>/.kiro/powers/dlc-supercharge/templates/verb-tasks/`` — the
    *installed* location that ``bootstrap`` copies into a target workspace.
    In a dev/CI checkout the templates live at ``dist/templates/verb-tasks/``
    instead, so the dry-run parity tests would fall back to the synthetic
    minimal task body and produce a too-short ``assembledPrompt``.

    Previously this passed only because the development workspace
    (``ops-guru/kiro-bridge-poc``) had self-installed DLC into its own
    ``.kiro/``. A clean checkout of the standalone ``ops-guru/dlc-supercharge``
    repo has no such self-install, so we stage the templates here and remove
    only what we created (never touching a pre-existing ``.kiro/``).
    """
    root = Path(__file__).parent.parent.parent
    src = root / "dist" / "templates" / "verb-tasks"
    dst = root / ".kiro" / "powers" / "dlc-supercharge" / "templates" / "verb-tasks"

    if not src.is_dir() or dst.is_dir():
        # No source templates, or an install already exists — leave as-is.
        yield
        return

    # Record which ancestor dirs we create so cleanup removes only those.
    created_root = None
    probe = dst
    while not probe.exists():
        created_root = probe
        probe = probe.parent

    dst.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for tmpl in src.glob("*.txt"):
        target = dst / tmpl.name
        shutil.copy2(tmpl, target)
        staged.append(target)

    try:
        yield
    finally:
        for target in staged:
            target.unlink(missing_ok=True)
        if created_root is not None and created_root.exists():
            shutil.rmtree(created_root, ignore_errors=True)


def normalize_eol(text: str) -> str:
    """Normalize CRLF/CR to LF — Python and PS sometimes disagree on EOL writes."""
    return text.replace("\r\n", "\n").replace("\r", "\n")
