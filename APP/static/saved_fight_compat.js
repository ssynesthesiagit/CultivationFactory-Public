import {api, enc} from "./tabletop/api.js";

// Shared by the table and the original combat screen. No mutation occurs until
// the player chooses the named continuation; Escape/Cancel leave the save alone.
export function offerSavedFightContinuation(matchId) {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "savedFightCompatibilityTitle");
    const title = document.createElement("h2");
    title.id = "savedFightCompatibilityTitle";
    title.textContent = "Reopen saved fight";
    const explanation = document.createElement("p");
    explanation.textContent = "Checking the saved fight with the current rules…";
    const proceed = document.createElement("button");
    proceed.hidden = true;
    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    let finished = false, submitting = false;
    const finish = (result, error) => {
      if (finished) return;
      finished = true;
      dialog.close(); dialog.remove();
      if (error) reject(error); else resolve(result);
    };
    cancel.onclick = () => { if (!submitting) finish(null); };
    dialog.addEventListener("cancel", event => { event.preventDefault(); if (!submitting) finish(null); });
    dialog.append(title, explanation, proceed, cancel);
    document.body.append(dialog);
    dialog.showModal();
    api(`/api/combat/matches/${enc(matchId)}/compatibility`).then(report => {
      if (finished) return;
      const matched = report.mode === "REPLAY_MATCHED";
      explanation.textContent = matched
        ? "Every recorded action and die roll matched the original save with the current rules. Reopen a copy of this fight?"
        : "Some recorded actions played out differently with the current rules. You can continue from the saved point, but future outcomes may change. This choice will be recorded in the fight log.";
      if (report.later_commits) explanation.textContent += ` The last undamaged save is ${report.later_commits} actions behind. Those later actions will remain in the original fight only.`;
      explanation.textContent += " A new save and a verified backup will be created. Your original fight stays unchanged.";
      proceed.textContent = matched ? "Reopen with current rules" : "Continue from saved point";
      proceed.hidden = false;
      proceed.onclick = async () => {
        submitting = true;
        proceed.disabled = true;
        cancel.disabled = true;
        // Once submitted, let the result resolve; closing a dialog cannot undo a
        // committed continuation. The endpoint is idempotent if the response is lost.
        try {
          const result = await api(`/api/combat/matches/${enc(matchId)}/continue-saved`,
            {body: {token: report.token, mode: report.mode}});
          finish(result.match_id);
        } catch (error) { finish(null, error); }
      };
    }).catch(error => finish(null, error));
  });
}
