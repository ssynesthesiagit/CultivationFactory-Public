// Zone materials (owner 2026-09-27): "procedural modifications to the floor depending on the
// effect".  Each material paints its own look over exactly a zone's squares: a per-pixel base
// (noise), vector detail (flames, cinders, bones, runes) and, for the lively ones, a few extra
// layers the stylesheet animates with transforms and opacity only (cheap: the GPU moves them,
// nothing is repainted per frame).
//
// Deterministic: the same zone (seeded from its id) always paints the same.  Painters draw on
// any 2D context and never touch the DOM or Math.random, so zones.test.mjs can run them in
// node against a recording context.  board.js owns the canvases and the layer elements.

import {makeCells, makeNoise, mulberry32} from "./textures.js";
import {bambooGroups, bambooCulms} from './scenery-sight.js?v=loslines3';

const TAU = Math.PI * 2;
const mix = (a, b, t) => a + (b - a) * t;
const smoothstep = (a, b, t) => { const u = Math.min(1, Math.max(0, (t - a) / (b - a))); return u * u * (3 - 2 * u); };
const ridge = (n, sharp) => Math.pow(1 - Math.abs(2 * n - 1), sharp);
const clamp = value => (value < 0 ? 0 : value > 255 ? 255 : value);

export function rgbOf(hex) {
  const text = String(hex || "#8f97a3").replace("#", "");
  const full = text.length === 3 ? text.split("").map(c => c + c).join("") : text.padEnd(6, "0");
  return [0, 2, 4].map(index => parseInt(full.slice(index, index + 2), 16) || 0);
}
export const rgba = ([r, g, b], a) => `rgba(${r | 0},${g | 0},${b | 0},${+a.toFixed(3)})`;

// ------------------------------------------------------------------ drawing helpers (square units)
function softDot(ctx, x, y, r, rgb, a) {
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, r);
  gradient.addColorStop(0, rgba(rgb, a));
  gradient.addColorStop(1, rgba(rgb, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(x - r, y - r, r * 2, r * 2);
}

function dot(ctx, x, y, r, style) {
  ctx.fillStyle = style;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, TAU);
  ctx.fill();
}

function polygon(ctx, points) {
  ctx.beginPath();
  points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
}

function strokeLine(ctx, points) {
  ctx.beginPath();
  points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.stroke();
}

// A lightning-style jagged line from a to b (midpoint displacement).
function jagged(rand, a, b, depth = 4, spread = 0.32) {
  if (depth === 0) return [a, b];
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const nx = -(b[1] - a[1]) / (length || 1), ny = (b[0] - a[0]) / (length || 1);
  const offset = (rand() - 0.5) * length * spread;
  const middle = [(a[0] + b[0]) / 2 + nx * offset, (a[1] + b[1]) / 2 + ny * offset];
  return [...jagged(rand, a, middle, depth - 1, spread).slice(0, -1), ...jagged(rand, middle, b, depth - 1, spread)];
}

// An irregular stone: n points around (x, y).
function chunk(rand, x, y, radius, sides = 6) {
  const turn = rand() * TAU;
  return Array.from({length: sides}, (_, index) => {
    const angle = turn + (index / sides) * TAU + (rand() - 0.5) * 0.6, r = radius * (0.65 + rand() * 0.45);
    return [x + Math.cos(angle) * r, y + Math.sin(angle) * r];
  });
}

// A crack in the ground from (x, y): a jagged run that holds its heading, tapers and now and
// then forks.  Pushes {points, width} onto out (a fork after its parent) for drawCracks.
function fissure(rand, x, y, angle, length, width, forks, out, forkChance = 0.1) {
  const points = [[x, y]], steps = Math.max(2, Math.round(length / 0.11)), forkAt = [];
  for (let step = 1; step <= steps; step += 1) {
    angle += (rand() - 0.5) * 0.3;
    const zig = angle + (rand() - 0.5) * 0.95;
    x += Math.cos(zig) * length / steps; y += Math.sin(zig) * length / steps;
    points.push([x, y]);
    if (forks > 0 && step < steps - 1 && rand() < forkChance) {
      const left = 1 - step / steps;
      forkAt.push([x, y, angle + (rand() < 0.5 ? -1 : 1) * (0.5 + rand() * 0.6), length * left * (0.35 + rand() * 0.4), width * (0.5 + left * 0.3)]);
    }
  }
  out.push({points, width});
  for (const [fx, fy, fa, fl, fw] of forkAt) fissure(rand, fx, fy, fa, fl, fw, forks - 1, out, forkChance);
  return out;
}

// Cracks drawn in passes (every lip under every gap): a soft dark bruise either side, a light
// lip on the far wall (the light comes from the top left, as the shadows do), the dark gap and
// its black core.  Each segment tapers towards the crack's tip.
function drawCracks(ctx, cracks, {bruise, lip, gap, core}) {
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const pass = (style, scale, shift = 0) => {
    ctx.strokeStyle = style;
    for (const {points, width} of cracks) for (let index = 1; index < points.length; index += 1) {
      const taper = 1 - (index / points.length) * 0.8, lineWidth = width * scale * taper, offset = width * shift * taper;
      ctx.lineWidth = Math.max(0.006, lineWidth);
      ctx.beginPath();
      ctx.moveTo(points[index - 1][0] + offset, points[index - 1][1] + offset * 1.3);
      ctx.lineTo(points[index][0] + offset, points[index][1] + offset * 1.3);
      ctx.stroke();
    }
  };
  pass(bruise, 2.8);
  pass(lip, 1.05, 0.42);
  pass(gap, 1);
  pass(core, 0.42);
}

// A loose stone with its shadow (rubble's look): tone is the lit face's brightness, tint the
// share of it each channel keeps (earthy browns rather than grey).
function rock(ctx, rand, x, y, r, tone, [tr, tg, tb] = [1, 0.94, 0.86]) {
  const points = chunk(rand, x, y, r, 5 + Math.floor(rand() * 3));
  ctx.save(); ctx.translate(r * 0.3, r * 0.42); polygon(ctx, points); ctx.fillStyle = "rgba(0,0,0,0.42)"; ctx.fill(); ctx.restore();
  polygon(ctx, points);
  const gradient = ctx.createLinearGradient(x - r, y - r, x + r, y + r);
  gradient.addColorStop(0, `rgb(${(tone + 34) * tr | 0},${(tone + 34) * tg | 0},${(tone + 34) * tb | 0})`);
  gradient.addColorStop(1, `rgb(${(tone - 50) * tr | 0},${(tone - 50) * tg | 0},${(tone - 50) * tb | 0})`);
  ctx.fillStyle = gradient;
  ctx.fill();
  ctx.strokeStyle = "rgba(24,18,14,0.5)";
  ctx.lineWidth = Math.min(0.012, r * 0.2);
  ctx.stroke();
}

// One tongue of flame standing at (x, y), leaning a little.  Drawn additively and fairly
// transparent, so where tongues overlap the fire blooms towards yellow-white on its own.
function tongue(ctx, rand, x, y, w, h) {
  const lean = (rand() - 0.5) * w * 1.8;
  const gradient = ctx.createLinearGradient(x, y, x + lean, y - h);
  gradient.addColorStop(0, "rgba(255,214,120,0.62)");
  gradient.addColorStop(0.3, "rgba(255,140,40,0.55)");
  gradient.addColorStop(0.7, "rgba(214,56,16,0.34)");
  gradient.addColorStop(1, "rgba(140,16,8,0)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.moveTo(x - w / 2, y);
  ctx.bezierCurveTo(x - w * 0.75, y - h * 0.45, x + lean - w * 0.2, y - h * 0.72, x + lean, y - h);
  ctx.bezierCurveTo(x + lean + w * 0.12, y - h * 0.62, x + w * 0.8, y - h * 0.38, x + w / 2, y);
  ctx.quadraticCurveTo(x, y + w * 0.4, x - w / 2, y);
  ctx.fill();
}

function glyph(ctx, rand, x, y, size) {
  // A made-up rune: a few strokes on a 3x3 lattice, so every formation reads as writing.
  const nodes = [];
  for (let gy = 0; gy < 3; gy += 1) for (let gx = 0; gx < 3; gx += 1) nodes.push([x + (gx - 1) * size * 0.45, y + (gy - 1) * size * 0.5]);
  const strokes = 2 + Math.floor(rand() * 3);
  ctx.beginPath();
  for (let index = 0; index < strokes; index += 1) {
    const a = nodes[Math.floor(rand() * 9)], b = nodes[Math.floor(rand() * 9)];
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
  }
  ctx.stroke();
}

// ------------------------------------------------------------------ the kit a painter works with
// spec: {x0, y0, w, h, ppc, seed, cells: [[x, y]], center: {x, y}, radius, color: [r, g, b]}.
// x0/y0/w/h are the painted rectangle in squares; ppc is canvas pixels per square.
function makeKit(spec, salt = 0) {
  const seed = (spec.seed + salt * 7919) >>> 0;
  const kit = {...spec, seed, rand: mulberry32(seed), noise: makeNoise(seed), fine: makeNoise(seed + 17)};
  kit.cellsAt = spacing => {
    const cells = makeCells(seed, spacing, spec.w + 2, spec.h + 2);
    return (x, y) => cells(x - spec.x0 + 1, y - spec.y0 + 1);
  };
  kit.cx = (spec.center?.x ?? spec.x0 + spec.w / 2 - 0.5) + 0.5;
  kit.cy = (spec.center?.y ?? spec.y0 + spec.h / 2 - 0.5) + 0.5;
  kit.reach = spec.radius > 0 ? spec.radius + 0.5 : Math.max(spec.w, spec.h) / 2 - 1;
  return kit;
}

function paintPixels(ctx, spec, base) {
  const width = Math.round(spec.w * spec.ppc), height = Math.round(spec.h * spec.ppc);
  const image = ctx.createImageData(width, height);
  const data = image.data;
  for (let py = 0; py < height; py += 1) {
    const y = spec.y0 + (py + 0.5) / spec.ppc;
    for (let px = 0; px < width; px += 1) {
      const [r, g, b, a] = base(spec.x0 + (px + 0.5) / spec.ppc, y);
      const index = (py * width + px) * 4;
      data[index] = clamp(r); data[index + 1] = clamp(g); data[index + 2] = clamp(b); data[index + 3] = clamp(a);
    }
  }
  ctx.putImageData(image, 0, 0);
}

const inSquares = (ctx, spec) => ctx.setTransform(spec.ppc, 0, 0, spec.ppc, -spec.x0 * spec.ppc, -spec.y0 * spec.ppc);

// ------------------------------------------------------------------ materials
// base(kit) -> (x, y) -> [r, g, b, a];  detail(ctx, kit) draws in square units.
// layers: extra animated layers (see LAYER_PAINTERS / TILE_PAINTERS and tabletop.css).
const M = {};

M.ash = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.7, y * 0.7), f = fine(x * 7, y * 7, 3), speck = fine(x * 16 + 5, y * 16, 2);
    const v = 122 + (n - 0.5) * 60 + (f - 0.5) * 40, soot = 1 - smoothstep(0.62, 0.76, speck) * 0.42;
    return [v * soot, v * soot * 0.97, v * soot * 0.93, 140 + smoothstep(0.3, 0.7, n) * 100];
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) {
      for (let i = 0; i < 3; i += 1) softDot(ctx, cx + rand(), cy + rand(), 0.12 + rand() * 0.25, [26, 24, 24], 0.4);
      for (let i = 0; i < 14; i += 1) dot(ctx, cx + rand(), cy + rand(), 0.008 + rand() * 0.018, `rgba(${200 + rand() * 40 | 0},${196 + rand() * 40 | 0},${190 + rand() * 40 | 0},0.7)`);
      if (rand() < 0.7) { ctx.globalCompositeOperation = "lighter"; softDot(ctx, cx + rand(), cy + rand(), 0.07, [255, 120, 40], 0.9); ctx.globalCompositeOperation = "source-over"; }
    }
  },
  layers: [{tile: "flakes", cells: 3, anim: "drift", dx: 1, dy: 1, duration: 26, opacity: 0.9}],
};

M.fire = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.8, y * 0.8), f = fine(x * 6, y * 6, 3);
    const glow = Math.max(ridge(noise(x * 1.1 + 13, y * 1.1, 3), 4) * 0.9, smoothstep(0.5, 0.75, n) * 0.7);
    const char = 30 + (f - 0.5) * 26;
    return [mix(char * 1.3, 240, glow), mix(char * 0.7, 96, glow), mix(char * 0.55, 24, glow), 240];
  },
  detail(ctx, {cells, rand}) {
    ctx.globalCompositeOperation = "lighter";
    for (const [cx, cy] of cells) softDot(ctx, cx + 0.5 + (rand() - 0.5) * 0.4, cy + 0.5 + (rand() - 0.5) * 0.4, 0.75, [210, 70, 10], 0.38);
    for (const [cx, cy] of cells) for (let i = 0; i < 4; i += 1) softDot(ctx, cx + rand(), cy + rand(), 0.035, [255, 190, 90], 0.95);
    ctx.globalCompositeOperation = "source-over";
  },
  layers: [
    {canvas: "flames", variant: 1, anim: "flicker", duration: 1.3},
    {canvas: "flames", variant: 2, anim: "flicker", duration: 0.9, reverse: true},
    {tile: "embers", cells: 2, anim: "drift", dx: 0, dy: -1, duration: 5.5, blend: "screen"},
  ],
};

M.lava = {
  base: kit => {
    const plates = kit.cellsAt(0.95), {noise, fine} = kit;
    return (x, y) => {
      const {edge, id} = plates(x, y);
      const f = fine(x * 8, y * 8, 3);
      if (id < 0.14 || edge < 0.1) {  // molten seam or an open pool
        const t = id < 0.14 ? 0.55 + noise(x * 2.2, y * 2.2, 3) * 0.45 : 1 - edge / 0.1;
        return [mix(170, 255, t), mix(28, 60 + 170 * t * t, t), mix(8, 20 + 90 * t * t * t, t), 255];
      }
      const halo = edge < 0.22 ? (1 - (edge - 0.1) / 0.12) * 0.6 : 0;
      const crust = 30 + id * 22 + (f - 0.5) * 22 + (noise(x * 0.9, y * 0.9) - 0.5) * 16;
      return [crust + halo * 120, crust * 0.86 + halo * 26, crust * 0.8, 252];
    };
  },
  layers: [{canvas: "lavaGlow", anim: "pulse", duration: 3.2, lo: 0.3, hi: 1, blend: "screen"}],
};

