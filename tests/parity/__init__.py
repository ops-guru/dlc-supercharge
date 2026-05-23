"""FR-19 parity gate package.

These tests compare the Python v2.0 bridge runtime against the v1.1 PowerShell
runtime byte-for-byte (modulo documented exclusions) on canonical fixtures.

This gate is the cutover-critical pre-merge check: WI-15 (delete legacy
``.kiro/scripts/*.ps1``/``*.sh``) MUST NOT proceed until all tests under
``tests/parity/`` are 100% green.
"""
