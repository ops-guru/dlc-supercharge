"""FR-18 cross-process fire-suppression.

Two API shapes are exposed:

* :func:`check_debounce` — simpler mtime-on-lockfile model (per the brief).
  Caller picks a stable ``lock_path`` keyed on whatever they like (e.g.
  ``.dlc/_bridge-jobs/<slug>-<verb>.lock``). First call within the window
  proceeds and touches the lock file; subsequent calls within ``window_seconds``
  of the lock-file's mtime are debounced.
* :func:`check_debounce_keyed` — v1.1-parity model with a JSON state file
  keyed by ``<HookId>::<TriggerPath>``. Used by hook adapters in Epic 3.

Both share :mod:`filelock` (D-2) for cross-process safety, and both fail-open
on lock-acquisition timeout (matches v1.1 — printing ``PROCEED`` on lock
timeout is preferable to deadlocking the orchestrator).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from dlc_bridge.util.encoding import atomic_write_bytes

__all__ = ["check_debounce", "check_debounce_keyed"]


def check_debounce(
    *,
    lock_path: Path,
    window_seconds: float = 120.0,
    timeout_seconds: float = 5.0,
) -> bool:
    """Return ``True`` to PROCEED, ``False`` if the call should be DEBOUNCED.

    Algorithm:

    1. Acquire ``FileLock(lock_path.with_suffix(...+'.flock'))`` with
       ``timeout_seconds``. On timeout, emit a warning and return ``True``
       (fail-open).
    2. With the lock held:
       a. If ``lock_path`` exists and ``now - mtime < window_seconds`` →
          return ``False`` (DEBOUNCED).
       b. Otherwise touch ``lock_path`` (update mtime) and return ``True``.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flock_path = lock_path.with_name(lock_path.name + ".flock")

    try:
        with FileLock(str(flock_path), timeout=timeout_seconds):
            now = time.time()
            if lock_path.exists():
                mtime = lock_path.stat().st_mtime
                if (now - mtime) < window_seconds:
                    return False
            # Touch the file (create or update mtime).
            lock_path.touch()
            # Force the mtime forward to "now" — filesystems may round.
            import os
            os.utime(lock_path, (now, now))
            return True
    except Timeout:
        sys.stderr.write(
            f"[dlc-bridge] warning: could not acquire {flock_path} within "
            f"{timeout_seconds}s; failing open (PROCEED)\n"
        )
        sys.stderr.flush()
        return True


def check_debounce_keyed(
    *,
    state_path: Path,
    hook_id: str,
    trigger_path: str,
    window_seconds: float = 120.0,
    gc_seconds: float = 300.0,
    timeout_seconds: float = 5.0,
) -> bool:
    """V1.1-parity debounce — keyed by ``HookId::TriggerPath`` in a JSON map.

    Matches ``debounce-check.ps1`` semantics. The JSON map at ``state_path``
    is rewritten atomically on every proceed, with entries older than
    ``gc_seconds`` garbage-collected.
    """
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    flock_path = state_path.with_name(state_path.name + ".lock")

    try:
        with FileLock(str(flock_path), timeout=timeout_seconds):
            content: dict[str, int] = {}
            if state_path.exists():
                try:
                    raw = state_path.read_text(encoding="utf-8")
                    if raw.strip():
                        loaded = json.loads(raw)
                        if isinstance(loaded, dict):
                            content = {k: int(v) for k, v in loaded.items()}
                except (json.JSONDecodeError, ValueError):
                    content = {}

            key = f"{hook_id}::{trigger_path}"
            now = int(time.time())
            last_fire = content.get(key, 0)

            if (now - last_fire) < window_seconds:
                return False

            content[key] = now

            # GC entries older than gc_seconds.
            to_remove = [
                k for k, ts in content.items() if (now - ts) >= gc_seconds
            ]
            for k in to_remove:
                content.pop(k, None)

            # Atomic write (compact JSON, no trailing newline, matches v1.1).
            data = json.dumps(content, separators=(",", ":")).encode("utf-8")
            atomic_write_bytes(state_path, data)
            return True
    except Timeout:
        sys.stderr.write(
            f"[dlc-bridge] warning: could not acquire {flock_path} within "
            f"{timeout_seconds}s; failing open (PROCEED)\n"
        )
        sys.stderr.flush()
        return True