M.ice = {
  base: kit => {
    const big = kit.cellsAt(1.4), small = kit.cellsAt(0.5), {noise, fine} = kit;
    return (x, y) => {
      const n = noise(x * 0.5, y * 0.5), f = fine(x * 9, y * 9, 2);
      let r = mix(206, 128, n), g = mix(230, 178, n), b = mix(244, 216, n);
      const sheen = Math.pow(Math.max(0, Math.sin((x + y) * 1.1 + n * 3)), 10) * 30;
      r += sheen + (f - 0.5) * 12; g += sheen + (f - 0.5) * 12; b += sheen + (f - 0.5) * 8;
      const e1 = big(x, y).edge, e2 = small(x, y).edge;
      if (e1 < 0.022) return [250, 254, 255, 245];
      if (e1 < 0.05) return [r * 0.8, g * 0.86, b * 0.93, 230];
      if (e2 < 0.012) return [mix(r, 248, 0.6), mix(g, 252, 0.6), 255, 230];
      return [r, g, b, 214];
    };
  },
  detail(ctx, {cells, rand}) {
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = 0.012;
    for (const [cx, cy] of cells) if (rand() < 0.6) {
      const x = cx + rand(), y = cy + rand(), s = 0.05 + rand() * 0.05;
      strokeLine(ctx, [[x - s, y], [x + s, y]]); strokeLine(ctx, [[x, y - s], [x, y + s]]);
    }
  },
};

M.frost = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.9, y * 0.9), f = fine(x * 6, y * 6, 3);
    return [226 + f * 20, 238 + f * 12, 250, 50 + smoothstep(0.25, 0.75, n) * 140 + (f - 0.5) * 50];
  },
  detail(ctx, {cells, rand}) {
    ctx.lineCap = "round";
    for (const [cx, cy] of cells) for (let i = 0; i < 2; i += 1) {
      // A fern of rime: a stem with paired side branches that shorten towards the tip.
      const x = cx + rand(), y = cy + rand(), angle = rand() * TAU, length = 0.25 + rand() * 0.25;
      ctx.strokeStyle = "rgba(250,254,255,0.9)";
      ctx.lineWidth = 0.022;
      const tip = [x + Math.cos(angle) * length, y + Math.sin(angle) * length];
      strokeLine(ctx, [[x, y], tip]);
      ctx.lineWidth = 0.014;
      for (let k = 1; k <= 4; k += 1) {
        const t = k / 5, bx = x + Math.cos(angle) * length * t, by = y + Math.sin(angle) * length * t, arm = length * 0.35 * (1 - t * 0.7);
        for (const side of [-1, 1]) strokeLine(ctx, [[bx, by], [bx + Math.cos(angle + side * 0.9) * arm, by + Math.sin(angle + side * 0.9) * arm]]);
      }
    }
  },
};

M.water = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.55, y * 0.55), f = fine(x * 5, y * 5, 2);
    const wave = Math.pow(Math.max(0, Math.sin((x * 0.8 + y * 1.9) * 3.4 + noise(x * 0.8, y * 0.8) * 9)), 14) * 46;
    return [mix(26, 56, n) + wave * 0.7 + (f - 0.5) * 10, mix(74, 126, n) + wave * 0.85 + (f - 0.5) * 12, mix(112, 156, n) + wave, 210];
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) if (rand() < 0.55) {
      const x = cx + rand(), y = cy + rand(), r = 0.1 + rand() * 0.12;
      for (let ring = 0; ring < 3; ring += 1) {
        ctx.strokeStyle = `rgba(220,240,255,${0.28 - ring * 0.08})`;
        ctx.lineWidth = 0.018;
        ctx.beginPath(); ctx.ellipse(x, y, r * (1 + ring * 0.7), r * (1 + ring * 0.7) * 0.62, 0, 0, TAU); ctx.stroke();
      }
    }
  },
  layers: [{tile: "caustics", cells: 3, anim: "drift", dx: 1, dy: 1, duration: 30, opacity: 0.55, blend: "screen"}],
};

M.mud = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.8, y * 0.8), m = noise(x * 2.1 + 4, y * 2.1, 3), f = fine(x * 12, y * 12, 2);
    const wet = smoothstep(0.45, 0.65, m), sheen = f > 0.8 ? 24 : 0;
    return [mix(98, 58, wet) + sheen + (f - 0.5) * 18, mix(70, 40, wet) + sheen * 0.9 + (f - 0.5) * 14, mix(42, 24, wet) + sheen * 0.7, 110 + smoothstep(0.25, 0.6, n) * 135];
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) if (rand() < 0.5) {
      const x = cx + 0.2 + rand() * 0.6, y = cy + 0.2 + rand() * 0.6, rx = 0.12 + rand() * 0.18, ry = rx * (0.5 + rand() * 0.3), turn = rand() * 3;
      ctx.fillStyle = "rgba(38,26,16,0.6)";
      ctx.beginPath(); ctx.ellipse(x, y, rx, ry, turn, 0, TAU); ctx.fill();
      ctx.strokeStyle = "rgba(255,240,220,0.2)";
      ctx.lineWidth = 0.02;
      ctx.beginPath(); ctx.ellipse(x, y, rx * 0.8, ry * 0.7, turn, 3.6, 4.8); ctx.stroke();
    }
  },
};

M.stone = {
  base: kit => {
    const slabs = kit.cellsAt(0.55), {noise, fine} = kit;
    return (x, y) => {
      const {edge, id} = slabs(x, y);
      const f = fine(x * 10, y * 10, 3), n = noise(x * 0.6, y * 0.6);
      if (edge < 0.035) return [36, 34, 32, 245];
      const bevel = Math.min(1, edge / 0.16);
      const v = 88 + id * 60 + (f - 0.5) * 26 + (n - 0.5) * 20 + bevel * 18;
      return [v * 1.02, v * 0.98, v * 0.93, 240];
    };
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) for (let i = 0; i < 2; i += 1) {
      const x = cx + rand(), y = cy + rand(), r = 0.03 + rand() * 0.04;
      dot(ctx, x + 0.015, y + 0.02, r, "rgba(0,0,0,0.35)");
      dot(ctx, x, y, r, `rgb(${120 + rand() * 50 | 0},${116 + rand() * 50 | 0},${110 + rand() * 50 | 0})`);
    }
  },
};

M.rubble = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.9, y * 0.9), f = fine(x * 14, y * 14, 2);
    return [118 + (f - 0.5) * 30, 108 + (f - 0.5) * 28, 96 + (f - 0.5) * 22, 70 + n * 90];
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) {
      const count = 5 + Math.floor(rand() * 4);
      for (let i = 0; i < count; i += 1) {
        const big = i === 0 && rand() < 0.5, r = big ? 0.2 + rand() * 0.1 : 0.06 + rand() * 0.11;
        const x = cx + 0.1 + rand() * 0.8, y = cy + 0.1 + rand() * 0.8, points = chunk(rand, x, y, r, 5 + Math.floor(rand() * 3));
        const tone = 92 + rand() * 60, warm = rand() * 14;
        ctx.save(); ctx.translate(0.03, 0.045); polygon(ctx, points); ctx.fillStyle = "rgba(0,0,0,0.45)"; ctx.fill(); ctx.restore();
        polygon(ctx, points);
        const gradient = ctx.createLinearGradient(x - r, y - r, x + r, y + r);
        gradient.addColorStop(0, `rgb(${tone + 40 + warm | 0},${tone + 36 | 0},${tone + 30 | 0})`);
        gradient.addColorStop(1, `rgb(${tone - 30 + warm | 0},${tone - 32 | 0},${tone - 36 | 0})`);
        ctx.fillStyle = gradient;
        ctx.fill();
        ctx.strokeStyle = "rgba(20,18,16,0.5)";
        ctx.lineWidth = 0.012;
        ctx.stroke();
      }
    }
  },
};

// Broken ground (Shatter Earth, Broken Ground, Grave Fracture): dry earth dried into plates,
// split by long forking rifts with a few upheaved slabs and grit along them.
M.cracked = {
  base: kit => {
    const plates = kit.cellsAt(0.6), {noise, fine} = kit;
    return (x, y) => {
      const wx = fine(x * 2.7, y * 2.7, 2) - 0.5, wy = fine(x * 2.7 + 31, y * 2.7 + 17, 2) - 0.5;
      const {edge, id} = plates(x + wx * 0.2, y + wy * 0.2);
      const n = noise(x * 0.55, y * 0.55, 3), grit = fine(x * 13 + 40, y * 13, 2);
      const gap = 1 - smoothstep(0.012, 0.05, edge);  // the hairline between two plates
      const lip = smoothstep(0.035, 0.06, edge) * (1 - smoothstep(0.06, 0.14, edge));  // plate edges curl up and dry paler
      const v = (0.82 + id * 0.24 + (n - 0.5) * 0.34 + (grit - 0.5) * 0.16 + lip * 0.1) * (1 - gap * 0.6);
      return [168 * v, 130 * v, 92 * v, 246];
    };
  },
  detail(ctx, kit) {
    const {cells, rand, cx, cy, reach} = kit;
    const rifts = [];
    // A few long rifts run out from the heart of the zone; wide zones get more of their own.
    const spokes = 3 + Math.floor(rand() * 2) + Math.round(reach * 0.3);
    for (let k = 0; k < spokes; k += 1) {
      const angle = (k / spokes) * TAU + (rand() - 0.5) * 0.9, length = (reach + 0.8) * (0.6 + rand() * 0.5);
      fissure(rand, cx + (rand() - 0.5) * 0.5, cy + (rand() - 0.5) * 0.5, angle, length, Math.min(0.17, 0.09 + reach * 0.012) + rand() * 0.03, 2, rifts, 0.08);
    }
    for (let k = Math.round(cells.length / 9); k > 0; k -= 1) {
      const [sx, sy] = cells[Math.floor(rand() * cells.length)];
      const x = sx + rand(), y = sy + rand(), angle = rand() * TAU, length = 0.6 + rand() * 1.0, width = 0.06 + rand() * 0.035;
      fissure(rand, x, y, angle, length, width, 1, rifts);
      fissure(rand, x, y, angle + Math.PI + (rand() - 0.5) * 0.6, length * (0.4 + rand() * 0.5), width, 1, rifts);
    }
    drawCracks(ctx, rifts, {bruise: "rgba(56,34,20,0.22)", lip: "rgba(238,208,164,0.6)", gap: "rgb(52,34,22)", core: "rgba(10,6,4,0.92)"});
    // Upheaved slabs beside the wider rifts, grit and pebbles all along them.
    for (const {points, width} of rifts) for (let index = 1; index < points.length - 1; index += 1) {
      const [x, y] = points[index], roll = rand();
      if (width > 0.08 && roll < 0.06) {
        const [nx, ny] = points[index + 1], length = Math.hypot(nx - x, ny - y) || 1, side = rand() < 0.5 ? -1 : 1;
        const r = 0.13 + rand() * 0.11, px = x - (ny - y) / length * side * r * 0.9, py = y + (nx - x) / length * side * r * 0.9;
        const slab = chunk(rand, px, py, r, 4 + Math.floor(rand() * 2));
        ctx.save(); ctx.translate(0.05, 0.07); polygon(ctx, slab); ctx.fillStyle = "rgba(20,10,4,0.55)"; ctx.fill(); ctx.restore();
        polygon(ctx, slab);
        const gradient = ctx.createLinearGradient(px - r, py - r, px + r, py + r);
        gradient.addColorStop(0, "rgb(214,178,132)"); gradient.addColorStop(1, "rgb(138,104,70)");
        ctx.fillStyle = gradient; ctx.fill();
        ctx.strokeStyle = "rgba(40,24,14,0.7)"; ctx.lineWidth = 0.014; ctx.stroke();
        ctx.strokeStyle = "rgba(250,226,186,0.5)"; ctx.lineWidth = 0.01;
        strokeLine(ctx, [slab[slab.length - 1], slab[0], slab[1]]);
      } else if (roll < 0.22) {
        for (let k = 1 + Math.floor(rand() * 3); k > 0; k -= 1) {
          rock(ctx, rand, x + (rand() - 0.5) * 0.4, y + (rand() - 0.5) * 0.4, 0.022 + rand() * 0.035, 150 + rand() * 50, [1, 0.8, 0.6]);
        }
      }
    }
  },
};

