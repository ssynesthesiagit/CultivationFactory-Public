// RULER1 (owner feedback desk FD-17): a right-press on a square, dragged to another square, draws
// a measuring line and a length tag, and never disagrees with the engine about the distance.
// None of this touches the fight, so it is plain JavaScript and runs without a browser.
//
// The fixtures below were computed with the engine itself
// (combat/gate2_grid.py SquareGrid.distance_between_cell_sets_ft); tests/test_map_ruler.py
// recomputes the same paths in Python on every run, so a drift on either side fails.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {installDOM} from '../../tests/objects_dom_stub.mjs';
import {RULER_DRAG_PX, rulerCells, rulerMeasure, rulerMarkup, createMapRuler} from './ruler.js';

// [from, to, square size, engine feet, engine cells]
const ENGINE_FIXTURES = [
  [{x: 0, y: 0}, {x: 4, y: 0}, 5, 20, 4],      // straight
  [{x: 0, y: 0}, {x: 3, y: 3}, 5, 15, 3],      // diagonal: one square per step, like a king
  [{x: 1, y: 1}, {x: 4, y: 5}, 5, 20, 4],      // mixed (3 across, 4 down)
  [{x: 0, y: 0}, {x: 4, y: 3}, 5, 20, 4],      // mixed (4 across, 3 down)
  [{x: 5, y: 5}, {x: 2, y: 3}, 5, 15, 3],      // mixed, negative direction
  [{x: 0, y: 0}, {x: 0, y: 7}, 5, 35, 7],      // a long straight run
  [{x: 2, y: 2}, {x: 2, y: 2}, 5, 0, 0],       // same square
  [{x: 0, y: 0, z: 0}, {x: 3, y: 3, z: 3}, 5, 15, 3],   // height counted as a third axis
  [{x: 0, y: 0, z: 0}, {x: 2, y: 2, z: 3}, 5, 15, 3],   // height is the longest axis
  [{x: 0, y: 0, z: 5}, {x: 0, y: 0, z: 0}, 5, 25, 5],   // straight up
  [{x: 1, y: 1, z: 1}, {x: 4, y: 3, z: 2}, 5, 15, 3],
  [{x: 0, y: 0, z: 1}, {x: 2, y: 2, z: 0}, 5, 10, 2],
  [{x: 0, y: 0}, {x: 3, y: 4}, 10, 40, 4],     // a map whose squares are 10 feet
];

test('the ruler uses the engine distance for straight, diagonal, mixed and height paths', () => {
  for (const [from, to, size, feet, cells] of ENGINE_FIXTURES) {
    const measure = rulerMeasure(from, to, size);
    assert.deepEqual([measure.feet, measure.cells], [feet, cells],
      `${JSON.stringify(from)} -> ${JSON.stringify(to)} at ${size} ft squares`);
    assert.equal(rulerCells(from, to), cells);
  }
});

test('the length tag says the feet, the squares and whether it is ground distance', () => {
  assert.equal(rulerMeasure({x: 0, y: 0}, {x: 3, y: 3}, 5).headline, '15 ft (3 squares)');
  assert.equal(rulerMeasure({x: 0, y: 0}, {x: 3, y: 3}, 5).detail, 'ground distance');
  assert.equal(rulerMeasure({x: 4, y: 4}, {x: 5, y: 4}, 5).headline, '5 ft (1 square)');
  assert.equal(rulerMeasure({x: 2, y: 2}, {x: 2, y: 2}, 5).headline, '0 ft (0 squares)');
  const raised = rulerMeasure({x: 0, y: 0, z: 3}, {x: 3, y: 0, z: 0}, 5);
  assert.equal(raised.headline, '15 ft (3 squares)');
  assert.equal(raised.detail, 'distance including height');
  assert.equal(raised.heightIncluded, true);
  // A missing square size falls back to five feet rather than reporting nonsense.
  assert.equal(rulerMeasure({x: 0, y: 0}, {x: 2, y: 0}, 0).headline, '10 ft (2 squares)');
});

