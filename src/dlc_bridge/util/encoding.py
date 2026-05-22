"""UTF-8 text I/O helpers with idempotence guard.

Centralizes every text- and JSON-write performed by the bridge so we can enforce
the NFR-3 (UTF-8 no-BOM, LF endings) and NFR-4 (idempotent writes — no rewrite
when on-disk bytes equal the proposed content) invariants in one place.

Idempotence matters because Kiro's ``fileEdited`` hook re-fires when any tracked
file changes. v1.1 PowerShell guarded this by comparing ``existingBytes`` to
``newBytes`` element-by-element before ``Move-Item -Force``. We mirror the same
guard via :func:`atomic_write_bytes`, layered under every text / JSON writer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = [
    "read_text_utf8",
    "write_text_utf8_lf",
    "atomic_write_utf8_lf",
    "atomic_write_bytes",
    "write_json_utf8_lf",
]


_UTF8_BOM = b"\xef\xbb\xbf"


def read_text_utf8(path: Path) -> str:
    """Read a file as UTF-8, tolerating a UTF-8 BOM.

    Strips a leading ``0xEF 0xBB 0xBF`` sequence if present. Does NOT normalize
    line endings — callers that need that should reach for :mod:`hash` (which
    applies the FR-8 normalization) or do their own ``.replace('\\r\\n', '\\n')``.

    Raises :class:`FileNotFoundError` if ``path`` does not exist; surfaces any
    ``UnicodeDecodeError`` raised by the codec.
    """
    raw = Path(path).read_bytes()
    if raw.startswith(_UTF8_BOM):
        raw = raw[3:]
    return raw.decode("utf-8")


def write_text_utf8_lf(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` as UTF-8 with LF line endings, no BOM.

    Does NOT apply the idempotence guard — use :func:`atomic_write_utf8_lf` for
    that. This helper is exposed primarily for tests and for the rare callers
    that want unconditional overwrite semantics.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ``newline='\\n'`` disables Python's default \\r\\n translation on Windows.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def atomic_write_bytes(path: Path, data: bytes) -> bool:
    """Atomic, idempotence-guarded byte write.

    Returns ``True`` if the file was (re)written, ``False`` if the on-disk
    bytes were already equal to ``data`` (no write performed).

    The write goes through a sibling ``.tmp`` file followed by
    :func:`os.replace` (atomic on POSIX and Windows since Python 3.3).
    """
    path = Path(path)
    if path.exists():
        existing = path.read_bytes()
        if existing == data:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # Write all bytes first, then atomic rename.
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return True


def atomic_write_utf8_lf(path: Path, content: str) -> bool:
    """Atomic, idempotence-guarded UTF-8 / LF text write.

    Encodes ``content`` (after CRLF→LF normalization) as UTF-8 without BOM and
    delegates to :func:`atomic_write_bytes`. Returns ``True`` if the file was
    actually written, ``False`` on no-op.
    """
    # Normalize line endings before encoding so callers that hand us a Windows-
    # native string still get LF on disk.
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    data = normalized.encode("utf-8")
    return atomic_write_bytes(path, data)


def write_json_utf8_lf(
    path: Path,
    obj: Any,
    indent: int = 2,
) -> bool:
    """Atomic, idempotence-guarded JSON write.

    Serializes via :func:`json.dumps` with ``ensure_ascii=False`` (preserves
    non-ASCII as UTF-8 bytes, matching v1.1's ``ConvertTo-Json -Depth 8``
    behaviour for the Kiro Powers registries). Appends a single trailing LF.

    Returns ``True`` if the file was written, ``False`` if the on-disk bytes
    already matched.
    """
    text = json.dumps(
        obj,
        indent=indent,
        ensure_ascii=False,
        separators=(",", ": "),
    )
    if not text.endswith("\n"):
        text += "\n"
    return atomic_write_utf8_lf(path, text)
