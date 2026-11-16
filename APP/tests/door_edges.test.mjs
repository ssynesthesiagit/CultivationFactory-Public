// DOOREDGE (owner 2026-10-10): a door, gate or window snaps to the wall line nearest the pointer
// inside its square -- any of the four edges or the middle -- while it stays on a straight wall.
// These pin the shared snapping geometry and drive the real editor entry point for placement and preview.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';
import {durability as defaults} from './object_defaults_fixture.mjs';
import {snapOpening, nearestOpeningSpot, openingOffset, wallMount} from '../static/tabletop/wall-openings.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';

const wall = (axis, line, from = 1, to = 20) => axis === 'h'
  ? {shape: 'line', points: [[from, line], [to, line]], blocks: 'sight_and_movement'}
  : {shape: 'line', points: [[line, from], [line, to]], blocks: 'sight_and_movement'};

test('a pointer near each edge or the middle snaps the opening to that line', () => {
  const cell = [4, 4];
  const cases = [
    ['top', wall('h', 4), {x: 4.5, y: 4.2}, {mount_axis: 'h', mount_line: 400, x: 4, y: 4}],
    ['bottom', wall('h', 5), {x: 4.5, y: 4.8}, {mount_axis: 'h', mount_line: 500, x: 4, y: 5}],
    ['left', wall('v', 4), {x: 4.2, y: 4.5}, {mount_axis: 'v', mount_line: 400, x: 4, y: 4}],
    ['right', wall('v', 5), {x: 4.8, y: 4.5}, {mount_axis: 'v', mount_line: 500, x: 5, y: 4}],
    ['middle', wall('h', 4.5), {x: 4.5, y: 4.6}, {mount_axis: 'h', mount_line: 450, x: 4, y: 4}],
    ['middle', wall('v', 4.5), {x: 4.6, y: 4.5}, {mount_axis: 'v', mount_line: 450, x: 4, y: 4}],
  ];
  for (const [edge, only, point, wanted] of cases) {
    assert.deepEqual(snapOpening(cell, point, [only]), {...wanted, edge}, `${edge} edge`);
  }
});

test('a pointer inside the square chooses the nearer of two parallel walls', () => {
  const cell = [6, 4], walls = [wall('h', 4), wall('h', 5)];
  assert.equal(snapOpening(cell, {x: 6.5, y: 4.1}, walls).mount_line, 400, 'upper half picks the top edge');
  assert.equal(snapOpening(cell, {x: 6.5, y: 4.9}, walls).mount_line, 500, 'lower half picks the bottom edge');
  const columns = [wall('v', 6), wall('v', 7)];
  assert.equal(snapOpening(cell, {x: 6.1, y: 4.5}, columns).mount_line, 600, 'left half picks the left edge');
  assert.equal(snapOpening(cell, {x: 6.9, y: 4.5}, columns).mount_line, 700, 'right half picks the right edge');
});

test('only a real wall is offered; a square with no wall refuses and names the edge', () => {
  const cell = [4, 4];
  assert.equal(snapOpening(cell, {x: 4.5, y: 4.5}, []), null);
  assert.equal(nearestOpeningSpot(cell, {x: 4.5, y: 4.8}), 'bottom');
  assert.equal(nearestOpeningSpot(cell, {x: 4.5, y: 4.2}), 'top');
  assert.equal(nearestOpeningSpot(cell, {x: 4.2, y: 4.5}), 'left');
  assert.equal(nearestOpeningSpot(cell, {x: 4.8, y: 4.5}), 'right');
  assert.equal(nearestOpeningSpot(cell, {x: 4.5, y: 4.5}), 'middle');
  // A wall on the top edge only: the pointer near the bottom still snaps to the wall that exists.
  assert.equal(snapOpening(cell, {x: 4.5, y: 4.9}, [wall('h', 4)]).mount_line, 400);
});

test('a mount that would fall outside the map is not offered', () => {
  const cell = [4, 4], bottom = [wall('h', 5)];
  assert.equal(snapOpening(cell, {x: 4.5, y: 4.8}, bottom, {width: 20, height: 14}).mount_line, 500);
  assert.equal(snapOpening(cell, {x: 4.5, y: 4.8}, bottom, {width: 20, height: 5}), null, 'no square below the map edge');
});

