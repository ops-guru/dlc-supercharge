"""Tests for :mod:`dlc_bridge.hooks.on_task_complete`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.hooks import on_task_complete


def test_no_coverage_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = on_task_complete.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "COVERAGE_TOOL=none-detected" in out
    assert "GATE_SKIPPED=" in out
    assert "HOOK_DONE" in out


def test_python_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
    rc = on_task_complete.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "COVERAGE_TOOL=pytest --cov" in out
    assert "THRESHOLD=80.0" in out
    assert "HOOK_DONE" in out


def test_node_jest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pkg = {"scripts": {"test": "jest"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    rc = on_task_complete.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert "COVERAGE_TOOL=jest --coverage" in out


def test_node_vitest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pkg = {"scripts": {"test": "vitest run"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    rc = on_task_complete.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert "COVERAGE_TOOL=vitest --coverage" in out


def test_threshold_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
    (tmp_path / ".dlc.config.json").write_text(
        json.dumps({"defaults": {"coverageThreshold": 95}}), encoding="utf-8"
    )
    rc = on_task_complete.main(
        ["--workspace", str(tmp_path), "--dlc-root", str(tmp_path / ".dlc")]
    )
    out = capsys.readouterr().out
    assert "THRESHOLD=95.0" in out


def test_report_stage_requires_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Force git branch lookup to return empty so no auto-slug derivation.
    import subprocess
    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    rc = on_task_complete.main(
        [
            "--stage", "report",
            "--workspace", str(tmp_path),
            "--dlc-root", str(tmp_path / ".dlc"),
        ]
    )
    assert rc == 1
    assert "ERROR=--slug required" in capsys.readouterr().out


def test_report_stage_writes_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = on_task_complete.main(
        [
            "--stage", "report",
            "--slug", "myslug",
            "--threshold", "80",
            "--before", "70",
            "--after", "82",
            "--tests-added", "3",
            "--dlc-root", str(tmp_path / ".dlc"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "REPORT=" in out
    assert "HOOK_DONE" in out
    report = tmp_path / ".dlc" / "myslug" / "analysis_output" / "coverage-task-1.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "Coverage report - task 1" in content
    assert "70" in content
    assert "82" in content


def test_report_stage_increments_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Pre-existing report numbers should be incremented past.
    analysis = tmp_path / ".dlc" / "myslug" / "analysis_output"
    analysis.mkdir(parents=True)
    (analysis / "coverage-task-1.md").write_text("", encoding="utf-8")
    (analysis / "coverage-task-2.md").write_text("", encoding="utf-8")
    rc = on_task_complete.main(
        [
            "--stage", "report",
            "--slug", "myslug",
            "--before", "0",
            "--after", "100",
            "--tests-added", "5",
            "--dlc-root", str(tmp_path / ".dlc"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "REPORT=" in out
    assert (analysis / "coverage-task-3.md").exists()