// An impact crater (Falling Star, Heaven-Weight Descent): a scorched bowl lit on its far wall,
// radial cracks smouldering at the heart, and a raised rim of ejecta thinning out beyond it.
M.crater = {
  base: ({noise, fine, cx, cy, reach}) => (x, y) => {
    const dx = x - cx, dy = y - cy, r = Math.sqrt(dx * dx + dy * dy) || 1e-6, ux = dx / r, uy = dy / r;
    const n = noise(x * 0.8, y * 0.8, 3), grit = fine(x * 12, y * 12, 2);
    const ray = noise(ux * 2.6 + 50, uy * 2.6 + 50, 2);  // varies with the angle only: streaks of ejecta
    const d = r / reach + (n - 0.5) * 0.1;  // a ragged rim
    // The slope (rising outward > 0): the bowl's wall steepening to the crest, the apron outside.
    const slope = smoothstep(0.28, 0.72, d) * (1 - smoothstep(0.74, 0.82, d)) * 1.2 - smoothstep(0.82, 0.88, d) * (1 - smoothstep(0.9, 1.12, d));
    const lit = slope * (ux + uy) * 0.7071;  // light from the top left: the far wall and the near apron are lit
    const scorch = 1 - smoothstep(0.12, 0.5, d);
    const crest = smoothstep(0.7, 0.82, d) * (1 - smoothstep(0.86, 1.02, d));
    const streak = smoothstep(0.5, 0.66, ray) * smoothstep(0.86, 0.96, d) * (1 - smoothstep(1.05, 1.4, d));
    const lumps = crest * (fine(x * 3.2, y * 3.2, 2) - 0.5) * 0.5;
    const tone = (0.66 + crest * 0.26 + lumps + streak * 0.26 + (n - 0.5) * 0.18 + (grit - 0.5) * 0.14) * (1 + lit * 0.6);
    const alpha = 250 * (1 - smoothstep(0.98, 1.35, d + (0.5 - ray) * 0.4));
    return [mix(160 * tone, 40, scorch * 0.8), mix(136 * tone, 32, scorch * 0.8), mix(106 * tone, 28, scorch * 0.8), alpha];
  },
  detail(ctx, kit) {
    const {rand, cx, cy, reach} = kit;
    const scale = Math.min(1.4, 0.7 + reach * 0.12);
    softDot(ctx, cx, cy, reach * 0.3, [10, 6, 4], 0.45);
    // Radial cracks from the point of impact, and a few broken rings in the wall.
    const cracks = [], spokes = 7 + Math.floor(rand() * 5);
    for (let k = 0; k < spokes; k += 1) {
      const angle = (k / spokes) * TAU + (rand() - 0.5) * 0.5;
      fissure(rand, cx + Math.cos(angle) * 0.08, cy + Math.sin(angle) * 0.08, angle, reach * (0.4 + rand() * 0.4), (0.06 + rand() * 0.03) * scale, 1, cracks, 0.06);
    }
    const heart = cracks.slice();
    for (let k = Math.round(reach * 1.2); k > 0; k -= 1) {
      const start = rand() * TAU, span = 0.3 + rand() * 0.5, ring = reach * (0.5 + rand() * 0.18), points = [];
      for (let t = 0; t <= 1.0001; t += 0.125) {
        const angle = start + span * t, wobble = ring * (1 + (rand() - 0.5) * 0.05);
        points.push([cx + Math.cos(angle) * wobble, cy + Math.sin(angle) * wobble]);
      }
      cracks.push({points, width: 0.035 * scale});
    }
    drawCracks(ctx, cracks, {bruise: "rgba(20,12,8,0.22)", lip: "rgba(214,190,160,0.4)", gap: "rgb(30,22,18)", core: "rgba(0,0,0,0.9)"});
    // Still smouldering where it struck.
    ctx.globalCompositeOperation = "lighter";
    softDot(ctx, cx, cy, Math.max(0.35, reach * 0.16), [255, 110, 30], 0.5);
    ctx.lineCap = "round";
    for (const {points, width} of heart) {
      const hot = Math.max(2, Math.round(points.length * 0.35));
      for (let index = 1; index < hot; index += 1) {
        ctx.strokeStyle = `rgba(255,${120 + (1 - index / hot) * 90 | 0},40,${0.75 * (1 - index / hot)})`;
        ctx.lineWidth = width * 0.5;
        strokeLine(ctx, [points[index - 1], points[index]]);
      }
    }
    ctx.globalCompositeOperation = "source-over";
    // Ejecta: heaped on the crest, thinning out beyond it; a few stones rolled into the bowl.
    for (let k = Math.round(TAU * reach * 7); k > 0; k -= 1) {
      const angle = rand() * TAU, d = 0.84 + (rand() + rand() - 1) * 0.12, r = (0.04 + rand() * rand() * 0.15) * scale;
      rock(ctx, rand, cx + Math.cos(angle) * reach * d, cy + Math.sin(angle) * reach * d, r, 120 + rand() * 60, [1, 0.86, 0.7]);
    }
    for (let k = Math.round(TAU * reach * 2.5); k > 0; k -= 1) {
      const angle = rand() * TAU, d = 0.95 + rand() * rand() * 0.45;
      rock(ctx, rand, cx + Math.cos(angle) * reach * d, cy + Math.sin(angle) * reach * d, 0.02 + rand() * 0.05, 116 + rand() * 50, [1, 0.86, 0.7]);
    }
    for (let k = Math.round(reach * 1.5); k > 0; k -= 1) {
      const angle = rand() * TAU, d = 0.25 + rand() * 0.4;
      rock(ctx, rand, cx + Math.cos(angle) * reach * d, cy + Math.sin(angle) * reach * d, 0.03 + rand() * 0.05, 76 + rand() * 30, [1, 0.9, 0.8]);
    }
  },
};

M.thorns = {
  base: ({noise}) => (x, y) => [54, 42, 30, 60 + noise(x * 0.8, y * 0.8) * 90],
  detail(ctx, {cells, rand}) {
    ctx.lineCap = "round";
    for (const [cx, cy] of cells) for (let i = 0; i < 4; i += 1) {
      const x = cx + rand(), y = cy + rand(), angle = rand() * TAU, length = 0.5 + rand() * 0.6, bend = (rand() - 0.5) * 0.9;
      const ex = x + Math.cos(angle) * length, ey = y + Math.sin(angle) * length;
      const mx = (x + ex) / 2 + Math.cos(angle + Math.PI / 2) * bend * length, my = (y + ey) / 2 + Math.sin(angle + Math.PI / 2) * bend * length;
      ctx.strokeStyle = "rgba(0,0,0,0.45)"; ctx.lineWidth = 0.09;
      ctx.beginPath(); ctx.moveTo(x + 0.025, y + 0.04); ctx.quadraticCurveTo(mx + 0.025, my + 0.04, ex + 0.025, ey + 0.04); ctx.stroke();
      ctx.strokeStyle = `rgb(${70 + rand() * 24 | 0},${58 + rand() * 20 | 0},${30})`; ctx.lineWidth = 0.055;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.quadraticCurveTo(mx, my, ex, ey); ctx.stroke();
      ctx.fillStyle = "rgb(168,146,100)";
      for (let k = 1; k < 8; k += 1) {
        const t = k / 8, px = (1 - t) * (1 - t) * x + 2 * (1 - t) * t * mx + t * t * ex, py = (1 - t) * (1 - t) * y + 2 * (1 - t) * t * my + t * t * ey;
        const dx = 2 * (1 - t) * (mx - x) + 2 * t * (ex - mx), dy = 2 * (1 - t) * (my - y) + 2 * t * (ey - my), d = Math.hypot(dx, dy) || 1;
        const side = k % 2 ? 1 : -1, nx = -dy / d * side, ny = dx / d * side;
        polygon(ctx, [[px - dx / d * 0.03, py - dy / d * 0.03], [px + dx / d * 0.03, py + dy / d * 0.03], [px + nx * 0.1 + dx / d * 0.045, py + ny * 0.1 + dy / d * 0.045]]);
        ctx.fill();
      }
    }
  },
};

M.vines = {
  base: ({noise, fine}) => (x, y) => [58 + fine(x * 8, y * 8) * 20, 92 + fine(x * 8, y * 8) * 26, 44, 50 + smoothstep(0.3, 0.7, noise(x * 0.7, y * 0.7)) * 110],
  detail(ctx, {cells, rand}) {
    ctx.lineCap = "round";
    for (const [cx, cy] of cells) for (let i = 0; i < 2; i += 1) {
      const x = cx + rand(), y = cy + rand(), angle = rand() * TAU, length = 0.6 + rand() * 0.6, bend = (rand() - 0.5) * 1.2;
      const ex = x + Math.cos(angle) * length, ey = y + Math.sin(angle) * length;
      const mx = (x + ex) / 2 + Math.cos(angle + Math.PI / 2) * bend * length * 0.5, my = (y + ey) / 2 + Math.sin(angle + Math.PI / 2) * bend * length * 0.5;
      ctx.strokeStyle = "rgb(62,104,40)"; ctx.lineWidth = 0.032;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.quadraticCurveTo(mx, my, ex, ey); ctx.stroke();
      for (let k = 1; k < 7; k += 1) {
        const t = k / 7, px = (1 - t) * (1 - t) * x + 2 * (1 - t) * t * mx + t * t * ex, py = (1 - t) * (1 - t) * y + 2 * (1 - t) * t * my + t * t * ey;
        const leafAngle = angle + (k % 2 ? 1 : -1) * (0.8 + rand() * 0.4);
        ctx.save(); ctx.translate(px, py); ctx.rotate(leafAngle);
        ctx.fillStyle = `rgb(${70 + rand() * 30 | 0},${128 + rand() * 40 | 0},${50 + rand() * 20 | 0})`;
        ctx.beginPath(); ctx.ellipse(0.06, 0, 0.065, 0.032, 0, 0, TAU); ctx.fill();
        ctx.strokeStyle = "rgba(200,240,160,0.35)"; ctx.lineWidth = 0.006;
        strokeLine(ctx, [[0, 0], [0.12, 0]]);
        ctx.restore();
      }
    }
  },
};

// A bamboo grove seen from above (owner 2026-09-29: "its not got any bamboo look about it"; rebuilt 2026-10-08: "culms
// seen from above as ringed green discs with leaf sprays, not starbursts"). Each stand is a tight cluster of upright
// culms -- green discs with a lit north-west rim, a pale node face and a dark hollow, each throwing a short south-east
// shadow -- under and around fans of long narrow leaves on short twigs. A darker understory of leaves sits beneath;
// lighter sprays reach outward on top, leaving the culm tops visible at the heart, so it reads as a thicket.
M.bamboo = {
  // Only the canopy's shade on the ground under it, mostly see-through, so the floor of the map shows between the culms
  // and a big stand has no box of its own colour around it (owner 2026-09-29: "there is a green box around it").
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.7, y * 0.7), f = fine(x * 7, y * 7, 3);
    return [18 + f * 10 + n * 8, 20 + f * 10 + n * 8, 10 + f * 6, 55 + n * 35];
  },
  detail(ctx, {cells, rand}) {
    // A leaf: narrow and pointed, with its shadow and a pale midrib. shade 0 is the dark understory, 1 the sunlit top.
    const leaf = (x, y, angle, length, width, shade, shadow = true) => {
      ctx.save(); ctx.translate(x, y); ctx.rotate(angle);
      if (shadow) {
        ctx.fillStyle = "rgba(0,0,0,0.2)";
        ctx.beginPath(); ctx.moveTo(0.015, 0.024);
        ctx.quadraticCurveTo(length * 0.35 + 0.015, -width + 0.024, length + 0.015, 0.024);
        ctx.quadraticCurveTo(length * 0.35 + 0.015, width + 0.024, 0.015, 0.024); ctx.fill();
      }
      ctx.fillStyle = `rgba(${46 + shade * 92 | 0},${92 + shade * 98 | 0},${28 + shade * 40 | 0},0.97)`;
      ctx.beginPath(); ctx.moveTo(0, 0);
      ctx.quadraticCurveTo(length * 0.35, -width, length, 0);
      ctx.quadraticCurveTo(length * 0.35, width, 0, 0); ctx.fill();
      ctx.strokeStyle = `rgba(222,240,170,${0.2 + shade * 0.3})`; ctx.lineWidth = 0.004;
      ctx.beginPath(); ctx.moveTo(0.01, 0); ctx.lineTo(length * 0.8, 0); ctx.stroke();
      ctx.restore();
    };
    // A spray: a short dark twig with four to seven leaves fanned from its tip like fingers, all leaning one way.
    const spray = (x, y, angle, scale, shade) => {
      const twig = 0.05 * scale, tx = x + Math.cos(angle) * twig, ty = y + Math.sin(angle) * twig;
      ctx.strokeStyle = "rgba(60,58,26,0.85)"; ctx.lineWidth = 0.008;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(tx, ty); ctx.stroke();
      const count = 4 + (rand() * 4 | 0), spread = 0.55 + rand() * 0.35;
      for (let k = 0; k < count; k += 1) {
        const a = angle + (k / (count - 1) - 0.5) * spread * 2 + (rand() - 0.5) * 0.15;
        leaf(tx, ty, a, (0.13 + rand() * 0.07) * scale, (0.019 + rand() * 0.007) * scale, Math.min(1, Math.max(0, shade + (rand() - 0.5) * 0.25)));
      }
    };
    // A culm seen end-on from above: shadow, green disc, lit rim, pale node face, dark hollow.
    const culm = (x, y, r) => {
      dot(ctx, x + r * 0.55, y + r * 0.75, r * 1.05, "rgba(0,0,0,0.38)");
      const g = rand();
      dot(ctx, x, y, r, `rgb(${62 + g * 36 | 0},${104 + g * 36 | 0},${36 + g * 14 | 0})`);
      ctx.strokeStyle = "rgba(24,38,12,0.95)"; ctx.lineWidth = r * 0.16;
      ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.stroke();
      ctx.strokeStyle = "rgba(214,236,150,0.85)"; ctx.lineWidth = r * 0.22;
      ctx.beginPath(); ctx.arc(x, y, r * 0.84, Math.PI * 0.95, Math.PI * 1.65); ctx.stroke();
      dot(ctx, x - r * 0.04, y - r * 0.04, r * 0.64, `rgb(${120 + g * 30 | 0},${156 + g * 24 | 0},${74 + g * 16 | 0})`);
      ctx.strokeStyle = "rgba(226,232,170,0.75)"; ctx.lineWidth = r * 0.1;
      ctx.beginPath(); ctx.arc(x - r * 0.04, y - r * 0.04, r * 0.64, 0, TAU); ctx.stroke();
      dot(ctx, x, y, r * 0.3, "rgba(30,38,14,0.92)");
    };
    // A stand of `size` squares a side (owner 2026-09-29: clumps painted together "combine ... into larger bamboo
    // trees"): more culms in a wider cluster, with longer sprays.
    const stand = (x0, y0, size) => {
      const reach = 0.44 * size, scale = 1.3 + 0.3 * (size - 1);
      softDot(ctx, x0 + 0.06 * size, y0 + 0.08 * size, reach * 1.2, [6, 10, 4], 0.42);
      // The understory: dark sprays all round, under everything.
      for (let i = 0, n = 10 + size * 8; i < n; i += 1) {
        const a = (i / n) * TAU + rand() * 0.5, d = reach * (0.3 + rand() * 0.55);
        spray(x0 + Math.cos(a) * d, y0 + Math.sin(a) * d, a + (rand() - 0.5) * 0.8, scale, 0.05 + rand() * 0.2);
      }
      // These are physical stems: their centres/radii also compile to LoS.
      // Randomness belongs to the leaves, never the blocking placement.
      const culms = bambooCulms(x0-size/2,y0-size/2,size).map(p=>[p.x/100,p.y/100,p.r/100]);
      culms.sort((p, q) => (p[0] + p[1]) - (q[0] + q[1]));
      for (const [x, y, r] of culms) culm(x, y, r);
      // The crown: lit sprays leaning outward from the outer culms, leaving the middle open.
      for (const [x, y] of culms) {
        const out = Math.atan2(y - y0, x - x0);
        if (rand() < 0.75) spray(x, y, out + (rand() - 0.5) * 1.2, scale, 0.45 + rand() * 0.45);
      }
      for (let i = 0, n = 8 + size * 6; i < n; i += 1) {
        const a = rand() * TAU, d = reach * (0.55 + rand() * 0.35);
        spray(x0 + Math.cos(a) * d, y0 + Math.sin(a) * d, a + (rand() - 0.5) * 0.9, scale, 0.35 + rand() * 0.5);
      }
    };
    // Squares painted together grow together: every whole 3x3 block, then every whole 2x2 block, is one stand;
    // the squares left over are a stand each.
    for (const {x,y,size} of bambooGroups(cells)) stand(x+size/2,y+size/2,size);
  },
};

