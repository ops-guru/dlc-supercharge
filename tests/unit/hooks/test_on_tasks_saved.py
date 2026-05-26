"""Tests for :mod:`dlc_bridge.hooks.on_tasks_saved`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import on_tasks_saved
from .conftest import BridgeInvocationRecorder
from ._helpers import make_state_md


@pytest.fixture()
def stub_state_funcs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out state.md helpers so tests don't need the v1.1 template."""
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "init_state", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "append_decision", lambda *a, **kw: True)


def _make_spec_file(tmp_path: Path, slug: str = "myslug") -> Path:
    """Create a Kiro spec file the hook can derive a slug from."""
    spec_dir = tmp_path / ".kiro" / "specs" / slug
    spec_dir.mkdir(parents=True)
    tasks_md = spec_dir / "tasks.md"
    tasks_md.write_text("# Tasks\n", encoding="utf-8")
    return tasks_md


def test_debounce_short_circuit(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod
    monkeypatch.setattr(
        debounce_mod, "check_debounce_keyed", lambda **kw: False
    )
    tasks = _make_spec_file(tmp_path)
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "PROBE_DEBOUNCED" in out
    # No bridge call expected.
    assert invoke_bridge_stub.calls == []


def test_self_fire_short_circuit(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Self-fire suppression (Issue #8): when tasks.md's current hash
    matches a recently-recorded self-write, skip bridge + id_propagate +
    epic_inject entirely.
    """
    from dlc_bridge.util import debounce as debounce_mod, self_writes
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)

    tasks = _make_spec_file(tmp_path)
    dlc_root = tmp_path / ".dlc"
    slug_path = dlc_root / "myslug"
    # Simulate the previous fire's recording.
    self_writes.record(file_path=tasks, slug_root=slug_path)

    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PROBE_SELF_FIRE" in out
    assert "HOOK_INIT_SKIPPED" in out
    # Bridge must not be called.
    assert invoke_bridge_stub.calls == []
    # And we should not have emitted HOOK_INIT_DONE.
    assert "HOOK_INIT_DONE" not in out


def test_self_fire_only_matches_exact_content(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the file changed AFTER recording (e.g. user edit), the new
    content's hash won't match the registry → proceed with the bridge."""
    from dlc_bridge.util import (
        debounce as debounce_mod,
        epic_inject,
        id_propagate,
        self_writes,
    )
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(
        id_propagate,
        "propagate_ids",
        lambda **kw: {"propagated": [], "unmapped": [], "threshold": 0.3},
    )
    monkeypatch.setattr(
        epic_inject,
        "inject_epic_dir",
        lambda *a, **kw: {"injected": 0, "skipped": 0, "failed": 0},
    )

    tasks = _make_spec_file(tmp_path)
    dlc_root = tmp_path / ".dlc"
    slug_path = dlc_root / "myslug"
    # Record an OLD hash.
    self_writes.record(file_path=tasks, slug_root=slug_path)
    # User edits the file — hash changes.
    tasks.write_text("# Tasks\n+ user added content\n", encoding="utf-8")

    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PROBE_SELF_FIRE" not in out
    # Bridge should be called normally.
    assert invoke_bridge_stub.calls, "bridge should fire on a real edit"
    assert "HOOK_INIT_DONE" in out


def test_init_happy_path(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod, id_propagate, epic_inject
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(
        id_propagate,
        "propagate_ids",
        lambda **kw: {
            "propagated": [{"id": "TC-1", "line": 0}],
            "unmapped": [],
            "threshold": 0.3,
        },
    )
    monkeypatch.setattr(
        epic_inject, "inject_epic_dir",
        lambda *a, **kw: {"injected": 0, "skipped": 0, "failed": 0},
    )

    dlc_root = tmp_path / ".dlc"
    slug_path = dlc_root / "myslug"
    plan_dir = slug_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "epic-001.plan.md").write_text(
        "---\ntitle: Foundation\nepic: 1\n---\n", encoding="utf-8"
    )

    tasks = _make_spec_file(tmp_path)
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STAGE=init" in out
    assert "SLUG=myslug" in out
    assert "BRIDGE_STARTING=plan-implementation" in out
    assert "PLAN=" in out
    assert "ID_PROPAGATED=" in out
    assert "1 injected" in out
    assert "ITERATION_STATE_INITIALIZED=" in out
    assert "HOOK_INIT_DONE" in out


def test_init_bridge_failure(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    tasks = _make_spec_file(tmp_path)
    invoke_bridge_stub.set_next(returncode=5, stdout="")
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 5
    assert "BRIDGE_FAILED" in out


def test_finalize_appends_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dlc_root = tmp_path / ".dlc"
    make_state_md(dlc_root / "myslug")
    appended: list = []
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(
        state_mod, "append_decision",
        lambda path, entry: appended.append((path, entry)) or True,
    )
    tasks = _make_spec_file(tmp_path)
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--stage", "finalize",
            "--dlc-root", str(dlc_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "DECISION_LOG_APPENDED=" in out
    assert "HOOK_FINALIZE_DONE" in out
    assert len(appended) == 1


def test_dry_run(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod, id_propagate, epic_inject
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(id_propagate, "propagate_ids", lambda **kw: {"propagated": []})
    monkeypatch.setattr(
        epic_inject, "inject_epic_dir",
        lambda *a, **kw: {"injected": 0, "skipped": 0, "failed": 0},
    )
    tasks = _make_spec_file(tmp_path)
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dry-run",
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    assert rc == 0
    assert invoke_bridge_stub.calls[0]["dry_run"] is True


def test_bridge_cached_passthrough(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the plan-implementation bridge short-circuits on cache hit,
    the hook re-emits ``BRIDGE_CACHED=<path>`` from the subprocess stdout.

    Discovered during v2.0.0 SMOKE-TEST-CHECKLIST section 5 on 2026-05-25.
    """
    from dlc_bridge.util import debounce as debounce_mod, id_propagate, epic_inject
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(id_propagate, "propagate_ids", lambda **kw: {"propagated": []})
    monkeypatch.setattr(
        epic_inject, "inject_epic_dir",
        lambda *a, **kw: {"injected": 0, "skipped": 0, "failed": 0},
    )

    dlc_root = tmp_path / ".dlc"
    plan_dir = dlc_root / "myslug" / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "epic-001.plan.md").write_text(
        "---\ntitle: Foundation\nepic: 1\n---\n", encoding="utf-8"
    )

    tasks = _make_spec_file(tmp_path)
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout="BRIDGE_CACHED=.dlc/myslug/plans/epic-001.plan.md\n",
    )
    rc = on_tasks_saved.main(
        [
            "--source", str(tasks),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/myslug/plans/epic-001.plan.md" in out
