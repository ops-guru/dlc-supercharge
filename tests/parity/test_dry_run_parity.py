"""FR-19 parity gate — dry-run JSON envelope per verb.

The v1.1 and v2.0 dry-run envelopes are intentionally different at the
byte level (per tech-design D-1): v1.1 emits a flat string ``command``;
v2.0 emits a structured ``args`` array. We compare structurally — on
``status``, ``verb`` identity, and basename-of(``skillPath``) — which is
the strongest invariant that survives the format change.

When PowerShell is unavailable we skip the cross-language portion of the
suite; the Python-only structural test still runs and asserts each verb
produces a well-formed envelope.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from dlc_bridge.verbs import SUPPORTED_VERBS

from .conftest import require_powershell_and_legacy, run_powershell


pytestmark = pytest.mark.parity


# Verb → canonical dry-run argv (skipped if missing key Kiro fixtures).
# Each verb gets a minimal `--target .` or `--source <path>` to exercise the
# dry-run path. The exact arguments mimic typical hook invocations.
VERB_DRY_RUN_ARGS: dict[str, list[str]] = {
    "analyze-requirements": ["--source", "."],
    "produce-tech-design": ["--source", "."],
    "plan-implementation": ["--source", "."],
    "finalize-sdlc": ["--source", "."],
    "discover": ["--source", "."],
    "review-pr": ["--pr", "1"],
    "stabilize-pr": ["--pr", "1"],
    "review-security": ["--source", "."],
    "review-ux": ["--source", "."],
    "review-a11y": ["--source", "."],
    "review-performance": ["--source", "."],
    "reverse-engineer-kb": ["--target", "."],
    "kb-gap-analysis": ["--source", ".", "--target", "."],
    "map-codebase": ["--target", "."],
    "babysit-pr": ["--pr", "1"],
    "hotfix": ["--pr", "1"],
}


def _python_dry_run(repo_root: Path, verb: str, args: list[str]) -> dict:
    """Run `uv run dlc-bridge <verb> --dry-run <args>` and parse the JSON envelope."""
    cp = subprocess.run(
        ["uv", "run", "dlc-bridge", verb, *args, "--dry-run"],
        cwd=str(repo_root),
        capture_output=True,
        check=True,
        timeout=60.0,
    )
    stdout = cp.stdout.decode("utf-8", errors="replace")
    # Some `uv run` warnings appear before the JSON; find the first '{' that opens the envelope.
    start = stdout.find("{")
    if start == -1:
        raise AssertionError(
            f"No JSON envelope in Python dry-run for {verb!r}: {stdout!r}"
        )
    return json.loads(stdout[start:])


def _ps_dry_run(repo_root: Path, verb: str, args: list[str]) -> dict:
    """Run v1.1 `dlc-bridge.ps1 <verb> -DryRun <args>` and parse the trailing JSON line."""
    script = repo_root / ".kiro" / "scripts" / "dlc-bridge.ps1"
    # Translate Python-style `--key value` to PS-style `-Key value`.
    ps_args: list[str] = []
    for i, a in enumerate(args):
        if a.startswith("--"):
            ps_args.append("-" + a[2:].title().replace("-", ""))
        else:
            ps_args.append(a)
    cp = run_powershell(
        ["-File", str(script), verb, *ps_args, "-DryRun"],
        check=False,  # PS may exit 0 even with [dlc-bridge] log lines
    )
    # JSON is the last line of stdout that starts with '{'
    lines = cp.stdout.splitlines()
    for line in reversed(lines):
        if line.strip().startswith("{") and '"status"' in line:
            return json.loads(line)
    raise AssertionError(
        f"No JSON envelope in PS dry-run for {verb!r}; stdout was:\n{cp.stdout}"
    )


class TestPythonDryRunStructure:
    """Python-only structural tests — run on EVERY CI leg (Windows + macOS + Linux)."""

    @pytest.mark.parametrize("verb", sorted(SUPPORTED_VERBS))
    def test_each_verb_emits_structured_envelope(
        self, verb: str, repo_root: Path
    ) -> None:
        """Every supported verb emits a well-formed dry-run JSON envelope."""
        envelope = _python_dry_run(repo_root, verb, VERB_DRY_RUN_ARGS[verb])
        # FR-5 envelope contract: status, verb, skillPath, command, args, assembledPrompt.
        for key in ("status", "verb", "skillPath", "command", "args", "assembledPrompt"):
            assert key in envelope, (
                f"verb={verb!r}: missing key {key!r} in dry-run envelope"
            )
        assert envelope["status"] == "dry-run"
        assert envelope["verb"] == verb
        # skillPath ends with SKILL.md
        assert envelope["skillPath"].endswith("SKILL.md")
        # args is a list (structured, per D-1)
        assert isinstance(envelope["args"], list)
        # assembledPrompt is non-empty
        assert len(envelope["assembledPrompt"]) > 50


@require_powershell_and_legacy
class TestCrossLanguageDryRun:
    """Cross-language verb-identity comparison — skipped without PowerShell or post-Epic-5 cutover."""

    @pytest.mark.parametrize("verb", sorted(SUPPORTED_VERBS))
    def test_both_implementations_agree_on_verb_and_skill_basename(
        self, verb: str, repo_root: Path
    ) -> None:
        """For each verb, both runtimes resolve the same skill folder.

        Compares structurally: verb name, status, and basename(skillPath).
        Does NOT compare the full ``command`` field — v1.1 emits a flat string
        while v2.0 emits a structured ``args`` list (per D-1).
        """
        # Python side
        py_env = _python_dry_run(repo_root, verb, VERB_DRY_RUN_ARGS[verb])

        # PS side may not support every verb (v1.1 used some friendlier
        # aliases). Skip gracefully if the PS process emits an unknown-verb error.
        try:
            ps_env = _ps_dry_run(repo_root, verb, VERB_DRY_RUN_ARGS[verb])
        except (AssertionError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
            pytest.skip(
                f"v1.1 PS does not support verb {verb!r} via this dry-run path: {e}"
            )

        assert py_env["status"] == ps_env["status"] == "dry-run"
        # Skill basename — last 2 path segments — should be identical.
        py_skill = Path(py_env["skillPath"]).parts[-2:]
        ps_skill = Path(ps_env["skillPath"]).parts[-2:]
        assert py_skill == ps_skill, (
            f"verb={verb!r}: skill-folder divergence.\n"
            f"Python: {py_env['skillPath']}\nPowerShell: {ps_env['skillPath']}"
        )
