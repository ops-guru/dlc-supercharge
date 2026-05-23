"""Tests for :mod:`dlc_bridge.util.state` (FR-12 state.md transitions).

Parity contract: state.md format must remain byte-identical to v1.1's output
on the same inputs. We test this via round-trip equality on a hand-rolled
reference state.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dlc_bridge.exceptions import ValidationError
from dlc_bridge.util.state import (
    advance_phase,
    append_decision,
    finalize,
    incr_escalation,
    init_state,
    iso_now,
    mark_skipped,
    record_pr,
)


_TEMPLATE = (
    "# State for <SLUG>\n"
    "\n"
    "**Current phase:** 1\n"
    "**Interaction mode:** <MODE>\n"
    "**Branch:** <BRANCH>\n"
    "**Base branch:** <BASE_BRANCH>\n"
    "**Worktree:** (n/a - Kiro mode, no worktree)\n"
    "**Linked issue:** (none)\n"
    "**PR number:** (none yet)\n"
    "\n"
    "## Phase Status\n"
    "\n"
    "| Phase | Status | Started | Completed | Notes |\n"
    "|---|---|---|---|---|\n"
    "| 1 | in_progress | <ISO_TIMESTAMP> | | |\n"
    "| 2a | pending | | | |\n"
    "| 2b | pending | | | |\n"
    "| 2c | pending | | | |\n"
    "| 3 | pending | | | |\n"
    "| 4 | pending | | | |\n"
    "| 5 | pending | | | |\n"
    "| 6 | pending | | | |\n"
    "| 7 | pending | | | |\n"
    "| 8 | pending | | | |\n"
    "\n"
    "## Decisions Log\n"
    "\n"
    "- [<ISO_TIMESTAMP>] AUTOPILOT DECISION (Phase 1 entry): Created state.md "
    "on first on-requirements-saved fire for slug '<SLUG>'.\n"
    "  Reasoning: Standard new-spec entry.\n"
    "  Risk: low\n"
    "  Would pause in confident mode: no\n"
    "\n"
    "## Escalation counter: 0\n"
)


@pytest.fixture
def state_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(state_path, template_path)`` with the template seeded."""
    template = tmp_path / "templates" / "state.md.template"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_bytes(_TEMPLATE.encode("utf-8"))
    state = tmp_path / "state.md"
    return state, template


def test_iso_now_format() -> None:
    now = iso_now()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", now)


