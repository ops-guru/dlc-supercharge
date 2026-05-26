"""Self-fire suppression via post-write content-hash registry.

When DLC-orchestrated logic (id_propagate, epic_inject, or other future
writers) writes to a Kiro spec file (``requirements.md``, ``design.md``,
``tasks.md``), that write changes the file's mtime + content hash, which
Kiro detects as a ``fileEdited`` event and re-fires the same hook —
causing a cache-miss self-fire loop (Issue #8).

This module records the post-write SHA-256 of each affected file in a
per-slug JSON registry. On the next hook fire, the hook can compare the
trigger file's current hash against the registry — if it matches a
recent self-write, the fire is treated as a self-trigger and suppressed.

State file
----------

``.dlc/<slug>/_self-writes.json``::

    {
      "<absolute-file-path>": [
        {"sha256": "<hex>", "at": <unix-timestamp-int>},
        ...
      ]
    }

* Up to :data:`MAX_ENTRIES_PER_FILE` entries are retained per file (FIFO).
* Entries older than ``ttl_seconds`` (default 600s) are GC'd on every
  :func:`record` call.

Concurrency
-----------

Uses :class:`filelock.FileLock` for the same cross-process safety as
:mod:`dlc_bridge.util.debounce`. Both :func:`record` and
:func:`is_self_fire` fail-open on lock timeout — recording a duplicate
or missing a self-fire is preferable to deadlocking the hook.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from dlc_bridge.util.encoding import atomic_write_bytes

__all__ = ["sha256_of_file", "record", "is_self_fire"]


MAX_ENTRIES_PER_FILE = 10
DEFAULT_TTL_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 5.0
REGISTRY_FILENAME = "_self-writes.json"


def sha256_of_file(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``'s contents.

    Streamed read; safe for files up to GBs.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _registry_path(slug_root: Path) -> Path:
    return Path(slug_root) / REGISTRY_FILENAME


def _load(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        raw = state_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _gc_and_truncate(
    entries: list, ttl_seconds: int, now_ts: int
) -> list:
    """Drop entries older than ``ttl_seconds``, keep at most
    :data:`MAX_ENTRIES_PER_FILE` (newest)."""
    pruned = [
        e
        for e in entries
        if isinstance(e, dict) and (now_ts - int(e.get("at", 0))) < ttl_seconds
    ]
    if len(pruned) > MAX_ENTRIES_PER_FILE:
        pruned = pruned[-MAX_ENTRIES_PER_FILE:]
    return pruned


def record(
    *,
    file_path: Path,
    slug_root: Path,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Compute SHA-256 of ``file_path`` and append it to the registry.

    Call this **after** any DLC-orchestrated write to a Kiro spec file
    (post id_propagate, post epic_inject, etc.). Returns the digest;
    empty string if ``file_path`` doesn't exist or recording failed.

    Adjacent-duplicate entries (same digest as the last recorded entry)
    just bump the timestamp instead of growing the list — keeps the
    registry compact when a writer runs multiple times without changing
    the file.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return ""

    slug_root = Path(slug_root)
    slug_root.mkdir(parents=True, exist_ok=True)
    state_path = _registry_path(slug_root)
    flock_path = state_path.with_name(state_path.name + ".lock")

    digest = sha256_of_file(file_path)
    abs_key = str(file_path.resolve())
    now_ts = int(time.time())

    try:
        with FileLock(str(flock_path), timeout=timeout_seconds):
            data = _load(state_path)
            entries = data.get(abs_key, [])
            if not isinstance(entries, list):
                entries = []
            if entries and entries[-1].get("sha256") == digest:
                entries[-1]["at"] = now_ts
            else:
                entries.append({"sha256": digest, "at": now_ts})
            entries = _gc_and_truncate(entries, ttl_seconds, now_ts)
            data[abs_key] = entries
            encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
            atomic_write_bytes(state_path, encoded)
    except Timeout:
        sys.stderr.write(
            f"[dlc-bridge] warning: could not acquire {flock_path} within "
            f"{timeout_seconds}s; skipping self-write record\n"
        )
        sys.stderr.flush()
    return digest


def is_self_fire(
    *,
    file_path: Path,
    slug_root: Path,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Return ``True`` iff ``file_path``'s current SHA-256 matches a
    recent registry entry for that path within ``ttl_seconds``.

    Fail-open: returns ``False`` on missing file, missing registry,
    parse error, or lock timeout — better to over-fire than to silently
    swallow a legitimate edit.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return False

    state_path = _registry_path(Path(slug_root))
    if not state_path.exists():
        return False

    abs_key = str(file_path.resolve())
    now_ts = int(time.time())
    flock_path = state_path.with_name(state_path.name + ".lock")

    try:
        digest = sha256_of_file(file_path)
    except OSError:
        return False

    try:
        with FileLock(str(flock_path), timeout=timeout_seconds):
            data = _load(state_path)
    except Timeout:
        return False

    entries = data.get(abs_key) or []
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("sha256") != digest:
            continue
        entry_at = int(entry.get("at", 0))
        if (now_ts - entry_at) < ttl_seconds:
            return True
    return False
