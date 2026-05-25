"""Tests for :mod:`dlc_bridge.hooks.on_pr_merged`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.hooks import on_pr_merged
from .conftest import BridgeInvocationRecorder
from ._helpers import make_state_md


@pytest.fixture(autouse=True)
def patch_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``shutil.which('gh')`` return a fake path by default."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)


def _patch_gh_view(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, payload: dict
) -> None:
    def fake_gh(pr):
        return (exit_code, json.dumps(payload), "")
    monkeypatch.setattr(on_pr_merged, "_run_gh_pr_view", fake_gh)


def test_gh_not_on_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    rc = on_pr_merged.main(["--pr", "1"])
    assert rc == 2
    assert "ERROR=gh CLI not on PATH" in capsys.readouterr().out


def test_pr_not_merged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _patch_gh_view(monkeypatch, 0, {"state": "OPEN", "mergedAt": None})
    rc = on_pr_merged.main(["--pr", "1", "--dlc-root", str(tmp_path / ".dlc")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PR_STATE=OPEN" in out
    assert "NOT_MERGED=" in out
    assert "HOOK_DONE" in out


def test_gh_view_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_gh(pr):
        return (1, "", "PR not found")
    monkeypatch.setattr(on_pr_merged, "_run_gh_pr_view", fake_gh)
    rc = on_pr_merged.main(["--pr", "999"])
    assert rc == 1
    assert "ERROR=gh pr view failed" in capsys.readouterr().out


def test_no_slug_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_gh_view(monkeypatch, 0, {"state": "MERGED", "mergedAt": "now"})
    root = tmp_path / ".dlc"
    root.mkdir()
    rc = on_pr_merged.main(["--pr", "42", "--dlc-root", str(root)])
    assert rc == 1
    assert "ERROR=no .dlc/*/state.md found" in capsys.readouterr().out


def test_multiple_slug_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_gh_view(monkeypatch, 0, {"state": "MERGED", "mergedAt": "now"})
    root = tmp_path / ".dlc"
    make_state_md(root / "foo", pr=42)
    make_state_md(root / "bar", pr=42)
    rc = on_pr_merged.main(["--pr", "42", "--dlc-root", str(root)])
    assert rc == 1
    assert "ERROR=multiple slugs match" in capsys.readouterr().out


def test_happy_path(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_gh_view(
        monkeypatch, 0, {"state": "MERGED", "mergedAt": "2026-05-22T10:00:00Z"}
    )
    root = tmp_path / ".dlc"
    state_path = make_state_md(root / "myslug", pr=42)
    # Add 'completed' status for finalize() to find phase 7 / 8 rows.
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\n| 7 | pending |  |  |  |\n| 8 | pending |  |  |  |\n",
        encoding="utf-8",
    )
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_pr_merged.main(["--pr", "42", "--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PR_STATE=MERGED" in out
    assert "PR_MERGED_AT=2026-05-22T10:00:00Z" in out
    assert "SLUG_DERIVED=myslug" in out
    assert "BRIDGE_STARTING=finalize-sdlc" in out
    assert "STATE_FINALIZED=" in out
    assert "HOOK_DONE" in out
    assert invoke_bridge_stub.calls[0]["verb"] == "finalize-sdlc"


def test_delete_state(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_gh_view(monkeypatch, 0, {"state": "MERGED", "mergedAt": "now"})
    root = tmp_path / ".dlc"
    state_path = make_state_md(root / "myslug", pr=99)
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\n| 7 | pending |  |  |  |\n| 8 | pending |  |  |  |\n",
        encoding="utf-8",
    )
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_pr_merged.main(
        ["--pr", "99", "--dlc-root", str(root), "--delete-state"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STATE_DELETED=" in out
    assert not state_path.exists()


def test_dry_run(
    invoke_bridge_stub: BridgeInvocationRecorder,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / ".dlc"
    state_path = make_state_md(root / "myslug", pr=42)
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\n| 7 | pending |  |  |  |\n| 8 | pending |  |  |  |\n",
        encoding="utf-8",
    )
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_pr_merged.main(
        ["--pr", "42", "--dry-run", "--dlc-root", str(root)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PR_STATE=MERGED" in out
    assert "HOOK_DONE" in out


def test_bridge_cached_passthrough(
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the finalize-sdlc bridge short-circuits on cache hit, the hook
    re-emits ``BRIDGE_CACHED=<path>`` from the subprocess stdout.

    Discovered during v2.0.0 SMOKE-TEST-CHECKLIST section 5 on 2026-05-25.
    """
    _patch_gh_view(monkeypatch, 0, {"state": "MERGED", "mergedAt": "now"})
    root = tmp_path / ".dlc"
    state_path = make_state_md(root / "myslug", pr=42)
    state_path.write_text(
        state_path.read_text(encoding="utf-8")
        + "\n| 7 | pending |  |  |  |\n| 8 | pending |  |  |  |\n",
        encoding="utf-8",
    )
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout="BRIDGE_CACHED=.dlc/myslug/analysis_output/finalization-report.md\n",
    )
    rc = on_pr_merged.main(["--pr", "42", "--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/myslug/analysis_output/finalization-report.md" in out
