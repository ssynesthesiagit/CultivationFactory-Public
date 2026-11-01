"""Notes on a finished character (owner 2026-10-17, NOTES1): a free-text notebook kept in the character's table record.

Add, edit and delete round-trip; notes survive a reload of the table store; table_advance.normalized() keeps notes and the
other keys; another character's notes are untouched; a button or name save does not wipe them. Synthetic fixtures only."""

import json
from pathlib import Path

import pytest

from combat import table_advance
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

PID = "0badc0de-0000-4000-8000-000000000011"
OTHER = "0badc0de-0000-4000-8000-000000000012"


def _service(tmp_path):
    service = TabletopService(None, tmp_path)

    class Combat:
        userdata_root = tmp_path

        def _factory_owner_sheet(self, project_id):
            return {"identity": {"name": "Test Character", "cultivation_level": 3}, "spheres_and_talents": {}}

    service.combat = Combat()
    return service


def _texts(view):
    return [row["text"] for row in view["notes"]]


def test_add_edit_delete_round_trip(tmp_path):
    service = _service(tmp_path)
    assert service.notes(PID)["notes"] == []

    service.add_note(PID, "  Ask the GM about the Sect's permission  ")
    service.add_note(PID, "Second thought")
    view = service.notes(PID)
    assert _texts(view) == ["Ask the GM about the Sect's permission", "Second thought"]
    first = view["notes"][0]
    assert len(first["id"]) == 32 and first["created"] and first["updated"] == first["created"]

    service.edit_note(PID, first["id"], "Permission granted by the Sect")
    edited = service.notes(PID)["notes"][0]
    assert edited["text"] == "Permission granted by the Sect"
    assert edited["id"] == first["id"] and edited["created"] == first["created"]

    service.delete_note(PID, first["id"])
    assert _texts(service.notes(PID)) == ["Second thought"]


def test_notes_persist_across_reload(tmp_path):
    service = _service(tmp_path)
    service.add_note(PID, "Keep this")
    reloaded = _service(tmp_path)  # a fresh service reads the same table store
    assert _texts(reloaded.notes(PID)) == ["Keep this"]


def test_normalized_keeps_notes_and_other_keys():
    assert "notes" in table_advance.empty()
    document = {"spheres": [{"sphere_id": "tianxia.sphere.magma"}], "talents": [{"talent_id": "T1"}],
                "forged": [], "manuals": [{"manual_id": "M1"}],
                "notes": [{"id": "a" * 32, "text": "kept", "created": "x", "updated": "x"},
                          {"id": "b" * 32},  # no text: dropped
                          "not a note"]}
    out = table_advance.normalized(document)
    assert out["spheres"] == [{"sphere_id": "tianxia.sphere.magma"}]
    assert out["talents"] == [{"talent_id": "T1"}] and out["manuals"] == [{"manual_id": "M1"}]
    assert [row["text"] for row in out["notes"]] == ["kept"]
    assert table_advance.normalized(None)["notes"] == []


def test_other_characters_are_unaffected(tmp_path):
    service = _service(tmp_path)
    service.add_note(PID, "Only for this character")
    assert service.notes(OTHER)["notes"] == []
    assert _texts(service.notes(PID)) == ["Only for this character"]


def test_button_and_name_saves_keep_notes(tmp_path):
    service = _service(tmp_path)
    service.add_note(PID, "Survives other saves")
    service.buttons.save_display_name(PID, "Renamed Hero")
    service.buttons.save(PID, {}, set())
    assert _texts(service.notes(PID)) == ["Survives other saves"]


def test_empty_and_oversized_notes_are_refused(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(TabletopError) as empty:
        service.add_note(PID, "   ")
    assert empty.value.code == "NOTE_EMPTY"
    with pytest.raises(TabletopError) as big:
        service.add_note(PID, "x" * (table_advance.NOTE_MAX_BYTES + 1))
    assert big.value.code == "NOTE_TOO_LONG"
    service.add_note(PID, "x" * table_advance.NOTE_MAX_BYTES)  # exactly the cap is allowed
    assert len(service.notes(PID)["notes"]) == 1


def test_unknown_note_ids_are_refused(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(TabletopError) as edit:
        service.edit_note(PID, "c" * 32, "x")
    assert edit.value.code == "NOTE_UNKNOWN"
    with pytest.raises(TabletopError) as delete:
        service.delete_note(PID, "c" * 32)
    assert delete.value.code == "NOTE_UNKNOWN"


def test_notes_ui_preserves_drafts_and_refreshes_only_undo_bar():
    source = (Path(__file__).parents[1] / "static/tabletop/notes.js").read_text()
    render = source.split("function render() {", 1)[1].split("function noteRow(", 1)[0]
    timer = source.split("function setUndo(note) {", 1)[1].split("function clearUndo(", 1)[0]
    change = source.split("async function change(run, done) {", 1)[1].split("function onClick(", 1)[0]

    assert 'const newDraft = $("notes-new")?.value' in render
    assert "const editDraft = editing ?" in render
    assert '$("notes-new").value = newDraft' in render
    assert '$(`notes-edit-${editing}`).value = editDraft' in render
    assert 'renderUndoBar();' in timer and "render();" not in timer
    assert "Still saving. Please wait" in change


def test_undo_brings_back_the_same_note(tmp_path):
    service = _service(tmp_path)
    service.add_note(PID, "Undo me")
    note = service.notes(PID)["notes"][0]
    service.delete_note(PID, note["id"])
    assert service.notes(PID)["notes"] == []
    service.restore_note(PID, note["id"])
    assert service.notes(PID)["notes"][0]["id"] == note["id"]
    with pytest.raises(TabletopError):
        service.restore_note(PID, note["id"])  # Undo can only restore a deleted row once


def test_note_writes_wait_for_the_table_write_lock(tmp_path, monkeypatch):
    """Two table clients must not overwrite each other: a note write waits while another table write holds the lock."""
    import threading

    from combat.tabletop import BUTTON_WRITE_LOCK

    service = _service(tmp_path)
    finished = threading.Event()
    attempted = threading.Event()

    class ObservedLock:
        def __enter__(self):
            attempted.set()
            BUTTON_WRITE_LOCK.acquire()

        def __exit__(self, *exc):
            BUTTON_WRITE_LOCK.release()

    monkeypatch.setattr("combat.tabletop.BUTTON_WRITE_LOCK", ObservedLock())

    def add():
        service.add_note(PID, "written after the lock")
        finished.set()

    with BUTTON_WRITE_LOCK:
        writer = threading.Thread(target=add)
        writer.start()
        assert attempted.wait(10)  # the writer has actually reached lock acquisition
        assert not finished.is_set()
    assert finished.wait(10)
    writer.join()
    assert _texts(service.notes(PID)) == ["written after the lock"]


def test_concurrent_note_adds_all_survive(tmp_path):
    import threading

    service = _service(tmp_path)
    threads = [threading.Thread(target=service.add_note, args=(PID, f"note {i}")) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(_texts(service.notes(PID))) == sorted(f"note {i}" for i in range(20))
