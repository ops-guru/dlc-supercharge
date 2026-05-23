"""Integration tests for :mod:`dlc_bridge.background_runner` (Epic 2b WI-18).

Covers FR-4 background mode: spawning a detached child that wraps a
subprocess and finalizes the status file on exit.

These tests intentionally invoke ``python`` itself as the wrapped command
(via ``sys.executable -c "..."``) so we don't need a real ``claude`` binary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dlc_bridge import background_runner
from dlc_bridge import status as status_mod

pytestmark = pytest.mark.integration


def _read_status(dlc: Path, job_id: str) -> dict:
    return json.loads(
        status_mod.status_path_for(job_id, dlc_root=dlc).read_text(encoding="utf-8")
    )


# ----- in-process: run_wrapped finalizes status correctly ------------------


def test_run_wrapped_returns_exit_code_and_duration(tmp_path: Path) -> None:
    """The lowest-level helper executes a process and returns (rc, duration)."""
    log = tmp_path / "out.log"
    cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
    rc, duration = background_runner.run_wrapped(cmd, log_path=log)
    assert rc == 0
    assert duration >= 0


def test_run_wrapped_propagates_nonzero_exit(tmp_path: Path) -> None:
    log = tmp_path / "out.log"
    cmd = [sys.executable, "-c", "import sys; sys.exit(3)"]
    rc, _ = background_runner.run_wrapped(cmd, log_path=log)
    assert rc == 3


def test_run_wrapped_writes_log(tmp_path: Path) -> None:
    log = tmp_path / "out.log"
    cmd = [sys.executable, "-c", "print('hello from child')"]
    background_runner.run_wrapped(cmd, log_path=log)
    assert log.is_file()
    contents = log.read_text(encoding="utf-8", errors="replace")
    assert "hello from child" in contents


# ----- module main(): finalize status on success ---------------------------


def test_main_finalizes_status_on_success(tmp_path: Path) -> None:
    """Invoking the module entry-point should write status='complete'."""
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(
        verb="hotfix", args={"mode": "revert"}, dlc_root=dlc,
    )
    rc = background_runner.main(
        [
            "--job-id", st0.jobId,
            "--dlc-root", str(dlc),
            "--log", str(tmp_path / "child.log"),
            "--",
            sys.executable, "-c", "import sys; sys.exit(0)",
        ]
    )
    # background_runner always returns 0 (the parent is already gone).
    assert rc == 0
    final = _read_status(dlc, st0.jobId)
    assert final["status"] == "complete"
    assert final["exitCode"] == 0
    assert final["endedAt"] is not None


def test_main_finalizes_status_on_error(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    background_runner.main(
        [
            "--job-id", st0.jobId,
            "--dlc-root", str(dlc),
            "--log", str(tmp_path / "child.log"),
            "--",
            sys.executable, "-c", "import sys; sys.exit(7)",
        ]
    )
    final = _read_status(dlc, st0.jobId)
    assert final["status"] == "error"
    assert final["exitCode"] == 7


def test_main_handles_missing_command_gracefully(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    rc = background_runner.main(
        [
            "--job-id", st0.jobId,
            "--dlc-root", str(dlc),
            "--",
            "this-command-definitely-does-not-exist-xyz",
        ]
    )
    assert rc == 0  # parent always exits clean
    final = _read_status(dlc, st0.jobId)
    assert final["status"] == "error"
    assert final["exitCode"] == 2  # CLAUDE_NOT_FOUND-equivalent


def test_main_requires_separator() -> None:
    """Missing ``--`` between own flags and command is a fatal arg error."""
    with pytest.raises(SystemExit):
        background_runner.main(["--job-id", "x", "echo", "hi"])


def test_main_requires_at_least_one_command_word() -> None:
    with pytest.raises(SystemExit):
        background_runner.main(["--job-id", "x", "--"])


# ----- end-to-end: spawn as a real subprocess ------------------------------


def test_spawned_subprocess_finalizes_status_end_to_end(tmp_path: Path) -> None:
    """Spawn ``python -m dlc_bridge.background_runner`` as a real subprocess.

    Exercises the actual entry-point path from outside this process.
    """
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(
        verb="analyze-requirements", args={"mode": "confident"}, dlc_root=dlc,
    )
    log = tmp_path / "child.log"

    # Use a child python invocation that sleeps briefly so we can observe the
    # transition. Keep total wait under 5s for CI.
    inner_cmd = [
        sys.executable,
        "-c",
        "import time; time.sleep(0.2); print('done')",
    ]
    runner_argv = [
        sys.executable, "-m", "dlc_bridge.background_runner",
        "--job-id", st0.jobId,
        "--dlc-root", str(dlc),
        "--log", str(log),
        "--",
    ] + inner_cmd

    proc = subprocess.run(
        runner_argv, capture_output=True, text=True, timeout=15, check=False,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"

    final = _read_status(dlc, st0.jobId)
    assert final["status"] == "complete"
    assert final["exitCode"] == 0
    assert "durationSec" in final
    assert final["durationSec"] >= 0.2


def test_detach_flags_documented_constants() -> None:
    """D-11: Windows uses DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP."""
    # 0x00000008 = DETACHED_PROCESS, 0x00000200 = CREATE_NEW_PROCESS_GROUP.
    # We don't run a detached spawn here (test isolation), but assert the
    # cli's spawn helper uses these flags on Windows when we trace it.
    from dlc_bridge import cli
    src = Path(cli.__file__).read_text(encoding="utf-8")
    if sys.platform == "win32":
        assert "0x00000008" in src
        assert "0x00000200" in src
    else:
        assert "start_new_session" in src


# ----- log file appending --------------------------------------------------


def test_log_path_appends_not_truncates(tmp_path: Path) -> None:
    """v1.1 wrote a header banner before the child started; we preserve it."""
    log = tmp_path / "out.log"
    log.write_text("== header banner ==\n", encoding="utf-8", newline="\n")

    cmd = [sys.executable, "-c", "print('child output')"]
    background_runner.run_wrapped(cmd, log_path=log)

    text = log.read_text(encoding="utf-8", errors="replace")
    assert "== header banner ==" in text
    assert "child output" in text


# ----- argv-list invocation (no shell=True) --------------------------------


def test_run_wrapped_never_invokes_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hardens FR-3 / WI-21: subprocess always uses argv list, never shell=True."""
    captured: dict = {}

    real_run = subprocess.run

    def spy_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["shell"] = kwargs.get("shell", False)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(
        "dlc_bridge.background_runner.subprocess.run", spy_run,
    )
    background_runner.run_wrapped(
        [sys.executable, "-c", "pass"], log_path=tmp_path / "log.txt",
    )
    assert isinstance(captured["cmd"], list)
    assert captured["shell"] is False
