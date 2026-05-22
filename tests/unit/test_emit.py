"""Tests for :mod:`dlc_bridge.util.emit`."""

from __future__ import annotations

import pytest

from dlc_bridge.util.emit import emit_log, emit_marker


def test_emit_marker_with_value(capsys: pytest.CaptureFixture[str]) -> None:
    emit_marker("BRIDGE_CACHED", ".dlc/foo/x.md")
    out = capsys.readouterr().out
    assert out == "BRIDGE_CACHED=.dlc/foo/x.md\n"


def test_emit_marker_defaults_value_to_one(capsys: pytest.CaptureFixture[str]) -> None:
    emit_marker("PROCEED")
    assert capsys.readouterr().out == "PROCEED=1\n"


def test_emit_marker_writes_lf_only(capsys: pytest.CaptureFixture[str]) -> None:
    emit_marker("X", "y")
    out = capsys.readouterr().out
    assert "\r" not in out


def test_emit_log_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    emit_log("error", "boom")
    captured = capsys.readouterr()
    assert captured.err == "[dlc-bridge] error: boom\n"
    assert captured.out == ""


def test_emit_log_format(capsys: pytest.CaptureFixture[str]) -> None:
    emit_log("warning", "something happened")
    assert capsys.readouterr().err == "[dlc-bridge] warning: something happened\n"
