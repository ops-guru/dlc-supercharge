"""FR-8 / FR-9 / FR-10 hash cache for bridge invocations.

The bridge cache short-circuits a verb invocation when the (slug, verb,
normalized-input-hash) tuple already maps to a successfully-produced artifact
that still exists on disk. The cache file lives at
``.dlc/<slug>/_bridge-cache.json`` and is the per-spec scoping unit.

Schema (v2, FR-9 / D-6)
-----------------------

::

    {
      "cache_version": 2,
      "analyze-requirements": {
        "hash": "<sha256 hex>",
        "artifact_path": ".dlc/<slug>/requirements.prd.md",
        "last_success_at": "2026-05-22T01:30:00Z"
      },
      "produce-tech-design": { ... }
    }

The top-level ``cache_version`` field is the only intentional shape change
from v1.1 (which had a flat verb→entry map with no version marker). v1 cache
files (missing the field, or `cache_version != 2`) are treated as a complete
miss on first v2 read so callers re-compute exactly once per verb on upgrade.

Parity with v1.1
----------------

Mirrors ``dlc-bridge.ps1`` helpers:

* :func:`check_cache` ~ ``Test-BridgeCache`` (read + TTL + artifact-exists check)
* :func:`write_cache` ~ ``Set-BridgeCache`` (atomic upsert)
* :func:`invalidate_cache` ~ no v1 analog (utility for tests / hooks)
* :func:`cache_path_for` ~ ``Get-BridgeCachePath``

All writes go through :func:`dlc_bridge.util.encoding.write_json_utf8_lf`
(NFR-3/NFR-4 — UTF-8 no-BOM, LF, atomic temp+rename, byte-equality guard).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dlc_bridge.util.encoding import write_json_utf8_lf

__all__ = [
    "CACHE_VERSION",
    "CacheEntry",
    "CacheHit",
    "cache_path_for",
    "load_cache",
    "check_cache",
    "write_cache",
    "invalidate_cache",
]

# FR-9 / D-6 — bumping invalidates all v1 entries on first v2 read.
CACHE_VERSION: int = 2


@dataclass(frozen=True)
class CacheEntry:
    """On-disk shape of a single (slug, verb) cache record."""

    hash: str
    artifact_path: str
    last_success_at: str  # ISO-8601 UTC, e.g. "2026-05-22T01:30:00Z"

    def to_dict(self) -> dict[str, str]:
        return {
            "hash": self.hash,
            "artifact_path": self.artifact_path,
            "last_success_at": self.last_success_at,
        }


@dataclass(frozen=True)
class CacheHit:
    """Returned by :func:`check_cache` when a valid entry is found."""

    verb: str
    artifact_path: Path
    age_hours: float


def _iso_now() -> str:
    """Return current UTC time in v1.1's ISO-8601 format (``...Z``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_dlc_root(dlc_root: Path | None) -> Path:
    """Return the ``.dlc`` directory; defaults to ``<cwd>/.dlc``.

    Tests pass an explicit ``dlc_root`` rooted at ``tmp_path``; production
    code derives it from the current working directory (which the bridge
    caller is expected to set to the project root).
    """
    return Path(dlc_root) if dlc_root is not None else Path.cwd() / ".dlc"


def cache_path_for(slug: str, *, dlc_root: Path | None = None) -> Path:
    """Return the absolute path to ``.dlc/<slug>/_bridge-cache.json``.

    Mirrors v1.1's ``Get-BridgeCachePath``. Does NOT create the parent
    directory; callers that need the file write through :func:`write_cache`
    which handles directory creation.
    """
    return _resolve_dlc_root(dlc_root) / slug / "_bridge-cache.json"


def load_cache(slug: str, *, dlc_root: Path | None = None) -> dict[str, Any]:
    """Read the cache file for ``slug``.

    Returns ``{}`` when:

    * The file does not exist.
    * The file is malformed JSON.
    * The top-level ``cache_version`` field is missing or != :data:`CACHE_VERSION`
      (FR-9 / D-6 — v1 entries silently miss).

    Otherwise returns the parsed JSON dict. Per-verb entries live as
    top-level keys alongside ``cache_version`` (matches v1.1 flat shape; the
    brief's nested ``entries`` form is NOT used — parity wins).
    """
    path = cache_path_for(slug, dlc_root=dlc_root)
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("cache_version") != CACHE_VERSION:
        # FR-9 / D-6: v1 entries treated as miss.
        return {}
    return data


def _entry_from_raw(raw: Any) -> CacheEntry | None:
    """Coerce a JSON sub-dict to a :class:`CacheEntry`, or None if malformed."""
    if not isinstance(raw, dict):
        return None
    h = raw.get("hash")
    p = raw.get("artifact_path")
    ts = raw.get("last_success_at")
    if not isinstance(h, str) or not isinstance(p, str) or not isinstance(ts, str):
        return None
    return CacheEntry(hash=h, artifact_path=p, last_success_at=ts)


