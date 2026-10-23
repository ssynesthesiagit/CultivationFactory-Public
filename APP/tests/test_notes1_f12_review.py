"""F11 review regressions: notebooks cannot alter rules, Undo restores a row,
and every table writer shares one reentrant thread/process transaction.

Only synthetic characters, local temporary files, and a fake DOM; no servers.
"""

import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import TabletopNoteRequest
from combat import table_advance
from combat.tabletop import ButtonStore, TabletopError
from tests.test_notes1_character_notes import PID, _service

ROOT = Path(__file__).resolve().parents[1]


def _rules_bytes(service):
    advancement = service.buttons.get(PID)["advancement"]
    return json.dumps({k: v for k, v in advancement.items() if k != "notes"},
                      ensure_ascii=False).encode("utf-8")


def test_note_crud_never_normalizes_rich_advancement_rows(tmp_path):
    service = _service(tmp_path)
    rich = table_advance.empty()
    rich.update(
        spheres=[{"sphere_id": "synthetic.water", "gm": False, "at": "2026-01-01"}],
        talents=[{"talent_id": "synthetic.ripple", "choices": {"mode": "gentle"}}],
        forged=[{"design": {"name": "Training form", "steps": [1, 2]}}],
        manuals=[{"manual_id": "synthetic.manual", "read": True}],
        abilities=[{"type": "ability", "changes": {"STR": 1}, "reason": "level_increase",
                    "cl": 4, "note": "earned", "at": "2026-01-02", "gm": False,
                    "receipt": {"source": "synthetic.level.4"}}],
        levels=[{"cl": 4, "before": {"abilities": []}, "after_key": "saved-key",
                 "choices": {"talent_ids": ["synthetic.ripple"]}}],
        method_changes=[{"from_method_id": "METHOD-002", "to_method_id": "METHOD-004",
                         "before": {"levels": [{"cl": 3}]}, "after_key": "method-key"}],
    )
    # Seed exact stored rows, including receipt metadata normalization does not own.
    service.buttons.root.mkdir(parents=True, exist_ok=True)
    service.buttons._path(PID).write_text(json.dumps({"advancement": rich, "display_name": "Kept"}))
    before = _rules_bytes(service)

    service.add_note(PID, "First")
    assert _rules_bytes(service) == before
    note_id = service.notes(PID)["notes"][0]["id"]
    service.edit_note(PID, note_id, "Edited")
    assert _rules_bytes(service) == before
    service.delete_note(PID, note_id)
    assert _rules_bytes(service) == before
    reloaded = _service(tmp_path)
    reloaded.restore_note(PID, note_id)
    assert _rules_bytes(reloaded) == before
    assert reloaded.buttons.get(PID)["display_name"] == "Kept"


