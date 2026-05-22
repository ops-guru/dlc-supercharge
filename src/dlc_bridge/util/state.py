"""FR-12 state.md transitions.

Port of v1.1 ``state-update.ps1`` (atomic ``state.md`` operations). The on-disk
format is the **byte-identical contract** — every line, every column, every
trailing-newline behaviour must match v1.1 so the parallel orchestrator
continues to parse the file the same way.

Operations mirror v1.1 verbs:

* :func:`init_state` — render the template with substitution placeholders
* :func:`advance_phase` — flip current-phase header + phase-status rows; append decision-log entry
* :func:`mark_skipped` — mark a phase as ``skipped``
* :func:`record_pr` — set the ``**PR number:** #N`` line
* :func:`incr_escalation` — bump the ``## Escalation counter:`` integer
* :func:`finalize` — close out phases 7+8 (or delete the file)
* :func:`append_decision` — insert a decision-log entry before the escalation counter (v2 extension)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from dlc_bridge.exceptions import BridgeError, ValidationError
from dlc_bridge.util.encoding import (
    atomic_write_utf8_lf,
    read_text_utf8,
)

__all__ = [
    "init_state",
    "advance_phase",
    "mark_skipped",
    "record_pr",
    "incr_escalation",
    "finalize",
    "append_decision",
    "iso_now",
]


# Default template path relative to the workspace root containing the state file.
_DEFAULT_TEMPLATE_REL = Path(".kiro/powers/dlc-supercharge/templates/state.md.template")

# Regexes mirror v1.1 byte-for-byte (see state-update.ps1).
_CURRENT_PHASE_RE = re.compile(r"^\*\*Current phase:\*\*\s+(\S+)\s*$")
_PHASE_ROW_RE = re.compile(
    r"^\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$"
)
_ESCALATION_RE = re.compile(r"^## Escalation counter:\s*(\d+)")
_PR_NUMBER_RE = re.compile(r"^\*\*PR number:\*\*")


def iso_now() -> str:
    """Return ISO-8601 UTC timestamp ``YYYY-MM-DDTHH:MM:SSZ``.

    Matches v1.1's ``(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')``.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_template(state_path: Path, template_path: Path | None) -> Path:
    """Locate the ``state.md.template``.

    If ``template_path`` is explicit, return it. Otherwise walk parents of
    ``state_path`` looking for ``.kiro/powers/dlc-supercharge/templates/state.md.template``.
    """
    if template_path is not None:
        explicit = Path(template_path)
        if not explicit.exists():
            raise BridgeError(
                f"state.md template not found at explicit path {explicit}"
            )
        return explicit
    candidate = state_path
    # Walk up to the filesystem root looking for the template directory.
    for parent in [candidate, *candidate.parents]:
        guess = parent / _DEFAULT_TEMPLATE_REL
        if guess.exists():
            return guess
    raise BridgeError(
        f"state.md template not found; searched parents of {state_path} for "
        f"{_DEFAULT_TEMPLATE_REL}"
    )


def init_state(
    path: Path,
    *,
    slug: str,
    branch: str | None = None,
    base_branch: str | None = None,
    interaction_mode: str | None = None,
    template_path: Path | None = None,
    # Accepted-and-ignored v2 kwargs (no v1.1 template placeholders for these):
    work_type: str | None = None,
    worktree: str | None = None,
    linked_issue: int | None = None,
    epic_issue: int | None = None,
) -> bool:
    """Render the v1.1 ``state.md`` template and write atomically.

    Recognised template placeholders:

    * ``<SLUG>`` ← ``slug``
    * ``<MODE>`` ← ``interaction_mode`` (default ``"confident"``)
    * ``<BRANCH>`` ← ``branch`` (default ``"(unknown)"``)
    * ``<BASE_BRANCH>`` ← ``base_branch`` (default ``"main"``)
    * ``<ISO_TIMESTAMP>`` ← :func:`iso_now`

    Any other kwargs are accepted (so the caller can match the brief's
    forward-compatible signature) but are not substituted because the v1.1
    template doesn't declare placeholders for them. Adding new placeholders
    would break byte-parity with v1.1 — Epic 4 (docs/v2 schema) is the right
    place to extend.

    :returns: ``True`` if a write occurred, ``False`` on idempotent no-op.
    """
    # ``work_type``, ``worktree``, ``linked_issue``, ``epic_issue`` are
    # intentionally unused. They are accepted to ease Epic 2b call sites that
    # want to forward orchestrator state without needing per-arg dispatch.
    del work_type, worktree, linked_issue, epic_issue

    tmpl_path = _find_template(Path(path), template_path)
    template = read_text_utf8(tmpl_path)

    resolved_mode = interaction_mode if interaction_mode else "confident"
    resolved_branch = branch if branch else "(unknown)"
    resolved_base = base_branch if base_branch else "main"
    now = iso_now()

    content = (
        template
        .replace("<SLUG>", slug)
        .replace("<MODE>", resolved_mode)
        .replace("<BRANCH>", resolved_branch)
        .replace("<BASE_BRANCH>", resolved_base)
        .replace("<ISO_TIMESTAMP>", now)
    )
    return atomic_write_utf8_lf(Path(path), content)


