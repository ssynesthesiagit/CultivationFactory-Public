// Wall looks (owner 2026-10-08: "build different walls ... Ancient China and cultivation as inspiration"). A wall's
// optional `look` picks how it is drawn; a wall without one is drawn exactly as before (board.js, tabletop.css). The look
// picks a default height when none was authored (map-heights.js); explicit heights always win.
import {rock, seeded} from "./art-kit.js?v=sol196p2";
// What a wall blocks stays its `blocks` field, and its squares come from its geometry alone.
//
// Seen from straight above, a wall is a band along its line at the drawn wall thickness (0.22 of a square). Each look is
// a stack of strokes along that line, bottom first: dark edges, the body, then the detail on top (brick joints,
// coping tiles, lattice, bamboo nodes, runes) as dashes that run around corners. Ends are square and flush; where a door
// or window cuts the wall (door_join) the ends are butt-cut so they meet its jambs. Filled rectangles and circles use a
// tile pattern in the look's colours with the look's edge. All of it is a few SVG elements per wall: cheap to draw.
export const WALL_LOOKS = Object.freeze({
  rammed_earth: "Rammed earth",
  grey_brick: "Grey brick",
  red_palace: "Red palace wall, glazed-tile coping",
  white_plaster: "White plaster, dark-tile coping",
  timber_lattice: "Timber lattice and paper screen",
  bamboo_fence: "Bamboo fence",
  stone_rampart: "Stone fortress rampart",
  jade_marble: "Jade and marble sect wall",
  ruined_stone: "Ruined stone",
  formation_barrier: "Formation barrier (glowing runes)",
  rock_cliff: "Natural rock cliff",
});

// Looks that read as bare natural stone rather than construction: a filled circle in one of these
// (or with no look at all, the old default) is a boulder/rock mass, not a built pillar; a filled rect
// in one of these gets cracked-rock fill instead of brick coursing (MAPART2, owner QA: "mountain-pass
// perimeter is brick ... should be able to read as rock cliff").
const NATURAL_LOOKS = new Set(["rammed_earth", "ruined_stone", "stone_rampart", "rock_cliff"]);
const BOULDER_TONE = {rammed_earth: "warm", ruined_stone: "moss", stone_rampart: "grey", rock_cliff: "grey"};

export const wallLook = wall => (Object.hasOwn(WALL_LOOKS, wall?.look) ? wall.look : null);

const T = 0.22;  // the drawn wall thickness, in squares (tabletop.css .tt-wall-line stroke-width)

