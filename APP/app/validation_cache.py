"""Bounded, process-local caches used by creation and portable-package audits.

Only successful results are retained. Keys describe the complete input, not a
claimed revision/hash from that input. File keys include ctime and inode as well
as size/mtime, so replacement or a rewrite with restored mtime is invalidated.
No verification marker is persisted across process restarts.
"""

from collections import OrderedDict
from copy import deepcopy
import hashlib
from pathlib import Path
import stat
import threading
from typing import Any, Callable


class ValidationResultCache:
    """Serialize identical cold reads and isolate returned mutable values."""

    def __init__(self, limit: int = 16):
        self.limit = limit
        self._values: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.RLock()
        self._inflight: dict[Any, threading.Event] = {}

    def get_or_compute(self, key: Any, compute: Callable[[], Any], *, still_current: Callable[[], bool] = lambda: True) -> Any:
        hit = False
        while True:
            with self._lock:
                if key in self._values:
                    self._values.move_to_end(key)
                    cached = self._values[key]
                    hit = True
                    break
                ready = self._inflight.get(key)
                if ready is None:
                    ready = self._inflight[key] = threading.Event()
                    break
            ready.wait()
        if hit:
            return deepcopy(cached)
        try:
            value = compute()
            if still_current():
                isolated = deepcopy(value)
                with self._lock:
                    self._values[key] = isolated
                    while len(self._values) > self.limit:
                        self._values.popitem(last=False)
            return value
        finally:
            with self._lock:
                self._inflight.pop(key).set()

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


def file_fingerprint(path: Path) -> tuple[Any, ...]:
    """Describe the actual file, including missing/non-regular inputs."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return (str(path), None)
    return (str(path), info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


_file_hashes = ValidationResultCache(limit=256)


def file_content_key(path: Path) -> tuple[Any, ...]:
    """Hash once per filesystem identity; never trust an advertised digest."""
    fingerprint = file_fingerprint(path)
    if len(fingerprint) == 2 or not stat.S_ISREG(fingerprint[3]):
        return (fingerprint, None)

    def digest() -> str:
        result = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                result.update(chunk)
        return result.hexdigest()

    return (fingerprint, _file_hashes.get_or_compute(
        fingerprint, digest, still_current=lambda: file_fingerprint(path) == fingerprint,
    ))
