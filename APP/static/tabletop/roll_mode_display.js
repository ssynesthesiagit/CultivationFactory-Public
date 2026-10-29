/** Visible Advantage/Disadvantage label and its per-source hover (owner 2026-10-15 04:39Z:
 *  "it should say 'advantage' or 'disadvantage' and have why underneath it when hovering over it").
 *
 * Shared by the table feed, the dice-court chip and the pre-commit target previews so every roll
 * surface explains its mode the same way. `sources` is the roll's `mode_sources` payload the server
 * already attaches to every explained roll (one row per contributing effect: kind, effect, owner, why).
 * Pure formatting: nothing here resolves, keeps or changes a roll.
 */

export function rollModeWord(mode) {
  return mode === "ADVANTAGE" ? "Advantage" : mode === "DISADVANTAGE" ? "Disadvantage" : "Normal roll";
}

export function rollModeHover(mode, sources) {
  const rows = (Array.isArray(sources) ? sources : []).filter(row => row && (row.kind === "advantage" || row.kind === "disadvantage"));
  const advantage = rows.filter(row => row.kind === "advantage");
  const disadvantage = rows.filter(row => row.kind === "disadvantage");
  const describe = row => `${row.effect}${row.owner ? ` (${row.owner})` : ""}: ${row.why || "applies to this roll"}`;
  if (!advantage.length && !disadvantage.length) return `${rollModeWord(mode)}: no Advantage or Disadvantage source applies`;
  const lines = [];
  if (mode === "NORMAL" && advantage.length && disadvantage.length) {
    // The engine wrote the mode down as NORMAL because both kinds are present:
    // the cancellation is the reason, so the first line explains it.
    lines.push(`Advantage (from ${advantage.map(describe).join("; ")}) cancels Disadvantage (from ${disadvantage.map(describe).join("; ")}), so the roll is made normally.`);
  } else if (mode === "NORMAL") lines.push("Normal roll: no remaining Advantage or Disadvantage.");
  for (const row of advantage) lines.push(`Advantage — ${describe(row)}`);
  for (const row of disadvantage) lines.push(`Disadvantage — ${describe(row)}`);
  return lines.join("\n");
}

/** The styled span every roll surface shows: the visible mode word whose hover lists the reasons. */
export function rollModeLabel(mode, sources) {
  const span = document.createElement("span");
  span.className = "tt-roll-mode" + (mode === "ADVANTAGE" ? " is-advantage" : mode === "DISADVANTAGE" ? " is-disadvantage" : " is-normal");
  span.textContent = rollModeWord(mode);
  span.title = rollModeHover(mode, sources);
  return span;
}
