// Natural drawings for the table's nonmagical rules terrain. This module only paints
// the rule cells supplied by the map; it never changes their movement or cover rules.
import {DECOR, decorArt} from "./decor-art.js?v=sol196r1";
import {bambooCulms} from './scenery-sight.js?v=loslines3';

// The biome pieces with a rules meaning (decor-art.js, rule "SIMPLE_COVER" or "DIFFICULT") are looks for ordinary
// cover and difficult terrain rows, so they join the list after the original eleven.
export const TERRAIN_LOOKS = Object.freeze([
  "boulder", "bamboo_clump", "broken_tiles", "lantern", "low_wall", "pillar_rubble",
  "roots", "rubble", "scree", "statue_plinth", "stones", "rice_tufts",
  ...Object.keys(DECOR).filter(kind => DECOR[kind].rule),
]);

const FLOOR_LOOK = Object.freeze({
  mountain: {DIFFICULT: "scree", SIMPLE_COVER: "boulder", QI_HAZARD: "stones"},
  bamboo: {DIFFICULT: "roots", SIMPLE_COVER: "bamboo_clump", QI_HAZARD: "stones"},
  shrine: {DIFFICULT: "broken_tiles", SIMPLE_COVER: "pillar_rubble", QI_HAZARD: "broken_tiles"},
  graveyard: {DIFFICULT: "broken_tiles", SIMPLE_COVER: "pillar_rubble", QI_HAZARD: "broken_tiles"},
  courtyard: {DIFFICULT: "stones", SIMPLE_COVER: "lantern", QI_HAZARD: "broken_tiles"},
  flagstone: {DIFFICULT: "stones", SIMPLE_COVER: "low_wall", QI_HAZARD: "broken_tiles"},
  platform: {DIFFICULT: "stones", SIMPLE_COVER: "low_wall", QI_HAZARD: "broken_tiles"},
  pillar: {DIFFICULT: "stones", SIMPLE_COVER: "statue_plinth", QI_HAZARD: "broken_tiles"},
  dark_stone: {DIFFICULT: "stones", SIMPLE_COVER: "statue_plinth", QI_HAZARD: "broken_tiles"},
});

export function terrainLook(entry, floorStyle = "flagstone") {
  if (TERRAIN_LOOKS.includes(entry?.look)) return entry.look;
  return FLOOR_LOOK[floorStyle]?.[entry?.type] || ({DIFFICULT: "stones", SIMPLE_COVER: "low_wall", QI_HAZARD: "broken_tiles"}[entry?.type] || "stones");
}

// Overlay mode intentionally returns the former square treatment; otherwise every
// valid rule type becomes ground texture or a physical object without a frame or label.
export function terrainPresentation(type, rulesOverlay = false) {
  const known = ["DIFFICULT", "SIMPLE_COVER", "QI_HAZARD"].includes(type);
  return {known, mode: rulesOverlay ? "rules" : type === "SIMPLE_COVER" ? "object" : "ground",
    edge: Boolean(rulesOverlay), hatch: Boolean(rulesOverlay && type === "DIFFICULT"), label: false};
}

export function terrainTooltip(type) {
  if (type === "DIFFICULT") return {title: "Difficult terrain", line: "Each foot of movement through it costs one extra foot."};
  if (type === "SIMPLE_COVER") return {title: "Simple cover", line: "A creature protected by this object gains +2 AC."};
  if (type === "QI_HAZARD") return {title: "Qi hazard", line: "Follow the hazard's trigger and save rules for this map."};
  return null;
}

// The drawings use the shared helpers in art-kit.js (faceted rocks, soft shadows, roots, bamboo).
import {blade, culm, fan, r2, rock, rockField, seeded, soft, taper, variantWrap} from "./art-kit.js?v=sol196p2";

