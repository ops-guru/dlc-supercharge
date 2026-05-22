"""FR-6 status-file lifecycle for bridge invocations.

Each bridge invocation produces a JSON document at
``.dlc/_bridge-jobs/<jobId>.status.json`` describing its current state.
Hooks like ``check-dlc-job`` enumerate this directory to surface
running / complete / cancelled / errored work to the user.

Schema (v1.1 parity)
--------------------

The v1.1 PowerShell helper (``dlc-bridge-status.ps1``) writes these fields:

* ``jobId`` — ``<verb>-<yyyyMMddTHHmmssZ>-<6 hex>``
* ``verb`` — one of :data:`dlc_bridge.verbs.SUPPORTED_VERBS`
* ``args`` — arbitrary dict of CLI args
* ``status`` — ``"running" | "complete" | "error" | "cancelled" | "cache-hit" | "dry-run"``
* ``startedAt`` — ISO-8601 UTC
* ``heartbeatAt`` — ISO-8601 UTC, updated alongside status transitions
* ``endedAt`` — ISO-8601 UTC or ``null`` while running
* ``exitCode`` — final exit code or ``null`` while running
* ``pid`` — owning process PID (informational)
* ``outputManifest`` — list of artifact paths emitted
* ``logPath`` — path to log file or empty string
* ``promptDigest`` — ``"sha256:<first 16 hex>"``

We follow v1.1 EXACTLY on field names. Two optional forward-compat fields
(``durationSec`` and ``attempts``) are accepted by writers but only emitted
when explicitly set; they DO NOT replace v1.1's ``endedAt``/``heartbeatAt``.
The brief mentioned ``completedAt`` — that field is intentionally NOT used
because v1.1 uses ``endedAt`` (parity rule).

Atomic writes go through :func:`dlc_bridge.util.encoding.write_json_utf8_lf`.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dlc_bridge.exceptions import CacheError
from dlc_bridge.util.encoding import write_json_utf8_lf

__all__ = [
    "StatusFile",
    "generate_job_id",
    "compute_prompt_digest",
    "status_path_for",
    "initialize_status",
    "complete_status",
    "error_status",
    "cancel_status",
    "read_status",
    "iso_now",
]

_JOB_ID_RAND_BYTES = 3  # 3 bytes → 6 hex chars, matches v1.1 `Substring(0,6)`.

# Valid status values per v1.1's `Complete-DlcStatus -ValidateSet`.
_VALID_STATUSES = frozenset(
    {"running", "complete", "error", "cancelled", "cache-hit", "dry-run"}
)


@dataclass
class StatusFile:
    """In-memory mirror of the on-disk status JSON.

    Field ORDER matches v1.1's emission order so JSON output is stable and
    parity-checkable. ``durationSec`` and ``attempts`` are forward-compat
    additions; both default to None and are excluded from JSON when None.
    """

    jobId: str
    verb: str
    args: dict[str, Any]
    status: str
    startedAt: str
    heartbeatAt: str
    endedAt: str | None = None
    exitCode: int | None = None
    pid: int | None = None
    outputManifest: list[str] = field(default_factory=list)
    logPath: str | None = ""
    promptDigest: str | None = None
    durationSec: float | None = None
    attempts: int | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict, dropping forward-compat None fields.

        v1.1's emitter always wrote all 12 fields (with PS ``$null`` for
        nulls). We preserve that for the v1.1 set, but omit
        ``durationSec``/``attempts`` when they're None — they didn't exist
        in v1.1, so emitting ``null`` keys would be a spurious shape change.
        """
        d = asdict(self)
        for optional in ("durationSec", "attempts"):
            if d.get(optional) is None:
                d.pop(optional, None)
        return d


