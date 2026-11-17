// Indoor floors and tiles, and grass/forest outdoor variants (owner 2026-10-08, SON202 lane): ancient-China and
// cultivation-inspired looks for the painted-floor pipeline (static/tabletop/textures.js paintFloor/painter).
// Like every floor, these are only the look -- a named terrain painted on top is what gives a square its rules
// (combat/ground_text.py floor_reading says so on the hover card, from the style's key alone, unchanged here).
// Hooked into textures.js with the smallest possible change: STYLES gains these keys via ALL_STYLES, and
// painter() falls through to painter() here when textures.js has no style of its own by that name. Deterministic,
// same contract as every other floor: (squareX, squareY) -> [r, g, b], plus an optional decorate(ctx, pps, rand).

const TAU = Math.PI * 2;

// Floor-fraction of a value: always in [0,1), unlike JavaScript's `%` which returns a negative result for a
// negative operand (SON202 review: this dropped radial ticks/spokes across half of every medallion and
// formation circle, wherever atan2 returned a negative angle).
const fract = v => v - Math.floor(v);

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Value noise on a lattice, smooth-stepped, several octaves (a local copy of textures.js's own helper, so this
// file has no import cycle with the module that calls into it).
function makeNoise(seed) {
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

// Jittered cells (flagstones, temple slabs): distance to nearest and second-nearest point.
function makeCells(seed, spacing, widthSquares, heightSquares) {
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

const mix = (a, b, t) => a + (b - a) * t;
const smoothstep = (a, b, t) => { const u = Math.min(1, Math.max(0, (t - a) / (b - a))); return u * u * (3 - 2 * u); };
const ridge = (n, sharp) => Math.pow(1 - Math.abs(2 * n - 1), sharp);
const mulberryHash = value => mulberry32((value | 0) ^ 0x5bd1e995)();

// A scatter of small tinted ellipses with a soft contact shadow (leaves, petals, pebbles, mushroom caps).
function scatter(context, pps, rand, widthSquares, heightSquares, count, pick) {
  for (let index = 0; index < count; index += 1) {
    const x = rand() * widthSquares, y = rand() * heightSquares, item = pick(x, y, rand);
    if (!item) continue;
    const [rgb, length, width, alpha = 1] = item, angle = rand() * Math.PI;
    context.save();
    context.translate(x * pps, y * pps);
    context.rotate(angle);
    context.fillStyle = "rgba(0,0,0,0.22)";
    context.beginPath(); context.ellipse(width * 0.35 * pps, width * 0.5 * pps, length * pps / 2, width * pps / 2, 0, 0, TAU); context.fill();
    context.fillStyle = `rgba(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0},${alpha})`;
    context.beginPath(); context.ellipse(0, 0, length * pps / 2, width * pps / 2, 0, 0, TAU); context.fill();
    context.restore();
  }
}

// Pointy-top regular hexagons of circumradius `size` (square units): the Voronoi cell of a precise triangular
// lattice (no jitter) is exactly a regular hexagon, so this reuses the same nearest/second-nearest distance
// trick as makeCells, just over the lattice's own six neighbours instead of a 3x3 box.
function hexGrid(size) {
  const root3 = Math.sqrt(3);
  const neighbours = [[0, 0], [1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];
  const toXY = (q, r) => [size * root3 * (q + r / 2), size * 1.5 * r];
  return (x, y) => {
    const q = (root3 / 3 * x - y / 3) / size, r = (2 / 3 * y) / size;
    let rx = q, rz = r, ry = -rx - rz;
    let ix = Math.round(rx), iy = Math.round(ry), iz = Math.round(rz);
    const dx = Math.abs(ix - rx), dy = Math.abs(iy - ry), dz = Math.abs(iz - rz);
    if (dx > dy && dx > dz) ix = -iy - iz; else if (dy > dz) iy = -ix - iz;
    let d1 = Infinity, d2 = Infinity, id = 0;
    for (const [oq, or_] of neighbours) {
      const [cx, cy] = toXY(ix + oq, iz + or_), ex = x - cx, ey = y - cy, d = ex * ex + ey * ey;
      if (d < d1) { d2 = d1; d1 = d; id = mulberryHash((ix + oq) * 977 + (iz + or_) * 8161); } else if (d < d2) d2 = d;
    }
    return {id, edge: Math.sqrt(d2) - Math.sqrt(d1)};
  };
}

const P = {};

// ------------------------------------------------------------------------------------------------------ indoor

// Polished dark palace-hall planks: a gloss highlight runs down the middle of each board.
P.wood_palace = ({noise, fine, seed}) => {
  const plankWidth = 0.55, rand = mulberry32(seed + 201), offsets = Array.from({length: 512}, () => rand());
  return (x, y) => {
    const row = Math.floor(y / plankWidth), v = (y / plankWidth) % 1;
    const shift = offsets[row & 511] * 4, seg = Math.floor((x + shift) / 3.2), u = ((x + shift) / 3.2) % 1;
    const tone = offsets[(row * 7 + seg) & 511];
    const grain = Math.sin(y * 34 + noise(x * 0.5, y * 3.2) * 10) * 0.5 + 0.5;
    const seam = v < 0.05 || u < 0.01 ? 0.5 : 1;
    const sheen = Math.pow(Math.max(0, Math.sin((u - 0.5) * Math.PI)), 6) * 22;
    const base = 64 + tone * 26 + grain * 10 + (fine(x * 10, y * 30, 2) - 0.5) * 8;
    return [(base + sheen) * seam * 1.05, (base + sheen * 0.8) * seam * 0.58, (base + sheen * 0.6) * seam * 0.4];
  };
};

// Tatami-like woven mats as real 1x2 rectangles, their orientation alternating pinwheel-fashion every 2x2
// block (owner feedback: an earlier pass never grouped two squares into one mat shape, so it just read as
// yellow bricks): dark cloth binding on each mat's two LONG edges only, a lighter seam at its short ends, fine
// weave ridges running the length of the straw, and a muted straw-gold rather than green.
P.tatami = ({noise, fine, seed}) => (x, y) => {
  const unit = 2, bx = Math.floor(x / unit), by = Math.floor(y / unit);
  const horizontal = ((bx + by) & 1) === 0;
  const lx = x - bx * unit, ly = y - by * unit;
  let along, across, matIndex;
  if (horizontal) {
    const half = ly < 1 ? 0 : 1;
    along = lx; across = ly - half; matIndex = half;
  } else {
    const half = lx < 1 ? 0 : 1;
    along = ly; across = lx - half; matIndex = half + 2;
  }
  if (across < 0.07 || across > 0.93) return [40, 36, 24];
  if (along < 0.025 || along > 1.975) return [72, 64, 42];
  const weave = Math.sin(along * 36) * 0.5 + 0.5;
  const fleck = Math.sin(along * 110 + across * 9) * 0.5 + 0.5;
  const tone = mulberryHash(bx * 131 + by * 977 + matIndex * 17 + seed);
  const n = noise(x * 1.0, y * 1.0), f = fine(x * 14, y * 14, 2);
  const base = 150 + tone * 16 + weave * 14 + fleck * 5 + (n - 0.5) * 10 + (f - 0.5) * 8;
  return [base * 1.05, base * 0.90, base * 0.55];
};

// Grey square fired-clay tiles: plain unglazed squares with a dark grout line.
P.clay_tile = ({noise, fine, seed}) => (x, y) => {
  const tx = Math.floor(x), ty = Math.floor(y), u = x - tx, v = y - ty;
  if (u < 0.035 || v < 0.035 || u > 0.965 || v > 0.965) return [58, 54, 48];
  const tone = mulberryHash(tx * 131 + ty * 977 + seed);
  const n = noise(x * 0.9, y * 0.9), f = fine(x * 14, y * 14, 2);
  const base = 118 + tone * 30 + (n - 0.5) * 18 + (f - 0.5) * 14;
  return [base * 1.04, base * 0.92, base * 0.78];
};

// Glazed green (celadon-like) tiles: a soft glaze highlight, its angle varying tile to tile so many tiles
// together never read as a repeating diagonal stripe (owner feedback: the gloss was too strong and repetitive).
P.glazed_green_tile = ({noise, fine, seed}) => (x, y) => {
  const tx = Math.floor(x), ty = Math.floor(y), u = x - tx, v = y - ty;
  if (u < 0.03 || v < 0.03 || u > 0.97 || v > 0.97) return [30, 36, 32];
  const tone = mulberryHash(tx * 131 + ty * 977 + seed);
  const angle = mulberryHash(tx * 71 + ty * 977 + seed + 1) * Math.PI;
  const sheen = Math.pow(Math.max(0, Math.sin(u * Math.cos(angle) + v * Math.sin(angle) + Math.PI / 2)), 18) * 20;
  const n = noise(x * 0.6, y * 0.6), f = fine(x * 10, y * 10, 2);
  const base = 74 + tone * 18 + (n - 0.5) * 10 + (f - 0.5) * 8;
  return [base * 0.55, base * 1.1 + sheen, base * 0.76 + sheen * 0.5];
};

// Red lacquered floor: long glossy boards with their own cross-seams, a soft gloss reflection down each
// board's centre, and a paler, less glossy worn path where feet cross it most (owner feedback: board seams,
// a deep-red gloss with soft reflections, slight wear on traffic paths).
P.lacquer_red = ({noise, fine, seed}) => {
  const plankWidth = 0.6, boardLength = 2.4, rand = mulberry32(seed + 301), offsets = Array.from({length: 512}, () => rand());
  return (x, y) => {
    const row = Math.floor(y / plankWidth), v = (y / plankWidth) % 1;
    const seg = Math.floor(x / boardLength), u = (x / boardLength) % 1;
    const tone = offsets[row & 511], segTone = offsets[(row * 13 + seg) & 511];
    const seam = (v < 0.04 || u < 0.012) ? 0.62 : 1;
    const sheen = Math.pow(Math.max(0, Math.sin((v - 0.5) * Math.PI)), 4) * 32;
    const wear = smoothstep(0.35, 0.62, noise(x * 0.22, y * 0.22, 2)) * 0.3;
    const f = fine(x * 8, y * 20, 2), n = noise(x * 0.4, y * 2.2);
    const base = (90 + tone * 16 + segTone * 12 + (f - 0.5) * 12 + (n - 0.5) * 10) * seam;
    const lit = base + sheen;
    return [mix(lit * 1.52, lit * 1.18, wear), mix(lit * 0.26 + sheen * 0.5, lit * 0.48, wear), mix(lit * 0.24 + sheen * 0.3, lit * 0.44, wear)];
  };
};

// White jade or marble slabs, large and pale, with clearly visible green-grey veining (owner feedback: the
// veining read as too faint).
P.jade_marble = ({noise, fine, seed}) => (x, y) => {
  const tx = Math.floor(x / 1.6), ty = Math.floor(y / 1.6), u = x / 1.6 - tx, v = y / 1.6 - ty;
  if (u < 0.012 || v < 0.012 || u > 0.988 || v > 0.988) return [168, 160, 140];
  const shift = mulberryHash(tx * 71 + ty * 977 + seed) * 20;
  const swirl = noise(x * 0.18 + shift, y * 0.18, 3) * 8;
  const vein = Math.pow(1 - Math.abs(Math.sin(x * 0.5 + y * 0.35 + swirl)), 20);
  const vein2 = Math.pow(1 - Math.abs(Math.sin(x * 0.5 + y * 0.35 + swirl + 1.6)), 32) * 0.6;
  const v2 = Math.max(vein, vein2);
  const cloud = (noise(x * 0.5 + shift, y * 0.5, 3) - 0.5) * 16, f = fine(x * 7, y * 7, 2);
  const base = 220 + cloud + (f - 0.5) * 8;
  return [base - v2 * 56, base - v2 * 28, base - v2 * 48];
};

// Herringbone brick: true staggered herringbone -- rectangular bricks laid in alternating 45-degree zigzag
// courses, each brick's short end butting the long side of the next, forming V chevrons down the floor (SON202r2
// review: the previous pass was diagonal basket weave -- a pinwheel of two PARALLEL bricks per square block --
// which rotation alone can't turn into herringbone, since rotating a block grid never changes which bricks are
// adjacent to which). Worked out and verified with a throwaway Node script (coverage/overlap check over an
// exhaustive brick enumeration, an end-adjacency check confirming every brick's two short ends always butt a
// PERPENDICULAR brick never a parallel one, and a rendered PNG actually showing the chevrons) before porting in;
// the same end-adjacency invariant is checked against this real painter() in floor-art-indoor.test.mjs.
//
// Construction: work in a coordinate frame (a, b) rotated 45 degrees from the square grid, so an axis-aligned
// brick in that frame reads as a brick tilted 45 degrees on screen -- the classic way herringbone parquet is
// actually installed relative to a room. Lay unit-w cells (i, j) = (floor(a/w), floor(b/w)); a cell's role comes
// from s = (i + j) mod 4: s=0/1 is the left/right half of a horizontal (a-aligned) brick anchored at (i, j) /
// (i-1, j); s=2/3 is the bottom/top half of a vertical (b-aligned) brick anchored at (i, j) / (i, j-1). Every
// brick's two short ends land on a brick of the opposite orientation by construction (confirmed by the
// end-adjacency check above), which is what makes this herringbone rather than basket weave.
P.herringbone_brick = ({noise, fine, seed}) => {
  const w = 0.4, root2 = Math.SQRT2;
  return (x, y) => {
    const a = (x + y) / root2, b = (x - y) / root2;
    const i = Math.floor(a / w), j = Math.floor(b / w);
    const s = (((i + j) % 4) + 4) % 4;
    let bi, bj, horizontal;
    if (s === 0) { bi = i; bj = j; horizontal = true; }
    else if (s === 1) { bi = i - 1; bj = j; horizontal = true; }
    else if (s === 2) { bi = i; bj = j; horizontal = false; }
    else { bi = i; bj = j - 1; horizontal = false; }
    let u, v;
    if (horizontal) { u = (a - bi * w) / (2 * w); v = (b - bj * w) / w; }
    else { u = (b - bj * w) / (2 * w); v = (a - bi * w) / w; }
    if (u < 0.04 || u > 0.96 || v < 0.06 || v > 0.94) return [58, 50, 42];
    const brickIndex = horizontal ? bi * 131 + bj * 977 : bi * 977 + bj * 131 + 500000;
    const tone = mulberryHash(brickIndex + seed);
    const n = noise(x * 0.8, y * 0.8), f = fine(x * 12, y * 12, 2);
    const base = 150 + tone * 32 + (n - 0.5) * 16 + (f - 0.5) * 14;
    return [base * 1.05, base * 0.72, base * 0.5];
  };
};

// Hexagonal stone tiles, true regular hexagons with a mortar groove between them.
P.hex_stone = ({noise, fine}) => {
  const hex = hexGrid(0.62);
  return (x, y) => {
    const {id, edge} = hex(x, y);
    if (edge < 0.035) return [46, 46, 44];
    const n = noise(x * 0.6, y * 0.6), f = fine(x * 11, y * 11, 2);
    const base = 118 + id * 40 + (n - 0.5) * 20 + (f - 0.5) * 16 + Math.min(1, edge * 6) * 10;
    return [base * 1.0, base * 0.98, base * 0.93];
  };
};

// Bamboo slat floor: narrow rounded slats, each its own tone, a dark seam between them.
P.bamboo_slat = ({noise, fine, seed}) => {
  const slatW = 0.3, rand = mulberry32(seed + 501), offsets = Array.from({length: 256}, () => rand());
  return (x, y) => {
    const col = Math.floor(x / slatW), u = x / slatW - col;
    const tone = offsets[col & 255];
    const seam = u < 0.04 || u > 0.96 ? 0.55 : 1;
    const bulge = Math.sin(u * Math.PI) * 14;
    const n = noise(x * 2, y * 0.6), f = fine(x * 4, y * 12, 2);
    const base = (150 + tone * 40 + bulge + (f - 0.5) * 12 + (n - 0.5) * 10) * seam;
    return [base * 1.02, base * 0.94, base * 0.56];
  };
};

// Stone floor with a carved taiji/bagua medallion: a SINGLE large accent roughly 3x3 squares across, over a
// plain stone base that tiles on its own (owner feedback: a per-square repeat looked garish; this should be
// one placeable piece, not a pattern).
P.taiji_medallion = ({noise, fine, seed}) => (x, y) => {
  const period = 3;
  const bx = (Math.floor(x / period) + 0.5) * period, by = (Math.floor(y / period) + 0.5) * period;
  const n = noise(x * 0.5, y * 0.5), f = fine(x * 10, y * 10, 2);
  const base = 150 + (n - 0.5) * 14 + (f - 0.5) * 10;
  const lx = x - bx, ly = y - by, r = Math.hypot(lx, ly), a = Math.atan2(ly, lx), R = 1.15;
  if (r > R && r < R + 0.09) return [40, 38, 34];
  if (r >= R + 0.09 && r < R + 0.2) {
    const tick = Math.abs(fract(a / (Math.PI / 4) + 0.5) - 0.5) < 0.1;
    return tick ? [210, 190, 130] : [base * 0.9, base * 0.88, base * 0.8];
  }
  if (r <= R) {
    // The real S-boundary (SON202 review: the previous `ly<0`-only split put a flat disc in each half with a
    // straight horizontal seam between them, not a yin-yang swirl). A half's default fill is the side the swirl
    // head opens away from (`lx < 0`); the opposite bump carries the same colour into the far side of that half
    // so the two heads interlock, and each head's own small eye is the other colour.
    const topBump = Math.hypot(lx, ly + R / 2) < R / 2, bottomBump = Math.hypot(lx, ly - R / 2) < R / 2;
    const eyeTop = Math.hypot(lx, ly + R / 2) < R / 7, eyeBottom = Math.hypot(lx, ly - R / 2) < R / 7;
    const swirlBlack = ly < 0 ? (lx < 0 || topBump) : (lx < 0 && !bottomBump);
    const black = eyeTop ? false : eyeBottom ? true : swirlBlack;
    return black ? [26, 24, 22] : [220, 212, 190];
  }
  return [base, base * 0.98, base * 0.92];
};

// Cloud-pattern carved stone: pale slab with a soft scrolling relief of ruyi-cloud ridges.
P.cloud_stone = ({noise, fine}) => (x, y) => {
  const warp = noise(x * 0.22, y * 0.22, 3) * 5;
  const field = (xx, yy) => ridge(noise(xx * 0.5 + warp, yy * 0.5, 3), 3);
  const h = field(x, y), hx = field(x + 0.06, y) - h, hy = field(x, y + 0.06) - h;
  const light = -(hx + hy) * 200, carve = h * 24;
  const base = 168 + (noise(x * 0.5, y * 0.5) - 0.5) * 14 + (fine(x * 9, y * 9, 2) - 0.5) * 10 - carve + light;
  return [base * 1.0, base * 0.99, base * 0.95];
};

// Alchemy-hall clay tiles, scorched here and there by boiled-over pots and failed pills: dark burn rings,
// soot stains and a few visibly cracked tiles (owner feedback: no scorch was visible before).
P.alchemy_scorch = ({noise, fine, seed, widthSquares, heightSquares}) => {
  const base = P.clay_tile({noise, fine, seed});
  const paint = (x, y) => base(x, y);
  paint.decorate = (context, pps, rand) => {
    const count = Math.max(2, Math.round(widthSquares * heightSquares * 0.22));
    for (let i = 0; i < count; i += 1) {
      const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, r = (0.3 + rand() * 0.45) * pps;
      const gradient = context.createRadialGradient(x, y, 0, x, y, r);
      gradient.addColorStop(0, "rgba(6,5,4,0.88)"); gradient.addColorStop(0.4, "rgba(20,14,10,0.7)");
      gradient.addColorStop(0.7, "rgba(60,26,16,0.4)"); gradient.addColorStop(1, "rgba(60,26,16,0)");
      context.fillStyle = gradient;
      context.beginPath(); context.arc(x, y, r, 0, TAU); context.fill();
      context.strokeStyle = "rgba(12,9,7,0.6)"; context.lineWidth = Math.max(1, pps * 0.025);
      context.beginPath(); context.arc(x, y, r * 0.72, 0, TAU); context.stroke();
    }
    const cracked = Math.max(1, Math.round(widthSquares * heightSquares * 0.08));
    for (let i = 0; i < cracked; i += 1) {
      const tx = Math.floor(rand() * widthSquares), ty = Math.floor(rand() * heightSquares);
      const cx = (tx + 0.5) * pps, cy = (ty + 0.5) * pps, a = rand() * TAU;
      context.strokeStyle = "rgba(10,8,6,0.85)"; context.lineWidth = Math.max(1, pps * 0.02);
      context.beginPath(); context.moveTo(cx - Math.cos(a) * pps * 0.4, cy - Math.sin(a) * pps * 0.4);
      context.lineTo(cx + Math.cos(a) * pps * 0.4, cy + Math.sin(a) * pps * 0.4); context.stroke();
      context.beginPath(); context.moveTo(cx, cy);
      context.lineTo(cx + Math.cos(a + 1.3) * pps * 0.25, cy + Math.sin(a + 1.3) * pps * 0.25); context.stroke();
    }
    scatter(context, pps, rand, widthSquares, heightSquares, widthSquares * heightSquares * 2,
      (x, y, r) => (r() < 0.5 ? [[26, 22, 18], 0.03 + r() * 0.03, 0.02, 0.6] : null));
  };
  return paint;
};

// Sutra-hall wood: pale honeyed planks with woven rug runners laid across them at a steady interval. The
// runners repeat on a fixed period rather than a fraction of the whole map, so the look is the same whatever
// size area it is painted on, instead of depending on the map's own width (an earlier pass tied the runner to
// the full map's width, so painting it over a narrow area could show only rug or only wood).
P.sutra_hall_wood = ({noise, fine, seed}) => {
  const plankWidth = 0.5, period = 6, rugWidth = 2.2, rand = mulberry32(seed + 601), offsets = Array.from({length: 512}, () => rand());
  return (x, y) => {
    const row = Math.floor(y / plankWidth), v = (y / plankWidth) % 1;
    const shift = offsets[row & 511] * 4, seg = Math.floor((x + shift) / 3), u = ((x + shift) / 3) % 1;
    const tone = offsets[(row * 7 + seg) & 511];
    const seam = v < 0.05 || u < 0.012 ? 0.6 : 1;
    const f = fine(x * 10, y * 30, 2), n = noise(x * 0.5, y * 3);
    const wood = (128 + tone * 36 + (n - 0.5) * 14 + (f - 0.5) * 12) * seam;
    const px = ((x % period) + period) % period, rugLeft = (period - rugWidth) / 2;
    if (px > rugLeft && px < rugLeft + rugWidth) {
      const rv = y % 1, ru = (px - rugLeft) / rugWidth;
      if (rv < 0.06 || rv > 0.94 || ru < 0.02 || ru > 0.98) return [40, 30, 22];
      const weave = Math.sin(y * 50) * 0.5 + 0.5, rugTone = 70 + weave * 14 + (fine(x * 8, y * 8, 2) - 0.5) * 10;
      return [rugTone * 1.5, rugTone * 0.5, rugTone * 0.4];
    }
    return [wood * 1.08, wood * 0.82, wood * 0.52];
  };
};

// Formation-array floor: dark stone under faint luminous rings and spokes, a cultivation look.
P.formation_floor = ({noise, fine}) => {
  const period = 4, spokes = 12;
  return (x, y) => {
    const n = noise(x * 0.5, y * 0.5), f = fine(x * 10, y * 10, 2);
    const base = 46 + (n - 0.5) * 20 + (f - 0.5) * 14;
    const bx = (Math.floor(x / period) + 0.5) * period, by = (Math.floor(y / period) + 0.5) * period;
    const lx = x - bx, ly = y - by, r = Math.hypot(lx, ly), a = Math.atan2(ly, lx);
    let glow = 0;
    for (const rr of [0.55, 1.05, 1.5]) glow = Math.max(glow, smoothstep(0.035, 0, Math.abs(r - rr)));
    if (r > 0.4 && r < 1.6 && Math.abs(fract(a / (TAU / spokes) + 0.5) - 0.5) < 0.012) glow = Math.max(glow, 0.8);
    return [mix(base, 70, glow * 0.55), mix(base * 1.02, 130, glow * 0.55), mix(base * 1.1, 210, glow * 0.6)];
  };
};

// Worn temple flagstones: pale slabs, their joints and a few patches gone soft with moss.
P.temple_moss_flagstone = ({noise, fine, seed, widthSquares, heightSquares}) => {
  const cells = makeCells(seed + 701, 1.5, widthSquares, heightSquares);
  return (x, y) => {
    const {edge, id} = cells(x, y);
    const n = noise(x * 0.5, y * 0.5), f = fine(x * 7, y * 7, 2);
    const moss = smoothstep(0.03, 0.12, 0.12 - edge) * smoothstep(0.3, 0.6, noise(x * 0.6 + 9, y * 0.6, 3));
    const base = 128 + id * 30 + (n - 0.5) * 24 + (f - 0.5) * 16 - (edge < 0.05 ? 50 : edge < 0.1 ? 20 : 0);
    return [mix(base, 70, moss), mix(base, 96, moss), mix(base * 0.92, 56, moss)];
  };
};

// A rug/carpet overlay, decor only: a repeating diamond lattice, red field, gold border, indigo centres.
P.rug_geometric = ({noise, fine}) => (x, y) => {
  const cell = 0.9;
  const tx = Math.floor(x / cell), ty = Math.floor(y / cell), u = x / cell - tx, v = y / cell - ty;
  const diamond = Math.abs(u - 0.5) + Math.abs(v - 0.5);
  if (diamond > 0.46 && diamond < 0.5) return [196, 158, 70];
  if (diamond < 0.18) return [67, 34, 70];
  const shade = (noise(x * 0.4, y * 0.4) - 0.5) * 10 + (fine(x * 9, y * 9, 2) - 0.5) * 8;
  return [92 + shade, 24 + shade * 0.6, 26 + shade * 0.5];
};

// A rug/carpet overlay, decor only: a repeating eight-petal lotus roundel, burgundy field, cream petals.
P.rug_lotus = ({noise, fine}) => (x, y) => {
  const cell = 1.3, ty = Math.floor(y / cell);
  const offset = (ty % 2) * cell / 2;
  const u = ((x + offset) / cell) % 1 - 0.5, v = (y / cell) % 1 - 0.5;
  const r = Math.hypot(u, v), a = Math.atan2(v, u), petal = 0.3 + 0.05 * Math.cos(a * 8);
  if (Math.abs(r - petal) < 0.03) return [222, 206, 168];
  if (r < 0.12) return [196, 150, 70];
  const shade = (noise(x * 0.5, y * 0.5) - 0.5) * 10 + (fine(x * 8, y * 8, 2) - 0.5) * 8;
  return [74 + shade, 18 + shade * 0.6, 30 + shade * 0.5];
};

// ------------------------------------------------------------------------------------------------------ grass

// A lush meadow: deep saturated green with wind-blown clumps.
P.grass_meadow = ({noise, fine}) => (x, y) => {
  const n = noise(x * 0.4, y * 0.4), m = noise(x * 2 + 7, y * 2, 3), f = fine(x * 16, y * 16, 2);
  const clump = smoothstep(0.55, 0.72, m), g = 108 + (n - 0.5) * 34 + (f - 0.5) * 30 + clump * 22;
  return [48 + (f - 0.5) * 10, g, 38 + (n - 0.5) * 14];
};

// Dry autumn grass: desaturated straw-gold and russet, gone brittle (toned down from an earlier pass that
// read too orange).
P.grass_autumn = ({noise, fine}) => (x, y) => {
  const n = noise(x * 0.4, y * 0.4), m = noise(x * 1.8 + 3, y * 1.8, 3), f = fine(x * 15, y * 15, 2);
  const dry = smoothstep(0.4, 0.68, m), base = 142 + (n - 0.5) * 30 + (f - 0.5) * 20;
  return [base * mix(0.92, 0.84, dry), base * mix(0.78, 0.68, dry), base * mix(0.44, 0.36, dry)];
};

// A short trimmed courtyard lawn: faint mowing stripes, otherwise even and well-kept.
P.grass_lawn = ({noise, fine}) => (x, y) => {
  const stripe = Math.floor((x * Math.cos(0.26) + y * Math.sin(0.26)) / 1.1) & 1;
  const n = noise(x * 0.6, y * 0.6), f = fine(x * 20, y * 20, 2);
  const g = 112 + stripe * 10 + (n - 0.5) * 14 + (f - 0.5) * 12;
  return [44 + (f - 0.5) * 6, g, 40];
};

// A wildflower meadow: airy grass dotted with small white, yellow, pink and violet blooms.
P.grass_wildflower = ({noise, fine, widthSquares, heightSquares}) => {
  const paint = (x, y) => {
    const n = noise(x * 0.4, y * 0.4), f = fine(x * 16, y * 16, 2);
    const g = 104 + (n - 0.5) * 30 + (f - 0.5) * 28;
    return [44 + (f - 0.5) * 8, g + 6, 36];
  };
  paint.decorate = (context, pps, rand) => scatter(context, pps, rand, widthSquares, heightSquares, widthSquares * heightSquares * 3,
    (x, y, r) => {
      const colors = [[240, 240, 230], [244, 206, 60], [230, 120, 160], [170, 130, 220]];
      return r() < 0.7 ? [colors[Math.floor(r() * colors.length)], 0.04 + r() * 0.03, 0.04 + r() * 0.03, 0.9] : null;
    });
  return paint;
};

// Trampled grass: worn dirt patches at a scale that shows clearly within a few squares, grass flattened and
// thinning towards each one (an earlier wide, low-frequency path rarely showed within a small painted area).
P.grass_trampled = ({noise, fine}) => (x, y) => {
  const path = smoothstep(0.35, 0.65, noise(x * 0.45, y * 0.45, 2));
  const n = noise(x * 0.8, y * 0.8), f = fine(x * 14, y * 14, 2);
  const g = mix(100 + (n - 0.5) * 22, 68, path);
  return [mix(40, 90, path) + (f - 0.5) * 10, mix(g, 72, path), mix(30, 48, path)];
};

// Mountain alpine grass: short, cool-toned turf broken by lichen-flecked stones (owner feedback: the rocks
// blended into the grass almost invisibly; they are bigger and higher-contrast now).
P.grass_alpine = ({noise, fine, seed, widthSquares, heightSquares}) => {
  const rocks = makeCells(seed + 811, 1.1, widthSquares, heightSquares);
  return (x, y) => {
    const {edge, id} = rocks(x, y);
    const f = fine(x * 15, y * 15, 2);
    if (id > 0.58) {
      const t = (118 + id * 50 + (f - 0.5) * 18) * (edge < 0.055 ? 0.7 : 1);
      return [t * 0.95, t * 0.95, t * 1.02];
    }
    const n = noise(x * 0.5, y * 0.5), g = 92 + (n - 0.5) * 24 + (f - 0.5) * 18;
    return [46, g, 56 + (n - 0.5) * 10];
  };
};

// ------------------------------------------------------------------------------------------------------ forest

// A pine-needle floor: reddish duff with fine directional needle litter.
P.forest_pine_needle = ({noise, fine, widthSquares, heightSquares}) => {
  const paint = (x, y) => {
    const n = noise(x * 0.45, y * 0.45), f = fine(x * 13, y * 13, 3);
    const base = 92 + (n - 0.5) * 30 + (f - 0.5) * 26;
    return [base * 1.05, base * 0.7, base * 0.42];
  };
  paint.decorate = (context, pps, rand) => {
    context.lineCap = "round";
    for (let i = 0; i < widthSquares * heightSquares * 16; i += 1) {
      const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = rand() * Math.PI, l = (0.07 + rand() * 0.07) * pps;
      context.strokeStyle = `rgba(${150 + rand() * 40 | 0},${104 + rand() * 26 | 0},${50 + rand() * 16 | 0},0.75)`;
      context.lineWidth = Math.max(0.6, pps * 0.01);
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); context.stroke();
    }
  };
  return paint;
};

// A moss carpet: darker, varied cushiony greens with fine speckle, a few sprigs, and bare soil showing
// through in patches (owner feedback: an earlier pass was flat neon-green blobs).
P.forest_moss = ({noise, fine, widthSquares, heightSquares}) => {
  const paint = (x, y) => {
    const n = noise(x * 0.6, y * 0.6), bump = smoothstep(0.3, 0.7, noise(x * 1.3 + 3, y * 1.3, 3)), f = fine(x * 20, y * 20, 2);
    const soil = smoothstep(0.78, 0.88, noise(x * 0.9 + 17, y * 0.9, 2));
    const g = mix(58 + bump * 32 + (n - 0.5) * 18 + (f - 0.5) * 14, 50, soil);
    return [mix(22 + (f - 0.5) * 6, 56, soil), g, mix(26 + (n - 0.5) * 8, 38, soil)];
  };
  paint.decorate = (context, pps, rand) => {
    for (let i = 0; i < widthSquares * heightSquares * 10; i += 1) {
      const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, r = (0.012 + rand() * 0.02) * pps;
      context.fillStyle = `rgba(${40 + rand() * 50 | 0},${80 + rand() * 60 | 0},${40 + rand() * 30 | 0},0.55)`;
      context.beginPath(); context.arc(x, y, r, 0, TAU); context.fill();
    }
    for (let i = 0; i < widthSquares * heightSquares * 2; i += 1) {
      const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, a = rand() * TAU, l = (0.08 + rand() * 0.06) * pps;
      context.strokeStyle = "rgba(90,130,60,0.6)"; context.lineWidth = Math.max(0.6, pps * 0.01);
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); context.stroke();
    }
  };
  return paint;
};

// Fern undergrowth: lighter shadowed soil, densely covered by overlapping fronds seen from above (owner
// feedback: an earlier pass was too dark and sparse).
P.forest_fern = ({noise, fine, widthSquares, heightSquares}) => {
  const paint = (x, y) => {
    const n = noise(x * 0.5, y * 0.5), f = fine(x * 12, y * 12, 2);
    const base = 60 + (n - 0.5) * 22 + (f - 0.5) * 16;
    return [base * 0.82, base * 1.08, base * 0.5];
  };
  paint.decorate = (context, pps, rand) => {
    const fronds = Math.round(widthSquares * heightSquares * 5.5);
    for (let i = 0; i < fronds; i += 1) {
      const x = rand() * widthSquares * pps, y = rand() * heightSquares * pps, angle = rand() * TAU, length = (0.45 + rand() * 0.5) * pps;
      const shade = 0.6 + rand() * 0.5;
      context.strokeStyle = `rgba(${50 + rand() * 20 | 0},${100 + shade * 60 | 0},${44 + rand() * 20 | 0},0.92)`;
      context.lineWidth = Math.max(0.7, pps * 0.014);
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + Math.cos(angle) * length, y + Math.sin(angle) * length); context.stroke();
      for (let k = 1; k < 7; k += 1) {
        const t = k / 7, px = x + Math.cos(angle) * length * t, py = y + Math.sin(angle) * length * t, arm = length * 0.26 * (1 - t * 0.55);
        for (const side of [-1, 1]) {
          context.beginPath(); context.moveTo(px, py);
          context.lineTo(px + Math.cos(angle + side * 1.05) * arm, py + Math.sin(angle + side * 1.05) * arm);
          context.stroke();
        }
      }
    }
  };
  return paint;
};

// Autumn leaf litter: fallen leaves in red, orange, gold and brown, thick over dark earth.
P.forest_leaf_litter = ({noise, fine, widthSquares, heightSquares}) => {
  const paint = (x, y) => {
    const n = noise(x * 0.45, y * 0.45), f = fine(x * 12, y * 12, 3);
    const base = 60 + (n - 0.5) * 24 + (f - 0.5) * 18;
    return [base * 1.1, base * 0.74, base * 0.42];
  };
  paint.decorate = (context, pps, rand) => scatter(context, pps, rand, widthSquares, heightSquares, widthSquares * heightSquares * 11,
    (x, y, r) => {
      const tones = [[178, 86, 36], [204, 138, 40], [160, 50, 30], [214, 180, 60], [120, 70, 32]];
      return [tones[Math.floor(r() * tones.length)], 0.1 + r() * 0.12, 0.06 + r() * 0.05, 0.92];
    });
  return paint;
};

// Mushroom-dotted loam: lighter loam with a few clear mushroom clusters, caps visible from above, and
// scattered leaf bits (owner feedback: the mushrooms were tiny specks and the floor was too dark overall).
P.forest_mushroom_loam = ({noise, fine, widthSquares, heightSquares}) => {
  const paint = (x, y) => {
    const n = noise(x * 0.5, y * 0.5), f = fine(x * 13, y * 13, 3);
    const base = 70 + (n - 0.5) * 26 + (f - 0.5) * 18;
    return [base * 1.04, base * 0.86, base * 0.6];
  };
  paint.decorate = (context, pps, rand) => {
    const clusters = Math.max(1, Math.round(widthSquares * heightSquares * 0.3));
    for (let c = 0; c < clusters; c += 1) {
      const cx = rand() * widthSquares * pps, cy = rand() * heightSquares * pps;
      const count = 2 + Math.floor(rand() * 3);
      for (let i = 0; i < count; i += 1) {
        const x = cx + (rand() - 0.5) * pps * 0.3, y = cy + (rand() - 0.5) * pps * 0.3, r = (0.07 + rand() * 0.07) * pps;
        context.fillStyle = "rgba(0,0,0,0.32)";
        context.beginPath(); context.ellipse(x + r * 0.3, y + r * 0.4, r * 0.9, r * 0.55, 0, 0, TAU); context.fill();
        context.fillStyle = rand() < 0.35 ? `rgba(${206 + rand() * 30 | 0},60,54,0.95)` : `rgba(${222 + rand() * 20 | 0},${206 + rand() * 20 | 0},${168 + rand() * 20 | 0},0.95)`;
        context.beginPath(); context.ellipse(x, y, r, r * 0.65, 0, 0, TAU); context.fill();
        context.strokeStyle = "rgba(255,255,255,0.3)"; context.lineWidth = Math.max(0.6, pps * 0.01);
        context.beginPath(); context.arc(x, y, r * 0.95, Math.PI * 0.1, Math.PI * 0.5); context.stroke();
        context.fillStyle = "rgba(230,220,196,0.9)";
        context.beginPath(); context.ellipse(x, y + r * 0.2, r * 0.22, r * 0.3, 0, 0, TAU); context.fill();
      }
    }
    scatter(context, pps, rand, widthSquares, heightSquares, widthSquares * heightSquares * 5,
      (x, y, r) => [[150 + r() * 30, 110 + r() * 20, 70 + r() * 16], 0.09 + r() * 0.08, 0.045 + r() * 0.03, 0.85]);
  };
  return paint;
};

// Root-tangled ground: raised brown roots with a lit edge and a shadowed underside, so they read as roots
// crossing the soil rather than stains (owner feedback: the roots were faint orange lines).
P.forest_root_tangle = ({noise, fine, seed}) => {
  const rootA = makeNoise(seed + 911), rootB = makeNoise(seed + 913);
  return (x, y) => {
    const n = noise(x * 0.5, y * 0.5), f = fine(x * 13, y * 13, 2);
    const root = Math.max(ridge(rootA(x * 0.5, y * 0.5, 3), 16), ridge(rootB(x * 0.65 + 11, y * 0.65, 3), 20) * 0.9);
    const soil = 62 + (n - 0.5) * 20 + (f - 0.5) * 14;
    const grad = rootA(x * 0.5 + 0.03, y * 0.5 - 0.03, 3) - rootA(x * 0.5 - 0.03, y * 0.5 + 0.03, 3);
    const light = Math.max(0, grad) * 55, shadow = Math.max(0, -grad) * 70;
    const woodR = 100 + light * 0.8 - shadow, woodG = 74 + light * 0.55 - shadow * 0.85, woodB = 44 + light * 0.3 - shadow * 0.55;
    return [mix(soil, woodR, root), mix(soil * 0.84, woodG, root), mix(soil * 0.55, woodB, root)];
  };
};

// ------------------------------------------------------------------------------------------------------ exports

export const INDOOR_STYLES = Object.freeze({
  wood_palace: "Palace hall wood",
  tatami: "Tatami mats",
  clay_tile: "Fired-clay tile",
  glazed_green_tile: "Glazed green tile",
  lacquer_red: "Red lacquered floor",
  jade_marble: "White jade marble",
  herringbone_brick: "Herringbone brick",
  hex_stone: "Hexagonal stone tile",
  bamboo_slat: "Bamboo slat floor",
  taiji_medallion: "Taiji medallion tile",
  cloud_stone: "Cloud-carved stone",
  alchemy_scorch: "Scorched alchemy tile",
  sutra_hall_wood: "Sutra-hall wood",
  formation_floor: "Formation-array floor",
  temple_moss_flagstone: "Mossy temple flagstone",
  rug_geometric: "Geometric rug",
  rug_lotus: "Lotus rug",
});

export const GRASS_STYLES = Object.freeze({
  grass_meadow: "Lush meadow",
  grass_autumn: "Dry autumn grass",
  grass_lawn: "Trimmed courtyard lawn",
  grass_wildflower: "Wildflower meadow",
  grass_trampled: "Trampled grass",
  grass_alpine: "Alpine grass",
});

export const FOREST_STYLES = Object.freeze({
  forest_pine_needle: "Pine-needle floor",
  forest_moss: "Moss carpet",
  forest_fern: "Fern undergrowth",
  forest_leaf_litter: "Autumn leaf litter",
  forest_mushroom_loam: "Mushroom-dotted loam",
  forest_root_tangle: "Root-tangled ground",
});

// Groups for the editor's floor/paint pickers (mapeditor.js): plain names, grouped by kind.
export const GROUPS = [
  {label: "Indoor", styles: INDOOR_STYLES},
  {label: "Grass", styles: GRASS_STYLES},
  {label: "Forest floor", styles: FOREST_STYLES},
];

export const ALL_STYLES = Object.freeze({...INDOOR_STYLES, ...GRASS_STYLES, ...FOREST_STYLES});

// Every indoor floor is a built/laid surface; every grass and forest floor is a ground cover (board.js: owner
// 2026-10-08, "sharper tile with a thin border" for artificial floors meeting anything else -- natural ones
// keep blending into their neighbours). Data per look, same convention as this module's own style-label tables.
export const STYLE_KIND = Object.freeze({
  ...Object.fromEntries(Object.keys(INDOOR_STYLES).map(key => [key, "artificial"])),
  ...Object.fromEntries(Object.keys(GRASS_STYLES).map(key => [key, "natural"])),
  ...Object.fromEntries(Object.keys(FOREST_STYLES).map(key => [key, "natural"])),
});

// A thin border colour for each artificial look's own material: dark grout for tile/stone, a darker sill line
// for wood, the look's own woven binding/border colour for mats and rugs. Unset for natural looks (never read).
export const STYLE_BORDER = Object.freeze({
  wood_palace: [36, 26, 18],
  tatami: [40, 36, 24],
  clay_tile: [58, 54, 48],
  glazed_green_tile: [30, 36, 32],
  lacquer_red: [44, 20, 16],
  jade_marble: [150, 142, 124],
  herringbone_brick: [58, 50, 42],
  hex_stone: [46, 46, 44],
  bamboo_slat: [60, 54, 30],
  taiji_medallion: [40, 38, 34],
  cloud_stone: [140, 134, 122],
  alchemy_scorch: [58, 54, 48],
  sutra_hall_wood: [42, 32, 22],
  formation_floor: [30, 32, 36],
  temple_moss_flagstone: [60, 56, 40],
  rug_geometric: [196, 158, 70],
  rug_lotus: [196, 150, 70],
});

// textures.js's painter(style, seed, widthSquares, heightSquares, patch) falls through to this when it has no
// style of its own by that name; same contract, null when the style isn't one of ours.
export function painter(style, seed, widthSquares, heightSquares, patch = false) {
  const factory = P[style];
  if (!factory) return null;
  const noise = makeNoise(seed), fine = makeNoise(seed + 17);
  return factory({noise, fine, seed, widthSquares, heightSquares, patch});
}
