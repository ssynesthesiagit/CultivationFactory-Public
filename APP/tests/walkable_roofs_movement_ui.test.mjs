// Exercise the production action bar, selected routes, click, quote/commit,
// reaction loop and reload continuation. HTTP/DOM are fixtures, not a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';
import {bindPress} from '../static/tabletop/kept-bar.js?v=speedreuse2-3';
import {economySections, economyPills} from '../static/tabletop/action-economy.js';
import {heightControl, heightFeet, flightText, movesAtHeight, heightMovement,
  roofLevelsAt, movementVerb, routeText, movementControl, startHeightLevel, appendTip} from '../static/tabletop/flight-ui.js';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function declaration(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, `${name} is production code`);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function exportedDeclaration(name) {
  const start = source.search(new RegExp(`export function ${name}\\(`));
  assert.ok(start >= 0, `${name} is production code`);
  return source.slice(start, source.indexOf('\n}', start) + 2).replace(/^export /, '');
}
const p = (x, y = 3, z = 2) => ({x, y, z});
const events = sequence => ({events: [{event_sequence: sequence}], last_sequence: sequence});
const selectByLabel = (document, label) => document.querySelectorAll('select')
  .find(select => select.getAttribute('aria-label') === label) || null;

function harness({flying = true} = {}) {
  const document = installDOM('<body><div id="ttActionBar"></div></body>');
  const actor = {entity_id: 'a', display_name: 'Rooftop walker', position: p(3),
    altitude_ft: 10, fly_speed_ft: flying ? 30 : 0, on_roof: true, active: true};
  const edge = {candidate_id: 'native-edge', destination: p(1), path: [p(3), p(2), p(1)],
    movement_mode: flying ? 'fly' : 'jump_down', can_jump_down: true, cost_ft: 10};
  const walk = {candidate_id: 'native-roof', destination: p(4), path: [p(3), p(4)],
    movement_mode: 'walk', cost_ft: 5};
  const air = {candidate_id: 'native-air', destination: p(0), path: [...edge.path, p(0)],
    movement_mode: 'fly', cost_ft: 15};
  const menu = {actor_id: 'a', decision_id: 'd', state_version: 2, manual: true,
    moves: flying ? [walk, edge, air] : [walk, edge], actions: [],
    movement_explanation: {summary: {actor_id: 'a'}, destinations: {}}};
  const app = {menu, state: {menu}, matchId: 'm', lastSequence: 6, showMoves: true,
    busy: false, fog: 'own', selected: new Set()};
  const calls = [], played = [], messages = [], prompts = [], renders = [];
  const h = {app, actor, edge, walk, air, calls, played, messages, prompts, renders,
    ready: true, previewHook: null, commitHook: null, syncHook: null, refreshes: 0};
  const board = {map: {width: 10, height: 10, walls: [
    {shape: 'rect', points: [[2, 2], [7, 7]], blocks: 'movement', filled: false}],
    floors: [{style: 'wood', cells: [[3, 3], [4, 3]]}]},
    setHighlights: value => { h.highlights = value; },
    setMovementExplanation: value => { h.explanation = value; }};
  const bindings = {app, document, board, refreshSequence: 0, bindPress,
    $: selector => document.querySelector(selector), enc: value => value,
    currentViewer: () => ({ready: h.ready}),
    presentation: () => ({current_actor_id: 'a'}), actorById: () => actor,
    modelOwner: () => null, serverDriving: () => false,
    sheetFor: async () => ({buttons: []}), movementLeft: () => '30 ft',
    heightControl, heightFeet, flightText, movesAtHeight, heightMovement,
    roofLevelsAt, movementVerb, routeText, movementControl, startHeightLevel, appendTip,
    renderRankedMenu, economySections, economyPills, handleUnavailableFight: async () => false, invalidateTargeting() {}, isManualActor: () => true, automaticSlot: actor => actor && actor.active === false,
    renderTokens() {}, gmNotice() {}, hint() {},
    toast: message => messages.push(message),
    synchronizePresets: async () => h.syncHook?.(),
    refresh: async () => { h.refreshes++; },
    readTableState: async () => ({menu: null}),
    render: state => { renders.push(state); app.state = state; app.menu = state.menu; },
    askReaction: async prompt => { prompts.push(prompt); return 'DECLINE'; },
    playEvents: async (batch, options) => { played.push({batch, options}); app.lastSequence = batch.last_sequence; },
    api: async (url, options) => {
      const body = structuredClone(options?.body);
      calls.push({url, body});
      if (url.endsWith('/prepare')) return {status: 'PREPARED'};
      if (url.endsWith('/movement-path/preview')) {
        await h.previewHook?.(body);
        return {status: 'ROUTE_PREVIEW', candidate: {candidate_id: 'quoted-drop', path: body.waypoints,
          metadata: {movement_mode: body.movement_mode}}};
      }
      if (url.endsWith('/movement-path/commit') || url.endsWith('/act')) {
        return (await h.commitHook?.(body)) || {status: 'COMMITTED', events: events(8), state: {menu: null}};
      }
      throw new Error(`Unexpected request ${url}`);
    },
  };
  const names = ['renderActionBar', 'moveHeight', 'selectedMoves', 'renderHighlights', 'onCellClick',
    'moveTo', 'refuseCoveredView', 'withReactions', 'resumePendingAction', 'act', 'appendReactionAnswer',
    'draftOptionRows', 'useGroup', 'renderItemsPanel', 'renderShapePanel', 'buttonDetail', 'reasonFor', 'runButton',
    'actionRules', 'costTag', 'autoStep', 'setControl'];
  const controller = new Function(...Object.keys(bindings),
    ['let menuLoadingTimer = null;', 'let menuLoadingActor = null;', ...names.map(declaration), exportedDeclaration('appendActionBarRankedChoice')].join('\n')
      + `\nreturn {${names.join(',')}};`)(...Object.values(bindings));
  return Object.assign(h, controller, {document, async choose(mode) {
    await controller.renderActionBar();
    const select = selectByLabel(document, 'Movement mode');
    assert.ok(select, 'the production action bar exposes the movement selector');
    select.value = mode;
    await select.dispatch('change');
    await controller.renderActionBar();
    return select;
  }});
}