def iso_now() -> str:
    """ISO-8601 UTC, second precision, trailing 'Z' — matches v1.1.

    Exposed publicly so callers (e.g. ``cli.py`` cache-hit status writer)
    don't have to duplicate the format string.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Backwards-compat alias for internal callers that imported the private name.
_iso_now = iso_now


def _job_id_ts(now: datetime | None = None) -> str:
    """Compact UTC timestamp ``yyyyMMddTHHmmssZ`` used in job IDs."""
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def generate_job_id(verb: str, *, now: datetime | None = None) -> str:
    """Return ``<verb>-<yyyyMMddTHHmmssZ>-<6 hex>``.

    Matches v1.1's ``New-DlcJobId``. The trailing 6-hex segment is a
    cryptographically random short tag; collision risk inside a single
    second per verb is ~1 in 16M.
    """
    return f"{verb}-{_job_id_ts(now)}-{secrets.token_hex(_JOB_ID_RAND_BYTES)}"


def compute_prompt_digest(prompt: str) -> str:
    """Return ``"sha256:<first 16 hex>"`` — v1.1's prompt digest format.

    Mirrors ``Get-DlcPromptDigest`` exactly: SHA-256 over UTF-8 bytes, take
    the first 16 hex chars (= 8 bytes = ~64 bits of collision resistance,
    plenty for replay detection).
    """
    hex_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return f"sha256:{hex_digest[:16]}"


def _status_dir(dlc_root: Path | None) -> Path:
    """Return (and ensure exists) the ``.dlc/_bridge-jobs/`` directory."""
    root = Path(dlc_root) if dlc_root is not None else Path.cwd() / ".dlc"
    d = root / "_bridge-jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def status_path_for(job_id: str, *, dlc_root: Path | None = None) -> Path:
    """Return ``.dlc/_bridge-jobs/<jobId>.status.json``.

    Does NOT create the parent directory; :func:`initialize_status` handles
    that. This helper is exposed for tests + hooks that need to inspect a
    known job ID.
    """
    root = Path(dlc_root) if dlc_root is not None else Path.cwd() / ".dlc"
    return root / "_bridge-jobs" / f"{job_id}.status.json"


def initialize_status(
    *,
    verb: str,
    args: dict[str, Any],
    job_id: str | None = None,
    prompt_digest: str | None = None,
    log_path: str | None = "",
    pid: int | None = None,
    dlc_root: Path | None = None,
) -> StatusFile:
    """Create the initial ``status='running'`` status file.

    Args:
        verb: Verb name (used to derive a fresh job-ID when ``job_id`` is None).
        args: Dict of CLI args (becomes ``args`` JSON field).
        job_id: Pre-allocated job-ID, or None to generate one.
        prompt_digest: Output of :func:`compute_prompt_digest`, or None.
        log_path: Optional path to a log file (background mode). Empty string
            for foreground.
        pid: Owning process PID; defaults to current process.
        dlc_root: Override the default ``.dlc`` location (tests).

    Returns:
        The :class:`StatusFile` instance. The on-disk JSON is written
        atomically before this returns.
    """
    if job_id is None:
        job_id = generate_job_id(verb)
    if pid is None:
        pid = os.getpid()
    now = _iso_now()
    status = StatusFile(
        jobId=job_id,
        verb=verb,
        args=dict(args),
        status="running",
        startedAt=now,
        heartbeatAt=now,
        endedAt=None,
        exitCode=None,
        pid=pid,
        outputManifest=[],
        logPath=log_path or "",
        promptDigest=prompt_digest,
    )
    _status_dir(dlc_root)
    write_json_utf8_lf(status_path_for(job_id, dlc_root=dlc_root), status.to_json_dict())
    return status


def _load_existing(job_id: str, dlc_root: Path | None) -> dict[str, Any]:
    """Read the on-disk JSON for ``job_id``; raise :class:`CacheError` if absent."""
    path = status_path_for(job_id, dlc_root=dlc_root)
    if not path.is_file():
        raise CacheError(f"status file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CacheError(f"status file malformed: {path}: {exc}") from exc


def _duration_seconds(started_at: str) -> float | None:
    """Return seconds elapsed since ``started_at`` (ISO-8601 UTC), or None."""
    try:
        ts = started_at.rstrip("Z")
        dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _finalize(
    *,
    job_id: str,
    status: str,
    exit_code: int,
    output_manifest: list[str] | None = None,
    log_path: str | None = None,
    prompt_digest: str | None = None,
    duration_sec: float | None = None,
    attempts: int | None = None,
    dlc_root: Path | None = None,
) -> StatusFile:
    """Shared body for the complete/error/cancel public functions."""
    if status not in _VALID_STATUSES:
        raise CacheError(f"invalid terminal status: {status!r}")

    existing = _load_existing(job_id, dlc_root)
    now = _iso_now()
    existing["status"] = status
    existing["endedAt"] = now
    existing["heartbeatAt"] = now
    existing["exitCode"] = exit_code
    if output_manifest is not None:
        existing["outputManifest"] = list(output_manifest)
    if log_path is not None:
        existing["logPath"] = log_path
    if prompt_digest is not None:
        existing["promptDigest"] = prompt_digest
    if duration_sec is None and existing.get("startedAt"):
        duration_sec = _duration_seconds(existing["startedAt"])
    if duration_sec is not None:
        existing["durationSec"] = float(duration_sec)
    if attempts is not None:
        existing["attempts"] = int(attempts)

    write_json_utf8_lf(status_path_for(job_id, dlc_root=dlc_root), existing)

    return StatusFile(
        jobId=existing["jobId"],
        verb=existing["verb"],
        args=existing.get("args", {}),
        status=existing["status"],
        startedAt=existing["startedAt"],
        heartbeatAt=existing["heartbeatAt"],
        endedAt=existing.get("endedAt"),
        exitCode=existing.get("exitCode"),
        pid=existing.get("pid"),
        outputManifest=list(existing.get("outputManifest") or []),
        logPath=existing.get("logPath", ""),
        promptDigest=existing.get("promptDigest"),
        durationSec=existing.get("durationSec"),
        attempts=existing.get("attempts"),
    )


def complete_status(
    *,
    job_id: str,
    exit_code: int = 0,
    output_manifest: list[str] | None = None,
    prompt_digest: str | None = None,
    log_path: str | None = None,
    duration_sec: float | None = None,
    attempts: int | None = None,
    dlc_root: Path | None = None,
) -> StatusFile:
    """Mark a status file as ``complete`` (exit 0) or ``error`` (exit !=0).

    Matches v1.1's ``Complete-DlcStatus`` semantics: terminal status is
    derived from the exit code so callers don't have to pick the string
    themselves. Use :func:`error_status` directly when there is no
    meaningful exit code (e.g. an internal crash before the subprocess
    started).
    """
    terminal = "complete" if exit_code == 0 else "error"
    return _finalize(
        job_id=job_id,
        status=terminal,
        exit_code=exit_code,
        output_manifest=output_manifest,
        log_path=log_path,
        prompt_digest=prompt_digest,
        duration_sec=duration_sec,
        attempts=attempts,
        dlc_root=dlc_root,
    )


def error_status(
    *,
    job_id: str,
    message: str | None = None,
    exit_code: int = 1,
    duration_sec: float | None = None,
    attempts: int | None = None,
    dlc_root: Path | None = None,
) -> StatusFile:
    """Mark a status file as ``error`` with an explicit exit code.

    ``message`` is accepted for caller convenience but is NOT written to the
    status file (v1.1 does not have an error-message field). The recommended
    pattern is: log the message via :func:`dlc_bridge.util.emit.emit_log` and
    then call this function with the corresponding exit code.
    """
    del message  # not part of the v1.1 schema; surface via emit_log instead
    return _finalize(
        job_id=job_id,
        status="error",
        exit_code=exit_code,
        duration_sec=duration_sec,
        attempts=attempts,
        dlc_root=dlc_root,
    )


def cancel_status(
    *,
    job_id: str,
    exit_code: int = 7,
    dlc_root: Path | None = None,
) -> StatusFile:
    """Mark a status file as ``cancelled`` (e.g. Ctrl+C / SIGTERM).

    Exit code defaults to 7 to match v1.1's ``CancelledError.exit_code``.
    """
    return _finalize(
        job_id=job_id,
        status="cancelled",
        exit_code=exit_code,
        dlc_root=dlc_root,
    )


def read_status(job_id: str, *, dlc_root: Path | None = None) -> StatusFile:
    """Read and parse the on-disk status JSON for ``job_id``.

    Raises :class:`CacheError` if the file is missing or malformed.
    """
    raw = _load_existing(job_id, dlc_root)
    return StatusFile(
        jobId=raw["jobId"],
        verb=raw["verb"],
        args=raw.get("args", {}),
        status=raw["status"],
        startedAt=raw["startedAt"],
        heartbeatAt=raw.get("heartbeatAt", raw["startedAt"]),
        endedAt=raw.get("endedAt"),
        exitCode=raw.get("exitCode"),
        pid=raw.get("pid"),
        outputManifest=list(raw.get("outputManifest") or []),
        logPath=raw.get("logPath", ""),
        promptDigest=raw.get("promptDigest"),
        durationSec=raw.get("durationSec"),
        attempts=raw.get("attempts"),
    )
