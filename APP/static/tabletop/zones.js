// Zones on the table (owner 2026-09-27): what a lasting effect's zone looks like and says.
//
// The engine decides what a zone does (combat rules; presentation.zones).  This module only
// reads a zone and answers display questions: which material to paint, where its edge runs,
// what its tooltip says.  Pure functions with no DOM, tested with `node --test` (zones.test.mjs);
// the painting itself is zonepaint.js and the layers are board.js.
import {effectText, saveName} from "./zone-text.js?v=r25x2";

// Materials the rules can name in trigger_profile.visual.material.  Anything else paints as
// "generic" (the zone's own colour) so a new material never breaks the table.
export const MATERIALS = [
  "ash", "fire", "lava", "ice", "frost", "water", "mud", "stone", "rubble", "thorns", "vines", "poison", "miasma",
  "lightning", "darkness", "radiance", "smoke", "fog", "dust", "wind", "blood", "sand", "grave", "metal", "glyphs", "spirit",
  "illusion", "stars", "sound", "web", "cracked", "crater", "glass", "wax", "bamboo", "generic",
];
const MATERIAL_SET = new Set(MATERIALS);

// Fallback tint per material, for zones that carry no `color` of their own.
export const MATERIAL_TINT = {
  ash: "#9a8f86", fire: "#ff7a2a", lava: "#ff5a1a", ice: "#a8d8f0", frost: "#dcefff", water: "#3a86b8", mud: "#6b4a2a",
  stone: "#8a8580", rubble: "#8c8174", thorns: "#5b6b2e", vines: "#4f8a3a", poison: "#9bc43a", miasma: "#7a6a8a",
  lightning: "#7ab8ff", darkness: "#1a1426", radiance: "#ffd98a", smoke: "#80828a", fog: "#d0d6dc", dust: "#ceb486", wind: "#d8e6ee",
  blood: "#8a1018", sand: "#d2b27a", grave: "#b8b0a0", metal: "#a8b0bc", glyphs: "#e8c46a", spirit: "#8fe8d8",
  illusion: "#c89aff", stars: "#8a8cff", sound: "#c8c0ff", web: "#e8e8e0", cracked: "#a07c56", crater: "#6e5f52",
  glass: "#bfe0d4", wax: "#f0e4c8", bamboo: "#5d7d3a", generic: "#8f97a3",
};
const LEGACY_TINT = "#8f97a3";

