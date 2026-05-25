"""Tests for :mod:`dlc_bridge.hooks._common`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dlc_bridge.hooks import _common

from ._helpers import make_state_md


# ---------------------------------------------------------------------------
# common_parser
# ---------------------------------------------------------------------------


class TestCommonParser:
    def test_has_slug_and_dry_run(self) -> None:
        parser = _common.common_parser("desc")
        args = parser.parse_args([])
        assert args.slug is None
        assert args.dry_run is False

    def test_dry_run_flag(self) -> None:
        parser = _common.common_parser("desc")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_slug_capture(self) -> None:
        parser = _common.common_parser("desc")
        args = parser.parse_args(["--slug", "foo"])
        assert args.slug == "foo"


# ---------------------------------------------------------------------------
# find_python_executable
# ---------------------------------------------------------------------------


def test_find_python_executable_returns_sys_executable() -> None:
    assert _common.find_python_executable() == sys.executable


# ---------------------------------------------------------------------------
# invoke_bridge
# ---------------------------------------------------------------------------


class TestInvokeBridgeDryRun:
    def test_dry_run_returns_completed_process_without_spawning(self) -> None:
        result = _common.invoke_bridge(
            "analyze-requirements",
            args=["--source", "foo.md"],
            dry_run=True,
        )
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0
        assert "DRY_RUN=" in result.stdout
        assert "analyze-requirements" in result.stdout
        assert "--source foo.md" in result.stdout

    def test_dry_run_argv_contains_verb(self) -> None:
        result = _common.invoke_bridge(
            "babysit-pr",
            args=["--pr", "42"],
            dry_run=True,
        )
        argv = result.args
        assert "dlc_bridge" in argv
        assert "babysit-pr" in argv
        assert "--pr" in argv
        assert "42" in argv

    def test_dry_run_background_flag(self) -> None:
        result = _common.invoke_bridge(
            "reverse-engineer-kb",
            args=["--target", "."],
            background=True,
            dry_run=True,
        )
        assert "--background" in result.args


class TestInvokeBridgeArgvShape:
    """Regression — ensure invoke_bridge never uses shell=True semantics."""

    def test_argv_is_list(self) -> None:
        result = _common.invoke_bridge(
            "map-codebase",
            args=["--target", "src/"],
            dry_run=True,
        )
        assert isinstance(result.args, list)
        # No single concatenated string anywhere in argv.
        for entry in result.args:
            assert isinstance(entry, str)


def test_invoke_bridge_real_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-dry-run path calls subprocess.run with shell=False."""
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Disable heartbeat for this test — we're verifying the argv path only.
    _common.invoke_bridge(
        "review-pr", args=["--pr", "1"], heartbeat_interval=None
    )
    assert captured["kwargs"]["shell"] is False
    assert "review-pr" in captured["argv"]


