"""Integration tests for :mod:`dlc_bridge.retry` (Epic 2b WI-6, WI-9).

Covers FR-7: exponential backoff + transient-error detection. Parity with
v1.1 ``dlc-bridge-retry.ps1`` is the contract.
"""

from __future__ import annotations

import pytest

from dlc_bridge import retry as retry_mod
from dlc_bridge.exceptions import RetryExhaustedError

pytestmark = pytest.mark.integration


# ----- is_transient (v1.1 transient pattern parity) ------------------------


def test_429_is_transient() -> None:
    assert retry_mod.is_transient("HTTP 429 rate limit exceeded") is True


def test_5xx_is_transient() -> None:
    assert retry_mod.is_transient("HTTP 500 server error") is True
    assert retry_mod.is_transient("HTTP 502 bad gateway") is True
    assert retry_mod.is_transient("HTTP 503 service unavailable") is True
    assert retry_mod.is_transient("HTTP 504 gateway timeout") is True


def test_3xx_4xx_not_transient() -> None:
    """Non-5xx HTTP codes are NOT transient (e.g. 4xx auth failures)."""
    assert retry_mod.is_transient("HTTP 404 not found") is False
    assert retry_mod.is_transient("HTTP 401 unauthorized") is False
    assert retry_mod.is_transient("HTTP 403 forbidden") is False


def test_timeout_phrasings_are_transient() -> None:
    """v1.1 regex: timed?\\s*out — matches timeout, timed out, timedout."""
    assert retry_mod.is_transient("operation timed out") is True
    assert retry_mod.is_transient("timeout exceeded") is True


def test_connection_reset_refused_are_transient() -> None:
    assert retry_mod.is_transient("connection reset by peer") is True
    assert retry_mod.is_transient("connection refused") is True


def test_rate_limit_phrasing_is_transient() -> None:
    """v1.1 regex ``rate\\s*limit`` matches whitespace (or no separator), NOT hyphens."""
    assert retry_mod.is_transient("rate limit exceeded") is True
    assert retry_mod.is_transient("ratelimit hit") is True
    # v1.1 does NOT treat hyphenated forms as transient.
    assert retry_mod.is_transient("just-a-hyphen") is False


def test_temporarily_unavailable_is_transient() -> None:
    assert retry_mod.is_transient("service temporarily unavailable") is True


def test_unrelated_messages_not_transient() -> None:
    assert retry_mod.is_transient("file not found") is False
    assert retry_mod.is_transient("syntax error at line 12") is False
    assert retry_mod.is_transient("validation failed: bad input") is False
    assert retry_mod.is_transient("") is False


def test_case_insensitive_pattern_match() -> None:
    """v1.1 PowerShell -match is case-insensitive."""
    assert retry_mod.is_transient("HTTP 429 RATE LIMIT") is True
    assert retry_mod.is_transient("Connection Reset By Peer") is True
    assert retry_mod.is_transient("TIMED OUT") is True


# ----- invoke_with_retry: success path -------------------------------------


def test_succeeds_on_first_attempt_no_sleeps_called() -> None:
    calls = []
    sleeps: list[float] = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry_mod.invoke_with_retry(fn, sleep=sleeps.append)
    assert result == "ok"
    assert len(calls) == 1
    assert sleeps == []


# ----- invoke_with_retry: eventual success ---------------------------------


def test_succeeds_on_third_attempt_with_v1_1_backoff() -> None:
    """3 attempts, 2 sleeps (2s, 8s), final attempt succeeds — v1.1 parity."""
    counter = {"n": 0}
    sleeps: list[float] = []

    def flaky():
        counter["n"] += 1
        if counter["n"] < 3:
            raise RuntimeError("HTTP 429 rate limit")
        return "ok"

    result = retry_mod.invoke_with_retry(flaky, sleep=sleeps.append)
    assert result == "ok"
    assert counter["n"] == 3
    # v1.1 default: backoffs (2, 8, 32); used [2, 8] at MaxAttempts=3.
    assert sleeps == [2.0, 8.0]


def test_succeeds_on_second_attempt() -> None:
    counter = {"n": 0}
    sleeps: list[float] = []

    def flaky():
        counter["n"] += 1
        if counter["n"] < 2:
            raise RuntimeError("HTTP 503")
        return 42

    result = retry_mod.invoke_with_retry(flaky, sleep=sleeps.append)
    assert result == 42
    assert counter["n"] == 2
    assert sleeps == [2.0]  # only 1 sleep needed


# ----- invoke_with_retry: exhaustion ---------------------------------------


