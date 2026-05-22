"""Verb registry and SKILL.md path resolution (FR-1, FR-2).

The 16 supported verbs and their skill-folder mappings mirror the v1.1
PowerShell ``dlc-bridge-verbs.ps1`` registry. Only ``discover`` has a remap
(to ``product-discovery``); every other verb maps 1:1 to its skill folder.

Skill resolution walks the DLC plugin cache:

    ~/.claude/plugins/cache/dlc-automation/dlc/<version>/skills/<folder>/SKILL.md

When multiple ``<version>`` directories exist we pick the highest by
numeric-tuple sort (e.g. ``1.17`` beats ``1.16``). Non-numeric directory
names are skipped. ``packaging.version`` is intentionally not imported —
stdlib only for this Epic (Tech design Section 10.2 WI-2).
"""

from __future__ import annotations

from pathlib import Path

from dlc_bridge.exceptions import ConfigurationError

# Mirrors v1.1 .kiro/scripts/dlc-bridge-verbs.ps1 $Script:DlcSupportedVerbs.
# Order is not load-bearing; the set is what matters for membership checks.
SUPPORTED_VERBS: frozenset[str] = frozenset(
    {
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
)

# Only the verbs whose skill folder differs from the verb name need an entry.
# All other verbs resolve to ``skills/<verb>/SKILL.md`` via the fallback in
# :func:`resolve_skill_path`.
VERB_TO_SKILL_FOLDER: dict[str, str] = {
    "discover": "product-discovery",
}


def _default_plugin_cache_root() -> Path:
    """Return the default DLC plugin cache root.

    Lives at ``~/.claude/plugins/cache/dlc-automation/dlc/``. The directory
    contains one subdirectory per installed plugin version.
    """
    return Path.home() / ".claude" / "plugins" / "cache" / "dlc-automation" / "dlc"


def _semver_key(name: str) -> tuple[int, ...] | None:
    """Return a numeric-tuple sort key for ``name``, or ``None`` if non-numeric.

    Used by :func:`resolve_skill_path` to pick the highest-version directory.
    ``"1.17"`` → ``(1, 17)``; ``"1.16.2"`` → ``(1, 16, 2)``. A name like
    ``"latest"`` returns ``None`` and is filtered out.
    """
    parts = name.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def skill_folder_for(verb: str) -> str:
    """Return the plugin-cache folder name for ``verb``.

    Falls back to ``verb`` itself when no explicit remap exists.
    """
    return VERB_TO_SKILL_FOLDER.get(verb, verb)


def resolve_skill_path(verb: str, plugin_cache_root: Path | None = None) -> Path:
    """Resolve the SKILL.md path for ``verb`` in the highest-semver plugin dir.

    Args:
        verb: One of :data:`SUPPORTED_VERBS`.
        plugin_cache_root: Override the default ``~/.claude/plugins/cache/dlc-automation/dlc``
            location (used by tests). Defaults to :func:`_default_plugin_cache_root`.

    Returns:
        Absolute :class:`~pathlib.Path` to the SKILL.md.

    Raises:
        ConfigurationError: If the plugin cache root does not exist, or no
            version directory contains the required ``skills/<folder>/SKILL.md``.
    """
    if verb not in SUPPORTED_VERBS:
        # Defensive — callers normally validate the verb first. This guards
        # against tests or callers that pass a verb directly.
        raise ConfigurationError(f"Unknown verb '{verb}'")

    root = plugin_cache_root if plugin_cache_root is not None else _default_plugin_cache_root()
    if not root.is_dir():
        raise ConfigurationError(
            f"DLC plugin cache not found at: {root}. Install the /dlc: plugin first."
        )

    folder = skill_folder_for(verb)
    version_dirs: list[tuple[tuple[int, ...], Path]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        key = _semver_key(entry.name)
        if key is None:
            continue
        version_dirs.append((key, entry))

    # Highest semver first.
    version_dirs.sort(key=lambda kv: kv[0], reverse=True)

    for _key, version_dir in version_dirs:
        candidate = version_dir / "skills" / folder / "SKILL.md"
        if candidate.is_file():
            return candidate.resolve()

    raise ConfigurationError(
        f"SKILL.md not found for verb '{verb}' (skill folder: '{folder}') "
        f"in any installed version under {root}"
    )


__all__ = [
    "SUPPORTED_VERBS",
    "VERB_TO_SKILL_FOLDER",
    "resolve_skill_path",
    "skill_folder_for",
]
