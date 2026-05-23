"""Python port of ``.kiro/scripts/hook-on-task-polish.ps1``.

Reads the per-task diff (against ``HEAD~1`` by default) limited to code
extensions, samples sibling source files to summarise the project's style
profile, and emits structured ``KEY=value`` output. Does NOT dispatch the
doc-writer subagent — that runs agent-side.

* ``--stage profile`` (default): gate check + diff + style-profile summary.
* ``--stage verify``: emit the project's test command for the agent to run.

Markers: ``SLUG``, ``POLISH_ENABLED``, ``GATE_SKIPPED``,
``DIFF_FILE_COUNT``, ``DIFF_FILE``, ``STYLE_PROFILE``, ``STYLE_SAMPLES``,
``TEST_CMD``, ``TESTS_SKIPPED``, ``NEXT``, terminal ``HOOK_DONE``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import emit


_CODE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java")


def _polish_gate_enabled(workspace: Path) -> bool:
    """Read ``.dlc.config.json defaults.taskPolish``; default ``False``."""
    cfg_path = workspace / ".dlc.config.json"
    if not cfg_path.exists():
        return False
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        return False
    defaults = cfg.get("defaults") or {}
    value = defaults.get("taskPolish")
    if value is None:
        return False
    return bool(value)


def _resolve_style_profile(workspace: Path) -> dict[str, object]:
    """Sample up to 5 source files; infer dominant docstring style.

    Mirrors v1.1 ``Resolve-StyleProfile`` heuristic: counts hits for
    google/numpy/rest/jsdoc; reports the dominant style (or ``unknown``).
    """
    samples: list[Path] = []
    for ext in _CODE_EXTENSIONS:
        for path in workspace.rglob(f"*{ext}"):
            if any(p in path.parts for p in ("node_modules", ".dlc")):
                continue
            samples.append(path)
            if len(samples) >= 5:
                break
        if len(samples) >= 5:
            break

    google = numpy = rest = jsdoc = 0
    for path in samples:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"Args:\s*\n\s+\w+:", content) or re.search(
            r"Returns:\s*\n\s+", content
        ):
            google += 1
        if re.search(r"Parameters\s*\n\s*-+\s*\n", content):
            numpy += 1
        if re.search(r":param\s+\w+:", content) or re.search(
            r":returns:", content
        ):
            rest += 1
        if re.search(r"/\*\*[\s\S]*?@param", content) or re.search(
            r"/\*\*[\s\S]*?@returns", content
        ):
            jsdoc += 1

    best = "unknown"
    best_n = 0
    for name, value in (
        ("google", google), ("numpy", numpy), ("rest", rest), ("jsdoc", jsdoc)
    ):
        if value > best_n:
            best_n = value
            best = name
    return {"style": best, "samples": len(samples)}


def _diff_files() -> list[str]:
    """Return code files in the most recent diff vs HEAD~1."""
    argv = [
        "git", "diff", "--name-only", "HEAD~1", "--",
        "*.py", "*.ts", "*.tsx", "*.js", "*.go", "*.rs", "*.java",
    ]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, check=False, shell=False
        )
    except (FileNotFoundError, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _test_command(workspace: Path) -> str | None:
    """Detect a per-project test runner — mirrors v1.1 ``-Stage verify``."""
    if (workspace / "package.json").exists():
        return "npm test"
    if (workspace / "pyproject.toml").exists():
        return "pytest"
    if (workspace / "Cargo.toml").exists():
        return "cargo test"
    if (workspace / "go.mod").exists():
        return "go test ./..."
    return None


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: on-task-polish")
    parser.add_argument(
        "--stage",
        choices=("profile", "verify"),
        default="profile",
        help="Pipeline stage.",
    )
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
        try:
            proc = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            branch = proc.stdout.strip() if proc.returncode == 0 else None
        except (FileNotFoundError, OSError):
            branch = None
        if branch:
            slug = _common.resolve_slug_from_branch(
                branch, dlc_root=args.dlc_root
            )
    if slug:
        emit.emit_marker("SLUG", slug)

    if args.stage == "verify":
        cmd = _test_command(workspace)
        if not cmd:
            emit.emit_marker("TESTS_SKIPPED", "no test runner detected")
            _common.emit_terminal("HOOK_DONE")
            return 0
        emit.emit_marker("TEST_CMD", cmd)
        emit.emit_marker(
            "NEXT",
            f"agent should run: {cmd} ; if failure -> revert polish diff",
        )
        _common.emit_terminal("HOOK_DONE")
        return 0

    # Stage = profile.
    enabled = _polish_gate_enabled(workspace)
    emit.emit_marker("POLISH_ENABLED", str(enabled))
    if not enabled:
        emit.emit_marker(
            "GATE_SKIPPED",
            "defaults.taskPolish is not true in .dlc.config.json",
        )
        _common.emit_terminal("HOOK_DONE")
        return 0

    diffs = _diff_files()
    emit.emit_marker("DIFF_FILE_COUNT", str(len(diffs)))
    for path in diffs:
        emit.emit_marker("DIFF_FILE", path)

    profile = _resolve_style_profile(workspace)
    emit.emit_marker("STYLE_PROFILE", str(profile["style"]))
    emit.emit_marker("STYLE_SAMPLES", str(profile["samples"]))

    emit.emit_marker(
        "NEXT",
        "agent dispatches dlc-doc-writer with diff + style profile; "
        "then call this wrapper with --stage verify",
    )
    _common.emit_terminal("HOOK_DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
