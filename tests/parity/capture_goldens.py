"""Capture v1.1 golden artifacts for the FR-19 parity gate.

This script is **NOT a test** (filename does not start with ``test_``). It is
an operator-run utility that refreshes ``tests/goldens/v1_1/`` from the v1.1
PowerShell sources still living under ``.kiro/scripts/`` (until Epic 5
deletes them).

The parity tests under ``tests/parity/`` largely run their own ad-hoc PS
invocations because that's simpler than reading off-disk goldens for the
limited number of fixtures we use. This script exists for the eventual
``capture-once-freeze-forever`` workflow (D-7) — when v1.1 is deleted, the
captured goldens here remain as the immutable v1.1 contract.

Usage:

    python tests/parity/capture_goldens.py [--force]

Without ``--force``, the script skips goldens that already exist. With
``--force``, it re-captures and overwrites.

Requires PowerShell on PATH (``pwsh`` preferred, ``powershell.exe`` fallback).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / ".kiro" / "scripts"
GOLDENS_DIR = REPO_ROOT / "tests" / "goldens" / "v1_1"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def find_powershell() -> str | None:
    for exe in ("pwsh", "powershell.exe", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def run_ps(ps: str, args: list[str]) -> subprocess.CompletedProcess:
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", *args]
    cp = subprocess.run(cmd, capture_output=True, check=False, timeout=60.0)
    cp_text = subprocess.CompletedProcess(
        args=cp.args,
        returncode=cp.returncode,
        stdout=cp.stdout.decode("utf-8", errors="replace"),
        stderr=cp.stderr.decode("utf-8", errors="replace"),
    )
    return cp_text


def maybe_write(path: Path, content: str | bytes, *, force: bool) -> bool:
    """Write ``content`` to ``path`` unless it exists and ``force`` is False."""
    if path.exists() and not force:
        print(f"  [skip] {path.relative_to(REPO_ROOT)} (exists; pass --force to overwrite)")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")
    print(f"  [write] {path.relative_to(REPO_ROOT)}")
    return True


def capture_help(ps: str, force: bool) -> None:
    print("Capturing dlc-bridge.ps1 help...")
    cp = run_ps(ps, ["-File", str(SCRIPTS_DIR / "dlc-bridge.ps1"), "help"])
    maybe_write(GOLDENS_DIR / "help" / "help.txt", cp.stdout, force=force)


def capture_slug_corpus(force: bool) -> None:
    """Slug rules are Python-only (no PS invocation needed)."""
    print("Capturing slug corpus (Python-side; PS rules verified statically)...")
    # Mirror tests/parity/test_slug_parity.py SLUG_FIXTURES; emit as JSON for
    # external tooling.
    corpus = {
        ".kiro/specs/add-oauth/requirements.md": "add-oauth",
        ".kiro/specs/add-oauth/design.md": "add-oauth",
        ".kiro/specs/add-oauth/tasks.md": "add-oauth",
        ".kiro\\specs\\add-oauth\\requirements.md": "add-oauth",
        ".kiro/specs/dlc-supercharge-python-migration/requirements.md": "dlc-supercharge-python-migration",
        ".dlc/my-slug/state.md": "my-slug",
        ".dlc/my-slug/plans/epic-001.plan.md": "my-slug",
    }
    maybe_write(
        GOLDENS_DIR / "slug-derive" / "corpus.json",
        json.dumps(corpus, indent=2),
        force=force,
    )


def capture_state_transitions(ps: str, force: bool) -> None:
    """Capture state.md after each operation. Runs each in an isolated tmpdir."""
    import tempfile
    print("Capturing state.md transitions...")

    transitions = [
        ("init", []),
        ("advance", [("NextPhase", "2a")]),
        ("mark_skipped", [("Phase", "2b"), ("Rationale", "skipped per user")]),
        ("record_pr", [("PrNumber", "42")]),
        ("incr_escalation", []),
    ]

    state_script = SCRIPTS_DIR / "state-update.ps1"
    tmpl_src = REPO_ROOT / ".kiro" / "powers" / "dlc-supercharge" / "templates" / "state.md.template"

    for op, extra_args in transitions:
        tmp = Path(tempfile.mkdtemp(prefix=f"goldens-state-{op}-"))
        try:
            slug_dir = tmp / ".dlc" / "test-slug"
            slug_dir.mkdir(parents=True)
            tmpl_dst = tmp / ".kiro" / "powers" / "dlc-supercharge" / "templates" / "state.md.template"
            tmpl_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmpl_src, tmpl_dst)

            # Always init first
            init_cmd = (
                f". '{state_script.as_posix()}'; "
                f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation init "
                f"-Slug 'test-slug' -Branch 'feature/parity' -BaseBranch 'main' -Mode 'confident'"
            )
            cp = run_ps(ps, ["-Command", init_cmd])
            if cp.returncode != 0:
                print(f"  [err] init failed: {cp.stderr}")
                continue

            if op != "init":
                extra_str = " ".join(f"-{k} '{v}'" for k, v in extra_args)
                cmd = (
                    f". '{state_script.as_posix()}'; "
                    f"Update-StateMd -SlugPath '{slug_dir.as_posix()}' -Operation {op} {extra_str}"
                )
                cp = run_ps(ps, ["-Command", cmd])
                if cp.returncode != 0:
                    print(f"  [err] {op} failed: {cp.stderr}")
                    continue

            state_md = slug_dir / "state.md"
            if state_md.exists():
                maybe_write(
                    GOLDENS_DIR / "state" / f"{op}.md",
                    state_md.read_text(encoding="utf-8"),
                    force=force,
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def capture_dry_runs(ps: str, force: bool) -> None:
    """Capture v1.1 dry-run JSON envelope per verb."""
    print("Capturing v1.1 dry-run JSON envelopes...")
    verbs_to_capture = [
        ("analyze-requirements", ["-Source", "."]),
        ("produce-tech-design", ["-Source", "."]),
        ("plan-implementation", ["-Source", "."]),
        ("map-codebase", ["-Target", "."]),
        ("reverse-engineer-kb", ["-Target", "."]),
        ("kb-gap-analysis", ["-Source", ".", "-Target", "."]),
        ("babysit-pr", ["-Pr", "1"]),
        ("hotfix", ["-Pr", "1"]),
        ("review", ["-Pr", "1"]),
    ]
    script = SCRIPTS_DIR / "dlc-bridge.ps1"
    for verb, args in verbs_to_capture:
        cp = run_ps(ps, ["-File", str(script), verb, *args, "-DryRun"])
        # Find the trailing JSON line
        for line in reversed(cp.stdout.splitlines()):
            if line.strip().startswith("{") and '"status"' in line:
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    print(f"  [warn] {verb}: JSON parse failed")
                    break
                maybe_write(
                    GOLDENS_DIR / "dry-run" / f"{verb}.json",
                    json.dumps(parsed, indent=2),
                    force=force,
                )
                break


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture v1.1 PowerShell goldens for the FR-19 parity gate"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-capture and overwrite existing goldens (default is skip-if-present)"
    )
    args = parser.parse_args()

    ps = find_powershell()
    if ps is None:
        print(
            "ERROR: PowerShell not on PATH. Install pwsh (https://aka.ms/powershell) "
            "or run on a Windows host with powershell.exe.",
            file=sys.stderr,
        )
        return 1
    print(f"Using PowerShell: {ps}")

    capture_help(ps, args.force)
    capture_slug_corpus(args.force)
    capture_state_transitions(ps, args.force)
    capture_dry_runs(ps, args.force)

    print("\nDone. Review the contents under tests/goldens/v1_1/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