test('on-roof flyer keeps Move / Fly by default and uses its native candidate', async () => {
  const h = harness();
  await h.renderActionBar();
  const select = selectByLabel(h.document, 'Movement mode');
  assert.deepEqual(select.options.map(row => row.textContent), ['Move / Fly', 'Jump down']);
  assert.equal(select.value, 'native');
  assert.equal(h.selectedMoves().length, 3);
  assert.ok(selectByLabel(h.document, 'Fly to height'));
  await h.onCellClick(h.edge.destination);
  assert.equal(h.calls.length, 2);
  assert.ok(h.calls[0].url.endsWith('/prepare'));
  assert.ok(h.calls[1].url.endsWith('/act'));
  assert.equal(h.calls[1].body.candidate_id, 'native-edge');
});

test('flyer deliberately drops using only marked edge routes and the quoted candidate', async () => {
  const h = harness();
  await h.choose('jump_down');
  assert.deepEqual(h.highlights.moves, [h.edge.destination]);
  assert.equal(selectByLabel(h.document, 'Fly to height'), null,
    'the drop starts at the roof height rather than selecting a fabricated landing square');
  assert.match(h.explanation.destinations['1,3'].reasons[0].message, /Jump down from height 10 ft/);
  assert.equal(h.selectedMoves()[0].candidate_id, h.edge.candidate_id, 'no duplicate native identity');
  assert.equal(h.edge.movement_mode, 'fly', 'the server menu remains unchanged');
  await h.onCellClick(h.walk.destination);
  await h.onCellClick(h.air.destination);
  assert.deepEqual(h.calls, [], 'unmarked destinations cannot be submitted in Jump down mode');
  assert.equal(await h.onCellClick(h.edge.destination), true);
  const [preview, commit] = h.calls;
  assert.ok(preview.url.endsWith('/movement-path/preview'));
  assert.deepEqual(preview.body, {decision_id: 'd', state_version: 2, actor_id: 'a',
    waypoints: h.edge.path, movement_mode: 'jump_down'});
  assert.ok(commit.url.endsWith('/movement-path/commit'));
  assert.deepEqual(commit.body, {...preview.body, candidate_id: 'quoted-drop', after: 6, reactions: []});
  assert.equal(h.app.busy, false);
  assert.equal(h.app.pendingMove, null);
  assert.equal(h.document.body.classList.contains('is-working'), false);
  assert.equal(h.played[0].options.finalizePause, true);
  assert.equal(h.renders.length, 1);
});

