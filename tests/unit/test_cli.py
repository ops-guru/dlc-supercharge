"""Unit tests for ``dlc_bridge.cli`` (FR-1, FR-3, FR-5, WI-17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.cli import main


pytestmark = pytest.mark.unit


# --- help + verb dispatch ---------------------------------------------------


def test_cli_help_verb_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    """`dlc-bridge help` should exit 0 and list every supported verb."""
    rc = main(["help"])
    assert rc == 0
    out = capsys.readouterr().out
    # All 16 verbs should appear in the banner.
    for verb in (
        "analyze-requirements",
        "produce-tech-design",
        "plan-implementation",
        "finalize-sdlc",
        "discover",
        "review-pr",
        "stabilize-pr",
        "review-security",
        "review-ux",
        "review-a11y",
        "review-performance",
        "reverse-engineer-kb",
        "kb-gap-analysis",
        "map-codebase",
        "babysit-pr",
        "hotfix",
    ):
        assert verb in out


def test_cli_unknown_verb_exits_4(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown verb must exit 4 with a diagnostic on stderr."""
    rc = main(["totally-not-a-verb"])
    assert rc == 4
    err = capsys.readouterr().err
    assert "Unknown verb" in err or "invalid choice" in err


def test_cli_no_args_exits_4(capsys: pytest.CaptureFixture[str]) -> None:
    """Missing positional verb must surface as exit 4, not argparse exit 2."""
    rc = main([])
    assert rc == 4


# --- dry-run JSON envelope (FR-5) ------------------------------------------


