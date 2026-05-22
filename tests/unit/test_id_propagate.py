"""Tests for :mod:`dlc_bridge.util.id_propagate` (FR-11 Jaccard ID propagation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.util.id_propagate import (
    STOP_WORDS,
    _jaccard,
    _tokenize,
    propagate_ids,
)


def test_stop_words_match_v1_1() -> None:
    """Stop-words list must match v1.1 byte-for-byte (id-propagate.ps1:44)."""
    expected = {
        "the", "a", "an", "and", "or", "but", "for", "to", "of", "in",
        "is", "are", "be", "will", "shall", "that", "this", "with", "as",
        "by", "on", "it", "from", "at", "if", "when", "then", "must",
        "should", "can", "may", "any", "all",
    }
    assert STOP_WORDS == expected


def test_tokenize_drops_short_and_stop_words() -> None:
    assert _tokenize("The system shall log in users") == {"system", "log", "users"}


def test_tokenize_empty() -> None:
    assert _tokenize("") == set()
    assert _tokenize(None) == set()  # type: ignore[arg-type]


def test_tokenize_lowercases() -> None:
    assert _tokenize("SYSTEM USERS") == {"system", "users"}


def test_jaccard_both_empty_returns_zero() -> None:
    assert _jaccard(set(), set()) == 0.0


def test_jaccard_disjoint() -> None:
    assert _jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_identical() -> None:
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_partial_overlap() -> None:
    # |{a,b} ∩ {a,c}| / |{a,b,c}| = 1 / 3
    assert _jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Fixture builders for integration-style propagation tests.
# ---------------------------------------------------------------------------


def _write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.encode("utf-8"))
    return p


@pytest.fixture
def prd_and_spec(tmp_path: Path):
    """Build a fresh ``(prd_path, spec_path)`` pair under ``tmp_path``."""
    def factory(prd_content: str, spec_content: str):
        prd = _write(tmp_path / "requirements.prd.md", prd_content)
        spec = _write(tmp_path / "spec.md", spec_content)
        return prd, spec
    return factory


class TestPropagation:
    def test_single_high_jaccard_match(self, prd_and_spec) -> None:
        """Fixture 1: single FR with strong token overlap → matches."""
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication\n"
            "Users must be able to authenticate via OAuth.\n",
            "## Requirements\n"
            "WHEN a user signs in THE system SHALL authenticate via OAuth.\n",
        )
        result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        ids = [p["id"] for p in result["propagated"]]
        assert "FR-1" in ids
        # ID comment injected inline on the EARS line.
        assert "<!-- FR-1 -->" in spec.read_text(encoding="utf-8")

    def test_below_threshold_unmapped(self, prd_and_spec) -> None:
        """Fixture 2: token overlap too low → goes to ``unmapped``."""
        prd, spec = prd_and_spec(
            "#### FR-1 - Photosynthesis pipeline\n"
            "Chlorophyll metabolism subsystem.\n",
            "WHEN a user signs in THE system SHALL authenticate.\n",
        )
        result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.30)
        assert "FR-1" in result["unmapped"]
        assert "<!-- FR-1 -->" not in spec.read_text(encoding="utf-8")

    def test_ears_pattern_required(self, prd_and_spec) -> None:
        """Fixture 3: a line WITHOUT EARS markers is never matched."""
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication via OAuth\n",
            "## Requirements\n"
            "Some random sentence about user authentication OAuth.\n",
        )
        result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        assert "FR-1" in result["unmapped"]

    def test_multi_id_single_paragraph(self, prd_and_spec) -> None:
        """Fixture 4: two FRs match the same EARS line → both comments inserted."""
        prd, spec = prd_and_spec(
            "#### FR-1 - Authentication via OAuth\n"
            "OAuth provider integration.\n"
            "#### FR-2 - Single sign-on\n"
            "OAuth-based SSO experience.\n",
            "WHEN a user signs in THE system SHALL authenticate OAuth SSO.\n",
        )
        result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        ids = [p["id"] for p in result["propagated"]]
        assert "FR-1" in ids
        assert "FR-2" in ids
        content = spec.read_text(encoding="utf-8")
        assert "<!-- FR-1 -->" in content
        assert "<!-- FR-2 -->" in content

    def test_idempotent_rerun(self, prd_and_spec) -> None:
        """Fixture 5: re-running produces byte-identical spec output."""
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication via OAuth\n",
            "WHEN a user signs in THE system SHALL authenticate via OAuth.\n",
        )
        propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        first = spec.read_bytes()
        propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        second = spec.read_bytes()
        assert first == second

    def test_stop_word_heavy_source(self, prd_and_spec) -> None:
        """Fixture 6: heavy stop-word noise filters correctly."""
        prd, spec = prd_and_spec(
            "#### FR-1 - Authentication via OAuth\n"
            "OAuth login authentication.\n",
            "WHEN a user is in the system and shall be at the end of any of "
            "all the time THE system SHALL authenticate via OAuth.\n",
        )
        result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        # After filtering stop-words, real tokens (authenticate, oauth)
        # should give enough overlap to match.
        assert "FR-1" in [p["id"] for p in result["propagated"]]

    def test_no_rewrite_when_no_changes(self, prd_and_spec) -> None:
        """Re-running with already-injected comments must not rewrite the file."""
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication\n",
            "WHEN a user signs in THE system SHALL authenticate. <!-- FR-1 -->\n",
        )
        before_mtime = spec.stat().st_mtime
        import time
        time.sleep(0.05)
        propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        after_mtime = spec.stat().st_mtime
        # No new IDs to inject AND no content change → atomic_write skips write.
        assert before_mtime == after_mtime

    def test_dry_run_no_write(self, prd_and_spec) -> None:
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication via OAuth\n",
            "WHEN a user signs in THE system SHALL authenticate via OAuth.\n",
        )
        before = spec.read_bytes()
        result = propagate_ids(
            dlc_prd=prd, kiro_req=spec, threshold=0.10, dry_run=True
        )
        assert spec.read_bytes() == before
        assert "FR-1" in [p["id"] for p in result["propagated"]]

    def test_output_schema(self, prd_and_spec) -> None:
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication via OAuth\n",
            "WHEN a user signs in THE system SHALL authenticate via OAuth.\n",
        )
        result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        assert set(result.keys()) >= {"propagated", "unmapped", "threshold", "sourceFile", "dlcFile"}
        assert result["threshold"] == 0.10
        # propagated entries are dicts with id + line keys
        for entry in result["propagated"]:
            assert "id" in entry
            assert "line" in entry

    def test_id_types_filter(self, prd_and_spec) -> None:
        """``id_types=['NFR']`` ignores FR-N headings."""
        prd, spec = prd_and_spec(
            "#### FR-1 - Auth via OAuth\n"
            "#### NFR-1 - Performance via OAuth\n",
            "WHEN a user signs in THE system SHALL authenticate via OAuth.\n",
        )
        result = propagate_ids(
            dlc_prd=prd, kiro_req=spec, threshold=0.10, id_types=["NFR"]
        )
        ids = [p["id"] for p in result["propagated"]]
        assert "NFR-1" in ids
        assert "FR-1" not in ids

    def test_default_threshold_is_0_30(self, prd_and_spec) -> None:
        """Default threshold mirrors v1.1 (0.30, NOT 0.40)."""
        from inspect import signature
        sig = signature(propagate_ids)
        assert sig.parameters["threshold"].default == 0.30

    def test_existing_id_not_duplicated(self, prd_and_spec) -> None:
        prd, spec = prd_and_spec(
            "#### FR-1 - User authentication via OAuth\n",
            "WHEN a user signs in THE system SHALL authenticate via OAuth. <!-- FR-1 -->\n",
        )
        propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
        content = spec.read_text(encoding="utf-8")
        # Only one instance of the comment on the line.
        assert content.count("<!-- FR-1 -->") == 1


def test_full_propagation_json_serializable(prd_and_spec) -> None:
    prd, spec = prd_and_spec(
        "#### FR-1 - User authentication via OAuth\n",
        "WHEN a user signs in THE system SHALL authenticate via OAuth.\n",
    )
    result = propagate_ids(dlc_prd=prd, kiro_req=spec, threshold=0.10)
    # Must round-trip cleanly through json.dumps for the stdout emit path.
    serialized = json.dumps(result, separators=(",", ":"))
    parsed = json.loads(serialized)
    assert parsed == result
