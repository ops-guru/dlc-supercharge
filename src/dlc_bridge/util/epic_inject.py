"""FR-13 epic plan injection into Kiro tasks.md.

Port of v1.1 ``epic-inject.ps1``. Reads epic plan files
(``.dlc/<slug>/plans/epic-NNN.plan.md``) with YAML-ish frontmatter and appends
new ``## Epic N`` sections to a Kiro spec ``tasks.md`` if they are not already
present.

Idempotent: existing ``## Epic <N>`` sections (regardless of completion-marker
state) are left untouched. Byte-equality guard prevents needless writes.
"""

from __future__ import annotations

import re
from pathlib import Path

from dlc_bridge.util.emit import emit_marker
from dlc_bridge.util.encoding import atomic_write_bytes, read_text_utf8

__all__ = ["inject_epic", "inject_epic_dir"]


# Dash character class: em-dash (U+2014), en-dash (U+2013), ASCII hyphen.
_DASH_CLASS = "[—–\\-]"

_FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.+?)\r?\n---\s*\r?\n", re.DOTALL)
_TITLE_RE = re.compile(r'^title:\s*"?([^"\r\n]+?)"?\s*$', re.MULTILINE)
_EPIC_NUM_RE = re.compile(r"^epic:\s*(\d+)\s*$", re.MULTILINE)
_SCOPE_ITEMS_RE = re.compile(r"^scope_items:\s*\[(.+?)\]\s*$", re.MULTILINE)
_DEPENDS_RE = re.compile(r"^depends_on_prior_epics:\s*\[(.*?)\]\s*$", re.MULTILINE)

_TASK_HEADING_RE = re.compile(
    rf"(?m)^###\s+T-(\d+)\s+{_DASH_CLASS}\s+(.+?)\s*$"
)
_EXISTING_EPIC_RE = re.compile(r"(?m)^##\s+Epic\s+(\d+)\b")
_TITLE_PREFIX_RE = re.compile(rf"^Epic\s+\d+\s+{_DASH_CLASS}")
_EPIC_FILENAME_RE = re.compile(r"^epic-0*(\d+)\.plan$")


def _parse_plan(plan_path: Path) -> dict | None:
    """Parse an epic plan file. Returns ``None`` on parse failure.

    Output keys: ``number`` (int), ``title`` (str), ``scope_items`` (list[str]),
    ``depends_on`` (list[str]), ``tasks`` (list of ``{number, title}`` dicts).
    """
    if not plan_path.exists():
        return None
    text = read_text_utf8(plan_path)

    title: str | None = None
    epic_number: int | None = None
    scope_items: list[str] = []
    depends_on: list[str] = []

    fm = _FRONTMATTER_RE.match(text)
    if fm:
        fm_text = fm.group(1)
        t_m = _TITLE_RE.search(fm_text)
        if t_m:
            title = t_m.group(1).strip()
        n_m = _EPIC_NUM_RE.search(fm_text)
        if n_m:
            epic_number = int(n_m.group(1))
        s_m = _SCOPE_ITEMS_RE.search(fm_text)
        if s_m:
            scope_items = [
                p.strip() for p in s_m.group(1).split(",") if p.strip()
            ]
        d_m = _DEPENDS_RE.search(fm_text)
        if d_m:
            depends_on = [
                p.strip() for p in d_m.group(1).split(",") if p.strip()
            ]

    # Fallbacks: epic number from filename, title from H1 heading.
    if epic_number is None:
        base = plan_path.stem  # e.g. "epic-002.plan"
        fn_m = _EPIC_FILENAME_RE.match(base)
        if fn_m:
            epic_number = int(fn_m.group(1))
    if title is None:
        h1_re = re.compile(
            rf"(?m)^#\s+(Epic\s+\d+\s+{_DASH_CLASS}\s+.+?)\s*$"
        )
        h1_m = h1_re.search(text)
        if h1_m:
            title = h1_m.group(1).strip()

    tasks: list[dict] = []
    for m in _TASK_HEADING_RE.finditer(text):
        tasks.append(
            {"number": int(m.group(1)), "title": m.group(2).strip()}
        )

    if epic_number is None or not tasks:
        return None
    return {
        "path": plan_path,
        "number": epic_number,
        "title": title if title else f"Epic {epic_number}",
        "scope_items": scope_items,
        "depends_on": depends_on,
        "tasks": tasks,
    }


def _format_epic_section(plan: dict) -> str:
    """Render a plan dict as a markdown ``## Epic N — Title`` section."""
    em_dash = "—"
    title = plan["title"]
    if _TITLE_PREFIX_RE.match(title):
        header = f"## {title}"
    else:
        header = f"## Epic {plan['number']} {em_dash} {title}"
    lines: list[str] = [header, ""]

    scope_bits: list[str] = []
    if plan["scope_items"]:
        scope_bits.append("Scope: " + ", ".join(plan["scope_items"]) + ".")
    if plan["depends_on"]:
        scope_bits.append(
            "Depends on Epics " + ", ".join(plan["depends_on"]) + "."
        )
    if scope_bits:
        lines.append(" ".join(scope_bits))
        lines.append("")

    for t in sorted(plan["tasks"], key=lambda x: x["number"]):
        lines.append(f"- [ ] {t['number']}. {t['title']}")
    lines.append("")
    return "\n".join(lines)


