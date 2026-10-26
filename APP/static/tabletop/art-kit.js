// Shared drawing helpers for the top-down map art (terrain-art.js, decor-art.js). Units: one square = 64.
// ---------------------------------------------------------------- the drawings (owner 2026-10-08 overhaul)
// Seen from above, lit from the north-west like the trees and props, each on a soft contact shadow falling
// south-east (stacked translucent ellipses: no filters or ids, since every cell shares one SVG). Rocks are faceted:
// a dark body, a lit top face pulled toward the light, and the edges between them.
export const r2 = n => Math.round(n * 10) / 10;
export function seeded(seed) {
  let a = seed >>> 0;
  return () => { a = (a * 1664525 + 1013904223) >>> 0; return a / 4294967296; };
}
export const soft = (cx, cy, rx, ry, alpha = 0.3) => [1, 0.8, 0.6].map((k, i) =>
  `<ellipse cx="${r2(cx)}" cy="${r2(cy)}" rx="${r2(rx * (1.15 - i * 0.15))}" ry="${r2(ry * (1.15 - i * 0.15))}" fill="#0d0b08" opacity="${r2(alpha * k * 0.5 * 100) / 100}"/>`).join("");
// A faceted stone at (cx, cy) of radius r. tone picks a palette: grey granite, warm sandstone or dark basalt.
export const TONES = {
  grey: ["#4f4b45", "#7c776d", "#b4ae9f", "#e3ddcb"],
  warm: ["#5a4a39", "#8b7760", "#bfaa88", "#ecdcbc"],
  dark: ["#2e2c2a", "#55524c", "#86817a", "#bdb7aa"],
  moss: ["#3c4434", "#5f6a4e", "#8d9a72", "#c6d2a2"],
};
export function rock(cx, cy, r, seed, tone = "grey", {squash = 1, angle = 0, sides = 7, shadow = true} = {}) {
  const rand = seeded(seed), [deep, body, lit, edge] = TONES[tone] || TONES.grey;
  const outer = [], inner = [];
  for (let i = 0; i < sides; i += 1) {
    const a = angle + (i / sides) * Math.PI * 2 + (rand() - 0.5) * 0.5, k = 0.78 + rand() * 0.3;
    const x = Math.cos(a) * r * k, y = Math.sin(a) * r * k * squash;
    outer.push([cx + x, cy + y]);
    inner.push([cx + x * 0.58 - r * 0.14, cy + y * 0.58 - r * 0.17]);
  }
  const path = pts => `M${pts.map(([x, y]) => `${r2(x)} ${r2(y)}`).join("L")}Z`;
  const ridges = outer.map(([x, y], i) => `M${r2(inner[i][0])} ${r2(inner[i][1])}L${r2(x)} ${r2(y)}`).filter((_, i) => i % 2 === 0).join("");
  return (shadow ? soft(cx + r * 0.22, cy + r * 0.3, r * 1.05, r * 0.95 * squash) : "")
    + `<path d="${path(outer)}" fill="${body}" stroke="${deep}" stroke-width="1.1" stroke-linejoin="round"/>`
    + `<path d="${ridges}" stroke="${deep}" stroke-width=".7" opacity=".55" fill="none"/>`
    + `<path d="${path(inner)}" fill="${lit}" stroke="${edge}" stroke-width=".7" stroke-linejoin="round"/>`
    + `<path d="M${r2(inner[sides - 1][0])} ${r2(inner[sides - 1][1])}L${r2(inner[0][0])} ${r2(inner[0][1])}L${r2(inner[1][0])} ${r2(inner[1][1])}" stroke="${edge}" stroke-width="1.1" fill="none" opacity=".8"/>`
    + (r >= 6 ? crack(cx - r * 0.14, cy - r * 0.17, r * 0.5, rand, deep) : "");
}
// A scattered field of rocks: how many, where, how big, and what mix of stone each one is are all drawn
// fresh from the square's own seed (not just the facets of a few fixed-position rocks), so a big run of
// one look reads as a natural spill instead of the same cluster's silhouette repeated square to square
// (owner playtest 2026-10-13: "more diversity for the rocks" -- rubble was still one rock-cluster icon,
// centred and identically shaped, on every square). Small loose grit fills the gaps between the rocks.
export function rockField(seed, {count = [4, 7], rMin = 4, rMax = 15, tones = ["grey", "warm"], dust = 8, margin = 7} = {}) {
  const rand = seeded((Number(seed) >>> 0) * 2654435761 + 97);
  const n = count[0] + Math.floor(rand() * (count[1] - count[0] + 1));
  const placed = [];
  let out = "";
  for (let i = 0; i < n; i += 1) {
    let x = 32, y = 32, r = rMin, tries = 0;
    do {
      x = margin + rand() * (64 - margin * 2);
      y = margin + rand() * (64 - margin * 2);
      r = rMin + rand() * (rMax - rMin);
      tries += 1;
    } while (tries < 6 && placed.some(p => Math.hypot(p.x - x, p.y - y) < (p.r + r) * 0.5));
    placed.push({x, y, r});
    const tone = tones[Math.floor(rand() * tones.length) % tones.length];
    out += rock(x, y, r, Math.floor(rand() * 90000) + 1, tone, {sides: 5 + Math.floor(rand() * 4), angle: rand() * Math.PI * 2});
  }
  for (let i = 0; i < dust; i += 1) {
    const x = r2(rand() * 64), y = r2(rand() * 64), s = r2(0.5 + rand() * 1.3), tone = rand() < 0.5 ? "#b4ae9f" : "#5f5a51";
    out += `<ellipse cx="${x}" cy="${y}" rx="${s}" ry="${r2(s * 0.7)}" fill="${tone}" opacity="${r2(0.35 + rand() * 0.4)}" transform="rotate(${Math.floor(rand() * 180)} ${x} ${y})"/>`;
  }
  return out;
}
// A hairline crack wandering across a rock's lit face.
export function crack(cx, cy, r, rand, color) {
  const a = rand() * Math.PI * 2, steps = 4;
  let x = cx - Math.cos(a) * r, y = cy - Math.sin(a) * r, d = `M${r2(x)} ${r2(y)}`;
  for (let i = 1; i <= steps; i += 1) {
    const t = i / steps, jitter = (rand() - 0.5) * r * 0.5;
    x = cx - Math.cos(a) * r + Math.cos(a) * 2 * r * t - Math.sin(a) * jitter;
    y = cy - Math.sin(a) * r + Math.sin(a) * 2 * r * t + Math.cos(a) * jitter;
    d += `L${r2(x)} ${r2(y)}`;
  }
  return `<path d="${d}" stroke="${color}" stroke-width=".8" fill="none" stroke-linejoin="round" opacity=".75"/>`;
}
// A tapering root or limb along a quadratic curve: width w at the start, a blunt point at the end.
export function taper([x0, y0], [mx, my], [x1, y1], w, end = 0.12) {
  const a0 = Math.atan2(my - y0, mx - x0), a1 = Math.atan2(y1 - my, x1 - mx);
  const n0 = [-Math.sin(a0) * w / 2, Math.cos(a0) * w / 2], n1 = [-Math.sin(a1) * w * end, Math.cos(a1) * w * end];
  const nm = [(n0[0] + n1[0]) * 0.6, (n0[1] + n1[1]) * 0.6];
  return `M${r2(x0 + n0[0])} ${r2(y0 + n0[1])}Q${r2(mx + nm[0])} ${r2(my + nm[1])} ${r2(x1 + n1[0])} ${r2(y1 + n1[1])}`
    + `Q${r2(x1 + Math.cos(a1) * w * end * 1.3)} ${r2(y1 + Math.sin(a1) * w * end * 1.3)} ${r2(x1 - n1[0])} ${r2(y1 - n1[1])}Q${r2(mx - nm[0])} ${r2(my - nm[1])} ${r2(x0 - n0[0])} ${r2(y0 - n0[1])}Z`;
}
// A fan of narrow bamboo leaves on a short twig, leaning toward angle (degrees).
export const fan = (x, y, angle, len, shade) => {
  const tw = [x + Math.cos(angle * Math.PI / 180) * 3, y + Math.sin(angle * Math.PI / 180) * 3];
  return `<path d="M${r2(x)} ${r2(y)}L${r2(tw[0])} ${r2(tw[1])}" stroke="#3c3a1a" stroke-width=".8"/>`
    + [-34, -17, 0, 17, 34].map((d, i) => blade(r2(tw[0]), r2(tw[1]), angle + 90 + d, len * (i === 2 ? 1 : 0.85), 1.9,
      ["#3f6b26", "#5d8c34", "#7eaa48", "#9cc45e"][Math.min(3, shade + (i % 2))])).join("");
};
// A bamboo culm cut or seen from above: a green ring with a pale node face.
export const culm = (x, y, r) => `<circle cx="${r2(x + r * 0.5)}" cy="${r2(y + r * 0.7)}" r="${r}" fill="#000" opacity=".35"/><circle cx="${x}" cy="${y}" r="${r}" fill="#4a7a2c" stroke="#1d3313" stroke-width=".9"/><path d="M${r2(x - r * 0.8)} ${r2(y + r * 0.2)}A${r * 0.82} ${r * 0.82} 0 0 1 ${r2(x + r * 0.2)} ${r2(y - r * 0.8)}" stroke="#cfe39a" stroke-width="${r2(r * 0.22)}" fill="none"/><circle cx="${x}" cy="${y}" r="${r2(r * 0.6)}" fill="#86a852" stroke="#e1e9b0" stroke-width="${r2(r * 0.1)}"/><circle cx="${x}" cy="${y}" r="${r2(r * 0.28)}" fill="#26300f"/>`;
export const blade = (x, y, a, len, w, color) => `<path d="M0 0Q${r2(w)} ${r2(-len * 0.45)} 0 ${r2(-len)}Q${r2(-w)} ${r2(-len * 0.45)} 0 0Z" transform="translate(${x} ${y}) rotate(${a})" fill="${color}" stroke="#1c3014" stroke-width=".5"/>`;
// Wraps a piece whose own geometry is one fixed hand-drawn path (a toppled pillar, a lantern, a tile
// patch) in a seeded offset, turn, touch of scale, and sometimes a mirror, so a single small piece
// repeated across separate squares never reads as the same stamp copy-pasted (owner playtest
// 2026-10-13, round 3: "the smaller parts like when it's just one square -- look natural too?").
export function variantWrap(seed, svg, {turn = 16, shift = 4, scale = 0.12, flip = true} = {}) {
  const rand = seeded((Number(seed) >>> 0) * 6151 + 271);
  const dx = r2((rand() - 0.5) * shift * 2), dy = r2((rand() - 0.5) * shift * 2);
  const deg = r2((rand() - 0.5) * turn * 2), s = r2(1 + (rand() - 0.5) * scale * 2);
  const flipX = flip && rand() < 0.5 ? -1 : 1;
  return `<g transform="translate(${dx} ${dy}) rotate(${deg} 32 32) translate(32 32) scale(${flipX * s} ${s}) translate(-32 -32)">${svg}</g>`;
}

