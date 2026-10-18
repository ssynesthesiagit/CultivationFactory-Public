// Built-in map backgrounds (owner 2026-09-25): floors painted in the browser from a style and a
// seed, so every map has a proper background without any art files.  Deterministic: the same
// style, seed and size always paint the same floor.

// Indoor floors/tiles and grass/forest variants (SON202): a separate module so that lane's art never
// touches this file's own painters; STYLES and painter() below just gain its keys.
import {ALL_STYLES as EXTRA_STYLES, STYLE_KIND as EXTRA_KIND, STYLE_BORDER as EXTRA_BORDER, painter as extraPainter}
  from "./floor-art-indoor.js?v=son202r1f1";

export const STYLES = {
  flagstone: "Flagstone courtyard",
  tiles: "Temple tiles",
  wood: "Wooden hall",
  grass: "Grass field",
  sand: "Sand",
  cave: "Cave rock",
  snow: "Snow",
  // More floors (owner 2026-09-27).  The keys are whitelisted server-side (combat/tabletop.py
  // BACKGROUND_STYLES), so renaming one orphans every saved map that uses it.
  lava_rock: "Volcanic rock",
  marsh: "Marsh",
  bamboo: "Bamboo forest floor",
  dirt_road: "Dirt road",
  marble: "Marble hall",
  dark_stone: "Dark stone",
  ice: "Frozen lake",
  shallows: "Shallow water",
  mountain: "Mountain rock",
  graveyard: "Graveyard",
  // Biome floors (owner 2026-10-08: "we might need more floor terrain, jungle biom, etc"). Like every floor they are only
  // the look; what a square does comes from named terrain painted on it (combat/ground_text.py floor_reading).
  jungle: "Jungle floor",
  forest_loam: "Forest loam",
  scree_ground: "Rocky scree",
  dunes: "Desert dunes",
  snowfield: "Windswept snow",
  swamp_mud: "Swamp mud",
  temple_court: "Temple courtyard",
  packed_dirt: "Village packed dirt",
  churned_earth: "Churned battlefield earth",
  plain: "Plain (no pattern)",
  ...EXTRA_STYLES,
};
export const DEFAULT_STYLE = "flagstone";

// Built, laid or maintained surfaces are "artificial"; raw ground, vegetation and undisturbed terrain are
// "natural" (owner 2026-10-08: "sharper tile with a thin border" where an artificial floor meets any other
// floor; natural-to-natural keeps the soft blended edge). Data per look, not a special case in board.js.
// Written as [key, kind] pairs, not `key: "value"` object literals -- this file's own key-collision test
// (floor-art-indoor.test.mjs) regexes for two-space-indented `word: "quoted",` lines to find STYLES' keys, and
// would mistake a literal object shaped the same way for more of them.
const OWN_KIND = Object.fromEntries([
  ["flagstone", "artificial"], ["tiles", "artificial"], ["wood", "artificial"], ["grass", "natural"],
  ["sand", "natural"], ["cave", "natural"], ["snow", "natural"], ["lava_rock", "natural"], ["marsh", "natural"],
  ["bamboo", "natural"], ["dirt_road", "artificial"], ["marble", "artificial"], ["dark_stone", "natural"],
  ["ice", "natural"], ["shallows", "natural"], ["mountain", "natural"], ["graveyard", "natural"],
  ["jungle", "natural"], ["forest_loam", "natural"], ["scree_ground", "natural"], ["dunes", "natural"],
  ["snowfield", "natural"], ["swamp_mud", "natural"], ["temple_court", "artificial"],
  ["packed_dirt", "artificial"], ["churned_earth", "natural"], ["plain", "natural"],
]);
const OWN_BORDER = {
  flagstone: [60, 56, 50], tiles: [52, 46, 36], wood: [38, 28, 20], dirt_road: [70, 56, 40],
  marble: [150, 142, 124], temple_court: [60, 54, 40], packed_dirt: [66, 52, 36],
};
export const STYLE_KIND = Object.freeze({...OWN_KIND, ...EXTRA_KIND});
export const STYLE_BORDER = Object.freeze({...OWN_BORDER, ...EXTRA_BORDER});
const DEFAULT_BORDER = [48, 44, 40];

export const isArtificial = style => STYLE_KIND[style] === "artificial";
export const borderColorFor = style => STYLE_BORDER[style] || DEFAULT_BORDER;

// The one rule (owner 2026-10-08): same style, no seam at all. Otherwise, if either side is artificial, the
// edge is crisp with a thin border in that side's own material colour (the artificial side's, if only one is);
// two naturals meeting stays a soft blended edge, same as every floor boundary did before this. Pure and
// deterministic so it can be tested without a canvas; board.js's per-cell compositing is the only caller.
export function edgeTreatment(styleA, styleB) {
  if (!styleA || !styleB || styleA === styleB) return null;
  const artificialA = isArtificial(styleA), artificialB = isArtificial(styleB);
  if (!artificialA && !artificialB) return {crisp: false, borderColor: null};
  return {crisp: true, borderColor: borderColorFor(artificialA ? styleA : styleB)};
}

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Value noise on a lattice, smooth-stepped, several octaves.
export function makeNoise(seed) {
  const size = 256, rand = mulberry32(seed), table = new Float32Array(size * size);
  for (let i = 0; i < table.length; i += 1) table[i] = rand();
  const at = (x, y) => table[((y & 255) << 8) | (x & 255)];
  const smooth = t => t * t * (3 - 2 * t);
  const value = (x, y) => {
    const x0 = Math.floor(x), y0 = Math.floor(y), fx = smooth(x - x0), fy = smooth(y - y0);
    const a = at(x0, y0), b = at(x0 + 1, y0), c = at(x0, y0 + 1), d = at(x0 + 1, y0 + 1);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  };
  return (x, y, octaves = 4) => {
    let sum = 0, amp = 0.5, freq = 1, norm = 0;
    for (let o = 0; o < octaves; o += 1) { sum += value(x * freq, y * freq) * amp; norm += amp; amp *= 0.5; freq *= 2.03; }
    return sum / norm;
  };
}

