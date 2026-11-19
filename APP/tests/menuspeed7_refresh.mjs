// Real native quote -> real phone controller and desktop refresh projection.
// Offline DOM assertions only; no GUI, server, embedding or model requests.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Element, installDOM} from './objects_dom_stub.mjs';
import {createPlay} from '../static/play/play-client.js';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {emptyMemory} from '../static/tabletop/fog_memory.js';
import {expandMovementGrid} from '../static/tabletop/movement-grid.js';
import {checkMove, retainMenuInspection} from '../static/tabletop/assisted-menu.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';

const {state, quote} = JSON.parse(readFileSync(0, 'utf8'));
const clone = x => structuredClone(x);
const text = n => [n.textContent, ...(n.children || []).map(text)].join(' ');
const find = (n, label) => n.querySelectorAll('button').find(b => text(b).includes(label));
const commits = h => h.calls.filter(c => c.path.endsWith('/movement-path/commit'));
const previews = h => h.calls.filter(c => c.path.endsWith('/movement-destination/preview'));
const owner = state.menu.actor_id, mid = state.presentation.match_id;
const target = expandMovementGrid(state.menu).moves.find(m =>
  m.destination.x === 4 && m.destination.y === 6 && !m.destination.z && m.movement_mode === 'walk');
assert.ok(target, 'Use a real offered native hazard destination');

function snapshot(mode = 'SUGGESTED') {
  const s = clone(state);
  // Keep two genuinely offered rows so local IDs can be reordered on refresh.
  const alternative = expandMovementGrid(state.menu).moves.find(m =>
    m.destination.x !== 4 && m.movement_mode === 'walk' && !m.can_jump_down);
  assert.ok(alternative);
  s.menu.movement_grid = [target, alternative].map(m => [m.destination.x, m.destination.y,
    m.destination.z || 0, m.cost_ft, m.movement_mode, false]);
  s.menu.moves = [];
  s.menu.actions = [];
  Object.assign(s.menu, {control_mode: mode, turn_mode: mode === 'SUGGESTED' ? 'Assisted' : 'Manual',
    ranked_slots: {Movement: ['movement:compact']}});
  s.presentation.actors.find(a => a.entity_id === owner).controller = mode;
  return s;
}

function phone(initial, reply = clone(quote)) {
  const doc = installDOM(readFileSync(new URL('../static/play/play.html', import.meta.url), 'utf8'));
  doc.createTextNode = s => Object.assign(new Element('span'), {textContent: s, nodeType: 3});
  const viewerStore = createViewerStore({viewId: 'menuspeed7f4'});
  viewerStore.bindPlayer(mid, [owner]);
  let current = clone(initial);
  const calls = [];
  const request = async (path, options = {}) => {
    calls.push({path, ...options});
    if (path.includes('/state?')) return clone(current);
    if (path.endsWith('/seat-status')) return {seats: {}};
    if (path.includes('/events?')) return {events: [], last_sequence: current.last_sequence};
    if (path.endsWith('/sheet')) return {buttons: [], library: {groups: []}};
    if (path.endsWith('/movement-destination/preview')) return typeof reply === 'function' ? reply() : clone(reply);
    if (path.endsWith('/movement-path/commit')) return {status: 'COMMITTED'};
    throw Error(`Unexpected offline request ${path}`);
  };
  const board = {element: new Element(), map: {width: 30, height: 30}, view: {x: 0, y: 0, zoom: 1},
    terrainAt: () => [], zonesAt: () => [], floorRecordAt: () => null, sceneryRecordAt: () => null,
    objectArtRecordAt: () => null, fit() {}, zoomBy() {}, centerOn() {}, closeHoverCard() {}};
  for (const key of ['setMap', 'setRoofView', 'setZones', 'setTokens', 'setFog', 'setRemembered', 'setHighlights'])
    board[key] = (...args) => {if (key === 'setMap') board.map = args[0];};
  const client = createPlay({doc, request, board, viewerStore, frame: () => {},
    memoryStore: {read: () => emptyMemory(), ready: () => false, save() {}},
    controlStore: {read: () => initial.menu.control_mode, write() {}}});
  return {client, doc, calls, setState: s => {current = clone(s);}, host: () => doc.getElementById('actionList')};
}