M.poison = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.8, y * 0.8), f = fine(x * 8, y * 8, 3);
    const pool = smoothstep(0.4, 0.62, n);
    return [mix(96, 122, pool) + (f - 0.5) * 20, mix(122, 160, pool) + (f - 0.5) * 22, mix(40, 46, pool), 70 + pool * 140];
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) for (let i = 0; i < 3; i += 1) {
      const x = cx + rand(), y = cy + rand(), r = 0.03 + rand() * 0.06;
      dot(ctx, x, y, r, "rgba(170,220,70,0.35)");
      ctx.strokeStyle = "rgba(215,250,140,0.65)"; ctx.lineWidth = 0.01;
      ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.stroke();
      dot(ctx, x - r * 0.35, y - r * 0.35, r * 0.22, "rgba(255,255,230,0.8)");
    }
  },
  layers: [{tile: "haze", tint: [150, 200, 70], cells: 4, anim: "drift", dx: 1, dy: 0, duration: 34, opacity: 0.6}],
};

M.miasma = {
  base: ({noise}) => (x, y) => {
    const n = noise(x * 0.6, y * 0.6), swirl = ridge(noise(x * 1.2 + 7, y * 1.2, 3), 4);
    return [mix(70, 92, n) + swirl * 30, mix(58, 84, n) + swirl * 22, mix(84, 64, n) + swirl * 34, 130 + n * 90];
  },
  layers: [
    {tile: "haze", tint: [120, 112, 84], cells: 4, anim: "drift", dx: 1, dy: 0, duration: 36, opacity: 0.75},
    {tile: "haze", tint: [112, 76, 130], cells: 3, anim: "drift", dx: -1, dy: 1, duration: 48, opacity: 0.55, variant: 1},
  ],
};

M.lightning = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.7, y * 0.7), scorch = ridge(fine(x * 1.3, y * 1.3, 3), 8);
    return [28 + scorch * 60, 32 + scorch * 80, 48 + scorch * 120, 70 + n * 80 + scorch * 60];
  },
  detail(ctx, {cells, rand}) {
    ctx.globalCompositeOperation = "lighter";
    for (const [cx, cy] of cells) if (rand() < 0.5) softDot(ctx, cx + rand(), cy + rand(), 0.4, [60, 110, 255], 0.28);
    ctx.globalCompositeOperation = "source-over";
  },
  layers: [
    {canvas: "arcs", variant: 1, anim: "flash", duration: 2.7, blend: "screen"},
    {canvas: "arcs", variant: 2, anim: "flash", duration: 3.9, delay: 1.2, blend: "screen"},
  ],
};

M.darkness = {
  base: ({noise, fine}) => (x, y) => {
    const tendril = ridge(noise(x * 0.9, y * 0.9, 4), 6);
    return [6 + tendril * 26, 5 + tendril * 12, 12 + tendril * 36, 232 + (fine(x * 4, y * 4) - 0.5) * 20];
  },
  layers: [{tile: "haze", tint: [0, 0, 0], cells: 4, anim: "drift", dx: -1, dy: 1, duration: 44, opacity: 0.8}],
};

M.radiance = {
  blend: "screen",
  base: ({noise}) => (x, y) => {
    const n = noise(x * 0.6, y * 0.6);
    return [255, 214 + n * 30, 130 + n * 50, 40 + n * 60];
  },
  detail(ctx, kit) {
    const {cells, rand, cx, cy, reach} = kit;
    ctx.globalCompositeOperation = "lighter";
    softDot(ctx, cx, cy, reach + 0.6, [255, 200, 110], 0.45);
    ctx.strokeStyle = "rgba(255,236,180,0.16)";
    ctx.lineWidth = 0.05;
    for (let k = 0; k < 18; k += 1) {
      const angle = (k / 18) * TAU + rand() * 0.2;
      strokeLine(ctx, [[cx, cy], [cx + Math.cos(angle) * (reach + 1), cy + Math.sin(angle) * (reach + 1)]]);
    }
    for (const [x, y] of cells) for (let i = 0; i < 3; i += 1) softDot(ctx, x + rand(), y + rand(), 0.05, [255, 250, 220], 0.9);
    ctx.globalCompositeOperation = "source-over";
  },
  layers: [{tile: "motes", tint: [255, 226, 150], cells: 2, anim: "drift", dx: 0, dy: -1, duration: 11, blend: "screen"}],
};

M.smoke = {
  base: ({noise}) => (x, y) => {
    const n = noise(x * 0.5, y * 0.5);
    return [80 + n * 34, 80 + n * 34, 86 + n * 34, 120 + smoothstep(0.3, 0.7, n) * 100];
  },
  layers: [
    {tile: "clouds", tint: [138, 138, 144], cells: 4, anim: "drift", dx: 1, dy: 0, duration: 38, opacity: 1},
    {tile: "clouds", tint: [70, 70, 76], cells: 3, anim: "drift", dx: -1, dy: 1, duration: 52, opacity: 0.8, variant: 1},
  ],
};

M.fog = {
  base: ({noise}) => (x, y) => {
    const n = noise(x * 0.45, y * 0.45);
    return [206, 210, 216, 60 + smoothstep(0.25, 0.75, n) * 100];
  },
  layers: [
    {tile: "clouds", tint: [226, 230, 236], cells: 4, anim: "drift", dx: 1, dy: 0, duration: 46, opacity: 0.8},
    {tile: "clouds", tint: [200, 206, 214], cells: 3, anim: "drift", dx: -1, dy: 0, duration: 64, opacity: 0.55, variant: 1},
  ],
};

// Airborne dust is a warm cloud, rather than sand painted onto the floor.
M.dust = {
  base: ({noise}) => (x, y) => [206, 180, 134, 60 + smoothstep(0.25, 0.75, noise(x * 0.45, y * 0.45)) * 100],
  layers: [
    {tile: "clouds", tint: [220, 198, 158], cells: 4, anim: "drift", dx: 1, dy: 0, duration: 46, opacity: 0.8},
    {tile: "clouds", tint: [190, 164, 118], cells: 3, anim: "drift", dx: -1, dy: 0, duration: 64, opacity: 0.55, variant: 1},
  ],
};

M.wind = {
  base: ({noise}) => (x, y) => [226, 232, 238, 14 + noise(x * 0.6, y * 0.6) * 30],
  detail(ctx, {cells, rand}) {
    ctx.lineCap = "round";
    for (const [cx, cy] of cells) for (let i = 0; i < 2; i += 1) {
      const x = cx + rand(), y = cy + rand(), length = 0.4 + rand() * 0.5;
      ctx.strokeStyle = "rgba(240,246,250,0.35)"; ctx.lineWidth = 0.018;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.quadraticCurveTo(x + length / 2, y - 0.08, x + length, y + (rand() - 0.5) * 0.1); ctx.stroke();
      for (let k = 0; k < 3; k += 1) dot(ctx, cx + rand(), cy + rand(), 0.012, "rgba(200,190,170,0.6)");
    }
  },
  layers: [{tile: "streaks", cells: 2, anim: "drift", dx: 1, dy: 0, duration: 3.2, opacity: 0.85}],
};

M.blood = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.9, y * 0.9), f = fine(x * 10, y * 10, 2);
    const pool = smoothstep(0.38, 0.5, n), deep = smoothstep(0.5, 0.7, n);
    const gloss = f > 0.82 ? 40 * pool : 0;
    return [mix(120, 64, deep) + gloss, mix(12, 4, deep) + gloss * 0.5, mix(16, 8, deep) + gloss * 0.5, pool * 232];
  },
  detail(ctx, {cells, rand}) {
    for (const [cx, cy] of cells) for (let i = 0; i < 6; i += 1) {
      const x = cx + rand(), y = cy + rand(), r = 0.015 + rand() * 0.04;
      dot(ctx, x, y, r, "rgba(110,8,14,0.85)");
      if (rand() < 0.3) { const angle = rand() * TAU; dot(ctx, x + Math.cos(angle) * r * 2.4, y + Math.sin(angle) * r * 2.4, r * 0.45, "rgba(110,8,14,0.8)"); }
    }
  },
};

M.sand = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.5, y * 0.5), f = fine(x * 14, y * 14, 2);
    const phase = x * 4.6 + y * 1.6 + noise(x * 0.6, y * 0.6) * 10;
    const shade = Math.cos(phase) * 26 + Math.pow(Math.max(0, Math.sin(phase)), 10) * 26 + (f - 0.5) * 14 + (n - 0.5) * 22;
    return [206 + shade, 176 + shade * 0.9, 122 + shade * 0.72, 222 + n * 30];
  },
};

// Shattered, fused glass (Glass Desert Judgment): sand melted here and there into crazed
// sea-green sheets, strewn with pale translucent shards whose edges catch the light.  Not ice:
// warm sand shows between and through it, and the glass is green-grey, not blue.
M.glass = {
  base: kit => {
    const panes = kit.cellsAt(0.45), {noise, fine} = kit;
    return (x, y) => {
      const n = noise(x * 0.6, y * 0.6, 3), m = noise(x * 0.9 + 9, y * 0.9 - 4, 3), f = fine(x * 14, y * 14, 2);
      const sand = (f - 0.5) * 20 + (n - 0.5) * 24;
      let r = 214 + sand, g = 190 + sand * 0.9, b = 146 + sand * 0.7;
      const shore = smoothstep(0.5, 0.54, m) * (1 - smoothstep(0.54, 0.57, m));  // the scorched edge of the melt
      r -= shore * 70; g -= shore * 66; b -= shore * 56;
      const fused = smoothstep(0.54, 0.58, m);
      if (fused > 0) {
        const {edge} = panes(x, y);
        const depth = smoothstep(0.56, 0.72, m), sheen = Math.pow(Math.max(0, Math.sin((x - y) * 2.2 + m * 10)), 10) * 90;
        r = mix(r, mix(192, 136, depth) + sheen, fused); g = mix(g, mix(218, 178, depth) + sheen, fused); b = mix(b, mix(200, 162, depth) + sheen, fused);
        if (edge < 0.035) { const t = fused * (1 - edge / 0.035); r = mix(r, 255, t); g = mix(g, 255, t); b = mix(b, 250, t); }
        else if (edge < 0.07) { r -= 34 * fused; g -= 30 * fused; b -= 26 * fused; }
      }
      return [r, g, b, 240];
    };
  },
  detail(ctx, kit) {
    const {cells, rand} = kit;
    kit.glints = [];
    ctx.lineJoin = "miter";
    for (const [cx, cy] of cells) {
      for (let i = 2 + Math.floor(rand() * 3); i > 0; i -= 1) {
        // A shard: three or four sharp corners, drawn out along one axis.
        const x = cx + rand(), y = cy + rand(), turn = rand() * TAU, size = rand() < 0.2 ? 0.26 + rand() * 0.16 : 0.1 + rand() * 0.14;
        const sides = rand() < 0.55 ? 3 : 4, stretch = 0.35 + rand() * 0.3, c = Math.cos(turn), s = Math.sin(turn);
        const points = Array.from({length: sides}, (_, k) => {
          const angle = (k / sides) * TAU + (rand() - 0.5) * 1.1, r = size * (0.55 + rand() * 0.45);
          const u = Math.cos(angle) * r, v = Math.sin(angle) * r * stretch;
          return [x + c * u - s * v, y + s * u + c * v];
        });
        ctx.save(); ctx.translate(0.035, 0.05); polygon(ctx, points); ctx.fillStyle = "rgba(90,64,34,0.3)"; ctx.fill(); ctx.restore();
        polygon(ctx, points);
        const gradient = ctx.createLinearGradient(x - size, y - size, x + size, y + size);
        gradient.addColorStop(0, "rgba(255,255,255,0.9)"); gradient.addColorStop(0.5, "rgba(226,246,238,0.6)"); gradient.addColorStop(1, "rgba(150,200,188,0.72)");
        ctx.fillStyle = gradient; ctx.fill();
        // The edges facing the light flare white, the far ones are dark; a facet line runs down the shard.
        let lit = 0;
        points.forEach(([px, py], k) => { if (px + py < points[lit][0] + points[lit][1]) lit = k; });
        const before = points[(lit + sides - 1) % sides], after = points[(lit + 1) % sides];
        ctx.strokeStyle = "rgba(34,60,54,0.8)"; ctx.lineWidth = 0.014;
        strokeLine(ctx, Array.from({length: sides - 1}, (_, k) => points[(lit + 1 + k) % sides]));
        ctx.strokeStyle = "rgba(255,255,255,1)"; ctx.lineWidth = 0.022;
        strokeLine(ctx, [before, points[lit], after]);
        ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 0.01;
        strokeLine(ctx, [points[lit], points[(lit + 2) % sides]]);
        if (rand() < 0.35) kit.glints.push(points[lit]);
      }
      for (let i = 0; i < 3; i += 1) dot(ctx, cx + rand(), cy + rand(), 0.006 + rand() * 0.008, "rgba(255,255,255,0.9)");  // glitter
    }
    // A small four-pointed sparkle where a shard's point catches the light.
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = "rgba(255,255,245,0.7)"; ctx.lineWidth = 0.01;
    for (const [x, y] of kit.glints) {
      softDot(ctx, x, y, 0.05, [255, 255, 240], 0.6);
      strokeLine(ctx, [[x - 0.07, y], [x + 0.07, y]]); strokeLine(ctx, [[x, y - 0.07], [x, y + 0.07]]);
    }
    ctx.globalCompositeOperation = "source-over";
  },
  layers: [{canvas: "glints", anim: "pulse", duration: 2.2, lo: 0.1, hi: 1, blend: "screen"}],
};

