// node --test APP/static/tabletop/board-terrain.test.mjs
// Terrain on the real board, not just the exported helpers: the overlay toggle must redraw the
// rules squares, each square must land on exactly one map square, and
// hovering overlapping rules must explain every one of them.  board.js is driven through a small
// DOM stub, the same way zones.test.mjs drives the painted materials: no browser, no canvas pixels.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CELL, createBoard} from './board.js';

// ---------------------------------------------------------------- the DOM stub
function stubContext() {
  const gradient = {addColorStop() {}};
  const noop = () => {};
  return {fillStyle: "", strokeStyle: "", lineWidth: 1, lineCap: "butt", filter: "none", globalCompositeOperation: "source-over",
          createImageData: (width, height) => ({width, height, data: new Uint8ClampedArray(width * height * 4)}),
          createLinearGradient: () => gradient, createRadialGradient: () => gradient,
          beginPath: noop, closePath: noop, moveTo: noop, lineTo: noop, quadraticCurveTo: noop, ellipse: noop,
          fill: noop, stroke: noop, fillRect: noop, clearRect: noop, drawImage: noop, putImageData: noop,
          save: noop, restore: noop, translate: noop, rotate: noop};
}

class StubElement {
  constructor(tag, namespaceURI = null) {
    this.tagName = String(tag).toLowerCase();
    this.namespaceURI = namespaceURI;
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.dataset = {};
    this.hidden = false;
    this.textContent = "";
    this.innerHTML = "";
    this.offsetWidth = 140;
    this.offsetHeight = 60;
    this.style = {setProperty(name, value) { this[name] = value; }};
    this.listeners = new Map();
    this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      contains: name => this.classes.has(name),
      toggle: (name, force) => { const on = force === undefined ? !this.classes.has(name) : Boolean(force); if (on) this.classes.add(name); else this.classes.delete(name); return on; },
    };
  }
  get className() { return [...this.classes].join(" "); }
  set className(value) { this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); this.attributes.set("class", this.className); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); if (name === "class") this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  removeAttribute(name) { this.attributes.delete(name); }
  appendChild(node) { node.parentNode = this; this.childNodes.push(node); return node; }
  replaceChildren(...nodes) { this.childNodes = []; for (const node of nodes) this.appendChild(node); }
  remove() { this.parentNode = null; }
  addEventListener(type, handler) { this.listeners.set(type, [...(this.listeners.get(type) || []), handler]); }
  dispatch(type, event = {}) { for (const handler of this.listeners.get(type) || []) handler(event); }
  getBoundingClientRect() { return {left: 0, top: 0, right: 1280, bottom: 720, width: 1280, height: 720}; }
  setPointerCapture() {}
  getContext() { return (this.context ||= stubContext()); }
  querySelector() { return null; }
  // Every descendant whose class list holds the name, the way querySelectorAll would find them.
  byClass(name) {
    const out = [];
    for (const child of this.childNodes) {
      if (child.classes?.has(name)) out.push(child);
      out.push(...child.byClass(name));
    }
    return out;
  }
  // Every piece of text under this node, in document order.
  text() {
    const parts = this.textContent ? [this.textContent] : [];
    for (const child of this.childNodes) parts.push(child.text());
    return parts.filter(Boolean).join(" | ");
  }
}

function withDom(run) {
  const previous = {document: globalThis.document, window: globalThis.window, localStorage: globalThis.localStorage, requestAnimationFrame: globalThis.requestAnimationFrame,
                    setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout};
  const body = new StubElement("body");
  globalThis.window = {innerWidth: 1280, innerHeight: 720, addEventListener() {}, removeEventListener() {}};
  const store = new Map();
  globalThis.document = {
    body,
    addEventListener() {}, removeEventListener() {},
    createElement: tag => new StubElement(tag),
    createElementNS: (ns, tag) => new StubElement(tag, ns),
  };
  globalThis.localStorage = {getItem: key => (store.has(key) ? store.get(key) : null), setItem: (key, value) => store.set(key, String(value))};
  globalThis.requestAnimationFrame = callback => { callback(); return 0; };
  // The hover card waits for the pointer to rest (board.js:887). Run those timers on the spot so
  // the card is there to read, instead of arriving after the test finished.
  let pending = 0;
  globalThis.setTimeout = callback => { pending += 1; callback(); return pending; };
  globalThis.clearTimeout = () => {};
  try {
    return run();
  } finally {
    for (const key of ["document", "window", "localStorage", "requestAnimationFrame", "setTimeout", "clearTimeout"]) {
      globalThis[key] = previous[key];
    }
  }
}

