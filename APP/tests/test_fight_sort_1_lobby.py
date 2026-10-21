"""FIGHTSORT1: the fight lobby lists saved fights by when they were last played, newest first.

Journal and metadata are synthetic (built in the test), so this runs on public CI. The client half runs the
real tabletop.js source in tests/fight_sort_1_lobby.test.mjs.
"""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from combat.gate5_service import CombatService, sort_matches_newest_first

APP = Path(__file__).resolve().parents[1]
OLD_UPDATED, NEWER_JOURNAL, STALE = ("match:" + letter * 24 for letter in "abc")


def test_sort_uses_last_played_at_before_updated_at():
    rows = [
        {"match_id": STALE, "last_played_at": "2026-10-01T00:00:00Z"},
        {"match_id": OLD_UPDATED, "last_played_at": "2026-10-19T05:27:15Z"},
        {"match_id": NEWER_JOURNAL, "last_played_at": "2026-10-19T06:14:00Z", "updated_at": "2026-10-19T05:27:15Z"},
    ]
    assert [row["match_id"] for row in sort_matches_newest_first(rows)] == [NEWER_JOURNAL, OLD_UPDATED, STALE]


def test_list_matches_returns_newest_journal_write_first(tmp_path):
    service = CombatService(APP, tmp_path / "UserData")
    metadata = {
        OLD_UPDATED: {"updated_at": "2026-10-19T06:00:00Z", "created_at": "2026-10-19T05:00:00Z"},
        # Older updated_at than the journal write below: the journal file's time is the activity time.
        NEWER_JOURNAL: {"updated_at": "2026-10-19T05:27:15Z", "created_at": "2026-10-19T05:00:00Z"},
        STALE: {"updated_at": None, "created_at": "2026-10-01T00:00:00Z"},
    }
    for match_id in metadata:
        service._match_dir(match_id).mkdir(parents=True, exist_ok=True)
    journal = service._match_dir(NEWER_JOURNAL) / "Journal.ndjson"
    journal.write_text('{"synthetic": true}\n', encoding="utf-8")
    written = datetime(2026, 10, 19, 6, 14, tzinfo=timezone.utc).timestamp()
    os.utime(journal, (written, written))
    service.persistence.list_matches = lambda: [
        {"match_id": match_id, "status": "ACTIVE"} for match_id in (STALE, OLD_UPDATED, NEWER_JOURNAL)
    ]
    service._read_metadata = lambda match_id, session=None: dict(metadata[match_id])

    rows = service.list_matches()

    assert [row["match_id"] for row in rows] == [NEWER_JOURNAL, OLD_UPDATED, STALE]
    assert [row["last_played_at"] for row in rows] == [
        "2026-10-19T06:14:00Z", "2026-10-19T06:00:00Z", "2026-10-01T00:00:00Z"]


def test_lobby_client_renders_api_order_and_plain_time():
    subprocess.run(["node", str(Path(__file__).with_name("fight_sort_1_lobby.test.mjs"))], check=True, cwd=APP)
