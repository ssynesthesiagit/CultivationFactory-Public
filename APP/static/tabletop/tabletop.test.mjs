// node --test APP/static/tabletop/tabletop.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView} from './fog_view.js';
import {createViewerStore, resolveViewerIdentity} from './viewer-identity.js';
import {compactStatePath} from './movement-grid.js';

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

for (const method of ['act', 'autoStep']) {
  test(`${method} passes the retained notice from a committed response to rendering`, async () => {
    const source = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');
    const start = source.indexOf(`async function ${method}(`);
    const end = source.indexOf('\n}', start) + 2;
    // act() refuses a submission while the view is covered; the real guard is included here.
    const guardStart = source.indexOf('function refuseCoveredView(');
    const guardEnd = source.indexOf('\n}', guardStart) + 2;
    assert.ok(guardStart >= 0 && guardEnd > guardStart, 'production refuseCoveredView');
    // act() clears a stale targeting state after a commit; with no targeting open it returns at once.
    const targetStart = source.indexOf('function invalidateTargeting(');
    const targetEnd = source.indexOf('\n}', targetStart) + 2;
    assert.ok(targetStart >= 0 && targetEnd > targetStart, 'production invalidateTargeting');
    const notice = {notice: 'The real result was saved.'};
    const state = {menu: {decision_id: 'd', state_version: 1}, divergence_diagnostic: notice};
    const rendered = [];
    const app = {state, matchId: 'm', fog: 'off', lastSequence: 0};
    const bindings = {app, document: {body: {classList: {add() {}, remove() {}}}},
      synchronizePresets: async () => {}, hint() {}, handleUnavailableFight: async () => false, invalidateTargeting() {},
      // The player's view is available, so the covered-view guard stands aside.
      currentViewer: () => ({ready: true}),
      withReactions: callback => callback([]), api: async () => ({status: 'COMMITTED', state, events: {events: []}}),
      readTableState: async (matchId, fog) => {
        assert.equal(matchId, 'm');
        assert.equal(fog, 'off');
        return state;
      },
      enc: encodeURIComponent, playEvents: async () => {}, render: row => rendered.push(row), gmNotice() {},
      toast: message => { throw Error(message); }, refresh: async () => {}, renderActionBar() {}, invalidateTargeting() {},
      handleUnavailableFight: async error => { throw error; },
      // No model seat in this fight (seats.js): autoStep runs as before.
      modelTurnNow: () => false};
    const action = new Function(...Object.keys(bindings), 'let refreshSequence = 0;\n'
      + source.slice(guardStart, guardEnd) + '\n' + source.slice(targetStart, targetEnd) + '\n' + source.slice(start, end)
      + `\nreturn ${method};`)(...Object.values(bindings));
    assert.equal(await action('candidate'), true);
    assert.equal(rendered[0].divergence_diagnostic, notice);
  });
}

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
