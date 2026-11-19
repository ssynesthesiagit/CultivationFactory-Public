// Exercise the shipped page and its DOM handlers, with only HTTP and time controlled.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
const {setImmediate: tick} = require('node:timers/promises');
const realTimers = require('node:timers');

const html = readFileSync(path.join(__dirname, '../static/tabletop/tabletop.html'), 'utf8');
const clone = value => structuredClone(value);
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};
async function until(check, message) {
  for (let i = 0; i < 100 && !check(); i++) await tick();
  assert.ok(check(), message);
}
const response = (body, status = 200) => new Response(JSON.stringify(body), {status});
const failure = (code, status = 409) => response({error: {code, message: code}}, status);

function actor(id = 'tabik', controller = 'MANUAL', x = 0) {
  return {entity_id: id, display_name: id === 'tabik' ? 'Tabik' : 'Ally', controller,
    primary_combatant: true, active: true, team_index: 0, position: {x, y: 0, z: 0},
    hit_points: {current: 20, maximum: 20}, speed_ft: 30, movement_remaining_ft: 30,
    defenses: [], resources: [], conditions: [], turn_state: {action: true, bonus_action: true}};
}
function menu(actions = [], moves = []) {
  return {manual: true, actor_id: 'tabik', decision_id: 'decision', state_version: 1,
    actions, moves, end_turn: 'end-turn'};
}
function snapshot(controller = 'MANUAL', choices = null) {
  return {menu: choices, last_sequence: 0, map: {background: {style: 'plain'}},
    presentation: {match_id: 'fight', display_name: 'Coordination fight',
      battlefield: {display_name: 'Arena', width_squares: 4, height_squares: 4, blocked_cells: []},
      actors: [actor('tabik', controller)], teams: [], zones: [], initiative_order: ['tabik'],
      current_actor_id: 'tabik', round_number: 1, terminal: false}};
}

async function page(name, state = snapshot()) {
  const {installDOM} = await import('./objects_dom_stub.mjs');
  const {createViewerStore} = await import('../static/tabletop/viewer-identity.js');
  const dom = installDOM(html);
  const storage = new Map();
  window.sessionStorage = {getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)};
  createViewerStore({viewId: 'coordination-test', storage: window.sessionStorage}).bindGM('fight');
  Object.assign(location, {search: '?match=fight&view=coordination-test',
    origin: 'http://localhost', href: 'http://localhost/tabletop?match=fight&view=coordination-test'});
  let sequence = 0;
  const timers = new Map(), intervals = new Map(), listeners = [];
  globalThis.setTimeout = (fn, ms, ...args) => {
    timers.set(++sequence, {ms, fn: () => fn(...args)}); return sequence;
  };
  globalThis.clearTimeout = id => timers.delete(id);
  globalThis.setInterval = (fn, ms) => { intervals.set(ms, fn); return ++sequence; };
  // Observe native window listener registration (not page functions).
  window.addEventListener = (type, fn) => listeners.push({type, fn});
  window.removeEventListener = (type, fn) => {
    const index = listeners.findIndex(row => row.type === type && row.fn === fn);
    if (index >= 0) listeners.splice(index, 1);
  };
  const h = {dom, state, timers, listeners, calls: [], unexpected: [], handler: null,
    count: suffix => h.calls.filter(call => call.url.pathname.endsWith(suffix)).length,
    poll: () => { assert.ok(intervals.has(3000), 'page installed its idle poll'); return intervals.get(3000)(); },
    fireTimers: async ms => {
      const due = [...timers].filter(([, row]) => row.ms === ms);
      for (const [id, row] of due) { timers.delete(id); await row.fn(); }
      return due.length;
    },
    checkRequests: () => assert.deepEqual(h.unexpected, [], 'all requests use the synthetic API'),
  };
  globalThis.fetch = async (requestPath, options = {}) => {
    const url = new URL(requestPath, 'http://localhost');
    const body = options.body ? JSON.parse(options.body) : null;
    const call = {url, body, options};
    h.calls.push(call);
    let result = await h.handler?.(call);
    if (result === undefined) {
      if (url.pathname === '/api/session') result = {token: 'test'};
      else if (url.pathname === '/api/tabletop/conditions') result = {conditions: {}};
      else if (url.pathname === '/api/tabletop/providers') result = {providers: []};
      else if (url.pathname === '/api/combat/matches' || url.pathname === '/api/combat/factory-characters') result = [];
      else if (url.pathname === '/api/tabletop/maps') result = {maps: [], builtin: []};
      else if (url.pathname.endsWith('/state')) result = clone(h.state);
      else if (url.pathname.endsWith('/events')) result = {events: [], last_sequence: h.state.last_sequence};
      else if (url.pathname.endsWith('/seat-status')) result = {seats: {}};
      else {
        h.unexpected.push(requestPath);
        throw Error(`Unexpected API ${requestPath}`);
      }
    }
    return result instanceof Response ? result : response(result);
  };
  // A distinct module instance gives each check its own real top-level state.
  await import(pathToFileURL(path.join(__dirname, '../static/tabletop/tabletop.js')).href + `?coordination=${name}`);
  await until(() => window.tabletop, 'the complete production page boots');
  h.table = window.tabletop;
  assert.equal(h.table.app.matchId, 'fight', dom.querySelector('.tt-toast.is-error')?.textContent);
  assert.ok(h.table.app.state, 'real loadMatch rendered the fixture');
  await tick(); // settle the asynchronous action-bar render
  h.checkRequests();
  return h;
}