// Jittered cells (for flagstones and rock cracks): distance to nearest and second-nearest point.
// Points live in a flat array over the map's extent (no string keys, no hypot: this runs per pixel).
export function makeCells(seed, spacing, widthSquares, heightSquares) {
  const rand = mulberry32(seed ^ 0x9e3779b9);
  const columns = Math.ceil(widthSquares / spacing) + 3, rows = Math.ceil(heightSquares / spacing) + 3;
  const px = new Float32Array(columns * rows), py = new Float32Array(columns * rows), pid = new Float32Array(columns * rows);
  for (let cy = 0; cy < rows; cy += 1) for (let cx = 0; cx < columns; cx += 1) {
    const index = cy * columns + cx;
    px[index] = (cx - 1 + 0.15 + rand() * 0.7) * spacing;
    py[index] = (cy - 1 + 0.15 + rand() * 0.7) * spacing;
    pid[index] = rand();
  }
  const result = {edge: 0, id: 0};
  return (x, y) => {
    const cx = Math.floor(x / spacing) + 1, cy = Math.floor(y / spacing) + 1;
    let d1 = Infinity, d2 = Infinity, id = 0;
    for (let dy = -1; dy <= 1; dy += 1) {
      const row = (cy + dy) * columns;
      for (let dx = -1; dx <= 1; dx += 1) {
        const index = row + cx + dx;
        const ex = x - px[index], ey = y - py[index];
        const d = ex * ex + ey * ey;
        if (d < d1) { d2 = d1; d1 = d; id = pid[index]; } else if (d < d2) d2 = d;
      }
    }
    result.edge = Math.sqrt(d2) - Math.sqrt(d1);
    result.id = id;
    return result;
  };
}

const clamp = value => (value < 0 ? 0 : value > 255 ? 255 : value);
const mix = (a, b, t) => a + (b - a) * t;
const smoothstep = (a, b, t) => { const u = Math.min(1, Math.max(0, (t - a) / (b - a))); return u * u * (3 - 2 * u); };
// One stable pseudo-random value per integer (a slab's tone, whether a grave plot is empty).
const mulberryHash = value => mulberry32((value | 0) ^ 0x5bd1e995)();
// Ridged noise: thin bright lines where the noise crosses its midpoint (caustics, lava veins, marble).
const ridge = (n, sharp) => Math.pow(1 - Math.abs(2 * n - 1), sharp);