// Stroke layers per look: w = width in squares, c = colour, d = dash pattern along the wall, o = dash offset,
// a = opacity, cap/join override. Widths above T are the edges and glows; at or below T, the face of the wall.
const LOOKS = {
  rammed_earth: [
    {w: T + 0.04, c: "#4a3420"}, {w: T, c: "#a8835a"},
    {w: T, c: "#8a6a44", d: "0.012 0.6", o: 0.3},                  // the joints between formwork lifts
    {w: 0.13, c: "#bf9a6c", a: 0.7}, {w: 0.05, c: "#d8b688", a: 0.6},  // the lit, slightly rounded top
    {w: 0.012, c: "#6e5232", a: 0.7, d: "0.18 0.07 0.05 0.1"},     // cracks along the top
  ],
  grey_brick: [
    {w: T + 0.04, c: "#2e3032"}, {w: T, c: "#8a8c8d"},
    {w: T, c: "#4a4c4e", d: "0.014 0.236"},                         // header joints across the wall
    {w: 0.012, c: "#4a4c4e"},                                       // the course seam along it
    {w: T - 0.03, c: "#a4a6a7", d: "0.11 0.14", o: 0.12, a: 0.35},  // lighter alternate bricks
  ],
  red_palace: [
    {w: T + 0.05, c: "#3a0e08"}, {w: T, c: "#a32c20"},
    {w: 0.11, c: "#6a4a12"}, {w: 0.09, c: "#d9a630"},              // the glazed-tile coping, golden
    {w: 0.09, c: "#8a6516", d: "0.012 0.068"},                      // tile joints
    {w: 0.03, c: "#f6d56e"},                                        // the ridge
  ],
  white_plaster: [
    {w: T + 0.04, c: "#5a554a"}, {w: T, c: "#e6dfcd"},
    {w: 0.1, c: "#2a2d33"}, {w: 0.08, c: "#4a4f58"},               // dark tile coping
    {w: 0.08, c: "#2a2d33", d: "0.012 0.068"},
    {w: 0.025, c: "#7a808a"},
  ],
  timber_lattice: [
    {w: T + 0.02, c: "#2a170a"}, {w: T - 0.04, c: "#5e3a1e"},      // the timber frame
    {w: 0.1, c: "#efe6cc"},                                         // paper panels
    {w: 0.1, c: "#5e3a1e", d: "0.012 0.06"},                        // the lattice
    {w: 0.012, c: "#5e3a1e"},
    {w: T + 0.03, c: "#3a2210", d: "0.06 0.94", o: 0.03},           // posts every square
  ],
  bamboo_fence: [
    {w: T + 0.03, c: "#2f4a18", join: "round"}, {w: T - 0.01, c: "#7f9f3e", join: "round"},
    {w: 0.06, c: "#b8d070", a: 0.7, join: "round"},                 // the lit culm
    {w: T, c: "#3f5a20", d: "0.016 0.14", join: "round"},           // nodes
    {w: T + 0.05, c: "#b8945a", d: "0.03 0.47", o: 0.2, join: "round"},  // cord bindings
  ],
  stone_rampart: [
    {w: T + 0.12, c: "#5d5850", d: "0.14 0.1"},                     // crenellations: merlons standing proud
    {w: T + 0.12, c: "#1e1c19", d: "0.14 0.1", o: -0.01, a: 0.5},
    {w: T + 0.03, c: "#3e3b36"}, {w: T, c: "#8f8a7e"},
    {w: T, c: "#4f4b44", d: "0.016 0.33", o: 0.1},                  // big block joints
    {w: 0.012, c: "#4f4b44"},
    {w: 0.08, c: "#b6b0a2", a: 0.6},                                // the walkway, worn lighter
  ],
  jade_marble: [
    {w: T + 0.04, c: "#2f5a4a"}, {w: T, c: "#e6ece6"},
    {w: T, c: "#c9d3cc", d: "0.012 0.49"},                          // slab joints
    {w: 0.07, c: "#4f9a7a"}, {w: 0.025, c: "#9fe0c0"},             // the inlaid jade band
    {w: T + 0.04, c: "#d4a957", d: "0.03 0.97", o: 0.48},           // gilt studs every square
  ],
  ruined_stone: [
    // a continuous rubble footing first: the wall still blocks along its whole length, so it never looks open
    {w: T + 0.04, c: "#33302b"}, {w: T, c: "#5f5a50"},
    {w: T + 0.02, c: "#2a2722", d: "0.55 0.06 0.3 0.09"},           // standing courses, broken where they fell
    {w: T, c: "#8a8478", d: "0.53 0.08 0.28 0.11"},
    {w: T - 0.06, c: "#a8a294", d: "0.2 0.1 0.12 0.18 0.3 0.06", a: 0.8},
    {w: T, c: "#4a463f", d: "0.014 0.27", o: 0.05},
    {w: 0.05, c: "#6f7d4c", d: "0.08 0.5 0.05 0.3", a: 0.8},        // moss in the cracks
  ],
  formation_barrier: [
    {w: T + 0.22, c: "#7fd0ff", a: 0.16}, {w: T + 0.1, c: "#9fdcff", a: 0.3},  // the glow
    {w: T - 0.06, c: "#1d2a5a"},
    {w: 0.1, c: "#f0d08a", d: "0.025 0.035 0.01 0.05", a: 0.95},   // runes
    {w: 0.02, c: "#e6f6ff"},
  ],
  rock_cliff: [
    // Solid natural rock, not a ruin: a continuous dark base, irregular lit facets catching the NW
    // light at a broken (non-brick) rhythm, hairline cracks, and lichen -- never fully open, same as
    // the others, but reading as cliff face rather than coursed masonry.
    {w: T + 0.05, c: "#221f1b"}, {w: T, c: "#6f6a5e"},
    {w: T - 0.03, c: "#89816f", d: "0.1 0.04 0.06 0.08 0.13 0.05", o: 0.1, a: 0.8},
    {w: 0.014, c: "#2b2822", d: "0.18 0.07 0.09 0.12 0.05 0.1", a: 0.75},
    {w: 0.05, c: "#5c6b42", d: "0.09 0.55 0.05 0.4", a: 0.7},       // lichen in the cracks
  ],
};

