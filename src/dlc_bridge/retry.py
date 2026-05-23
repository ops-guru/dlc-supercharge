"""FR-7 retry helper with exponential backoff + v1.1 transient detection.

Wraps a callable that may fail with a transient (retryable) error and
re-tries up to a fixed budget with growing backoff between attempts.

Parity contract with v1.1
-------------------------

Ported line-by-line from ``.kiro/scripts/dlc-bridge-retry.ps1`` (89 LOC).
Key invariants:

* **3 total attempts by default.** ``MaxAttempts=3``.
* **2 sleeps between attempts.** Backoffs are ``[2.0, 8.0, 32.0]`` but the
  loop returns ``retries-exhausted`` BEFORE sleeping on the final failed
  attempt, so at the default budget only the first 2 entries are used
  (``2s``, ``8s``). The literal ``32s`` is kept in the config so callers
  raising ``MaxAttempts`` to 4 get the documented behavior.
* **Index clamp.** Sleep duration is ``Backoffs[min(attempt-1, len-1)]`` —
  matches v1.1's ``[Math]::Min($attempt - 1, $Backoffs.Count - 1)``.
* **Transient regex set.** Six case-insensitive patterns lifted verbatim
  from v1.1's ``$Script:DlcTransientPatterns``:

  * ``\\b429\\b`` (Too many requests)
  * ``\\b5\\d\\d\\b`` (5xx server errors)
  * ``timed?\\s*out`` (Timeouts)
  * ``connection\\s*(reset|refused)`` (Network resets)
  * ``temporarily\\s*unavailable`` (Service degradation)
  * ``rate\\s*limit`` (Generic rate-limit phrasing)

  The brief listed additional patterns ("internal server error",
  "service unavailable", "5xx") — those are subsumed by ``\\b5\\d\\d\\b``
  in practice. We follow v1.1 EXACTLY (parity wins).
* **Non-transient short-circuit.** Non-transient failures return
  immediately on the first attempt; only the transient class is retried.
* **Exit-code 5 on exhaustion.** When all attempts fail transiently, raise
  :class:`~dlc_bridge.exceptions.RetryExhaustedError` (whose ``exit_code``
  is 5). v1.1 returns ``status='retries-exhausted'``, ``exit=5`` from the
  helper; cli.py translates either form to ``sys.exit(5)``.
"""

from __future__ import annotations

import re
import time
from typing import Callable, TypeVar

from dlc_bridge.exceptions import RetryExhaustedError

__all__ = [
    "DEFAULT_BACKOFFS_S",
    "DEFAULT_MAX_ATTEMPTS",
    "TRANSIENT_PATTERNS",
    "is_transient",
    "invoke_with_retry",
]

T = TypeVar("T")

# v1.1 ``$Script:DlcTransientPatterns`` ported verbatim. Lines 19-27 of
# ``dlc-bridge-retry.ps1``. Case-insensitive when applied via :func:`is_transient`.
TRANSIENT_PATTERNS: tuple[str, ...] = (
    r"\b429\b",
    r"\b5\d\d\b",
    r"timed?\s*out",
    r"connection\s*(reset|refused)",
    r"temporarily\s*unavailable",
    r"rate\s*limit",
)
_TRANSIENT_RE = re.compile("|".join(TRANSIENT_PATTERNS), re.IGNORECASE)

# v1.1 defaults from ``dlc-bridge-retry.ps1:73-74``.
DEFAULT_BACKOFFS_S: tuple[float, ...] = (2.0, 8.0, 32.0)
DEFAULT_MAX_ATTEMPTS: int = 3


def is_transient(text: str) -> bool:
    """Return True if ``text`` (typically stderr) matches any transient pattern.

    Mirrors v1.1's ``Test-DlcTransientError`` semantics — but takes a single
    string argument rather than the ``(ExitCode, Stderr)`` tuple. Callers
    that want the exit-code short-circuit (``ExitCode == 0`` → ``False``)
    should check the exit code themselves before consulting this function.
    """
    if not text:
        return False
    return _TRANSIENT_RE.search(text) is not None


def invoke_with_retry(
    fn: Callable[..., T],
    *args,
    backoffs: tuple[float, ...] = DEFAULT_BACKOFFS_S,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    is_retryable: Callable[[BaseException], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> T:
    """Invoke ``fn(*args, **kwargs)`` with exponential-backoff retry.

    Args:
        fn: The callable to invoke. Returns ``T`` on success or raises any
            exception.
        backoffs: Per-attempt sleep durations in seconds. Indexed by
            ``min(attempt - 1, len(backoffs) - 1)`` — matches v1.1's clamp.
        max_attempts: Total attempt budget (including the first). Default 3.
        is_retryable: Predicate ``Callable[[BaseException], bool]``. When
            None (default), uses :func:`is_transient` against the exception's
            string form. Pass a custom predicate to retry based on a
            subprocess result's stderr (the cli.py wiring does exactly this).
        sleep: Injection point for tests — :func:`time.sleep` by default.

    Returns:
        Whatever ``fn`` returned on the first successful attempt.

    Raises:
        RetryExhaustedError: All ``max_attempts`` failed AND every failure
            was classified as retryable (i.e. the retry budget was actually
            consumed). The original exception is chained via ``__cause__``.
        BaseException: The first failure that is NOT classified as
            retryable, re-raised verbatim (v1.1's ``status='non-transient'``
            branch).

    Trace at default (max_attempts=3, backoffs=(2,8,32)):
        1. attempt=1 fails-retryable → sleep backoffs[0]=2 → attempt=2
        2. attempt=2 fails-retryable → sleep backoffs[1]=8 → attempt=3
        3. attempt=3 fails-retryable → IS final → raise RetryExhaustedError
        (no sleep, no attempt 4, the literal 32 is never used at default)
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if not backoffs:
        raise ValueError("backoffs must be a non-empty sequence")

    predicate = is_retryable or (lambda exc: is_transient(str(exc)))
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — caller controls predicate
            last_exc = exc
            if not predicate(exc):
                # Non-transient: re-raise immediately (v1.1's 'non-transient' branch).
                raise

            if attempt >= max_attempts:
                # Retry budget exhausted.
                raise RetryExhaustedError(
                    f"retries exhausted after {attempt} attempts: {exc}"
                ) from exc

            backoff_idx = min(attempt - 1, len(backoffs) - 1)
            sleep(backoffs[backoff_idx])

    # Unreachable — loop either returns, re-raises, or raises
    # RetryExhaustedError. Guards against future edits.
    raise RetryExhaustedError(  # pragma: no cover — defensive
        f"retries exhausted: {last_exc}"
    )
