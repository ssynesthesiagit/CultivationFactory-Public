/* dice3d.js - Tianxia Character Foundry: light, local 3D dice tray.
 *
 * Plain ES module, no dependencies, no network, no WebGL. Real convex polyhedra are rotated with
 * quaternions and drawn on a Canvas 2D overlay (perspective projection, back-face culling, flat
 * Lambert + specular shading, bevelled edges, face numbers mapped onto each face plane).
 *
 * In combat the server's roller decides every value. The tray only animates: every die is built so
 * that its final orientation (computed before the throw starts) shows exactly the value supplied.
 */
import {rollModeHover, rollModeWord} from "./roll_mode_display.js?v=rollreason1";

const PHI = (1 + Math.sqrt(5)) / 2;
export const SUPPORTED_SIDES = Object.freeze([4, 6, 8, 10, 12, 20, 100]);
const CAMERA_K = 4.6; // camera distance in die circumradii (mild perspective)
const TILT = { 4: 0.68, 6: 0.42, 8: 0.3, 10: 0.26, 12: 0.26, 20: 0.22 }; // rest tilt so dice read as 3D
const TILT_AXIS = norm([1, -0.38, 0]); // tips the result face up-right so the front and left sides show
const VISUAL = { 4: 1.3, 6: 1.02, 8: 1.08, 10: 1.08, 12: 1.04, 20: 1.04 }; // similar apparent sizes
const FONT_K = { 4: 1.1, 6: 0.95, 8: 1.3, 10: 1.32, 12: 1.1, 20: 1.4 }; // label size vs face inradius
const FONT_FAMILY = '"Trebuchet MS", "DejaVu Sans", "Segoe UI", system-ui, sans-serif';
const HOLD_MS = 4000;
const FADE_MS = 380;

export const THEMES = Object.freeze({
  crimson: Object.freeze({ body: '#7c1119', edge: '#e0b24c', text: '#f7d98b', glow: '#ffcf5a' }),
  jade: Object.freeze({ body: '#1d6e51', edge: '#bfe6cc', text: '#f1fff6', glow: '#7dffc4' }),
  ivory: Object.freeze({ body: '#ece2cc', edge: '#8c6a36', text: '#3a2816', glow: '#ffe9a0' }),
  midnight: Object.freeze({ body: '#1a2852', edge: '#9db4ff', text: '#e7edff', glow: '#86a8ff' }),
});