def _read_state_lines(path: Path) -> list[str]:
    """Read state.md into a list of newline-stripped lines."""
    text = read_text_utf8(path).replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        # Drop the trailing blank produced by a final LF so re-joining with
        # ``\n`` doesn't add a spurious blank line.
        text = text[:-1]
    return text.split("\n")


def _write_state_lines(path: Path, lines: list[str]) -> bool:
    """Atomic write of state.md lines joined with LF, no trailing LF."""
    content = "\n".join(lines)
    return atomic_write_utf8_lf(path, content)


def advance_phase(
    path: Path,
    *,
    next_phase: str,
    notes: str | None = None,
    from_phase: str | None = None,  # accepted-and-ignored (legacy alias)
    to_phase: str | None = None,    # accepted-and-ignored (legacy alias)
    artifact_note: str | None = None,  # accepted-and-ignored
) -> bool:
    """Advance the current phase and append a decision-log entry.

    Steps (in order, mirroring ``state-update.ps1::_Advance-Phase``):

    1. Find ``**Current phase:** <X>`` and replace ``<X>`` with ``next_phase``.
    2. In the phase-status table:
       - Row matching the old current phase + ``in_progress`` → ``completed``
         (sets Completed col to now, replaces Notes if ``notes`` supplied).
       - Row matching ``next_phase`` + ``pending`` → ``in_progress``
         (sets Started col to now).
    3. Insert a 4-line decision-log entry before ``## Escalation counter:``.

    :raises ValidationError: if the current-phase header cannot be found.
    :returns: ``True`` on write, ``False`` on no-op.
    """
    # ``from_phase`` / ``to_phase`` / ``artifact_note`` are accepted to match
    # the brief's forward-looking signature; v1.1 doesn't use them.
    del from_phase, to_phase, artifact_note

    path = Path(path)
    lines = _read_state_lines(path)
    now = iso_now()

    # 1. Find + update current-phase header.
    current_phase: str | None = None
    for i, line in enumerate(lines):
        m = _CURRENT_PHASE_RE.match(line)
        if m:
            current_phase = m.group(1)
            lines[i] = f"**Current phase:** {next_phase}"
            break
    if current_phase is None:
        raise ValidationError(
            f"could not parse current phase from {path}"
        )

    # 2. Update phase-status table rows.
    for i, line in enumerate(lines):
        m = _PHASE_ROW_RE.match(line)
        if not m:
            continue
        row_phase, row_status, row_started, _row_completed, row_notes = m.groups()
        if row_phase == current_phase and row_status == "in_progress":
            new_notes = notes if notes else row_notes
            lines[i] = (
                f"| {row_phase} | completed | {row_started} | {now} | {new_notes} |"
            )
        elif row_phase == next_phase and row_status == "pending":
            lines[i] = f"| {row_phase} | in_progress | {now} |  |  |"

    # 3. Insert decision-log entry before the escalation counter line.
    decision_entry = [
        f"- [{now}] AUTOPILOT DECISION (Phase {next_phase} entry): "
        f"Advanced from {current_phase}.",
        "  Reasoning: Hook chain completion advanced state.",
        "  Risk: low",
        "  Would pause in confident mode: no",
    ]
    output: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and _ESCALATION_RE.match(line):
            output.extend(decision_entry)
            output.append("")
            inserted = True
        output.append(line)
    if not inserted:
        # No escalation counter? Append the entry at the end as a graceful
        # degradation — better than silently dropping the decision-log entry.
        output.append("")
        output.extend(decision_entry)

    return _write_state_lines(path, output)


