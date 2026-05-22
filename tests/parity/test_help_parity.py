"""FR-19 parity gate — `help` verb.

Both v1.1 and v2.0 emit a free-form help text on ``help``. The exact byte
content differs intentionally between v1.1 (Powershell ``Write-Host``) and
v2.0 (Python ``print(...)``), but both MUST mention every supported verb so
users can discover them.

This test asserts the verb-coverage invariant — the strongest invariant that
remains meaningful across the v1.1 → v2.0 reformatting.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from .conftest import require_powershell, run_powershell


pytestmark = pytest.mark.parity


# The 16 supported verbs (per FR-1; mirrors src/dlc_bridge/verbs.py SUPPORTED_VERBS).
SUPPORTED_VERBS: list[str] = [
    "analyze-requirements",
    "produce-tech-design",
    "plan-implementation",
    "finalize-sdlc",
    "discover",
    "review-pr",
    "stabilize-pr",
    "review-security",
    "review-ux",
    "review-a11y",
    "review-performance",
    "reverse-engineer-kb",
    "kb-gap-analysis",
    "map-codebase",
    "babysit-pr",
    "hotfix",
]


def _python_help_output(repo_root: Path) -> str:
    """Run `uv run dlc-bridge help` and return stdout.

    Decodes with ``errors='replace'`` because on Windows ``uv run`` may not
    set the child's stdout encoding to UTF-8, and the help text contains an
    em-dash that Windows-1252 cannot represent. The decoded replacement is
    fine for the substring assertions below.
    """
    cp = subprocess.run(
        ["uv", "run", "dlc-bridge", "help"],
        cwd=str(repo_root),
        capture_output=True,
        check=True,
        timeout=60.0,
    )
    return cp.stdout.decode("utf-8", errors="replace")


def test_python_help_lists_all_supported_verbs(repo_root: Path) -> None:
    """The Python bridge ``help`` output names every supported verb."""
    out = _python_help_output(repo_root)
    # v2.0 lists verbs from `SUPPORTED_VERBS`; older v1.1 used a slightly different
    # set of friendly aliases (e.g., "reqs" -> "analyze-requirements"). We assert
    # the canonical FR-1 list is present.
    missing = [v for v in SUPPORTED_VERBS if v not in out]
    assert not missing, (
        f"Python help is missing canonical verbs: {missing!r}\n"
        f"Help output was:\n{out}"
    )


@require_powershell
def test_ps_help_includes_canonical_verbs(repo_root: Path) -> None:
    """v1.1 PS ``help`` mentions a recognizable subset of the canonical verb set.

    v1.1 used some friendly aliases ("reqs" for analyze-requirements, "design"
    for produce-tech-design, etc.); the test asserts a representative subset
    that v1.1 verbatim mentioned.
    """
    script = repo_root / ".kiro" / "scripts" / "dlc-bridge.ps1"
    cp = run_powershell(["-File", str(script), "help"])
    out = cp.stdout
    # Verbs that v1.1 lists verbatim (cross-checked against dlc-bridge.ps1).
    v1_1_verbs = [
        "reverse-engineer-kb",
        "kb-gap-analysis",
        "map-codebase",
        "babysit-pr",
        "hotfix",
        "review",
        "stabilize",
        "discover",
        "design",
        "plan",
    ]
    missing = [v for v in v1_1_verbs if v not in out]
    assert not missing, (
        f"v1.1 PS help missing expected verbs: {missing!r}\n"
        f"Help output was:\n{out}"
    )
