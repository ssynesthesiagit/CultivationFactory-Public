// The sheet's Notes tab (owner 2026-10-17, NOTES1): a free-text notebook the player or GM keeps on a character.
// Notes live in the character's table record (combat/table_advance.py "notes"); the server keeps them and
// the sealed install never changes. Add, edit in place, delete (with Undo), and newest-first or oldest-first.

let deps = null;          // {h, $, fetchJson, toast, projectId}
let data = null;          // GET /notes
let newestFirst = true;   // the sort choice is kept while the sheet is open
let editing = null;       // id of the note being edited
let undo = null;          // {note, timer} for the last delete
let busy = false;
let notice = "";          // a plain message shown above the list

export function initNotes(options) {
  deps = options;
  const root = deps.$("notes-root");
  root.addEventListener("click", onClick);
  root.addEventListener("change", onChange);
}

export async function loadNotes() {
  const { $, fetchJson, h } = deps;
  try {
    data = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/notes`);
    render();
  } catch (error) {
    $("notes-root").replaceChildren(h("p", { class: "muted" }, `Could not load the notes: ${error.message}`));
  }
}

async function post(path, body) {
  const session = await deps.fetchJson("/api/session");
  return deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token }, body: JSON.stringify(body),
  });
}

function when(stamp) {
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function sorted(notes) {
  const rows = [...notes];
  return newestFirst ? rows.reverse() : rows;
}

// Runs one change, then reloads the list. Failures are shown in plain words, not as codes.
async function change(run, done) {
  if (busy) {
    notice = "Still saving. Please wait before making another change.";
    render();
    return;
  }
  busy = true;
  try {
    data = await run();
    notice = done || "";
  } catch (error) {
    notice = `That did not save: ${error.message}`;
  } finally {
    busy = false;
    render();
  }
}

function onClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  const id = button.dataset.noteId;
  if (button.id === "notes-add") {
    const text = deps.$("notes-new").value;
    void change(async () => { const next = await post("notes", { text }); deps.$("notes-new").value = ""; return next; }, "Note added.");
  } else if (button.dataset.noteEdit) {
    editing = id; notice = ""; render();
  } else if (button.dataset.noteCancel !== undefined) {
    editing = null; render();
  } else if (button.dataset.noteSave) {
    const text = deps.$(`notes-edit-${id}`)?.value || "";
    void change(async () => { const next = await post("notes/edit", { id, text }); editing = null; return next; }, "Note saved.");
  } else if (button.dataset.noteDelete) {
    const note = (data?.notes || []).find((row) => row.id === id);
    void change(async () => {
      const next = await post("notes/delete", { id, text: "" });
      if (editing === id) editing = null; // keep an unsaved draft in another note
      if (note) setUndo(note);
      return next;
    }, "Note deleted.");
  } else if (button.id === "notes-undo" && undo) {
    const { note } = undo;
    clearUndo();
    void change(async () => post("notes", { text: note.text, id: note.id }), "Note brought back.");
  }
}

function onChange(event) {
  if (event.target.id === "notes-order") {
    newestFirst = event.target.value === "newest";
    render();
  }
}

// Undo lasts a few seconds; after that the delete stands.
function setUndo(note) {
  clearUndo();
  undo = { note, timer: setTimeout(() => { undo = null; renderUndoBar(); }, 8000) };
  renderUndoBar();
}

function clearUndo() {
  if (undo) clearTimeout(undo.timer);
  undo = null;
}

function renderUndoBar() {
  if (!deps || !data) return;
  const { h, $ } = deps;
  // replaceChildren() turns a null argument into the text "null", so pass only real nodes.
  const undoBar = undo ? [h("p", { class: "notes-undo" }, "Note deleted. ",
    h("button", { type: "button", class: "btn", id: "notes-undo" }, "Undo"))] : [];
  $("notes-undo-container")?.replaceChildren(...undoBar);
}

function render() {
  const { h, $ } = deps;
  if (!data) return;
  const newDraft = $("notes-new")?.value;
  const editDraft = editing ? $(`notes-edit-${editing}`)?.value : undefined;
  const notes = data.notes || [];
  const limit = Math.round((data.max_bytes || 20480) / 1024);
  const rows = sorted(notes).map((note) => noteRow(note));
  // Same rule as renderUndoBar: replaceChildren() must never receive null (it would show the word "null").
  $("notes-root").replaceChildren(...[
    h("p", { class: "muted" }, "Jot down anything you want to remember about this character: plans, reminders, what a GM said. " +
      "These notes are saved with this character's table record and do not change the character's rules or powers."),
    h("label", { class: "field" }, h("span", null, `New note (up to ${limit} KB)`),
      h("textarea", { id: "notes-new", rows: "3", maxlength: "100000" })),
    h("div", { class: "notes-tools" },
      h("button", { type: "button", class: "btn btn-accent", id: "notes-add" }, "Add note"),
      h("label", { class: "field" }, h("span", null, "Order"),
        h("select", { id: "notes-order" },
          h("option", { value: "newest", selected: newestFirst || null }, "Newest first"),
          h("option", { value: "oldest", selected: !newestFirst || null }, "Oldest first")))),
    notice ? h("p", { class: "muted", role: "status" }, notice) : null,
    h("div", { id: "notes-undo-container" }),
    notes.length ? h("ul", { class: "notes-list" }, ...rows) : h("p", { class: "muted" }, "No notes yet."),
  ].filter(Boolean));
  if (newDraft !== undefined) $("notes-new").value = newDraft;
  if (editDraft !== undefined && editing) $(`notes-edit-${editing}`).value = editDraft;
  renderUndoBar();
}

function noteRow(note) {
  const { h } = deps;
  const stamp = note.updated && note.updated !== note.created
    ? `Written ${when(note.created)}, edited ${when(note.updated)}`
    : `Written ${when(note.created)}`;
  if (editing === note.id) {
    return h("li", { class: "note" },
      h("textarea", { id: `notes-edit-${note.id}`, rows: "4", maxlength: "100000", "aria-label": "Edit this note" }, note.text),
      h("div", { class: "notes-tools" },
        h("button", { type: "button", class: "btn btn-accent", "data-note-save": "1", "data-note-id": note.id }, "Save"),
        h("button", { type: "button", class: "btn", "data-note-cancel": "1" }, "Cancel")));
  }
  return h("li", { class: "note" },
    h("p", { class: "note-text", style: { "white-space": "pre-wrap" } }, note.text),
    h("p", { class: "muted note-stamp" }, stamp),
    h("div", { class: "notes-tools" },
      h("button", { type: "button", class: "btn", "data-note-edit": "1", "data-note-id": note.id }, "Edit"),
      h("button", { type: "button", class: "btn", "data-note-delete": "1", "data-note-id": note.id }, "Delete")));
}
