// What the ground under a square is made of, and what it does (owner 2026-09-30: "hovering over the
// types of ground for a ... second should bring up the type of material and its effects on movement or
// anything else"). A pure builder so the card is testable without a DOM; board.js decides which
// material, named terrain, cells and walls are under the pointer and passes them in. The readable
// name-and-effect for each kind comes from the server catalog (combat/ground_text.py) as `catalog`, keyed
// "floor:<style>" / "terrain:<name>" / "cell:<kind>" / "structure:<kind>". Pure presentation: a kind the
// catalog does not know says nothing rather than guessing a rule, and no mechanic is written out here --
// the wording lives once, on the server, so the table, the map editor and the tests cannot drift apart.

export function groundCard(cell, ctx = {}) {
  if (!cell) return null;
  const {style = null, terrain = null, tree = false, difficult = false, hazard = false, cover = false, blocked = false,
         sight = false, centerline = false, catalog = {}} = ctx;
  const lines = [];
  let heading = null;    // the kind that decides what the square DOES; the floor is only the fallback
  let material = null;   // the painted floor, also named beneath any rule heading
  const add = (key, {names = false} = {}) => {
    const entry = catalog[key];
    if (!entry) return;
    if (names) { if (!heading && entry.name) heading = entry.name; }
    else if (material === null && entry.name) material = entry.name;
    for (const line of entry.lines || []) lines.push(line);
  };
  // The painted floor is only the look, so it is named as the material and never heads the card. A
  // named terrain painted on the square is a rule of its own: it heads the card and its lines follow the
  // material, so hovering a square says what the ground does instead of only what it is drawn as.
  if (style) add(`floor:${style}`);
  if (terrain) add(`terrain:${terrain}`, {names: true});
  if (difficult) add("cell:difficult", {names: true});
  if (cover) add("cell:cover", {names: true});
  if (hazard) add("cell:hazard", {names: true});
  // A solid wall already says it blocks sight, so only a square that is sight-only needs saying
  // separately: it stops sight while a creature still walks through it.
  const geometry = centerline ? ":centerline" : "";
  if (blocked) add((tree ? "structure:tree" : "structure:wall") + geometry, {names: true});
  else if (sight) add("cell:sight" + geometry, {names: true});
  if (heading && material) lines.unshift(`Material: ${material}`);
  return lines.length ? {title: heading || material || "Ground", lines} : null;
}
