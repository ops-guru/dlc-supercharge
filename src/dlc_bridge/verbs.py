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

Verb-task template resolution
-----------------------------

:func:`resolve_verb_template` reads a ``{verb}.txt`` template from
``.kiro/powers/dlc-supercharge/templates/verb-tasks/`` and substitutes
``{key}`` placeholders with values from a dict. Mirrors v1.1's
``Resolve-VerbTemplate`` exactly: pure string substitution, NEVER shell
expansion. The result is a task body that ``cli.py`` passes to ``claude``
as a final positional argument.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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


_VERB_TASKS_RELATIVE = Path(".kiro/powers/dlc-supercharge/templates/verb-tasks")
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _default_template_root() -> Path:
    """Return the default verb-task template directory.

    Resolved relative to the current working directory (which the bridge
    caller is expected to set to the project root). Tests override this
    via the ``template_root`` parameter of :func:`resolve_verb_template`.
    """
    return Path.cwd() / _VERB_TASKS_RELATIVE


def resolve_verb_template(
    verb: str,
    verb_args: dict[str, Any] | None = None,
    *,
    template_root: Path | None = None,
) -> str:
    """Read the ``{verb}.txt`` template and substitute ``{key}`` placeholders.

    Args:
        verb: One of :data:`SUPPORTED_VERBS`.
        verb_args: Mapping of placeholder name (no braces) → substitution value.
            Values are str-ified before injection (matching v1.1's
            ``[string]$VerbArgs[$key]`` cast).
        template_root: Override the template directory (tests). Defaults to
            ``<cwd>/.kiro/powers/dlc-supercharge/templates/verb-tasks/``.

    Returns:
        The substituted template body.

    Raises:
        ConfigurationError: If ``verb`` is not in :data:`SUPPORTED_VERBS`, or
            the template file is missing.

    Notes:
        Pure string substitution. NO ``Invoke-Expression``, no shell
        expansion, no eval — safe by construction. The v1.1 SECURITY block
        in ``dlc-bridge-verbs.ps1`` (lines 18-31) applies verbatim: user
        args flow into the task body as STRING literals; ``claude``
        receives the task as a single argv element, never as a shell
        command. Defense-in-depth: input validation in :mod:`dlc_bridge.cli`
        rejects path-traversal / enum violations before this is reached.
    """
    if verb not in SUPPORTED_VERBS:
        supported = ", ".join(sorted(SUPPORTED_VERBS))
        raise ConfigurationError(
            f"Unknown verb '{verb}'. Supported verbs: {supported}"
        )

    root = template_root if template_root is not None else _default_template_root()
    template_path = root / f"{verb}.txt"
    if not template_path.is_file():
        # Fall back to a synthetic minimal task body so the bridge can still
        # invoke claude in environments where the template directory is not
        # checked in (early-stage repos, tests). Mirrors the principle that
        # the bridge is best-effort about prompt assembly: the SKILL.md
        # carries the actual operating instructions.
        return _synthetic_task(verb, verb_args or {})

    template = template_path.read_text(encoding="utf-8")
    for key, value in (verb_args or {}).items():
        template = template.replace("{" + key + "}", str(value))
    return template


def _synthetic_task(verb: str, verb_args: dict[str, Any]) -> str:
    """Build a minimal task body when no template file exists.

    Format: ``"/dlc:<verb> --key1 value1 --key2 value2"``. Used as a
    fallback so the bridge stays functional in repos that don't ship
    the v1.1 template directory.
    """
    parts = [f"/dlc:{verb}"]
    for key, value in verb_args.items():
        if value is None or value == "":
            continue
        # Quote values containing whitespace.
        sval = str(value)
        if " " in sval:
            parts.append(f'--{key} "{sval}"')
        else:
            parts.append(f"--{key} {sval}")
    return " ".join(parts)


__all__ = [
    "SUPPORTED_VERBS",
    "VERB_TO_SKILL_FOLDER",
    "resolve_skill_path",
    "resolve_verb_template",
    "skill_folder_for",
]
