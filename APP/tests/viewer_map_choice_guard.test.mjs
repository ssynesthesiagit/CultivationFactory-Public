// Complete shipped entry point: real key/board/hint handlers, map picker,
// identity reads, polling and resumePendingAction. HTTP and DOM layout only
// are stubbed. Native focus/painting must be checked by the lead outside sandbox.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {CELL} from '../static/tabletop/board.js';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {installDOM} from './objects_dom_stub.mjs';
import {actor, IN, OUT, memoryStorage, tableState} from './viewer_identity_harness.mjs';

async function until(check, message) {
  for (let i = 0; i < 100 && !check(); i++) await tick();
  assert.ok(check(), message);
}

let instance = 0;
async function pendingMapChoice({allowDecline = true} = {}) {
  const id = ++instance, matchId = `map-guard-${id}`, viewId = `view-${id}`;
  const dom = installDOM(readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8'));
  const storage = memoryStorage();
  createViewerStore({viewId, storage}).bindPlayer(matchId, ['a']);
  window.sessionStorage = storage;
  window.localStorage = memoryStorage();
  Object.assign(location, {search: `?match=${matchId}&view=${viewId}`,
    origin: 'http://localhost', href: `http://localhost/tabletop?match=${matchId}&view=${viewId}`});
  let poll;
  globalThis.setInterval = fn => { poll = fn; return 0; };
  const state = tableState([actor('a', OUT), actor('b', IN)], {matchId});
  Object.assign(state.presentation, {terminal: false, teams: [], initiative_order: []});
  const cell = {x: 5, y: 4};
  // Engine-shaped optional place choice. This tests answer transport, not the
  // eligibility/range rules of an individual teleport ability.
  const prompt = {title: 'Choose a teleport destination', reaction: 'Reaction teleport', reactor: 'A',
    trigger: 'B attacks A', summary: 'Teleport to the highlighted space.', cost: '1 CP',
    context: {decision_id: 'reaction-1', reactor_id: 'a', checkpoint: 'HIT'},
    choice: {minimum: 1, maximum: 1, allow_decline: allowDecline,
      options: [{id: 'destination', label: 'Highlighted space', cell}],
      map_pick: {cells: [cell], instruction: 'Choose where to land.', cancel_label: 'Stay here'}}};
  const pending = {method: 'act', request: {candidate_id: 'attack'}, reactions: [], reaction: prompt};
  const events = {events: [], dice: [], last_sequence: state.last_sequence};
  let seatsFail = false, currentState = state;
  const calls = [];
  const response = result => ({ok: true, status: 200, text: async () => JSON.stringify(result), json: async () => result});
  globalThis.fetch = async (path, options = {}) => {
    calls.push({path, body: options.body ? JSON.parse(options.body) : null});
    if (path.endsWith('/act')) return response({status: 'COMMITTED', state, events});
    if (path.endsWith('/seat-status')) {
      if (seatsFail) throw Error('controls read unavailable');
      return response({seats: {}});
    }
    if (path === '/api/session') return response({token: 'test'});
    if (path === '/api/tabletop/conditions') return response({conditions: {}});
    if (path === '/api/tabletop/providers') return response({providers: []});
    if (path.includes('/events?')) return response(events);
    if (path.includes('/state?')) return response(structuredClone(currentState));
    throw Error(`Unexpected production API ${path}`);
  };
  await import(`../static/tabletop/tabletop.js?map-guard-${id}`);
  await until(() => window.tabletop?.app.matchId === matchId, 'complete table boots');
  const {app, board, loadMatch} = window.tabletop;
  currentState = {...state, pending_action: pending};
  let settled = false;
  const continuation = loadMatch(matchId).then(result => { settled = true; return result; });
  await until(() => app.mapPick && app.waitingReaction, 'saved action waits in the real map picker');
  const pick = app.mapPick, waiting = app.waitingReaction, choice = app.pendingChoice;
  const cancel = dom.querySelector('#ttHint button');
  const writes = () => calls.filter(call => call.body);
  const point = target => ({clientX: board.view.x + (target.x + 0.5) * CELL * board.view.zoom,
    clientY: board.view.y + (target.y + 0.5) * CELL * board.view.zoom, pointerId: 1});
  const clickSquare = async () => {
    const viewport = dom.querySelector('#ttViewport'), details = point(cell);
    await viewport.dispatch('pointerdown', details);
    await viewport.dispatch('pointerup', details);
  };
  const escape = () => dom.dispatch('keydown', {target: dom.body, key: 'Escape'});
  const assertPending = () => {
    assert.deepEqual(writes(), [], 'no answer or other user request');
    assert.equal(app.mapPick, pick, 'retain the exact outstanding picker');
    assert.equal(app.waitingReaction, waiting, 'retain the exact outstanding continuation');
    assert.equal(app.pendingChoice, choice);
    assert.equal(settled, false);
  };
  const failControls = async () => {
    seatsFail = true;
    await poll();
    assert.equal(app.seatStatus, null);
    assert.equal(dom.body.classList.contains('is-viewer-pending'), true);
    assert.equal(Boolean(dom.querySelector('#ttReaction').open), false);
    assert.equal(Boolean(dom.querySelector('#ttViewerPicker').open), false, 'Escape is outside any dialog');
    assertPending();
  };
  const recover = async (retainChoice = true) => {
    seatsFail = false;
    await dom.querySelector('#ttViewerRetry').click();
    await until(() => !dom.body.classList.contains('is-viewer-pending'), 'controls recovery uncovers the map');
    if (retainChoice) assertPending();
  };
  return {dom, app, board, cell, prompt, pick, waiting, choice, cancel, continuation, writes,
    clickSquare, escape, assertPending, failControls, recover, poll,
    completeRemotely: () => { currentState = state; }};
}

test('covered optional map choice ignores shipped Escape; recovery and explicit square answer submit once', async () => {
  const h = await pendingMapChoice();
  await h.failControls();
  await h.escape();
  await tick(); // allow the real promise continuation to submit if wrongly settled
  h.assertPending();
  await h.recover();
  await h.clickSquare();
  assert.equal(await h.continuation, true);
  assert.deepEqual(h.writes().map(call => call.body.reactions),
    [[{...h.prompt.context, selection: 'USE', option_ids: ['destination']}]]);
  assert.equal(h.app.mapPick, null);
  assert.equal(h.app.pendingChoice, null);
  await h.escape();
  assert.equal(h.writes().length, 1);
});

for (const input of ['square', 'token', 'hint Cancel']) {
test(`covered ${input} cannot settle; visible Cancel still declines once`, async () => {
  const h = await pendingMapChoice();
  await h.failControls();
  if (input === 'square') await h.clickSquare();
  else if (input === 'token') {
    // Force delivery despite the cover: test the production answer guard
    // independently of CSS hit testing, through the real token listener.
    await h.board.tokenNode('b').dispatch('click', {
      clientX: h.board.view.x + (h.cell.x + 0.5) * CELL * h.board.view.zoom,
      clientY: h.board.view.y + (h.cell.y + 0.5) * CELL * h.board.view.zoom});
  } else await h.cancel.click();
  await tick();
  h.assertPending();
  await h.recover();
  await h.cancel.click();
  assert.equal(await h.continuation, true);
  assert.deepEqual(h.writes().map(call => call.body.reactions), [[{...h.prompt.context, selection: 'DECLINE'}]]);
});
}

test('visible optional map choice retains shipped Escape decline behavior', async () => {
  const h = await pendingMapChoice();
  await h.escape();
  assert.equal(await h.continuation, true);
  assert.deepEqual(h.writes().map(call => call.body.reactions), [[{...h.prompt.context, selection: 'DECLINE'}]]);
});

test('required map choice cannot decline even when visible', async () => {
  const h = await pendingMapChoice({allowDecline: false});
  await h.escape();
  await tick();
  h.assertPending();
  await h.clickSquare();
  assert.equal(await h.continuation, true);
  assert.equal(h.writes().length, 1);
  assert.equal(h.writes()[0].body.reactions[0].selection, 'USE');
});

test('remote completion still cleans a covered map choice without submitting or resurrecting it', async () => {
  const h = await pendingMapChoice();
  await h.failControls();
  h.completeRemotely();
  await h.poll();
  assert.equal(await h.continuation, true);
  assert.equal(h.app.mapPick, null);
  assert.equal(h.app.pendingChoice, null);
  assert.equal(h.app.waitingReaction, null);
  assert.deepEqual(h.writes(), []);
  await h.recover(false);
  assert.equal(h.app.mapPick, null);
  assert.equal(h.app.waitingReaction, null);
  await h.escape();
  await h.cancel.click();
  assert.deepEqual(h.writes(), []);
});
