"""One reentrant JSON-file transaction shared by table and profile writers.

The thread lock queues in-process callers; the file lock excludes other server
processes. Nested writes to the same record reuse the held file lock. Readers
continue to see the last complete atomic publication.
"""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import threading

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_TRANSACTIONS: set[Path] = set()


def write_lock(path: Path) -> threading.RLock:
    """The in-process lock for one record, shared across service instances."""
    path = Path(path).resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.RLock())


@contextmanager
def file_transaction(path: Path):
    """Hold the record's thread and process locks across read-modify-write."""
    path = Path(path).resolve()
    with write_lock(path):
        if path in _TRANSACTIONS:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            _TRANSACTIONS.add(path)
            try:
                yield
            finally:
                _TRANSACTIONS.remove(path)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
