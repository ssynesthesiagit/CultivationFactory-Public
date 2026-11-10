"""The table and event feed share the committed sequence from the opening onward."""
import json

from combat import journal_feed
from tests.test_lock2_persistence import table_match, act


def test_manual_opening_and_commit_have_the_feed_cursor(tmp_path):
    _, table, mid = table_match(tmp_path)
    journal = table._match_dir(mid) / "Journal.ndjson"
    assert not journal.exists() or not journal.read_bytes().strip()
    state = table.state(mid, include_menu=True)
    assert state["menu"]["manual"] and state["menu"]["actions"]
    assert state["last_sequence"] == table.events(mid, 0)["last_sequence"] > 0

    assert act(table, mid, "end")["status"] == "COMMITTED"
    after = table.state(mid, include_menu=True)
    assert after["last_sequence"] == table.events(mid, 0)["last_sequence"]
    assert after["last_sequence"] > state["last_sequence"]


def test_cursor_keeps_prior_events_when_last_row_is_empty_and_after_rewrite(tmp_path):
    (tmp_path / "GenesisState.json").write_text(json.dumps(
        {"initial_events": [{"sequence": 3, "event_type": "MATCH_CREATED"}]}))
    journal = tmp_path / "Journal.ndjson"
    journal.write_text(json.dumps({"events": [{"sequence": 5}]}) + "\n" +
                       json.dumps({"events": []}) + "\n")
    assert journal_feed.last_sequence(tmp_path) == journal_feed.journal_since(tmp_path, 0)[2] == 5
    journal.write_text(json.dumps({"events": [{"sequence": 4}]}) + "\n")
    assert journal_feed.last_sequence(tmp_path) == journal_feed.journal_since(tmp_path, 0)[2] == 4
