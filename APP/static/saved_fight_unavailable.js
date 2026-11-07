import {api, enc} from "./tabletop/api.js?v=p20261010-06";
import {SAVED_FIGHT_UNSUPPORTED_MESSAGE} from "./tabletop/error-text.js?v=p20261010-06";

// The save is kept unless the player presses the named delete button. Opening,
// dismissing or cancelling this notice never sends a request or changes a save.
export function offerSavedFightRemoval(matchId) {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "savedFightUnavailableTitle");
    dialog.setAttribute("aria-describedby", "savedFightUnavailableExplanation");
    const title = document.createElement("h2");
    title.id = "savedFightUnavailableTitle";
    title.textContent = "Saved fight can't continue";
    const explanation = document.createElement("p");
    explanation.id = "savedFightUnavailableExplanation";
    explanation.textContent = SAVED_FIGHT_UNSUPPORTED_MESSAGE;
    const note = document.createElement("p");
    note.textContent = "Your saved fight will stay until you choose Delete saved fight. Deletion cannot be undone.";
    const keep = document.createElement("button");
    keep.type = "button";
    keep.textContent = "Keep saved fight";
    keep.autofocus = true;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete saved fight";
    let finished = false, submitting = false;
    const finish = (deleted, error) => {
      if (finished) return;
      finished = true;
      dialog.close(); dialog.remove();
      if (error) reject(error); else resolve(deleted);
    };
    keep.onclick = () => { if (!submitting) finish(false); };
    dialog.addEventListener("cancel", event => { event.preventDefault(); if (!submitting) finish(false); });
    remove.onclick = async () => {
      if (finished || submitting) return;
      submitting = true;
      keep.disabled = remove.disabled = true;
      // Wait for the response: closing a dialog cannot undo an in-flight delete.
      try {
        await api(`/api/tabletop/matches/${enc(matchId)}`, {method: "DELETE"});
        finish(true);
      } catch (error) { finish(false, error); }
    };
    dialog.append(title, explanation, note, keep, remove);
    document.body.append(dialog);
    dialog.showModal();
  });
}
