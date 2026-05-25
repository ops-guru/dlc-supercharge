"""Tests for :mod:`dlc_bridge.hooks.reverse_engineer_kb`."""

from __future__ import annotations

import pytest

from dlc_bridge.hooks import reverse_engineer_kb
from .conftest import BridgeInvocationRecorder


def test_happy_path(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout='{"jobId":"kb-1","log":"C:/logs/kb.log"}',
    )
    rc = reverse_engineer_kb.main(["--target", "some/path"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TARGET=some/path" in out
    assert "MODE=full" in out
    assert "MAX_FILES=500" in out
    assert "BRIDGE_STARTING=reverse-engineer-kb" in out
    assert "BRIDGE_EXIT=0" in out
    assert "JOB_ID=kb-1" in out
    assert "LOG=C:/logs/kb.log" in out
    assert "HOOK_DONE" in out
    assert invoke_bridge_stub.calls[0]["args"] == [
        "--target", "some/path", "--mode", "full", "--max-files", "500"
    ]


def test_incremental_mode(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = reverse_engineer_kb.main(
        ["--target", "x", "--mode", "incremental", "--max-files", "200"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "MODE=incremental" in out
    assert "MAX_FILES=200" in out


def test_bridge_failure(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=6, stdout="")
    rc = reverse_engineer_kb.main(["--target", "x"])
    assert rc == 6
    assert "BRIDGE_FAILED" in capsys.readouterr().out


def test_bridge_cached_passthrough(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the bridge short-circuits on cache hit, the hook re-emits
    ``BRIDGE_CACHED=<path>`` from the subprocess stdout.

    Discovered during v2.0.0 SMOKE-TEST-CHECKLIST section 5 on 2026-05-25.
    """
    invoke_bridge_stub.set_next(
        returncode=0, stdout="BRIDGE_CACHED=.dlc/kb/architecture.md\n"
    )
    rc = reverse_engineer_kb.main(["--target", "some/path"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/kb/architecture.md" in out
