"""Python port of ``.kiro/scripts/hook-on-task-complete.ps1``.

Detects the project's coverage tool from ``package.json`` / ``pyproject.toml``
/ ``Cargo.toml`` / ``go.mod`` and emits a structured ``KEY=value`` summary.
Does NOT dispatch the test-writer subagent — that runs agent-side after the
wrapper output is parsed.

* ``--stage measure`` (default): detect tool, summarise recent diff, emit
  threshold-check verdict.
* ``--stage report``: agent-supplied summary write — writes
  ``coverage-task-N.md`` under ``.dlc/<slug>/analysis_output/``.

Markers: ``SLUG``, ``COVERAGE_TOOL``, ``THRESHOLD``, ``DIFF_STAT``,
``GATE_SKIPPED``, ``NEXT``, ``REPORT``, terminal ``HOOK_DONE`` / ``ERROR``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit
from dlc_bridge.util import state as state_mod
from dlc_bridge.util.encoding import atomic_write_utf8_lf


def _resolve_coverage_tool(workspace: Path) -> str | None:
    """Detect project coverage tool — mirrors v1.1 ``Resolve-CoverageTool``."""
    pkg_json = workspace / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError, OSError):
            pkg = {}
        scripts = pkg.get("scripts", {}) or {}
        combined = " ".join(str(v) for v in scripts.values())
        if "vitest" in combined:
            return "vitest --coverage"
        if "jest" in combined:
            return "jest --coverage"
        if "nyc" in combined:
            return "nyc npm test"
        return "npm test -- --coverage"
    if (workspace / "pyproject.toml").exists():
        return "pytest --cov"
    if (workspace / "Cargo.toml").exists():
        return "cargo llvm-cov --summary-only"
    if (workspace / "go.mod").exists():
        return "go test -coverprofile=coverage.out ./..."
    return None


def _resolve_threshold(workspace: Path, default: float) -> float:
    """Read ``.dlc.config.json defaults.coverageThreshold`` or default."""
    cfg_path = workspace / ".dlc.config.json"
    if not cfg_path.exists():
        return default
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        return default
    defaults = cfg.get("defaults") or {}
    value = defaults.get("coverageThreshold")
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _diff_summary() -> str:
    """Return one-line ``git diff --stat HEAD~1`` output, or empty."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--stat", "HEAD~1"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except (FileNotFoundError, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    flattened = re.sub(r"\r?\n", " | ", proc.stdout.strip())
    return flattened


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: on-task-complete")
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Coverage threshold pct (overridden by .dlc.config.json).",
    )
    parser.add_argument(
        "--stage",
        choices=("measure", "report"),
        default="measure",
        help="Pipeline stage.",
    )
    parser.add_argument("--before", type=float, default=None)
    parser.add_argument("--after", type=float, default=None)
    parser.add_argument("--tests-added", type=int, default=None)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (used by tests). Defaults to cwd.",
    )
    parser.add_argument(
        "--dlc-root",
        default=None,
        help="Override .dlc root (used by tests).",
    )
    args = parser.parse_args(argv)

    workspace = Path(args.workspace) if args.workspace else Path.cwd()

    slug = args.slug
    if not slug:
        branch = None
        try:
            proc = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            if proc.returncode == 0:
                branch = proc.stdout.strip() or None
        except (FileNotFoundError, OSError):
            branch = None
        if branch:
            slug = _common.resolve_slug_from_branch(
                branch, dlc_root=args.dlc_root
            )
    if slug:
        emit.emit_marker("SLUG", slug)

    if args.stage == "report":
        if not slug:
            emit.emit_marker("ERROR", "--slug required for --stage report")
            return 1
        analysis_dir = _common.dlc_root_for(args.dlc_root) / slug / "analysis_output"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(analysis_dir.glob("coverage-task-*.md"))
        n = len(existing) + 1
        report_path = analysis_dir / f"coverage-task-{n}.md"
        now = state_mod.iso_now()
        content = "\n".join(
            [
                f"# Coverage report - task {n}",
                "",
                f"- Timestamp: {now}",
                f"- Threshold: {args.threshold}%",
                f"- Coverage before: {args.before}%",
                f"- Coverage after: {args.after}%",
                f"- Tests added: {args.tests_added}",
                "",
            ]
        )
        atomic_write_utf8_lf(report_path, content)
        emit.emit_marker("REPORT", str(report_path))
        _common.emit_terminal("HOOK_DONE")
        return 0

    # Stage = measure.
    tool = _resolve_coverage_tool(workspace)
    if not tool:
        emit.emit_marker("COVERAGE_TOOL", "none-detected")
        emit.emit_marker(
            "GATE_SKIPPED", "no coverage tool found in project root"
        )
        _common.emit_terminal("HOOK_DONE")
        return 0
    emit.emit_marker("COVERAGE_TOOL", tool)

    effective_threshold = _resolve_threshold(workspace, args.threshold)
    emit.emit_marker("THRESHOLD", str(effective_threshold))

    diff_stat = _diff_summary()
    if diff_stat:
        emit.emit_marker("DIFF_STAT", diff_stat)

    emit.emit_marker(
        "NEXT",
        f"agent should run: {tool} then call this wrapper with "
        f"--stage report --before <x> --after <y> --tests-added <n>",
    )
    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
