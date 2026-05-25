"""Tests for :mod:`dlc_bridge.hooks.on_design_saved`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import on_design_saved
from .conftest import BridgeInvocationRecorder
from ._helpers import make_state_md


@pytest.fixture()
def stub_state_funcs(monkeypatch: pytest.MonkeyPatch) -> None:
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "init_state", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)


def _spec(tmp_path: Path, slug: str = "myslug", content: str | None = None) -> Path:
    spec_dir = tmp_path / ".kiro" / "specs" / slug
    spec_dir.mkdir(parents=True)
    design = spec_dir / "design.md"
    body = content or ("\n".join(f"line {i}" for i in range(50)) + "\n")
    design.write_text(body, encoding="utf-8")
    return design


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
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    assert rc == 0
    assert "PROBE_DEBOUNCED" in capsys.readouterr().out
    assert invoke_bridge_stub.calls == []


def test_skeleton_short_circuit(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    # Only 5 non-blank lines — skeleton.
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path, content="line1\nline2\nline3\n")),
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "DESIGN_SKELETON=" in out
    assert "HOOK_INIT_SKIPPED" in out
    assert invoke_bridge_stub.calls == []


def test_init_happy_path(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod, id_propagate
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(
        id_propagate,
        "propagate_ids",
        lambda **kw: {
            "propagated": [{"id": "WI-1", "line": 0}],
            "unmapped": [],
            "threshold": 0.3,
        },
    )

    dlc_root = tmp_path / ".dlc"
    td_dir = dlc_root / "myslug" / "designs"
    td_dir.mkdir(parents=True)
    (td_dir / "tech-design.md").write_text("# TD\n", encoding="utf-8")
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STAGE=init" in out
    assert "SLUG=myslug" in out
    assert "BRIDGE_STARTING=produce-tech-design" in out
    assert "TECH_DESIGN=" in out
    assert "ID_PROPAGATED=" in out
    assert "1 injected" in out
    assert "HOOK_INIT_DONE" in out


def test_surfaces_review_available(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod, id_propagate
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(id_propagate, "propagate_ids", lambda **kw: {})

    dlc_root = tmp_path / ".dlc"
    analysis = dlc_root / "myslug" / "analysis_output"
    analysis.mkdir(parents=True)
    (analysis / "security-review.md").write_text("", encoding="utf-8")
    (analysis / "ux-review.md").write_text("", encoding="utf-8")
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "REVIEW_AVAILABLE=" in out
    # Both review files should be surfaced.
    available = [
        ln for ln in out.splitlines() if ln.startswith("REVIEW_AVAILABLE=")
    ]
    assert len(available) == 2


def test_reviews_parallel(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dlc_root = tmp_path / ".dlc"
    td_dir = dlc_root / "myslug" / "designs"
    td_dir.mkdir(parents=True)
    (td_dir / "tech-design.md").write_text("# TD\n", encoding="utf-8")
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "reviews",
            "--domains", "security,performance",
            "--dlc-root", str(dlc_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "REVIEW_OK=security" in out
    assert "REVIEW_OK=performance" in out
    assert "HOOK_REVIEWS_DONE" in out


def test_finalize(
    tmp_path: Path,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dlc_root = tmp_path / ".dlc"
    make_state_md(dlc_root / "myslug")
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "finalize",
            "--dlc-root", str(dlc_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STATE_ADVANCED=3" in out
    assert "HOOK_FINALIZE_DONE" in out


def test_bridge_cached_passthrough(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the produce-tech-design bridge short-circuits on cache hit, the
    hook re-emits ``BRIDGE_CACHED=<path>`` from the subprocess stdout.

    Discovered during v2.0.0 SMOKE-TEST-CHECKLIST section 5 on 2026-05-25.
    """
    from dlc_bridge.util import debounce as debounce_mod, id_propagate
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(id_propagate, "propagate_ids", lambda **kw: {})

    dlc_root = tmp_path / ".dlc"
    td_dir = dlc_root / "myslug" / "designs"
    td_dir.mkdir(parents=True)
    (td_dir / "tech-design.md").write_text("# TD\n", encoding="utf-8")
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout="BRIDGE_CACHED=.dlc/myslug/designs/tech-design.md\n",
    )
    rc = on_design_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/myslug/designs/tech-design.md" in out
