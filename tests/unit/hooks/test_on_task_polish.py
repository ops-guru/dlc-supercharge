"""Tests for :mod:`dlc_bridge.hooks.on_task_polish`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.hooks import on_task_polish


def test_gate_disabled_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = on_task_polish.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "POLISH_ENABLED=False" in out
    assert "GATE_SKIPPED=" in out
    assert "HOOK_DONE" in out


def test_gate_enabled_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".dlc.config.json").write_text(
        json.dumps({"defaults": {"taskPolish": True}}), encoding="utf-8"
    )
    monkeypatch.setattr(on_task_polish, "_diff_files", lambda: ["a.py", "b.ts"])
    monkeypatch.setattr(
        on_task_polish,
        "_resolve_style_profile",
        lambda ws: {"style": "google", "samples": 3},
    )
    rc = on_task_polish.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "POLISH_ENABLED=True" in out
    assert "DIFF_FILE_COUNT=2" in out
    assert "DIFF_FILE=a.py" in out
    assert "DIFF_FILE=b.ts" in out
    assert "STYLE_PROFILE=google" in out
    assert "STYLE_SAMPLES=3" in out
    assert "HOOK_DONE" in out


def test_verify_stage_python(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
    rc = on_task_polish.main(
        ["--stage", "verify", "--workspace", str(tmp_path),
         "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "TEST_CMD=pytest" in out
    assert "HOOK_DONE" in out


def test_verify_stage_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    rc = on_task_polish.main(
        ["--stage", "verify", "--workspace", str(tmp_path),
         "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert "TEST_CMD=npm test" in out


def test_verify_stage_no_runner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = on_task_polish.main(
        ["--stage", "verify", "--workspace", str(tmp_path),
         "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "TESTS_SKIPPED=" in out
    assert "HOOK_DONE" in out


def test_resolve_style_profile_smoke(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text(
        '''def f(x):
    """Hi.

    Args:
        x: thing
    Returns:
        result
    """
    return x
''',
        encoding="utf-8",
    )
    profile = on_task_polish._resolve_style_profile(tmp_path)
    assert profile["style"] == "google"
    assert profile["samples"] >= 1
