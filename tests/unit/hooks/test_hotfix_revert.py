"""Tests for :mod:`dlc_bridge.hooks.hotfix_revert`."""

from __future__ import annotations

import pytest

from dlc_bridge.hooks import hotfix_revert
from .conftest import BridgeInvocationRecorder


def test_happy_path(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout="revert PR created at https://github.com/example/repo/pull/9999\n",
    )
    rc = hotfix_revert.main(["--pr", "42"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PR=42" in out
    assert "BRIDGE_STARTING=hotfix" in out
    assert "MODE=revert" in out
    assert "BRIDGE_EXIT=0" in out
    assert "BRIDGE_OUTPUT=" in out
    assert "https://github.com/example/repo/pull/9999" in out
    assert "HOOK_DONE" in out
    assert invoke_bridge_stub.calls[0]["args"] == ["--pr", "42", "--mode", "revert"]


def test_multiline_output_flattened(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=0, stdout="line1\nline2\nline3\n")
    rc = hotfix_revert.main(["--pr", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    bridge_lines = [ln for ln in out.splitlines() if ln.startswith("BRIDGE_OUTPUT=")]
    assert len(bridge_lines) == 1
    assert " | " in bridge_lines[0]


def test_bridge_failure(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke_bridge_stub.set_next(returncode=4, stdout="")
    rc = hotfix_revert.main(["--pr", "1"])
    out = capsys.readouterr().out
    assert rc == 4
    assert "BRIDGE_FAILED" in out
    assert "HOOK_DONE" not in out


def test_dry_run(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = hotfix_revert.main(["--pr", "10", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert invoke_bridge_stub.calls[0]["dry_run"] is True
    assert "HOOK_DONE" in out


def test_bridge_cached_passthrough(
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the bridge short-circuits on cache hit, the hook re-emits
    ``BRIDGE_CACHED=<path>`` from the subprocess stdout.

    Discovered during v2.0.0 SMOKE-TEST-CHECKLIST section 5 on 2026-05-25.
    """
    invoke_bridge_stub.set_next(
        returncode=0, stdout="BRIDGE_CACHED=.dlc/pr-42/hotfix-report.md\n"
    )
    rc = hotfix_revert.main(["--pr", "42"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/pr-42/hotfix-report.md" in out
