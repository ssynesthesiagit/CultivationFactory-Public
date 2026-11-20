// node --experimental-vm-modules --test APP/static/tabletop/tabletop.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import {createViewerStore} from './viewer-identity.js';
import {openTablePage} from '../../tests/tabletop_page.mjs';

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
  const table = await openTablePage({viewId, storage, inspect: ['refresh'], async request(path, options) {
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

test('retained commit notice renders plain text and clears for another fight', async t => {
  const diagnostic = {notice: '<plain warning>', persistence_notice: 'The action was saved.',
    preview_id: 'hidden-id', preview_post_state_sha256: 'hidden-hash'};
  const h = await page(t, {gm: true, state: {...snapshot(), divergence_diagnostic: diagnostic}});
  assert.equal(h.panel()?.textContent, '<plain warning> The action was saved.');
  assert.equal(h.panel().children.length, 0, 'notice is plain text, not interpreted as markup');
  assert.equal(h.document.querySelector('.tt-left').firstChild, h.panel());
  await h.refresh();
  assert.equal(h.document.querySelectorAll('#ttCommitNotice').length, 1);
  h.state = snapshot();
  h.state.presentation.match_id = 'next';
  assert.equal(await h.loadMatch('next'), true);
  assert.equal(h.panel(), null);
});

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

test('refresh drops an older response after the local fog view changes', async t => {
  const h = await page(t, {state: snapshot()});
  const pending = [];
  const select = h.document.getElementById('ttFog');
  select.value = 'team';
  await select.dispatch('change');
  assert.equal(h.app.fog, 'team');
  const panel = h.document.getElementById('ttRound');
  const original = panel.textContent, paints = [];
  let heading = original;
  Object.defineProperty(panel, 'textContent', {
    get: () => heading,
    set: value => { heading = value; paints.push(value); },
  });
  h.handler = ({url}) => {
    if (!url.pathname.endsWith('/state')) return;
    assert.equal(url.searchParams.get('fog'), 'true', 'both views retain server perception for immediate masking');
    return new Promise(resolve => pending.push(resolve));
  };
  const older = h.refresh();
  await tick();
  assert.equal(pending.length, 1);
  select.value = 'own';
  await select.dispatch('change');
  assert.equal(h.app.fog, 'own', 'the picker changes displayed perception immediately');
  assert.equal(h.savedFog(), 'own');
  assert.equal(pending.length, 1, 'changing local perception does not refetch state');

  const newer = h.refresh();
  await tick();
  assert.equal(pending.length, 2);
  pending[1]({...snapshot(), presentation: {...h.state.presentation, round_number: 3}});
  await newer;
  pending[0]({...snapshot(), presentation: {...h.state.presentation, round_number: 2}});
  await older;
  assert.deepEqual(paints, ["Round 3 · Fighter's turn"]);
});
