"""Python port of ``.kiro/scripts/hook-kb-gap-analysis.ps1``.

Validates the ``--source`` and ``--kb`` paths exist, then makes a single
shell-out to the bridge with the ``kb-gap-analysis`` verb. Emits
``KEY=value`` including the bridge exit code and (best-effort) the
``BRIDGE_CACHED`` marker on cache hit.

Markers: ``SOURCE``, ``KB``, ``MODE``, ``BRIDGE_STARTING=kb-gap-analysis``,
``BRIDGE_EXIT``, ``BRIDGE_CACHED``, terminal ``HOOK_DONE`` /
``BRIDGE_FAILED`` / ``ERROR``.
"""

from __future__ import annotations

from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: kb-gap-analysis")
    parser.add_argument(
        "--source", required=True, help="Path to the requirements file."
    )
    parser.add_argument(
        "--kb", required=True, help="Path to the KB root."
    )
    parser.add_argument(
        "--mode",
        choices=("full", "patch"),
        default="full",
        help="Analysis mode.",
    )
    args = parser.parse_args(argv)

    if not Path(args.source).exists():
        emit.emit_marker("ERROR", f"source not found: {args.source}")
        return 1
    if not Path(args.kb).exists():
        emit.emit_marker(
            "ERROR", f"kb root not found: {args.kb} (run reverse-engineer-kb first)"
        )
        return 1

    emit.emit_marker("SOURCE", args.source)
    emit.emit_marker("KB", args.kb)
    emit.emit_marker("MODE", args.mode)
    emit.emit_marker("BRIDGE_STARTING", "kb-gap-analysis")

    bridge_args = [
        "--source", args.source,
        "--kb", args.kb,
        "--mode", args.mode,
    ]
    result = _common.invoke_bridge(
        "kb-gap-analysis", args=bridge_args, dry_run=args.dry_run
    )
    _common.emit_bridge_exit(result.returncode)

    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
