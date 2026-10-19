// node --test APP/static/tabletop/fog_memory_board.test.mjs
//
// Remembered fog on the real board. rememberFog() is taken from tabletop.js and run against the real createBoard(),
// so what is recorded per viewer and what a greyed square shows are both checked on the same objects the table uses.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from '../../tests/objects_dom_stub.mjs';
import {createBoard, initials, REMEMBERED_TIP} from './board.js';
import {emptyMemory, ghostCells, loadMemory, memoryKey, recordSeen, saveMemory} from './fog_memory.js';
import {createFogMemoryStore} from './fog_memory_store.js';
import {blockerSegments, visibilityPolygons} from './fog_polygon.js';
import {paintFloor} from './textures.js';
import {edgeTreatment} from './textures.js';

installDOM('<body></body>');

// Software alpha raster for the canvas calls setFog makes, so the tests read real per-pixel alpha instead of call
// records. Covers fillRect, polygon fill, clearRect, drawImage with source-over / destination-out / destination-in,
// and a blur filter (a Gaussian whose sigma is the blur radius, as CSS blur(Npx) is defined).
function insideSubpath(points, x, y) {
  let crossings = 0;
  for (let i = 0; i < points.length; i++) {
    const [a, b] = [points[i], points[(i + 1) % points.length]];
    if ((a[1] > y) !== (b[1] > y) && x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])) crossings++;
  }
  return crossings % 2 === 1;
}
// A raster canvas's toDataURL returns a traceable token too (rasterCanvasesByToken below), the same trick
// pixelCanvas uses, so a test can read back a CSS mask image (e.g. the remembered layer's applyRememberedCut
// cut) as real per-pixel alpha instead of trusting the string alone.
const rasterCanvasesByToken = new Map();
let rasterCanvasSerial = 0;
// Width and height are plain properties that reallocate the alpha buffer, as the canvas element does on resize.
function rasterCanvas(width, height) {
  const canvas = {_w: 0, _h: 0, alpha: new Float32Array(0)};
  const resize = () => { canvas.alpha = new Float32Array(canvas._w * canvas._h); };
  Object.defineProperties(canvas, {
    width: {get: () => canvas._w, set: v => { canvas._w = v; resize(); }, enumerable: true},
    height: {get: () => canvas._h, set: v => { canvas._h = v; resize(); }, enumerable: true},
  });
  canvas.width = width; canvas.height = height;
  canvas.getContext = () => new RasterContext(canvas);
  canvas.toDataURL = () => {
    const token = `data:raster-test;id=${rasterCanvasSerial++}`;
    rasterCanvasesByToken.set(token, canvas);
    return token;
  };
  return canvas;
}
function alphaOfFill(style) {
  if (typeof style !== 'string') return 1;
  const match = /rgba\([^)]*,\s*([\d.]+)\)/.exec(style);
  return match ? Number(match[1]) : 1;
}
class RasterContext {
  constructor(canvas) {
    this.canvas = canvas;
    this.fillStyle = '#fff';
    this.globalCompositeOperation = 'source-over';
    this.filter = 'none';
    this.subpaths = [];
  }
  // Writes `alpha` where `covered(px, py)` holds, under the current composite operation.
  composite(covered, alpha) {
    const {width, height, alpha: a} = this.canvas;
    for (let py = 0; py < height; py++) for (let px = 0; px < width; px++) {
      if (!covered(px, py)) continue;
      const i = py * width + px;
      if (this.globalCompositeOperation === 'destination-out') a[i] *= 1 - alpha;
      else if (this.globalCompositeOperation === 'destination-in') a[i] *= alpha;
      else a[i] += alpha * (1 - a[i]);
    }
  }
  // A fill under a blur filter is blurred as a whole, as the browser does: the fill is drawn to its own layer, blurred,
  // then composited. Without a filter it is painted directly.
  fillRect(x, y, w, h) {
    this.fillCoverage((px, py) => px + 0.5 >= x && px + 0.5 <= x + w && py + 0.5 >= y && py + 0.5 <= y + h);
  }
  fillCoverage(covered) {
    const alpha = alphaOfFill(this.fillStyle);
    if (!this.filter.startsWith('blur(')) { this.composite(covered, alpha); return; }
    const {width, height} = this.canvas;
    const layer = new Float32Array(width * height);
    for (let py = 0; py < height; py++) for (let px = 0; px < width; px++) if (covered(px, py)) layer[py * width + px] = alpha;
    const blurred = gaussianBlur(layer, width, height, Number.parseFloat(this.filter.slice(5)));
    const a = this.canvas.alpha;
    for (let i = 0; i < width * height; i++) {
      if (this.globalCompositeOperation === 'destination-out') a[i] *= 1 - blurred[i];
      else if (this.globalCompositeOperation === 'destination-in') a[i] *= blurred[i];
      else a[i] += blurred[i] * (1 - a[i]);
    }
  }
  clearRect(x, y, w, h) {
    const {width, alpha: a} = this.canvas;
    for (let py = 0; py < this.canvas.height; py++) for (let px = 0; px < width; px++)
      if (px + 0.5 >= x && px + 0.5 <= x + w && py + 0.5 >= y && py + 0.5 <= y + h) a[py * width + px] = 0;
  }
  rect(x, y, w, h) { this.subpaths.push([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]); }
  beginPath() { this.subpaths = []; }
  moveTo(x, y) { this.subpaths.push([[x, y]]); }
  lineTo(x, y) { this.subpaths[this.subpaths.length - 1].push([x, y]); }
  closePath() {}
  fill() {
    const subpaths = this.subpaths;
    this.fillCoverage((px, py) => subpaths.some(points => insideSubpath(points, px + 0.5, py + 0.5)));
  }
  drawImage(source) {
    const {width, height, alpha: a} = this.canvas;
    let src = source.alpha;
    if (this.filter.startsWith('blur(')) src = gaussianBlur(src, width, height, Number.parseFloat(this.filter.slice(5)));
    const before = a.slice();
    for (let i = 0; i < width * height; i++) {
      const s = src[i];
      if (this.globalCompositeOperation === 'destination-out') a[i] = before[i] * (1 - s);
      else if (this.globalCompositeOperation === 'destination-in') a[i] = before[i] * s;
      else a[i] = s + before[i] * (1 - s);
    }
  }
}
// Separable Gaussian with sigma = the blur radius, as CSS blur(Npx) is defined. Its tail reaches past the inset square,
// so a seed that is not clipped to the saved cells really does light the neighbours.
function gaussianBlur(src, width, height, sigma) {
  if (!(sigma > 0)) return Float32Array.from(src);
  const r = Math.ceil(sigma * 3);
  const kernel = Array.from({length: 2 * r + 1}, (_, i) => Math.exp(-((i - r) ** 2) / (2 * sigma * sigma)));
  const norm = kernel.reduce((a, b) => a + b, 0);
  const rows = new Float32Array(width * height), out = new Float32Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    let sum = 0;
    for (let k = -r; k <= r; k++) { const xx = x + k; if (xx >= 0 && xx < width) sum += src[y * width + xx] * kernel[k + r]; }
    rows[y * width + x] = sum / norm;
  }
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    let sum = 0;
    for (let k = -r; k <= r; k++) { const yy = y + k; if (yy >= 0 && yy < height) sum += rows[yy * width + x] * kernel[k + r]; }
    out[y * width + x] = sum / norm;
  }
  return out;
}

