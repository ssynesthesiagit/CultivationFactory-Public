"""Bounded, process-local summaries of fully verified immutable terminal inputs.

Hash file contents, not timestamps or only the journal tail: same-size edits to
an earlier commit, controller record, metadata or summary must invalidate reuse.
The writer lock's transient ownership file is the only excluded input.
"""
import json
import threading
from collections import OrderedDict

from .canonical import sha256_file


def identity(match_dir):
    return tuple((str(path.relative_to(match_dir)), sha256_file(path))
                 for path in sorted(match_dir.rglob("*"))
                 if path.is_file() and path.name != ".writer.lock")


def without_summary(key):
    return tuple(row for row in key if row[0] != "FinalSummary.json")


class TerminalSummaryCache:
    def __init__(self, limit=8):
        self.limit = limit
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def get(self, match_id, key):
        with self.lock:
            entry = self.entries.get(match_id)
            if entry is None or entry[0] != key:
                return None
            self.entries.move_to_end(match_id)
            return json.loads(entry[1])

    def put(self, match_id, key, summary):
        with self.lock:
            self.entries[match_id] = (key, json.dumps(summary))
            self.entries.move_to_end(match_id)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)