def mark_skipped(
    path: Path,
    *,
    phase: str,
    reason: str,
) -> bool:
    """Mark ``phase`` as ``skipped`` with ``reason`` in the artifacts column."""
    path = Path(path)
    lines = _read_state_lines(path)
    now = iso_now()
    row_re = re.compile(rf"^\|\s*{re.escape(phase)}\s*\|")
    for i, line in enumerate(lines):
        if row_re.match(line):
            lines[i] = f"| {phase} | skipped | {now} | {now} | {reason} |"
            break
    return _write_state_lines(path, lines)


def record_pr(path: Path, *, pr_number: int) -> bool:
    """Set the ``**PR number:** #N`` line.

    If no ``**PR number:**`` line exists, raises :class:`ValidationError` (the
    init template should always provide one).
    """
    path = Path(path)
    lines = _read_state_lines(path)
    found = False
    for i, line in enumerate(lines):
        if _PR_NUMBER_RE.match(line):
            lines[i] = f"**PR number:** #{pr_number}"
            found = True
            break
    if not found:
        raise ValidationError(
            f"no '**PR number:**' line found in {path}"
        )
    return _write_state_lines(path, lines)


def incr_escalation(
    path: Path,
    *,
    context: str | None = None,
    reason: str | None = None,
    escalation_type: str | None = None,
) -> bool:
    """Increment the ``## Escalation counter:`` integer.

    If ``context`` is provided, also appends a section to ``escalation-context.md``
    in the same directory (timestamped, matching v1.1).
    """
    # ``reason`` / ``escalation_type`` are accepted to match the brief's
    # signature; v1.1 doesn't track them in state.md.
    del reason, escalation_type

    path = Path(path)
    lines = _read_state_lines(path)
    bumped = False
    for i, line in enumerate(lines):
        m = _ESCALATION_RE.match(line)
        if m:
            count = int(m.group(1)) + 1
            lines[i] = f"## Escalation counter: {count}"
            bumped = True
            break
    if not bumped:
        raise ValidationError(
            f"no '## Escalation counter:' line found in {path}"
        )
    result = _write_state_lines(path, lines)

    if context:
        ctx_path = path.parent / "escalation-context.md"
        existing = ctx_path.read_text(encoding="utf-8") if ctx_path.exists() else ""
        appended = existing + f"\n## {iso_now()}\n{context}\n"
        atomic_write_utf8_lf(ctx_path, appended)

    return result


def finalize(path: Path, *, delete_state: bool = False) -> bool:
    """Close out phases 7 and 8, or delete the state file.

    :param delete_state: if ``True``, remove the file (used at SDLC completion
        to keep the worktree clean — matches v1.1 ``-DeleteState`` switch).
    """
    path = Path(path)
    if delete_state:
        if path.exists():
            path.unlink()
            return True
        return False
    lines = _read_state_lines(path)
    now = iso_now()
    final_phase_re = re.compile(r"^\|\s*([78])\s*\|")
    for i, line in enumerate(lines):
        m = final_phase_re.match(line)
        if m:
            phase = m.group(1)
            lines[i] = f"| {phase} | completed | {now} | {now} | finalized |"
    return _write_state_lines(path, lines)


def append_decision(path: Path, *, entry: str) -> bool:
    """Insert ``entry`` into the Decisions Log, just before the escalation counter.

    Caller is responsible for entry formatting (typically a bullet line); this
    helper just handles the insertion point. Idempotent only at the byte-level
    via the underlying atomic write — re-inserting the same entry will append
    a duplicate (decision-log semantics in v1.1).
    """
    path = Path(path)
    lines = _read_state_lines(path)
    output: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and _ESCALATION_RE.match(line):
            output.append(entry)
            output.append("")
            inserted = True
        output.append(line)
    if not inserted:
        output.append("")
        output.append(entry)
    return _write_state_lines(path, output)