// Fill colours for filled walls (a rectangle or circle of solid wall): base, joint, edge.
const FILLS = {
  rammed_earth: ["#a8835a", "#8a6a44", "#4a3420"], grey_brick: ["#8a8c8d", "#4a4c4e", "#2e3032"],
  red_palace: ["#a32c20", "#6a1a12", "#3a0e08"], white_plaster: ["#e6dfcd", "#b8b09c", "#5a554a"],
  timber_lattice: ["#efe6cc", "#5e3a1e", "#2a170a"], bamboo_fence: ["#7f9f3e", "#3f5a20", "#2f4a18"],
  stone_rampart: ["#8f8a7e", "#4f4b44", "#2a2824"], jade_marble: ["#e6ece6", "#4f9a7a", "#2f5a4a"],
  ruined_stone: ["#8a8478", "#4a463f", "#33302b"], formation_barrier: ["#1d2a5a", "#f0d08a", "#7fd0ff"],
  rock_cliff: ["#6f6a5e", "#453f37", "#221f1b"],
};

// How a filled rect's tile pattern is drawn: "rock" breaks up into irregular cracked facets (no brick
// grid) for bare stone looks, "bamboo" lays down vertical culms with node bands (a flat tinted brick
// grid read as a baked carpet on bandit-camp's and ricefield-bamboo-valley's bamboo-fence huts, owner
// QA), anything else keeps the original brick/masonry coursing.
const FILL_STYLE = {ruined_stone: "rock", rock_cliff: "rock", bamboo_fence: "bamboo"};

const n = v => Math.round(v * 1000) / 1000;

// A deterministic per-wall seed (FNV-1a over its id, falling back to its drawn position so an
// unnamed wall still gets a stable seed): art must not change shape on every re-render.
function hashSeed(text) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < text.length; i += 1) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function rockFillBody(base, joint) {
  return `<rect x="0" y="0" width="1" height="1" fill="${base}"/>`
    + `<path d="M.06 .34L.38 .12L.66 .4L.5 .7L.16 .6Z" fill="${joint}" opacity=".4"/>`
    + `<path d="M.6 0L1 .14L.9 .52L.58 .46Z" fill="${joint}" opacity=".3"/>`
    + `<path d="M0 .78L.3 .68L.48 1L.08 1Z" fill="${joint}" opacity=".35"/>`
    + `<path d="M.06 .34 .38 .12 .66 .4 .5 .7 .16 .6 .06 .34M.6 0 1 .14 .9 .52 .58 .46M0 .78 .3 .68 .48 1" stroke="${joint}" stroke-width=".02" fill="none" opacity=".8"/>`;
}

