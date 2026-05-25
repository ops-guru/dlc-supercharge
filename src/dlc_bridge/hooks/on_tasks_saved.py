"""Python port of ``.kiro/scripts/hook-on-tasks-saved.ps1``.

Phase 3 (planning) chain. Two stages:

* ``--stage init`` (default): debounce → slug → state ensure → bridge
  ``plan-implementation`` → id-propagate (TC,T) → preserve / create
  ``_iteration-state.md``.
* ``--stage finalize``: append a decision-log entry; state stays at
  Phase 3.

Markers: ``STAGE``, ``TRIGGER``, ``SLUG``, ``STATE_INITIALIZED``,
``STATE_EXISTS``, ``BRIDGE_STARTING=plan-implementation``,
``BRIDGE_EXIT``, ``PLAN``, ``ID_PROPAGATED``, ``ID_PROPAGATE_SKIPPED``,
``EPIC_INJECTED``, ``EPIC_SKIPPED``, ``INJECT_SUMMARY``,
``ITERATION_STATE_INITIALIZED``, ``ITERATION_STATE_PRESERVED``,
``DECISION_LOG_APPENDED``, terminal ``PROBE_DEBOUNCED`` /
``BRIDGE_FAILED`` / ``HOOK_INIT_DONE`` / ``HOOK_FINALIZE_DONE``.
"""

from __future__ import annotations

from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import debounce as debounce_mod
from dlc_bridge.util import emit
from dlc_bridge.util import epic_inject
from dlc_bridge.util import id_propagate
from dlc_bridge.util import slug as slug_mod
from dlc_bridge.util import state as state_mod
from dlc_bridge.util.encoding import atomic_write_utf8_lf

_HOOK_ID = "on-tasks-saved"


def _ensure_iteration_state(
    plan_dir: Path, slug: str
) -> tuple[str, Path] | None:
    """Create ``_iteration-state.md`` if absent; return marker + path.

    Returns ``("ITERATION_STATE_INITIALIZED", path)`` on creation,
    ``("ITERATION_STATE_PRESERVED", path)`` if already present, or ``None``
    if ``plan_dir`` does not exist.
    """
    if not plan_dir.exists():
        return None
    iter_state = plan_dir / "_iteration-state.md"
    if iter_state.exists():
        return ("ITERATION_STATE_PRESERVED", iter_state)
    epic_files = sorted(plan_dir.glob("epic-*.plan.md"))
    total_epics = len(epic_files)
    lines = [
        "---",
        f"slug: {slug}",
        f"total_epics: {total_epics}",
        "delivered: 0",
        "in_progress: 0",
        f"remaining: {total_epics}",
        "---",
        "",
        "# Iteration state",
        "",
    ]
    for ef in epic_files:
        lines.append(f"## {ef.stem}")
        lines.append("status: pending")
        lines.append("")
    atomic_write_utf8_lf(iter_state, "\n".join(lines))
    return ("ITERATION_STATE_INITIALIZED", iter_state)


