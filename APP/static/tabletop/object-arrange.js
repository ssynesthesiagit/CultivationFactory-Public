// Several objects in one 5-foot square (owner 2026-10-08, SOL201: "place objects to share space and organize its
// positions dynamically to look natural if they fit in the 5ft square"). Shared by the map editor and the combat table.
//
// Space: each object kind has a footprint (combat/rules/objects.json "footprint_note"): tiny 1, small 2, medium and
// large 4 out of a square's 4, so a square holds up to 4 tiny, 2 small, 1 small + 2 tiny, or 1 medium/large alone.
// Look only: blocking, sight and cover still come from each object's own rules (combat/ext/objects.py).
//
// Arrangement: a lone object is drawn exactly as before (the whole square, no offset). Objects sharing a square are
// laid out from a seed of the map and the square, so every viewer and every reload sees the same layout: bigger items
// toward the back (north) and centre, a small turn and position jitter, pushed apart until no two overlap, kept inside
// the square. A hand nudge (`nudge: [dx, dy]`, hundredths of a square, saved on the object) moves one from its spot.

export const FOOTPRINT_FILL = {tiny: 1, small: 2, medium: 4, large: 4};
export const SQUARE_CAPACITY = 4;
// Radius (in squares) of the floor patch a shared object covers, and the share of the 64x64 drawing its art fills.
export const FOOTPRINT_RADIUS = {tiny: 0.22, small: 0.285, medium: 0.36, large: 0.42};
// How much of its 64x64 drawing each shareable prop fills (the larger of width and height, measured from object-art.js
// in Chromium), so a sack and a crate of one footprint are drawn at the floor size they really cover. Others: 0.75.
const ART_SPAN = {crate: 0.72, barrel: 0.72, chest: 0.72, banner: 0.84, rope: 0.79, vine: 1.14, incense_burner: 0.8,
  meditation_cushion: 0.63, stone_lantern: 0.93, woven_basket: 0.73, grain_sack: 0.49, war_brazier: 0.83, camp_banner: 0.9,
  ammo_crate: 1.11, blacksmith_anvil: 0.81, steamer_trunk: 0.86};
const MAX_TURN = 11;     // degrees of rotation jitter either way
const MAX_SHIFT = 0.06;  // squares of position jitter either way
export const NUDGE_LIMIT = 40;

const FACING_TURN = {east: 0, south: 90, west: 180, north: 270};

// The layouts by count, in slot order: back first (north), so the largest item (sorted first) stands at the back.
const SLOTS = {
  2: [[0.35, 0.34], [0.65, 0.66]],
  3: [[0.5, 0.29], [0.27, 0.72], [0.73, 0.72]],
  4: [[0.29, 0.29], [0.71, 0.29], [0.29, 0.71], [0.71, 0.71]],
};

// `defaults` is the server's combat/object_rules.editor_defaults(): {presets: {kind: {size, footprint}}, footprint_fill,
// square_capacity}. It is the one source of what fits; FOOTPRINT_FILL/SQUARE_CAPACITY above are only the fallback for
// the table, which gets each object's footprint already worked out by the server (tabletop_service._objects).
const fillTable = defaults => defaults?.footprint_fill || FOOTPRINT_FILL;
const capacityOf = defaults => Number(defaults?.square_capacity) || SQUARE_CAPACITY;

// Same precedence as combat/object_rules.footprint: an opening fills its square; a footprint the server already worked
// out wins; else the placement's own size, except that a placement left at its preset's size uses the preset footprint.
export function footprintOf(object, defaults = {}) {
  const table = fillTable(defaults);
  if (object?.mount_axis) return "large";
  const named = object?.footprint;
  if (named && named in table) return named;
  const preset = defaults?.presets?.[object?.kind] || defaults?.presets?.custom;
  const presetSize = String(preset?.size || "medium").toLowerCase();
  let size = String(object?.size || presetSize).toLowerCase();
  if (preset?.footprint && size === presetSize) size = String(preset.footprint).toLowerCase();
  return size in table ? size : "medium";
}

export const fillOf = (object, defaults) => Number(fillTable(defaults)[footprintOf(object, defaults)]);

