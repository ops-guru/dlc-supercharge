"""FR-19 parity gate — FR-17 slug derivation.

Slug derivation rules from v1.1 ``slug-derive.ps1`` + the more permissive
``Resolve-CacheSlug`` fallback in ``dlc-bridge.ps1::283``:

1. ``.kiro/specs/<slug>/<file>.md`` → ``<slug>``
2. Nested specs (``.kiro/specs/<a>/specs/<b>/``) → error
3. ``.dlc/<slug>/...`` → ``<slug>`` (cache-slug fallback)
4. ``pr=N`` (no path) → ``pr-N``
5. No match → error

These cases are hand-written from the v1.1 source and validated against the
PowerShell implementation manually (see :mod:`tests.parity.capture_goldens`
for the capture script that re-runs them when v1.1 is available).
"""

from __future__ import annotations

import pytest

from dlc_bridge.exceptions import ValidationError
from dlc_bridge.util.slug import from_path


pytestmark = pytest.mark.parity


# Each tuple is (case_name, source_path, pr, expected_result_or_None).
# ``expected_result_or_None == None`` means: expect ValidationError.
SLUG_FIXTURES = [
    # 1. Spec-path direct match
    ("spec_requirements", ".kiro/specs/add-oauth/requirements.md", None, "add-oauth"),
    ("spec_design", ".kiro/specs/add-oauth/design.md", None, "add-oauth"),
    ("spec_tasks", ".kiro/specs/add-oauth/tasks.md", None, "add-oauth"),
    # 2. Backslash path (Windows source) — must normalize before matching
    ("spec_windows_path", r".kiro\specs\add-oauth\requirements.md", None, "add-oauth"),
    # 3. Slug containing hyphens
    ("spec_multi_hyphen_slug", ".kiro/specs/dlc-supercharge-python-migration/requirements.md", None, "dlc-supercharge-python-migration"),
    # 4. Nested specs — rejected
    ("nested_specs_rejected", ".kiro/specs/parent/specs/child/requirements.md", None, None),
    # 5. .dlc fallback
    ("dlc_fallback", ".dlc/my-slug/state.md", None, "my-slug"),
    ("dlc_fallback_nested", ".dlc/my-slug/plans/epic-001.plan.md", None, "my-slug"),
    # 6. PR-number fallback
    ("pr_fallback", None, 42, "pr-42"),
    ("pr_fallback_zero_rejected", None, 0, None),  # PS treats non-positive as no fallback
    ("pr_fallback_negative_rejected", None, -1, None),
    # 7. No fallback available
    ("no_match_error", "random/path/file.md", None, None),
    ("no_match_empty_error", None, None, None),
]


@pytest.mark.parametrize(
    "name,source,pr,expected",
    SLUG_FIXTURES,
    ids=[t[0] for t in SLUG_FIXTURES],
)
def test_slug_matches_v1_1_contract(
    name: str,
    source: str | None,
    pr: int | None,
    expected: str | None,
) -> None:
    """Python ``slug.from_path`` matches v1.1 ``slug-derive.ps1`` / ``Resolve-CacheSlug``."""
    if expected is None:
        with pytest.raises(ValidationError):
            from_path(source, pr=pr)
    else:
        assert from_path(source, pr=pr) == expected, (
            f"Slug divergence for fixture {name!r}: "
            f"source={source!r} pr={pr!r} expected={expected!r}"
        )
