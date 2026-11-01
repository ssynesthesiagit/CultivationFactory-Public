// New placeable object art catalog (owner 2026-10-08: "add more assets ... give them hp ac etc ... have it work on
// building lots of various assets that make sense"). Same hand as object-art.js: top-down, one 64x64 square, lit
// from the north-west, each prop standing on a soft blurred contact shadow that falls south-east (a tall prop's
// falls further); no frame round the square; rotation and shadow wrapping are object-art.js's job (objectArt()),
// not this file's -- every case here only returns {sil, defs, body, tall?}, exactly like object-art.js's own prop().
// This file is self-contained (its own tiny paint helpers) so object-art.js only needs one import and one line in
// its default switch branch: the smallest hook, not a shared module both files depend on.

const style = (fill, stroke = "none", width = 1, extra = "") => `style="fill:${fill};stroke:${stroke};stroke-width:${width};stroke-linecap:round;stroke-linejoin:round${extra}"`;
const P = (d, fill, stroke, width, extra) => `<path d="${d}" ${style(fill, stroke, width, extra)}/>`;
const R = (x, y, w, h, fill, rx = 0, stroke, width, extra) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" ${style(fill, stroke, width, extra)}/>`;
const C = (x, y, r, fill, stroke, width, extra) => `<circle cx="${x}" cy="${y}" r="${r}" ${style(fill, stroke, width, extra)}/>`;
const E = (x, y, rx, ry, fill, stroke, width, extra) => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" ${style(fill, stroke, width, extra)}/>`;
const f = n => Math.round(n * 100) / 100;
const stops = list => list.map(([at, color, alpha = 1]) => `<stop offset="${at}" stop-color="${color}" stop-opacity="${alpha}"/>`).join("");
const linear = (id, [x1, y1, x2, y2], list) => `<linearGradient id="${id}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stops(list)}</linearGradient>`;
const radial = (id, [cx, cy, r], list) => `<radialGradient id="${id}" cx="${cx}" cy="${cy}" r="${r}">${stops(list)}</radialGradient>`;

// Material ramps, north-west lit to south-east shade (the same light object-art.js's trees, bamboo and props use).
const WOOD = [[0, "#d4a66b"], [0.55, "#a8773f"], [1, "#6e4824"]];
const DARK_WOOD = [[0, "#9a6d43"], [0.6, "#6b4628"], [1, "#3f2814"]];
const RED_WOOD = [[0, "#b23a2c"], [0.5, "#7e241a"], [1, "#43110b"]]; // lacquered wood
const IRON = [[0, "#7d848c"], [0.5, "#4a5058"], [1, "#25292e"]];
const BRONZE = [[0, "#f3d58e"], [0.45, "#c0903f"], [1, "#5e4019"]];
const STONE = [[0, "#d9d5ca"], [0.55, "#a9a59a"], [1, "#6c6960"]];
const CLOTH = [[0, "#e7dcc0"], [0.5, "#c7b488"], [1, "#8a7550"]]; // undyed linen / burlap
const RED_CLOTH = [[0, "#e0634e"], [0.45, "#b5352a"], [1, "#5f1712"]]; // lacquer-red banner cloth
const CANVAS = [[0, "#d8cfa8"], [0.5, "#b6a877"], [1, "#766b46"]]; // tent/awning canvas
const STRAW = [[0, "#e8c96a"], [0.5, "#c9a238"], [1, "#8a6a1e"]];
const WATER = [[0, "#bfe3ea"], [0.5, "#7fb6c4"], [1, "#3f7a8c"]];
const COAL = [[0, "#ffdf8a"], [0.35, "#f08838"], [1, "#6e1e0a"]];
const LEATHER = [[0, "#c08a56"], [0.5, "#8c5c34"], [1, "#4a2e16"]];

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

// A lumpy pile silhouette: n overlapping rounded blobs along a rough ring, for boulders, sacks of grain, hay.
function lumps(cx, cy, r, n, seed, squash = 1) {
  let d = "";
  for (let i = 0; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2 + seed * 0.7, rad = r * (0.72 + 0.28 * Math.abs(Math.sin(seed + i * 2.1)));
    const x = f(cx + Math.cos(a) * rad), y = f(cy + Math.sin(a) * rad * squash);
    d += `${i ? "L" : "M"}${x} ${y}`;
  }
  return `${d}Z`;
}

export const CATALOG_FACE = {
  incense_burner: "Incense burner", prayer_wheel: "Prayer wheel", bronze_ding: "Bronze ding cauldron",
  stone_guardian_lion: "Stone guardian lion", sutra_shelf: "Sutra shelf", meditation_cushion: "Meditation cushion",
  temple_gong: "Temple gong", offering_table: "Offering altar table", stone_lantern: "Stone lantern",
  market_stall: "Market stall", produce_cart: "Vendor's cart", woven_basket: "Woven basket", grain_sack: "Grain sack",
  water_barrel: "Water barrel", village_well: "Stone well", haystack: "Haystack", fence_section: "Fence section",
  weapon_rack: "Weapon rack", war_brazier: "Iron brazier", palisade_section: "Palisade section",
  sandbag_wall: "Sandbag wall", ballista: "Ballista", camp_banner: "Camp banner", army_tent: "Army tent",
  ammo_crate: "Ammunition crate", alchemy_furnace: "Alchemy furnace", pill_cabinet: "Pill cabinet",
  workbench: "Workbench", blacksmith_anvil: "Blacksmith's anvil", herb_drying_rack: "Herb drying rack",
  fallen_log: "Fallen log", tree_stump: "Tree stump", boulder_pile: "Boulder pile", rowboat: "Rowboat",
  dock_section: "Dock section", dining_table: "Dining table", wooden_bed: "Bed", folding_screen: "Folding screen",
  bookcase: "Bookcase", carved_throne: "Carved throne", steamer_trunk: "Steamer trunk", lacquer_chest: "Lacquer chest",
};
export const CATALOG_KNOWN = new Set(Object.keys(CATALOG_FACE));
// Kinds tall enough to throw the longer shadow object-art.js gives a standing prop (matches pillar/statue/banner/bell/custom).
const TALL = new Set(["prayer_wheel", "bronze_ding", "stone_guardian_lion", "temple_gong", "stone_lantern", "market_stall",
  "weapon_rack", "war_brazier", "camp_banner", "folding_screen", "bookcase", "carved_throne", "army_tent", "alchemy_furnace",
  "village_well", "haystack"]);

