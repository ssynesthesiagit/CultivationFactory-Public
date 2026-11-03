// Trees seen from above (owner 2026-09-28 trees; 2026-10-08 overhaul and "other types of trees, fall, willows, cherry
// blossoms"). Every kind of tree follows the same rules: its trunk squares (board.js treeCells) block movement and
// sight like a wall, and the crown drawn here is only the look. A tree's `look` names one of TREE_LOOKS; a tree saved
// without one is the broadleaf it has always been. Markup is in board units (one square = 1), lit from the north-west.
import {bambooCulms} from './scenery-sight.js?v=loslines3';
export const TREE_LOOKS = Object.freeze({
  broadleaf: "Broadleaf tree",
  maple: "Autumn maple",
  cherry: "Cherry blossom",
  willow: "Weeping willow",
  pine: "Pine",
  snowy_pine: "Snowy pine",
  dead: "Bare dead tree",
  ancient: "Gnarled ancient tree",
  bamboo_stand: "Bamboo stand",
  golden_bamboo: "Golden bamboo stand",
});

export const treeLook = tree => (Object.hasOwn(TREE_LOOKS, tree?.look) ? tree.look : "broadleaf");

const r3 = n => Math.round(n * 1000) / 1000;

// Leaf palettes for the clumped crowns: gradient stops (lit, mid, shade), the underside, the lit-dab colour.
const CROWNS = {
  broadleaf: {stops: ["#8dba52", "#4f8030", "#24421a"], under: "#162a0f", understory: "#1c3313", dab: [[200, 240, 130], [230, 240, 170]], dark: "rgba(16,36,10,0.45)", rim: "rgba(14,28,8,0.35)", glow: "rgba(190,226,120,0.2)"},
  maple: {stops: ["#f6b04a", "#d0582a", "#6e2014"], under: "#4a160c", understory: "#5a1d10", dab: [[255, 214, 120], [250, 170, 90]], dark: "rgba(70,18,8,0.45)", rim: "rgba(60,14,6,0.4)", glow: "rgba(255,210,120,0.22)"},
  cherry: {stops: ["#ffe1ec", "#f2a4c0", "#b0577a"], under: "#6e3348", understory: "#5c3b2c", dab: [[255, 246, 250], [255, 214, 230]], dark: "rgba(120,50,80,0.35)", rim: "rgba(110,40,70,0.35)", glow: "rgba(255,240,246,0.3)"},
  willow: {stops: ["#d6e690", "#9ab955", "#5b7c30"], under: "#4d6e2a", understory: "#3b5521", dab: [[230, 240, 170], [210, 230, 150]], dark: "rgba(40,60,20,0.35)", rim: "rgba(60,80,30,0.3)", glow: "rgba(230,240,170,0.25)"},
  ancient: {stops: ["#a8b66e", "#5c7a3a", "#2a4019"], under: "#1a2e10", understory: "#22381a", dab: [[170, 210, 110], [150, 190, 120]], dark: "rgba(10,24,6,0.5)", rim: "rgba(10,20,6,0.45)", glow: "rgba(170,210,110,0.16)"},
};

function seeded(tree, salt = 0) {
  let seed = ((tree.x * 73856093) ^ (tree.y * 19349663) ^ ((tree.seed || 1) * 83492791) ^ salt) >>> 0;
  return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
}

// A ragged clump outline: a circle whose edge bulges into small leafy scallops.
function clump(cx, cy, r, rand) {
  const n = 20 + Math.floor(rand() * 9), phase = rand() * 6.28, pts = [];
  for (let i = 0; i < n; i += 1) {
    const a = phase + (i / n) * Math.PI * 2, k = 0.8 + rand() * 0.3;
    pts.push([cx + Math.cos(a) * r * k, cy + Math.sin(a) * r * k]);
  }
  let d = "";
  pts.forEach(([x, y], i) => {
    const [nx, ny] = pts[(i + 1) % n], mx = (x + nx) / 2, my = (y + ny) / 2;
    const out = 1.1 + rand() * 0.28, qx = cx + (mx - cx) * out, qy = cy + (my - cy) * out;
    d += `${i ? "" : `M${r3(x)} ${r3(y)}`}Q${r3(qx)} ${r3(qy)} ${r3(nx)} ${r3(ny)}`;
  });
  return `${d}Z`;
}