async function recovery() {
  const h = await page('recovery'), {app} = h.table;
  const initialReads = h.count('/state');
  h.state.menu = menu();
  await h.poll();
  assert.equal(h.count('/state') - initialReads, 1);
  assert.equal(app.menu.manual, true);
  const rendered = app.receivedState;
  // 0701001f78: every poll reads state, but an unchanged manual menu is not re-rendered.
  await h.poll();
  assert.equal(h.count('/state') - initialReads, 2);
  assert.equal(app.receivedState, rendered);
  app.menu = null; h.state.menu = null; h.state.presentation.actors[0].controller = 'AI';
  await h.poll();
  assert.equal(h.count('/state') - initialReads, 3);
  assert.notEqual(app.receivedState, rendered);
  const aiRender = app.receivedState;
  app.busy = true; h.state.presentation.actors[0].controller = 'MANUAL';
  await h.poll();
  assert.equal(h.count('/state') - initialReads, 3);
  assert.equal(app.receivedState, aiRender);
  app.busy = false;
  h.checkRequests();
  console.log('manual menu recovery: PASS');
}

async function control() {
  const h = await page('control', snapshot('AI')), {app, runButton} = h.table;
  let confirmations = 0;
  window.confirm = globalThis.confirm = () => { confirmations++; return false; };
  assert.match((await runButton({}, 'tabik')).message, /Tabik is played by the AI - take control/);
  const cached = app.state;
  app.state = null;
  const reads = h.count('/state');
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/state')) return failure('COMBAT_MATCH_NOT_FOUND', 404);
  };
  assert.match((await runButton({}, 'tabik')).message, /table is still loading this fight/i);
  assert.equal(h.count('/state') - reads, 1, 'the unavailable refresh cannot restore a snapshot');
  assert.equal(app.state, null);
  h.handler = null;
  app.state = cached;
  h.state.presentation.actors[0].controller = 'MANUAL';
  h.state.menu = menu();
  await h.table.loadMatch('fight');
  // Reopening clears selection; select the fighter as a player does before using its switch.
  const token = h.table.board.element.querySelectorAll('.tt-token').find(node => node.dataset.tokenId === 'tabik');
  assert.ok(token, 'the reopened fight renders Tabik for selection');
  await token.click();
  h.handler = ({url, body}) => {
    if (url.pathname.endsWith('/controller-mode')) {
      h.state.presentation.actors[0].controller = body.controller_mode;
      h.state.menu = body.controller_mode === 'MANUAL' ? menu() : null;
      return {};
    }
    if (url.pathname.endsWith('/automatic-run')) return {status: 'COMMITTED'};
  };
  await h.dom.querySelector('#ttInspector [data-control="LOCAL_AUTO"]').click();
  await until(() => h.count('/automatic-run') === 1 && app.automaticRun === null, 'handing over starts the current AI turn');
  assert.equal(confirmations, 0); assert.equal(h.count('/controller-mode'), 1);
  assert.equal(h.count('/automatic-run'), 1);
  await h.dom.querySelector('#ttInspector [data-control="MANUAL"]').click();
  await until(() => app.menu?.manual && h.count('/controller-mode') === 2, 'taking control applies immediately');
  assert.equal(confirmations, 0); assert.equal(h.count('/controller-mode'), 2);
  h.checkRequests();
  console.log('AI control applies immediately and starts the current AI turn: PASS');
}