// Scratch canvases setFog makes (the sight mask, the explored accumulator, the seed) are rasters only while setFog runs,
// so the rest of the board keeps the stub's canvases.
let rasterOn = false;
// A real pixel buffer for the canvas calls textures.js paintFloor and board.js floorSwatchUrl make (REMEMBERART), so a
// test can read back the actual painted ground colours instead of the stub's inert, content-free canvas, through the
// real setRemembered() rendering path (review finding 4: a test must exercise that path, not call paintFloor alone).
// paintFloor paints with putImageData, not fillRect; floorSwatchUrl crops with drawImage(source, sx,sy,sw,sh, dx,dy,dw,dh).
// toDataURL returns a traceable token (pixelCanvasesByToken below), not a real encoded image: nothing here decodes PNGs.
const pixelCanvasesByToken = new Map();
let pixelCanvasSerial = 0;
function pixelCanvas() {
  const canvas = {_w: 0, _h: 0, pixels: new Uint8ClampedArray(0)};
  const resize = () => { canvas.pixels = new Uint8ClampedArray(canvas._w * canvas._h * 4); };
  Object.defineProperties(canvas, {
    width: {get: () => canvas._w, set: v => { canvas._w = v; resize(); }, enumerable: true},
    height: {get: () => canvas._h, set: v => { canvas._h = v; resize(); }, enumerable: true},
  });
  const context = {
    fillStyle: '#000', strokeStyle: '#000', filter: 'none', globalCompositeOperation: 'source-over',
    paths: [], clips: null, stack: [], lineWidth: 1,
    createImageData: (w, h) => ({width: w, height: h, data: new Uint8ClampedArray(w * h * 4)}),
    putImageData(image) { canvas.pixels = Uint8ClampedArray.from(image.data); },
    createRadialGradient: () => ({addColorStop() {}}),
    createLinearGradient: () => ({addColorStop() {}}),
    // source, then either (dx, dy) for a full copy or (sx, sy, sw, sh, dx, dy, dw, dh) for a crop/scale -- the two
    // shapes floorSwatchUrl and applyRememberedCut each use. A source with no real pixels (e.g. the fog's litMask,
    // painted outside the raster window) is skipped rather than guessed at.
    drawImage(source, ...rest) {
      if (!source?.pixels) return;
      const [sx, sy, sw, sh, dx, dy, dw, dh] = rest.length >= 8 ? rest
        : [0, 0, source.width, source.height, rest[0] || 0, rest[1] || 0, source.width, source.height];
      const src = source.pixels, srcW = source.width, dstW = canvas.width;
      for (let yy = 0; yy < canvas.height; yy += 1) {
        const sy2 = Math.floor(sy + ((yy + 0.5 - dy) * sh) / dh);
        for (let xx = 0; xx < dstW; xx += 1) {
          if (xx + 0.5 < dx || xx + 0.5 >= dx + dw || yy + 0.5 < dy || yy + 0.5 >= dy + dh) continue;
          const sx2 = Math.floor(sx + ((xx + 0.5 - dx) * sw) / dw);
          if (sx2 < 0 || sx2 >= srcW || sy2 < 0 || sy2 >= source.height) continue;
          // Area resampling for smaller crops retains sub-pixel seam strokes;
          // copying just one nearest pixel can erase a one-pixel border entirely.
          const x0 = sx + (xx - dx) * sw / dw, x1 = x0 + sw / dw;
          const y0 = sy + (yy - dy) * sh / dh, y1 = y0 + sh / dh;
          const color = [0, 0, 0]; let alpha = 0, area = 0;
          for (let py = Math.max(0, Math.floor(y0)); py < Math.min(source.height, Math.ceil(y1)); py++) {
            for (let px = Math.max(0, Math.floor(x0)); px < Math.min(srcW, Math.ceil(x1)); px++) {
              const weight = Math.max(0, Math.min(x1, px + 1) - Math.max(x0, px)) * Math.max(0, Math.min(y1, py + 1) - Math.max(y0, py));
              const si = (py * srcW + px) * 4, a = src[si + 3] / 255;
              area += weight; alpha += a * weight;
              for (let c = 0; c < 3; c++) color[c] += src[si + c] * a * weight;
            }
          }
          this.pixel(xx, yy, color.map(c => alpha ? c / alpha : 0), area ? alpha / area : 0);
        }
      }
    },
    pixel(x, y, color, a) {
      if (this.clips && !this.clips.some(p => insideSubpath(p, x + 0.5, y + 0.5))) return;
      const i = (y * canvas.width + x) * 4, dst = canvas.pixels, da = dst[i + 3] / 255;
      if (this.globalCompositeOperation === 'destination-out') { dst[i + 3] *= 1 - a; return; }
      if (this.globalCompositeOperation === 'source-in') {
        for (let c = 0; c < 3; c++) dst[i + c] = color[c];
        dst[i + 3] = a * da * 255; return;
      }
      const out = a + da * (1 - a);
      for (let c = 0; c < 3; c++) dst[i + c] = out ? (color[c] * a + dst[i + c] * da * (1 - a)) / out : 0;
      dst[i + 3] = out * 255;
    },
    fillRect(x, y, w, h) {
      // Gradient decoration is outside these seam assertions. The blend mask's
      // solid fill, Gaussian blur, clip and Porter-Duff operations are real.
      if (typeof this.fillStyle !== 'string') return;
      const color = this.fillStyle === '#000' ? [0, 0, 0] : (this.fillStyle.match(/[\d.]+/g)?.map(Number) || [255, 255, 255]);
      const {width, height} = canvas;
      let layer = new Float32Array(width * height);
      for (let py = 0; py < height; py++) for (let px = 0; px < width; px++)
        if (px + 0.5 >= x && px + 0.5 < x + w && py + 0.5 >= y && py + 0.5 < y + h) layer[py * width + px] = 1;
      if (this.filter.startsWith('blur(')) layer = gaussianBlur(layer, width, height, Number.parseFloat(this.filter.slice(5)));
      for (let py = 0; py < height; py++) for (let px = 0; px < width; px++) this.pixel(px, py, color, layer[py * width + px]);
    },
    clearRect() { canvas.pixels.fill(0); },
    save() { this.stack.push({clips: this.clips, filter: this.filter, fillStyle: this.fillStyle, globalCompositeOperation: this.globalCompositeOperation}); },
    restore() { Object.assign(this, this.stack.pop()); },
    beginPath() { this.paths = []; },
    rect(x, y, w, h) { this.paths.push([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]); },
    clip() { this.clips = this.paths; },
    fill() {},
    moveTo(x, y) { this.paths.push([[x, y]]); },
    lineTo(x, y) { this.paths.at(-1).push([x, y]); },
    stroke() {
      const color = this.strokeStyle.match(/[\d.]+/g).map(Number);
      for (const [a, b] of this.paths) {
        if (!b) continue;
        const half = this.lineWidth / 2;
        this.save(); this.fillStyle = `rgb(${color.join(',')})`;
        this.fillRect(Math.min(a[0], b[0]) - half, Math.min(a[1], b[1]) - half,
          Math.abs(b[0] - a[0]) + 2 * half, Math.abs(b[1] - a[1]) + 2 * half);
        this.restore();
      }
    },
  };
  canvas.getContext = () => context;
  canvas.toDataURL = () => {
    const token = `data:pixel-test;id=${pixelCanvasSerial++}`;
    pixelCanvasesByToken.set(token, canvas);
    return token;
  };
  return canvas;
}
// The real pixel buffer a pixelCanvas's traceable toDataURL() token stands for, or null for an ordinary href
// (no pixel data behind it -- the stub's constant placeholder, or no image at all).
const pixelsFromHref = href => pixelCanvasesByToken.get(href) || null;
// The real alpha buffer a rasterCanvas's traceable toDataURL() token stands for, parsed out of a CSS
// `url(data:raster-test;id=N)` mask-image string, or null for anything else (e.g. 'none').
const alphaFromHref = url => rasterCanvasesByToken.get((/^url\((.*)\)$/.exec(url) || [])[1]) || null;
let pixelRasterOn = false;
// REMEMBERART2: board.js's own persistent canvases (the live floor, built once by createBoard, long before any
// test turns pixelRasterOn on around setMap/setFog/setRemembered) stay the stub's inert Element otherwise, so a
// capture cropped straight from one of them would see no real pixels. Wires a real pixel buffer onto the
// existing element in place, keeping the stub's own properties (hidden, dataset, ...) board.js still depends on.
function upgradeToPixelCanvas(element) {
  const backing = pixelCanvas();
  Object.defineProperties(element, {
    width: {get: () => backing.width, set: v => { backing.width = v; }, configurable: true},
    height: {get: () => backing.height, set: v => { backing.height = v; }, configurable: true},
    pixels: {get: () => backing.pixels, configurable: true},
  });
  element.getContext = () => backing.getContext();
  element.toDataURL = () => backing.toDataURL();
  return element;
}
// A loaded <img> stand-in for an uploaded background: natural size plus real pixels, so
// backgroundComposition's drawImage(bgImage, ...) crop reads real content instead of being skipped.
function upgradeToPixelImage(element, width, height, pixels) {
  element.naturalWidth = width; element.naturalHeight = height;
  element.width = width; element.height = height;
  element.pixels = pixels;
  return element;
}
const realCreateElement = document.createElement.bind(document);
document.createElement = tag => {
  if (pixelRasterOn && tag === 'canvas') return pixelCanvas();
  if (rasterOn && tag === 'canvas') return rasterCanvas(0, 0);
  return realCreateElement(tag);
};
const WIDTH = 4, HEIGHT = 2;
const at = (x, y) => y * WIDTH + x;
const CELL = 64;
const seenOnly = indexes => {
  const seen = new Uint8Array(WIDTH * HEIGHT);
  for (const index of indexes) seen[index] = 1;
  return seen;
};

const tabletopSource = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');
const tabletopFunction = name => {
  const start = tabletopSource.indexOf(`function ${name}(`);
  return tabletopSource.slice(start, tabletopSource.indexOf('\n}\n', start) + 3);
};
const rememberFogSource = tabletopFunction('rememberFog');
const rememberedCellsSource = tabletopFunction('rememberedCells');

const map = ruleTerrain => ({width: WIDTH, height: HEIGHT, background: {url: null, opacity: 1, style: 'flagstone', seed: 1},
  display: {}, walls: [], trees: [], ruleTerrain, cells: {blocked: [], cover: [], hazard: [], difficult: [], sightGhost: []}});
const coverRow = {type: 'SIMPLE_COVER', look: 'low_wall', cells: [[2, 1]]};
const zoneRow = {zone_id: 'ember', source_definition_id: 'fog.test', affected_cells: [[2, 1]], center: [2, 1], radius_cells: 0,
  trigger_profile: {kind: 'TYPED', name: 'Ember Pool', visual: {material: 'fire'}}};
const goblin = (id, x, y, team = 1) => ({entity_id: id, display_name: 'Goblin', position: {x, y}, team});

// A viewer's session: the real rememberFog bound to a real board and a storage that outlives a "reload".
function session({storage = new Map(), objects = [], owned = [], unseen = [], gm = false, backend} = {}) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  let helpers;
  const board = createBoard(host, {onFloorReady: () => {
    helpers.refreshFloorMemory();
  }});
  const store = {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)};
  const app = {matchId: 'match-1', fog: 'on', state: {objects}, fogMemory: null};
  const fogMemoryStore = backend ? createFogMemoryStore({storage: store, backend}) :
    {read: key => app.fogMemory?.key === key ? app.fogMemory.memory : loadMemory(store, key),
      ready: () => true, save: (key, memory) => saveMemory(store, key, memory)};
  const bindings = {app, board, isGMView: () => gm, memoryKey, loadMemory, saveMemory, recordSeen, ghostCells, emptyMemory, fogMemoryStore,
    preferenceStorage: store, viewerStore: {viewId: 'viewer-a'},
    isOwnedActor: actor => owned.includes(actor.entity_id), unseenByViewers: actor => unseen.includes(actor.entity_id),
    initials, TEAM_HEX: ['#fff', '#f00'], teamIndex: actor => actor.team || 0};
  helpers = new Function(...Object.keys(bindings), `${rememberedCellsSource}\n${rememberFogSource}\n${tabletopFunction('refreshFloorMemory')}\nreturn {rememberedCells, rememberFog, refreshFloorMemory};`)(...Object.values(bindings));
  return {board, app, rememberFog: helpers.rememberFog, rememberedCells: helpers.rememberedCells, storage, fogMemoryStore};
}

test('table captures survive a quota-limited reload without losing unseen ground, creatures or objects', async () => {
  const key = memoryKey('match-1', 'viewer-a:on', WIDTH, HEIGHT);
  const old = {version: 3, cells: {0: {terrain: [], zones: [], floor: {style: 'wood', seed: 7, patch: false},
    tokens: [{id: 'old-goblin'}], objects: [{id: 'old-chest'}]}}};
  class LimitedStorage extends Map {
    // Pixel harness URLs are short trace tokens; a small remaining quota models
    // an origin already occupied by other fights/preferences.
    set(k, value) { if (value.length > 400) throw new Error('QuotaExceededError'); return super.set(k, value); }
  }
  const storage = new LimitedStorage([[key, JSON.stringify(old)]]);
  const snapshots = new Map();
  const backend = {get: async k => structuredClone(snapshots.get(k)),
    set: async (k, value) => snapshots.set(k, structuredClone(value))};
  const first = session({storage, backend});
  first.board.setMap({...map([]), background: {style: 'plain', seed: 1, opacity: 1}});
  const seen = seenOnly(Array.from({length: WIDTH * HEIGHT - 1}, (_, i) => i + 1));
  assert.equal(first.rememberFog(seen, [], new Set()), null, 'the real table cannot capture over a loading save');
  assert.equal(first.app.fogMemory, null);
  await first.fogMemoryStore.flush(key);
  let next;
  pixelRasterOn = true;
  try {
    // Repaint now with the pixel canvas enabled, then use the production snapshot path.
    upgradeToPixelCanvas(first.board.element.querySelector('.tt-bg-floor'));
    first.board.setMap({...map([]), background: {style: 'plain', seed: 2, opacity: 1}});
    next = first.rememberFog(seen, [], new Set());
  } finally { pixelRasterOn = false; }
  assert.ok(JSON.stringify(next.cells).length > 400, 'captured ground exceeds the local quota');
  for (let i = 1; i < WIDTH * HEIGHT; i++) assert.ok(pixelsFromHref(next.cells[i].floor.swatch), 'the table stored a sight-time pixel crop');
  await first.fogMemoryStore.flush(key);
  assert.deepEqual(JSON.parse(storage.get(key)), old, 'localStorage still contains the pre-quota snapshot');
  const reloaded = session({storage, backend});
  reloaded.board.setMap(map([]));
  reloaded.rememberedCells();
  await reloaded.fogMemoryStore.flush(key);
  assert.deepEqual(reloaded.rememberedCells().cells, next.cells, 'all accumulated sight-time pixels reload exactly');
  assert.deepEqual(reloaded.rememberedCells().cells[0], old.cells[0], 'unseen old ground, creature and object survive');
  assert.equal(Object.keys(next.cells).length, WIDTH * HEIGHT);
});

// Draw the remembered squares the way tabletop.js does: one board, live map as given, memory as returned.
function look(s, {ruleTerrain = [], zones = [], seen, actors = []}) {
  s.board.setMap(map(ruleTerrain));
  s.board.setZones(zones, {round: 1});
  s.board.setFog(seen);
  s.board.setRemembered(s.rememberFog(seen, actors, new Set(s.app.state.objects.map(row => row.id))));
}


