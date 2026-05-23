"""Command-line dispatcher for the DLC bridge.

This module is the console-script entry point declared in ``pyproject.toml``
under ``[project.scripts]``:

    dlc-bridge = "dlc_bridge.cli:main"

Behaviour summary
-----------------

* ``dlc-bridge help`` — prints a help banner listing the 16 supported verbs.
* ``dlc-bridge <verb> --dry-run [...]`` — emits an FR-5 JSON envelope.
* ``dlc-bridge <verb> [...]`` — full live dispatch (Epic 2b WI-16):

  1. Resolve SKILL.md path for the verb.
  2. Derive a slug from --source / --target / --pr (FR-17).
  3. If a slug + canonical input file are derivable, hash the input
     (FR-8) and consult the cache (FR-8/9/10). On hit, emit
     ``BRIDGE_CACHED=<path>`` + ``BRIDGE_EXIT=0`` and exit 0.
  4. Otherwise: assemble the verb-task body, generate a job-ID, write
     the initial ``running`` status JSON, and invoke
     ``claude -p --append-system-prompt-file <skill> --permission-mode
     bypassPermissions --max-budget-usd <N> <task>`` (FR-2).
  5. Foreground: wrap the claude call in :func:`retry.invoke_with_retry`
     with the v1.1 transient predicate. On final success, write the
     cache entry and complete the status file; emit ``BRIDGE_OK=<path>``.
  6. ``--background``: spawn ``python -m dlc_bridge.background_runner``
     as a detached child (D-11, FR-4); parent emits
     ``BACKGROUND_JOB_ID=<id>`` and exits 0 immediately.

Validation failures (unknown verb, out-of-range int, traversal path, etc.)
raise :class:`~dlc_bridge.exceptions.ValidationError` and exit 4.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from dlc_bridge import __version__
from dlc_bridge import cache as cache_mod
from dlc_bridge import retry as retry_mod
from dlc_bridge import status as status_mod
from dlc_bridge.exceptions import (
    BridgeError,
    ConfigurationError,
    RetryExhaustedError,
    ValidationError,
)
from dlc_bridge.util.emit import emit_log, emit_marker
from dlc_bridge.util.hash import get_normalized_input_hash
from dlc_bridge.util.slug import from_path as slug_from_path
from dlc_bridge.verbs import (
    SUPPORTED_VERBS,
    resolve_skill_path,
    resolve_verb_template,
)

# Sentinel exit codes that the dispatcher itself returns (in addition to the
# exit-code attributes on :class:`BridgeError` subclasses).
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_CLAUDE_NOT_FOUND = 2

# Numeric range limits for argparse validation (FR-3).
MAX_FILES_MIN = 1
MAX_FILES_MAX = 5000
MAX_FILES_DEFAULT = 200

MAX_BUDGET_USD_MIN = 0.0
MAX_BUDGET_USD_MAX = 50.0
MAX_BUDGET_USD_DEFAULT = 5.0

CACHE_MAX_AGE_HOURS_DEFAULT = 0.0  # 0 == no expiry

MODE_CHOICES = ("interactive", "confident", "autopilot")

# Help text emitted by ``dlc-bridge help``.
_HELP_TEXT = """\
dlc-bridge — DLC SuperCharge bridge ({version})

Usage:
    dlc-bridge <verb> [--source PATH] [--target PATH] [--mode MODE]
                      [--pr N] [--max-files N] [--max-budget-usd N]
                      [--cache-max-age-hours N] [--background]
                      [--no-cache] [--dry-run]
    dlc-bridge help

Supported verbs (16):
    analyze-requirements   produce-tech-design   plan-implementation
    finalize-sdlc          discover              review-pr
    stabilize-pr           review-security       review-ux
    review-a11y            review-performance    reverse-engineer-kb
    kb-gap-analysis        map-codebase          babysit-pr
    hotfix