// A tapering limb or root from (x0, y0) to (x1, y1) bending through (mx, my), w wide at its base.
function limb([x0, y0], [mx, my], [x1, y1], w, fill, stroke, end = 0.24) {
  const a0 = Math.atan2(my - y0, mx - x0), a1 = Math.atan2(y1 - my, x1 - mx);
  const n0 = [-Math.sin(a0) * w / 2, Math.cos(a0) * w / 2], n1 = [-Math.sin(a1) * w * end / 2, Math.cos(a1) * w * end / 2];
  const nm = [(n0[0] + n1[0]) * 0.55, (n0[1] + n1[1]) * 0.55];
  const d = `M${r3(x0 + n0[0])} ${r3(y0 + n0[1])}Q${r3(mx + nm[0])} ${r3(my + nm[1])} ${r3(x1 + n1[0])} ${r3(y1 + n1[1])}`
    + `L${r3(x1 - n1[0])} ${r3(y1 - n1[1])}Q${r3(mx - nm[0])} ${r3(my - nm[1])} ${r3(x0 - n0[0])} ${r3(y0 - n0[1])}Z`;
  return `<path d="${d}" fill="${fill}" stroke="${stroke}" stroke-width="${r3(w * 0.12)}"/>`;
}

const shadow = (cx, cy, reach, size, k = 1) => `<ellipse cx="${r3(cx + 0.35 * size)}" cy="${r3(cy + 0.45 * size)}" rx="${r3(reach * 1.1 * k)}" ry="${r3(reach * k)}" fill="url(#tt-tree-shadow)"/>`;

// Roots flaring out from under the crown's edge.
function roots(cx, cy, reach, size, rand, count, color = "#4a3622") {
  let out = "";
  for (let i = 0; i < count; i += 1) {
    const a = (i / count) * Math.PI * 2 + rand() * 1.2, r0 = reach * 0.66, r1 = reach * (0.92 + rand() * 0.14), bend = (rand() - 0.5) * 0.4;
    out += limb([cx + Math.cos(a) * r0, cy + Math.sin(a) * r0], [cx + Math.cos(a + bend * 0.5) * (r0 + r1) / 2, cy + Math.sin(a + bend * 0.5) * (r0 + r1) / 2],
      [cx + Math.cos(a + bend) * r1, cy + Math.sin(a + bend) * r1], 0.16 * size, color, "#20150a");
  }
  return out;
}

// Limbs from the trunk out toward the crown's edge.
function limbs(cx, cy, reach, size, rand, count, reachK = 0.7, color = "#6e5133") {
  let out = "";
  for (let i = 0; i < count; i += 1) {
    const a = (i / count) * Math.PI * 2 + rand() * 0.6, len = reach * (reachK - 0.08 + rand() * 0.2), bend = (rand() - 0.5) * 0.6;
    out += limb([cx, cy], [cx + Math.cos(a + bend) * len * 0.5, cy + Math.sin(a + bend) * len * 0.5], [cx + Math.cos(a) * len, cy + Math.sin(a) * len], 0.12 * size, color, "#2b1d10");
  }
  return out;
}

// Petals or fallen leaves on the ground round a tree, in the colours given.
function litter(cx, cy, reach, rand, count, colors, size = 0.05) {
  let out = "";
  for (let i = 0; i < count; i += 1) {
    const a = rand() * Math.PI * 2, d = reach * (0.75 + rand() * 0.5), x = r3(cx + Math.cos(a) * d), y = r3(cy + Math.sin(a) * d);
    out += `<ellipse cx="${x}" cy="${y}" rx="${r3(size * (0.7 + rand() * 0.6))}" ry="${r3(size * 0.5)}" transform="rotate(${Math.round(rand() * 180)} ${x} ${y})" fill="${colors[i % colors.length]}" opacity="0.85"/>`;
  }
  return out;
}

