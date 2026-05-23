"""Test helpers shared by hook unit tests."""

from __future__ import annotations

from pathlib import Path


def make_state_md(
    slug_dir: Path,
    *,
    current_phase: str = "3",
    pr: int | None = None,
    branch: str | None = None,
    decisions: list[str] | None = None,
) -> Path:
    """Write a minimal state.md compatible with the v1.1 template parsing.

    Returns the path to the written file.
    """
    slug_dir.mkdir(parents=True, exist_ok=True)
    state_path = slug_dir / "state.md"
    lines = [
        f"# SDLC State — {slug_dir.name}",
        "",
        f"**Current phase:** {current_phase}",
        f"**Branch:** {branch or '(unknown)'}",
        f"**PR number:** #{pr}" if pr else "**PR number:** (none)",
        "",
        "## Phase status",
        "",
        "| Phase | Status | Started | Completed | Notes |",
        "|-------|--------|---------|-----------|-------|",
        f"| {current_phase} | in_progress |  |  |  |",
        "",
        "## Decisions Log",
        "",
    ]
    for d in decisions or []:
        lines.append(d)
    lines.append("")
    lines.append("## Escalation counter: 0")
    state_path.write_text("\n".join(lines), encoding="utf-8")
    return state_path