const WORD = {tiny: "tiny", small: "small", medium: "medium-sized", large: "large"};

// Whether `object` may join the objects already in its square: {ok: true} or {ok: false, reason: plain words}.
export function squareRoom(others, object, defaults = {}, names = {}) {
  if (!others.length) return {ok: true};
  const label = row => String(row.name || names[row.kind] || row.kind || "object").toLowerCase();
  const counts = new Map();
  for (const row of others) counts.set(label(row), (counts.get(label(row)) || 0) + 1);
  const listed = [...counts].map(([name, count]) => count > 1 ? `${count} ${name.endsWith("s") ? name : `${name}s`}` : name);
  const here = listed.length > 1 ? `${listed.slice(0, -1).join(", ")} and ${listed.at(-1)}` : listed[0];
  if (object.mount_axis || others.some(row => row.mount_axis)) {
    return {ok: false, reason: `A door, gate or window fills its opening; nothing else fits there (the ${here}).`};
  }
  const used = others.reduce((sum, row) => sum + fillOf(row, defaults), 0);
  const need = fillOf(object, defaults);
  if (used + need <= capacityOf(defaults)) return {ok: true};
  const size = WORD[footprintOf(object, defaults)];
  return {ok: false, reason: `No room: the ${here} already ${others.length > 1 ? "take" : "takes"} up this 5-foot square, and a ${size} `
    + `${label(object)} will not fit beside ${others.length > 1 ? "them" : "it"}. A square holds up to 4 tiny objects, 2 small ones, `
    + `1 small and 2 tiny, or 1 medium or large object on its own.`};
}

