// Phone entry/re-entry uses only the existing human controller authority.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

const actorId = 'actor:factory.phone-binding';
function harness({controller = 'MANUAL', pending = false, model = false} = {}) {
  const doc = installDOM(readFileSync(new URL('../static/play/play.html', import.meta.url), 'utf8'));
  doc.createTextNode = text => Object.assign(new Element('span'), {textContent: String(text), nodeType: 3});
  const viewerStore = createViewerStore({viewId: 'phone-binding-test'});
  viewerStore.bindPlayer('phone-binding', [actorId]);
  const actor = {entity_id: actorId, display_name: 'Player', primary_combatant: true,
    controller, active: true, position: {x: 0, y: 0, z: 0}, team_index: 0,
    hit_points: {current: 20, maximum: 20}, conditions: [], resources: []};
  const snapshot = {last_sequence: 1, presentation: {match_id: 'phone-binding', display_name: 'Phone binding',
    current_actor_id: actorId, round_number: 1, actors: [actor], zones: [],
    battlefield: {width_squares: 2, height_squares: 2, terrain_regions: []}},
    map: {}, objects: [], items: [], fog_perception: {[actorId]: {cells: [[0, 0]], creatures: [actorId]}},
    menu: {manual: true, actor_id: actorId, control_mode: controller,
      turn_mode: controller === 'SUGGESTED' ? 'Assisted' : 'Manual', decision_id: 'decision', state_version: 1,
      actions: [{label: 'Wait', source_definition_id: 'wait', cost_label: 'Action; no resource cost',
        options: [{candidate_id: 'wait', label: 'Wait in your square'}]}], moves: [], end_turn: 'end',
      ranked_slots: {Action: ['wait'], Movement: [], 'Bonus action': []}}};
  if (pending) snapshot.pending_action = {method: 'act', request: {candidate_id: 'wait'}, reactions: [],
    reaction: {reaction: 'Footwork', reactor: 'Player', context: {reactor_id: actorId},
      trigger: 'An attacker strikes Player.', cost: 'Expend Martial Focus.',
      choice: {minimum: 1, maximum: 1, allow_decline: true, options: [{id: 'stay', label: 'Stay in your square'}]}}};
  const writes = [];
  const request = async (path, options = {}) => {
    if (options.body) {
      writes.push({path, body: options.body});
      assert.ok(path.endsWith('/controller-mode'), 'No combat action is automatic on phone entry');
      actor.controller = options.body.controller_mode;
      snapshot.menu.control_mode = actor.controller;
      snapshot.menu.turn_mode = actor.controller === 'SUGGESTED' ? 'Assisted' : 'Manual';
      return {};
    }
    if (path.includes('/state?')) return structuredClone(snapshot);
    if (path.endsWith('/seat-status')) return {seats: model ? {[actorId]: {control: 'MODEL'}} : {}};
    if (path.includes('/events?')) return {events: [], last_sequence: 1};
    if (path.endsWith('/sheet')) return {buttons: [], library: {groups: []}};
    throw new Error(`Unexpected fake request: ${path}`);
  };
  const board = {element: new Element(), map: {width: 2, height: 2}, view: {x: 0, y: 0, zoom: 1},
    closeHoverCard() {}, fit() {}, terrainAt: () => [], zonesAt: () => [], floorRecordAt: () => null};
  for (const method of ['setMap', 'setRoofView', 'setZones', 'setTokens', 'setFog', 'setRemembered', 'setHighlights'])
    board[method] = value => { if (method === 'setMap') board.map = value; };
  const client = createPlay({doc, request, board, viewerStore,
    memoryStore: {read: () => ({version: 3, cells: {}}), ready: () => false}, frame: () => {}});
  return {client, doc, writes, snapshot};
}
const text = node => [node.textContent, ...(node.children || []).map(text)].join(' ');

test('stored human binding opens Assisted without another bind click; Manual survives polling', async () => {
  const h = harness();
  await h.client.load('phone-binding');
  assert.equal(h.client.state.menu.control_mode, 'SUGGESTED');
  assert.deepEqual(h.writes.map(row => row.body), [{actor_id: actorId, controller_mode: 'SUGGESTED'}]);
  assert.match(text(h.doc.getElementById('actionList')), /Suggested plan/);
  assert.equal(await h.client.setControl('MANUAL'), true);
  await h.client.refresh();
  assert.equal(h.client.state.menu.control_mode, 'MANUAL');
  assert.doesNotMatch(text(h.doc.getElementById('actionList')), /Suggested plan/);
  assert.equal(h.writes.length, 2);
  await h.client.load('phone-binding');
  assert.equal(h.client.state.menu.control_mode, 'MANUAL');
  assert.equal(h.writes.length, 2, 'Reopening must respect an explicit Manual choice');
});

test('reopening an already Assisted binding does not write controller state', async () => {
  const h = harness({controller: 'SUGGESTED'});
  await h.client.load('phone-binding');
  assert.match(text(h.doc.getElementById('actionList')), /Suggested plan/);
  assert.deepEqual(h.writes, []);
});

test('stored bindings never change a model seat or interrupt a pending human decision', async () => {
  for (const options of [{model: true}, {pending: true}]) {
    const h = harness(options);
    await h.client.load('phone-binding');
    assert.deepEqual(h.writes, []);
    if (options.pending) assert.equal(h.doc.getElementById('reactionCard').open, true);
    else assert.equal(h.doc.getElementById('mapCover').hidden, false);
  }
});