// The clumped crown shared by broadleaf, maple, cherry and the ancient tree.
function crown(tree, look) {
  const pal = CROWNS[look], size = tree.size === 2 ? 2 : 1, cx = tree.x + size / 2, cy = tree.y + size / 2;
  const ancient = look === "ancient", reach = (size === 2 ? 2.7 : 1.65) * (ancient ? 1.06 : 1);
  const rand = seeded(tree);
  let out = shadow(cx, cy, reach, size);
  if (look === "maple") out += litter(cx, cy, reach, seeded(tree, 7), 26 * size, ["#e2672f", "#f0a63c", "#b8331f", "#f5c04a"], 0.07);
  if (look === "cherry") out += litter(cx, cy, reach, seeded(tree, 7), 34 * size, ["#ffd6e4", "#f6b2c8", "#fff0f5"], 0.045);
  out += `<path d="${clump(cx + reach * 0.05, cy + reach * 0.07, reach * (look === "cherry" ? 0.78 : 0.86), rand)}" fill="${pal.understory}" opacity="${look === "cherry" ? 0.75 : 0.92}"/>`;
  out += limbs(cx, cy, reach, size, rand, size === 2 ? 7 : 5, 0.7, look === "cherry" ? "#5a3a2e" : "#6e5133");
  out += `<circle cx="${r3(cx)}" cy="${r3(cy)}" r="${r3(0.13 * size)}" fill="#4a3520" stroke="#2b1d10" stroke-width="0.03"/>`;
  out += roots(cx, cy, reach, size * (ancient ? 1.2 : 1), rand, (size === 2 ? 4 : 3) + (ancient ? 3 : 0), ancient ? "#54412c" : "#4a3622");
  // The crown: an outer ring of clumps, then an inner ring, then the top; outer ones are darker and lower. Cherry
  // blossom is airier, with gaps where the dark branches show.
  const rings = size === 2 ? [[8, 0.62, 0.34], [5, 0.3, 0.36], [1, 0, 0.34]] : [[6, 0.58, 0.36], [3, 0.24, 0.38], [1, 0, 0.3]];
  const airy = look === "cherry" ? 0.82 : 1;
  rings.forEach(([count, dist, rad], ring) => {
    const turn = rand() * Math.PI * 2;
    for (let i = 0; i < count; i += 1) {
      const a = turn + (i / count) * Math.PI * 2 + (rand() - 0.5) * 0.4;
      const d = reach * dist * (0.9 + rand() * 0.2), r = reach * rad * (0.85 + rand() * 0.3) * airy;
      const x = cx + Math.cos(a) * d, y = cy + Math.sin(a) * d;
      out += `<path d="${clump(x + r * 0.12, y + r * 0.16, r, rand)}" fill="${pal.under}" opacity="${ring === 0 ? 0.8 : 0.7}"/>`;
      out += `<path d="${clump(x, y, r * 0.94, rand)}" fill="url(#tt-tree-${look})" stroke="${pal.rim}" stroke-width="0.012"/>`;
      out += `<path d="${clump(x - r * 0.2, y - r * 0.24, r * 0.55, rand)}" fill="${pal.glow}"/>`;
      for (let k = 0; k < 14; k += 1) {
        const lit = k < 9, la = lit ? -2.4 + rand() * 1.8 : 0.3 + rand() * 1.8, ld = r * (0.2 + rand() * 0.65);
        const lx = r3(x + Math.cos(la) * ld), ly = r3(y + Math.sin(la) * ld), [cr, cg, cb] = pal.dab[k % 2];
        out += `<ellipse cx="${lx}" cy="${ly}" rx="${r3(r * (0.06 + rand() * 0.05))}" ry="${r3(r * 0.04)}" transform="rotate(${Math.round(rand() * 180)} ${lx} ${ly})" `
          + `fill="${lit ? `rgba(${cr},${cg},${cb},0.5)` : pal.dark}"/>`;
      }
    }
  });
  if (ancient) {  // hanging moss and a few old dead twigs poking through the top
    const moss = seeded(tree, 3);
    for (let i = 0; i < 7 * size; i += 1) {
      const a = moss() * Math.PI * 2, d = reach * (0.3 + moss() * 0.6), x = r3(cx + Math.cos(a) * d), y = r3(cy + Math.sin(a) * d);
      out += `<path d="M${x} ${y}q${r3(0.04 * size)} ${r3(0.12 * size)} 0 ${r3(0.22 * size)}" stroke="#9fb27a" stroke-width="${r3(0.035 * size)}" fill="none" opacity="0.7"/>`;
    }
  }
  return out;
}