async function transientRead() {
  const h = await page('transient-read');
  let calls = 0, mode = 'once';
  h.handler = ({url}) => {
    if (!url.pathname.endsWith('/state')) return;
    calls++;
    if (mode === 'stale') return failure('TABLETOP_STALE');
    if (mode === 'always' || calls === 1) return failure('COMBAT_CONTENT_NOT_READY');
    return clone(h.state);
  };
  const opening = h.table.loadMatch('fight');
  await until(() => [...h.timers.values()].some(row => row.ms === 250), 'transient read pauses before retry');
  assert.equal(await h.fireTimers(250), 1);
  assert.equal(await opening, true);
  assert.equal(calls, 2);
  calls = 0; mode = 'always';
  const failing = h.table.loadMatch('fight');
  await until(() => [...h.timers.values()].some(row => row.ms === 250), 'second transient failure gets only one retry');
  assert.equal(await h.fireTimers(250), 1);
  assert.equal(await failing, false); assert.equal(calls, 2);
  calls = 0; mode = 'stale';
  assert.equal(await h.table.loadMatch('fight'), false); assert.equal(calls, 1);
  assert.equal([...h.timers.values()].some(row => row.ms === 250), false);
  h.checkRequests();
  console.log('one transient read retry: PASS');
}

async function autoBusy() {
  const h = await page('auto-busy', snapshot('LOCAL_AUTO')), {app} = h.table;
  const pending = deferred();
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/automatic-run')) return pending.promise;
    if (url.pathname.endsWith('/prepare')) return {status: 'PREPARED'};
    if (url.pathname.endsWith('/act')) return {status: 'COMMITTED', state: clone(h.state), events: {events: []}};
  };
  const step = h.table.autoStep();
  assert.ok(app.automaticRun);
  assert.equal(await h.table.autoStep(), false);
  await until(() => h.count('/automatic-run') === 1, 'automatic-run request is pending');
  assert.equal(h.count('/automatic-run'), 1);
  const group = {label: 'Stale action', source_definition_id: 'system:test.stale', economy: 'ACTION',
    options: [{candidate_id: 'stale', target_ids: ['tabik'], option_ids: []}]};
  const move = {candidate_id: 'move', destination: {x: 1, y: 1, z: 0}, path: []};
  app.menu = app.state.menu = menu([group], [move]); app.showMoves = true;
  assert.equal(await h.table.useGroup(group), false);
  const {CELL} = await import('../static/tabletop/board.js');
  const {board} = h.table, view = board.view;
  // Drive a logical square through the board transform; no painted size/layout is asserted.
  const point = {clientX: view.x + 1.5 * CELL * view.zoom, clientY: view.y + 1.5 * CELL * view.zoom, pointerId: 1};
  await board.viewport.dispatch('pointerdown', point);
  await board.viewport.dispatch('pointerup', point);
  const beforeListeners = h.listeners.length;
  const token = board.element.querySelectorAll('.tt-token').find(node => node.dataset.tokenId === 'tabik');
  assert.ok(token, 'the real page rendered the current token');
  await token.dispatch('pointerdown', {clientX: 0, clientY: 0});
  await tick();
  assert.equal(h.count('/act'), 0);
  assert.equal(h.count('/prepare'), 0);
  assert.equal(app.dragMove ?? null, null);
  assert.equal(h.listeners.length, beforeListeners);
  pending.resolve({status: 'COMMITTED'});
  assert.equal(await step, true);
  assert.equal(app.automaticRun, null);
  h.checkRequests();
  console.log('auto-step action exclusion: PASS');
}

