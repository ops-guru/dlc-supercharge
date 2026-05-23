"""Utility modules for the DLC SuperCharge bridge.

This package contains the parity-sensitive helper surface ported from the v1.1
PowerShell scripts:

* :mod:`encoding` — UTF-8 no-BOM / LF text + JSON writers with idempotence guard (NFR-3, NFR-4)
* :mod:`emit` — structured stdout / stderr markers and log lines
* :mod:`mode` — interaction-mode resolution (CLI > env > default)
* :mod:`slug` — FR-17 slug derivation from spec paths / PR numbers
* :mod:`hash` — FR-8 normalized SHA-256 (byte-identical to v1.1)
* :mod:`state` — FR-12 state.md transitions (init / advance / mark_skipped / ...)
* :mod:`id_propagate` — FR-11 Jaccard-based DLC ID propagation
* :mod:`epic_inject` — FR-13 idempotent epic plan injection into tasks.md
* :mod:`debounce` — FR-18 cross-process fire-suppression via :mod:`filelock`
* :mod:`power` — FR-16 Kiro Powers registry writer (no-BOM JSON)
"""