function bambooFillBody(base, joint, seed = 1) {
  // A four-square bank of uneven culms: nodes belong to each stalk, never a cross-wall grid.
  // Bounded seeded banks keep neighbouring huts distinct without per-frame SVG growth.
  const rand = seeded(seed);
  let out = `<rect x="0" y="0" width="4" height="1" fill="${joint}"/>`;
  for (let i = 0; i < 16; i += 1) {
    const x = i / 4 + rand() * 0.04, w = 0.14 + rand() * 0.08;
    const tone = ['#7d9250', '#91a65e', '#a5b574', base][Math.floor(rand() * 4)];
    out += `<rect x="${n(x)}" y="0" width="${n(w)}" height="1" rx=".06" fill="${tone}"/>`
      + `<rect x="${n(x + 0.02)}" y="0" width=".025" height="1" fill="#eaf0c8" opacity=".3"/>`;
    for (const y of [0.12 + rand() * 0.22, 0.6 + rand() * 0.22]) {
      out += `<ellipse cx="${n(x + w / 2)}" cy="${n(y)}" rx="${n(w / 2)}" ry=".026" fill="${joint}"/>`
        + `<path d="M${n(x)} ${n(y - 0.025)}h${n(w)}" stroke="#d1d6a1" stroke-width=".015"/>`;
    }
    if (rand() < 0.5) out += `<path d="M${n(x + w / 2)} .16q-.18-.13-.23-.1q.05.15.23.1q.2-.12.27-.08q-.08.13-.27.08" fill="#4f7136"/>`;
  }
  return out;
}

// Pattern definitions for filled walls, put once in the walls layer's <defs>.
// Tall rectangles run vertically: turn the entire tile (including its joints)
// rather than stretching it. Both orientations stay anchored to board space so
// adjacent pieces keep a continuous pattern. Lines/outlines already orient their
// stroke layers along the path; squares and circles have no preferred direction.
export function wallPatternDefs() {
  return Object.entries(FILLS).flatMap(([look, [base, joint]]) => {
    const style = FILL_STYLE[look] || "brick";
    const size = style === "brick" ? [0.5, 0.25] : style === "bamboo" ? [4, 1] : [1, 1];
    const body = style === "rock" ? rockFillBody(base, joint)
      : style === "bamboo" ? bambooFillBody(base, joint)
      : `<rect x="0" y="0" width="0.5" height="0.25" fill="${base}"/>`
        + `<path d="M0 .125H.5M.25 0V.125M0 .125V.25M.5 .125V.25" stroke="${joint}" stroke-width=".014" fill="none"/>`;
    return (style === "bamboo" ? Array.from({length: 9}, (_, i) => i) : [0]).flatMap(variant =>
      [false, true].map(vertical =>
        `<pattern id="tt-wall-pat-${look}${variant ? `-seed${variant}` : ''}${vertical ? '-v' : ''}" width="${size[0]}" height="${size[1]}" patternUnits="userSpaceOnUse"${vertical ? ' patternTransform="rotate(90)"' : ''}>${variant ? bambooFillBody(base, joint, variant * 7919) : body}</pattern>`));
  }).join("");
}

// A masonry drum/pillar seen from above: concentric courses (a touch eccentric, never a bullseye),
// an NW-lit highlight arc and one weathered chip at the rim. Used for small square or round filled
// walls whose look is a built one (owner QA: maple-shrine's flat red "pillar" squares, and round
// walls in general, read as rule markers rather than a real object).
function pillarArt(r, seed, [base, joint, edge]) {
  const rand = seeded(seed);
  const rings = 2 + Math.floor(rand() * 2);
  const ex = 1 + (rand() - 0.5) * 0.06, ey = 1 + (rand() - 0.5) * 0.06;
  let out = `<ellipse cx="0" cy="0" rx="${n(r * ex)}" ry="${n(r * ey)}" fill="${base}" stroke="${edge}" stroke-width="${n(r * 0.1)}"/>`;
  for (let i = 1; i <= rings; i += 1) {
    const k = i / (rings + 1);
    out += `<ellipse cx="${n((rand() - 0.5) * r * 0.06)}" cy="${n((rand() - 0.5) * r * 0.06)}" rx="${n(r * ex * k)}" ry="${n(r * ey * k)}" fill="none" stroke="${joint}" stroke-width="${n(r * 0.03)}" opacity="${n(0.4 + k * 0.3)}"/>`;
  }
  out += `<path d="M${n(-r * 0.55)} ${n(-r * 0.72)}A${n(r * 0.85)} ${n(r * 0.85)} 0 0 1 ${n(r * 0.62)} ${n(-r * 0.4)}" stroke="${edge}" stroke-width="${n(r * 0.22)}" fill="none" opacity=".22" stroke-linecap="round"/>`;
  const chipA = rand() * Math.PI * 2;
  out += `<path d="M${n(Math.cos(chipA) * r * 0.92)} ${n(Math.sin(chipA) * r * 0.92)}L${n(Math.cos(chipA + 0.25) * r * 1.04)} ${n(Math.sin(chipA + 0.25) * r * 1.04)}L${n(Math.cos(chipA + 0.5) * r * 0.9)} ${n(Math.sin(chipA + 0.5) * r * 0.9)}Z" fill="${edge}" opacity=".5"/>`;
  return out;
}

