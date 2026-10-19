// Natural drawings for the table's nonmagical rules terrain. This module only paints
// the rule cells supplied by the map; it never changes their movement or cover rules.
import {DECOR, decorArt} from "./decor-art.js?v=sol196r1";

// The biome pieces with a rules meaning (decor-art.js, rule "SIMPLE_COVER" or "DIFFICULT") are looks for ordinary
// cover and difficult terrain rows, so they join the list after the original eleven.
export const TERRAIN_LOOKS = Object.freeze([
  "boulder", "bamboo_clump", "broken_tiles", "lantern", "low_wall", "pillar_rubble",
  "roots", "rubble", "scree", "statue_plinth", "stones",
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
import {blade, culm, fan, r2, rock, soft, taper} from "./art-kit.js?v=sol196p2";

const shapes = Object.freeze({
  // One big rounded boulder with a smaller stone tucked against it.
  boulder: rock(30, 31, 25, 11, "grey", {sides: 9}) + rock(53, 51, 8, 4, "grey", {sides: 6})
    + '<path d="M18 22q6-5 14-4M24 38l6 6M40 22l4 4" stroke="#4f4b45" stroke-width="1" fill="none" opacity=".7"/>'
    + '<path d="M36 47q6 1 10-4q-2 5-9 6z" fill="#6f7d4c" opacity=".85"/>',
  // A clump of bamboo from above: a ring of culms and narrow leaves fanning out from them.
  bamboo_clump: soft(35, 37, 26, 24, 0.38)
    + [[0, 22], [40, 20], [85, 23], [130, 21], [175, 22], [220, 20], [265, 23], [310, 21]].map(([a, d], i) =>
      fan(r2(32 + Math.cos(a * Math.PI / 180) * d * 0.55), r2(32 + Math.sin(a * Math.PI / 180) * d * 0.55), a, 14, i % 2)).join("")
    + [[26, 26, 4.6], [35, 23, 4], [40, 32, 4.6], [31, 37, 4.2], [22, 35, 3.8], [33, 30, 3.4]].map(([x, y, r]) => culm(x, y, r)).join("")
    + [[20, 30], [70, 26], [160, 27], [250, 28], [330, 25]].map(([a, d], i) =>
      fan(r2(32 + Math.cos(a * Math.PI / 180) * d * 0.7), r2(32 + Math.sin(a * Math.PI / 180) * d * 0.7), a + 20, 12, 2)).join(""),
  // Floor tiles cracked and lifted: some tipped, some missing, chips in the gaps.
  broken_tiles: soft(32, 34, 26, 24, 0.2)
    + '<path d="M6 8L30 7L31 30L7 31Z" fill="#3a3631"/><path d="M34 9L57 6L59 29L35 31Z" fill="#3a3631"/><path d="M7 35L29 34L30 57L6 58Z" fill="#3a3631"/>'
    + '<path d="M7 7L29 8L28 29L8 30Z" fill="#a39b8b" stroke="#5a5449" stroke-width=".9"/><path d="M8 8.5L28 9" stroke="#e2dccb" stroke-width="1" opacity=".8"/><path d="M12 14l7 6 6-2M18 20l-2 7" stroke="#4a453d" stroke-width=".9" fill="none"/>'
    + '<path d="M36 10L56 8L57 27L37 30Z" fill="#8f8777" stroke="#5a5449" stroke-width=".9" transform="rotate(7 46 19)"/><path d="M37 11L55 9" stroke="#d6cfbd" stroke-width="1" opacity=".7" transform="rotate(7 46 19)"/>'
    + '<path d="M8 36L28 35L29 56L8 57Z" fill="#9c9483" stroke="#5a5449" stroke-width=".9" transform="rotate(-6 18 46)"/><path d="M10 37L27 36.5" stroke="#ddd6c4" stroke-width="1" opacity=".7" transform="rotate(-6 18 46)"/>'
    + '<path d="M35 35L58 34L59 58L36 58Z" fill="#2c2924"/><path d="M38 38L49 36L46 47L37 49Z" fill="#7d7566" stroke="#4a453d" stroke-width=".8"/>'
    + '<path d="M51 44l5 1-1 6-6-1zM41 52l4-1 1 4-4 1z" fill="#8f8777" stroke="#4a453d" stroke-width=".6"/>'
    + '<path d="M21 31l3 2-2 2zM31 22l2 1-1 2z" fill="#b8b09f"/>',
  // A stone lantern seen from above: the square roof with its four hips and corner curls, the jewel on top,
  // and warm light spilling round it onto the ground.
  lantern: '<circle cx="32" cy="32" r="31" fill="#ffcf6e" opacity=".12"/><circle cx="32" cy="32" r="26" fill="#ffcf6e" opacity=".16"/><circle cx="32" cy="32" r="23" fill="#ffe2a0" opacity=".2"/>'
    + soft(37, 38, 20, 18, 0.35)
    + '<path d="M11 11Q32 15 53 11Q49 32 53 53Q32 49 11 53Q15 32 11 11Z" fill="#8a857a" stroke="#3f3c36" stroke-width="1.2"/>'
    + '<path d="M11 11L32 32L53 11Q32 15 11 11Z" fill="#c9c3b4"/><path d="M11 11L32 32L11 53Q15 32 11 11Z" fill="#aaa497"/>'
    + '<path d="M53 11L32 32L53 53Q49 32 53 11Z" fill="#6f6a60"/><path d="M11 53L32 32L53 53Q32 49 11 53Z" fill="#5f5a51"/>'
    + '<path d="M11 11L32 32L53 53M53 11L32 32L11 53" stroke="#3f3c36" stroke-width="1" fill="none"/>'
    + '<path d="M11 11L32 32M11 53L32 32" stroke="#ece6d6" stroke-width=".7" opacity=".6"/>'
    + '<circle cx="32" cy="32" r="6" fill="#9a9488" stroke="#3f3c36" stroke-width="1"/><circle cx="30.5" cy="30.5" r="2.6" fill="#e9e3d3"/>'
    + '<path d="M9 9l4 1-1 4zM55 9l-4 1 1 4zM9 55l4-1-1-4zM55 55l-4-1 1-4z" fill="#d6d0c0" stroke="#3f3c36" stroke-width=".6"/>',
  // A tumbledown dry-stone wall running east to west: a band of stacked stones with gaps and a fallen one.
  low_wall: soft(33, 36, 31, 17, 0.35)
    + [[6, 25, 9, 1], [21, 23, 10, 2], [37, 25, 9.5, 3], [53, 23, 10, 5], [12, 39, 9.5, 7], [28, 40, 10, 8], [44, 39, 9.5, 9], [58, 40, 7, 10]]
    .map(([x, y, r, seed]) => rock(x, y, r, seed + 30, "warm", {sides: 6, squash: 0.8, shadow: false})).join("")
    + rock(52, 56, 5, 41, "warm", {sides: 5}),
  // A toppled column: a fluted drum lying east-west with its broken end, and chunks of capital beside it.
  pillar_rubble: soft(32, 37, 28, 16, 0.35)
    + '<path d="M7 21Q4 32 7 43H45L49 39 45 35 50 31 45 27 48 24 45 21Z" fill="#a49e90" stroke="#4f4b45" stroke-width="1.1"/>'
    + '<path d="M8 22H45L46 24 44 27H8Z" fill="#e9e3d4"/><path d="M8 27H44L47 31H8Z" fill="#cbc5b6"/><path d="M8 36H45L48 39 45 43H8Z" fill="#7e786c"/>'
    + '<path d="M9 27H44M9 31H46M9 35.5H45M9 39.5H46" stroke="#6f695e" stroke-width=".7" fill="none"/>'
    + '<path d="M7 21Q4 32 7 43Q11 32 7 21Z" fill="#8e887b" stroke="#4f4b45" stroke-width=".8"/>'
    + rock(55, 48, 7.5, 51, "grey", {sides: 6}) + rock(52, 14, 6, 52, "grey", {sides: 5}) + rock(19, 53, 5, 53, "grey", {sides: 5}),
  // Gnarled roots across the ground: thick, tapering, barked, crossing each other.
  roots: soft(32, 34, 30, 26, 0.18)
    + [
      // Surface roots of a tree off this square, entering from the north-west and forking as they run out; the forks
      // are drawn first so each parent root covers the joint.
      [[37, 31], [50, 38], [64, 41], 7], [[37, 32], [42, 48], [37, 64], 7], [[27, 44], [36, 55], [50, 62], 5.5],
      [[32, 16], [47, 13], [63, 6], 5.5], [[19, 13], [12, 22], [4, 27], 4.5],
      [[-2, 9], [22, 16], [39, 33], 12], [[-2, 36], [15, 34], [29, 46], 9], [[13, -2], [19, 10], [34, 16], 8.5],
    ].map(([a, m, b, w]) => `<path d="${taper(a, m, b, w, 0.42)}" fill="#5f4a35" stroke="#1f160c" stroke-width="1"/>`
      + `<path d="${taper([a[0] - 0.8, a[1] - 1.2], [m[0] - 0.8, m[1] - 1.2], [b[0] - 0.6, b[1] - 0.8], w * 0.36, 0.4)}" fill="#a38664" opacity=".7"/>`).join("")
    + '<ellipse cx="22" cy="17" rx="2.2" ry="1.4" fill="#2e2216"/><ellipse cx="44" cy="40" rx="1.6" ry="1.1" fill="#2e2216"/><ellipse cx="16" cy="35" rx="1.6" ry="1.1" fill="#2e2216"/>',
  // A spill of masonry: broken blocks and stones of mixed sizes, with grit between them.
  rubble: rock(21, 23, 13, 61, "grey", {sides: 5}) + rock(44, 19, 10, 62, "warm", {sides: 5}) + rock(42, 42, 14, 63, "grey", {sides: 6})
    + rock(17, 46, 9, 64, "warm", {sides: 5}) + rock(56, 55, 5.5, 65, "grey", {sides: 5}) + rock(29, 56, 5, 66, "grey", {sides: 5})
    + '<path d="M30 33l2 1-1 2zM9 33l2 0 0 2zM55 32l2 1-2 1zM28 9l2 1-2 1z" fill="#b4ae9f"/>',
  // Loose scree: many small angular stones scattered downslope.
  scree: [[10, 12, 4.5], [24, 9, 3.5], [40, 12, 5], [54, 10, 3.5], [16, 26, 3.5], [32, 24, 5.5], [48, 28, 4.5], [8, 40, 4], [22, 41, 5], [38, 40, 3.5],
    [55, 43, 5], [14, 54, 3.5], [30, 55, 4.5], [46, 56, 4], [60, 30, 3]]
    .map(([x, y, r], i) => rock(x, y, r, 70 + i, i % 3 ? "grey" : "dark", {sides: 5})).join("")
    + '<path d="M18 17l1.5 1-1 1.5zM44 20l1.5.5-1 1.5zM28 33l1.5 1-1.5 1zM50 37l1 1.5-1.5.5zM9 48l1.5 1-1 1zM38 48l1.5 1-1.5.5z" fill="#9c968a"/>',
  // An empty statue plinth: a two-step square base whose figure has broken away, leaving the feet.
  statue_plinth: soft(36, 38, 26, 24, 0.35)
    + '<path d="M8 8H56V56H8Z" fill="#8d887d" stroke="#3f3c36" stroke-width="1.1"/><path d="M8 8L14 14H50L56 8Z" fill="#cfc9ba"/><path d="M8 8L14 14V50L8 56Z" fill="#b2ac9e"/>'
    + '<path d="M56 8L50 14V50L56 56Z" fill="#6c675e"/><path d="M8 56L14 50H50L56 56Z" fill="#5f5a51"/>'
    + '<path d="M14 14H50V50H14Z" fill="#a7a194" stroke="#4f4b45" stroke-width=".9"/><path d="M15 49V15H49" stroke="#ebe5d6" stroke-width="1" fill="none"/>'
    + '<path d="M25 26l6-2 2 7-6 2zM34 31l6-1 1 7-6 1z" fill="#6e7d70" stroke="#2f3a32" stroke-width=".8"/><path d="M25.5 26.5l5-1.6M34.5 31.3l5-.8" stroke="#c6d6c8" stroke-width=".8"/>'
    + '<path d="M22 40l3 3-4 1zM42 22l2 3-3 0z" fill="#8a9a8c" stroke="#2f3a32" stroke-width=".5"/>',
  // A few smooth river stones half-sunk in the ground.
  stones: [[17, 19, 11, 81, 0.7, 0.3], [44, 15, 9, 82, 0.75, -0.4], [46, 43, 12, 83, 0.65, 0.5], [19, 46, 10, 84, 0.7, -0.2], [32, 31, 5.5, 85, 0.8, 0]]
    .map(([x, y, r, seed, squash, angle]) => soft(x + 1.6, y + 2.2, r * 1.05, r * squash) + `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${r2(r * squash)}" transform="rotate(${r2(angle * 57)} ${x} ${y})" fill="#7d786f" stroke="#3f3c36" stroke-width="1"/>`
      + `<ellipse cx="${r2(x - r * 0.18)}" cy="${r2(y - r * 0.2)}" rx="${r2(r * 0.66)}" ry="${r2(r * squash * 0.6)}" transform="rotate(${r2(angle * 57)} ${x} ${y})" fill="#b1ab9e"/>`
      + `<ellipse cx="${r2(x - r * 0.3)}" cy="${r2(y - r * 0.32)}" rx="${r2(r * 0.25)}" ry="${r2(r * squash * 0.18)}" transform="rotate(${r2(angle * 57)} ${x} ${y})" fill="#e8e2d2" opacity=".8"/>`).join(""),
});

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
  const art = DECOR[look]?.rule ? decorArt(look, seed) : shapes[TERRAIN_LOOKS.includes(look) ? look : terrainLook({type})];
  // Each drawing carries its own soft contact shadow.
  const turn = [90, 180, 270].includes(Number(rotation)) ? ` transform="rotate(${Number(rotation)} 32 32)"` : "";
  return `<title>${tip}</title><g class="tt-rule-terrain tt-rule-terrain-${type.toLowerCase()}" aria-hidden="true"${turn}>${art}</g>`;
}