// A small seeded generator (FNV-1a hash into mulberry32): the same map and square always give the same numbers.
function seeded(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  let a = h >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The number in a map object's id ("object:map.7" on the table, 7 in the editor), so both order a square alike.
const idOrder = id => { const match = /(\d+)$/.exec(String(id)); return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER; };
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

// Lay out the objects of one square. items: [{id, kind, footprint, nudge?}]. Returns Map id -> {cx, cy, radius, scale, turn}:
// the centre (0..1 within the square), the footprint radius, the token scale (1 = the whole square) and the extra
// degrees of turn to add to the object's own rotation.
export function arrangeSquare(items, seedKey) {
  const out = new Map();
  if (items.length === 1) {
    out.set(items[0].id, {cx: 0.5, cy: 0.5, radius: 0.5, scale: 1, turn: 0, shared: false});
    return out;
  }
  const random = seeded(String(seedKey));
  const order = [...items].sort((a, b) => (FOOTPRINT_FILL[b.footprint] || 4) - (FOOTPRINT_FILL[a.footprint] || 4)
    || idOrder(a.id) - idOrder(b.id) || String(a.id).localeCompare(String(b.id)));
  const template = SLOTS[Math.min(order.length, 4)];
  const mirror = random() < 0.5;
  const placed = order.map((item, index) => {
    const radius = FOOTPRINT_RADIUS[item.footprint] ?? FOOTPRINT_RADIUS.medium;
    let [cx, cy] = template[index] || [0.25 + random() * 0.5, 0.25 + random() * 0.5];  // a fifth item (old overfull data)
    if (mirror) cx = 1 - cx;
    cx += (random() * 2 - 1) * MAX_SHIFT;
    cy += (random() * 2 - 1) * MAX_SHIFT;
    const turn = Math.round((random() * 2 - 1) * MAX_TURN);
    return {item, radius, cx, cy, turn};
  });
  // Keep each inside the square, then push apart any two that overlap; repeat until nothing moves.
  for (let round = 0; round < 80; round += 1) {
    for (const row of placed) {
      row.cx = clamp(row.cx, row.radius, 1 - row.radius);
      row.cy = clamp(row.cy, row.radius, 1 - row.radius);
    }
    let moved = false;
    for (let i = 0; i < placed.length; i += 1) for (let j = i + 1; j < placed.length; j += 1) {
      const a = placed[i], b = placed[j];
      let dx = b.cx - a.cx, dy = b.cy - a.cy;
      let distance = Math.hypot(dx, dy);
      const gap = a.radius + b.radius + 0.005 - distance;
      if (gap <= 0) continue;
      if (distance < 1e-6) { dx = 1; dy = 0; distance = 1; }
      const push = gap / 2 / distance;
      a.cx -= dx * push; a.cy -= dy * push;
      b.cx += dx * push; b.cy += dy * push;
      moved = true;
    }
    if (!moved) break;
  }
  for (const row of placed) {  // the last push may have nudged one past an edge
    row.cx = clamp(row.cx, row.radius, 1 - row.radius);
    row.cy = clamp(row.cy, row.radius, 1 - row.radius);
  }
  // Hand nudges, back to front: each moves its object toward the nudged spot but stops short of touching a neighbour
  // or the square's edge, so a saved nudge can never stack two objects on top of each other.
  const clear = (row, x, y) => placed.every(other => other === row
    || Math.hypot(other.cx - x, other.cy - y) >= other.radius + row.radius - 1e-9);
  for (const row of placed) {
    if (!Array.isArray(row.item.nudge)) continue;
    const [nx, ny] = row.item.nudge.map(value => clamp(Number(value) || 0, -NUDGE_LIMIT, NUDGE_LIMIT) / 100);
    const tx = clamp(row.cx + nx, row.radius, 1 - row.radius), ty = clamp(row.cy + ny, row.radius, 1 - row.radius);
    let low = 0, high = 1;
    if (clear(row, tx, ty)) low = 1;
    else for (let step = 0; step < 24; step += 1) {
      const mid = (low + high) / 2;
      if (clear(row, row.cx + (tx - row.cx) * mid, row.cy + (ty - row.cy) * mid)) low = mid; else high = mid;
    }
    row.cx += (tx - row.cx) * low;
    row.cy += (ty - row.cy) * low;
  }
  for (const {item, radius, cx, cy, turn} of placed) {
    out.set(item.id, {cx, cy, radius, scale: Math.min(1, (2 * radius) / (ART_SPAN[item.kind] || 0.75)), turn, shared: true});
  }
  return out;
}

// Every object on a map: Map id -> layout (arrangeSquare), each square seeded by the map look seed and the square.
export function arrangeObjects(objects, mapSeed = "", defaults = {}) {
  const squares = new Map();
  for (const object of objects || []) {
    const key = `${object.x},${object.y}`;
    if (!squares.has(key)) squares.set(key, []);
    squares.get(key).push({id: object.id, kind: object.kind, footprint: footprintOf(object, defaults), nudge: object.nudge});
  }
  const out = new Map();
  for (const [key, items] of squares) for (const [id, layout] of arrangeSquare(items, `${mapSeed || ""}|${key}`)) out.set(id, layout);
  return out;
}

// The token fields for one object's layout: offsets in squares from the square's corner, a scale, and its turn
// (its own rotation, else the way it faces, plus the jitter). A lone object keeps its token exactly as before.
export function layoutTokenFields(layout, {rotation = null, facing = null} = {}) {
  if (!layout?.shared) return {};
  const base = rotation !== null && rotation !== undefined && rotation !== "" && Number.isFinite(Number(rotation))
    ? Number(rotation) : (FACING_TURN[String(facing || "").toLowerCase()] ?? 0);
  return {scale: layout.scale, offsetX: layout.cx - layout.scale / 2, offsetY: layout.cy - layout.scale / 2,
          rotation: (((base + layout.turn) % 360) + 360) % 360, shared: true};
}

// The nudge that puts an object where the pointer dropped it (point in squares on the board), from its laid-out
// centre and the nudge it already had.
export function nudgeFor(point, square, layout, current = [0, 0]) {
  const [ox, oy] = Array.isArray(current) ? current.map(value => Number(value) || 0) : [0, 0];
  const dx = Math.round(ox + (point.x - square[0] - layout.cx) * 100);
  const dy = Math.round(oy + (point.y - square[1] - layout.cy) * 100);
  return [clamp(dx, -NUDGE_LIMIT, NUDGE_LIMIT) || 0, clamp(dy, -NUDGE_LIMIT, NUDGE_LIMIT) || 0];  // never -0
}
