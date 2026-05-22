"""Tests for :mod:`dlc_bridge.hooks.check_dlc_job`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.hooks import check_dlc_job


def _write_status(
    job_dir: Path, job_id: str, status: str, started: str, verb: str = "review-pr"
) -> None:
    payload = {
        "jobId": job_id,
        "verb": verb,
        "status": status,
        "startedAt": started,
        "endedAt": "",
        "exitCode": 0 if status == "complete" else "",
        "pid": 1234,
        "logPath": f".dlc/_bridge-jobs/{job_id}.log",
    }
    (job_dir / f"{job_id}.status.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_no_dir_emits_no_jobs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = check_dlc_job.main(["--dlc-root", str(tmp_path / "missing")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NO_JOBS=" in out
    assert "HOOK_DONE" in out


def test_empty_dir_emits_no_jobs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    (root / "_bridge-jobs").mkdir(parents=True)
    rc = check_dlc_job.main(["--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NO_JOBS=" in out
    assert "HOOK_DONE" in out


def test_lists_jobs_with_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    jd = root / "_bridge-jobs"
    jd.mkdir(parents=True)
    _write_status(jd, "j1", "running", "2026-05-22T10:00:00Z")
    _write_status(jd, "j2", "complete", "2026-05-22T09:00:00Z")
    _write_status(jd, "j3", "cache-hit", "2026-05-22T08:00:00Z")
    _write_status(jd, "j4", "error", "2026-05-22T07:00:00Z")
    rc = check_dlc_job.main(["--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    # Verify markers all present.
    assert "COUNT_RUNNING=1" in out
    assert "COUNT_COMPLETE=1" in out
    assert "COUNT_CACHE_HIT=1" in out
    assert "COUNT_ERROR=1" in out
    assert "COUNT_CANCELLED=0" in out
    assert "TOTAL_REPORTED=4" in out
    # Newest first
    job_lines = [line for line in out.splitlines() if line.startswith("JOB=")]
    assert len(job_lines) == 4
    assert "id=j1" in job_lines[0]
    assert "HOOK_DONE" in out


def test_caps_at_20_jobs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    jd = root / "_bridge-jobs"
    jd.mkdir(parents=True)
    for i in range(25):
        _write_status(jd, f"j{i:02d}", "complete", f"2026-05-22T10:{i:02d}:00Z")
    rc = check_dlc_job.main(["--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    job_lines = [line for line in out.splitlines() if line.startswith("JOB=")]
    assert len(job_lines) == 20
    assert "TOTAL_REPORTED=20" in out


def test_tolerates_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    jd = root / "_bridge-jobs"
    jd.mkdir(parents=True)
    _write_status(jd, "good", "complete", "2026-05-22T10:00:00Z")
    (jd / "bad.status.json").write_text("not json", encoding="utf-8")
    rc = check_dlc_job.main(["--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TOTAL_REPORTED=1" in out


def test_other_status_bucketed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".dlc"
    jd = root / "_bridge-jobs"
    jd.mkdir(parents=True)
    _write_status(jd, "weird", "weirdstate", "2026-05-22T10:00:00Z")
    rc = check_dlc_job.main(["--dlc-root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TOTAL_REPORTED=1" in out
