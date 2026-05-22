"""FR-19 parity gate — FR-8 normalized hash.

These 12 hex digests are **cross-validated against v1.1 PowerShell**: the same
algorithm (BOM strip, DLC ID strip, CRLF/CR normalization, trailing-whitespace
collapse, trailing-newline normalization, SHA-256 hex) emits the SAME hex on
the SAME input bytes when executed under PowerShell 5.1 (validated against
``Get-NormalizedInputHash`` in v1.1's ``dlc-bridge.ps1``).

Cross-validation was performed locally with ``powershell.exe`` on this branch;
results match all 12 fixtures (8 from Phase 4 probe per tech-design Appendix A.2,
plus 4 additional invariants).

These constants are therefore the **v1.1 contract**. Any regression in
``dlc_bridge.util.hash`` would change one of these digests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dlc_bridge.util.hash import get_normalized_input_hash


pytestmark = pytest.mark.parity


# Each tuple is (case_name, raw_bytes, expected_sha256_hex).
# Expected hex is the v1.1 contract — cross-validated against PowerShell.
HASH_FIXTURES: list[tuple[str, bytes, str]] = [
    (
        "plain_lf",
        b"hello\nworld\n",
        "4a1e67f2fe1d1cc7b31d0ca2ec441da4778203a036a77da10344c85e24ff0f92",
    ),
    (
        "crlf_normalized_to_lf",
        b"hello\r\nworld\r\n",
        "4a1e67f2fe1d1cc7b31d0ca2ec441da4778203a036a77da10344c85e24ff0f92",
    ),
    (
        "mixed_endings_with_bare_cr",
        b"a\r\nb\rc\nd",
        "cf2c7f63055d2e84af6e3f01ac1bb7fce598d20cf213fab2b56b8e8047b46ced",
    ),
    (
        "with_utf8_bom_stripped",
        b"\xef\xbb\xbfhello\n",
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
    ),
    (
        "dlc_id_fr_stripped",
        b"Story <!-- FR-1 --> done\n",
        "f984eff1c70f0d11c1b2fcc07fff8db1aabad9cad4bb4b668e6163ea8807e57f",
    ),
    (
        "all_id_types_stripped",
        b"a <!-- FR-1 --> <!-- NFR-2 --> <!-- WI-3 --> <!-- D-4 --> <!-- R-5 --> <!-- T-6 --> <!-- TC-7 --> b\n",
        "38141843224f06b6a84778f6059dbfd5c7f7c88d16a3ec25e3042bb45806788b",
    ),
    (
        "trailing_whitespace_collapsed",
        b"hello   \nworld\t\n",
        "4a1e67f2fe1d1cc7b31d0ca2ec441da4778203a036a77da10344c85e24ff0f92",
    ),
    (
        "missing_trailing_lf",
        b"hello\nworld",
        "4a1e67f2fe1d1cc7b31d0ca2ec441da4778203a036a77da10344c85e24ff0f92",
    ),
    (
        "multi_trailing_lf",
        b"hello\n\n\n\n",
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
    ),
    (
        "empty_file_normalizes_to_lf",
        b"",
        "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    ),
    (
        "lf_only_normalizes_to_single_lf",
        b"\n\n\n",
        "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    ),
    (
        "em_dash_utf8_preserved",
        b"hello \xe2\x80\x94 world\n",  # "hello — world\n"
        "d88f0a20c295ce8be1ac96fb91dc3b4c6d387858f4294581a37975755c34a64a",
    ),
]


@pytest.mark.parametrize(
    "name,raw,expected_hex",
    HASH_FIXTURES,
    ids=[t[0] for t in HASH_FIXTURES],
)
def test_hash_matches_v1_1_contract(
    name: str,
    raw: bytes,
    expected_hex: str,
    tmp_path: Path,
) -> None:
    """The Python implementation produces the v1.1 contracted hex digest."""
    fixture = tmp_path / f"{name}.txt"
    fixture.write_bytes(raw)
    actual = get_normalized_input_hash(fixture)
    assert actual == expected_hex, (
        f"Hash divergence for fixture {name!r} would break v1.1 cache parity.\n"
        f"Expected (v1.1 PS contract): {expected_hex}\n"
        f"Actual   (Python v2.0):      {actual}"
    )