// A session whose fog canvas is a raster. Returns the session; the raster is the board's fog canvas.
function rasterSession(opts) {
  const s = session(opts);
  const fog = s.board.element.querySelector('.tt-fog');
  const canvas = rasterCanvas(WIDTH * CELL, HEIGHT * CELL);
  fog.getContext = () => canvas.getContext();
  s.fogCanvas = canvas;
  return s;
}
// Runs setFog with the scratch canvases as rasters, then returns the fog canvas's per-pixel alpha.
function paintFog(s, seen, explored = null, saved = null, geometry = {}) {
  rasterOn = true;
  try { s.board.setFog(seen, explored, geometry, saved); } finally { rasterOn = false; }
  return s.fogCanvas;
}
// Alpha at a cell's centre: 0.933 never seen, 0.4 explored, 0 in sight this frame.
const alphaAt = (canvas, x, y) => canvas.alpha[(y * CELL + CELL / 2) * canvas.width + x * CELL + CELL / 2];

const tiles = board => board.element.querySelectorAll('.tt-remembered-tile');
const tileAt = (board, x, y) => tiles(board).find(tile => tile.getAttribute('x') === String(x) && tile.getAttribute('y') === String(y));
// Backing and artwork have separate masks; find this tile's artwork by its board coordinates.
const groupOf = tile => {
  const layer = tile.parentNode.classList.contains('tt-remembered-backing') ? tile.parentNode.parentNode : tile.parentNode;
  const image = layer.querySelectorAll('.tt-remembered-floor').find(image =>
    image.getAttribute('x') === tile.getAttribute('x') && image.getAttribute('y') === tile.getAttribute('y'));
  return image ? image.parentNode.parentNode : tile.parentNode;
};

test('a square seen then unseen is drawn greyed with the terrain, zone and creature it had when last seen', () => {
  const storage = new Map();
  const chest = {id: 'chest', name: 'Chest', kind: 'chest', x: 2, y: 1, hp: 10};
  const s = session({storage, objects: [chest]});
  look(s, {ruleTerrain: [coverRow], zones: [zoneRow], seen: seenOnly([at(2, 1)]), actors: [goblin('gob', 2, 1)]});
  // The viewer looks elsewhere: the cover, zone and goblin are gone from the live map.
  look(s, {ruleTerrain: [], zones: [], seen: seenOnly([at(0, 0)]), actors: []});

  const tile = tileAt(s.board, 2, 1);
  assert.ok(tile, 'the square is drawn as remembered');
  const group = groupOf(tile);
  assert.equal(group.querySelectorAll('.tt-rule-terrain').length, 1, 'the cover it had is drawn, though the live map no longer has it');
  assert.equal(group.querySelectorAll('.tt-remembered-zone').length, 1, 'the zone it was in is drawn');
  assert.equal(group.querySelectorAll('.tt-remembered-mark')[0]?.textContent, initials('Goblin'), 'the goblin it had is marked');
});

test('a remembered square that has not changed draws no opaque tile, so its live art shows through dimmed', () => {
  const s = session({storage: new Map(), objects: []});
  look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(2, 1)])});
  look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(0, 0)])});
  assert.equal(tileAt(s.board, 2, 1), undefined, 'an unchanged remembered square is not an opaque tile');
  assert.equal(tiles(s.board).length, 0, 'no remembered square is drawn over the live map');
  // The square is seen again, so it is no longer remembered.
  look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(2, 1)])});
  assert.equal(tileAt(s.board, 2, 1), undefined, 'a square in view is not remembered');
});

test('a remembered square that changed while unseen shows the old record, not the live map', () => {
  const s = session({storage: new Map(), objects: []});
  look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(2, 1)])});
  // The cover is removed while the viewer looks elsewhere: the square now differs from its record.
  look(s, {ruleTerrain: [], seen: seenOnly([at(0, 0)])});
  const tile = tileAt(s.board, 2, 1);
  assert.ok(tile, 'a changed remembered square is drawn from its record');
  assert.equal(groupOf(tile).querySelectorAll('.tt-rule-terrain').length, 1, 'the old cover is drawn, not the live map');
  assert.equal(tile.parentNode.parentNode.style.maskImage.startsWith('url('), true,
    'the remembered layer is cut along the live sight shape, so the opaque base never covers what is seen now');
});

test('the remembered layer is not cut when nothing changed; only the fog wash is applied', () => {
  const s = session({storage: new Map(), objects: []});
  look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(2, 1)])});
  look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(0, 0)])});
  assert.equal(s.board.element.querySelector('.tt-remembered-layer').style.maskImage, 'none');
});

// visibility() from tabletop.js, bound to a session's board and saved record, with no live viewer to see from.
const visibilitySource = tabletopFunction('visibility');
function visibilityOf(s) {
  const bindings = {app: s.app, board: s.board, isGMView: () => false, rememberedCells: s.rememberedCells,
    fogAudience: () => [], perceivedCells: () => { throw new Error('no live viewers'); }};
  return new Function(...Object.keys(bindings), `${visibilitySource}\nreturn visibility();`)(...Object.values(bindings));
}

// A reload with no live sight: the saved record is read by the real visibility(), then painted through the same
// setFog argument renderTokens passes (app.savedExplored). Dropping either link leaves the saved square fully fogged.
test('a reload with no live sight: visibility() saves the remembered square and the board paints it dimmed', () => {
  const storage = new Map();
  look(session({storage}), {ruleTerrain: [coverRow], seen: seenOnly([at(2, 1)])});
  const reloaded = rasterSession({storage});
  reloaded.board.setMap(map([coverRow]));
  const seen = visibilityOf(reloaded);
  assert.equal(reloaded.app.savedExplored[at(2, 1)], 1, 'visibility() saves the remembered square');
  assert.equal(seen[at(2, 1)], 0, 'nothing is in live sight');
  paintFog(reloaded, seen, reloaded.app.explored, reloaded.app.savedExplored, {polygons: []});
  assert.ok(Math.abs(alphaAt(reloaded.fogCanvas, 2, 1) - 0.4) < 0.05, 'the remembered square is dimmed, not fully fogged');
  assert.ok(alphaAt(reloaded.fogCanvas, 0, 0) > 0.9, 'a never-seen square keeps the full wash');
});

test('renderTokens hands the saved record to setFog as its fourth argument', () => {
  assert.match(tabletopSource, /board\.setFog\(seen, app\.explored, fogGeometry\(seen\), app\.savedExplored\);/);
});


// Partly lit square: a viewer in the left room sees through a doorway (wall x=2, gap y=1), so (3,0) is lit only at its
// lower-left corner. Its centre is dark, and the old seed read the centre, so it dimmed the whole square.
const DOOR = {walls: [{shape: 'line', points: [[2, 0], [2, 1]]}]};
const doorSight = viewer => ({polygons: visibilityPolygons([viewer], blockerSegments({walls: DOOR.walls, width: WIDTH, height: HEIGHT}), WIDTH, HEIGHT)});
// Whether a point (in cell units) lies inside the lit shape.
const insideLit = (sight, x, y) => sight.polygons.some(polygon => insideSubpath(polygon.points, x, y));
// Pixel-level check: pixels of a cell whose centre lies outside the lit shape keep the full wash.
function cellSamples(canvas, x, y) {
  const samples = [];
  for (let py = 0; py < CELL; py += 4) for (let px = 0; px < CELL; px += 4)
    samples.push({px: x * CELL + px + 0.5, py: y * CELL + py + 0.5, alpha: canvas.alpha[(y * CELL + py) * canvas.width + x * CELL + px]});
  return samples;
}
// Seen-this-frame cells, marked explored the way tabletop.js marks them before setFog.
function frameExplored(indexes, explored = new Uint8Array(WIDTH * HEIGHT)) {
  for (const index of indexes) explored[index] = 1;
  return explored;
}

test('a fresh view of a partly lit doorway square leaves the unlit part at full fog, now and after the viewer moves away', () => {
  const s = rasterSession({storage: new Map(), objects: []});
  s.board.setMap(map([]));
  s.board.setZones([], {round: 1});
  const lit = doorSight({x: 0.5, y: 1.2});
  // The square (3,0) is in the service's sight for this frame, so tabletop.js marks it explored before setFog.
  const seen = seenOnly([at(0, 0), at(1, 0), at(0, 1), at(1, 1), at(2, 1), at(3, 1), at(3, 0)]);
  const explored = frameExplored([...seen.keys()].filter(i => seen[i]));
  const fog = paintFog(s, seen, explored, null, lit);
  const outside = cellSamples(fog, 3, 0).filter(sample => !insideLit(lit, sample.px / CELL, sample.py / CELL));
  assert.ok(outside.length > 0, 'the square has pixels outside the lit shape');
  for (const sample of outside) assert.ok(sample.alpha > 0.9, `pixel (${sample.px},${sample.py}) outside the shape is at full fog`);
  // The viewer moves to the other room. Pixels never lit by any frame keep the full wash; the lit corner stays explored.
  const later = paintFog(s, seenOnly([at(0, 1)]), explored, null, doorSight({x: 0.5, y: 0.5}));
  for (const sample of cellSamples(later, 3, 0)) {
    if (insideLit(lit, sample.px / CELL, sample.py / CELL)) continue;
    assert.ok(sample.alpha > 0.9, `after moving away, pixel (${sample.px},${sample.py}) never lit is still at full fog`);
  }
});


test('a reload seeds only the saved square: its blurred edge never reaches an unsaved neighbour', () => {
  const s = rasterSession({storage: new Map(), objects: []});
  s.board.setMap(map([]));
  s.board.setZones([], {round: 1});
  // Only (1,0) is saved and nothing is in sight: the explored array holds the saved cell, as visibility() marks it.
  const saved = seenOnly([at(1, 0)]);
  const explored = frameExplored([at(1, 0)]);
  const fog = paintFog(s, seenOnly([]), explored, saved, {polygons: []});
  // The seed lives in the accumulator, one canvas per explored array. It must be empty outside the saved square.
  const seed = explored.sightCanvas;
  const outside = [];
  for (let py = 0; py < seed.height; py++) for (let px = 0; px < seed.width; px++) {
    const cx = Math.floor(px / CELL), cy = Math.floor(py / CELL);
    if (cx === 1 && cy === 0) continue;
    if (seed.alpha[py * seed.width + px] > 0) outside.push([px, py]);
  }
  assert.deepEqual(outside.slice(0, 3), [], 'no seed alpha lies outside the saved square');
  assert.ok(Math.abs(alphaAt(fog, 1, 0) - 0.4) < 0.05, 'the saved square gets the dim wash');
  for (const [x, y] of [[0, 0], [2, 0], [0, 1], [1, 1], [2, 1], [3, 0], [3, 1]])
    for (const sample of cellSamples(fog, x, y)) assert.ok(sample.alpha > 0.9, `unsaved (${x},${y}) is at full fog`);
});

// A 2-step staircase across the 4x2 grid: (0,0)-(1,0) on top, (1,1)-(2,1) on the bottom, the two rows touching only
// at the single corner (1,0)/(2,1). This is what a continuous diagonal sight edge, quantised to cells, looks like:
// it must read as one soft frontier, not a lattice of squares each blurred and clipped on its own.
const STAIRCASE = [[0, 0], [1, 0], [1, 1], [2, 1]];
const staircaseIndexes = STAIRCASE.map(([x, y]) => at(x, y));