Flags:
    --source PATH              Input artifact (must resolve under project root)
    --target PATH              Output artifact (must resolve under project root)
    --mode MODE                One of: interactive | confident | autopilot
    --pr N                     Pull-request number (positive integer)
    --max-files N              Cap on files inspected (1..5000, default 200)
    --max-budget-usd N         Claude budget cap (0..50, default 5.0)
    --cache-max-age-hours N    Cache TTL in hours; 0 = no expiry
    --background               Run detached (returns jobId immediately)
    --no-cache                 Bypass cache lookup
    --force                    Bypass cache lookup (alias for --no-cache)
    --dry-run                  Print JSON envelope and exit 0; no side effects

Exit codes:
    0   success
    1   generic bridge failure
    2   claude CLI not on PATH
    4   input validation / path traversal / unknown verb
    5   retries exhausted (transient failures)
    7   blocked by debounce / cross-process lock / cancelled
    9   bootstrap / plugin-cache configuration failure
"""

# Per-verb canonical-input-path resolution. Mirrors v1.1's Resolve-CacheInputPath
# (dlc-bridge.ps1:304-325). Verbs that hash --source (most verbs) come first;
# verbs that hash --target (codebase-scanning verbs) live in the second set.
_SOURCE_HASHED_VERBS = frozenset(
    {
        "analyze-requirements",
        "plan-implementation",
        "kb-gap-analysis",
        "finalize-sdlc",
        "review-security",
        "review-ux",
        "review-a11y",
        "review-performance",
    }
)
_TARGET_HASHED_VERBS = frozenset(
    {
        "produce-tech-design",
        "map-codebase",
        "reverse-engineer-kb",
        "discover",
    }
)

# Per-verb best-effort artifact-path predictions for cache recording. Mirrors
# v1.1's Get-ExpectedArtifactPath (dlc-bridge.ps1:327-369). Each value is a
# sequence of slug-relative suffix paths; the first one that exists on disk
# is recorded.
_VERB_TO_ARTIFACT_SUFFIXES: dict[str, tuple[str, ...]] = {
    "analyze-requirements": ("requirements.prd.md",),
    "produce-tech-design": ("designs/tech-design.md",),
    "plan-implementation": (
        "plans/epic-001.plan.md",
        "plans/epic-001-plan.md",
    ),
    "map-codebase": (".map.md",),
    "kb-gap-analysis": ("gap-analysis/report.md",),
    "reverse-engineer-kb": ("kb/index.json", "kb/architecture.md"),
    "finalize-sdlc": ("analysis_output/finalization-report.md",),
    "discover": ("discovery/discovery.md",),
    "review-security": ("analysis_output/SECURITY_REVIEW_REPORT.md",),
    "review-ux": ("designs/ux-review.md",),
    "review-a11y": ("analysis_output/A11Y_REVIEW_REPORT.md",),
    "review-performance": ("analysis_output/PERFORMANCE_REVIEW_REPORT.md",),
}


class _RaisingArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that raises ``ValidationError`` instead of
    calling :func:`sys.exit` on error.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValidationError(message)


def _validate_path_under_root(
    value: str, label: str, root: Path | None = None
) -> Path:
    """Resolve ``value`` and verify it stays under ``root`` (project root)."""
    root_resolved = (root or Path.cwd()).resolve()
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (root_resolved / raw).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValidationError(f"{label} '{value}' resolves above project root")
    return candidate


def _int_range(value: str, *, label: str, low: int, high: int) -> int:
    """Argparse type-converter for bounded integers (FR-3)."""
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be an integer, got '{value}'") from exc
    if n < low or n > high:
        raise ValidationError(f"{label} must be in [{low}, {high}], got {n}")
    return n


def _float_range(value: str, *, label: str, low: float, high: float) -> float:
    """Argparse type-converter for bounded floats (FR-3)."""
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a number, got '{value}'") from exc
    if x < low or x > high:
        raise ValidationError(f"{label} must be in [{low}, {high}], got {x}")
    return x


def _positive_int(value: str, *, label: str) -> int:
    """Argparse type-converter for strictly-positive integers (FR-3)."""
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be an integer, got '{value}'") from exc
    if n <= 0:
        raise ValidationError(f"{label} must be > 0, got {n}")
    return n


def _non_negative_float(value: str, *, label: str) -> float:
    """Argparse type-converter for non-negative floats (FR-3)."""
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a number, got '{value}'") from exc
    if x < 0:
        raise ValidationError(f"{label} must be >= 0, got {x}")
    return x


def build_parser() -> _RaisingArgumentParser:
    """Construct the argparse parser used by :func:`main`."""
    parser = _RaisingArgumentParser(
        prog="dlc-bridge",
        description="DLC SuperCharge bridge — Python runtime for /dlc: hookchain.",
        add_help=False,
    )
    parser.add_argument("verb", help="One of the 16 supported verbs, or 'help'.")
    parser.add_argument("--source", default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument(
        "--mode", default="confident", choices=MODE_CHOICES,
        help="Interaction mode (default: confident).",
    )
    parser.add_argument(
        "--pr", default=None, type=lambda v: _positive_int(v, label="--pr"),
    )
    parser.add_argument(
        "--max-files", default=MAX_FILES_DEFAULT,
        type=lambda v: _int_range(
            v, label="--max-files", low=MAX_FILES_MIN, high=MAX_FILES_MAX
        ),
    )
    parser.add_argument(
        "--max-budget-usd", default=MAX_BUDGET_USD_DEFAULT,
        type=lambda v: _float_range(
            v, label="--max-budget-usd",
            low=MAX_BUDGET_USD_MIN, high=MAX_BUDGET_USD_MAX,
        ),
    )
    parser.add_argument(
        "--cache-max-age-hours", default=CACHE_MAX_AGE_HOURS_DEFAULT,
        type=lambda v: _non_negative_float(v, label="--cache-max-age-hours"),
    )
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the cache (alias for --no-cache; matches v1.1 -Force).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--slug", default=None,
        help="Override slug derivation (cache scoping).",
    )
    return parser


def _emit_help(stream) -> int:  # noqa: ANN001
    """Print the help banner and return exit 0."""
    stream.write(_HELP_TEXT.format(version=__version__))
    return EXIT_OK


# ----- claude argv assembly -------------------------------------------------


def _build_claude_argv(
    *, skill_path: Path, max_budget_usd: float, task_body: str
) -> list[str]:
    """Assemble the ``claude -p ...`` argv. Mirrors v1.1 dlc-bridge.ps1:599 exactly.

    The task body is the FINAL positional element; this is intentional so
    PowerShell-style array-passing semantics map cleanly to Python's
    subprocess argv-list invocation. NEVER use shell=True.
    """
    return [
        "claude",
        "-p",
        "--append-system-prompt-file",
        str(skill_path),
        "--permission-mode",
        "bypassPermissions",
        "--max-budget-usd",
        str(max_budget_usd),
        task_body,
    ]


# ----- dry-run envelope (FR-5) ---------------------------------------------


def _synthetic_dry_run_skill_path(verb: str) -> Path:
    """Return a placeholder SKILL.md path for dry-run when the plugin cache is absent.

    The dry-run envelope contract (FR-5) requires a ``skillPath`` that ends in
    ``SKILL.md``. When the DLC plugin cache is not installed (CI runners,
    fresh clones), the real resolver raises ``ConfigurationError``. For dry-run
    only, we synthesize a path that preserves the documented shape
    (``.../skills/<folder>/SKILL.md``) so downstream tooling can still pattern-match
    against the envelope without requiring the live plugin install.

    Real (non-dry-run) dispatch still fails closed via the original
    ``ConfigurationError`` — this fallback is dry-run-scoped only.
    """
    from dlc_bridge.verbs import _default_plugin_cache_root, skill_folder_for

    folder = skill_folder_for(verb)
    return (
        _default_plugin_cache_root() / "uninstalled" / "skills" / folder / "SKILL.md"
    )


def _build_dry_run_envelope(
    verb: str,
    skill_path: Path,
    args: argparse.Namespace,
    task_body: str,
) -> dict[str, object]:
    """Assemble the FR-5 dry-run JSON envelope.

    Schema (locked contract):

    .. code-block:: json

       {
         "status": "dry-run",
         "verb": "<verb>",
         "skillPath": "<absolute path to SKILL.md>",
         "command": "claude",
         "args": ["-p", "--append-system-prompt-file", "<skillPath>", ...],
         "assembledPrompt": "<task body>"
       }
    """
    claude_args: list[str] = [
        "-p",
        "--append-system-prompt-file",
        str(skill_path),
        "--permission-mode",
        "bypassPermissions",
        "--max-budget-usd",
        str(args.max_budget_usd),
    ]
    return {
        "status": "dry-run",
        "verb": verb,
        "skillPath": str(skill_path),
        "command": "claude",
        "args": claude_args,
        "assembledPrompt": task_body,
    }


# ----- cache helpers -------------------------------------------------------


def _resolve_cache_input_path(
    verb: str, source: Path | None, target: Path | None
) -> Path | None:
    """Pick the canonical input file for the (verb, slug, hash) cache key.

    Mirrors v1.1's ``Resolve-CacheInputPath`` (dlc-bridge.ps1:304-325).
    """
    if verb in _SOURCE_HASHED_VERBS:
        return source or target
    if verb in _TARGET_HASHED_VERBS:
        return target or source
    return source or target


def _resolve_cache_slug(
    source: Path | None, target: Path | None, pr: int | None, override: str | None
) -> str | None:
    """Derive a slug for cache scoping. Returns None on no-slug-available."""
    if override:
        return override
    for path in (source, target):
        if path is None:
            continue
        try:
            return slug_from_path(path, pr=pr)
        except ValidationError:
            continue
    if pr is not None and pr > 0:
        return f"pr-{pr}"
    return None


def _predict_artifact(
    verb: str, slug: str, *, dlc_root: Path | None = None
) -> str | None:
    """Best-effort prediction of the artifact path a verb should produce.

    Returns a project-relative path string (forward-slash) when one of the
    known suffixes exists on disk under ``.dlc/<slug>/``. Returns None when
    no candidate exists; the caller skips the cache write in that case.
    """
    suffixes = _VERB_TO_ARTIFACT_SUFFIXES.get(verb)
    if not suffixes:
        return None
    root = Path(dlc_root) if dlc_root is not None else Path.cwd() / ".dlc"
    slug_root = root / slug
    for suffix in suffixes:
        candidate = slug_root / suffix
        if candidate.is_file():
            return f".dlc/{slug}/{suffix}".replace("\\", "/")
    return None


# ----- foreground vs background -------------------------------------------


def _emit_cache_hit(slug: str, verb: str, source_hash: str, hit: cache_mod.CacheHit) -> int:
    """Write the v1.1 cache-hit status file + emit BRIDGE_CACHED markers.

    Mirrors ``dlc-bridge.ps1:811-839``: the cache-hit observability JSON
    has a slightly different shape than the regular status file (extra
    ``cachedArtifact`` / ``slug`` / ``inputHash`` fields, no
    ``promptDigest``/``outputManifest``) and is emitted so ``check-dlc-job``
    surfaces cache hits alongside running/complete jobs.
    """
    # Generate a unique cache-hit job-ID: keep the timestamp + random
    # suffix from a fresh job-ID, but prefix with `-cache-hit-` so it's
    # easily distinguishable.
    cache_hit_job_id = f"{verb}-cache-hit-{status_mod.generate_job_id(verb).split('-', 1)[1]}"
    try:
        from dlc_bridge.util.encoding import write_json_utf8_lf
        write_json_utf8_lf(
            status_mod.status_path_for(cache_hit_job_id),
            {
                "jobId": cache_hit_job_id,
                "verb": verb,
                "status": "cache-hit",
                "cachedArtifact": str(hit.artifact_path),
                "startedAt": status_mod.iso_now(),
                "endedAt": status_mod.iso_now(),
                "exitCode": 0,
                "pid": os.getpid(),
                "slug": slug,
                "inputHash": source_hash,
            },
        )
    except OSError as exc:  # pragma: no cover — defensive
        emit_log("warn", f"cache-hit-status-write-failed: {exc}")

    emit_marker("BRIDGE_CACHED", str(hit.artifact_path))
    emit_marker("BRIDGE_EXIT", "0")
    return EXIT_OK


def _spawn_background(
    *,
    job_id: str,
    argv: list[str],
    log_path: Path,
    dlc_root: Path | None,
) -> subprocess.Popen[bytes]:
    """Spawn the background_runner module as a detached child (D-11).

    The parent returns immediately; the child writes the terminal status
    file when claude exits.
    """
    runner_argv: list[str] = [
        sys.executable,
        "-m",
        "dlc_bridge.background_runner",
        "--job-id",
        job_id,
        "--log",
        str(log_path),
    ]
    if dlc_root is not None:
        runner_argv.extend(["--dlc-root", str(dlc_root)])
    runner_argv.append("--")
    runner_argv.extend(argv)

    popen_kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "shell": False,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        popen_kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(runner_argv, **popen_kwargs)


_MANIFEST_PATH_RE = re.compile(
    r"(?:^|\s|\(|\"|`)((?:\.?[/\\]?(?:\.dlc|\.kiro|src|requirements)"
    r"[/\\][\w./\\-]+?\.(?:md|json|xlsx|txt))(?:\s|$|\)|,|\"|`))"
)


def _scan_output_manifest(stdout: str) -> list[str]:
    """Extract artifact paths from claude's stdout. Best-effort port of v1.1.

    Mirrors v1.1's ``Get-DlcOutputManifest`` regex pattern (dlc-bridge.ps1:625-652).
    Returns a sorted, de-duplicated list of paths found in stdout that look
    like artifact paths under ``.dlc/``, ``.kiro/``, ``src/``, ``requirements*``.
    Paths are returned verbatim from stdout — they are NOT verified against
    the filesystem by this scan (callers may filter further).
    """
    if not stdout:
        return []
    found: dict[str, None] = {}
    for m in _MANIFEST_PATH_RE.finditer(stdout):
        raw = m.group(1).rstrip(' )",`')
        found[raw] = None
    return sorted(found.keys())


def _claude_attempt(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One claude attempt. Raises :class:`subprocess.CalledProcessError` on non-zero exit.

    Wrapped by :func:`retry.invoke_with_retry`. Returning the
    :class:`subprocess.CompletedProcess` on success lets the caller harvest
    stdout for the output-manifest scan.
    """
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if proc.returncode != 0:
        # Convert to an exception so invoke_with_retry can apply the
        # transient predicate to proc.stderr.
        raise subprocess.CalledProcessError(
            returncode=proc.returncode,
            cmd=argv,
            output=proc.stdout,
            stderr=proc.stderr,
        )
    return proc


