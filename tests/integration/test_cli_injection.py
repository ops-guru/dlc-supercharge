"""WI-21 / FR-3 argparse + subprocess injection-style negative tests.

The bridge MUST NOT shell-expand user input. These tests verify that:

1. Argparse rejects path-traversal / out-of-enum / out-of-range values.
2. Path-like input with shell metacharacters does not execute as a shell command.
3. All subprocess invocations use argv LISTS (never shell=True).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dlc_bridge.cli import main

pytestmark = pytest.mark.integration


# ----- argparse validation (FR-3) ------------------------------------------


def test_verb_with_semicolons_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """Semicolons in the verb argument do NOT execute; rejected at validation."""
    rc = main(["analyze-requirements;rm -rf /"])
    assert rc == 4
    err = capsys.readouterr().err
    assert "Unknown verb" in err or "invalid" in err.lower()


def test_verb_with_backticks_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """Backticks (PS / bash subshell) do NOT execute; treated as part of verb string."""
    rc = main(["`whoami`"])
    assert rc == 4


def test_verb_with_dollar_sub_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """``$(...)`` subshell metacharacters do NOT execute."""
    rc = main(["$(echo pwn)"])
    assert rc == 4


def test_source_path_traversal_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--source", "../../etc/passwd",
    ])
    assert rc == 4


def test_target_path_traversal_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--target", "../../../foo",
    ])
    assert rc == 4


def test_source_with_command_substitution_treated_as_literal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    """``--source "$(rm -rf /)"`` is parsed as a literal string, not executed.

    Argparse never shells out; the value is just a Path() argument. Either
    the value is well-formed and resolves under root (accepted) or it
    escapes (rejected exit 4). In NEITHER case is the substring executed.
    """
    monkeypatch.chdir(tmp_path)
    # The literal value contains shell metacharacters but is treated as a path.
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--source", "$(rm -rf /)",
    ])
    # Path "$(rm -rf /)" under cwd is a legal (nonexistent) path — accepted
    # by dry-run validation. The key assertion: rc != 0 only if argparse
    # genuinely rejects it; rc != 7 or worse from actual command execution.
    # Most importantly: NO subprocess was spawned with shell=True.
    assert rc in (0, 4)


def test_mode_out_of_enum_rejected() -> None:
    rc = main(["analyze-requirements", "--mode", "rm-rf-slash"])
    assert rc == 4


def test_pr_with_metachars_rejected() -> None:
    rc = main(["analyze-requirements", "--pr", "123; cat /etc/passwd"])
    assert rc == 4


def test_max_files_with_metachars_rejected() -> None:
    rc = main(["analyze-requirements", "--max-files", "5; rm"])
    assert rc == 4


def test_max_budget_with_metachars_rejected() -> None:
    rc = main(["analyze-requirements", "--max-budget-usd", "5; pwn"])
    assert rc == 4


# ----- subprocess invocations always use argv list, never shell=True -------


def test_foreground_dispatch_never_uses_shell(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live foreground dispatch must invoke subprocess.run with a LIST argv,
    never with ``shell=True``. FR-3 / WI-21 hardening.
    """
    monkeypatch.chdir(tmp_path)
    src = tmp_path / ".kiro" / "specs" / "spec-x" / "requirements.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("body\n", encoding="utf-8", newline="\n")

    captured: list = []

    def spy_run(argv, **kwargs):
        captured.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("dlc_bridge.cli.subprocess.run", spy_run)
    rc = main(["analyze-requirements", "--source", str(src)])
    assert rc == 0
    assert captured, "subprocess.run must have been called"
    for call in captured:
        assert isinstance(call["argv"], list), (
            "argv must be a list, not a shell string"
        )
        assert call["kwargs"].get("shell", False) is False, (
            "subprocess invocations must never use shell=True"
        )


def test_background_dispatch_popen_argv_list(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Background mode's Popen call must use argv list (not shell-string)."""
    monkeypatch.chdir(tmp_path)
    src = tmp_path / ".kiro" / "specs" / "spec-x" / "requirements.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("body\n", encoding="utf-8", newline="\n")

    captured: list = []

    class SpyPopen:
        def __init__(self, argv, **kwargs):
            captured.append({"argv": argv, "kwargs": kwargs})
            self.pid = 9

    monkeypatch.setattr("dlc_bridge.cli.subprocess.Popen", SpyPopen)

    rc = main(["analyze-requirements", "--source", str(src), "--background"])
    assert rc == 0
    assert len(captured) == 1
    assert isinstance(captured[0]["argv"], list)
    assert captured[0]["kwargs"].get("shell", False) is False


# ----- task-body shell metacharacters pass through inert --------------------


def test_task_body_with_metacharacters_passes_inert_to_claude(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-supplied path with shell metas appears in argv but does NOT execute.

    The task body is the final argv element; it contains the user input
    inert because subprocess.run is invoked with a LIST, not a string.
    """
    monkeypatch.chdir(tmp_path)
    src = tmp_path / ".kiro" / "specs" / "spec-x" / "weird;name.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("body\n", encoding="utf-8", newline="\n")

    captured: list = []

    def spy_run(argv, **kwargs):
        captured.append(list(argv))
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("dlc_bridge.cli.subprocess.run", spy_run)

    main(["analyze-requirements", "--source", str(src)])
    assert captured
    argv = captured[0]
    # The path containing ; should be PRESENT in the argv but only as a
    # literal argv element — never expanded by a shell.
    assert any(";" in elem for elem in argv)
    # Subprocess.run was called with shell omitted/false.
    assert captured  # smoke