// Painter for one style: (squareX, squareY) -> [r, g, b]  (coordinates in squares, fractional).
export function painter(style, seed, widthSquares, heightSquares, patch = false) {
  const noise = makeNoise(seed), fine = makeNoise(seed + 17);
  if (style === "flagstone") {
    const cells = makeCells(seed, 1.45, widthSquares, heightSquares);
    return (x, y) => {
      const {edge, id} = cells(x, y);
      const n = noise(x * 0.8, y * 0.8), f = fine(x * 6, y * 6, 2);
      const base = 96 + id * 24 + (n - 0.5) * 40 + (f - 0.5) * 18;
      const grout = edge < 0.06 ? 0.66 : edge < 0.11 ? 0.86 : 1;
      const warm = id * 10;
      return [base * grout + warm, base * grout + warm * 0.6, base * grout * 0.92];
    };
  }
  if (style === "tiles") {
    return (x, y) => {
      const tx = Math.floor(x), ty = Math.floor(y), u = x - tx, v = y - ty;
      const grout = u < 0.05 || v < 0.05 || u > 0.95 || v > 0.95;
      const checker = (tx + ty) % 2 === 0;
      const n = noise(x * 1.5, y * 1.5), f = fine(x * 8, y * 8, 2);
      if (grout) return [46, 52, 48];
      const shade = (n - 0.5) * 30 + (f - 0.5) * 14;
      return checker ? [112 + shade, 138 + shade, 118 + shade] : [178 + shade, 168 + shade, 140 + shade];
    };
  }
  if (style === "wood") {
    const plankWidth = 0.5, rand = mulberry32(seed + 5), offsets = Array.from({length: 512}, () => rand());
    return (x, y) => {
      const row = Math.floor(y / plankWidth), v = (y / plankWidth) % 1;
      const shift = offsets[row & 511] * 4, seg = Math.floor((x + shift) / 4), u = ((x + shift) / 4) % 1;
      const tone = offsets[(row * 7 + seg) & 511];
      const grain = Math.sin((y * 40) + noise(x * 0.6, y * 4) * 12) * 0.5 + 0.5;
      const seam = v < 0.06 || u < 0.012 ? 0.55 : 1;
      const base = 118 + tone * 40 + grain * 18 + (fine(x * 10, y * 30, 2) - 0.5) * 14;
      return [base * seam * 1.05, base * seam * 0.72, base * seam * 0.45];
    };
  }
  if (style === "grass") {
    return (x, y) => {
      const n = noise(x * 0.35, y * 0.35), m = noise(x * 1.7 + 9, y * 1.7 + 3, 3), f = fine(x * 14, y * 14, 2);
      const dirt = n > 0.64 ? Math.min(1, (n - 0.64) * 6) : 0;
      const g = 96 + (m - 0.5) * 50 + (f - 0.5) * 40;
      return [mix(58 + (m - 0.5) * 20, 128, dirt), mix(g, 104, dirt), mix(44 + (f - 0.5) * 16, 72, dirt)];
    };
  }
  if (style === "sand") {
    return (x, y) => {
      const n = noise(x * 0.4, y * 0.4), ripple = Math.sin(x * 3.1 + y * 1.3 + noise(x * 0.7, y * 0.7) * 8) * 0.5 + 0.5, f = fine(x * 12, y * 12, 2);
      const base = 188 + (n - 0.5) * 40 + ripple * 12 + (f - 0.5) * 14;
      return [base, base * 0.86, base * 0.64];
    };
  }
  if (style === "cave") {
    const cells = makeCells(seed, 2.4, widthSquares, heightSquares);
    return (x, y) => {
      const {edge} = cells(x, y);
      const n = noise(x * 0.5, y * 0.5), f = fine(x * 7, y * 7, 3);
      const crack = edge < 0.05 ? 0.5 : 1;
      const base = (58 + (n - 0.5) * 50 + (f - 0.5) * 30) * crack;
      return [base, base * 0.97, base * 1.02];
    };
  }
  if (style === "snow") {
    return (x, y) => {
      const n = noise(x * 0.3, y * 0.3), f = fine(x * 9, y * 9, 2);
      const base = 214 + (n - 0.5) * 40 + (f - 0.5) * 12;
      return [base * 0.93, base * 0.97, base + 8];
    };
  }
  // ---- More floors (owner 2026-09-27).  Same contract as above: (x, y) in squares -> [r, g, b].
  // A painter may also carry a `decorate(context, pps, rand)` pass for shapes a per-pixel
  // function draws badly (leaves, reeds, headstones); it runs once, after the pixels.
  if (style === "lava_rock") {
    // Cooled basalt: porous, rust-tinged rock whose veins still glow where the ground runs hot.
    return (x, y) => {
      const n = noise(x * 0.4, y * 0.4), f = fine(x * 9, y * 9, 3), pore = fine(x * 24 + 7, y * 24, 1);
      const facet = ridge(noise(x * 0.7 + 3, y * 0.7, 3), 2);
      let base = 36 + facet * 26 + (n - 0.5) * 22 + (f - 0.5) * 20;
      if (pore > 0.72) base *= 0.62;
      const rust = smoothstep(0.55, 0.75, noise(x * 0.5 + 60, y * 0.5, 3));
      const vein = ridge(noise(x * 0.55 + 9, y * 0.55 + 4, 4), 22);
      const heat = smoothstep(0.38, 0.6, noise(x * 0.22 + 40, y * 0.22 + 11, 3));
      const glow = vein * heat;
      const halo = ridge(noise(x * 0.55 + 9, y * 0.55 + 4, 4), 5) * heat * 0.4;
      const r = base * 1.08 + rust * 22 + halo * 90, g = base * 0.95 + rust * 6 + halo * 18, b = base * 0.9;
      return [mix(r, 255, glow), mix(g, 60 + 150 * glow * glow, glow), mix(b, 20 + 50 * glow * glow * glow, glow)];
    };
  }
  if (style === "marsh") {
    // Olive mud and moss broken by pools of dark standing water, reeds at the pool edges.
    const shore = (x, y) => noise(x * 0.26, y * 0.26);
    const paint = (x, y) => {
      const n = shore(x, y), m = noise(x * 1.3 + 7, y * 1.3 + 2, 3), f = fine(x * 11, y * 11, 2);
      const water = smoothstep(0.43, 0.37, n);
      const moss = smoothstep(0.5, 0.66, m);
      const gr = mix(88, 60, moss) + (f - 0.5) * 24, gg = mix(76, 92, moss) + (f - 0.5) * 24, gb = mix(50, 40, moss) + (f - 0.5) * 14;
      const glint = Math.pow(fine(x * 0.9 + 3, y * 2.4, 2), 4) * 70;
      const wr = 26 + glint * 0.55 + (m - 0.5) * 12, wg = 44 + glint * 0.75 + (m - 0.5) * 14, wb = 42 + glint * 0.9;
      const bank = water > 0 && water < 1 ? 1 - Math.abs(water - 0.5) * 2 : 0;  // dark wet line at the waterline
      return [mix(gr, wr, water) * (1 - bank * 0.35), mix(gg, wg, water) * (1 - bank * 0.35), mix(gb, wb, water) * (1 - bank * 0.3)];
    };
    paint.decorate = (context, pps, rand) => {
      const count = Math.round(widthSquares * heightSquares * 1.6);
      context.lineCap = "round";
      for (let index = 0; index < count; index += 1) {
        const x = rand() * widthSquares, y = rand() * heightSquares, n = shore(x, y);
        if (n < 0.37 || n > 0.5) continue;  // reeds grow on the banks, not in open water or dry ground
        const blades = 3 + Math.floor(rand() * 5);
        for (let b = 0; b < blades; b += 1) {
          const angle = -Math.PI / 2 + (rand() - 0.5) * 1.1, length = (0.18 + rand() * 0.28) * pps;
          const bx = x * pps + (rand() - 0.5) * 0.12 * pps, by = y * pps;
          context.strokeStyle = `rgba(${110 + rand() * 50 | 0},${120 + rand() * 40 | 0},${58 + rand() * 20 | 0},0.85)`;
          context.lineWidth = Math.max(0.8, pps * 0.025);
          context.beginPath();
          context.moveTo(bx, by);
          context.quadraticCurveTo(bx + Math.cos(angle) * length * 0.5 + (rand() - 0.5) * pps * 0.08, by + Math.sin(angle) * length * 0.5,
                                   bx + Math.cos(angle) * length, by + Math.sin(angle) * length);
          context.stroke();
        }
      }
    };
    return paint;
  }
  if (style === "bamboo") {
    // Dark earth under a litter of fallen bamboo leaves, dappled by light through the canopy.
    const paint = (x, y) => {
      const n = noise(x * 0.5, y * 0.5), f = fine(x * 10, y * 10, 3), dapple = smoothstep(0.52, 0.7, noise(x * 0.32 + 19, y * 0.32 + 4, 3));
      const base = 58 + (n - 0.5) * 30 + (f - 0.5) * 22 + dapple * 34;
      return [base * 1.08, base * 0.95, base * 0.62];
    };
    paint.decorate = (context, pps, rand) => {
      const leaves = Math.round(widthSquares * heightSquares * 9);
      const tones = [[176, 150, 82], [150, 128, 64], [124, 132, 60], [196, 172, 108], [112, 92, 50], [96, 124, 58]];
      for (let index = 0; index < leaves; index += 1) {
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, angle = rand() * Math.PI;
        const length = (0.3 + rand() * 0.3) * pps, width = (0.045 + rand() * 0.035) * pps;
        const [r, g, b] = tones[Math.floor(rand() * tones.length)], shade = 0.75 + rand() * 0.35;
        context.save();
        context.translate(x, y);
        context.rotate(angle);
        context.fillStyle = `rgba(0,0,0,0.18)`;
        context.beginPath(); context.ellipse(width * 0.3, width * 0.5, length / 2, width / 2, 0, 0, Math.PI * 2); context.fill();
        context.fillStyle = `rgb(${r * shade | 0},${g * shade | 0},${b * shade | 0})`;
        context.beginPath();
        context.moveTo(-length / 2, 0);
        context.quadraticCurveTo(0, -width, length / 2, 0);
        context.quadraticCurveTo(0, width, -length / 2, 0);
        context.fill();
        context.strokeStyle = `rgba(${r * 0.6 | 0},${g * 0.6 | 0},${b * 0.5 | 0},0.6)`;
        context.lineWidth = Math.max(0.5, pps * 0.008);
        context.beginPath(); context.moveTo(-length / 2, 0); context.lineTo(length / 2, 0); context.stroke();
        context.restore();
      }
      // A few fallen culms: long jointed poles, so the floor reads as bamboo rather than any wood.
      const culms = Math.max(1, Math.round(widthSquares * heightSquares / 60));
      for (let index = 0; index < culms; index += 1) {
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, angle = rand() * Math.PI;
        const length = (3 + rand() * 4) * pps, width = (0.2 + rand() * 0.08) * pps;
        context.save();
        context.translate(x, y);
        context.rotate(angle);
        context.fillStyle = "rgba(0,0,0,0.3)";
        context.fillRect(-length / 2 + width * 0.3, -width / 2 + width * 0.35, length, width);
        const gradient = context.createLinearGradient(0, -width / 2, 0, width / 2);
        gradient.addColorStop(0, "#c8bf7a"); gradient.addColorStop(0.45, "#9c9a52"); gradient.addColorStop(1, "#5e6230");
        context.fillStyle = gradient;
        context.fillRect(-length / 2, -width / 2, length, width);
        context.fillStyle = "rgba(60,58,26,0.8)";
        for (let joint = -length / 2 + pps * (0.5 + rand() * 0.4); joint < length / 2 - pps * 0.2; joint += pps * (0.9 + rand() * 0.4)) {
          context.fillRect(joint, -width / 2, Math.max(1, pps * 0.035), width);
        }
        context.restore();
      }
    };
    return paint;
  }
  if (style === "dirt_road" && patch) {
    // Painted as a floor patch (owner 2026-09-29: "dirt road material should be dirt"): packed earth and pebbles only --
    // the road's ruts and grass verges belong to the whole-map background.
    return (x, y) => {
      const n = noise(x * 0.6, y * 0.6), f = fine(x * 12, y * 12, 2), pebble = fine(x * 22 + 3, y * 22, 1);
      const shade = 1 + (pebble > 0.78 ? 0.18 : 0) - (pebble < 0.12 ? 0.1 : 0);
      return [(138 + (n - 0.5) * 34 + (f - 0.5) * 26) * shade, (108 + (n - 0.5) * 28 + (f - 0.5) * 22) * shade, (74 + (n - 0.5) * 20 + (f - 0.5) * 16) * shade];
    };
  }
  if (style === "dirt_road") {
    // A packed-earth road with cart ruts along the long axis of the map, grass verges either side.
    const horizontal = widthSquares >= heightSquares, across = horizontal ? heightSquares : widthSquares;
    const half = Math.max(2.4, across * 0.23);
    return (x, y) => {
      const along = horizontal ? x : y, crossing = horizontal ? y : x;
      const centre = across / 2 + (noise(along * 0.05, 3.3, 2) - 0.5) * across * 0.4;
      const offset = Math.abs(crossing - centre);
      const ragged = offset + (fine(x * 1.4, y * 1.4, 3) - 0.5) * 1.1;
      const n = noise(x * 0.6, y * 0.6), f = fine(x * 12, y * 12, 2), pebble = fine(x * 22 + 3, y * 22, 1);
      let dr = 138 + (n - 0.5) * 34 + (f - 0.5) * 26, dg = 108 + (n - 0.5) * 28 + (f - 0.5) * 22, db = 74 + (n - 0.5) * 20 + (f - 0.5) * 16;
      const rut = Math.abs(offset - half * 0.4);
      const groove = rut < 0.26 ? (1 - rut / 0.26) * 0.28 : 0;
      const crown = offset < half * 0.18 ? 0.06 : 0;  // a grassy hump between the ruts
      const shade = 1 - groove + (pebble > 0.78 ? 0.18 : 0);
      dr *= shade; dg *= shade; db *= shade;
      const verge = smoothstep(half - 0.5, half + 0.7, ragged);
      const m = noise(x * 1.7 + 9, y * 1.7 + 3, 3);
      const gr = 64 + (m - 0.5) * 22, gg = 100 + (m - 0.5) * 46 + (f - 0.5) * 36, gb = 46 + (f - 0.5) * 16;
      const green = Math.max(verge, crown * smoothstep(0.55, 0.7, m));
      return [mix(dr, gr, green), mix(dg, gg, green), mix(db, gb, green)];
    };
  }
  if (style === "marble") {
    // Worn stone slabs in one palette. Independent slab weathering replaces checkerboard parity;
    // muted joints and continuous veins sit naturally beside the surrounding paving.
    return (x, y) => {
      const tx = Math.floor(x / 2), ty = Math.floor(y / 2), u = x / 2 - tx, v = y / 2 - ty;
      const joint = smoothstep(0.09, 0.012, Math.min(u, v, 1 - u, 1 - v));
      const tone = mulberryHash(tx * 73856093 ^ ty * 19349663 ^ seed);
      // Few octaves of turbulence: marble veins sweep in long curves rather than squiggle.
      const turbulence = noise(x * 0.16, y * 0.16, 2) * 7 + noise(x * 0.9, y * 0.9, 2) * 0.5;
      const vein = Math.pow(1 - Math.abs(Math.sin(x * 0.4 + y * 0.28 + turbulence)), 60);
      const faint = Math.pow(1 - Math.abs(Math.sin(x * 0.7 - y * 0.55 + turbulence * 1.3)), 30) * 0.55;
      const cloud = (noise(x * 0.6, y * 0.6, 4) - 0.5) * 20;
      const sheen = (noise(x * 0.15, y * 0.15, 2) - 0.5) * 14 + (fine(x * 6, y * 6, 2) - 0.5) * 6;
      const wear = cloud + sheen + (tone - 0.5) * 16 - vein * 22 - faint * 12;
      const rgb = [166 + wear, 163 + wear, 150 + wear];
      return [mix(rgb[0], 132, joint * 0.55), mix(rgb[1], 129, joint * 0.55), mix(rgb[2], 117, joint * 0.55)];
    };
  }
  if (style === "dark_stone") {
    // Blue-black slate blocks in a running bond, each block its own tone, edges bevelled.
    return (x, y) => {
      const row = Math.floor(y), shift = row % 2 ? 1 : 0, bx = Math.floor((x + shift) / 2);
      const u = ((x + shift) / 2) % 1, v = y - row;
      if (u < 0.02 || v < 0.035 || u > 0.985 || v > 0.97) return [16, 17, 21];
      const tone = mulberryHash(bx * 31 + row * 977 + seed);
      const n = noise(x * 0.9, y * 0.9), f = fine(x * 10, y * 10, 3);
      const bevel = (v < 0.1 || u < 0.05 ? 12 : 0) - (v > 0.88 || u > 0.95 ? 12 : 0);
      const base = 44 + tone * 18 + (n - 0.5) * 18 + (f - 0.5) * 16 + bevel;
      return [base * 0.92, base * 0.97, base * 1.12];
    };
  }
  if (style === "ice") {
    // A frozen lake: clear blue ice over dark water, milky patches of frost, long white cracks.
    const cracks = makeCells(seed, 3.1, widthSquares, heightSquares), crackle = makeCells(seed + 9, 0.8, widthSquares, heightSquares);
    return (x, y) => {
      const n = noise(x * 0.32, y * 0.32), f = fine(x * 8, y * 8, 2), frost = smoothstep(0.5, 0.8, noise(x * 0.25 + 21, y * 1.2, 4));
      let r = mix(84, 168, n), g = mix(128, 204, n), b = mix(166, 230, n);
      r = mix(r, 224, frost * 0.45); g = mix(g, 236, frost * 0.45); b = mix(b, 246, frost * 0.45);
      const streak = Math.pow(Math.max(0, Math.sin((x - y) * 0.7 + n * 3)), 12) * 26;
      r += streak + (f - 0.5) * 10; g += streak + (f - 0.5) * 10; b += streak + (f - 0.5) * 8;
      const main = cracks(x, y).edge, small = crackle(x, y).edge;
      if (main < 0.03) return [246, 252, 255];
      if (main < 0.07) return [r * 0.82, g * 0.86, b * 0.92];  // the crack's shadow in the ice
      if (small < 0.014) return [mix(r, 236, 0.55), mix(g, 244, 0.55), mix(b, 250, 0.55)];
      return [r, g, b];
    };
  }
  if (style === "shallows") {
    // Ankle-deep water over sand and pebbles, with sunlight caustics rippling on the bottom.
    const stones = makeCells(seed + 4, 0.42, widthSquares, heightSquares);
    return (x, y) => {
      const n = noise(x * 0.3, y * 0.3), f = fine(x * 9, y * 9, 2);
      let r = 176 + (f - 0.5) * 22, g = 156 + (f - 0.5) * 20, b = 112 + (f - 0.5) * 16;
      const {edge, id} = stones(x, y);
      if (id > 0.72 && edge > 0.06) { const s = 0.55 + id * 0.35; r = 120 * s + 30; g = 116 * s + 24; b = 104 * s + 20; }
      const depth = 0.42 + n * 0.4;
      r = mix(r, 34, depth); g = mix(g, 118, depth); b = mix(b, 132, depth);
      const caustic = ridge(noise(x * 0.9 + 5, y * 0.9, 3), 10) * 0.7 + ridge(fine(x * 1.6, y * 1.6 + 9, 2), 14) * 0.5;
      return [r + caustic * 70, g + caustic * 86, b + caustic * 80];
    };
  }
  if (style === "mountain") {
    // Grey-brown bedrock in tilted strata, cracked into slabs, with scree and lichen.
    const slabs = makeCells(seed, 2.6, widthSquares, heightSquares);
    return (x, y) => {
      const n = noise(x * 0.4, y * 0.4), f = fine(x * 9, y * 9, 3);
      const strata = Math.sin((x * 0.35 + y * 0.95) * 3.2 + n * 7);
      const band = strata > 0.55 ? 16 : strata < -0.6 ? -14 : 0;
      const facet = (ridge(noise(x * 0.3 + 5, y * 0.3, 4), 1.5) - 0.5) * 50;
      const {edge, id} = slabs(x + (fine(x * 2, y * 2, 2) - 0.5) * 0.5, y);
      let base = 92 + (n - 0.5) * 30 + band + facet + (f - 0.5) * 26 + id * 10;
      if (edge < 0.03) base *= 0.55; else if (edge < 0.06) base *= 0.85;
      const scree = smoothstep(0.62, 0.72, noise(x * 0.5 + 33, y * 0.5 + 8, 3)) * (fine(x * 20, y * 20, 1) > 0.6 ? 1 : 0.4);
      const lichen = smoothstep(0.74, 0.8, fine(x * 2.2 + 50, y * 2.2, 3)) * 0.7;
      let r = base * 1.04 + scree * 20, g = base * 0.98 + scree * 16, b = base * 0.9 + scree * 12;
      r = mix(r, 150, lichen * 0.55); g = mix(g, 152, lichen * 0.55); b = mix(b, 70, lichen * 0.55);
      return [r, g, b];
    };
  }
  if (style === "graveyard") {
    // Patchy dead grass and grave dirt, grave mounds each with a small headstone. A perfectly even
    // column*3/row*4 grid of these (even with each stone's own shape randomised) still reads as a
    // stamped row (owner QA, ruined-spirit-shrine: "~9 near-identical blobs ... along the full bottom
    // wall"), so alternate rows run in a staggered (running-bond) offset and every plot gets its own
    // position jitter -- deterministic (from column/row, not the stateful rand()) so the ground hump
    // painted per-pixel below and the headstone drawn in decorate() always land on the same spot.
    const plot = (column, row) => {
      const skip = mulberryHash(column * 131 + row * 7919 + seed) < 0.3;
      const stagger = (row % 2) * 1.1;
      const jx = (mulberryHash(column * 977 + row * 131 + seed + 11) - 0.5) * 1.3;
      const jy = (mulberryHash(column * 311 + row * 653 + seed + 23) - 0.5) * 1.0;
      return {skip, x: column * 3 + stagger + jx, y: row * 4 + jy};
    };
    // Index each complete shifted mound in every lookup cell its bounds touch.
    // Painting and decoration share these positions; no per-pixel hashing or
    // whole-map scan, and crossing an original grid boundary cannot clip a mound.
    const plots = [], buckets = [], emptyPlots = [];
    for (let column = 0; column * 3 < widthSquares; column += 1) for (let row = 0; row * 4 < heightSquares; row += 1) {
      const p = plot(column, row);
      if (p.skip) continue;
      plots.push(p);
      for (let bx = Math.floor((p.x + 0.85) / 3); bx <= Math.floor((p.x + 2.15) / 3); bx += 1)
        for (let by = Math.floor((p.y + 1) / 4); by <= Math.floor((p.y + 3.3) / 4); by += 1) {
          if (!buckets[by]) buckets[by] = [];
          if (!buckets[by][bx]) buckets[by][bx] = [];
          buckets[by][bx].push(p);
        }
    }
    const paint = (x, y) => {
      const n = noise(x * 0.5, y * 0.5), m = noise(x * 1.4 + 6, y * 1.4, 3), f = fine(x * 12, y * 12, 2);
      const grass = smoothstep(0.45, 0.62, m);
      let r = mix(98, 94, grass) + (f - 0.5) * 22 + (n - 0.5) * 18, g = mix(86, 100, grass) + (f - 0.5) * 22 + (n - 0.5) * 16, b = mix(72, 66, grass) + (f - 0.5) * 14;
      for (const p of buckets[Math.floor(y / 4)]?.[Math.floor(x / 3)] || emptyPlots) {
        const lx = x - p.x, ly = y - p.y;
        if (lx <= 0.85 || lx >= 2.15 || ly <= 1 || ly >= 3.3) continue;
        // A low hump: soft at the rim, lit from the upper left, a little barer than the grass.
        const u = (lx - 1.5) / 0.55, v = (ly - 2.15) / 1.05, d = Math.sqrt(u * u * 0.7 + v * v);
        const hump = smoothstep(1, 0.55, d), light = -(u * 0.6 + v * 0.4) * 16 * hump;
        r = mix(r, 88 + light, hump * 0.85); g = mix(g, 74 + light, hump * 0.85); b = mix(b, 60 + light * 0.8, hump * 0.85);
        break; // Shifted plot bounds cannot overlap with these spacing/jitter limits.
      }
      return [r, g, b];
    };
    paint.decorate = (context, pps, rand) => {
      for (const p of plots) {
        const cx = (p.x + 1.5) * pps, top = (p.y + 0.82) * pps;
        const width = (0.62 + rand() * 0.22) * pps, depth = (0.2 + rand() * 0.06) * pps, tilt = (rand() - 0.5) * 0.18;
        const tone = 128 + rand() * 50;
        context.save();
        context.translate(cx, top);
        context.rotate(tilt);
        context.fillStyle = "rgba(0,0,0,0.35)";
        context.fillRect(-width / 2 + depth * 0.4, depth * 0.3, width, depth * 1.4);
        context.fillStyle = `rgb(${tone | 0},${tone * 0.98 | 0},${tone * 0.94 | 0})`;
        context.beginPath();
        context.moveTo(-width / 2, depth);
        context.lineTo(-width / 2, 0);
        context.quadraticCurveTo(0, -depth * 1.1, width / 2, 0);
        context.lineTo(width / 2, depth);
        context.closePath();
        context.fill();
        context.fillStyle = `rgba(255,255,255,0.18)`;
        context.fillRect(-width / 2, 0, width, depth * 0.25);
        context.restore();
      }
      // Pale pebbles and bone-white scraps scattered through the grass.
      for (let index = 0; index < widthSquares * heightSquares * 0.8; index += 1) {
        context.fillStyle = `rgba(${200 + rand() * 30 | 0},${196 + rand() * 30 | 0},${182 + rand() * 30 | 0},0.55)`;
        context.beginPath();
        context.ellipse(rand() * widthSquares * pps, rand() * heightSquares * pps, pps * (0.02 + rand() * 0.03), pps * (0.015 + rand() * 0.02), rand() * 3, 0, Math.PI * 2);
        context.fill();
      }
    };
    return paint;
  }
  // ---------------------------------------------------------------- biome floors (owner 2026-10-08)
  // Scatter drawn on top of a floor's pixels: small ellipses (leaves, pebbles, clods) with a soft shadow.
  const scatter = (context, pps, rand, count, pick) => {
    for (let index = 0; index < count; index += 1) {
      const x = rand() * widthSquares, y = rand() * heightSquares, item = pick(x, y, rand);
      if (!item) continue;
      const [rgb, length, width, alpha = 1] = item, angle = rand() * Math.PI;
      context.save();
      context.translate(x * pps, y * pps);
      context.rotate(angle);
      context.fillStyle = "rgba(0,0,0,0.22)";
      context.beginPath(); context.ellipse(width * 0.35 * pps, width * 0.5 * pps, length * pps / 2, width * pps / 2, 0, 0, Math.PI * 2); context.fill();
      context.fillStyle = `rgba(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0},${alpha})`;
      context.beginPath(); context.ellipse(0, 0, length * pps / 2, width * pps / 2, 0, 0, Math.PI * 2); context.fill();
      context.restore();
    }
  };
  if (style === "jungle") {
    // Dark wet earth almost hidden under leaf litter and creeping moss, thick roots snaking across it.
    const rootNoise = makeNoise(seed + 41);
    const paint = (x, y) => {
      const n = noise(x * 0.45, y * 0.45), m = smoothstep(0.48, 0.66, noise(x * 1.1 + 5, y * 1.1 + 9, 3)), f = fine(x * 12, y * 12, 3);
      const root = ridge(rootNoise(x * 0.42, y * 0.42, 3), 18);
      let r = 52 + (n - 0.5) * 26 + (f - 0.5) * 20, g = 42 + (n - 0.5) * 22 + (f - 0.5) * 18, b = 28 + (f - 0.5) * 12;
      r = mix(r, 54, m * 0.8); g = mix(g, 78 + (f - 0.5) * 24, m * 0.8); b = mix(b, 36, m * 0.8);
      return [mix(r, 92, root * 0.85), mix(g, 70, root * 0.85), mix(b, 44, root * 0.85)];
    };
    paint.decorate = (context, pps, rand) => scatter(context, pps, rand, widthSquares * heightSquares * 14, (x, y, r) => {
      const tones = [[66, 104, 42], [92, 124, 52], [116, 96, 46], [54, 84, 36], [140, 120, 60]];
      return [tones[Math.floor(r() * tones.length)], 0.1 + r() * 0.12, 0.05 + r() * 0.04, 0.9];
    });
    return paint;
  }
  if (style === "forest_loam") {
    // Brown loam with pine needles and old leaves, moss in the hollows, the odd twig.
    const paint = (x, y) => {
      const n = noise(x * 0.4, y * 0.4), m = smoothstep(0.55, 0.7, noise(x * 0.9 + 3, y * 0.9 + 1, 3)), f = fine(x * 13, y * 13, 3);
      const base = 78 + (n - 0.5) * 30 + (f - 0.5) * 26;
      return [mix(base * 1.0, 74, m * 0.8), mix(base * 0.78, 86, m * 0.8), mix(base * 0.52, 48, m * 0.8)];
    };
    paint.decorate = (context, pps, rand) => {
      scatter(context, pps, rand, widthSquares * heightSquares * 8, (x, y, r) => {
        const tones = [[150, 104, 54], [176, 128, 64], [118, 80, 42], [196, 150, 80]];
        return [tones[Math.floor(r() * tones.length)], 0.1 + r() * 0.12, 0.05 + r() * 0.04, 0.85];
      });
      context.lineCap = "round";
      for (let index = 0; index < widthSquares * heightSquares * 10; index += 1) {  // needles
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = rand() * Math.PI, l = (0.08 + rand() * 0.08) * pps;
        context.strokeStyle = `rgba(${150 + rand() * 40 | 0},${110 + rand() * 30 | 0},${60 + rand() * 20 | 0},0.7)`;
        context.lineWidth = Math.max(0.6, pps * 0.012);
        context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); context.stroke();
      }
    };
    return paint;
  }
  if (style === "scree_ground") {
    // Grey-brown grit packed with loose angular stones, a few larger slabs.
    const cells = makeCells(seed + 7, 0.26, widthSquares, heightSquares), big = makeCells(seed + 13, 0.9, widthSquares, heightSquares);
    const paint = (x, y) => {
      const wobble = (fine(x * 9, y * 9, 2) - 0.5) * 0.05;
      const {edge, id} = cells(x, y), n = noise(x * 0.5, y * 0.5), f = fine(x * 16, y * 16, 2), slab = big(x, y);
      const stone = edge + wobble > 0.04 && id > 0.55, rock = slab.edge + wobble > 0.08 && slab.id > 0.86;
      let tone = 102 + (n - 0.5) * 24 + (f - 0.5) * 30;
      if (stone) tone = 108 + id * 26 + (f - 0.5) * 16 + Math.min(1, edge * 5) * 12 - (edge < 0.07 ? 18 : 0);
      if (rock) tone = 116 + slab.id * 20 + (n - 0.5) * 18 + Math.min(1, slab.edge * 3) * 12 - (slab.edge < 0.11 ? 20 : 0);
      return [tone * 0.98, tone * 0.95, tone * 0.88];
    };
    return paint;
  }
  if (style === "dunes") {
    // Gold sand in long wind ripples: each ripple a lit windward slope and a short shadowed lee, over broad dune swells,
    // with grain speckle and a few pebbles. Moderate contrast so tokens stay readable.
    const paint = (x, y) => {
      const swell = noise(x * 0.16, y * 0.16), warp = noise(x * 0.3 + 4, y * 0.3, 3) * 3, f = fine(x * 22, y * 22, 2), g = fine(x * 40, y * 40, 1);
      const phase = (x * 0.3 + y * 0.95 + warp * 1.6) * 1.15, saw = phase - Math.floor(phase);
      const ripple = saw < 0.75 ? (saw / 0.75) * 14 - 4 : 10 - 26 * Math.sin(((saw - 0.75) / 0.25) * Math.PI / 2) + 12 * ((saw - 0.75) / 0.25);
      const dune = (swell - 0.5) * 44, tone = 0.86 + (g - 0.5) * 0.08;
      return [(198 + dune + ripple + (f - 0.5) * 12) * tone, (164 + dune * 0.9 + ripple * 0.9 + (f - 0.5) * 10) * tone, (108 + dune * 0.7 + ripple * 0.6 + (f - 0.5) * 8) * tone];
    };
    paint.decorate = (context, pps, rand) => scatter(context, pps, rand, widthSquares * heightSquares * 1.1, (x, y, r) => [[132 + r() * 40, 108 + r() * 30, 82 + r() * 20], 0.04 + r() * 0.05, 0.03 + r() * 0.03, 0.85]);
    return paint;
  }
  if (style === "snowfield") {
    // Wind-packed snow, kept below pure white so tokens read: blue-grey hollows, wind ripples and sharp sastrugi ridges,
    // patches of frozen ground showing through, and a line of old tracks.
    const bare = makeNoise(seed + 29);
    const paint = (x, y) => {
      const n = noise(x * 0.2, y * 0.2), warp = noise(x * 0.5 + 2, y * 0.5 + 8, 3), f = fine(x * 16, y * 16, 2);
      const ripple = Math.sin((x * 1.4 - y * 0.7 + warp * 3) * 4.2), ridgeLine = ridge(noise(x * 0.7 + 13, y * 0.28, 3), 14);
      const ground = smoothstep(0.69, 0.75, bare(x * 0.6, y * 0.6, 3)) * 0.8;
      const shade = (n - 0.5) * 36 + ripple * 5 + ridgeLine * 14 - smoothstep(0.2, 0.6, 1 - n) * 10;
      const r = 158 + shade + (f - 0.5) * 8, g = 170 + shade + (f - 0.5) * 8, b = 190 + shade * 0.8 + (f - 0.5) * 6;
      return [mix(r, 138, ground), mix(g, 132, ground), mix(b, 126, ground)];
    };
    paint.decorate = (context, pps, rand) => {
      // a winding line of old footprints
      const startY = rand() * heightSquares;
      for (let x = 0.3, i = 0; x < widthSquares; x += 0.45, i += 1) {
        const y = startY + Math.sin(x * 0.4) * 1.2 + (i % 2 ? 0.12 : -0.12);
        context.fillStyle = "rgba(120,138,160,0.45)";
        context.beginPath(); context.ellipse(x * pps, y * pps, 0.07 * pps, 0.12 * pps, 1.2, 0, Math.PI * 2); context.fill();
      }
      scatter(context, pps, rand, widthSquares * heightSquares * 0.8, (x, y, r) => [[236, 242, 250], 0.03 + r() * 0.03, 0.02, 0.8]);
    };
    return paint;
  }
  if (style === "swamp_mud") {
    // Black-brown sucking mud with sheens of standing water, bubbles and floating scum.
    const paint = (x, y) => {
      const n = noise(x * 0.3, y * 0.3), m = noise(x * 1.4 + 5, y * 1.4 + 2, 3), f = fine(x * 12, y * 12, 2);
      const wet = smoothstep(0.55, 0.64, n), scum = smoothstep(0.68, 0.78, m) * wet * 0.6;
      const glint = Math.pow(fine(x * 1.1 + 3, y * 2.7, 2), 5) * 70 * wet;
      const r = mix(84 + (n - 0.5) * 24 + (f - 0.5) * 22, 44 + glint * 0.6, wet), g = mix(68 + (n - 0.5) * 20 + (f - 0.5) * 20, 50 + glint * 0.7, wet), b = mix(46 + (f - 0.5) * 12, 38 + glint * 0.6, wet);
      return [mix(r, 92, scum * 0.7), mix(g, 102, scum * 0.7), mix(b, 46, scum * 0.7)];
    };
    paint.decorate = (context, pps, rand) => {
      for (let index = 0; index < widthSquares * heightSquares * 1.4; index += 1) {
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, r = (0.02 + rand() * 0.035) * pps;
        context.strokeStyle = "rgba(170,170,140,0.45)"; context.lineWidth = Math.max(0.5, pps * 0.008);
        context.beginPath(); context.arc(x, y, r, 0, Math.PI * 2); context.stroke();
      }
    };
    return paint;
  }
  if (style === "temple_court") {
    // Large dressed slabs in courses: each slab its own tone (grey, buff, faintly green), worn and darker near its
    // edges, moss creeping along some joints, and here and there a slab carved with a round lotus motif.
    const paint = (x, y) => {
      const row = Math.floor(y / 1.5), offset = row % 2 ? 0.9 : 0, u = (x + offset) / 1.8, tx = Math.floor(u), fu = u - tx, fv = y / 1.5 - row;
      const id = mulberryHash(tx * 131 + row * 977), hue = mulberryHash(tx * 71 + row * 313), n = noise(x * 0.6, y * 0.6), f = fine(x * 11, y * 11, 3);
      const joint = fu < 0.014 || fu > 0.986 || fv < 0.018 || fv > 0.982;
      if (joint) {
        const moss = smoothstep(0.48, 0.64, noise(x * 1.2 + 4, y * 1.2, 2));
        return [mix(98, 84, moss), mix(94, 104, moss), mix(86, 66, moss)];
      }
      const edge = Math.min(fu, 1 - fu, fv, 1 - fv), wear = smoothstep(0.0, 0.08, edge);
      const base = 132 + id * 40 + (n - 0.5) * 20 + (f - 0.5) * 16 - (1 - wear) * 14;
      const warm = hue < 0.33 ? [8, 2, -10] : hue < 0.66 ? [0, 0, 0] : [-4, 4, -2];
      // a carved lotus roundel on one slab in seven
      let carve = 0;
      if (id > 0.86) {
        const cx = (fu - 0.5) * 1.8, cy = (fv - 0.5) * 1.5, d = Math.sqrt(cx * cx + cy * cy), a = Math.atan2(cy, cx);
        const petal = 0.32 + 0.08 * Math.cos(a * 8);
        carve = (Math.abs(d - petal) < 0.025 || Math.abs(d - 0.14) < 0.02 || Math.abs(d - 0.48) < 0.02) ? -26 : 0;
      }
      return [base + warm[0] + carve, base + warm[1] + carve, base + warm[2] + carve - 4];
    };
    return paint;
  }
  if (style === "packed_dirt") {
    // Trodden village earth: lighter worn paths, darker damp patches, wheel ruts, straw wisps, stones and puddle stains.
    const paint = (x, y) => {
      const n = noise(x * 0.35, y * 0.35), path = ridge(noise(x * 0.12 + 11, y * 0.12, 2), 6), f = fine(x * 14, y * 14, 2);
      const stain = smoothstep(0.7, 0.78, noise(x * 0.9 + 1, y * 0.9 + 7, 2)), damp = smoothstep(0.55, 0.7, noise(x * 0.5 + 31, y * 0.5 + 3, 3));
      const rut = ridge(noise(x * 0.08 + 5, y * 0.5 + 2, 2), 22) * path;
      const base = 112 + (n - 0.5) * 30 + (f - 0.5) * 24 + path * 24 - stain * 26 - damp * 16 - rut * 22;
      return [base * 1.04, base * 0.88, base * 0.66];
    };
    paint.decorate = (context, pps, rand) => {
      scatter(context, pps, rand, widthSquares * heightSquares * 1.5, (x, y, r) => [[150 + r() * 40, 140 + r() * 30, 120 + r() * 20], 0.04 + r() * 0.05, 0.03 + r() * 0.03, 0.85]);
      context.lineCap = "round";
      for (let index = 0; index < widthSquares * heightSquares * 2; index += 1) {  // straw
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = rand() * Math.PI, l = (0.1 + rand() * 0.12) * pps;
        context.strokeStyle = `rgba(${206 + rand() * 30 | 0},${176 + rand() * 30 | 0},${96 + rand() * 30 | 0},0.75)`;
        context.lineWidth = Math.max(0.6, pps * 0.014);
        context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); context.stroke();
      }
    };
    return paint;
  }
  if (style === "churned_earth") {
    // Mud churned by boots and hooves: dark ruts, trodden tufts of grass, a scorched patch or two, boot prints,
    // scattered straw and spent arrows.
    const paint = (x, y) => {
      const n = noise(x * 0.4, y * 0.4), rut = ridge(noise(x * 0.6 + 3, y * 0.25, 3), 10), f = fine(x * 13, y * 13, 3);
      const grass = smoothstep(0.66, 0.76, noise(x * 1.6 + 9, y * 1.6 + 2, 3)) * (0.5 + fine(x * 20, y * 20, 2) * 0.5);
      const scorch = smoothstep(0.76, 0.84, noise(x * 0.35 + 21, y * 0.35 + 5, 2)), wet = smoothstep(0.6, 0.7, noise(x * 0.7 + 41, y * 0.7, 2));
      const base = 80 + (n - 0.5) * 26 + (f - 0.5) * 30 - rut * 30 - wet * 14;
      let r = base * 1.0, g = base * 0.82, b = base * 0.6;
      r = mix(r, 78, grass); g = mix(g, 86, grass); b = mix(b, 48, grass);
      return [mix(r, 36, scorch), mix(g, 30, scorch), mix(b, 26, scorch)];
    };
    paint.decorate = (context, pps, rand) => {
      context.lineCap = "round";
      for (let index = 0; index < widthSquares * heightSquares * 0.9; index += 1) {  // boot prints
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = rand() * Math.PI;
        context.save(); context.translate(x, y); context.rotate(a);
        context.fillStyle = "rgba(30,20,12,0.4)";
        context.beginPath(); context.ellipse(0, 0, 0.05 * pps, 0.1 * pps, 0, 0, Math.PI * 2); context.fill();
        context.beginPath(); context.ellipse(0, 0.14 * pps, 0.04 * pps, 0.045 * pps, 0, 0, Math.PI * 2); context.fill();
        context.restore();
      }
      for (let index = 0; index < widthSquares * heightSquares * 1.2; index += 1) {  // straw
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = rand() * Math.PI, l = (0.1 + rand() * 0.12) * pps;
        context.strokeStyle = `rgba(${196 + rand() * 30 | 0},${166 + rand() * 30 | 0},${90 + rand() * 30 | 0},0.7)`;
        context.lineWidth = Math.max(0.6, pps * 0.013);
        context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); context.stroke();
      }
      for (let index = 0; index < widthSquares * heightSquares * 0.1; index += 1) {  // spent arrows
        const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = Math.PI * (1.1 + rand() * 0.3), l = (0.25 + rand() * 0.15) * pps;
        context.strokeStyle = "rgba(0,0,0,0.3)"; context.lineWidth = Math.max(0.8, pps * 0.025);
        context.beginPath(); context.moveTo(x + pps * 0.03, y + pps * 0.05); context.lineTo(x + Math.cos(a) * l + pps * 0.08, y + Math.sin(a) * l + pps * 0.1); context.stroke();
        context.strokeStyle = "rgba(140,100,60,0.95)"; context.lineWidth = Math.max(0.7, pps * 0.018);
        context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); context.stroke();
        context.fillStyle = "rgba(232,226,210,0.95)";
        context.beginPath(); context.arc(x + Math.cos(a) * l, y + Math.sin(a) * l, pps * 0.025, 0, Math.PI * 2); context.fill();
      }
    };
    return paint;
  }
  // Indoor floors/tiles and grass/forest variants (SON202): a style this module doesn't know is theirs.
  const extra = extraPainter(style, seed, widthSquares, heightSquares, patch);
  if (extra) return extra;
  return () => [34, 40, 38];
}