test('the door is drawn on its mount line, at an edge or the middle', () => {
  const cases = [
    [{mount_axis: 'h', mount_line: 400, x: 4, y: 4}, {offsetY: -0.5}],
    [{mount_axis: 'h', mount_line: 500, x: 4, y: 5}, {offsetY: -0.5}],
    [{mount_axis: 'h', mount_line: 450, x: 4, y: 4}, {offsetY: 0}],
    [{mount_axis: 'v', mount_line: 400, x: 4, y: 4}, {offsetX: -0.5}],
    [{mount_axis: 'v', mount_line: 500, x: 5, y: 4}, {offsetX: -0.5}],
  ];
  for (const [object, offset] of cases) {
    assert.deepEqual(openingOffset(object), offset);
    const token = tableObjectTokens([{id: 'object:map.1', kind: 'door', ...object}], new Set(), [], null, 20)[0];
    assert.equal(token.offsetX ?? 0, offset.offsetX ?? 0);
    assert.equal(token.offsetY ?? 0, offset.offsetY ?? 0);
    assert.equal(token.rotation, object.mount_axis === 'v' ? 90 : 0);
  }
});

test('the legacy centre-of-square wallMount is unchanged', () => {
  assert.deepEqual(wallMount({kind: 'door', x: 4, y: 4}, [wall('h', 4)]), {mount_axis: 'h', mount_line: 400});
  assert.deepEqual(wallMount({kind: 'door', x: 4, y: 4}, [wall('h', 4.5)]), {mount_axis: 'h', mount_line: 450});
  assert.equal(wallMount({kind: 'crate', x: 4, y: 4}, [wall('h', 4)]), null);
});

// ------------------------------------------------------------------ the real editor

async function openEditor(walls, objects = []) {
  const dom = installDOM(readFileSync(new URL('../static/tabletop/mapeditor.html', import.meta.url), 'utf8'));
  let saved = {map_id: 'edges', display_name: 'Edge yard', width_squares: 20, height_squares: 14,
    background: {style: 'plain'}, walls, terrain: [], materials: [], trees: [],
    starts: {team1: [], team2: []}, objects};
  location.search = '?map=edges';
  globalThis.fetch = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    let result;
    if (path === '/api/session') result = {token: 'test'};
    else if (path === '/api/tabletop/terrains') result = {terrains: []};
    else if (path === '/api/tabletop/maps' && body) result = saved = {...body.map, map_id: 'edges'};
    else if (path === '/api/tabletop/maps') result = {maps: [saved], builtin: [], object_defaults: defaults};
    else if (path === '/api/tabletop/maps/edges') result = saved;
    else throw Error(`Unexpected API ${path}`);
    return {ok: true, status: 200, text: async () => JSON.stringify(result), json: async () => structuredClone(result)};
  };
  await import(`../static/tabletop/mapeditor.js?door-edges=${Math.random()}`);
  for (let i = 0; i < 100 && !window.mapEditor; i += 1) await tick();
  assert.ok(window.mapEditor);
  const {editor, board} = window.mapEditor;
  // The stub viewport is 800x600 at zoom 1 and CELL is 64, so a board point (x, y) is (x*64, y*64) pixels.
  const at = (x, y) => ({clientX: x * 64, clientY: y * 64, button: 0, pointerId: 1});
  await dom.querySelector('[data-tool="object"]').click();
  dom.querySelector('#meObjectKind').value = 'door';
  return {dom, editor, board, at, click: point => board.viewport.dispatch('pointerdown', at(point.x, point.y))};
}

test('placing with the real editor snaps to the edge nearest the pointer', async () => {
  const {editor, click} = await openEditor([wall('h', 4), wall('h', 5)]);
  await click({x: 6.5, y: 4.2});
  assert.deepEqual({x: editor.doc.objects[0].x, y: editor.doc.objects[0].y, axis: editor.doc.objects[0].mount_axis, line: editor.doc.objects[0].mount_line},
    {x: 6, y: 4, axis: 'h', line: 400}, 'upper half lands on the top edge');
  await click({x: 6.5, y: 4.8});
  assert.deepEqual({x: editor.doc.objects[1].x, y: editor.doc.objects[1].y, line: editor.doc.objects[1].mount_line},
    {x: 6, y: 5, line: 500}, 'lower half lands on the bottom edge');
});

test('placing with no wall on the square is refused in plain words', async () => {
  const {dom, editor, click} = await openEditor([]);
  await click({x: 6.5, y: 4.8});
  assert.equal(editor.doc.objects.length, 0);
  assert.match(dom.querySelector('.tt-toast.is-error').textContent, /There is no wall along the bottom edge of that square/);
});

test('the editor previews the line the opening will snap to while the pointer moves', async () => {
  const {editor, board, at} = await openEditor([wall('h', 4), wall('h', 5)]);
  await board.viewport.dispatch('pointermove', at(6.5, 4.9));
  assert.deepEqual({axis: editor.openingPreview.mount_axis, line: editor.openingPreview.mount_line},
    {axis: 'h', line: 500}, 'the preview follows the pointer to the bottom edge');
  await board.viewport.dispatch('pointerleave', at(0, 0));
  assert.equal(editor.openingPreview, null, 'leaving the map clears the preview');
});
