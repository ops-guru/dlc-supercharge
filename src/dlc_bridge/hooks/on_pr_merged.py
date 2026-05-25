"""Python port of ``.kiro/scripts/hook-on-pr-merged.ps1``.

Verifies the PR is merged via ``gh``, locates the slug (either via
``--slug`` or by scanning ``.dlc/*/state.md`` for the matching
``**PR number:**`` field), runs the ``finalize-sdlc`` bridge, and marks
``state.md`` complete (optionally deleting it per the DLC Phase 7 cleanup
contract).

Markers: ``PR_STATE``, ``NOT_MERGED``, ``PR_MERGED_AT``, ``SLUG``,
``SLUG_DERIVED``, ``BRIDGE_STARTING=finalize-sdlc``, ``BRIDGE_EXIT``,
``STATE_FINALIZED``, ``STATE_DELETED``, ``REPORT``, terminal
``HOOK_DONE`` / ``BRIDGE_FAILED`` / ``ERROR``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit
from dlc_bridge.util import state as state_mod


def _run_gh_pr_view(pr: int) -> tuple[int, str, str]:
    """Run ``gh pr view <pr> --json state,mergedAt,mergeCommit``.

    Returns ``(exit_code, stdout, stderr)``. Uses an argv-list, never
    ``shell=True``.
    """
    argv = ["gh", "pr", "view", str(pr), "--json", "state,mergedAt,mergeCommit"]
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: on-pr-merged")
    parser.add_argument(
        "--pr", type=int, required=True, help="The merged PR number."
    )
    parser.add_argument(
        "--delete-state",
        action="store_true",
        help="Remove state.md after marking phases 7+8 completed.",
    )
    parser.add_argument(
        "--dlc-root",
        default=None,
        help="Override .dlc root (used by tests).",
    )
    args = parser.parse_args(argv)

    # Step 1: verify merge via gh CLI.
    if shutil.which("gh") is None:
        emit.emit_marker("ERROR", "gh CLI not on PATH")
        return 2

    if args.dry_run:
        # Skip gh check on dry-run; pretend it's MERGED so we exercise the
        # downstream path through the bridge invocation stub.
        pr_info: dict = {"state": "MERGED", "mergedAt": "2026-01-01T00:00:00Z"}
    else:
        code, out, err = _run_gh_pr_view(args.pr)
        if code != 0:
            emit.emit_marker("ERROR", f"gh pr view failed: {err or out}")
            return 1
        try:
            pr_info = json.loads(out)
        except (ValueError, json.JSONDecodeError) as e:
            emit.emit_marker("ERROR", f"could not parse gh output: {e}")
            return 1

    pr_state = str(pr_info.get("state", ""))
    emit.emit_marker("PR_STATE", pr_state)
    if pr_state != "MERGED":
        emit.emit_marker(
            "NOT_MERGED",
            f"PR #{args.pr} state={pr_state}; refusing to finalize",
        )
        _common.emit_terminal("HOOK_DONE")
        return 0
    emit.emit_marker("PR_MERGED_AT", str(pr_info.get("mergedAt", "")))

    # Step 2: locate slug if not supplied.
    slug = args.slug
    if not slug:
        matches = _common.find_slugs_for_pr(args.pr, dlc_root=args.dlc_root)
        if len(matches) == 1:
            slug = matches[0]
            emit.emit_marker("SLUG_DERIVED", slug)
        elif len(matches) > 1:
            emit.emit_marker(
                "ERROR",
                f"multiple slugs match PR #{args.pr} : {', '.join(matches)}; "
                "rerun with --slug",
            )
            return 1
        else:
            emit.emit_marker(
                "ERROR",
                f"no .dlc/*/state.md found for PR #{args.pr} ; rerun with --slug",
            )
            return 1
    emit.emit_marker("SLUG", slug)
    slug_path = _common.dlc_root_for(args.dlc_root) / slug

    # Step 3: finalize-sdlc bridge.
    emit.emit_marker("BRIDGE_STARTING", "finalize-sdlc")
    bridge_args = ["--source", str(slug_path)]
    result = _common.invoke_bridge(
        "finalize-sdlc", args=bridge_args, dry_run=args.dry_run
    )
    _common.emit_bridge_exit(result.returncode)
    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    # Step 4: mark state complete; optionally delete.
    state_path = slug_path / "state.md"
    if state_path.exists():
        state_mod.finalize(state_path)
        emit.emit_marker("STATE_FINALIZED", "phases 7+8 marked completed")
        if args.delete_state:
            state_mod.finalize(state_path, delete_state=True)
            emit.emit_marker("STATE_DELETED", str(state_path))

    report = slug_path / "analysis_output" / "finalization-report.md"
    if report.exists():
        emit.emit_marker("REPORT", str(report))

    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
