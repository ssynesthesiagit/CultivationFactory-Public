"""Notes on a finished character (owner 2026-10-17, NOTES1): a free-text notebook kept in the character's table record.

Add, edit and delete round-trip; notes survive a reload of the table store; table_advance.normalized() keeps notes and the
other keys; another character's notes are untouched; a button or name save does not wipe them. Synthetic fixtures only."""

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

        def require_factory_character(self, project_id):
            return None

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
    """Two table clients must not overwrite each other: a note write waits while another write holds this record."""
    import threading

    from combat import tabletop

    service = _service(tmp_path)
    record_lock = service.buttons.write_lock(PID)
    finished = threading.Event()
    attempted = threading.Event()

    class ObservedLock:
        def __enter__(self):
            attempted.set()
            record_lock.acquire()

        def __exit__(self, *exc):
            record_lock.release()

    monkeypatch.setattr(tabletop, "button_write_lock", lambda path: ObservedLock())

    def add():
        service.add_note(PID, "written after the lock")
        finished.set()

    with record_lock:
        writer = threading.Thread(target=add)
        writer.start()
        assert attempted.wait(10)  # the writer has actually reached lock acquisition
        assert not finished.is_set()
    assert finished.wait(10)
    writer.join()
    assert _texts(service.notes(PID)) == ["written after the lock"]


def test_another_characters_write_does_not_queue_behind_this_records(tmp_path):
    """NOTES1F15: one process-wide lock made every character's table writes wait their turn."""
    import threading

    service = _service(tmp_path)
    written = threading.Event()

    def add_other():
        service.add_note(OTHER, "a different character")
        written.set()

    with service.buttons.transaction(PID):  # this character's write is in progress
        writer = threading.Thread(target=add_other)
        writer.start()
        assert written.wait(10)  # the other character never waits for it
    writer.join()
    assert _texts(service.notes(OTHER)) == ["a different character"]
    assert service.notes(PID)["notes"] == []


def test_note_refusals_are_worded_as_notes_not_as_fight_choices():
    """NOTES1F15R: the Notes tab answered an empty note with "Check the selected fighters, map and ability options",
    and a note that was gone with "That fight, map or character is no longer available". A player reading the Notes
    tab is told about the note. Calls the sheet's real error builder (static/tabletop/error-text.js) under node."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed to call the sheet's error builder")
    module = Path(__file__).resolve().parents[1] / "static" / "tabletop" / "error-text.js"
    cases = [{"code": "NOTE_EMPTY", "status": 400}, {"code": "NOTE_TOO_LONG", "status": 400},
             {"code": "NOTE_UNKNOWN", "status": 404}]
    program = (f'import {{playerError}} from {json.dumps(str(module))};\n'
               f'const cases = {json.dumps(cases)};\n'
               'process.stdout.write(JSON.stringify(cases.map((c) => playerError(c))));\n')
    result = subprocess.run([node, "--input-type=module", "-e", program],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    empty, too_long, unknown = json.loads(result.stdout)
    for message in (empty, too_long, unknown):
        assert "note" in message.lower(), message
        assert "fighter" not in message.lower() and "ability" not in message.lower(), message
        assert "The table could not accept those choices" not in message, message
    assert "20 KB" in too_long, too_long
    assert "no longer available. Return to its list" not in unknown, unknown


def test_concurrent_note_adds_all_survive(tmp_path):
    import threading

    service = _service(tmp_path)
    threads = [threading.Thread(target=service.add_note, args=(PID, f"note {i}")) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(_texts(service.notes(PID))) == sorted(f"note {i}" for i in range(20))
