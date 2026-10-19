// Exercise the actual page functions without a DOM/browser dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {createSeatContext} = require('./tabletop_seats_harness.cjs');
const source = fs.readFileSync(path.join(__dirname, '../static/tabletop/tabletop.js'), 'utf8');
// The real fog view table, so loadMatch's own "a fight you play opens on your own view" default
// runs here instead of silently failing on a missing binding.
const fogViewModule = fs.readFileSync(path.join(__dirname, '../static/tabletop/fog_view.js'), 'utf8')
  .replace(/^export /mg, '');
function pageFunction(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  const body = source.slice(start, source.indexOf('\n}', start) + 2);
  const dependencies = {
    runButton: ['refusalFor'],
    pollTable: ['renderObservedState', 'resumeServerPrompt', 'scheduleSeatPoll'],
    autoStep: ['modelTurnNow'],
    loadMatch: ['handleUnavailableFight', 'closeLoadedFight'],
  };
  const prefix = name === 'runButton' ? 'async function synchronizePresets() {}\n' : '';
  return prefix + [...(dependencies[name] || []).map(pageFunction), body].join('\n');
}
async function recovery() {
  let reads = 0, renders = 0;
  const actor = {controller: 'MANUAL'};
  const app = {matchId: 'fight', menu: null, lastSequence: 7};
  const ctx = createSeatContext({app, refreshSequence: 0, document: {hidden: false}, enc: encodeURIComponent,
    eventsThroughState: async events => events,
    presentation: () => ({current_actor_id: 'tabik'}), actorById: () => actor,
    isManualActor: a => a.controller === 'MANUAL',
    api: async url => url.includes('/events') ? {events: []} : (++reads, {menu: {manual: true}}),
    readTableState: async () => (++reads, {menu: {manual: true}}),
    playEvents: async () => {}, render: state => {renders++; app.menu = state.menu;}});
  vm.runInContext(pageFunction('pollTable'), ctx);
  await ctx.pollTable();
  assert.equal(reads, 1); assert.equal(renders, 1);
  await ctx.pollTable(); assert.equal(reads, 1);
  app.menu = null; actor.controller = 'AI';
  await ctx.pollTable(); assert.equal(reads, 1);
  app.busy = true; actor.controller = 'MANUAL';
  await ctx.pollTable(); assert.equal(reads, 1);
  console.log('manual menu recovery: PASS');
}
async function control() {
  let calls = 0, confirmations = 0, approved = false;
  const actor = {display_name: 'Tabik', controller: 'AI', primary_combatant: true};
  const ctx = createSeatContext({app: {menu: null, matchId: 'fight'}, enc: encodeURIComponent,
    actorById: () => actor, presentation: () => ({current_actor_id: 'tabik'}),
    isManualActor: a => a?.controller === 'MANUAL', toast: () => {}, refresh: async () => {},
    loadSeats: async () => {},
    api: async () => {calls++;}, window: {confirm: () => {confirmations++; return approved;}}});
  vm.runInContext(pageFunction('runButton') + '\n' + pageFunction('setControl'), ctx);
  assert.match((await ctx.runButton({}, 'tabik')).message, /Tabik is played by the AI - take control/);
  actor.controller = 'MANUAL';
  assert.match((await ctx.runButton({}, 'tabik')).message, /table is still loading this fight/);
  await ctx.setControl('tabik', 'LOCAL_AUTO');
  assert.equal(confirmations, 1); assert.equal(calls, 0);
  approved = true; await ctx.setControl('tabik', 'LOCAL_AUTO'); assert.equal(calls, 1);
  await ctx.setControl('tabik', 'MANUAL'); assert.equal(confirmations, 2); assert.equal(calls, 2);
  console.log('AI control explanation and confirmation: PASS');
}
async function transientRead() {
  let calls = 0, pauses = 0;
  const error = {status: 409, code: 'COMBAT_CONTENT_NOT_READY'};
  const ctx = createSeatContext({app: {fog: 'team'}, enc: encodeURIComponent, sleep: async () => {pauses++;},
    api: async () => {if (++calls === 1) throw error; return {menu: 'back'};}});
  vm.runInContext(pageFunction('readTableState'), ctx);
  assert.equal((await ctx.readTableState('fight')).menu, 'back');
  assert.equal(calls, 2); assert.equal(pauses, 1);
  calls = 0; ctx.api = async () => {calls++; throw error;};
  await assert.rejects(ctx.readTableState('fight')); assert.equal(calls, 2);
  calls = 0; error.code = 'TABLETOP_STALE';
  await assert.rejects(ctx.readTableState('fight')); assert.equal(calls, 1);
  console.log('one transient read retry: PASS');
}
async function autoBusy() {
  let finish, clicks = 0;
  const pending = new Promise(resolve => {finish = resolve;});
  const classes = new Set();
  const app = {matchId: 'fight', fog: 'off', busy: false, state: {menu: {decision_id: 'original', state_version: 2}}};
  const ctx = createSeatContext({app, refreshSequence: 0, enc: encodeURIComponent, toast: () => {},
    document: {body: {classList: {add: x => classes.add(x), remove: x => classes.delete(x)}}},
    api: () => pending, withReactions: send => send([]), playEvents: async () => {},
    readTableState: async () => (await pending).state,
    render: () => {}, renderActionBar: () => {}, act: () => {clicks++;},
    presentation: () => ({current_actor_id: 'ai'}), actorById: () => ({controller: 'LOCAL_AUTO'})});
  vm.runInContext(['autoStep', 'useGroup', 'onCellClick', 'onTokenPointerDown'].map(pageFunction).join('\n'), ctx);
  const step = ctx.autoStep();
  assert.equal(app.busy, true); assert.equal(classes.has('is-working'), true);
  assert.equal(await ctx.useGroup({options: [{candidate_id: 'stale'}]}), false);
  await ctx.onCellClick({x: 1, y: 1}); ctx.onTokenPointerDown('tabik', {});
  assert.equal(clicks, 0);
  finish({status: 'COMMITTED', state: {}, events: {}}); assert.equal(await step, true);
  assert.equal(app.busy, false); assert.equal(classes.size, 0);
  console.log('auto-step action exclusion: PASS');
}
async function repeatedChoice() {
  let finish, settled = false, sends = 0;
  const action = new Promise(resolve => {finish = resolve;});
  const nodes = [];
  const app = {busy: false};
  const host = {firstChild: {}, appendChild: node => nodes.push(node)};
  const ctx = createSeatContext({app, $: () => host, hint: () => {}, toast: () => {},
    document: {},
    act: async () => {sends++; app.busy = true; return action;}});
  ctx.document.createElement = () => ({addEventListener(_event, fn) {this.click = fn;}});
  vm.runInContext(pageFunction('chooseFromList') + '\n' + pageFunction('runButton'), ctx);
  const choice = ctx.chooseFromList({label: 'Toggle'}, [{candidate_id: 'a', label: 'A'}, {candidate_id: 'b', label: 'B'}]);
  choice.then(() => {settled = true;});
  const first = nodes[0].click();
  await nodes[0].click(); await nodes[1].click(); nodes[2].click();
  await Promise.resolve(); assert.equal(settled, false); assert.equal(sends, 1);
  assert.match((await ctx.runButton({kind: 'combo'}, 'tabik')).message, /Still working/);
  finish(true); await first; assert.equal(await choice, true);
  console.log('duplicate choice cannot cancel an in-flight action: PASS');
}
async function stalePoll() {
  let finish, renders = 0, reads = 0;
  const stateRead = new Promise(resolve => {finish = resolve;});
  const app = {matchId: 'fight', menu: null, state: {version: 1}};
  const ctx = createSeatContext({app, refreshSequence: 0, document: {hidden: false}, enc: encodeURIComponent,
    eventsThroughState: async events => events,
    presentation: () => ({current_actor_id: 'tabik'}), actorById: () => ({}), isManualActor: () => true,
    api: async () => ({events: []}), readTableState: async () => {reads++; return stateRead;},
    playEvents: async () => {}, render: () => {renders++;}});
  vm.runInContext(pageFunction('pollTable'), ctx);
  const polling = ctx.pollTable(); await Promise.resolve();
  await ctx.pollTable(); assert.equal(reads, 1); // slow polls do not pile up
  app.state = {version: 2}; // another action completed while the read was in flight
  finish({version: 1}); await polling;
  assert.equal(renders, 0); assert.equal(app.polling, false);
  console.log('poll cannot overwrite a completed action: PASS');
}
async function restoredPendingAction() {
  const sent = [], renders = [];
  const pending = {request: {candidate_id: 'candidate-1', decision_id: 'decision-2', state_version: 3, after: 4},
    reactions: [{checkpoint: 'first', selection: 'USE'}], reaction: {context: {checkpoint: 'second'}}};
  const ctx = createSeatContext({app: {matchId: 'fight', busy: false}, refreshSequence: 0, enc: encodeURIComponent,
    askReaction: async prompt => {assert.equal(prompt.context.checkpoint, 'second'); return 'DECLINE';},
    api: async (_url, options) => {sent.push(options.body); return {status: 'COMMITTED', state: {ok: true}, events: {events: []}};},
    playEvents: async () => {}, render: state => renders.push(state), gmNotice: () => {}, toast: () => {}, refresh: async () => {}});
  vm.runInContext(pageFunction('resumePendingAction'), ctx);
  await ctx.resumePendingAction(pending);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].candidate_id, pending.request.candidate_id);
  assert.deepEqual(Array.from(sent[0].reactions, row => row.selection), ['USE', 'DECLINE']);
  assert.deepEqual(renders, [{ok: true}]);
  console.log('restored pending action asks and resubmits original request: PASS');
}
async function reopenWithAutoplay() {
  let releaseEvents, releaseAnswer, sends = 0, clicks = 0;
  const events = new Promise(resolve => {releaseEvents = resolve;});
  const answer = new Promise(resolve => {releaseAnswer = resolve;});
  const timers = [];
  const pending = {method: 'auto_step', request: {decision_id: 'original', state_version: 5, after: 6},
    reactions: [{checkpoint: 'consent', selection: 'USE'}], reaction: {context: {checkpoint: 'dice'}}};
  const state = {menu: {manual: false}, pending_action: pending,
    presentation: {battlefield: {display_name: 'Arena'}, current_actor_id: 'ai'}};
  const app = {busy: false, playing: true, selected: new Set(), lastSequence: 6, fog: 'team'};
  const ctx = createSeatContext({app, refreshSequence: 0, seatReadSequence:0, feedFollow: {}, enc: encodeURIComponent,
    resetViewerPresentation() {}, renderViewerIdentity() {}, resumeServerPrompt() {},
    history: {replaceState: () => {}}, $: () => ({replaceChildren: () => {}, remove() {}}), loadConditionInfo: () => {},
    document: {body: {classList: {remove() {}}}}, clearTimeout() {}, hint() {},
    board: {setTokens() {}, setZones() {}, setHighlights() {}, setMovementExplanation() {}, setFog() {}},
    renderInspector() {}, renderItemsPanel() {}, renderShapePanel() {}, renderPip() {},
    localStorage: {getItem: () => 'team'}, readTableState: async () => state,
    presentation: () => state.presentation, actorById: () => ({}), isManualActor: () => false, hasManualFighter: () => true,
    appendTableLine: () => {}, appendFeed: () => {}, renderActionBar: () => {}, gmNotice: () => {}, broadcastActors: () => {},
    toast: message => {if (!message.includes('Still working')) throw Error(message);}, refresh: async () => {}, openLobby: () => {}, loadSeats: async () => {}, loadProviders: async () => {},
    setTimeout: callback => timers.push(callback), play: () => {throw Error('autoplay overtook recovery');},
    act: () => {clicks++;},
    askReaction: async prompt => {assert.equal(prompt.context.checkpoint, 'dice'); return answer;},
    playEvents: async () => {}, render: s => {app.state = s; app.menu = null; ctx.scheduleAutoPlay();},
    api: async (url, options) => {
      if (url.includes('/events?')) return events;
      sends++; assert.match(url, /auto-step$/);
      assert.equal(options.body.decision_id, 'original'); assert.equal(options.body.state_version, 5);
      assert.deepEqual(Array.from(options.body.reactions, r => r.selection), ['USE', 'DECLINE']);
      return {status: 'COMMITTED', state: {...state, pending_action: null}, events: {events: []}};
    }});
  Object.assign(ctx, {location: {search: ''}, URLSearchParams, setFogPicker() {}});
  vm.runInContext("var viewerStore=createViewerStore({viewId:'recovery-test'});viewerStore.bindGM('fight');",ctx);
  vm.runInContext(fogViewModule + '\n' + ['closeChoice', 'squareFogDebug', 'tabletopUrl', 'loadMatch', 'resumePendingAction', 'scheduleAutoPlay', 'useGroup', 'autoStep'].map(pageFunction).join('\n'), ctx);
  const loading = ctx.loadMatch('fight'); await Promise.resolve(); await Promise.resolve();
  assert.equal(app.busy, true); assert.equal(app.playing, false);
  timers.splice(0).forEach(fn => fn()); // render's autoplay fires during a delayed events response
  assert.equal(await ctx.autoStep(), false);
  assert.equal(await ctx.useGroup({options: [{candidate_id: 'other'}]}), false);
  assert.equal(clicks, 0); assert.equal(sends, 0);
  releaseEvents({events: [], last_sequence: 6}); await Promise.resolve(); await Promise.resolve();
  assert.equal(app.busy, true);
  timers.splice(0).forEach(fn => fn());
  await ctx.resumePendingAction(pending); assert.equal(sends, 0); // duplicate recovery is excluded
  releaseAnswer('DECLINE'); await loading;
  assert.equal(sends, 1); assert.equal(app.busy, false);
  assert.ok(timers.length); // normal autoplay is scheduled only after recovery finishes
  timers.splice(0);
  ctx.readTableState = async () => {throw Error('missing fight');};
  ctx.toast = () => {};
  await ctx.loadMatch('missing');
  assert.equal(app.busy, false);
  assert.equal(timers.length, 0); // failed loading cannot autoplay the previous fight's state
  console.log('reopen reserves recovery before delayed events, autoplay and manual actions: PASS');
}
(async () => {await recovery(); await control(); await transientRead(); await autoBusy(); await repeatedChoice(); await stalePoll(); await restoredPendingAction(); await reopenWithAutoplay();})()
  .catch(error => {console.error(error); process.exitCode = 1;});