// Pooled candle wax (Court of Ten Thousand Candles, Waxen City): smooth ivory pools, a second
// flow set on some of them, glossy rounded edges, spatter around them and a few guttering
// candle stubs standing in the pools whose flames flicker.
const WAX_POOL = 0.42;  // noise level where a pool begins (the base and the detail agree on it)
const waxHeight = m => smoothstep(WAX_POOL, WAX_POOL + 0.07, m) + smoothstep(0.56, 0.6, m) * 0.6;
// Wax gathers towards the middle of the zone, so even a small zone reads as wax, not floor.
const waxGather = ({cx, cy, reach}) => (x, y) => 0.12 * (1 - Math.min(1, Math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / (reach + 0.5)));
M.wax = {
  base: kit => {
    const {noise, fine} = kit, gather = waxGather(kit);
    return (x, y) => {
      // Pools are flat; only their rounded edges catch the light (sampled a step towards it).
      const lift = gather(x, y), m = noise(x * 0.55, y * 0.55, 3) + lift, up = noise(x * 0.55 - 0.05, y * 0.55 - 0.05, 3) + lift;
      const tint = fine(x * 0.35, y * 0.35, 2), gloss = smoothstep(0.66, 0.82, fine(x * 1.6, y * 1.6, 2));
      const cover = smoothstep(WAX_POOL, WAX_POOL + 0.015, m), thick = smoothstep(WAX_POOL + 0.02, 0.62, m);
      const slope = (waxHeight(m) - waxHeight(up)) * 2.6;
      const light = Math.max(0, slope) * 100 + gloss * thick * 16, shade = Math.max(0, -slope) * 40;
      const warm = mix(1, 0.93, smoothstep(0.35, 0.7, tint));
      const r = mix(220, 236, thick) + light - shade * 0.8;
      const g = mix(196, 224, thick) * warm + light - shade;
      const b = mix(150, 194, thick) * warm * warm + light * 0.9 - shade * 1.1;
      return [r, g, b, cover * 248];
    };
  },
  detail(ctx, kit) {
    const {cells, rand, noise} = kit, gather = waxGather(kit);
    const pool = (x, y) => noise(x * 0.55, y * 0.55, 3) + gather(x, y);
    // Spatter around the pools' edges: drops, and teardrops flung outward.
    for (const [cx, cy] of cells) for (let i = 0; i < 4; i += 1) {
      const x = cx + rand(), y = cy + rand(), m = pool(x, y), r = 0.028 + rand() * 0.04, turn = rand() * TAU, fling = rand() < 0.5;
      if (m < WAX_POOL - 0.07 || m > WAX_POOL + 0.015) continue;
      const tail = fling ? r * (1.6 + rand() * 1.6) : 0, tx = x + Math.cos(turn) * tail, ty = y + Math.sin(turn) * tail;
      const nx = -Math.sin(turn) * r, ny = Math.cos(turn) * r;
      const drop = () => {
        ctx.beginPath();
        if (!fling) { ctx.arc(x, y, r, 0, TAU); return; }
        ctx.moveTo(tx, ty);
        ctx.quadraticCurveTo(x + nx * 1.1 + (tx - x) * 0.3, y + ny * 1.1 + (ty - y) * 0.3, x + nx, y + ny);
        ctx.arc(x, y, r, turn + Math.PI / 2, turn - Math.PI / 2);
        ctx.quadraticCurveTo(x - nx * 1.1 + (tx - x) * 0.3, y - ny * 1.1 + (ty - y) * 0.3, tx, ty);
        ctx.closePath();
      };
      ctx.save(); ctx.translate(0.014, 0.02); drop(); ctx.fillStyle = "rgba(90,60,26,0.4)"; ctx.fill(); ctx.restore();
      drop(); ctx.fillStyle = "rgb(236,224,194)"; ctx.fill();
      dot(ctx, x - r * 0.35, y - r * 0.4, r * 0.35, "rgba(255,255,250,0.95)");
    }
    // Candle stubs guttered into the pools, each with a charred wick (the flames are a layer).
    kit.candles = [];
    const stubs = [];
    for (let k = Math.max(1, Math.round(cells.length / 6)); k > 0; k -= 1) {
      let x = 0, y = 0;
      for (let tries = 0; tries < 6; tries += 1) {
        const [sx, sy] = cells[Math.floor(rand() * cells.length)];
        x = sx + 0.2 + rand() * 0.6; y = sy + 0.25 + rand() * 0.6;
        if (pool(x, y) > WAX_POOL + 0.06) break;
      }
      for (let j = 0, size = rand() < 0.4 ? 2 + Math.floor(rand() * 2) : 1; j < size; j += 1) {  // now and then a cluster
        const turn = rand() * TAU, gap = j ? 0.24 + rand() * 0.12 : 0;
        stubs.push([x + Math.cos(turn) * gap, y + Math.sin(turn) * gap * 0.8, 0.12 + rand() * 0.07, 0.6 + rand() * 1.2]);
      }
    }
    stubs.sort((a, b) => a[1] - b[1]);  // the nearer (southern) stubs overlap the farther ones
    for (const [x, y, r, tall] of stubs) {
      const rise = r * tall;
      softDot(ctx, x + 0.05, y + 0.06, r * 2.8, [90, 56, 22], 0.35);
      ctx.fillStyle = "rgba(240,230,204,0.95)";  // its own puddle
      ctx.beginPath(); ctx.ellipse(x, y + r * 0.2, r * 1.8, r * 1.5, 0, 0, TAU); ctx.fill();
      const side = ctx.createLinearGradient(x - r, 0, x + r, 0);
      side.addColorStop(0, "rgb(238,226,196)"); side.addColorStop(0.55, "rgb(216,196,156)"); side.addColorStop(1, "rgb(160,134,96)");
      ctx.fillStyle = side;  // the stub's side, seen a little from the south
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI); ctx.lineTo(x - r, y - rise); ctx.arc(x, y - rise, r, Math.PI, 0, true); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "rgba(248,242,228,0.9)";  // a run of wax down the side
      ctx.beginPath(); ctx.ellipse(x - r * 0.45, y - rise * 0.4, r * 0.16, rise * 0.5 + r * 0.1, 0, 0, TAU); ctx.fill();
      const top = ctx.createRadialGradient(x, y - rise, 0, x, y - rise, r);
      top.addColorStop(0, "rgb(222,202,160)"); top.addColorStop(0.7, "rgb(242,232,208)"); top.addColorStop(1, "rgb(252,248,238)");
      dot(ctx, x, y - rise, r, top);
      ctx.strokeStyle = "rgba(120,96,62,0.6)"; ctx.lineWidth = 0.008;
      ctx.beginPath(); ctx.arc(x, y - rise, r, 0, TAU); ctx.stroke();
      ctx.strokeStyle = "rgb(36,26,20)"; ctx.lineWidth = 0.02; ctx.lineCap = "round";
      strokeLine(ctx, [[x, y - rise], [x + 0.014, y - rise - 0.04]]);
      kit.candles.push([x + 0.014, y - rise - 0.04]);
    }
    ctx.globalCompositeOperation = "lighter";
    for (const [x, y] of kit.candles) softDot(ctx, x, y, 0.6, [255, 140, 50], 0.22);
    ctx.globalCompositeOperation = "source-over";
    ctx.strokeStyle = "rgba(46,32,24,0.8)"; ctx.lineWidth = 0.014; ctx.lineCap = "round";  // wicks of candles that burnt away
    for (const [cx, cy] of cells) if (rand() < 0.15) {
      const x = cx + rand(), y = cy + rand(), angle = rand() * TAU;
      if (pool(x, y) < WAX_POOL + 0.04) continue;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.quadraticCurveTo(x + Math.cos(angle) * 0.04, y + Math.sin(angle) * 0.04, x + Math.cos(angle + 0.8) * 0.07, y + Math.sin(angle + 0.8) * 0.07); ctx.stroke();
    }
  },
  layers: [{canvas: "candles", anim: "flicker", duration: 1.4}],
};

M.grave = {
  base: ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.7, y * 0.7), f = fine(x * 12, y * 12, 2);
    return [mix(84, 146, n) + (f - 0.5) * 20, mix(76, 140, n) + (f - 0.5) * 18, mix(66, 124, n) + (f - 0.5) * 14, 170 + n * 50];
  },
  detail(ctx, {cells, rand}) {
    ctx.lineCap = "round";
    for (const [cx, cy] of cells) {
      const bones = 1 + Math.floor(rand() * 2);
      for (let i = 0; i < bones; i += 1) {
        const x = cx + 0.2 + rand() * 0.6, y = cy + 0.2 + rand() * 0.6, angle = rand() * TAU, half = 0.1 + rand() * 0.08;
        const ax = x - Math.cos(angle) * half, ay = y - Math.sin(angle) * half, bx = x + Math.cos(angle) * half, by = y + Math.sin(angle) * half;
        ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 0.05; strokeLine(ctx, [[ax + 0.015, ay + 0.02], [bx + 0.015, by + 0.02]]);
        ctx.strokeStyle = "rgb(226,218,196)"; ctx.lineWidth = 0.035; strokeLine(ctx, [[ax, ay], [bx, by]]);
        const nx = -Math.sin(angle) * 0.018, ny = Math.cos(angle) * 0.018;
        for (const [ex, ey] of [[ax, ay], [bx, by]]) { dot(ctx, ex + nx, ey + ny, 0.026, "rgb(232,224,202)"); dot(ctx, ex - nx, ey - ny, 0.026, "rgb(232,224,202)"); }
      }
      if (rand() < 0.12) {  // now and then a skull
        const x = cx + 0.3 + rand() * 0.4, y = cy + 0.3 + rand() * 0.4;
        dot(ctx, x + 0.02, y + 0.03, 0.09, "rgba(0,0,0,0.35)");
        dot(ctx, x, y, 0.09, "rgb(230,222,200)");
        dot(ctx, x - 0.032, y + 0.005, 0.022, "rgb(40,34,30)"); dot(ctx, x + 0.032, y + 0.005, 0.022, "rgb(40,34,30)");
      }
      for (let i = 0; i < 3; i += 1) dot(ctx, cx + rand(), cy + rand(), 0.015 + rand() * 0.02, "rgba(170,164,150,0.8)");
    }
  },
};

M.metal = {
  base: ({noise}) => (x, y) => { const n = noise(x * 0.7, y * 0.7); return [70 + n * 20, 76 + n * 20, 86 + n * 22, 70 + n * 80]; },
  detail(ctx, kit) {
    const {cells, rand} = kit;
    kit.glints = [];
    for (const [cx, cy] of cells) for (let i = 0; i < 4; i += 1) {
      const x = cx + rand(), y = cy + rand(), angle = rand() * TAU, length = 0.14 + rand() * 0.22, width = 0.03 + rand() * 0.04;
      const tip = [x + Math.cos(angle) * length, y + Math.sin(angle) * length];
      const nx = -Math.sin(angle) * width, ny = Math.cos(angle) * width;
      const points = [[x + nx, y + ny], tip, [x - nx, y - ny]];
      ctx.save(); ctx.translate(0.02, 0.03); polygon(ctx, points); ctx.fillStyle = "rgba(0,0,0,0.4)"; ctx.fill(); ctx.restore();
      polygon(ctx, points);
      const gradient = ctx.createLinearGradient(x + nx, y + ny, x - nx, y - ny);
      gradient.addColorStop(0, "rgb(222,230,240)"); gradient.addColorStop(0.5, "rgb(150,160,174)"); gradient.addColorStop(1, "rgb(78,86,98)");
      ctx.fillStyle = gradient; ctx.fill();
      ctx.strokeStyle = "rgba(20,24,30,0.6)"; ctx.lineWidth = 0.008; ctx.stroke();
      if (rand() < 0.35) kit.glints.push(tip);
    }
  },
  layers: [{canvas: "glints", anim: "pulse", duration: 1.9, lo: 0, hi: 1, blend: "screen"}],
};

M.glyphs = {
  base: ({noise, color}) => (x, y) => [color[0], color[1], color[2], 18 + noise(x * 0.6, y * 0.6) * 30],
  detail(ctx, kit) {
    const {cells, rand, color} = kit;
    ctx.strokeStyle = rgba(color, 0.5);
    ctx.lineWidth = 0.018;
    ctx.lineCap = "round";
    for (const [cx, cy] of cells) if (rand() < 0.45) glyph(ctx, rand, cx + 0.2 + rand() * 0.6, cy + 0.2 + rand() * 0.6, 0.14);
  },
  layers: [{canvas: "formation", anim: "spin", duration: 140}],
};

M.spirit = {
  base: ({noise}) => (x, y) => { const n = noise(x * 0.5, y * 0.5); return [150, 232, 222, 18 + smoothstep(0.3, 0.8, n) * 70]; },
  detail(ctx, {cells, rand}) {
    ctx.globalCompositeOperation = "lighter";
    for (const [cx, cy] of cells) if (rand() < 0.5) softDot(ctx, cx + rand(), cy + rand(), 0.3, [120, 230, 210], 0.2);
    ctx.globalCompositeOperation = "source-over";
  },
  layers: [
    {tile: "wisps", cells: 3, anim: "drift", dx: 0, dy: -1, duration: 16, blend: "screen"},
    {tile: "wisps", cells: 2, anim: "drift", dx: 1, dy: -1, duration: 24, opacity: 0.6, blend: "screen", variant: 1},
  ],
};

