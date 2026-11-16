// Production render, token selection and mini-sheet paths; no GUI or transport.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setTimeout as nativeTimeout, setInterval as nativeInterval} from 'node:timers';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard, initials} from '../static/tabletop/board.js';
import {modelOwner, controlOf} from '../static/tabletop/seats.js';
import {heightFeet, flightText} from '../static/tabletop/flight-ui.js';
import {fogViewers} from '../static/tabletop/fog_view.js';
import {renderInformation} from '../static/tabletop/information.js';
import {economyPills} from '../static/tabletop/action-economy.js';
import {retainMenuInspection} from '../static/tabletop/assisted-menu.js';

const source = readFileSync(process.env.CF_COMMITSPEED_TABLE_SOURCE ||
  new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function piece(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `production ${name}`);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}

function harness(fog = 'own') {
  const document = installDOM('<body><div id="ttViewport"></div><span id="ttMatchName"></span>'
    + '<span id="ttRound"></span><section id="ttInformation"></section><section id="ttInspector"></section></body>');
  // The existing DOM stub exposes children; the production information panel
  // also uses these standard DOM fields when rendering private text.
  const information = document.getElementById('ttInformation');
  information.ownerDocument = document;
  Object.defineProperty(information, 'childNodes', {get: () => information.children});
  // The DOM stub disables browser timers; Node's test runner still needs its own.
  Object.assign(globalThis, {setTimeout: nativeTimeout, setInterval: nativeInterval});
  const board = createBoard(document.getElementById('ttViewport'));
  const app = {matchId: 'm', selected: new Set(), fog, lastSequence: 0, seatStatus: {seats: {}}, busy: false};
  const roster = ['a', 'b', 'c'].map((id, index) => ({entity_id: id, display_name: `Fighter ${id.toUpperCase()}`,
    controller: 'MANUAL', active: true, position: {x: index + 1, y: 1}, conditions: [],
    hit_points: {current: 10 + index, maximum: 20}, speed_ft: 30, movement_remaining_ft: 30}));
  const viewer = {status: 'player', ready: true, actor_ids: roster.map(actor => actor.entity_id)};
  const map = {width: 8, height: 6, walls: [], objects: [], trees: [], decor: [], background: {},
    cells: {blocked: [], sight: []}, centerlineCells: [], floors: []};
  const noop = () => {};
  const bindings = {app, board, document, heightFeet, flightText, initials, modelOwner, controlOf, renderInformation,
    retainMenuInspection,
    $: selector => document.querySelector(selector),
    presentation: () => app.state?.presentation, actors: () => app.state?.presentation.actors || [],
    actorById: id => app.state?.presentation.actors.find(a => a.entity_id === id),
    mapFromState: () => map, wallSightCells: () => [], opacityGrid: () => null,
    isGMView: () => false, isOwnedActor: actor => viewer.actor_ids.includes(actor.entity_id), isManualActor: () => true,
    currentViewer: () => viewer,
    reconcileViewerIdentity: noop, resumeViewerDialogs: noop, renderCommitNotice: noop, invalidateTargeting: noop,
    renderZones: noop, renderInitiative: noop, renderRoster: noop, renderActionBar: noop,
    renderItemsPanel: noop, renderShapePanel: noop, scheduleAutoPlay: noop, renderHighlights: noop,
    broadcastActors: noop, renderPip: noop, scheduleSeatPoll: noop, requestDeferredMenu: noop,
    tokenLabels: () => new Map(), visibility: () => null, teamIndex: () => 0,
    tokenGeometry: () => ({width: 1, height: 1, scale: 1, offsetX: 0, offsetY: 0}),
    unseenByViewers: () => false, tokenSensePresentation: () => ({}), tokenImage: () => null,
    tableObjectTokens: () => [], roofAudience: () => [], fogGeometry: () => ({}), rememberFog: () => null,
    fogAudience: () => fogViewers(app.fog, roster, {owned: roster, selected: app.selected}),
    shownCondition: () => false, projectOf: () => null, concentrationCard: () => '', movementLeft: () => '',
    hoverCard: {isOpen: false}, TianxiaSheetViewModel: {armorBreakdown: () => '', armorCard: () => ({})},
    renderTipCard: noop, openSeatLog: noop, playedByWord: () => 'You',
    economyPills,
    TEAM_COLORS: ['red'], TEAM_HEX: ['red'],
  };
  const ui = Function(...Object.keys(bindings),
    ['escapeHtml', 'pct', 'render', 'reconcileOptionDraft', 'renderTokens', 'renderInspector', 'selectActor', 'onTokenClick']
      .map(piece).join('\n') + '\nreturn {render, selectActor, onTokenClick};')(...Object.values(bindings));
  const state = (actor, pending = false, manual = true, version = 1) => ({last_sequence: version,
    presentation: {match_id: 'm', display_name: 'Selection test', round_number: 1,
      current_actor_id: actor, actors: roster, zones: [], battlefield: {blocked_cells: []}},
    menu: pending ? null : {actor_id: actor, manual, state_version: version},
    ...(pending ? {menu_pending: {actor_id: actor, state_version: version}} : {})});
  function selected(id) {
    assert.deepEqual([...app.selected], [id]);
    for (const actor of roster) assert.equal(board.tokenNode(actor.entity_id).classList.contains('is-selected'),
      actor.entity_id === id, `token ${actor.entity_id}`);
    assert.equal(document.querySelector('#ttInspector h2').textContent, `Fighter ${id.toUpperCase()}`);
    assert.match(document.querySelector('#ttInspector').innerHTML, new RegExp(`HP ${roster.find(a => a.entity_id === id).hit_points.current} / 20`));
  }
  ui.render(state('a'));
  return {app, ui, state, selected, board, viewer, information};
}

