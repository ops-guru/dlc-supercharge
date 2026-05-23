"""Tests for :mod:`dlc_bridge.util.epic_inject` (FR-13 epic plan injection)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.util.epic_inject import (
    _parse_plan,
    inject_epic,
    inject_epic_dir,
)


_EM_DASH = "—"
_EN_DASH = "–"


def _write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.encode("utf-8"))
    return p


@pytest.fixture
def plan_factory(tmp_path: Path):
    """Build (plan_path, tasks_path) pairs for injection tests."""
    def factory(plan_content: str, tasks_content: str, plan_name: str = "epic-002.plan.md"):
        plan_dir = tmp_path / "plans"
        plan = _write(plan_dir / plan_name, plan_content)
        tasks = _write(tmp_path / "tasks.md", tasks_content)
        return plan, tasks
    return factory


_BASE_PLAN = (
    "---\n"
    "title: \"Epic 2 — Implementation\"\n"
    "epic: 2\n"
    "scope_items: [WI-3, WI-4, WI-5]\n"
    "depends_on_prior_epics: [1]\n"
    "---\n"
    "\n"
    "# Epic 2 — Implementation\n"
    "\n"
    "### T-1 — First task\n"
    "Lorem ipsum.\n"
    "\n"
    "### T-2 — Second task\n"
    "Dolor sit amet.\n"
)

_BASE_TASKS = (
    "# Tasks for slug\n"
    "\n"
    "## Epic 1 — Foundation\n"
    "\n"
    "Scope: WI-1, WI-2.\n"
    "\n"
    "- [ ] 1. Bootstrap package\n"
)


class TestParsePlan:
    def test_extracts_frontmatter_fields(self, plan_factory) -> None:
        plan, _ = plan_factory(_BASE_PLAN, _BASE_TASKS)
        parsed = _parse_plan(plan)
        assert parsed is not None
        assert parsed["number"] == 2
        assert parsed["title"] == "Epic 2 — Implementation"
        assert parsed["scope_items"] == ["WI-3", "WI-4", "WI-5"]
        assert parsed["depends_on"] == ["1"]
        assert len(parsed["tasks"]) == 2
        assert parsed["tasks"][0]["number"] == 1
        assert parsed["tasks"][1]["title"] == "Second task"

    def test_accepts_en_dash_in_task_heading(self, plan_factory) -> None:
        content = (
            "---\nepic: 3\n---\n\n"
            f"### T-1 {_EN_DASH} En-dash task\n"
        )
        plan, _ = plan_factory(content, _BASE_TASKS, plan_name="epic-003.plan.md")
        parsed = _parse_plan(plan)
        assert parsed is not None
        assert parsed["tasks"][0]["title"] == "En-dash task"

    def test_accepts_hyphen_in_task_heading(self, plan_factory) -> None:
        content = (
            "---\nepic: 4\n---\n\n"
            "### T-1 - ASCII hyphen task\n"
        )
        plan, _ = plan_factory(content, _BASE_TASKS, plan_name="epic-004.plan.md")
        parsed = _parse_plan(plan)
        assert parsed is not None
        assert parsed["tasks"][0]["title"] == "ASCII hyphen task"

    def test_accepts_em_dash_in_task_heading(self, plan_factory) -> None:
        content = (
            "---\nepic: 5\n---\n\n"
            f"### T-1 {_EM_DASH} Em-dash task\n"
        )
        plan, _ = plan_factory(content, _BASE_TASKS, plan_name="epic-005.plan.md")
        parsed = _parse_plan(plan)
        assert parsed is not None
        assert parsed["tasks"][0]["title"] == "Em-dash task"

    def test_epic_number_from_filename_fallback(self, tmp_path: Path) -> None:
        # Frontmatter without ``epic:`` — number comes from filename.
        plan = tmp_path / "epic-007.plan.md"
        plan.write_text(
            "---\ntitle: x\n---\n\n### T-1 - task\n", encoding="utf-8"
        )
        parsed = _parse_plan(plan)
        assert parsed is not None
        assert parsed["number"] == 7

    def test_no_tasks_returns_none(self, plan_factory) -> None:
        content = "---\nepic: 9\n---\n\nNo tasks here.\n"
        plan, _ = plan_factory(content, _BASE_TASKS, plan_name="epic-009.plan.md")
        assert _parse_plan(plan) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _parse_plan(tmp_path / "missing.md") is None


class TestInjectEpic:
    def test_injects_new_epic(self, plan_factory) -> None:
        plan, tasks = plan_factory(_BASE_PLAN, _BASE_TASKS)
        result = inject_epic(plan, tasks)
        assert result["status"] == "injected"
        assert result["epic"] == 2
        assert result["write"] == "written"
        content = tasks.read_text(encoding="utf-8")
        assert "## Epic 2 — Implementation" in content
        assert "Scope: WI-3, WI-4, WI-5." in content
        assert "Depends on Epics 1." in content
        assert "- [ ] 1. First task" in content
        assert "- [ ] 2. Second task" in content

    def test_skips_existing_epic(self, plan_factory) -> None:
        # tasks.md already has ``## Epic 2``.
        plan_content = _BASE_PLAN
        existing_tasks = _BASE_TASKS + "\n## Epic 2 — Already present\n"
        plan, tasks = plan_factory(plan_content, existing_tasks)
        before = tasks.read_bytes()
        result = inject_epic(plan, tasks)
        assert result["status"] == "skipped"
        # No write occurred.
        assert tasks.read_bytes() == before

    def test_idempotent_re_inject(self, plan_factory) -> None:
        plan, tasks = plan_factory(_BASE_PLAN, _BASE_TASKS)
        inject_epic(plan, tasks)
        snapshot = tasks.read_bytes()
        # Second invocation sees the epic now exists in tasks.md → skips.
        result = inject_epic(plan, tasks)
        assert result["status"] == "skipped"
        assert tasks.read_bytes() == snapshot

    def test_parse_failure_returns_failed(self, tmp_path: Path) -> None:
        bad = tmp_path / "epic-010.plan.md"
        bad.write_text("totally malformed\n", encoding="utf-8")
        tasks = tmp_path / "tasks.md"
        tasks.write_text(_BASE_TASKS, encoding="utf-8")
        result = inject_epic(bad, tasks)
        assert result["status"] == "parse_failed"

    def test_dry_run_no_write(self, plan_factory) -> None:
        plan, tasks = plan_factory(_BASE_PLAN, _BASE_TASKS)
        before = tasks.read_bytes()
        result = inject_epic(plan, tasks, dry_run=True)
        assert result["status"] == "injected"
        assert result["write"] == "dry_run"
        assert tasks.read_bytes() == before


class TestInjectEpicDir:
    def test_batch_injects_multiple_epics(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        _write(
            plan_dir / "epic-002.plan.md",
            _BASE_PLAN,
        )
        _write(
            plan_dir / "epic-003.plan.md",
            "---\nepic: 3\n---\n\n### T-1 - Third epic task\n",
        )
        tasks = _write(tmp_path / "tasks.md", _BASE_TASKS)
        result = inject_epic_dir(plan_dir, tasks)
        assert result["injected"] == 2
        assert result["skipped"] == 0
        assert result["failed"] == 0
        content = tasks.read_text(encoding="utf-8")
        assert "## Epic 2" in content
        assert "## Epic 3" in content

    def test_skips_already_present(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        _write(plan_dir / "epic-002.plan.md", _BASE_PLAN)
        tasks = _write(
            tmp_path / "tasks.md",
            _BASE_TASKS + "\n## Epic 2 — already\n",
        )
        result = inject_epic_dir(plan_dir, tasks)
        assert result["injected"] == 0
        assert result["skipped"] == 1

    def test_empty_plan_dir(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        tasks = _write(tmp_path / "tasks.md", _BASE_TASKS)
        result = inject_epic_dir(plan_dir, tasks)
        assert result["injected"] == 0

    def test_missing_plan_dir(self, tmp_path: Path) -> None:
        tasks = _write(tmp_path / "tasks.md", _BASE_TASKS)
        result = inject_epic_dir(tmp_path / "nonexistent", tasks)
        assert result["failed"] == 1

    def test_missing_tasks_file(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        _write(plan_dir / "epic-002.plan.md", _BASE_PLAN)
        result = inject_epic_dir(plan_dir, tmp_path / "missing.md")
        assert result["failed"] == 1

    def test_idempotent_batch(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        _write(plan_dir / "epic-002.plan.md", _BASE_PLAN)
        tasks = _write(tmp_path / "tasks.md", _BASE_TASKS)
        inject_epic_dir(plan_dir, tasks)
        snapshot = tasks.read_bytes()
        inject_epic_dir(plan_dir, tasks)
        assert tasks.read_bytes() == snapshot
