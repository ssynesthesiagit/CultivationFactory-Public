// Afterimage map art (owner 2026-10-18: "some better art than the little white square").
// An Afterimage is a TEMPORARY_IMAGE map marker left by movement (combat/ext/motion_status.py). The table sends its
// owner-neutral row only, so this art is generic on purpose: one translucent humanoid ghost for every Afterimage,
// whoever left it. It never shows the owner's likeness, HP or name plate. Used by object-presentation.js (which marks
// the token) and board.js (which draws it). Pure helpers, no DOM, so the node test can load it.

export const AFTERIMAGE_KIND = "TEMPORARY_IMAGE";
export const AFTERIMAGE_DETAIL = "Afterimage — a visible image left by movement; disappears when successfully targeted or at the start of its creator's next turn.";

export function isAfterimageMarker(object) {
  return object?.kind === AFTERIMAGE_KIND;
}

// A head and a tapering body in one 64x64 square, drawn the same way as the rest of the object art (viewBox 0 0 64 64).
const SILHOUETTE = "M24 13 a8 8 0 1 0 16 0 a8 8 0 1 0 -16 0 Z "
  + "M22 27 Q32 22 42 27 L46 46 Q47 52 42 53 L40 58 Q38 60 35 58 L33 53 L31 53 L29 58 Q26 60 24 58 L22 53 Q17 52 18 46 Z";

// The trail is the same silhouette 3 px left and 1 px down, fainter, so the figure looks like it has just moved.
// Only class names and plain attributes: no ids, so several ghosts on one board never clash.
export function afterimageGhostArt() {
  return '<svg viewBox="0 0 64 64" class="tt-afterimage-ghost" aria-hidden="true">'
    + `<path class="tt-afterimage-trail" transform="translate(-3 1)" d="${SILHOUETTE}"/>`
    + `<path class="tt-afterimage-body" d="${SILHOUETTE}"/>`
    + "</svg>";
}