// A weeping willow from above: a rounded, light yellow-green crown, and round it long fine fronds hanging past the
// edge in soft curtains -- bunches of thin strands falling together, half see-through, lit on the north-west.
function willow(tree) {
  const size = tree.size === 2 ? 2 : 1, cx = tree.x + size / 2, cy = tree.y + size / 2, reach = size === 2 ? 2.8 : 1.7, rand = seeded(tree);
  let out = shadow(cx, cy, reach, size, 1.02);
  out += `<path d="${clump(cx, cy, reach * 0.97, rand)}" fill="rgb(104,134,56)" opacity="0.45"/>`;
  out += limbs(cx, cy, reach, size, rand, size === 2 ? 6 : 4, 0.6);
  const curtains = [];
  for (let g = 0, n = size === 2 ? 54 : 32; g < n; g += 1) curtains.push([(g / n) * Math.PI * 2 + rand() * 0.12, rand()]);
  curtains.sort((p, q) => -Math.cos(p[0] - 3.93) + Math.cos(q[0] - 3.93));
  for (const [a, tone] of curtains) {
    const curl = (rand() - 0.5) * 0.5, lit = (1 - Math.cos(a - 3.93)) / 2, nx = -Math.sin(a), ny = Math.cos(a);
    let d = "";
    for (let j = 0; j < 9; j += 1) {
      const off = (j / 8 - 0.5) * reach * 0.16, r0 = reach * (0.5 + rand() * 0.12), r1 = reach * (0.9 + rand() * 0.12);
      const x0 = cx + Math.cos(a) * r0 + nx * off, y0 = cy + Math.sin(a) * r0 + ny * off;
      const x1 = cx + Math.cos(a + curl * 0.3) * r1 + nx * off * 1.2, y1 = cy + Math.sin(a + curl * 0.3) * r1 + ny * off * 1.2;
      const mx = (x0 + x1) / 2 + nx * curl * reach * 0.08, my = (y0 + y1) / 2 + ny * curl * reach * 0.08;
      d += `M${r3(x0)} ${r3(y0)}Q${r3(mx)} ${r3(my)} ${r3(x1)} ${r3(y1)}`;
    }
    const r = Math.round(120 + lit * 70 + tone * 20), g = Math.round(150 + lit * 60), b = Math.round(60 + lit * 30);
    out += `<path d="${d}" stroke="rgb(${r},${g},${b})" stroke-width="${r3(0.014 * size)}" fill="none" stroke-linecap="round" opacity="${r3(0.55 + lit * 0.35)}"/>`;
  }
  // The crown: soft overlapping clumps, lit on the north-west, with fine frond strokes running outward over it.
  for (let i = 0, n = size === 2 ? 11 : 7; i < n; i += 1) {
    const a = rand() * Math.PI * 2, d = i === 0 ? 0 : reach * (0.18 + rand() * 0.32), r = reach * (0.24 + rand() * 0.08);
    const x = cx + Math.cos(a) * d, y = cy + Math.sin(a) * d;
    out += `<path d="${clump(x + r * 0.1, y + r * 0.14, r, rand)}" fill="#4d6e2a" opacity="0.7"/>`
      + `<path d="${clump(x, y, r * 0.94, rand)}" fill="url(#tt-tree-willow)" stroke="#55752d" stroke-width="0.008"/>`;
  }
  let fine = "";
  for (let i = 0, n = size === 2 ? 220 : 120; i < n; i += 1) {
    const a = rand() * Math.PI * 2, at = reach * Math.sqrt(rand()) * 0.62, len = reach * (0.08 + rand() * 0.1);
    fine += `M${r3(cx + Math.cos(a) * at)} ${r3(cy + Math.sin(a) * at)}l${r3(Math.cos(a) * len)} ${r3(Math.sin(a) * len)}`;
  }
  out += `<path d="${fine}" stroke="#e1eda6" stroke-width="${r3(0.01 * size)}" opacity="0.45" stroke-linecap="round"/>`;
  return out;
}

