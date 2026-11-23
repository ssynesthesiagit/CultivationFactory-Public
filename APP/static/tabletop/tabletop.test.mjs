// node --test APP/static/tabletop/tabletop.test.mjs
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import * as vm from 'node:vm';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView} from './fog_view.js';
import {createViewerStore, resolveViewerIdentity} from './viewer-identity.js';
import {compactStatePath} from './movement-grid.js';
// VM modules require an opt-in on Node versions that still gate them.
if (!vm.SourceTextModule) {
  const child = spawnSync(process.execPath, ['--experimental-vm-modules', '--test', fileURLToPath(import.meta.url)], {stdio: 'inherit'});
  process.exit(child.status ?? 1);
}
const {openTablePage} = await import('../../tests/tabletop_page.mjs');


test('retained commit notice renders plain text and clears for another fight', () => {
  const source = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function renderCommitNotice(');
  const end = source.indexOf('\nfunction render(', start);
  const nodes = new Map();
  const document = {
    querySelector: selector => ({
      insertAdjacentElement: (position, panel) => {
        assert.equal(selector, '.tt-left');
        assert.equal(position, 'afterbegin');
        nodes.set(panel.id, panel);
      },
    }),
    getElementById: id => nodes.get(id),
    createElement: () => ({setAttribute() {}, remove() { nodes.delete(this.id); }}),
  };
  const renderNotice = new Function('document', source.slice(start, end) + '\nreturn renderCommitNotice;')(document);
  const diagnostic = {notice: '<plain warning>', persistence_notice: 'The action was saved.',
    preview_id: 'hidden-id', preview_post_state_sha256: 'hidden-hash'};
  renderNotice({divergence_diagnostic: diagnostic});
  assert.equal(nodes.get('ttCommitNotice').textContent, '<plain warning> The action was saved.');
  renderNotice({divergence_diagnostic: diagnostic});
  assert.equal(nodes.size, 1);
  renderNotice({});
  assert.equal(nodes.size, 0);
  const renderBody = source.slice(end, source.indexOf('\nfunction ', end + 1));
  assert.match(renderBody, /renderCommitNotice\(state\)/);
});

const notice = {notice: 'The real result was saved.'};
const feed = {events: [], last_sequence: 0};
const snapshot = (controller = 'MANUAL', menu = null) => ({menu, last_sequence: 0,
  presentation: {match_id: 'm', current_actor_id: 'fighter', round_number: 1, teams: [],
    battlefield: {display_name: 'Arena', width_squares: 4, height_squares: 4},
    actors: [{entity_id: 'fighter', display_name: 'Fighter', controller, active: true,
      primary_combatant: true, position: {x: 0, y: 0}, hit_points: {current: 10, maximum: 10}}]},
});

async function page(t, {gm = false, state}) {
  const values = new Map();
  const storage = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
  const viewId = 'notice-test';
  const store = createViewerStore({viewId, storage});
  for (const id of ['m', 'next']) {
    if (gm) store.bindGM(id);
    else store.bindPlayer(id, ['fighter']);
  }
  const calls = [], h = {state, handler: null};
  const table = await openTablePage({viewId, storage, inspect: ['useGroup'], async request(path, options) {
    const url = new URL(path, 'http://localhost');
    const call = {url, body: options.body ? JSON.parse(options.body) : null};
    calls.push(call);
    const override = h.handler?.(call);
    if (override !== undefined) return override;
    if (url.pathname.endsWith('/state')) return h.state;
    if (url.pathname.endsWith('/events')) return feed;
    if (url.pathname.endsWith('/seat-status')) return {seats: {}};
  }});
  t.after(table.checkRequests);
  assert.equal(await table.loadMatch('m'), true);
  return Object.assign(h, table, {calls, savedFog: () => createViewerStore({viewId, storage}).readFog('m'),
    panel: () => table.document.getElementById('ttCommitNotice')});
}

for (const method of ['act', 'autoStep']) {
  test(`${method} passes the retained notice from a committed response to rendering`, async t => {
    const manual = method === 'act';
    const menu = manual ? {decision_id: 'd', state_version: 1, actor_id: 'fighter',
      manual: true, moves: [], actions: [], end_turn: 'candidate'} : null;
    const controller = manual ? 'MANUAL' : 'LOCAL_AUTO';
    const h = await page(t, {gm: true, state: snapshot(controller, menu)});
    const committed = {...snapshot(controller), divergence_diagnostic: notice};
    h.calls.length = 0;
    h.handler = ({url}) => {
      if (url.pathname.endsWith('/prepare')) return {status: 'PREPARED'};
      if (url.pathname.endsWith('/act')) return {status: 'COMMITTED', state: committed, events: feed};
      if (url.pathname.endsWith('/automatic-run')) {
        // autoStep starts the server run; the committed notice arrives in
        // its final state read, not in the run's status receipt.
        h.state = committed;
        return {status: 'COMMITTED', running: false, seats: {}};
      }
    };
    assert.equal(h.panel(), null);
    assert.equal(await h[method]('candidate'), true);
    assert.equal(h.panel()?.textContent, notice.notice);
    if (manual) {
      assert.equal(h.calls.find(call => call.url.pathname.endsWith('/act'))?.body.candidate_id, 'candidate');
      assert.equal(h.calls.some(call => call.url.pathname.endsWith('/state')), false, 'render uses the commit response');
    } else {
      const run = h.calls.findIndex(call => call.url.pathname.endsWith('/automatic-run'));
      const read = h.calls.findIndex(call => call.url.pathname.endsWith('/state'));
      assert.ok(run >= 0 && read > run, 'read the committed snapshot after starting the run');
    }
  });
}

test('human origin picker lists multiple origins and immediately submits a single origin', async t => {
  const menu = {decision_id: 'd', state_version: 1, actor_id: 'fighter', manual: true,
    moves: [], actions: [], end_turn: 'end'};
  const h = await page(t, {gm: true, state: snapshot('MANUAL', menu)});
  h.calls.length = 0;
  h.handler = ({url}) => {
    if (url.pathname.endsWith('/prepare')) return {status: 'PREPARED'};
    if (url.pathname.endsWith('/act')) return {status: 'COMMITTED', state: snapshot(), events: feed};
  };
  const group = {label: 'Choose origin', placement_picker: true, destination_choice: true,
    options: [{candidate_id: 'first', label: 'First'}, {candidate_id: 'second', label: 'Second'}]};
  const pending = h.useGroup(group);
  assert.equal(h.app.pendingChoice?.kind, 'list');
  const buttons = [...h.document.getElementById('ttHint').querySelectorAll('button')];
  assert.deepEqual(buttons.map(b => b.textContent).slice(0, 2), ['First', 'Second']);
  assert.equal(h.calls.some(call => call.url.pathname.endsWith('/act')), false);
  h.app.listPick.cancel();
  await pending;
  await h.useGroup({...group, options: [{candidate_id: 'only', label: 'Only'}]});
  assert.equal(h.calls.find(call => call.url.pathname.endsWith('/act'))?.body.candidate_id, 'only');
});

test('refresh drops an older response after the local fog view changes', async () => {
  const source = readFileSync(new URL('./tabletop.js?v=rel6-2', import.meta.url), 'utf8');
  const memoryStart = source.indexOf('function tokenIdsKey(');
  const refreshStart = source.indexOf('async function readTableState(');
  const refreshEnd = source.indexOf('\nasync function setControl(', refreshStart);
  const eventsStart = source.indexOf('async function eventsThroughState(');
  const eventsEnd = source.indexOf('\n}', eventsStart) + 2;
  assert.ok(eventsStart >= 0 && eventsEnd > eventsStart, 'find eventsThroughState');
  const selectorStart = source.indexOf('$("#ttFog").addEventListener("change"');
  const selectorEnd = source.indexOf('\n$("#ttViewerChange")', selectorStart);
  assert.ok(refreshStart >= 0 && refreshEnd > refreshStart, 'find readTableState and refresh');
  assert.ok(selectorStart >= 0 && selectorEnd > selectorStart, 'find the fog selector handler');

  const pending = [];
  const rendered = [];
  const localViews = [];
  const roster = [{entity_id: 'fighter', primary_combatant: true, controller: 'MANUAL', team_index: 0}];
  const viewerStore = createViewerStore({viewId: 'refresh-test'});
  viewerStore.bindPlayer('match-1', ['fighter']);
  viewerStore.writeFog('match-1', 'team');
  const app = {matchId: 'match-1', fog: 'team', lastSequence: 0,
    state: {presentation: {actors: roster}}, seatStatus: {seats: {}}};
  const api = path => {
    if (path.includes('/state?fog=')) {
      const fog = new URL(path, 'http://tabletop.local').searchParams.get('fog');
      assert.equal(fog, 'true', 'both views retain server perception for immediate local masking');
      return new Promise(resolve => pending.push(resolve));
    }
    if (path.includes('/events?')) return Promise.resolve({events: []});
    throw new Error(`Unexpected request: ${path}`);
  };
  const select = {addEventListener: (_event, handler) => { select.handler = handler; }};
  const bindings = {
    $: selector => selector === '#ttFog' ? select : null,
    app, api, enc: encodeURIComponent, sleep: async () => {}, playEvents: async () => {},
    render: state => rendered.push(state.setting), toast: message => { throw new Error(message); },
    viewerStore, DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView, compactStatePath,
    preferenceStorage: {getItem: () => null},
    currentViewer: () => resolveViewerIdentity(viewerStore.read(app.matchId), roster, app.seatStatus),
    resetViewerPresentation() {}, renderTokens: () => localViews.push(app.fog), renderInspector() {}, renderHighlights() {},
    selectGMView() { throw new Error('this fixture remains an explicitly bound player'); },
    openViewerPicker() { throw new Error('the valid saved binding must not be reprompted'); },
    // The picker also restates the chosen view's help text (fog_view.js); this test is about
    // the stale response, so the picker is not exercised here. tests/fog_view.test.mjs covers it.
    setFogPicker() {},
    // Model seats (seats.js) load beside the state; none in this fight.
    loadSeats: async () => {}, resumeServerPrompt() {},
    // refresh() hands an unavailable fight to handleUnavailableFight; this fixture's fight is available.
    handleUnavailableFight: async () => false,
    // refresh() builds its state path through the movement-grid import; the fixture uses the real helper.
    compactStatePath,
  };
  const harness = new Function(...Object.keys(bindings), [
    'let refreshSequence = 0;',
    source.slice(eventsStart, eventsEnd),
    source.slice(memoryStart, refreshStart),
    source.slice(refreshStart, refreshEnd),
    source.slice(selectorStart, selectorEnd),
    'return {refresh, select: event => $("#ttFog").handler(event)};',
  ].join('\n'))(...Object.values(bindings));

  const older = harness.refresh();
  await new Promise(setImmediate);
  await harness.select({target: {value: 'own'}});
  assert.deepEqual(localViews, ['own'], 'the picker changes the displayed perception immediately');
  assert.equal(viewerStore.readFog('match-1'), 'own');
  assert.equal(pending.length, 1, 'changing local perception does not refetch state');
  const newer = harness.refresh();
  await new Promise(setImmediate);
  assert.equal(pending.length, 2);

  pending[1]({setting: 'newer', last_sequence: 0});
  await newer;
  pending[0]({setting: 'older', last_sequence: 0});
  await older;
  assert.deepEqual(rendered, ['newer']);
});
