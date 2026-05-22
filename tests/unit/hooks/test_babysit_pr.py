"""Tests for :mod:`dlc_bridge.hooks.babysit_pr`."""

from __future__ import annotations

import pytest

from dlc_bridge.hooks import babysit_pr
from .conftest import BridgeInvocationRecorder


def test_happy_path(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout='{"jobId":"abc-123","log":"C:/logs/x.log"}',
    )
    rc = babysit_pr.main(["--pr", "42"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PR=42" in out
    assert "MODE=default" in out
    assert "BRIDGE_STARTING=babysit-pr" in out
    assert "BRIDGE_EXIT=0" in out
    assert "JOB_ID=abc-123" in out
    assert "LOG=C:/logs/x.log" in out
    assert "HOOK_DONE" in out

    assert len(invoke_bridge_stub.calls) == 1
    call = invoke_bridge_stub.calls[0]
    assert call["verb"] == "babysit-pr"
    assert call["args"] == ["--pr", "42", "--mode", "default"]


def test_aggressive_mode(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = babysit_pr.main(["--pr", "7", "--mode", "aggressive"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "MODE=aggressive" in out
    assert invoke_bridge_stub.calls[0]["args"] == ["--pr", "7", "--mode", "aggressive"]


def test_bridge_failure(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=5, stdout="")
    rc = babysit_pr.main(["--pr", "42"])
    out = capsys.readouterr().out
    assert rc == 5
    assert "BRIDGE_EXIT=5" in out
    assert "BRIDGE_FAILED" in out
    assert "HOOK_DONE" not in out


def test_dry_run(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = babysit_pr.main(["--pr", "42", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert invoke_bridge_stub.calls[0]["dry_run"] is True
    assert "HOOK_DONE" in out


def test_missing_pr_argument() -> None:
    with pytest.raises(SystemExit):
        babysit_pr.main([])