// A conifer from above: stacked tiers, each a ragged star of branch tips, bristling with short needle strokes that run
// outward, dark blue-green beneath and lighter toward the leader and on the north-west. Snowy: snow lying in patches
// on the upper tiers.
function pine(tree, snowy) {
  const size = tree.size === 2 ? 2 : 1, cx = tree.x + size / 2, cy = tree.y + size / 2, reach = size === 2 ? 2.4 : 1.45, rand = seeded(tree);
  let out = shadow(cx, cy, reach, size, 1.05);
  const tiers = [[1, "#173322", [38, 74, 52]], [0.78, "#1f4029", [50, 92, 64]], [0.56, "#285036", [64, 112, 76]], [0.34, "#31603f", [84, 136, 92]], [0.16, "#3c7049", [110, 160, 110]]];
  tiers.forEach(([k, base, [gr, gg, gb]], t) => {
    const r = reach * k, points = Math.round(18 + 22 * k), turn = rand() * 6.28;
    let d = "";
    for (let i = 0; i <= points * 2; i += 1) {
      const a = turn + (i / (points * 2)) * Math.PI * 2, rr = i % 2 ? r * (0.8 + rand() * 0.06) : r * (0.94 + rand() * 0.08);
      d += `${i ? "L" : "M"}${r3(cx + Math.cos(a) * rr)} ${r3(cy + Math.sin(a) * rr)}`;
    }
    out += `<path d="${d}Z" fill="#0d1f14" opacity="0.6" transform="translate(${r3(0.05 * size)} ${r3(0.07 * size)})"/>`;
    out += `<path d="${d}Z" fill="${base}" stroke="#0d1f14" stroke-width="${r3(0.012 * size)}"/>`;
    // Needles, binned into a few shades so a tier is a handful of paths rather than hundreds.
    const bins = new Map();
    for (let i = 0, n = Math.round(150 * k * k * size + 20); i < n; i += 1) {
      const a = rand() * Math.PI * 2, dd = r * (0.25 + Math.sqrt(rand()) * 0.68), len = reach * (0.07 + rand() * 0.07), tilt = a + (rand() - 0.5) * 0.5;
      const light = (1 - Math.cos(a - 3.93)) / 2, mix = Math.round(Math.min(1, Math.max(0.15, 0.25 + light * 0.75 + (rand() - 0.5) * 0.2)) * 5) / 5;
      const x = cx + Math.cos(a) * dd, y = cy + Math.sin(a) * dd;
      bins.set(mix, (bins.get(mix) || "") + `M${r3(x)} ${r3(y)}l${r3(Math.cos(tilt) * len)} ${r3(Math.sin(tilt) * len)}`);
    }
    for (const [mix, d] of bins) out += `<path d="${d}" stroke="rgb(${Math.round(gr * mix + 10)},${Math.round(gg * mix + 20)},${Math.round(gb * mix + 14)})" stroke-width="${r3(0.018 * size)}" stroke-linecap="round"/>`;
    if (snowy && t >= 1) {
      // Snow lying along the needles: short drifts that follow each spray outward, bluish-white with a shaded
      // underside, on about half the tier so the green shows between them.
      let shade = "", snow = "";
      for (let i = 0, n = Math.round(70 * k * size + 12); i < n; i += 1) {
        const a = rand() * Math.PI * 2, dd = r * (0.35 + Math.sqrt(rand()) * 0.55), len = reach * (0.05 + rand() * 0.07), tilt = a + (rand() - 0.5) * 0.4;
        if (rand() < 0.45) continue;
        const x = cx + Math.cos(a) * dd, y = cy + Math.sin(a) * dd, ex = x + Math.cos(tilt) * len, ey = y + Math.sin(tilt) * len, w = 0.03 * size * (0.7 + rand() * 0.6);
        shade += `M${r3(x + 0.012 * size)} ${r3(y + 0.018 * size)}L${r3(ex + 0.012 * size)} ${r3(ey + 0.018 * size)}`;
        snow += `<path d="M${r3(x)} ${r3(y)}L${r3(ex)} ${r3(ey)}" stroke="${rand() < 0.5 ? "#eef4f9" : "#dbe6ef"}" stroke-width="${r3(w)}" stroke-linecap="round"/>`;  // width varies: one path each
      }
      out += `<path d="${shade}" stroke="#7f95a6" stroke-width="${r3(0.034 * size)}" stroke-linecap="round" opacity="0.6"/>` + snow;
    }
  });
  out += `<circle cx="${r3(cx)}" cy="${r3(cy)}" r="${r3(0.05 * size)}" fill="${snowy ? "#ffffff" : "#9cc896"}"/>`;
  return out;
}

// A bare dead tree: a forked trunk and branching limbs, grey and cracked, throwing a lace of shadow; no leaves.
function dead(tree) {
  const size = tree.size === 2 ? 2 : 1, cx = tree.x + size / 2, cy = tree.y + size / 2, reach = size === 2 ? 2.4 : 1.5, rand = seeded(tree);
  let shadows = "", wood = "";
  const branch = (x, y, a, len, w, depth) => {
    const bend = (rand() - 0.5) * 0.7, ex = x + Math.cos(a + bend) * len, ey = y + Math.sin(a + bend) * len;
    const mx = x + Math.cos(a + bend * 0.3) * len * 0.5, my = y + Math.sin(a + bend * 0.3) * len * 0.5;
    shadows += `<path d="M${r3(x + 0.2 * size)} ${r3(y + 0.26 * size)}Q${r3(mx + 0.2 * size)} ${r3(my + 0.26 * size)} ${r3(ex + 0.2 * size)} ${r3(ey + 0.26 * size)}" stroke="rgba(0,0,0,0.3)" stroke-width="${r3(w * 0.8)}" fill="none" stroke-linecap="round"/>`;
    wood += limb([x, y], [mx, my], [ex, ey], w, depth < 2 ? "#7d7266" : "#8f857a", "#2e2822", depth < 4 ? 0.62 : 0.15);
    if (depth < 4) for (let k = 0, n = 2 + (rand() < 0.3 ? 1 : 0); k < n; k += 1) branch(ex, ey, a + (k - (n - 1) / 2) * 0.6 + (rand() - 0.5) * 0.3, len * 0.66, w * 0.58, depth + 1);
  };
  for (let i = 0, n = size === 2 ? 5 : 4; i < n; i += 1) branch(cx, cy, (i / n) * Math.PI * 2 + rand() * 0.8, reach * 0.36, 0.13 * size, 0);
  const trunk = `<circle cx="${r3(cx)}" cy="${r3(cy)}" r="${r3(0.2 * size)}" fill="#6a5f53" stroke="#2e2822" stroke-width="${r3(0.025 * size)}"/>`
    + `<circle cx="${r3(cx - 0.03 * size)}" cy="${r3(cy - 0.03 * size)}" r="${r3(0.12 * size)}" fill="#a39788"/><path d="M${r3(cx - 0.1 * size)} ${r3(cy)}L${r3(cx + 0.08 * size)} ${r3(cy - 0.04 * size)}" stroke="#2e2822" stroke-width="${r3(0.02 * size)}"/>`;
  return shadows + wood + trunk;
}

