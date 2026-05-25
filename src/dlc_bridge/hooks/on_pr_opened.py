"""Python port of ``.kiro/scripts/hook-on-pr-opened.ps1``.

Phase 4 -> 5 chain. Two stages:

* ``--stage init`` (default): locate slug from git branch → record PR
  number → advance state to Phase 4 → dispatch the ``babysit-pr`` bridge.
* ``--stage finalize``: advance state to Phase 5, capture babysit job id
  in the decisions log.

Markers: ``STAGE``, ``PR``, ``MODE``, ``BRANCH``, ``SLUG``,
``STATE_INITIALIZED``, ``PR_RECORDED``, ``STATE_ADVANCED``,
``BRIDGE_STARTING=babysit-pr``, ``BRIDGE_EXIT``, ``BABYSIT_JOB``,
terminal ``HOOK_INIT_DONE`` / ``HOOK_FINALIZE_DONE`` /
``BRIDGE_FAILED`` / ``ERROR``.
"""

from __future__ import annotations

import subprocess

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit
from dlc_bridge.util import state as state_mod


def _current_git_branch() -> str | None:
    """Return ``git branch --show-current`` output, or ``None`` on failure."""
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: on-pr-opened")
    parser.add_argument("--pr", type=int, required=True, help="PR number.")
    parser.add_argument(
        "--mode",
        choices=("default", "aggressive"),
        default="default",
        help="Babysit mode.",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="(finalize only) Bridge job id from init; recorded in the log.",
    )
    parser.add_argument(
        "--stage",
        choices=("init", "finalize"),
        default="init",
        help="Pipeline stage.",
    )
    parser.add_argument(
        "--dlc-root",
        default=None,
        help="Override .dlc root (used by tests).",
    )
    args = parser.parse_args(argv)

    slug = args.slug
    if not slug:
        branch = _current_git_branch()
        if branch:
            emit.emit_marker("BRANCH", branch)
            slug = _common.resolve_slug_from_branch(
                branch, dlc_root=args.dlc_root
            )
    if not slug:
        emit.emit_marker("ERROR", "could not derive slug; rerun with --slug <name>")
        return 1
    emit.emit_marker("SLUG", slug)
    slug_path = _common.dlc_root_for(args.dlc_root) / slug
    state_path = slug_path / "state.md"

    if args.stage == "finalize":
        notes = (
            f"babysit running, job {args.job_id}"
            if args.job_id
            else "babysit dispatched"
        )
        if state_path.exists():
            state_mod.advance_phase(state_path, next_phase="5", notes=notes)
        emit.emit_marker("STATE_ADVANCED", "5")
        if args.job_id:
            emit.emit_marker("BABYSIT_JOB", args.job_id)
        _common.emit_terminal("HOOK_FINALIZE_DONE")
        return 0

    # Stage = init.
    emit.emit_marker("STAGE", "init")
    emit.emit_marker("PR", str(args.pr))
    emit.emit_marker("MODE", args.mode)

    if not state_path.exists():
        try:
            state_mod.init_state(state_path, slug=slug)
            emit.emit_marker("STATE_INITIALIZED", str(state_path))
        except Exception as e:  # pragma: no cover — defensive, template-missing case
            emit.emit_marker("ERROR", f"state.md init failed: {e}")
            return 1

    state_mod.record_pr(state_path, pr_number=args.pr)
    emit.emit_marker("PR_RECORDED", f"#{args.pr}")

    state_mod.advance_phase(
        state_path, next_phase="4", notes=f"PR #{args.pr} opened"
    )
    emit.emit_marker("STATE_ADVANCED", "4")

    emit.emit_marker("BRIDGE_STARTING", "babysit-pr")
    bridge_args = ["--pr", str(args.pr), "--mode", args.mode]
    result = _common.invoke_bridge(
        "babysit-pr", args=bridge_args, dry_run=args.dry_run
    )
    _common.emit_bridge_exit(result.returncode)
    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    job_id = _common.parse_bridge_json_field(result.stdout, "jobId")
    if job_id:
        emit.emit_marker("BABYSIT_JOB", job_id)

    _common.emit_terminal("HOOK_INIT_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
