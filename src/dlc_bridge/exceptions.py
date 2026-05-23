"""Typed exception hierarchy for the DLC bridge.

Each exception carries an ``exit_code`` class attribute so :func:`dlc_bridge.cli.main`
can translate raised errors into deterministic process exit codes that match the
v1.1 PowerShell bridge contract (FR-3).

Exit-code map (mirrors v1.1 ``dlc-bridge.ps1`` and tech-design Section 5.5):

* ``0`` — success (no exception)
* ``1`` — generic bridge failure (:class:`BridgeError`, :class:`CacheError`)
* ``2`` — sentinel ``NOT_IMPLEMENTED`` reserved for the Epic 1 dispatch stub
* ``4`` — input validation failure (:class:`ValidationError`)
* ``5`` — retries exhausted (:class:`RetryExhaustedError`)
* ``7`` — blocked by debounce / lock (:class:`BlockedError`)
* ``9`` — bootstrap / configuration failure (:class:`ConfigurationError`)
"""

from __future__ import annotations


class BridgeError(Exception):
    """Base class for all bridge errors.

    Subclasses override ``exit_code`` to align with the v1.1 exit-code contract.
    """

    exit_code: int = 1

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.__class__.__name__)


class ValidationError(BridgeError):
    """Argparse / input validation failure (exit 4)."""

    exit_code: int = 4


class ConfigurationError(BridgeError):
    """Bootstrap / environment / plugin-cache configuration failure (exit 9)."""

    exit_code: int = 9


class CacheError(BridgeError):
    """Cache read/write failure (exit 1)."""

    exit_code: int = 1


class RetryExhaustedError(BridgeError):
    """Transient-failure retry budget exhausted (exit 5)."""

    exit_code: int = 5


class BlockedError(BridgeError):
    """Invocation blocked by debounce or cross-process lock (exit 7)."""

    exit_code: int = 7


__all__ = [
    "BridgeError",
    "BlockedError",
    "CacheError",
    "ConfigurationError",
    "RetryExhaustedError",
    "ValidationError",
]
