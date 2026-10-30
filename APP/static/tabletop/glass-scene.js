// Game Master control for Glass Heart Refraction's printed scene (owner 2026-10-16: a human GM must be
// able to declare it in the table, not only by calling the API). Plain choices in, the same request the
// server validates out: POST /api/tabletop/matches/{id}/glass-scene. Used by tabletop.js; see glass-scene.test.mjs.

// Values must match APP/combat/ext/glass_heart.py SCENE_LABELS.
export const GLASS_SCENE_CHOICES = [
  {value: "major_combat", label: "A major combat"},
  {value: "emotionally_decisive", label: "An emotionally decisive scene"},
];

// Keep this Game Master control absent from non-GM toolbars from the first identity render onward.
export function setGlassSceneVisibility(button, viewStatus, hasMatch) {
  const isGM = viewStatus === "gm";
  button.hidden = !isGM;
  button.disabled = !isGM || !hasMatch;
}

// Builds the request for one scene declaration. Throws a player-readable Error for a missing choice,
// so the table can show the message as a toast without sending anything.
export function glassSceneRequest(matchId, {bearerId, scene, stateVersion}) {
  if (!GLASS_SCENE_CHOICES.some(choice => choice.value === scene)) {
    throw new Error("Choose a major combat or an emotionally decisive scene.");
  }
  if (!bearerId) throw new Error("Choose a creature present in this fight.");
  if (!Number.isInteger(stateVersion)) throw new Error("Wait for the table to refresh, then declare the scene again.");
  return {
    url: `/api/tabletop/matches/${encodeURIComponent(matchId)}/glass-scene`,
    body: {bearer_id: bearerId, scene, expected_state_version: stateVersion},
  };
}