function prism(hueShift) {
  return ({noise, fine}) => (x, y) => {
    const n = noise(x * 0.5, y * 0.5), hue = ((x * 38 + y * 24 + n * 260 + hueShift) % 360 + 360) % 360;
    const [r, g, b] = hsl(hue, 0.62, 0.66);
    return [r, g, b, 60 + ridge(fine(x * 1.2, y * 1.2, 2), 3) * 90];
  };
}
function hsl(h, s, l) {
  const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0) * 255, f(8) * 255, f(4) * 255];
}
M.illusion = {
  base: prism(0),
  layers: [
    {canvas: "prism", anim: "pulse", duration: 4.6, lo: 0, hi: 1},
    {tile: "sparkles", cells: 2, anim: "drift", dx: 1, dy: -1, duration: 20, blend: "screen"},
  ],
};

M.stars = {
  base: ({noise, fine}) => (x, y) => {
    const nebula = smoothstep(0.45, 0.8, noise(x * 0.5, y * 0.5, 5)), tint = fine(x * 0.4, y * 0.4, 2);
    return [8 + nebula * mix(40, 20, tint), 10 + nebula * mix(20, 40, tint), 28 + nebula * 70, 236];
  },
  detail(ctx, kit) {
    const {cells, rand} = kit;
    kit.bright = [];
    for (const [cx, cy] of cells) {
      for (let i = 0; i < 9; i += 1) dot(ctx, cx + rand(), cy + rand(), 0.006 + rand() * 0.012, `rgba(${210 + rand() * 45 | 0},${220 + rand() * 35 | 0},255,${0.5 + rand() * 0.5})`);
      if (rand() < 0.45) kit.bright.push([cx + rand(), cy + rand(), 0.05 + rand() * 0.05]);
    }
    for (const [x, y, r] of kit.bright) softDot(ctx, x, y, r, [230, 236, 255], 0.5);
  },
  layers: [{canvas: "twinkle", anim: "pulse", duration: 2.3, lo: 0.15, hi: 1, blend: "screen"}],
};

M.sound = {
  base: () => () => [206, 200, 250, 16],
  detail(ctx, {cx, cy, reach, rand}) {
    const spacing = 0.5 + rand() * 0.12;  // each zone rings at its own pitch
    for (let r = 0.25 + rand() * 0.2, ring = 0; r < reach + 1; r += spacing, ring += 1) {
      ctx.strokeStyle = `rgba(214,206,255,${ring % 2 ? 0.14 : 0.32})`;
      ctx.lineWidth = ring % 2 ? 0.02 : 0.035;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, TAU); ctx.stroke();
    }
  },
  layers: [
    {canvas: "rings", anim: "ripple", duration: 2.8},
    {canvas: "rings", anim: "ripple", duration: 2.8, delay: 1.4},
  ],
};

M.web = {
  base: () => () => [210, 210, 204, 22],
  detail(ctx, {cells, rand}) {
    ctx.lineCap = "round";
    const anchors = Math.max(1, Math.round(cells.length / 7));
    for (let index = 0; index < anchors; index += 1) {
      const [ax, ay] = cells[Math.floor(rand() * cells.length)];
      const x = ax + 0.2 + rand() * 0.6, y = ay + 0.2 + rand() * 0.6, spokes = 8 + Math.floor(rand() * 4), reach = 1.1 + rand() * 0.9;
      const ends = Array.from({length: spokes}, (_, k) => {
        const angle = (k / spokes) * TAU + (rand() - 0.5) * 0.3, r = reach * (0.75 + rand() * 0.35);
        return [Math.cos(angle) * r, Math.sin(angle) * r];
      });
      ctx.strokeStyle = "rgba(240,240,232,0.6)"; ctx.lineWidth = 0.014;
      for (const [ex, ey] of ends) strokeLine(ctx, [[x, y], [x + ex, y + ey]]);
      ctx.lineWidth = 0.009;
      for (let t = 0.14; t < 1; t += 0.1 + rand() * 0.04) {
        ctx.beginPath();
        ends.forEach(([ex, ey], k) => {
          const px = x + ex * t, py = y + ey * t;
          if (!k) { ctx.moveTo(px, py); return; }
          const [qx, qy] = ends[k - 1];
          ctx.quadraticCurveTo(x + (ex + qx) * t * 0.42, y + (ey + qy) * t * 0.42, px, py);  // threads sag inward
        });
        const [fx, fy] = ends[0], [lx, ly] = ends[ends.length - 1];
        ctx.quadraticCurveTo(x + (fx + lx) * t * 0.42, y + (fy + ly) * t * 0.42, x + fx * t, y + fy * t);
        ctx.stroke();
      }
    }
    ctx.strokeStyle = "rgba(235,235,228,0.35)"; ctx.lineWidth = 0.01;
    for (const [cx, cy] of cells) if (rand() < 0.4) strokeLine(ctx, [[cx + rand(), cy + rand()], [cx + rand(), cy + rand()]]);
  },
};

M.generic = {
  base: ({noise, fine, color}) => (x, y) => {
    const n = noise(x * 0.6, y * 0.6), weave = Math.sin((x + y) * 9) * Math.sin((x - y) * 9);
    const lift = (fine(x * 5, y * 5, 2) - 0.5) * 30 + weave * 10;
    return [color[0] + lift, color[1] + lift, color[2] + lift, 80 + n * 70];
  },
};

// ------------------------------------------------------------------ walls (owner 2026-09-27)
// A wall is a zone painted in its material and then raised: what the material looks like built up
// into a barrier (masonry, a glacier's crest, force panes, a dune's ridge, a row of talismans), then a
// bevel lit from the top left like the rest of the table.  Painters draw in the wall's own frame: x runs
// along the wall and y across it (a wall running up and down is drawn with the axes swapped), from
// kit.wall {u0, u1, v0, v1} (its extent along and across) and kit.wall.cells / has(u, v).
const WALL = {
  stone(ctx, kit) {
    // Dressed blocks in courses, the joints staggered course to course.
    const {rand, wall} = kit, {u0, u1, v0, v1, at, span, has} = wall;
    const course = (v1 - v0) / Math.max(2, Math.round((v1 - v0) * 3)), block = 0.66;
    ctx.lineJoin = "round";
    for (let v = v0, row = 0; v < v1 - 0.01; v += course, row += 1) {
      for (let u = u0 - (row % 2 ? block / 2 : 0); u < u1; u += block) {
        const a = Math.max(u, u0), b = Math.min(u + block, u1);
        const [x, y] = at(a, v), [w, h] = span(b - a, course);
        if (!has(Math.floor(x + w / 2), Math.floor(y + h / 2))) continue;
        const tone = 0.5 + rand() * 0.5;
        ctx.fillStyle = `rgba(${150 * tone | 0},${142 * tone | 0},${128 * tone | 0},0.55)`;
        ctx.fillRect(x + 0.02, y + 0.02, w - 0.04, h - 0.04);
        ctx.strokeStyle = "rgba(255,248,230,0.3)"; ctx.lineWidth = 0.02;
        strokeLine(ctx, [[x + 0.03, y + h - 0.03], [x + 0.03, y + 0.03], [x + w - 0.03, y + 0.03]]);
        ctx.strokeStyle = "rgba(20,16,12,0.85)"; ctx.lineWidth = 0.035;
        ctx.strokeRect(x, y, w, h);
      }
    }
  },
  ice(ctx, kit) {
    // A glacier's jagged crest along the middle, its facets lit on the near side and blue in shadow beyond.
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall, mid = (v0 + v1) / 2, steps = Math.max(3, Math.round((u1 - u0) * 2.2));
    const crest = Array.from({length: steps + 1}, (_, k) => [u0 + (k / steps) * (u1 - u0), mid + (rand() - 0.5) * (v1 - v0) * 0.3]);
    for (let k = 0; k < steps; k += 1) {
      const [ua, va] = crest[k], [ub, vb] = crest[k + 1], foot = ua + (ub - ua) * (0.2 + rand() * 0.6);
      polygon(ctx, [at(ua, va), at(ub, vb), at(foot, v0)]);
      ctx.fillStyle = `rgba(236,248,255,${0.35 + rand() * 0.3})`; ctx.fill();
      polygon(ctx, [at(ua, va), at(ub, vb), at(foot, v1)]);
      ctx.fillStyle = `rgba(40,96,150,${0.3 + rand() * 0.25})`; ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 0.014;
      strokeLine(ctx, [at(foot, v0), at(ua, va)]);
    }
    ctx.strokeStyle = "rgba(255,255,255,0.95)"; ctx.lineWidth = 0.035;
    strokeLine(ctx, crest.map(([u, v]) => at(u, v)));
  },
  glass(ctx, kit) {
    // A force wall: clear green-grey panes, one a square, with bright seams and a streak of reflection.
    const {wall} = kit, {u0, u1, v0, v1, at} = wall;
    ctx.fillStyle = "rgba(170,214,204,0.6)";
    for (const [x, y] of wall.cells) ctx.fillRect(x, y, 1, 1);
    ctx.lineCap = "round";
    for (let u = u0; u < u1; u += 1) {
      polygon(ctx, [at(u + 0.18, v0), at(u + 0.42, v0), at(u + 0.3, v1), at(u + 0.06, v1)]);
      ctx.fillStyle = "rgba(255,255,255,0.28)"; ctx.fill();
      ctx.strokeStyle = "rgba(30,50,48,0.7)"; ctx.lineWidth = 0.05;
      strokeLine(ctx, [at(u, v0), at(u, v1)]);
      ctx.strokeStyle = "rgba(240,255,250,0.9)"; ctx.lineWidth = 0.02;
      strokeLine(ctx, [at(u + 0.03, v0), at(u + 0.03, v1)]);
    }
  },
  sand(ctx, kit) {
    // A dune: sunlit on the near slope, shaded beyond the ridge, rippled along its length.
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall, mid = v0 + (v1 - v0) * 0.45;
    const [ax, ay] = at(u0, v0), [bx, by] = at(u0, v1);
    const gradient = ctx.createLinearGradient(ax, ay, bx, by);
    gradient.addColorStop(0, "rgba(255,236,196,0.05)");
    gradient.addColorStop(0.4, "rgba(255,240,206,0.4)");
    gradient.addColorStop(0.47, "rgba(120,84,40,0.35)");
    gradient.addColorStop(1, "rgba(90,62,30,0.12)");
    ctx.fillStyle = gradient;
    for (const [x, y] of wall.cells) ctx.fillRect(x, y, 1, 1);
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(255,246,222,0.75)"; ctx.lineWidth = 0.03;
    const ridge = Array.from({length: Math.round((u1 - u0) * 4) + 1}, (_, k) => at(u0 + k / 4, mid + Math.sin(k * 0.9 + rand() * 0.4) * 0.05));
    strokeLine(ctx, ridge);
    ctx.lineWidth = 0.014;
    for (const v of [v0 + 0.12, v0 + 0.24, mid + 0.16, mid + 0.3]) {
      ctx.strokeStyle = v < mid ? "rgba(255,240,210,0.35)" : "rgba(90,60,28,0.3)";
      const phase = rand() * TAU;
      strokeLine(ctx, Array.from({length: Math.round((u1 - u0) * 6) + 1}, (_, k) => at(u0 + k / 6, v + Math.sin(k * 1.3 + phase) * 0.025)));
    }
  },
  lava(ctx, kit) {
    // A wall of molten stone: a glowing crest along the top, cooled black rims either side.
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall, mid = (v0 + v1) / 2;
    const crest = jagged(rand, [u0 + 0.1, mid], [u1 - 0.1, mid], 5, 0.12).map(([u, v]) => at(u, v));
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.globalCompositeOperation = "lighter";
    for (const [width, style] of [[0.3, "rgba(255,90,20,0.35)"], [0.1, "rgba(255,170,60,0.7)"], [0.035, "rgba(255,240,180,0.9)"]]) {
      ctx.strokeStyle = style; ctx.lineWidth = width;
      strokeLine(ctx, crest);
    }
    ctx.globalCompositeOperation = "source-over";
  },
  water(ctx, kit) {
    // A wall of rain and surging water: crests running along it, foam at its feet.
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall;
    ctx.lineCap = "round";
    for (let v = v0 + 0.15; v < v1 - 0.05; v += 0.22) {
      const phase = rand() * TAU;
      ctx.strokeStyle = "rgba(225,245,255,0.45)"; ctx.lineWidth = 0.02;
      strokeLine(ctx, Array.from({length: Math.round((u1 - u0) * 6) + 1}, (_, k) => at(u0 + k / 6, v + Math.sin(k * 1.1 + phase) * 0.04)));
    }
    for (const v of [v0 + 0.05, v1 - 0.05]) for (let u = u0; u < u1; u += 0.08) {
      const [x, y] = at(u + rand() * 0.06, v + (rand() - 0.5) * 0.06);
      dot(ctx, x, y, 0.02 + rand() * 0.025, "rgba(240,250,255,0.7)");
    }
  },
  wind(ctx, kit) {
    // A wall of wind: a pale roaring band of streaks and curls, dust caught in it.
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall;
    ctx.fillStyle = "rgba(214,228,238,0.3)";
    for (const [x, y] of wall.cells) ctx.fillRect(x, y, 1, 1);
    ctx.lineCap = "round";
    for (let k = 0; k < (u1 - u0) * (v1 - v0) * 5; k += 1) {
      const u = u0 + rand() * (u1 - u0), v = v0 + 0.1 + rand() * (v1 - v0 - 0.2), length = 0.3 + rand() * 0.5;
      ctx.strokeStyle = `rgba(248,252,255,${0.35 + rand() * 0.35})`; ctx.lineWidth = 0.015 + rand() * 0.015;
      const points = Array.from({length: 7}, (_, i) => at(u + (i / 6) * length, v + Math.sin(i * 0.9) * 0.04));
      if (rand() < 0.35) { const r = 0.06; for (let i = 0; i <= 8; i += 1) { const angle = i * 0.8; points.push(at(u + length + Math.sin(angle) * r * (1 - i / 10), v - r + Math.cos(angle) * r * (1 - i / 10))); } }
      strokeLine(ctx, points);
    }
    for (let k = 0; k < (u1 - u0) * 8; k += 1) { const [x, y] = at(u0 + rand() * (u1 - u0), v0 + rand() * (v1 - v0)); dot(ctx, x, y, 0.012, "rgba(190,176,150,0.7)"); }
  },
  glyphs(ctx, kit) {
    // A talisman wall: a warded line of light with paper talismans strung along it, red script on yellow.
    const {rand, wall} = kit, {u0, u1, v0, v1, at, span} = wall, mid = (v0 + v1) / 2;
    ctx.fillStyle = "rgba(240,200,110,0.18)";
    for (const [x, y] of wall.cells) ctx.fillRect(x, y, 1, 1);
    ctx.globalCompositeOperation = "lighter";
    ctx.lineCap = "round";
    for (const [width, style] of [[0.6, "rgba(255,190,80,0.14)"], [0.3, "rgba(255,200,100,0.22)"], [0.1, "rgba(255,226,150,0.5)"]]) {
      ctx.strokeStyle = style; ctx.lineWidth = width;
      strokeLine(ctx, [at(u0, mid), at(u1, mid)]);
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.strokeStyle = "rgba(120,30,20,0.9)"; ctx.lineWidth = 0.02;
    strokeLine(ctx, [at(u0, mid - 0.24), at(u1, mid - 0.24)]);
    for (let u = u0 + 0.25; u < u1; u += 0.5) {
      const [w, h] = span(0.24, 0.5), [x, y] = at(u - 0.12 + (rand() - 0.5) * 0.04, mid - 0.24);
      ctx.save();
      ctx.translate(x + w / 2, y);
      ctx.rotate((rand() - 0.5) * 0.14);
      ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fillRect(-w / 2 + 0.02, 0.03, w, h);
      ctx.fillStyle = `rgb(${236 + rand() * 14 | 0},${214 + rand() * 18 | 0},${130 + rand() * 30 | 0})`; ctx.fillRect(-w / 2, 0, w, h);
      ctx.strokeStyle = "rgba(150,40,24,0.85)"; ctx.lineWidth = 0.012; ctx.strokeRect(-w / 2 + 0.018, 0.018, w - 0.036, h - 0.036);
      ctx.strokeStyle = "rgba(176,26,18,0.95)"; ctx.lineWidth = 0.016;
      ctx.lineWidth = 0.02;
      glyph(ctx, rand, 0, h * 0.3, 0.1);
      glyph(ctx, rand, 0, h * 0.7, 0.1);
      ctx.restore();
    }
  },
  smoke(ctx, kit) {
    // A bank of smoke: heavy billows along it, spilling a little past its squares.
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall;
    for (let u = u0; u < u1; u += 0.35) for (let v = v0 + 0.25; v < v1; v += 0.5) {
      const [x, y] = at(u + rand() * 0.3, v + (rand() - 0.5) * 0.3);
      softDot(ctx, x, y, 0.35 + rand() * 0.25, rand() < 0.5 ? [150, 150, 156] : [60, 60, 66], 0.35);
    }
  },
  darkness(ctx, kit) {
    const {rand, wall} = kit, {u0, u1, v0, v1, at} = wall;
    for (let u = u0; u < u1; u += 0.4) { const [x, y] = at(u + rand() * 0.3, (v0 + v1) / 2 + (rand() - 0.5) * (v1 - v0) * 0.6); softDot(ctx, x, y, 0.45 + rand() * 0.3, [0, 0, 4], 0.5); }
  },
};

// How a wall stands up, lit from the top left like the rest of the table: a bright lip along its top
// and left edges, and its front (south) and east faces showing as darker bands inside its squares, so
// the squares it fills stay exact.  face: the front face's depth in squares.  Smoke and darkness, which
// only hide, get none and stay a cloud.
const RELIEF = {solid: {lit: 0.8, shade: 0.62, face: 0.3}, low: {lit: 0.6, shade: 0.45, face: 0.18}, screen: null};
const AIRY = new Set(["wind", "smoke", "fog", "darkness", "spirit", "radiance", "illusion", "sound"]);

function relief(ctx, cells, has, {lit, shade, face}) {
  const light = [255, 246, 222], side = face * 0.55;
  const band = (x, y, w, h, gx1, gy1, from, to) => {
    const gradient = ctx.createLinearGradient(x, y, gx1, gy1);
    gradient.addColorStop(0, rgba([0, 0, 0], from));
    gradient.addColorStop(1, rgba([0, 0, 0], to));
    ctx.fillStyle = gradient;
    ctx.fillRect(x, y, w, h);
  };
  const glow = (x, y, w, h, gx1, gy1) => {
    const gradient = ctx.createLinearGradient(x, y, gx1, gy1);
    gradient.addColorStop(0, rgba(light, lit * 0.45));
    gradient.addColorStop(1, rgba(light, 0));
    ctx.fillStyle = gradient;
    ctx.fillRect(x, y, w, h);
  };
  ctx.lineCap = "butt";
  for (const [x, y] of cells) {
    const top = !has(x, y - 1), left = !has(x - 1, y), bottom = !has(x, y + 1), right = !has(x + 1, y);
    const east = right ? side : 0, south = bottom ? face : 0;
    // The faces: the front one darkening towards the floor, the east one a little lighter.
    if (bottom) band(x, y + 1 - face, 1 - east, face, x, y + 1, shade * 0.55, shade);
    if (right) band(x + 1 - side, y, side, 1, x + 1, y, shade * 0.4, shade * 0.85);
    // The top: a soft sheen in from its lit edges, then the lip itself, and the lip where the top meets
    // the front face.
    if (top) glow(x, y, 1 - east, 0.16, x, y + 0.16);
    if (left) glow(x, y, 0.16, 1 - south, x + 0.16, y);
    ctx.strokeStyle = rgba(light, lit);
    ctx.lineWidth = 0.035;
    if (top) strokeLine(ctx, [[x, y + 0.07], [x + 1 - east, y + 0.07]]);
    if (left) strokeLine(ctx, [[x + 0.07, y], [x + 0.07, y + 1 - south]]);
    ctx.strokeStyle = rgba(light, lit * 0.6);
    ctx.lineWidth = 0.022;
    if (bottom) strokeLine(ctx, [[x, y + 1 - face], [x + 1 - east, y + 1 - face]]);
    if (right) strokeLine(ctx, [[x + 1 - side, y], [x + 1 - side, y + 1 - south]]);
  }
}

// Raise a zone painted with paintMaterial into a wall.  wall: zones.js wallRule(); axis: "x" or "y"
// (zones.js wallAxis).  Deterministic from the zone's seed, like the materials.
export function paintWall(ctx, material, spec, wall, axis = "x") {
  const kit = makeKit(spec, 53);
  const inside = new Set(spec.cells.map(([x, y]) => `${x},${y}`));
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of spec.cells) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); }
  const along = axis === "x";
  kit.wall = {
    kind: wall?.kind || "low", axis,
    cells: spec.cells.map(([x, y]) => (along ? [x, y] : [y, x])),
    has: (u, v) => inside.has(along ? `${u},${v}` : `${v},${u}`),
    u0: along ? minX : minY, u1: (along ? maxX : maxY) + 1, v0: along ? minY : minX, v1: (along ? maxY : maxX) + 1,
    at: (u, v) => [u, v],
    span: (du, dv) => [du, dv],
  };
  inSquares(ctx, spec);
  ctx.save();
  if (!along) ctx.transform(0, 1, 1, 0, 0, 0);  // the wall's frame: (u, v) -> (v, u) on the board
  WALL[material]?.(ctx, kit);
  ctx.restore();
  ctx.globalCompositeOperation = "source-over";
  const strength = RELIEF[kit.wall.kind];
  // Walls of air, cloud or light stand up only gently.
  const soft = AIRY.has(material) ? 0.5 : 1;
  if (strength) relief(ctx, spec.cells, (x, y) => inside.has(`${x},${y}`), {lit: strength.lit * soft, shade: strength.shade * soft, face: strength.face});
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = "source-over";
}

