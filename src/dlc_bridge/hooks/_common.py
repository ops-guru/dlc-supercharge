"""Shared helpers for the 14 hook modules.

Centralises:

* :func:`common_parser` — argparse parent with the universally accepted
  flags (``--slug``, ``--dry-run``).
* :func:`invoke_bridge` — spawn ``python -m dlc_bridge <verb> [args]`` as a
  subprocess with an argv-list (never ``shell=True``). The single mockable
  surface used by every hook module's unit tests.
* :func:`emit_terminal` — write a bare terminal token (``HOOK_DONE``,
  ``HOOK_INIT_DONE``, …) to stdout, matching v1.1's
  ``Write-Output 'HOOK_DONE'`` behaviour.
* State-md readers (:func:`read_current_phase`, :func:`read_pr_number`,
  :func:`read_branch`, :func:`resolve_slug_from_branch`,
  :func:`find_slugs_for_pr`).
* :func:`parse_bridge_json_field` — pull a string field out of the bridge's
  single-line JSON status payload (jobId / log).

All callers stay clear of :mod:`dlc_bridge.cache` and
:mod:`dlc_bridge.status` — hooks talk to the bridge **as a subprocess** and
to plain on-disk artifacts only. This keeps the hook surface a thin shell
over the public CLI exactly like the v1.1 PS wrappers.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from dlc_bridge.util import emit

__all__ = [
    "common_parser",
    "find_python_executable",
    "invoke_bridge",
    "emit_terminal",
    "emit_propagate_outcome",
    "read_state_text",
    "read_current_phase",
    "read_pr_number",
    "read_branch",
    "resolve_slug_from_branch",
    "find_slugs_for_pr",
    "parse_bridge_json_field",
    "dlc_root_for",
]


# Regexes mirror the patterns used by the v1.1 PS wrappers verbatim.
_CURRENT_PHASE_RE = re.compile(r"\*\*Current phase:\*\*\s+(\S+)")
_PR_NUMBER_RE = re.compile(r"\*\*PR number:\*\*\s+#(\d+)")
_BRANCH_RE = re.compile(r"\*\*Branch:\*\*\s+(\S+)")
_DECISION_LINE_RE = re.compile(
    r"^- \[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]\s+(.+)$"
)


def common_parser(description: str) -> argparse.ArgumentParser:
    """Build an argparse parser with the universally-accepted hook flags.

    Hook modules call this then ``parser.add_argument(...)`` for the flags
    specific to their v1.1 PS counterpart.

    Universal flags (subset honoured per-hook):

    * ``--slug NAME`` — explicit slug (most hooks accept it).
    * ``--dry-run`` — record invocations without spawning the bridge.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--slug",
        default=None,
        help="Explicit slug to scope the hook against (overrides derivation).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Record bridge invocations but do not actually spawn subprocesses.",
    )
    return parser


def find_python_executable() -> str:
    """Return the current Python executable.

    Used by :func:`invoke_bridge` to spawn ``python -m dlc_bridge`` with the
    same interpreter the hook is running under (so virtualenv / uv-managed
    interpreters chain correctly).
    """
    return sys.executable


