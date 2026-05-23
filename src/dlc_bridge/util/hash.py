"""FR-8 normalized SHA-256 hash for cache anchoring.

Byte-identical reproduction of v1.1's ``Get-NormalizedInputHash``
(``dlc-bridge.ps1`` lines 145–183). The parity probe in tech-design Appendix A.2
validated 8/8 fixtures byte-identical between this Python implementation and
the v1.1 PS pipeline.

The normalization steps exist so cache hits survive cosmetic edits that the
bridge itself makes (DLC ID comment injection, line-ending churn from cross-
shell editing, trailing whitespace shifts).

Steps (in order):

1. Read file as raw bytes.
2. Strip a leading UTF-8 BOM (``0xEF 0xBB 0xBF``) if present.
3. Strip DLC ID comments: ``<!-- FR-N -->``, ``<!-- NFR-N -->``, ``<!-- WI-N -->``,
   ``<!-- D-N -->``, ``<!-- R-N -->``, ``<!-- T-N -->``, ``<!-- TC-N -->``.
4. Normalize line endings: CRLF → LF, then bare CR → LF.
5. Collapse trailing whitespace before each LF (``[ \\t]+\\n`` → ``\\n``).
6. Normalize trailing newlines to exactly one final LF.
7. Compute ``sha256(normalized_bytes).hexdigest()`` (lowercase hex).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

__all__ = ["get_normalized_input_hash"]


_DLC_ID_RE = re.compile(rb"<!--\s*(FR|NFR|WI|D|R|T|TC)-\d+\s*-->")
_TRAILING_WS_RE = re.compile(rb"[ \t]+\n")
_UTF8_BOM = b"\xef\xbb\xbf"


def get_normalized_input_hash(path: Path) -> str:
    """Return the FR-8 SHA-256 hex digest of ``path``.

    See module docstring for the full step list. Raises
    :class:`FileNotFoundError` if ``path`` does not exist.
    """
    raw = Path(path).read_bytes()

    # 2. Strip BOM.
    if raw.startswith(_UTF8_BOM):
        raw = raw[3:]

    # 3. Strip DLC ID writeback comments.
    raw = _DLC_ID_RE.sub(b"", raw)

    # 4. Normalize line endings.
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    # 5. Collapse trailing whitespace before LFs.
    raw = _TRAILING_WS_RE.sub(b"\n", raw)

    # 6. Exactly one trailing LF.
    raw = raw.rstrip(b"\n") + b"\n"

    # 7. SHA-256 hex.
    return hashlib.sha256(raw).hexdigest()