def _is_subprocess_transient(exc: BaseException) -> bool:
    """Predicate for ``invoke_with_retry``: examines stderr for transient regex."""
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr or ""
        return retry_mod.is_transient(stderr)
    return retry_mod.is_transient(str(exc))


# ----- dispatch ------------------------------------------------------------


def _dispatch(args: argparse.Namespace, stdout, stderr) -> int:  # noqa: ANN001
    """Route a parsed ``args`` namespace to live dispatch / dry-run / help."""
    verb: str = args.verb

    if verb == "help":
        return _emit_help(stdout)

    if verb not in SUPPORTED_VERBS:
        supported = ", ".join(sorted(SUPPORTED_VERBS))
        raise ValidationError(
            f"Unknown verb '{verb}'. Supported verbs: {supported}"
        )

    # Validate path args (WI-17).
    if args.source is not None:
        args.source = _validate_path_under_root(args.source, "--source")
    if args.target is not None:
        args.target = _validate_path_under_root(args.target, "--target")

    # Skill + task assembly (WI-16). Skill resolution may raise ConfigurationError
    # when the DLC plugin cache is not installed. For --dry-run we tolerate the
    # missing cache and emit a synthetic placeholder path so dry-run remains
    # usable in environments without the plugin installed (CI, fresh clones).
    # Real dispatch still requires the cache and surfaces the original error.
    try:
        skill_path = resolve_skill_path(verb)
    except ConfigurationError:
        if not args.dry_run:
            raise
        skill_path = _synthetic_dry_run_skill_path(verb)
    verb_args: dict[str, object] = {}
    if args.source is not None:
        verb_args["source"] = str(args.source)
    if args.target is not None:
        verb_args["target"] = str(args.target)
    if args.pr is not None:
        verb_args["pr"] = args.pr
    verb_args["mode"] = args.mode
    if args.slug:
        verb_args["slug"] = args.slug
    task_body = resolve_verb_template(verb, verb_args)

    if args.dry_run:
        envelope = _build_dry_run_envelope(verb, skill_path, args, task_body)
        stdout.write(json.dumps(envelope, indent=2, ensure_ascii=False))
        stdout.write("\n")
        return EXIT_OK

    # Cache check (FR-8/9/10). Skipped on --force / --no-cache.
    bypass_cache = args.force or args.no_cache
    cache_slug: str | None = None
    cache_input_path: Path | None = None
    source_hash: str | None = None

    if not bypass_cache:
        cache_slug = _resolve_cache_slug(args.source, args.target, args.pr, args.slug)
        if cache_slug is None:
            emit_log("info", "cache-skipped: could not derive slug from inputs")
        else:
            cache_input_path = _resolve_cache_input_path(verb, args.source, args.target)
            if cache_input_path is None:
                emit_log("info", f"cache-skipped: no input file to hash for verb '{verb}'")
            elif not Path(cache_input_path).is_file():
                emit_log("info", f"cache-skipped: input file not found at {cache_input_path}")
                cache_input_path = None
            else:
                source_hash = get_normalized_input_hash(Path(cache_input_path))
                hit = cache_mod.check_cache(
                    slug=cache_slug,
                    verb=verb,
                    source_hash=source_hash,
                    max_age_hours=args.cache_max_age_hours,
                )
                if hit is not None:
                    emit_log("info", f"cache-hit: {verb} (slug={cache_slug}) -> {hit.artifact_path}")
                    return _emit_cache_hit(cache_slug, verb, source_hash, hit)
                else:
                    emit_log("info", f"cache-miss: {verb} (slug={cache_slug}); will invoke claude")
    else:
        emit_log("info", "cache-bypass: --force / --no-cache supplied")

    # Build claude argv + assemble status file.
    claude_argv = _build_claude_argv(
        skill_path=skill_path,
        max_budget_usd=args.max_budget_usd,
        task_body=task_body,
    )

    job_id = status_mod.generate_job_id(verb)
    prompt_digest = status_mod.compute_prompt_digest(task_body)

    # Background path (FR-4, WI-18) — parent spawns detached child and exits.
    if args.background:
        log_path = Path.cwd() / ".dlc" / "_bridge-logs" / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        status_mod.initialize_status(
            verb=verb,
            args=_jsonable_args(args),
            job_id=job_id,
            prompt_digest=prompt_digest,
            log_path=str(log_path),
        )
        try:
            _spawn_background(
                job_id=job_id, argv=claude_argv, log_path=log_path, dlc_root=None
            )
        except (OSError, FileNotFoundError) as exc:
            emit_log("error", f"background spawn failed: {exc}")
            status_mod.error_status(job_id=job_id, exit_code=1)
            return EXIT_GENERIC
        emit_marker("BACKGROUND_JOB_ID", job_id)
        return EXIT_OK

    # Foreground path (FR-7 retry-wrapped).
    status_mod.initialize_status(
        verb=verb,
        args=_jsonable_args(args),
        job_id=job_id,
        prompt_digest=prompt_digest,
        log_path="",
    )
    start = time.monotonic()
    attempts = 0

    def _attempt_with_counter() -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        attempts += 1
        return _claude_attempt(claude_argv)

    try:
        proc = retry_mod.invoke_with_retry(
            _attempt_with_counter,
            is_retryable=_is_subprocess_transient,
        )
    except FileNotFoundError as exc:
        emit_log("error", f"claude not on PATH: {exc}")
        status_mod.error_status(
            job_id=job_id,
            exit_code=EXIT_CLAUDE_NOT_FOUND,
            duration_sec=time.monotonic() - start,
            attempts=attempts or 1,
        )
        return EXIT_CLAUDE_NOT_FOUND
    except RetryExhaustedError as exc:
        emit_log("error", f"retries exhausted: {exc}")
        status_mod.error_status(
            job_id=job_id,
            exit_code=5,
            duration_sec=time.monotonic() - start,
            attempts=attempts or len(retry_mod.DEFAULT_BACKOFFS_S),
        )
        return 5
    except subprocess.CalledProcessError as exc:
        emit_log("error", f"claude exited {exc.returncode}: {exc.stderr or ''}")
        status_mod.error_status(
            job_id=job_id,
            exit_code=exc.returncode or 1,
            duration_sec=time.monotonic() - start,
            attempts=attempts or 1,
        )
        return exc.returncode or 1

    # Success — write cache + finalize status.
    duration = time.monotonic() - start
    manifest = _scan_output_manifest(proc.stdout or "")

    if cache_slug and source_hash:
        artifact = _predict_artifact(verb, cache_slug)
        if artifact:
            try:
                cache_mod.write_cache(
                    slug=cache_slug,
                    verb=verb,
                    source_hash=source_hash,
                    artifact_path=artifact,
                )
                emit_log("info", f"cache-write: {verb} (slug={cache_slug}) -> {artifact}")
            except OSError as exc:
                emit_log("warn", f"cache-write-failed: {exc}")
        else:
            emit_log(
                "info",
                f"cache-write-skipped: expected artifact for '{verb}' not present on disk",
            )

    status_mod.complete_status(
        job_id=job_id,
        exit_code=0,
        output_manifest=manifest,
        duration_sec=duration,
        attempts=attempts,
    )

    # BRIDGE_OK marker — first artifact path (if any) is the canonical result.
    bridge_ok_value = manifest[0] if manifest else ""
    emit_marker("BRIDGE_OK", bridge_ok_value)
    emit_marker("BRIDGE_EXIT", "0")
    return EXIT_OK


def _jsonable_args(args: argparse.Namespace) -> dict[str, object]:
    """Convert an argparse namespace into a JSON-friendly dict for the status file."""
    out: dict[str, object] = {}
    for k, v in vars(args).items():
        if isinstance(v, Path):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point."""
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    try:
        parsed = parser.parse_args(list(argv))
    except ValidationError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return exc.exit_code
    except BridgeError as exc:  # pragma: no cover — defensive
        sys.stderr.write(f"error: {exc}\n")
        return exc.exit_code

    try:
        return _dispatch(parsed, sys.stdout, sys.stderr)
    except ValidationError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return exc.exit_code
    except ConfigurationError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return exc.exit_code
    except BridgeError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