async function repeatedChoice() {
  const group = {label: 'Toggle', source_definition_id: 'system:test.toggle', economy: 'ACTION', placement_picker: true,
    options: ['a', 'b'].map(id => ({candidate_id: id, label: id.toUpperCase(), target_ids: ['tabik'], option_ids: []}))};
  const h = await page('repeated-choice', snapshot('MANUAL', menu([group])));
  const action = deferred();
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/prepare')) return {status: 'PREPARED'};
    if (url.pathname.endsWith('/act')) return action.promise;
  };
  let settled = false;
  const choice = h.table.runButton({label: 'Toggle', combat: {source_definition_id: group.source_definition_id}}, 'tabik');
  choice.then(() => { settled = true; });
  await until(() => h.table.app.listPick, 'the page offers both options and Cancel');
  const nodes = h.dom.querySelector('#ttHint').querySelectorAll('button');
  assert.deepEqual(nodes.map(node => node.textContent), ['A', 'B', 'Cancel']);
  const first = nodes[0].click();
  await until(() => h.count('/act') === 1, 'first option is being applied');
  await nodes[0].click(); await nodes[1].click(); await nodes[2].click();
  await tick(); assert.equal(settled, false); assert.equal(h.count('/act'), 1);
  assert.match((await h.table.runButton({kind: 'combo'}, 'tabik')).message, /Still working/);
  action.resolve({status: 'COMMITTED', state: snapshot(), events: {events: []}});
  await first; assert.equal((await choice).ok, true);
  h.checkRequests();
  console.log('duplicate choice cannot cancel an in-flight action: PASS');
}

async function stalePoll() {
  const h = await page('stale-poll'), {app} = h.table;
  const stateRead = deferred();
  let reads = 0;
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/state')) { reads++; return stateRead.promise; }
  };
  const polling = h.poll();
  await until(() => reads === 1, 'first poll is waiting for state');
  await h.poll(); assert.equal(reads, 1);
  const rendered = app.receivedState;
  app.state = {...app.state, version: 2}; // a different action completed while the read was in flight
  stateRead.resolve({...clone(h.state), version: 1});
  await polling;
  assert.equal(app.state.version, 2);
  assert.equal(app.receivedState, rendered); // the stale snapshot was not rendered
  assert.equal(app.polling, false);
  h.checkRequests();
  console.log('poll cannot overwrite a completed action: PASS');
}

function savedAction(checkpoint, automatic = false) {
  return {method: automatic ? 'auto_step' : 'act',
    request: automatic ? {decision_id: 'original', state_version: 5, after: 6}
      : {candidate_id: 'candidate-1', decision_id: 'decision-2', state_version: 3, after: 4},
    reactions: [{checkpoint: automatic ? 'consent' : 'first', selection: 'USE'}],
    reaction: {reactor: 'Tabik', reaction: 'Test reaction', trigger: 'An attack targets Tabik',
      summary: 'Decline the reaction', cost: 'None', context: {checkpoint}}};
}
function decline(h) {
  const button = h.dom.querySelector('#ttReaction [data-answer="DECLINE"]');
  assert.ok(button, 'the real reaction dialog offers Decline');
  button.dispatchEvent(new Event('click', {bubbles: true, cancelable: true}));
}

async function restoredPendingAction() {
  const h = await page('restored-pending'), pending = savedAction('second');
  h.state.pending_action = pending; h.state.last_sequence = 4;
  const committed = {...clone(h.state), pending_action: null};
  committed.presentation.display_name = 'Recovered action';
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/act')) return {status: 'COMMITTED', state: committed, events: {events: []}};
  };
  const loading = h.table.loadMatch('fight');
  await until(() => h.dom.querySelector('#ttReaction').open, 'saved action asks its outstanding reaction');
  assert.equal(h.table.app.waitingReaction.prompt.context.checkpoint, 'second');
  assert.equal(h.count('/act'), 0);
  const before = h.table.app.receivedState;
  decline(h);
  assert.equal(await loading, true);
  const sent = h.calls.filter(call => call.url.pathname.endsWith('/act'));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].body.candidate_id, pending.request.candidate_id);
  assert.equal(sent[0].body.decision_id, pending.request.decision_id);
  assert.equal(sent[0].body.state_version, pending.request.state_version);
  assert.deepEqual(sent[0].body.reactions.map(row => row.selection), ['USE', 'DECLINE']);
  assert.notEqual(h.table.app.receivedState, before);
  assert.deepEqual(h.table.app.receivedState.received, committed);
  h.checkRequests();
  console.log('restored pending action asks and resubmits original request: PASS');
}

