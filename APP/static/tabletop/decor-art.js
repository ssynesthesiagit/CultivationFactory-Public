// Biome asset packs (owner 2026-10-08: "make a bunch more assets too, different bioms and stuff"). Each piece is drawn
// top-down in one 64x64 square, lit from the north-west, on its own soft contact shadow, like the props and terrain.
// A piece either has NO rules (`rule: null`: map decoration only, saved in the map's `decor` list and never seen by
// the fight) or uses an EXISTING rules terrain type (`rule: "SIMPLE_COVER"` or `"DIFFICULT"`: saved as an ordinary
// terrain row whose `look` is this piece, so it behaves exactly like any other cover or difficult square).
import {blade, r2, rock, seeded, soft, taper} from "./art-kit.js?v=sol196p2";

export const DECOR_BIOMES = Object.freeze({
  forest: {name: "Forest", floors: ["grass", "dirt_road"]},
  mountain: {name: "Mountain and rocks", floors: ["mountain", "grass"]},
  desert: {name: "Desert", floors: ["sand", "dirt_road"]},
  winter: {name: "Snow and ice", floors: ["snow", "ice"]},
  swamp: {name: "Swamp", floors: ["marsh", "shallows"]},
  temple: {name: "Temple and courtyard", floors: ["flagstone", "tiles"]},
  village: {name: "Village and market", floors: ["dirt_road", "wood"]},
  battlefield: {name: "Battlefield", floors: ["grass", "dirt_road"]},
  cultivation: {name: "Cultivation sect", floors: ["temple_court", "jungle"]},
});

const path = (d, fill, stroke = "none", width = 1, extra = "") => `<path d="${d}" fill="${fill}" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"${extra}/>`;
const circ = (x, y, r, fill, stroke = "none", width = 1, extra = "") => `<circle cx="${r2(x)}" cy="${r2(y)}" r="${r2(r)}" fill="${fill}" stroke="${stroke}" stroke-width="${width}"${extra}/>`;
const ell = (x, y, rx, ry, fill, angle = 0, extra = "") => `<ellipse cx="${r2(x)}" cy="${r2(y)}" rx="${r2(rx)}" ry="${r2(ry)}" fill="${fill}"${angle ? ` transform="rotate(${r2(angle)} ${r2(x)} ${r2(y)})"` : ""}${extra}/>`;
const op = a => ` opacity="${a}"`;
const deg = a => a * 180 / Math.PI;

// A short wooden plank or pole along a line, lit on its north-west edge.
function plank(x0, y0, x1, y1, w, fill = "#9c7448", dark = "#3b2612", light = "#d9b07a") {
  const a = Math.atan2(y1 - y0, x1 - x0), nx = -Math.sin(a) * w / 2, ny = Math.cos(a) * w / 2;
  return path(`M${r2(x0 + nx)} ${r2(y0 + ny)}L${r2(x1 + nx)} ${r2(y1 + ny)}L${r2(x1 - nx)} ${r2(y1 - ny)}L${r2(x0 - nx)} ${r2(y0 - ny)}Z`, fill, dark, 0.8)
    + path(`M${r2(x0 - nx * 0.6)} ${r2(y0 - ny * 0.6)}L${r2(x1 - nx * 0.6)} ${r2(y1 - ny * 0.6)}`, "none", light, 0.7, op(0.7));
}
// A lumpy leafy bush of radius r: dark underside, lit clumps, leaf flecks.
function bush(cx, cy, r, rand, [dark, mid, lit] = ["#1f3a17", "#4c7a2e", "#8fbf55"]) {
  let out = soft(cx + r * 0.25, cy + r * 0.3, r * 1.1, r, 0.4) + circ(cx + 1, cy + 1.5, r, dark);
  for (let i = 0; i < 8; i += 1) {  // a ring of clumps round the edge, then one on top, for a lumpy outline
    const a = (i / 8) * Math.PI * 2 + rand() * 0.4, d = r * (0.48 + rand() * 0.1), rr = r * (0.4 + rand() * 0.12);
    out += circ(cx + Math.cos(a) * d, cy + Math.sin(a) * d, rr, mid, dark, 0.6);
  }
  out += circ(cx - r * 0.08, cy - r * 0.1, r * 0.5, mid, dark, 0.6);
  for (let i = 0; i < 12; i += 1) {
    const a = -2.4 + rand() * 1.9, d = r * (0.2 + rand() * 0.6);
    out += ell(cx + Math.cos(a) * d, cy + Math.sin(a) * d, r * 0.13, r * 0.07, lit, rand() * 180, op(0.75));
  }
  return out;
}
// A clay pot or jar seen from above: rim, dark mouth, lit shoulder.
const jar = (x, y, r, body = "#b06a3c", rim = "#d99a63") => soft(x + r * 0.3, y + r * 0.4, r * 1.05, r, 0.4)
  + circ(x, y, r, body, "#4a2612", 0.9) + path(`M${r2(x - r * 0.8)} ${r2(y - r * 0.1)}A${r2(r * 0.8)} ${r2(r * 0.8)} 0 0 1 ${r2(x + r * 0.1)} ${r2(y - r * 0.8)}`, "none", rim, r2(r * 0.25), op(0.8))
  + circ(x, y, r * 0.5, rim, "#4a2612", 0.7) + circ(x, y, r * 0.36, "#1e120a");
// A woven basket from above: rim ring, weave, and what it holds.
const basket = (x, y, r, fill) => soft(x + r * 0.3, y + r * 0.4, r * 1.05, r, 0.4)
  + circ(x, y, r, "#a8834d", "#4a3418", 1) + circ(x, y, r * 0.84, "none", "#6e5128", 1.6, ` stroke-dasharray="2 1.4"`)
  + circ(x, y, r * 0.7, fill[0]) + Array.from({length: 6}, (_, i) => circ(x + Math.cos(i * 1.1) * r * 0.32, y + Math.sin(i * 1.1) * r * 0.32, r * 0.22, fill[i % 2 ? 1 : 0], "rgba(0,0,0,.35)", 0.5)).join("");
// A tied grain sack lying down.
const sack = (x, y, angle, s = 1) => `<g transform="translate(${r2(x)} ${r2(y)}) rotate(${r2(angle)}) scale(${s})">`
  + soft(2, 3, 11, 8, 0.45) + path("M-11 -6Q-12 -9 -6 -9L4 -8Q8 -4 8 0Q8 4 4 8L-6 9Q-12 9 -11 6Z", "#cbb58a", "#5e4c2c", 0.9)
  + path("M-8 -5Q-2 -7 4 -5", "none", "#efe3c4", 1.1, op(0.8)) + path("M-9 3Q-2 5 4 3", "none", "#8d7a55", 0.9)
  + path("M8 -2.5L12 -4M8 2.5L12 4M8 0H13", "none", "#a28e66", 1.6) + path("M7.6 -3v6", "none", "#4a3a20", 1.8) + "</g>";
// A flame: outer orange, inner yellow, white core.
const flame = (x, y, s) => path(`M${x} ${r2(y - 9 * s)}Q${r2(x + 6 * s)} ${r2(y - 2 * s)} ${r2(x + 3.5 * s)} ${r2(y + 4 * s)}Q${x} ${r2(y + 6 * s)} ${r2(x - 3.5 * s)} ${r2(y + 4 * s)}Q${r2(x - 6 * s)} ${r2(y - 2 * s)} ${x} ${r2(y - 9 * s)}Z`, "#f08a2c", "#a3361a", 0.6)
  + path(`M${x} ${r2(y - 5 * s)}Q${r2(x + 3 * s)} ${r2(y)} ${r2(x + 1.8 * s)} ${r2(y + 3 * s)}Q${x} ${r2(y + 4 * s)} ${r2(x - 1.8 * s)} ${r2(y + 3 * s)}Q${r2(x - 3 * s)} ${r2(y)} ${x} ${r2(y - 5 * s)}Z`, "#ffd35a") + circ(x, y + 1.5 * s, 1.2 * s, "#fff6d6");
// Warm light pooled on the ground.
const glow = (x, y, r) => circ(x, y, r, "#ffcf6e", "none", 1, op(0.1)) + circ(x, y, r * 0.75, "#ffcf6e", "none", 1, op(0.14)) + circ(x, y, r * 0.5, "#ffe2a0", "none", 1, op(0.18));
// A sword, spear or arrow lying at an angle.
const blade2 = (x0, y0, x1, y1, w = 1.6) => path(`M${x0} ${y0}L${x1} ${y1}`, "none", "#2a2f33", w + 1.2) + path(`M${x0} ${y0}L${x1} ${y1}`, "none", "#cfd6db", w);