// ---------------------------------------------------------------- vector / quaternion math
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function add(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function scale(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
function norm(a) { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
function avg(pts) { return scale(pts.reduce(add, [0, 0, 0]), 1 / pts.length); }
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const LIGHT = norm([-0.45, 0.62, 0.85]);
const HALF = norm(add(LIGHT, [0, 0, 1]));

export function quatAxisAngle(axis, angle) {
  const a = norm(axis), s = Math.sin(angle / 2);
  return [Math.cos(angle / 2), a[0] * s, a[1] * s, a[2] * s];
}
export function quatMul(a, b) {
  const [aw, ax, ay, az] = a, [bw, bx, by, bz] = b;
  return [aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw];
}
function quatNormalize(q) { const l = Math.hypot(...q) || 1; return q.map((c) => c / l); }
export function quatRotate(q, v) {
  const u = [q[1], q[2], q[3]], t = scale(cross(u, v), 2);
  return add(add(v, scale(t, q[0])), cross(u, t));
}
function quatToMatrix(q) {
  const [w, x, y, z] = q;
  return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
}
function mulMat(m, v) { return [dot(m[0], v), dot(m[1], v), dot(m[2], v)]; }
// Quaternion for the rotation matrix whose rows are r, u, n (maps r->x, u->y, n->z).
function quatFromRows(r, u, n) {
  const [m00, m01, m02] = r, [m10, m11, m12] = u, [m20, m21, m22] = n, tr = m00 + m11 + m22;
  let s;
  if (tr > 0) { s = Math.sqrt(tr + 1) * 2; return quatNormalize([s / 4, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s]); }
  if (m00 > m11 && m00 > m22) { s = Math.sqrt(1 + m00 - m11 - m22) * 2; return quatNormalize([(m21 - m12) / s, s / 4, (m01 + m10) / s, (m02 + m20) / s]); }
  if (m11 > m22) { s = Math.sqrt(1 + m11 - m00 - m22) * 2; return quatNormalize([(m02 - m20) / s, (m01 + m10) / s, s / 4, (m12 + m21) / s]); }
  s = Math.sqrt(1 + m22 - m00 - m11) * 2;
  return quatNormalize([(m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, s / 4]);
}

// ---------------------------------------------------------------- procedural geometry
function shapeVertices(sides) {
  const cube = [];
  for (const x of [-1, 1]) for (const y of [-1, 1]) for (const z of [-1, 1]) cube.push([x, y, z]);
  const cyc = (p, q) => { // cyclic permutations of (0, +-p, +-q)
    const out = [];
    for (const a of [-1, 1]) for (const b of [-1, 1]) out.push([0, a * p, b * q], [a * p, b * q, 0], [b * q, 0, a * p]);
    return out;
  };
  if (sides === 4) return [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]];
  if (sides === 6) return cube;
  if (sides === 8) return [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
  if (sides === 12) return cube.concat(cyc(1 / PHI, PHI));
  if (sides === 20) return cyc(1, PHI);
  // d10: pentagonal trapezohedron. Ring height c keeps each kite planar for apex height h.
  const h = 1.05, cos36 = Math.cos(Math.PI / 5), c = (h * (1 - cos36)) / (1 + cos36), v = [[0, 0, h], [0, 0, -h]];
  for (let i = 0; i < 10; i++) v.push([Math.cos((i * Math.PI) / 5), Math.sin((i * Math.PI) / 5), i % 2 ? -c : c]);
  return v;
}

// Brute-force convex hull (<= 20 vertices): every supporting plane through 3 vertices is a face.
function hullFaces(verts) {
  const faces = [], eps = 1e-6;
  for (let i = 0; i < verts.length; i++) for (let j = i + 1; j < verts.length; j++) for (let k = j + 1; k < verts.length; k++) {
    const raw = cross(sub(verts[j], verts[i]), sub(verts[k], verts[i]));
    if (Math.hypot(...raw) < eps) continue;
    let n = norm(raw), d = dot(n, verts[i]);
    if (d < 0) { n = scale(n, -1); d = -d; }
    if (d < eps || faces.some((f) => dot(f.n, n) > 1 - eps) || verts.some((v) => dot(v, n) > d + eps)) continue;
    const idx = verts.map((_, m) => m).filter((m) => Math.abs(dot(verts[m], n) - d) < 1e-5);
    const c = avg(idx.map((m) => verts[m])), a = norm(sub(verts[idx[0]], c)), b = cross(n, a);
    const ang = (m) => { const w = sub(verts[m], c); return Math.atan2(dot(w, b), dot(w, a)); };
    idx.sort((p, q) => ang(p) - ang(q)); // counter-clockwise seen from outside
    faces.push({ n, d, idx, center: c });
  }
  return faces;
}

// Opposite faces sum like real dice (d10 digits 0-9 sum to 9); low/high values alternate.
function assignValues(faces, sides) {
  const lo = sides === 10 ? 0 : 1, hi = sides === 10 ? 9 : sides, r6 = (x) => Math.round(x * 1e6);
  const order = faces.map((_, i) => i).sort((a, b) => (r6(faces[b].n[2]) - r6(faces[a].n[2]))
    || (Math.atan2(faces[a].n[1], faces[a].n[0]) - Math.atan2(faces[b].n[1], faces[b].n[0])));
  let pair = 0, next = lo;
  for (const i of order) {
    const f = faces[i];
    if (f.value !== undefined) continue;
    const j = faces.findIndex((g) => dot(g.n, f.n) < -1 + 1e-6);
    if (j < 0) { f.value = next++; continue; } // d4 has no opposite faces
    [f.value, faces[j].value] = pair % 2 ? [hi - pair, lo + pair] : [lo + pair, hi - pair];
    pair++;
  }
}

// Where each number sits on its face, which way is "up" for the glyph, and how big it may be.
function labelFrames(faces, verts, sides) {
  for (const f of faces) {
    const P = f.idx.map((i) => verts[i]);
    let c = f.center, up;
    if (sides === 10) { // kite: number sits in the wide part, reading toward the pole
      const ai = P.reduce((best, p, i) => (Math.abs(p[2]) > Math.abs(P[best][2]) ? i : best), 0);
      const apex = P[ai], wide = avg([P[(ai + 1) % 4], P[(ai + 3) % 4]]);
      c = add(apex, scale(sub(wide, apex), 0.74));
      up = sub(apex, c);
    } else if (sides === 6) up = sub(avg([P[0], P[1]]), c);
    else up = sub(P[0], c);
    up = norm(sub(up, scale(f.n, dot(up, f.n))));
    let inr = Infinity;
    for (let i = 0; i < P.length; i++) {
      const a = P[i], e = norm(sub(P[(i + 1) % P.length], a)), w = sub(c, a);
      inr = Math.min(inr, Math.hypot(...sub(w, scale(e, dot(w, e)))));
    }
    Object.assign(f, { label: c, up, right: cross(up, f.n), font: inr * FONT_K[sides] });
  }
}

const GEOMETRY = new Map();
/** Unit-circumradius geometry for a die; d100 uses the d10 shape. */
export function getDieGeometry(sides) {
  const key = Number(sides) === 100 ? 10 : Number(sides);
  if (!TILT[key]) throw new RangeError(`Unsupported die: d${sides}`);
  if (!GEOMETRY.has(key)) {
    const raw = shapeVertices(key), r = Math.max(...raw.map((v) => Math.hypot(...v)));
    const verts = raw.map((v) => scale(v, 1 / r)), faces = hullFaces(verts);
    assignValues(faces, key);
    labelFrames(faces, verts, key);
    GEOMETRY.set(key, { sides: key, verts, faces, tilt: TILT[key], visual: VISUAL[key] });
  }
  return GEOMETRY.get(key);
}

/** Final orientation: face `faceValue` points at the camera, its number upright (+ small yaw/tilt). */
export function restOrientation(sides, faceValue, { yaw = 0, tilt } = {}) {
  const g = getDieGeometry(sides), f = g.faces.find((x) => x.value === faceValue);
  if (!f) throw new RangeError(`d${sides} has no face ${faceValue}`);
  const align = quatFromRows(f.right, f.up, f.n), tq = quatAxisAngle(TILT_AXIS, -(tilt ?? g.tilt));
  const u = quatRotate(tq, [0, 1, 0]), lean = Math.atan2(u[0], u[1]); // pre-yaw cancels the on-screen lean of the tilt
  return quatNormalize(quatMul(tq, quatMul(quatAxisAngle([0, 0, 1], yaw + lean), align)));
}

/** Value of the face most directly facing the camera (+z) for orientation q. */
export function topFace(sides, q) {
  let best = null, bz = -Infinity;
  for (const f of getDieGeometry(sides).faces) { const z = quatRotate(q, f.n)[2]; if (z > bz) { bz = z; best = f; } }
  return best.value;
}

/** Tumble that decays to exactly qFinal at t = 1 (angular speed falls to zero). */
export function tumbleOrientation(qFinal, spins, t) {
  const k = Math.pow(1 - clamp(t, 0, 1), 3);
  let q = qFinal;
  for (const s of spins) q = quatMul(quatAxisAngle(s.axis, s.angle * k), q);
  return q;
}

/** Validate one caller-supplied group and split it into physical dice (d100 -> tens + ones d10). */
export function expandGroup(group) {
  const sides = Number(group && group.sides), value = group && group.value;
  if (!SUPPORTED_SIDES.includes(sides)) throw new RangeError(`Unsupported die: d${group && group.sides}`);
  if (!Number.isInteger(value) || value < 1 || value > sides) throw new RangeError(`d${sides} cannot show ${value}`);
  if (sides === 100) return [{ shape: 10, face: Math.floor((value % 100) / 10), role: 'tens' }, { shape: 10, face: value % 10, role: 'ones' }];
  if (sides === 10) return [{ shape: 10, face: value % 10, role: 'd10' }];
  return [{ shape: sides, face: value, role: 'plain' }];
}

/** Text printed on a face: d10 shows 1-10, percentile tens die 00-90, ones die 0-9. */
export function faceText(role, face) {
  if (role === 'tens') return face === 0 ? '00' : `${face}0`;
  if (role === 'd10') return face === 0 ? '10' : String(face);
  return String(face);
}

// ---------------------------------------------------------------- expressions and local rolls
/** Parse "d20", "1d20+5", "2d6 + 1d4 - 1", "1d20 adv", "1d20 dis", "d100" (also "d%"). Throws on invalid input. */
export function parseDiceExpression(text) {
  if (typeof text !== 'string') throw new TypeError('Dice expression must be a string');
  let mode = 'normal';
  const body = text.toLowerCase().replace(/\b(adv(?:antage)?|dis(?:adv(?:antage)?)?)\b/g, (w) => {
    const m = w.startsWith('adv') ? 'advantage' : 'disadvantage';
    if (mode !== 'normal' && mode !== m) throw new SyntaxError(`Both advantage and disadvantage in "${text}"`);
    mode = m;
    return ' ';
  }).trim();
  if (!body) throw new SyntaxError(`Empty dice expression: "${text}"`);
  const groups = [], re = /\s*([+-]?)\s*(?:(\d*)d(\d+|%)|(\d+))\s*/y;
  let modifier = 0, pos = 0;
  while (pos < body.length) {
    re.lastIndex = pos;
    const m = re.exec(body);
    if (!m || !m[0].length || (pos > 0 && !m[1])) throw new SyntaxError(`Invalid dice expression: "${text}"`);
    pos = re.lastIndex;
    const sign = m[1] === '-' ? -1 : 1;
    if (m[4] !== undefined) { modifier += sign * Number(m[4]); continue; }
    const count = m[2] === '' ? 1 : Number(m[2]), sides = m[3] === '%' ? 100 : Number(m[3]);
    if (sign < 0) throw new SyntaxError(`Dice cannot be subtracted: "${text}"`);
    if (!SUPPORTED_SIDES.includes(sides)) throw new RangeError(`Unsupported die d${m[3]} in "${text}"`);
    if (count < 1 || count > 100) throw new RangeError(`Dice count must be 1-100 in "${text}"`);
    groups.push({ count, sides });
  }
  if (!groups.length) throw new SyntaxError(`No dice in "${text}"`);
  if (mode !== 'normal') {
    const d20 = groups.filter((g) => g.sides === 20);
    if (d20.length !== 1 || d20[0].count !== 1) throw new SyntaxError(`Advantage/disadvantage needs exactly one d20: "${text}"`);
  }
  return { groups, modifier, mode };
}

/** Unbiased integer in 1..sides from crypto.getRandomValues (rejection sampling). */
export function cryptoRandomInt(sides) {
  const n = Math.floor(sides);
  if (!(n >= 1 && n <= 0x7fffffff)) throw new RangeError(`Bad die size ${sides}`);
  const buf = new Uint32Array(1), limit = Math.floor(0x100000000 / n) * n;
  let x;
  do { globalThis.crypto.getRandomValues(buf); x = buf[0]; } while (x >= limit);
  return (x % n) + 1;
}

function expressionString(p) {
  const dice = p.groups.map((g) => `${g.count}d${g.sides}`).join('+');
  const mod = p.modifier ? (p.modifier > 0 ? `+${p.modifier}` : `${p.modifier}`) : '';
  return dice + mod + (p.mode === 'normal' ? '' : p.mode === 'advantage' ? ' adv' : ' dis');
}

/** Out-of-combat roll (sheet checks etc.). Advantage rolls 2d20 and keeps the highest. */
export function rollLocal(expression, rng = cryptoRandomInt) {
  const p = typeof expression === 'string' ? parseDiceExpression(expression) : expression;
  const draw = (sides) => {
    const v = rng(sides);
    if (!Number.isInteger(v) || v < 1 || v > sides) throw new RangeError(`rng returned ${v} for d${sides}`);
    return v;
  };
  const groups = [], discarded = [];
  for (const g of p.groups) for (let i = 0; i < g.count; i++) {
    const a = draw(g.sides);
    if (g.sides === 20 && p.mode !== 'normal') {
      const b = draw(20), keep = p.mode === 'advantage' ? Math.max(a, b) : Math.min(a, b);
      groups.push({ sides: 20, value: keep });
      discarded.push({ sides: 20, value: keep === a ? b : a });
    } else groups.push({ sides: g.sides, value: a });
  }
  const total = groups.reduce((s, g) => s + g.value, 0) + p.modifier;
  const sum = summarizeRoll(groups, { modifier: p.modifier, discarded });
  return { groups, discarded, modifier: p.modifier, total, mode: p.mode, text: `${expressionString(p)}: ${sum.text}` };
}

/** Structured summary used by the chip and the aria-live announcement. */
export function summarizeRoll(groups, meta = {}) {
  const modifier = Number(meta.modifier) || 0;
  const sum = groups.reduce((s, g) => s + g.value, 0);
  const total = Number.isFinite(meta.total) ? meta.total : sum + modifier;
  const dice = groups.map((g) => (g.label ? `${g.value} ${g.label}` : String(g.value)));
  const dropped = (meta.discarded || []).map((g) => String(g.value));
  const d20 = groups.filter((g) => Number(g.sides) === 20).map((g) => g.value);
  const crit = meta.critical ?? d20.includes(20);
  const fumble = !crit && (meta.fumble ?? (d20.length > 0 && d20.includes(1)));
  const label = meta.label || (meta.kind && meta.kind !== 'plain' ? meta.kind[0].toUpperCase() + meta.kind.slice(1) : '');
  const showTotal = groups.length > 1 || modifier !== 0 || total !== sum;
  let text = dice.join(' + ') + (dropped.length ? ` (dropped ${dropped.join(', ')})` : '');
  if (modifier) text += modifier > 0 ? ` + ${modifier}` : ` − ${-modifier}`;
  if (showTotal) text += ` = ${total}`;
  if (label) text = `${label} · ${text}`;
  // The owner's roll-mode label (2026-10-15 04:39Z) travels with the same summary the
  // log and previews use, so the dice tray can show and explain the mode too.
  return { label, dice, dropped, modifier, total, showTotal, crit: !!crit, fumble: !!fumble, text,
    mode: meta.mode || 'NORMAL', sources: meta.mode_sources || [] };
}

// ---------------------------------------------------------------- colour helpers
const COLORS = new Map();
let colorCtx = null;
function rgbOf(css) {
  const key = String(css || '#808080');
  if (COLORS.has(key)) return COLORS.get(key);
  let out = [128, 128, 128];
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(key.trim());
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join('') : hex[1];
    out = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  } else if (globalThis.document) { // let the browser normalise named / rgb() / hsl() colours
    colorCtx = colorCtx || globalThis.document.createElement('canvas').getContext('2d');
    colorCtx.fillStyle = '#808080';
    colorCtx.fillStyle = key;
    const v = String(colorCtx.fillStyle);
    out = v[0] === '#' ? rgbOf(v) : (v.match(/[\d.]+/g) || [128, 128, 128]).slice(0, 3).map(Number);
  }
  COLORS.set(key, out);
  return out;
}
const rgbCss = (c, k = 1, lift = 0) => `rgb(${c.map((v) => Math.round(clamp(v * k + lift, 0, 255))).join(',')})`;

function resolveTheme(t) {
  if (typeof t === 'string') return { ...(THEMES[t] || THEMES.crimson) };
  return { ...THEMES.crimson, ...(t || {}) };
}

// ---------------------------------------------------------------- DOM tray
const STYLE_ID = 'dice3d-style';
const CSS = `.dice3d-canvas{position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:2147483000;display:none}
.dice3d-chip{position:fixed;z-index:2147483001;pointer-events:none;transform:translate(-50%,-100%) translateY(8px);opacity:0;
transition:opacity .22s ease,transform .22s ease;font:500 15px/1.35 system-ui,"Segoe UI",sans-serif;color:#f5efe2;
background:rgba(17,13,20,.9);border:1px solid var(--dice3d-accent,#c9a45a);border-radius:999px;padding:6px 16px;
white-space:nowrap;box-shadow:0 6px 22px rgba(0,0,0,.45);font-variant-numeric:tabular-nums}
.dice3d-chip.show{opacity:1;transform:translate(-50%,-100%)}
.dice3d-chip .d3-label{opacity:.75}.dice3d-chip .d3-sep{opacity:.45;margin:0 .45em}
.dice3d-chip .d3-drop{opacity:.45;text-decoration:line-through;margin-left:.35em}
.dice3d-chip .d3-total{font-weight:700;font-size:1.3em;margin-left:.2em}
.dice3d-chip .d3-tag{font-size:.7em;font-weight:800;letter-spacing:.1em;margin-left:.7em;vertical-align:.15em}
.dice3d-chip .d3-mode{margin-left:.2em;text-decoration:none;cursor:help;pointer-events:auto;background:rgba(255,255,255,.12);border-radius:999px;padding:2px 8px;white-space:pre-line}
.dice3d-chip.crit{border-color:#ffd35a;box-shadow:0 0 0 1px rgba(255,211,90,.55),0 0 24px 5px rgba(255,196,50,.55)}
.dice3d-chip.crit .d3-total,.dice3d-chip.crit .d3-tag{color:#ffd35a}
.dice3d-chip.fumble{border-color:#ff4d4d;box-shadow:0 0 0 1px rgba(255,77,77,.55),0 0 24px 5px rgba(255,50,50,.5)}
.dice3d-chip.fumble .d3-total,.dice3d-chip.fumble .d3-tag{color:#ff6b6b}
.dice3d-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
@media (prefers-reduced-motion:reduce){.dice3d-chip{transition:none}}`;

export function createDiceTray(options = {}) {
  const doc = (options.container && options.container.ownerDocument) || globalThis.document;
  if (!doc) throw new Error('createDiceTray needs a DOM document');
  const win = doc.defaultView || globalThis;
  const container = options.container || doc.body;
  const duration = clamp(Number(options.durationMs) || 1300, 200, 6000);
  let theme = resolveTheme(options.theme);
  let canvas = null, ctx = null, chip = null, W = 0, H = 0, dpr = 1;
  let dice = [], summary = null, pending = null, raf = 0, startTime = 0, fade = 1;
  let animating = false, destroyed = false, hideTimer = 0, fallbackTimer = 0, maxDelay = 0;

  if (!doc.getElementById(STYLE_ID)) {
    const st = doc.createElement('style');
    st.id = STYLE_ID;
    st.textContent = CSS;
    doc.head.appendChild(st);
  }
  const live = doc.createElement('div');
  live.className = 'dice3d-sr';
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('role', 'status');
  container.appendChild(live);

  function ensureDom() {
    if (!canvas) {
      canvas = doc.createElement('canvas');
      canvas.className = 'dice3d-canvas';
      canvas.setAttribute('aria-hidden', 'true');
      container.appendChild(canvas);
      ctx = canvas.getContext('2d');
    }
    if (!chip) {
      chip = doc.createElement('div');
      chip.className = 'dice3d-chip';
      chip.setAttribute('aria-hidden', 'true');
      container.appendChild(chip);
    }
    canvas.style.display = 'block';
    resize();
  }
  function resize() {
    dpr = Math.min(win.devicePixelRatio || 1, 2);
    W = win.innerWidth;
    H = win.innerHeight;
    const cw = Math.round(W * dpr), ch = Math.round(H * dpr);
    if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
  }

  function layout(specs) {
    const n = specs.length, rnd = (a, b) => a + Math.random() * (b - a);
    let size = clamp(Math.min(W, H) * 0.075, 26, 72) * (n > 6 ? Math.max(0.55, Math.sqrt(6 / n)) : 1);
    let gap, cols, rows;
    for (let pass = 0; pass < 3; pass++) {
      gap = size * 2.35;
      cols = Math.max(1, Math.min(n, Math.floor(Math.min(W * 0.72, 980) / gap)));
      rows = Math.ceil(n / cols);
      if (rows * gap <= H * 0.4) break;
      size *= (H * 0.4) / (rows * gap);
    }
    const top = clamp(H * 0.7 - ((rows - 1) * gap) / 2, H * 0.45, H - size * 1.8 - (rows - 1) * gap);
    const rest = specs.map((_, i) => {
      const row = Math.floor(i / cols), inRow = Math.min(cols, n - row * cols), col = i - row * cols;
      return [W / 2 + (col - (inRow - 1) / 2) * gap + rnd(-0.2, 0.2) * size, top + row * gap + rnd(-0.2, 0.2) * size];
    });
    // One shared throw vector keeps the handful in formation, so dice spread instead of piling up in flight.
    const xs = rest.map((p) => p[0]), edge = size * 2.5, side = Math.floor(Math.random() * 3);
    const tv = side === 0 ? [-(Math.max(...xs) + edge), rnd(-0.25, 0.04) * H]
      : side === 1 ? [W - Math.min(...xs) + edge, rnd(-0.25, 0.04) * H]
        : [rnd(-0.2, 0.2) * W, H - Math.min(...rest.map((p) => p[1])) + edge];
    return specs.map((s, i) => {
      const [x1, y1] = rest[i], k = rnd(1, 1.04);
      const x0 = x1 + tv[0] * k + rnd(-0.5, 0.5) * size, y0 = y1 + tv[1] * k + rnd(-0.5, 0.5) * size;
      const dir = norm([x1 - x0, -(y1 - y0), 0]); // screen y points down, world y points up
      const spins = [{ axis: cross(dir, [0, 0, 1]), angle: rnd(2.2, 3.6) * 2 * Math.PI },
        { axis: norm([rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)]), angle: rnd(0.4, 1.1) * 2 * Math.PI }];
      return { ...s, geom: getDieGeometry(s.shape), size, x0, y0, x1, y1, spins, delay: Math.min(i * 30, 240),
        q: restOrientation(s.shape, s.face, { yaw: rnd(-0.22, 0.22) }), lastQ: null };
    });
  }

  function height(t) {
    if (t < 0.28) { const s = t / 0.28; return 1.1 * (1 - s * s); }
    for (const [a, b, amp] of [[0.28, 0.54, 0.4], [0.54, 0.72, 0.14], [0.72, 0.84, 0.045]]) {
      if (t < b) { const s = (t - a) / (b - a); return amp * 4 * s * (1 - s); }
    }
    return 0;
  }
  function stateAt(d, t) {
    const f = Math.pow(1 - t, 2.4) * Math.cos(Math.PI * 1.25 * t); // arrive, overshoot slightly, come back
    return { d, t, x: d.x1 + (d.x0 - d.x1) * f, y: d.y1 + (d.y0 - d.y1) * f, h: height(t),
      q: t >= 1 ? d.q : tumbleOrientation(d.q, d.spins, t) };
  }

  function drawShadow(s, alpha) {
    const r = s.d.size * s.d.geom.visual * (0.9 + 0.3 * s.h), ox = s.x + s.h * s.d.size * 0.55;
    const oy = s.y + s.d.size * 0.3 + s.h * s.d.size * 0.75;
    const g = ctx.createRadialGradient(ox, oy, r * 0.15, ox, oy, r * 1.2);
    g.addColorStop(0, `rgba(0,0,0,${(0.45 * alpha * (1 - 0.4 * Math.min(1, s.h))).toFixed(3)})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(ox, oy, r * 1.2, r * 0.85, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawDie(s, alpha, glow) {
    const { d, x, y, h, q } = s, g = d.geom, m = d.size * g.visual * (1 + 0.5 * h), R = quatToMatrix(q);
    const proj = (v) => { const p = CAMERA_K / (CAMERA_K - v[2]); return [x + m * v[0] * p, y - m * v[1] * p]; };
    const pv = g.verts.map((v) => proj(mulMat(R, v)));
    const body = rgbOf(d.color || theme.body), edge = rgbOf(theme.edge), vis = [];
    d.lastQ = q;
    for (const f of g.faces) { const n = mulMat(R, f.n); if (CAMERA_K * n[2] - f.d > 1e-3) vis.push([f, n]); }
    const path = (f) => { ctx.beginPath(); f.idx.forEach((i, j) => (j ? ctx.lineTo(pv[i][0], pv[i][1]) : ctx.moveTo(pv[i][0], pv[i][1]))); ctx.closePath(); };
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = alpha;
    if (glow) {
      ctx.save();
      ctx.shadowColor = glow;
      ctx.shadowBlur = m * 0.9 * dpr;
      ctx.fillStyle = glow;
      for (const [f] of vis) { path(f); ctx.fill(); }
      ctx.restore();
    }
    ctx.lineJoin = 'round';
    ctx.lineWidth = Math.max(1, m * 0.04);
    for (const [f, n] of vis) {
      const lam = Math.max(0, dot(n, LIGHT)), spec = Math.pow(Math.max(0, dot(n, HALF)), 36) * 55;
      path(f);
      ctx.fillStyle = rgbCss(body, 0.36 + 0.72 * lam, spec);
      ctx.fill();
      ctx.strokeStyle = rgbCss(edge, 0.5 + 0.6 * lam);
      ctx.stroke();
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    const text = rgbOf(theme.text), dark = text[0] + text[1] + text[2] > 380;
    for (const [f, n] of vis) {
      const face = clamp((n[2] - 0.1) / 0.35, 0, 1);
      if (face <= 0.02) continue;
      const c = mulMat(R, f.label), p0 = proj(c), pr = proj(add(c, scale(mulMat(R, f.right), 0.05)));
      const pd = proj(sub(c, scale(mulMat(R, f.up), 0.05)));
      // affine map from glyph space (0.01 world units) onto the projected face plane
      ctx.setTransform(dpr * (pr[0] - p0[0]) / 5, dpr * (pr[1] - p0[1]) / 5, dpr * (pd[0] - p0[0]) / 5,
        dpr * (pd[1] - p0[1]) / 5, dpr * p0[0], dpr * p0[1]);
      const label = faceText(d.role, f.value), fs = f.font * 100 * (label.length > 1 ? 0.78 : 1), base = fs * 0.36;
      ctx.font = `700 ${fs.toFixed(1)}px ${FONT_FAMILY}`;
      ctx.globalAlpha = alpha * face;
      ctx.fillStyle = dark ? 'rgba(0,0,0,0.45)' : 'rgba(255,255,255,0.35)';
      ctx.fillText(label, fs * 0.03, base + fs * 0.045);
      ctx.fillStyle = theme.text;
      ctx.fillText(label, 0, base);
      if (label === '6' || label === '9') ctx.fillRect(-fs * 0.24, base + fs * 0.1, fs * 0.48, fs * 0.08);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
  }

  function glowFor(d) {
    if (d.dim || d.shape !== 20 || !summary) return null;
    if (summary.crit && d.face === 20) return '#ffcc3d';
    if (summary.fumble && d.face === 1) return '#ff3b3b';
    return null;
  }

  function drawFrame(elapsed, final) {
    resize();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const states = dice.map((d) => stateAt(d, final ? 1 : clamp((elapsed - d.delay) / duration, 0, 1)));
    states.sort((a, b) => a.h - b.h || a.y - b.y);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (const s of states) drawShadow(s, fade * (s.d.dim ? 0.4 : 1));
    for (const s of states) drawDie(s, fade * (s.d.dim ? 0.42 : 1), final ? glowFor(s.d) : null);
  }

  function tick(now) {
    if (!startTime) startTime = now;
    const elapsed = now - startTime;
    if (elapsed >= duration + maxDelay) { settle(); return; }
    drawFrame(elapsed, false);
    raf = win.requestAnimationFrame(tick);
  }

  function showChip() {
    const s = summary, el = (cls, txt) => { const e = doc.createElement('span'); e.className = cls; e.textContent = txt; return e; };
    const parts = [];
    if (s.label) parts.push(el('d3-label', s.label), el('d3-sep', '·'));
    parts.push(el('d3-dice', s.dice.join(' + ')));
    if (s.dropped.length) parts.push(el('d3-drop', s.dropped.join(' ')));
    if (s.modifier) parts.push(el('d3-mod', s.modifier > 0 ? ` + ${s.modifier}` : ` − ${-s.modifier}`));
    if (s.showTotal) parts.push(el('d3-eq', ' = '), el('d3-total', String(s.total)));
    else parts[parts.length - 1].className += ' d3-total';
    if (s.crit) parts.push(el('d3-tag', 'CRITICAL'));
    else if (s.fumble) parts.push(el('d3-tag', 'FUMBLE'));
    // Owner 2026-10-15 04:39Z: the roll display itself says Advantage/Disadvantage and
    // hovering that word lists the reasons underneath, one line per source.
    const hasCancellation = s.mode === 'NORMAL' &&
      s.sources.some(source => source && source.kind === 'advantage') &&
      s.sources.some(source => source && source.kind === 'disadvantage');
    if (s.mode === 'ADVANTAGE' || s.mode === 'DISADVANTAGE' || hasCancellation) {
      const tag = el('d3-tag d3-mode', rollModeWord(s.mode));
      tag.style.pointerEvents = 'auto';
      tag.title = rollModeHover(s.mode, s.sources);
      parts.push(tag);
    }
    chip.replaceChildren(...parts);
    chip.className = `dice3d-chip${s.crit ? ' crit' : s.fumble ? ' fumble' : ''}`;
    chip.dataset.kind = s.kind || 'plain';
    chip.style.setProperty('--dice3d-accent', theme.glow || theme.edge);
    const xs = dice.map((d) => d.x1), top = Math.min(...dice.map((d) => d.y1 - d.size * 1.35));
    chip.style.left = `${clamp((Math.min(...xs) + Math.max(...xs)) / 2, 140, W - 140)}px`;
    chip.style.top = `${Math.max(52, top)}px`;
    void chip.offsetWidth; // restart the fade-in transition
    chip.classList.add('show');
  }

  function announce(text) {
    live.textContent = '';
    win.setTimeout(() => { if (!destroyed) live.textContent = text; }, 30);
  }

  function resolvePending() { const p = pending; pending = null; if (p) p(); }

  function settle() {
    if (!animating) return;
    animating = false;
    win.cancelAnimationFrame(raf);
    win.clearTimeout(fallbackTimer);
    raf = 0;
    fade = 1;
    drawFrame(0, true);
    showChip();
    announce(`Rolled ${summary.text}${summary.crit ? '. Critical!' : summary.fumble ? '. Fumble.' : ''}`);
    resolvePending();
    hideTimer = win.setTimeout(fadeOut, HOLD_MS);
  }

  function fadeOut() {
    if (!chip) return;
    chip.classList.remove('show');
    let t0 = 0;
    const step = (now) => {
      if (!t0) t0 = now;
      fade = 1 - (now - t0) / FADE_MS;
      if (fade <= 0) { hideCanvas(); return; }
      drawFrame(0, true);
      raf = win.requestAnimationFrame(step);
    };
    raf = win.requestAnimationFrame(step);
  }

  function hideCanvas() {
    win.cancelAnimationFrame(raf);
    raf = 0;
    fade = 1;
    dice = [];
    if (canvas) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.style.display = 'none';
    }
  }

  function stopAll() {
    win.cancelAnimationFrame(raf);
    win.clearTimeout(hideTimer);
    win.clearTimeout(fallbackTimer);
    raf = 0;
    animating = false;
  }

  function roll(groups, meta = {}) {
    if (destroyed) return Promise.reject(new Error('Dice tray has been destroyed'));
    let specs;
    try {
      if (!Array.isArray(groups) || !groups.length) throw new TypeError('roll() needs at least one die group');
      specs = [];
      for (const g of groups) for (const s of expandGroup(g)) specs.push({ ...s, color: g.color, dim: false });
      for (const g of meta.discarded || []) for (const s of expandGroup(g)) specs.push({ ...s, color: g.color, dim: true });
    } catch (err) {
      return Promise.reject(err);
    }
    stopAll();
    resolvePending(); // a replaced roll counts as finished
    ensureDom();
    summary = { ...summarizeRoll(groups, meta), kind: meta.kind || 'plain' };
    dice = layout(specs);
    maxDelay = Math.max(...dice.map((d) => d.delay));
    fade = 1;
    animating = true;
    if (chip) chip.classList.remove('show');
    const promise = new Promise((resolve) => { pending = resolve; });
    const reduced = win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { settle(); return promise; }
    startTime = 0;
    raf = win.requestAnimationFrame(tick);
    // Background tabs pause rAF; never leave the caller waiting.
    fallbackTimer = win.setTimeout(settle, duration + maxDelay + 1500);
    return promise;
  }

  function clear() {
    stopAll();
    resolvePending();
    hideCanvas();
    if (chip) chip.classList.remove('show');
  }

  return {
    roll,
    setTheme(next) {
      theme = resolveTheme(next);
      if (chip) chip.style.setProperty('--dice3d-accent', theme.glow || theme.edge);
      if (dice.length && !animating && canvas && canvas.style.display !== 'none') drawFrame(0, true);
    },
    clear,
    destroy() {
      if (destroyed) return;
      clear();
      destroyed = true;
      for (const el of [canvas, chip, live]) if (el && el.parentNode) el.parentNode.removeChild(el);
      canvas = ctx = chip = null;
    },
    /** Debug/test hook: what each drawn die currently shows (value read back from its last drawn pose). */
    _snapshot() {
      return dice.map((d) => ({ sides: d.shape, role: d.role, dim: d.dim, requested: faceText(d.role, d.face),
        shown: d.lastQ ? faceText(d.role, topFace(d.shape, d.lastQ)) : null, x: d.x1, y: d.y1 }));
    },
  };
}