def invoke_bridge(
    verb: str,
    *,
    args: list[str] | None = None,
    background: bool = False,
    dry_run: bool = False,
    cwd: Path | str | None = None,
    capture_output: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Spawn ``python -m dlc_bridge <verb> [args]`` as a subprocess.

    :param verb: one of the 16 bridge verbs (see
        :data:`dlc_bridge.verbs.SUPPORTED_VERBS`).
    :param args: optional list of additional CLI args (e.g. ``['--source',
        path, '--slug', slug]``). NEVER pass a single string — must be a
        list to preserve the argv-list contract (no shell expansion).
    :param background: if ``True``, append ``--background``.
    :param dry_run: if ``True``, returns a stubbed ``CompletedProcess`` with
        ``returncode=0`` and a ``DRY_RUN=<argv>`` line on stdout. No
        subprocess is spawned.
    :param cwd: optional working directory.
    :param capture_output: capture stdout/stderr (default True).
    :param timeout: subprocess timeout in seconds.
    :returns: :class:`subprocess.CompletedProcess` with text-mode stdout/err.
    """
    argv: list[str] = [find_python_executable(), "-m", "dlc_bridge", verb]
    if args:
        argv.extend(args)
    if background:
        argv.append("--background")

    if dry_run:
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=f"DRY_RUN={' '.join(argv)}\n",
            stderr="",
        )

    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        check=False,
        # Explicit: no shell expansion. Argv-list only.
        shell=False,
    )


def emit_terminal(token: str) -> None:
    """Write a bare terminal token (e.g. ``HOOK_DONE``) to stdout + flush.

    Matches v1.1's ``Write-Output 'HOOK_DONE'`` — no ``=`` sign, just the
    token followed by ``\\n``. Used for terminal markers; KEY=value markers
    go through :func:`dlc_bridge.util.emit.emit_marker`.
    """
    sys.stdout.write(f"{token}\n")
    sys.stdout.flush()


def emit_propagate_outcome(
    result: dict, *, prd: Path | str, source: Path | str
) -> None:
    """Emit a granular ``ID_PROPAGATE*`` marker based on parser yield.

    Distinguishes three outcomes that all looked identical under the
    pre-v1.2 ``emit_marker("ID_PROPAGATED", ...)`` happy-path:

    * ``ID_PROPAGATE_NO_ENTRIES`` — PRD parsed but yielded zero ``FR-N``/``NFR-N``
      headings. Almost always a producer/consumer format drift between the
      ``/dlc:analyze-requirements`` skill output and ``id_propagate``'s
      heading regex. Surface loudly so the user can re-tune the parser.
    * ``ID_PROPAGATE_ZERO_MATCHES`` — entries parsed, but none cleared the
      Jaccard threshold. Tunable via ``--threshold``.
    * ``ID_PROPAGATED`` — at least one ID injected.
    """
    propagated = result.get("propagated") or []
    unmapped = result.get("unmapped") or []
    threshold = result.get("threshold")
    arrow = f"{prd} -> {source}"
    if not propagated and not unmapped:
        emit.emit_marker(
            "ID_PROPAGATE_NO_ENTRIES",
            (
                f"{arrow}; 0 FR/NFR headings parsed from PRD "
                f"(check ### vs #### / dash style)"
            ),
        )
        return
    if not propagated:
        emit.emit_marker(
            "ID_PROPAGATE_ZERO_MATCHES",
            (
                f"{arrow}; {len(unmapped)} entries parsed but all below "
                f"threshold={threshold}"
            ),
        )
        return
    emit.emit_marker(
        "ID_PROPAGATED",
        f"{arrow}; {len(propagated)} injected, {len(unmapped)} unmapped",
    )


def dlc_root_for(dlc_root: Path | str | None = None) -> Path:
    """Resolve the ``.dlc`` root directory.

    :param dlc_root: explicit root (used by tests via tmp_workspace). Falls
        back to ``Path.cwd() / '.dlc'`` for production.
    """
    if dlc_root is not None:
        return Path(dlc_root)
    return Path.cwd() / ".dlc"


def read_state_text(slug: str, *, dlc_root: Path | str | None = None) -> str | None:
    """Read ``<dlc_root>/<slug>/state.md`` text, or ``None`` if absent.

    Matches v1.1's ``Get-Content -Raw -LiteralPath`` semantics: returns the
    full file content as a single string, or ``None`` if the file doesn't
    exist.
    """
    state_path = dlc_root_for(dlc_root) / slug / "state.md"
    if not state_path.exists():
        return None
    return state_path.read_text(encoding="utf-8")


def read_current_phase(
    slug: str, *, dlc_root: Path | str | None = None
) -> str | None:
    """Extract ``**Current phase:** <X>`` from the state.md, or ``None``."""
    content = read_state_text(slug, dlc_root=dlc_root)
    if content is None:
        return None
    m = _CURRENT_PHASE_RE.search(content)
    return m.group(1) if m else None


def read_pr_number(
    slug: str, *, dlc_root: Path | str | None = None
) -> int | None:
    """Extract ``**PR number:** #N`` from the state.md, or ``None``."""
    content = read_state_text(slug, dlc_root=dlc_root)
    if content is None:
        return None
    m = _PR_NUMBER_RE.search(content)
    return int(m.group(1)) if m else None


def read_branch(
    slug: str, *, dlc_root: Path | str | None = None
) -> str | None:
    """Extract ``**Branch:** <X>`` from the state.md, or ``None``."""
    content = read_state_text(slug, dlc_root=dlc_root)
    if content is None:
        return None
    m = _BRANCH_RE.search(content)
    return m.group(1) if m else None


def read_recent_decisions(
    slug: str,
    *,
    limit: int = 2,
    dlc_root: Path | str | None = None,
) -> list[str]:
    """Return the most recent ``limit`` decision-log lines from state.md.

    Each entry is ``<timestamp> <message>`` (no leading ``- [...]`` marker)
    to match v1.1's ``hook-resume-dlc-sdlc.ps1`` output shape.
    """
    content = read_state_text(slug, dlc_root=dlc_root)
    if content is None:
        return []
    decisions: list[str] = []
    for line in content.splitlines():
        m = _DECISION_LINE_RE.match(line)
        if m:
            decisions.append(f"{m.group(1)} {m.group(2)}")
            if len(decisions) >= limit:
                break
    return decisions


def resolve_slug_from_branch(
    branch: str | None, *, dlc_root: Path | str | None = None
) -> str | None:
    """Scan ``.dlc/*/state.md`` for ``**Branch:** <branch>``.

    Returns the directory name (slug) of the first match, or ``None`` if no
    match. Matches v1.1's ``Resolve-SlugFromBranch`` helper used across
    several hooks.
    """
    if not branch:
        return None
    root = dlc_root_for(dlc_root)
    if not root.exists():
        return None
    pattern = re.compile(rf"\*\*Branch:\*\*\s+{re.escape(branch)}\s*$", re.MULTILINE)
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        state_path = entry / "state.md"
        if not state_path.exists():
            continue
        try:
            content = state_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if pattern.search(content):
            return entry.name
    return None


def find_slugs_for_pr(
    pr: int, *, dlc_root: Path | str | None = None
) -> list[str]:
    """Return all slugs whose state.md has ``**PR number:** #<pr>``.

    Matches v1.1's ``hook-on-pr-merged.ps1`` slug discovery loop.
    """
    root = dlc_root_for(dlc_root)
    if not root.exists():
        return []
    pattern = re.compile(rf"\*\*PR number:\*\*\s+#{pr}\b")
    results: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        state_path = entry / "state.md"
        if not state_path.exists():
            continue
        try:
            content = state_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if pattern.search(content):
            results.append(entry.name)
    return results


def parse_bridge_json_field(stdout: str, field: str) -> str | None:
    """Extract ``"field":"value"`` from a single-line JSON bridge response.

    The bridge emits a single-line JSON envelope on background dispatches
    (containing ``jobId``, ``log``, etc.). The v1.1 PS wrappers regex-match
    these fields; we replicate that behaviour rather than full JSON parsing
    so partial / multi-line stdout doesn't trip us up.
    """
    if not stdout:
        return None
    # First try strict JSON parsing on each line.
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        value = obj.get(field)
        if value is not None:
            return str(value)
    # Fallback: regex match the field anywhere in the output.
    pattern = re.compile(rf'"{re.escape(field)}"\s*:\s*"([^"]+)"')
    m = pattern.search(stdout)
    return m.group(1) if m else None


def list_status_files(
    *, dlc_root: Path | str | None = None
) -> list[Path]:
    """Return ``.dlc/_bridge-jobs/*.status.json`` files sorted by name."""
    job_dir = dlc_root_for(dlc_root) / "_bridge-jobs"
    if not job_dir.exists():
        return []
    return sorted(job_dir.glob("*.status.json"))


def surface_bridge_cached(stdout: str) -> str | None:
    """Surface a ``BRIDGE_CACHED=<path>`` marker from bridge stdout.

    Returns the path string if a `BRIDGE_CACHED=` line is present, else
    ``None``. Used by several Pattern-A wrappers to re-emit the marker so
    the calling agent sees the cache-hit short-circuit.
    """
    if not stdout:
        return None
    m = re.search(r"^BRIDGE_CACHED=(\S+)", stdout, re.MULTILINE)
    return m.group(1) if m else None


def emit_bridge_exit(exit_code: int) -> None:
    """Emit ``BRIDGE_EXIT=<n>`` — convenience wrapper."""
    emit.emit_marker("BRIDGE_EXIT", str(exit_code))
