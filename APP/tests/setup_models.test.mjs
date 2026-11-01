// Real setup lifecycle and preset handlers; no browser, rendering, or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {canAddFighter} from '../static/tabletop/limits.js';
import {applyPick} from '../static/tabletop/fighter-picker.js';
import {MODEL_PREFIX, setupControlHtml, splitSetupControl, serverDriving} from '../static/tabletop/seats.js';
import {compactStatePath} from '../static/tabletop/movement-grid.js';
import {createTableHarness, actor, tableState, functionSource} from './viewer_identity_harness.mjs';

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.handlers = {}; this._value = ''; this.selectors = new Map(); this.dataset = {}; }
  set value(value) { this._value = this.tag === 'select' && this.options && !this.options.some(o => o.value === value) ? '' : value; }
  get value() { return this._value; }
  set innerHTML(html) {
    this.children = [];
    if (this.tag === 'select') {
      this.options = [...html.matchAll(/<option value="([^"]*)"/g)].map(m => ({value: m[1]}));
      this.value = this.options[0]?.value || '';
    }
    if (html.startsWith('<h4>')) {
      const slots = new Element('div'); slots.className = 'tt-slots';
      this.append(new Element('h4'), slots, new Element('button'));
    }
  }
  append(...items) { items.forEach(item => this.appendChild(item)); }
  appendChild(item) { item.parent = this; this.children.push(item); }
  replaceChildren(...items) { this.children = []; this.append(...items); if (this.tag === 'select') this.options = items; }
  querySelector(selector) {
    if (selector.startsWith('[data-')) {
      if (!this.selectors.has(selector)) this.selectors.set(selector, new Element(/load|save|delete/.test(selector) ? 'button' : 'select'));
      return this.selectors.get(selector);
    }
    return this.children.find(item => selector.startsWith('.') ? item.className === selector.slice(1) : item.tag === selector);
  }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  dispatchEvent(event) { return this.handlers[event.type]?.(event); }
  click() { if (!this.disabled) return this.handlers.click?.(); }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}
