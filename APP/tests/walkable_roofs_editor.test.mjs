// Full production map editor entry point, persistence API and undo/redo under
// deterministic DOM. Browser layout is a separate check.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';

test('roof height, climbing surface and apertures save/reopen through real editor controls', async () => {
  const document = installDOM(readFileSync(new URL('../static/tabletop/mapeditor.html', import.meta.url), 'utf8'));
  const cells = Array.from({length: 16}, (_, i) => [3 + i % 4, 3 + Math.floor(i / 4)]);
  const source = {map_id: 'roof-walk-copy', display_name: 'Roof test house', width_squares: 10, height_squares: 10,
    background: {style: 'grass'}, walls: [{shape: 'rect', points: [[2, 2], [7, 7]], blocks: 'movement', filled: false}],
    materials: [{material: 'floor:wood', cells}], terrain: [], objects: [], trees: [], starts: {team1: [], team2: []}};
  let saved = null;
  globalThis.fetch = async (path, options = {}) => {
    let result;
    if (path === '/api/session') result = {token: 'test'};
    else if (path === '/api/tabletop/terrains') result = {terrains: [], ground: {}};
    else if (path === '/api/tabletop/maps' && options.body) {
      saved = JSON.parse(options.body).map; result = {...saved, map_id: 'roof-walk-copy'};
    } else if (path === '/api/tabletop/maps') result = {maps: [], builtin: [], object_defaults: {presets: {}, groups: {}, materials: {}, sizes: {}}};
    else if (path === '/api/tabletop/maps/roof-walk-copy') result = JSON.parse(JSON.stringify(saved || source));
    else throw Error('Unexpected test API ' + path);
    return {ok: true, status: 200, text: async () => JSON.stringify(result), json: async () => result};
  };
  await import('../static/tabletop/mapeditor.js?roof-walk-editor-test');
  for (let i = 0; i < 100 && !window.mapEditor; i++) await tick();
  assert.ok(window.mapEditor);
  const $ = id => document.querySelector('#' + id);
  const set = async (id, value, type = 'change') => { $(id).value = value; await $(id).dispatch(type); };
  const reopen = async () => { await window.mapEditor.save(); await window.mapEditor.open('map:roof-walk-copy'); };
  await window.mapEditor.open('map:roof-walk-copy');
  const {editor, board} = window.mapEditor;

  assert.equal(Number($('meRoofHeight').value), 15, 'old map shows the inferred building roof height');
  await set('meRoofHeight', '20'); assert.equal(editor.doc.roofs.height_ft, 20);
  await set('meRoofClimbCheck', 'slippery'); assert.equal(editor.doc.roofs.climb_check, 'slippery');
  await set('meRoofBuilding', '3,3');
  assert.equal(Number($('meRoofHeight').value), 20);
  assert.equal($('meRoofClimbCheck').value, 'slippery');
  await set('meRoofClimbCheck', 'none');
  await set('meRoofHeight', '15');
  assert.equal(editor.doc.roofs.regions[0].height_ft, 15);
  assert.equal(editor.doc.roofs.regions[0].climb_check, 'none');
  await reopen();
  assert.equal(Number($('meRoofHeight').value), 15);
  await set('meRoofHeight', '20');
  assert.equal(editor.doc.roofs.regions[0].height_ft, 20);
  await set('meRoofHeight', '10');

  const unchanged = JSON.stringify(editor.doc), historyLength = editor.history.length;
  await set('meRoofHeight', '2.5');
  assert.equal(JSON.stringify(editor.doc), unchanged);
  assert.equal(editor.history.length, historyLength, 'invalid height creates no undo entry');

  $('meRoofOpeningX').value = '4'; $('meRoofOpeningY').value = '4';
  $('meRoofOpeningKind').value = 'skylight'; $('meRoofOpeningOpen').checked = false;
  await $('meRoofOpeningSave').click();
  assert.deepEqual(editor.doc.roofs.openings, [{x: 3, y: 3, kind: 'skylight', open: false}]);
  assert.match(board.element.querySelector('[data-roof]').innerHTML, /Closed skylight: glass blocks passage/);
  await reopen();
  assert.equal($('meRoofOpeningKind').value, 'skylight');
  assert.equal($('meRoofOpeningOpen').checked, false);
  assert.equal(Number($('meRoofOpeningX').value), 4, 'saved coordinates are shown as one-based squares');
  $('meRoofOpeningOpen').checked = true; await $('meRoofOpeningSave').click();
  assert.deepEqual(editor.doc.roofs.openings, [{x: 3, y: 3, kind: 'skylight', open: true}]);
  await $('meUndo').click(); assert.equal(editor.doc.roofs.openings[0].open, false);
  await $('meRedo').click(); assert.equal(editor.doc.roofs.openings[0].open, true);

  const beforeInvalid = JSON.stringify(editor.doc), beforeHistory = editor.history.length;
  $('meRoofOpeningX').value = '1'; $('meRoofOpeningY').value = '1';
  await $('meRoofOpeningSave').click();
  assert.equal(JSON.stringify(editor.doc), beforeInvalid);
  assert.equal(editor.history.length, beforeHistory, 'an off-roof opening does not disturb history');
  await set('meRoofOpening', '3,3');
  await $('meRoofOpeningRemove').click(); assert.deepEqual(editor.doc.roofs.openings, []);
  await $('meUndo').click(); assert.equal(editor.doc.roofs.openings[0].kind, 'skylight');
  await reopen();
  assert.deepEqual(saved.roofs, editor.doc.roofs);
  assert.equal(saved.roofs.regions[0].height_ft, 10);
  assert.deepEqual(saved.roofs.openings, [{x: 3, y: 3, kind: 'skylight', open: true}]);
});
