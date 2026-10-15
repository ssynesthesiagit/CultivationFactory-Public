"""Append-only decision records for model seats, written beside the Factory data.

One JSON line per model decision (turn or reaction), or per ranked prompt
response linked by plan_decision_id, for later training and
audit. Writes never raise: a failed record must not change the fight. Set
FACTORY_SEAT_RECORDS=0 to turn recording off. The file rotates to
seat_decisions.jsonl.1 once it reaches the size cap; the previous .1 is replaced.
Up to four match workers share the file, so the size check, rename and append
run under an exclusive lock on seat_decisions.jsonl.lock.
"""
import fcntl
import json
import os
from pathlib import Path

MAX_BYTES = 200 * 1024 * 1024
FILE_NAME = "seat_decisions.jsonl"
LOCK_NAME = FILE_NAME + ".lock"


def enabled():
    return os.environ.get("FACTORY_SEAT_RECORDS", "1") != "0"


def append(data_dir, record, *, max_bytes=MAX_BYTES):
    """Append one record; return False (never raise) if it was not written."""
    if not enabled():
        return False
    try:
        data_dir = Path(data_dir)
        path = data_dir / FILE_NAME
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with (data_dir / LOCK_NAME).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if path.exists() and path.stat().st_size + len(line.encode("utf-8")) > max_bytes:
                    path.replace(path.with_name(FILE_NAME + ".1"))
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        return True
    except (OSError, TypeError, ValueError):
        return False
