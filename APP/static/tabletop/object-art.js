// Shared top-down drawings for placed objects on the combat table and map editor.
import {CATALOG_KNOWN, CATALOG_FACE, catalogProp} from "./object-art-catalog.js?v=son198r2";

const known = new Set(["door", "gate", "barricade", "wall_section", "pillar", "statue", "ice_block", "crate", "barrel", "chest", "cart", "banner", "rope", "vine", "window", "bell", "custom", ...CATALOG_KNOWN]);

// The face a token shows only when a kind has no drawing; every kind but door, gate and window is drawn below, so
// these are words (screen readers, a broken SVG), never emoji (owner 2026-10-08: objects must look like their label).
export const OBJECT_FACE = {door: "🚪", gate: "⛩", barricade: "Barricade", wall_section: "Wall", pillar: "Pillar", statue: "Statue", ice_block: "Ice", crate: "Crate", barrel: "Barrel", chest: "Chest", cart: "Cart", banner: "Banner", rope: "Rope", vine: "Vines", window: "▢", bell: "Bell", custom: "Object", ...CATALOG_FACE};

// ---------------------------------------------------------------- placed props (owner 2026-10-08 overhaul)
// Seen from straight above in one 64x64 square, lit from the north-west like the trees and bamboo, each standing on
// a soft blurred contact shadow that falls south-east (tall props cast a longer one). No frame round the square.
// Paint is inline style: tabletop.css styles .tt-object-art paths for the door, and a style attribute outranks it.
// Gradient and filter ids are unique per drawing, so many copies on one map (some hidden by fog) never share one.
let serial = 0;
const style = (fill, stroke = "none", width = 1, extra = "") => `style="fill:${fill};stroke:${stroke};stroke-width:${width};stroke-linecap:round;stroke-linejoin:round${extra}"`;
const P = (d, fill, stroke, width, extra) => `<path d="${d}" ${style(fill, stroke, width, extra)}/>`;
const R = (x, y, w, h, fill, rx = 0, stroke, width, extra) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" ${style(fill, stroke, width, extra)}/>`;
const C = (x, y, r, fill, stroke, width, extra) => `<circle cx="${x}" cy="${y}" r="${r}" ${style(fill, stroke, width, extra)}/>`;
const E = (x, y, rx, ry, fill, stroke, width, extra) => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" ${style(fill, stroke, width, extra)}/>`;
const f = n => Math.round(n * 100) / 100;
const stops = list => list.map(([at, color, alpha = 1]) => `<stop offset="${at}" stop-color="${color}" stop-opacity="${alpha}"/>`).join("");
const linear = (id, [x1, y1, x2, y2], list) => `<linearGradient id="${id}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stops(list)}</linearGradient>`;
const radial = (id, [cx, cy, r], list) => `<radialGradient id="${id}" cx="${cx}" cy="${cy}" r="${r}">${stops(list)}</radialGradient>`;

// Light wood, dark wood, iron, stone, bronze: the shared material ramps (NW lit to SE shade).
const WOOD = [[0, "#d4a66b"], [0.55, "#a8773f"], [1, "#6e4824"]];
const DARK_WOOD = [[0, "#9a6d43"], [0.6, "#6b4628"], [1, "#3f2814"]];
const IRON = [[0, "#7d848c"], [0.5, "#4a5058"], [1, "#25292e"]];
const STONE = [[0, "#d9d5ca"], [0.55, "#a9a59a"], [1, "#6c6960"]];
const BRONZE = [[0, "#f3d58e"], [0.45, "#c0903f"], [1, "#5e4019"]];

// A scalloped column top: n flutes round radius r.
function fluted(cx, cy, r, n, depth) {
  let d = "";
  for (let i = 0; i < n; i += 1) {
    const a0 = (i / n) * Math.PI * 2, a1 = ((i + 1) / n) * Math.PI * 2, am = (a0 + a1) / 2;
    const p0 = [cx + Math.cos(a0) * r, cy + Math.sin(a0) * r], p1 = [cx + Math.cos(a1) * r, cy + Math.sin(a1) * r];
    const q = [cx + Math.cos(am) * (r - depth), cy + Math.sin(am) * (r - depth)];
    d += `${i ? "" : `M${f(p0[0])} ${f(p0[1])}`}Q${f(q[0])} ${f(q[1])} ${f(p1[0])} ${f(p1[1])}`;
  }
  return `${d}Z`;
}

// A coil: an Archimedean spiral from r0 to r1 over turns, as a smooth polyline.
function spiral(cx, cy, r0, r1, turns, start = 0) {
  const steps = Math.ceil(turns * 36), pts = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps, a = start + t * turns * Math.PI * 2, r = r0 + (r1 - r0) * t;
    pts.push(`${f(cx + Math.cos(a) * r)} ${f(cy + Math.sin(a) * r)}`);
  }
  return `M${pts.join("L")}`;
}

// An ivy leaf, tip pointing along -y from its stalk at the origin.
const LEAF = "M0 0C-2.6-1-5.6-3.6-4.6-6.8C-3.6-6.4-2.4-6.4-1.6-7.4C-1.4-8.8-.6-9.8 0-10.6C.6-9.8 1.4-8.8 1.6-7.4C2.4-6.4 3.6-6.4 4.6-6.8C5.6-3.6 2.6-1 0 0Z";

