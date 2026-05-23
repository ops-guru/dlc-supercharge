"""FR-19 parity gate — FR-11 id-propagate.

Cross-language comparison of Python ``id_propagate.propagate_ids`` against
v1.1 ``id-propagate.ps1`` on three fixtures:

* ``basic``         — 3 FR/NFR entries that match EARS lines (all propagate)
* ``unmapped``      — high-threshold case where no EARS line matches
* ``idempotent``    — pre-existing inline comment; re-run should not change file

For each fixture, both implementations are driven from the same input. The
resulting source.md is compared byte-for-byte; the stdout JSON is compared as
parsed dict.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dlc_bridge.util.id_propagate import propagate_ids

from .conftest import normalize_eol, require_powershell_and_legacy, run_powershell


pytestmark = pytest.mark.parity


def _strip_bom(text: str) -> str:
    """Strip UTF-8 BOM (v1.1 PS sometimes writes one despite the no-BOM intent)."""
    return text.lstrip("﻿")


def _normalize(text: str) -> str:
    return normalize_eol(_strip_bom(text))


def _ps_propagate(
    dlc_prd: Path,
    kiro_req: Path,
    repo_root: Path,
    threshold: float = 0.30,
) -> dict:
    """Run v1.1 ``id-propagate.ps1`` and return parsed stdout JSON."""
    script = repo_root / ".kiro" / "scripts" / "id-propagate.ps1"
    cp = run_powershell(
        [
            "-File", str(script),
            "-DlcPrd", str(dlc_prd),
            "-KiroReq", str(kiro_req),
            "-Threshold", str(threshold),
        ],
    )
    # PS may emit `[bridge]`-style log lines on stderr; the JSON is on stdout.
    stdout = cp.stdout.strip()
    return json.loads(stdout)


def _setup_fixture(fixture_dir: Path, fixture_name: str, tmp_path: Path) -> tuple[Path, Path]:
    """Copy a fixture pair into ``tmp_path/<fixture_name>/`` and return paths."""
    target = tmp_path / fixture_name
    target.mkdir(parents=True, exist_ok=True)
    src_prd = fixture_dir / "dlc.prd.md"
    src_source = fixture_dir / "source.md"
    dst_prd = target / "dlc.prd.md"
    dst_source = target / "source.md"
    shutil.copy2(src_prd, dst_prd)
    shutil.copy2(src_source, dst_source)
    return dst_prd, dst_source


FIXTURES = [
    ("basic", 0.30, 3),  # expect 3 propagations
    ("unmapped", 0.90, 0),  # threshold high enough that nothing propagates
    ("idempotent", 0.30, 1),  # 1 entry, already commented — propagated but no write
]


@require_powershell_and_legacy
@pytest.mark.parametrize("name,threshold,expected_propagated", FIXTURES, ids=[f[0] for f in FIXTURES])
def test_id_propagate_matches_v1_1(
    name: str,
    threshold: float,
    expected_propagated: int,
    tmp_path: Path,
    fixtures_root: Path,
    repo_root: Path,
) -> None:
    """Python and v1.1 PS produce byte-equal source.md + structurally-equal stdout."""
    fixture_dir = fixtures_root / "id-prop" / name

    # Python side
    py_prd, py_source = _setup_fixture(fixture_dir, "py", tmp_path)
    py_result = propagate_ids(
        dlc_prd=py_prd,
        kiro_req=py_source,
        threshold=threshold,
    )

    # PowerShell side
    ps_prd, ps_source = _setup_fixture(fixture_dir, "ps", tmp_path)
    ps_result = _ps_propagate(ps_prd, ps_source, repo_root, threshold=threshold)

    # 1. Modified source files match byte-for-byte (after EOL/BOM normalization)
    py_text = _normalize(py_source.read_text(encoding="utf-8"))
    ps_text = _normalize(ps_source.read_text(encoding="utf-8"))
    assert py_text == ps_text, (
        f"Fixture {name!r}: source.md diverges after id-propagate.\n"
        f"Python output:\n{py_text}\n---\n"
        f"PowerShell output:\n{ps_text}"
    )

    # 2. Propagated count matches
    assert len(py_result["propagated"]) == expected_propagated
    assert len(ps_result["propagated"]) == expected_propagated

    # 3. Propagated IDs match (set comparison — order doesn't matter)
    py_ids = {p["id"] for p in py_result["propagated"]}
    ps_ids = {p["id"] for p in ps_result["propagated"]}
    assert py_ids == ps_ids, (
        f"Fixture {name!r}: propagated ID set diverges. "
        f"Python: {py_ids}, PowerShell: {ps_ids}"
    )

    # 4. Threshold echoed correctly
    assert py_result["threshold"] == threshold
    assert float(ps_result["threshold"]) == threshold


class TestIdPropagateRegression:
    """Python-only regression tests for id_propagate. Run on every CI leg."""

    def test_basic_fixture_propagates_three_ids(
        self, tmp_path: Path, fixtures_root: Path
    ) -> None:
        py_prd, py_source = _setup_fixture(
            fixtures_root / "id-prop" / "basic", "regression", tmp_path
        )
        result = propagate_ids(dlc_prd=py_prd, kiro_req=py_source, threshold=0.30)
        assert len(result["propagated"]) == 3

    def test_high_threshold_unmaps(self, tmp_path: Path, fixtures_root: Path) -> None:
        py_prd, py_source = _setup_fixture(
            fixtures_root / "id-prop" / "unmapped", "regression", tmp_path
        )
        result = propagate_ids(dlc_prd=py_prd, kiro_req=py_source, threshold=0.90)
        assert len(result["unmapped"]) == 1
        assert "FR-99" in result["unmapped"]
