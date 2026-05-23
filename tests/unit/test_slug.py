"""Tests for :mod:`dlc_bridge.util.slug`."""

from __future__ import annotations

import pytest

from dlc_bridge.exceptions import ValidationError
from dlc_bridge.util.slug import from_path


def test_kiro_specs_requirements_md() -> None:
    assert from_path(".kiro/specs/add-oauth/requirements.md") == "add-oauth"


def test_kiro_specs_design_md() -> None:
    assert from_path(".kiro/specs/dlc-supercharge/design.md") == "dlc-supercharge"


def test_dlc_path_fallback() -> None:
    assert from_path(".dlc/foo-bar/state.md") == "foo-bar"


def test_dlc_path_with_subdir() -> None:
    assert from_path(".dlc/foo/plans/epic-001.plan.md") == "foo"


def test_pr_fallback() -> None:
    assert from_path(None, pr=42) == "pr-42"


def test_pr_overrides_zero() -> None:
    # pr=0 should NOT trigger pr-fallback (PR numbers start at 1).
    with pytest.raises(ValidationError):
        from_path(None, pr=0)


def test_nested_specs_rejected() -> None:
    with pytest.raises(ValidationError, match="nested specs"):
        from_path(".kiro/specs/parent/specs/child/requirements.md")


def test_no_match_raises() -> None:
    with pytest.raises(ValidationError):
        from_path("/some/random/path/file.txt")


def test_no_args_raises() -> None:
    with pytest.raises(ValidationError):
        from_path(None)


def test_backslash_normalization() -> None:
    # Windows-style paths should be accepted.
    assert from_path(".kiro\\specs\\my-slug\\requirements.md") == "my-slug"


def test_kiro_priority_over_pr() -> None:
    # When both source and pr are provided, source wins.
    assert from_path(".kiro/specs/my-spec/x.md", pr=99) == "my-spec"
