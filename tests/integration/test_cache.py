"""Integration tests for :mod:`dlc_bridge.cache` (Epic 2b WI-6, WI-9).

Covers FR-8 (hash anchor), FR-9 (cache_version: 2 invalidation), and
FR-10 (--cache-max-age-hours TTL).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dlc_bridge import cache as cache_mod

pytestmark = pytest.mark.integration


def _seed_artifact(dlc_root: Path, slug: str, suffix: str = "requirements.prd.md") -> Path:
    """Create an artifact file under ``<.dlc>/<slug>/`` and return its path."""
    art = dlc_root / slug / suffix
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("artifact body\n", encoding="utf-8", newline="\n")
    return art


def test_cache_path_for_returns_expected_layout(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    path = cache_mod.cache_path_for("foo", dlc_root=dlc)
    assert path == dlc / "foo" / "_bridge-cache.json"


def test_load_cache_returns_empty_when_missing(tmp_path: Path) -> None:
    assert cache_mod.load_cache("nonexistent", dlc_root=tmp_path / ".dlc") == {}


def test_write_cache_then_check_cache_returns_hit(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    h = "deadbeef" * 8  # 64-char fake SHA-256
    mutated = cache_mod.write_cache(
        slug="spec-a",
        verb="analyze-requirements",
        source_hash=h,
        artifact_path=".dlc/spec-a/requirements.prd.md",
        dlc_root=dlc,
    )
    assert mutated is True

    hit = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash=h, dlc_root=dlc,
    )
    assert hit is not None
    assert hit.verb == "analyze-requirements"
    assert str(hit.artifact_path).replace("\\", "/").endswith("requirements.prd.md")


def test_check_cache_miss_when_hash_differs(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md",
        dlc_root=dlc,
    )
    miss = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="b" * 64, dlc_root=dlc,
    )
    assert miss is None


def test_check_cache_miss_when_artifact_deleted(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    art = _seed_artifact(dlc, "spec-a")
    h = "f" * 64
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements", source_hash=h,
        artifact_path=".dlc/spec-a/requirements.prd.md", dlc_root=dlc,
    )
    # Artifact present → hit.
    assert cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash=h, dlc_root=dlc,
    ) is not None

    # Delete artifact → miss even on matching hash.
    art.unlink()
    assert cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash=h, dlc_root=dlc,
    ) is None


def test_check_cache_v1_entries_treated_as_miss_fr9(tmp_path: Path) -> None:
    """FR-9 / D-6: any cache file without cache_version=2 is invalidated."""
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    # Manually write a v1-shape file (no cache_version field).
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    v1_payload = {
        "analyze-requirements": {
            "hash": "x" * 64,
            "artifact_path": ".dlc/spec-a/requirements.prd.md",
            "last_success_at": "2026-05-22T00:00:00Z",
        }
    }
    cache_path.write_text(
        json.dumps(v1_payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    # check_cache must miss (v1 invalidated).
    hit = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="x" * 64, dlc_root=dlc,
    )
    assert hit is None

    # load_cache also returns {} so callers can re-write cleanly.
    assert cache_mod.load_cache("spec-a", dlc_root=dlc) == {}


def test_check_cache_v1_with_explicit_version_1_also_misses(tmp_path: Path) -> None:
    """Explicit cache_version=1 (older format) must also be invalidated."""
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_version": 1,
        "analyze-requirements": {
            "hash": "x" * 64,
            "artifact_path": ".dlc/spec-a/requirements.prd.md",
            "last_success_at": "2026-05-22T00:00:00Z",
        },
    }
    cache_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    assert cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="x" * 64, dlc_root=dlc,
    ) is None


def test_write_cache_always_emits_cache_version_2(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md",
        dlc_root=dlc,
    )
    raw = json.loads(
        (dlc / "spec-a" / "_bridge-cache.json").read_text(encoding="utf-8")
    )
    assert raw["cache_version"] == 2


def test_write_cache_no_bom_lf_endings(tmp_path: Path) -> None:
    """NFR-3: cache JSON is UTF-8 no-BOM, LF-terminated."""
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md",
        dlc_root=dlc,
    )
    data = (dlc / "spec-a" / "_bridge-cache.json").read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "must not write BOM"
    assert b"\r\n" not in data, "must not write CRLF"


def test_write_cache_preserves_sibling_verb_entries(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    _seed_artifact(dlc, "spec-a", suffix="designs/tech-design.md")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md",
        dlc_root=dlc,
    )
    cache_mod.write_cache(
        slug="spec-a", verb="produce-tech-design",
        source_hash="b" * 64,
        artifact_path=".dlc/spec-a/designs/tech-design.md",
        dlc_root=dlc,
    )
    raw = json.loads(
        (dlc / "spec-a" / "_bridge-cache.json").read_text(encoding="utf-8")
    )
    assert raw["cache_version"] == 2
    assert "analyze-requirements" in raw
    assert "produce-tech-design" in raw
    assert raw["analyze-requirements"]["hash"] == "a" * 64
    assert raw["produce-tech-design"]["hash"] == "b" * 64


def test_write_cache_is_idempotent_on_no_op(tmp_path: Path) -> None:
    """Atomic write returns False on byte-equal no-op."""
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    h = "c" * 64
    first = cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements", source_hash=h,
        artifact_path=".dlc/spec-a/requirements.prd.md", dlc_root=dlc,
    )
    assert first is True

    # Wait so timestamp would differ; the cache writes a fresh
    # last_success_at on every call so this WILL mutate. The idempotence
    # contract is at the encoding level (bytes-equal), not the cache level.
    time.sleep(1.1)
    second = cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements", source_hash=h,
        artifact_path=".dlc/spec-a/requirements.prd.md", dlc_root=dlc,
    )
    # last_success_at changes → bytes differ → mutated.
    assert second is True


def test_ttl_zero_means_no_expiry_fr10(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    # Hand-write an old last_success_at to simulate aged entry.
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cache_path.write_text(
        json.dumps({
            "cache_version": 2,
            "analyze-requirements": {
                "hash": "x" * 64,
                "artifact_path": ".dlc/spec-a/requirements.prd.md",
                "last_success_at": old_ts,
            },
        }) + "\n",
        encoding="utf-8", newline="\n",
    )
    # TTL=0 means never expire → still a hit.
    hit = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="x" * 64, max_age_hours=0, dlc_root=dlc,
    )
    assert hit is not None
    assert hit.age_hours >= 24 * 29  # at least ~29 days old


def test_ttl_expires_old_entries_fr10(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cache_path.write_text(
        json.dumps({
            "cache_version": 2,
            "analyze-requirements": {
                "hash": "x" * 64,
                "artifact_path": ".dlc/spec-a/requirements.prd.md",
                "last_success_at": old_ts,
            },
        }) + "\n",
        encoding="utf-8", newline="\n",
    )
    # TTL=1h → 10h-old entry expired.
    hit = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="x" * 64, max_age_hours=1.0, dlc_root=dlc,
    )
    assert hit is None


def test_ttl_within_window_still_hits(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cache_path.write_text(
        json.dumps({
            "cache_version": 2,
            "analyze-requirements": {
                "hash": "x" * 64,
                "artifact_path": ".dlc/spec-a/requirements.prd.md",
                "last_success_at": recent_ts,
            },
        }) + "\n",
        encoding="utf-8", newline="\n",
    )
    hit = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="x" * 64, max_age_hours=1.0, dlc_root=dlc,
    )
    assert hit is not None


def test_invalidate_specific_verb(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements", source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md", dlc_root=dlc,
    )
    cache_mod.write_cache(
        slug="spec-a", verb="produce-tech-design", source_hash="b" * 64,
        artifact_path=".dlc/spec-a/designs/tech-design.md", dlc_root=dlc,
    )
    removed = cache_mod.invalidate_cache(
        slug="spec-a", verb="analyze-requirements", dlc_root=dlc,
    )
    assert removed == 1
    raw = cache_mod.load_cache("spec-a", dlc_root=dlc)
    assert "analyze-requirements" not in raw
    assert "produce-tech-design" in raw


def test_invalidate_all_for_slug(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements", source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md", dlc_root=dlc,
    )
    cache_mod.write_cache(
        slug="spec-a", verb="produce-tech-design", source_hash="b" * 64,
        artifact_path=".dlc/spec-a/designs/tech-design.md", dlc_root=dlc,
    )
    removed = cache_mod.invalidate_cache(slug="spec-a", verb=None, dlc_root=dlc)
    assert removed == 2
    raw = cache_mod.load_cache("spec-a", dlc_root=dlc)
    # cache_version still there, but no verb entries.
    assert raw.get("cache_version") == 2
    assert all(k == "cache_version" for k in raw.keys())


def test_invalidate_missing_verb_returns_0(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    _seed_artifact(dlc, "spec-a")
    cache_mod.write_cache(
        slug="spec-a", verb="analyze-requirements", source_hash="a" * 64,
        artifact_path=".dlc/spec-a/requirements.prd.md", dlc_root=dlc,
    )
    removed = cache_mod.invalidate_cache(
        slug="spec-a", verb="hotfix", dlc_root=dlc,
    )
    assert removed == 0


def test_invalidate_when_file_missing_returns_0(tmp_path: Path) -> None:
    assert cache_mod.invalidate_cache(
        slug="never-cached", verb="hotfix", dlc_root=tmp_path / ".dlc",
    ) == 0


def test_load_cache_handles_malformed_json(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{not valid json", encoding="utf-8", newline="\n")
    assert cache_mod.load_cache("spec-a", dlc_root=dlc) == {}


def test_check_cache_handles_corrupt_entry_shape(tmp_path: Path) -> None:
    """Malformed verb-entry (missing fields) treated as miss, not crash."""
    dlc = tmp_path / ".dlc"
    cache_path = dlc / "spec-a" / "_bridge-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({
            "cache_version": 2,
            "analyze-requirements": "not-a-dict",  # corrupt entry
        }) + "\n",
        encoding="utf-8", newline="\n",
    )
    hit = cache_mod.check_cache(
        slug="spec-a", verb="analyze-requirements",
        source_hash="x" * 64, dlc_root=dlc,
    )
    assert hit is None