// A 32-bit seed from a zone id (FNV-1a), so each zone paints the same way on every refresh.
export function hashSeed(text) {
  let hash = 0x811c9dc5;
  for (const char of String(text ?? "")) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

export const cellXY = cell => (Array.isArray(cell) ? [cell[0], cell[1]] : [cell.x, cell.y]);

// The drawable zones out of presentation.zones: an array of zone rows (or an object keyed by
// zone id); rows that are not objects, are inactive or cover no squares are skipped.
export function zoneList(zones) {
  const rows = Array.isArray(zones) ? zones : zones && typeof zones === "object" ? Object.values(zones) : [];
  return rows.filter(zone => zone && typeof zone === "object" && zone.active !== false && zone.zone_id
    && Array.isArray(zone.affected_cells) && zone.affected_cells.length > 0);
}

// Map terrain is identified by explicit scenery metadata (or the legacy map
// owner and source), not by shape: techniques and blockers also use that shape.
// The rules overlay restores
// ordinary edges, movement marks, and names; walls keep their distinct wall rims.
export function zonePresentation(zone, rulesOverlay = false) {
  const mapTerrain = (zone?.owner_id === null && zone?.trigger_profile?.map === true)
    || zone?.source_definition_id === "system:battlefield.terrain";
  const wall = Boolean(zone?.trigger_profile?.wall);
  return {mapTerrain, hatch: Boolean(rulesOverlay), label: Boolean(rulesOverlay), softRim: !rulesOverlay && !mapTerrain && !wall};
}

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
export const validColor = value => (typeof value === "string" && HEX.test(value.trim()) ? value.trim() : null);

function obscuredLevel(value) {
  const text = String(value ?? "").toLowerCase();
  if (text.startsWith("heav")) return "heavy";
  if (text.startsWith("light")) return "light";
  return null;
}

// {radius_ft, color, level} -> {radiusCells, radiusFt, color, level}, or null when unusable.
export function normalizeLight(light) {
  if (!light || typeof light !== "object") return null;
  const radiusFt = Number(light.radius_ft);
  if (!Number.isFinite(radiusFt) || radiusFt <= 0) return null;
  return {radiusFt, radiusCells: radiusFt / 5, color: validColor(light.color) || "#ffd28a", level: light.level === "dim" ? "dim" : "bright"};
}

// Walls (owner 2026-09-27: "theres a lava wall, maybe a sand wall? theres various walls, those should be
// able to be placed and block los when applicable as well as movement").  A wall is a zone whose
// trigger_profile.wall carries its rule, as the engine lays it on the grid (combat/zones.py sync_walls):
// blocks_movement -> impassable, and it hides what is behind it like a map's BLOCKED square;
// blocks_sight -> hides but can be walked through; cover; move_cost -> each square costs that many times
// the movement.  visual.wall alone marks a zone to draw as a wall when no rule came with it.
// kind: "solid" (blocks movement), "screen" (blocks sight only) or "low" (cover or slow going only).
export function wallRule(zone) {
  const profile = zone?.trigger_profile && typeof zone.trigger_profile === "object" ? zone.trigger_profile : {};
  const rule = profile.wall && typeof profile.wall === "object" ? profile.wall : null;
  if (!rule && profile.visual?.wall !== true) return null;
  // obscures "all" | "hostile" (smoke, darkness; a Monsoon Wall hides only from its creator's foes); see_through: a solid
  // wall you can see through (Force Wall) -- it still stops movement and attacks (combat/rules/terrain.json "walls").
  const blocksMovement = Boolean(rule?.blocks_movement);
  const obscures = rule?.obscures === "all" || rule?.obscures === "hostile" ? rule.obscures : rule?.blocks_sight ? "all" : null;
  const moveCost = Number(rule?.move_cost);
  return {
    blocksMovement, blocksSight: Boolean(obscures), obscures, seeThrough: Boolean(rule?.see_through), cover: Boolean(rule?.cover),
    moveCost: Number.isFinite(moveCost) && moveCost > 1 ? moveCost : null,
    kind: blocksMovement ? "solid" : obscures ? "screen" : "low",
  };
}

// The squares active walls hide sight through, as [x, y], for the fog and the line-of-sight hint.  As in
// the engine, a solid wall's square with a creature standing in it stays open until the creature leaves
// (occupied: [{x, y}] or [[x, y]]); a wall that blocks sight itself hides all of its squares.
// hostile(zone): true when the zone's creator is the viewer's foe (a Monsoon Wall hides only from them).
export function wallSightCells(zones, {occupied = [], hostile = () => true} = {}) {
  const standing = new Set(occupied.map(cell => cellXY(cell).join(",")));
  const out = new Set();
  for (const zone of zoneList(zones)) {
    const rule = wallRule(zone);
    if (!rule) continue;
    const hides = rule.obscures === "all" || (rule.obscures === "hostile" && hostile(zone));
    if (!hides && !(rule.blocksMovement && !rule.seeThrough)) continue;
    const opened = new Set((zone.trigger_profile?.openings || []).map(row => cellXY(row.cell).join(",")));
    for (const cell of zone.affected_cells) {
      const [x, y] = cellXY(cell);
      if (!Number.isInteger(x) || !Number.isInteger(y) || opened.has(`${x},${y}`)) continue;
      if (hides || !standing.has(`${x},${y}`)) out.add(`${x},${y}`);
    }
  }
  return [...out].map(key => key.split(",").map(Number)).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
}

// "x" when a wall runs left to right (at least as wide as it is tall), "y" when it runs up and down.
export function wallAxis(cells) {
  const {width, height} = cellBounds(cells);
  return width >= height ? "x" : "y";
}

// "action:typed.factory.x.ASH_BASE_ASHFALL" -> "Ash Base Ashfall" (legacy zones carry no name).
function nameFromDefinition(id) {
  if (String(id || "").startsWith("action:typed.")) return "Area effect";
  const tail = String(id || "Zone").split(/[.:/]/).filter(Boolean).pop() || "Zone";
  return tail.replace(/[_-]+/g, " ").toLowerCase().replace(/\b\p{L}/gu, letter => letter.toUpperCase()).trim() || "Zone";
}

// The shades an area of magical darkness can be drawn in. combat/ext/tabik_dark.py decides which one an area
// gets, from the typed rows that shaped it; the drawing is board.js.
// An area the engine never tagged is not one of these looks at all -- another sphere's darkness, or one saved
// before the looks existed -- and is drawn exactly as it always was (see darknessComposition).
export const DARKNESS_LOOKS = new Set(["veil", "pitch", "tentacles"]);

// How much of the floor each look hides once the whole area is drawn, as the owner's brief puts it (2026-10-03
// 03:38): "a more transparent darkness" (45-55% hidden), "still slightly transparent but almost pitch black"
// (88-92%), and "dark tentacles you can barely see" waving over a see-through veil.
export const DARKNESS_FILL = {veil: 0.5, pitch: 0.9, tentacles: 0.44};

// A screen wall stands up as a cloud the floor shows through, so it is drawn lighter than the same look on the
// ground. These are the two factors the table has always used for one (see board.js, before the looks existed).
const DARKNESS_SCREEN_GROUND = 0.86;
const DARKNESS_SCREEN_AIR = 0.5;

// The alphas one look is drawn with, for the whole composition and not for one layer of it.
//
// A look's fill is the WHOLE darkness: what the floor still shows through a finished area is 1 - fill. Two
// layers sit between the floor and the eye -- the material on the ground and the veil in the air -- and each
// takes the same share of that budget, so the two together hide exactly fill:
//     (1 - share) * (1 - share) = 1 - fill
// Equal shares, because each layer also darkens what the other cannot reach (the floor below; the grid, the
// walls and the creatures above), and because one number per layer is what a reader can check. Everything that
// rides on the veil -- the drifting haze, the tentacles -- sits inside that share rather than on top of it,
// which is why the tentacles are faint: "you can barely see" them.
//
// Returns null for an area with no look, so the table keeps the drawing it has always had.
export function darknessComposition(look, {wall = false} = {}) {
  const fill = DARKNESS_FILL[look];
  if (!Number.isFinite(fill)) return null;
  const share = 1 - Math.sqrt(1 - fill);
  return {look, fill, share, ground: share * (wall ? DARKNESS_SCREEN_GROUND : 1), air: share * (wall ? DARKNESS_SCREEN_AIR : 1)};
}

// Everything the table needs to draw one zone, with every field defaulted.
export function zoneLook(zone) {
  const profile = zone.trigger_profile && typeof zone.trigger_profile === "object" ? zone.trigger_profile : {};
  const typed = profile.kind === "TYPED";
  const visual = profile.visual && typeof profile.visual === "object" ? profile.visual : {};
  const material = typed && MATERIAL_SET.has(visual.material) ? visual.material : "generic";
  const difficult = profile.difficult === true ? "all" : profile.difficult === "hostile" || profile.difficult === "all" ? profile.difficult : null;
  const baseName = typeof profile.name === "string" && profile.name.trim() ? profile.name.trim() : nameFromDefinition(zone.source_definition_id);
  const modifiers = [...new Set([...(profile.talents || []), ...(profile.augments || [])])]
    .filter(name => typeof name === "string" && name.trim() && name !== baseName);
  return {
    typed, material, difficult,
    obscured: obscuredLevel(visual.obscured ?? profile.obscured),
    darkness: visual.darkness === true || profile.darkness === true,
    // Which look this darkness is drawn with (owner 2026-10-03 03:38), or null when the engine has not said --
    // another sphere's darkness, an area saved before the looks existed, or an unreadable value. Null is not a
    // look: it keeps the drawing that darkness has always had, rather than picking one on the player's behalf.
    darknessLook: DARKNESS_LOOKS.has(visual.darkness_look) ? visual.darkness_look : null,
    darknessTentacles: visual.darkness_tentacles === true,
    light: normalizeLight(visual.light ?? profile.light),
    color: validColor(profile.color) || (typed ? MATERIAL_TINT[material] : LEGACY_TINT),
    name: baseName + (modifiers.length ? ` · ${modifiers.join(" + ")}` : ""),
    terrain: (Array.isArray(profile.terrain) ? profile.terrain : []).filter(item => typeof item === "string" && item.trim()),
    concentration: Boolean(zone.concentration_link),
    wall: wallRule(zone),
  };
}

// The one definition the map's own painted terrain comes from.  combat/zones.py map_zones builds every area the map
// editor painted (combat/tabletop.py to_battlefield "map_terrain") with this source_definition_id, and nothing else in
// combat/ does -- it is the map's own provenance, not a shape and not an ability's name.
export const MAP_TERRAIN_SOURCE = "system:battlefield.terrain";

// Is this natural ground the map itself was painted with?
//
// Owner 2026-10-03: "there's still some surrounding grids around various terrain, I think it was loose gravel?" --
// ground that was always part of the map is not an effect, so nothing is drawn round it: its own art and the hover
// card are what describe it, and it blends into the squares beside it.  An effect someone cast keeps its team-coloured
// edge, because that says whose it is and where it stops.
//
// Deliberately NOT keyed on trigger_profile.shape "painted": that shape also describes areas a character cast or that
// an aura worked out, which read as ordinary ground art (Guarded Threshold's sealed stone, Grove Domain's foliage) and
// lose their team-coloured edge if they are mistaken for the landscape.  Map terrain is the only area the map itself
// painted, so that is what is asked for here, and no terrain or ability is named.
export function paintedGround(zone) {
  return zonePresentation(zone).mapTerrain;
}

// Rounds a zone has left, or null when it lasts until dismissed.
export function roundsLeft(zone, round) {
  const duration = Number(zone.duration_rounds);
  if (!Number.isFinite(duration) || duration <= 0 || zone.duration_rounds === null) return null;
  const elapsed = Math.max(0, (Number(round) || 0) - (Number(zone.created_round) || 0));
  return Math.max(0, duration - elapsed);
}

const capitalise = text => text.charAt(0).toUpperCase() + text.slice(1);

// Tooltip text: {title, lines}.  owner is the caster's display name when the table knows it.
// What typed effects do, in a line (owner 2026-09-27: "when hovering over terrains showing what my character would know
// about it, like silence or difficult terrain or damage or poisoned or whatever it does").
export {effectText} from "./zone-text.js?v=r25x2";

// Who a trigger reaches, from the viewer's side (foe: the zone's creator is the viewer's foe).
function whoText(who, foe) {
  if (who === "any") return "anyone";
  if (who === "ally") return foe === true ? "its creator's allies" : foe === false ? "your side" : "its creator's allies";
  if (who === "self") return "its creator";
  if (who !== "hostile") return "affected creatures (targets not shown here)";
  return foe === true ? "you" : foe === false ? "your foes" : "its creator's foes";
}

// Same mechanical metadata/presentation contract as status_text.zone_sight_text.
// Policy comes from the server's targeting.json projection. Old/offline rows
// without that policy use the no-miss-chance wording, never guessed percentages.
export function zoneSightText(profile, rules = {}) {
  const visual = profile.visual || {}, wall = profile.wall || {};
  const heavy = !Object.keys(wall).length && (profile.obscured === 'heavy' || visual.darkness);
  const light = profile.lightly_obscured === true || profile.obscured === 'light' || visual.light === 'dim';
  const through = Boolean(wall.obscures);
  if (!(heavy || light || through)) return visual.obscured && !wall.blocks_sight
    && !(wall.blocks_movement && !wall.see_through) ? 'Visual cloud only: this area adds no concealment.' : '';
  const parts = [];
  if (heavy) parts.push(visual.sees === 'inward'
    ? 'Heavily obscured: creatures inside cannot see out, but creatures outside can see in.'
    : `Heavily obscured (${profile.name || 'this area'}): you can't see into it. Creatures inside cannot be seen from outside or by others inside.`);
  else if (light) parts.push('Lightly obscured: creatures inside are still visible.');
  if (through) parts.push(wall.obscures === 'hostile'
    ? "This wall hides creatures on the other side from its creator's foes."
    : 'This wall hides creatures on the other side.');
  parts.push("Attacks against creatures you can't see have Disadvantage.");
  const total = rules.total_concealment_miss_percent || 0, partial = rules.concealment_miss_percent || 0;
  if ((heavy || through) && total) parts.push(`If you can't see the target, attacks also have a ${total}% miss chance (total concealment).`);
  if (light && partial) parts.push(`Sight-based attacks against visible creatures inside have a ${partial}% miss chance (concealment).`);
  if (heavy && profile.owner_sees) parts.push('Its creator sees through it normally.');
  if (profile.obscured === 'heavy' && profile.team_sees) {
    if (heavy && profile.owner_sees) parts.push("Its creator's teammates see creatures inside as lightly obscured.");
    if (partial) parts.push(`Teammates' sight-based attacks against visible creatures inside have a ${partial}% miss chance (concealment).`);
  }
  parts.push('Senses that perceive the target without sight bypass this concealment within their range; senses that see through this effect bypass its sight blocking.');
  return parts.join(' ');
}

export function zoneTooltip(zone, look, {round = 0, owner = null, foe = null} = {}) {
  const lines = [];
  if (zone?.detail) lines.push(zone.detail);
  const profile = zone?.trigger_profile || {};
  const numbers = profile.numbers || {};
  const wall = look.wall;
  if (wall?.blocksMovement && wall.seeThrough) lines.push("Wall: blocks movement and attacks; you can see through it");
  else if (wall?.blocksMovement) lines.push("Wall: blocks movement and sight");
  else if (wall?.obscures === "hostile") lines.push("Wall: hides what is behind it from its creator's foes; can be walked through");
  else if (wall?.blocksSight) lines.push("Wall: blocks sight, can be walked through");
  if (wall?.obscures && !profile.wall?.obscures && !look.obscured) lines.push("Attacks through it have Disadvantage");
  const breach = zone?.trigger_profile?.wall?.breach;
  if (breach) lines.push(breach.result === "collapse" ? `A Large creature beside it may force through (Action, ${breach.ability} ${breach.skill ? `(${breach.skill})` : ""})`
                                                       : `Beside it: Action, ${breach.ability} (${breach.skill}) to open a section`);
  if (wall?.cover) lines.push("Gives cover");
  if (wall?.moveCost) lines.push(`Costs ${wall.moveCost}× movement`);
  // The talents it carries (owner 2026-09-27: Numbing Darkness, Pure Darkness), and what they do while you stay inside.
  if ((profile.talents || []).length) lines.push(`With ${profile.talents.join(" and ")}`);
  for (const rule of profile.inside || []) {
    if (rule.reading) lines.push(`${rule.name && rule.name !== look.name ? `${rule.name}: ` : ""}while inside (${whoText(rule.who || "any", foe)}): ${rule.reading}`);
  }
  if (look.terrain.length) lines.push(capitalise(look.terrain.join(", ")));
  if (look.difficult === "hostile") lines.push(foe === true ? "Difficult terrain for you" : foe === false ? "Difficult terrain for your foes (not you)" : "Difficult terrain (for foes)");
  else if (look.difficult === "all") lines.push("Difficult terrain");
  for (const trigger of profile.triggers || []) {
    const moments = (trigger.on || []).map(on => ({enter: "entering it", start: "starting a turn in it", end: "ending a turn in it",
      cross: "crossing it", technique: "using a technique inside it", prone: "falling Prone inside it"})[on] || "when its stated trigger occurs").join(" or ");
    const what = effectText(trigger.effects, numbers);
    const limit = trigger.first_each_round ? "only the first qualifying creature each round" : trigger.per_round ? "once per round per creature" : "once per turn per creature";
    if (what) lines.push(`${trigger.name && trigger.name !== look.name ? `${trigger.name}: ` : ""}${capitalise(moments)} (${whoText(trigger.who || "hostile", foe)}), ${limit}: ${what}`);
  }
  const through = profile.move_through;
  if (through) {
    const what = through.effects ? effectText(through.effects, numbers)
      : `${saveName(through.ability || "CON")} save${numbers.save_dc ? ` DC ${numbers.save_dc}` : ""}: ${effectText(through.on_fail, numbers) || "no effect"} on a failure`;
    lines.push(`Moving ${Number(through.min_ft) ? `more than ${through.min_ft} ft ` : ""}through it (${whoText("hostile", foe)}): ${what}`);
  }
  const sightText = zone.sight_text || zoneSightText(profile, zone.sight_rules);
  if (sightText) lines.push(sightText);
  if (look.darkness) lines.push("Magical darkness");
  if (look.light) lines.push(`${look.light.level === "dim" ? "Dim" : "Bright"} light, ${look.light.radiusFt} ft`);
  const left = roundsLeft(zone, round);
  if (profile.map) {
    lines.push("Map scenery: affects everyone in these squares for the whole fight. No action or resource cost.");
    if (look.difficult) lines.push("Moving here costs twice as much movement.");
    if (look.obscured === "light") lines.push("Details are harder to see; creatures are not automatically Hidden.");
  }
  if (left !== null) lines.push(left === 0 ? "Ending" : `${left} round${left === 1 ? "" : "s"} left`);
  if (look.concentration) lines.push("Concentration");
  if (owner || zone.applied_by) lines.push(`From ${owner || zone.applied_by}`);
  // Forged areas lead with their placed geometry and saved trigger effects.
  // The primary's printed delivery is background, explicitly original rules.
  if (zone.source_detail) lines.push(zone.source_detail);
  return {title: look.name, lines};
}

export function cellBounds(cells) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const cell of cells) {
    const [x, y] = cellXY(cell);
    if (x < minX) minX = x; if (y < minY) minY = y; if (x > maxX) maxX = x; if (y > maxY) maxY = y;
  }
  return {minX, minY, maxX, maxY, width: maxX - minX + 1, height: maxY - minY + 1};
}

