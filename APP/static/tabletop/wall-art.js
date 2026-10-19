// Wall looks (owner 2026-10-08: "build different walls ... Ancient China and cultivation as inspiration"). A wall's
// optional `look` picks how it is drawn; a wall without one is drawn exactly as before (board.js, tabletop.css). The look
// picks a default height when none was authored (map-heights.js); explicit heights always win.
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
});

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
};

// Fill colours for filled walls (a rectangle or circle of solid wall): base, joint, edge.
const FILLS = {
  rammed_earth: ["#a8835a", "#8a6a44", "#4a3420"], grey_brick: ["#8a8c8d", "#4a4c4e", "#2e3032"],
  red_palace: ["#a32c20", "#6a1a12", "#3a0e08"], white_plaster: ["#e6dfcd", "#b8b09c", "#5a554a"],
  timber_lattice: ["#efe6cc", "#5e3a1e", "#2a170a"], bamboo_fence: ["#7f9f3e", "#3f5a20", "#2f4a18"],
  stone_rampart: ["#8f8a7e", "#4f4b44", "#2a2824"], jade_marble: ["#e6ece6", "#4f9a7a", "#2f5a4a"],
  ruined_stone: ["#8a8478", "#4a463f", "#33302b"], formation_barrier: ["#1d2a5a", "#f0d08a", "#7fd0ff"],
};

const n = v => Math.round(v * 1000) / 1000;

// Pattern definitions for filled walls, put once in the walls layer's <defs>.
// Tall rectangles run vertically: turn the entire tile (including its joints)
// rather than stretching it. Both orientations stay anchored to board space so
// adjacent pieces keep a continuous pattern. Lines/outlines already orient their
// stroke layers along the path; squares and circles have no preferred direction.
export function wallPatternDefs() {
  return Object.entries(FILLS).flatMap(([look, [base, joint]]) =>
    [false, true].map(vertical =>
      `<pattern id="tt-wall-pat-${look}${vertical ? '-v' : ''}" width="0.5" height="0.25" patternUnits="userSpaceOnUse"${vertical ? ' patternTransform="rotate(90)"' : ''}>`
      + `<rect x="0" y="0" width="0.5" height="0.25" fill="${base}"/>`
      + `<path d="M0 .125H.5M.25 0V.125M0 .125V.25M.5 .125V.25" stroke="${joint}" stroke-width=".014" fill="none"/></pattern>`)).join("");
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
export function wallLookMarkup(wall) {
  const look = wallLook(wall);
  if (!look) return null;
  const sight = wall.blocks === "sight";
  const cap = wall.door_join ? "butt" : "square";
  let out = "";
  if ((wall.shape === "rect" || wall.shape === "circle") && wall.filled) {
    const [, , edge] = FILLS[look];
    const [a, b] = wall.points || [];
    const vertical = wall.shape === "rect" && a && b && Math.abs(b[1] - a[1]) > Math.abs(b[0] - a[0]);
    out += shapeElement(wall, `fill="url(#tt-wall-pat-${look}${vertical ? '-v' : ''})" stroke="${edge}" stroke-width="0.08"`);
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