test('the drawing is a line between the two square centres with the tag on it', () => {
  const markup = rulerMarkup({x: 10, y: 20}, {x: 150, y: 20}, rulerMeasure({x: 0, y: 0}, {x: 2, y: 0}, 5), {width: 800});
  assert.match(markup, /class="tt-ruler-line"[^>]*x1="10"[^>]*y1="20"[^>]*x2="150"[^>]*y2="20"/);
  assert.match(markup, /10 ft \(2 squares\)/);
  assert.match(markup, /ground distance/);
  assert.equal((markup.match(/class="tt-ruler-end"/g) || []).length, 2);
});

function rulerHarness({active = true} = {}) {
  installDOM('<body><div id="ttViewport"></div></body>');
  const doc = globalThis.document;
  const viewport = doc.querySelector('#ttViewport');
  const state = {cancelled: 0};
  const view = {x: 0, y: 0, zoom: 1};
  const ruler = createMapRuler({
    viewport,
    cellAt: (x, y) => (x < 0 || y < 0 ? null : {x: Math.floor(x / (64 * view.zoom)), y: Math.floor(y / (64 * view.zoom))}),
    toPixels: cell => ({x: (cell.x + 0.5) * 64, y: (cell.y + 0.5) * 64}),
    squareSizeFt: () => 5,
    onPlainRightClick: () => { state.cancelled += 1; },
    doc,
  });
  const press = (x, y, id = 1) => viewport.dispatch('pointerdown', {button: 2, pointerId: id, clientX: x, clientY: y});
  const move = (x, y, id = 1) => viewport.dispatch('pointermove', {button: 2, buttons: 2, pointerId: id, clientX: x, clientY: y});
  const release = (x, y, id = 1) => viewport.dispatch('pointerup', {button: 2, pointerId: id, clientX: x, clientY: y});
  return {doc, viewport, ruler, state, press, move, release, overlay: () => doc.querySelector('.tt-ruler')};
}

test('a right-click that does not drag is still an ordinary click, and draws nothing', async () => {
  const h = rulerHarness();
  await h.press(32, 32);
  await h.move(35, 33);         // a few pixels of wobble stay inside the threshold
  assert.equal(h.overlay().innerHTML, '');
  await h.release(35, 33);
  assert.equal(h.state.cancelled, 1);
  assert.equal(h.overlay().innerHTML, '');
  assert.equal(RULER_DRAG_PX, 6);
});

test('a right-drag draws a live length tag and does not count as a click', async () => {
  const h = rulerHarness();
  await h.press(32, 32);                 // square 0,0
  await h.move(224, 32);                 // square 3,0
  assert.match(h.overlay().innerHTML, /15 ft \(3 squares\)/);
  assert.match(h.overlay().innerHTML, /ground distance/);
  assert.equal(h.state.cancelled, 0);
  await h.release(224, 32);
  assert.equal(h.overlay().innerHTML, '', 'the line goes away when the button is released');
  assert.equal(h.state.cancelled, 0, 'measuring never cancels the ability pick');
});

// The engine counts height as a third axis (combat/gate2_grid.py distance_cells). The production
// wiring must hand each end the height of the token in its square: without it a flyer 20 ft up read
// 5 ft from the neighbouring square while the engine says 20 ft.
test('a production drag from an airborne token includes its height, like the engine', async () => {
  const h = wiringHarness();
  h.state.heights.set('0,0', 4);         // a creature 20 ft above the floor on square 0,0
  await h.press(32, 32);
  await h.move(96, 32);                  // one square across, four squares up
  assert.match(h.overlay().innerHTML, /20 ft \(4 squares\)/, 'height is the longest of the three axes');
  assert.match(h.overlay().innerHTML, /distance including height/);
  await h.release(96, 32);
});

