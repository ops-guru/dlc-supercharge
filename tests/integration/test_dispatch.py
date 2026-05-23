"""End-to-end integration tests for ``dlc-bridge`` dispatch (Epic 2b WI-16, WI-18).

Mocks ``subprocess.run`` so we don't invoke the real ``claude`` binary.
Verifies cache-hit short-circuit, foreground success path with cache write,
background spawn path, and marker emission.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dlc_bridge import cache as cache_mod
from dlc_bridge import status as status_mod
from dlc_bridge.cli import main

pytestmark = pytest.mark.integration


def _seed_source_file(tmp_path: Path, slug: str = "spec-x") -> Path:
    """Create a minimal source file inside a spec layout under tmp_path."""
    src = tmp_path / ".kiro" / "specs" / slug / "requirements.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("Test requirements body\n", encoding="utf-8", newline="\n")
    return src


def _seed_artifact(tmp_path: Path, slug: str = "spec-x") -> Path:
    """Create the expected output artifact for analyze-requirements."""
    art = tmp_path / ".dlc" / slug / "requirements.prd.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("PRD body\n", encoding="utf-8", newline="\n")
    return art


def _mock_claude_success(monkeypatch: pytest.MonkeyPatch, stdout: str = "") -> list:
    """Install a subprocess.run mock that always returns rc=0.

    Returns the list that captures each call's argv.
    """
    calls: list = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": list(argv), "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=stdout, stderr=""
        )

    monkeypatch.setattr("dlc_bridge.cli.subprocess.run", fake_run)
    return calls


def _mock_claude_failure(
    monkeypatch: pytest.MonkeyPatch, stderr: str, rc: int = 1
) -> list:
    calls: list = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": list(argv), "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=argv, returncode=rc, stdout="", stderr=stderr
        )

    monkeypatch.setattr("dlc_bridge.cli.subprocess.run", fake_run)
    return calls


# ----- help / dry-run paths (no subprocess) --------------------------------


def test_help_returns_0_and_lists_all_verbs(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["help"])
    assert rc == 0
    out = capsys.readouterr().out
    for verb in (
        "analyze-requirements",
        "produce-tech-design",
        "hotfix",
    ):
        assert verb in out


def test_dry_run_emits_json_with_assembled_prompt(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    rc = main(
        ["analyze-requirements", "--dry-run", "--source", str(src)]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry-run"
    assert payload["verb"] == "analyze-requirements"
    assert payload["command"] == "claude"
    # assembledPrompt now contains real (synthetic) task body.
    assert payload["assembledPrompt"]
    assert "/dlc:analyze-requirements" in payload["assembledPrompt"]


# ----- foreground success: cache write + BRIDGE_OK -------------------------


def test_foreground_success_writes_cache_and_emits_bridge_ok(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    _seed_artifact(tmp_path)  # pre-create the expected artifact
    calls = _mock_claude_success(monkeypatch)

    rc = main(["analyze-requirements", "--source", str(src)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BRIDGE_EXIT=0" in out
    assert "BRIDGE_OK=" in out

    # subprocess.run was invoked once with argv-list (FR-3 / WI-21).
    assert len(calls) == 1
    assert isinstance(calls[0]["argv"], list)
    assert calls[0]["argv"][0] == "claude"
    assert calls[0]["kwargs"].get("shell") in (None, False)

    # Cache file written.
    cache_path = tmp_path / ".dlc" / "spec-x" / "_bridge-cache.json"
    assert cache_path.is_file()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["cache_version"] == 2
    assert "analyze-requirements" in data


# ----- cache hit short-circuit ----------------------------------------------


def test_cache_hit_short_circuits_without_subprocess(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second invocation with same input hash → cache hit, no claude invoked."""
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    _seed_artifact(tmp_path)

    # First call seeds the cache.
    calls = _mock_claude_success(monkeypatch)
    rc = main(["analyze-requirements", "--source", str(src)])
    assert rc == 0
    assert len(calls) == 1
    capsys.readouterr()  # flush captured output

    # Second call: should hit cache, NOT invoke claude.
    rc2 = main(["analyze-requirements", "--source", str(src)])
    assert rc2 == 0
    out = capsys.readouterr().out
    assert "BRIDGE_CACHED=" in out
    # subprocess NOT called again.
    assert len(calls) == 1


