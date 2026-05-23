"""Detached background-mode wrapper for the bridge (FR-4, WI-18).

When ``dlc-bridge <verb> ... --background`` is invoked, ``cli.py`` writes
the initial ``status='running'`` JSON and then spawns this module as a
detached subprocess:

    python -m dlc_bridge.background_runner --job-id <id> [--dlc-root <p>] -- <cmd> [args...]

This wrapper takes over from the parent ``dlc-bridge`` process: it
exec's ``<cmd> [args...]`` (typically ``claude -p ...``), waits for
completion, and writes the terminal ``complete`` / ``error`` status
JSON. Because the parent has already detached, the parent can exit
immediately after spawning us — mirroring v1.1's ``Start-Job`` semantic
where the user's caller doesn't wait for the bridge invocation.

Platform note (D-11)
--------------------

On Windows, the parent spawns this module with
``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`` so the child runs
independently of the parent console. On POSIX, ``start_new_session=True``
gives equivalent detachment. The empirical probe in tech-design Appendix
A.3 confirmed the child outlives the parent under these flags.

Invocation contract
-------------------

The ``--`` separator divides our own flags from the wrapped command:

::

    python -m dlc_bridge.background_runner \\
        --job-id analyze-requirements-20260522T013000Z-abcdef \\
        --dlc-root /path/to/.dlc \\
        --log /path/to/.dlc/_bridge-logs/<jobId>.log \\
        -- claude -p --append-system-prompt-file /path/to/SKILL.md \\
        --permission-mode bypassPermissions --max-budget-usd 5 \\
        "<task body>"

Output of the wrapped command is appended to the log file (NOT to
stdout/stderr — those are typically /dev/null because the parent has
detached).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from dlc_bridge.status import complete_status, error_status

__all__ = ["main", "run_wrapped"]


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Split argv into our flags and the wrapped command (after ``--``)."""
    if "--" not in argv:
        raise SystemExit(
            "background_runner: missing '--' separator between flags and command"
        )
    sep_idx = argv.index("--")
    own = argv[:sep_idx]
    cmd = argv[sep_idx + 1 :]
    if not cmd:
        raise SystemExit("background_runner: no command supplied after '--'")

    parser = argparse.ArgumentParser(prog="dlc_bridge.background_runner")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--dlc-root", default=None)
    parser.add_argument("--log", default=None)
    parser.add_argument("--attempts", type=int, default=1)
    ns = parser.parse_args(own)
    return ns, cmd


def run_wrapped(
    cmd: list[str],
    *,
    log_path: Path | None = None,
) -> tuple[int, float]:
    """Run ``cmd``, appending stdout+stderr to ``log_path``. Return (exit, duration)."""
    start = time.monotonic()
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Append in case the parent wrote a header banner first.
        with open(log_path, "ab", buffering=0) as logf:
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=logf,
                check=False,
                shell=False,
            )
    else:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    return proc.returncode, time.monotonic() - start


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m dlc_bridge.background_runner``.

    Parses our own flags, executes the wrapped command, and finalizes
    the status file. Always returns 0 so the wrapper itself doesn't
    propagate the child's exit code to its parent (the parent is
    already gone in normal operation).
    """
    if argv is None:
        argv = sys.argv[1:]

    ns, cmd = _parse_args(argv)

    dlc_root = Path(ns.dlc_root) if ns.dlc_root else None
    log_path = Path(ns.log) if ns.log else None

    try:
        exit_code, duration = run_wrapped(cmd, log_path=log_path)
    except FileNotFoundError as exc:
        # The wrapped command (typically `claude`) is not on PATH.
        error_status(
            job_id=ns.job_id,
            message=f"command not found: {exc}",
            exit_code=2,
            dlc_root=dlc_root,
        )
        return 0
    except OSError as exc:  # pragma: no cover — defensive
        error_status(
            job_id=ns.job_id,
            message=f"OS error invoking wrapped command: {exc}",
            exit_code=1,
            dlc_root=dlc_root,
        )
        return 0

    complete_status(
        job_id=ns.job_id,
        exit_code=exit_code,
        log_path=str(log_path) if log_path else None,
        duration_sec=duration,
        attempts=ns.attempts,
        dlc_root=dlc_root,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — module entry
    raise SystemExit(main())