test('a reload seed of several saved squares is blurred as one shape: no staircase gap at a shared edge or corner', () => {
  const s = rasterSession({storage: new Map(), objects: []});
  s.board.setMap(map([]));
  s.board.setZones([], {round: 1});
  const saved = seenOnly(staircaseIndexes);
  const explored = frameExplored(staircaseIndexes);
  paintFog(s, seenOnly([]), explored, saved, {polygons: []});
  const seed = explored.sightCanvas;
  const px = (x, y) => seed.alpha[y * seed.width + x];
  // The shared edges between (0,0)/(1,0) and between (1,0)/(1,1) are well inside the saved region, far from its
  // outer boundary: an unbroken sight frontier never dips there, let alone drops to the near-dark seam a separate
  // per-square inset-and-blur leaves (~0.04 of full alpha, measured against this same scenario before this fix).
  assert.ok(px(64, 32) > 0.8, `edge (0,0)/(1,0) has no staircase gap, got ${px(64, 32)}`);
  assert.ok(px(96, 64) > 0.8, `edge (1,0)/(1,1) has no staircase gap, got ${px(96, 64)}`);
  // The single corner where (1,0) and (2,1) touch diagonally stays soft (it is the shape's own outer corner) but
  // not the near-zero a separately blurred, inset square leaves there (~0.001, measured the same way).
  assert.ok(px(128, 64) > 0.3, `diagonal corner (1,0)/(2,1) is not a near-dark seam, got ${px(128, 64)}`);
});

test('a reloaded remembered artwork layer feathers along the same frontier with no staircase gap or unsaved coverage', () => {
  const storage = new Map();
  const coverStaircase = {type: 'SIMPLE_COVER', look: 'low_wall', cells: STAIRCASE};
  const seenStaircase = seenOnly(staircaseIndexes);
  const first = session({storage});
  // The viewer sees the staircase with cover, then looks elsewhere while the cover is removed: every staircase
  // square is a changed remembered tile (same recipe as "a remembered square that changed while unseen ...").
  look(first, {ruleTerrain: [coverStaircase], seen: seenStaircase});
  look(first, {ruleTerrain: [], seen: seenOnly([at(3, 1)])});

  const reloaded = rasterSession({storage});
  reloaded.board.setMap(map([]));
  const seen = visibilityOf(reloaded);  // no live viewers: nothing is in sight this frame
  // Warm floorSwatchUrl's cache for these squares under the inert stub canvas, the same as every other
  // setRemembered test does: textures.js's real paintFloor/crop pixel path is a separate concern (REMEMBERART2,
  // pixelCanvas) from the alpha raster setFog/applyRememberedCut need below, and the two don't mix in one call.
  reloaded.board.setRemembered(reloaded.rememberFog(seen, [], new Set()));
  rasterOn = true;
  let rememberedSvg;
  try {
    reloaded.board.setFog(seen, reloaded.app.explored, {polygons: []}, reloaded.app.savedExplored);
    reloaded.board.setRemembered(reloaded.rememberFog(seen, [], new Set()));
    rememberedSvg = reloaded.board.element.querySelector('.tt-remembered-layer');
  } finally { rasterOn = false; }
  assert.ok(tileAt(reloaded.board, 1, 0), 'the staircase square is drawn as a changed remembered tile');
  assert.equal(rememberedSvg.querySelector('.tt-remembered-pictures').style.maskImage, undefined,
    'artwork is opaque; only the common wash feathers');
  const mask = reloaded.app.explored.sightCanvas;
  assert.ok(mask, 'the mask image is a traceable raster, not a placeholder');
  const px = (x, y) => mask.alpha[y * mask.width + x];
  assert.ok(px(64, 32) > 0.8, `remembered-layer edge (0,0)/(1,0) has no staircase gap, got ${px(64, 32)}`);
  assert.ok(px(96, 64) > 0.8, `remembered-layer edge (1,0)/(1,1) has no staircase gap, got ${px(96, 64)}`);
  // Coverage only: live-state isolation is checked by the composed-color regressions below.
  for (const sample of cellSamples({alpha: mask.alpha, width: mask.width}, 3, 0))
    assert.equal(sample.alpha, 0, `never-seen (3,0) gets no remembered-layer coverage, got ${sample.alpha}`);
});

// Compose the actual fog/backing/art masks in board draw order. Opaque replacement colors stand for live floor
// or cover pixels; changing those colors must have zero influence on an unseen remembered frontier pixel.
const rememberedCSS = readFileSync(new URL('./tabletop.css', import.meta.url), 'utf8');
const backingHex = /\.tt-remembered-tile\s*\{\s*fill:\s*#([\da-f]{6})/.exec(rememberedCSS)[1];
const backingRGB = [0, 2, 4].map(i => parseInt(backingHex.slice(i, i + 2), 16));
const artOpacity = Number(/\.tt-remembered-art\s*\{\s*opacity:\s*([\d.]+)/.exec(rememberedCSS)[1]);
const overRGB = (above, below, alpha) => above.map((value, i) => value * alpha + below[i] * (1 - alpha));

test('FOGGREY mixed captured procedural neutral and unchanged ground share one raster wash', () => {
  const s = rasterSession({storage: new Map(), objects: []});
  s.board.setMap(map([]));
  // Warm real procedural crops with the pixel raster; the same raw ground is
  // then classified as captured, procedural, neutral, and unchanged in turn.
  const cells = {};
  pixelRasterOn = true;
  try {
    const raw = paintFloor('flagstone', 1, WIDTH, HEIGHT, {patch: true});
    const crop = pixelCanvas(); crop.width = crop.height = raw.width / WIDTH;
    crop.getContext('2d').drawImage(raw, 0, 0, crop.width, crop.height, 0, 0, crop.width, crop.height);
    cells[0] = {floor: {swatch: crop.toDataURL()}};
    cells[1] = {floor: {style: 'flagstone', seed: 1, patch: true}};
    cells[2] = {floor: null};
    s.board.setRemembered({cells, ghosts: [0, 1, 2], changed: [0, 1, 2], width: WIDTH});
  } finally { pixelRasterOn = false; }
  const explored = frameExplored(Array.from({length: WIDTH * HEIGHT}, (_, i) => i));
  paintFog(s, seenOnly([]), explored, seenOnly(Array.from({length: WIDTH * HEIGHT}, (_, i) => i)));
  const layer = s.board.element.querySelector('.tt-remembered-layer');
  const siblings = s.board.element.children;
  assert.ok(Array.from(siblings).indexOf(layer) < Array.from(siblings).indexOf(s.board.element.querySelector('.tt-fog')),
    'one wash must paint after the composed saved ground');
  assert.equal(artOpacity, 1, 'no independent art dimming');
  assert.ok(!layer.querySelector('.tt-remembered-underlay'), 'no separately tinted tile copy');
  const means = [];
  for (let x = 0; x < 3; x++) {
    const image = layer.querySelectorAll('.tt-remembered-floor')[x];
    const source = pixelsFromHref(image.getAttribute('href'));
    assert.ok(source, 'each source has real untinted floor pixels');
    const alpha = alphaAt(s.fogCanvas, x, 0);
    assert.ok(Math.abs(alpha - 0.4) < 0.01, 'same wash inside explored ground');
    const rendered = pixelCanvas(); rendered.width = source.width; rendered.height = source.height;
    const ctx = rendered.getContext('2d'); ctx.drawImage(source, 0, 0);
    for (let y = 0; y < source.height; y++) for (let px = 0; px < source.width; px++) ctx.pixel(px, y, backingRGB, alpha);
    means.push(Array.from(rendered.pixels).reduce((sum, value, i) => sum + (i % 4 < 3 ? value : 0), 0) / (source.width * source.height * 3));
  }
  assert.ok(Math.max(...means) - Math.min(...means) < 6, `mixed source neighbours retain consistent brightness: ${means}`);
  assert.ok(Math.abs(alphaAt(s.fogCanvas, 3, 0) - 0.4) < 0.01, 'unchanged ground gets the identical wash');
});

for (const count of [1, 8]) test(`${count} remembered blue zones retain floor pixels after a table reload, even without zone CSS`, () => {
  const storage = new Map();
  const first = session({storage});
  first.board.setZones(Array.from({length: count}, (_, i) => ({...zoneRow, zone_id: `water-${i}`,
    trigger_profile: {kind: 'TYPED', name: 'Water Pool', visual: {material: 'water'}}})), {round: 1});
  pixelRasterOn = true;
  try {
    const width = WIDTH * 16, height = HEIGHT * 16;
    const pixels = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++)
      pixels.set([60 + x * 2, 50 + y * 4, 40, 255], (y * width + x) * 4);
    upgradeToPixelImage(first.board.element.querySelector('.tt-bg-image'), width, height, pixels);
    first.board.setMap({...map([]), background: {url: 'https://example.test/zone-floor.png', fit: 'stretch'}});
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
  } finally { pixelRasterOn = false; }
  const saved = first.app.fogMemory.memory.cells[at(2, 1)];
  assert.equal(saved.zones.length, count);
  const reloaded = session({storage});
  look(reloaded, {zones: [], seen: seenOnly([at(0, 0)])}); // pools disappeared while unseen
  const art = groupOf(tileAt(reloaded.board, 2, 1)).querySelector('.tt-remembered-art');
  const floor = art.querySelector('.tt-remembered-floor');
  assert.equal(floor.getAttribute('href'), saved.floor.swatch);
  const source = pixelsFromHref(floor.getAttribute('href'));
  const zones = art.querySelectorAll('.tt-remembered-zone');
  assert.equal(zones.length, count, 'only sight-time zones are redrawn');
  const zoneCSSOpacity = Number(/\.tt-remembered-zone\s*\{\s*opacity:\s*([\d.]+)/.exec(rememberedCSS)[1]);
  for (const cssOpacity of [1, zoneCSSOpacity]) {
    const rendered = pixelCanvas();
    rendered.width = source.width; rendered.height = source.height;
    const context = rendered.getContext('2d');
    context.drawImage(source, 0, 0);
    let transmission = 1;
    for (const zone of zones) {
      // SVG defaults to opaque when fill-opacity is absent. Deliberately test without the CSS opacity rule.
      const alpha = Number(zone.getAttribute('fill-opacity') ?? 1);
      transmission *= 1 - alpha * cssOpacity;
      const color = zone.getAttribute('fill');
      assert.match(color, /^#[\da-f]{6}$/i);
      const rgb = [1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16));
      for (let y = 0; y < source.height; y++) for (let x = 0; x < source.width; x++)
        context.pixel(x, y, rgb, alpha * cssOpacity);
    }
    const variance = canvas => {
      const red = Array.from(canvas.pixels).filter((_, i) => i % 4 === 0);
      const mean = red.reduce((a, b) => a + b, 0) / red.length;
      return red.reduce((sum, value) => sum + (value - mean) ** 2, 0) / red.length;
    };
    assert.ok(variance(rendered) > variance(source) * 0.2, 'rasterized saved floor retains visible variance under the tint');
    assert.ok(transmission >= 0.5, 'even eight overlapping zones leave most floor detail visible');
    for (const zone of zones) assert.ok(Number(zone.getAttribute('fill-opacity') ?? 1) <= 0.2,
      'SVG itself limits the tint alpha');
  }
});

for (const change of ['floor', 'cover']) test(`reloaded ${change} changed unseen cannot leak through a fractional remembered frontier`, () => {
  const storage = new Map();
  const first = session({storage});
  pixelRasterOn = true;
  try {
    const width = WIDTH * 16, height = HEIGHT * 16;
    const pixels = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++)
      pixels.set([100 + x, 80 + y, 40, 255], (y * width + x) * 4);
    upgradeToPixelImage(first.board.element.querySelector('.tt-bg-image'), width, height, pixels);
    const original = map([coverRow]);
    original.background = {url: 'https://example.test/fogedge-old.png', fit: 'stretch'};
    first.board.setMap(original);
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
  } finally { pixelRasterOn = false; }
  const savedFloor = first.app.fogMemory.memory.cells[at(2, 1)].floor.swatch;
  const savedPixels = pixelsFromHref(savedFloor);
  assert.ok(savedPixels, 'capture real sight-time floor pixels before changing the live map');

  const reloaded = rasterSession({storage});
  // Removing the cover makes this a changed remembered tile through the existing table path. The floor case
  // also replaces its background; this regression targets compositing of changed tiles, not change detection.
  const replacementMap = map([]);
  replacementMap.background = {url: 'https://example.test/fogedge-old.png', fit: 'stretch'};
  if (change === 'floor') replacementMap.background = {url: null, opacity: 1, style: 'wood', seed: 91};
  reloaded.board.setMap(replacementMap);
  const seen = visibilityOf(reloaded);
  rasterOn = true;
  try {
    reloaded.board.setFog(seen, reloaded.app.explored, {polygons: []}, reloaded.app.savedExplored);
    reloaded.board.setRemembered(reloaded.rememberFog(seen, [], new Set()));
  } finally { rasterOn = false; }
  const tile = tileAt(reloaded.board, 2, 1);
  assert.ok(tile, 'the replacement makes this a changed remembered square');
  assert.equal(groupOf(tile).querySelector('.tt-remembered-floor').getAttribute('href'), savedFloor);
  const layer = reloaded.board.element.querySelector('.tt-remembered-layer');
  const outer = alphaFromHref(layer.style.maskImage);
  const pictures = layer.querySelector('.tt-remembered-pictures');
  if (pictures) {
    assert.equal(pictures.getAttribute('viewBox'), `0 0 ${WIDTH} ${HEIGHT}`);
    assert.equal(pictures.style.maskImage, undefined, 'saved pixels are not feathered separately from the wash');
  }
  // Fall back to the old single-layer mask so this regression measures the faulty compositor too.
  const frontier = reloaded.app.explored.sightCanvas;
  const px = 2 * CELL, py = CELL + 32, index = py * outer.width + px;
  const explored = reloaded.app.explored.sightCanvas.alpha[index];
  assert.ok(explored > 0.3 && explored < 0.7, `sample lies in fractional frontier: ${explored}`);
  const sx = 0, sy = Math.floor(32 * savedPixels.height / CELL);
  const oldRGB = Array.from(savedPixels.pixels.slice((sy * savedPixels.width + sx) * 4, (sy * savedPixels.width + sx) * 4 + 3));
  const compose = liveRGB => {
    const remembered = overRGB(oldRGB, liveRGB, outer.alpha[index]);
    return overRGB(backingRGB, remembered, reloaded.fogCanvas.alpha[index]);
  };
  assert.deepEqual(compose([255, 0, 0]), compose([0, 255, 255]),
    'final pixel cannot depend on unseen live replacement colors');
  assert.equal(outer.alpha[index], 1, 'neutral backing remains opaque with no live sight');
  assert.ok(frontier.alpha[index] > 0.3 && frontier.alpha[index] < 0.7, 'the common fog wash still feathers');
  assert.equal(artOpacity, 1, 'saved artwork has no independent darkening');
  assert.deepEqual(compose([255, 0, 0]), overRGB(backingRGB, oldRGB, reloaded.fogCanvas.alpha[index]));
});

test('a changed remembered square beside a live wedge keeps cached detail where the explored mask is zero', () => {
  const storage = new Map();
  const first = session({storage});
  pixelRasterOn = true;
  try {
    const width = WIDTH * 16, height = HEIGHT * 16;
    const pixels = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++)
      pixels.set([80 + x * 2, 60 + y * 3, 40, 255], (y * width + x) * 4);
    upgradeToPixelImage(first.board.element.querySelector('.tt-bg-image'), width, height, pixels);
    const original = map([coverRow]);
    original.background = {url: 'https://example.test/remembered-wedge.png', fit: 'stretch'};
    first.board.setMap(original);
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
  } finally { pixelRasterOn = false; }
  const savedFloor = first.app.fogMemory.memory.cells[at(2, 1)].floor.swatch;
  const savedPixels = pixelsFromHref(savedFloor);
  const reloaded = rasterSession({storage});
  reloaded.board.setMap(map([])); // cover removed while unseen
  const seen = seenOnly([at(3, 1)]);
  const explored = frameExplored([at(2, 1), at(3, 1)]);
  rasterOn = true;
  try {
    reloaded.board.setFog(seen, explored, {polygons: [{points: [[2.6, 1], [4, 1], [4, 2], [3.2, 2]]}]});
    reloaded.board.setRemembered(reloaded.rememberFog(seen, [], new Set()));
  } finally { rasterOn = false; }
  const layer = reloaded.board.element.querySelector('.tt-remembered-layer');
  const picture = layer.querySelector('.tt-remembered-floor');
  assert.ok(picture, 'isolation backing includes a saved picture, not only a flat rectangle');
  assert.equal(picture.getAttribute('href'), savedFloor, 'picture uses the sight-time floor');
  assert.ok(!layer.querySelector('.tt-remembered-underlay'), 'no second tinted floor copy');
  const outer = alphaFromHref(layer.style.maskImage);
  const frontier = explored.sightCanvas;
  const colors = new Set();
  for (const [dx, dy] of [[4, 12], [4, 44]]) {
    const index = (CELL + dy) * outer.width + 2 * CELL + dx;
    assert.equal(frontier.alpha[index], 0, 'picture feather has no coverage outside the wedge');
    assert.equal(outer.alpha[index], 1, 'backing still isolates unseen live state');
    const offset = (Math.floor(dy * savedPixels.height / CELL) * savedPixels.width
      + Math.floor(dx * savedPixels.width / CELL)) * 4;
    const oldRGB = Array.from(savedPixels.pixels.slice(offset, offset + 3));
    const base = overRGB(backingRGB, oldRGB, reloaded.fogCanvas.alpha[index]);
    const compose = live => overRGB(backingRGB, overRGB(oldRGB, live, outer.alpha[index]), reloaded.fogCanvas.alpha[index]);
    assert.deepEqual(compose([255, 0, 0]), compose([0, 255, 255]), 'unseen edits cannot change the pixel');
    assert.ok(base.every((value, i) => value < oldRGB[i]), 'cached picture is darker');
    colors.add(base.join(','));
  }
  assert.equal(colors.size, 2, 'cached texture remains non-uniform where a flat block used to appear');
});