def test_force_flag_bypasses_cache(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--force`` must bypass an otherwise-hot cache."""
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    _seed_artifact(tmp_path)
    calls = _mock_claude_success(monkeypatch)

    # Seed cache.
    main(["analyze-requirements", "--source", str(src)])
    assert len(calls) == 1
    capsys.readouterr()

    # --force should re-invoke claude.
    rc = main(["analyze-requirements", "--source", str(src), "--force"])
    assert rc == 0
    assert len(calls) == 2


def test_no_cache_flag_bypasses_cache(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    _seed_artifact(tmp_path)
    calls = _mock_claude_success(monkeypatch)

    main(["analyze-requirements", "--source", str(src)])
    main(["analyze-requirements", "--source", str(src), "--no-cache"])
    # Two invocations, one cached + one bypassed.
    assert len(calls) == 2


# ----- foreground failure: retries + error exit code -----------------------


def test_transient_failure_retries_then_exhausts(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)

    # Mock sleep so the test runs fast.
    monkeypatch.setattr("dlc_bridge.cli.retry_mod.time.sleep", lambda _: None)

    calls = _mock_claude_failure(monkeypatch, stderr="HTTP 429 rate limit", rc=1)

    rc = main(["analyze-requirements", "--source", str(src)])
    # Retries exhausted → exit 5.
    assert rc == 5
    # 3 attempts per FR-7.
    assert len(calls) == 3


def test_non_transient_failure_returns_immediately(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)

    calls = _mock_claude_failure(monkeypatch, stderr="syntax error", rc=1)

    rc = main(["analyze-requirements", "--source", str(src)])
    # Non-transient — claude's exit code propagates.
    assert rc == 1
    assert len(calls) == 1


# ----- background mode ------------------------------------------------------


def test_background_mode_emits_job_id_and_returns_0(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)

    # Mock the actual Popen call so we don't spawn a real child.
    spawned: list = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            spawned.append({"argv": list(argv), "kwargs": kwargs})
            self.pid = 999

    monkeypatch.setattr("dlc_bridge.cli.subprocess.Popen", FakePopen)

    rc = main(["analyze-requirements", "--source", str(src), "--background"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BACKGROUND_JOB_ID=" in out
    # One detached child was spawned, never with shell=True.
    assert len(spawned) == 1
    assert spawned[0]["kwargs"].get("shell") in (None, False)
    # argv begins with python -m dlc_bridge.background_runner.
    argv = spawned[0]["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == "-m"
    assert argv[2] == "dlc_bridge.background_runner"
    # Detach flag/option present per platform.
    if sys.platform == "win32":
        assert spawned[0]["kwargs"].get("creationflags") == 0x00000008 | 0x00000200
    else:
        assert spawned[0]["kwargs"].get("start_new_session") is True


def test_background_writes_initial_running_status(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = 1
    monkeypatch.setattr("dlc_bridge.cli.subprocess.Popen", FakePopen)

    rc = main(["analyze-requirements", "--source", str(src), "--background"])
    assert rc == 0
    out = capsys.readouterr().out
    # Extract jobId from marker.
    job_marker = [ln for ln in out.splitlines() if ln.startswith("BACKGROUND_JOB_ID=")]
    assert job_marker
    job_id = job_marker[0].split("=", 1)[1]

    # Initial status file written; status='running'.
    status_file = status_mod.status_path_for(job_id)
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    assert raw["status"] == "running"
    assert raw["verb"] == "analyze-requirements"


# ----- subprocess argv shape (FR-3, WI-21 hardening) -----------------------


def test_claude_invoked_with_argv_list_not_string(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess invocation always uses argv LIST (FR-3 / WI-21 hardening)."""
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    calls = _mock_claude_success(monkeypatch)

    main(["analyze-requirements", "--source", str(src)])
    assert calls
    argv = calls[0]["argv"]
    assert isinstance(argv, list)
    assert argv[0] == "claude"
    assert "-p" in argv
    # SKILL.md path should be an absolute path.
    sp_idx = argv.index("--append-system-prompt-file")
    assert Path(argv[sp_idx + 1]).is_absolute()
    # bypassPermissions present.
    assert "bypassPermissions" in argv


def test_max_budget_passed_through_to_claude(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    calls = _mock_claude_success(monkeypatch)

    main([
        "analyze-requirements", "--source", str(src),
        "--max-budget-usd", "12.5",
    ])
    argv = calls[0]["argv"]
    assert "12.5" in argv
    bg_idx = argv.index("--max-budget-usd")
    assert argv[bg_idx + 1] == "12.5"


# ----- status file lifecycle on full dispatch ------------------------------


def test_foreground_success_writes_complete_status(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After foreground success, the per-invocation status file is ``complete``."""
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    _seed_artifact(tmp_path)
    _mock_claude_success(monkeypatch)

    main(["analyze-requirements", "--source", str(src)])

    # Find the status file in .dlc/_bridge-jobs/
    jobs_dir = tmp_path / ".dlc" / "_bridge-jobs"
    statuses = list(jobs_dir.glob("analyze-requirements-*.status.json"))
    assert statuses, "no status file written by foreground dispatch"
    # The latest one should be 'complete' (filter out cache-hit names).
    completed = [
        s for s in statuses if "cache-hit" not in s.name
    ]
    assert completed
    raw = json.loads(completed[-1].read_text(encoding="utf-8"))
    assert raw["status"] == "complete"
    assert raw["exitCode"] == 0


def test_cache_hit_writes_cache_hit_status(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """v1.1 parity: cache hit writes a ``status='cache-hit'`` observability file."""
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)
    _seed_artifact(tmp_path)
    _mock_claude_success(monkeypatch)

    # Seed cache.
    main(["analyze-requirements", "--source", str(src)])
    capsys.readouterr()

    # Trigger cache hit on second call.
    main(["analyze-requirements", "--source", str(src)])

    jobs_dir = tmp_path / ".dlc" / "_bridge-jobs"
    cache_hit_statuses = list(jobs_dir.glob("analyze-requirements-cache-hit-*.status.json"))
    assert cache_hit_statuses
    raw = json.loads(cache_hit_statuses[-1].read_text(encoding="utf-8"))
    assert raw["status"] == "cache-hit"
    assert raw["exitCode"] == 0


# ----- unknown verb ---------------------------------------------------------


def test_unknown_verb_exits_4(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["never-a-verb"])
    assert rc == 4


# ----- claude not on PATH --------------------------------------------------


def test_claude_not_on_path_exits_2(
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _seed_source_file(tmp_path)

    def boom(*a, **kw):
        raise FileNotFoundError("claude not on PATH")

    monkeypatch.setattr("dlc_bridge.cli.subprocess.run", boom)

    rc = main(["analyze-requirements", "--source", str(src)])
    assert rc == 2
