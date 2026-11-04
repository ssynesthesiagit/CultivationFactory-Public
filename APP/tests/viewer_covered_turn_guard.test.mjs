// Complete shipped entry point for an ordinary, unfinished turn of a fighter you play:
// real key handler, action bar, useGroup choice, identity reads, polling and Retry.
// HTTP, DOM layout and the sheet channel are stubbed; native focus and painting are not claimed here.
//
// The cover hides the map and every control with it, but the document still receives
// key presses and the last menu stays on the page. A press made while the controls are
// unknown must not spend the turn the player cannot see. Three separate guards stop that,
// and each one below fails when its own guard is removed:
//   - the keyboard handler only plays the turn shortcuts while the view is available;
//   - actOnce() refuses before it retires the question the player still has to answer;
//   - act() refuses again after its awaited sheet synchronisation, because the view can
//     go covered while that await is in flight.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {installDOM} from './objects_dom_stub.mjs';
import {actor, IN, OUT, memoryStorage, tableState} from './viewer_identity_harness.mjs';

async function until(check, message) {
  for (let i = 0; i < 200 && !check(); i++) await tick();
  assert.ok(check(), message);
}

// The table asks open character sheets to save their settings over a BroadcastChannel.
// This stand-in keeps the same asynchronous delivery, so the shipped module code runs
// unchanged; the real global is put back when the test that needs it ends.
function openSheets() {
  const peers = new Set(), tablePosts = [], original = globalThis.BroadcastChannel;
  const deliver = (from, data) => {
    for (const peer of [...peers]) if (peer !== from) void tick().then(() => peer.listeners.forEach(fn => fn({data})));
  };
  class TestChannel {
    constructor(name) { this.table = name === 'tianxia-tabletop'; peers.add(this); this.listeners = []; }
    addEventListener(type, fn) { if (type === 'message') this.listeners.push(fn); }
    postMessage(data) { if (this.table) tablePosts.push(data); deliver(this, data); }
  }
  window.BroadcastChannel = globalThis.BroadcastChannel = TestChannel;
  // say() resolves once the table has had the message, as a real sheet's post would be
  // answered in a later turn -- pressing a button first must not race the sheet.
  return {tablePosts, say: async data => { deliver(new TestChannel('character-sheet'), data); await tick(); await tick(); },
    restore: () => { window.BroadcastChannel = globalThis.BroadcastChannel = original; }};
}