test('sight accumulates across frames: two disjoint sight shapes both stay explored, and a fresh explored array starts empty', () => {
  const s = rasterSession({storage: new Map(), objects: []});
  s.board.setMap(map([]));
  s.board.setZones([], {round: 1});
  const explored = frameExplored([]);
  // Frame 1: the viewer in the left room sees (0,0) and (1,0). Frame 2: the viewer has moved, sees only (3,1).
  const first = seenOnly([at(0, 0), at(1, 0)]);
  paintFog(s, first, frameExplored([at(0, 0), at(1, 0)], explored), null, {polygons: visibilityPolygons([{x: 0.5, y: 0.5}], blockerSegments({walls: DOOR.walls, width: WIDTH, height: HEIGHT}), WIDTH, HEIGHT)});
  // Frame 2: the viewer is in the right room, behind the wall at x=2, so the left room is out of sight.
  const second = seenOnly([at(3, 1)]);
  const wall = blockerSegments({walls: DOOR.walls, width: WIDTH, height: HEIGHT});
  const fog = paintFog(s, second, frameExplored([at(3, 1)], explored), null, {polygons: visibilityPolygons([{x: 3.5, y: 0.5}], wall, WIDTH, HEIGHT)});
  assert.ok(Math.abs(alphaAt(fog, 0, 0) - 0.4) < 0.05, 'frame 1 sight, now out of sight, stays explored (dim wash)');
  assert.ok(Math.abs(alphaAt(fog, 1, 0) - 0.4) < 0.05, 'the second explored cell from frame 1 stays explored');
  assert.ok(alphaAt(fog, 3, 1) < 0.05, 'the square in view now is not dimmed');
  // A map or viewer change installs a new explored array: it starts empty, with no sight carried over.
  const fresh = frameExplored([]);
  const after = paintFog(s, seenOnly([]), fresh, null, {polygons: []});
  assert.ok(alphaAt(after, 0, 0) > 0.9, 'a fresh explored array does not remember the old viewer');
});

test('squares never seen, owned creatures and creatures the viewer cannot see are never recorded', () => {
  const storage = new Map();
  const s = session({storage, owned: ['mine'], unseen: ['ghost-foe']});
  look(s, {seen: seenOnly([at(0, 0)]), actors: [
    goblin('mine', 0, 0, 0), goblin('ghost-foe', 0, 0), goblin('dragon', 3, 1)]});
  const saved = JSON.stringify([...storage.values()]);
  assert.ok(JSON.parse([...storage.values()][0] || '{}').cells?.['0'], 'the seen square is saved in memory');
  assert.equal(saved.includes('dragon'), false, 'a creature on a never-seen square is not recorded');
  assert.equal(saved.includes('"mine"'), false, 'the viewer\'s own creature is not a remembered enemy');
  assert.equal(saved.includes('ghost-foe'), false, 'a creature the viewer cannot see is not recorded');
  assert.equal(tileAt(s.board, 3, 1), undefined, 'the never-seen square is not drawn');
});

test('the GM view and fog-off draw no remembered squares', () => {
  const gm = session({storage: new Map(), gm: true});
  look(gm, {seen: seenOnly([at(0, 0)])});
  assert.equal(tiles(gm.board).length, 0);
});

test('hovering a remembered square says so and gives no live terrain, while a square in view explains its terrain', () => {
  // The card waits for the pointer to rest; run that timer on the spot so the card is there to read.
  const realSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = callback => { callback(); return 0; };
  const words = node => [node.textContent, ...node.children.map(words)].filter(Boolean).join(' ');
  // A fresh board per hover, so the card from one hover cannot be read for another.
  const hoverOn = (x, y) => {
    for (const old of document.body.querySelectorAll('.tt-zone-tip')) old.remove();
    const s = session({storage: new Map(), objects: []});
    look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(2, 1)])});
    look(s, {ruleTerrain: [coverRow], seen: seenOnly([at(0, 0)])});
    s.board.viewport.dispatch('pointermove', {clientX: x * 64 + 32, clientY: y * 64 + 32, buttons: 0});
    const card = document.body.querySelectorAll('.tt-zone-tip')[0];
    return card ? words(card) : '';
  };
  try {
    const ghostText = hoverOn(2, 1);
    assert.match(ghostText, /You remember this area as it looked when you last saw it\./, 'the remembered square says it is remembered');
    assert.doesNotMatch(ghostText, /Simple cover/, 'the live cover on an unseen square is not explained');
    const seenText = hoverOn(0, 0);
    assert.doesNotMatch(seenText, /You remember/, 'a square in view is not called remembered');
  } finally {
    globalThis.setTimeout = realSetTimeout;
  }
});

// Magical Darkness (owner 2026-10-13): a darkness area the viewer cannot see into stays drawn with its look over the dimmed
// map. Its colour comes from whose area it is, which the viewer does not need to see the darkness, so it must not make the
// square look changed.
const darknessZone = {zone_id: 'dark', source_definition_id: 'fog.darkness', affected_cells: [[2, 1]], center: [2, 1], radius_cells: 0,
  owner_id: 'caster', trigger_profile: {kind: 'TYPED', name: 'Darkness', visual: {darkness: true, darkness_look: 'veil'}}};

test('darkness the viewer cannot see into draws no opaque tile across a reload, even when its owner is off the roster', () => {
  const storage = new Map();
  const first = session({storage});
  first.board.setMap(map([]));
  first.board.setZones([darknessZone], {round: 1, teamOf: () => ({color: '#f00', owner: 'Caster', foe: true})});
  first.board.setFog(seenOnly([at(2, 1)]));
  first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
  // Reload: the owner is not on the roster yet, so the zone has the neutral colour; the viewer still cannot see in.
  const reloaded = session({storage});
  reloaded.board.setMap(map([]));
  reloaded.board.setZones([darknessZone], {round: 1, teamOf: () => null});
  reloaded.board.setFog(seenOnly([at(0, 0)]));
  reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  assert.equal(tileAt(reloaded.board, 2, 1), undefined, 'the darkness square is not an opaque block');
  assert.equal(tiles(reloaded.board).length, 0, 'no remembered square covers the dimmed map');
});