// Each prop: its shadow silhouette, whether it stands tall (a longer shadow), and the drawing. u is the id prefix.
function prop(kind, open, u) {
  switch (kind) {
    case "crate": {
      // A planked box: a board frame round the lid, three lid planks, a diagonal brace, iron corner brackets.
      const nails = [[11.5, 11.5], [52.5, 11.5], [11.5, 52.5], [52.5, 52.5], [32, 11.5], [32, 52.5], [11.5, 32], [52.5, 32]];
      return {sil: R(9, 9, 46, 46, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}f`, [0, 0, 1, 1], [[0, "#c18f55"], [1, "#7a5129"]]),
        body: R(9, 9, 46, 46, `url(#${u}f)`, 2, "#3b2612", 1.2)
          + R(14, 14, 36, 36, `url(#${u}w)`)
          + P("M14 26h36M14 38h36", "none", "#5a3a1c", 1.1)
          + P("M16 19.5h12M33 31h14M18 43.5h10M36 21h9", "none", "#e7c28c", 0.7, ";opacity:.7")
          + P("M15 49L49 15", "none", "#3b2612", 7.4) + P("M15 49L49 15", "none", `url(#${u}f)`, 5.4)
          + P("M16.5 46.5L46.5 16.5", "none", "#e3bd85", 0.8, ";opacity:.8")
          + P("M9.6 13.4h44.8M13.4 9.6v44.8M50.6 9.6v44.8M9.6 50.6h44.8", "none", "#3b2612", 0.9)
          + P("M10 10.6h43", "none", "#ecc994", 0.9, ";opacity:.75") + P("M10.6 10v43", "none", "#ecc994", 0.9, ";opacity:.6")
          + P("M9 18V9h9M46 9h9v9M55 46v9h-9M18 55H9v-9", "none", "#2b2e33", 3.2)
          + P("M9.6 17V9.6H17M47 9.6h7.4", "none", "#9aa1a8", 0.7)
          + nails.map(([x, y]) => C(x, y, 0.95, "#d9d2bf", "#2b2e33", 0.4)).join("")};
    }
    case "barrel": {
      // Seen from above: the bulging staves round the rim, an iron hoop, the head's boards, the bung.
      const staves = Array.from({length: 18}, (_, i) => {
        const a = (i / 18) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
        return `M${f(32 + c * 17.6)} ${f(32 + s * 17.6)}L${f(32 + c * 23)} ${f(32 + s * 23)}`;
      }).join("");
      return {sil: C(32, 32, 23.4, "#000"),
        defs: radial(`${u}b`, [0.36, 0.32, 0.75], [[0, "#b98650"], [0.6, "#87582d"], [1, "#4e3117"]])
          + radial(`${u}h`, [0.35, 0.3, 0.8], [[0, "#e1b47a"], [0.6, "#b2814c"], [1, "#7c522a"]]),
        body: C(32, 32, 23, `url(#${u}b)`, "#2e1d0d", 1.2) + P(staves, "none", "#3a2512", 0.8)
          + C(32, 32, 20.4, "none", "#24272b", 2.8) + P("M17 23A17 17 0 0 1 29 13", "none", "#a9b0b7", 1.1)
          + C(32, 32, 17.4, "#3d2712") + C(32, 32, 15.9, `url(#${u}h)`)
          + P("M26.5 17.1V46.9M37.5 17.1V46.9M21 20.4V43.6M43 20.4V43.6", "none", "#6b4523", 0.9)
          + P("M23 22v8M29 19v6M34 28v9M40 22v7", "none", "#f0cf9c", 0.6, ";opacity:.6")
          + C(38.5, 36.5, 2.3, "#2e1c0c", "#d8b077", 0.8) + P("M20.5 25A13 13 0 0 1 28 18.5", "none", "#f6dcae", 1.3, ";opacity:.8")};
    }
    case "chest": {
      // An iron-bound chest; the domed lid lit along its crest. Open: the lid tipped back, coins inside.
      if (open) {
        return {sil: R(9, 4, 46, 46, "#000", 2),
          defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}i`, [0, 0, 0, 1], IRON),
          body: R(9, 4, 46, 12, "#5b1c16", 2, "#2b1b0e", 1.2) + R(12, 6, 40, 8, "#8d2b22", 1) + P("M14 8.5h36", "none", "#c8402f", 1, ";opacity:.7")
            + R(16, 4, 4, 12, `url(#${u}i)`) + R(44, 4, 4, 12, `url(#${u}i)`)
            + R(9, 16, 46, 34, `url(#${u}w)`, 2, "#2b1b0e", 1.2) + R(13.5, 20, 37, 25.5, "#1d140c", 1)
            + P("M14 22h36", "none", "#000", 2, ";opacity:.5")
            + [[22, 33, 4], [29, 30, 4.4], [36, 34, 4], [42, 29, 3.6], [27, 38, 3.4], [33, 26, 3.2], [40, 38, 3]].map(([x, y, r]) => C(x, y, r, "#d9ac4a", "#7a5718", 0.7)).join("")
            + [[21, 31.6], [28.6, 28.4], [35, 32.4], [41, 27.6], [32.4, 24.8]].map(([x, y]) => C(x, y, 1, "#fff2c2")).join("")
            + R(16, 16, 4, 34, `url(#${u}i)`) + R(44, 16, 4, 34, `url(#${u}i)`)
            + P("M10 17h44", "none", "#f0c98f", 0.9, ";opacity:.7") + R(28, 46, 8, 7, "#d4a957", 1, "#5a4214", 0.8)};
      }
      return {sil: R(9, 13, 46, 38, "#000", 3),
        defs: linear(`${u}l`, [0, 0, 0, 1], [[0, "#9c6a39"], [0.32, "#e0b276"], [0.5, "#c08a50"], [1, "#5f3d1c"]])
          + linear(`${u}i`, [0, 0, 0, 1], [[0, "#596068"], [0.32, "#a3aab1"], [0.5, "#5d646c"], [1, "#24282c"]]),
        body: R(9, 13, 46, 38, `url(#${u}l)`, 3, "#2b1b0e", 1.3)
          + P("M10 22.5h44M10 41.5h44", "none", "#5a3a1c", 0.9) + P("M12 31h40", "none", "#f3d39f", 0.7, ";opacity:.6")
          + R(15.5, 13, 5, 38, `url(#${u}i)`, 0.5, "#1c1f23", 0.5) + R(43.5, 13, 5, 38, `url(#${u}i)`, 0.5, "#1c1f23", 0.5)
          + [17.9, 45.9].flatMap(x => [16.5, 26, 36, 47].map(y => C(x, y, 0.9, "#d6d9dc", "#1c1f23", 0.3))).join("")
          + R(9, 13, 46, 38, "none", 3, "#2a2e33", 2)
          + P("M9 19.5V13h6.5M48.5 13H55v6.5M55 44.5V51h-6.5M15.5 51H9v-6.5", "none", "#1f2327", 2.6)
          + R(27.5, 45, 9, 9, "#d4a957", 1.2, "#5a4214", 0.9) + P("M32 48.2v3.2", "none", "#2a1d08", 1.4) + C(32, 48.2, 1.1, "#2a1d08")};
    }
    case "cart": {
      // A hand cart facing east: a planked bed with side rails, two wheels seen edge-on, the shafts reaching forward.
      return {sil: P("M7 14h40v36H7zM14 6h26v8H14zM14 50h26v8H14zM46 24l16 3v10l-16 3z", "#000"),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}d`, [0, 0, 0, 1], DARK_WOOD) + linear(`${u}t`, [0, 0, 0, 1], [[0, "#8a7a68"], [0.5, "#4b3a2a"], [1, "#2c2016"]]),
        body: P("M45 25.5L62 28.5M45 38.5L62 35.5", "none", "#3f2814", 3.6) + P("M45 25.5L62 28.5M45 38.5L62 35.5", "none", "#b88a55", 2.2)
          + P("M58 28v8", "none", "#5b3c1e", 2.2)
          + R(13, 6.5, 28, 7, `url(#${u}t)`, 3.5, "#1f1710", 1) + R(13, 50.5, 28, 7, `url(#${u}t)`, 3.5, "#1f1710", 1)
          + P("M15 8.6h24M15 52.6h24", "none", "#b8c0c8", 0.8, ";opacity:.7") + R(24.5, 4, 5, 3.4, "#3a3f45", 1) + R(24.5, 56.6, 5, 3.4, "#3a3f45", 1)
          + R(7, 14, 40, 36, `url(#${u}w)`, 1.5, "#3b2612", 1.2)
          + P("M8 21.5h38M8 28.5h38M8 35.5h38M8 42.5h38", "none", "#6b4523", 0.9)
          + P("M11 18h10M25 25h14M12 32h9M28 39h12M15 46h9", "none", "#f0cf9c", 0.6, ";opacity:.55")
          + R(7, 14, 40, 4, `url(#${u}d)`, 1) + R(7, 46, 40, 4, `url(#${u}d)`, 1) + R(7, 14, 4, 36, `url(#${u}d)`, 1) + R(43, 14, 4, 36, `url(#${u}d)`, 1)
          + P("M8 15h38M8 15v34", "none", "#d9ae78", 0.8, ";opacity:.7")
          + [[9, 16], [45, 16], [9, 48], [45, 48], [27, 16], [27, 48]].map(([x, y]) => C(x, y, 0.9, "#c9c2ae", "#2b2e33", 0.3)).join("")
          + P("M13 25.5Q13 21 19 21.5L27 23Q30 27 30 32Q30 37 27 41L19 42.5Q13 43 13 38.5Z", "#c9b38a", "#5e4c2c", 0.9)
          + P("M16 24.5Q22 23.5 26 26M15.5 35Q21 36 26 34", "none", "#8d7a55", 0.9, ";opacity:.8") + P("M16 23.5Q21 22.6 25 24", "none", "#efe2c2", 1, ";opacity:.8")
          + P("M30 29.5L34.5 27.5M30 34.5L34.5 36.5M30 32H35", "none", "#a28e66", 1.6) + P("M29.6 29v6", "none", "#4a3a20", 1.8)};
    }
    case "pillar": {
      // A tall stone column seen from above: the round, fluted top with its moulded ring, lit on the north-west,
      // standing on a low round footing and throwing a long shadow south-east (that shadow is what says "tall").
      return {tall: true, sil: C(32, 32, 21, "#000") + P("M17.2 46.8L46.8 17.2L60 31L31 60Z", "#000"),
        defs: radial(`${u}f`, [0.4, 0.38, 0.7], STONE)
          + radial(`${u}c`, [0.36, 0.33, 0.72], [[0, "#fbf9f2"], [0.5, "#d6d1c3"], [0.85, "#9b968a"], [1, "#6a665d"]]),
        body: C(32, 32, 25, `url(#${u}f)`, "#4a4740", 1) + C(32, 32, 23, "none", "#ece8dc", 0.8, ";opacity:.5")
          + C(34, 34.5, 21, "#000", "none", 1, ";opacity:.3")
          + P(fluted(32, 32, 20.5, 24, 2.2), `url(#${u}c)`, "#4f4c45", 1.1)
          + C(32, 32, 15.5, "none", "#7b766b", 1.4) + C(32, 32, 14.3, "none", "#fffdf6", 0.9, ";opacity:.75")
          + C(32, 32, 9.5, "none", "#a39e92", 0.8, ";opacity:.8")
          + P("M19.5 27A13.5 13.5 0 0 1 27 19", "none", "#ffffff", 1.8, ";opacity:.8")};
    }
    case "statue": {
      // A figure in old bronze on a stepped stone plinth, facing east: head and topknot, broad shoulders, both hands
      // on the hilt of a sword held point-forward. The sword and the head make it a person, the plinth a statue.
      const blade = "M45 32H55";
      return {tall: true, sil: `<g transform="translate(32 32) scale(1.2) translate(-32 -32)">${R(24, 16, 15, 32, "#000", 7)}${P(blade, "none", "#000", 3)}</g>`, base: R(8, 8, 48, 48, "#000", 2),
        defs: linear(`${u}p`, [0, 0, 1, 1], STONE) + radial(`${u}b`, [0.3, 0.28, 0.9], [[0, "#b5e0c8"], [0.45, "#5c9a80"], [1, "#24473c"]])
          + radial(`${u}h`, [0.3, 0.28, 0.9], [[0, "#d4f2df"], [0.5, "#6aa88c"], [1, "#2c5246"]]),
        body: R(8, 8, 48, 48, `url(#${u}p)`, 2, "#55524b", 1.2) + R(13, 13, 38, 38, `url(#${u}p)`, 1.5, "#6f6b62", 0.9)
          + P("M9.5 54.5V9.5h45M14.5 49.5V14.5h35", "none", "#f4f1e8", 1, ";opacity:.6")
          + `<g transform="translate(32 32) scale(1.2) translate(-32 -32)">`
          + P("M27 18Q19 32 27 46L31 44Q26 32 31 20Z", "#2f5a4c", "#173028", 0.8)
          + R(24.5, 16.5, 14, 31, `url(#${u}b)`, 7, "#173028", 1)
          + P("M35 20Q42 24 43.5 30M35 44Q42 40 43.5 34", "none", "#173028", 4.4) + P("M35 20Q42 24 43.5 30M35 44Q42 40 43.5 34", "none", `url(#${u}h)`, 3)
          + P(blade, "none", "#2a2f33", 3) + P(blade, "none", "#e9eef0", 1.6) + P("M45 27.5v9", "none", "#c49a3a", 2) 
          + C(44, 32, 2.6, `url(#${u}h)`, "#173028", 0.8)
          + C(31.5, 32, 6, `url(#${u}h)`, "#173028", 1) + C(26.4, 32, 2.6, "#2f5a4c", "#173028", 0.7)
          + P("M28.5 28Q31 25.5 34.5 27", "none", "#effcf3", 1.1, ";opacity:.85") + P("M26 19Q29 17.5 33 18", "none", "#d3efdd", 1, ";opacity:.7") + "</g>"};
    }
    case "ice_block": {
      // A clear, faceted block of ice: a bright flat top, cold blue sides, white edges, a crack and a glint.
      return {sil: P("M12 20L31 9L53 15L57 38L45 55L19 53L7 37Z", "#000"),
        defs: linear(`${u}t`, [0, 0, 1, 1], [[0, "#f4fdff", 0.95], [0.6, "#bfe8f2", 0.85], [1, "#8fd0e2", 0.85]])
          + linear(`${u}s`, [0, 0, 1, 1], [[0, "#7cc4da", 0.85], [1, "#2f7d9c", 0.92]]),
        body: P("M12 20L31 9L53 15L57 38L45 55L19 53L7 37Z", `url(#${u}s)`, "#e6fbff", 1.2)
          + P("M12 20L31 9L53 15L46 21L30 16L19 24Z", "#d9f5fb", "none", 1, ";opacity:.85")
          + P("M7 37L12 20L19 24L20 42Z", "#a5dcea", "none", 1, ";opacity:.8")
          + P("M20 42L19 53L45 55L57 38L48 37L41 46Z", "#2c6f8e", "none", 1, ";opacity:.55")
          + P("M19 24L30 16L46 21L48 37L41 46L20 42Z", `url(#${u}t)`, "#ffffff", 1.1)
          + P("M19 24L30 16L46 21", "none", "#ffffff", 1.6) + P("M46 21L48 37L41 46L20 42", "none", "#5aaecb", 0.9)
          + P("M27 22l5 7-3 5 6 6M38 25l2 5", "none", "#ffffff", 0.9, ";opacity:.85")
          + P("M24 27l9-4", "none", "#ffffff", 2, ";opacity:.6")
          + P("M41 18.5l1.2-3 1.2 3 3 1.2-3 1.2-1.2 3-1.2-3-3-1.2z", "#ffffff")};
    }
    case "banner": {
      // A war banner on a weighted stand: the pole's gilt finial, lacquer-red cloth streaming east with a gold device.
      return {tall: true, sil: P("M18 24C30 20 40 26 52 22L61 25L54 32L61 39C48 42 34 37 18 40Z", "#000"), base: C(17, 32, 10, "#000"),
        defs: linear(`${u}c`, [0, 0, 0, 1], [[0, "#e0634e"], [0.45, "#b5352a"], [1, "#5f1712"]]) + radial(`${u}s`, [0.35, 0.3, 0.8], [[0, "#d6d1c4"], [0.6, "#8e897d"], [1, "#4e4b44"]])
          + radial(`${u}g`, [0.35, 0.3, 0.8], [[0, "#fff1c4"], [0.5, "#d4a957"], [1, "#7a5a1e"]]),
        body: C(17, 32, 10, `url(#${u}s)`, "#3a3833", 1.1) + C(17, 32, 6.5, "none", "#6d695f", 0.8)
          + P("M19 24.5C30 20.5 40 26.5 52 22.5L60.5 25.5L53.5 32L60.5 38.5C48 41.5 34 36.5 19 39.5Z", `url(#${u}c)`, "#3b0c08", 1)
          + P("M24 23.8C32 22 40 27 50 24M24 39C34 36.5 42 39.5 52 38.5", "none", "#d4a957", 1.3)
          + P("M30 22.5C31 28 31 34 30 38.5M43 25C44 30 44 34 43 39", "none", "#3b0c08", 1.4, ";opacity:.5")
          + P("M36 24.5C37 29 37 34 36 38", "none", "#f28b72", 1.2, ";opacity:.45")
          + C(37.5, 31.5, 4.2, "none", "#f0d08a", 1.4) + P("M37.5 28.6v5.8M34.8 31.5h5.4", "none", "#f0d08a", 1.2)
          + P("M19 23v17", "none", "#2b1a0c", 3) + P("M19 23v17", "none", "#9b7041", 1.6)
          + C(17, 32, 3.4, `url(#${u}g)`, "#4a3610", 0.8) + C(16, 31, 1, "#fff7da")};
    }
    case "rope": {
      // A coil of rope lying flat: three and a half tight turns of twisted strand and a loose frayed end.
      const coil = spiral(29, 30, 3.2, 19.6, 3.6, 0.4);
      const end = 0.4 + 3.6 * Math.PI * 2;
      const ex = f(29 + Math.cos(end) * 19.6), ey = f(30 + Math.sin(end) * 19.6);
      const tail = `M${ex} ${ey}C${f(ex + 6)} ${f(ey + 2)} 52 44 57 52`;
      return {sil: C(29, 30, 22, "#000") + P(tail, "none", "#000", 5),
        body: P(`${coil}${tail}`, "none", "#3d2c14", 6) + P(`${coil}${tail}`, "none", "#c09a5c", 4.4)
          + P(`${coil}${tail}`, "none", "#7c5b2c", 4.4, ";stroke-dasharray:1.1 2.1;stroke-linecap:butt")
          + P(`${coil}${tail}`, "none", "#f0d6a0", 1, ";opacity:.55;transform:translate(-.7px,-.7px)")
          + P("M57 52l2.5 1.2M57 52l1.4 2.6M57 52l2.8-.6", "none", "#d9bd85", 0.9)};
    }
    case "vine": {
      // Creeping vines across the ground: twisting stems, ivy leaves in three greens, curling tendrils, two buds.
      const stems = "M4 50C14 46 18 38 26 36S40 38 44 28S52 12 60 8M10 14C18 18 22 26 26 36M26 36C30 44 38 50 48 56M44 28C50 32 54 38 60 40";
      const leaves = [[8, 48, -60, 1.1], [15, 44, 20, 1], [20, 38, -40, 1.1], [27, 33, 10, 1.2], [33, 37, 120, 1], [38, 34, -20, 1.1], [43, 25, 50, 1.2],
        [46, 18, -30, 1], [52, 12, 40, 1.1], [57, 9, -70, 0.9], [13, 17, 80, 1], [18, 22, -50, 1.1], [23, 28, 70, 1], [30, 43, -110, 1.1],
        [36, 48, 30, 1], [42, 52, -80, 1.1], [48, 33, 140, 1], [54, 37, 30, 1.1], [58, 41, 110, 0.9], [9, 30, -20, 0.8], [52, 50, -40, 0.8]];
      const greens = ["#4f8a30", "#2f5f24", "#8cbc4e"];
      const leafAt = ([x, y, a, s], paint) => `<g transform="translate(${x} ${y}) rotate(${a}) scale(${s})">${paint}</g>`;
      return {sil: P(stems, "none", "#000", 4) + leaves.map(leaf => leafAt(leaf, P(LEAF, "#000"))).join(""),
        body: P(stems, "none", "#2c3f1c", 3) + P(stems, "none", "#6f7a3a", 1.6)
          + P("M48 33q4-2 3-6t-4-2M20 38q-5 1-5-3t4-3M36 48q1 5 5 4", "none", "#7d8f45", 1, ";opacity:.9")
          + leaves.map((leaf, i) => leafAt(leaf, P(LEAF, greens[i % 3], "#16260f", 0.9) + P("M0-1V-8", "none", "#c9e08e", 0.6, ";opacity:.8"))).join("")
          + [[39, 41], [16, 24], [50, 25], [31, 52]].map(([x, y]) => [0, 1, 2, 3, 4].map(k => C(f(x + Math.cos(k * 1.257) * 1.5), f(y + Math.sin(k * 1.257) * 1.5), 1.1, "#f4ecd0", "#8a7a52", 0.3)).join("") + C(x, y, 0.8, "#e8b84a")).join("")};
    }
    case "bell": {
      // A temple bell under its beam. Seen from straight above a bell is only a disc, which reads as a shield; so,
      // like a map icon, it is drawn from a little to the south: the beam on two posts, the bell's dome, waist bands,
      // bosses and flared mouth hanging below it, and its shadow on the ground.
      const bosses = [24, 28.5, 33, 37.5].flatMap(y => [26, 30, 34, 38].map(x => C(x + (y - 31) * 0.05, y, 0.9, "#f6dc98", "#5e4019", 0.3))).join("");
      return {tall: true, upright: true, sil: E(32, 50, 20, 6, "#000") + R(4, 52, 8, 5, "#000") + R(52, 52, 8, 5, "#000"),
        defs: linear(`${u}b`, [0, 0, 1, 0], [[0, "#6d4b1d"], [0.28, "#f6dc98"], [0.5, "#c69545"], [1, "#4a3110"]]) + linear(`${u}w`, [0, 0, 1, 0], DARK_WOOD)
          + linear(`${u}m`, [0, 0, 0, 1], DARK_WOOD),
        body: R(6, 12, 6, 44, `url(#${u}w)`, 1, "#24160a", 1) + R(52, 12, 6, 44, `url(#${u}w)`, 1, "#24160a", 1)
          + R(4, 53, 10, 4, "#6c685f", 1, "#33312c", 0.8) + R(50, 53, 10, 4, "#6c685f", 1, "#33312c", 0.8)
          + P("M2 13Q4 9 9 10H55Q60 9 62 13L60 16H4Z", `url(#${u}m)`, "#24160a", 1) + P("M5 11.8H59", "none", "#d1a571", 0.8, ";opacity:.6")
          + P("M32 16v4", "none", "#3a3f45", 2.4) + E(32, 21, 3, 2.2, "none", "#3a3f45", 1.6)
          + P("M22 26Q22 21 32 21Q42 21 42 26L43.5 43Q45 47 49 48.5Q32 52 15 48.5Q19 47 20.5 43Z", `url(#${u}b)`, "#3f2a0c", 1)
          + P("M21.3 31.5Q32 33 42.7 31.5M21 40Q32 41.6 43 40", "none", "#5e4019", 1) + bosses
          + E(32, 48.6, 17, 3.2, "#2a1b07", "#7a5a22", 0.8) + E(32, 48.2, 12, 1.6, "#120b03")
          + P("M25 24Q24.5 32 24 44", "none", "#fff4cf", 1.4, ";opacity:.6") + P("M37 41q2 3 1 6", "none", "#5fa58a", 1.6, ";opacity:.5")};
    }
    case "wall_section": {
      // A block of dressed masonry filling the square's width, east to west: three courses of stone, lit tops, a
      // shadowed southern face.
      const rows = [[0, 12, 25, 37, 51, 64], [0, 6, 19, 31, 44, 57, 64], [0, 10, 22, 35, 48, 64]];
      const tones = ["#7d786f", "#6c6861", "#86817a", "#73706a", "#8c867c", "#68645e", "#7f7a71", "#77726a"];
      let blocks = "", n = 0;
      rows.forEach((xs, row) => {
        const y = 13 + row * 12;
        for (let i = 0; i + 1 < xs.length; i += 1, n += 1) {
          const x0 = xs[i] + 0.5, x1 = xs[i + 1] - 0.5;
          blocks += R(f(x0), y + 0.5, f(x1 - x0), 11, tones[n % tones.length], 1, "#3e3b36", 0.8)
            + P(`M${f(x0 + 1)} ${y + 10.2}V${y + 1.5}H${f(x1 - 1)}`, "none", "#e2dccd", 0.9, ";opacity:.75")
            + P(`M${f(x0 + 1.5)} ${y + 10.9}H${f(x1 - 0.8)}V${y + 2}`, "none", "#4a463f", 0.9, ";opacity:.6");
        }
      });
      return {sil: R(0, 13, 64, 37, "#000"),
        body: R(0, 12.5, 64, 37.5, "#2f2c28") + blocks + R(0, 49, 64, 3.5, "#3b3832") + P("M0 52.5h64", "none", "#25231f", 1)
          + P("M6 17l2 1M40 30l3-1M22 42l1 2M52 18l-2 2", "none", "#5d5850", 0.8)};
    }
    case "barricade": {
      // A cheval-de-frise, east to west: a log with sharpened stakes driven through it in crossed pairs, lashed with rope.
      const xs = [10, 21, 32, 43, 54];
      const stake = (x0, y0, x1, y1) => {
        const dx = x1 - x0, dy = y1 - y0, len = Math.hypot(dx, dy), nx = -dy / len * 1.6, ny = dx / len * 1.6;
        const b0 = [x0 + dx * 0.16, y0 + dy * 0.16], b1 = [x1 - dx * 0.16, y1 - dy * 0.16];
        const shaft = `M${f(b0[0] + nx)} ${f(b0[1] + ny)}L${f(b1[0] + nx)} ${f(b1[1] + ny)}L${f(x1)} ${f(y1)}L${f(b1[0] - nx)} ${f(b1[1] - ny)}L${f(b0[0] - nx)} ${f(b0[1] - ny)}L${f(x0)} ${f(y0)}Z`;
        const points = `M${f(b0[0] + nx)} ${f(b0[1] + ny)}L${f(x0)} ${f(y0)}L${f(b0[0] - nx)} ${f(b0[1] - ny)}ZM${f(b1[0] + nx)} ${f(b1[1] + ny)}L${f(x1)} ${f(y1)}L${f(b1[0] - nx)} ${f(b1[1] - ny)}Z`;
        return P(shaft, "#8a6036", "#3b2612", 0.8) + P(points, "#e6cf9f", "#5b3f22", 0.5) + P(`M${f(b0[0] + nx * 0.4)} ${f(b0[1] + ny * 0.4)}L${f(b1[0] + nx * 0.4)} ${f(b1[1] + ny * 0.4)}`, "none", "#c79a63", 0.6);
      };
      const stakes = xs.map(x => stake(x - 6, 9, x + 6, 55) + stake(x + 6, 9, x - 6, 55)).join("");
      return {sil: P("M3 28h58v8H3z", "#000") + xs.map(x => P(`M${x - 6} 9L${x + 6} 55M${x + 6} 9L${x - 6} 55`, "none", "#000", 3.4)).join(""),
        defs: linear(`${u}l`, [0, 0, 0, 1], [[0, "#9c7448"], [0.35, "#c59b66"], [1, "#4f3519"]]),
        body: stakes + R(3, 28, 58, 8, `url(#${u}l)`, 4, "#2e1d0d", 1)
          + P("M8 31h9M22 33h12M40 30.5h10M50 33.5h7", "none", "#5b3f22", 0.8) + E(4.6, 32, 1.8, 3.6, "#d9b98a", "#5b3f22", 0.6) + E(59.4, 32, 1.8, 3.6, "#d9b98a", "#5b3f22", 0.6)
          + xs.map(x => P(`M${x - 2} 28.5l4 7M${x + 2} 28.5l-4 7`, "none", "#d8c58f", 1.3)).join("")};
    }
    case "custom": {
      // An unnamed object is drawn as a marker post: a squared timber post on a stone footing, its end grain on top,
      // a lacquer-red band and a paper tag pinned to it, standing tall enough to throw a long shadow.
      return {tall: true, sil: R(22, 22, 20, 20, "#000", 2) + P("M22 42L42 22L56 36L36 56Z", "#000"), base: P("M20 14H44L50 20V44L44 50H20L14 44V20Z", "#000"),
        defs: linear(`${u}s`, [0, 0, 1, 1], STONE) + linear(`${u}w`, [0, 0, 1, 1], WOOD),
        body: P("M20 14H44L50 20V44L44 50H20L14 44V20Z", `url(#${u}s)`, "#4a4740", 1) + P("M15.5 43V20.6L20.6 15.5H43", "none", "#f1ede2", 0.9, ";opacity:.6")
          + R(21.5, 21.5, 21, 21, `url(#${u}w)`, 1.5, "#3b2612", 1.1)
          + C(32, 32, 7.5, "none", "#7a5129", 0.8) + C(32, 32, 4.5, "none", "#7a5129", 0.8) + C(32, 32, 1.6, "#7a5129")
          + P("M23.5 25.5Q26 23 29 23.5", "none", "#f2d3a0", 1, ";opacity:.8")
          + P("M21.5 36.5h21", "none", "#8d2b22", 3) + P("M21.5 35.5h21", "none", "#e0634e", 0.8, ";opacity:.6")
          + P("M42.5 26L52 28L50.5 41L42.5 39Z", "#efe0b0", "#8a7444", 0.7) + P("M45.5 30.5l4 .8M45.2 33.5l4 .8M45 36.5l3 .6", "none", "#b5352a", 1)
          + C(43.5, 27.5, 1, "#3a3f45")};
    }
    default: return CATALOG_KNOWN.has(kind) ? catalogProp(kind, open, u) : null;
  }
}

// ---------------------------------------------------------------- openings in a wall (owner 2026-10-08, phase 5)
// A door, gate or window fills a one-square gap in a straight wall (wall-openings.js mounts it): at rotation 0 the wall
// runs east-west through y = 32 at a drawn wall's thickness (y 25..39), the stone jambs end the wall flush at x 0..8 and
// 56..64, and the leaf or frame spans the gap between them. Open: the leaf swings 90 degrees about its hinge into the
// square beside the wall, with a faint swing arc (class tt-art-arc). Only the look: the rules square, mount and open
// state come from the map and the fight.
//
// A door is also the one map object a player has to spot from straight overhead (owner 2026-10-21: "i cant see any
// doors"). So the leaf carries the marks that say "door" at a glance, in the wall gap itself: the planked slab, an iron
// hinge edge with knuckles standing proud at the hinged jamb, a brass lever and knob at the latch edge reaching into the
// room, and a worn threshold line across the gap. Locked and jammed doors get a small padlock or a wedged bar, so the
// state reads without opening the hover card.
function openingArt(kind, {open, locked = false, jammed = false} = {}, rotate) {
  serial = (serial + 1) % 1e9;
  const u = `tto${serial}`;
  // Stone jambs a little proud of the wall (a drawn wall is 14 units thick at y 25..39), ending it flush at the gap.
  const jamb = x => R(x, 21, 9, 22, `url(#${u}j)`, 1.4, "#26241f", 1.1) + P(`M${x + 1.2} 41.5V22.4H${x + 7.8}`, "none", "#eeeadf", 1, ";opacity:.8")
    + P(`M${x + 1} 32h7`, "none", "#5b5750", 0.7, ";opacity:.6");
  const jambs = jamb(0) + jamb(55);
  // the threshold: a lighter worn sill across the gap, so the doorway reads with the leaf open
  const sill = R(9, 26, 46, 12, `url(#${u}s)`, 0, "#3a3732", 0.6) + P("M11 32h42", "none", "#5d5850", 0.7, ";opacity:.45");
  const arc = d => P(d, "none", "#f6e7c4", 1.2, ";opacity:.5;stroke-dasharray:3 2.5").replace("<path ", '<path class="tt-art-arc" ');
  const defs = `<defs><filter id="${u}f" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.7"/></filter>`
    + linear(`${u}j`, [0, 0, 1, 1], [[0, "#cdc8bc"], [0.55, "#9a958a"], [1, "#68645c"]])
    + linear(`${u}s`, [0, 0, 0, 1], [[0, "#aaa496"], [1, "#807b70"]])
    + linear(`${u}w`, [0, 0, 0, 1], [[0, "#e0aa6c"], [0.42, "#b47c45"], [1, "#5e3c1c"]])
    + linear(`${u}i`, [0, 0, 0, 1], [[0, "#c2c9cf"], [0.5, "#6a737b"], [1, "#2c3136"]])
    + radial(`${u}b`, [0.34, 0.3, 0.8], BRONZE) + "</defs>";
  const shade = body => `<g filter="url(#${u}f)" style="opacity:.5"><g transform="translate(2.2 3.2)">${body}</g></g>`;
  let leaves = "", silhouette = "";
  if (kind === "door") {
    // The planked slab spans the wall gap. From straight overhead these are the marks that read as "door": the leaf,
    // the iron hinge edge with its knuckles standing proud of both wall faces at the hinged jamb, the brass lever and
    // knob reaching into the room at the latch edge, and the worn threshold line. Open, the same leaf (handle and all)
    // swings 90 degrees about the hinge, leaving the gap clear.
    const leaf =
      `<g class="tt-door-leaf">`
      + R(9, 25.2, 46, 13.6, `url(#${u}w)`, 1.2, "#2a190a", 1.2)
      + P("M16.5 25.8v12.4M24 25.8v12.4M31.5 25.8v12.4M39 25.8v12.4M46.5 25.8v12.4", "none", "#4a2e14", 0.9)
      + P("M10 26.4h44", "none", "#ffd9a4", 1.1, ";opacity:.85")
      + P("M10.2 38.2h43.6", "none", "#3a2410", 0.9, ";opacity:.7")
      // A raised centre panel: a lit north edge and a shaded south edge make it read as a slab, not a wall band.
      + R(13.2, 27.4, 32, 9.2, "none", 0.8, "#f0c690", 0.9)
      + R(13.2, 33.4, 32, 3.2, "none", 0.6, "#5a3a1c", 0.7, ";opacity:.55")
      // Two iron straps run from the hinge edge across the leaf.
      + R(10, 26.6, 15, 2.3, `url(#${u}i)`, 0.6, "#1c1f23", 0.4)
      + R(10, 34.9, 15, 2.3, `url(#${u}i)`, 0.6, "#1c1f23", 0.4)
      + C(11, 27.75, 0.9, "#d6d9dc", "#1c1f23", 0.3) + C(11, 36.05, 0.9, "#d6d9dc", "#1c1f23", 0.3)
      + `</g>`;
    // The hinge edge: an iron strip down the hinge jamb and two round knuckles standing proud of the leaf's faces, so
    // the side the door is hinged on is obvious from above.
    const hinge =
      `<g class="tt-door-hinge">`
      + R(9.1, 23.4, 2.8, 17.2, `url(#${u}i)`, 0.5, "#15181b", 0.7)
      + C(9, 22.6, 2.7, `url(#${u}i)`, "#15181b", 0.9) + C(8.2, 21.8, 1, "#e6ecef")
      + C(9, 41.4, 2.7, `url(#${u}i)`, "#15181b", 0.9) + C(8.2, 40.6, 1, "#8f979e")
      + `</g>`;
    // The latch edge: a brass backplate and a lever with a round knob, reaching past the leaf into the room so the
    // handle is still obvious at the size of one square.
    const handle =
      `<g class="tt-door-handle">`
      + R(44.4, 29.2, 5.4, 5.6, `url(#${u}b)`, 1.1, "#4c3a12", 0.8)
      + P("M50.2 32.2v7.6", "none", "#4c3a12", 3.6) + P("M50.2 32.2v7.6", "none", "#e2bd62", 2)
      + C(50.2, 40.6, 3.1, `url(#${u}b)`, "#4c3a12", 0.9) + C(49.1, 39.4, 1, "#fff3c8")
      + `</g>`;
    // Locked: a small brass padlock in the middle of the leaf. Jammed: a bar wedged across the whole doorway.
    const lock = locked
      ? `<g class="tt-door-lock">`
        + R(29.4, 28.6, 8.2, 6.8, `url(#${u}b)`, 1.2, "#3f2f0c", 0.9)
        + P("M31.2 28.6v-2.8a2.3 2.3 0 0 1 4.6 0v2.8", "none", "#2c3136", 1.5)
        + C(33.5, 32, 1.2, "#2a1d08") + P("M33.5 33v2.1", "none", "#2a1d08", 0.9)
        + `</g>`
      : "";
    const bar = jammed
      ? `<g class="tt-door-bar">`
        + P("M11.5 21.5L52.5 42.5", "none", "#2e1d0d", 5.6) + P("M11.5 21.5L52.5 42.5", "none", "#b07a40", 3.2)
        + R(8.6, 19.4, 5.6, 3.6, "#3a3f45", 0.7, "#15181b", 0.6) + R(49.8, 41, 5.6, 3.6, "#3a3f45", 0.7, "#15181b", 0.6)
        + `</g>`
      : "";
    // A subtle threshold line across the gap, kept outside the swinging leaf so an open door leaves it in place.
    const threshold = `<g class="tt-door-threshold">`
      + P("M9.5 32h45", "none", "#f4ead2", 1.2, ";opacity:.62")
      + P("M10 30.9h44M10 33.1h44", "none", "#4e4a43", 0.5, ";opacity:.5")
      + `</g>`;
    silhouette = open ? R(3, 32, 12, 46, "#000") : R(9, 25.2, 46, 13.6, "#000");
    leaves = open
      ? threshold + arc("M55 32A46 46 0 0 1 9 78") + `<g transform="rotate(90 9 32)">${leaf}${handle}${lock}${bar}</g>` + hinge
      : threshold + leaf + handle + lock + bar + hinge;
  } else if (kind === "gate") {
    // Double wrought-iron leaves meeting in the middle: a frame, pickets with spear finials, a brass ring latch.
    const half = x0 => R(x0, 27, 23, 10, "#1c1f23", 0.8, "none", 1, ";opacity:.55") + R(x0, 27, 23, 10, "none", 0.8, `url(#${u}i)`, 2)
      + Array.from({length: 5}, (_, i) => C(x0 + 2.8 + i * 4.35, 32, 1.9, `url(#${u}i)`, "#1c1f23", 0.7) + C(x0 + 2.4 + i * 4.35, 31.4, 0.7, "#eef2f4")).join("")
      + P(`M${x0 + 1} 27.8h21`, "none", "#e3e8ec", 0.8, ";opacity:.8");
    const west = half(9), east = half(32);
    const hinges = C(9, 32, 2.6, "#3a3f45", "#15181b", 0.9) + C(55, 32, 2.6, "#3a3f45", "#15181b", 0.9);
    silhouette = open ? R(4, 32, 10, 23, "#000") + R(50, 32, 10, 23, "#000") : R(9, 27, 46, 10, "#000");
    leaves = open
      ? arc("M32 32A23 23 0 0 1 9 55") + arc("M32 32A23 23 0 0 0 55 55")
        + `<g transform="rotate(90 9 32)">${west}</g><g transform="rotate(-90 55 32)">${east}</g>` + hinges
      : west + east + C(32, 32, 2.6, "none", "#e2bd62", 1.5) + hinges;
  } else {
    // A window set in the wall: a stone sill, a lacquer-red frame and paper-screen panes on a wooden lattice. Open, the
    // two wooden shutters fold out to the south side of the wall.
    const frame = R(9, 26, 46, 12, "#8d2b22", 0.8, "#2a0e0a", 1);
    const panes = R(11.5, 28.5, 41, 7, "#f2ead2", 0.3) + P("M18.3 28.5v7M25.1 28.5v7M31.9 28.5v7M38.7 28.5v7M45.5 28.5v7M11.5 32h41", "none", "#6a4a2a", 0.8)
      + P("M12 29.2h40", "none", "#ffffff", 0.8, ";opacity:.7");
    const shutter = x0 => R(x0, 27, 23, 9, `url(#${u}w)`, 1, "#2a190a", 1)
      + P(`M${x0 + 4.6} 27.6v7.8M${x0 + 9.2} 27.6v7.8M${x0 + 13.8} 27.6v7.8M${x0 + 18.4} 27.6v7.8`, "none", "#4a2e14", 0.8);
    silhouette = open ? R(4, 38, 10, 23, "#000") + R(50, 38, 10, 23, "#000") : R(9, 26, 46, 12, "#000");
    leaves = open
      ? frame + R(11.5, 28.5, 41, 7, "#1b1a1c", 0.3) + arc("M32 38A23 23 0 0 1 9 61") + arc("M32 38A23 23 0 0 0 55 61")
        + `<g transform="rotate(90 9 38)">${shutter(9)}</g><g transform="rotate(-90 55 38)">${shutter(32)}</g>`
      : frame + panes;
  }
  return `<svg viewBox="0 0 64 64" aria-hidden="true" class="tt-object-art tt-opening-art" data-object-kind="${kind}" data-open="${open ? "1" : "0"}">${defs}`
    + `<g${rotate}>${shade(R(0, 21, 9, 22, "#000") + R(55, 21, 9, 22, "#000") + silhouette)}${sill}${leaves}${jambs}</g></svg>`;
}

export function objectArt(kind, {open = false, state = null, locked = false, jammed = false, rotation = null, facing = null} = {}) {
  if (!known.has(kind)) return null;
  const turn = rotation !== null && rotation !== undefined && rotation !== "" && Number.isFinite(Number(rotation))
    ? Number(rotation) : ({east: 0, south: 90, west: 180, north: 270}[String(facing || "").toLowerCase()] ?? 0);
  let rotate = turn ? ` transform="rotate(${turn} 32 32)"` : "";
  if (kind === "door" || kind === "gate" || kind === "window")
    return openingArt(kind, {open: open || state === "open", locked: locked || state === "locked", jammed: jammed || state === "jammed"}, rotate);
  serial = (serial + 1) % 1e9;
  const u = `tto${serial}`;
  const drawing = prop(kind, open || state === "open", u);
  if (!drawing) return null;
  // The shadow keeps falling south-east whichever way the prop is turned; a tall prop throws it further.
  const [dx, dy] = drawing.tall ? [6, 8] : [2.4, 3.4];
  // The bell is drawn from a little to the south, so it always hangs upright rather than turning on its side.
  if (drawing.upright) rotate = "";
  const shadow = `<g filter="url(#${u}shadow)" style="opacity:${drawing.tall ? 0.42 : 0.5}"><g transform="translate(${dx} ${dy})"><g${rotate}>${drawing.sil}</g></g>`
    + (drawing.base ? `<g transform="translate(2.4 3.4)"><g${rotate}>${drawing.base}</g></g>` : "") + "</g>";
  const defs = `<defs><filter id="${u}shadow" x="-25%" y="-25%" width="150%" height="150%"><feGaussianBlur stdDeviation="${drawing.tall ? 2.6 : 1.9}"/></filter>${drawing.defs || ""}</defs>`;
  return `<svg viewBox="0 0 64 64" aria-hidden="true" class="tt-object-art tt-prop-art" data-object-kind="${kind}">${defs}${shadow}<g${rotate}>${drawing.body}</g></svg>`;
}