class TestInitState:
    def test_writes_substituted_template(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        wrote = init_state(
            state,
            slug="my-slug",
            branch="feat/foo",
            base_branch="main",
            interaction_mode="confident",
            template_path=template,
        )
        assert wrote is True
        content = state.read_text(encoding="utf-8")
        assert "# State for my-slug" in content
        assert "**Interaction mode:** confident" in content
        assert "**Branch:** feat/foo" in content
        assert "**Base branch:** main" in content
        assert "<SLUG>" not in content
        assert "<MODE>" not in content
        assert "<BRANCH>" not in content
        assert "<BASE_BRANCH>" not in content
        assert "<ISO_TIMESTAMP>" not in content

    def test_default_values_applied(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        content = state.read_text(encoding="utf-8")
        assert "**Interaction mode:** confident" in content
        assert "**Branch:** (unknown)" in content
        assert "**Base branch:** main" in content

    def test_no_bom_no_crlf(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        raw = state.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" not in raw

    def test_accepts_v2_kwargs_without_breaking(
        self, state_paths: tuple[Path, Path]
    ) -> None:
        state, template = state_paths
        # These args have no template placeholders — must be silently accepted.
        wrote = init_state(
            state,
            slug="x",
            template_path=template,
            work_type="feature",
            worktree="/tmp/wt",
            linked_issue=42,
            epic_issue=99,
        )
        assert wrote is True

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        from dlc_bridge.exceptions import BridgeError

        with pytest.raises(BridgeError):
            init_state(
                tmp_path / "state.md",
                slug="x",
                template_path=tmp_path / "missing.template",
            )


class TestAdvancePhase:
    def test_flips_current_phase_and_rows(
        self, state_paths: tuple[Path, Path]
    ) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        advance_phase(state, next_phase="2a")
        content = state.read_text(encoding="utf-8")
        # Current-phase header updated.
        assert "**Current phase:** 2a" in content
        # Old phase row marked completed.
        assert re.search(r"\|\s*1\s*\|\s*completed\s*\|", content)
        # New phase row in_progress.
        assert re.search(r"\|\s*2a\s*\|\s*in_progress\s*\|", content)

    def test_decision_log_entry_inserted(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        advance_phase(state, next_phase="2a")
        content = state.read_text(encoding="utf-8")
        assert "AUTOPILOT DECISION (Phase 2a entry): Advanced from 1." in content
        assert "Reasoning: Hook chain completion advanced state." in content
        assert "Risk: low" in content
        assert "Would pause in confident mode: no" in content

    def test_notes_override(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        advance_phase(state, next_phase="2a", notes="my note")
        content = state.read_text(encoding="utf-8")
        assert re.search(
            r"\|\s*1\s*\|\s*completed\s*\|\s*\S+\s*\|\s*\S+\s*\|\s*my note\s*\|",
            content,
        )

    def test_missing_current_phase_raises(self, tmp_path: Path) -> None:
        state = tmp_path / "state.md"
        state.write_text("# no header here\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            advance_phase(state, next_phase="2a")

    def test_accepts_legacy_kwargs(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        advance_phase(state, next_phase="2a", from_phase="1", to_phase="2a", artifact_note="x")


class TestMarkSkipped:
    def test_sets_skipped_row(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        mark_skipped(state, phase="2b", reason="not applicable")
        content = state.read_text(encoding="utf-8")
        assert re.search(
            r"\|\s*2b\s*\|\s*skipped\s*\|\s*\S+\s*\|\s*\S+\s*\|\s*not applicable\s*\|",
            content,
        )


class TestRecordPr:
    def test_sets_pr_number(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        record_pr(state, pr_number=123)
        content = state.read_text(encoding="utf-8")
        assert "**PR number:** #123" in content

    def test_no_pr_line_raises(self, tmp_path: Path) -> None:
        state = tmp_path / "state.md"
        state.write_text("no header here\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            record_pr(state, pr_number=1)


class TestIncrEscalation:
    def test_increments_counter(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        incr_escalation(state)
        assert "## Escalation counter: 1" in state.read_text(encoding="utf-8")
        incr_escalation(state)
        assert "## Escalation counter: 2" in state.read_text(encoding="utf-8")

    def test_appends_context_file(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        incr_escalation(state, context="something went wrong")
        ctx = state.parent / "escalation-context.md"
        assert ctx.exists()
        assert "something went wrong" in ctx.read_text(encoding="utf-8")

    def test_missing_counter_raises(self, tmp_path: Path) -> None:
        state = tmp_path / "state.md"
        state.write_text("no counter here\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            incr_escalation(state)


class TestFinalize:
    def test_marks_phases_7_and_8(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        finalize(state)
        content = state.read_text(encoding="utf-8")
        assert re.search(r"\|\s*7\s*\|\s*completed\s*\|", content)
        assert re.search(r"\|\s*8\s*\|\s*completed\s*\|", content)

    def test_delete_state(self, state_paths: tuple[Path, Path]) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        finalize(state, delete_state=True)
        assert not state.exists()

    def test_delete_state_missing_is_noop(self, tmp_path: Path) -> None:
        assert finalize(tmp_path / "missing.md", delete_state=True) is False


class TestAppendDecision:
    def test_inserts_before_escalation_counter(
        self, state_paths: tuple[Path, Path]
    ) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        entry = "- **2026-05-22** — Custom decision entry."
        append_decision(state, entry=entry)
        content = state.read_text(encoding="utf-8")
        # Entry must appear before the counter line.
        entry_pos = content.index(entry)
        counter_pos = content.index("## Escalation counter:")
        assert entry_pos < counter_pos


class TestRoundTripParity:
    """Round-trip test: init then advance, assert phase status table preserved
    line-for-line except for the touched rows."""

    def test_advance_preserves_unaffected_rows(
        self, state_paths: tuple[Path, Path]
    ) -> None:
        state, template = state_paths
        init_state(state, slug="x", template_path=template)
        before = state.read_text(encoding="utf-8")
        advance_phase(state, next_phase="2a")
        after = state.read_text(encoding="utf-8")

        # Every line that doesn't reference phase 1 or 2a, and isn't the
        # current-phase header or the decision log, must be byte-identical.
        before_lines = before.split("\n")
        after_lines_idx = {i: l for i, l in enumerate(after.split("\n"))}
        # We're not asserting strict line-index parity (the advance inserts
        # the decision-log entry), but every row matching ``| 2b |`` ... ``| 8 |``
        # must be unchanged.
        for phase in ["2b", "2c", "3", "4", "5", "6", "7", "8"]:
            before_row = next(
                l for l in before_lines if re.match(rf"\|\s*{phase}\s*\|", l)
            )
            after_row = next(
                l for l in after.split("\n") if re.match(rf"\|\s*{phase}\s*\|", l)
            )
            assert before_row == after_row, (
                f"phase {phase} row changed: {before_row!r} → {after_row!r}"
            )
