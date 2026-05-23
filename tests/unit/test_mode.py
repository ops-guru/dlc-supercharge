"""Tests for :mod:`dlc_bridge.util.mode`."""

from __future__ import annotations

import pytest

from dlc_bridge.exceptions import ValidationError
from dlc_bridge.util.mode import VALID_MODES, resolve_mode


def test_default_is_confident() -> None:
    assert resolve_mode(None, env={}) == "confident"


def test_cli_arg_wins_over_env() -> None:
    assert resolve_mode("interactive", env={"SDLC_ORCHESTRATOR_MODE": "autopilot"}) == "interactive"


def test_env_var_used_when_cli_is_none() -> None:
    assert resolve_mode(None, env={"SDLC_ORCHESTRATOR_MODE": "autopilot"}) == "autopilot"


def test_cli_empty_string_treated_as_unset() -> None:
    # Empty string from CLI should fall through to env / default.
    assert resolve_mode("", env={"SDLC_ORCHESTRATOR_MODE": "interactive"}) == "interactive"


def test_invalid_mode_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        resolve_mode("yolo", env={})


def test_invalid_env_mode_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        resolve_mode(None, env={"SDLC_ORCHESTRATOR_MODE": "nope"})


def test_case_insensitive_normalization() -> None:
    assert resolve_mode("AUTOPILOT", env={}) == "autopilot"


def test_strips_whitespace() -> None:
    assert resolve_mode(" interactive ", env={}) == "interactive"


def test_valid_modes_frozen_set() -> None:
    assert VALID_MODES == frozenset({"interactive", "confident", "autopilot"})