function draw(kind, u) {
  switch (kind) {
    // ---------------------------------------------------------------------------------------------- temple / sect
    case "incense_burner": {
      // A squat bronze censer on three short feet: ash-filled bowl, two ring handles, a smouldering stick trailing smoke.
      return {sil: C(32, 34, 16, "#000"),
        defs: radial(`${u}b`, [0.36, 0.3, 0.8], BRONZE) + radial(`${u}a`, [0.4, 0.35, 0.8], [[0, "#4a4038"], [1, "#1c1712"]]),
        body: C(32, 34, 16, `url(#${u}b)`, "#3a2c12", 1.1) + C(32, 34, 13.6, "none", "#f6dc98", 0.9, ";opacity:.6")
          + C(32, 34, 11, `url(#${u}a)`, "#120d08", 0.8) + P("M22 27A11 11 0 0 1 32 23", "none", "#8a6a2e", 1, ";opacity:.5")
          + [[19.5, 34], [44.5, 34]].map(([x, y]) => C(x, y, 2.3, `url(#${u}b)`, "#3a2c12", 0.7)).join("")
          + P("M38 26q1 8-1 14", "none", "#caa968", 1.3) + C(37.4, 24.6, 1, "#ffd27a")
          + P("M37.4 23.6Q40 20 38 16Q42 19 40 24", "none", "#cfd6d8", 1, ";opacity:.4")};
    }
    case "prayer_wheel": {
      // A painted wooden drum, mantras in vertical gilt bands round its side, spinning on a spindle atop a post.
      // Drawn from a little south, like the temple bell, so the drum's side -- not just a flat lid -- is seen;
      // it stays upright however the token is rotated.
      return {tall: true, upright: true, sil: R(18, 16, 28, 31, "#000", 8), base: R(26, 44, 12, 12, "#000", 2),
        defs: linear(`${u}d`, [0, 0, 1, 0], [[0, "#7e241a"], [0.15, "#d4604a"], [0.5, "#b5352a"], [0.85, "#d4604a"], [1, "#5a150f"]])
          + linear(`${u}w`, [0, 0, 1, 1], WOOD) + radial(`${u}g`, [0.4, 0.3, 0.8], [[0, "#fff2c2"], [1, "#9a7a2e"]]),
        body: R(27, 44, 10, 12, `url(#${u}w)`, 2, "#2e1d0d", 1) + P("M28.4 45V55", "none", "#caa968", 0.8, ";opacity:.5")
          + E(32, 44, 9, 3, "#241408", "#3b2612", 0.8)
          + R(19, 16, 26, 29, `url(#${u}d)`, 6, "#3a0f0a", 1.2)
          + [23, 27.5, 36.5, 41].map(x => P(`M${x} 19V42`, "none", "#f0d9a8", 1.1, ";opacity:.8")).join("")
          + P("M19 28.5h26M19 34.5h26", "none", "#5a150f", 0.9, ";opacity:.6")
          + E(32, 16, 13, 4, `url(#${u}g)`, "#5e4019", 1) + E(32, 16, 13, 4, "none", "#ffe9ae", 1, ";opacity:.6")
          + P("M20.5 22A13 13 0 0 1 27 17", "none", "#f6dcae", 1.1, ";opacity:.55")
          + R(30, 5, 4, 12, `url(#${u}w)`, 1, "#2e1d0d", 1) + C(32, 5, 3, `url(#${u}g)`, "#5e4019", 0.9)};
    }
    case "bronze_ding": {
      // A three-legged ritual bronze cauldron wide enough to fill its square; loop handles, a cloud-pattern rim band.
      return {tall: true, sil: C(32, 32, 22, "#000"), base: [[14, 50], [50, 50], [32, 15]].map(([x, y]) => P(`M${x} 50L${x - 2} 58L${x + 2} 58Z`, "#000")).join(""),
        defs: radial(`${u}b`, [0.36, 0.32, 0.78], BRONZE) + radial(`${u}r`, [0.36, 0.32, 0.78], [[0, "#8a6a2e"], [1, "#3a2c12"]]),
        body: [[14, 50], [50, 50], [32, 17]].map(([x, y]) => P(`M${x} ${y}L${x < 32 ? x - 3 : x === 32 ? x : x + 3} ${y + 9}L${x < 32 ? x + 1 : x === 32 ? x - 2 : x - 1} ${y + 9}Z`, `url(#${u}r)`, "#2c2008", 0.8)).join("")
          + C(32, 30, 22, `url(#${u}b)`, "#2c2008", 1.3) + C(32, 30, 19.4, "none", "#f6dc98", 1, ";opacity:.55")
          + C(32, 30, 15, `url(#${u}r)`, "#2c2008", 1) + P("M15 22A17 17 0 0 1 25 12", "none", "#fff2c2", 1.4, ";opacity:.75")
          + [[14, 25], [50, 25]].map(([x, y]) => P(`M${x} ${y}q${x < 32 ? -5 : 5} 1 ${x < 32 ? -5 : 5} 7`, "none", `url(#${u}b)`, 3.2) + P(`M${x} ${y}q${x < 32 ? -5 : 5} 1 ${x < 32 ? -5 : 5} 7`, "none", "#2c2008", 0.7, ";fill:none")).join("")
          + C(32, 30, 10, "none", "#8a6a2e", 0.8) + C(32, 30, 6.5, "none", "#8a6a2e", 0.7, ";opacity:.7")};
    }
    case "stone_guardian_lion": {
      // A carved stone lion's head on a low plinth: a scalloped mane ring, pricked ears, flat stone eyes and
      // snout, and a tail curling round the base -- the features that read "lion" at a glance from above.
      return {tall: true, sil: C(32, 30, 18, "#000"), base: R(9, 9, 46, 46, "#000", 2),
        defs: linear(`${u}p`, [0, 0, 1, 1], STONE) + radial(`${u}m`, [0.38, 0.32, 0.8], [[0, "#fbf9f2"], [0.5, "#d2cdbe"], [1, "#8a867b"]]),
        body: R(9, 9, 46, 46, `url(#${u}p)`, 2, "#55524b", 1.1) + P("M10.5 51.5V10.5h43", "none", "#f4f1e8", 0.9, ";opacity:.55")
          + P("M44 38Q55 44 49 54Q44 48 38 44Z", `url(#${u}p)`, "#6a655b", 0.9)
          + P(fluted(32, 30, 17, 16, 4), `url(#${u}m)`, "#6a655b", 1.1)
          + P("M18 22L25 21L23 28Z", `url(#${u}m)`, "#6a655b", 0.8) + P("M46 22L39 21L41 28Z", `url(#${u}m)`, "#6a655b", 0.8)
          + C(32, 30, 9.4, `url(#${u}m)`, "#6a655b", 1)
          + [[27, 27], [37, 27]].map(([x, y]) => C(x, y, 1.6, "#3a3730")).join("")
          + P("M30 33Q32 35 34 33Q33 37 32 38Q31 37 30 33Z", "#3a3730")
          + P("M20 24A16 16 0 0 1 28 15", "none", "#fffdf6", 1.3, ";opacity:.7")};
    }
    case "sutra_shelf": {
      // An open wooden shelf unit stacked with bound sutra scrolls and folded prayer slips, seen from above.
      return {sil: R(10, 10, 44, 44, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}paint`, [0, 0, 1, 0], [[0, "#e8dcc0"], [1, "#c7b488"]]),
        body: R(10, 10, 44, 44, `url(#${u}w)`, 2, "#3b2612", 1.1) + P("M11.5 52.5V11.5h41", "none", "#e7c28c", 0.8, ";opacity:.6")
          + R(10, 22, 44, 1.6, "#2b1b0e") + R(10, 34, 44, 1.6, "#2b1b0e") + R(10, 46, 44, 1.6, "#2b1b0e")
          + [14, 24, 44].map(x => R(x, 13, 7, 7, `url(#${u}paint)`, 1, "#8a7444", 0.7)).join("")
          + [14, 32, 42].map(x => R(x, 25, 8, 7, `url(#${u}paint)`, 1, "#8a7444", 0.7)).join("")
          + [18, 28, 38, 48].map(x => R(x, 37, 6, 7, `url(#${u}paint)`, 1, "#8a7444", 0.7)).join("")
          + [16, 30].map(x => R(x, 49, 9, 4, "#b5352a", 0.5, "#4a140e", 0.6)).join("")};
    }
    case "meditation_cushion": {
      // A round cloth cushion stuffed with kapok: a piped rolled edge, curved quilting seams from a buttoned
      // centre, and four small corner tufts -- deliberately small and flat on the floor, not scaled up like
      // the standing furniture round it.
      const seams = Array.from({length: 6}, (_, i) => { const a = i / 6 * Math.PI * 2 + 0.4,
        x0 = f(32 + Math.cos(a) * 6), y0 = f(35 + Math.sin(a) * 6), x1 = f(32 + Math.cos(a) * 15.5), y1 = f(35 + Math.sin(a) * 15.5);
        return P(`M${x0} ${y0}Q32 35 ${x1} ${y1}`, "none", "#9a7f52", 0.8, ";opacity:.55"); }).join("");
      return {sil: C(32, 35, 18, "#000"),
        defs: radial(`${u}c`, [0.34, 0.26, 0.85], [[0, "#f3e6c4"], [0.45, "#d9bd86"], [0.8, "#b4925a"], [1, "#7a5c38"]]),
        body: C(32, 35, 18, `url(#${u}c)`, "#4a3a20", 1.1) + C(32, 35, 17.4, "none", "#fff3d8", 1, ";opacity:.4")
          + C(32, 35, 14.6, "none", "#8a7045", 1.1, ";opacity:.5") + seams
          + C(32, 35, 3, "#5a4a2a", "#cdb57e", 0.8) + C(32, 35, 1.1, "#2e2414")
          + [[32, 17.4], [32, 52.6], [13.6, 35], [50.4, 35]].map(([x, y]) => C(x, y, 1.7, "#7a5c38", "#4a3a20", 0.5)).join("")
          + P("M17 26A18 18 0 0 1 27 19", "none", "#fff8e4", 1.3, ";opacity:.65")};
    }
    case "temple_gong": {
      // A broad bronze gong hangs in a lacquered wooden frame on two posts, struck with a padded mallet resting below.
      return {tall: true, sil: C(32, 32, 16, "#000") + R(6, 50, 7, 5, "#000") + R(51, 50, 7, 5, "#000"),
        defs: radial(`${u}g`, [0.35, 0.3, 0.85], BRONZE) + linear(`${u}w`, [0, 0, 1, 0], DARK_WOOD),
        body: R(8, 10, 6, 42, `url(#${u}w)`, 1, "#24160a", 1) + R(50, 10, 6, 42, `url(#${u}w)`, 1, "#24160a", 1)
          + R(6, 51, 9, 4, "#6c685f", 1, "#33312c", 0.8) + R(49, 51, 9, 4, "#6c685f", 1, "#33312c", 0.8)
          + P("M4 11Q6 7 11 8H53Q58 7 60 11L58 14H6Z", "url(#" + u + "w)", "#24160a", 1)
          + C(32, 32, 16, `url(#${u}g)`, "#3a2c12", 1.2) + C(32, 32, 12.6, "none", "#fff2c2", 1, ";opacity:.5")
          + C(32, 32, 6, "none", "#5e4019", 1) + C(32, 32, 2, "#3a2c12")
          + P("M20 24A17 17 0 0 1 29 17", "none", "#fffbe8", 1.6, ";opacity:.75")
          + R(44, 44, 10, 3.4, "#5a3a1c", 1.4, "#24160a", 0.7) + C(53.5, 45.7, 2.4, "#d9b98a", "#5a3a1c", 0.7)};
    }
    case "offering_table": {
      // A low lacquered altar table: a bowl of fruit, an incense stick and a cup of wine set out for the ancestors.
      return {sil: R(9, 18, 46, 30, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], RED_WOOD),
        body: R(9, 18, 46, 30, `url(#${u}w)`, 2, "#2c0e08", 1.1) + R(13, 22, 38, 22, "none", 1, "#f0c98f", 0.8, ";opacity:.5")
          + P("M9 20h46M9 44h46", "none", "#5a140d", 0.9)
          + C(20, 29, 5.4, "#8a6a2e", "#3a2c12", 0.7) + [[-2.4, -1.6], [1.6, -2], [2.2, 1.6], [-1.2, 2.4]].map(([dx, dy]) => C(f(20 + dx), f(29 + dy), 2.2, "#c0392b", "#5a140d", 0.4)).join("")
          + R(32, 24, 7, 11, "#e8dcc0", 1, "#8a7045", 0.7) + P("M35.5 22v-5", "none", "#caa968", 1.3) + C(35.5, 16, 1, "#ffd27a")
          + C(44, 33, 3.4, "#7c4322", "#3a2008", 0.7) + C(44, 33, 2.2, "#c9963f")};
    }
    case "stone_lantern": {
      // A carved stone garden lantern: a square foot, a shaft, a square firebox with a glowing window, and a
      // squared cap broad enough to catch the north-west light like a little roof.
      return {tall: true, sil: R(17, 16, 30, 32, "#000", 3), base: R(21, 44, 22, 10, "#000", 2),
        defs: linear(`${u}paint`, [0, 0, 1, 1], STONE) + radial(`${u}c`, [0.34, 0.3, 0.8], [[0, "#f4f1e6"], [0.55, "#c7c2b4"], [1, "#8a867b"]]),
        body: R(21, 44, 22, 10, `url(#${u}paint)`, 2, "#55524b", 1.1) + P("M22.5 45.5h19", "none", "#f4f1e6", 0.9, ";opacity:.5")
          + R(27, 35, 10, 10, `url(#${u}paint)`, 1, "#55524b", 1) + P("M27.8 35.8v8.4", "none", "#f4f1e6", 0.8, ";opacity:.4")
          + R(20, 20, 24, 16, `url(#${u}paint)`, 2, "#55524b", 1.2) + R(21.2, 21.2, 21.6, 13.6, "none", 1.4, "#f4f1e6", 0.8, ";opacity:.55")
          + R(25, 23, 14, 11, "#241f18", 1.2, "#120d08", 0.8) + R(25, 23, 14, 11, "none", 1, "#ffb14a", 0.7, ";opacity:.75")
          + C(32, 28.5, 3, "#ffe08a") + C(32, 28.5, 5.4, "none", "#ff9a3a", 1.3, ";opacity:.4")
          + P("M15 17L32 8L49 17L45 20L32 13L19 20Z", `url(#${u}c)`, "#6a655b", 1.1)
          + P("M15 17L32 8L49 17", "none", "#fffdf6", 1.4, ";opacity:.7")
          + P("M27 10.5Q32 6 37 10.5Z", `url(#${u}c)`, "#6a655b", 0.8)
          + P("M16.5 18.5A18 18 0 0 1 26 11", "none", "#fffdf6", 1.1, ";opacity:.5")};
    }

    // ------------------------------------------------------------------------------------------- village / market
    case "market_stall": {
      // A wooden vendor's stall with a striped cloth awning over a counter stacked with wares, facing east.
      return {tall: true, sil: P("M4 14L34 4L62 14L62 20L4 20ZM6 22h40v38H6z", "#000"),
        defs: linear(`${u}c`, [0, 0, 1, 0], [[0, "#b5352a"], [0.5, "#e0dcc8"], [1, "#b5352a"]]) + linear(`${u}w`, [0, 0, 1, 1], WOOD),
        body: P("M4 14L34 4L62 14L62 20L4 20Z", `url(#${u}c)`, "#3a1209", 1.1)
          + P("M4 20L4 14L34 4L34 10L10 19Z", "none", "#fff2cf", 0.8, ";opacity:.5")
          + R(6, 22, 40, 38, `url(#${u}w)`, 1.5, "#3b2612", 1.1) + P("M7.5 58.5V23.5h38", "none", "#e7c28c", 0.8, ";opacity:.5")
          + R(9, 25, 34, 8, "none", 1, "#2b1b0e", 0.8) + [[13, 30, 4.4], [24, 29, 4], [34, 31, 4.2]].map(([x, y, r]) => C(x, y, r, "#9a3a2a", "#4a140e", 0.5)).join("")
          + [[13, 37, "#d9b24a"], [24, 37, "#7a9a3a"], [34, 37, "#d9b24a"]].map(([x, y, color]) => R(x - 4, y, 8, 9, color, 1, "#3a2c12", 0.6)).join("")
          + R(44, 4, 4, 54, "none", 1, "#2b1b0e", 0.7)};
    }
    case "produce_cart": {
      // A two-wheeled vendor's cart heaped with vegetables and baskets, pushed from the west, blocking its square.
      return {sil: P("M8 20h36v30H8zM44 30l16 2v8l-16 2z", "#000"),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}t`, [0, 0, 0, 1], [[0, "#8a7a68"], [0.5, "#4b3a2a"], [1, "#2c2016"]]),
        body: P("M43 31L58 33M43 39L58 37", "none", "#3f2814", 3) + P("M43 31L58 33M43 39L58 37", "none", "#b88a55", 1.8)
          + R(14, 6, 24, 7, `url(#${u}t)`, 3, "#1f1710", 1) + R(24.5, 3.6, 5, 3.4, "#3a3f45", 1)
          + R(8, 20, 36, 30, `url(#${u}w)`, 1.5, "#3b2612", 1.1) + P("M9.4 49V21.4h34", "none", "#e7c28c", 0.8, ";opacity:.5")
          + [[16, 30, "#7a9a3a"], [26, 32, "#c9963f"], [36, 29, "#9a3a2a"], [16, 41, "#d9b24a"], [28, 42, "#7a9a3a"], [38, 40, "#9a3a2a"]].map(([x, y, color]) => C(x, y, 4.6, color, "#3a2c12", 0.6)).join("")
          + [[13, 24], [43, 24], [13, 46], [43, 46]].map(([x, y]) => C(x, y, 1, "#c9c2ae", "#2b2e33", 0.3)).join("")};
    }
    case "woven_basket": {
      // A round coiled wicker basket, lid askew: rings of coiled cane crossed by diagonal binding stitches, a
      // cloth bundle showing over the rim.
      const rings = [16.6, 13.2, 9.8, 6.4, 3].map((r, i) => C(32, 34, r, "none", i % 2 ? "#5a3a1c" : "#f0d9a0", 1, `;opacity:${i % 2 ? 0.5 : 0.45}`)).join("");
      const stitches = Array.from({length: 16}, (_, i) => { const a = i / 16 * Math.PI * 2,
        x0 = f(32 + Math.cos(a) * 3), y0 = f(34 + Math.sin(a) * 3), x1 = f(32 + Math.cos(a) * 16.6), y1 = f(34 + Math.sin(a) * 16.6);
        return P(`M${x0} ${y0}L${x1} ${y1}`, "none", "#6a4a22", 0.6, ";opacity:.5"); }).join("");
      return {sil: C(32, 34, 17, "#000"),
        defs: radial(`${u}b`, [0.36, 0.3, 0.82], [[0, "#e2bd7a"], [0.45, "#c89a56"], [0.75, "#9a6b32"], [1, "#5e3c1c"]]),
        body: C(32, 34, 17, `url(#${u}b)`, "#3a2612", 1.2) + rings + stitches
          + C(32, 34, 17.3, "none", "#2b1c0e", 1.4, ";opacity:.35")
          + R(22, 23, 11, 7, "#c7b488", 1.4, "#5a4a2a", 0.8) + P("M23 25Q27 22 33 24", "none", "#f0e2bc", 0.9, ";opacity:.6")
          + P("M16 25A17 17 0 0 1 26 18", "none", "#fff6de", 1.2, ";opacity:.6")};
    }
    case "grain_sack": {
      // A burlap sack slumped against the wall, tied at the neck, heavy with grain spilling a little at the base.
      return {sil: `<g transform="translate(32 33) scale(1.1) translate(-32 -33)">${P(lumps(32, 36, 14, 10, 1.3, 0.85), "#000")}</g>`,
        defs: linear(`${u}c`, [0, 0, 0.7, 1], CLOTH),
        body: `<g transform="translate(32 33) scale(1.1) translate(-32 -33)">`
          + P(lumps(32, 36, 14, 10, 1.3, 0.85), `url(#${u}c)`, "#4a3a20", 1)
          + P("M20 30q4-10 12-10q8 0 12 10", "none", "#8a7550", 0.8, ";opacity:.6")
          + P("M24 23Q32 18 40 23", "none", "#3a2c12", 2.4) + P("M30 21Q32 17 34 21", "none", "#5a4a2a", 1.6)
          + P("M17 33A15 15 0 0 1 25 24", "none", "#f6ecd4", 1.2, ";opacity:.6")
          + [[24, 40], [32, 44], [40, 39]].map(([x, y]) => P(`M${x - 2} ${y}q2 3 4 0`, "none", "#6a5a35", 0.9)).join("") + "</g>"};
    }
    case "water_barrel": {
      // An open-topped rain barrel, rope-handled, half full and kept ready for washing or putting out fires.
      return {sil: C(32, 32, 20, "#000"),
        defs: radial(`${u}b`, [0.36, 0.32, 0.78], [[0, "#c69a5c"], [0.6, "#8f6336"], [1, "#55381a"]]) + radial(`${u}w`, [0.4, 0.35, 0.75], WATER),
        body: C(32, 32, 20, `url(#${u}b)`, "#2e1d0d", 1.2)
          + Array.from({length: 14}, (_, i) => { const a = i / 14 * Math.PI * 2, c = Math.cos(a), s = Math.sin(a); return P(`M${f(32 + c * 15)} ${f(32 + s * 15)}L${f(32 + c * 20)} ${f(32 + s * 20)}`, "none", "#3a2512", 0.7); }).join("")
          + C(32, 32, 17.6, "none", "#24272b", 2.4) + C(32, 32, 14.4, "#24160a", "#3a2512", 1)
          + C(32, 32, 13, `url(#${u}w)`, "none", 0, ";opacity:.9") + E(28, 28, 5, 3, "#eaf6fa", "none", 0, ";opacity:.4")
          + P("M15 23A17 17 0 0 1 25 14", "none", "#f6dcae", 1.2, ";opacity:.7")
          + P("M12 20q-4 2 -2 6M52 20q4 2 2 6", "none", "#5a3a1c", 1.4)};
    }
    case "village_well": {
      // A round stone well under a peaked wooden roof, winch and bucket on a crossbeam, deep shadow in its mouth.
      return {tall: true, sil: P("M6 18L32 6L58 18L58 24L6 24Z", "#000") + C(32, 42, 18, "#000"),
        defs: linear(`${u}r`, [0, 0, 1, 0], DARK_WOOD) + radial(`${u}paint`, [0.36, 0.32, 0.8], STONE),
        body: P("M6 18L32 6L58 18L58 24L6 24Z", `url(#${u}r)`, "#24160a", 1.1)
          + P("M6 24L6 18L32 6L32 12L14 21Z", "none", "#caa968", 0.8, ";opacity:.5")
          + R(30, 10, 4, 18, "#5a3a1c", 1, "#24160a", 0.8)
          + C(32, 42, 18, `url(#${u}paint)`, "#55524b", 1.2) + C(32, 42, 15, "none", "#f4f1e6", 0.9, ";opacity:.5")
          + C(32, 42, 12.4, "#15110c") + E(32, 40.6, 11, 4, "#28211a")
          + P("M19 34A14 14 0 0 1 28 25", "none", "#fffdf6", 1.3, ";opacity:.65")
          + R(28, 20, 8, 3, "#3a2512", 1, "#1a1008", 0.7) + P("M32 23v12", "none", "#5a3a1c", 1.6) + R(29, 34, 6, 3, "#8a6a3a", 1, "#3a2512", 0.6)};
    }
    case "haystack": {
      // A tall conical stack of loose hay, high enough to block sight and movement until it is scattered.
      return {tall: true, sil: C(32, 34, 20, "#000"),
        defs: radial(`${u}h`, [0.36, 0.3, 0.8], STRAW),
        body: C(32, 34, 20, `url(#${u}h)`, "#6a4f16", 1.1)
          + Array.from({length: 40}, (_, i) => { const a = (i * 2.4 + i * i * 0.37) % (Math.PI * 2), r = 4 + (i % 7) * 2.4, x1 = f(32 + Math.cos(a) * r), y1 = f(34 + Math.sin(a) * r * 0.95); return P(`M${x1} ${y1}L${f(x1 + Math.cos(a) * 5)} ${f(y1 + Math.sin(a) * 5)}`, "none", i % 2 ? "#a9822c" : "#f3dd8e", 1, ";opacity:.6"); }).join("")
          + C(32, 34, 17, "none", "#6a4f16", 0.6, ";opacity:.4")
          + P("M15 25A18 18 0 0 1 27 15", "none", "#fdf0c4", 1.4, ";opacity:.55")};
    }
    case "fence_section": {
      // A length of post-and-rail farm fencing running east to west, filling its square like a simple barrier.
      const posts = [10, 32, 54];
      return {sil: R(2, 24, 60, 6, "#000") + R(2, 40, 60, 6, "#000") + posts.map(x => R(x - 3, 16, 6, 40, "#000")).join(""),
        defs: linear(`${u}w`, [0, 0, 0, 1], WOOD),
        body: posts.map(x => R(x - 3, 16, 6, 40, `url(#${u}w)`, 1.5, "#2e1d0d", 1) + C(x, 16, 3, `url(#${u}w)`, "#2e1d0d", 1)).join("")
          + R(2, 25, 60, 5, `url(#${u}w)`, 1, "#2e1d0d", 1) + R(2, 41, 60, 5, `url(#${u}w)`, 1, "#2e1d0d", 1)
          + P("M3 26.5h58M3 42.5h58", "none", "#e7c28c", 0.8, ";opacity:.5")
          + posts.map(x => P(`M${x - 2} 17.5h4`, "none", "#e7c28c", 0.7, ";opacity:.5")).join("")};
    }

    // ---------------------------------------------------------------------------------------- fortress / battlefield
    case "weapon_rack": {
      // A wooden A-frame rack holding spears, a glaive and spare shields for a watch post, facing east.
      return {tall: true, sil: P("M14 54L14 10L50 10L50 54Z", "#000"),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}i`, [0, 0, 1, 1], IRON),
        body: R(14, 10, 6, 44, `url(#${u}w)`, 1, "#2e1d0d", 1) + R(44, 10, 6, 44, `url(#${u}w)`, 1, "#2e1d0d", 1)
          + R(14, 10, 36, 5, `url(#${u}w)`, 1, "#2e1d0d", 1) + R(14, 49, 36, 5, `url(#${u}w)`, 1, "#2e1d0d", 1)
          + [20, 27, 34, 41].map((x, i) => P(`M${x} 48L${x + (i % 2 ? 3 : -3)} 14`, "none", "#5a3a1c", 2) + C(x + (i % 2 ? 3 : -3), 13, 1.6, `url(#${u}i)`, "#24282c", 0.6)).join("")
          + E(18, 46, 5, 3, `url(#${u}i)`, "#24282c", 0.8) + E(45, 46, 5, 3, `url(#${u}i)`, "#24282c", 0.8)
          + P("M15.4 46V11.4h4" , "none", "#e7c28c", 0.8, ";opacity:.5")};
    }
    case "war_brazier": {
      // A standing iron bowl on a tripod stand, heaped with glowing coals and a plume of rising smoke.
      return {tall: true, sil: C(32, 32, 15, "#000"), base: R(26, 46, 12, 10, "#000", 2),
        defs: radial(`${u}i`, [0.36, 0.3, 0.8], IRON) + radial(`${u}c`, [0.4, 0.3, 0.8], COAL),
        body: [[20, 48], [44, 48]].map(([x, y]) => P(`M32 36L${x} ${y}`, "none", `url(#${u}i)`, 2.6)).join("") + P("M32 36L32 50", "none", `url(#${u}i)`, 2.6)
          + C(32, 32, 15, `url(#${u}i)`, "#1c1f23", 1.2) + C(32, 32, 12.4, "none", "#b7bec5", 1, ";opacity:.5")
          + C(32, 32, 10.4, `url(#${u}c)`, "#4a1604", 1) + [[-4, -2], [3, -3], [2, 3], [-2, 2]].map(([dx, dy]) => C(f(32 + dx), f(32 + dy), 2, "#ffe9ae", "none", 0, ";opacity:.8")).join("")
          + P("M28 22q-3-7 2-13M36 22q3-7-1-13", "none", "#9a9a9a", 1.4, ";opacity:.4")
          + P("M20 24A13 13 0 0 1 28 17", "none", "#dfe4e8", 1.3, ";opacity:.6")};
    }
    case "palisade_section": {
      // A row of thick sharpened logs driven upright and lashed with rope, filling its square like a barricade.
      const xs = [8, 18, 28, 38, 48, 58];
      return {sil: xs.map(x => P(`M${x - 4} 6L${x + 4} 6L${x + 3} 58L${x - 3} 58Z`, "#000")).join(""),
        defs: linear(`${u}w`, [0, 0, 1, 0], WOOD),
        body: xs.map(x => P(`M${x - 4} 10L${x} 2L${x + 4} 10L${x + 3} 58L${x - 3} 58Z`, `url(#${u}w)`, "#2e1d0d", 1)
          + P(`M${x - 3} 11L${x} 4L${x + 3} 11`, "none", "#e7c28c", 0.9, ";opacity:.6")
          + P(`M${x - 2.6} 20V54M${x + 2.6} 20V54`, "none", "#5a3a1c", 0.7, ";opacity:.6")).join("")
          + [20, 46].map(y => P(`M5 ${y}H60`, "none", "#6a4a22", 2.4) + P(`M5 ${y}H60`, "none", "#9a6d43", 1.2)).join("")};
    }
    case "sandbag_wall": {
      // Two courses of tied earth-filled sacks stacked brick-fashion into a low rampart; tan burlap, not grey
      // stone, so it reads apart from a boulder pile. Packed fill swallows anything but a solid blow.
      const row = (y, xs) => xs.map(x => R(x, y, 13, 11, `url(#${u}c)`, 5.5, "#4a3a20", 0.9)
        + P(`M${f(x + 1)} ${y + 2}Q${f(x + 6.5)} ${y - 1} ${f(x + 12)} ${y + 2}`, "none", "#f3e9cc", 0.9, ";opacity:.55")
        + C(f(x + 11.6), f(y + 5.5), 1.4, "#4a3a20")).join("");
      return {sil: R(2, 18, 60, 30, "#000", 10),
        defs: linear(`${u}c`, [0, 0, 0, 1], CLOTH),
        body: row(20, [4, 18, 32, 46]) + row(33, [-2, 11, 25, 39, 53])};
    }
    case "ballista": {
      // A siege crossbow bolted to a heavy timber frame on two wheels, bow-arms spread, a bolt nocked, facing east.
      return {sil: P("M6 28h30v8H6zM30 10l26 22l-26 22z", "#000"),
        defs: linear(`${u}w`, [0, 0, 1, 1], DARK_WOOD) + linear(`${u}i`, [0, 0, 1, 0], IRON),
        body: P("M30 10Q46 20 52 32Q46 44 30 54", "none", "#3b2612", 3.4) + P("M30 10Q46 20 52 32Q46 44 30 54", "none", `url(#${u}i)`, 2)
          + R(8, 29, 30, 6, `url(#${u}w)`, 1.5, "#241408", 1.1) + P("M9.4 30.4h27", "none", "#caa968", 0.7, ";opacity:.5")
          + [14, 36].map(x => C(x, 48, 6, "#2b2e33", "#15171a", 1)).join("") + [14, 36].map(x => C(x, 48, 2.6, "#5a5e63")).join("")
          + R(14, 26, 24, 2.4, `url(#${u}i)`, 1) + P("M14 27L50 27", "none", "#caa968", 1, ";marker-end:none")
          + P("M46 25.6L52 27L46 28.4", "none", "#e8c98a", 1.2)};
    }
    case "camp_banner": {
      // A plain cloth standard planted on a bare wooden pole, marking a camp or rally point, flying east.
      return {tall: true, sil: P("M18 22C28 18 36 24 48 20L56 23L50 28L56 33C40 36 30 31 18 34Z", "#000"), base: C(16, 28, 7, "#000"),
        defs: linear(`${u}c`, [0, 0, 0, 1], RED_CLOTH),
        body: C(16, 28, 7, "#5a3a1c", "#24160a", 1) + C(16, 28, 3, "none", "#8a6a3a", 0.8)
          + P("M17 20C27 16 35 22 47 18L55 21L49 26L55 31C39 34 29 29 17 32Z", `url(#${u}c)`, "#3b0c08", 1)
          + P("M20 20C28 18 36 22 44 20M20 31C28 29 36 31 44 30", "none", "#d4a957", 1)
          + P("M17 17v17", "none", "#2b1a0c", 2.6) + P("M17 17v17", "none", "#9b7041", 1.4)};
    }
    case "army_tent": {
      // A canvas command tent pitched over its ridge-pole, guy ropes staked out, pegged shut until torn down.
      return {tall: true, sil: P("M4 36L32 8L60 36L60 56L4 56Z", "#000"),
        defs: linear(`${u}c`, [0, 0, 0, 1], CANVAS),
        body: P("M4 36L32 8L60 36L60 56L4 56Z", `url(#${u}c)`, "#4a4228", 1.2)
          + P("M4 36L32 56L60 36", "none", "#4a4228", 1) + P("M32 8V56", "none", "#4a4228", 1.4)
          + P("M4 36L32 8L32 56", "none", "#efe6c4", 0.9, ";opacity:.5")
          + P("M14 44Q32 34 50 44", "none", "#4a4228", 0.9, ";opacity:.6") + P("M20 50Q32 44 44 50", "none", "#4a4228", 0.9, ";opacity:.5")
          + [[4, 36, -8, 4], [60, 36, 8, 4]].map(([x, y, dx, dy]) => P(`M${x} ${y}L${x + dx} ${y + dy}`, "none", "#2a2514", 1)).join("")
          + R(29, 50, 6, 6, "#2a2514", 1)};
    }
    case "ammo_crate": {
      // A wooden crate of arrows and crossbow bolts, lid pried half off, fletching bristling over the rim.
      const nails = [[11.5, 11.5], [52.5, 11.5], [11.5, 52.5], [52.5, 52.5]];
      return {sil: R(9, 9, 46, 46, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}f`, [0, 0, 1, 1], [[0, "#c18f55"], [1, "#7a5129"]]),
        body: R(9, 9, 46, 46, `url(#${u}f)`, 2, "#3b2612", 1.2) + R(14, 14, 36, 36, `url(#${u}w)`)
          + [10, 18, 26, 34, 42, 50].map(x => P(`M${x} 6L${x + 6} -4`, "none", "#caa968", 2.6)).join("")
          + [14, 23, 32, 41].map(x => P(`M${x} 10L${x + 10} -6`, "none", "#5a3a1c", 1.4)).join("")
          + [14.5, 24.5, 34.5, 44.5].map(x => P(`M${x} 2L${x + 4.4} -7L${x + 5.6} -7L${x + 3.6} 2Z`, "#d9412e", "#4a140e", 0.6)).join("")
          + P("M14 26h36M14 38h36", "none", "#5a3a1c", 1.1) + P("M9.6 13.4h44.8M13.4 9.6v44.8", "none", "#3b2612", 0.9)
          + nails.map(([x, y]) => C(x, y, 0.95, "#d9d2bf", "#2b2e33", 0.4)).join("")};
    }

    // ---------------------------------------------------------------------------------------------- alchemy / workshop
    case "alchemy_furnace": {
      // A clay-lined stone furnace with a glowing firebox slit and a short flue, too solid to see or walk through.
      return {tall: true, sil: R(10, 10, 44, 44, "#000", 4),
        defs: linear(`${u}paint`, [0, 0, 1, 1], STONE) + radial(`${u}g`, [0.4, 0.35, 0.8], COAL),
        body: R(10, 10, 44, 44, `url(#${u}paint)`, 4, "#4a4740", 1.2) + R(15, 15, 34, 34, "none", 2, "#f4f1e6", 0.9, ";opacity:.5")
          + C(44, 16, 5, `url(#${u}paint)`, "#4a4740", 1) + C(44, 16, 2.4, "#2a2620")
          + R(21, 30, 22, 10, "#241a10", 2, "#120d08", 1) + R(24, 33, 16, 4, `url(#${u}g)`, 1)
          + P("M44 27q2-6-1-11M40 27q3-6-1-12", "none", "#9a9a9a", 1.2, ";opacity:.4")
          + P("M16 22A13 13 0 0 1 24 15", "none", "#fffdf6", 1.3, ";opacity:.6")};
    }
    case "pill_cabinet": {
      // A wooden apothecary cabinet of small labelled drawers, each holding a different pill, herb or powder.
      return {sil: R(10, 10, 44, 44, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}d`, [0, 0, 0, 1], [[0, "#e8dcc0"], [1, "#b89a62"]]),
        body: R(10, 10, 44, 44, `url(#${u}w)`, 2, "#3b2612", 1.1) + P("M11.5 52.5V11.5h41", "none", "#e7c28c", 0.8, ";opacity:.55")
          + Array.from({length: 4}, (_, row) => Array.from({length: 4}, (_, col) => {
            const x = 14 + col * 9, y = 13 + row * 9;
            return R(x, y, 7.6, 7, `url(#${u}d)`, 0.6, "#5a4a2a", 0.6) + C(x + 3.8, y + 5.6, 0.6, "#3a2c12");
          }).join("")).join("")};
    }
    case "workbench": {
      // A sturdy, scarred wooden workbench fitted with a vice at one end and a row of tools laid along the back.
      return {sil: R(6, 20, 52, 26, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD),
        body: R(6, 20, 52, 26, `url(#${u}w)`, 2, "#3b2612", 1.1) + P("M7.4 44.6V21.4h49.2", "none", "#e7c28c", 0.8, ";opacity:.5")
          + P("M8 20h50", "none", "#5a3a1c", 1) + R(8, 24, 10, 6, "#5a5e63", 1, "#24282c", 0.9) + P("M10 25v4M16 25v4", "none", "#8a8e93", 1)
          + [[26, 25], [32, 25], [38, 25], [44, 25]].map(([x, y], i) => P(`M${x} ${y}L${x} ${y + 10 + i}`, "none", "#5a5e63", 1.6)).join("")
          + C(50, 32, 4.4, "#6a6e73", "#2b2e33", 0.8) + C(50, 32, 1.6, "#3a3f45")
          + P("M9 40q44 0 48 0", "none", "#5a3a1c", 1, ";opacity:.6")};
    }
    case "blacksmith_anvil": {
      // A solid iron anvil bedded into a thick stump; a heavy obstacle despite its small footprint on the floor.
      return {sil: P("M16 28h32v10H16zM24 38h16v8h-16z", "#000") + C(32, 48, 13, "#000"),
        defs: linear(`${u}w`, [0, 0, 1, 1], DARK_WOOD) + linear(`${u}i`, [0, 0, 1, 1], IRON),
        body: C(32, 48, 13, `url(#${u}w)`, "#241408", 1.1) + C(32, 48, 10.4, "none", "#caa968", 0.8, ";opacity:.5")
          + R(24, 39, 16, 8, `url(#${u}i)`, 1.5, "#15171a", 1) + R(14, 27, 36, 9, `url(#${u}i)`, 2, "#15171a", 1.2)
          + R(16, 27.5, 32, 2.2, "none", "#cfd6da", 0.9, ";opacity:.7")
          + P("M14 31h8v-4h-8z", "none", `url(#${u}i)`, 0) + P("M46 31l8 -2v5l-8 2z", `url(#${u}i)`, "#15171a", 1)
          + P("M19 30A13 13 0 0 1 27 24", "none", "#e6ebee", 1.2, ";opacity:.55")};
    }
    case "herb_drying_rack": {
      // A wooden frame strung with twine, hung with bundles of drying roots, leaves and herbs.
      return {sil: R(8, 8, 48, 48, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 0], WOOD),
        body: R(8, 8, 4, 48, `url(#${u}w)`, 1, "#2e1d0d", 1) + R(52, 8, 4, 48, `url(#${u}w)`, 1, "#2e1d0d", 1)
          + P("M8 10h48M8 54h48", "none", `url(#${u}w)`, 2.4)
          + [16, 28, 40, 50].map(x => P(`M${x} 10V54`, "none", "#8a7045", 0.6, ";opacity:.5")).join("")
          + [[16, 20, "#6a8a3a"], [28, 24, "#9a7a3a"], [40, 20, "#6a8a3a"], [50, 24, "#9a7a3a"], [20, 40, "#7a9a4a"], [44, 42, "#8a6a2e"]]
            .map(([x, y, color]) => P(`M${x} ${y}q-3 6 0 12`, "none", "#5a4a2a", 2) + P(`M${x} ${y}q-3 6 0 12`, "none", color, 1.4)).join("")};
    }

    // ----------------------------------------------------------------------------------------------------- nature
    case "fallen_log": {
      // A great fallen trunk lying across the ground east to west, bark ridges and a mossy flank, cut ends showing rings.
      return {sil: R(4, 22, 56, 20, "#000", 10),
        defs: linear(`${u}w`, [0, 0, 0, 1], DARK_WOOD) + radial(`${u}r`, [0.5, 0.5, 0.6], [[0, "#c9a86a"], [0.6, "#9a7540"], [1, "#5a3a1c"]]),
        body: R(4, 22, 56, 20, `url(#${u}w)`, 10, "#241408", 1.2) + P("M5.4 32Q8 23.4 15 22.6", "none", "#caa968", 1, ";opacity:.5")
          + [26, 30, 34].map(r => C(10, 32, r * 0.55, "none", "#5a3a1c", 0.7, ";opacity:.6")).join("")
          + C(10, 32, 9, `url(#${u}r)`, "#241408", 1) + C(54, 32, 9, `url(#${u}r)`, "#241408", 1)
          + P("M20 24Q32 20 44 24M18 40Q32 44 46 40", "none", "#4a3014", 1, ";opacity:.5")
          + P("M24 23q6 4 0 8q6 4 0 8", "none", "#5a7a3a", 2.2, ";opacity:.5")};
    }
    case "tree_stump": {
      // A wide, weathered tree stump, growth rings on its cut top, bark ridged round the rim, a few mushrooms at the base.
      return {sil: C(32, 32, 17, "#000"),
        defs: radial(`${u}r`, [0.45, 0.4, 0.65], [[0, "#d9b36a"], [0.5, "#a9773f"], [1, "#6a4a22"]]) + linear(`${u}w`, [0, 0, 1, 1], DARK_WOOD),
        body: C(32, 32, 17, `url(#${u}w)`, "#241408", 1.1) + C(32, 32, 14, `url(#${u}r)`, "#4a3014", 1)
          + [10.6, 8, 5.4, 2.8].map(r => C(32, 32, r, "none", "#6a4a22", 0.9, ";opacity:.6")).join("")
          + P("M22 24q4-3 8 0", "none", "#4a3014", 1, ";opacity:.5") + P("M34 38q4 3 8-1", "none", "#4a3014", 1, ";opacity:.4")
          + P("M18 24A14 14 0 0 1 27 16", "none", "#f6e8c6", 1.1, ";opacity:.5")
          + [[42, 42], [45, 38]].map(([x, y]) => E(x, y, 2.6, 1.8, "#d9c2a0", "#8a6a3a", 0.5)).join("")};
    }
    case "boulder_pile": {
      // A jumble of broken boulders and scree heaped together, filling its square; a glancing hit barely chips it.
      return {sil: `<g transform="translate(32 33) scale(1.1) translate(-32 -33)">${P(lumps(32, 34, 18, 11, 2.1), "#000")}</g>`,
        defs: radial(`${u}s1`, [0.36, 0.3, 0.8], STONE) + radial(`${u}s2`, [0.4, 0.3, 0.8], [[0, "#c7c2b4"], [0.6, "#948f80"], [1, "#55524b"]]),
        body: `<g transform="translate(32 33) scale(1.1) translate(-32 -33)">`
          + [[20, 28, 10, `url(#${u}s1)`], [40, 24, 9, `url(#${u}s2)`], [24, 42, 9, `url(#${u}s2)`], [42, 40, 8, `url(#${u}s1)`], [32, 32, 7, `url(#${u}s1)`]]
            .map(([x, y, r, fill]) => C(x, y, r, fill, "#3e3b33", 1)).join("")
          + P("M16 24A16 16 0 0 1 26 15", "none", "#fffdf6", 1.3, ";opacity:.6")
          + P("M14 30q4-2 6 2M36 20q3-2 6 1M20 40q4 2 4 6M38 36q3 2 6 0", "none", "#3e3b33", 0.9, ";opacity:.6") + "</g>"};
    }

    // ------------------------------------------------------------------------------------------------------- water
    case "rowboat": {
      // A wooden rowboat, oars shipped along the thwarts, a pointed bow to the east, filling the square it rests in.
      return {sil: P("M4 32Q10 18 32 18Q54 18 60 32Q54 46 32 46Q10 46 4 32Z", "#000"),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}i`, [0, 0, 1, 1], [[0, "#4a3a28"], [1, "#241408"]]),
        body: P("M4 32Q10 18 32 18Q54 18 60 32Q54 46 32 46Q10 46 4 32Z", `url(#${u}w)`, "#241408", 1.2)
          + P("M8 32Q13 22 32 22Q51 22 56 32Q51 42 32 42Q13 42 8 32Z", `url(#${u}i)`, "#120a04", 0.9)
          + P("M10 32Q14 24 32 24Q50 24 54 32", "none", "#8a6a3a", 0.8, ";opacity:.5")
          + P("M20 24V40M32 22V42M44 24V40", "none", "#5a3a1c", 1)
          + P("M14 32H50", "none", "#6a4a22", 2) + P("M10 20A22 22 0 0 1 24 16", "none", "#f0d9a8", 1, ";opacity:.45")};
    }
    case "dock_section": {
      // A plank section of a wooden pier running east to west over the waterline, walkable but breakable underfoot.
      return {sil: R(2, 14, 60, 36, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 0, 1], WOOD),
        body: R(2, 14, 60, 36, `url(#${u}w)`, 2, "#3b2612", 1) + [20, 32, 44].map(x => P(`M${x} 14V50`, "none", "#2e1d0d", 1)).join("")
          + P("M3.4 15.4h57", "none", "#e7c28c", 0.8, ";opacity:.5")
          + [8, 56].map(x => C(x, 20, 1.1, "#2b2e33")).join("") + [8, 56].map(x => C(x, 44, 1.1, "#2b2e33")).join("")};
    }

    // --------------------------------------------------------------------------------------------------- interior
    case "dining_table": {
      // A long wooden dining table laid with bowls, cups and chopsticks for a meal, running east to west.
      return {sil: R(4, 20, 56, 24, "#000", 4),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD),
        body: R(4, 20, 56, 24, `url(#${u}w)`, 4, "#3b2612", 1.1) + P("M5.4 43.4V21.4h53", "none", "#e7c28c", 0.8, ";opacity:.5")
          + [14, 32, 50].map(x => C(x, 32, 4.4, "#e8dcc0", "#8a7045", 0.7)).join("")
          + [14, 32, 50].map(x => C(x, 32, 2.4, "#c7b488")).join("")
          + [[22, 26], [22, 38], [40, 26], [40, 38]].map(([x, y]) => R(x, y, 0.9, 4, "#4a3014")).join("")};
    }
    case "wooden_bed": {
      // A simple wood-framed bed with a stuffed mattress, a folded blanket at the foot and a pillow at the head.
      return {sil: R(10, 6, 44, 52, "#000", 3),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD) + linear(`${u}m`, [0, 0, 0, 1], [[0, "#eef1e0"], [1, "#c6c7ac"]]),
        body: R(10, 6, 44, 52, `url(#${u}w)`, 3, "#2e1d0d", 1.2) + R(14, 10, 36, 44, `url(#${u}m)`, 3, "#7a7a62", 0.8)
          + R(14, 10, 36, 10, "#d9412e", 2, "#4a140e", 0.7) + P("M16 14h32", "none", "#f0c9c0", 0.7, ";opacity:.5")
          + R(16, 42, 32, 10, "#8a9ab0", 2, "#4a5a6a", 0.6) + P("M18 45q14 3 28 0", "none", "#6a7a8a", 0.8, ";opacity:.6")
          + P("M11.4 9V51", "none", "#e7c28c", 0.8, ";opacity:.4")};
    }
    case "folding_screen": {
      // A tall folding screen of painted panels, standing open enough to block the sight-line across it.
      const panels = [8, 24, 40];
      return {tall: true, sil: R(6, 6, 52, 52, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], DARK_WOOD) + linear(`${u}p`, [0, 0, 1, 1], [[0, "#e8dcc0"], [0.5, "#c7b488"], [1, "#8a7550"]]),
        body: panels.map(x => R(x, 6, 16, 52, `url(#${u}p)`, 1, "#4a3a20", 1.1)).join("")
          + panels.map(x => R(x, 6, 3, 52, `url(#${u}w)`, 0.5, "#241408", 0.8)).join("")
          + R(53, 6, 3, 52, `url(#${u}w)`, 0.5, "#241408", 0.8)
          + P("M14 16Q22 10 30 16T46 16", "none", "#5a7a4a", 1.4, ";opacity:.7")
          + P("M14 44Q22 50 30 44T46 44", "none", "#7a9a5a", 1.2, ";opacity:.6")
          + P("M7.4 7.4V56.6", "none", "#f0e8d0", 0.7, ";opacity:.4")};
    }
    case "bookcase": {
      // A tall wooden bookcase crowded with scrolls and bound volumes, filling its square against the wall.
      return {tall: true, sil: R(6, 6, 52, 52, "#000", 2),
        defs: linear(`${u}w`, [0, 0, 1, 1], WOOD),
        body: R(6, 6, 52, 52, `url(#${u}w)`, 2, "#3b2612", 1.2) + P("M7.4 57.6V7.4h50", "none", "#e7c28c", 0.8, ";opacity:.5")
          + [18, 30, 42, 54].map(y => R(6, y, 52, 1.6, "#2b1b0e")).join("")
          + Array.from({length: 3}, (_, row) => Array.from({length: 7}, (_, i) => {
            const x = 9 + i * 7, y = 9 + row * 12, colors = ["#9a3a2a", "#3a5a8a", "#7a9a3a", "#c9963f", "#5a3a8a"];
            return R(x, y, 5, 8, colors[(i + row) % colors.length], 0.6, "#2b1b0e", 0.5);
          }).join("")).join("")};
    }
    case "carved_throne": {
      // An ornate, high-backed wooden throne, carved and gilded, armrests curling into dragon heads, facing south.
      return {tall: true, sil: R(14, 4, 36, 54, "#000", 4),
        defs: linear(`${u}w`, [0, 0, 1, 1], RED_WOOD) + linear(`${u}g`, [0, 0, 0, 1], BRONZE),
        body: R(14, 4, 36, 24, `url(#${u}w)`, 4, "#2c0e08", 1.2) + P(fluted(32, 14, 16, 10, 2), "none", "#c9963f", 0.7, ";opacity:.4")
          + P("M15.4 6V26", "none", "#e8a27a", 0.8, ";opacity:.4")
          + R(16, 30, 32, 22, `url(#${u}w)`, 3, "#2c0e08", 1.1) + R(20, 34, 24, 14, "#8a2a1e", 2, "#4a140e", 0.7)
          + R(10, 30, 8, 18, `url(#${u}g)`, 3, "#5e4019", 0.9) + R(46, 30, 8, 18, `url(#${u}g)`, 3, "#5e4019", 0.9)
          + C(14, 30, 3, `url(#${u}g)`, "#5e4019", 0.7) + C(50, 30, 3, `url(#${u}g)`, "#5e4019", 0.7)
          + C(32, 16, 4, `url(#${u}g)`, "#5e4019", 0.8)};
    }
    case "steamer_trunk": {
      // A flat-topped travel trunk bound in leather straps with iron corners, scuffed from the road.
      return {sil: R(9, 13, 46, 38, "#000", 3),
        defs: linear(`${u}w`, [0, 0, 0, 1], WOOD) + linear(`${u}l`, [0, 0, 0, 1], LEATHER),
        body: R(9, 13, 46, 38, `url(#${u}w)`, 3, "#2b1b0e", 1.2) + P("M10 19.5h44M10 44.5h44", "none", "#5a3a1c", 0.9)
          + R(9, 24, 46, 6, `url(#${u}l)`, 1, "#2a1a0c", 0.8) + R(9, 38, 46, 6, `url(#${u}l)`, 1, "#2a1a0c", 0.8)
          + [16, 48].flatMap(x => [17, 50].map(y => R(x - 2.5, y - 2.5, 5, 5, "#8a8e93", 0.8, "#2b2e33", 0.5))).join("")
          + R(27, 13, 10, 5, "#8a8e93", 1, "#2b2e33", 0.6) + P("M11.4 15V49", "none", "#f3d39f", 0.7, ";opacity:.5")};
    }
    case "lacquer_chest": {
      // A red-lacquered treasury chest with brass fittings and a phoenix medallion, bigger than a simple chest.
      return {sil: R(8, 9, 48, 46, "#000", 3),
        defs: linear(`${u}l`, [0, 0, 0, 1], RED_WOOD) + radial(`${u}b`, [0.4, 0.35, 0.8], BRONZE),
        body: R(8, 9, 48, 46, `url(#${u}l)`, 3, "#2c0e08", 1.3) + R(8, 9, 48, 10, "#8a2a1e", 2, "#3a1209", 1)
          + P("M10 14h44", "none", "#e8a27a", 0.9, ";opacity:.5") + R(10, 21, 44, 32, "none", 2, "#d4a957", 0.8, ";opacity:.4")
          + C(32, 37, 9, `url(#${u}b)`, "#5e4019", 1) + C(32, 37, 6, "none", "#fff2c2", 0.9, ";opacity:.5")
          + P("M27 32q5-4 10 0M27 42q5 4 10 0", "none", "#5e4019", 1, ";opacity:.6")
          + R(27, 46, 10, 8, `url(#${u}b)`, 1.4, "#5a4214", 0.9) + P("M32 49.4v4", "none", "#2a1d08", 1.4)
          + [[12, 12], [52, 12], [12, 51], [52, 51]].map(([x, y]) => C(x, y, 2.4, `url(#${u}b)`, "#5e4019", 0.7)).join("")};
    }
    default: return null;
  }
}

