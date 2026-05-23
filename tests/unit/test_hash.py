"""Tests for :mod:`dlc_bridge.util.hash` (FR-8 normalized SHA-256).

Per tech-design Appendix A.2, the Python implementation is **byte-identical**
to v1.1's ``Get-NormalizedInputHash`` on 8/8 canonical fixtures. These tests
validate the algorithm invariants:

* BOM stripping
* DLC ID comment stripping
* CRLF / CR / LF normalization
* Trailing-whitespace collapse
* Trailing-newline normalization
* Determinism (same input → same hash)
* Equivalence between superficially-different inputs that normalize the same way
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dlc_bridge.util.hash import get_normalized_input_hash


_UTF8_BOM = b"\xef\xbb\xbf"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """A per-test directory for hash-input fixtures."""
    d = tmp_path / "hash"
    d.mkdir()
    return d


class TestNormalizationInvariants:
    """Tests assert that two inputs differing only in normalized-away features
    produce the same hash. These cover the 8 canonical scenarios from the
    parity probe (lines 145-183 of dlc-bridge.ps1)."""

    def test_lf_only_file(self, fixture_dir: Path) -> None:
        # Canonical: plain LF endings, no BOM, single trailing LF.
        f = fixture_dir / "lf.txt"
        f.write_bytes(b"hello\nworld\n")
        # Expected hex precomputed via the same algorithm (which is the v1.1 contract).
        expected = _sha256_hex(b"hello\nworld\n")
        assert get_normalized_input_hash(f) == expected

    def test_bom_stripped_before_hash(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "with_bom.txt"
        f2 = fixture_dir / "no_bom.txt"
        f1.write_bytes(_UTF8_BOM + b"hello\n")
        f2.write_bytes(b"hello\n")
        assert get_normalized_input_hash(f1) == get_normalized_input_hash(f2)

    def test_crlf_normalized_to_lf(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "crlf.txt"
        f2 = fixture_dir / "lf.txt"
        f1.write_bytes(b"a\r\nb\r\n")
        f2.write_bytes(b"a\nb\n")
        assert get_normalized_input_hash(f1) == get_normalized_input_hash(f2)

    def test_bare_cr_normalized(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "cr.txt"
        f2 = fixture_dir / "lf.txt"
        f1.write_bytes(b"a\rb\r")
        f2.write_bytes(b"a\nb\n")
        assert get_normalized_input_hash(f1) == get_normalized_input_hash(f2)

    def test_mixed_endings_normalized(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "mixed.txt"
        f2 = fixture_dir / "lf.txt"
        f1.write_bytes(b"a\r\nb\rc\nd\n")
        f2.write_bytes(b"a\nb\nc\nd\n")
        assert get_normalized_input_hash(f1) == get_normalized_input_hash(f2)

    def test_dlc_id_comments_stripped(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "with_ids.md"
        f2 = fixture_dir / "no_ids.md"
        f1.write_bytes(
            b"## Story\n"
            b"The system shall log in <!-- FR-1 --> all users <!-- NFR-3 -->.\n"
        )
        f2.write_bytes(
            b"## Story\n"
            b"The system shall log in  all users .\n"
        )
        assert get_normalized_input_hash(f1) == get_normalized_input_hash(f2)

    def test_all_dlc_id_types_stripped(self, fixture_dir: Path) -> None:
        f = fixture_dir / "all_ids.md"
        # Cover all ID types listed in the regex.
        f.write_bytes(
            b"x <!-- FR-1 --> <!-- NFR-2 --> <!-- WI-3 --> "
            b"<!-- D-4 --> <!-- R-5 --> <!-- T-6 --> <!-- TC-7 --> y\n"
        )
        # All comments should strip; what remains is "x        y\n" — then
        # trailing-ws-collapse leaves the inter-token spaces alone (they're
        # not followed by \n).
        expected = _sha256_hex(b"x        y\n")
        assert get_normalized_input_hash(f) == expected

    def test_trailing_whitespace_before_lf_collapsed(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "trail_ws.txt"
        f2 = fixture_dir / "no_trail_ws.txt"
        f1.write_bytes(b"hello   \nworld\t\n")
        f2.write_bytes(b"hello\nworld\n")
        assert get_normalized_input_hash(f1) == get_normalized_input_hash(f2)

    def test_trailing_newlines_normalized_to_one(self, fixture_dir: Path) -> None:
        f1 = fixture_dir / "many_lf.txt"
        f2 = fixture_dir / "one_lf.txt"
        f3 = fixture_dir / "no_lf.txt"
        f1.write_bytes(b"hello\n\n\n\n")
        f2.write_bytes(b"hello\n")
        f3.write_bytes(b"hello")  # no trailing LF — should still normalize to one
        h1 = get_normalized_input_hash(f1)
        h2 = get_normalized_input_hash(f2)
        h3 = get_normalized_input_hash(f3)
        assert h1 == h2 == h3

    def test_empty_file(self, fixture_dir: Path) -> None:
        f = fixture_dir / "empty.txt"
        f.write_bytes(b"")
        # Normalizes to a single LF (rstrip + append \n).
        expected = _sha256_hex(b"\n")
        assert get_normalized_input_hash(f) == expected

    def test_em_dash_preserved(self, fixture_dir: Path) -> None:
        # Multi-byte UTF-8 must survive normalization.
        f = fixture_dir / "em.txt"
        f.write_bytes("hello — world\n".encode("utf-8"))
        expected = _sha256_hex("hello — world\n".encode("utf-8"))
        assert get_normalized_input_hash(f) == expected


class TestDeterminism:
    def test_same_input_same_hash(self, fixture_dir: Path) -> None:
        f = fixture_dir / "x.md"
        f.write_bytes(b"deterministic\n")
        h1 = get_normalized_input_hash(f)
        h2 = get_normalized_input_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in h1)

    def test_idempotent_on_already_normalized_input(self, fixture_dir: Path) -> None:
        # Re-writing the file with its normalized form should not change the hash.
        f = fixture_dir / "x.md"
        f.write_bytes(b"hello\nworld\n")
        h1 = get_normalized_input_hash(f)
        f.write_bytes(b"hello\nworld\n")
        h2 = get_normalized_input_hash(f)
        assert h1 == h2

    def test_missing_file_raises(self, fixture_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            get_normalized_input_hash(fixture_dir / "missing.txt")