// A bamboo stand that grows as tall and dense as a tree: bunches of culm discs under leaf fans. Golden bamboo is the
// yellow-culmed kind with paler leaves.
function bamboo(tree, golden) {
  const size = tree.size === 2 ? 2 : 1, cx = tree.x + size / 2, cy = tree.y + size / 2, reach = size === 2 ? 2.1 : 1.3, rand = seeded(tree);
  const leafColors = golden ? ["#7f9a3a", "#a8bf55", "#c9d97a", "#5f7a2c"] : ["#3f6b26", "#5d8c34", "#7eaa48", "#2f5520"];
  const culmColor = golden ? ["#c9a83a", "#e8d27a", "#7a6418"] : ["#4a7a2c", "#b6cf86", "#1d3313"];
  let out = shadow(cx, cy, reach, size, 0.95);
  const fan = (x, y, angle, len, shade) => {
    let s = "";
    for (let k = 0; k < 5; k += 1) {
      const a = angle + (k - 2) * 0.32, lx = x + Math.cos(a) * len, ly = y + Math.sin(a) * len, w = len * 0.14;
      const nx = -Math.sin(a) * w, ny = Math.cos(a) * w;
      s += `<path d="M${r3(x)} ${r3(y)}Q${r3((x + lx) / 2 + nx)} ${r3((y + ly) / 2 + ny)} ${r3(lx)} ${r3(ly)}Q${r3((x + lx) / 2 - nx)} ${r3((y + ly) / 2 - ny)} ${r3(x)} ${r3(y)}Z" fill="${leafColors[(shade + k) % 4]}" stroke="#1c3014" stroke-width="0.008"/>`;
    }
    return s;
  };
  for (let i = 0, n = 26 * size; i < n; i += 1) {
    const a = rand() * Math.PI * 2, d = reach * (0.2 + rand() * 0.55);
    out += fan(cx + Math.cos(a) * d, cy + Math.sin(a) * d, a + (rand() - 0.5) * 0.8, reach * 0.24 + rand() * 0.08, 3);
  }
  const culms = bambooCulms(tree.x,tree.y,size).map(p=>[p.x/100,p.y/100,p.r/100]);
  culms.sort((p, q) => (p[0] + p[1]) - (q[0] + q[1]));
  for (const [x, y, r] of culms) {
    out += `<circle cx="${r3(x + r * 0.5)}" cy="${r3(y + r * 0.7)}" r="${r3(r)}" fill="#000" opacity="0.35"/>`
      + `<circle cx="${r3(x)}" cy="${r3(y)}" r="${r3(r)}" fill="${culmColor[0]}" stroke="${culmColor[2]}" stroke-width="${r3(r * 0.18)}"/>`
      + `<circle cx="${r3(x)}" cy="${r3(y)}" r="${r3(r * 0.6)}" fill="${culmColor[1]}" opacity="0.85"/><circle cx="${r3(x)}" cy="${r3(y)}" r="${r3(r * 0.26)}" fill="#26300f"/>`;
  }
  for (let i = 0, n = 16 * size; i < n; i += 1) {
    const a = rand() * Math.PI * 2, d = reach * (0.4 + rand() * 0.45);
    out += fan(cx + Math.cos(a) * d, cy + Math.sin(a) * d, a + (rand() - 0.5) * 0.9, reach * 0.2 + rand() * 0.06, 1 + (i % 2));
  }
  return out;
}

