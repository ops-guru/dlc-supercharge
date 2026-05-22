"""FR-19 parity gate — FR-12 state.md transitions.

Cross-language tests that compare the Python ``state.py`` output against
v1.1 ``state-update.ps1`` output on canonical fixtures. Both implementations
are driven from the same input state.md, the same template, and the same
operation. The resulting state.md files are compared after masking
non-deterministic fields (timestamps).

When ``powershell.exe``/``pwsh`` is unavailable (Linux/macOS CI legs), these
tests are skipped via :data:`tests.parity.conftest.require_powershell`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from dlc_bridge.util.state import (
    advance_phase,
    incr_escalation,
    init_state,
    mark_skipped,
    record_pr,
)

from .conftest import normalize_eol, require_powershell, run_powershell


pytestmark = pytest.mark.parity


# Mask ISO-8601 UTC timestamps so timestamp drift between the two runs
# doesn't false-positive the comparison.
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_TIMESTAMP_PLACEHOLDER = "<TS>"


def _strip_bom(text: str) -> str:
    """Strip a leading UTF-8 BOM (``\\ufeff``).

    v1.1 PowerShell 5.1 ``Set-Content -Encoding utf8`` writes a BOM; this is a
    documented v1.1 bug that v2.0 explicitly fixes (per NFR-3). The parity
    comparison strips the BOM before comparing — divergence here is the
    INTENTIONAL behavioral fix, not a regression.
    """
    return text.lstrip("﻿")


def _mask_timestamps(text: str) -> str:
    return _ISO_RE.sub(_TIMESTAMP_PLACEHOLDER, normalize_eol(_strip_bom(text)))


def _bootstrap_state_dir(tmp_path: Path, repo_root: Path) -> Path:
    """Set up a slug-rooted directory with the v1.1 template available.

    Returns the slug-root directory (NOT the template path). Both
    implementations expect to find the template at
    ``<slug-root>/.kiro/powers/dlc-supercharge/templates/state.md.template``.
    """
    slug_dir = tmp_path / ".dlc" / "test-slug"
    slug_dir.mkdir(parents=True)
    tmpl_src = repo_root / ".kiro" / "powers" / "dlc-supercharge" / "templates" / "state.md.template"
    tmpl_dst = tmp_path / ".kiro" / "powers" / "dlc-supercharge" / "templates" / "state.md.template"
    tmpl_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tmpl_src, tmpl_dst)
    return slug_dir


def _ps_init(slug_dir: Path, repo_root: Path) -> None:
    """Drive v1.1's ``Update-StateMd -Operation init`` on ``slug_dir``."""
    script = repo_root / ".kiro" / "scripts" / "state-update.ps1"
    cmd = (
        f". '{script.as_posix()}'; "
        f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation init "
        f"-Slug 'test-slug' -Branch 'feature/parity' -BaseBranch 'main' -Mode 'confident'"
    )
    run_powershell(["-Command", cmd])


def _ps_advance(slug_dir: Path, repo_root: Path, next_phase: str, notes: str | None = None) -> None:
    script = repo_root / ".kiro" / "scripts" / "state-update.ps1"
    notes_arg = f" -Notes '{notes}'" if notes else ""
    cmd = (
        f". '{script.as_posix()}'; "
        f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation advance "
        f"-NextPhase '{next_phase}'{notes_arg}"
    )
    run_powershell(["-Command", cmd])


def _ps_mark_skipped(slug_dir: Path, repo_root: Path, phase: str, rationale: str) -> None:
    script = repo_root / ".kiro" / "scripts" / "state-update.ps1"
    cmd = (
        f". '{script.as_posix()}'; "
        f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation mark_skipped "
        f"-Phase '{phase}' -Rationale '{rationale}'"
    )
    run_powershell(["-Command", cmd])


def _ps_record_pr(slug_dir: Path, repo_root: Path, pr: int) -> None:
    script = repo_root / ".kiro" / "scripts" / "state-update.ps1"
    cmd = (
        f". '{script.as_posix()}'; "
        f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation record_pr "
        f"-PrNumber {pr}"
    )
    run_powershell(["-Command", cmd])


def _ps_incr_escalation(slug_dir: Path, repo_root: Path) -> None:
    script = repo_root / ".kiro" / "scripts" / "state-update.ps1"
    cmd = (
        f". '{script.as_posix()}'; "
        f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation incr_escalation"
    )
    run_powershell(["-Command", cmd])


