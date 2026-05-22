"""Command-line dispatcher for the DLC bridge (FR-1, FR-3, FR-5, FR-17).

This module is the console-script entry point declared in ``pyproject.toml``
under ``[project.scripts]``:

    dlc-bridge = "dlc_bridge.cli:main"

Behaviour summary
-----------------

* ``dlc-bridge help`` — prints a help banner listing the 16 supported verbs
  and the principal flags, then exits 0.
* ``dlc-bridge <verb> --dry-run [...]`` — emits a JSON envelope to stdout
  matching the FR-5 contract and exits 0. No side effects.
* ``dlc-bridge <verb> [...]`` (live dispatch) — Epic 1 stub: prints
  ``NOT_IMPLEMENTED`` to stderr and exits 2. The real ``claude -p`` invocation
  lands in Epic 2 WI-16.
* Validation failures (unknown verb, out-of-range int, traversal path, etc.)
  raise :class:`~dlc_bridge.exceptions.ValidationError` and exit 4.

All numeric ranges and the path-traversal guard are implemented here
(WI-2 + WI-17). The dry-run JSON schema is the contract Epic 2 must preserve.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from dlc_bridge import __version__
from dlc_bridge.exceptions import BridgeError, ConfigurationError, ValidationError
from dlc_bridge.verbs import SUPPORTED_VERBS, resolve_skill_path

# Sentinel exit codes that the dispatcher itself returns (in addition to the
# exit-code attributes on :class:`BridgeError` subclasses).
EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 2

# Numeric range limits for argparse validation (FR-3).
MAX_FILES_MIN = 1
MAX_FILES_MAX = 5000
MAX_FILES_DEFAULT = 200

MAX_BUDGET_USD_MIN = 0.0
MAX_BUDGET_USD_MAX = 50.0
MAX_BUDGET_USD_DEFAULT = 5.0

CACHE_MAX_AGE_HOURS_DEFAULT = 0.0  # 0 == no expiry

MODE_CHOICES = ("interactive", "confident", "autopilot")

# Help text emitted by ``dlc-bridge help``. Byte-identical parity with v1.1 is
# enforced by the Epic 4 parity gate; for Epic 1 the contract is just "lists
# all 16 verbs and exits 0".
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
    --dry-run                  Print JSON envelope and exit 0; no side effects

Exit codes:
    0   success
    1   generic bridge failure
    2   NOT_IMPLEMENTED (Epic 1 dispatch stub; see Epic 2 WI-16)
    4   input validation / path traversal / unknown verb
    5   retries exhausted (transient failures)
    7   blocked by debounce / cross-process lock
    9   bootstrap / plugin-cache configuration failure
"""


class _RaisingArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that raises ``ValidationError`` instead of
    calling :func:`sys.exit` on error.

    This lets :func:`main` route every parse failure through the same
    ``BridgeError`` exit-code translation, guaranteeing argparse failures
    surface as exit 4 rather than argparse's default exit 2.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValidationError(message)


def _validate_path_under_root(
    value: str, label: str, root: Path | None = None
) -> Path:
    """Resolve ``value`` and verify it stays under ``root`` (project root).

    Args:
        value: Raw string from argparse (``--source`` / ``--target``).
        label: Human-readable arg label for the error message (e.g. ``"--source"``).
        root: Project root to check against. Defaults to :func:`Path.cwd`.

    Returns:
        Resolved absolute :class:`Path` of ``value``.

    Raises:
        ValidationError: If the resolved candidate escapes ``root``.
    """
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
        raise ValidationError(
            f"{label} must be in [{low}, {high}], got {n}"
        )
    return n


