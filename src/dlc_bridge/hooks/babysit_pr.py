"""Python port of ``.kiro/scripts/hook-babysit-pr.ps1``.

Single shell-out to the ``babysit-pr`` bridge verb (background by default
in the bridge for this verb). Emits ``KEY=value`` lines including the
bridge's returned ``jobId`` and log path so the agent can surface a tail
command.

Markers: ``PR``, ``MODE``, ``BRIDGE_STARTING=babysit-pr``, ``BRIDGE_EXIT``,
``JOB_ID``, ``LOG``, terminal ``HOOK_DONE`` / ``BRIDGE_FAILED``.
"""

from __future__ import annotations

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: babysit-pr")
    parser.add_argument(
        "--pr", type=int, required=True, help="PR number to babysit."
    )
    parser.add_argument(
        "--mode",
        choices=("default", "aggressive"),
        default="default",
        help="Babysit mode.",
    )
    args = parser.parse_args(argv)

    emit.emit_marker("PR", str(args.pr))
    emit.emit_marker("MODE", args.mode)
    emit.emit_marker("BRIDGE_STARTING", "babysit-pr")

    bridge_args = ["--pr", str(args.pr), "--mode", args.mode]
    result = _common.invoke_bridge(
        "babysit-pr", args=bridge_args, dry_run=args.dry_run
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