def _resolve_artifact(artifact_path: str, dlc_root: Path | None) -> Path:
    """Resolve ``artifact_path`` against the project root (parent of ``.dlc``).

    Mirrors v1.1: if the artifact path is absolute use it as-is; otherwise
    join against the project root (NOT ``.dlc``). The cache stores paths like
    ``.dlc/<slug>/requirements.prd.md`` which join to the project root.
    """
    p = Path(artifact_path)
    if p.is_absolute():
        return p
    project_root = _resolve_dlc_root(dlc_root).parent
    return project_root / p


def _hours_since(iso_ts: str) -> float | None:
    """Return hours elapsed since ``iso_ts``, or None on parse failure."""
    try:
        # Accept both 'Z' and offset-aware strings.
        ts = iso_ts.rstrip("Z")
        # Python's fromisoformat in 3.11+ handles 'Z' directly but older datasets
        # may end in 'Z'; we strip and treat as UTC explicitly.
        dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600.0


def check_cache(
    *,
    slug: str,
    verb: str,
    source_hash: str,
    max_age_hours: float = 0.0,
    dlc_root: Path | None = None,
) -> CacheHit | None:
    """Look up a cache entry; return a :class:`CacheHit` if valid, else None.

    Args:
        slug: Slug derived via :func:`dlc_bridge.util.slug.from_path`.
        verb: One of :data:`dlc_bridge.verbs.SUPPORTED_VERBS`.
        source_hash: SHA-256 hex from :func:`dlc_bridge.util.hash.get_normalized_input_hash`.
        max_age_hours: TTL in hours. ``0`` (default) disables expiry per FR-10.
        dlc_root: Override the default ``.dlc`` location (tests).

    Returns:
        A :class:`CacheHit` if **all** of these hold:

        1. The cache file is well-formed v2.
        2. ``cache[verb].hash == source_hash``.
        3. ``cache[verb].artifact_path`` resolves to an existing file on disk.
        4. ``max_age_hours == 0`` or the entry is younger than the TTL.

        ``None`` otherwise (cache miss).
    """
    data = load_cache(slug, dlc_root=dlc_root)
    if not data:
        return None
    entry = _entry_from_raw(data.get(verb))
    if entry is None:
        return None
    if entry.hash != source_hash:
        return None
    artifact = _resolve_artifact(entry.artifact_path, dlc_root)
    if not artifact.is_file():
        return None
    age = _hours_since(entry.last_success_at) or 0.0
    if max_age_hours > 0 and age > max_age_hours:
        return None
    return CacheHit(
        verb=verb,
        artifact_path=artifact,
        age_hours=age,
    )


def write_cache(
    *,
    slug: str,
    verb: str,
    source_hash: str,
    artifact_path: Path | str,
    dlc_root: Path | None = None,
) -> bool:
    """Upsert the (verb) → entry mapping for ``slug``.

    Always writes ``cache_version: 2`` at the top level. Preserves any other
    existing verb entries verbatim. Returns ``True`` if the file was actually
    mutated, ``False`` on byte-equal no-op (atomic write idempotence guard).
    """
    path = cache_path_for(slug, dlc_root=dlc_root)

    existing = load_cache(slug, dlc_root=dlc_root)
    # Preserve any sibling verb entries; drop the version field, we'll re-emit it.
    sibling_entries = {
        k: v for k, v in existing.items() if k != "cache_version"
    }

    entry = CacheEntry(
        hash=source_hash,
        artifact_path=str(artifact_path).replace("\\", "/"),
        last_success_at=_iso_now(),
    )
    payload: dict[str, Any] = {"cache_version": CACHE_VERSION}
    payload.update(sibling_entries)
    payload[verb] = entry.to_dict()

    return write_json_utf8_lf(path, payload)


def invalidate_cache(
    *,
    slug: str,
    verb: str | None = None,
    dlc_root: Path | None = None,
) -> int:
    """Delete one or all verb entries for ``slug``. Returns count removed.

    When ``verb`` is None, removes every per-verb entry (leaves the file
    with just ``cache_version: 2``). When ``verb`` is a specific name, only
    that entry is dropped. The file itself is never deleted — that keeps
    re-write semantics simple and avoids races with concurrent readers.
    """
    existing = load_cache(slug, dlc_root=dlc_root)
    if not existing:
        return 0
    sibling_entries = {
        k: v for k, v in existing.items() if k != "cache_version"
    }
    if verb is None:
        removed = len(sibling_entries)
        sibling_entries = {}
    else:
        if verb not in sibling_entries:
            return 0
        del sibling_entries[verb]
        removed = 1

    path = cache_path_for(slug, dlc_root=dlc_root)
    payload: dict[str, Any] = {"cache_version": CACHE_VERSION}
    payload.update(sibling_entries)
    write_json_utf8_lf(path, payload)
    return removed