function assertDisclosure(host, hazard = true) {
  assert.match(text(host), /Route: square/);
  assert.match(text(host), new RegExp(`${quote.candidate.movement_cost_ft} ft of movement`));
  assert.equal(text(host).includes('Warning: this route crosses a known hazard'), hazard);
  assert.ok(!text(host).includes('Hidden spy'));
}

if (process.argv[2] === 'chooser') {
  for (const mode of ['MANUAL', 'SUGGESTED']) for (const entry of ['list', 'map']) for (const hazard of [true, false]) {
    const reply = clone(quote);
    reply.candidate.metadata.hazard_exposure = hazard;
    reply.candidate.metadata.expected_opportunity_attacks = [{display_name: 'Hidden spy'}];
    const h = phone(snapshot(mode), reply);
    await h.client.load(mid);
    const stateRequest = h.calls.find(call => call.path.includes('/state?'));
    assert.ok(stateRequest, 'phone must fetch table state');
    assert.equal(new URL(stateRequest.path, 'http://test').searchParams.get('compact'), 'true',
      'phone opts into compact/lazy state instead of enumerating eagerly');
    if (mode === 'SUGGESTED') await find(h.host(), 'Change —').click();
    await find(h.host(), 'Move — tap').click();
    if (entry === 'list') await find(h.host(), 'Check route —').click();
    else await h.client.tap({x: 4, y: 6});
    assert.equal(previews(h).length, 1);
    assert.equal(commits(h).length, 0, 'Manual/Change inspection must never commit');
    assertDisclosure(h.host(), hazard);
    assert.ok(find(h.host(), 'Confirm move —'));
    await h.client.refresh();
    assertDisclosure(h.host(), hazard);
    await find(h.host(), 'Confirm move —').click();
    assert.equal(previews(h).length, 1, 'An unchanged poll must not require another paid inspection');
    assert.equal(commits(h).length, 1);
    assert.equal(commits(h)[0].body.candidate_id, quote.candidate.candidate_id);
    assert.deepEqual(commits(h)[0].body.waypoints, quote.candidate.canonical_path);
  }
  console.log('Manual/Change list and map: native hazard/safe disclosure, poll, explicit confirmation PASS');
} else {
  assert.equal(process.argv[2], 'refresh');
  // Execute the actual desktop render entry through its state installation.
  // Later map painting is outside this controller regression; real ranked DOM
  // below proves what a refresh offers before a subsequent confirmation click.
  const desktop = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = desktop.indexOf('function render(state,');
  const end = desktop.indexOf('  app.state = state;', start) + '  app.state = state;'.length;
  assert.ok(start >= 0 && end > start);
  const desktopRefresh = new Function('app', 'expandMovementGrid', 'retainMenuInspection',
    `${desktop.slice(start, end)}\nreturn state;\n}\nreturn render;`);
  const changes = {
    unchanged() {},
    reordered(s) {s.menu.movement_grid.reverse();},
    match(s) {s.presentation.match_id += '-other';},
    decision(s) {s.menu.decision_id += '-other';},
    version(s) {s.menu.state_version++;},
    actor(s) {s.menu.actor_id = 'other';},
    control(s) {s.menu.control_mode = 'MANUAL';},
    turnMode(s) {s.menu.turn_mode = 'Manual';},
    automatic(s) {s.menu.manual = false;},
    pending(s) {s.pending_action = {method: 'act', reaction: {context: {reactor_id: 'other'}}};},
    terminal(s) {s.presentation.terminal = true;},
    destination(s) {s.menu.movement_grid[0][0]++;},
    mode(s) {s.menu.movement_grid[0][4] = 'fly';},
  };
  for (const [name, change] of Object.entries(changes)) {
    const same = ['unchanged', 'reordered'].includes(name);
    const initial = snapshot(), next = clone(initial);
    change(next);
    const h = phone(initial);
    await h.client.load(mid);
    await find(h.host(), 'Check route for this step').click();
    assert.equal(commits(h).length, 0);
    h.setState(next); await h.client.refresh();
    const retained = h.client.state.menu.moves.find(m => m.route_checked);
    assert.equal(!!retained, same, `phone ${name} boundary`);
    if (same) {
      // Reordering may change the top suggestion: choose the retained route
      // through Change so this tests semantic destination matching as well.
      if (name === 'reordered') {
        await find(h.host(), 'Change —').click(); await find(h.host(), 'Move — tap').click();
        assertDisclosure(h.host());
        await find(h.host(), 'Confirm move —').click();
      } else {assertDisclosure(h.host()); await find(h.host(), 'Confirm this step').click();}
      assert.equal(previews(h).length, 1);
      assert.equal(commits(h).length, 1);
      assert.equal(commits(h)[0].body.candidate_id, quote.candidate.candidate_id);
    } else assert.equal(commits(h).length, 0);

    const before = {...initial, menu: expandMovementGrid(clone(initial.menu))};
    await checkMove(before.menu, before.menu.moves[0], async () => clone(quote), () => true);
    const app = {state: before, menu: before.menu, matchId: mid};
    const refreshed = desktopRefresh(app, expandMovementGrid, retainMenuInspection)(clone(next));
    const checked = refreshed.menu.moves.find(m => m.route_checked);
    assert.equal(!!checked, same, `desktop ${name} boundary`);
    if (same) {
      const sent = [], inspected = [];
      const root = renderRankedMenu({...refreshed.menu, moves: [checked]}, {
        doc: {createElement: tag => new Element(tag)},
        onMove: m => sent.push(m), onPreviewMove: m => inspected.push(m)});
      const confirm = find(root, 'Confirm');
      assert.ok(confirm); assert.match(text(confirm), /Warning: this route crosses a known hazard/);
      await confirm.click();
      assert.equal(sent.length, 1); assert.equal(inspected.length, 0);
      assert.deepEqual(sent[0].path, quote.candidate.canonical_path);
    }
  }
  // A pending question clearing on the same decision must not resurrect a
  // quote from before it, nor may a late response cross a control-mode change.
  const beforePending = snapshot(); beforePending.pending_action = {method: 'act'};
  beforePending.menu = expandMovementGrid(beforePending.menu);
  await checkMove(beforePending.menu, beforePending.menu.moves[0], async () => clone(quote), () => true);
  const afterPending = snapshot(); afterPending.menu = expandMovementGrid(afterPending.menu);
  retainMenuInspection(beforePending, afterPending);
  assert.ok(!afterPending.menu.moves.some(m => m.route_checked));
  let release;
  const h = phone(snapshot(), () => new Promise(resolve => {release = resolve;}));
  await h.client.load(mid);
  const inspection = find(h.host(), 'Check route for this step').click();
  const next = snapshot('MANUAL'); h.setState(next); await h.client.refresh();
  release(clone(quote)); await inspection;
  assert.ok(!h.client.state.menu.moves.some(m => m.route_checked));
  assert.equal(commits(h).length, 0);
  // An unchanged poll may reorder the local handles while inspection is in
  // flight. Its reply must attach to the destination, without duplicating IDs.
  const racing = phone(snapshot(), () => new Promise(resolve => {release = resolve;}));
  await racing.client.load(mid);
  const checking = find(racing.host(), 'Check route for this step').click();
  const shuffled = snapshot(); shuffled.menu.movement_grid.reverse();
  racing.setState(shuffled); await racing.client.refresh();
  release(clone(quote)); await checking;
  const rows = racing.client.state.menu.moves;
  assert.equal(new Set(rows.map(m => m.candidate_id)).size, rows.length);
  assert.equal(rows.find(m => m.route_checked).candidate_id, 'route:1');
  await find(racing.host(), 'Change —').click(); await find(racing.host(), 'Move — tap').click();
  await find(racing.host(), 'Confirm move —').click();
  assert.equal(commits(racing)[0].body.candidate_id, quote.candidate.candidate_id);
  // Inspection must retain effective menu prices (e.g. dragging), rather than
  // replace them with the native quote's unmultiplied engine route cost.
  const priced = {...target, cost_ft: target.cost_ft * 2};
  await checkMove(state.menu, priced, async () => clone(quote), () => true);
  assert.equal(priced.cost_ft, target.cost_ft * 2);
  console.log('phone/desktop inspect -> unchanged/reordered refresh -> confirm; changed boundaries and stale replies PASS');
}
