"""Python port of ``.kiro/scripts/hook-check-dlc-job.ps1``.

Enumerates ``.dlc/_bridge-jobs/*.status.json`` and emits a structured
``KEY=value`` stream the calling Kiro agent renders into a markdown table.
Sorted by ``startedAt`` descending (newest first), limited to 20 most
recent rows.

Markers emitted (in order):

* ``NO_JOBS=<reason>`` — if the directory or status files are missing.
* ``JOB=id=...|verb=...|status=...|started=...|ended=...|exit=...|pid=...|log=...``
  — one row per job.
* ``COUNT_RUNNING=N``, ``COUNT_COMPLETE=N``, ``COUNT_CACHE_HIT=N``,
  ``COUNT_ERROR=N``, ``COUNT_CANCELLED=N``, ``TOTAL_REPORTED=N`` — summary.

Terminal: ``HOOK_DONE``.
"""

from __future__ import annotations

import json

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: check-dlc-job")
    parser.add_argument(
        "--dlc-root",
        default=None,
        help="Override .dlc root (used by tests).",
    )
    args = parser.parse_args(argv)

    files = _common.list_status_files(dlc_root=args.dlc_root)
    job_dir_path = _common.dlc_root_for(args.dlc_root) / "_bridge-jobs"

    if not job_dir_path.exists():
        emit.emit_marker("NO_JOBS", "no .dlc/_bridge-jobs/ directory")
        _common.emit_terminal("HOOK_DONE")
        return 0

    if not files:
        emit.emit_marker("NO_JOBS", f"no .status.json files under {job_dir_path}")
        _common.emit_terminal("HOOK_DONE")
        return 0

    jobs: list[dict] = []
    for path in files:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        jobs.append(obj)

    # Sort descending by startedAt; tolerate missing field by sorting it last.
    jobs.sort(key=lambda j: str(j.get("startedAt", "")), reverse=True)
    jobs = jobs[:20]

    counts = {
        "running": 0,
        "complete": 0,
        "error": 0,
        "cancelled": 0,
        "cache-hit": 0,
        "other": 0,
    }
    for job in jobs:
        status = str(job.get("status", ""))
        if status in counts:
            counts[status] += 1
        else:
            counts["other"] += 1

        row = "|".join(
            [
                f"id={job.get('jobId', '')}",
                f"verb={job.get('verb', '')}",
                f"status={job.get('status', '')}",
                f"started={job.get('startedAt', '')}",
                f"ended={job.get('endedAt', '')}",
                f"exit={job.get('exitCode', '')}",
                f"pid={job.get('pid', '')}",
                f"log={job.get('logPath', '')}",
            ]
        )
        emit.emit_marker("JOB", row)

    emit.emit_marker("COUNT_RUNNING", str(counts["running"]))
    emit.emit_marker("COUNT_COMPLETE", str(counts["complete"]))
    emit.emit_marker("COUNT_CACHE_HIT", str(counts["cache-hit"]))
    emit.emit_marker("COUNT_ERROR", str(counts["error"]))
    emit.emit_marker("COUNT_CANCELLED", str(counts["cancelled"]))
    emit.emit_marker("TOTAL_REPORTED", str(len(jobs)))
    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