// Every shape takes the cell's own seed (board.js hashes each square's x,y into one) and feeds it into
// its rock facets or control points, so a run of squares with the same look never draws the same piece
// twice -- the fix for a biome stamped identically across a whole field (owner playtest 2026-10-13).
const shapes = Object.freeze({
  // Rice growing in flooded ground: sparse, ragged rows of blades, with water showing through.
  // The map's floor supplies the water; this look changes no difficult-terrain cost or coverage.
  rice_tufts: seed => {
    const rand = seeded(seed);
    let out = '';
    for (let row = 0; row < 2; row += 1) for (let col = 0; col < 3; col += 1) {
      if (rand() < 0.18) continue;
      const x = 8 + col * 21 + (rand() - 0.5) * 12;
      const y = 18 + row * 29 + (rand() - 0.5) * 14;
      for (let b = 0; b < 3; b += 1) {
        const bend = (b - 1) * (3 + rand() * 4), height = 6 + rand() * 9;
        out += `<path d="M${r2(x)} ${r2(y)}q${r2(bend * 0.2)} ${r2(-height * 0.6)} ${r2(bend)} ${r2(-height)}" stroke="${b === 0 ? '#b6c579' : '#698448'}" stroke-width="${r2(0.8 + rand() * 0.8)}" stroke-linecap="round" fill="none"/>`;
      }
    }
    return out;
  },
  // One to three boulders of varied size and count (a lone slab here, a jumbled pair there), with a
  // patch of lichen that only sometimes appears, so a boulder field never reads as the same rock replayed.
  boulder: seed => {
    const rand = seeded((Number(seed) >>> 0) * 40503 + 3);
    return rockField(seed, {count: [1, 3], rMin: 8, rMax: 19, tones: ["grey"], dust: 0, margin: 8})
      + (rand() < 0.6 ? `<path d="M${r2(16 + rand() * 20)} ${r2(40 + rand() * 10)}q6 1 10-4q-2 5-9 6z" fill="#6f7d4c" opacity=".85"/>` : "");
  },
  // A clump of bamboo from above: a ring of culms and narrow leaves fanning out from them, the whole
  // ring turned a little differently per square so neighbouring clumps don't line up.
  bamboo_clump: seed => {
    const spin = (seed * 37) % 360 + (seed % 997) / 997;
    return soft(35, 37, 26, 24, 0.38)
    + [[0, 22], [40, 20], [85, 23], [130, 21], [175, 22], [220, 20], [265, 23], [310, 21]].map(([a, d], i) =>
      fan(r2(32 + Math.cos((a + spin) * Math.PI / 180) * d * 0.55), r2(32 + Math.sin((a + spin) * Math.PI / 180) * d * 0.55), a + spin, 14, i % 2)).join("")
    + bambooCulms(0,0,1,true).map(p=>culm(p.x*.64,p.y*.64,p.r*.64)).join("")
    + [[20, 30], [70, 26], [160, 27], [250, 28], [330, 25]].map(([a, d], i) =>
      fan(r2(32 + Math.cos((a + spin) * Math.PI / 180) * d * 0.7), r2(32 + Math.sin((a + spin) * Math.PI / 180) * d * 0.7), a + spin + 20, 12, 2)).join("");
  },
  // Floor tiles cracked and lifted: some tipped, some missing, chips in the gaps. The whole patch is
  // nudged, turned and sometimes mirrored by the square's own seed (variantWrap) since the tile layout
  // itself is one fixed drawing -- otherwise a shrine floor's many broken-tile squares would all show
  // the exact same crack and chip, just like the paired pillars below (owner playtest round 3).
  broken_tiles: seed => variantWrap(seed, soft(32, 34, 26, 24, 0.2)
    + '<path d="M6 8L30 7L31 30L7 31Z" fill="#3a3631"/><path d="M34 9L57 6L59 29L35 31Z" fill="#3a3631"/><path d="M7 35L29 34L30 57L6 58Z" fill="#3a3631"/>'
    + '<path d="M7 7L29 8L28 29L8 30Z" fill="#a39b8b" stroke="#5a5449" stroke-width=".9"/><path d="M8 8.5L28 9" stroke="#e2dccb" stroke-width="1" opacity=".8"/><path d="M12 14l7 6 6-2M18 20l-2 7" stroke="#4a453d" stroke-width=".9" fill="none"/>'
    + '<path d="M36 10L56 8L57 27L37 30Z" fill="#8f8777" stroke="#5a5449" stroke-width=".9" transform="rotate(7 46 19)"/><path d="M37 11L55 9" stroke="#d6cfbd" stroke-width="1" opacity=".7" transform="rotate(7 46 19)"/>'
    + '<path d="M8 36L28 35L29 56L8 57Z" fill="#9c9483" stroke="#5a5449" stroke-width=".9" transform="rotate(-6 18 46)"/><path d="M10 37L27 36.5" stroke="#ddd6c4" stroke-width="1" opacity=".7" transform="rotate(-6 18 46)"/>'
    + '<path d="M35 35L58 34L59 58L36 58Z" fill="#2c2924"/><path d="M38 38L49 36L46 47L37 49Z" fill="#7d7566" stroke="#4a453d" stroke-width=".8"/>'
    + '<path d="M51 44l5 1-1 6-6-1zM41 52l4-1 1 4-4 1z" fill="#8f8777" stroke="#4a453d" stroke-width=".6"/>'
    + '<path d="M21 31l3 2-2 2zM31 22l2 1-1 2z" fill="#b8b09f"/>', {turn: 20, shift: 5}),
  // A stone lantern seen from above: the square roof with its four hips and corner curls, the jewel on top,
  // and warm light spilling round it onto the ground. Lanterns are usually placed one at a time, but the
  // small wrap keeps a row of them from looking machine-stamped too.
  lantern: seed => variantWrap(seed, '<circle cx="32" cy="32" r="31" fill="#ffcf6e" opacity=".12"/><circle cx="32" cy="32" r="26" fill="#ffcf6e" opacity=".16"/><circle cx="32" cy="32" r="23" fill="#ffe2a0" opacity=".2"/>'
    + soft(37, 38, 20, 18, 0.35)
    + '<path d="M11 11Q32 15 53 11Q49 32 53 53Q32 49 11 53Q15 32 11 11Z" fill="#8a857a" stroke="#3f3c36" stroke-width="1.2"/>'
    + '<path d="M11 11L32 32L53 11Q32 15 11 11Z" fill="#c9c3b4"/><path d="M11 11L32 32L11 53Q15 32 11 11Z" fill="#aaa497"/>'
    + '<path d="M53 11L32 32L53 53Q49 32 53 11Z" fill="#6f6a60"/><path d="M11 53L32 32L53 53Q32 49 11 53Z" fill="#5f5a51"/>'
    + '<path d="M11 11L32 32L53 53M53 11L32 32L11 53" stroke="#3f3c36" stroke-width="1" fill="none"/>'
    + '<path d="M11 11L32 32M11 53L32 32" stroke="#ece6d6" stroke-width=".7" opacity=".6"/>'
    + '<circle cx="32" cy="32" r="6" fill="#9a9488" stroke="#3f3c36" stroke-width="1"/><circle cx="30.5" cy="30.5" r="2.6" fill="#e9e3d3"/>'
    + '<path d="M9 9l4 1-1 4zM55 9l-4 1 1 4zM9 55l4-1-1-4zM55 55l-4-1 1-4z" fill="#d6d0c0" stroke="#3f3c36" stroke-width=".6"/>', {turn: 8, shift: 2, flip: false}),
  // A tumbledown dry-stone wall running east to west: a band of stacked stones with gaps and a fallen one.
  // Each stone's own spot, size and shape shifts with the seed and the odd stone drops out entirely, so two
  // low walls in neighbouring squares don't read as the same row of stones copy-pasted sideways (owner
  // playtest round 3: "the smaller parts ... look natural too?" -- a pair of these was the complaint).
  low_wall: seed => {
    const rand = seeded((Number(seed) >>> 0) * 977 + 41);
    const stones = [[6, 25, 9, 1], [21, 23, 10, 2], [37, 25, 9.5, 3], [53, 23, 10, 5], [12, 39, 9.5, 7], [28, 40, 10, 8], [44, 39, 9.5, 9], [58, 40, 7, 10]]
      .filter(() => rand() > 0.12)
      .map(([x, y, r, rockSeed]) => [x + (rand() - 0.5) * 7, y + (rand() - 0.5) * 5, r * (0.8 + rand() * 0.35), rockSeed, 5 + Math.floor(rand() * 3), 0.68 + rand() * 0.28]);
    return soft(33 + (rand() - 0.5) * 6, 36, 31, 17, 0.35)
      + stones.map(([x, y, r, rockSeed, sides, squash]) => rock(x, y, r, rockSeed + 30 + seed, "warm", {sides, squash, shadow: false})).join("")
      + rock(52 + (rand() - 0.5) * 8, 56 + (rand() - 0.5) * 4, 4 + rand() * 3, 41 + seed, "warm", {sides: 5});
  },
  // A toppled column: a fluted drum lying east-west with its broken end, and chunks of capital beside it.
  // The whole thing is wrapped in the square's own offset/turn/mirror (variantWrap) on top of the corner
  // rocks' own seeded texture, so two pillars don't fall at the exact same angle in the exact same spot
  // (owner playtest round 3, the same "paired blocks" complaint as low_wall above).
  pillar_rubble: seed => variantWrap(seed, soft(32, 37, 28, 16, 0.35)
    + '<path d="M7 21Q4 32 7 43H45L49 39 45 35 50 31 45 27 48 24 45 21Z" fill="#a49e90" stroke="#4f4b45" stroke-width="1.1"/>'
    + '<path d="M8 22H45L46 24 44 27H8Z" fill="#e9e3d4"/><path d="M8 27H44L47 31H8Z" fill="#cbc5b6"/><path d="M8 36H45L48 39 45 43H8Z" fill="#7e786c"/>'
    + '<path d="M9 27H44M9 31H46M9 35.5H45M9 39.5H46" stroke="#6f695e" stroke-width=".7" fill="none"/>'
    + '<path d="M7 21Q4 32 7 43Q11 32 7 21Z" fill="#8e887b" stroke="#4f4b45" stroke-width=".8"/>'
    + rock(55, 48, 7.5, 51 + seed, "grey", {sides: 6}) + rock(52, 14, 6, 52 + seed, "grey", {sides: 5}) + rock(19, 53, 5, 53 + seed, "grey", {sides: 5}), {turn: 22, shift: 5}),
  // Gnarled roots across the ground: thick, tapering, barked, crossing each other, each root's course
  // nudged a little so a field of them doesn't repeat the same branching from square to square.
  roots: seed => {
    const rand = seeded(seed), jitter = n => n + (rand() - 0.5) * 5;
    return soft(32, 34, 30, 26, 0.18)
    + [
      // Surface roots of a tree off this square, entering from the north-west and forking as they run out; the forks
      // are drawn first so each parent root covers the joint.
      [[37, 31], [50, 38], [64, 41], 7], [[37, 32], [42, 48], [37, 64], 7], [[27, 44], [36, 55], [50, 62], 5.5],
      [[32, 16], [47, 13], [63, 6], 5.5], [[19, 13], [12, 22], [4, 27], 4.5],
      [[-2, 9], [22, 16], [39, 33], 12], [[-2, 36], [15, 34], [29, 46], 9], [[13, -2], [19, 10], [34, 16], 8.5],
    ].map(([a, m, b, w]) => [[a[0], a[1]], [jitter(m[0]), jitter(m[1])], [jitter(b[0]), jitter(b[1])], w])
      .map(([a, m, b, w]) => `<path d="${taper(a, m, b, w, 0.42)}" fill="#5f4a35" stroke="#1f160c" stroke-width="1"/>`
      + `<path d="${taper([a[0] - 0.8, a[1] - 1.2], [m[0] - 0.8, m[1] - 1.2], [b[0] - 0.6, b[1] - 0.8], w * 0.36, 0.4)}" fill="#a38664" opacity=".7"/>`).join("")
    + '<ellipse cx="22" cy="17" rx="2.2" ry="1.4" fill="#2e2216"/><ellipse cx="44" cy="40" rx="1.6" ry="1.1" fill="#2e2216"/><ellipse cx="16" cy="35" rx="1.6" ry="1.1" fill="#2e2216"/>';
  },
  // A spill of broken masonry: a different count, mix of sizes, and scatter of blocks every square, grey
  // and warm stone mixed with grit between them -- never the same rock-cluster silhouette twice.
  rubble: seed => rockField(seed, {count: [4, 7], rMin: 4, rMax: 15.5, tones: ["grey", "warm"], dust: 9, margin: 6}),
  // Loose scree: many small angular stones scattered downslope, the count and spread varying with the seed
  // so a slope of scree doesn't repeat the same fifteen stones over and over.
  scree: seed => rockField(seed, {count: [9, 16], rMin: 2.2, rMax: 6, tones: ["grey", "dark"], dust: 7, margin: 3}),
  // An empty statue plinth: a two-step square base whose figure has broken away, leaving the feet.
  statue_plinth: seed => variantWrap(seed, soft(36, 38, 26, 24, 0.35)
    + '<path d="M8 8H56V56H8Z" fill="#8d887d" stroke="#3f3c36" stroke-width="1.1"/><path d="M8 8L14 14H50L56 8Z" fill="#cfc9ba"/><path d="M8 8L14 14V50L8 56Z" fill="#b2ac9e"/>'
    + '<path d="M56 8L50 14V50L56 56Z" fill="#6c675e"/><path d="M8 56L14 50H50L56 56Z" fill="#5f5a51"/>'
    + '<path d="M14 14H50V50H14Z" fill="#a7a194" stroke="#4f4b45" stroke-width=".9"/><path d="M15 49V15H49" stroke="#ebe5d6" stroke-width="1" fill="none"/>'
    + '<path d="M25 26l6-2 2 7-6 2zM34 31l6-1 1 7-6 1z" fill="#6e7d70" stroke="#2f3a32" stroke-width=".8"/><path d="M25.5 26.5l5-1.6M34.5 31.3l5-.8" stroke="#c6d6c8" stroke-width=".8"/>'
    + '<path d="M22 40l3 3-4 1zM42 22l2 3-3 0z" fill="#8a9a8c" stroke="#2f3a32" stroke-width=".5"/>', {turn: 6, shift: 2}),
  // A few smooth river stones half-sunk in the ground.
  stones: seed => [[17, 19, 11, 81, 0.7, 0.3], [44, 15, 9, 82, 0.75, -0.4], [46, 43, 12, 83, 0.65, 0.5], [19, 46, 10, 84, 0.7, -0.2], [32, 31, 5.5, 85, 0.8, 0]]
    .map(([x, y, r, stoneSeed, squash, angle]) => {
      const rand = seeded(stoneSeed + seed), a = r2((angle * 57 + (rand() - 0.5) * 50) % 360);
      return soft(x + 1.6, y + 2.2, r * 1.05, r * squash) + `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${r2(r * squash)}" transform="rotate(${a} ${x} ${y})" fill="#7d786f" stroke="#3f3c36" stroke-width="1"/>`
      + `<ellipse cx="${r2(x - r * 0.18)}" cy="${r2(y - r * 0.2)}" rx="${r2(r * 0.66)}" ry="${r2(r * squash * 0.6)}" transform="rotate(${a} ${x} ${y})" fill="#b1ab9e"/>`
      + `<ellipse cx="${r2(x - r * 0.3)}" cy="${r2(y - r * 0.32)}" rx="${r2(r * 0.25)}" ry="${r2(r * squash * 0.18)}" transform="rotate(${a} ${x} ${y})" fill="#e8e2d2" opacity=".8"/>`;
    }).join(""),
});