test('private findings stay with the bound observer through deferred menu handoffs', () => {
  const h = harness();
  h.viewer.actor_ids = ['a'];
  const findings = {
    a: {information_text: ['Bloodsense: Fighter B is injured.']},
    b: {information_text: ['Bloodsense: blood was spilled within the last hour.']},
  };
  const state = pending => ({...h.state('b', pending, true, 2), observer_information: findings});
  const lines = () => h.information.childNodes.filter(node => node.tagName === 'P').map(node => node.textContent);
  h.ui.render(state(true));
  assert.deepEqual(lines(), findings.a.information_text);
  h.ui.selectActor('b');
  assert.deepEqual(lines(), findings.a.information_text);
  h.ui.render(state(false));
  assert.deepEqual(lines(), findings.a.information_text);
  h.viewer.actor_ids = ['c'];
  h.ui.render(state(false));
  assert.deepEqual(lines(), []);
  assert.equal(h.information.hidden, true);
});

test('deferred human handoff selects the new fighter and its mini sheet once ready', () => {
  const h = harness();
  h.selected('a');
  h.ui.render(h.state('b', true, true, 2));
  h.selected('a');
  h.ui.render(h.state('b', true, true, 2)); // polling must retain the handoff
  h.ui.render(h.state('b', false, true, 2));
  h.selected('b');
  h.ui.selectActor('c');
  h.ui.render(h.state('b', false, true, 2)); // consumed; same-turn refresh preserves clicks
  h.selected('c');
});

for (const click of ['selectActor', 'onTokenClick', 'sameToken', 'shiftClick', 'shiftToggle']) {
  test(`a deliberate ${click} while loading owns the selection`, () => {
    const h = harness();
    h.ui.render(h.state('b', true, true, 2));
    if (click === 'selectActor') h.ui.selectActor('c');
    else h.ui.onTokenClick(['sameToken', 'shiftToggle'].includes(click) ? 'a' : 'c',
      {shiftKey: ['shiftClick', 'shiftToggle'].includes(click)});
    const expected = [...h.app.selected];
    h.ui.render(h.state('b', true, true, 2));
    h.ui.render(h.state('b', false, true, 2));
    assert.deepEqual([...h.app.selected], expected);
    if (click === 'shiftToggle') assert.equal(h.board.tokenNode('a').classList.contains('is-selected'), false);
    else if (click !== 'shiftClick') h.selected(expected[0]);
    else {
      assert.equal(h.board.tokenNode('a').classList.contains('is-selected'), true);
      assert.equal(h.board.tokenNode('c').classList.contains('is-selected'), true);
    }
  });
}

test('chosen-token perception never follows automatic handoffs', () => {
  const h = harness('selected');
  h.ui.selectActor('a');
  h.ui.render(h.state('b', true, true, 2));
  h.ui.render(h.state('b', false, true, 2));
  h.selected('a');
});

test('switching to chosen-token perception while loading preserves the chosen token', () => {
  const h = harness();
  h.ui.render(h.state('b', true, true, 2));
  h.app.fog = 'selected';
  h.ui.render(h.state('b', false, true, 2));
  h.selected('a');
  h.app.fog = 'own';
  h.ui.render(h.state('b', false, true, 2));
  h.selected('a');
});

test('a newer turn supersedes the pending handoff and AI readiness does not select it', () => {
  const h = harness();
  h.ui.render(h.state('b', true, true, 2));
  h.ui.render(h.state('c', false, false, 3));
  h.selected('a');
  h.ui.render(h.state('c', true, true, 4)); // menu delay during the same turn is not a handoff
  h.ui.render(h.state('c', false, true, 4));
  h.selected('a');
});

test('a deferred AI menu clears the handoff without selecting the AI fighter', () => {
  const h = harness();
  h.ui.render(h.state('b', true, false, 2));
  h.ui.render(h.state('b', false, false, 2));
  h.selected('a');
  h.ui.render(h.state('b', false, true, 3));
  h.selected('a');
});

test('a model-owned human menu does not take over the selected mini sheet', () => {
  const h = harness();
  h.app.seatStatus.seats.b = {control: 'MODEL'};
  h.ui.render(h.state('b', true, true, 2));
  h.ui.render(h.state('b', false, true, 2));
  h.selected('a');
  assert.equal(h.app.pendingTurnSelection, null);
});

test('a newer deferred human turn replaces the earlier pending selection', () => {
  const h = harness();
  h.ui.render(h.state('b', true, true, 2));
  h.ui.render(h.state('c', true, true, 3));
  h.selected('a');
  h.ui.render(h.state('c', false, true, 3));
  h.selected('c');
});

test('immediately ready handoffs and initially empty selections retain their behavior', () => {
  const h = harness();
  h.ui.render(h.state('b', false, true, 2));
  h.selected('b');
  h.app.selected.clear();
  h.ui.render(h.state('c', true, true, 3));
  h.selected('c');
  h.ui.render(h.state('c', false, true, 3));
  h.selected('c');
});