test('a right-drag to a diagonal square reports the engine distance, not the path length', async () => {
  const h = rulerHarness();
  await h.press(32, 32);
  await h.move(32 + 3 * 64, 32 + 3 * 64);
  assert.match(h.overlay().innerHTML, /15 ft \(3 squares\)/);
  await h.release(32 + 3 * 64, 32 + 3 * 64);
});

test('a drag outside the map keeps the last square instead of dropping the line', async () => {
  const h = rulerHarness();
  await h.press(32, 32);
  await h.move(224, 32);
  await h.move(-40, -40);                // off the map: board.cellAt() answers null
  assert.match(h.overlay().innerHTML, /15 ft \(3 squares\)/);
  await h.release(224, 32);
});

// ---------------------------------------------------------------- production wiring
// tabletop.js keeps the real right-click contract in two places: the contextmenu listener (cancel
// an open pick) and wireMapRuler() (measure on drag, cancel on a plain click). Both are read out of
// the shipped file and run against a stubbed table so the ordering browsers use cannot break them.
const tabletop = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');

function piece(name) {
  const start = tabletop.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return tabletop.slice(start, tabletop.indexOf('\n}', start) + 2);
}

function wiringHarness() {
  installDOM('<body><div id="ttViewport"></div></body>');
  const viewport = globalThis.document.querySelector('#ttViewport');
  const state = {cancelled: 0, active: true, prevented: 0, heights: new Map()};
  const board = {view: {x: 0, y: 0, zoom: 1}, map: {square_size_ft: 5},
    cellAt: (x, y) => ({x: Math.floor(x / 64), y: Math.floor(y / 64)}),
    // What the real board answers: the height in squares of the token drawn in the square (board.js).
    heightAtCell: (x, y) => state.heights.get(`${x},${y}`) || 0};
  const start = tabletop.indexOf('$("#ttViewport").addEventListener("contextmenu"');
  const end = tabletop.indexOf('document.addEventListener("keydown"', start);
  assert.ok(start >= 0 && end > start, 'the production right-click handler is where the test expects it');
  const code = `${piece('wireMapRuler')}
    const ruler = wireMapRuler($("#ttViewport"));
    ${tabletop.slice(start, end)}
    globalThis.__ruler = ruler;`;
  runInNewContext(code, {board, CELL: 64, createMapRuler, $: () => viewport,
    abilityChoiceActive: () => state.active,
    cancelAbilityChoice: () => { state.cancelled += 1; }});
  const press = (x, y) => viewport.dispatch('pointerdown', {button: 2, pointerId: 1, clientX: x, clientY: y});
  const move = (x, y) => viewport.dispatch('pointermove', {button: 2, buttons: 2, pointerId: 1, clientX: x, clientY: y});
  const release = (x, y) => viewport.dispatch('pointerup', {button: 2, pointerId: 1, clientX: x, clientY: y});
  const menu = () => viewport.dispatch('contextmenu', {preventDefault() { state.prevented += 1; }});
  const overlay = () => globalThis.document.querySelector('.tt-ruler');
  return {state, press, move, release, menu, overlay, viewport, doc: globalThis.document};
}

// A token is a child of the viewport that stops propagation of its own pointerdown, as board.js does.
function addToken(doc, viewport) {
  const token = doc.createElement('div');
  token.addEventListener('pointerdown', event => event.stopPropagation());
  viewport.appendChild(token);
  return token;
}

// Delivers a press that starts on the token the way a browser does: the viewport's capture listeners
// first, then the token, then the viewport's bubble listeners, which the token's stopPropagation()
// cuts off. The stub's plain dispatch() would call every listener and hide that ordering.
async function pressOnToken(viewport, token, details) {
  let stopped = false;
  const event = {target: token, button: 2, buttons: 2, pointerId: 1, preventDefault() {}, ...details,
    stopPropagation() { stopped = true; }};
  const all = viewport.listeners.get('pointerdown') || [];
  const captured = all.filter(fn => viewport.captureListeners?.has(fn));
  const bubbling = all.filter(fn => !viewport.captureListeners?.has(fn));
  await Promise.all(captured.map(fn => fn(event)));
  await Promise.all((token.listeners.get('pointerdown') || []).map(fn => fn(event)));
  if (!stopped) await Promise.all(bubbling.map(fn => fn(event)));
}