def test_cli_dry_run_emits_json(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
) -> None:
    """`--dry-run` must emit a JSON envelope with the FR-5 keys and exit 0."""
    rc = main(["analyze-requirements", "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    # Schema contract from tech-design Section 10.2 (WI-2 / FR-5).
    for key in ("status", "verb", "skillPath", "command", "args", "assembledPrompt"):
        assert key in payload, f"missing key '{key}' in dry-run envelope"
    assert payload["status"] == "dry-run"
    assert payload["verb"] == "analyze-requirements"
    assert payload["command"] == "claude"
    assert isinstance(payload["args"], list)
    assert "-p" in payload["args"]
    assert "--append-system-prompt-file" in payload["args"]
    # The fake fixture lives under tests/fixtures/fake_plugin_cache/...
    assert payload["skillPath"].endswith("SKILL.md")


def test_cli_dry_run_propagates_budget_to_args(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
) -> None:
    """``--max-budget-usd`` should appear in the assembled ``args`` list."""
    rc = main(["analyze-requirements", "--dry-run", "--max-budget-usd", "7.5"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "--max-budget-usd" in payload["args"]
    idx = payload["args"].index("--max-budget-usd")
    assert payload["args"][idx + 1] == "7.5"


# --- live dispatch (Epic 2b WI-16: real claude subprocess invocation) -------


def test_cli_live_dispatch_invokes_claude(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live dispatch (Epic 2b WI-16) invokes claude and emits BRIDGE_OK on success.

    A mocked ``subprocess.run`` stands in for ``claude``; verifies the
    EXIT_NOT_IMPLEMENTED sentinel from Epic 1 has been REMOVED.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".dlc").mkdir()

    import subprocess
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        # Mimic CompletedProcess with empty stdout/stderr and rc=0.
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("dlc_bridge.cli.subprocess.run", fake_run)

    rc = main(["analyze-requirements"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BRIDGE_EXIT=0" in out
    assert calls, "subprocess.run should have been called at least once"
    # Argv must be a LIST (not a string) and start with 'claude -p ...'.
    assert isinstance(calls[0], list)
    assert calls[0][0] == "claude"
    assert "-p" in calls[0]
    assert "--append-system-prompt-file" in calls[0]
    assert "--permission-mode" in calls[0]
    assert "bypassPermissions" in calls[0]


def test_cli_live_dispatch_does_not_emit_not_implemented(
    capsys: pytest.CaptureFixture[str],
    plugin_cache_root_mock: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Epic 1 EXIT_NOT_IMPLEMENTED sentinel must no longer be emitted."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".dlc").mkdir()

    import subprocess
    monkeypatch.setattr(
        "dlc_bridge.cli.subprocess.run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    rc = main(["analyze-requirements"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "NOT_IMPLEMENTED" not in err


# --- path-traversal validation (FR-3, WI-17) -------------------------------


def test_cli_path_traversal_source_exits_4(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    """`--source ../../etc/passwd` must exit 4."""
    monkeypatch.chdir(tmp_path)
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--source",
        "../../etc/passwd",
    ])
    assert rc == 4
    assert "resolves above project root" in capsys.readouterr().err


def test_cli_path_traversal_target_exits_4(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    """`--target ../../etc/passwd` must exit 4."""
    monkeypatch.chdir(tmp_path)
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--target",
        "../../foo",
    ])
    assert rc == 4
    assert "resolves above project root" in capsys.readouterr().err


def test_cli_relative_source_under_root_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    """A relative source under CWD must NOT trigger the traversal guard."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.md").write_text("x", encoding="utf-8", newline="\n")
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--source",
        "requirements.md",
    ])
    assert rc == 0


def test_cli_absolute_source_under_root_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_cache_root_mock: Path,
) -> None:
    """An absolute path that is still under CWD must be accepted."""
    monkeypatch.chdir(tmp_path)
    sub = tmp_path / "sub" / "doc.md"
    sub.parent.mkdir()
    sub.write_text("x", encoding="utf-8", newline="\n")
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--source",
        str(sub),
    ])
    assert rc == 0


# --- numeric range validation (FR-3) ---------------------------------------


def test_cli_max_files_too_low_exits_4(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--max-files 0` is below the documented floor (1)."""
    rc = main(["analyze-requirements", "--dry-run", "--max-files", "0"])
    assert rc == 4


def test_cli_max_files_too_high_exits_4(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--max-files 9999` is above the documented ceiling (5000)."""
    rc = main(["analyze-requirements", "--dry-run", "--max-files", "9999"])
    assert rc == 4


def test_cli_max_budget_negative_exits_4(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--max-budget-usd -1` is below the documented floor (0.0)."""
    rc = main(["analyze-requirements", "--dry-run", "--max-budget-usd", "-1"])
    assert rc == 4


def test_cli_max_budget_too_high_exits_4(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--max-budget-usd 60` is above the documented ceiling (50.0)."""
    rc = main(["analyze-requirements", "--dry-run", "--max-budget-usd", "60"])
    assert rc == 4


def test_cli_pr_must_be_positive(capsys: pytest.CaptureFixture[str]) -> None:
    """`--pr 0` must exit 4 — PR numbers are strictly positive."""
    rc = main(["analyze-requirements", "--dry-run", "--pr", "0"])
    assert rc == 4


def test_cli_pr_negative_exits_4(capsys: pytest.CaptureFixture[str]) -> None:
    """`--pr -5` must exit 4."""
    rc = main(["analyze-requirements", "--dry-run", "--pr", "-5"])
    assert rc == 4


def test_cli_cache_max_age_negative_exits_4() -> None:
    """`--cache-max-age-hours -1` must exit 4 (must be >= 0)."""
    rc = main([
        "analyze-requirements",
        "--dry-run",
        "--cache-max-age-hours",
        "-1",
    ])
    assert rc == 4


def test_cli_mode_invalid_exits_4() -> None:
    """`--mode bogus` must exit 4 (enum mismatch)."""
    rc = main(["analyze-requirements", "--dry-run", "--mode", "bogus"])
    assert rc == 4


def test_cli_mode_valid_accepted(plugin_cache_root_mock: Path) -> None:
    """All three documented modes must parse without error."""
    for mode in ("interactive", "confident", "autopilot"):
        rc = main([
            "analyze-requirements",
            "--dry-run",
            "--mode",
            mode,
        ])
        assert rc == 0, f"mode '{mode}' should be accepted"


# --- background / no-cache flags pass-through -------------------------------


def test_cli_background_flag_accepted(
    plugin_cache_root_mock: Path,
) -> None:
    """`--background` is accepted in Epic 1 (full impl Epic 2 WI-18)."""
    rc = main(["analyze-requirements", "--dry-run", "--background"])
    assert rc == 0


def test_cli_no_cache_flag_accepted(plugin_cache_root_mock: Path) -> None:
    """`--no-cache` is accepted in Epic 1."""
    rc = main(["analyze-requirements", "--dry-run", "--no-cache"])
    assert rc == 0