// ------------------------------------------------------------------ extra layers (zone-sized)
const LAYER_PAINTERS = {
  flames(ctx, {cells, rand}) {
    ctx.globalCompositeOperation = "lighter";
    for (const [cx, cy] of cells) {
      const count = 5 + Math.floor(rand() * 3);
      for (let i = 0; i < count; i += 1) tongue(ctx, rand, cx + rand(), cy + 0.15 + rand() * 0.95, 0.1 + rand() * 0.14, 0.22 + rand() * 0.42);
    }
  },
  lavaGlow(ctx, kit) {
    const plates = kit.cellsAt(0.95);
    // Same plates as the base (same seed), so the glow lands exactly on the seams.
    const width = Math.round(kit.w * kit.ppc), height = Math.round(kit.h * kit.ppc), image = ctx.createImageData(width, height);
    for (let py = 0; py < height; py += 1) for (let px = 0; px < width; px += 1) {
      const {edge, id} = plates(kit.x0 + (px + 0.5) / kit.ppc, kit.y0 + (py + 0.5) / kit.ppc);
      const t = id < 0.14 ? 0.7 : edge < 0.2 ? Math.pow(1 - edge / 0.2, 1.6) : 0;
      const index = (py * width + px) * 4;
      image.data[index] = 255; image.data[index + 1] = 150 + t * 80; image.data[index + 2] = 60; image.data[index + 3] = t * 210;
    }
    ctx.putImageData(image, 0, 0);
  },
  arcs(ctx, {cells, rand}) {
    ctx.globalCompositeOperation = "lighter";
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const count = Math.max(2, Math.round(cells.length / 6));
    for (let index = 0; index < count; index += 1) {
      const [ax, ay] = cells[Math.floor(rand() * cells.length)];
      const nearby = cells.filter(([x, y]) => Math.abs(x - ax) + Math.abs(y - ay) >= 2 && Math.abs(x - ax) + Math.abs(y - ay) <= 5);
      const [bx, by] = nearby.length ? nearby[Math.floor(rand() * nearby.length)] : [ax + 1, ay + 1];
      const main = jagged(rand, [ax + rand(), ay + rand()], [bx + rand(), by + rand()]);
      const fork = main[Math.floor(main.length / 2)];
      const branch = jagged(rand, fork, [fork[0] + (rand() - 0.5) * 1.6, fork[1] + (rand() - 0.5) * 1.6], 3);
      for (const [width, style] of [[0.2, "rgba(70,120,255,0.22)"], [0.08, "rgba(140,190,255,0.6)"], [0.028, "rgba(246,250,255,0.95)"]]) {
        ctx.strokeStyle = style; ctx.lineWidth = width;
        strokeLine(ctx, main);
        ctx.lineWidth = width * 0.6;
        strokeLine(ctx, branch);
      }
      softDot(ctx, main[0][0], main[0][1], 0.25, [180, 210, 255], 0.7);
      softDot(ctx, main[main.length - 1][0], main[main.length - 1][1], 0.25, [180, 210, 255], 0.7);
    }
  },
  glints(ctx, kit) {
    ctx.globalCompositeOperation = "lighter";
    for (const [x, y] of kit.glints || []) {
      softDot(ctx, x, y, 0.1, [255, 255, 255], 0.9);
      ctx.strokeStyle = "rgba(255,255,255,0.9)"; ctx.lineWidth = 0.01;
      strokeLine(ctx, [[x - 0.12, y], [x + 0.12, y]]); strokeLine(ctx, [[x, y - 0.12], [x, y + 0.12]]);
    }
  },
  candles(ctx, kit) {
    // Small flames on the stubs wax's detail placed (shared kit), with their glow.
    ctx.globalCompositeOperation = "lighter";
    for (const [x, y] of kit.candles || []) {
      softDot(ctx, x, y - 0.05, 0.3, [255, 170, 80], 0.4);
      tongue(ctx, kit.rand, x, y + 0.01, 0.055, 0.16);
      softDot(ctx, x, y - 0.03, 0.03, [255, 250, 220], 0.9);
    }
  },
  twinkle(ctx, kit) {
    ctx.globalCompositeOperation = "lighter";
    for (const [x, y, r] of kit.bright || []) {
      softDot(ctx, x, y, r * 2, [200, 215, 255], 0.8);
      ctx.strokeStyle = "rgba(235,240,255,0.85)"; ctx.lineWidth = 0.01;
      strokeLine(ctx, [[x - r * 3, y], [x + r * 3, y]]); strokeLine(ctx, [[x, y - r * 3], [x, y + r * 3]]);
    }
  },
  formation(ctx, kit) {
    // A cultivator's formation: rings, a band of runes and an eight-pointed star, centred on the zone.
    const {cx, cy, reach, rand, color, ppc} = kit;
    const glow = [Math.min(255, color[0] + 50), Math.min(255, color[1] + 50), Math.min(255, color[2] + 50)];
    ctx.globalCompositeOperation = "lighter";
    ctx.shadowColor = rgba(color, 0.9);
    ctx.shadowBlur = ppc * 0.12;
    ctx.strokeStyle = rgba(glow, 0.85);
    const outer = Math.max(0.8, reach - 0.15);
    for (const [r, width] of [[outer, 0.05], [outer - 0.12, 0.02], [outer * 0.62, 0.035], [outer * 0.55, 0.015], [outer * 0.2, 0.03]]) {
      ctx.lineWidth = width;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, TAU); ctx.stroke();
    }
    ctx.lineWidth = 0.022;
    const band = (outer - 0.06 + outer * 0.62) / 2, count = Math.max(8, Math.round(band * 7));
    for (let index = 0; index < count; index += 1) {
      const angle = (index / count) * TAU;
      ctx.save(); ctx.translate(cx + Math.cos(angle) * band, cy + Math.sin(angle) * band); ctx.rotate(angle + Math.PI / 2);
      glyph(ctx, rand, 0, 0, Math.min(0.24, band * 0.28));
      ctx.restore();
    }
    ctx.lineWidth = 0.03;
    const star = outer * 0.55;
    for (const turn of [0, Math.PI / 4]) {
      ctx.beginPath();
      for (let k = 0; k <= 4; k += 1) { const angle = turn + (k / 4) * TAU; ctx[k ? "lineTo" : "moveTo"](cx + Math.cos(angle) * star, cy + Math.sin(angle) * star); }
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
  },
  prism(ctx, kit) { paintPixels(ctx, kit, prism(150)(kit)); },
  rings(ctx, {cx, cy, reach, rand}) {
    for (let r = 0.2 + rand() * 0.2; r < reach + 1; r += 0.9) {
      ctx.strokeStyle = "rgba(230,224,255,0.55)"; ctx.lineWidth = 0.045;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, TAU); ctx.stroke();
    }
  },
};