test('right-click without a drag still cancels targeting, whichever contextmenu order the browser uses', async () => {
  // Linux/Windows Chromium fires contextmenu on the press; macOS on the release. Both must cancel once.
  for (const order of ['menu-on-press', 'menu-on-release']) {
    const h = wiringHarness();
    await h.press(32, 32);
    if (order === 'menu-on-press') await h.menu();
    await h.release(32, 32);
    if (order === 'menu-on-release') await h.menu();
    assert.equal(h.state.cancelled, 1, order);
    assert.ok(h.state.prevented >= 1, `${order}: the browser menu is suppressed`);
  }
});

test('a ruler drag never cancels the ability pick, whichever contextmenu order the browser uses', async () => {
  for (const order of ['menu-on-press', 'menu-on-release']) {
    const h = wiringHarness();
    await h.press(32, 32);
    await h.move(224, 32);
    if (order === 'menu-on-press') await h.menu();
    assert.match(h.overlay().innerHTML, /15 ft \(3 squares\)/, `${order}: the line is live while dragging`);
    await h.release(224, 32);
    if (order === 'menu-on-release') await h.menu();
    assert.equal(h.state.cancelled, 0, order);
    assert.equal(h.overlay().innerHTML, '', order);
  }
});

test('with no pick open a right click answers nothing at all', async () => {
  const h = wiringHarness();
  h.state.active = false;
  await h.press(32, 32);
  await h.menu();
  await h.release(32, 32);
  assert.equal(h.state.cancelled, 0);
  assert.equal(h.state.prevented, 0);
});

test('the ruler is created once and its overlay lives above the map', () => {
  const h = wiringHarness();
  assert.equal(globalThis.document.querySelectorAll('.tt-ruler-layer').length, 1);
  assert.equal(h.overlay().getAttribute('class'), 'tt-ruler');
});

// A press that starts on a token square is stopped by the token (board.js). The ruler listens in the
// capture phase so it still sees it: without that, a drag from your own creature never measures and
// on Linux (menu on press) the pick is cancelled by the contextmenu.
test('a right-drag that starts on a token square measures from it and never cancels the pick', async () => {
  for (const order of ['menu-on-press', 'menu-on-release']) {
    const h = wiringHarness();
    const token = addToken(h.doc, h.viewport);
    await pressOnToken(h.viewport, token, {clientX: 32, clientY: 32});
    await h.move(224, 32);
    if (order === 'menu-on-press') await h.menu();
    assert.match(h.overlay().innerHTML, /15 ft \(3 squares\)/, `${order}: the line is live from the token square`);
    await h.release(224, 32);
    if (order === 'menu-on-release') await h.menu();
    assert.equal(h.state.cancelled, 0, order);
    assert.equal(h.overlay().innerHTML, '', order);
  }
});

test('a plain right-click on a token square still cancels targeting', async () => {
  const h = wiringHarness();
  const token = addToken(h.doc, h.viewport);
  await pressOnToken(h.viewport, token, {clientX: 32, clientY: 32});
  await h.menu();
  await h.release(32, 32);
  assert.equal(h.state.cancelled, 1);
});

// On Linux the menu opens on press, so the release is the last event of the click. That release must
// not leave a one-shot flag behind, or the next keyboard menu key (a contextmenu with no right press)
// would be swallowed once and could not cancel the pick.
test('a keyboard menu after a Linux right-click still cancels the open pick', async () => {
  const h = wiringHarness();
  await h.press(32, 32);
  await h.menu();
  await h.release(32, 32);
  assert.equal(h.state.cancelled, 1);
  await h.menu();
  assert.equal(h.state.cancelled, 2);
});
