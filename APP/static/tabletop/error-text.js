import {MAX_FIGHTERS_PER_SIDE} from "./limits.js?v=r25";

export const SAVED_FIGHT_UNSUPPORTED_MESSAGE = "This fight was saved with an older version and can't continue — start a new one.";

// One player-facing error builder. Raw diagnostics stay on the Error object;
// they are never interpolated into a toast (paths and internal ids may be private).
// The sheet's own load failure (GET /api/tabletop/characters/<id>/sheet). The server answers a character that is not
// installed with COMBAT_CONTENT_NOT_READY, which playerError() words as a fight being saved, so the sheet asks here.
// `error` is the Error that fetchJson() throws; its `body` holds the server's JSON answer. Users: sheet.js main().
export const SHEET_NOT_INSTALLED_MESSAGE = "That character isn't installed here. Finalize it first, or pick another character below.";
export function sheetLoadMessage(error) {
  const code = error?.body?.error?.code || "";
  if (code === "COMBAT_CONTENT_NOT_READY") return SHEET_NOT_INSTALLED_MESSAGE;
  return `Could not load this character (${error?.message || "unknown error"}). Choose another:`;
}

export function playerError({code = "", status = 0, validationErrors = null, requestBody = null, path = ""} = {}) {
  if (status === 422 && path === "/api/combat/factory-matches" && Array.isArray(validationErrors)) {
    for (const issue of validationErrors) {
      const field = issue?.loc?.at(-1);
      if ((field === "project_ids" || field === "opponent_actor_ids") && issue?.type === "too_long") {
        const count = Array.isArray(requestBody?.[field]) ? requestBody[field].length : null;
        const team = field === "project_ids" ? "Team 1" : "Team 2";
        const actual = Number.isInteger(count) ? count : "too many";
        return Number.isInteger(count) ? `${team} has ${actual} fighters; the most is ${MAX_FIGHTERS_PER_SIDE}.`
          : `${team} has too many fighters; the most is ${MAX_FIGHTERS_PER_SIDE}.`;
      }
      if (field === "project_ids" && issue?.type === "too_short") return "Choose at least one fighter for Team 1.";
      if (field === "project_ids" || field === "opponent_actor_ids") return "Choose finished fighters for both teams.";
      if (field === "arena_id") return "Choose an arena from the map list.";
      if (field === "control_modes") return "Choose who controls each fighter: You or AI.";
      if (field === "prefight") return "Check the buffs chosen for before the fight.";
      if (field === "display_name" || field === "match_seed") return "Check the fight name and try again.";
    }
    return "The fight setup was not accepted. Check that each team has a fighter, each character appears once, and the map and ability choices are valid.";
  }
  // The map cannot seat every fighter, so no fight was started. Keep this
  // ahead of the generic 422 below, which would otherwise hide the reason.
  if (code === "COMBAT_SETUP_NO_ROOM") {
    return "That map has no room for every fighter. Choose a larger map, or take a fighter off the team.";
  }
  if ((status === 400 || status === 422) && path === "/api/combat/factory-matches") {
    return "The fight setup was not accepted. Check the teams, map and fighter options, then try again.";
  }
  if (code === "COMBAT_CONTENT_NOT_READY") return "This fight is still being saved or cannot be opened with these rules. Open it again from Fights. If it still fails, keep the saved fight and ask the GM for help.";
  if (code === "COMBAT_MATCH_NOT_FOUND") return "This saved fight is no longer available. Open Fights and choose an available fight.";
  // An unsupported save cannot be repaired by refreshing the current turn.
  if (code === "COMBAT_SAVED_FIGHT_UNSUPPORTED") return SAVED_FIGHT_UNSUPPORTED_MESSAGE;
  if (/FIGHTER_RETIRED/.test(code)) return "That character has been retired, so it cannot be chosen for a new fight. Pick a different character. Fights already saved with it can still be opened.";
  if (/SESSION|TOKEN/.test(code) || status === 403) return "The table could not authorize this request. Reload the page to reconnect, then check the current fight before acting again.";
  if (code === "TABLETOP_BUSY") return "Another action on this table is still finishing. Wait a moment, then try again. Nothing you chose was lost.";
  if (/STATE_VERSION|DECISION|STALE|CONFLICT/.test(code) || status === 409) return "The fight or its choices have changed. Wait for the table to refresh, then choose from the current turn's buttons.";
  if (/RESOURCE|INSUFFICIENT|COST/.test(code)) return "That ability cannot pay its cost. Check your current resource amounts and choose an affordable ability.";
  if (/TARGET|RANGE|POSITION|MOVEMENT/.test(code)) return "That target or destination is not available. Choose a highlighted target or a reachable square from the current choices.";
  if (/MAP_SIZE/.test(code)) return "The map size is invalid. Use a whole number from 6 to 80 for width and 6 to 60 for height, then save again.";
  if (/BACKGROUND|UPLOAD/.test(code) || status === 413) return "The image could not be uploaded. Choose a PNG, JPEG or WebP image under 12 MB, then upload again.";
  if (/MAP_WALL|MAP_TOO_COMPLEX/.test(code)) return "The map's walls could not be saved. Undo the last wall edit or simplify the walls, then save again.";
  if (/POWERING/.test(code)) return "This ability cannot be paid for by the pool you chose. On your sheet, under “Which pool pays”, pick one of the pools offered — Stamina, Qi or Resonance, the energy your character spends — then save again.";
  if (/NAME/.test(code)) return "A valid name is required. Enter a name in the name field, then save again.";
  if (status === 404) return "That fight, map or character is no longer available. Return to its list and choose an available entry.";
  if (status === 400 || status === 422) return "The table could not accept those choices. Check the selected fighters, map and ability options, then choose again. If it still fails, ask the GM for help.";
  if (status >= 500) return "The table could not finish this request. Reopen the fight to check what was saved before acting again. If it still fails, ask the GM for help.";
  return "The table could not connect. Check your connection and reopen the fight to check its current state before acting again.";
}