def inject_epic(plan_path: Path, tasks_path: Path, *, dry_run: bool = False) -> dict:
    """Inject a single epic plan into ``tasks_path``.

    Returns a dict with keys ``status`` (``injected`` / ``skipped`` /
    ``parse_failed``), ``epic`` (int or None), ``tasks`` (int task count), and
    ``write`` (``written`` / ``identical`` / ``dry_run``).
    """
    plan = _parse_plan(Path(plan_path))
    if plan is None:
        emit_marker("EPIC_PARSE_FAILED", Path(plan_path).name)
        return {
            "status": "parse_failed",
            "epic": None,
            "tasks": 0,
            "write": "skipped",
        }

    tasks_text = read_text_utf8(Path(tasks_path))
    existing = {int(m.group(1)) for m in _EXISTING_EPIC_RE.finditer(tasks_text)}

    if plan["number"] in existing:
        emit_marker(
            "EPIC_SKIPPED", f"{plan['number']} (already in tasks.md)"
        )
        return {
            "status": "skipped",
            "epic": plan["number"],
            "tasks": len(plan["tasks"]),
            "write": "skipped",
        }

    section = _format_epic_section(plan)
    existing_norm = tasks_text.replace("\r\n", "\n")
    existing_trimmed = existing_norm.rstrip("\n") + "\n\n"
    new_content = existing_trimmed + section
    new_content = new_content.rstrip("\n") + "\n"

    write_status = "dry_run"
    if not dry_run:
        wrote = atomic_write_bytes(Path(tasks_path), new_content.encode("utf-8"))
        if wrote:
            emit_marker("WRITE", str(tasks_path))
            write_status = "written"
        else:
            emit_marker("WRITE_SKIPPED", "identical content")
            write_status = "identical"

    emit_marker("EPIC_INJECTED", f"{plan['number']} tasks={len(plan['tasks'])}")
    return {
        "status": "injected",
        "epic": plan["number"],
        "tasks": len(plan["tasks"]),
        "write": write_status,
    }


def inject_epic_dir(plan_dir: Path, tasks_path: Path, *, dry_run: bool = False) -> dict:
    """Inject every ``epic-*.plan.md`` under ``plan_dir`` into ``tasks_path``.

    Iterates plan files in lexical order, accumulates new epic sections, then
    appends them in a single atomic write at the end. Mirrors v1.1's batch
    behaviour so the on-saved hook fires at most once per invocation.

    Returns a summary dict ``{injected, skipped, failed, write}``.
    """
    plan_dir = Path(plan_dir)
    tasks_path = Path(tasks_path)

    if not plan_dir.is_dir():
        emit_marker("ERROR", f"PlanDir not found: {plan_dir}")
        return {"injected": 0, "skipped": 0, "failed": 1, "write": "skipped"}
    if not tasks_path.is_file():
        emit_marker("ERROR", f"KiroTasks not found: {tasks_path}")
        return {"injected": 0, "skipped": 0, "failed": 1, "write": "skipped"}

    plan_files = sorted(plan_dir.glob("epic-*.plan.md"))
    if not plan_files:
        emit_marker("INJECT_SUMMARY", "injected=0 skipped=0 failed=0")
        return {"injected": 0, "skipped": 0, "failed": 0, "write": "skipped"}

    tasks_text = read_text_utf8(tasks_path)
    existing = {int(m.group(1)) for m in _EXISTING_EPIC_RE.finditer(tasks_text)}

    injected = 0
    skipped = 0
    failed = 0
    append_blocks: list[str] = []

    for pf in plan_files:
        plan = _parse_plan(pf)
        if plan is None:
            emit_marker("EPIC_PARSE_FAILED", pf.name)
            failed += 1
            continue
        if plan["number"] in existing:
            emit_marker(
                "EPIC_SKIPPED",
                f"{plan['number']} (already in tasks.md)",
            )
            skipped += 1
            continue
        append_blocks.append(_format_epic_section(plan))
        emit_marker(
            "EPIC_INJECTED",
            f"{plan['number']} tasks={len(plan['tasks'])}",
        )
        injected += 1

    write_status = "skipped"
    if injected > 0 and not dry_run:
        existing_norm = tasks_text.replace("\r\n", "\n")
        existing_trimmed = existing_norm.rstrip("\n") + "\n\n"
        appended = "\n".join(append_blocks).replace("\r\n", "\n")
        new_content = existing_trimmed + appended
        new_content = new_content.rstrip("\n") + "\n"
        wrote = atomic_write_bytes(tasks_path, new_content.encode("utf-8"))
        if wrote:
            emit_marker("WRITE", str(tasks_path))
            write_status = "written"
        else:
            emit_marker("WRITE_SKIPPED", "identical content")
            write_status = "identical"

    emit_marker(
        "INJECT_SUMMARY",
        f"injected={injected} skipped={skipped} failed={failed}",
    )
    return {
        "injected": injected,
        "skipped": skipped,
        "failed": failed,
        "write": write_status,
    }
