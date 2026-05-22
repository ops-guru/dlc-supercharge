"""Python port of ``.kiro/scripts/hook-reverse-engineer-kb.ps1``.

Single shell-out to the ``reverse-engineer-kb`` bridge verb (background by
default for this verb). Emits ``KEY=value`` including the returned
``jobId`` + log path.

Markers: ``TARGET``, ``MODE``, ``MAX_FILES``,
``BRIDGE_STARTING=reverse-engineer-kb``, ``BRIDGE_EXIT``, ``JOB_ID``,
``LOG``, terminal ``HOOK_DONE`` / ``BRIDGE_FAILED``.
"""

from __future__ import annotations

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: reverse-engineer-kb")
    parser.add_argument(
        "--target", required=True, help="Path to the legacy codebase."
    )
    parser.add_argument(
        "--mode",
        choices=("full", "incremental"),
        default="full",
        help="Build mode.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Max files to scan (cost cap).",
    )
    args = parser.parse_args(argv)

    emit.emit_marker("TARGET", args.target)
    emit.emit_marker("MODE", args.mode)
    emit.emit_marker("MAX_FILES", str(args.max_files))
    emit.emit_marker("BRIDGE_STARTING", "reverse-engineer-kb")

    bridge_args = [
        "--target", args.target,
        "--mode", args.mode,
        "--max-files", str(args.max_files),
    ]
    result = _common.invoke_bridge(
        "reverse-engineer-kb", args=bridge_args, dry_run=args.dry_run
    )
    _common.emit_bridge_exit(result.returncode)

    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    job_id = _common.parse_bridge_json_field(result.stdout, "jobId")
    if job_id:
        emit.emit_marker("JOB_ID", job_id)
    log_path = _common.parse_bridge_json_field(result.stdout, "log")
    if log_path:
        emit.emit_marker("LOG", log_path)

    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
