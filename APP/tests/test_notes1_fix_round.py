"""NOTES1 review fixes (fix/char-notes-1): a note written after a level or a Primary Method change must not block its Undo,
Undo must keep every note as it is now, and the advancement writers must wait for the table write lock.

Synthetic fixtures only (grow5_support builds a made-up character in tmp_path)."""

import threading

import pytest

from combat import table_advance, table_method
from combat.tabletop import TabletopError
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
    # undo() refuses unless the record is still in the state the change left it in (see table_method.apply).
    saved["method_changes"][-1]["after_key"] = table_advance.overlay_key(
        {k: v for k, v in saved.items() if k != "method_changes"})
    saved["notes"] = [{"id": "b" * 32, "text": "kept", "created": "x", "updated": "x"}]
    restored = table_method.undo(saved)
    assert restored["notes"] == saved["notes"]
    assert restored["method_changes"] == []


@pytest.mark.parametrize("name", ["level_up", "undo_level", "add_ability", "add_insight", "immortal_art", "forge",
                                  "add_advancement", "remove_advancement", "change_method", "undo_method",
                                  "acquire_feature"])
def test_advancement_writers_are_serialized(name):
    assert hasattr(getattr(TabletopService, name), "__wrapped__"), f"{name} must be decorated with serialized_write"


@pytest.mark.parametrize("writer", ["level_up", "undo_level"])
def test_level_writers_wait_for_the_table_write_lock(tmp_path, writer, monkeypatch):
    from combat import tabletop

    s = service(tmp_path)
    payload = choices(s.advancement(PID))
    if writer == "undo_level":
        s.level_up(PID, payload)
    record_lock = s.buttons.write_lock(PID)
    finished = threading.Event()
    attempted = threading.Event()

    class ObservedLock:
        def __enter__(self):
            attempted.set()
            record_lock.acquire()

        def __exit__(self, *exc):
            record_lock.release()

    monkeypatch.setattr(tabletop, "button_write_lock", lambda path: ObservedLock())

    def run():
        if writer == "level_up":
            s.level_up(PID, payload)
        else:
            s.undo_level(PID)
        finished.set()

    with record_lock:
        thread = threading.Thread(target=run)
        thread.start()
        assert attempted.wait(10)
        assert not finished.is_set()
    assert finished.wait(30)
    thread.join()


def test_restore_refuses_a_hand_edited_undo_row(tmp_path):
    """NOTES1F15: a corrupted notes_undo must say the note cannot be undone, not crash the request."""
    import json

    s = service(tmp_path)
    s.add_note(PID, "Delete me")
    note_id = s.notes(PID)["notes"][0]["id"]
    s.delete_note(PID, note_id)
    stored = json.loads(s.buttons._path(PID).read_text())
    stored["notes_undo"] = {"note": "not a note row", "index": "first"}
    s.buttons._path(PID).write_text(json.dumps(stored))

    with pytest.raises(TabletopError) as refused:
        s.restore_note(PID, note_id)
    assert refused.value.code == "NOTE_UNKNOWN"
    assert _texts(s) == []


def test_notes_never_compile_the_whole_owner_sheet(tmp_path):
    """NOTES1F15: opening the Notes tab reads this character's table record only, so it must not build the sheet."""

    class Combat:
        userdata_root = tmp_path

        def require_factory_character(self, project_id):
            return None

        def _factory_owner_sheet(self, project_id, **kwargs):
            raise AssertionError("the notes routes must not compile the owner sheet")

    s = TabletopService(None, tmp_path)
    s.combat = Combat()
    s.add_note(PID, "Cheap to open")
    assert _texts(s.notes(PID)) == ["Cheap to open"]


def test_delete_keeps_the_other_drafts_and_a_second_change_waits():
    """notes.js (NOTES1F15): deleting one note keeps another note's unsaved edit draft and the new-note draft,
    and a change started while one is still saving is shown in plain words instead of racing it.

    Drives the real notes.js with a fake DOM and a deferred request (no browser)."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed to drive notes.js")
    module = Path(__file__).resolve().parents[1] / "static/tabletop/notes.js"
    script = """