// ------------------------------------------------------------------ drifting tiles (seamless)
// Value noise on a torus: u, v in [0, 1) wrap, so the tile repeats without a seam.
function torusNoise(seed, period) {
  const rand = mulberry32(seed);
  const octaves = [0, 1, 2, 3, 4].map(level => {
    const size = period << level, table = new Float32Array(size * size);
    for (let index = 0; index < table.length; index += 1) table[index] = rand();
    return {size, table};
  });
  const smooth = t => t * t * (3 - 2 * t);
  const sample = ({size, table}, u, v) => {
    const x = u * size, y = v * size, x0 = Math.floor(x), y0 = Math.floor(y), fx = smooth(x - x0), fy = smooth(y - y0);
    const at = (i, j) => table[(((j % size) + size) % size) * size + (((i % size) + size) % size)];
    const a = at(x0, y0), b = at(x0 + 1, y0), c = at(x0, y0 + 1), d = at(x0 + 1, y0 + 1);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  };
  return (u, v, count = 4) => {
    let sum = 0, amp = 0.5, norm = 0;
    for (let level = 0; level < count; level += 1) { sum += sample(octaves[level], u, v) * amp; norm += amp; amp *= 0.5; }
    return sum / norm;
  };
}

// Draw at (x, y) and at every wrapped copy that reaches into the tile.
function wrapped(size, x, y, reach, draw) {
  for (const ox of [-size, 0, size]) for (const oy of [-size, 0, size]) {
    const px = x + ox, py = y + oy;
    if (px + reach < 0 || py + reach < 0 || px - reach > size || py - reach > size) continue;
    draw(px, py);
  }
}

function cloudTile(ctx, size, seed, tint, {low, high, alpha, period = 3}) {
  const noise = torusNoise(seed, period), image = ctx.createImageData(size, size), step = 3 / size;
  for (let py = 0; py < size; py += 1) for (let px = 0; px < size; px += 1) {
    const u = px / size, v = py / size, n = noise(u, v, 5), cover = smoothstep(low, high, n);
    // Emboss: brighter where the noise rises towards the top-left light, darker on the far side.
    const slope = n - noise((u - step + 1) % 1, (v - step + 1) % 1, 4);
    const light = Math.max(0.55, Math.min(1.45, 0.9 + slope * 9 + (n - 0.5) * 0.4));
    const index = (py * size + px) * 4;
    image.data[index] = clamp(tint[0] * light + (tint[0] < 40 ? 0 : 6)); image.data[index + 1] = clamp(tint[1] * light); image.data[index + 2] = clamp(tint[2] * light);
    image.data[index + 3] = cover * alpha;
  }
  ctx.putImageData(image, 0, 0);
}

const TILE_PAINTERS = {
  clouds: (ctx, size, seed, tint) => cloudTile(ctx, size, seed, tint, {low: 0.38, high: 0.72, alpha: 200}),
  haze: (ctx, size, seed, tint) => cloudTile(ctx, size, seed, tint, {low: 0.3, high: 0.75, alpha: 170, period: 2}),
  heavy: (ctx, size, seed, tint) => cloudTile(ctx, size, seed, tint, {low: 0.2, high: 0.6, alpha: 245}),
  // Faint dark strands waving across a Darkness that grabs at whatever stands in it (owner 2026-10-03 03:38:
  // "dark tentacles you can barely see waving in the area"). Each strand is a tapering curve that fades as it
  // reaches out, drawn with wrapped() so a tiled area has no seam; board.js drifts two layers of these slowly.
  tentacles(ctx, size, seed, tint = [4, 4, 12]) {
    const rand = mulberry32(seed);
    ctx.lineCap = "round";
    for (let index = 0; index < 7; index += 1) {
      const x = rand() * size, y = rand() * size, length = size * (0.26 + rand() * 0.4);
      const sway = size * (0.04 + rand() * 0.08), phase = rand() * 6.283;
      const width = size * (0.009 + rand() * 0.013), strength = 0.24 + rand() * 0.3;
      wrapped(size, x, y, length + width * 6, (px, py) => {
        const at = t => [px + length * t, py + Math.sin(phase + t * 4.1) * sway * t];
        for (let step = 0; step < 8; step += 1) {
          const t = step / 8;
          ctx.strokeStyle = `rgba(${tint[0]}, ${tint[1]}, ${tint[2]}, ${(strength * (1 - t)).toFixed(3)})`;
          ctx.lineWidth = width * (1.7 - t);
          strokeLine(ctx, [at(t), at(t + 1 / 8)]);
        }
        softDot(ctx, px, py, width * 3.4, tint, strength * 0.45);
      });
    }
    ctx.lineCap = "butt";
  },
  caustics(ctx, size, seed) {
    const a = torusNoise(seed, 3), b = torusNoise(seed + 1, 4), image = ctx.createImageData(size, size);
    for (let py = 0; py < size; py += 1) for (let px = 0; px < size; px += 1) {
      const u = px / size, v = py / size, line = Math.max(ridge(a(u, v, 3), 12), ridge(b(u, v, 3), 16) * 0.8);
      const index = (py * size + px) * 4;
      image.data[index] = 190; image.data[index + 1] = 235; image.data[index + 2] = 255; image.data[index + 3] = line * 200;
    }
    ctx.putImageData(image, 0, 0);
  },
  embers(ctx, size, seed) {
    const rand = mulberry32(seed);
    ctx.globalCompositeOperation = "lighter";
    for (let index = 0; index < 26; index += 1) {
      const x = rand() * size, y = rand() * size, r = size * (0.006 + rand() * 0.012), trail = size * (0.02 + rand() * 0.05);
      wrapped(size, x, y, trail + r * 4, (px, py) => {
        const gradient = ctx.createLinearGradient(px, py, px, py + trail);
        gradient.addColorStop(0, "rgba(255,210,120,0.95)"); gradient.addColorStop(1, "rgba(255,90,20,0)");
        ctx.strokeStyle = gradient; ctx.lineWidth = r * 1.4;
        strokeLine(ctx, [[px, py], [px + (rand() - 0.5) * r * 3, py + trail]]);
        softDot(ctx, px, py, r * 3.5, [255, 150, 50], 0.6);
      });
    }
  },
  flakes(ctx, size, seed) {
    const rand = mulberry32(seed);
    for (let index = 0; index < 60; index += 1) {
      const x = rand() * size, y = rand() * size, r = size * (0.003 + rand() * 0.007), ember = rand() < 0.12;
      wrapped(size, x, y, r * 4, (px, py) => {
        if (ember) { ctx.globalCompositeOperation = "lighter"; softDot(ctx, px, py, r * 3, [255, 130, 50], 0.9); ctx.globalCompositeOperation = "source-over"; }
        else dot(ctx, px, py, r, `rgba(${190 + rand() * 50 | 0},${186 + rand() * 50 | 0},${180 + rand() * 50 | 0},${0.45 + rand() * 0.4})`);
      });
    }
  },
  wisps(ctx, size, seed) {
    const rand = mulberry32(seed);
    for (let index = 0; index < 9; index += 1) {
      const x = rand() * size, y = rand() * size, length = size * (0.12 + rand() * 0.14), width = size * (0.03 + rand() * 0.03);
      wrapped(size, x, y, length, (px, py) => {
        ctx.save(); ctx.translate(px, py); ctx.scale(width / length, 1);
        const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, length);
        gradient.addColorStop(0, "rgba(200,255,245,0.55)"); gradient.addColorStop(0.5, "rgba(120,230,210,0.22)"); gradient.addColorStop(1, "rgba(80,200,190,0)");
        ctx.fillStyle = gradient; ctx.fillRect(-length, -length, length * 2, length * 2);
        ctx.restore();
        softDot(ctx, px, py - length * 0.5, size * 0.012, [230, 255, 250], 0.9);
      });
    }
  },
  motes(ctx, size, seed, tint) {
    const rand = mulberry32(seed);
    for (let index = 0; index < 22; index += 1) {
      const x = rand() * size, y = rand() * size, r = size * (0.008 + rand() * 0.016);
      wrapped(size, x, y, r * 3, (px, py) => softDot(ctx, px, py, r * 3, tint, 0.85));
    }
  },
  sparkles(ctx, size, seed) {
    const rand = mulberry32(seed);
    ctx.lineWidth = Math.max(1, size * 0.006);
    for (let index = 0; index < 14; index += 1) {
      const x = rand() * size, y = rand() * size, r = size * (0.02 + rand() * 0.025), color = hsl(rand() * 360, 0.9, 0.78);
      wrapped(size, x, y, r, (px, py) => {
        ctx.strokeStyle = rgba(color, 0.9);
        strokeLine(ctx, [[px - r, py], [px + r, py]]); strokeLine(ctx, [[px, py - r], [px, py + r]]);
        softDot(ctx, px, py, r * 0.6, color, 0.7);
      });
    }
  },
  streaks(ctx, size, seed) {
    const rand = mulberry32(seed);
    ctx.lineCap = "round";
    for (let index = 0; index < 12; index += 1) {
      const x = rand() * size, y = rand() * size, length = size * (0.18 + rand() * 0.3);
      wrapped(size, x, y, length, (px, py) => {
        const gradient = ctx.createLinearGradient(px, py, px + length, py);
        gradient.addColorStop(0, "rgba(255,255,255,0)"); gradient.addColorStop(0.6, "rgba(245,250,255,0.6)"); gradient.addColorStop(1, "rgba(255,255,255,0)");
        ctx.strokeStyle = gradient; ctx.lineWidth = Math.max(1, size * (0.006 + rand() * 0.008));
        ctx.beginPath(); ctx.moveTo(px, py); ctx.quadraticCurveTo(px + length / 2, py - size * 0.02, px + length, py + (rand() - 0.5) * size * 0.03); ctx.stroke();
      });
    }
  },
};

// ------------------------------------------------------------------ public painting API
export const materialLayers = material => (M[material] || M.generic).layers || [];

// Shared-board light obscurement: natural painted smoke/fog stays visible over
// patterned floors. Spell zones and darkness retain their existing appearance.
export function lightHazeStyle(zone, look, color, haze) {
  const paintedMist = zone.trigger_profile?.natural_haze === true && zone.trigger_profile?.shape === "painted" && !look.darkness
    && (look.material === "smoke" || look.material === "fog");
  return {
    tint: paintedMist ? color.map(value => value + (255 - value) * 0.35)
      : look.darkness ? [10, 10, 16] : haze,
    fill: paintedMist ? 0.36 : 0.16,
    drifts: paintedMist ? [
      {tile: "clouds", cells: 4, dx: 1, dy: 0, duration: 46, opacity: 0.9},
      {tile: "haze", cells: 3, dx: -1, dy: 1, duration: 64, opacity: 0.65, variant: 1},
    ] : [{tile: "haze", cells: 4, dx: 1, dy: 0, duration: 50, opacity: 0.85}],
  };
}
export const materialBlend = material => (M[material] || M.generic).blend || null;

// Paint the material's base and detail on ctx.  The context must be w*ppc by h*ppc pixels.
// Returns the kit, which layer painters of the same zone reuse (shared glints and stars).
export function paintMaterial(ctx, material, spec) {
  const def = M[material] || M.generic;
  const kit = makeKit(spec);
  if (def.base) paintPixels(ctx, spec, def.base(kit));
  inSquares(ctx, spec);
  def.detail?.(ctx, kit);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = "source-over";
  return kit;
}

// Paint one zone-sized animated layer ("flames", "arcs", ...).  shared is paintMaterial's kit.
export function paintLayer(ctx, kind, spec, variant = 0, shared = null) {
  const painter = LAYER_PAINTERS[kind];
  if (!painter) return;
  const kit = {...makeKit(spec, variant + 1), glints: shared?.glints, bright: shared?.bright, candles: shared?.candles};
  if (kind === "lavaGlow") kit.cellsAt = makeKit(spec).cellsAt;  // the seams of the base, not new ones
  inSquares(ctx, spec);
  painter(ctx, kit);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = "source-over";
  ctx.shadowBlur = 0;
}

// Paint a seamless tile (size x size pixels) for a drifting layer.
export function paintTile(ctx, kind, size, seed, tint = [128, 128, 134]) {
  (TILE_PAINTERS[kind] || TILE_PAINTERS.clouds)(ctx, size, seed >>> 0, tint);
  ctx.globalCompositeOperation = "source-over";
}

// The colour of the haze a zone's obscurement shows (smoke is grey, poison is green ...).
const HAZE = {
  smoke: [118, 118, 124], fire: [96, 92, 90], ash: [128, 124, 120], lava: [90, 84, 82], lightning: [110, 120, 150],
  fog: [214, 220, 226], dust: [206, 180, 134], ice: [220, 232, 242], frost: [226, 236, 246], water: [200, 214, 224], wind: [226, 232, 238],
  poison: [150, 196, 90], miasma: [112, 100, 92], darkness: [8, 8, 14], stars: [20, 22, 50], spirit: [170, 232, 222],
  radiance: [255, 232, 176], sand: [206, 180, 134], blood: [120, 40, 40], grave: [180, 186, 176],
};
export function hazeTint(material, color) {
  if (HAZE[material]) return HAZE[material];
  const [r, g, b] = color;
  return [mix(r, 150, 0.5), mix(g, 150, 0.5), mix(b, 156, 0.5)];
}
