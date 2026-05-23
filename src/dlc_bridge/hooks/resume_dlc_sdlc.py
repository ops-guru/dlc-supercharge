"""Python port of ``.kiro/scripts/hook-resume-dlc-sdlc.ps1``.

Reads ``.dlc/<slug>/state.md`` and emits the current phase + PR + recent
decisions log + a suggested next action as ``KEY=value`` lines. If no slug
is supplied, enumerates all ``.dlc/*/state.md`` files so the agent can ask
the user to pick.

Markers: ``AVAILABLE=<slug>::<phase>``, ``NO_STATES``, ``SLUG``,
``STATE_PATH``, ``CURRENT_PHASE``, ``PR``, ``BRANCH``,
``RECENT_DECISION``, ``NEXT_ACTION``, ``NEXT``, terminal ``HOOK_DONE`` /
``ERROR``.
"""

from __future__ import annotations

import re

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


# Phase → suggested next action mapping. Mirrors v1.1 switch block exactly.
def _next_action_for_phase(phase: str, pr: int | None) -> str:
    """Return the suggested next action string for a given phase."""
    if re.match(r"^1$", phase):
        return "Re-save requirements.md in Kiro to re-fire on-requirements-saved."
    if re.match(r"^2a$", phase):
        return "Re-save requirements.md to redrive Phase 2 reviewer scan."
    if re.match(r"^2b$", phase):
        return (
            "Re-fire on-requirements-saved once reviewer reports are written "
            "under .dlc/<slug>/analysis_output/."
        )
    if re.match(r"^2c$", phase):
        return "Save design.md in Kiro to fire on-design-saved."
    if re.match(r"^3$", phase):
        return (
            "Save tasks.md, or use /dlc:build epic-NNN in terminal to execute "
            "the first Epic."
        )
    if re.match(r"^4$", phase):
        if pr:
            return (
                f"Babysit may be in flight for PR #{pr} ; use check-dlc-job to monitor."
            )
        return "Re-fire on-pr-opened with the PR number."
    if re.match(r"^5$", phase):
        if pr:
            return f"Babysit running for PR #{pr} ; use check-dlc-job hook."
        return "Phase 5; PR was not recorded - re-fire on-pr-opened."
    if re.match(r"^6$", phase):
        return (
            "Phase 6 is manual staging verification; re-fire on-pr-opened "
            "-Mode aggressive if babysit needs rerun."
        )
    if re.match(r"^[78]$", phase):
        if pr:
            return f"Re-fire on-pr-merged for PR #{pr} to finalize."
        return "Run on-pr-merged once you have the merged PR number."
    return "Phase not recognised; review state.md manually."


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: resume-dlc-sdlc")
    parser.add_argument(
        "--dlc-root",
        default=None,
        help="Override .dlc root (used by tests).",
    )
    args = parser.parse_args(argv)

    root = _common.dlc_root_for(args.dlc_root)

    if not args.slug:
        if not root.exists():
            emit.emit_marker("NO_STATES", "no .dlc/*/state.md files found")
            _common.emit_terminal("HOOK_DONE")
            return 0
        entries: list[str] = []
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            state_path = entry / "state.md"
            if not state_path.exists():
                continue
            content = state_path.read_text(encoding="utf-8")
            phase_match = re.search(r"\*\*Current phase:\*\*\s+(\S+)", content)
            phase = phase_match.group(1) if phase_match else ""
            entries.append(f"{entry.name}::{phase}")
        if not entries:
            emit.emit_marker("NO_STATES", "no .dlc/*/state.md files found")
            _common.emit_terminal("HOOK_DONE")
            return 0
        for e in entries:
            emit.emit_marker("AVAILABLE", e)
        emit.emit_marker(
            "NEXT",
            "agent asks user to pick a slug then re-invokes this wrapper "
            "with --slug <name>",
        )
        _common.emit_terminal("HOOK_DONE")
        return 0

    state_path = root / args.slug / "state.md"
    if not state_path.exists():
        emit.emit_marker("ERROR", f"no state.md at {state_path}")
        return 1
    emit.emit_marker("SLUG", args.slug)
    emit.emit_marker("STATE_PATH", str(state_path))

    phase = _common.read_current_phase(args.slug, dlc_root=args.dlc_root) or ""
    emit.emit_marker("CURRENT_PHASE", phase)

    pr = _common.read_pr_number(args.slug, dlc_root=args.dlc_root)
    if pr:
        emit.emit_marker("PR", str(pr))

    branch = _common.read_branch(args.slug, dlc_root=args.dlc_root)
    if branch:
        emit.emit_marker("BRANCH", branch)

    for decision in _common.read_recent_decisions(
        args.slug, limit=2, dlc_root=args.dlc_root
    ):
        emit.emit_marker("RECENT_DECISION", decision)

    emit.emit_marker("NEXT_ACTION", _next_action_for_phase(phase, pr))

    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
