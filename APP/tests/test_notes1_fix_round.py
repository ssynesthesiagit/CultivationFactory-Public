"""NOTES1 review fixes (fix/char-notes-1): a note written after a level or a Primary Method change must not block its Undo,
Undo must keep every note as it is now, and the advancement writers must wait for the table write lock.

Synthetic fixtures only (grow5_support builds a made-up character in tmp_path)."""

import threading

import pytest

from combat import table_advance, table_method
from combat.tabletop import BUTTON_WRITE_LOCK
from combat.tabletop_service import TabletopService

from tests.grow5_support import PID, choices, service


def _texts(s):
    return [row["text"] for row in s.notes(PID)["notes"]]


def test_note_written_after_a_level_does_not_block_its_undo(tmp_path):
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    s.add_note(PID, "Written after level 2")
    s.edit_note(PID, s.notes(PID)["notes"][0]["id"], "Edited after level 2")
    s.add_note(PID, "Second note")

    s.undo_level(PID)  # must not refuse: notes change no rules

    assert s.buttons.get(PID)["advancement"]["levels"] == []
    assert _texts(s) == ["Edited after level 2", "Second note"]


def test_undo_level_does_not_bring_back_a_deleted_note(tmp_path):
    s = service(tmp_path)
    s.add_note(PID, "Old note")
    s.level_up(PID, choices(s.advancement(PID)))  # the snapshot taken here holds "Old note"
    note_id = s.notes(PID)["notes"][0]["id"]
    s.delete_note(PID, note_id)

    s.undo_level(PID)

    assert _texts(s) == []  # the deletion survives the undo


def test_overlay_key_ignores_notes_but_not_rules():
    base = table_advance.empty()
    with_note = {**base, "notes": [{"id": "a" * 32, "text": "hi", "created": "x", "updated": "x"}]}
    assert table_advance.overlay_key(base) == table_advance.overlay_key(with_note)
    assert table_advance.overlay_key(base) != table_advance.overlay_key({**base, "spheres": [{"sphere_id": "x"}]})


def test_primary_method_undo_keeps_current_notes():
    saved = table_advance.empty()
    saved["method_changes"] = [{"from_method_id": "old", "to_method_id": "new", "before": {"spheres": []}}]
    saved["notes"] = [{"id": "b" * 32, "text": "kept", "created": "x", "updated": "x"}]
    restored = table_method.undo(saved)
    assert restored["notes"] == saved["notes"]
    assert restored["method_changes"] == []


@pytest.mark.parametrize("name", ["level_up", "undo_level", "add_ability", "add_insight", "immortal_art", "forge",
                                  "add_advancement", "remove_advancement"])
def test_advancement_writers_are_serialized(name):
    assert hasattr(getattr(TabletopService, name), "__wrapped__"), f"{name} must be decorated with serialized_write"


@pytest.mark.parametrize("writer", ["level_up", "undo_level"])
def test_level_writers_wait_for_the_table_write_lock(tmp_path, writer):
    s = service(tmp_path)
    payload = choices(s.advancement(PID))
    if writer == "undo_level":
        s.level_up(PID, payload)
    finished = threading.Event()

    def run():
        if writer == "level_up":
            s.level_up(PID, payload)
        else:
            s.undo_level(PID)
        finished.set()

    with BUTTON_WRITE_LOCK:
        thread = threading.Thread(target=run)
        thread.start()
        assert not finished.wait(0.3)  # still waiting for the other table write
    assert finished.wait(30)
    thread.join()
