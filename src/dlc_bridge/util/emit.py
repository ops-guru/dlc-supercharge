"""Structured stdout / stderr emitters for the bridge.

v1.1 PowerShell hooks scan bridge output for ``KEY=value`` markers
(``BRIDGE_CACHED=...``, ``PROCEED``, ``DEBOUNCED``, ``EPIC_INJECTED=...``, ...).
These helpers keep the marker format byte-identical so existing hook adapters
don't need to change.
"""

from __future__ import annotations

import sys

__all__ = ["emit_marker", "emit_log"]


def emit_marker(key: str, value: str = "1") -> None:
    """Print a ``KEY=value`` marker to stdout, flushed.

    Examples used by v1.1:

    * ``BRIDGE_CACHED=.dlc/foo/requirements.prd.md``
    * ``PROCEED=1``
    * ``DEBOUNCED=1``
    * ``EPIC_INJECTED=2 tasks=5``

    The default ``value`` of ``"1"`` matches the convention for boolean-flag
    markers (``PROCEED``, ``DEBOUNCED``, etc.).
    """
    sys.stdout.write(f"{key}={value}\n")
    sys.stdout.flush()


def emit_log(level: str, message: str) -> None:
    """Print a structured log line to stderr.

    Format: ``[dlc-bridge] <level>: <message>\\n``. Stderr is intentional —
    stdout is reserved for ``KEY=value`` markers consumed by hooks; mixing log
    chatter on stdout would corrupt the marker stream.
    """
    sys.stderr.write(f"[dlc-bridge] {level}: {message}\n")
    sys.stderr.flush()