// A gnarled ancient tree: a crown broken into a few heavy, irregular masses of mossy foliage with gaps between them,
// through which great twisting limbs show; a thick fissured trunk at the heart, and roots flaring far out over the
// ground. Only the look is bigger: the trunk squares are the same as any tree's.
function ancientTree(tree) {
  const size = tree.size === 2 ? 2 : 1, cx = tree.x + size / 2, cy = tree.y + size / 2, reach = (size === 2 ? 2.8 : 1.75), rand = seeded(tree);
  const pal = CROWNS.ancient;
  let out = shadow(cx, cy, reach, size, 1.05);
  // root flare: heavy roots curving out from the trunk and tapering away just past the crown's edge, mostly in its shade
  for (let i = 0, n = size === 2 ? 8 : 6; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2 + rand() * 0.5, bend = (rand() < 0.5 ? -1 : 1) * (0.25 + rand() * 0.25), r1 = reach * (0.92 + rand() * 0.12);
    const p0 = [cx + Math.cos(a) * 0.2 * size, cy + Math.sin(a) * 0.2 * size];
    const mid = [cx + Math.cos(a + bend) * r1 * 0.55, cy + Math.sin(a + bend) * r1 * 0.55], end = [cx + Math.cos(a + bend * 0.3) * r1, cy + Math.sin(a + bend * 0.3) * r1];
    out += limb(p0, mid, end, 0.28 * size, "#5e4a33", "#22170c", 0.1)
      + `<path d="M${r3(p0[0])} ${r3(p0[1])}Q${r3(mid[0] - 0.02)} ${r3(mid[1] - 0.03)} ${r3(end[0])} ${r3(end[1])}" stroke="#9c8462" stroke-width="${r3(0.025 * size)}" fill="none" opacity="0.55"/>`;
  }
  // great limbs twisting out from the trunk (seen in the gaps of the crown)
  const limbAngles = [];
  for (let i = 0, n = size === 2 ? 6 : 5; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2 + rand() * 0.6, len = reach * (0.55 + rand() * 0.12), bend = (rand() - 0.5) * 1.1;
    limbAngles.push(a);
    out += limb([cx, cy], [cx + Math.cos(a + bend) * len * 0.5, cy + Math.sin(a + bend) * len * 0.5], [cx + Math.cos(a) * len, cy + Math.sin(a) * len], 0.24 * size, "#6a5238", "#22170c", 0.35);
    out += `<path d="M${r3(cx)} ${r3(cy)}Q${r3(cx + Math.cos(a + bend) * len * 0.5 - 0.02)} ${r3(cy + Math.sin(a + bend) * len * 0.5 - 0.03)} ${r3(cx + Math.cos(a) * len)} ${r3(cy + Math.sin(a) * len)}" stroke="#a88e68" stroke-width="${r3(0.035 * size)}" fill="none" opacity="0.6"/>`;
  }
  // trunk: thick, fissured, with a hollow
  out += `<circle cx="${r3(cx)}" cy="${r3(cy)}" r="${r3(0.3 * size)}" fill="#5b4630" stroke="#1f150b" stroke-width="${r3(0.03 * size)}"/>`
    + [0.4, 1.5, 2.6, 3.7, 4.9].map(a => `<path d="M${r3(cx + Math.cos(a) * 0.08 * size)} ${r3(cy + Math.sin(a) * 0.08 * size)}L${r3(cx + Math.cos(a + 0.2) * 0.27 * size)} ${r3(cy + Math.sin(a + 0.2) * 0.27 * size)}" stroke="#2c1f12" stroke-width="${r3(0.022 * size)}"/>`).join("")
    + `<circle cx="${r3(cx)}" cy="${r3(cy)}" r="${r3(0.12 * size)}" fill="none" stroke="#3a2a18" stroke-width="${r3(0.015 * size)}"/>`;
  // the crown: a few heavy masses placed between the limbs, leaving gaps over the limbs and the trunk
  const masses = size === 2 ? 5 : 4, turn = rand() * Math.PI * 2;
  for (let m = 0; m < masses; m += 1) {
    const a = turn + (m / masses) * Math.PI * 2 + (rand() - 0.5) * 0.5, d = reach * (0.5 + rand() * 0.12);
    const mx = cx + Math.cos(a) * d, my = cy + Math.sin(a) * d, mr = reach * (0.36 + rand() * 0.08);
    out += `<path d="${clump(mx + mr * 0.1, my + mr * 0.14, mr, rand)}" fill="${pal.understory}" opacity="0.9"/>`;
    for (let i = 0, n = size === 2 ? 5 : 4; i < n; i += 1) {
      const ca = rand() * Math.PI * 2, cd = mr * rand() * 0.55, r = mr * (0.42 + rand() * 0.16);
      const x = mx + Math.cos(ca) * cd, y = my + Math.sin(ca) * cd;
      out += `<path d="${clump(x + r * 0.12, y + r * 0.16, r, rand)}" fill="${pal.under}" opacity="0.75"/>`
        + `<path d="${clump(x, y, r * 0.94, rand)}" fill="url(#tt-tree-ancient)" stroke="${pal.rim}" stroke-width="0.012"/>`
        + `<path d="${clump(x - r * 0.2, y - r * 0.24, r * 0.5, rand)}" fill="${pal.glow}"/>`;
      for (let k = 0; k < 10; k += 1) {
        const lit = k < 6, la = lit ? -2.4 + rand() * 1.8 : 0.3 + rand() * 1.8, ld = r * (0.2 + rand() * 0.65);
        const lx = r3(x + Math.cos(la) * ld), ly = r3(y + Math.sin(la) * ld);
        out += `<ellipse cx="${lx}" cy="${ly}" rx="${r3(r * 0.09)}" ry="${r3(r * 0.05)}" transform="rotate(${Math.round(rand() * 180)} ${lx} ${ly})" fill="${lit ? (k % 2 ? "rgba(196,206,140,0.5)" : "rgba(160,180,120,0.5)") : pal.dark}"/>`;
      }
    }
  }
  // hanging moss
  for (let i = 0; i < 9 * size; i += 1) {
    const a = rand() * Math.PI * 2, d = reach * (0.35 + rand() * 0.55), x = r3(cx + Math.cos(a) * d), y = r3(cy + Math.sin(a) * d);
    out += `<path d="M${x} ${y}q${r3(0.04 * size)} ${r3(0.12 * size)} 0 ${r3(0.24 * size)}" stroke="#b0ba86" stroke-width="${r3(0.03 * size)}" fill="none" opacity="0.65"/>`;
  }
  return out;
}

