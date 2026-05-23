"""Tests for :mod:`dlc_bridge.util.encoding`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.util.encoding import (
    atomic_write_bytes,
    atomic_write_utf8_lf,
    read_text_utf8,
    write_json_utf8_lf,
    write_text_utf8_lf,
)


_UTF8_BOM = b"\xef\xbb\xbf"


class TestReadTextUtf8:
    def test_reads_plain_utf8(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_bytes(b"hello\nworld\n")
        assert read_text_utf8(target) == "hello\nworld\n"

    def test_strips_bom(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_bytes(_UTF8_BOM + b"hello\n")
        assert read_text_utf8(target) == "hello\n"

    def test_preserves_crlf(self, tmp_path: Path) -> None:
        # read_text_utf8 must NOT normalize endings; that's hash.py's job.
        target = tmp_path / "f.txt"
        target.write_bytes(b"a\r\nb\r\n")
        assert read_text_utf8(target) == "a\r\nb\r\n"

    def test_handles_multibyte_utf8(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_bytes("café — résumé\n".encode("utf-8"))
        assert read_text_utf8(target) == "café — résumé\n"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_text_utf8(tmp_path / "missing.txt")


class TestWriteTextUtf8Lf:
    def test_writes_lf_endings(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        write_text_utf8_lf(target, "a\nb\n")
        assert target.read_bytes() == b"a\nb\n"

    def test_no_bom_written(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        write_text_utf8_lf(target, "hello\n")
        assert not target.read_bytes().startswith(_UTF8_BOM)

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c.txt"
        write_text_utf8_lf(target, "x")
        assert target.read_text(encoding="utf-8") == "x"


class TestAtomicWriteUtf8Lf:
    def test_writes_when_file_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        assert atomic_write_utf8_lf(target, "hello\n") is True
        assert target.read_bytes() == b"hello\n"

    def test_skips_when_bytes_identical(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_bytes(b"hello\n")
        original_mtime = target.stat().st_mtime
        # Spin briefly to ensure mtime would change if a write occurred.
        import time
        time.sleep(0.05)
        assert atomic_write_utf8_lf(target, "hello\n") is False
        assert target.stat().st_mtime == original_mtime

    def test_writes_when_bytes_differ(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_bytes(b"hello\n")
        assert atomic_write_utf8_lf(target, "goodbye\n") is True
        assert target.read_bytes() == b"goodbye\n"

    def test_normalizes_crlf_to_lf(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        atomic_write_utf8_lf(target, "a\r\nb\r\n")
        assert target.read_bytes() == b"a\nb\n"

    def test_never_writes_bom(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        atomic_write_utf8_lf(target, "café\n")
        assert not target.read_bytes().startswith(_UTF8_BOM)

    def test_atomic_rename_no_tmp_left(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        atomic_write_utf8_lf(target, "hello\n")
        assert not (tmp_path / "f.txt.tmp").exists()


class TestAtomicWriteBytes:
    def test_writes_arbitrary_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "f.bin"
        data = b"\x00\x01\x02\xff"
        assert atomic_write_bytes(target, data) is True
        assert target.read_bytes() == data

    def test_skips_when_identical(self, tmp_path: Path) -> None:
        target = tmp_path / "f.bin"
        target.write_bytes(b"abc")
        assert atomic_write_bytes(target, b"abc") is False


class TestWriteJsonUtf8Lf:
    def test_no_bom(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        write_json_utf8_lf(target, {"a": 1})
        assert not target.read_bytes().startswith(_UTF8_BOM)

    def test_no_crlf(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        write_json_utf8_lf(target, {"a": 1, "b": [1, 2]})
        assert b"\r\n" not in target.read_bytes()

    def test_trailing_lf(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        write_json_utf8_lf(target, {"a": 1})
        assert target.read_bytes().endswith(b"\n")

    def test_round_trips(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        obj = {"name": "café", "tags": ["x", "y"]}
        write_json_utf8_lf(target, obj)
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == obj

    def test_preserves_non_ascii(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        write_json_utf8_lf(target, {"em": "—"})
        # ensure_ascii=False → em-dash kept as UTF-8, not — escape
        assert "—".encode("utf-8") in target.read_bytes()

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        write_json_utf8_lf(target, {"a": 1})
        assert write_json_utf8_lf(target, {"a": 1}) is False


# --- WI-20: byte-equality guard, mtime preservation -------------------------


class TestByteEqualityGuard:
    """NFR-4 atomic write byte-equality guard tests (Epic 2b WI-20).

    Verify the idempotence guard in :func:`atomic_write_bytes` actually
    prevents file mutation when proposed content equals on-disk bytes,
    AND that mtime is preserved across the no-op (Kiro hook self-fire
    avoidance — if the file's mtime doesn't change, downstream watchers
    don't refire).
    """

    def test_second_write_returns_false_when_bytes_equal(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        atomic_write_bytes(target, b"identical content\n")
        result = atomic_write_bytes(target, b"identical content\n")
        assert result is False

    def test_second_write_returns_true_when_bytes_change(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        atomic_write_bytes(target, b"first\n")
        result = atomic_write_bytes(target, b"second\n")
        assert result is True
        assert target.read_bytes() == b"second\n"

    def test_no_op_write_preserves_mtime(self, tmp_path: Path) -> None:
        """Critical hook-loop safety guarantee: no mtime change on byte-equal write."""
        import time

        target = tmp_path / "f.txt"
        atomic_write_bytes(target, b"content\n")
        first_mtime = target.stat().st_mtime_ns

        # Wait a measurable interval, then re-write the same bytes.
        time.sleep(0.05)
        result = atomic_write_bytes(target, b"content\n")
        second_mtime = target.stat().st_mtime_ns

        assert result is False
        assert first_mtime == second_mtime, (
            "byte-equal write must NOT change mtime "
            "(otherwise Kiro fileEdited hooks re-fire in a loop)"
        )

    def test_mutation_write_updates_mtime(self, tmp_path: Path) -> None:
        """Sanity check: a real mutation DOES update mtime."""
        import time

        target = tmp_path / "f.txt"
        atomic_write_bytes(target, b"A\n")
        first_mtime = target.stat().st_mtime_ns
        time.sleep(0.05)
        atomic_write_bytes(target, b"B\n")
        second_mtime = target.stat().st_mtime_ns
        assert second_mtime > first_mtime

    def test_utf8_lf_byte_equality_guard(self, tmp_path: Path) -> None:
        """atomic_write_utf8_lf inherits the byte-equality guard."""
        target = tmp_path / "f.md"
        atomic_write_utf8_lf(target, "line one\nline two\n")
        result = atomic_write_utf8_lf(target, "line one\nline two\n")
        assert result is False

    def test_utf8_lf_normalizes_crlf_then_byte_eq_holds(self, tmp_path: Path) -> None:
        """CRLF input → normalized → idempotent on LF-equivalent re-write."""
        target = tmp_path / "f.md"
        # First write with LF.
        atomic_write_utf8_lf(target, "a\nb\n")
        # Second write with CRLF should normalize to LF and detect no change.
        result = atomic_write_utf8_lf(target, "a\r\nb\r\n")
        assert result is False

    def test_json_byte_equality_skips_mtime_change(self, tmp_path: Path) -> None:
        """JSON writer also preserves mtime on byte-equal no-op."""
        import time

        target = tmp_path / "f.json"
        payload = {"key": "value", "n": 42}
        write_json_utf8_lf(target, payload)
        first_mtime = target.stat().st_mtime_ns
        time.sleep(0.05)
        result = write_json_utf8_lf(target, payload)
        second_mtime = target.stat().st_mtime_ns
        assert result is False
        assert first_mtime == second_mtime
