"""Property tests for the cross-platform advisory file lock (LedgerLock).

Feature: safe-persistence-and-config-validation
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.persistence import file_lock
from autopilot.infrastructure.persistence.file_lock import LedgerLock, lock_path_for

path_string_strategy = st.text(min_size=1, max_size=50).filter(
    lambda s: "\x00" not in s
)


class TestLockPathDeterminism:
    """Property 9: Lock path is a deterministic function of the ledger path.

    **Validates: Requirements 3.7**
    """

    @settings(max_examples=100)
    @given(p=path_string_strategy)
    def test_same_path_yields_same_lock_path(self, p):
        assert lock_path_for(p) == lock_path_for(p)

    @settings(max_examples=100)
    @given(p=path_string_strategy, q=path_string_strategy)
    def test_distinct_paths_yield_distinct_lock_paths(self, p, q):
        if p != q:
            assert lock_path_for(p) != lock_path_for(q)


class TestNonBlockingLock:
    """`blocking=False` fails fast instead of waiting, so callers can detect
    that another process already holds the lock (e.g. a per-workspace run
    lock) without hanging.

    **Validates: run-level concurrency guard**
    """

    def test_default_is_blocking(self):
        tmpdir = tempfile.mkdtemp()
        lock_path = Path(tmpdir) / "state.json.lock"

        with LedgerLock(lock_path) as lock:
            assert lock._blocking is True

    def test_non_blocking_second_acquisition_raises_immediately(self):
        if file_lock.fcntl is None:
            pytest.skip("fcntl not available on this platform")

        tmpdir = tempfile.mkdtemp()
        lock_path = Path(tmpdir) / "run.lock"

        with LedgerLock(lock_path, blocking=True):
            with pytest.raises(OSError):
                with LedgerLock(lock_path, blocking=False):
                    pass

    def test_non_blocking_lock_succeeds_when_free(self):
        tmpdir = tempfile.mkdtemp()
        lock_path = Path(tmpdir) / "run.lock"

        with LedgerLock(lock_path, blocking=False):
            pass

    def test_non_blocking_lock_released_and_reacquirable(self):
        if file_lock.fcntl is None:
            pytest.skip("fcntl not available on this platform")

        tmpdir = tempfile.mkdtemp()
        lock_path = Path(tmpdir) / "run.lock"

        with LedgerLock(lock_path, blocking=False):
            pass

        # Now free again — a second non-blocking acquisition must succeed.
        with LedgerLock(lock_path, blocking=False):
            pass


class TestLockOSErrorPreventsAcquisition:
    """Property 8 (raw LedgerLock failure mode): Lock acquisition OS errors
    propagate and never leave a held lock.

    **Validates: Requirements 3.6**
    """

    def test_unsupported_platform_raises_os_error(self):
        tmpdir = tempfile.mkdtemp()
        lock_path = Path(tmpdir) / "ledger.json.lock"

        with patch.object(file_lock, "fcntl", None), patch.object(
            file_lock, "msvcrt", None
        ):
            with pytest.raises(OSError):
                with LedgerLock(lock_path):
                    pass

    def test_flock_failure_raises_and_closes_handle(self):
        tmpdir = tempfile.mkdtemp()
        lock_path = Path(tmpdir) / "ledger.json.lock"

        if file_lock.fcntl is None:
            pytest.skip("fcntl not available on this platform")

        def fake_flock(*args, **kwargs):
            raise OSError("simulated flock failure")

        with patch.object(file_lock.fcntl, "flock", side_effect=fake_flock):
            with pytest.raises(OSError):
                with LedgerLock(lock_path):
                    pass

        # A subsequent normal acquisition should succeed, proving no lingering
        # open file handle or lock state was left behind.
        with LedgerLock(lock_path):
            pass


class TestConcurrentAppendsNeverLoseEntries:
    """Property 5: Concurrent ledger appends never lose entries.

    **Validates: Requirements 3.1, 3.2**
    """

    @settings(max_examples=25, deadline=None)
    @given(n=st.integers(min_value=2, max_value=15))
    def test_concurrent_appends_preserve_all_entries(self, n):
        from concurrent.futures import ThreadPoolExecutor

        from autopilot.domain.entities.ledger_entry import LedgerEntry
        from autopilot.infrastructure.persistence.ledger import Ledger

        tmpdir = tempfile.mkdtemp()
        ledger_path = Path(tmpdir) / "ledger.json"
        ledger = Ledger(ledger_path)

        run_ids = [f"run-{i}" for i in range(n)]

        def do_append(run_id):
            ledger.append(LedgerEntry(run_id=run_id, ticket_id="TEST-1"))

        with ThreadPoolExecutor(max_workers=n) as executor:
            list(executor.map(do_append, run_ids))

        data = ledger.load()
        assert len(data) == n
        assert {r["run_id"] for r in data} == set(run_ids)


class TestLockReleaseOnSuccess:
    """Property 6: Lock is released after a successful append.

    **Validates: Requirements 3.4**
    """

    def test_sequential_appends_complete_without_deadlock(self):
        from autopilot.domain.entities.ledger_entry import LedgerEntry
        from autopilot.infrastructure.persistence.ledger import Ledger

        tmpdir = tempfile.mkdtemp()
        ledger_path = Path(tmpdir) / "ledger.json"
        ledger = Ledger(ledger_path)

        for i in range(10):
            count = ledger.append(LedgerEntry(run_id=f"run-{i}", ticket_id="TEST-1"))
            assert count == i + 1


class TestLockReleaseOnFailure:
    """Property 7: Lock is released after a failed append.

    **Validates: Requirements 3.5**
    """

    def test_lock_released_after_save_failure(self):
        from autopilot.domain.entities.ledger_entry import LedgerEntry
        from autopilot.infrastructure.persistence.ledger import Ledger

        if file_lock.fcntl is None:
            pytest.skip("fcntl not available on this platform")

        tmpdir = tempfile.mkdtemp()
        ledger_path = Path(tmpdir) / "ledger.json"
        ledger = Ledger(ledger_path)

        def fake_save(*args, **kwargs):
            raise RuntimeError("simulated save failure")

        with patch.object(ledger, "save", side_effect=fake_save):
            with pytest.raises(RuntimeError):
                ledger.append(LedgerEntry(run_id="run-1", ticket_id="TEST-1"))

        # Lock must have been released: a non-blocking probe should succeed.
        lock_path = lock_path_for(ledger_path)
        with open(lock_path, "a+b") as fh:
            file_lock.fcntl.flock(
                fh.fileno(), file_lock.fcntl.LOCK_EX | file_lock.fcntl.LOCK_NB
            )
            file_lock.fcntl.flock(fh.fileno(), file_lock.fcntl.LOCK_UN)


class TestLockOSErrorPreventsMutation:
    """Property 8: Lock acquisition/release OS errors prevent any ledger
    mutation.

    **Validates: Requirements 3.6**
    """

    def test_flock_error_during_append_leaves_ledger_unchanged(self):
        from autopilot.domain.entities.ledger_entry import LedgerEntry
        from autopilot.infrastructure.persistence.ledger import Ledger

        if file_lock.fcntl is None:
            pytest.skip("fcntl not available on this platform")

        tmpdir = tempfile.mkdtemp()
        ledger_path = Path(tmpdir) / "ledger.json"
        pre_existing = b'[{"run_id": "existing", "ticket_id": "TEST-0"}]'
        ledger_path.write_bytes(pre_existing)

        ledger = Ledger(ledger_path)

        def fake_flock(*args, **kwargs):
            raise OSError("simulated flock failure")

        with patch.object(file_lock.fcntl, "flock", side_effect=fake_flock):
            with pytest.raises(OSError):
                ledger.append(LedgerEntry(run_id="run-1", ticket_id="TEST-1"))

        assert ledger_path.read_bytes() == pre_existing
