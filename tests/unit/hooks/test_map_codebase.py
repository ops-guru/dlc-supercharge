"""Tests for :mod:`dlc_bridge.hooks.map_codebase`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import map_codebase
from .conftest import BridgeInvocationRecorder


def test_happy_path_existing_target(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = map_codebase.main(["--target", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"TARGET={tmp_path}" in out
    assert "BRIDGE_STARTING=map-codebase" in out
    assert "BRIDGE_EXIT=0" in out
    assert "HOOK_DONE" in out
    assert invoke_bridge_stub.calls[0]["args"] == ["--target", str(tmp_path)]


def test_warns_on_missing_target(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    missing = tmp_path / "nope"
    rc = map_codebase.main(["--target", str(missing)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARN=target path does not exist" in out


def test_bridge_failure(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=4, stdout="")
    rc = map_codebase.main(["--target", str(tmp_path)])
    assert rc == 4
    assert "BRIDGE_FAILED" in capsys.readouterr().out


def test_map_extraction(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stdout = (
        'STAGE=ready\n'
        '{"outputManifest":[".dlc/maps/auth.map.md",".dlc/maps/billing.map.md"]}\n'
    )
    invoke_bridge_stub.set_next(returncode=0, stdout=stdout)
    rc = map_codebase.main(["--target", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MAP=.dlc/maps/auth.map.md" in out
    assert "MAP=.dlc/maps/billing.map.md" in out


def test_bridge_cached(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(
        returncode=0, stdout="BRIDGE_CACHED=.dlc/maps/cached.map.md\n"
    )
    rc = map_codebase.main(["--target", str(tmp_path)])
    assert rc == 0
    assert "BRIDGE_CACHED=" in capsys.readouterr().out
