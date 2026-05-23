"""Interaction-mode resolution.

The bridge supports three interaction modes (per PRD FR-1 and the SDLC
orchestrator contract):

* ``interactive`` — pause for user confirmation at every decision point
* ``confident`` — default; pause only at major checkpoints
* ``autopilot`` — never pause; auto-decide using documented heuristics

Resolution precedence (CLI wins, env fills in, default last):

1. Explicit ``cli_mode`` argument
2. ``SDLC_ORCHESTRATOR_MODE`` environment variable
3. ``"confident"`` default
"""

from __future__ import annotations

import os
from typing import Mapping

from dlc_bridge.exceptions import ValidationError

__all__ = ["VALID_MODES", "resolve_mode"]


VALID_MODES: frozenset[str] = frozenset({"interactive", "confident", "autopilot"})


def resolve_mode(
    cli_mode: str | None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve the active interaction mode.

    :param cli_mode: explicit value from ``--mode`` (or ``None`` if absent).
    :param env: environment-variable mapping; defaults to :data:`os.environ`.
        Pass an explicit dict in tests to avoid environment leakage.
    :returns: one of ``"interactive"``, ``"confident"``, ``"autopilot"``.
    :raises ValidationError: if the resolved value is not one of the three
        accepted modes.
    """
    env_mapping = env if env is not None else os.environ

    raw = cli_mode if cli_mode else env_mapping.get("SDLC_ORCHESTRATOR_MODE", "")
    candidate = raw.strip().lower() if raw else "confident"

    if candidate not in VALID_MODES:
        raise ValidationError(
            f"invalid interaction mode {candidate!r}; "
            f"expected one of {sorted(VALID_MODES)}"
        )
    return candidate