async function reopenWithAutoplay() {
  const initial = snapshot('LOCAL_AUTO');
  initial.presentation.actors.push(actor('ally', 'MANUAL', 2));
  const h = await page('reopen-autoplay', initial), {app} = h.table;
  const events = deferred(), pending = savedAction('dice', true);
  h.state.pending_action = pending; h.state.last_sequence = 6;
  const committed = {...clone(h.state), pending_action: null};
  let waitingForEvents = false;
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/state') && url.pathname.includes('/missing/')) return failure('COMBAT_MATCH_NOT_FOUND', 404);
    if (url.pathname.endsWith('/events')) { waitingForEvents = true; return events.promise; }
    if (url.pathname.endsWith('/auto-step')) return {status: 'COMMITTED', state: committed, events: {events: []}};
  };
  app.playing = true;
  const loading = h.table.loadMatch('fight');
  await until(() => waitingForEvents && app.state?.pending_action, 'reload waits for the delayed event history');
  assert.equal(app.busy, true); assert.equal(app.playing, false);
  await h.fireTimers(60);
  assert.equal(await h.table.autoStep(), false);
  assert.equal(await h.table.useGroup({options: [{candidate_id: 'other'}]}), false);
  assert.equal(h.count('/act'), 0); assert.equal(h.count('/auto-step'), 0);
  assert.equal(h.count('/automatic-run'), 0);
  events.resolve({events: [], last_sequence: 6});
  await until(() => h.dom.querySelector('#ttReaction').open, 'history completes before the saved prompt opens');
  assert.equal(app.waitingReaction.prompt.context.checkpoint, 'dice');
  assert.equal(app.busy, true);
  await h.fireTimers(60);
  const waiting = app.waitingReaction;
  // Re-applying the view asks resumeServerPrompt through its real DOM path.
  await h.dom.querySelector('#ttViewerGM').click();
  assert.equal(await h.table.loadMatch('fight'), false);
  assert.equal(app.waitingReaction, waiting);
  assert.equal(h.count('/auto-step'), 0);
  assert.equal(h.count('/automatic-run'), 0);
  decline(h);
  assert.equal(await loading, true);
  const sent = h.calls.filter(call => call.url.pathname.endsWith('/auto-step'));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].body.decision_id, 'original'); assert.equal(sent[0].body.state_version, 5);
  assert.deepEqual(sent[0].body.reactions.map(row => row.selection), ['USE', 'DECLINE']);
  assert.equal(app.busy, false);
  assert.ok([...h.timers.values()].some(row => row.ms === 60), 'autoplay is scheduled after recovery finishes');
  h.timers.clear();
  assert.equal(await h.table.loadMatch('missing'), false);
  assert.equal(app.busy, false);
  assert.equal(app.state, null);
  assert.equal([...h.timers.values()].some(row => row.ms === 60), false);
  assert.equal(h.count('/automatic-run'), 0);
  h.checkRequests();
  console.log('reopen reserves recovery before delayed events, autoplay and manual actions: PASS');
}

const watchdog = realTimers.setTimeout(() => {
  console.error('page coordination did not finish all eight checks');
  process.exit(1);
}, 20000);
(async () => {
  await recovery(); await control(); await transientRead(); await autoBusy();
  await repeatedChoice(); await stalePoll(); await restoredPendingAction(); await reopenWithAutoplay();
})().catch(error => { console.error(error); process.exitCode = 1; })
  .finally(() => realTimers.clearTimeout(watchdog));