test('non-flyer can choose Jump down and a new decision restores ordinary Move', async () => {
  const h = harness({flying: false});
  const select = await h.choose('jump_down');
  assert.deepEqual(select.options.map(row => row.textContent), ['Move', 'Jump down']);
  assert.equal(h.selectedMoves()[0].movement_mode, 'jump_down');
  h.app.menu = {...h.app.menu, decision_id: 'next'};
  h.moveHeight();
  assert.equal(h.app.moveMode, 'native');
  assert.equal(h.selectedMoves().length, 2);
});

test('quote holds the busy gate and a covered or stale response cannot commit a drop', async () => {
  for (const change of ['covered', 'stale']) {
    const h = harness();
    await h.choose('jump_down');
    h.previewHook = async () => {
      assert.equal(h.app.busy, true);
      assert.equal(await h.moveTo(h.edge), false, 'a second click cannot start another quote');
      if (change === 'covered') h.ready = false;
      else h.app.state = {menu: {...h.app.menu, decision_id: 'new-decision'}};
    };
    assert.equal(await h.onCellClick(h.edge.destination), false);
    assert.equal(h.calls.length, 1, 'the read-only preview is the only request');
    assert.match(h.messages.at(-1), change === 'covered' ? /covered/ : /fight changed/i);
    assert.equal(h.app.busy, false);
    assert.equal(h.app.pendingMove, null);
    assert.equal(h.document.body.classList.contains('is-working'), false);
  }
});

test('settings synchronization cannot silently replace the chosen edge path', async () => {
  const h = harness();
  await h.choose('jump_down');
  h.syncHook = () => {
    const next = {...h.app.menu, state_version: 3, moves: [{...h.edge, candidate_id: 'replacement',
      path: [p(3), p(2, 4), p(1)]}]};
    h.app.state = {menu: next}; h.app.menu = next;
  };
  assert.equal(await h.onCellClick(h.edge.destination), false);
  assert.deepEqual(h.calls, []);
  assert.match(h.messages.at(-1), /Choose where to move again/);
});

test('drop reactions reuse the quoted binding and reload resumes its exact path', async () => {
  const h = harness();
  await h.choose('jump_down');
  let commits = 0;
  const reaction = {context: {reaction_id: 'edge-oa'}, label: 'Opportunity attack'};
  h.commitHook = async () => ++commits === 1
    ? {status: 'REACTION_REQUIRED', reaction, events: events(7)} : null;
  assert.equal(await h.onCellClick(h.edge.destination), true);
  assert.equal(h.calls.filter(row => row.url.endsWith('/preview')).length, 1);
  const [first, second] = h.calls.filter(row => row.url.endsWith('/commit'));
  assert.deepEqual(second.body, {...first.body, after: 7,
    reactions: [{reaction_id: 'edge-oa', selection: 'DECLINE'}]});
  assert.deepEqual(h.prompts, [reaction]);
  const reload = harness();
  const pending = {method: 'act', request: {candidate_id: 'quoted-drop', actor_id: 'a',
    decision_id: 'd', state_version: 2, after: 0, movement_path: reload.edge.path,
    movement_mode: 'jump_down'}, reaction, reactions: []};
  const before = structuredClone(pending);
  await reload.resumePendingAction(pending);
  assert.equal(reload.calls.length, 1);
  assert.ok(reload.calls[0].url.endsWith('/movement-path/commit'));
  assert.deepEqual(reload.calls[0].body, {candidate_id: 'quoted-drop', actor_id: 'a',
    decision_id: 'd', state_version: 2, after: 6, waypoints: reload.edge.path,
    movement_mode: 'jump_down', reactions: [{reaction_id: 'edge-oa', selection: 'DECLINE'}]});
  assert.deepEqual(pending, before, 'the saved binding is not mutated while translating API fields');
  assert.equal(reload.app.busy, false);
});