// A round or small-square object standing on the floor, every look: a flat tile-pattern disc/square
// with a thick edge (the old default for both shapes) reads as a dead placeholder at this scale (owner
// QA, mountain-pass and ruined-spirit-shrine's circles; maple-shrine's flat red squares). A natural
// look (or none at all, the long-standing default) is a cracked, shaded, irregular boulder, reusing
// art-kit.js's existing rock() (MAPART1, corkboard #2331); a built look is a round masonry pillar/well.
function standaloneObjectMarkup(wall, look, cx, cy, r, boulderScale) {
  const seed = hashSeed(String(wall.id ?? `${cx},${cy}`));
  const sight = wall.blocks === "sight";
  const natural = look == null || NATURAL_LOOKS.has(look);
  let body;
  if (natural) {
    const rand = seeded(seed);
    const tone = BOULDER_TONE[look] || "grey";
    const sides = 6 + Math.floor(rand() * 3), angle = rand() * Math.PI * 2, squash = 0.92 + rand() * 0.14;
    body = `<g transform="translate(${n(cx)} ${n(cy)}) scale(${n(r * boulderScale / 32)})">${rock(0, 0, 32, seed, tone, {sides, angle, squash, shadow: true})}</g>`;
  } else {
    const fills = FILLS[look] || FILLS.grey_brick;
    body = `<g transform="translate(${n(cx)} ${n(cy)})">${pillarArt(r, seed, fills)}</g>`;
  }
  return `<g class="tt-wall-look tt-wall-look-${look || "boulder"}"${sight ? ' opacity="0.85"' : ""}>${body}</g>`;
}

function circleWallMarkup(wall, look) {
  const [a, b] = wall.points || [];
  if (!a || !b) return null;
  const [cx, cy] = a, r = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!(r > 0)) return null;
  return standaloneObjectMarkup(wall, look, cx, cy, r, 1);
}

// A small, roughly square filled wall reads as an object standing on the floor (a pillar, a brazier
// stand) rather than a wall run; the brick-grid fill at that size is too faint to show, so it looks
// like a flat tinted marker square instead (owner QA, maple-shrine's "shrine-pillar" squares). Any
// filled rect this size and shape gets the same pillar-cap treatment the circle looks use -- but only
// when it stands alone: a run built from several joined rect segments (bandit-camp's wall-2/wall-4
// corner fillers, ricefield-bamboo-valley's hut corner posts) must keep reading as one continuous
// wall, not sprout a round blob where two straight segments meet.
function rectBounds(wall) {
  const [a, b] = wall.points || [];
  if (!a || !b) return null;
  if (wall.shape === "rect") return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
  if (wall.shape === "circle") {
    const r = Math.hypot(b[0] - a[0], b[1] - a[1]);
    return [a[0] - r, a[1] - r, a[0] + r, a[1] + r];
  }
  return null;
}

function touchesAnother(wall, bounds, siblings) {
  const eps = 0.01;
  for (const other of siblings) {
    if (other === wall) continue;
    const ob = rectBounds(other);
    if (ob && bounds[0] - eps <= ob[2] && ob[0] - eps <= bounds[2] && bounds[1] - eps <= ob[3] && ob[1] - eps <= bounds[3]) return true;
  }
  return false;
}

