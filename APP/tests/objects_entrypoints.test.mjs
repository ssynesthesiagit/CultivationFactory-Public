import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {durability as defaults} from './object_defaults_fixture.mjs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';

const staticURL = new URL('../static/tabletop/', import.meta.url);
const clone = value => structuredClone(value);
async function until(check) { for (let i = 0; i < 100; i++) { if (check()) return; await tick(); } assert.ok(check(), 'entry point settled'); }
function mockAPI(handler) {
  globalThis.fetch = async (path, options = {}) => {
    const result = await handler(path, options.body ? JSON.parse(options.body) : null);
    return {ok: true, status: 200, text: async () => JSON.stringify(result), json: async () => result};
  };
}

test('production editor selects with Objects and deletes explicitly or with Erase, undo/redo and save/reopen', async () => {
  const dom = installDOM(readFileSync(new URL('mapeditor.html', staticURL), 'utf8'));
  let saved = {map_id: 'sol69', display_name: 'Door yard', width_squares: 8, height_squares: 8,
    background: {style: 'plain'}, walls: [], terrain: [], materials: [], trees: [],
    starts: {team1: [], team2: []}, objects: [{id: 1, kind: 'door', x: 3, y: 3}]};
  location.search = '?map=sol69';
  mockAPI((path, body) => {
    if (path === '/api/session') return {token: 'test'};
    if (path === '/api/tabletop/terrains') return {terrains: []};
    if (path === '/api/tabletop/maps' && body) return clone(saved = {...body.map, map_id: 'sol69'});
    if (path === '/api/tabletop/maps') return {maps: [saved], builtin: [], object_defaults: defaults};
    if (path === '/api/tabletop/maps/sol69') return clone(saved);
    throw Error(`Unexpected API ${path}`);
  });
  await import('../static/tabletop/mapeditor.js');
  await until(() => window.mapEditor);
  const {editor, board} = window.mapEditor;
  const token = () => board.element.querySelector('.tt-token.is-object');
  assert.ok(token(), dom.querySelector('.tt-toast.is-error')?.textContent);
  await token().dispatch('focus');  // keyboard focus opens the card at once; pointer hover now waits 500 ms
  assert.match(dom.querySelector('.tt-token-card').innerHTML, /18 HP \(default\).*15 AC \(default\)/);
  for (const tool of ['object', 'erase']) {
    await dom.querySelector(`[data-tool="${tool}"]`).click();
    await token().dispatch('pointerdown');
    if (tool === 'object') {
      await token().click();
      assert.equal(editor.doc.objects.length, 1);
      await dom.querySelector('#meObjectRotate').click();
      assert.equal(editor.doc.objects[0].rotation, 90);
      await dom.dispatch('keydown', {key:'e',target:token()});
      assert.equal(editor.doc.objects[0].rotation, 180);
      await dom.dispatch('keydown', {key:'q',target:token()});
      assert.equal(editor.doc.objects[0].rotation, 90);
      await dom.dispatch('keydown', {key:'r',target:token()});
      assert.equal(editor.tool, 'rect', 'R still selects the rectangle tool');
      await dom.querySelector('[data-tool="object"]').click();
      await dom.querySelector('#meObjectRemove').click();
    }
    assert.equal(editor.doc.objects.length, 0);
    assert.equal(token(), null);
    await dom.querySelector('#meUndo').click();
    assert.equal(editor.doc.objects.length, 1);
    assert.ok(token());
    await dom.querySelector('#meRedo').click();
    assert.equal(editor.doc.objects.length, 0);
    await dom.querySelector('#meSave').click();
    assert.equal(saved.objects.length, 0);
    await window.mapEditor.open('map:sol69');
    assert.equal(editor.doc.objects.length, 0);
    assert.equal(token(), null);
    assert.equal(dom.querySelector('.tt-toast.is-error'), null);
    // Reload the same fixture so both tools start with a placed object.
    if (tool === 'object') {
      saved.objects = [{id: 1, kind: 'door', x: 3, y: 3}];
      await window.mapEditor.open('map:sol69');
    }
  }
});

test('production table targets, hovers and submits object attack; committed destruction removes token', async () => {
  const dom = installDOM(readFileSync(new URL('tabletop.html', staticURL), 'utf8'));
  location.search = '?match=sol69';
  const objectId = 'object:map.1';
  const menu = {manual: true, actor_id: 'actor:test', decision_id: 'decision', state_version: 1, moves: [], actions: [
    {label: 'Break obstacle', source_definition_id: 'test:attack', options: [
      {candidate_id: 'break-door', target_ids: [objectId]}, {candidate_id: 'break-other', target_ids: ['object:other']}]}]};
  let state = {menu: null, last_sequence: 0, map: {background: {style: 'plain'}},
    presentation: {battlefield: {display_name: 'Yard', width_squares: 8, height_squares: 8, blocked_cells: []},
      actors: [], teams: [], zones: [], initiative_order: [], round_number: 1, terminal: true},
    objects: [{id: objectId, kind: 'door', x: 3, y: 3, name: 'Wooden door', hp: 7, max_hp: 18, detail: 'AC 15 · wood'}]};
  let submitted;
  mockAPI((path, body) => {
    if (path === '/api/session') return {token: 'test'};
    if (path === '/api/tabletop/conditions') return {conditions: {}};
    if (path.includes('/events')) return {events: [], last_sequence: 0};
    // The live table prepares an action (read-only) before it submits the candidate.
    if (path.endsWith('/prepare')) return {status: 'PREPARED'};
    if (path.endsWith('/act')) { submitted = body; state = {...state, menu: null, objects: []}; return {status: 'COMMITTED', state: clone(state), events: {events: [], last_sequence: 1}}; }
    // act() previews the action without reserving it before submitting (b59df5b2).
    if (path.endsWith('/prepare')) return {status: 'PREPARED'};
    if (new URL(path, 'http://localhost').pathname === '/api/tabletop/matches/sol69/state') return clone(state);
    throw Error(`Unexpected API ${path}`);
  });
  await import('../static/tabletop/tabletop.js');
  await until(() => window.tabletop);
  const {app, board, runButton} = window.tabletop;
  // This object-control smoke uses the explicit GM action. An unbound initial
  // table now deliberately covers objects along with the rest of the scene.
  await dom.querySelector('#ttViewerGM').click();
  const token = () => board.element.querySelector('.tt-token.is-object');
  assert.ok(token(), dom.querySelector('.tt-toast.is-error')?.textContent || 'real loadMatch renders object');
  await token().dispatch('focus');  // keyboard focus opens the card at once; pointer hover now waits 500 ms
  assert.match(dom.querySelector('.tt-token-card').innerHTML, /7 \/ 18 HP/);
  assert.match(dom.querySelector('.tt-token-card').innerHTML, /AC 15/);
  app.menu = menu; app.state.menu = menu;
  const action = runButton({label: 'Break obstacle', combat: {source_definition_id: 'test:attack'}}, menu.actor_id);
  await until(() => token()?.classList.contains('is-targetable'));
  assert.ok(token().classList.contains('is-targetable'));
  assert.ok(board.element.querySelector('.tt-highlights')?.children.length || board.element.querySelector('.tt-marks')?.children.length);
  await token().click();
  assert.equal((await action).ok, true);
  assert.equal(submitted.candidate_id, 'break-door');
  assert.equal(submitted.decision_id, 'decision');
  assert.equal(token(), null);
  await window.tabletop.loadMatch('sol69');
  assert.equal(token(), null, 'destroyed object stays absent on reload');
  assert.equal(dom.querySelector('.tt-toast.is-error'), null);
});