// The terrain layer's rule groups: the <g transform="translate(x y) scale(s)"> nodes board.js
// creates for each rules cell.  The blocked/sight rects go straight into the layer, so a transform
// is exactly what separates a drawn rules square from them.
function ruleGroups(board) {
  const layer = board.element.byClass("tt-terrain")[0];
  return (layer?.childNodes || []).filter(node => (node.getAttribute("transform") || "").startsWith("translate("));
}

// One square's painted bounds, in the layer's own square units: the group's translate and scale
// applied to the rect drawn inside it.
function squareBounds(group) {
  const transform = group.getAttribute("transform");
  const [x, y] = transform.match(/translate\((-?[\d.]+) (-?[\d.]+)\)/).slice(1).map(Number);
  const scale = Number(transform.match(/scale\(([\d.]+)\)/)?.[1] ?? 1);  // a missing scale is the bug, not a crash
  const rect = group.innerHTML.match(/<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"/);
  if (!rect) return null;
  const [rx, ry, rw, rh] = rect.slice(1).map(Number);
  return {scale, min: {x: x + rx * scale, y: y + ry * scale}, max: {x: x + (rx + rw) * scale, y: y + (ry + rh) * scale}};
}

function rulesSquareClasses(group) {
  return [...group.innerHTML.matchAll(/class="(tt-cell-[a-z]+)"/g)].map(match => match[1]);
}

// The board tooltip, after the pointer has rested on a square long enough for the card to appear.
// The shared hover card hangs off document.body, not the board viewport.
function hoverText(viewport, board, x, y) {
  board.viewport.dispatch("pointermove", {clientX: x * CELL + CELL / 2, clientY: y * CELL + CELL / 2, buttons: 0});
  return document.body.byClass("tt-zone-tip")[0]?.text() || "";
}

// ---------------------------------------------------------------- the maps under test
const sectMap = JSON.parse(readFileSync(new URL('../../combat/maps/builtin-sect-trial-platform.json', import.meta.url), 'utf8'));

// The shape tabletop.js hands the board for a saved fight: rule terrain rows plus the legacy
// per-type cell lists older maps and fights still carry.
function boardMap({terrain = [], cells = {}, width = 20, height = 16} = {}) {
  return {width, height, background: {url: null, opacity: 1, style: "flagstone", seed: 3702}, display: {},
          walls: [], trees: [], ruleTerrain: terrain, cells: {blocked: [], cover: [], hazard: [], difficult: [], ...cells}};
}

const coverRow = {type: "SIMPLE_COVER", look: "low_wall", cells: [[6, 2], [7, 2]]};
const difficultRow = {type: "DIFFICULT", look: "scree", cells: [[7, 2]]};  // overlaps the cover at 7,2

test('the board paints natural scenery for rule terrain and redraws the rules squares on the overlay toggle', async t => {
  await t.test('the loaded Sect platform shows no frames by default and full rules squares on demand', async () => {
    await withDom(async () => {
      const board = createBoard(new StubElement("div"));
      board.setMap(boardMap({terrain: sectMap.terrain}));

      const natural = ruleGroups(board);
      assert.equal(natural.length, sectMap.terrain[0].cells.length, 'every Sect rules cell is drawn');
      for (const group of natural) {
        assert.match(group.innerHTML, /<g class="tt-rule-terrain/);
        assert.doesNotMatch(group.innerHTML, /tt-cell-|<rect/, 'natural scenery carries no rules frame');
      }

      board.setRulesOverlay(true);
      const framed = ruleGroups(board);
      assert.equal(framed.length, sectMap.terrain[0].cells.length, 'the toggle redraws every rules cell');
      for (const group of framed) {
        assert.deepEqual(rulesSquareClasses(group), ['tt-cell-cover']);
        assert.doesNotMatch(group.innerHTML, /tt-rule-terrain/, 'overlay mode replaces the scenery, it does not stack on it');
      }

      board.setRulesOverlay(false);
      const back = ruleGroups(board);
      assert.equal(back.length, sectMap.terrain[0].cells.length, 'turning the overlay off repaints the scenery');
      for (const group of back) assert.match(group.innerHTML, /<g class="tt-rule-terrain/);
    });
  });

  await t.test('a rules square covers exactly one map square without adding a frame', async () => {
    await withDom(async () => {
      const board = createBoard(new StubElement("div"));
      board.setMap(boardMap({terrain: [coverRow, difficultRow]}));
      const layer = board.element.byClass("tt-terrain")[0];
      assert.equal(layer.getAttribute("viewBox"), "0 0 20 16", 'the layer works in whole squares');

      board.setRulesOverlay(true);
      const bounds = new Map();
      for (const group of ruleGroups(board)) {
        const [x, y] = group.getAttribute("transform").match(/translate\((-?[\d.]+) (-?[\d.]+)\)/).slice(1).map(Number);
        bounds.set(`${x},${y}`, squareBounds(group));
      }
      assert.deepEqual([...bounds.keys()].sort(), ['6,2', '7,2'], 'the overlap paints one group per square');

      // The whole point of the 1/64 scale: the 64x64 local frame lands on a single map square.
      for (const [key, square] of bounds) {
        const [x, y] = key.split(',').map(Number);
        assert.deepEqual(square.min, {x, y}, `${key} starts on its own square`);
        assert.deepEqual(square.max, {x: x + 1, y: y + 1}, `${key} ends one square later, not 64 squares later`);
      }

      // Owner-approved tabletop styling keeps rule squares borderless to avoid a grid over the map.
      for (const group of ruleGroups(board)) {
        assert.doesNotMatch(group.innerHTML, /stroke(?:-width)?=/, 'rules overlay does not add a frame or hatch stroke');
      }
      const css = readFileSync(new URL('./tabletop.css', import.meta.url), 'utf8');
      for (const cls of ['cover', 'hazard', 'difficult']) {
        const rule = new RegExp(`\\.tt-cell-${cls}\\s*\\{([^}]*)`).exec(css)?.[1] || '';
        assert.doesNotMatch(rule, /stroke(?:-width)?\s*:/, `.tt-cell-${cls} stays borderless`);
      }
    });
  });
});

test('hovering a square explains every rule that applies to it', async t => {
  await t.test('a square with both cover and difficult ground lists both', async () => {
    await withDom(async () => {
      const viewport = new StubElement("div");
      const board = createBoard(viewport);
      board.setMap(boardMap({terrain: [coverRow, difficultRow]}));
      const text = hoverText(viewport, board, 7, 2);
      assert.match(text, /Simple cover.*\+2 AC/s, 'the cover benefit is explained');
      assert.match(text, /Difficult terrain.*one extra foot/s, 'the movement cost is explained too');
    });
  });

  await t.test('a square with a single rule still explains only that rule', async () => {
    await withDom(async () => {
      const viewport = new StubElement("div");
      const board = createBoard(viewport);
      board.setMap(boardMap({terrain: [coverRow, difficultRow]}));
      const text = hoverText(viewport, board, 6, 2);
      assert.match(text, /Simple cover/);
      assert.doesNotMatch(text, /Difficult terrain/, 'the neighbouring square\'s rule is not borrowed');
    });
  });

  await t.test('legacy map.cells terrain draws and hovers like the rule rows', async () => {
    await withDom(async () => {
      const viewport = new StubElement("div");
      const board = createBoard(viewport);
      board.setMap(boardMap({terrain: [], cells: {cover: [[3, 5]], difficult: [[3, 5]]}}));
      // One drawing per type, as the map editor's own cells are: the two lists share a square, so
      // both the cover and the difficult ground are painted on it.
      const drawn = ruleGroups(board);
      assert.equal(drawn.length, 2, 'both legacy rules are drawn on the square they share');
      assert.deepEqual(drawn.flatMap(rulesSquareClasses), [], 'natural scenery carries no rules frame');
      for (const group of drawn) assert.match(group.innerHTML, /<g class="tt-rule-terrain/);

      board.setRulesOverlay(true);
      const framed = ruleGroups(board);
      assert.equal(framed.length, 2, 'the toggle still frames every legacy square');
      assert.deepEqual(framed.flatMap(rulesSquareClasses).sort(), ['tt-cell-cover', 'tt-cell-difficult']);
      for (const group of framed) {
        assert.deepEqual(squareBounds(group).max, {x: 4, y: 6}, 'and each still lands on one square');
      }

      const text = hoverText(viewport, board, 3, 5);
      assert.match(text, /Simple cover.*\+2 AC/s);
      assert.match(text, /Difficult terrain.*one extra foot/s, 'both legacy rules reach the hover card');
    });
  });
});