const clone = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(resolve => setImmediate(resolve));
async function harness({providers = [{id: 'model', label: 'Helpful model'}], failSeat = null, deferred = null,
  failPause = false, lostSeatResponse = null, failStatus = false, failRelease = false, lostReleaseResponse = false,
  conflictingSeat = false, failOpen = false, realLoader = false, loaderFailure = null} = {}) {
  const source = await readFile(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const host = new Element('div'), calls = [], notices = [], teams = [], presets = [], picker = [];
  let paused = false, sequence = 0, creates = 0;
  const seats = {}, characters = [{project_id: 'a', display_name: 'Alice'}, {project_id: 'b', display_name: 'Bob'}];
  const faults = {failPause, failStatus, failRelease, lostReleaseResponse, failOpen, loaderFailure};
  const nodes = new Map();
  // An explicit GM binding preserves the setup-only cases' original view. The
  // final player case selects a real stored binding instead of default-GM hacks.
  const viewer = realLoader ? createTableHarness({matchId: 'new', gm: true, initialize: false}) : null;
  const app = viewer?.app || {selected: new Set(), fog: 'GM', lastSequence: 0};
  app.providers = providers;
  const ctx = vm.createContext({URLSearchParams, builderBuilt: false, refreshSequence: 0, seatReadSequence: 0, feedFollow: {}, compactStatePath,
    preferenceStorage: {getItem: () => null},
    app, canAddFighter, applyPick, MODEL_PREFIX,
    setupControlHtml, splitSetupControl, FACTORY: 'actor:factory.', Event, enc: encodeURIComponent,
    document: {createElement: tag => new Element(tag), body: {classList: {remove() {}}}},
    Option: function(text, value) {this.text = text; this.value = value;},
    $: selector => {
      if (selector === '#ttBuilder') return host;
      if (!nodes.has(selector)) {
        const node = new Element('div'); node.open = selector === '#ttLobby';
        node.close = () => {node.open = false; calls.push('close');}; nodes.set(selector, node);
      }
      return nodes.get(selector);
    },
    escapeHtml: value => value, prompt: () => 'Saved', confirm: () => true,
    loadProviders: async () => {}, toast: message => notices.push(message),
    // The builder reads the model list's retry state (provider-list.js, SEATLIST1) for its "retrying" note.
    providerList: {state: {unavailable: false}},
    fighterPicker: {fillSlotFace() {}, open: options => picker.push(options)},
    loadPrefight: async entry => {entry.prefight = new Set(); return true;}, serializePrefight: () => [],
    loadMatch: async mid => {calls.push('open'); assert.equal(mid, 'new'); if (faults.failOpen) throw Error('Could not load fight'); return true;},
    loadConditionInfo: async () => {}, closeChoice() {}, history: {replaceState() {}}, tabletopUrl: mid => mid,
    loadSeats: async () => {}, render(state) { ctx.app.state = state; ctx.app.menu = state.menu || null; },
    rememberFogView: () => true, clearTimeout() {}, hint() {}, squareFogDebug: () => false,
    board: {setTokens() {}, setZones() {}, setHighlights() {}, setMovementExplanation() {}, setFog() {}},
    renderInspector() {}, renderItemsPanel() {}, renderShapePanel() {}, renderPip() {},
    appendTableLine() {}, appendFeed() {}, renderActionBar() {}, scheduleAutoPlay: () => calls.push('autoplay'),
    openLobby: () => {nodes.get('#ttLobby').open = true; if (realLoader) calls.push('lobby');},
    api: async (url, options) => {
      if (url.includes('/state?fog=')) {
        calls.push('open'); assert.ok(url.includes('/matches/new/'));
        if (faults.loaderFailure === 'state') throw Error('State read unavailable');
        if (faults.loaderFailure === 'stale') ctx.refreshSequence++;
        return tableState(characters.map((row, i) => actor(`actor:factory.${row.project_id}`, {x: 20 + i, y: 15})), {matchId: 'new'});
      }
      if (url.endsWith('/events?after=0')) {
        if (faults.loaderFailure === 'events') throw Error('Events read unavailable');
        if (faults.loaderFailure === 'events-stale') ctx.refreshSequence++;
        return {events: [], last_sequence: 0};
      }
      if (url.endsWith('factory-characters')) return characters;
      if (url.endsWith('/maps')) return {maps: [], builtin: []};
      const body = options?.body;
      if (url.endsWith('factory-matches')) { calls.push(['create', clone(body)]); creates++; return {match_id: 'new'}; }
      if (url.endsWith('/playback')) {
        if (faults.failPause && body.paused) throw Error('Could not pause playback');
        if (faults.failRelease && !body.paused) throw Error('Could not release playback');
        paused = body.paused; calls.push(['pause', paused]);
        if (faults.lostReleaseResponse && !body.paused) throw Error('Release response interrupted');
        return {paused};
      }
      if (url.endsWith('/seat-status')) {
        calls.push('status');
        if (faults.failStatus) throw Error('Status unavailable');
        return {seats: clone(seats), paused};
      }
      if (url.endsWith('/seat')) {
        calls.push(['seat', body.actor_id]);
        assert.equal(paused, true, 'runner must stay paused through every seat request');
        if (body.actor_id === failSeat) {
          if (conflictingSeat) seats[body.actor_id] = {control: 'AI'};
          throw Error('Model unavailable');
        }
        seats[body.actor_id] = body;
        // Simulate observe on each seat POST: later fighter has initiative and
        // could trigger a reaction for the first. Neither can run during setup.
        if (!paused) sequence++;
        if (deferred && body.actor_id.endsWith('.b')) await deferred;
        if (body.actor_id === lostSeatResponse) throw Error('Response interrupted');
        return {};
      }
      const store = url.endsWith('saved-teams') ? teams : presets;
      if (body) {store.splice(0, store.length, clone(body.preset)); return clone(body.preset);}
      return url.endsWith('saved-teams') ? {teams: clone(store)} : {presets: clone(store)};
    },
  });
  if (realLoader) {
    viewer.api = (...args) => ctx.api(...args);
    Object.assign(ctx, {viewerStore: viewer.viewerStore, NO_FOG_VIEW: 'GM', DEFAULT_FOG_VIEW: 'own', serverDriving,
      resetViewerPresentation: viewer.resetViewerPresentation, renderViewerIdentity: viewer.renderViewerIdentity,
      currentViewer: viewer.currentViewer, reconcileViewerIdentity: viewer.reconcileViewerIdentity,
      renderTokens: viewer.renderTokens, resumeServerPrompt: viewer.resumeServerPrompt,
      render: state => {app.state = state; viewer.reconcileViewerIdentity();}});
    vm.runInContext(functionSource('loadSeats'), ctx);
    for (const declaration of ['async function loadMatch(', 'async function readTableState(',
      'function tokenIdsKey(', 'function rememberedTokenIds(',
      'function closeLoadedFight(', 'async function handleUnavailableFight(']) {
      const start = source.indexOf(declaration);
      vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
    }
  }
  const start = source.indexOf('async function buildFightBuilder()');
  const end = source.indexOf('\n}', source.indexOf('function presetBar(')) + 2;
  vm.runInContext(source.slice(start, end), ctx);
  await ctx.buildFightBuilder(); await settle();
  // The builder now appends a model-list note before the bars (provider-list.js, SEATLIST1), so find
  // the panels by what they are rather than by position.
  const teamHost = host.children.find(node => node.className === 'tt-teams');
  const bars = teamHost.children.map(box => box.children.at(-1));
  const sides = bars.map(bar => bar.querySelector('[data-team-save]').presetSides[0]);
  sides.forEach((side, i) => {side.slots[0].who.value = characters[i].project_id; side.slots[0].prefight = new Set();});
  const foot = host.children.at(-1);
  const create = foot.children.find(node => node.textContent === 'Create fight');
  const openCreated = foot.children.find(node => node.textContent === 'Open created fight');
  return {ctx, host, sides, bars, create, openCreated, calls, notices, picker, seats, faults,
    paused: () => paused, sequence: () => sequence, creates: () => creates};
}

test('all model seats are installed while paused, before the table opens', async () => {
  let release; const deferred = new Promise(resolve => {release = resolve;});
  const h = await harness({deferred});
  h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
  const creating = h.create.click(); await settle();
  assert.deepEqual(h.calls[0][1].control_modes, {'actor:factory.a': 'MANUAL', 'actor:factory.b': 'MANUAL'});
  assert.deepEqual(h.calls.slice(1), [['pause', true], ['seat', 'actor:factory.a'], ['seat', 'actor:factory.b']]);
  assert.equal(h.sequence(), 0);
  assert.equal(h.create.disabled, true);
  await h.create.click(); assert.equal(h.creates(), 1);
  release(); await creating;
  assert.deepEqual(h.calls.slice(-3), [['pause', false], 'close', 'open']);
  assert.equal(Object.keys(h.seats).length, 2);
});

test('seat failure names the fighter and leaves that fighter in player control', async () => {
  const h = await harness({failSeat: 'actor:factory.b'});
  h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
  await h.create.click();
  assert.equal(h.calls[0][1].control_modes['actor:factory.b'], 'MANUAL');
  assert.equal(h.seats['actor:factory.b'], undefined);
  assert.match(h.notices[0], /Bob.*You now play Bob/);
  assert.equal(h.calls.at(-1), 'open');
});

test('a failed playback pause retains the fight for open and setup retry', async () => {
  const h = await harness({failPause: true});
  h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
  await h.create.click();
  assert.equal(h.calls.length, 1);
  assert.equal(Object.keys(h.seats).length, 0);
  assert.match(h.notices[0], /Could not pause playback/);
  assert.equal(h.create.disabled, false);
  assert.equal(h.openCreated.hidden, false);
  assert.match(h.notices[0], /fight already exists.*Could not pause playback.*Could not confirm.*same fight/);
  await h.openCreated.click();
  assert.equal(h.ctx.app.userPaused, true);
  h.faults.failPause = false;
  await h.create.click();
  assert.equal(h.creates(), 1);
  assert.equal(Object.keys(h.seats).length, 2);
  assert.equal(h.openCreated.hidden, true);
});

test('a committed model seat with a lost response is confirmed before release', async () => {
  const h = await harness({lostSeatResponse: 'actor:factory.b'});
  h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
  await h.create.click();
  assert.equal(h.seats['actor:factory.b'].control, 'MODEL');
  assert.deepEqual(h.calls.slice(-4), ['status', ['pause', false], 'close', 'open']);
  assert.match(h.notices[0], /Bob's selected model is seated/);
  assert.ok(h.notices.every(message => !message.includes('You now play Bob')));
});

test('unavailable ownership status keeps playback paused until the same setup can be retried', async () => {
  const h = await harness({lostSeatResponse: 'actor:factory.b', failStatus: true});
  h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
  await h.create.click();
  assert.equal(h.paused(), true);
  assert.ok(!h.calls.includes('open'));
  assert.match(h.notices[0], /Could not confirm who plays Bob.*Automatic turns are paused/);
  assert.ok(h.notices.every(message => !message.includes('You now play Bob')));
  h.faults.failStatus = false;
  await h.create.click();
  assert.equal(h.creates(), 1);
  assert.equal(h.paused(), false);
});

test('conflicting ownership is never described as player control or released', async () => {
  const h = await harness({failSeat: 'actor:factory.b', conflictingSeat: true});
  h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
  await h.create.click();
  assert.equal(h.paused(), true);
  assert.ok(!h.calls.includes('open'));
  assert.ok(h.notices.every(message => !message.includes('You now play Bob')));
});

for (const lostResponse of [false, true]) {
  test(`release ${lostResponse ? 'committed with lost response' : 'failure'} allows open and retry without duplicate creation`, async () => {
    const h = await harness(lostResponse ? {lostReleaseResponse: true} : {failRelease: true});
    h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
    await h.create.click();
    assert.equal(h.paused(), true);
    assert.equal(h.openCreated.hidden, false);
    assert.equal(h.create.textContent, 'Retry fight setup');
    assert.match(h.notices[0], /fight already exists.*Automatic turns are paused.*same fight/);
    await h.openCreated.click();
    assert.equal(h.calls.at(-1), 'open');
    h.faults.failRelease = h.faults.lostReleaseResponse = false;
    // Later edits must not alter or invalidate the retained creation snapshot.
    h.sides.forEach(side => {side.slots[0].who.value = ''; side.slots[0].control.value = 'MANUAL';});
    await h.create.click();
    assert.equal(h.creates(), 1);
    assert.equal(h.calls.filter(call => call[0] === 'seat').length, 2);
    assert.equal(h.paused(), false);
    assert.equal(h.openCreated.hidden, true);
  });
}

test('table opening errors retain the created fight for retry', async () => {
  const h = await harness({failOpen: true});
  await h.create.click();
  assert.equal(h.openCreated.hidden, false);
  await h.openCreated.click();
  assert.match(h.notices.at(-1), /fight already exists.*Could not load fight/);
  h.faults.failOpen = false;
  await h.create.click();
  assert.equal(h.creates(), 1);
});

for (const failure of ['state', 'events', 'stale', 'events-stale', 'busy']) for (const model of [false, true]) {
  test(`real loader ${failure} failure retains ${model ? 'model' : 'ordinary'} fight for same-fight retry`, async () => {
    const h = await harness({realLoader: true, loaderFailure: failure});
    if (model) h.sides.forEach(side => {side.slots[0].control.value = 'MODEL:model';});
    if (failure === 'busy') h.ctx.app.busy = true;
    await h.create.click();
    assert.equal(h.openCreated.hidden, false);
    assert.equal(h.create.textContent, 'Retry fight setup');
    assert.equal(h.creates(), 1);
    assert.equal(h.ctx.$('#ttLobby').open, true, 'recovery controls must be visible even after a busy or stale opening');
    assert.ok(!h.calls.includes('autoplay'));
    if (model) assert.equal(h.paused(), true);
    if (['state', 'events'].includes(failure)) assert.ok(h.calls.includes('lobby'));
    await h.openCreated.click();
    assert.equal(h.openCreated.hidden, false);
    assert.match(h.notices.at(-1), /fight already exists.*same fight/);
    if (model) assert.equal(h.paused(), true);
    h.faults.loaderFailure = null;
    h.ctx.app.busy = false;
    await h.create.click();
    assert.equal(h.creates(), 1);
    assert.equal(h.ctx.app.matchId, 'new', `${h.notices.join(' | ')}; calls: ${JSON.stringify(h.calls)}`);
    assert.equal(h.openCreated.hidden, true);
    assert.equal(h.create.textContent, 'Create fight');
    assert.equal(h.calls.filter(call => call[0] === 'seat').length, model ? 2 : 0);
    assert.ok(h.calls.includes('autoplay'));
    if (model) assert.equal(h.paused(), false);
  });
}

test('real loader confirms opening with an explicit player binding and its own fog default', async () => {
  const h = await harness({realLoader: true});
  h.ctx.viewerStore.bindPlayer('new', ['actor:factory.a']);
  await h.create.click();
  assert.equal(h.ctx.app.fog, 'own');
  assert.equal(h.ctx.currentViewer().status, 'player', `${h.notices.join(' | ')}; calls: ${JSON.stringify(h.calls)}`);
  assert.equal(h.openCreated.hidden, true);
  assert.equal(h.create.textContent, 'Create fight');
  assert.ok(h.calls.includes('autoplay'));
});

test('when every model seat fails all model fighters stay manual and playback is released', async () => {
  const h = await harness({failSeat: 'actor:factory.a'});
  h.sides[0].slots[0].control.value = 'MODEL:model';
  await h.create.click();
  assert.equal(Object.keys(h.seats).length, 0);
  assert.equal(h.calls[0][1].control_modes['actor:factory.a'], 'MANUAL');
  assert.deepEqual(h.calls.slice(-3), [['pause', false], 'close', 'open']);
  assert.match(h.notices[0], /You now play Alice/);
});

for (const store of ['team', 'preset']) for (const removed of [false, true]) {
  test(`${store} save → reload → create ${removed ? 'falls back to AI for a removed model' : 'keeps the model'}`, async () => {
    const h = await harness();
    const side = h.sides[0]; side.slots[0].control.value = 'MODEL:model';
    const bar = store === 'team' ? h.bars[0] : h.host.children.find(node => node.className === 'tt-presets');
    await bar.querySelector(`[data-${store}-save]`).click();
    await settle();
    if (removed) h.ctx.app.providers = [];
    side.slots[0].control.value = 'MANUAL';
    bar.querySelector(`[data-${store}]`).value = 'Saved';
    await bar.querySelector(`[data-${store}-load]`).click();
    assert.equal(side.slots[0].control.value, removed ? 'LOCAL_AUTO' : 'MODEL:model');
    await h.create.click();
    assert.equal(h.calls[0][1].control_modes['actor:factory.a'], removed ? 'LOCAL_AUTO' : 'MANUAL');
    assert.equal(Boolean(h.seats['actor:factory.a']), !removed);
  });
}

test('re-picking keeps a model on AI selection and respects an explicit You selection', async () => {
  const h = await harness(), entry = h.sides[0].slots[0];
  entry.control.value = 'MODEL:model';
  const face = entry.slot.children.find(child => child.className === 'tt-slot-face');
  face.click(); h.picker.at(-1).onPick({project_id: 'a', mode: 'LOCAL_AUTO'});
  assert.equal(entry.control.value, 'MODEL:model');
  face.click(); h.picker.at(-1).onPick({project_id: 'a', mode: 'MANUAL'});
  assert.equal(entry.control.value, 'MANUAL');
});

test('no-model setup retains You/AI modes and makes no seat or playback requests', async () => {
  const h = await harness({providers: []}); await h.create.click();
  assert.deepEqual(h.calls[0][1].control_modes, {'actor:factory.a': 'MANUAL', 'actor:factory.b': 'LOCAL_AUTO'});
  assert.deepEqual(h.calls.slice(1), ['close', 'open']);
});

test('a finished setup permits a later new fight from the reused builder', async () => {
  const h = await harness();
  await h.create.click();
  assert.equal(h.create.textContent, 'Create fight');
  await h.create.click();
  assert.equal(h.creates(), 2);
});
