"""Byte-bound JSON-lines tails for CombatService's read-only match views.

All lines are validated on first read or any prefix edit. Only complete,
previously validated prefixes are reused on append; no journal validation,
commit, or replay path uses this presentation cache. Returned rows are copied.
"""
from collections import OrderedDict, deque
from copy import deepcopy
import json
from pathlib import Path
from sys import getsizeof
from threading import RLock

_CACHE = OrderedDict()
_LOCK = RLock()
_BUDGET = 64 * 1024 * 1024


def read_tail(path: Path, limit: int = 12):
    """Match read_jsonl(path)[-limit:], including errors and zero/negative limits.

    Read the full text every time: timestamps, inode reuse and same-size edits
    cannot hide changes. Keep at most four paths and 64 MiB of input text.
    UTF-8 and universal newline handling match Path.read_text's normal behavior.
    """
    if not path.is_file():
        return []
    text = path.read_text(encoding='utf-8')
    if limit <= 0:
        return [json.loads(line) for line in text.splitlines() if line.strip()][-limit:]
    key = str(path.resolve())
    with _LOCK:
        previous = _CACHE.get(key)
        rows = deque(maxlen=limit)
        suffix = text
        if previous is not None:
            old, count, tail = previous
            if count >= limit and old.endswith('\n') and text.startswith(old):
                rows.extend(tail[-limit:])
                suffix = text[len(old):]
        for line in suffix.splitlines():
            if line.strip():
                rows.append(json.loads(line))
        # Never cache a failed parse or a result owned by a caller.
        if getsizeof(text) <= _BUDGET:
            _CACHE[key] = (text, limit, tuple(rows))
            _CACHE.move_to_end(key)
            while len(_CACHE) > 4 or sum(getsizeof(entry[0]) for entry in _CACHE.values()) > _BUDGET:
                _CACHE.popitem(last=False)
        else:
            _CACHE.pop(key, None)
        return deepcopy(list(rows))