// Kinds the owner's lead flagged as reading too small at table zoom (2026-10-08 contact-sheet review): scaled up
// around the square's centre so each one fills about 75-85% of it, same as the redrawn crate/barrel/chest do.
// Left at 1 (or close to it) for a kind that is deliberately small (a cushion, a sack) or already fills the square.
const GROW = {
  incense_burner: 1.5, bronze_ding: 1.15, stone_guardian_lion: 1.15, sutra_shelf: 1.1, temple_gong: 1.2,
  offering_table: 1.15, stone_lantern: 1.3, produce_cart: 1.15, woven_basket: 1.35, water_barrel: 1.25,
  weapon_rack: 1.1, war_brazier: 1.3, ballista: 1.2, camp_banner: 1.25, ammo_crate: 1.15, pill_cabinet: 1.1,
  workbench: 1.1, blacksmith_anvil: 1.3, herb_drying_rack: 1.1, tree_stump: 1.3, dining_table: 1.1,
  wooden_bed: 1.1, carved_throne: 1.2, steamer_trunk: 1.2, lacquer_chest: 1.15, dock_section: 1.1,
};
const growGroup = (content, factor) => `<g transform="translate(32 32) scale(${factor}) translate(-32 -32)">${content}</g>`;

export function catalogProp(kind, _open, u) {
  const drawing = draw(kind, u);
  const factor = drawing && GROW[kind];
  if (!drawing || !factor) return drawing;
  return {...drawing, sil: growGroup(drawing.sil, factor), body: growGroup(drawing.body, factor),
           ...(drawing.base ? {base: growGroup(drawing.base, factor)} : {})};
}