export const DECOR = Object.freeze({
  // ---------------------------------------------------------------- forest
  fern: {scale: 1.15, biome: "forest", name: "Fern", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = soft(34, 36, 24, 22, 0.3);
    for (let i = 0; i < 9; i += 1) {
      const a = i * 40 + rand() * 20, len = 18 + rand() * 7, rad = a * Math.PI / 180;
      let frond = `<g transform="translate(32 32) rotate(${r2(a)})">` + path(`M0 0Q${r2(len * 0.5)} -2 ${r2(len)} 1`, "none", "#2f5220", 1.2);
      for (let j = 1; j < 9; j += 1) {
        const t = j / 9 * len, l = 5.5 * Math.sin(Math.PI * (j / 9)) + 1;
        frond += path(`M${r2(t)} 0Q${r2(t + 1.5)} ${r2(-l * 0.7)} ${r2(t + 2.5)} ${r2(-l)}Q${r2(t + 2.6)} ${r2(-l * 0.4)} ${r2(t)} 0ZM${r2(t)} 0Q${r2(t + 1.5)} ${r2(l * 0.7)} ${r2(t + 2.5)} ${r2(l)}Q${r2(t + 2.6)} ${r2(l * 0.4)} ${r2(t)} 0Z`,
          Math.cos(rad + 0.8) < 0 ? "#9ccb5c" : "#62a03a", "#1f3a15", 0.4);
      }
      out += frond + "</g>";
    }
    return out + circ(32, 32, 2.6, "#3a5a24");
  }},
  mushrooms: {scale: 1.3, biome: "forest", name: "Mushrooms", rule: null, draw: seed => {
    const rand = seeded(seed), caps = [[24, 26, 7, "#b2412e"], [38, 22, 5, "#c4553a"], [36, 38, 8, "#a63a28"], [22, 42, 4.5, "#c4553a"], [46, 34, 3.5, "#d97a52"]];
    let out = "";
    for (const [x, y, r, c] of caps) {
      out += soft(x + 2, y + 3, r * 1.1, r * 0.9, 0.45) + circ(x, y, r, c, "#4a160c", 0.9)
        + path(`M${r2(x - r * 0.7)} ${r2(y - r * 0.1)}A${r2(r * 0.72)} ${r2(r * 0.72)} 0 0 1 ${r2(x + r * 0.1)} ${r2(y - r * 0.72)}`, "none", "#f08a6e", r2(r * 0.18), op(0.7));
      for (let k = 0; k < Math.round(r / 1.5); k += 1) out += circ(x + (rand() - 0.5) * r * 1.2, y + (rand() - 0.5) * r * 1.2, r * 0.13, "#f6ecd6");
    }
    return out;
  }},
  fallen_log: {biome: "forest", name: "Fallen log", rule: "SIMPLE_COVER", draw: () => soft(33, 38, 30, 11, 0.45)
    + path("M4 26Q4 22 9 22H55Q60 22 60 32Q60 42 55 42H9Q4 42 4 38Z", "#6e5133", "#2b1d10", 1.1)
    + path("M8 25H54M9 30H56M9 35H57M9 39H54", "none", "#4a3520", 0.9) + path("M9 23.5H54", "none", "#b08a5c", 1.4, op(0.8))
    + ell(56, 32, 4.5, 10, "#c39b67", 0, ` stroke="#2b1d10" stroke-width="1"`) + ell(56, 32, 2.8, 6.4, "none", 0, ` stroke="#8a6640" stroke-width=".7"`) + ell(56, 32, 1.2, 2.6, "#8a6640")
    + path("M18 22q3-6 8-5M38 42q2 6 7 6", "none", "#5a4129", 2.4) + ell(28, 26, 5, 2.4, "#6f8f3c", -8, op(0.8)) + ell(44, 37, 4, 2, "#6f8f3c", 10, op(0.7))},
  stump: {scale: 1.2, biome: "forest", name: "Tree stump", rule: "SIMPLE_COVER", draw: () => soft(35, 37, 22, 20, 0.45)
    + [0, 72, 144, 216, 288].map(a => taper([32 + Math.cos(a * Math.PI / 180) * 10, 32 + Math.sin(a * Math.PI / 180) * 10], [32 + Math.cos((a + 15) * Math.PI / 180) * 18, 32 + Math.sin((a + 15) * Math.PI / 180) * 18], [32 + Math.cos((a + 8) * Math.PI / 180) * 25, 32 + Math.sin((a + 8) * Math.PI / 180) * 25], 9, 0.5))
      .map(d => path(d, "#5f4a35", "#1f160c", 0.9)).join("")
    + circ(32, 32, 14, "#5b4129", "#22170b", 1.2) + circ(31.4, 31.4, 11.5, "#c9a170")
    + [8.6, 5.8, 3].map(r => circ(31.4, 31.4, r, "none", "#8a6640", 0.8)).join("") + circ(31.4, 31.4, 1, "#6e4f2e")
    + path("M31 20l1 9 7 4", "none", "#5e4329", 0.9) + path("M20 28Q22 21 29 20", "none", "#f0d2a0", 1.2, op(0.7))},
  leaf_litter: {biome: "forest", name: "Leaf litter", rule: null, draw: seed => {
    const rand = seeded(seed), colors = ["#9a6a2c", "#c08a3a", "#7a5226", "#b4542a", "#d4a050", "#6f7a34"];
    let out = "";
    for (let i = 0; i < 46; i += 1) {
      const x = 4 + rand() * 56, y = 4 + rand() * 56, a = rand() * 180, s = 2.2 + rand() * 2;
      out += `<g transform="translate(${r2(x)} ${r2(y)}) rotate(${r2(a)})">${path(`M0 ${r2(-s)}Q${r2(s * 0.8)} 0 0 ${r2(s)}Q${r2(-s * 0.8)} 0 0 ${r2(-s)}Z`, colors[i % 6], "rgba(40,20,5,.5)", 0.4)}${path(`M0 ${r2(-s)}V${r2(s)}`, "none", "rgba(40,20,5,.5)", 0.3)}</g>`;
    }
    return out;
  }},
  forest_bush: {scale: 1.35, biome: "forest", name: "Bush", rule: null, draw: seed => bush(32, 32, 20, seeded(seed))
    + [[26, 24], [38, 30], [30, 40]].map(([x, y]) => circ(x, y, 1.6, "#c43a3a", "#5a1010", 0.4)).join("")},
  wildflowers: {biome: "forest", name: "Wildflowers", rule: null, draw: seed => {
    const rand = seeded(seed), colors = ["#f3e36a", "#f2f2f2", "#c98ad8", "#f08aa8", "#8ac0f0"];
    let out = "";
    for (let i = 0; i < 26; i += 1) out += blade(r2(6 + rand() * 52), r2(8 + rand() * 50), r2(rand() * 360), 7, 1.3, "#5d8c34");
    for (let i = 0; i < 18; i += 1) {
      const x = 6 + rand() * 52, y = 6 + rand() * 52, c = colors[i % 5];
      out += [0, 1, 2, 3, 4].map(k => circ(x + Math.cos(k * 1.257) * 1.7, y + Math.sin(k * 1.257) * 1.7, 1.3, c, "rgba(0,0,0,.25)", 0.3)).join("") + circ(x, y, 0.9, "#e8a53a");
    }
    return out;
  }},
  mossy_rock: {scale: 1.2, biome: "forest", name: "Mossy rock", rule: "SIMPLE_COVER", draw: seed => rock(32, 32, 22, 401 + seed * 13, "grey", {sides: 8})
    + path("M16 24Q22 15 33 14Q28 20 22 22Q19 26 16 24Z", "#5f7f34", "none", 1, op(0.85)) + path("M38 40q6-2 9-8q1 6-4 10q-3 1-5-2z", "#5f7f34", "none", 1, op(0.8))
    + [[20, 20], [27, 16], [42, 37]].map(([x, y]) => circ(x, y, 1.1, "#9cbf5c")).join("")},

  // ---------------------------------------------------------------- mountain and rocks
  crag: {scale: 1.1, biome: "mountain", name: "Crag", rule: "SIMPLE_COVER", draw: seed => rock(30, 33, 26, 501 + seed * 13, "dark", {sides: 6, squash: 0.85})
    + rock(46, 20, 11, 502 + seed * 13, "dark", {sides: 5, shadow: false}) + path("M18 30l10 4 4 10M36 26l6 8", "none", "#1d1b19", 1.1, op(0.8))},
  cliff_edge: {biome: "mountain", name: "Cliff edge", rule: "SIMPLE_COVER", draw: () =>
    // the drop: a soft dark fall-off below the lip, then the ragged rock shelf above it
    path("M0 38L8 33 16 37 24 31 33 35 41 30 50 35 58 31 64 34V58Q32 66 0 58Z", "#1d1a18", "none", 1, op(0.85)) + soft(32, 46, 32, 10, 0.5)
    + path("M0 12Q6 6 14 9L22 5 32 9 42 4 52 8 60 6 64 10V34L58 31 50 35 41 30 33 35 24 31 16 37 8 33 0 38Z", "#8c867b", "#3e3b36", 1)
    + path("M0 32L8 28 16 32 24 26 33 30 41 25 50 30 58 26 64 29", "none", "#d6d0c2", 1.6, op(0.8))
    + path("M8 34L10 40M24 31l1 7M41 30l-1 7M58 31l1 6", "none", "#3e3b36", 1.2, op(0.8))
    + path("M10 12l6 9-4 6M34 8l-3 10 6 6M52 11l4 9", "none", "#5d5850", 1, op(0.8)) + rock(20, 16, 5, 503, "grey", {sides: 5}) + rock(46, 19, 4, 504, "grey", {sides: 5})},
  cairn: {scale: 1.4, biome: "mountain", name: "Cairn", rule: "SIMPLE_COVER", draw: seed => rock(32, 34, 17, 511 + seed * 13, "grey", {sides: 7, squash: 0.9})
    + rock(31, 31, 11, 512 + seed * 13, "warm", {sides: 6, shadow: false}) + rock(30.5, 29, 6.5, 513 + seed * 13, "grey", {sides: 6, shadow: false}) + rock(30, 27.5, 3, 514, "warm", {sides: 5, shadow: false})},
  loose_gravel: {biome: "mountain", name: "Loose gravel", rule: "DIFFICULT", draw: seed => {
    const rand = seeded(seed);
    // Four independent per-edge ripples (own phase, amplitude and wavelength, seeded) instead of a dead
    // straight margin on all four sides: the patch keeps its full square footprint in the middle -- so a
    // run of these squares still reads as one connected field, not isolated puffs -- but each edge bows
    // in and out unevenly, and pebbles fade out as they near it, so the boundary blends raggedly into the
    // bare ground instead of looking like a pasted rectangular tile (owner playtest round 3).
    const edgeNoise = () => ({amp: 3 + rand() * 5, ph: rand() * Math.PI * 2, freq: 1.3 + rand() * 1.6});
    const edges = {left: edgeNoise(), right: edgeNoise(), top: edgeNoise(), bottom: edgeNoise()};
    const ripple = (e, t) => e.amp * Math.sin(t * e.freq * Math.PI * 2 + e.ph);
    const feather = 11;
    let out = "";
    for (let i = 0; i < 110; i += 1) {
      const x = -4 + rand() * 72, y = -4 + rand() * 72;
      const dl = x - ripple(edges.left, y / 64), dr = 64 - x - ripple(edges.right, y / 64);
      const dt = y - ripple(edges.top, x / 64), db = 64 - y - ripple(edges.bottom, x / 64);
      const fade = Math.max(0, Math.min(1, Math.min(dl, dr, dt, db) / feather + 0.3));
      if (fade <= 0.05) continue;
      const r = (0.7 + rand() * 1.6) * (0.55 + fade * 0.45), t = ["#8a8478", "#a9a397", "#6f6a61", "#c2bcaf"][i % 4];
      out += ell(r2(x) + 0.4, r2(y) + 0.6, r, r * 0.8, "#000", 0, op(r2(0.3 * fade * 100) / 100))
        + ell(r2(x), r2(y), r, r * 0.8, t, rand() * 180, op(r2(Math.min(1, 0.5 + fade * 0.5) * 100) / 100));
    }
    return out;
  }},
  boulder_pair: {scale: 1.1, biome: "mountain", name: "Boulders", rule: "SIMPLE_COVER", draw: seed => rock(23, 27, 17, 521 + seed * 13, "grey", {sides: 8}) + rock(45, 42, 14, 522 + seed * 13, "warm", {sides: 7})},
  mountain_shrub: {scale: 1.3, biome: "mountain", name: "Hardy shrub", rule: null, draw: seed => bush(32, 32, 19, seeded(seed), ["#2a3a22", "#5e6e42", "#a3ac74"])
    + path("M20 44l-4 6M44 44l5 5M32 47v6", "none", "#5a4630", 1.4)},
  fissure: {biome: "mountain", name: "Rock fissure", rule: null, draw: () => {
    const line = "M0 30L10 25 17 32 27 26 34 35 44 29 51 38 64 33";
    return path(line, "none", "#2a2725", 9, op(0.7)) + path(line, "none", "#0d0c0b", 4.5)
      + path("M0 26.5L10 21.5 17 28.5 27 22.5 34 31.5 44 25.5 51 34.5 64 29.5", "none", "#d6d0c2", 1.3, op(0.7))
      + path("M17 32l-4 9M34 35l3 10M44 29l4-8M51 38l-2 8", "none", "#1d1b19", 2) + path("M17 32l-4 9M34 35l3 10", "none", "#0d0c0b", 0.8);
  }},

  // ---------------------------------------------------------------- desert
  dune_ripples: {biome: "desert", name: "Dune ripples", rule: null, draw: () => [10, 20, 30, 40, 50].map(y =>
    path(`M2 ${y + 4}Q16 ${y - 3} 32 ${y + 2}T62 ${y}`, "none", "#9a7442", 2.2, op(0.55)) + path(`M2 ${y + 2}Q16 ${y - 5} 32 ${y}T62 ${y - 2}`, "none", "#f6dcaa", 1.4, op(0.75))).join("")},
  cactus: {scale: 1.25, biome: "desert", name: "Cactus", rule: "SIMPLE_COVER", draw: () => {
    const arm = (x, y, r) => circ(x + 1.5, y + 2, r, "#000", "none", 1, op(0.3)) + circ(x, y, r, "#4f8a3c", "#1f3a17", 1)
      + Array.from({length: 8}, (_, i) => path(`M${r2(x + Math.cos(i * 0.785) * r * 0.25)} ${r2(y + Math.sin(i * 0.785) * r * 0.25)}L${r2(x + Math.cos(i * 0.785) * r)} ${r2(y + Math.sin(i * 0.785) * r)}`, "none", "#2f5d27", 0.8)).join("")
      + Array.from({length: 8}, (_, i) => path(`M${r2(x + Math.cos(i * 0.785 + 0.39) * r)} ${r2(y + Math.sin(i * 0.785 + 0.39) * r)}l${r2(Math.cos(i * 0.785 + 0.39) * 2.4)} ${r2(Math.sin(i * 0.785 + 0.39) * 2.4)}`, "none", "#f2ecd0", 0.5)).join("")
      + path(`M${r2(x - r * 0.6)} ${r2(y - r * 0.2)}A${r2(r * 0.65)} ${r2(r * 0.65)} 0 0 1 ${r2(x + r * 0.1)} ${r2(y - r * 0.65)}`, "none", "#9ccf7a", 1.2, op(0.8));
    return soft(36, 38, 22, 18, 0.35) + plank(32, 32, 18, 32, 8, "#4f8a3c", "#1f3a17", "#9ccf7a") + plank(32, 32, 32, 48, 7, "#4f8a3c", "#1f3a17", "#9ccf7a")
      + arm(18, 32, 6) + arm(32, 48, 5.5) + arm(32, 32, 10) + circ(32, 29, 2, "#f0a0c0", "#8a3050", 0.5);
  }},
  barrel_cactus: {scale: 1.3, biome: "desert", name: "Barrel cacti", rule: null, draw: () => [[24, 26, 8], [40, 36, 6.5], [26, 44, 5]].map(([x, y, r]) =>
    soft(x + 2, y + 3, r * 1.1, r, 0.4) + circ(x, y, r, "#5a9442", "#1f3a17", 1)
    + Array.from({length: 10}, (_, i) => path(`M${x} ${y}L${r2(x + Math.cos(i * 0.628) * r)} ${r2(y + Math.sin(i * 0.628) * r)}`, "none", "#2f5d27", 0.8)).join("")
    + circ(x - r * 0.25, y - r * 0.25, r * 0.4, "#9ccf7a", "none", 1, op(0.35)) + circ(x, y, r * 0.25, "#f2c23a", "#8a5a10", 0.4)).join("")},
  bleached_bones: {scale: 1.15, biome: "desert", name: "Bleached bones", rule: null, draw: () => soft(32, 36, 24, 14, 0.3)
    + path("M14 32Q32 24 50 30", "none", "#cfc6b0", 3) + [18, 24, 30, 36, 42, 47].map((x, i) => path(`M${x} ${29 - i * 0.2}Q${x - 3} 20 ${x + 2} 15M${x} ${31}Q${x - 3} 40 ${x + 2} 45`, "none", "#e9e2cf", 2.2)).join("")
    + path("M50 30L58 27", "none", "#e9e2cf", 2.4) + ell(56, 40, 6, 4.5, "#ece5d2", 20, ` stroke="#8a8270" stroke-width=".8"`) + ell(54.5, 39.5, 1.2, 1, "#4a4436") + ell(57.5, 40.8, 1.2, 1, "#4a4436")
    + path("M8 46l6 3M10 44l2 6", "none", "#e9e2cf", 2)},
  sandstone: {scale: 1.1, biome: "desert", name: "Sandstone rock", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 26, 22, 0.45)
    + path("M10 22L22 10 44 11 56 24 54 46 40 55 18 52 8 38Z", "#b5683a", "#5a2e14", 1.1) + path("M14 23L24 14 42 15 50 25 46 34 22 33Z", "#e3a36a", "#f6cfa0", 0.7)
    + path("M12 36L52 38M14 44L48 47", "none", "#8a4a24", 1.1, op(0.8)) + path("M22 33L46 34", "none", "#c9814a", 1.6) + path("M20 18L40 17", "none", "#ffe1b8", 1, op(0.7))},
  dry_scrub: {scale: 1.5, biome: "desert", name: "Dry scrub", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = soft(33, 35, 16, 14, 0.25);
    for (let i = 0; i < 16; i += 1) {
      const a = rand() * Math.PI * 2, l = 10 + rand() * 9;
      out += path(`M32 32Q${r2(32 + Math.cos(a + 0.4) * l * 0.5)} ${r2(32 + Math.sin(a + 0.4) * l * 0.5)} ${r2(32 + Math.cos(a) * l)} ${r2(32 + Math.sin(a) * l)}`, "none", i % 2 ? "#8a7448" : "#6a5634", 1.1);
      out += circ(32 + Math.cos(a) * l, 32 + Math.sin(a) * l, 1.3, "#a8a060");
    }
    return out;
  }},
  sand_drift: {biome: "desert", name: "Deep sand drift", rule: "DIFFICULT", draw: () => soft(34, 36, 28, 22, 0.2)
    + path("M4 40Q18 18 36 22Q54 26 60 44Q44 52 30 50Q12 50 4 40Z", "#d9b57a", "none") + path("M8 38Q20 22 36 25Q50 28 56 40", "none", "#f6dcaa", 2.4, op(0.9))
    + path("M14 44Q30 40 50 45", "none", "#a8834d", 1.4, op(0.7)) + path("M20 34Q32 30 44 34", "none", "#f9e6c0", 1, op(0.8))},

  // ---------------------------------------------------------------- snow and ice
  ice_shards: {scale: 1.2, biome: "winter", name: "Ice shards", rule: "DIFFICULT", draw: () => soft(34, 36, 22, 18, 0.1)
    + [[20, 24, -30, 14], [36, 18, 20, 12], [44, 38, 60, 15], [24, 44, -70, 11], [34, 32, 0, 9]].map(([x, y, a, l]) =>
      `<g transform="translate(${x} ${y}) rotate(${a})">${path(`M${-l / 2} 0L0 -3L${l / 2} 0L0 3Z`, "#9fd6e6", "#e8fbff", 0.8, op(0.9))}${path(`M${-l / 2} 0L0 -3L${l / 2} 0Z`, "#e6f8fc", "none", 1, op(0.9))}${path(`M${-l / 2} 0H${l / 2}`, "none", "#ffffff", 0.6)}</g>`).join("")},
  snow_drift: {biome: "winter", name: "Snow drift", rule: "DIFFICULT", draw: () => soft(36, 40, 26, 16, 0.12)
    + path("M4 42Q10 24 26 22Q40 16 52 26Q62 34 58 46Q40 54 22 52Q8 50 4 42Z", "#c8d6e2", "none") + path("M8 40Q14 26 28 25Q40 20 50 28Q58 34 55 42", "#eef4f9", "none")
    + path("M12 36Q20 28 30 28", "none", "#ffffff", 2, op(0.9)) + path("M20 48Q36 50 54 44", "none", "#9fb2c4", 1.2, op(0.8))},
  frozen_puddle: {scale: 1.2, biome: "winter", name: "Frozen puddle", rule: null, draw: () =>
    path("M10 30Q12 16 30 16Q50 14 54 28Q58 44 40 48Q20 52 12 42Q8 36 10 30Z", "#7fb4cc", "#e6f6fb", 1.2, op(0.85)) + path("M16 30Q20 20 32 20", "none", "#ffffff", 2.4, op(0.7))
    + path("M24 28l8 6 10-4M32 34l2 8M18 38l6-4", "none", "#e6f6fb", 0.8, op(0.9))},
  snowy_rock: {scale: 1.2, biome: "winter", name: "Snowy rock", rule: "SIMPLE_COVER", draw: seed => rock(32, 33, 22, 601 + seed * 13, "dark", {sides: 8})
    + path("M14 26Q18 14 32 13Q44 13 48 22Q40 20 34 24Q24 22 14 26Z", "#eef4f9", "#9fb2c4", 0.8) + path("M18 23Q24 17 32 16", "none", "#ffffff", 1.6)},
  snowy_shrub: {scale: 1.3, biome: "winter", name: "Snowy shrub", rule: null, draw: seed => bush(32, 32, 20, seeded(seed), ["#1f3324", "#3f5e44", "#7fa088"])
    + [[24, 24, 7], [36, 25, 6], [28, 36, 5], [40, 36, 4.5], [20, 34, 4]].map(([x, y, r]) => ell(x + 0.8, y + 1, r, r * 0.6, "#9fb2c4", -20) + ell(x, y, r, r * 0.6, "#f2f6f9", -20)).join("")},
  icicle_pillar: {scale: 1.2, biome: "winter", name: "Ice pillar", rule: "SIMPLE_COVER", draw: () => soft(38, 40, 20, 18, 0.4)
    + path("M32 8L44 18 50 34 42 52 24 54 14 38 18 18Z", "#6fb4cc", "#e6fbff", 1.1, op(0.9)) + path("M32 8L44 18 36 30 22 22 18 18Z", "#d6f4fb", "none", 1, op(0.9))
    + path("M22 22L36 30 42 52M36 30L50 34", "none", "#ffffff", 0.9, op(0.8)) + path("M28 14l-2 8", "none", "#ffffff", 2, op(0.7))},
  footprints: {biome: "winter", name: "Footprints in snow", rule: null, draw: () => [[10, 56, 30], [18, 46, 35], [24, 36, 25], [32, 27, 30], [38, 18, 20], [46, 9, 28]].map(([x, y, a], i) =>
    ell(x + (i % 2 ? 3.5 : -3.5), y, 2.8, 5, "#7f95a8", a, op(0.85)) + ell(x + (i % 2 ? 3.5 : -3.5) - 0.5, y - 0.8, 2, 3.8, "#a9bccb", a, op(0.9))
    + ell(x + (i % 2 ? 3.5 : -3.5) + 0.6, y + 0.9, 2.4, 1, "#ffffff", a, op(0.6))).join("")},

  // ---------------------------------------------------------------- swamp
  reeds: {scale: 1.3, biome: "swamp", name: "Reeds", rule: null, draw: seed => {
    // Tufts of reeds leaning with the wind, tipped with pale seed heads.
    const rand = seeded(seed);
    let out = soft(34, 36, 20, 16, 0.25);
    for (const [cx, cy] of [[24, 26], [38, 24], [30, 38], [44, 38]]) {
      for (let i = 0; i < 8; i += 1) {
        const a = -55 + (i - 3.5) * 9 + (rand() - 0.5) * 8, len = 13 + rand() * 9, x = cx + (rand() - 0.5) * 4, y = cy + (rand() - 0.5) * 4;
        const ex = x + Math.cos((a - 90) * Math.PI / 180) * -len, ey = y + Math.sin((a - 90) * Math.PI / 180) * -len;
        out += blade(r2(x), r2(y), r2(a + 180), len, 1.4, ["#6f8a3c", "#8ea64e", "#556e2c"][i % 3]);
        if (i % 3 === 0) out += ell(ex, ey, 1, 2.4, "#c9b98a", a + 180);
      }
      out += circ(cx, cy, 2, "#3a4a22");
    }
    return out;
  }},
  lily_pads: {scale: 1.2, biome: "swamp", name: "Lily pads", rule: null, draw: () => [[22, 24, 9, 30], [40, 22, 7, 140], [36, 40, 10, 250], [18, 44, 6, 80]].map(([x, y, r, a]) =>
    ell(x + 1, y + 1.5, r, r, "#0d2a24", 0, op(0.35)) + `<path d="M${x} ${y}L${r2(x + Math.cos(a * Math.PI / 180) * r)} ${r2(y + Math.sin(a * Math.PI / 180) * r)}A${r} ${r} 0 1 1 ${r2(x + Math.cos((a + 25) * Math.PI / 180) * r)} ${r2(y + Math.sin((a + 25) * Math.PI / 180) * r)}Z" fill="#4f8a3c" stroke="#1f3a17" stroke-width=".8"/>`
    + path(`M${x} ${y}L${r2(x - r * 0.6)} ${r2(y - r * 0.4)}M${x} ${y}L${r2(x + r * 0.2)} ${r2(y - r * 0.7)}M${x} ${y}L${r2(x - r * 0.5)} ${r2(y + r * 0.5)}`, "none", "#86b864", 0.6)).join("")
    + [0, 1, 2, 3, 4, 5].map(k => ell(36 + Math.cos(k * 1.047) * 2.4, 40 + Math.sin(k * 1.047) * 2.4, 2.2, 1.2, "#f6d6e4", k * 60)).join("") + circ(36, 40, 1.3, "#f2c23a")},
  mangrove_roots: {scale: 1.1, biome: "swamp", name: "Mangrove roots", rule: "DIFFICULT", draw: seed => {
    // Arching prop roots seen from above: loops springing out from a central knot and plunging into the mud.
    // Each root's angle and reach is nudged by the square's own seed, so a mangrove stand of many squares
    // doesn't repeat the same seven loops over and over (owner playtest 2026-10-13).
    const rand = seeded(seed);
    let out = soft(32, 34, 28, 24, 0.22);
    for (const [a0, l0] of [[0, 26], [50, 22], [100, 27], [150, 23], [205, 26], [255, 22], [305, 25]]) {
      const a = a0 + (rand() - 0.5) * 24, l = l0 * (0.85 + rand() * 0.3);
      const r = a * Math.PI / 180, ex = 32 + Math.cos(r) * l, ey = 32 + Math.sin(r) * l;
      const mx = 32 + Math.cos(r + 0.35) * l * 0.6, my = 32 + Math.sin(r + 0.35) * l * 0.6;
      const d = `M32 32Q${r2(mx)} ${r2(my)} ${r2(ex)} ${r2(ey)}`;
      out += path(d, "none", "#1f170e", 6) + path(d, "none", "#6a5840", 4.2) + path(d, "none", "#a48e68", 1.2, op(0.7))
        + ell(ex, ey, 3, 2, "#1a140c", deg(r), op(0.8));
    }
    return out + circ(32, 32, 6, "#4a3a28", "#1f170e", 1) + circ(31, 31, 3, "#6a5840");
  }},
  cattails: {scale: 1.45, biome: "swamp", name: "Cattails", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = soft(33, 35, 16, 14, 0.3);
    for (let i = 0; i < 18; i += 1) out += blade(r2(32 + (rand() - 0.5) * 12), r2(32 + (rand() - 0.5) * 12), r2(rand() * 360), 15, 1.8, i % 2 ? "#6f8a3c" : "#556e2c");
    for (let i = 0; i < 7; i += 1) {
      const x = 32 + (rand() - 0.5) * 22, y = 32 + (rand() - 0.5) * 22;
      out += ell(x + 0.6, y + 0.8, 1.9, 4.6, "#000", 30, op(0.3)) + ell(x, y, 1.8, 4.4, "#6a4226", 30, ` stroke="#2e1a0c" stroke-width=".5"`) + ell(x - 0.5, y - 1, 0.6, 2.2, "#a0704a", 30);
    }
    return out;
  }},
  murky_pool: {scale: 1.1, biome: "swamp", name: "Murky pool", rule: null, draw: () =>
    path("M8 30Q8 14 28 12Q50 10 56 28Q60 46 40 52Q16 56 10 42Z", "#3c4a2a", "#26301a", 1.4) + path("M12 30Q12 18 28 16Q46 14 52 28", "none", "#7a8a52", 1.4, op(0.6))
    + ell(24, 30, 8, 3, "#5a6a3a", -10, op(0.6)) + ell(40, 40, 6, 2, "#5a6a3a", 15, op(0.5)) + [[30, 24], [44, 30], [20, 40]].map(([x, y]) => circ(x, y, 1, "#b0bc80", "none", 1, op(0.8))).join("")
    + circ(36, 32, 3, "none", "#8a9a62", 0.5, op(0.6)) + circ(36, 32, 5, "none", "#8a9a62", 0.4, op(0.4))},
  rotten_log: {biome: "swamp", name: "Rotting log", rule: "SIMPLE_COVER", draw: () => soft(33, 38, 30, 11, 0.45)
    + path("M4 26Q4 22 9 22H55Q60 22 60 32Q60 42 55 42H9Q4 42 4 38Z", "#4e4232", "#1f170e", 1.1)
    + path("M8 26H54M9 31H56M9 36H57", "none", "#2f271c", 0.9) + ell(56, 32, 4.5, 10, "#7a6a50", 0, ` stroke="#1f170e" stroke-width="1"`) + ell(56, 32, 2.4, 5.6, "#2a2016")
    + path("M10 22Q20 16 32 22Q40 26 50 22", "#5f7a34", "none", 1, op(0.85)) + [[16, 30], [30, 34], [44, 28]].map(([x, y]) => circ(x, y, 2.6, "#c4b48a", "#5a4a30", 0.5)).join("")},
  swamp_mushrooms: {scale: 1.35, biome: "swamp", name: "Glowing fungus", rule: null, draw: () => glow(32, 34, 20)
    + [[24, 28, 5], [36, 26, 4], [32, 38, 6], [44, 36, 3.5], [22, 40, 3]].map(([x, y, r]) => soft(x + 1.5, y + 2, r, r * 0.9, 0.4) + circ(x, y, r, "#7fd6b8", "#1f5a48", 0.8) + circ(x - r * 0.3, y - r * 0.3, r * 0.4, "#d6fff0", "none", 1, op(0.7))).join("")},

  // ---------------------------------------------------------------- temple and courtyard
  stone_lantern: {scale: 1.35, biome: "temple", name: "Stone lantern", rule: "SIMPLE_COVER", draw: () => glow(32, 32, 28) + soft(37, 38, 18, 16, 0.4)
    + path("M14 18Q32 12 50 18L46 46Q32 50 18 46Z", "#7d786e", "#3a3732", 1.1) + path("M14 18Q32 12 50 18L32 30Z", "#c8c2b2") + path("M14 18L32 30 18 46Z", "#a19b8d") + path("M50 18L32 30 46 46Z", "#66625a")
    + path("M14 18L32 30 50 18M32 30L18 46M32 30L46 46", "none", "#3a3732", 0.8) + circ(32, 30, 5, "#9a9488", "#3a3732", 0.9) + circ(31, 29, 2.4, "#ece6d6")
    + path("M24 50h16", "none", "#ffcf6e", 2, op(0.8))},
  incense_burner: {scale: 1.5, biome: "temple", name: "Incense burner", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 18, 16, 0.45)
    + circ(32, 32, 16, "#6e5a2a", "#2a200c", 1.1) + circ(32, 32, 13, "#b08a3a", "#5a4416", 0.8) + circ(32, 32, 10, "#4a4036")
    + [[29, 30], [33, 28], [35, 33], [30, 35]].map(([x, y]) => path(`M${x} ${y}l-1 -2`, "none", "#c44a2a", 1.2) + circ(x - 1, y - 2, 0.8, "#ff8a3a")).join("")
    + [[16, 32], [48, 32], [32, 16], [32, 48]].map(([x, y]) => circ(x, y, 2.6, "#d4a957", "#5a4416", 0.6)).join("")
    + path("M28 26Q22 16 30 10Q36 6 32 2", "none", "#d8d4cc", 2, op(0.35)) + path("M34 28Q40 20 36 14", "none", "#d8d4cc", 1.6, op(0.3))},
  prayer_flags: {biome: "temple", name: "Prayer flags", rule: null, draw: () => soft(32, 38, 30, 6, 0.2)
    + path("M2 20Q32 32 62 20", "none", "#3a2a1a", 0.9) + ["#c8402f", "#f0d08a", "#4f8a5f", "#3f6fb0", "#f2f2f2", "#c8402f", "#f0d08a"].map((c, i) => {
      const x = 8 + i * 8, y = 20 + Math.sin((i + 0.5) / 7 * Math.PI) * 7;
      return `<g transform="translate(${r2(x)} ${r2(y)}) rotate(${r2(-12 + i * 4)})">${path("M-3 0H3L2.5 9L0 7.5L-2.5 9Z", c, "rgba(0,0,0,.45)", 0.5)}${path("M-1.5 3h3M-1.5 5h3", "none", "rgba(0,0,0,.35)", 0.4)}</g>`;
    }).join("") + circ(2, 20, 1.6, "#5a4630") + circ(62, 20, 1.6, "#5a4630")},
  koi_pond_edge: {scale: 1.15, biome: "temple", name: "Koi pond", rule: null, draw: () =>
    // A small round pond edged with stones, two koi and a lily pad.
    path("M10 32Q8 14 28 11Q50 9 55 28Q60 48 38 54Q14 58 10 32Z", "#2a5f70", "none") + path("M15 32Q14 18 29 16Q46 14 50 29", "none", "#4f9aaa", 2.4, op(0.6))
    + Array.from({length: 14}, (_, i) => {
      const a = i / 14 * Math.PI * 2, x = 32.5 + Math.cos(a) * 24, y = 32.5 + Math.sin(a) * 22;
      return rock(x, y, 5 + (i % 3), 701 + i, "grey", {sides: 6, squash: 0.85});
    }).join("")
    + ell(26, 30, 5, 2, "#f08a3a", -20) + path("M21 31.5l-3 2 0-4z", "#f08a3a") + ell(27, 29.4, 1.6, 0.8, "#ffffff", -20)
    + ell(38, 40, 4.4, 1.8, "#f2f2f2", 30) + ell(38.8, 40.4, 1.6, 1, "#e0402a", 30) + path("M34 38l-3-1 1 3z", "#f2f2f2")
    + `<path d="M40 24L46 24A6 6 0 1 1 44 19Z" fill="#4f8a3c" stroke="#1f3a17" stroke-width=".7"/>`},
  offering_table: {scale: 1.25, biome: "temple", name: "Offering table", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 24, 16, 0.45)
    + path("M8 20H56V44H8Z", "#7a2a22", "#2a0e0a", 1.1) + path("M9 21H55", "none", "#c8605a", 1.2, op(0.8)) + path("M8 20H56V24H8Z", "#5a1e18", "none", 1, op(0.6))
    + jar(18, 32, 5, "#c0b8a0", "#e8e2d0") + circ(32, 32, 7, "#d4a957", "#5a4416", 0.8) + [[30, 30, "#e0402a"], [34, 30, "#f08a3a"], [32, 34, "#e0402a"]].map(([x, y, c]) => circ(x, y, 2.4, c, "rgba(0,0,0,.4)", 0.4)).join("")
    + jar(46, 32, 4, "#4a6a8a", "#8ab0d0") + path("M44 28l1-6M48 28l-1-6", "none", "#c44a2a", 1)},
  prayer_mat: {scale: 1.2, biome: "temple", name: "Prayer mat", rule: null, draw: () => soft(33, 35, 22, 18, 0.2)
    + path("M12 14H52V50H12Z", "#7a2a3a", "#3a0e18", 1) + path("M16 18H48V46H16Z", "none", "#d4a957", 1.2) + path("M20 22H44V42H20Z", "#9a3a4a", "none")
    + circ(32, 32, 6, "none", "#d4a957", 1) + path("M32 26v12M26 32h12", "none", "#d4a957", 0.8) + path("M12 14v36M52 14v36", "none", "#f0d08a", 1, ` stroke-dasharray="1 1.5"`)},
  bonsai_pot: {scale: 1.6, biome: "temple", name: "Bonsai in a pot", rule: null, draw: seed => soft(36, 38, 18, 16, 0.4)
    + path("M14 20H50V44H14Z", "#3f5a6a", "#16242c", 1.1) + path("M16 22H48V42H16Z", "#4a3a28") + path("M15 21H49", "none", "#8ab0c0", 1, op(0.7))
    + path("M24 34Q30 30 34 32T44 26", "none", "#4a3520", 2.4) + bush(36, 28, 9, seeded(seed), ["#1c3313", "#3d6a28", "#8dba52"])},

  // ---------------------------------------------------------------- village and market
  market_stall: {biome: "village", name: "Market stall", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 30, 26, 0.45)
    + Array.from({length: 6}, (_, i) => path(`M${r2(4 + i * 9.33)} 6H${r2(4 + (i + 1) * 9.33)}L${r2(4 + (i + 1) * 9.33 - 1)} 58H${r2(4 + i * 9.33 + 1)}Z`, i % 2 ? "#e9dcc0" : "#c8402f", "rgba(0,0,0,.35)", 0.6)).join("")
    + path("M4 6H60", "none", "#5a3a20", 2.4) + path("M4 58H60", "none", "#5a3a20", 1.6) + path("M4 6V58M60 6V58", "none", "#3a2414", 1.2)
    + path("M5 8L32 30 59 8M5 56L32 32 59 56", "none", "#000", 0.6, op(0.18)) + path("M4 6Q32 12 60 6", "none", "#fff", 1, op(0.3))},
  baskets: {scale: 1.15, biome: "village", name: "Baskets of goods", rule: null, draw: () => basket(22, 24, 11, ["#c4402a", "#e05a36"]) + basket(42, 28, 9, ["#d9b84a", "#f0d06a"]) + basket(30, 46, 9, ["#5a8a3a", "#7aaa48"])},
  sack_pile: {scale: 1.15, biome: "village", name: "Pile of sacks", rule: "SIMPLE_COVER", draw: () => sack(22, 24, -20) + sack(42, 26, 15) + sack(30, 42, 80) + sack(32, 32, -5, 0.95)},
  hay_bale: {scale: 1.1, biome: "village", name: "Hay bales", rule: "SIMPLE_COVER", draw: () => [[8, 12, 30, 20], [26, 34, 30, 20]].map(([x, y, w, h]) =>
    soft(x + w / 2 + 3, y + h / 2 + 4, w * 0.6, h * 0.65, 0.45) + path(`M${x} ${y}H${x + w}V${y + h}H${x}Z`, "#d4b25a", "#6a5220", 1)
    + Array.from({length: 7}, (_, i) => path(`M${x + 2} ${r2(y + 2 + i * 2.6)}H${x + w - 2}`, "none", i % 2 ? "#b08a3a" : "#ecd27a", 0.8)).join("")
    + path(`M${r2(x + w * 0.3)} ${y}V${y + h}M${r2(x + w * 0.7)} ${y}V${y + h}`, "none", "#6a4a20", 1.4) + path(`M${x + 1} ${y + 1}H${x + w - 1}`, "none", "#fff2b0", 1, op(0.7))).join("")},
  water_well: {scale: 1.15, biome: "village", name: "Well", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 24, 22, 0.45)
    + Array.from({length: 12}, (_, i) => {
      const a0 = i / 12 * Math.PI * 2, a1 = (i + 1) / 12 * Math.PI * 2;
      return path(`M${r2(32 + Math.cos(a0) * 22)} ${r2(32 + Math.sin(a0) * 22)}A22 22 0 0 1 ${r2(32 + Math.cos(a1) * 22)} ${r2(32 + Math.sin(a1) * 22)}L${r2(32 + Math.cos(a1) * 15)} ${r2(32 + Math.sin(a1) * 15)}A15 15 0 0 0 ${r2(32 + Math.cos(a0) * 15)} ${r2(32 + Math.sin(a0) * 15)}Z`, ["#9a948a", "#aaa49a", "#8a8478"][i % 3], "#3e3b36", 0.8);
    }).join("") + circ(32, 32, 15, "#0e1a20") + circ(33, 33, 11, "#1f3a48", "none", 1, op(0.8)) + ell(30, 30, 4, 2, "#6fa0b4", -30, op(0.5))
    + plank(6, 32, 58, 32, 4, "#7a5a38", "#2a1a0c", "#c4996a") + circ(32, 32, 2.6, "#5a4630", "#2a1a0c", 0.6) + path("M32 34v6", "none", "#c9b38a", 0.9)},
  wooden_fence: {biome: "village", name: "Wooden fence", rule: "SIMPLE_COVER", draw: () => soft(32, 37, 32, 8, 0.45)
    + plank(0, 27, 64, 27, 4.4, "#8a6640", "#2e1d0d", "#c9a070") + plank(0, 37, 64, 37, 4.4, "#8a6640", "#2e1d0d", "#c9a070")
    + [6, 24, 42, 60].map(x => circ(x, 32, 5.2, "#6e5133", "#2b1d10", 1) + circ(x - 0.6, 31.4, 3.6, "#b48a5c") + circ(x - 0.6, 31.4, 1.8, "none", "#7a5a38", 0.5)).join("")},
  handcart: {scale: 1.1, biome: "village", name: "Handcart with goods", rule: "SIMPLE_COVER", draw: () => soft(34, 38, 28, 22, 0.45)
    + plank(46, 26, 62, 22, 2.4) + plank(46, 38, 62, 42, 2.4)
    + path("M14 8h22v6h-22zM14 50h22v6h-22z", "#4b3a2a", "#1f1710", 1) + path("M6 14H46V50H6Z", "#a8773f", "#3b2612", 1.2)
    + path("M7 20H45M7 26H45M7 32H45M7 38H45M7 44H45", "none", "#6b4523", 0.8)
    + basket(18, 24, 7, ["#c4402a", "#e05a36"]) + basket(34, 38, 7, ["#5a8a3a", "#7aaa48"]) + jar(34, 22, 5) + jar(18, 40, 4.5, "#8a8a9a", "#c0c0d0")},
  pottery: {scale: 1.2, biome: "village", name: "Clay pots", rule: null, draw: () => jar(22, 24, 9) + jar(40, 22, 7, "#a8582e", "#d48a5a") + jar(32, 42, 10, "#9a4e2a", "#d08850") + jar(48, 40, 5, "#b06a3c", "#e0a070")},

  // ---------------------------------------------------------------- battlefield
  broken_weapons: {scale: 1.15, biome: "battlefield", name: "Broken weapons", rule: null, draw: () => soft(32, 36, 24, 18, 0.25)
    + blade2(10, 20, 30, 34) + path("M30 34l5 3", "none", "#5a3a20", 2.6) + path("M28 31l4 6", "none", "#c9a046", 1.6)
    + plank(36, 12, 52, 50, 2, "#8a6640", "#2e1d0d", "#c9a070") + path("M36 12l-3-7 6 3z", "#cfd6db", "#2a2f33", 0.6)
    + blade2(18, 50, 30, 46, 1.2) + path("M44 40l8 4M46 44l4-6", "none", "#6a4a2a", 1.6)
    + circ(14, 40, 6, "#6e5133", "#2b1d10", 1) + circ(14, 40, 3.6, "none", "#9aa1a8", 1.2) + circ(14, 40, 1.4, "#9aa1a8")},
  torn_banner: {scale: 1.1, biome: "battlefield", name: "Fallen banner", rule: null, draw: () => soft(32, 36, 26, 14, 0.25)
    + plank(6, 50, 52, 12, 2.4, "#6e5133", "#2b1d10", "#b48a5c")
    + path("M20 38L44 18 54 30 46 34 52 40 30 52Z", "#b5352a", "#3b0c08", 0.9) + path("M22 39L44 20M28 46L50 28", "none", "#7a1a14", 1, op(0.6))
    + path("M36 28l4 4-4 4-4-4z", "#d4a957", "#5a4416", 0.6) + path("M46 34l3 1M50 40l2-1", "none", "#3b0c08", 0.8)},
  brazier: {scale: 1.4, biome: "battlefield", name: "Brazier", rule: "SIMPLE_COVER", draw: () => glow(32, 32, 30) + soft(36, 38, 18, 16, 0.45)
    + circ(32, 32, 15, "#2e2f33", "#0e0f11", 1.2) + circ(32, 32, 12, "#3a2418") + [[28, 30], [35, 29], [31, 36], [37, 35], [26, 36]].map(([x, y]) => circ(x, y, 3, "#e05a1a")).join("")
    + flame(31, 32, 1.2) + flame(37, 34, 0.8) + flame(26, 34, 0.7) + [[18, 20], [46, 20], [18, 44], [46, 44]].map(([x, y]) => circ(x, y, 2, "#4a4c52", "#0e0f11", 0.6)).join("")},
  spear_rack: {scale: 1.1, biome: "battlefield", name: "Spear rack", rule: "SIMPLE_COVER", draw: () => soft(34, 38, 28, 12, 0.4)
    + plank(6, 26, 58, 26, 4, "#7a5a38") + plank(6, 38, 58, 38, 4, "#7a5a38")
    + [12, 22, 32, 42, 52].map(x => plank(x - 3, 52, x + 3, 10, 1.8, "#9a7448") + path(`M${x + 3} 10l1.5 -6 1 6z`, "#cfd6db", "#2a2f33", 0.5)).join("")},
  shield_pile: {scale: 1.15, biome: "battlefield", name: "Pile of shields", rule: null, draw: () => [[22, 26, "#7a2a22"], [40, 24, "#2a4a7a"], [32, 40, "#5a5a3a"]].map(([x, y, c]) =>
    soft(x + 2, y + 3, 12, 11, 0.45) + circ(x, y, 11, c, "#1a1a1a", 1.2) + circ(x, y, 9, "none", "#9aa1a8", 1.4) + circ(x, y, 3, "#b8bec4", "#3a3f45", 0.8)
    + path(`M${x - 6} ${y - 5}Q${x - 2} ${y - 9} ${x + 4} ${y - 8}`, "none", "#fff", 1, op(0.35))).join("")},
  arrows_in_ground: {biome: "battlefield", name: "Spent arrows", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let i = 0; i < 9; i += 1) {
      const x = 10 + rand() * 44, y = 10 + rand() * 44, a = 200 + rand() * 40, l = 8 + rand() * 6;
      const ex = x + Math.cos(a * Math.PI / 180) * l, ey = y + Math.sin(a * Math.PI / 180) * l;
      out += path(`M${r2(x + 1)} ${r2(y + 1.5)}L${r2(ex + 3)} ${r2(ey + 4)}`, "none", "#000", 1, op(0.3)) + path(`M${r2(x)} ${r2(y)}L${r2(ex)} ${r2(ey)}`, "none", "#8a6640", 1)
        + path(`M${r2(ex)} ${r2(ey)}l-2 -1.5M${r2(ex)} ${r2(ey)}l-1.5 2`, "none", "#e9e2cf", 1.2) + circ(x, y, 0.9, "#3a2a1a");
    }
    return out;
  }},
  scorch_crater: {scale: 1.1, biome: "battlefield", name: "Scorched crater", rule: null, draw: () =>
    circ(32, 32, 26, "#1a1410", "none", 1, op(0.35)) + circ(32, 32, 19, "#2a1e16", "none", 1, op(0.7)) + circ(32, 32, 12, "#120c08", "none", 1, op(0.8))
    + path("M14 20Q22 26 30 22M44 14Q40 24 46 30M50 44Q40 42 36 50M16 46Q24 40 22 34", "none", "#3a2a1e", 1.4, op(0.8))
    + [[28, 30], [36, 34], [32, 26]].map(([x, y]) => circ(x, y, 1.4, "#e05a1a", "none", 1, op(0.8))).join("") + path("M10 32Q20 28 26 32", "none", "#5a4a3a", 1, op(0.6))},
  war_drum: {scale: 1.3, biome: "battlefield", name: "War drum", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 20, 18, 0.45)
    + circ(32, 32, 18, "#7a2a22", "#2a0e0a", 1.2) + circ(32, 32, 15, "#d8c49a", "#5a4430", 1) + circ(32, 32, 9, "none", "#b8a47a", 0.8)
    + Array.from({length: 12}, (_, i) => circ(32 + Math.cos(i * 0.5236) * 16.5, 32 + Math.sin(i * 0.5236) * 16.5, 1, "#d4a957")).join("")
    + path("M22 24Q28 20 36 21", "none", "#fff4dc", 1.6, op(0.7)) + plank(46, 46, 58, 58, 2.4, "#8a6640") + circ(58, 58, 2.6, "#c8402f", "#3b0c08", 0.6)},
  // ---------------------------------------------------------------- phase 4 (owner 2026-10-08: "keep going with more
  // assets"): alternates of the common pieces, seasonal looks, and a cultivation-sect pack.
  grass_tufts: {scale: 1.1, biome: "forest", name: "Grass tufts", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let t = 0; t < 5; t += 1) {
      const cx = 10 + rand() * 44, cy = 10 + rand() * 44;
      out += soft(cx + 1.5, cy + 2, 7, 5, 0.3);
      for (let i = 0; i < 11; i += 1) out += blade(r2(cx + (rand() - 0.5) * 3), r2(cy + (rand() - 0.5) * 3), r2(-70 + rand() * 140), 10 + rand() * 6, 1.5, ["#9cc85a", "#b6d870", "#7aa848"][i % 3]);
    }
    return out;
  }},
  puddle: {scale: 1.15, biome: "forest", name: "Puddle", rule: null, draw: seed => {
    const rand = seeded(seed), k = 0.8 + rand() * 0.4;
    return path(`M${r2(12 * k + 4)} 32Q12 18 30 17Q${r2(48 + rand() * 6)} 16 52 30Q54 46 36 48Q16 50 ${r2(12 * k + 4)} 32Z`, "#3a3226", "none", 1, op(0.6))
      + path("M16 32Q16 21 30 20Q46 19 49 30Q51 43 36 45Q19 46 16 32Z", "#5a7a88", "#2a2620", 0.8, op(0.85))
      + path("M20 28Q24 22 32 22", "none", "#cfe3ea", 1.6, op(0.7)) + ell(38, 36, 6, 2, "#9bbcc8", 10, op(0.4));
  }},
  autumn_leaves: {biome: "forest", name: "Autumn leaves", rule: null, draw: seed => {
    const rand = seeded(seed), colors = ["#d4552a", "#e8862e", "#f2b23a", "#b8331f", "#c96a24", "#9a4a1c"];
    let out = "";
    for (let i = 0; i < 40; i += 1) {
      const x = 4 + rand() * 56, y = 4 + rand() * 56, a = rand() * 360, s = 2.4 + rand() * 1.8;
      out += `<g transform="translate(${r2(x)} ${r2(y)}) rotate(${r2(a)}) scale(${r2(s / 5)})">${path("M0 -5L1.5 -2 4.5 -3 3 0 5 2 1.5 2 0 5 -1.5 2 -5 2 -3 0 -4.5 -3 -1.5 -2Z", colors[i % 6], "rgba(60,20,5,.5)", 0.4)}</g>`;
    }
    return out;
  }},
  spring_blossoms: {biome: "forest", name: "Spring blossoms", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let i = 0; i < 14; i += 1) out += blade(r2(8 + rand() * 48), r2(8 + rand() * 48), r2(rand() * 360), 6, 1.2, "#7ab04a");
    for (let i = 0; i < 12; i += 1) {
      const x = 8 + rand() * 48, y = 8 + rand() * 48, c = ["#f6c6d8", "#ffffff", "#f3e36a"][i % 3];
      out += [0, 1, 2, 3, 4].map(k => circ(x + Math.cos(k * 1.257) * 2, y + Math.sin(k * 1.257) * 2, 1.6, c, "rgba(0,0,0,.2)", 0.3)).join("") + circ(x, y, 1, "#e8a53a");
    }
    for (let i = 0; i < 30; i += 1) out += ell(4 + rand() * 56, 4 + rand() * 56, 1.3, 0.8, "#f8d2e0", rand() * 180, op(0.9));
    return out;
  }},
  log_pile: {scale: 1.1, biome: "forest", name: "Stacked logs", rule: "SIMPLE_COVER", draw: () => soft(34, 38, 26, 18, 0.45)
    + [[12, 24], [12, 34], [12, 44], [16, 29], [16, 39]].map(([x, y], i) => path(`M${x} ${y - 4.5}H52Q55 ${y - 4.5} 55 ${y}Q55 ${y + 4.5} 52 ${y + 4.5}H${x}Z`, i > 2 ? "#7a5a38" : "#6e5133", "#2b1d10", 0.9)
      + ell(x, y, 3, 4.5, "#c9a170", 0, ` stroke="#2b1d10" stroke-width=".8"`) + ell(x, y, 1.6, 2.6, "none", 0, ` stroke="#8a6640" stroke-width=".5"`)).join("")},
  rock_slab: {scale: 1.2, biome: "mountain", name: "Rock slab", rule: "SIMPLE_COVER", draw: seed => rock(32, 32, 24, 541 + seed * 13, "grey", {sides: 5, squash: 0.6, angle: 0.3})
    + path("M14 34l14-6 18 2", "none", "#4f4b45", 1, op(0.6))},
  alpine_flowers: {biome: "mountain", name: "Alpine flowers", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let i = 0; i < 9; i += 1) {
      const x = 8 + rand() * 48, y = 8 + rand() * 48;
      out += circ(x + 1, y + 1.4, 3.6, "#000", "none", 1, op(0.2)) + [0, 1, 2, 3, 4, 5].map(k => ell(x + Math.cos(k * 1.047) * 2.4, y + Math.sin(k * 1.047) * 2.4, 2.2, 1, "#f4f2ea", k * 60)).join("") + circ(x, y, 1.2, "#e8c040");
    }
    return out;
  }},
  cracked_earth: {scale: 1.1, biome: "desert", name: "Cracked earth", rule: null, draw: () =>
    path("M8 30Q10 12 32 10Q54 10 56 30Q58 52 32 54Q8 54 8 30Z", "#c9a06a", "none", 1, op(0.6))
    + path("M14 28L24 24 30 30 40 22 50 28M24 24L22 14M30 30L28 42 18 46M40 22L44 12M30 30L42 38 50 46M42 38L52 36", "none", "#6a4a28", 1.2, op(0.85))},
  oasis_pool: {scale: 1.15, biome: "desert", name: "Small oasis", rule: null, draw: seed => soft(34, 36, 26, 22, 0.15)
    + path("M12 32Q12 16 30 15Q48 14 52 30Q54 46 36 48Q16 50 12 32Z", "#d8c08a", "none") + path("M16 32Q16 20 30 19Q45 18 48 30Q50 43 36 44Q20 45 16 32Z", "#3f8a94", "#2a5a60", 0.8)
    + path("M20 28Q24 22 32 22", "none", "#bfe6ea", 1.6, op(0.7))
    + [[14, 20], [48, 22], [46, 46], [16, 44]].map(([x, y], i) => blade(x, y, i * 90 - 40, 9, 2, "#5d8c34") + blade(x, y, i * 90 + 10, 8, 2, "#7aa548")).join("")},
  desert_rocks: {scale: 1.25, biome: "desert", name: "Desert rocks", rule: "SIMPLE_COVER", draw: seed => rock(24, 28, 15, 561 + seed * 13, "warm", {sides: 6}) + rock(44, 40, 11, 562 + seed * 13, "warm", {sides: 5}) + rock(42, 20, 6, 563 + seed * 13, "warm", {sides: 5})},
  snowy_log: {scale: 1.05, biome: "winter", name: "Snowy log", rule: "SIMPLE_COVER", draw: () => soft(33, 38, 30, 11, 0.3)
    + path("M4 26Q4 22 9 22H55Q60 22 60 32Q60 42 55 42H9Q4 42 4 38Z", "#5e4a34", "#2b1d10", 1.1) + path("M8 30H56M9 36H57", "none", "#3e2f20", 0.9)
    + ell(56, 32, 4.5, 10, "#b8946a", 0, ` stroke="#2b1d10" stroke-width="1"`)
    + path("M6 26Q12 18 22 22Q30 17 40 22Q48 18 56 24Q50 28 40 27Q30 30 20 27Q12 30 6 26Z", "#eef4f9", "#9fb2c4", 0.8)},
  snow_tufts: {biome: "winter", name: "Grass in snow", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let t = 0; t < 5; t += 1) {
      const cx = 10 + rand() * 44, cy = 10 + rand() * 44;
      out += ell(cx + 1, cy + 1.5, 6, 3, "#9fb2c4", 0, op(0.5));
      for (let i = 0; i < 7; i += 1) out += blade(r2(cx + (rand() - 0.5) * 3), r2(cy), r2(-50 + rand() * 100), 6 + rand() * 4, 1, ["#a89a5a", "#c4b47a", "#8a7a48"][i % 3]);
    }
    return out;
  }},
  bog_tufts: {biome: "swamp", name: "Bog tussocks", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let t = 0; t < 4; t += 1) {
      const cx = 12 + rand() * 40, cy = 12 + rand() * 40;
      out += soft(cx + 2, cy + 2.5, 8, 6, 0.4) + circ(cx, cy, 6, "#5a5a2a", "#2a2a12", 0.8);
      for (let i = 0; i < 12; i += 1) out += blade(r2(cx), r2(cy), r2(rand() * 360), 7 + rand() * 4, 1.2, ["#8a8a3a", "#a8a04a", "#6a6a2a"][i % 3]);
    }
    return out;
  }},
  swamp_puddle: {scale: 1.15, biome: "swamp", name: "Stagnant puddle", rule: null, draw: () =>
    path("M12 32Q12 16 30 15Q50 14 52 30Q54 46 36 48Q16 50 12 32Z", "#2a3420", "#1a2012", 1) + path("M16 30Q18 20 30 19", "none", "#7a8a5a", 1.4, op(0.6))
    + [[24, 30, 4], [38, 38, 3], [34, 24, 2.4]].map(([x, y, r]) => ell(x, y, r, r * 0.6, "#6a7a3a", 20, op(0.8))).join("") + circ(40, 28, 2, "none", "#9aaa6a", 0.5, op(0.6))},
  stone_bench: {scale: 1.1, biome: "temple", name: "Stone bench", rule: "SIMPLE_COVER", draw: () => soft(34, 37, 26, 10, 0.45)
    + path("M6 26H58V38H6Z", "#a39e92", "#4a4740", 1) + path("M7 27H57", "none", "#e8e4d8", 1.2, op(0.8)) + path("M6 38H58", "none", "#5a564e", 1.4)
    + path("M14 26V38M50 26V38", "none", "#7a766c", 0.8)},
  raked_gravel: {biome: "temple", name: "Raked gravel", rule: null, draw: () =>
    [10, 18, 26, 34, 42, 50].map(y => path(`M2 ${y}Q20 ${y - 3} 32 ${y}T62 ${y}`, "none", "#c8c2b2", 2, op(0.55)) + path(`M2 ${y + 2}Q20 ${y - 1} 32 ${y + 2}T62 ${y + 2}`, "none", "#6e6a60", 1, op(0.45))).join("")
    + rock(46, 30, 7, 731, "grey", {sides: 6})},
  plum_petals: {biome: "temple", name: "Fallen plum petals", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let i = 0; i < 46; i += 1) out += ell(4 + rand() * 56, 4 + rand() * 56, 1.6, 1, ["#f6b8cc", "#fbd8e4", "#e890ac"][i % 3], rand() * 180, op(0.9));
    return out;
  }},
  bronze_cauldron: {scale: 1.55, biome: "temple", name: "Bronze cauldron", rule: "SIMPLE_COVER", draw: () => soft(36, 38, 18, 16, 0.45)
    + circ(32, 32, 16, "#6a5a2a", "#22180a", 1.2) + circ(32, 32, 13, "#b08a3a", "#5a4416", 0.8) + circ(32, 32, 11, "#2a2016")
    + circ(30, 30, 6, "#3a3020") + [[14, 32], [50, 32]].map(([x, y]) => path(`M${x} ${y - 5}v10`, "none", "#8a6a2a", 3)).join("")
    + path("M20 24A14 14 0 0 1 30 18", "none", "#f0d08a", 1.6, op(0.7)) + path("M30 26Q26 18 32 12", "none", "#d8d4cc", 1.6, op(0.3))},
  firewood_stack: {scale: 1.25, biome: "village", name: "Firewood stack", rule: "SIMPLE_COVER", draw: () => soft(34, 38, 26, 16, 0.45)
    + Array.from({length: 12}, (_, i) => {
      const x = 14 + (i % 6) * 7.2 + (Math.floor(i / 6) % 2) * 3.6, y = 26 + Math.floor(i / 6) * 10;
      return circ(x, y, 3.8, "#6e5133", "#2b1d10", 0.8) + circ(x - 0.4, y - 0.4, 2.6, "#c9a170") + circ(x - 0.4, y - 0.4, 1.1, "none", "#8a6640", 0.5);
    }).join("")},
  flower_planter: {scale: 1.1, biome: "village", name: "Flower planter", rule: null, draw: seed => soft(34, 37, 24, 12, 0.4)
    + path("M8 24H56V40H8Z", "#7a5a38", "#2b1d10", 1) + path("M10 26H54V38H10Z", "#4a3520")
    + bush(18, 32, 6, seeded(seed), ["#1f3a17", "#4c7a2e", "#8fbf55"]) + bush(32, 32, 6, seeded(seed + 1), ["#1f3a17", "#4c7a2e", "#8fbf55"]) + bush(46, 32, 6, seeded(seed + 2), ["#1f3a17", "#4c7a2e", "#8fbf55"])
    + [[16, 30, "#e0402a"], [20, 34, "#f3e36a"], [30, 30, "#c98ad8"], [34, 34, "#e0402a"], [44, 30, "#f3e36a"], [48, 34, "#f08aa8"]].map(([x, y, c]) => circ(x, y, 1.6, c, "rgba(0,0,0,.3)", 0.3)).join("")},
  mud_puddle: {scale: 1.15, biome: "village", name: "Muddy puddle", rule: null, draw: () =>
    path("M10 32Q10 18 28 16Q50 14 54 30Q56 46 36 48Q14 50 10 32Z", "#4a3a26", "none", 1, op(0.7)) + path("M16 32Q16 22 30 21Q46 20 48 31Q49 42 35 43Q20 44 16 32Z", "#5a5a50", "#2a2216", 0.8, op(0.85))
    + path("M20 28Q24 24 32 24", "none", "#b8b8a8", 1.2, op(0.6)) + ell(26, 38, 3, 1.4, "#3a2a1a", 15) + ell(40, 34, 2.4, 1.2, "#3a2a1a", -20)},
  caltrops: {biome: "battlefield", name: "Caltrops", rule: "DIFFICULT", draw: seed => {
    const rand = seeded(seed);
    let out = "";
    for (let i = 0; i < 16; i += 1) {
      const x = 6 + rand() * 52, y = 6 + rand() * 52, a = rand() * 120;
      out += circ(x + 0.8, y + 1.2, 2.6, "#000", "none", 1, op(0.3))
        + [0, 120, 240].map(k => path(`M${r2(x)} ${r2(y)}L${r2(x + Math.cos((a + k) * Math.PI / 180) * 3.2)} ${r2(y + Math.sin((a + k) * Math.PI / 180) * 3.2)}`, "none", "#3a3f45", 1.4)).join("")
        + circ(x, y, 1, "#9aa1a8");
    }
    return out;
  }},
  palisade: {scale: 1.0, biome: "battlefield", name: "Wooden palisade", rule: "SIMPLE_COVER", draw: () => soft(32, 37, 32, 8, 0.45)
    + Array.from({length: 9}, (_, i) => {
      const x = 4 + i * 7;
      return circ(x, 32, 4, "#7a5a38", "#2b1d10", 0.9) + circ(x - 0.6, 31.4, 2.6, "#b48a5c") + path(`M${x - 1.6} 30.4l1.6-1.6 1.6 1.6`, "none", "#e0c79a", 0.8);
    }).join("") + path("M0 36H64", "none", "#3a2a1a", 1.6, op(0.7))},
  trampled_grass: {biome: "battlefield", name: "Trampled grass", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = path("M8 30Q12 16 30 16Q50 16 54 32Q54 48 32 50Q12 48 8 30Z", "#5a4a2a", "none", 1, op(0.35));
    for (let i = 0; i < 40; i += 1) out += blade(r2(8 + rand() * 48), r2(8 + rand() * 48), r2(60 + rand() * 50), 7, 1.1, ["#7a8a3a", "#5e6e2c", "#8a7a3a"][i % 3]);
    return out;
  }},

  // ---------------------------------------------------------------- cultivation sect
  spirit_herbs: {scale: 1.25, biome: "cultivation", name: "Spirit herbs", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = glow(32, 32, 22).replaceAll("#ffcf6e", "#9ff0c8").replaceAll("#ffe2a0", "#d6ffe8");
    for (const [cx, cy] of [[24, 26], [40, 30], [30, 42]]) {
      out += soft(cx + 1.5, cy + 2, 7, 6, 0.3);
      for (let i = 0; i < 7; i += 1) {
        const a = i * 51 + rand() * 20;
        out += `<g transform="translate(${cx} ${cy}) rotate(${r2(a)})">${path("M0 0Q3 -4 0 -9Q-3 -4 0 0Z", i % 2 ? "#5fbf8a" : "#3f9a6a", "#1f4a34", 0.5)}${path("M0 -1V-8", "none", "#c8f0d8", 0.5)}</g>`;
      }
      out += circ(cx, cy, 2, "#f0f8ff", "#7fd6b8", 0.6) + circ(cx, cy, 0.9, "#9ff0ff");
    }
    return out;
  }},
  qi_crystals: {scale: 1.5, biome: "cultivation", name: "Qi crystal cluster", rule: "SIMPLE_COVER", draw: () =>
    glow(32, 32, 26).replaceAll("#ffcf6e", "#7fc8ff").replaceAll("#ffe2a0", "#c8ecff") + soft(36, 38, 18, 14, 0.4)
    + [[30, 30, -20, 18], [38, 34, 30, 14], [24, 38, -60, 12], [36, 24, 10, 11], [28, 22, -40, 9]].map(([x, y, a, l]) =>
      `<g transform="translate(${x} ${y}) rotate(${a})">${path(`M0 ${-l}L4 ${-l * 0.55}L3 4L-3 4L-4 ${-l * 0.55}Z`, "#6fb8f0", "#2a5a8a", 0.8, op(0.92))}${path(`M0 ${-l}L4 ${-l * 0.55}L0 2Z`, "#d6f0ff", "none", 1, op(0.8))}${path(`M0 ${-l}V2`, "none", "#ffffff", 0.6, op(0.8))}</g>`).join("")},
  formation_flags: {scale: 1.35, biome: "cultivation", name: "Formation flags", rule: null, draw: () =>
    circ(32, 32, 20, "none", "#d4a957", 0.8, ` stroke-dasharray="2 2"` + op(0.7))
    + [0, 1, 2, 3, 4, 5, 6, 7].map(i => {
      const a = i * Math.PI / 4, x = 32 + Math.cos(a) * 20, y = 32 + Math.sin(a) * 20, c = ["#c8402f", "#3f6fb0", "#e8c040", "#4f8a5f"][i % 4];
      return circ(x + 1, y + 1.4, 2.2, "#000", "none", 1, op(0.3)) + circ(x, y, 1.6, "#5a4630") + path(`M${r2(x)} ${r2(y)}l${r2(Math.cos(a + 1.2) * 7)} ${r2(Math.sin(a + 1.2) * 7)}l${r2(Math.cos(a + 0.6) * 4)} ${r2(Math.sin(a + 0.6) * 4)}z`, c, "rgba(0,0,0,.4)", 0.5);
    }).join("") + path("M32 24v16M24 32h16", "none", "#d4a957", 0.8, op(0.6))},
  array_stone: {scale: 1.6, biome: "cultivation", name: "Array stone", rule: "SIMPLE_COVER", draw: () =>
    glow(32, 32, 20).replaceAll("#ffcf6e", "#9fdcff").replaceAll("#ffe2a0", "#d6f2ff") + soft(36, 38, 16, 14, 0.45)
    + path("M20 18L44 18 48 32 44 46 20 46 16 32Z", "#6a7078", "#2a2e33", 1.1) + path("M20 18L44 18 40 26 24 26Z", "#a8b0b8")
    + circ(32, 34, 7, "none", "#7fd0ff", 1.2) + path("M32 27v14M25 34h14M27 29l10 10M37 29l-10 10", "none", "#7fd0ff", 0.7) + circ(32, 34, 2, "#d6f2ff")},
  sect_gate_pillar: {scale: 1.45, biome: "cultivation", name: "Sect gate pillar", rule: "SIMPLE_COVER", draw: () => soft(38, 40, 20, 18, 0.5)
    + path("M14 14H50V50H14Z", "#5a5650", "#22201c", 1) + path("M14 14L18 18H46L50 14Z", "#9a948a")
    + circ(32, 32, 13, "#9a2a22", "#3a0c08", 1.2) + circ(32, 32, 10, "none", "#d4a957", 1.2) + circ(29, 29, 4, "#c8483a", "none", 1, op(0.7))
    + path("M32 22v20M22 32h20", "none", "#d4a957", 0.8, op(0.7))},
  jade_stele: {scale: 1.35, biome: "cultivation", name: "Jade stele", rule: "SIMPLE_COVER", draw: () => soft(36, 39, 22, 10, 0.5)
    + path("M10 26H54V40H10Z", "#4a4640", "#1a1814", 1) + path("M14 28H50V38H14Z", "#3f9a7a", "#1a4a3a", 1) + path("M15 29H49", "none", "#a8f0d0", 1, op(0.7))
    + [18, 23, 28, 33, 38, 43].map(x => path(`M${x} 31v4`, "none", "#1a4a3a", 1)).join("") + path("M10 26Q32 20 54 26", "none", "#6a665e", 1.4)},
  beast_nest: {scale: 1.45, biome: "cultivation", name: "Spirit-beast nest", rule: null, draw: seed => {
    const rand = seeded(seed);
    let out = soft(34, 36, 20, 18, 0.4);
    for (let i = 0; i < 40; i += 1) {
      const a = rand() * Math.PI * 2, r = 12 + rand() * 6, l = 6 + rand() * 6, x = 32 + Math.cos(a) * r, y = 32 + Math.sin(a) * r;
      out += path(`M${r2(x)} ${r2(y)}l${r2(Math.cos(a + 1.6) * l)} ${r2(Math.sin(a + 1.6) * l)}`, "none", ["#8a6a3a", "#a8844a", "#6a4a2a"][i % 3], 1.4);
    }
    return out + circ(32, 32, 11, "#4a3420") + [[28, 30, "#e8e0f0"], [35, 29, "#d6f0ff"], [32, 36, "#f6e0c0"]].map(([x, y, c]) => ell(x, y, 4, 3.2, c, -20, ` stroke="#6a6060" stroke-width=".6"`) + ell(x - 1, y - 1, 1.4, 0.9, "#ffffff", -20, op(0.8))).join("")
      + circ(32, 32, 11, "none", "#9ff0ff", 0.6, op(0.5));
  }},
  broken_immortal_sword: {scale: 1.3, biome: "cultivation", name: "Broken immortal sword", rule: null, draw: () =>
    glow(32, 32, 18).replaceAll("#ffcf6e", "#c8e8ff").replaceAll("#ffe2a0", "#ffffff") + soft(34, 36, 22, 8, 0.3)
    + path("M10 44L30 26", "none", "#2a2f33", 5) + path("M10 44L30 26", "none", "#e8f0f6", 3.4) + path("M12 42L28 27.6", "none", "#ffffff", 1, op(0.8))
    + path("M30 26l3 1-1 3", "#e8f0f6", "#2a2f33", 0.6) + path("M8 46l-3 3M6 41l6 6", "none", "#d4a957", 2.4) + circ(4, 50, 2, "#d4a957", "#5a4416", 0.6)
    + path("M40 20L50 12", "none", "#2a2f33", 4.6) + path("M40 20L50 12", "none", "#e8f0f6", 3) + path("M50 12l4 -2-2 4z", "#e8f0f6", "#2a2f33", 0.5)
    + path("M36 30l3-2M42 26l2 3", "none", "#9fdcff", 1, op(0.8))},
  spirit_spring: {scale: 1.35, biome: "cultivation", name: "Spirit spring", rule: null, draw: () =>
    glow(32, 32, 26).replaceAll("#ffcf6e", "#8ff0e0").replaceAll("#ffe2a0", "#d6fff8")
    + Array.from({length: 12}, (_, i) => rock(32 + Math.cos(i * 0.5236) * 18, 32 + Math.sin(i * 0.5236) * 17, 4.5, 761 + i, "grey", {sides: 6, squash: 0.85})).join("")
    + circ(32, 32, 14, "#2f8a8a", "#1a4a4a", 1) + circ(32, 32, 9, "none", "#9ff0e0", 1, op(0.7)) + circ(32, 32, 4.5, "none", "#d6fff8", 1, op(0.8)) + circ(32, 32, 1.6, "#ffffff")},
});