test('a remembered square saved before terrain was recorded is dropped on load, not drawn as changed', () => {
  const storage = new Map([[memoryKey('match-1', 'viewer-a:on', WIDTH, HEIGHT),
    JSON.stringify({version: 1, cells: {[at(2, 1)]: {tokens: [], objects: [], zones: [{name: 'Darkness', color: '#f00'}]}}})]]);
  const s = session({storage});
  look(s, {zones: [darknessZone], seen: seenOnly([at(0, 0)])});
  assert.equal(tileAt(s.board, 2, 1), undefined, 'the old record is not drawn as an opaque tile');
});

// A real replacement while unseen (owner 2026-10-13 review): caster A's darkness is remembered, then caster B's darkness with
// the same name covers the square while the viewer cannot see it. The live art changed, so the old record must cover it.
test('a same-name darkness area that replaced the remembered one while unseen still covers the live square', () => {
  const storage = new Map();
  const casterA = {...darknessZone, zone_id: 'dark-a', owner_id: 'caster-a'};
  const casterB = {...darknessZone, zone_id: 'dark-b', owner_id: 'caster-b'};
  const first = session({storage});
  first.board.setMap(map([]));
  first.board.setZones([casterA], {round: 1, teamOf: () => ({color: '#f00', owner: 'A', foe: true})});
  first.board.setFog(seenOnly([at(2, 1)]));
  first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
  const reloaded = session({storage});
  reloaded.board.setMap(map([]));
  reloaded.board.setZones([casterB], {round: 1, teamOf: () => ({color: '#00f', owner: 'B', foe: true})});
  reloaded.board.setFog(seenOnly([at(0, 0)]));
  reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  assert.ok(tileAt(reloaded.board, 2, 1), 'the remembered square is drawn over the live darkness it no longer matches');
});

// REMEMBERART (owner 2026-10-13): a changed remembered square used to get the opaque base with nothing drawn over
// it whenever it had no rule terrain of its own -- almost every ordinary floor square -- so it looked like a flat
// near-black block with only a creature's initials on it. It must now draw the ground itself, dimmed.
test('a changed remembered square with no rule terrain still shows ground art, not a flat block', () => {
  const storage = new Map();
  const chest = {id: 'chest', name: 'Chest', kind: 'chest', x: 2, y: 1, hp: 10};
  const s = session({storage, objects: [chest]});
  look(s, {seen: seenOnly([at(2, 1)])});
  // The chest is destroyed while the viewer looks elsewhere: the plain floor square now differs from its record
  // (the live square has no objects any more), with no rule terrain of its own to draw either.
  s.app.state.objects = [];
  look(s, {seen: seenOnly([at(0, 0)])});
  const tile = tileAt(s.board, 2, 1);
  assert.ok(tile, 'the changed square is drawn from its record');
  const image = groupOf(tile).querySelector('.tt-remembered-floor');
  assert.ok(image, 'a plain floor square with no rule terrain still gets ground art, not just the opaque base');
  assert.equal(image.getAttribute('data-floor-style'), 'flagstone', "the map's own background style is used");
});

// No live-state leak (owner 2026-10-13): the floor patch under a remembered square can be repainted (a map edit)
// while the viewer cannot see it. The square is already drawn from its record for another reason (its cover is
// gone); the ground art drawn over it must still be the floor the viewer actually saw, not the live one underneath.
//
// REMEMBERART2 (review round 2, P2): a wood patch against the map's flagstone background is a crisp border seam
// (textures.js edgeTreatment: artificial meets anything else), not a plain opaque patch -- board.js draws a thin
// border line across it (setMap's "seams" pass) that a bare style/seed/patch replay never reproduces. The square
// must be captured, not labelled "wood", and the captured swatch -- not a fresh capture of the edited live square
// -- is what a reload shows.
test('a changed remembered square keeps the exact border seam it had, not a later live edit, across a reload', () => {
  const storage = new Map();
  const woodFloor = [{style: 'wood', cells: [[2, 1]]}];
  const first = session({storage});
  pixelRasterOn = true;
  let capturedFloor, capturedPixels;
  try {
    upgradeToPixelCanvas(first.board.element.querySelector('.tt-bg-floor'));
    first.board.setMap({...map([coverRow]), floors: woodFloor});
    first.board.setZones([], {round: 1});
    first.board.setFog(seenOnly([at(2, 1)]));
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
    capturedFloor = first.app.fogMemory.memory.cells[at(2, 1)].floor;
    capturedPixels = pixelsFromHref(capturedFloor?.swatch)?.pixels;
  } finally { pixelRasterOn = false; }
  assert.ok(capturedFloor?.swatch, 'a crisp border seam is captured at sight time, not replayed from style/seed/patch alone');
  assert.ok(capturedPixels, 'the captured swatch is a real pixel crop');
  const colors = new Set();
  for (let i = 0; i < capturedPixels.length; i += 4) colors.add(`${capturedPixels[i]},${capturedPixels[i + 1]},${capturedPixels[i + 2]}`);
  assert.ok(colors.size > 1, 'the captured swatch shows real ground detail (wood grain and the border line), not a flat fill');
  const border = edgeTreatment('flagstone', 'wood').borderColor.map(v => v | 0);
  const live = first.board.element.querySelector('.tt-bg-floor');
  const pps = live.width / WIDTH, seam = (Math.floor(pps * 1.5) * live.width + 2 * pps) * 4;
  assert.deepEqual(Array.from(live.pixels.slice(seam, seam + 3)), border,
    'the live seam has its specified colour; removing the stroke fails');
  pixelRasterOn = true;
  try {
    const raw = pixelCanvas(); raw.width = raw.height = 16;
    raw.getContext('2d').drawImage(paintFloor('wood', 1, WIDTH, HEIGHT, {patch: true}), 2 * pps, pps, pps, pps, 0, 0, 16, 16);
    assert.notDeepEqual(capturedPixels, raw.pixels, 'the captured crop contains border pixels, unlike bare wood');
  } finally { pixelRasterOn = false; }

  // Reload (a fresh tab): the cover is gone (still marks the square changed) and the floor patch has been edited
  // to the map's plain flagstone -- no seam, no border at all -- while the viewer could not see it.
  const reloaded = session({storage});
  reloaded.board.setMap({...map([]), floors: []});
  reloaded.board.setZones([], {round: 1});
  reloaded.board.setFog(seenOnly([at(0, 0)]));
  reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  const tile = tileAt(reloaded.board, 2, 1);
  assert.ok(tile, 'the changed square is drawn from its record');
  const image = groupOf(tile).querySelector('.tt-remembered-floor');
  assert.equal(image?.getAttribute('data-floor-style'), 'captured',
    'a captured border seam is drawn from its own swatch, not relabelled provenance');
  assert.equal(image?.getAttribute('href'), capturedFloor.swatch,
    'the remembered square shows exactly the swatch captured at sight time, not a new capture of the edited live square');
});

// REMEMBERART2: the review's own example -- a grass/sand boundary -- is a natural-natural seam, feathered by
// setMap's blur pass (display.blend), not bordered. The captured swatch must still freeze what was actually
// blended at sight time rather than today's live blend, which the map's own blend amount or patches could change.
test('a changed remembered square keeps the exact blended boundary it had, not a later live edit', () => {
  const storage = new Map();
  const sandPatch = [{style: 'sand', cells: [[2, 1]]}];
  const first = session({storage});
  pixelRasterOn = true;
  let capturedFloor, capturedPixels;
  try {
    upgradeToPixelCanvas(first.board.element.querySelector('.tt-bg-floor'));
    first.board.setMap({...map([coverRow]), background: {url: null, opacity: 1, style: 'grass', seed: 1},
      display: {blend: 1}, floors: sandPatch});
    first.board.setZones([], {round: 1});
    first.board.setFog(seenOnly([at(2, 1)]));
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
    capturedFloor = first.app.fogMemory.memory.cells[at(2, 1)].floor;
    capturedPixels = pixelsFromHref(capturedFloor?.swatch)?.pixels;
  } finally { pixelRasterOn = false; }
  assert.ok(capturedFloor?.swatch, 'a blended natural seam is captured at sight time, not replayed from style/seed/patch alone');
  assert.ok(capturedPixels, 'the captured swatch is a real pixel crop');
  const colors = new Set();
  for (let i = 0; i < capturedPixels.length; i += 4) colors.add(`${capturedPixels[i]},${capturedPixels[i + 1]},${capturedPixels[i + 2]}`);
  assert.ok(colors.size > 1, 'the captured swatch shows the real blended boundary, not a flat fill');
  pixelRasterOn = true;
  try {
    const raw = pixelCanvas(); raw.width = raw.height = 16;
    const sand = paintFloor('sand', 1, WIDTH, HEIGHT, {patch: true});
    const pps = sand.width / WIDTH;
    raw.getContext('2d').drawImage(sand, 2 * pps, pps, pps, pps, 0, 0, 16, 16);
    assert.notDeepEqual(capturedPixels, raw.pixels, 'a raw sand crop cannot pass as a blended grass/sand edge');
    const edge = capturedPixels.slice(0, 3), rawEdge = raw.pixels.slice(0, 3);
    assert.ok(edge[0] < rawEdge[0], 'the edge includes darker grass through the feathered sand alpha');
  } finally { pixelRasterOn = false; }

  // Reload: the sand patch and the blend setting are both gone while the viewer could not see it -- today's live
  // square is a plain, unblended grass background.
  const reloaded = session({storage});
  reloaded.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'grass', seed: 1}, floors: []});
  reloaded.board.setZones([], {round: 1});
  reloaded.board.setFog(seenOnly([at(0, 0)]));
  reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  const tile = tileAt(reloaded.board, 2, 1);
  assert.ok(tile, 'the changed square is drawn from its record');
  const image = groupOf(tile).querySelector('.tt-remembered-floor');
  assert.equal(image?.getAttribute('href'), capturedFloor.swatch,
    'the remembered square shows exactly the blend captured at sight time, not a capture of the now-unblended live square');
});