// A bank of pre-drawn variants per look, the same trick decor-art.js's decorShape uses for placed
// props: a big DIFFICULT field can span thousands of squares, and redrawing a rock pile's full geometry
// (several faceted rocks each) for every one of them on every render is real, measurable cost. Picking
// one of a bank of cached variants by seed keeps that cost flat while still breaking up the stamped
// look -- combined with the per-square nudge and turn below (continuous, so even two squares sharing a
// variant still don't land alike). The bank is wide enough that a human eye can't spot the repeat inside
// one field (owner playtest 2026-10-13, round 2: "more diversity for the rocks" -- 12 was too few once
// the shapes themselves also moved, since the eye would still start to notice the loop).
const ART_VARIANTS = 48;
const variantCache = new Map();
function variantArt(look, type, seed) {
  // Resolve the look that will actually be drawn ONCE, then use that same resolved look for both the
  // cache key and the lookup below -- keying by the raw, unresolved `look` let an unsupported or missing
  // look's fallback (which depends on `type`) get cached under `type`'s absence, so whichever terrain
  // type rendered that seed first silently decided the fallback art for every other type after it
  // (pre-merge review finding, terrain-art.js:153).
  const effectiveLook = TERRAIN_LOOKS.includes(look) ? look : terrainLook({type});
  const variantSeed = 1 + (Math.abs(Number(seed) || 1) % ART_VARIANTS) * 7;
  const key = effectiveLook + "|" + variantSeed;
  let art = variantCache.get(key);
  if (art === undefined) {
    art = DECOR[effectiveLook]?.rule ? decorArt(effectiveLook, variantSeed) : shapes[effectiveLook](variantSeed);
    variantCache.set(key, art);
  }
  return art;
}