export const DECOR_KINDS = Object.freeze(Object.keys(DECOR));

// A piece's drawing, grown about the square's centre so a single-square prop fills most of its square (owner
// 2026-10-08: props at 40% of the cell were too small to read at table zoom).
export function decorArt(kind, seed = 1) {
  const piece = DECOR[kind];
  if (!piece) return "";
  const body = piece.draw(Number(seed) || 1);
  return piece.scale ? `<g transform="translate(32 32) scale(${piece.scale}) translate(-32 -32)">${body}</g>` : body;
}

// One decoration's markup in a 64x64 square, turned about its centre.
export function decorMarkup(kind, {seed = 1, rotation = 0} = {}) {
  if (!DECOR[kind]) return "";
  const turn = Number(rotation) || 0;
  return `<g class="tt-decor-art" data-decor="${kind}"${turn ? ` transform="rotate(${turn} 32 32)"` : ""}>${decorArt(kind, seed)}</g>`;
}

// ---------------------------------------------------------------- one layer for many pieces (review fix 1)
// Each piece is drawn once per variant and reused with <use>; a piece's seed picks one of DECOR_VARIANTS variants.
export const DECOR_VARIANTS = 4;
const pieces = new Map();
const decorId = row => `tt-dp-${row.kind}-${Math.abs(Number(row.seed) || 1) % DECOR_VARIANTS}`;
function decorShape(row) {
  const id = decorId(row);
  if (!pieces.has(id)) pieces.set(id, `<g id="${id}">${decorArt(row.kind, 1 + (Math.abs(Number(row.seed) || 1) % DECOR_VARIANTS) * 7)}</g>`);
  return pieces.get(id);
}
// The decoration layer in square units: each distinct piece once, then one <use> per placed piece, turned in place.
export function decorLayerMarkup(rows) {
  const valid = rows.filter(row => DECOR[row?.kind] && !DECOR[row.kind].rule && Number.isFinite(row.x) && Number.isFinite(row.y));
  const used = new Map(valid.map(row => [decorId(row), row]));
  return `<defs>${[...used.values()].map(decorShape).join("")}</defs>` + valid.map(row => {
    const turn = [90, 180, 270].includes(Number(row.rotation)) ? ` rotate(${Number(row.rotation)} 32 32)` : "";
    return `<use href="#${decorId(row)}" class="tt-decor" transform="translate(${row.x} ${row.y}) scale(0.015625)${turn}"/>`;
  }).join("");
}

// The same pieces as sprites for scenery-raster.js (each piece fills its square, with room for glow and shadow).
export function decorScene(rows) {
  const valid = rows.filter(row => DECOR[row?.kind] && !DECOR[row.kind].rule && Number.isFinite(row.x) && Number.isFinite(row.y));
  const shapes = new Map();
  for (const row of valid) {
    const id = decorId(row);
    if (!shapes.has(id)) shapes.set(id, {markup: `<g transform="scale(0.015625)">${decorShape(row).replace(` id="${id}"`, "")}</g>`, box: [-0.5, -0.5, 2, 2]});
  }
  return {shapes, placements: valid.map(row => ({id: decorId(row), x: row.x, y: row.y, rotation: [90, 180, 270].includes(Number(row.rotation)) ? Number(row.rotation) : 0})),
          fallback: () => decorLayerMarkup(valid)};
}
