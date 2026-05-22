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
