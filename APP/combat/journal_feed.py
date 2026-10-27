"""Incremental reads of a match's journal for the table's history feed.

Consumers: ``combat.tabletop.journal_since`` -- which serves
``TabletopService.events``, the ``/api/tabletop/matches/<id>/events`` endpoint
and the ``events`` block of every act/auto-step response -- and any other reader
of the same committed rows. This module is a read cache in front of two files,
not saved fight state: it never writes, never keeps an engine, actor or menu,
and holds nothing a reload would need.

**Why.** ``Journal.ndjson`` holds one canonical JSON record per line, appended
and fsynced per committed action, so it only grows. Reading it from byte zero
made every request pay the whole fight: the page polls ``/events`` about every
three seconds with the sequence it already holds, and every table action asks
again, so a long fight got monotonically more expensive to watch -- a call that
provably returns nothing still paid for the full parse (HUNT107 finding 1,
round 24).

**How.** A journal is append-only, so a request only has to read the records its
cursor has not seen. This module remembers, per journal, the byte offset,
record count and highest event sequence of the row boundaries it has parsed,
plus the tail bytes of the record ending at each of them. A request restarts at
the newest boundary whose highest sequence the cursor has already passed and
reads forward, which in the polling case is the append tail. A cursor that lags
behind (a reopened page asking ``after=0``) restarts at a sparse checkpoint
rather than at byte zero, and a full request still returns everything.

**Identical output.** ``journal_since`` returns exactly what a full parse of the
same request returns, in the same order, for the same journal, so no caller can
tell an incremental read from a complete one. That is what lets the page keep
polling the same endpoint unchanged.

**When the cache is dropped.** A remembered prefix is only reused when the file
is provably the same append-only stream: the same inode, at least as many bytes
as were parsed, and the remembered tail bytes still sitting at the remembered
offset. A rewritten, truncated, replaced or deleted journal (a torn record
recovered by ``Gate3MatchStore.scan_journal``, a replaced save, a deleted
match) invalidates and is read again from the start. What is remembered lives in
this module for the life of the process, so a rebuilt ``TabletopService`` keeps
using it (it is still the same journal on the same disk), and only a process
restart, an explicit ``clear_caches`` or dropping one match forgets it. No saved
fight depends on any of this, so old saved fights and replays are unaffected.

Records are returned as the parser produced them and are shared with the caller,
exactly as a full parse's were; consumers read them and format their own copies
(``combat.history_feed.format_history_feed`` does), so nothing here hands out a
record it might later change.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JOURNAL_NAME = "Journal.ndjson"
GENESIS_NAME = "GenesisState.json"
# Opening bookkeeping is hidden; costs and rule riders remain visible.
HIDDEN_LOG_EVENT_TYPES = frozenset({
    "REACTION_WINDOW_OPENED", "INTENT_ACCEPTED", "TURN_ENDED", "MATCH_CREATED",
})

# Bytes of a record's tail kept to notice a rewritten journal, how many row
# boundaries are remembered per journal, and how many journals and sealed
# histories are remembered at all. All are read-cache limits: exceeding one costs
# a slower read, never a different answer.
_TAIL_BYTES = 128
_MAX_MARKS = 512
_TRACKED_JOURNALS = 64
_TRACKED_GENESISES = 2
_GENESIS_EVENT_LIMIT = 50_000


@dataclass(frozen=True)
class RowMark:
    """One parsed row boundary of a journal.

    ``rows`` counts the non-blank records before it, ``offset`` is the byte just
    past its last record, ``high`` the highest event sequence among those records
    (0 when they carry none) and ``tail`` the last bytes of the record ending
    there. ``tail`` is kept on the newest boundary only, where it lets the next
    request check that the bytes before ``offset`` are still the ones that were
    parsed; it is empty everywhere else and on the start of a file.
    """

    rows: int
    offset: int
    high: int
    tail: bytes


ORIGIN = RowMark(0, 0, 0, b"")


@dataclass
class Frontier:
    """Every row boundary of one journal that has been parsed so far, ascending.

    A cursor restarts at the newest boundary it has already read, so a poll costs
    the records committed since. The list is bounded: the recent history stays
    exact and the older half is thinned, which only affects a cursor that has
    fallen a long way behind (a reopened page), never the one a running table
    polls with.
    """

    inode: int
    marks: list[RowMark] = field(default_factory=lambda: [ORIGIN])

    def restart(self, after: int) -> RowMark:
        """The newest boundary whose highest sequence the cursor has already seen.

        Reading from here can only skip records holding nothing new, because
        every event in them is at or below the cursor. A cursor below them all
        starts at the beginning of the file.
        """
        chosen = ORIGIN
        for mark in self.marks:
            if mark.high <= after:
                chosen = mark
        return chosen


class JournalReader:
    """Incremental reader for one match's journal. See the module docstring."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.frontier: Frontier | None = None
        self.records_parsed = 0
        self.record_bytes = 0
        self.restarted = False

    def read(self, after_sequence: int, *, seen_sequences=()) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
        """(events, rolls, last event sequence, commit count) committed after the cursor.

        Identical to a full parse of the same journal, whatever earlier calls
        happened to remember about it.
        """
        after = int(after_sequence)
        seen = set(seen_sequences)
        events: list[dict[str, Any]] = []
        rolls: list[dict[str, Any]] = []
        self.records_parsed, self.record_bytes, self.restarted = 0, 0, False
        try:
            stream = self.path.open("rb")
        except OSError:  # a fight that has not committed yet, or a deleted match
            self.forget()
            return events, rolls, after, 0
        with stream:
            front = self._trusted(stream)
            start = front.restart(after) if front is not None else ORIGIN
            self.restarted = front is not None and start.rows > 0
            # Boundaries the read starts behind are still valid to restart from later.
            marks = [mark for mark in front.marks if mark.rows <= start.rows] if front is not None else [ORIGIN]
            rows, high, position, last_tail = start.rows, start.high, start.offset, b""
            # Whether this read completed a record boundary, which is what decides if there
            # is a newest one to validate the next read against. It is deliberately not a
            # length comparison: thinning the older half of the list below can leave it
            # shorter than it started, and a rewrite check that came and went with the list
            # length would be off on exactly the long fights that need it.
            advanced = False
            stream.seek(start.offset)
            while True:
                line = stream.readline()
                if not line:
                    break
                position += len(line)
                if not line.strip():
                    continue
                rows += 1
                self.records_parsed += 1
                self.record_bytes += len(line)
                row = json.loads(line)
                fresh, row_high = [], 0
                for event in row.get("events") or []:
                    sequence = int(event.get("sequence", 0))
                    row_high = max(row_high, sequence)
                    if sequence > after and sequence not in seen:
                        fresh.append(event)
                        seen.add(sequence)
                high = max(high, row_high)
                if fresh:
                    events.extend(fresh)
                    rolls.extend(row.get("rolls") or [])
                # A record still being written is read for this request, the way
                # a full parse would, but not remembered: its bytes may still grow.
                if line.endswith(b"\n"):
                    marks.append(RowMark(rows, position, high, b""))
                    # Bound the unpublished list even on a large cold read. Keep
                    # origin and recent boundaries; sparse older checkpoints only
                    # affect how much a lagging cursor must re-read.
                    if len(marks) > _MAX_MARKS:
                        marks[:_MAX_MARKS // 2] = marks[:_MAX_MARKS // 2:2]
                    last_tail = line[-_TAIL_BYTES:]
                    advanced = True
            # The boundaries parsed above are published only here, and only complete: a
            # parse that raised on a half-written record leaves the previously published
            # prefix exactly as it was, so nothing unvalidated is ever remembered.
            if advanced:
                newest = marks[-1]  # only the newest boundary keeps the tail it is checked by
                marks[-1] = RowMark(newest.rows, newest.offset, newest.high, last_tail)
                self.frontier = Frontier(os.fstat(stream.fileno()).st_ino, marks)
        return events, rolls, max(after, high), rows

    def forget(self) -> None:
        """Stop trusting this journal; the next read starts from byte zero."""
        self.frontier = None

    def _trusted(self, stream) -> Frontier | None:
        """The remembered prefix, when this file is provably the same stream.

        The same inode, no shorter than what was parsed, and the remembered tail
        still at the remembered offset. Anything else is a different journal, so
        it is read again from the start.
        """
        current = self.frontier
        if current is None:
            return None
        newest = current.marks[-1]
        stat = os.fstat(stream.fileno())
        if current.inode != stat.st_ino or stat.st_size < newest.offset:
            return None
        if newest.tail:
            stream.seek(newest.offset - len(newest.tail))
            if stream.read(len(newest.tail)) != newest.tail:
                return None
        return current


_JOURNALS: "OrderedDict[str, JournalReader]" = OrderedDict()
_GENESIS: "OrderedDict[str, tuple[int, int, list[dict[str, Any]], list[dict[str, Any]]]]" = OrderedDict()


def reader_for(match_dir: Path) -> JournalReader:
    """The reader remembered for one match, evicting the oldest when full."""
    key = str(match_dir)
    found = _JOURNALS.get(key)
    if found is None:
        found = JournalReader(Path(match_dir) / JOURNAL_NAME)
    else:
        _JOURNALS.move_to_end(key)
    _JOURNALS[key] = found
    while len(_JOURNALS) > _TRACKED_JOURNALS:
        _JOURNALS.popitem(last=False)
    return found


def forget(match_dir: Path) -> None:
    """Drop what is remembered about one match, its journal and its genesis."""
    key = str(match_dir)
    _JOURNALS.pop(key, None)
    _GENESIS.pop(key, None)


def clear_caches() -> None:
    """Forget every journal and genesis; the next read starts from disk again."""
    _JOURNALS.clear()
    _GENESIS.clear()


def read_stats(match_dir: Path) -> dict[str, Any]:
    """What the last read of one match's journal had to touch.

    ``records_parsed`` and ``record_bytes`` count the journal records that read
    decoded, ``restarted`` says it began part-way along a journal it had already
    parsed, and ``remembered_rows`` is how many records earlier reads had
    already covered. Used by the table history-feed tests to show an incremental
    poll reads only the records appended since the cursor.
    """
    found = _JOURNALS.get(str(match_dir))
    if found is None or found.frontier is None:
        return {"records_parsed": 0, "record_bytes": 0, "restarted": False, "remembered_rows": 0}
    return {"records_parsed": found.records_parsed, "record_bytes": found.record_bytes,
            "restarted": found.restarted, "remembered_rows": found.frontier.marks[-1].rows}


def retained_history(match_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A fight's sealed opening/history: the events and rolls in its genesis.

    ``GenesisState.json`` is written when the match is created and its integrity
    is checked on reload. Its parse can be remembered against the file's identity
    and size, avoiding a complete opening-history read on every poll.
    """
    directory = Path(match_dir)
    key = str(directory)
    genesis = directory / GENESIS_NAME
    try:
        stat = genesis.stat()
    except OSError:
        _GENESIS.pop(key, None)
        return [], []
    remembered = _GENESIS.get(key)
    if remembered is not None and remembered[0] == stat.st_ino and remembered[1] == stat.st_size:
        _GENESIS.move_to_end(key)
        return remembered[2], remembered[3]
    document = json.loads(genesis.read_text(encoding="utf-8"))
    events = list(document.get("initial_events") or [])
    rolls = list(document.get("initial_rolls") or [])
    if len(events) <= _GENESIS_EVENT_LIMIT:  # a bounded read cache, never a reason to answer differently
        _GENESIS[key] = (stat.st_ino, stat.st_size, events, rolls)
        _GENESIS.move_to_end(key)
        while len(_GENESIS) > _TRACKED_GENESISES:
            _GENESIS.popitem(last=False)
    return events, rolls


def journal_since(match_dir: Path, after_sequence: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    """(events, rolls, last event sequence, commit count) committed after ``after_sequence``."""
    after = int(after_sequence)
    events: list[dict[str, Any]] = []
    rolls: list[dict[str, Any]] = []
    last = after
    # Every fight stores its opening in genesis. Advance over hidden bookkeeping
    # while preserving the same cursor and deduplication as the LIVE full reader.
    retained, retained_rolls = retained_history(match_dir)
    fresh = [event for event in retained if int(event["sequence"]) > after]
    if fresh:
        events.extend(event for event in fresh
                      if event.get("event_type") not in HIDDEN_LOG_EVENT_TYPES)
        rolls.extend(retained_rolls)
        last = max(last, max(int(event["sequence"]) for event in fresh))
    new_events, new_rolls, journal_last, commits = reader_for(match_dir).read(
        after, seen_sequences=(int(event["sequence"]) for event in fresh))
    if new_events:
        events.extend(new_events)
        rolls.extend(new_rolls)
        last = max(last, journal_last)
    return events, rolls, last, commits