const els = {};
const handlers = {};
const made = [];
const el = (id) => (els[id] ??= { id, value: "", textContent: "",
  addEventListener(event, handler) { handlers[id + ":" + event] = handler; },
  closest() { return null; }, replaceChildren() {} });
const h = (tag, attrs, ...kids) => { const node = { tag, attrs, kids: kids.flat(Infinity) }; made.push(node); return node; };
const mod = await import(process.argv[1]);
const first = { id: "a".repeat(32), text: "First", created: "2026-01-01", updated: "2026-01-01" };
const second = { id: "b".repeat(32), text: "Second", created: "2026-01-02", updated: "2026-01-02" };
const posts = [];
let release = null;
mod.initNotes({ $: el, h, toast() {}, projectId: () => "pid",
  fetchJson: async (url, options) => {
    if (options) {
      posts.push({ url, body: JSON.parse(options.body) });
      if (url.endsWith("/notes/delete")) return new Promise((resolve) => { release = () => resolve({ notes: [first, second] }); });
    }
    return { notes: [first, second], max_bytes: 20480 };
  } });
await mod.loadNotes();
const click = (button) => handlers["notes-root:click"]({ target: { closest: () => button } });
click({ dataset: { noteEdit: "1", noteId: second.id } });          // start editing the second note
els["notes-edit-" + second.id].value = "Draft kept";               // typed but not saved
els["notes-new"].value = "New note draft";                         // typed but not added
click({ dataset: { noteDelete: "1", noteId: first.id } });         // slow delete of the other note
await new Promise((resolve) => setTimeout(resolve, 10));
click({ id: "notes-add", dataset: {} });                           // a second change while saving
const refused = made.some((node) => node.kids.some((kid) => typeof kid === "string" && kid.includes("Still saving")));
if (!refused) throw Error("a second change went through while one was saving");
release();
await new Promise((resolve) => setTimeout(resolve, 10));
const area = els["notes-edit-" + second.id];
if (!area || area.value !== "Draft kept") throw Error("another note's unsaved draft was lost");
if (els["notes-new"].value !== "New note draft") throw Error("the new-note draft was lost");
const deleted = posts.find((post) => post.url.endsWith("/notes/delete"));
if (JSON.stringify(deleted.body) !== JSON.stringify({ id: first.id, text: "" }))
  throw Error("delete did not send only the note's id");
console.log("drafts kept and the second change refused");
"""
    result = subprocess.run([node, "--input-type=module", "-e", script, module.as_uri()],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_notes_tab_never_hands_null_to_replace_children():
    # Regression (NOTES1F9R): replaceChildren(null) puts the word "null" on the page. Drive the real notes.js render
    # with a fake DOM (no browser) and check that every child passed to replaceChildren is a real node.
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed to drive notes.js")
    module = Path(__file__).resolve().parents[1] / "static/tabletop/notes.js"
    script = """
const calls = [];
const els = {};
const el = (id) => (els[id] ??= { id, value: "", addEventListener() {}, closest() { return null; },
  replaceChildren(...nodes) { calls.push({ id, nodes }); } });
const h = (tag, attrs, ...kids) => ({ tag, attrs, kids: kids.flat(Infinity) });
const mod = await import(process.argv[1]);
const note = { id: "a".repeat(32), text: "hi", created: "2026-01-01T00:00:00Z", updated: "2026-01-01T00:00:00Z" };
mod.initNotes({ $: el, h, toast() {}, projectId: () => "pid",
  fetchJson: async () => ({ notes: [note], max_bytes: 20480 }) });
await mod.loadNotes();
const bad = calls.filter((c) => c.nodes.some((n) => n === null || typeof n !== "object")).map((c) => c.id);
console.log(JSON.stringify({ calls: calls.length, bad }));
"""
    result = subprocess.run([node, "--input-type=module", "-e", script, module.as_uri()],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["calls"] >= 2
    assert report["bad"] == []
