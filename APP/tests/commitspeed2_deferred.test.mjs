// Production request code, no GUI, network or model inference.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function piece(name, async = false) {
  const start = source.indexOf(`${async ? 'async ' : ''}function ${name}(`);
  assert.ok(start >= 0);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

test('human commit clears old choices and responds while menu read is pending', async () => {
  const wait = deferred(), oldMenu = {decision_id: 'old', state_version: 10, actor_id: 'p', actions: [], end_turn: 'end'};
  const app = {matchId: 'm', state: {menu: oldMenu}, menu: oldMenu, lastSequence: 20};
  const next = {menu: null, menu_pending: {state_version: 11}, last_sequence: 21};
  const bindings = {
    app, hint() {}, synchronizePresets: async () => {}, refuseCoveredView: () => false,
    document: {body: {classList: {add() {}, remove() {}}}}, enc: encodeURIComponent,
    withReactions: send => send([]), api: async () => ({status: 'COMMITTED', state: next, events: {}}),
    invalidateTargeting() {}, renderActionBar() {}, playEvents: async () => {},
    readTableState: () => { throw new Error('commit must not await a second state read'); },
    refresh: () => wait.promise, gmNotice() {}, toast() {}, handleUnavailableFight: async () => false,
  };
  const code = `let refreshSequence=0; let deferredMenuRead=null;
    ${piece('requestDeferredMenu')}
    function render(state) { app.state=state; app.menu=state.menu; requestDeferredMenu(); }
    ${piece('act', true)}
    return {act, requestDeferredMenu};`;
  const ui = Function(...Object.keys(bindings), code)(...Object.values(bindings));
  assert.equal(await ui.act('end'), true);
  assert.equal(app.busy, false);
  assert.equal(app.menu, null);
  assert.equal(app.state, next);
  const same = ui.requestDeferredMenu();
  assert.equal(same, ui.requestDeferredMenu()); // polls cannot supersede the read
  wait.resolve();
  await same;
});

test('a late next-menu read cannot overwrite a newer commit or another match', async () => {
  for (const change of ['commit', 'match']) {
    const wait = deferred(), displayed = [];
    const app = {matchId: 'm', fog: 'own', lastSequence: 21, state: {menu_pending: {state_version: 11}}};
    const bindings = {
      app, hint() {}, enc: encodeURIComponent, api: async () => ({events: [], last_sequence: 21}),
      readTableState: () => wait.promise, loadSeats: async () => {},
      eventsThroughState: async e => e, playEvents: async () => {},
      render: s => displayed.push(s), renderObservedState: s => displayed.push(s),
      resumeServerPrompt() {}, handleUnavailableFight: async () => false, toast() {},
    };
    const ui = Function(...Object.keys(bindings), `let refreshSequence=0; let deferredMenuRead=null;
      ${piece('requestDeferredMenu')}
      ${piece('refresh', true)}
      return {read: requestDeferredMenu, newer: () => {refreshSequence++;}};`)(...Object.values(bindings));
    const read = ui.read();
    await Promise.resolve();
    if (change === 'commit') ui.newer();
    else app.matchId = 'other';
    wait.resolve({menu: {decision_id: 'late', state_version: 11}, last_sequence: 21});
    await read;
    assert.deepEqual(displayed, []);
  }
});

test('AI playback yields when the awaited menu belongs to a human', async () => {
  const app = {matchId: 'm', state: {menu_pending: {state_version: 11}}, busy: false, menu: null};
  const requestDeferredMenu = async () => {
    app.menu = {manual: true};
    app.state = {menu: app.menu};
  };
  const step = Function('app', 'requestDeferredMenu', `${piece('autoStep', true)}; return autoStep;`)(app, requestDeferredMenu);
  assert.equal(await step(), false); // no automatic submission on the player's turn
});

test('a different committed version starts its own menu read', async () => {
  const app = {matchId: 'm', state: {menu_pending: {state_version: 11}}};
  const waits = [deferred(), deferred()];
  let reads = 0;
  const request = Function('app', 'refresh', `let deferredMenuRead=null; const hint = () => {};
    ${piece('requestDeferredMenu')}; return requestDeferredMenu;`)(app, () => waits[reads++].promise);
  const first = request();
  assert.equal(request(), first);
  app.state.menu_pending.state_version = 12;
  const second = request();
  assert.notEqual(second, first);
  waits[0].resolve();
  await first;
  assert.equal(request(), second); // the old finally cannot clear the new read
  waits[1].resolve();
  await second;
  assert.equal(reads, 2);
});

test('an acknowledgement for a closed fight cannot clear another fight menu', async () => {
  const started = deferred(), acknowledgement = deferred();
  const app = {matchId: 'm', menu: {manual: true}, state: {menu: {decision_id: 'old', state_version: 10}}, lastSequence: 20};
  const forbidden = () => { throw new Error('old fight touched the new table'); };
  const bindings = {
    app, hint() {}, synchronizePresets: async () => {}, refuseCoveredView: () => false,
    document: {body: {classList: {add() {}, remove() {}}}}, enc: encodeURIComponent,
    withReactions: send => send([]), api: () => { started.resolve(); return acknowledgement.promise; },
    invalidateTargeting: forbidden, renderActionBar: forbidden, playEvents: forbidden,
    render: forbidden, refresh: forbidden, gmNotice: forbidden,
    toast: forbidden, handleUnavailableFight: async () => false,
  };
  const act = Function(...Object.keys(bindings), `let refreshSequence=0;
    ${piece('act', true)}; return act;`)(...Object.values(bindings));
  const pending = act('end');
  await started.promise;
  const newState = {menu: {decision_id: 'new', state_version: 30}};
  app.matchId = 'other'; app.state = newState; app.menu = newState.menu;
  acknowledgement.resolve({status: 'COMMITTED', state: {menu: null, menu_pending: {state_version: 11}}});
  assert.equal(await pending, false);
  assert.equal(app.state, newState);
  assert.equal(app.menu, newState.menu);
});
