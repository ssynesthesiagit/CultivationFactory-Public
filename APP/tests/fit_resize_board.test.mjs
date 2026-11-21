import test from 'node:test';
import assert from 'node:assert/strict';
import {installDOM} from './objects_dom_stub.mjs';
import {map} from './area_elevation_fixture.mjs';
import {createBoard} from '../static/tabletop/board.js';

// FITRESIZE1: Fit is computed from the viewport size at the click. The table's viewport shrinks when the
// action bar grows (a menu landing after "Loading your choices…"), so a fitted board must refit when the
// viewport resizes, and a view the player zoomed, panned or centred must stay where they left it.
function setup() {
  const observers = [];
  globalThis.ResizeObserver = class { constructor(fn) { this.fn = fn; observers.push(this); } observe(node) { this.node = node; } };
  const doc = installDOM('<body></body>'), viewport = doc.body;
  let rect = {left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600};
  viewport.getBoundingClientRect = () => rect;
  const board = createBoard(viewport);
  delete globalThis.ResizeObserver;
  board.setMap(map);
  const observer = observers.find(o => o.node === viewport);
  assert.ok(observer, 'the board observes its viewport size');
  const resize = height => { rect = {...rect, bottom: height, height}; observer.fn([]); };
  return {board, viewport, resize};
}

test('a fitted board refits when the viewport shrinks', () => {
  const {board, resize} = setup();
  board.fit();
  const before = board.view;
  resize(380);
  const after = board.view;
  assert.ok(after.zoom < before.zoom, `zoom ${after.zoom} refit to the shorter viewport (was ${before.zoom})`);
  board.fit();
  assert.deepEqual(board.view, after, 'the resize produced exactly what Fit gives at the new size');
});

for (const [name, move] of [
  ['zoomed', board => board.zoomBy(1.5)],
  ['centred', board => board.centerOn(2, 2)],
  ['panned', async (board, viewport) => {
    await viewport.dispatch('pointerdown', {pointerId: 1, clientX: 100, clientY: 100, button: 0});
    await viewport.dispatch('pointermove', {pointerId: 1, clientX: 160, clientY: 130});
  }],
]) test(`a ${name} view stays put when the viewport resizes`, async () => {
  const {board, viewport, resize} = setup();
  board.fit();
  await move(board, viewport);
  const before = board.view;
  resize(380);
  assert.deepEqual(board.view, before);
});
