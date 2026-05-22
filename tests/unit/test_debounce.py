"""Tests for :mod:`dlc_bridge.util.debounce` (FR-18 fire-suppression)."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from dlc_bridge.util.debounce import check_debounce, check_debounce_keyed


class TestSimpleDebounce:
    def test_first_call_proceeds(self, tmp_path: Path) -> None:
        lock = tmp_path / "my.lock"
        assert check_debounce(lock_path=lock, window_seconds=60.0) is True
        assert lock.exists()

    def test_second_call_within_window_debounced(self, tmp_path: Path) -> None:
        lock = tmp_path / "my.lock"
        assert check_debounce(lock_path=lock, window_seconds=60.0) is True
        # Immediate re-call must be debounced.
        assert check_debounce(lock_path=lock, window_seconds=60.0) is False

    def test_proceeds_after_window_expires(self, tmp_path: Path) -> None:
        lock = tmp_path / "my.lock"
        assert check_debounce(lock_path=lock, window_seconds=0.1) is True
        # Backdate the lock's mtime past the window.
        past = time.time() - 5.0
        os.utime(lock, (past, past))
        assert check_debounce(lock_path=lock, window_seconds=0.1) is True

    def test_concurrent_only_one_proceeds_then_other_debounces(
        self, tmp_path: Path
    ) -> None:
        """When two threads race on the same lock, the second must see the
        first's mtime and debounce."""
        lock = tmp_path / "my.lock"
        results: list[bool] = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            results.append(check_debounce(lock_path=lock, window_seconds=60.0))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Exactly one True, one False — order non-deterministic.
        assert sorted(results) == [False, True]


class TestKeyedDebounce:
    def test_first_call_proceeds(self, tmp_path: Path) -> None:
        state = tmp_path / "_recent-fires.json"
        result = check_debounce_keyed(
            state_path=state,
            hook_id="on-saved",
            trigger_path="/some/file.md",
            window_seconds=60.0,
        )
        assert result is True
        assert state.exists()

    def test_same_key_within_window_debounced(self, tmp_path: Path) -> None:
        state = tmp_path / "_recent-fires.json"
        check_debounce_keyed(
            state_path=state,
            hook_id="on-saved",
            trigger_path="/some/file.md",
            window_seconds=60.0,
        )
        result = check_debounce_keyed(
            state_path=state,
            hook_id="on-saved",
            trigger_path="/some/file.md",
            window_seconds=60.0,
        )
        assert result is False

    def test_different_key_proceeds(self, tmp_path: Path) -> None:
        state = tmp_path / "_recent-fires.json"
        check_debounce_keyed(
            state_path=state,
            hook_id="on-saved",
            trigger_path="/file-a.md",
            window_seconds=60.0,
        )
        # Different trigger path → different key → proceeds.
        result = check_debounce_keyed(
            state_path=state,
            hook_id="on-saved",
            trigger_path="/file-b.md",
            window_seconds=60.0,
        )
        assert result is True

    def test_gc_drops_old_entries(self, tmp_path: Path) -> None:
        import json

        state = tmp_path / "_recent-fires.json"
        # Seed an ancient entry.
        old_ts = int(time.time()) - 1000  # well over gc_seconds default 300
        state.write_text(
            json.dumps({"stale::path": old_ts}), encoding="utf-8"
        )
        # New unrelated call triggers a write + GC pass.
        check_debounce_keyed(
            state_path=state,
            hook_id="fresh",
            trigger_path="/x",
            window_seconds=60.0,
            gc_seconds=300.0,
        )
        # Stale entry should be gone.
        content = json.loads(state.read_text(encoding="utf-8"))
        assert "stale::path" not in content
        assert "fresh::/x" in content

    def test_malformed_state_starts_fresh(self, tmp_path: Path) -> None:
        state = tmp_path / "_recent-fires.json"
        state.write_text("not json at all", encoding="utf-8")
        result = check_debounce_keyed(
            state_path=state,
            hook_id="on-saved",
            trigger_path="/x.md",
            window_seconds=60.0,
        )
        assert result is True


class TestFailOpen:
    def test_lock_timeout_fails_open(self, tmp_path: Path, capsys) -> None:
        """If filelock.Timeout fires, check_debounce returns True (PROCEED)
        and emits a warning to stderr.

        We provoke this by holding the underlying flock in another thread
        with a very short timeout.
        """
        from filelock import FileLock

        lock = tmp_path / "x.lock"
        flock_path = lock.with_name(lock.name + ".flock")
        held = FileLock(str(flock_path))
        held.acquire()
        try:
            result = check_debounce(
                lock_path=lock,
                window_seconds=60.0,
                timeout_seconds=0.1,
            )
        finally:
            held.release()
        assert result is True
        captured = capsys.readouterr()
        assert "warning" in captured.err
