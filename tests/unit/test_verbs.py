"""Unit tests for ``dlc_bridge.verbs`` (FR-1, FR-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.exceptions import ConfigurationError
from dlc_bridge.verbs import (
    SUPPORTED_VERBS,
    VERB_TO_SKILL_FOLDER,
    resolve_skill_path,
    skill_folder_for,
)


pytestmark = pytest.mark.unit


def test_supported_verbs_count() -> None:
    """The bridge must expose exactly the 16 verbs documented in the PRD."""
    assert len(SUPPORTED_VERBS) == 16


def test_supported_verbs_membership() -> None:
    """All 16 PRD-listed verbs must be present (no typos, no drift)."""
    expected = {
        "analyze-requirements",
        "produce-tech-design",
        "plan-implementation",
        "finalize-sdlc",
        "discover",
        "review-pr",
        "stabilize-pr",
        "review-security",
        "review-ux",
        "review-a11y",
        "review-performance",
        "reverse-engineer-kb",
        "kb-gap-analysis",
        "map-codebase",
        "babysit-pr",
        "hotfix",
    }
    assert set(SUPPORTED_VERBS) == expected


def test_verb_to_skill_folder_discover_remap() -> None:
    """`discover` remaps to `product-discovery` (only documented remap)."""
    assert VERB_TO_SKILL_FOLDER["discover"] == "product-discovery"
    assert skill_folder_for("discover") == "product-discovery"


def test_skill_folder_for_identity_fallback() -> None:
    """Verbs without an explicit remap resolve to their own name."""
    assert skill_folder_for("analyze-requirements") == "analyze-requirements"
    assert skill_folder_for("review-security") == "review-security"


def test_resolve_skill_path_picks_highest_semver(tmp_path: Path) -> None:
    """When two version dirs exist, the higher one must win."""
    for ver in ("1.16", "1.17"):
        skill_dir = tmp_path / ver / "skills" / "analyze-requirements"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"# v{ver}\n", encoding="utf-8", newline="\n"
        )

    resolved = resolve_skill_path("analyze-requirements", plugin_cache_root=tmp_path)
    assert resolved.parent.parent.parent.name == "1.17"


def test_resolve_skill_path_discover_uses_remap(tmp_path: Path) -> None:
    """`discover` should resolve under the ``product-discovery`` folder."""
    skill_dir = tmp_path / "1.17" / "skills" / "product-discovery"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# pd\n", encoding="utf-8", newline="\n")

    resolved = resolve_skill_path("discover", plugin_cache_root=tmp_path)
    assert resolved.parent.name == "product-discovery"


def test_resolve_skill_path_skips_non_numeric_dirs(tmp_path: Path) -> None:
    """Directories like ``latest`` must be ignored, not crash the sort."""
    # Non-numeric dir present but contains nothing useful.
    (tmp_path / "latest").mkdir()

    skill_dir = tmp_path / "1.0" / "skills" / "analyze-requirements"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# v1.0\n", encoding="utf-8", newline="\n")

    resolved = resolve_skill_path("analyze-requirements", plugin_cache_root=tmp_path)
    assert "1.0" in resolved.parts


def test_resolve_skill_path_missing_raises(tmp_path: Path) -> None:
    """An empty plugin cache root must raise :class:`ConfigurationError`."""
    with pytest.raises(ConfigurationError, match="SKILL.md not found"):
        resolve_skill_path("analyze-requirements", plugin_cache_root=tmp_path)


def test_resolve_skill_path_missing_cache_root_raises(tmp_path: Path) -> None:
    """A non-existent cache root must raise :class:`ConfigurationError`."""
    bogus = tmp_path / "does-not-exist"
    with pytest.raises(ConfigurationError, match="plugin cache not found"):
        resolve_skill_path("analyze-requirements", plugin_cache_root=bogus)


def test_resolve_skill_path_unknown_verb_raises(tmp_path: Path) -> None:
    """Defensive check — callers must validate the verb first."""
    with pytest.raises(ConfigurationError, match="Unknown verb"):
        resolve_skill_path("not-a-verb", plugin_cache_root=tmp_path)


def test_plugin_cache_root_mock_fixture_works(
    plugin_cache_root_mock: Path,
) -> None:
    """The shared fixture should redirect resolve_skill_path at the fake cache."""
    resolved = resolve_skill_path("analyze-requirements")
    assert resolved.is_file()
    # Resolve to a comparable form; on Windows resolve() may return UNC paths,
    # so compare via ``samefile``.
    assert resolved.parent.parent.parent.parent.samefile(plugin_cache_root_mock)
