"""FR-17 slug derivation from source / target paths.

Port of v1.1 ``slug-derive.ps1`` plus the more permissive ``Resolve-CacheSlug``
fallback in ``dlc-bridge.ps1::283``.

Priority chain:

1. ``.kiro/specs/<slug>/<file>.md`` → ``<slug>``
   (rejects nested specs like ``.kiro/specs/parent/specs/child/...``)
2. ``.dlc/<slug>/...`` → ``<slug>`` (cache-slug fallback)
3. PR number → ``pr-<N>``
4. Otherwise: :class:`ValidationError`
"""

from __future__ import annotations

import re
from pathlib import Path

from dlc_bridge.exceptions import ValidationError

__all__ = ["from_path"]


# Match exactly one path segment between ``.kiro/specs/`` and the trailing
# ``.md`` file; ``[^/]+`` rejects nested slugs (the ``/specs/`` test below
# additionally rejects ``.kiro/specs/<parent>/specs/<child>/...``).
_SPEC_PATH_RE = re.compile(r"\.kiro/specs/([^/]+)/[^/]+\.md$")
_NESTED_SPEC_RE = re.compile(r"\.kiro/specs/[^/]+/specs/")
_DLC_PATH_RE = re.compile(r"\.dlc/([^/]+)/")


def from_path(source: str | Path | None, pr: int | None = None) -> str:
    """Derive a slug from a source path, falling back to a PR number.

    :param source: the canonical input path (e.g. ``.kiro/specs/foo/requirements.md``
        or ``.dlc/foo/state.md``); may be ``None`` if only ``pr`` is supplied.
    :param pr: PR number to fall back to when ``source`` doesn't match.
    :returns: the derived slug string.
    :raises ValidationError: if no rule matches.
    """
    if source is not None:
        normalized = str(source).replace("\\", "/")
        if _NESTED_SPEC_RE.search(normalized):
            raise ValidationError(
                f"nested specs not supported: {source}"
            )
        m = _SPEC_PATH_RE.search(normalized)
        if m:
            return m.group(1)
        m = _DLC_PATH_RE.search(normalized)
        if m:
            return m.group(1)

    if pr is not None and pr > 0:
        return f"pr-{pr}"

    raise ValidationError(
        f"could not derive slug from source={source!r} pr={pr!r}; "
        "expected .kiro/specs/<slug>/<file>.md, .dlc/<slug>/..., or pr=<N>"
    )