let instance = 0;
async function manualTurn({manual = true, sheet = false} = {}) {
  const id = ++instance, matchId = `turn-guard-${id}`, viewId = `view-${id}`;
  const dom = installDOM(readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8'));
  const storage = memoryStorage();
  createViewerStore({viewId, storage}).bindPlayer(matchId, ['a']);
  window.sessionStorage = storage;
  window.localStorage = memoryStorage();
  Object.assign(location, {search: `?match=${matchId}&view=${viewId}`,
    origin: 'http://localhost', href: `http://localhost/tabletop?match=${matchId}&view=${viewId}`});
  let poll;
  globalThis.setInterval = fn => { poll = fn; return 0; };
  // The fight is not over and it is the bound fighter's turn: the engine offers the
  // actions of that turn, one needing a target picked and one that ends the turn.
  // manual=false is the same fight as the table projects it for a fighter who does not
  // own the menu -- the state still holds it, but this screen has no action bar.
  const state = tableState([actor('a', IN), actor('b', OUT)], {matchId});
  state.menu = {actor_id: 'a', decision_id: 'decision-1', state_version: 3, manual,
    end_turn: 'end-turn-1', moves: [],
    actions: [{source_definition_id: 'strike', label: 'Strike', description: 'Hit a creature.',
      options: [{candidate_id: 'strike-b', label: 'Strike B', target_ids: ['b'], option_ids: []},
        {candidate_id: 'strike-a', label: 'Strike yourself', target_ids: ['a'], option_ids: []}]}]};
  Object.assign(state.presentation, {terminal: false, teams: [], initiative_order: []});
  const events = {events: [], dice: [], last_sequence: state.last_sequence};
  let seatsFail = false;
  const calls = [];
  const response = result => ({ok: true, status: 200, text: async () => JSON.stringify(result), json: async () => result});
  globalThis.fetch = async (path, options = {}) => {
    calls.push({path, body: options.body ? JSON.parse(options.body) : null});
    if (path.endsWith('/act') || path.endsWith('/auto-step')) return response({status: 'COMMITTED', state, events});
    // act() previews an ordinary action without reserving it (b59df5b2) before the commit.
    if (path.endsWith('/prepare')) return response({status: 'PREPARED'});
    if (path.endsWith('/seat-status')) {
      if (seatsFail) throw Error('controls read unavailable');
      return response({seats: {}});
    }
    if (path === '/api/session') return response({token: 'test'});
    if (path === '/api/tabletop/conditions') return response({conditions: {}});
    if (path === '/api/tabletop/providers') return response({providers: []});
    if (path.includes('/events?')) return response(events);
    if (path.includes('/state?')) return response(structuredClone(state));
    throw Error(`Unexpected production API ${path}`);
  };
  const sheets = sheet ? openSheets() : null;
  await import(`../static/tabletop/tabletop.js?turn-guard-${id}`);
  await until(() => window.tabletop?.app.matchId === matchId, 'complete table boots');
  const {app} = window.tabletop;
  if (manual) await until(() => app.menu?.end_turn, 'the manual turn is on screen');
  else await until(() => app.state && !app.menu, 'the table is on screen without the fighter action bar');
  const button = label => dom.querySelectorAll('#ttActionBar button').find(node => node.querySelector('b')?.textContent === label);
  // A prepared action is not spent: /prepare only gathers choices (act() reserves nothing there),
  // so a "write" is the submitted act/auto-step, the thing the covered guards must stop.
  const writes = () => calls.filter(call => call.body && /\/act$|\/auto-step$/.test(call.path));
  const toasts = () => dom.querySelector('#ttToasts').children.map(node => node.textContent);
  // The DOM stub awaits whatever a listener returns, and useGroup's promise only
  // settles once the player answers, so presses are fired and then observed.
  const press = node => { void node.dispatch('click'); };
  const key = (name, code) => dom.dispatch('keydown', {target: dom.body, key: name, code: code || name});
  const space = () => key(' ', 'Space');
  const step = () => key('s', 'KeyS');
  const failControls = async () => {
    seatsFail = true;
    await poll();
    assert.equal(app.seatStatus, null, 'the controls read failed');
    assert.equal(dom.body.classList.contains('is-viewer-pending'), true, 'the table is covered');
    assert.equal(Boolean(dom.querySelector('#ttViewerPicker').open), false, 'the shortcut is outside any dialog');
  };
  const recover = async () => {
    seatsFail = false;
    await dom.querySelector('#ttViewerRetry').click();
    await until(() => !dom.body.classList.contains('is-viewer-pending'), 'Retry uncovers the map');
  };
  return {dom, app, button, press, writes, toasts, space, step, failControls, recover,
    matchId, sheets, allowControls: () => { seatsFail = false; }, endTurn: 'end-turn-1'};
}

test('covered Space does not end a manual turn or cancel its open choice; a visible End turn still submits once', async () => {
  const h = await manualTurn();
  const endTurn = h.button('End turn');
  assert.ok(endTurn, 'the turn offers a visible End turn button');
  h.press(h.button('Strike'));                    // the real useGroup choice for this attack
  await until(() => h.app.targeting && h.app.pendingChoice, 'the table waits for a target');
  const targeting = h.app.targeting, choice = h.app.pendingChoice;

  await h.failControls();
  await h.space();
  await tick();
  await tick();
  assert.deepEqual(h.writes(), [], 'a covered Space writes no action');
  assert.equal(h.app.targeting, targeting, 'the open choice is not cancelled by a covered press');
  assert.equal(h.app.pendingChoice, choice, 'the question on screen is left exactly as it was');
  assert.equal(h.app.menu?.end_turn, h.endTurn, 'the retained turn is untouched');

  await h.recover();
  h.press(endTurn);
  await until(() => h.writes().length === 1, 'the explicit visible End turn submits once');
  assert.deepEqual(h.writes().map(call => call.path), [`/api/tabletop/matches/${h.app.matchId}/act`]);
  assert.equal(h.writes()[0].body.candidate_id, h.endTurn);
  assert.equal(h.writes()[0].body.decision_id, 'decision-1');
});

test('a visible Space still ends the turn once', async () => {
  const h = await manualTurn();
  await h.space();
  await until(() => h.writes().length === 1, 'Space ends the turn when the view is available');
  assert.equal(h.writes()[0].body.candidate_id, h.endTurn);
  assert.deepEqual(h.writes().map(call => call.path), [`/api/tabletop/matches/${h.app.matchId}/act`]);
});

// actOnce() runs for the button on screen as well as for the keyboard, so a covered
// press of that button must be refused before it retires the question underneath it.
test('a covered End turn button writes nothing and leaves the open question exactly as it was', async () => {
  const h = await manualTurn();
  const endTurn = h.button('End turn');
  h.press(h.button('Strike'));
  await until(() => h.app.targeting && h.app.pendingChoice, 'the table waits for a target');
  const targeting = h.app.targeting, choice = h.app.pendingChoice;

  await h.failControls();
  h.press(endTurn);                                 // the retained button, not a key press
  for (let i = 0; i < 20; i++) await tick();        // a submission would reach /act within these turns
  assert.deepEqual(h.writes(), [], 'the covered button writes no action');
  assert.equal(h.app.targeting, targeting, 'the covered press does not cancel the open choice');
  assert.equal(h.app.pendingChoice, choice, 'the player still has the question they were asked');
  assert.equal(h.app.menu?.end_turn, h.endTurn, 'the retained turn is untouched');
  assert.ok(h.toasts().some(text => text.includes('Nothing was sent')), 'the player is told nothing went out');

  await h.recover();
  h.press(endTurn);                                 // the same button works once the view is back
  await until(() => h.writes().length === 1, 'the recovered button submits once');
  assert.equal(h.writes()[0].body.candidate_id, h.endTurn);
});

// A sheet that has not saved its settings holds the action at the table's
// synchronizePresets() await. The view can go covered during that wait, so act() has to
// look again immediately before it posts.
test('an action held on a sheet save is not submitted when the view is covered while it waits', async () => {
  const h = await manualTurn({sheet: true});
  const endTurn = h.button('End turn');
  try {
    await h.sheets.say({type: 'settings-pending', sheet_id: 'sheet-1', actor_id: 'a', match_id: h.matchId});
    h.press(endTurn);
    await until(() => h.sheets.tablePosts.some(post => post.type === 'settings-flush'),
      'the action waits for the sheet to save its settings');
    assert.deepEqual(h.writes(), [], 'nothing is submitted while the sheet is still saving');

    await h.failControls();                         // the seat read fails during the wait
    await h.sheets.say({type: 'settings-flushed', sheet_id: 'sheet-1', match_id: h.matchId,
      request_id: h.sheets.tablePosts.at(-1).request_id, ok: true});
    for (let i = 0; i < 20; i++) await tick();
    assert.deepEqual(h.writes(), [], 'the released action is not submitted to a covered view');
    assert.ok(h.toasts().some(text => text.includes('Nothing was sent')),
      'the released action reports that nothing went out');
    assert.equal(h.app.menu?.end_turn, h.endTurn, 'the retained turn is untouched');

    // The same wait with the view available still submits, so the first half cannot pass
    // merely because the sheet never answered.
    await h.recover();
    await await h.sheets.say({type: 'settings-pending', sheet_id: 'sheet-2', actor_id: 'a', match_id: h.matchId});
    h.press(endTurn);
    await until(() => h.sheets.tablePosts.filter(post => post.type === 'settings-flush').length === 2,
      'the second action waits for its sheet too');
    await h.sheets.say({type: 'settings-flushed', sheet_id: 'sheet-2', match_id: h.matchId,
      request_id: h.sheets.tablePosts.at(-1).request_id, ok: true});
    await until(() => h.writes().length === 1, 'a visible view submits the released action');
    assert.equal(h.writes()[0].body.candidate_id, h.endTurn);
    assert.deepEqual(h.writes().map(call => call.path), [`/api/tabletop/matches/${h.app.matchId}/act`]);
  } finally { h.sheets.restore(); }
});

// S is the other gameplay shortcut the cover has to swallow. It is available on a fight
// this screen shows but does not drive, which is the state it is meant for.
test('S steps a visible fight and is swallowed while the view is covered', async () => {
  const h = await manualTurn({manual: false});
  await h.step();
  await until(() => h.writes().length === 1, 'a visible S lets the fight move on');
  await until(() => !h.app.busy, 'the visible step settles');   // polling skips a busy action
  assert.deepEqual(h.writes().map(call => call.path), [`/api/tabletop/matches/${h.app.matchId}/auto-step`]);

  await h.failControls();
  await h.step();
  for (let i = 0; i < 20; i++) await tick();        // a step would reach /auto-step within these turns
  assert.equal(h.writes().length, 1, 'a covered S moves nothing on');
});

test('a covered Space leaves the focused Retry button to work and ends no turn', async () => {
  const h = await manualTurn();
  await h.failControls();
  const retry = h.dom.querySelector('#ttViewerRetry');
  assert.equal(retry.hidden, false, 'the cover offers Retry while the controls are unknown');
  // Space is left unprevented while covered, so it still reaches the focused control.
  let prevented = 0;
  await h.dom.dispatch('keydown', {target: retry, key: ' ', code: 'Space', preventDefault: () => { prevented++; }});
  assert.equal(prevented, 0, 'the covered table does not swallow the key press meant for Retry');
  for (let i = 0; i < 10; i++) await tick();   // an action would reach /act within these turns
  assert.deepEqual(h.writes(), [], 'a covered Space aimed at Retry writes no action');
  h.allowControls();
  await retry.click();                          // native focus and activation are the browser suite's to run
  await until(() => !h.dom.body.classList.contains('is-viewer-pending'), 'Retry uncovers the map');
  assert.deepEqual(h.writes(), [], 'recovering the view ends no turn');
});