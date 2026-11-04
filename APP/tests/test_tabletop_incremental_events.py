"""The table's event feed reads the journal incrementally (owner 2026-10-03, HUNT107 #1).

``/events`` and the ``events`` block of every act/auto-step answer "what happened
after the sequence I already hold". These tests pin that an incremental read
returns exactly what a full read of the journal returns, that a poll reads only
the records committed since the cursor, and that a reloaded, rewritten,
truncated or replaced journal is read again from the start -- including while
the reader already holds that journal, which is the case a running table is in.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

import pytest

from combat import journal_feed
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import ROOT, act, table_match


def full_parse(match_dir: Path, after: int) -> tuple[list[dict], list[dict], int, int]:
    """The pre-fix read, kept here as the expected answer: every record, every call."""
    events: list[dict] = []
    rolls: list[dict] = []
    last, commits = after, 0
    journal = Path(match_dir) / "Journal.ndjson"
    if not journal.is_file():
        return events, rolls, last, commits
    with journal.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            commits += 1
            fresh = [event for event in row.get("events") or [] if int(event.get("sequence", 0)) > after]
            if not fresh:
                continue
            events.extend(fresh)
            rolls.extend(row.get("rolls") or [])
            last = max(last, max(int(event.get("sequence", 0)) for event in fresh))
    return events, rolls, last, commits


def full_feed(match_dir: Path, after: int) -> tuple[list[dict], list[dict], int, int]:
    """A full read of the opening history and journal, both straight off disk.

    :func:`full_parse` is the journal half of the pre-fix read; a fight also
    serves its opening events, so the oracle covers both.
    """
    directory = Path(match_dir)
    events: list[dict] = []
    rolls: list[dict] = []
    last, commits = after, 0
    if (directory / "GenesisState.json").is_file():
        document = json.loads((directory / "GenesisState.json").read_text(encoding="utf-8"))
        sealed = [event for event in (document.get("initial_events") or [])
                  if int(event["sequence"]) > after]
        if sealed:
            events.extend(event for event in sealed
                          if event["event_type"] not in journal_feed.HIDDEN_LOG_EVENT_TYPES)
            rolls.extend(document.get("initial_rolls") or [])
            last = max(last, max(int(event["sequence"]) for event in sealed))
    journal_events, journal_rolls, journal_last, commits = full_parse(match_dir, after)
    if journal_events:
        events.extend(journal_events)
        rolls.extend(journal_rolls)
        last = max(last, journal_last)
    return events, rolls, last, commits


def journal_sequences(match_dir: Path) -> list[int]:
    """Every event sequence in the journal, read straight off disk."""
    return [int(event.get("sequence", 0)) for row in _records(match_dir) for event in (row.get("events") or [])]


def _records(match_dir: Path) -> list[dict]:
    journal = Path(match_dir) / "Journal.ndjson"
    if not journal.is_file():
        return []
    return [json.loads(line) for line in journal.read_bytes().split(b"\n") if line.strip()]


def records(match_dir: Path) -> int:
    return len(_records(match_dir))


def played(tmp_path: Path, steps: int):
    """A real factory fight played at the table, ``steps`` committed actions in."""
    combat, table, mid = table_match(tmp_path)
    for _ in range(steps):
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def cold(cursor, call):
    """The same request answered with nothing remembered from earlier reads."""
    journal_feed.clear_caches()
    return call(cursor)


# ------------------------------------------------------------------ the table's feed
def test_a_poll_returns_only_the_events_committed_since_the_cursor(tmp_path):
    """The reported bug: every poll re-read the whole fight. It must read the new records."""
    _combat, table, mid = played(tmp_path, 3)
    match_dir = Path(table._match_dir(mid))

    whole = cold(0, lambda after: table.events(mid, after))
    assert whole["events"], "a played fight has a history"
    assert journal_feed.read_stats(match_dir)["records_parsed"] == records(match_dir)

    before = records(match_dir)
    for _ in range(3):
        assert act(table, mid, "end")["status"] == "COMMITTED"
    grew = records(match_dir) - before
    assert grew > 0

    poll = table.events(mid, whole["last_sequence"])
    stats = journal_feed.read_stats(match_dir)  # what the poll itself had to read
    # The answer must be the one a full read of the same request gives, and the feed prints
    # only some of the journal's events (decision plumbing and repeated records are dropped),
    # so the feed is compared against a full read at the same cursor, not against the journal.
    assert poll == cold(whole["last_sequence"], lambda after: table.events(mid, after))
    assert all((row["event_sequence"] or 0) > whole["last_sequence"] for row in poll["events"])
    assert poll["events"], "the three actions after the cursor produced events"
    assert poll["last_sequence"] == table.events(mid, 0)["last_sequence"]
    assert {row["roll_id"] for row in poll["dice"]} <= {row["roll_id"] for row in whole["dice"]}
    # The whole point: the poll decoded the records committed since the cursor, not the fight.
    assert stats["records_parsed"] <= grew, stats
    assert stats["restarted"] is True
    # Fewer bytes than the whole journal. (On a fight this short the fraction is coarse;
    # test_poll_cost_does_not_grow_with_the_fight pins the strong version on a long one.)
    assert stats["record_bytes"] < (match_dir / "Journal.ndjson").stat().st_size


def test_a_poll_costs_nothing_when_the_fight_has_moved_on(tmp_path):
    """The case the hunt measured: a cursor past the end provably returns nothing."""
    _combat, table, mid = played(tmp_path, 4)
    match_dir = Path(table._match_dir(mid))
    table.events(mid, 0)
    spent = table.events(mid, 10 ** 9)
    assert spent["events"] == [] and spent["dice"] == []
    assert spent["last_sequence"] == 10 ** 9
    assert journal_feed.read_stats(match_dir)["records_parsed"] == 0


def test_the_feed_is_identical_whether_it_read_the_fight_or_only_what_is_new(tmp_path):
    """Same request, same answer -- whether the records were read now or remembered."""
    _combat, table, mid = played(tmp_path, 4)
    match_dir = Path(table._match_dir(mid))
    whole = table.events(mid, 0)
    for cursor in (0, 1, 5, whole["last_sequence"] // 2, whole["last_sequence"], 10 ** 9):
        answer = table.events(mid, cursor)          # warm: only what the cursor has not seen
        assert answer == cold(cursor, lambda after: table.events(mid, after))  # a full read again
        # What the table shows is the journal's events after the cursor, less the plumbing
        # events the feed deliberately does not print.
        shown = {row["event_sequence"] for row in answer["events"]}
        assert shown <= {int(event["sequence"]) for event in full_feed(match_dir, cursor)[0]}
        assert shown <= {row["event_sequence"] for row in table.events(mid, 0)["events"]}
        assert answer["last_sequence"] == full_feed(match_dir, cursor)[2]


def test_the_feed_survives_reloading_the_table_from_disk(tmp_path):
    """A reloaded table is a new service over the same saved fight: same feed, still incremental."""
    _combat, table, mid = played(tmp_path, 3)
    before = table.events(mid, 0)
    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reloaded.events(mid, 0) == before

    assert act(reloaded, mid, "end")["status"] == "COMMITTED"
    poll = reloaded.events(mid, before["last_sequence"])
    assert poll["events"] and poll["last_sequence"] > before["last_sequence"]
    assert reloaded.events(mid, poll["last_sequence"])["events"] == []
    assert reloaded.state(mid)["last_sequence"] == poll["last_sequence"]
    # What is remembered lives in the module, so a rebuilt service over the same journal
    # keeps reading incrementally: it is still the same file on the same disk. Only a
    # restart, clear_caches() or dropping the match forgets it.
    match_dir = Path(table._match_dir(mid))
    journal_feed.clear_caches()
    cleared = reloaded.events(mid, poll["last_sequence"])
    assert journal_feed.read_stats(match_dir)["records_parsed"] == records(match_dir), "nothing remembered"
    warm = reloaded.events(mid, poll["last_sequence"])
    assert journal_feed.read_stats(match_dir)["records_parsed"] == 0, "the poll read nothing new"
    assert warm == cleared


# ------------------------------------------------------------------ the read itself
def _synthetic(directory: Path, rows: int, name: str = "Journal.ndjson") -> None:
    with (directory / name).open("wb") as handle:
        for index in range(rows):
            first = index * 2 + 1
            events = [] if index % 17 == 0 else [
                {"sequence": first, "event_type": "DAMAGE_COMMITTED", "actor_id": "a"},
                {"sequence": first + 1, "event_type": "ATTACK_ROLLED", "actor_id": "a"}]
            handle.write(json.dumps({"record_sequence": index + 1, "events": events,
                                     "rolls": [{"roll_id": f"r{index}", "total": index}]},
                                    separators=(",", ":")).encode() + b"\n")
            if index == rows // 3:
                handle.write(b"\n")  # a hand-edited journal can carry a blank line


def _append(directory: Path, first_index: int, count: int, name: str = "Journal.ndjson") -> None:
    """Commit ``count`` more records of the same shape :func:`_synthetic` writes."""
    with (directory / name).open("ab") as handle:
        for index in range(first_index, first_index + count):
            first = index * 2 + 1
            handle.write(json.dumps({"record_sequence": index + 1, "events": [
                {"sequence": first, "event_type": "DAMAGE_COMMITTED"},
                {"sequence": first + 1, "event_type": "ATTACK_ROLLED"}], "rolls": []},
                separators=(",", ":")).encode() + b"\n")


def _marks(directory: Path) -> list:
    return journal_feed.reader_for(directory).frontier.marks


def test_every_cursor_reads_the_same_as_a_full_parse(tmp_path):
    """Cold, warm, repeated and out-of-order cursors all answer like a full parse."""
    _synthetic(tmp_path, 300)
    random.seed(20261003)
    cursors = [0, 1, 2, 3, 31, 32, 33, 300, 301, 599, 600, 10 ** 9]
    cursors += [random.randint(0, 620) for _ in range(40)]
    for cursor in cursors:
        assert journal_feed.journal_since(tmp_path, cursor) == full_parse(tmp_path, cursor), cursor

    journal_feed.clear_caches()
    walk = [0]
    for _ in range(80):  # the page's pattern: poll with what it holds, then reopen and re-read
        walk.append(random.choice([walk[-1], walk[-1] + 1, walk[-1] + 17, max(0, walk[-1] - 30), 0, 10 ** 9]))
    for cursor in walk:
        assert journal_feed.journal_since(tmp_path, cursor) == full_parse(tmp_path, cursor), cursor


def test_a_fight_that_grows_is_read_from_the_cursor_onwards(tmp_path):
    """A poll with the sequence the table holds reads the records committed since, and a
    cursor that lags behind restarts at a sparse checkpoint rather than at byte zero."""
    _synthetic(tmp_path, 200)
    journal_feed.clear_caches()
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    with (tmp_path / "Journal.ndjson").open("ab") as handle:
        for index in range(200, 210):
            first = index * 2 + 1
            handle.write(json.dumps({"record_sequence": index + 1, "events": [
                {"sequence": first, "event_type": "DAMAGE_COMMITTED"},
                {"sequence": first + 1, "event_type": "ATTACK_ROLLED"}], "rolls": []},
                separators=(",", ":")).encode() + b"\n")

    newest = 419  # the last sequence of the first 200 records
    assert journal_feed.journal_since(tmp_path, newest) == full_parse(tmp_path, newest)
    assert journal_feed.read_stats(tmp_path)["records_parsed"] == 10
    for cursor in (400, 300, 1):
        assert journal_feed.journal_since(tmp_path, cursor) == full_parse(tmp_path, cursor)
        # Never the whole file, and never further back than one sparse checkpoint.
        assert journal_feed.read_stats(tmp_path)["records_parsed"] < 210
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    # A full read takes the whole file, except leading book-keeping records that
    # carry no event at all and so cannot be what any cursor is waiting for.
    assert journal_feed.read_stats(tmp_path)["records_parsed"] >= 200


def test_a_rewritten_or_replaced_journal_is_read_again(tmp_path):
    """Anything but the same append-only stream must be read from the start again."""
    _synthetic(tmp_path, 60)
    journal = tmp_path / "Journal.ndjson"
    journal_feed.clear_caches()
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)

    lines = journal.read_bytes().split(b"\n")
    journal.write_bytes(b"\n".join(lines[:-6]) + b"\n")  # a torn tail recovered
    # Nothing is cleared: the reader still holds this journal, and a shorter file is a
    # different journal, so it must be read from the start again.
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    assert journal_feed.read_stats(tmp_path)["records_parsed"] == records(tmp_path)

    kept = journal.read_bytes()
    raw = bytearray(journal.read_bytes())
    at = raw.rfind(b'"event_type":"DAMAGE_COMMITTED"')  # same length, different record
    assert at > 0
    raw[at + 20] = ord("X")
    assert len(raw) == journal.stat().st_size
    journal.write_bytes(bytes(raw))
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)

    journal.unlink()
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    journal.write_bytes(kept)
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)


def test_a_replaced_journal_is_read_again_with_the_cache_still_warm(tmp_path):
    """A different file at the same path is a different journal, with no missing-file read between.

    Unlinking first would let the reader forget the match on its way past, so the cache
    would be empty for the wrong reason. A recovery that swaps a new journal into place
    leaves the path always readable, and only the remembered file's identity can tell.
    """
    _synthetic(tmp_path, 30)
    journal = tmp_path / "Journal.ndjson"
    journal_feed.clear_caches()
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    before = journal.stat().st_ino

    _synthetic(tmp_path, 12, "replacement.ndjson")
    os.replace(tmp_path / "replacement.ndjson", journal)  # as Gate3MatchStore recovery does
    assert journal.stat().st_ino != before
    # The reader still holds the old journal here: nothing was cleared and the path never
    # went missing, so this answer can only be right if the replacement invalidated it.
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    assert journal_feed.read_stats(tmp_path)["records_parsed"] == 12
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)


def test_a_rewrite_on_a_long_fight_is_caught_past_the_thinning_bound(tmp_path):
    """The bytes a remembered boundary is checked by must survive thinning the list.

    A long fight's remembered boundaries are thinned to a bounded list, and the tail
    bytes that catch a rewrite live on the newest boundary only. Deciding to keep them
    by comparing the list's length meant that on the read which crossed the bound the
    list came out shorter than it started, the bytes were dropped, and a same-size
    rewrite of the last record raising an event above the client's cursor was answered
    from the stale checkpoint: the table silently missed an event that a full read of
    the same journal returns. Nothing else in the file changed, so the tail check is the
    only thing that can catch this.
    """
    _synthetic(tmp_path, 520)
    journal = tmp_path / "Journal.ndjson"
    journal_feed.clear_caches()
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    lagging = journal_feed.journal_since(tmp_path, 0)[2]

    # Commit records one at a time, as a fight does, until the read that follows crosses
    # the bound and the published list is thinned as it is published.
    written = 520
    while len(_marks(tmp_path)) + 1 <= journal_feed._MAX_MARKS:
        _append(tmp_path, written, 1)
        written += 1
        assert journal_feed.journal_since(tmp_path, lagging) == full_parse(tmp_path, lagging)
    _append(tmp_path, written, 1)
    written += 1
    assert journal_feed.journal_since(tmp_path, lagging) == full_parse(tmp_path, lagging)
    # Proof that this read really thinned the remembered boundaries.
    assert len(_marks(tmp_path)) < written, "this read was meant to thin the remembered boundaries"

    # Rewrite the last record in place: the same file, the same length, the same inode,
    # but its first event now carries a sequence above the cursor the client is holding.
    # The cursor is what a table polls with, read off disk so that the rewrite follows the
    # crossing poll directly -- a reopen in between would re-record the boundary.
    cursor = max(journal_sequences(tmp_path))
    raised = 9999
    digits = str(2 * (written - 1) + 1).encode()
    assert len(str(raised)) == len(digits)
    size, inode = journal.stat().st_size, journal.stat().st_ino
    at = journal.read_bytes().rfind(b'"sequence":' + digits)
    assert at > 0 and at + 11 + len(digits) <= size
    with journal.open("r+b") as handle:
        handle.seek(at + 11)
        handle.write(str(raised).encode())
    assert journal.stat().st_size == size, "a same-size rewrite is the hard case"
    assert journal.stat().st_ino == inode

    expected = full_parse(tmp_path, cursor)
    assert [int(event["sequence"]) for event in expected[0]] == [raised], \
        "the rewrite must put one event above the cursor, or the test proves nothing"
    assert journal_feed.journal_since(tmp_path, cursor) == expected
    assert _marks(tmp_path)[-1].tail, "the newest boundary must keep the bytes it is checked by"
    # And the same holds for a reader whose cursor sits below the rewritten record.
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)


def test_a_parse_failure_publishes_no_boundary(tmp_path):
    """A half-written record must leave the last good boundary remembered, not a newer one.

    Publishing the boundaries a read parsed before it raised would leave the reader
    trusting bytes it never checked the tail of, which is how a rewritten record gets
    served from a checkpoint that was never validated.
    """
    _synthetic(tmp_path, 20)
    journal_feed.clear_caches()
    journal = tmp_path / "Journal.ndjson"
    journal_feed.journal_since(tmp_path, 0)
    good = _marks(tmp_path)[-1]

    written = journal.read_bytes()
    journal.write_bytes(written + b'{"record_sequence":21,"events":[{"sequence":41')
    for _ in range(2):
        with pytest.raises(ValueError):
            journal_feed.journal_since(tmp_path, 0)
    assert _marks(tmp_path)[-1] == good, "a refused read must not move the remembered boundary"
    assert _marks(tmp_path)[-1].tail, "and must leave the remembered one still checked"

    journal.write_bytes(written + json.dumps(
        {"record_sequence": 21, "events": [{"sequence": 41, "event_type": "DAMAGE_COMMITTED"}], "rolls": []},
        separators=(",", ":")).encode() + b"\n")
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    assert _marks(tmp_path)[-1].tail


def test_opening_history_uses_the_same_cursor_and_ignores_retired_receipt(tmp_path):
    """Opening events stream through the journal cursor and hide bookkeeping.

    An old compatibility receipt must not change which opening events are visible.
    Repeated reads and cursor filtering must return the same events and rolls.
    """
    _synthetic(tmp_path, 10)
    (tmp_path / "SavedFightCompatibility.json").write_text(json.dumps(
        {"obsolete": True}), encoding="utf-8")
    (tmp_path / "GenesisState.json").write_text(json.dumps({
        "initial_events": [{"sequence": 1, "event_type": "MATCH_CREATED", "payload": {"name": "Opening"}},
                           {"sequence": 2, "event_type": "INITIATIVE_ROLLED",
                            "payload": {"log": "Rolled initiative."}}],
        "initial_rolls": [{"roll_id": "genesis-1", "total": 12}]}), encoding="utf-8")
    journal_feed.clear_caches()

    def sealed(after: int) -> list[int]:
        return [int(event["sequence"]) for event in journal_feed.retained_history(tmp_path)[0]]

    assert sealed(0) == [1, 2]
    events, rolls, last, commits = journal_feed.journal_since(tmp_path, 0)
    assert [int(event["sequence"]) for event in events] == [2] + journal_sequences(tmp_path)
    assert [roll["roll_id"] for roll in rolls][0] == "genesis-1"
    assert [roll["roll_id"] for roll in rolls][1:] == [roll["roll_id"] for roll in full_parse(tmp_path, 0)[1]]
    assert last == max(journal_sequences(tmp_path))
    assert commits == records(tmp_path)

    # The page's own pattern: hold the newest sequence, then ask again.
    assert journal_feed.journal_since(tmp_path, last) == ([], [], last, records(tmp_path))
    for cursor in (0, 1, 2, last, last + 1, 10 ** 9):
        assert journal_feed.journal_since(tmp_path, cursor) == full_feed(tmp_path, cursor), cursor
    # A fresh fight has no sealed history, and must not pick any up from a neighbour.
    other = tmp_path / "other"
    other.mkdir()
    _synthetic(other, 4)
    assert journal_feed.retained_history(other) == ([], [])
    assert journal_feed.journal_since(other, 0) == full_feed(other, 0)


def test_a_torn_record_is_never_remembered(tmp_path):
    """A half-written record is read (and refused) as before, then read again once completed."""
    _synthetic(tmp_path, 20)
    journal_feed.clear_caches()
    journal = tmp_path / "Journal.ndjson"
    written = journal.read_bytes()
    journal.write_bytes(written + b'{"record_sequence":21,"events":[{"sequence":41')
    for _ in range(2):
        with pytest.raises(ValueError):
            journal_feed.journal_since(tmp_path, 0)
    journal.write_bytes(written + json.dumps(
        {"record_sequence": 21, "events": [{"sequence": 41, "event_type": "DAMAGE_COMMITTED"}], "rolls": []},
        separators=(",", ":")).encode() + b"\n")
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)


def test_large_cold_read_idle_and_append_keep_bounded_checkpoints(tmp_path):
    """A reopened long fight must bound idle work as well as decoded records."""
    written = 20_000
    _synthetic(tmp_path, written)
    journal_feed.clear_caches()
    assert journal_feed.journal_since(tmp_path, 0) == full_parse(tmp_path, 0)
    cursor = 2 * written
    for appended in (0, 1, 700):
        if appended:
            _append(tmp_path, written, appended)
            written += appended
        assert journal_feed.journal_since(tmp_path, cursor) == full_parse(tmp_path, cursor)
        assert journal_feed.read_stats(tmp_path)["records_parsed"] == appended
        marks = _marks(tmp_path)
        assert len(marks) <= journal_feed._MAX_MARKS
        assert marks[0] == journal_feed.ORIGIN
        assert marks[-1].rows == written
        assert marks[-1].tail == (tmp_path / "Journal.ndjson").read_bytes()[-journal_feed._TAIL_BYTES:]
        cursor = 2 * written
        assert journal_feed.journal_since(tmp_path, cursor) == full_parse(tmp_path, cursor)
        assert journal_feed.read_stats(tmp_path)["records_parsed"] == 0
        assert _marks(tmp_path) == marks
    # Sparse checkpoints still return every unseen event for a reopened/lagging page.
    for cursor in (0, 2001, 39_999):
        assert journal_feed.journal_since(tmp_path, cursor) == full_parse(tmp_path, cursor)
        assert len(_marks(tmp_path)) <= journal_feed._MAX_MARKS


def test_poll_cost_does_not_grow_with_the_fight(tmp_path):
    """The cost a long fight used to pay on every poll: a full read that never shrinks."""
    _synthetic(tmp_path, 4000)
    journal_feed.clear_caches()
    cursor = journal_feed.journal_since(tmp_path, 0)[2]
    with (tmp_path / "Journal.ndjson").open("ab") as handle:
        for index in range(4000, 4004):
            first = index * 2 + 1
            handle.write(json.dumps({"record_sequence": index + 1, "events": [
                {"sequence": first, "event_type": "DAMAGE_COMMITTED"},
                {"sequence": first + 1, "event_type": "ATTACK_ROLLED"}], "rolls": []},
                separators=(",", ":")).encode() + b"\n")

    def cheapest(call):
        best = float("inf")
        for _ in range(5):
            start = time.perf_counter()
            call()
            best = min(best, time.perf_counter() - start)
        return best

    whole = cheapest(lambda: full_parse(tmp_path, 0))
    journal_feed.clear_caches()
    journal_feed.journal_since(tmp_path, 0)  # remember the fight, as a running table does
    poll = cheapest(lambda: journal_feed.journal_since(tmp_path, cursor))
    assert poll < whole / 20, f"a poll cost {poll:.6f}s against a full read of {whole:.6f}s"
    assert journal_feed.read_stats(tmp_path)["records_parsed"] == 4
