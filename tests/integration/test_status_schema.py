"""WI-19 status-file schema tests (Epic 2b).

Asserts that :mod:`dlc_bridge.status` produces JSON matching the v1.1 field
set (jobId/verb/args/status/startedAt/heartbeatAt/endedAt/exitCode/pid/
outputManifest/logPath/promptDigest) and that the lifecycle transitions
(initialize → complete / error / cancel) update the right fields.

The brief mentioned ``completedAt``/``durationSec`` as required fields —
v1.1 actually uses ``endedAt`` and has no ``durationSec``. We follow v1.1
parity exactly: ``endedAt`` is the terminal-timestamp field. ``durationSec``
and ``attempts`` are forward-compat additions that only appear when
explicitly set.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from dlc_bridge import status as status_mod
from dlc_bridge.exceptions import CacheError

pytestmark = pytest.mark.integration


# Required v1.1 field set (mirrors ``dlc-bridge-status.ps1:98-111``).
V1_1_REQUIRED_FIELDS = frozenset(
    {
        "jobId", "verb", "args", "status",
        "startedAt", "heartbeatAt", "endedAt",
        "exitCode", "pid", "outputManifest",
        "logPath", "promptDigest",
    }
)


# ----- generate_job_id ------------------------------------------------------


def test_job_id_format_matches_v1_1() -> None:
    """``<verb>-<yyyyMMddTHHmmssZ>-<6 hex>`` parity with v1.1 New-DlcJobId."""
    jid = status_mod.generate_job_id("analyze-requirements")
    m = re.fullmatch(
        r"analyze-requirements-(\d{8}T\d{6}Z)-([0-9a-f]{6})",
        jid,
    )
    assert m is not None, f"job-id did not match v1.1 shape: {jid}"


def test_job_id_uniqueness_in_same_second() -> None:
    """Random suffix gives collision-resistance even within the same second."""
    ids = {status_mod.generate_job_id("hotfix") for _ in range(50)}
    assert len(ids) == 50


def test_job_id_uses_utc_timezone() -> None:
    """ts segment must be UTC (trailing Z; no local-time leakage)."""
    jid = status_mod.generate_job_id("babysit-pr")
    # The middle segment must end with Z.
    parts = jid.split("-")
    # verb has hyphens too; the timestamp is the second-to-last segment.
    ts_segment = parts[-2]
    assert ts_segment.endswith("Z")


# ----- compute_prompt_digest -----------------------------------------------


def test_prompt_digest_v1_1_format() -> None:
    """``sha256:<16 hex>`` matches v1.1 Get-DlcPromptDigest."""
    digest = status_mod.compute_prompt_digest("hello")
    assert digest.startswith("sha256:")
    hex_part = digest.split(":", 1)[1]
    assert len(hex_part) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", hex_part)


def test_prompt_digest_stable_per_input() -> None:
    """Same input → same digest (deterministic)."""
    a = status_mod.compute_prompt_digest("task body 123")
    b = status_mod.compute_prompt_digest("task body 123")
    assert a == b


# ----- initialize_status ----------------------------------------------------


def test_initialize_status_writes_running(tmp_path: Path) -> None:
    """``initialize_status`` writes a ``status='running'`` JSON file with v1.1 fields."""
    dlc = tmp_path / ".dlc"
    st = status_mod.initialize_status(
        verb="analyze-requirements",
        args={"source": "x.md", "mode": "confident"},
        prompt_digest="sha256:abcdef0123456789",
        dlc_root=dlc,
    )
    assert st.status == "running"
    assert st.endedAt is None
    assert st.exitCode is None

    on_disk = json.loads(
        status_mod.status_path_for(st.jobId, dlc_root=dlc).read_text(encoding="utf-8")
    )
    # All v1.1 fields present.
    for f in V1_1_REQUIRED_FIELDS:
        assert f in on_disk, f"missing v1.1 field {f}"

    # status / verb / args content correct.
    assert on_disk["status"] == "running"
    assert on_disk["verb"] == "analyze-requirements"
    assert on_disk["args"] == {"source": "x.md", "mode": "confident"}
    # endedAt null while running.
    assert on_disk["endedAt"] is None


def test_initialize_status_pid_defaults_to_current(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st = status_mod.initialize_status(
        verb="hotfix", args={}, dlc_root=dlc,
    )
    assert st.pid == os.getpid()


def test_initialize_status_explicit_job_id(tmp_path: Path) -> None:
    """Caller can pre-allocate the job-ID."""
    dlc = tmp_path / ".dlc"
    st = status_mod.initialize_status(
        verb="hotfix", args={}, job_id="hotfix-custom-123abc", dlc_root=dlc,
    )
    assert st.jobId == "hotfix-custom-123abc"
    assert status_mod.status_path_for(st.jobId, dlc_root=dlc).is_file()


def test_initialize_status_no_bom_lf_writes(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    raw = status_mod.status_path_for(st.jobId, dlc_root=dlc).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "must not write BOM"
    assert b"\r\n" not in raw, "must not write CRLF"


# ----- complete_status ------------------------------------------------------


def test_complete_status_writes_complete_for_exit_0(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="analyze-requirements", args={}, dlc_root=dlc)
    time.sleep(0.05)
    st = status_mod.complete_status(
        job_id=st0.jobId, exit_code=0,
        output_manifest=[".dlc/foo/req.md"], dlc_root=dlc,
    )
    assert st.status == "complete"
    assert st.exitCode == 0
    assert st.endedAt is not None
    assert st.outputManifest == [".dlc/foo/req.md"]
    # Duration was auto-computed.
    assert st.durationSec is not None
    assert st.durationSec >= 0


def test_complete_status_writes_error_for_nonzero_exit(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    st = status_mod.complete_status(job_id=st0.jobId, exit_code=5, dlc_root=dlc)
    assert st.status == "error"
    assert st.exitCode == 5


def test_complete_status_emits_v1_1_field_set(tmp_path: Path) -> None:
    """After completion, the JSON still has every v1.1 field."""
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(
        verb="hotfix", args={"mode": "revert"},
        prompt_digest="sha256:0000000000000000", dlc_root=dlc,
    )
    status_mod.complete_status(job_id=st0.jobId, exit_code=0, dlc_root=dlc)
    raw = json.loads(
        status_mod.status_path_for(st0.jobId, dlc_root=dlc).read_text(encoding="utf-8")
    )
    for f in V1_1_REQUIRED_FIELDS:
        assert f in raw


def test_error_status_marks_error(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    st = status_mod.error_status(
        job_id=st0.jobId, message="oops", exit_code=4, dlc_root=dlc,
    )
    assert st.status == "error"
    assert st.exitCode == 4
    # endedAt populated; duration computed.
    assert st.endedAt is not None
    assert st.durationSec is not None


def test_cancel_status_marks_cancelled(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    st = status_mod.cancel_status(job_id=st0.jobId, dlc_root=dlc)
    assert st.status == "cancelled"
    assert st.exitCode == 7  # CancelledError exit code


# ----- read_status -----------------------------------------------------------


def test_read_status_round_trip(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(
        verb="analyze-requirements",
        args={"source": "in.md", "mode": "autopilot"},
        prompt_digest="sha256:1234567890abcdef", dlc_root=dlc,
    )
    loaded = status_mod.read_status(st0.jobId, dlc_root=dlc)
    assert loaded.jobId == st0.jobId
    assert loaded.verb == "analyze-requirements"
    assert loaded.args["source"] == "in.md"
    assert loaded.promptDigest == "sha256:1234567890abcdef"


def test_read_status_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(CacheError):
        status_mod.read_status("nonexistent-job-id", dlc_root=tmp_path / ".dlc")


def test_read_status_raises_on_malformed_json(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    path = status_mod.status_path_for("bad-job", dlc_root=dlc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8", newline="\n")
    with pytest.raises(CacheError):
        status_mod.read_status("bad-job", dlc_root=dlc)


# ----- forward-compat fields (durationSec / attempts) ----------------------


def test_optional_fields_excluded_when_none(tmp_path: Path) -> None:
    """``durationSec`` and ``attempts`` must NOT appear when never set."""
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    raw = json.loads(
        status_mod.status_path_for(st0.jobId, dlc_root=dlc).read_text(encoding="utf-8")
    )
    # v1.1 schema has neither field, so initial running state should omit them.
    assert "durationSec" not in raw
    assert "attempts" not in raw


def test_attempts_field_present_when_set(tmp_path: Path) -> None:
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    status_mod.complete_status(
        job_id=st0.jobId, exit_code=0, attempts=2, dlc_root=dlc,
    )
    raw = json.loads(
        status_mod.status_path_for(st0.jobId, dlc_root=dlc).read_text(encoding="utf-8")
    )
    assert raw["attempts"] == 2


# ----- schema validation ----------------------------------------------------


def test_status_json_is_valid_json(tmp_path: Path) -> None:
    """JSON-loads round-trip succeeds with no exception."""
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(
        verb="analyze-requirements", args={"source": "x"}, dlc_root=dlc,
    )
    status_mod.complete_status(job_id=st0.jobId, exit_code=0, dlc_root=dlc)
    raw_text = status_mod.status_path_for(st0.jobId, dlc_root=dlc).read_text(
        encoding="utf-8"
    )
    parsed = json.loads(raw_text)
    assert isinstance(parsed, dict)


def test_complete_status_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CacheError):
        status_mod.complete_status(
            job_id="nonexistent", exit_code=0, dlc_root=tmp_path / ".dlc",
        )


def test_no_completedAt_field_v1_1_parity(tmp_path: Path) -> None:
    """Parity: v1.1 uses ``endedAt`` NOT ``completedAt``. Brief was wrong."""
    dlc = tmp_path / ".dlc"
    st0 = status_mod.initialize_status(verb="hotfix", args={}, dlc_root=dlc)
    status_mod.complete_status(job_id=st0.jobId, exit_code=0, dlc_root=dlc)
    raw = json.loads(
        status_mod.status_path_for(st0.jobId, dlc_root=dlc).read_text(encoding="utf-8")
    )
    # Negative assertion: v1.1 has no completedAt.
    assert "completedAt" not in raw
    # Positive assertion: v1.1 has endedAt.
    assert "endedAt" in raw
    assert raw["endedAt"] is not None