def test_exhausts_and_raises_after_max_attempts() -> None:
    counter = {"n": 0}
    sleeps: list[float] = []

    def always_transient():
        counter["n"] += 1
        raise RuntimeError("HTTP 429 too many requests")

    with pytest.raises(RetryExhaustedError):
        retry_mod.invoke_with_retry(always_transient, sleep=sleeps.append)
    # v1.1 default: 3 total attempts.
    assert counter["n"] == 3
    # 2 sleeps used (2s, 8s); third attempt fails without sleeping.
    assert sleeps == [2.0, 8.0]


def test_retry_exhausted_error_exit_code_is_5() -> None:
    """RetryExhaustedError carries exit_code=5 (FR-7 contract)."""
    try:
        retry_mod.invoke_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("HTTP 500 server error")),
            sleep=lambda _: None,
        )
    except RetryExhaustedError as exc:
        assert exc.exit_code == 5
    else:
        pytest.fail("expected RetryExhaustedError")


# ----- invoke_with_retry: non-transient short-circuit ----------------------


def test_non_transient_not_retried() -> None:
    counter = {"n": 0}
    sleeps: list[float] = []

    def non_transient():
        counter["n"] += 1
        raise RuntimeError("validation failed: bad input")

    with pytest.raises(RuntimeError, match="validation failed"):
        retry_mod.invoke_with_retry(non_transient, sleep=sleeps.append)

    assert counter["n"] == 1  # NOT retried
    assert sleeps == []  # NO sleeps


# ----- invoke_with_retry: custom predicate ---------------------------------


def test_custom_predicate_overrides_default() -> None:
    """Caller can supply a custom is_retryable predicate."""
    counter = {"n": 0}
    sleeps: list[float] = []

    def fail_with_unrelated_error():
        counter["n"] += 1
        raise ValueError("something else")

    # Default predicate would NOT retry (no transient match). Custom one will.
    with pytest.raises(RetryExhaustedError):
        retry_mod.invoke_with_retry(
            fail_with_unrelated_error,
            is_retryable=lambda exc: isinstance(exc, ValueError),
            sleep=sleeps.append,
        )
    assert counter["n"] == 3
    assert sleeps == [2.0, 8.0]


def test_custom_predicate_can_opt_out_of_transient() -> None:
    """Custom predicate returning False short-circuits even on a 429."""
    counter = {"n": 0}

    with pytest.raises(RuntimeError, match="HTTP 429"):
        retry_mod.invoke_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
            is_retryable=lambda exc: False,  # never retry
            sleep=lambda _: None,
        )


# ----- invoke_with_retry: backoff config -----------------------------------


def test_backoff_index_clamps_when_attempts_exceed_backoffs() -> None:
    """v1.1 clamp: ``Backoffs[min(attempt-1, len-1)]``."""
    counter = {"n": 0}
    sleeps: list[float] = []

    def always_transient():
        counter["n"] += 1
        raise RuntimeError("HTTP 429")

    # Custom: 5 attempts, but only 2 backoff entries [1, 4]. Indices 0,1,1,1
    # for sleeps at attempts 1,2,3,4 (sleep happens before next attempt).
    with pytest.raises(RetryExhaustedError):
        retry_mod.invoke_with_retry(
            always_transient,
            backoffs=(1.0, 4.0),
            max_attempts=5,
            sleep=sleeps.append,
        )
    assert counter["n"] == 5
    # 4 sleeps for 5 attempts; indices clamp to (1.0, 4.0, 4.0, 4.0).
    assert sleeps == [1.0, 4.0, 4.0, 4.0]


def test_max_attempts_1_means_no_retry() -> None:
    counter = {"n": 0}
    sleeps: list[float] = []
    with pytest.raises(RetryExhaustedError):
        retry_mod.invoke_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
            max_attempts=1, sleep=sleeps.append,
        )
    assert sleeps == []  # no sleeps when only 1 attempt allowed


def test_invalid_max_attempts_rejected() -> None:
    with pytest.raises(ValueError):
        retry_mod.invoke_with_retry(lambda: None, max_attempts=0)


def test_empty_backoffs_rejected() -> None:
    with pytest.raises(ValueError):
        retry_mod.invoke_with_retry(lambda: None, backoffs=())


# ----- invoke_with_retry: args / kwargs pass-through ----------------------


def test_args_kwargs_passed_through() -> None:
    def fn(a, b, *, c):
        return a + b + c

    result = retry_mod.invoke_with_retry(fn, 1, 2, c=3)
    assert result == 6
