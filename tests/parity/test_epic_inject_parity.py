"""FR-19 parity gate — FR-13 epic-inject.

Cross-language comparison of Python ``epic_inject.inject_epic_dir`` against
v1.1 ``epic-inject.ps1`` on two fixtures:

* ``fresh``         — fresh tasks.md, plan with 3 tasks (all inject)
* ``skip-existing`` — tasks.md already has ``## Epic 1`` header (skip-injection)

Both implementations are driven from the same plan + tasks.md.before; the
resulting tasks.md is compared byte-for-byte (after EOL/BOM normalization).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dlc_bridge.util.epic_inject import inject_epic_dir

from .conftest import normalize_eol, require_powershell, run_powershell


pytestmark = pytest.mark.parity


def _strip_bom(text: str) -> str:
    return text.lstrip("﻿")


def _normalize(text: str) -> str:
    return normalize_eol(_strip_bom(text))


def _ps_inject(plan_dir: Path, tasks_path: Path, repo_root: Path) -> str:
    """Run v1.1 ``epic-inject.ps1`` and return stdout."""
    script = repo_root / ".kiro" / "scripts" / "epic-inject.ps1"
    cp = run_powershell(
        [
            "-File", str(script),
            "-PlanDir", str(plan_dir),
            "-KiroTasks", str(tasks_path),
        ],
    )
    return cp.stdout


def _setup(fixture_dir: Path, name: str, tmp_path: Path) -> tuple[Path, Path]:
    """Copy a fixture into ``tmp_path/<name>/`` and return (plan_dir, tasks_path)."""
    target = tmp_path / name
    target.mkdir(parents=True, exist_ok=True)
    plan_dir = target / "plans"
    plan_dir.mkdir()
    for src in fixture_dir.glob("epic-*.plan.md"):
        shutil.copy2(src, plan_dir / src.name)
    tasks_path = target / "tasks.md"
    shutil.copy2(fixture_dir / "tasks.md.before", tasks_path)
    return plan_dir, tasks_path


FIXTURES = [
    ("fresh", 1, 0),
    ("skip-existing", 0, 1),
]


@require_powershell
@pytest.mark.parametrize(
    "name,expected_injected,expected_skipped",
    FIXTURES,
    ids=[f[0] for f in FIXTURES],
)
def test_epic_inject_matches_v1_1(
    name: str,
    expected_injected: int,
    expected_skipped: int,
    tmp_path: Path,
    fixtures_root: Path,
    repo_root: Path,
) -> None:
    """Python and v1.1 PS produce byte-equal tasks.md after epic injection."""
    fixture_dir = fixtures_root / "epic-inject" / name

    # Python side
    py_plan_dir, py_tasks = _setup(fixture_dir, "py", tmp_path)
    py_result = inject_epic_dir(py_plan_dir, py_tasks)
    assert py_result["injected"] == expected_injected
    assert py_result["skipped"] == expected_skipped

    # PowerShell side
    ps_plan_dir, ps_tasks = _setup(fixture_dir, "ps", tmp_path)
    ps_stdout = _ps_inject(ps_plan_dir, ps_tasks, repo_root)

    # 1. Modified tasks.md matches byte-for-byte
    py_text = _normalize(py_tasks.read_text(encoding="utf-8"))
    ps_text = _normalize(ps_tasks.read_text(encoding="utf-8"))
    assert py_text == ps_text, (
        f"Fixture {name!r}: tasks.md diverges after epic-inject.\n"
        f"Python output:\n{py_text}\n---\n"
        f"PowerShell output:\n{ps_text}"
    )

    # 2. PS emitted the matching summary marker
    expected_summary = (
        f"INJECT_SUMMARY=injected={expected_injected} "
        f"skipped={expected_skipped} failed=0"
    )
    assert expected_summary in ps_stdout, (
        f"Expected v1.1 PS to emit {expected_summary!r}; got stdout:\n{ps_stdout}"
    )


class TestEpicInjectRegression:
    """OS-agnostic regression tests — Python-only, run on every CI leg."""

    def test_fresh_injects_one_epic(
        self, tmp_path: Path, fixtures_root: Path
    ) -> None:
        plan_dir, tasks_path = _setup(
            fixtures_root / "epic-inject" / "fresh", "regression", tmp_path
        )
        result = inject_epic_dir(plan_dir, tasks_path)
        assert result["injected"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        tasks_md = tasks_path.read_text(encoding="utf-8")
        assert "## Epic 1" in tasks_md
        # All 3 tasks present as checkboxes
        for i in range(1, 4):
            assert f"- [ ] {i}. " in tasks_md

    def test_existing_epic_is_skipped(
        self, tmp_path: Path, fixtures_root: Path
    ) -> None:
        plan_dir, tasks_path = _setup(
            fixtures_root / "epic-inject" / "skip-existing", "regression", tmp_path
        )
        before = tasks_path.read_text(encoding="utf-8")
        result = inject_epic_dir(plan_dir, tasks_path)
        after = tasks_path.read_text(encoding="utf-8")
        assert result["injected"] == 0
        assert result["skipped"] == 1
        assert before == after  # idempotent — no write happened