// seed varies a biome piece between squares (each rock its own shape); the rules never see it.
// rotation turns a biome piece's drawing about the square's centre (the editor's Turn control); only the look.
export function terrainCellMarkup(type, look, rulesOverlay = false, seed = 7, rotation = 0) {
  const presentation = terrainPresentation(type, rulesOverlay);
  if (!presentation.known) return "";
  const tip = type === "DIFFICULT" ? "Difficult terrain: each foot of movement costs one extra foot." :
    type === "SIMPLE_COVER" ? "Simple cover: a creature protected by it gains +2 AC." : "Qi hazard square.";
  if (rulesOverlay) {
    const klass = type === "SIMPLE_COVER" ? "tt-cell-cover" : type === "QI_HAZARD" ? "tt-cell-hazard" : "tt-cell-difficult";
    return `<title>${tip}</title><rect x="0" y="0" width="64" height="64" class="${klass}"/>`;
  }
  const art = look === 'bamboo_clump' ? shapes.bamboo_clump(seed) : variantArt(look, type, seed);
  // Physical bamboo stems are fixed in shared hundredths; leaf fans retain
  // their variant. Turning rotates both these stems and the compiled cross.
  if (look === 'bamboo_clump') return `<title>${tip}</title><g class="tt-rule-terrain tt-rule-terrain-${type.toLowerCase()}" aria-hidden="true"${[90,180,270].includes(Number(rotation)) ? ` transform="rotate(${Number(rotation)} 32 32)"` : ''}>${art}</g>`;
  // Each drawing carries its own soft contact shadow. A small seeded nudge and spin of the whole piece
  // (cheap, computed fresh per square even when its variant is shared with a neighbour) keeps a big field
  // of one look from reading as the same icon copy-pasted across every square (owner playtest 2026-10-13:
  // a rubble field stamped identically, square after square; round 2: still too uniform at normal zoom,
  // so the spin was added on top of the shapes themselves now varying in count, size, and position).
  const place = seeded(Number(seed) + 500), nudgeX = r2((place() - 0.5) * 5), nudgeY = r2((place() - 0.5) * 5);
  const spin = seeded(Number(seed) + 9000), wobble = r2((spin() - 0.5) * 20);
  const turn = [90, 180, 270].includes(Number(rotation)) ? ` transform="rotate(${Number(rotation)} 32 32)"` : "";
  return `<title>${tip}</title><g class="tt-rule-terrain tt-rule-terrain-${type.toLowerCase()}" aria-hidden="true"${turn}>` +
    `<g transform="translate(${nudgeX} ${nudgeY}) rotate(${wobble} 32 32)">${art}</g></g>`;
}
