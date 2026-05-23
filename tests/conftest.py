"""Shared pytest fixtures for the DLC bridge test suite.

Established fixtures
--------------------

* :func:`workspace_root` — the worktree root (where ``pyproject.toml`` lives).
* :func:`tmp_workspace` — a per-test ``tmp_path`` with a ``.dlc/`` subdirectory
  already created (matches the layout the bridge expects at runtime).
* :func:`plugin_cache_root_mock` — a ``pytest.MonkeyPatch`` wired to a fake
  plugin-cache fixture under ``tests/fixtures/fake_plugin_cache``. Tests that
  exercise :func:`dlc_bridge.verbs.resolve_skill_path` use this to avoid
  depending on the user's real ``~/.claude/plugins/cache`` directory.

Epic 2 will expand this file with ``claude_mock`` (subprocess monkeypatch),
``git_root_marker``, and richer ``.dlc/`` seed fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

# Root of the worktree (one level up from ``tests/``). Used by fixtures that
# need a stable on-disk reference (the fake plugin cache lives under
# ``tests/fixtures/`` so it is resolved relative to this).
_TESTS_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _TESTS_DIR.parent
_FAKE_PLUGIN_CACHE_ROOT = _TESTS_DIR / "fixtures" / "fake_plugin_cache" / "dlc"


@pytest.fixture(scope="session")
def workspace_root() -> Path:
    """Return the worktree root (where ``pyproject.toml`` lives)."""
    return _WORKSPACE_ROOT


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Yield a per-test temp directory with a ``.dlc/`` subdir pre-created."""
    (tmp_path / ".dlc").mkdir()
    return tmp_path


@pytest.fixture()
def plugin_cache_root_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Point :func:`dlc_bridge.verbs._default_plugin_cache_root` at the fake cache.

    Yields the fake plugin-cache root so tests can introspect it. Restoring
    the original behaviour is handled by ``monkeypatch`` teardown.
    """
    from dlc_bridge import verbs

    monkeypatch.setattr(
        verbs, "_default_plugin_cache_root", lambda: _FAKE_PLUGIN_CACHE_ROOT
    )
    yield _FAKE_PLUGIN_CACHE_ROOT
