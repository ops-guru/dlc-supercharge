"""Python port of ``.kiro/scripts/hook-map-codebase.ps1``.

Single shell-out to the ``map-codebase`` bridge verb. Emits ``KEY=value``
with the bridge exit and (when present) the produced
``.dlc/maps/<sanitized>.map.md`` path — derived from the bridge's
``outputManifest`` JSON field.

Markers: ``TARGET``, ``WARN``, ``BRIDGE_STARTING=map-codebase``,
``BRIDGE_EXIT``, ``BRIDGE_CACHED``, ``MAP``, terminal ``HOOK_DONE`` /
``BRIDGE_FAILED``.
"""

from __future__ import annotations

import re
from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


# Match `.dlc/maps/<name>.map.md` or `.dlc\maps\<name>.map.md` inside the
# bridge's outputManifest JSON line — mirrors v1.1 wrapper.
_MAP_PATH_RE = re.compile(r'\.dlc[\\/]maps[\\/][^"\\,]+\.map\.md')


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: map-codebase")
    parser.add_argument(
        "--target", required=True, help="Subsystem path to map."
    )
    args = parser.parse_args(argv)

    if not Path(args.target).exists():
        emit.emit_marker(
            "WARN",
            f"target path does not exist locally: {args.target} "
            "(passing through to bridge anyway)",
        )

    emit.emit_marker("TARGET", args.target)
    emit.emit_marker("BRIDGE_STARTING", "map-codebase")

    bridge_args = ["--target", args.target]
    result = _common.invoke_bridge(
        "map-codebase", args=bridge_args, dry_run=args.dry_run
    )
    _common.emit_bridge_exit(result.returncode)

    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    # Best-effort: surface map files from the outputManifest JSON line.
    if result.stdout:
        for line in result.stdout.splitlines():
            if '"outputManifest"' not in line:
                continue
            for match in _MAP_PATH_RE.findall(line):
                emit.emit_marker("MAP", match)
            break

    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