// REMEMBERART2: an uploaded background has no procedural provenance at all (floorAt already returns null for it),
// so the only way to show what was actually seen is a real pixel capture of the on-screen CSS object-fit crop
// (board.js: bgImage.style.objectFit, "cover" by default). The synthetic image below is blue in the rows "cover"
// crops away and a column-varying red/green elsewhere, so any captured swatch should be entirely non-blue (the
// crop excluded those rows) and non-uniform (a real crop, not a flat fallback).
test('an uploaded background is captured as what the object-fit crop actually showed, not a flat or neutral default', () => {
  const storage = new Map();
  const first = session({storage});
  pixelRasterOn = true;
  let capturedFloor, pixels;
  try {
    const size = 64;
    const imagePixels = new Uint8ClampedArray(size * size * 4);
    for (let y = 0; y < size; y += 1) for (let x = 0; x < size; x += 1) {
      const i = (y * size + x) * 4;
      const croppedAway = y < 16 || y >= 48; // outside "cover"'s visible band for a 4x2 board on a square image
      imagePixels[i] = croppedAway ? 0 : 255;
      imagePixels[i + 1] = croppedAway ? 0 : Math.floor((x / size) * 255);
      imagePixels[i + 2] = croppedAway ? 255 : 0;
      imagePixels[i + 3] = 255;
    }
    upgradeToPixelImage(first.board.element.querySelector('.tt-bg-image'), size, size, imagePixels);
    first.board.setMap({...map([coverRow]), background: {url: 'https://example.test/bg.png', opacity: 1}});
    first.board.setZones([], {round: 1});
    first.board.setFog(seenOnly([at(2, 1)]));
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
    capturedFloor = first.app.fogMemory.memory.cells[at(2, 1)].floor;
    pixels = pixelsFromHref(capturedFloor?.swatch)?.pixels;
  } finally { pixelRasterOn = false; }
  assert.ok(capturedFloor?.swatch, 'an uploaded background is captured: there is no procedural provenance to replay instead');
  assert.ok(pixels, 'the captured swatch is a real pixel crop');
  for (let i = 0; i < pixels.length; i += 4) {
    assert.ok(pixels[i + 2] < 128, `pixel ${i / 4} shows the band "cover" crops away, not what was actually displayed`);
  }
  const greens = new Set();
  for (let i = 0; i < pixels.length; i += 4) greens.add(pixels[i + 1]);
  assert.ok(greens.size > 1, 'the captured swatch is a real crop of the image, not a flat fill');

  // Reload with a different image while unseen: the remembered square must still show what was captured.
  const reloaded = session({storage});
  reloaded.board.setMap({...map([]), background: {url: 'https://example.test/other.png', opacity: 1}});
  reloaded.board.setZones([], {round: 1});
  reloaded.board.setFog(seenOnly([at(0, 0)]));
  reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  const tile = tileAt(reloaded.board, 2, 1);
  assert.ok(tile, 'the changed square (its cover is gone) is drawn from its record');
  const image = groupOf(tile).querySelector('.tt-remembered-floor');
  assert.equal(image?.getAttribute('href'), capturedFloor.swatch,
    'the remembered square shows exactly what was captured, not a capture of the new image');
});

for (const fit of ['cover', 'stretch']) test(`transparent uploaded ground freezes its composed backdrop across theme/map edits and reload (${fit})`, () => {
  const storage = new Map(), first = session({storage});
  const priorComputedStyle = globalThis.getComputedStyle;
  let theme = 'rgb(240,220,200)';
  globalThis.getComputedStyle = () => ({color: theme});
  pixelRasterOn = true;
  try {
    // Image and board have the same aspect ratio, so every output pixel is
    // known exactly. The remembered tile has clear and half-transparent halves.
    const width = WIDTH * 16, height = HEIGHT * 16;
    const pixels = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      pixels.set([200, 80, 40, x % 16 < 8 ? 0 : 128], (y * width + x) * 4);
    }
    upgradeToPixelImage(first.board.element.querySelector('.tt-bg-image'), width, height, pixels);
    const sightMap = {...map([coverRow]), background: {url: 'https://example.test/alpha.png', fit}};
    first.board.setMap(sightMap);
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
    const saved = first.app.fogMemory.memory.cells[at(2, 1)].floor;
    const captured = Uint8ClampedArray.from(pixelsFromHref(saved.swatch).pixels);
    for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) {
      const pixel = Array.from(captured.slice((y * 16 + x) * 4, (y * 16 + x + 1) * 4));
      assert.deepEqual(pixel, x < 8 ? [240, 220, 200, 255] : [220, 150, 120, 255],
        x < 8 ? 'transparent pixels preserve the sight-time backdrop' : 'semitransparent pixels are composed over the sight-time backdrop');
    }

    // Same image and geometry, new theme: future visible captures must refresh
    // the cache, while the already saved record remains immutable.
    theme = 'rgb(20,40,60)';
    const newCapture = first.board.floorRecordAt(2, 1);
    assert.deepEqual(Array.from(pixelsFromHref(newCapture.swatch).pixels.slice(0, 4)), [20, 40, 60, 255],
      'new visible captures refresh the theme-sensitive composition cache');
    first.board.setMap({...map([]), background: {url: 'https://example.test/later.png', fit}});
    first.board.setRemembered(first.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
    assert.equal(groupOf(tileAt(first.board, 2, 1)).querySelector('.tt-remembered-floor').getAttribute('href'), saved.swatch,
      'unseen reconstruction after a theme/map change keeps the original composition');

    // Persistent DOM canvases keep the normal stub; only capture scratch
    // canvases use the software raster (which has no DOM dataset).
    pixelRasterOn = false;
    const reload = session({storage});
    reload.board.setMap({...map([]), background: {style: 'wood'}});
    reload.board.setRemembered(reload.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
    const href = groupOf(tileAt(reload.board, 2, 1)).querySelector('.tt-remembered-floor').getAttribute('href');
    assert.equal(href, saved.swatch, 'reload reuses the persisted sight-time composition');
    assert.deepEqual(pixelsFromHref(href).pixels, captured, 'reload preserves every composed pixel');
  } finally {
    pixelRasterOn = false;
    globalThis.getComputedStyle = priorComputedStyle;
  }
});

// REMEMBERART2: storage stays bounded because a captured swatch is only taken where provenance replay would not
// be exact -- a seam or an uploaded background -- not for every remembered square on an ordinary map.
test('a square away from any seam is still cheap style/seed/patch provenance, not a captured swatch', () => {
  const s = session({storage: new Map()});
  s.board.setMap({...map([]), floors: [{style: 'wood', cells: [[2, 1]]}]});
  assert.deepEqual(s.board.floorRecordAt(0, 0), {style: 'flagstone', seed: 1, patch: false},
    'a square nowhere near the wood patch has no seam, no blend and no border, so it stays cheap provenance');
});

// REMEMBERART2 / review round 2: "plain" previously returned null from floorAt and fell back to a generic
// flagstone-styled neutral swatch -- a different texture than the plain ground the viewer actually saw. "plain"
// now uses the same opaque gradient/grid pixels for its live canvas and saved crop.
test('a plain background with no patches captures its displayed backdrop, not invented provenance', () => {
  const s = session({storage: new Map()});
  s.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'plain', seed: 1}});
  assert.ok(s.board.floorRecordAt(0, 0).swatch);
});

test('natural background and diagonal recipients retain their blended landmark across reload', () => {
  const storage = new Map(), first = session({storage}), unblended = session();
  const recipients = [at(1, 1), at(1, 0)];
  const rules = [{...coverRow, cells: [[1, 1], [1, 0]]}];
  pixelRasterOn = true;
  let saved;
  try {
    upgradeToPixelCanvas(first.board.element.querySelector('.tt-bg-floor'));
    first.board.setMap({...map(rules), background: {style: 'grass', seed: 23}, display: {blend: 1},
      floors: [{style: 'sand', cells: [[2, 1]]}]});
    first.board.setRemembered(first.rememberFog(seenOnly(recipients), [], new Set()));
    saved = recipients.map(i => first.app.fogMemory.memory.cells[i].floor);
    for (const record of saved) assert.ok(record.swatch, 'background recipients, including diagonals, require composition crops');
    upgradeToPixelCanvas(unblended.board.element.querySelector('.tt-bg-floor'));
    unblended.board.setMap({...map([]), background: {style: 'grass', seed: 23}, display: {}, floors: []});
    const raw = unblended.board.element.querySelector('.tt-bg-floor'), pps = raw.width / WIDTH;
    for (let n = 0; n < recipients.length; n++) {
      const crop = pixelCanvas(); crop.width = crop.height = 16;
      crop.getContext('2d').drawImage(raw, pps, Math.floor(recipients[n] / WIDTH) * pps, pps, pps, 0, 0, 16, 16);
      assert.notDeepEqual(pixelsFromHref(saved[n].swatch).pixels, crop.pixels, 'the feathered neighbour differs from pure grass');
    }
  } finally { pixelRasterOn = false; }
  const reload = session({storage});
  reload.board.setMap({...map([]), background: {style: 'grass', seed: 23}, floors: []});
  reload.board.setRemembered(reload.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  for (let n = 0; n < recipients.length; n++) {
    const i = recipients[n];
    assert.equal(groupOf(tileAt(reload.board, i % WIDTH, Math.floor(i / WIDTH))).querySelector('.tt-remembered-floor').getAttribute('href'), saved[n].swatch);
  }
});

test('plain ground and its transparent patch edges share an opaque themed backdrop across reload and live edit', () => {
  const storage = new Map(), first = session({storage});
  const priorComputedStyle = globalThis.getComputedStyle;
  globalThis.getComputedStyle = element => ({color: element.style.color === 'var(--floor-1)' ? 'color(srgb 0.313726 0.352942 0.392158)'
    : element.style.color === 'var(--floor-2)' ? 'rgb(140,150,160)' : 'rgb(240,240,240)'});
  pixelRasterOn = true;
  let saved;
  try {
    const live = upgradeToPixelCanvas(first.board.element.querySelector('.tt-bg-floor'));
    first.board.setMap({...map([coverRow]), background: {style: 'plain'}, display: {blend: 1},
      floors: [{style: 'sand', cells: [[2, 1]]}]});
    assert.equal(live.hidden, false, 'plain ground uses the same displayed canvas that is captured');
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1), at(0, 0)]), [], new Set()));
    saved = first.app.fogMemory.memory.cells[at(2, 1)].floor;
    const pixels = pixelsFromHref(saved.swatch).pixels;
    for (let i = 3; i < pixels.length; i += 4) assert.equal(pixels[i], 255, 'feathered crops include an opaque backdrop');
    const plain = pixelsFromHref(first.app.fogMemory.memory.cells[at(0, 0)].floor.swatch);
    assert.ok(plain.pixels[0] >= 80 && plain.pixels[2] >= 100, 'saved ground uses resolved theme colours');
    const pps = live.width / WIDTH, crop = pixelCanvas(); crop.width = crop.height = 16;
    crop.getContext('2d').drawImage(live, 0, 0, pps, pps, 0, 0, 16, 16);
    assert.deepEqual(plain.pixels, crop.pixels, 'saved plain gradient/grid is the displayed representation');
    const colors = new Set();
    for (let i = 0; i < plain.pixels.length; i += 4) colors.add(String(plain.pixels.slice(i, i + 3)));
    assert.ok(colors.size > 1, 'plain ground preserves gradient/grid detail');
  } finally { pixelRasterOn = false; globalThis.getComputedStyle = priorComputedStyle; }
  const reload = session({storage});
  reload.board.setMap({...map([]), background: {style: 'wood'}, floors: []});
  reload.board.setRemembered(reload.rememberFog(seenOnly([at(0, 1)]), [], new Set()));
  assert.equal(groupOf(tileAt(reload.board, 2, 1)).querySelector('.tt-remembered-floor').getAttribute('href'), saved.swatch);
});

