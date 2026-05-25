"""Python port of ``.kiro/scripts/hook-hotfix-revert.ps1``.

Single shell-out to the ``hotfix`` bridge verb with ``--mode revert``.
Synchronous by default. Emits ``KEY=value`` with bridge exit + verbatim
bridge output (so the calling agent can surface the revert branch / PR
URL).

Markers: ``PR``, ``BRIDGE_STARTING=hotfix``, ``MODE=revert``,
``BRIDGE_EXIT``, ``BRIDGE_OUTPUT``, terminal ``HOOK_DONE`` /
``BRIDGE_FAILED``.
"""

from __future__ import annotations

import re

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: hotfix-revert")
    parser.add_argument(
        "--pr", type=int, required=True, help="PR number to revert."
    )
    args = parser.parse_args(argv)

    emit.emit_marker("PR", str(args.pr))
    emit.emit_marker("BRIDGE_STARTING", "hotfix")
    emit.emit_marker("MODE", "revert")

    bridge_args = ["--pr", str(args.pr), "--mode", "revert"]
    result = _common.invoke_bridge(
        "hotfix", args=bridge_args, dry_run=args.dry_run
    )
    _common.emit_bridge_exit(result.returncode)

    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    if result.stdout:
        # Flatten the bridge's stdout into one line for the agent to quote.
        single_line = re.sub(r"\r?\n", " | ", result.stdout.strip())
        if single_line:
            emit.emit_marker("BRIDGE_OUTPUT", single_line)

    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