def _append_decision_log(state_path: Path) -> bool:
    """Append a ``PLANNING COMPLETE`` block to the decisions log."""
    if not state_path.exists():
        return False
    now = state_mod.iso_now()
    entry_lines = [
        f"- [{now}] PLANNING COMPLETE: tasks.md saved, "
        "plan-implementation bridge succeeded.",
        "  Epic markers and task checklists are reconciled against "
        ".dlc/<slug>/plans/epic-*.plan.md by epic-inject in the init "
        "stage (idempotent).",
        "  Risk: low",
        "  Would pause in confident mode: no",
    ]
    state_mod.append_decision(state_path, entry="\n".join(entry_lines))
    return True


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: on-tasks-saved")
    parser.add_argument(
        "--source", required=True, help="The triggering tasks.md path."
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
    parser.add_argument(
        "--debounce-state-path",
        default=None,
        help="Override debounce-state json path (used by tests).",
    )
    args = parser.parse_args(argv)

    trigger_path = args.source

    if args.stage == "finalize":
        try:
            slug = args.slug or slug_mod.from_path(trigger_path)
        except Exception as e:
            emit.emit_marker(
                "ERROR", f"could not derive slug from {trigger_path}: {e}"
            )
            return 1
        slug_path = _common.dlc_root_for(args.dlc_root) / slug
        state_path = slug_path / "state.md"
        if state_path.exists():
            _append_decision_log(state_path)
            emit.emit_marker("DECISION_LOG_APPENDED", str(state_path))
        emit.emit_marker("SLUG", slug)
        _common.emit_terminal("HOOK_FINALIZE_DONE")
        return 0

    # Stage = init.
    emit.emit_marker("STAGE", "init")
    emit.emit_marker("TRIGGER", trigger_path)

    debounce_state = (
        Path(args.debounce_state_path)
        if args.debounce_state_path
        else _common.dlc_root_for(args.dlc_root) / "_recent-fires.json"
    )
    proceed = debounce_mod.check_debounce_keyed(
        state_path=debounce_state,
        hook_id=_HOOK_ID,
        trigger_path=trigger_path,
    )
    if not proceed:
        _common.emit_terminal("PROBE_DEBOUNCED")
        return 0

    try:
        slug = args.slug or slug_mod.from_path(trigger_path)
    except Exception as e:
        emit.emit_marker(
            "ERROR", f"could not derive slug from {trigger_path}: {e}"
        )
        return 1
    emit.emit_marker("SLUG", slug)

    slug_path = _common.dlc_root_for(args.dlc_root) / slug
    state_path = slug_path / "state.md"
    if not state_path.exists():
        try:
            state_mod.init_state(state_path, slug=slug)
            state_mod.advance_phase(
                state_path,
                next_phase="3",
                notes="state initialised from tasks.md save",
            )
            emit.emit_marker("STATE_INITIALIZED", str(state_path))
        except Exception as e:  # pragma: no cover - defensive
            emit.emit_marker("ERROR", f"state.md init failed: {e}")
            return 1
    else:
        emit.emit_marker("STATE_EXISTS", str(state_path))

    emit.emit_marker("BRIDGE_STARTING", "plan-implementation")
    result = _common.invoke_bridge(
        "plan-implementation",
        args=["--source", trigger_path],
        dry_run=args.dry_run,
    )
    _common.emit_bridge_exit(result.returncode)
    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    # Locate produced plan: prefer epic-001, fall back to any epic-*.plan.md.
    plan_dir = slug_path / "plans"
    plan_path: Path | None = None
    if plan_dir.exists():
        candidate = plan_dir / "epic-001.plan.md"
        if candidate.exists():
            plan_path = candidate
        else:
            candidates = sorted(plan_dir.glob("epic-*.plan.md"))
            if candidates:
                plan_path = candidates[0]

    if plan_path is not None:
        emit.emit_marker("PLAN", str(plan_path))
        try:
            id_propagate.propagate_ids(
                dlc_prd=plan_path,
                kiro_req=Path(trigger_path),
                id_types=["TC", "T"],
            )
            emit.emit_marker(
                "ID_PROPAGATED", f"{plan_path} -> {trigger_path}"
            )
        except Exception as e:
            emit.emit_marker("ID_PROPAGATE_SKIPPED", f"propagate failed: {e}")
    else:
        emit.emit_marker(
            "ID_PROPAGATE_SKIPPED", f"no plan file under {plan_dir}"
        )

    if plan_dir.exists():
        # epic_inject.inject_epic_dir emits its own EPIC_INJECTED /
        # EPIC_SKIPPED / INJECT_SUMMARY markers via emit_marker.
        epic_inject.inject_epic_dir(plan_dir, Path(trigger_path))

    iter_marker = _ensure_iteration_state(plan_dir, slug)
    if iter_marker is not None:
        marker_name, marker_path = iter_marker
        emit.emit_marker(marker_name, str(marker_path))

    _common.emit_terminal("HOOK_INIT_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