@require_powershell
class TestStateParityCrossLanguage:
    """Each test drives an identical operation on two separate workspaces
    (one Python, one PS) and compares the resulting state.md byte-for-byte
    after timestamp masking."""

    def test_init_produces_byte_equal_state(self, tmp_path: Path, repo_root: Path) -> None:
        # Python side
        py_root = tmp_path / "py"
        py_root.mkdir()
        py_slug = _bootstrap_state_dir(py_root, repo_root)
        init_state(
            py_slug / "state.md",
            slug="test-slug",
            branch="feature/parity",
            base_branch="main",
            interaction_mode="confident",
        )

        # PowerShell side
        ps_root = tmp_path / "ps"
        ps_root.mkdir()
        ps_slug = _bootstrap_state_dir(ps_root, repo_root)
        _ps_init(ps_slug, repo_root)

        py_out = _mask_timestamps((py_slug / "state.md").read_text(encoding="utf-8"))
        ps_out = _mask_timestamps((ps_slug / "state.md").read_text(encoding="utf-8"))
        assert py_out == ps_out, (
            "state.md from init operation diverges between Python and v1.1 PS"
        )

    def test_advance_produces_byte_equal_state(self, tmp_path: Path, repo_root: Path) -> None:
        # Set up both sides with init first
        py_root = tmp_path / "py"
        py_root.mkdir()
        py_slug = _bootstrap_state_dir(py_root, repo_root)
        init_state(
            py_slug / "state.md",
            slug="test-slug",
            branch="feature/parity",
            base_branch="main",
            interaction_mode="confident",
        )
        advance_phase(py_slug / "state.md", next_phase="2a")

        ps_root = tmp_path / "ps"
        ps_root.mkdir()
        ps_slug = _bootstrap_state_dir(ps_root, repo_root)
        _ps_init(ps_slug, repo_root)
        _ps_advance(ps_slug, repo_root, "2a")

        py_out = _mask_timestamps((py_slug / "state.md").read_text(encoding="utf-8"))
        ps_out = _mask_timestamps((ps_slug / "state.md").read_text(encoding="utf-8"))
        assert py_out == ps_out

    def test_mark_skipped_produces_byte_equal_state(
        self, tmp_path: Path, repo_root: Path
    ) -> None:
        py_root = tmp_path / "py"
        py_root.mkdir()
        py_slug = _bootstrap_state_dir(py_root, repo_root)
        init_state(
            py_slug / "state.md",
            slug="test-slug",
            branch="feature/parity",
            base_branch="main",
            interaction_mode="confident",
        )
        mark_skipped(py_slug / "state.md", phase="2b", reason="per user request")

        ps_root = tmp_path / "ps"
        ps_root.mkdir()
        ps_slug = _bootstrap_state_dir(ps_root, repo_root)
        _ps_init(ps_slug, repo_root)
        _ps_mark_skipped(ps_slug, repo_root, "2b", "per user request")

        py_out = _mask_timestamps((py_slug / "state.md").read_text(encoding="utf-8"))
        ps_out = _mask_timestamps((ps_slug / "state.md").read_text(encoding="utf-8"))
        assert py_out == ps_out

    def test_record_pr_produces_byte_equal_state(
        self, tmp_path: Path, repo_root: Path
    ) -> None:
        py_root = tmp_path / "py"
        py_root.mkdir()
        py_slug = _bootstrap_state_dir(py_root, repo_root)
        init_state(
            py_slug / "state.md",
            slug="test-slug",
            branch="feature/parity",
            base_branch="main",
            interaction_mode="confident",
        )
        record_pr(py_slug / "state.md", pr_number=42)

        ps_root = tmp_path / "ps"
        ps_root.mkdir()
        ps_slug = _bootstrap_state_dir(ps_root, repo_root)
        _ps_init(ps_slug, repo_root)
        _ps_record_pr(ps_slug, repo_root, 42)

        py_out = _mask_timestamps((py_slug / "state.md").read_text(encoding="utf-8"))
        ps_out = _mask_timestamps((ps_slug / "state.md").read_text(encoding="utf-8"))
        assert py_out == ps_out

    def test_incr_escalation_produces_byte_equal_state(
        self, tmp_path: Path, repo_root: Path
    ) -> None:
        py_root = tmp_path / "py"
        py_root.mkdir()
        py_slug = _bootstrap_state_dir(py_root, repo_root)
        init_state(
            py_slug / "state.md",
            slug="test-slug",
            branch="feature/parity",
            base_branch="main",
            interaction_mode="confident",
        )
        incr_escalation(py_slug / "state.md")

        ps_root = tmp_path / "ps"
        ps_root.mkdir()
        ps_slug = _bootstrap_state_dir(ps_root, repo_root)
        _ps_init(ps_slug, repo_root)
        _ps_incr_escalation(ps_slug, repo_root)

        py_out = _mask_timestamps((py_slug / "state.md").read_text(encoding="utf-8"))
        ps_out = _mask_timestamps((ps_slug / "state.md").read_text(encoding="utf-8"))
        assert py_out == ps_out


class TestStateRoundTrip:
    """OS-agnostic regression tests for state.md operations — these run on every
    CI leg (Windows/macOS/Linux) without requiring a PowerShell host."""

    def test_round_trip_init_advance_skip(self, tmp_path: Path, repo_root: Path) -> None:
        """Composing init → advance → mark_skipped produces a deterministic shape."""
        slug = _bootstrap_state_dir(tmp_path, repo_root)
        init_state(slug / "state.md", slug="rt", branch="feat", base_branch="main")
        advance_phase(slug / "state.md", next_phase="2a")
        mark_skipped(slug / "state.md", phase="2b", reason="N/A")

        out = (slug / "state.md").read_text(encoding="utf-8")
        out = _mask_timestamps(out)

        # Anchor invariants — header, current phase, status row shape, decision log
        assert "**Current phase:** 2a" in out
        assert "| 2b | skipped | <TS> | <TS> | N/A |" in out
        assert "Phase Status" in out
        assert "Decisions Log" in out
        assert "## Escalation counter:" in out