const cache = new Map();

// A canvas painted for the map: pixels per square scale down for big maps to stay light.
// patch: painted as a floor patch in the map editor rather than as the whole map's background (a dirt road patch is dirt).
export function paintFloor(style, seed, widthSquares, heightSquares, {patch = false} = {}) {
  const chosen = STYLES[style] ? style : DEFAULT_STYLE;
  const key = `${chosen}:${seed}:${widthSquares}x${heightSquares}${patch ? ":patch" : ""}`;
  if (cache.has(key)) return cache.get(key);
  const pps = Math.max(10, Math.min(36, Math.floor(1500 / Math.max(widthSquares, heightSquares))));
  const canvas = document.createElement("canvas");
  canvas.width = widthSquares * pps;
  canvas.height = heightSquares * pps;
  const context = canvas.getContext("2d");
  const image = context.createImageData(canvas.width, canvas.height);
  const paint = painter(chosen, (Number(seed) || 1) >>> 0, widthSquares, heightSquares, patch);
  const data = image.data;
  for (let py = 0; py < canvas.height; py += 1) {
    const y = (py + 0.5) / pps;
    for (let px = 0; px < canvas.width; px += 1) {
      const [r, g, b] = paint((px + 0.5) / pps, y);
      const index = (py * canvas.width + px) * 4;
      data[index] = clamp(r); data[index + 1] = clamp(g); data[index + 2] = clamp(b); data[index + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  paint.decorate?.(context, pps, mulberry32(((Number(seed) || 1) >>> 0) + 99));
  // Soft vignette so the edges of the map read as edges.
  const gradient = context.createRadialGradient(canvas.width / 2, canvas.height / 2, Math.min(canvas.width, canvas.height) * 0.35,
                                                canvas.width / 2, canvas.height / 2, Math.max(canvas.width, canvas.height) * 0.75);
  gradient.addColorStop(0, "rgba(0,0,0,0)");
  gradient.addColorStop(1, "rgba(0,0,0,0.35)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);
  if (cache.size > 12) cache.delete(cache.keys().next().value);
  cache.set(key, canvas);
  return canvas;
}
