"""Tests for :mod:`dlc_bridge.hooks.on_pr_opened`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import on_pr_opened
from .conftest import BridgeInvocationRecorder
from ._helpers import make_state_md


def test_no_slug_no_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(on_pr_opened, "_current_git_branch", lambda: None)
    rc = on_pr_opened.main(
        ["--pr", "1", "--dlc-root", str(tmp_path / ".dlc")]
    )
    assert rc == 1
    assert "ERROR=could not derive slug" in capsys.readouterr().out


def test_init_happy_path(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Pre-populate the state via the v1.1 template (state_mod will init).
    # We pass --slug explicitly so no branch lookup is needed.
    root = tmp_path / ".dlc"
    root.mkdir()
    invoke_bridge_stub.set_next(
        returncode=0, stdout='{"jobId":"j99","log":"x.log"}'
    )

    # Stub out the state_mod functions used during init since we don't have a
    # real template path. The init code calls init_state -> advance_phase ->
    # record_pr. We mock all of them to no-ops.
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "init_state", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "record_pr", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)

    rc = on_pr_opened.main(
        ["--pr", "42", "--slug", "myslug", "--dlc-root", str(root)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STAGE=init" in out
    assert "PR=42" in out
    assert "MODE=default" in out
    assert "SLUG=myslug" in out
    assert "STATE_INITIALIZED=" in out
    assert "PR_RECORDED=#42" in out
    assert "STATE_ADVANCED=4" in out
    assert "BRIDGE_STARTING=babysit-pr" in out
    assert "BABYSIT_JOB=j99" in out
    assert "HOOK_INIT_DONE" in out


def test_finalize_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / ".dlc"
    make_state_md(root / "myslug")
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)

    rc = on_pr_opened.main(
        [
            "--pr", "42", "--slug", "myslug", "--stage", "finalize",
            "--job-id", "j99", "--dlc-root", str(root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STATE_ADVANCED=5" in out
    assert "BABYSIT_JOB=j99" in out
    assert "HOOK_FINALIZE_DONE" in out


def test_init_bridge_failure(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / ".dlc"
    root.mkdir()
    invoke_bridge_stub.set_next(returncode=5, stdout="")
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "init_state", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "record_pr", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)
    rc = on_pr_opened.main(
        ["--pr", "1", "--slug", "s", "--dlc-root", str(root)]
    )
    assert rc == 5
    assert "BRIDGE_FAILED" in capsys.readouterr().out


def test_slug_resolved_from_branch(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(on_pr_opened, "_current_git_branch", lambda: "feat/bar")
    root = tmp_path / ".dlc"
    make_state_md(root / "bar", branch="feat/bar")
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "record_pr", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)
    rc = on_pr_opened.main(["--pr", "1", "--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRANCH=feat/bar" in out
    assert "SLUG=bar" in out


def test_bridge_cached_passthrough(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the bridge short-circuits on cache hit, the hook re-emits
    ``BRIDGE_CACHED=<path>`` from the subprocess stdout.

    Discovered during v2.0.0 SMOKE-TEST-CHECKLIST section 5 on 2026-05-25.
    """
    root = tmp_path / ".dlc"
    root.mkdir()
    invoke_bridge_stub.set_next(
        returncode=0, stdout="BRIDGE_CACHED=.dlc/myslug/babysit-report.md\n"
    )
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "init_state", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "record_pr", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)
    rc = on_pr_opened.main(
        ["--pr", "42", "--slug", "myslug", "--dlc-root", str(root)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/myslug/babysit-report.md" in out
