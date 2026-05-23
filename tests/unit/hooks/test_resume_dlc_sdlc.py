"""Tests for :mod:`dlc_bridge.hooks.resume_dlc_sdlc`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import resume_dlc_sdlc
from ._helpers import make_state_md


def test_no_dlc_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = resume_dlc_sdlc.main(["--dlc-root", str(tmp_path / "missing")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NO_STATES=" in out
    assert "HOOK_DONE" in out


def test_no_slug_lists_available(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    make_state_md(root / "foo", current_phase="2c")
    make_state_md(root / "bar", current_phase="4")
    rc = resume_dlc_sdlc.main(["--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "AVAILABLE=foo::2c" in out
    assert "AVAILABLE=bar::4" in out
    assert "NEXT=" in out
    assert "HOOK_DONE" in out


def test_with_slug_emits_briefing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    make_state_md(
        root / "myslug",
        current_phase="3",
        pr=42,
        branch="feat/x",
        decisions=[
            "- [2026-05-22T10:00:00Z] Decision A",
            "- [2026-05-22T11:00:00Z] Decision B",
        ],
    )
    rc = resume_dlc_sdlc.main(["--slug", "myslug", "--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SLUG=myslug" in out
    assert "CURRENT_PHASE=3" in out
    assert "PR=42" in out
    assert "BRANCH=feat/x" in out
    assert "RECENT_DECISION=2026-05-22T10:00:00Z Decision A" in out
    assert "NEXT_ACTION=Save tasks.md" in out
    assert "HOOK_DONE" in out


def test_missing_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    root.mkdir()
    rc = resume_dlc_sdlc.main(["--slug", "nope", "--dlc-root", str(root)])
    assert rc == 1
    assert "ERROR=no state.md" in capsys.readouterr().out


@pytest.mark.parametrize(
    "phase,expected_substring",
    [
        ("1", "Re-save requirements.md"),
        ("2a", "redrive Phase 2"),
        ("2b", "Re-fire on-requirements-saved"),
        ("2c", "Save design.md"),
        ("3", "Save tasks.md"),
        ("4", "Re-fire on-pr-opened"),
        ("5", "Phase 5"),
        ("6", "manual staging verification"),
        ("7", "Run on-pr-merged"),
        ("8", "Run on-pr-merged"),
        ("unknown", "Phase not recognised"),
    ],
)
def test_phase_routing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    phase: str,
    expected_substring: str,
) -> None:
    root = tmp_path / ".dlc"
    make_state_md(root / "s", current_phase=phase)
    rc = resume_dlc_sdlc.main(["--slug", "s", "--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    next_lines = [
        ln for ln in out.splitlines() if ln.startswith("NEXT_ACTION=")
    ]
    assert any(expected_substring in ln for ln in next_lines), (
        f"phase {phase!r}: expected substring {expected_substring!r} in {next_lines}"
    )


def test_phase_4_with_pr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    make_state_md(root / "s", current_phase="4", pr=99)
    rc = resume_dlc_sdlc.main(["--slug", "s", "--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PR #99" in out