class TestInvokeBridgeHeartbeat:
    """Heartbeat emission during long-running bridge subprocesses.

    Defends against Kiro bash tools that abandon a long-silent subprocess
    before it completes. Discovered during the feedback-collector e2e on
    2026-05-25 when produce-tech-design took 7m38s and the hook bash was
    killed at ~3m37s, causing premature state advance.
    """

    @staticmethod
    def _make_sleep_run(sleep_sec: float):
        """A fake subprocess.run that sleeps before returning."""
        import time as _time

        def fake_run(argv, **kwargs):
            _time.sleep(sleep_sec)
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        return fake_run

    def test_heartbeat_emits_progress_during_long_subprocess(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A subprocess that runs ≥ 2 heartbeat intervals must produce ≥ 1
        ``BRIDGE_PROGRESS=`` marker on the wrapper's stdout."""
        monkeypatch.setattr(subprocess, "run", self._make_sleep_run(0.35))
        _common.invoke_bridge(
            "produce-tech-design",
            args=["--target", "x.md"],
            heartbeat_interval=0.1,
        )
        out = capsys.readouterr().out
        progress_lines = [
            line for line in out.splitlines() if line.startswith("BRIDGE_PROGRESS=")
        ]
        assert progress_lines, (
            f"expected BRIDGE_PROGRESS markers in wrapper stdout; got: {out!r}"
        )

    def test_heartbeat_marker_shape(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Marker format: ``BRIDGE_PROGRESS=verb=<v> elapsed=<N>s``."""
        monkeypatch.setattr(subprocess, "run", self._make_sleep_run(0.25))
        _common.invoke_bridge(
            "produce-tech-design",
            args=["--target", "x.md"],
            heartbeat_interval=0.1,
        )
        out = capsys.readouterr().out
        assert "BRIDGE_PROGRESS=verb=produce-tech-design" in out
        assert "elapsed=" in out
        assert "s" in out

    def test_heartbeat_disabled_when_interval_none(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``heartbeat_interval=None`` suppresses all progress markers."""
        monkeypatch.setattr(subprocess, "run", self._make_sleep_run(0.3))
        _common.invoke_bridge(
            "produce-tech-design",
            args=["--target", "x.md"],
            heartbeat_interval=None,
        )
        out = capsys.readouterr().out
        assert "BRIDGE_PROGRESS=" not in out

    def test_heartbeat_disabled_for_zero_interval(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``heartbeat_interval=0`` (or negative) also suppresses markers
        — defensive against accidental zero-division-like configs."""
        monkeypatch.setattr(subprocess, "run", self._make_sleep_run(0.2))
        _common.invoke_bridge(
            "produce-tech-design",
            args=["--target", "x.md"],
            heartbeat_interval=0.0,
        )
        out = capsys.readouterr().out
        assert "BRIDGE_PROGRESS=" not in out

    def test_heartbeat_skipped_for_background(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Background mode returns immediately — no heartbeats needed."""
        monkeypatch.setattr(subprocess, "run", self._make_sleep_run(0.25))
        _common.invoke_bridge(
            "reverse-engineer-kb",
            args=["--target", "x"],
            background=True,
            heartbeat_interval=0.1,
        )
        out = capsys.readouterr().out
        assert "BRIDGE_PROGRESS=" not in out

    def test_heartbeat_stops_after_subprocess_returns(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """After invoke_bridge returns, the heartbeat thread must stop
        — verified by waiting longer than the interval and checking no
        further markers appear."""
        import time as _time

        monkeypatch.setattr(subprocess, "run", self._make_sleep_run(0.2))
        _common.invoke_bridge(
            "produce-tech-design",
            args=["--target", "x.md"],
            heartbeat_interval=0.1,
        )
        capsys.readouterr()  # drain
        _time.sleep(0.25)  # would emit 2+ more if thread still alive
        out = capsys.readouterr().out
        assert "BRIDGE_PROGRESS=" not in out


# ---------------------------------------------------------------------------
# emit_terminal
# ---------------------------------------------------------------------------


class TestEmitTerminal:
    def test_writes_bare_token_with_lf(self, capsys: pytest.CaptureFixture[str]) -> None:
        _common.emit_terminal("HOOK_DONE")
        out = capsys.readouterr().out
        assert out == "HOOK_DONE\n"

    def test_no_equals_sign(self, capsys: pytest.CaptureFixture[str]) -> None:
        _common.emit_terminal("HOOK_INIT_DONE")
        out = capsys.readouterr().out
        assert "=" not in out


class TestEmitPropagateOutcome:
    """Granular ID_PROPAGATE marker per propagate_ids() yield."""

    def test_no_entries_emits_no_entries_marker(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = {"propagated": [], "unmapped": [], "threshold": 0.3}
        _common.emit_propagate_outcome(result, prd="prd.md", source="src.md")
        out = capsys.readouterr().out
        assert "ID_PROPAGATE_NO_ENTRIES=" in out
        assert "ID_PROPAGATED=" not in out
        assert "ID_PROPAGATE_ZERO_MATCHES=" not in out

    def test_zero_matches_emits_zero_matches_marker(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = {
            "propagated": [],
            "unmapped": ["FR-1", "FR-2"],
            "threshold": 0.3,
        }
        _common.emit_propagate_outcome(result, prd="prd.md", source="src.md")
        out = capsys.readouterr().out
        assert "ID_PROPAGATE_ZERO_MATCHES=" in out
        assert "2 entries parsed" in out
        assert "threshold=0.3" in out

    def test_propagated_emits_propagated_marker(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = {
            "propagated": [{"id": "FR-1", "line": 5}],
            "unmapped": ["FR-2"],
            "threshold": 0.3,
        }
        _common.emit_propagate_outcome(result, prd="prd.md", source="src.md")
        out = capsys.readouterr().out
        assert "ID_PROPAGATED=" in out
        assert "1 injected" in out
        assert "1 unmapped" in out


# ---------------------------------------------------------------------------
# State-md readers
# ---------------------------------------------------------------------------


class TestStateReaders:
    def test_read_current_phase(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "myslug", current_phase="2c")
        phase = _common.read_current_phase("myslug", dlc_root=dlc_root)
        assert phase == "2c"

    def test_read_current_phase_missing_slug(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        dlc_root.mkdir()
        assert _common.read_current_phase("nope", dlc_root=dlc_root) is None

    def test_read_pr_number(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "s", pr=42)
        assert _common.read_pr_number("s", dlc_root=dlc_root) == 42

    def test_read_pr_number_missing(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "s")  # no PR
        assert _common.read_pr_number("s", dlc_root=dlc_root) is None

    def test_read_branch(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "s", branch="feature/x")
        assert _common.read_branch("s", dlc_root=dlc_root) == "feature/x"

    def test_read_recent_decisions(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(
            dlc_root / "s",
            decisions=[
                "- [2026-05-22T10:00:00Z] First decision",
                "- [2026-05-22T11:00:00Z] Second decision",
                "- [2026-05-22T12:00:00Z] Third decision",
            ],
        )
        decisions = _common.read_recent_decisions("s", limit=2, dlc_root=dlc_root)
        assert len(decisions) == 2
        assert decisions[0].startswith("2026-05-22T10:00:00Z First")
        assert decisions[1].startswith("2026-05-22T11:00:00Z Second")


class TestSlugResolution:
    def test_resolve_slug_from_branch(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "foo", branch="feat/foo")
        make_state_md(dlc_root / "bar", branch="feat/bar")
        assert (
            _common.resolve_slug_from_branch("feat/foo", dlc_root=dlc_root)
            == "foo"
        )

    def test_resolve_slug_from_branch_none(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        dlc_root.mkdir()
        assert _common.resolve_slug_from_branch(None, dlc_root=dlc_root) is None

    def test_resolve_slug_no_match(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "foo", branch="feat/foo")
        assert (
            _common.resolve_slug_from_branch("feat/nope", dlc_root=dlc_root)
            is None
        )

    def test_find_slugs_for_pr_single(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "foo", pr=99)
        assert _common.find_slugs_for_pr(99, dlc_root=dlc_root) == ["foo"]

    def test_find_slugs_for_pr_multiple(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        make_state_md(dlc_root / "foo", pr=42)
        make_state_md(dlc_root / "bar", pr=42)
        results = _common.find_slugs_for_pr(42, dlc_root=dlc_root)
        assert set(results) == {"foo", "bar"}

    def test_find_slugs_for_pr_none(self, tmp_path: Path) -> None:
        dlc_root = tmp_path / ".dlc"
        dlc_root.mkdir()
        assert _common.find_slugs_for_pr(7, dlc_root=dlc_root) == []


# ---------------------------------------------------------------------------
# parse_bridge_json_field / surface_bridge_cached / list_status_files
# ---------------------------------------------------------------------------


class TestJSONFieldParsing:
    def test_jobid_extraction(self) -> None:
        stdout = '{"jobId":"abc-123","log":"C:/logs/x.log"}\n'
        assert _common.parse_bridge_json_field(stdout, "jobId") == "abc-123"
        assert _common.parse_bridge_json_field(stdout, "log") == "C:/logs/x.log"

    def test_missing_field(self) -> None:
        stdout = '{"foo":"bar"}'
        assert _common.parse_bridge_json_field(stdout, "jobId") is None

    def test_empty_stdout(self) -> None:
        assert _common.parse_bridge_json_field("", "jobId") is None

    def test_regex_fallback_for_partial_json(self) -> None:
        # Bridge sometimes emits envelope wrapped in marker lines.
        stdout = 'PROGRESS\n  Some text containing "jobId":"xyz" inline\n'
        assert _common.parse_bridge_json_field(stdout, "jobId") == "xyz"


class TestSurfaceBridgeCached:
    def test_found(self) -> None:
        out = "STAGE=init\nBRIDGE_CACHED=.dlc/foo/x.md\nDONE\n"
        assert _common.surface_bridge_cached(out) == ".dlc/foo/x.md"

    def test_missing(self) -> None:
        assert _common.surface_bridge_cached("nothing here") is None


class TestListStatusFiles:
    def test_empty_dir(self, tmp_path: Path) -> None:
        root = tmp_path / ".dlc"
        root.mkdir()
        assert _common.list_status_files(dlc_root=root) == []

    def test_lists_files(self, tmp_path: Path) -> None:
        root = tmp_path / ".dlc"
        jd = root / "_bridge-jobs"
        jd.mkdir(parents=True)
        (jd / "a.status.json").write_text("{}", encoding="utf-8")
        (jd / "b.status.json").write_text("{}", encoding="utf-8")
        # Non-status file should be ignored.
        (jd / "ignore.log").write_text("", encoding="utf-8")
        files = _common.list_status_files(dlc_root=root)
        assert len(files) == 2
        assert all(p.suffix == ".json" for p in files)


# ---------------------------------------------------------------------------
# dlc_root_for / emit_bridge_exit
# ---------------------------------------------------------------------------


def test_dlc_root_for_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert _common.dlc_root_for() == tmp_path / ".dlc"


def test_dlc_root_for_explicit(tmp_path: Path) -> None:
    assert _common.dlc_root_for(tmp_path) == tmp_path


def test_emit_bridge_exit(capsys: pytest.CaptureFixture[str]) -> None:
    _common.emit_bridge_exit(7)
    assert capsys.readouterr().out == "BRIDGE_EXIT=7\n"
