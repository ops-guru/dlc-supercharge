"""Tests for :mod:`dlc_bridge.util.self_writes` (Issue #8 self-fire registry)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dlc_bridge.util.self_writes import (
    MAX_ENTRIES_PER_FILE,
    REGISTRY_FILENAME,
    is_self_fire,
    record,
    sha256_of_file,
)


# ---------------------------------------------------------------------------
# sha256_of_file
# ---------------------------------------------------------------------------


def test_sha256_of_file_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello world\n")
    assert sha256_of_file(p) == sha256_of_file(p)


def test_sha256_of_file_known_value(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"abc")
    # sha256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
    assert sha256_of_file(p) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_of_file_streams_large(tmp_path: Path) -> None:
    """Hashing a >64KB file (forces multiple read chunks) still matches."""
    p = tmp_path / "big.bin"
    payload = b"X" * (130 * 1024)
    p.write_bytes(payload)
    import hashlib

    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_of_file(p) == expected


# ---------------------------------------------------------------------------
# record + is_self_fire happy path
# ---------------------------------------------------------------------------


class TestRecordAndDetect:
    def test_record_then_self_fire_detected(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        spec.write_text("# hello\n", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        record(file_path=spec, slug_root=slug_root)
        assert is_self_fire(file_path=spec, slug_root=slug_root) is True

    def test_unmodified_file_with_no_registry_is_not_self_fire(
        self, tmp_path: Path
    ) -> None:
        spec = tmp_path / "spec.md"
        spec.write_text("# hello\n", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        # No record call.
        assert is_self_fire(file_path=spec, slug_root=slug_root) is False

    def test_external_edit_not_self_fire(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        spec.write_text("# v1\n", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        record(file_path=spec, slug_root=slug_root)
        # External edit changes the file.
        spec.write_text("# v1\n+ user added line\n", encoding="utf-8")
        assert is_self_fire(file_path=spec, slug_root=slug_root) is False

    def test_registry_file_written_at_expected_path(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        spec.write_text("x", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        record(file_path=spec, slug_root=slug_root)
        assert (slug_root / REGISTRY_FILENAME).exists()

    def test_record_returns_digest(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        spec.write_bytes(b"abc")
        slug_root = tmp_path / ".dlc" / "myslug"
        digest = record(file_path=spec, slug_root=slug_root)
        assert digest == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_missing_file_record_returns_empty(self, tmp_path: Path) -> None:
        slug_root = tmp_path / ".dlc" / "myslug"
        digest = record(file_path=tmp_path / "nope.md", slug_root=slug_root)
        assert digest == ""

    def test_missing_file_is_not_self_fire(self, tmp_path: Path) -> None:
        slug_root = tmp_path / ".dlc" / "myslug"
        slug_root.mkdir(parents=True, exist_ok=True)
        # Create the registry but query a non-existent file.
        (slug_root / REGISTRY_FILENAME).write_text("{}", encoding="utf-8")
        assert (
            is_self_fire(file_path=tmp_path / "ghost.md", slug_root=slug_root)
            is False
        )

    def test_corrupt_registry_returns_false(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        spec.write_text("x", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        slug_root.mkdir(parents=True, exist_ok=True)
        (slug_root / REGISTRY_FILENAME).write_text(
            "{not valid json", encoding="utf-8"
        )
        # Fail-open: treat as not-a-self-fire so the legit fire proceeds.
        assert is_self_fire(file_path=spec, slug_root=slug_root) is False


class TestRetentionAndGC:
    def test_dedupes_adjacent_identical_records(self, tmp_path: Path) -> None:
        """Recording the same hash twice keeps one entry (timestamp bumped)."""
        spec = tmp_path / "spec.md"
        spec.write_text("same\n", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        record(file_path=spec, slug_root=slug_root)
        record(file_path=spec, slug_root=slug_root)
        data = json.loads(
            (slug_root / REGISTRY_FILENAME).read_text(encoding="utf-8")
        )
        abs_key = str(spec.resolve())
        assert len(data[abs_key]) == 1

    def test_multiple_distinct_writes_grow_list(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        slug_root = tmp_path / ".dlc" / "myslug"
        for i in range(3):
            spec.write_text(f"version {i}\n", encoding="utf-8")
            record(file_path=spec, slug_root=slug_root)
        data = json.loads(
            (slug_root / REGISTRY_FILENAME).read_text(encoding="utf-8")
        )
        abs_key = str(spec.resolve())
        assert len(data[abs_key]) == 3

    def test_caps_at_MAX_ENTRIES_PER_FILE(self, tmp_path: Path) -> None:
        spec = tmp_path / "spec.md"
        slug_root = tmp_path / ".dlc" / "myslug"
        for i in range(MAX_ENTRIES_PER_FILE + 5):
            spec.write_text(f"v{i}\n", encoding="utf-8")
            record(file_path=spec, slug_root=slug_root)
        data = json.loads(
            (slug_root / REGISTRY_FILENAME).read_text(encoding="utf-8")
        )
        abs_key = str(spec.resolve())
        assert len(data[abs_key]) == MAX_ENTRIES_PER_FILE
        # Latest entries kept (oldest evicted).
        timestamps = [e["at"] for e in data[abs_key]]
        assert timestamps == sorted(timestamps)

    def test_ttl_expired_entries_treated_as_not_self_fire(
        self, tmp_path: Path
    ) -> None:
        spec = tmp_path / "spec.md"
        spec.write_text("v1\n", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        # Record with a very short TTL.
        record(file_path=spec, slug_root=slug_root, ttl_seconds=1)
        time.sleep(1.2)
        # After TTL, the entry no longer counts as a self-fire match.
        assert (
            is_self_fire(file_path=spec, slug_root=slug_root, ttl_seconds=1)
            is False
        )


class TestMultiFile:
    def test_independent_keys_per_file(self, tmp_path: Path) -> None:
        a = tmp_path / "a.md"
        a.write_text("A", encoding="utf-8")
        b = tmp_path / "b.md"
        b.write_text("B", encoding="utf-8")
        slug_root = tmp_path / ".dlc" / "myslug"
        record(file_path=a, slug_root=slug_root)
        # Only `a` is recorded; `b` must not be detected as self-fire.
        assert is_self_fire(file_path=a, slug_root=slug_root) is True
        assert is_self_fire(file_path=b, slug_root=slug_root) is False


class TestConcurrencyTolerance:
    def test_record_creates_slug_dir_if_missing(self, tmp_path: Path) -> None:
        """slug_root may not exist yet on first fire — record() must create it."""
        spec = tmp_path / "spec.md"
        spec.write_text("x", encoding="utf-8")
        slug_root = tmp_path / "deep" / "nested" / ".dlc" / "myslug"
        # Does not pre-create slug_root.
        record(file_path=spec, slug_root=slug_root)
        assert (slug_root / REGISTRY_FILENAME).exists()