function squarePillarWall(wall, siblings) {
  const [a, b] = wall.points || [];
  if (!a || !b) return false;
  const w = Math.abs(b[0] - a[0]), h = Math.abs(b[1] - a[1]);
  if (!(w > 0 && h > 0 && w <= 1.5 && h <= 1.5 && Math.max(w, h) / Math.min(w, h) <= 1.3)) return false;
  return !touchesAnother(wall, rectBounds(wall), siblings);
}

function squarePillarMarkup(wall, look) {
  const [a, b] = wall.points;
  const cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2, r = Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) / 2;
  return standaloneObjectMarkup(wall, look, cx, cy, r, 1.3);
}

function shapeElement(wall, extra) {
  const points = wall.points || [];
  if (wall.shape === "rect" && points.length >= 2) {
    const [[x0, y0], [x1, y1]] = points;
    return `<rect x="${n(Math.min(x0, x1))}" y="${n(Math.min(y0, y1))}" width="${n(Math.abs(x1 - x0))}" height="${n(Math.abs(y1 - y0))}" ${extra}/>`;
  }
  if (wall.shape === "circle" && points.length >= 2) {
    const [[cx, cy], [ex, ey]] = points;
    return `<circle cx="${n(cx)}" cy="${n(cy)}" r="${n(Math.hypot(ex - cx, ey - cy))}" ${extra}/>`;
  }
  return `<polyline points="${points.map(([x, y]) => `${n(x)},${n(y)}`).join(" ")}" ${extra}/>`;
}

// One wall piece in its look, as SVG markup in square units (null when the wall has no look).
// siblings: the map's full wall list, so a small square rect can tell a standalone pillar from a
// corner segment of a longer run (squarePillarWall); omit it only for a one-off preview piece.
export function wallLookMarkup(wall, siblings = []) {
  const look = wallLook(wall);
  // Circles (boulders, pillars, braziers...) and small square "pillar" walls get their
  // own art regardless of look -- including no look at all, the long-standing default -- since the
  // generic brick-pattern fill never suited either shape (see circleWallMarkup/squarePillarMarkup).
  if (wall.shape === "circle" && wall.filled) return circleWallMarkup(wall, look);
  if (wall.shape === "rect" && wall.filled && squarePillarWall(wall, siblings)) return squarePillarMarkup(wall, look);
  if (!look) return null;
  const sight = wall.blocks === "sight";
  const cap = wall.door_join ? "butt" : "square";
  let out = "";
  if (wall.shape === "rect" && wall.filled) {
    const [, , edge] = FILLS[look];
    const [a, b] = wall.points || [];
    const vertical = Math.abs(b[1] - a[1]) > Math.abs(b[0] - a[0]);
    // Stable wall ids pick a bank; split pieces retain their id and unnamed previews use the default.
    const variant = look === 'bamboo_fence' && wall.id != null ? 1 + hashSeed(String(wall.id)) % 8 : 0;
    out += shapeElement(wall, `fill="url(#tt-wall-pat-${look}${variant ? `-seed${variant}` : ''}${vertical ? '-v' : ''})" stroke="${edge}" stroke-width="0.08"`);
  } else {
    for (const layer of LOOKS[look]) {
      const attrs = [`fill="none"`, `stroke="${layer.c}"`, `stroke-width="${n(layer.w)}"`, `stroke-linecap="${layer.d ? "butt" : cap}"`,
        `stroke-linejoin="${layer.join || "miter"}"`, `stroke-miterlimit="3"`];
      if (layer.d) attrs.push(`stroke-dasharray="${layer.d}"`, `stroke-dashoffset="${layer.o || 0}"`);
      if (layer.a) attrs.push(`opacity="${layer.a}"`);
      out += shapeElement(wall, attrs.join(" "));
    }
  }
  // A wall that only blocks sight (a screen, a barrier of light) is drawn a little see-through, as such walls were.
  return `<g class="tt-wall-look tt-wall-look-${look}" data-wall-look="${look}"${sight ? ' opacity="0.85"' : ""}>${out}</g>`;
}
