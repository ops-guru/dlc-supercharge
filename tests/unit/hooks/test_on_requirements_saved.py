"""Tests for :mod:`dlc_bridge.hooks.on_requirements_saved`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.hooks import on_requirements_saved
from .conftest import BridgeInvocationRecorder
from ._helpers import make_state_md


@pytest.fixture()
def stub_state_funcs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub state.md helpers."""
    from dlc_bridge.util import state as state_mod
    monkeypatch.setattr(state_mod, "init_state", lambda *a, **kw: True)
    monkeypatch.setattr(state_mod, "advance_phase", lambda *a, **kw: True)


def _spec(tmp_path: Path, slug: str = "myslug") -> Path:
    spec_dir = tmp_path / ".kiro" / "specs" / slug
    spec_dir.mkdir(parents=True)
    req = spec_dir / "requirements.md"
    req.write_text("# Requirements\n", encoding="utf-8")
    return req


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
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    assert rc == 0
    assert "PROBE_DEBOUNCED" in capsys.readouterr().out
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
    monkeypatch.setattr(id_propagate, "propagate_ids", lambda **kw: {})

    req = _spec(tmp_path)
    dlc_root = tmp_path / ".dlc"
    # Pre-create the PRD so the id-propagate branch triggers.
    prd_dir = dlc_root / "myslug"
    prd_dir.mkdir(parents=True)
    (prd_dir / "requirements.prd.md").write_text("# PRD\n", encoding="utf-8")

    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_requirements_saved.main(
        [
            "--source", str(req),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STAGE=init" in out
    assert "SLUG=myslug" in out
    assert "BRIDGE_STARTING=analyze-requirements" in out
    assert "PRD=" in out
    assert "ID_PROPAGATED=" in out
    assert "HOOK_INIT_DONE" in out


def test_init_surfaces_bridge_cached_marker(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression: when the bridge short-circuits on a cache hit, the hook
    must re-emit ``BRIDGE_CACHED=<path>`` on its own stdout so operators
    can distinguish a cache hit from a real fire.

    Pre-fix, ``on_requirements_saved._stage_init`` ignored ``result.stdout``
    so the ``BRIDGE_CACHED`` marker (emitted by ``cli._emit_cache_hit``) was
    invisible to the calling Kiro agent. The fix routes ``result.stdout``
    through :func:`dlc_bridge.hooks._common.surface_bridge_cached` and
    re-emits the marker.

    Discovered during v2.0.0 smoke-test section 5 on 2026-05-25.
    """
    from dlc_bridge.util import debounce as debounce_mod, id_propagate
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    monkeypatch.setattr(id_propagate, "propagate_ids", lambda **kw: {})

    req = _spec(tmp_path)
    dlc_root = tmp_path / ".dlc"
    prd_dir = dlc_root / "myslug"
    prd_dir.mkdir(parents=True)
    (prd_dir / "requirements.prd.md").write_text("# PRD\n", encoding="utf-8")

    # Simulate the bridge cache-hit path: subprocess emits BRIDGE_CACHED
    # + BRIDGE_EXIT=0 on stdout and returns 0.
    invoke_bridge_stub.set_next(
        returncode=0,
        stdout="BRIDGE_CACHED=.dlc/myslug/requirements.prd.md\nBRIDGE_EXIT=0\n",
    )
    rc = on_requirements_saved.main(
        [
            "--source", str(req),
            "--dlc-root", str(dlc_root),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "BRIDGE_CACHED=.dlc/myslug/requirements.prd.md" in out, (
        "hook did not passthrough BRIDGE_CACHED; smoke-test section 5 "
        "regression has returned"
    )


def test_init_bridge_failure(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dlc_bridge.util import debounce as debounce_mod
    monkeypatch.setattr(debounce_mod, "check_debounce_keyed", lambda **kw: True)
    req = _spec(tmp_path)
    invoke_bridge_stub.set_next(returncode=4, stdout="")
    rc = on_requirements_saved.main(
        [
            "--source", str(req),
            "--dlc-root", str(tmp_path / ".dlc"),
            "--debounce-state-path", str(tmp_path / "_fires.json"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 4
    assert "BRIDGE_FAILED" in out


def test_reviews_no_domains(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "reviews",
            "--dlc-root", str(tmp_path / ".dlc"),
        ]
    )
    assert rc == 0
    assert "REVIEWS_SKIPPED=" in capsys.readouterr().out
    assert invoke_bridge_stub.calls == []


def test_reviews_invalid_domain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "reviews",
            "--domains", "security,bogus",
            "--dlc-root", str(tmp_path / ".dlc"),
        ]
    )
    assert rc == 1
    assert "ERROR=invalid domain(s): bogus" in capsys.readouterr().out


def test_reviews_missing_prd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dlc_root = tmp_path / ".dlc"
    (dlc_root / "myslug").mkdir(parents=True)
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "reviews",
            "--domains", "security",
            "--dlc-root", str(dlc_root),
        ]
    )
    assert rc == 1
    assert "ERROR=PRD missing" in capsys.readouterr().out


def test_reviews_parallel_dispatch(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dlc_root = tmp_path / ".dlc"
    prd_dir = dlc_root / "myslug"
    prd_dir.mkdir(parents=True)
    (prd_dir / "requirements.prd.md").write_text("# PRD\n", encoding="utf-8")
    invoke_bridge_stub.set_next(returncode=0, stdout="")
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "reviews",
            "--domains", "security,ux,a11y",
            "--dlc-root", str(dlc_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    # 3 reviews dispatched.
    assert len(invoke_bridge_stub.calls) == 3
    verbs = {c["verb"] for c in invoke_bridge_stub.calls}
    assert verbs == {"review-security", "review-ux", "review-a11y"}
    assert "REVIEW_OK=security" in out
    assert "REVIEW_OK=ux" in out
    assert "REVIEW_OK=a11y" in out
    assert "HOOK_REVIEWS_DONE" in out


def test_reviews_partial_failure(
    tmp_path: Path,
    invoke_bridge_stub: BridgeInvocationRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dlc_root = tmp_path / ".dlc"
    prd_dir = dlc_root / "myslug"
    prd_dir.mkdir(parents=True)
    (prd_dir / "requirements.prd.md").write_text("# PRD\n", encoding="utf-8")
    invoke_bridge_stub.set_for_verb("review-security", returncode=0)
    invoke_bridge_stub.set_for_verb("review-ux", returncode=1)
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "reviews",
            "--domains", "security,ux",
            "--dlc-root", str(dlc_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "REVIEW_OK=security" in out
    assert "REVIEW_FAILED=ux exit=1" in out
    assert "HOOK_REVIEWS_PARTIAL" in out


def test_finalize_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_state_funcs: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dlc_root = tmp_path / ".dlc"
    make_state_md(dlc_root / "myslug")
    rc = on_requirements_saved.main(
        [
            "--source", str(_spec(tmp_path)),
            "--stage", "finalize",
            "--dlc-root", str(dlc_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "STATE_ADVANCED=2c" in out
    assert "HOOK_FINALIZE_DONE" in out
