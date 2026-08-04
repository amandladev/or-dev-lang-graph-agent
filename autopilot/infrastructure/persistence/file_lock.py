"""Cross-platform advisory file lock used to serialize Ledger appends
across processes.

Uses only Python standard library facilities: fcntl.flock on POSIX,
msvcrt.locking on Windows. No third-party locking dependency is introduced.
"""

from pathlib import Path
from types import TracebackType

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


class LedgerLock:
    """Advisory, exclusive lock held for the duration of a
    load-modify-write cycle.

    By default the lock blocks until it can be acquired (used for the
    Ledger append cycle, which is expected to be brief). Pass
    `blocking=False` to fail fast instead — e.g. to detect that another
    process already holds a per-workspace run lock — which raises
    `BlockingIOError`/`OSError` immediately rather than waiting.
    """

    def __init__(self, lock_path: str | Path, blocking: bool = True) -> None:
        self._lock_path = Path(lock_path)
        self._fh = None
        self._blocking = blocking

    def __enter__(self) -> "LedgerLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+b")
        try:
            if fcntl is not None:
                flags = fcntl.LOCK_EX if self._blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(self._fh.fileno(), flags)
            elif msvcrt is not None:
                self._fh.seek(0)
                mode = msvcrt.LK_LOCK if self._blocking else msvcrt.LK_NBLCK
                msvcrt.locking(self._fh.fileno(), mode, 1)
            else:
                raise OSError(
                    "No supported file locking mechanism (fcntl/msvcrt) "
                    "available on this platform"
                )
        except Exception:
            self._fh.close()
            self._fh = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            if self._fh is not None:
                if fcntl is not None:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
        return False


def lock_path_for(target_path: str | Path) -> Path:
    """Deterministically derive a lock file path from a target file path.

    Two calls with the same `target_path` always return the same lock path.
    """
    return Path(str(target_path) + ".lock")