def _float_range(value: str, *, label: str, low: float, high: float) -> float:
    """Argparse type-converter for bounded floats (FR-3)."""
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a number, got '{value}'") from exc
    if x < low or x > high:
        raise ValidationError(
            f"{label} must be in [{low}, {high}], got {x}"
        )
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
    """Construct the argparse parser used by :func:`main`.

    Exposed publicly so tests can introspect or extend the parser without
    invoking the full dispatch path.
    """
    parser = _RaisingArgumentParser(
        prog="dlc-bridge",
        description="DLC SuperCharge bridge — Python runtime for /dlc: hookchain.",
        add_help=False,  # we render our own help via the `help` verb
    )
    parser.add_argument(
        "verb",
        help="One of the 16 supported verbs, or 'help'.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Input artifact path (must resolve under project root).",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Output artifact path (must resolve under project root).",
    )
    parser.add_argument(
        "--mode",
        default="confident",
        choices=MODE_CHOICES,
        help="Interaction mode (default: confident).",
    )
    parser.add_argument(
        "--pr",
        default=None,
        type=lambda v: _positive_int(v, label="--pr"),
        help="Pull-request number (positive integer).",
    )
    parser.add_argument(
        "--max-files",
        default=MAX_FILES_DEFAULT,
        type=lambda v: _int_range(
            v, label="--max-files", low=MAX_FILES_MIN, high=MAX_FILES_MAX
        ),
        help=f"Cap on files inspected ({MAX_FILES_MIN}..{MAX_FILES_MAX}, "
        f"default {MAX_FILES_DEFAULT}).",
    )
    parser.add_argument(
        "--max-budget-usd",
        default=MAX_BUDGET_USD_DEFAULT,
        type=lambda v: _float_range(
            v,
            label="--max-budget-usd",
            low=MAX_BUDGET_USD_MIN,
            high=MAX_BUDGET_USD_MAX,
        ),
        help=f"Claude budget cap ({MAX_BUDGET_USD_MIN}..{MAX_BUDGET_USD_MAX}, "
        f"default {MAX_BUDGET_USD_DEFAULT}).",
    )
    parser.add_argument(
        "--cache-max-age-hours",
        default=CACHE_MAX_AGE_HOURS_DEFAULT,
        type=lambda v: _non_negative_float(v, label="--cache-max-age-hours"),
        help="Cache TTL in hours; 0 = no expiry (default 0).",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Run detached (returns jobId immediately). Full implementation in Epic 2 WI-18.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass cache lookup.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON envelope and exit 0; no side effects.",
    )
    return parser


def _emit_help(stream) -> int:  # noqa: ANN001 — any text stream
    """Print the help banner and return exit 0."""
    stream.write(_HELP_TEXT.format(version=__version__))
    return EXIT_OK


def _build_dry_run_envelope(
    verb: str,
    skill_path: Path,
    args: argparse.Namespace,
) -> dict[str, object]:
    """Assemble the FR-5 dry-run JSON envelope.

    Schema (locked contract — Epic 2 WI-16 must preserve):

    .. code-block:: json

       {
         "status": "dry-run",
         "verb": "<verb>",
         "skillPath": "<absolute path to SKILL.md>",
         "command": "claude",
         "args": ["-p", "--append-system-prompt-file", "<skillPath>", ...],
         "assembledPrompt": "(deferred to Epic 2 WI-16)"
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
        "assembledPrompt": "(deferred to Epic 2 WI-16)",
    }


def _dispatch(args: argparse.Namespace, stdout, stderr) -> int:  # noqa: ANN001
    """Route a parsed ``args`` namespace to dry-run or stub dispatch.

    Side effects (writes to ``stdout`` / ``stderr``) are confined to this
    function so unit tests can capture them via ``capsys``.
    """
    verb: str = args.verb

    if verb == "help":
        return _emit_help(stdout)

    if verb not in SUPPORTED_VERBS:
        supported = ", ".join(sorted(SUPPORTED_VERBS))
        raise ValidationError(
            f"Unknown verb '{verb}'. Supported verbs: {supported}"
        )

    # Validate path args (WI-17). These are resolved against CWD, which the
    # hook caller is expected to set to the project root.
    if args.source is not None:
        args.source = _validate_path_under_root(args.source, "--source")
    if args.target is not None:
        args.target = _validate_path_under_root(args.target, "--target")

    # Skill resolution — fail with ConfigurationError (exit 9) if the plugin
    # cache is missing. Tests typically monkeypatch :func:`resolve_skill_path`
    # or pass ``--dry-run`` against a stubbed plugin-cache fixture.
    skill_path = resolve_skill_path(verb)

    if args.dry_run:
        envelope = _build_dry_run_envelope(verb, skill_path, args)
        stdout.write(json.dumps(envelope, indent=2, ensure_ascii=False))
        stdout.write("\n")
        return EXIT_OK

    # Real dispatch — deferred to Epic 2 WI-16. Print a clear sentinel and
    # exit 2 so callers can distinguish "feature not yet built" from real
    # failures.
    stderr.write(
        "NOT_IMPLEMENTED: real `claude -p` invocation is deferred to Epic 2 WI-16. "
        "Use --dry-run to exercise the dispatch path in Epic 1.\n"
    )
    return EXIT_NOT_IMPLEMENTED


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point.

    Args:
        argv: Optional argv list (sans program name). Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (0 on success; see :mod:`dlc_bridge.exceptions` for
        the full mapping).
    """
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
