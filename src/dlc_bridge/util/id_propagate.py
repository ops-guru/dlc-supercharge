"""FR-11 DLC ID propagation via Jaccard similarity.

Port of v1.1 ``id-propagate.ps1``. Walks a DLC-style PRD for
``#### <ID> - <Title>`` headings, then for each ID computes the best Jaccard
match against EARS-detected lines in the Kiro spec, and injects an inline
``<!-- FR-N -->`` (or ``<!-- NFR-N -->`` etc.) HTML comment on the matched line.

Idempotent at the byte level — re-running with no new matches will not rewrite
the spec file (avoids retriggering the on-saved hook in a self-fire loop).

Output to stdout (when ``write_result=True``): single-line compact JSON
``{propagated, unmapped, threshold}`` matching the v1.1 contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dlc_bridge.util.encoding import atomic_write_bytes, read_text_utf8

__all__ = ["propagate_ids", "STOP_WORDS"]


# Stop-words list verbatim from id-propagate.ps1:44.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "for", "to", "of", "in",
        "is", "are", "be", "will", "shall", "that", "this", "with", "as",
        "by", "on", "it", "from", "at", "if", "when", "then", "must",
        "should", "can", "may", "any", "all",
    }
)

# Token splitter: matches v1.1 ``-split '[^a-z0-9]+'`` (operates on already-lowercased input).
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# EARS regex verbatim from id-propagate.ps1:113. PowerShell ``-match`` is
# case-insensitive by default — Python needs explicit IGNORECASE.
_EARS_RE = re.compile(
    r"\b(THE\s+\S+\s+SHALL\b"
    r"|WHEN\s+.+?\s+THE\s+\S+\s+SHALL\b"
    r"|IF\s+.+?\s+THEN\s+THE\s+\S+\s+SHALL\b"
    r"|SHALL\b)",
    re.IGNORECASE,
)

# Inline HTML-comment ID extractor (v1.1 ``<!--\s*(\S+?)\s*-->``).
_INLINE_ID_RE = re.compile(r"<!--\s*(\S+?)\s*-->")


def _tokenize(text: str) -> set[str]:
    """Lowercase, split, drop short / stop-word tokens. Returns a set."""
    if not text:
        return set()
    return {
        w
        for w in _TOKEN_SPLIT_RE.split(text.lower())
        if len(w) >= 3 and w not in STOP_WORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity: ``|A ∩ B| / |A ∪ B|``. Returns 0.0 if union is empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _parse_prd_entries(text: str, id_type_pattern: str) -> list[dict[str, str]]:
    """Parse ``#### <ID> - <Title>`` headings + their description blocks."""
    heading_re = re.compile(
        rf"^####\s+({id_type_pattern})-(\d+)\s+[-]\s+(.+?)\s*$",
        re.MULTILINE,
    )
    # Iterate line by line so we can collect description blocks until the next
    # ``##+ `` heading (mirroring v1.1's behaviour).
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section_heading_re = re.compile(r"^##+ ")
    for line in text.split("\n"):
        m = heading_re.match(line)
        if m:
            if current is not None:
                entries.append(current)
            current = {
                "id": f"{m.group(1)}-{m.group(2)}",
                "title": m.group(3),
                "description": "",
            }
        elif section_heading_re.match(line):
            if current is not None:
                entries.append(current)
                current = None
        elif current is not None:
            current["description"] += " " + line
    if current is not None:
        entries.append(current)
    return entries


def propagate_ids(
    *,
    dlc_prd: Path,
    kiro_req: Path,
    threshold: float = 0.30,
    id_types: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Propagate DLC IDs from ``dlc_prd`` into ``kiro_req``.

    :param dlc_prd: path to the DLC-style PRD with ``#### FR-N - Title`` headings.
    :param kiro_req: path to the Kiro spec artifact (requirements.md / design.md / tasks.md).
    :param threshold: Jaccard similarity threshold; v1.1 default is **0.30**.
    :param id_types: which ID types to propagate (default ``['FR', 'NFR']``).
    :param dry_run: if ``True``, compute results but don't rewrite ``kiro_req``.
    :returns: dict with keys ``propagated``, ``unmapped``, ``threshold``,
        ``sourceFile``, ``dlcFile`` (the last two are v2 extensions).
    """
    if id_types is None:
        id_types = ["FR", "NFR"]
    id_type_pattern = "|".join(re.escape(t.strip()) for t in id_types)

    prd_text = read_text_utf8(Path(dlc_prd))
    entries = _parse_prd_entries(prd_text, id_type_pattern)

    kiro_text = read_text_utf8(Path(kiro_req))
    # Match v1.1: drop the trailing empty element produced by a final LF.
    kiro_normalised = kiro_text.replace("\r\n", "\n").replace("\r", "\n")
    kiro_lines = kiro_normalised.split("\n")
    if kiro_lines and kiro_lines[-1] == "":
        kiro_lines = kiro_lines[:-1]

    # Detect EARS lines.
    ears_entries: list[dict] = []
    for i, line in enumerate(kiro_lines):
        if _EARS_RE.search(line):
            ears_entries.append(
                {
                    "lineIndex": i,
                    "text": line,
                    "existingIds": _INLINE_ID_RE.findall(line),
                }
            )

    propagated: list[dict] = []
    unmapped: list[str] = []
    for e in entries:
        e_tokens = _tokenize(f"{e['title']} {e['description']}")
        best_score = 0.0
        best_ears: dict | None = None
        for ears in ears_entries:
            ears_tokens = _tokenize(ears["text"])
            score = _jaccard(e_tokens, ears_tokens)
            if score > best_score:
                best_score = score
                best_ears = ears
        if best_ears is not None and best_score >= threshold:
            line_idx = best_ears["lineIndex"]
            existing_line = kiro_lines[line_idx]
            id_comment_re = re.compile(
                rf"<!--\s*{re.escape(e['id'])}\s*-->"
            )
            if not id_comment_re.search(existing_line):
                kiro_lines[line_idx] = (
                    existing_line.rstrip() + f" <!-- {e['id']} -->"
                )
            propagated.append({"id": e["id"], "line": line_idx})
        else:
            unmapped.append(e["id"])

    # Atomic write — byte-equality guard prevents on-saved hook self-loops.
    if not dry_run:
        new_content = "\n".join(kiro_lines) + "\n"
        atomic_write_bytes(Path(kiro_req), new_content.encode("utf-8"))

    return {
        "propagated": propagated,
        "unmapped": unmapped,
        "threshold": threshold,
        "sourceFile": str(kiro_req),
        "dlcFile": str(dlc_prd),
    }


def propagate_ids_to_stdout(**kwargs) -> dict:  # pragma: no cover - thin CLI helper
    """Convenience wrapper that runs :func:`propagate_ids` and prints the
    compact JSON output v1.1 emits."""
    result = propagate_ids(**kwargs)
    print(json.dumps(result, separators=(",", ":")))
    return result
