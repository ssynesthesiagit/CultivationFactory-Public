// JSON-backed map editor history. Map documents contain only serializable data.
export function createMapHistory(editor, render) {
  return {
    change(mutator) {
      editor.history.push(JSON.stringify(editor.doc));
      if (editor.history.length > 100) editor.history.shift();
      editor.future = [];
      mutator(editor.doc);
      editor.dirty = true;
      render();
    },
    undo() {
      if (!editor.history.length) return;
      editor.future.push(JSON.stringify(editor.doc));
      editor.doc = JSON.parse(editor.history.pop());
      editor.dirty = true;
      render();
    },
    redo() {
      if (!editor.future.length) return;
      editor.history.push(JSON.stringify(editor.doc));
      editor.doc = JSON.parse(editor.future.pop());
      editor.dirty = true;
      render();
    },
  };
}