// The gradients every tree on the board shares: put once in the trees layer.
export function treeDefs() {
  const grad = (id, [a, b, c]) => `<radialGradient id="${id}" cx="0.34" cy="0.3" r="0.8"><stop offset="0" stop-color="${a}"/><stop offset="0.5" stop-color="${b}"/><stop offset="1" stop-color="${c}"/></radialGradient>`;
  return `<defs>${Object.entries(CROWNS).map(([look, pal]) => grad(`tt-tree-${look}`, pal.stops)).join("")}`
    + `<radialGradient id="tt-tree-shadow"><stop offset="0.5" stop-color="#000" stop-opacity="0.45"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient></defs>`;
}

// One tree's markup, in board units.
export function treeMarkup(tree) {
  const look = treeLook(tree);
  const body = look === "willow" ? willow(tree) : look === "pine" || look === "snowy_pine" ? pine(tree, look === "snowy_pine")
    : look === "dead" ? dead(tree) : look === "ancient" ? ancientTree(tree) : look === "bamboo_stand" || look === "golden_bamboo" ? bamboo(tree, look === "golden_bamboo") : crown(tree, look);
  return `<g class="tt-tree" data-tree-look="${look}">${body}</g>`;
}

// ---------------------------------------------------------------- one layer for many trees (review fix 1)
// Each kind of tree is drawn once per size and variant and reused: a map's trees become a handful of shared drawings
// placed with <use>, not one full drawing per tree. A tree's seed picks one of TREE_VARIANTS variants of its kind.
// MAPART2 (owner QA, emerald-canopy): at 3, a stand of any size cycles the same three silhouettes fast enough that
// "even with size variation the repetition is noticeable at a glance" (realm-maple-shrine's 210-tree border is the
// extreme case). Raised to the same order as terrain-art.js's own ART_VARIANTS bank (48, after the owner's own
// playtest found even 12 "too few once the shapes themselves also moved").
export const TREE_VARIANTS = 8;
const shapes = new Map();
const variantOf = tree => (Math.abs(Number(tree.seed) || 1) % TREE_VARIANTS);
export const treeShapeId = tree => `tt-ts-${treeLook(tree)}-${tree.size === 2 ? 2 : 1}-${variantOf(tree)}`;
function treeShape(tree) {
  const id = treeShapeId(tree);
  if (!shapes.has(id)) {
    const size = tree.size === 2 ? 2 : 1;
    shapes.set(id, treeMarkup({x: 0, y: 0, size, seed: 1 + variantOf(tree) * 7919, look: treeLook(tree)}).replace('<g class="tt-tree"', `<g id="${id}" class="tt-tree"`));
  }
  return shapes.get(id);
}
// The whole tree layer: shared gradients, each distinct drawing once, then one <use> per tree at its square.
export function treeLayerMarkup(list) {
  const used = new Map();
  for (const tree of list) used.set(treeShapeId(tree), tree);
  return treeDefs() + `<defs>${[...used.values()].map(treeShape).join("")}</defs>`
    + list.map(tree => `<use href="#${treeShapeId(tree)}" x="${Number(tree.x) || 0}" y="${Number(tree.y) || 0}"/>`).join("");
}

// The same forest as sprites for scenery-raster.js: each shared drawing with the box it fills around its square.
export function treeScene(list) {
  const shapes = new Map();
  for (const tree of list) {
    const id = treeShapeId(tree);
    if (!shapes.has(id)) {
      const size = tree.size === 2 ? 2 : 1;
      shapes.set(id, {markup: treeDefs() + treeShape(tree).replace(` id="${id}"`, ""), box: [-3, -3, size + 6, size + 6]});
    }
  }
  return {shapes, placements: list.map(tree => ({id: treeShapeId(tree), x: Number(tree.x) || 0, y: Number(tree.y) || 0})),
          fallback: () => treeLayerMarkup(list)};
}
