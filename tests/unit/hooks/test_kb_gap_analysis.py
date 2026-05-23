"""Tests for :mod:`dlc_bridge.hooks.kb_gap_analysis`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import kb_gap_analysis
from .conftest import BridgeInvocationRecorder


def test_missing_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = kb_gap_analysis.main(
        ["--source", str(tmp_path / "missing.xlsx"), "--kb", str(tmp_path)]
    )
    assert rc == 1
    assert "ERROR=source not found" in capsys.readouterr().out


def test_missing_kb(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "src.xlsx"
    src.touch()
    rc = kb_gap_analysis.main(
        ["--source", str(src), "--kb", str(tmp_path / "missing-kb")]
    )
    assert rc == 1
    assert "ERROR=kb root not found" in capsys.readouterr().out


def test_happy_path(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "src.xlsx"
    src.touch()
    kb = tmp_path / "kb"
    kb.mkdir()
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = kb_gap_analysis.main(["--source", str(src), "--kb", str(kb)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"SOURCE={src}" in out
    assert f"KB={kb}" in out
    assert "MODE=full" in out
    assert "BRIDGE_STARTING=kb-gap-analysis" in out
    assert "BRIDGE_EXIT=0" in out
    assert "HOOK_DONE" in out
    assert invoke_bridge_stub.calls[0]["args"] == [
        "--source", str(src), "--kb", str(kb), "--mode", "full"
    ]


def test_patch_mode(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "src.xlsx"
    src.touch()
    kb = tmp_path / "kb"
    kb.mkdir()
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = kb_gap_analysis.main(
        ["--source", str(src), "--kb", str(kb), "--mode", "patch"]
    )
    assert rc == 0
    assert "MODE=patch" in capsys.readouterr().out


def test_bridge_cached(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "src.xlsx"
    src.touch()
    kb = tmp_path / "kb"
    kb.mkdir()
    invoke_bridge_stub.set_next(
        returncode=0, stdout="BRIDGE_CACHED=.dlc/foo/report.md\n"
    )
    rc = kb_gap_analysis.main(["--source", str(src), "--kb", str(kb)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BRIDGE_CACHED=.dlc/foo/report.md" in out


def test_bridge_failure(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "src.xlsx"
    src.touch()
    kb = tmp_path / "kb"
    kb.mkdir()
    invoke_bridge_stub.set_next(returncode=5, stdout="")
    rc = kb_gap_analysis.main(["--source", str(src), "--kb", str(kb)])
    assert rc == 5
    assert "BRIDGE_FAILED" in capsys.readouterr().out