def test_delete_undo_preserves_original_row_and_creation_order_across_reload(tmp_path, monkeypatch):
    ticks = iter(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"])
    monkeypatch.setattr(table_advance, "now", lambda: next(ticks))
    service = _service(tmp_path)
    for text in ["First", "Middle", "Last"]:
        service.add_note(PID, text)
    note_id = service.notes(PID)["notes"][1]["id"]
    service.edit_note(PID, note_id, "Middle edited")
    original = deepcopy(service.notes(PID)["notes"])
    service.delete_note(PID, note_id)
    # An unrelated table save and another add must not destroy Undo.
    service.buttons.save(PID, {}, set())
    service.add_note(PID, "Newer")
    reloaded = _service(tmp_path)
    restored = reloaded.restore_note(PID, note_id)["notes"]
    assert restored[:3] == original
    assert restored[3]["text"] == "Newer"
    assert "notes_undo" not in reloaded.buttons.get(PID)
    with pytest.raises(TabletopError):
        reloaded.restore_note(PID, note_id)


def test_add_request_cannot_supply_a_note_identity():
    with pytest.raises(ValidationError):
        TabletopNoteRequest(text="Spoofed", id="a" * 32)


def test_restore_cannot_invent_a_deleted_note(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(TabletopError, match="no longer available"):
        service.restore_note(PID, "a" * 32)
    assert service.notes(PID)["notes"] == []


def test_primary_method_service_undo_retains_notes(tmp_path):
    from tests.test_grow5b_method import start, payload, PID as method_pid

    service = start(tmp_path)
    service.change_method(method_pid, payload(save=True))
    service.add_note(method_pid, "Written after changing Method")
    original = deepcopy(service.notes(method_pid)["notes"])
    service.undo_method(method_pid)
    assert service.notes(method_pid)["notes"] == original
    assert service.buttons.get(method_pid)["advancement"]["method_changes"] == []
    assert service.combat._factory_owner_sheet(method_pid)["method"]["record_id"] == "METHOD-002"


def test_note_service_and_store_use_the_same_nested_transaction(tmp_path, monkeypatch):
    service = _service(tmp_path)
    entered = []
    transaction = ButtonStore.transaction

    @contextmanager
    def observed(store, project_id):
        entered.append(project_id)
        with transaction(store, project_id):
            yield

    monkeypatch.setattr(ButtonStore, "transaction", observed)
    service.add_note(PID, "Saved once, inside one reentrant file lock")
    assert entered == [PID, PID]  # service validation + store write


def test_table_transaction_excludes_a_second_process(tmp_path):
    """No assumption about worker count: another process must obey the same lock."""
    store = ButtonStore(tmp_path / "tabletop_buttons")
    script = """
import fcntl, sys
from pathlib import Path
from combat.tabletop import ButtonStore
store = ButtonStore(Path(sys.argv[1]))
path = store._path(sys.argv[2]).with_suffix(".transaction.lock")
with path.open("a") as stream:
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("locked")
    else:
        raise AssertionError("the parent's table transaction did not hold the file lock")
"""
    # A decorated writer must hold the file lock, not only BUTTON_WRITE_LOCK.
    # Observe it from inside the write, before it releases its transaction.
    original_get = store.get

    def get(project_id):
        result = subprocess.run([sys.executable, "-c", script, str(store.root), project_id],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "locked"
        return original_get(project_id)

    store.get = get
    store.save_display_name(PID, "Serialized")


def test_notes_editor_counts_utf8_and_refuses_oversize_before_saving():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed to drive notes.js")
    script = """
const handlers = {};
const els = {};
const all = [];
const el = (id) => (els[id] ??= {id, value: "", tagName: "TEXTAREA", textContent: "",
  setCustomValidity(message) { this.validityMessage = message; },
  addEventListener(event, handler) { handlers[event] = handler; }, replaceChildren() {}});
const h = (tag, attrs, ...kids) => { const n = {tag, attrs, kids}; all.push(n); return n; };
const mod = await import(process.argv[1]);
const posts = [];
const note = {id: "a".repeat(32), text: "Original", created: "2026-01-01", updated: "2026-01-01"};
mod.initNotes({$: el, h, projectId: () => "synthetic",
  fetchJson: async (url, options) => {
    if (options) posts.push({url, body: JSON.parse(options.body)});
    return {notes: [note], max_bytes: 20480, token: "fake"};
  }});
await mod.loadNotes();
handlers.input({target: null}); // an edited note can disappear after another client deletes it
const field = el("notes-new");
field.value = "界".repeat(6826) + "aa"; // exactly 20 KB, not 20,480 characters
handlers.input({target: field});
if (field.validityMessage) throw Error("valid UTF-8 boundary rejected");
if (!el("notes-new-size").textContent.startsWith("20480 of 20480")) throw Error("wrong byte count");
field.value += "a";
handlers.input({target: field});
if (!field.validityMessage) throw Error("no size warning while typing");
handlers.click({target: {closest: () => ({id: "notes-add", dataset: {}})}});
await new Promise(resolve => setImmediate(resolve));
if (posts.length) throw Error("oversized text was sent to the server");
if (field.value.length !== 6829) throw Error("oversize draft lost");
handlers.click({target: {closest: () => ({dataset: {noteEdit: "1", noteId: note.id}})}});
const areas = all.filter(n => n.tag === "textarea");
if (areas.length < 2 || areas.some(n => n.attrs.maxlength !== "20480"))
  throw Error("textarea cap does not match the server");
if (!areas.some(n => n.attrs.id === "notes-edit-" + note.id)) throw Error("edit cap not checked");
// Undo must call restore, not add with client-supplied row fields.
handlers.click({target: {closest: () => ({dataset: {noteDelete: "1", noteId: note.id}})}});
await new Promise(resolve => setImmediate(resolve));
handlers.click({target: {closest: () => ({id: "notes-undo", dataset: {}})}});
await new Promise(resolve => setImmediate(resolve));
const restored = posts.at(-1);
if (!restored.url.endsWith("/notes/restore") || JSON.stringify(restored.body) !== JSON.stringify({id: note.id}))
  throw Error("Undo did not use server-stored row");
console.log("UTF-8 editor and restore route OK");
"""
    result = subprocess.run([node, "--input-type=module", "-e", script,
                             (ROOT / "static/tabletop/notes.js").as_uri()],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_notes_test_functions_have_two_blank_lines():
    """Keep the reviewed spacing fix without a new lint dependency."""
    source = (ROOT / "tests/test_notes1_character_notes.py").read_text()
    assert "\n\n\ndef test_note_writes_wait_for_the_table_write_lock" in source