test('delayed image readiness snapshots currently visible ground, never unseen squares or stale map loads', () => {
  const storage = new Map(), first = session({storage});
  const image = first.board.element.querySelector('.tt-bg-image');
  image.setAttribute('src', 'old.png');
  first.board.setMap({...map([coverRow]), background: {url: 'old.png'}});
  const oldLoad = image.onload;
  // The stub has no src-property reflector; setAttribute simulates the browser.
  image.setAttribute('src', 'new.png');
  // Browsers may retain the old image's natural dimensions until decoding the
  // replacement; complete=false must prevent capturing those stale pixels.
  upgradeToPixelImage(image, 4, 2, new Uint8ClampedArray(4 * 2 * 4).fill(90));
  image.complete = false;
  first.board.setMap({...map([coverRow]), background: {url: 'new.png', fit: 'stretch'}});
  first.rememberFog(seenOnly([at(2, 1), at(1, 1)]), [], new Set());
  assert.equal(first.app.fogMemory.memory.cells[at(2, 1)].floor, null);
  first.app.fogMemoryInputs = [seenOnly([at(2, 1)]), [], new Set()];
  pixelRasterOn = true;
  let saved;
  try {
    upgradeToPixelImage(image, 64, 32, new Uint8ClampedArray(64 * 32 * 4).fill(180));
    image.complete = true;
    oldLoad();
    assert.equal(first.app.fogMemory.memory.cells[at(2, 1)].floor, null, 'an old URL callback cannot snapshot the new image');
    image.onload();
    saved = first.app.fogMemory.memory.cells[at(2, 1)].floor;
    assert.ok(saved?.swatch, 'image load records ground without waiting for another table render');
    assert.equal(first.app.fogMemory.memory.cells[at(1, 1)].floor, null, 'squares no longer seen are never backfilled');
    first.app.fogMemoryInputs = [seenOnly([at(0, 0)]), [], new Set()];
    image.pixels.fill(250);
    image.onload();
    assert.equal(first.app.fogMemory.memory.cells[at(2, 1)].floor.swatch, saved.swatch, 'loss of sight freezes the loaded crop');
    const pendingLoad = image.onload;
    first.board.setMap({...map([]), background: {style: 'grass'}});
    pendingLoad();
    assert.equal(first.app.fogMemory.memory.cells[at(2, 1)].floor.swatch, saved.swatch, 'a removed image cannot refresh memory');
  } finally { pixelRasterOn = false; }
  const reload = session({storage});
  reload.board.setMap(map([]));
  reload.board.setRemembered(reload.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  assert.equal(groupOf(tileAt(reload.board, 2, 1)).querySelector('.tt-remembered-floor').getAttribute('href'), saved.swatch);
});

// Crops one square's pixels out of a real paintFloor canvas (pixelRasterOn), the same way floorSwatchUrl does,
// so a test can build its own reference crop to compare the production swatch against.
function cropCell(canvas, mapWidth, x, y) {
  const pps = canvas.width / mapWidth, out = new Uint8ClampedArray(pps * pps * 4);
  for (let yy = 0; yy < pps; yy += 1) for (let xx = 0; xx < pps; xx += 1) {
    const si = ((y * pps + yy) * canvas.width + (x * pps + xx)) * 4, di = (yy * pps + xx) * 4;
    out[di] = canvas.pixels[si]; out[di + 1] = canvas.pixels[si + 1]; out[di + 2] = canvas.pixels[si + 2]; out[di + 3] = canvas.pixels[si + 3];
  }
  return out;
}

// Review r1 finding 1: a record with no floor provenance -- missing (an old v3 record) or explicitly null (no
// procedural texture when it was captured) -- must never fall back to today's live floor, which can leak a floor
// that changed while the square was unseen.
test('a record saved before floor provenance existed never shows the live floor underneath', () => {
  const chest = {id: 'chest', name: 'Chest', kind: 'chest', x: 2, y: 1, hp: 10};
  const storage = new Map([[memoryKey('match-1', 'viewer-a:on', WIDTH, HEIGHT), JSON.stringify({version: 3,
    cells: {[at(2, 1)]: {terrain: [], zones: [], tokens: [],
      objects: [{id: 'chest', name: 'Chest', kind: 'chest', x: 2, y: 1}]}}})]]);
  const s = session({storage, objects: [chest]});
  // The chest is gone now (the square is changed); the live map has a real procedural floor (flagstone).
  s.app.state.objects = [];
  look(s, {seen: seenOnly([at(0, 0)])});
  const tile = tileAt(s.board, 2, 1);
  assert.ok(tile, 'the changed square is drawn from its record');
  const image = groupOf(tile).querySelector('.tt-remembered-floor');
  assert.equal(image?.getAttribute('data-floor-style'), 'neutral',
    'a record with no floor field never shows the live floor; it gets the neutral fallback instead');
});

test('a record with no texture when it was captured never shows a floor added to the map later', () => {
  const storage = new Map();
  const first = session({storage});
  // Captured with a custom uploaded background: no procedural floor to record (explicit null).
  first.board.setMap({...map([coverRow]), background: {url: 'https://example.test/bg.png', opacity: 1}});
  first.board.setZones([], {round: 1});
  first.board.setFog(seenOnly([at(2, 1)]));
  first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
  // Reload: the custom image is gone, replaced by a real procedural floor; the cover is also gone (still marks
  // the square changed).
  const reloaded = session({storage});
  reloaded.board.setMap(map([]));
  reloaded.board.setZones([], {round: 1});
  reloaded.board.setFog(seenOnly([at(0, 0)]));
  reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
  const tile = tileAt(reloaded.board, 2, 1);
  assert.ok(tile, 'the changed square is drawn from its record');
  const image = groupOf(tile).querySelector('.tt-remembered-floor');
  assert.equal(image?.getAttribute('data-floor-style'), 'neutral',
    'an explicit no-texture record never shows a floor added to the map later');
});

// Review r1 finding 2: the floor index must drop a removed patch even when the procedural canvas stays hidden
// (a plain background with no patches left never repaints the canvas, so the old repaint-gated clear never ran).
test('floorAt drops a removed floor patch on a plain background', () => {
  const s = session({storage: new Map()});
  s.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'plain', seed: 1}, floors: [{style: 'wood', cells: [[2, 1]]}]});
  assert.deepEqual(s.board.floorAt(2, 1), {style: 'wood', seed: 1, patch: true}, 'the patch is reported while present');
  s.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'plain', seed: 1}, floors: []});
  assert.equal(s.board.floorAt(2, 1), null,
    'the removed patch is not reported once gone');
});

// Review r1 finding 3a: a changed remembered square must keep the seed it was captured with, not whatever the
// live map's seed is now -- otherwise reloading with a different seed (or the map simply being regenerated)
// changes the texture of ground the viewer never actually looked at again.
test('a changed remembered square keeps the seed it was painted with, not a later live seed', () => {
  // The sessions themselves (createBoard's own persistent canvases, e.g. the live floor) are built outside
  // pixelRasterOn -- they need the stub's full element (dataset, hidden, ...), not the minimal pixel-only one.
  // Only setMap/setFog/setRemembered (and the reference paintFloor calls) run under it: paintFloor's cache is
  // keyed by (style, seed, size, patch) regardless of raster mode, so if any of those specific calls ran as a
  // normal, content-free stub canvas first, the later real-pixel calls would just return that same cached,
  // pixel-less canvas (review r1 finding 4's bug, reproduced while writing this test).
  const storage = new Map();
  const first = session({storage});
  const reloaded = session({storage});
  pixelRasterOn = true;
  let oldCrop, newCrop, swatch;
  try {
    first.board.setMap({...map([coverRow]), background: {url: null, opacity: 1, style: 'flagstone', seed: 9001}});
    first.board.setZones([], {round: 1});
    first.board.setFog(seenOnly([at(2, 1)]));
    first.board.setRemembered(first.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
    // A plain background with no floor patch: floorAt's patch flag is false, so the reference must match (the
    // live board never paints its background with {patch: true}).
    oldCrop = cropCell(paintFloor('flagstone', 9001, WIDTH, HEIGHT), WIDTH, 2, 1);
    reloaded.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'flagstone', seed: 9002}});
    reloaded.board.setZones([], {round: 1});
    reloaded.board.setFog(seenOnly([at(0, 0)]));
    newCrop = cropCell(paintFloor('flagstone', 9002, WIDTH, HEIGHT), WIDTH, 2, 1);
    reloaded.board.setRemembered(reloaded.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
    const tile = tileAt(reloaded.board, 2, 1);
    const image = groupOf(tile)?.querySelector('.tt-remembered-floor');
    swatch = pixelsFromHref(image?.getAttribute('href'));
  } finally { pixelRasterOn = false; }
  assert.ok(swatch, 'the drawn swatch is a real pixel crop');
  assert.deepEqual(swatch.pixels, oldCrop, 'the remembered square keeps the seed it was captured with');
  assert.notDeepEqual(swatch.pixels, newCrop, "and does not match today's live seed");
});

// Review r1 finding 3b: an unchanged background floor must be drawn the way the live board draws a BACKGROUND
// (no {patch: true}), not substituted with patch-mode art -- some styles (dirt_road) omit real detail in patch
// mode that only the background painter draws (ruts and grass verges).
test('an unchanged background floor is drawn as the live background, not patch-mode art', () => {
  const s = session({storage: new Map()});
  pixelRasterOn = true;
  let backgroundCrop, patchCrop, swatch;
  try {
    s.board.setMap({...map([coverRow]), background: {url: null, opacity: 1, style: 'dirt_road', seed: 9003}});
    s.board.setZones([], {round: 1});
    s.board.setFog(seenOnly([at(2, 1)]));
    s.board.setRemembered(s.rememberFog(seenOnly([at(2, 1)]), [], new Set()));
    // The cover is gone while the viewer looks elsewhere: the square is changed, but its background floor style
    // has not changed at all.
    s.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'dirt_road', seed: 9003}});
    backgroundCrop = cropCell(paintFloor('dirt_road', 9003, WIDTH, HEIGHT), WIDTH, 2, 1);
    patchCrop = cropCell(paintFloor('dirt_road', 9003, WIDTH, HEIGHT, {patch: true}), WIDTH, 2, 1);
    s.board.setZones([], {round: 1});
    s.board.setFog(seenOnly([at(0, 0)]));
    s.board.setRemembered(s.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
    const tile = tileAt(s.board, 2, 1);
    const image = groupOf(tile)?.querySelector('.tt-remembered-floor');
    swatch = pixelsFromHref(image?.getAttribute('href'));
  } finally { pixelRasterOn = false; }
  assert.ok(swatch, 'the drawn swatch is a real pixel crop');
  assert.deepEqual(swatch.pixels, backgroundCrop, 'the background style is drawn the way the live board draws a background');
  assert.notDeepEqual(swatch.pixels, patchCrop,
    "and not substituted with patch-mode art, which omits background-only detail (dirt_road's ruts and verges)");
});

// Review r1 finding 4: the pixel regression must exercise the real remembered-floor rendering path (setRemembered
// -> floorSwatchUrl -> the real paintFloor canvas), not call paintFloor alone -- that would pass even if the
// production fix (the <image class="tt-remembered-floor"> itself) were removed.
test('the floor art a remembered square draws is a real crop through setRemembered, non-uniform, not a flat block', () => {
  const chest = {id: 'chest', name: 'Chest', kind: 'chest', x: 2, y: 1, hp: 10};
  const s = session({storage: new Map(), objects: [chest]});
  pixelRasterOn = true;
  let swatch;
  try {
    s.board.setMap({...map([]), background: {url: null, opacity: 1, style: 'flagstone', seed: 9004}});
    s.board.setZones([], {round: 1});
    s.board.setFog(seenOnly([at(2, 1)]));
    // The chest must actually be recorded as perceived here, or its removal below changes nothing to react to.
    s.board.setRemembered(s.rememberFog(seenOnly([at(2, 1)]), [], new Set(['chest'])));
    s.app.state.objects = [];
    s.board.setFog(seenOnly([at(0, 0)]));
    s.board.setRemembered(s.rememberFog(seenOnly([at(0, 0)]), [], new Set()));
    const tile = tileAt(s.board, 2, 1);
    assert.ok(tile, 'the changed square (its object is gone) is drawn from its record');
    const image = groupOf(tile).querySelector('.tt-remembered-floor');
    swatch = pixelsFromHref(image?.getAttribute('href'));
  } finally { pixelRasterOn = false; }
  assert.ok(swatch, "setRemembered draws a real crop, not the stub's placeholder image");
  const colors = new Set();
  for (let i = 0; i < swatch.pixels.length; i += 4) colors.add(`${swatch.pixels[i]},${swatch.pixels[i + 1]},${swatch.pixels[i + 2]}`);
  assert.ok(colors.size > 1, 'the ground texture drawn is non-uniform, not a flat fill');
  assert.ok(!colors.has('7,9,14'), 'the texture is not the opaque remembered-tile base colour');
});