// The edge of a set of squares as closed loops of corner points, following the square edges
// exactly (outer edges clockwise on screen, holes anticlockwise).  Two squares that touch only
// at a corner get separate loops: at such a pinch the trace always takes the right-hand turn.
export function cellOutline(cells) {
  const inside = new Set(cells.map(cell => cellXY(cell).join(",")));
  const has = (x, y) => inside.has(`${x},${y}`);
  const outgoing = new Map();  // "x,y" -> edges leaving that corner
  const edges = [];
  const add = (x0, y0, x1, y1) => {
    const edge = {x0, y0, x1, y1, used: false};
    edges.push(edge);
    const key = `${x0},${y0}`;
    if (!outgoing.has(key)) outgoing.set(key, []);
    outgoing.get(key).push(edge);
  };
  for (const key of inside) {
    const [x, y] = key.split(",").map(Number);
    if (!has(x, y - 1)) add(x, y, x + 1, y);
    if (!has(x + 1, y)) add(x + 1, y, x + 1, y + 1);
    if (!has(x, y + 1)) add(x + 1, y + 1, x, y + 1);
    if (!has(x - 1, y)) add(x, y + 1, x, y);
  }
  const loops = [];
  for (const start of edges) {
    if (start.used) continue;
    const points = [];
    let edge = start;
    while (edge && !edge.used) {
      edge.used = true;
      points.push([edge.x0, edge.y0]);
      const dx = Math.sign(edge.x1 - edge.x0), dy = Math.sign(edge.y1 - edge.y0);
      const choices = (outgoing.get(`${edge.x1},${edge.y1}`) || []).filter(next => !next.used);
      // Prefer the right turn, then straight on, then the left turn.
      const rank = next => {
        const ndx = Math.sign(next.x1 - next.x0), ndy = Math.sign(next.y1 - next.y0);
        if (ndx === -dy && ndy === dx) return 0;
        if (ndx === dx && ndy === dy) return 1;
        return 2;
      };
      edge = choices.sort((a, b) => rank(a) - rank(b))[0];
    }
    // Keep only the corners: drop points where the edge carries straight on.
    const corners = points.filter((point, index) => {
      const prev = points[(index - 1 + points.length) % points.length], next = points[(index + 1) % points.length];
      return (point[0] - prev[0]) * (next[1] - point[1]) - (point[1] - prev[1]) * (next[0] - point[0]) !== 0;
    });
    if (corners.length >= 4) loops.push(corners);
  }
  return loops;
}

export const outlinePath = loops => loops.map(loop => `M${loop.map(point => point.join(" ")).join("L")}Z`).join("");

// Diagonal hatching for difficult terrain as one SVG path: the lines x + y = k + 1/2 clipped to
// each square, so the hatch runs on unbroken across neighbouring squares and never through the
// grid's corners.  Two strokes a square: visible, but it does not bury the material.
export function hatchPath(cells) {
  return cells.map(cell => {
    const [x, y] = cellXY(cell);
    return `M${x} ${y + 0.5}L${x + 0.5} ${y}M${x + 0.5} ${y + 1}L${x + 1} ${y + 0.5}`;
  }).join("");
}

// Where the name label sits: centred over the middle square of the zone's top row, on the edge.
export function labelAnchor(cells) {
  const {minY} = cellBounds(cells);
  const top = cells.map(cellXY).filter(([, y]) => y === minY).map(([x]) => x).sort((a, b) => a - b);
  return {x: top[Math.floor((top.length - 1) / 2)] + 0.5, y: minY};
}
