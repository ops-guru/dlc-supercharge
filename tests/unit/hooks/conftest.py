"""Shared fixtures for hook unit tests.

Centralises the ``invoke_bridge_stub`` fixture used by every hook test: it
monkeypatches :func:`dlc_bridge.hooks._common.invoke_bridge` with a
recording stub so tests can assert what argv was passed and configure the
returned :class:`subprocess.CompletedProcess` per call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterator

import pytest

from dlc_bridge.hooks import _common


class BridgeInvocationRecorder:
    """Records :func:`_common.invoke_bridge` calls; returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next_returncode: int = 0
        self._next_stdout: str = ""
        self._next_stderr: str = ""
        self._per_verb_returncodes: dict[str, int] = {}
        self._per_verb_stdouts: dict[str, str] = {}

    def set_next(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        """Configure the next subprocess return."""
        self._next_returncode = returncode
        self._next_stdout = stdout
        self._next_stderr = stderr

    def set_for_verb(self, verb: str, returncode: int = 0, stdout: str = "") -> None:
        """Configure return values for a specific verb."""
        self._per_verb_returncodes[verb] = returncode
        self._per_verb_stdouts[verb] = stdout

    def __call__(
        self,
        verb: str,
        *,
        args: list[str] | None = None,
        background: bool = False,
        dry_run: bool = False,
        cwd: Path | str | None = None,
        capture_output: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        record = {
            "verb": verb,
            "args": list(args or []),
            "background": background,
            "dry_run": dry_run,
            "cwd": cwd,
        }
        self.calls.append(record)
        rc = self._per_verb_returncodes.get(verb, self._next_returncode)
        out = self._per_verb_stdouts.get(verb, self._next_stdout)
        argv = ["python", "-m", "dlc_bridge", verb, *(args or [])]
        return subprocess.CompletedProcess(
            args=argv,
            returncode=rc,
            stdout=out,
            stderr=self._next_stderr,
        )


@pytest.fixture()
def invoke_bridge_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[BridgeInvocationRecorder]:
    """Replace :func:`_common.invoke_bridge` with a recording stub."""
    recorder = BridgeInvocationRecorder()
    monkeypatch.setattr(_common, "invoke_bridge", recorder)
    yield recorder


@pytest.fixture()
def tmp_dlc_root(tmp_path: Path) -> Path:
    """Yield a temp ``.dlc/`` root directory for tests that need it."""
    root = tmp_path / ".dlc"
    root.mkdir()
    return root
