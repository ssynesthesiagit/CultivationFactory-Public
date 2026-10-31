// SOL156: real table playback/rendering and real board nodes, without a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard, CELL} from '../static/tabletop/board.js';
import {modelOwner} from '../static/tabletop/seats.js';
import {resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';
import {heightFeet, flightText} from '../static/tabletop/flight-ui.js';

const source = readFileSync(process.env.SOL156_TABLE_SOURCE || new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const slice = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const timer = globalThis.setTimeout;
const point = (x, y = 1) => ({x, y});
// Journal feed shape from tabletop_service.events()/format_history_feed: one
// sequence per event, recorded route and destination in raw.payload.
const movement = (sequence, path, extra = {}) => ({event_sequence: sequence, event_type: 'MOVEMENT_COMMITTED',
  actor_id: 'a', raw: {payload: {path, destination: path.at(-1), ...extra}}});
const batch = (...events) => ({events, dice: [], last_sequence: events.at(-1)?.event_sequence || 0});

function harness() {
  const document = installDOM('<body><div id="ttViewport"></div><span id="ttMatchName"></span><span id="ttRound"></span></body>');
  globalThis.setTimeout = (fn, ms) => timer(fn, Math.min(ms, 5));
  globalThis.requestAnimationFrame = fn => timer(fn, 0);
  const board = createBoard(document.getElementById('ttViewport'));
  const map = {width: 20, height: 14, walls: [], trees: [], background: {style: 'plain'}, cells: {blocked: [], sight: []}, floors: []};
  board.setMap(map);
  const state = (sequence = 0, position = point(1)) => ({last_sequence: sequence, menu: {manual: true, decision_id: 'd', state_version: sequence},
    presentation: {match_id: 'm', current_actor_id: 'a', battlefield: {blocked_cells: []}, actors: [{entity_id: 'a', position, display_name: 'Ana',
      hit_points: {current: 10, maximum: 10}, conditions: [], active: true}]}});
  const app = {matchId: 'm', state: state(), lastSequence: 0, selected: new Set(), fog: 'off', diceOn: false};
  let client;
  const noop = () => {};
  // Movement tests deliberately use an explicit GM view; the separate player
  // identity gate drives real fog, roof ownership and first-frame masking.
  const gmView = resolveViewerIdentity({version:1,role:'gm',actor_ids:[]},[],{seats:{}});
  const bindings = {
    app, board, document, refreshSequence: 0, enc: v => v,
    $: s => document.querySelector(s), renderCommitNotice: noop, invalidateTargeting: noop,
    actorById: id => app.state.presentation.actors.find(a => a.entity_id === id),
    actors: () => app.state.presentation.actors, presentation: () => app.state.presentation,
    tokenLabels: () => new Map(), visibility: () => null, TEAM_HEX: ['red'],
    tokenGeometry: () => ({width: 1, height: 1, scale: 1, offsetX: 0, offsetY: 0}),
    unseenByViewers: () => false, teamIndex: () => 0, isManualActor: () => true,
    currentViewer:()=>gmView, isGMView:()=>true, isOwnedActor:()=>false,
    reconcileViewerIdentity:()=>false, resumeViewerDialogs:noop, roofAudience:()=>[],
    shownCondition: () => false, tokenImage: () => null, actorLight: () => null, tableObjectTokens: () => [], fogGeometry: () => ({}), rememberFog: () => null, tokenSensePresentation: () => ({}), fogAudience: () => [],
    mapFromState: () => map, wallSightCells: () => [], opacityGrid: () => null,
    renderZones: noop, renderInitiative: noop, renderRoster: noop, renderInspector: noop, renderActionBar: noop,
    renderItemsPanel: noop, renderShapePanel: noop, scheduleAutoPlay: noop, renderHighlights: noop,
    broadcastActors: noop, renderPip: noop, appendFeed: noop, gmNotice: noop, toast: noop,
    cleanRules: value => value || '', closeChoice: noop, hint: noop,
    synchronizePresets: async () => {},
    // Shared table seams this playback harness does not exercise: no remembered fog
    // squares, draft reconciliation, or unavailable-fight recovery in these slices.
    rememberedTokenIds: () => null, reconcileOptionDraft: noop,
    handleUnavailableFight: async () => false, closeLoadedFight: noop,
    modelOwner, heightFeet, flightText, loadSeats: async () => {}, resumeServerPrompt: noop, scheduleSeatPoll: noop,
    renderObservedState: state => client.render(state),
    // Saved-format recovery is not part of playback; a load error here is never COMBAT_SAVED_FIGHT_UNSUPPORTED.
    handleUnavailableFight: async () => false,
    mapPickCells: choice => ({cells: choice.options.map(o => o.cell), options: new Map()}),
    readTableState: async () => { app.onStateRead?.(); return app.nextState || app.nextResponse?.state; }, api: async url => app.api ? app.api(url) : app.nextResponse,
    askReaction: async prompt => {
      app.prompts.push(prompt);
      if (prompt.choice?.space_map) {
        const answer = client.mapPickChoice(prompt);
        client.renderTokens(); app.mapPick.close('DECLINE');
        return answer;
      }
      client.renderTokens(); return 'pass';
    },
  };
  const code = [slice('function modelTurnNow()', '// While the server advances'),
    slice('function reconcileOptionDraft(', 'function render(state'),
    slice('function render(state', '// The creatures whose perception'),
    slice('function renderTokens()', '// A creature\'s token art'),
    slice(source.match(/(?:async )?function playEvents\(/)[0], '// ------------------------------------------------------------------ sheets'),
    slice('function setMapPick(pick)', '// What the prompt has to say'),
    slice('function appendReactionAnswer(', 'async function askReaction('),
    'const MAP_PICK_BODY_CLASS = "is-map-pick";',
    slice('function mapPickContext(prompt)', '// A fresh board selection'),
    slice(source.includes('async function eventsThroughState(') ? 'async function eventsThroughState(' : 'async function refresh()', 'async function setControl('),
    slice('function appendReactionAnswer(', 'async function askReaction('),
    slice('async function withReactions(', '// The Items panel over the action bar'),
    slice('function refuseCoveredView(', '// Act on one candidate that needs no further choice'),
    slice('async function act(', '// An ability the fight runs nothing for'),
    slice('async function autoStep()', 'async function play()'),
    'return {render, renderTokens, playEvents, refresh, withReactions, resumePendingAction, act, autoStep, setMapPick, mapPickChoice};'].join('\n');
  client = new Function(...Object.keys(bindings), code)(...Object.values(bindings));
  client.renderTokens();
  const node = document.querySelector('.tt-token');
  const drawn = [];
  let transform = node.style.transform;
  Object.defineProperty(node.style, 'transform', {get: () => transform, set: value => {
    if (value === transform) return; // repeated identical styles cannot move a token
    transform = value;
    const [x, y] = value.match(/-?\d+(?:\.\d+)?/g).map(Number);
    drawn.push({x: x / CELL, y: y / CELL});
  }});
  return {...client, app, board, node, drawn, state};
}

test('waypoint move survives hover/selection redraws before committed state arrives', async () => {
  const h = harness(), path = [point(1), point(2), point(2, 2), point(3, 2)];
  await h.playEvents(batch(movement(1, path)));
  h.renderTokens(); // app.state still contains the start: the original rubber band
  h.renderTokens();
  h.render(h.state(1, path.at(-1)));
  assert.deepEqual(h.drawn, path.slice(1));
  assert.equal(h.app.movePositions.size, 0);
});

test('own act with fog redraws safely while waiting for its post-animation state read', async () => {
  const h = harness(), path = [point(1), point(2), point(3)];
  h.app.fog = 'own';
  h.app.nextState = h.state(1, point(3));
  h.app.nextResponse = {status: 'COMMITTED', state: h.app.nextState, events: batch(movement(1, path))};
  h.app.onStateRead = () => h.renderTokens();
  assert.equal(await h.act('move'), true);
  assert.deepEqual(h.drawn, path.slice(1));
});

test('overlapping refresh arriving mid-animation plays each sequence once and rejects stale snapshot', async () => {
  const h = harness(), path = [point(1), point(2), point(3), point(4)];
  const events = batch(movement(1, path));
  h.app.nextState = h.state(0); // state read just before the commit
  h.app.nextResponse = events;
  const playing = h.playEvents(events);
  await timerPromise(1);
  h.renderTokens();
  const refreshing = h.refresh();
  await Promise.all([playing, refreshing]);
  h.renderTokens();
  assert.deepEqual(h.drawn, path.slice(1));
  assert.equal(h.app.state.last_sequence, 0, 'older snapshot was not installed');
  h.render(h.state(1, point(4)));
  assert.deepEqual(h.drawn, path.slice(1));
});

test('a commit between refresh reads plays the missing tail before rendering, without losing later moves', async () => {
  const h = harness();
  const first = movement(1, [point(1), point(2)]), second = movement(2, [point(2), point(3)]);
  h.app.nextState = h.state(1, point(2));
  let reads = 0;
  h.app.api = async () => (++reads === 1 ? batch() : batch(first, second));
  await h.refresh();
  assert.equal(reads, 2, 'only a state ahead of the feed needs a tail read');
  assert.deepEqual(h.drawn, [point(2)]);
  assert.equal(h.app.lastSequence, 1, 'events newer than this snapshot remain unconsumed');
  await h.playEvents(batch(first, second)); h.renderTokens(); h.render(h.state(2, point(3)));
  assert.deepEqual(h.drawn, [point(2), point(3)]);
});

test('opportunity attack pause and continuation do not replay committed route steps', async () => {
  const h = harness();
  h.app.prompts = [];
  // Incremental journal responses may overlap. The pause response is displayed
  // before asking, then the continuation includes the already-seen prefix.
  const first = movement(1, [point(1), point(2)]);
  const last = movement(3, [point(2), point(2, 2), point(3, 2)]);
  let sends = 0;
  const result = await h.withReactions(async answers => {
    sends++;
    if (!answers.length) return {status: 'REACTION_REQUIRED', reaction: {reaction: 'Opportunity Attack'}, events: batch(first)};
    assert.deepEqual(h.drawn, [point(2)], 'token stays at the reaction pause');
    return {status: 'COMMITTED', events: batch(first,
      {event_sequence: 2, event_type: 'ATTACK_ROLLED', actor_id: 'foe', target_ids: ['a'], raw: {payload: {}}}, last)};
  });
  await h.playEvents(result.events);
  h.render(h.state(3, point(3, 2)));
  assert.equal(sends, 2);
  assert.equal(h.app.prompts.length, 1);
  assert.deepEqual(h.drawn, [point(2), point(2, 2), point(3, 2)]);
});

test('current atomic server pause waits for answers and then plays the full route once', async () => {
  const h = harness(); h.app.prompts = [];
  const events = batch(movement(1, [point(1), point(2), point(3)]));
  const result = await h.withReactions(async answers => answers.length
    ? {status: 'COMMITTED', events}
    : {status: 'REACTION_REQUIRED', reaction: {reaction: 'Opportunity Attack'}, events: batch()});
  assert.deepEqual(h.drawn, []);
  await h.playEvents(result.events); h.renderTokens();
  assert.deepEqual(h.drawn, [point(2), point(3)]);
});

test('mid-route place snapshot survives answer and committed replay resumes from that square', async () => {
  const h = harness();
  h.setMapPick({positions: new Map([['a', point(3)]]),
    cursors: new Map([['a', {event_sequence: 1, path_index: 2}]]), cells: []});
  h.renderTokens();
  h.setMapPick(null); // answering calls renderHighlights/renderTokens with old state
  h.renderTokens();
  await h.playEvents(batch(movement(1, [point(1), point(2), point(3), point(4), point(5)])));
  h.renderTokens(); h.render(h.state(1, point(5)));
  assert.deepEqual(h.drawn, [point(3), point(4), point(5)]);
});

test('AI auto-step uses the same single playback while a UI redraw occurs before state render', async () => {
  const h = harness(), path = [point(1), point(2), point(3)];
  h.app.playing = true;
  h.app.nextResponse = {status: 'COMMITTED', state: h.state(1, point(3)), events: batch(movement(1, path))};
  const step = h.autoStep();
  await timerPromise(1); h.renderTokens();
  assert.equal(await step, true);
  h.renderTokens();
  assert.deepEqual(h.drawn, path.slice(1));
});

test('teleport is one jump and forced push/pull follows its recorded slide once', async () => {
  for (const teleport of [true, false]) {
    const h = harness(), path = [point(1), point(2), point(3), point(4)];
    await h.playEvents(batch(movement(1, path, {teleport, movement_kind: 'forced'})));
    h.renderTokens(); h.render(h.state(1, point(4)));
    assert.deepEqual(h.drawn, teleport ? [point(4)] : path.slice(1));
    assert.equal(h.node.classList.contains('is-blinking'), false);
  }
});

const timerPromise = ms => new Promise(resolve => timer(resolve, ms));

test('pending-action resume skips all displayed events and the second visit to a square', async () => {
  const scenarios = process.env.SOL156_RECORDING
    ? JSON.parse(readFileSync(process.env.SOL156_RECORDING, 'utf8')).scenarios : [
      {events: batch(movement(1, [point(1), point(2)]), movement(2, [point(2), point(3)]),
        movement(3, [point(3), point(4)])), pause: point(3), cursor: {event_sequence: 2, path_index: 1}, expected: [point(4)]},
      {events: batch(movement(1, [point(1), point(2), point(3), point(2), point(4)])),
        pause: point(2), cursor: {event_sequence: 1, path_index: 3}, expected: [point(4)]}];
  for (const scenario of scenarios) {
    const h = harness(); h.app.prompts = [];
    h.setMapPick({positions: new Map([['a', scenario.pause]]),
      cursors: new Map([['a', scenario.cursor]]), cells: []});
    h.renderTokens(); h.setMapPick(null); h.drawn.length = 0;
    h.app.nextResponse = {status: 'COMMITTED', events: scenario.events,
      state: h.state(scenario.events.last_sequence, scenario.expected.at(-1))};
    const prompt = scenario.prompt || {context: {}, reaction: 'Choose a space', choice: {options: [],
      space_map: {chooser_id: 'a', origin: scenario.pause,
        tokens: [{id: 'a', position: scenario.pause, movement_cursor: scenario.cursor}]}}};
    if (scenario.prompt) {
      prompt.choice.space_map = {chooser_id: 'a', origin: scenario.pause,
        tokens: [{id: 'a', position: scenario.pause, movement_cursor: scenario.cursor}]};
    }
    await h.resumePendingAction({method: 'act', request: {}, reaction: prompt});
    assert.deepEqual(h.drawn, scenario.expected);
    assert.equal(h.app.prompts.length, 1);
    assert.equal(h.app.busy, false);
  }
});

test('legacy pause without cursor holds position until committed state rather than guessing a route occurrence', async () => {
  const h = harness();
  h.setMapPick({positions: new Map([['a', point(2)]]), cells: []});
  h.renderTokens(); h.setMapPick(null); h.drawn.length = 0;
  await h.playEvents(batch()); h.renderTokens();
  assert.deepEqual(h.drawn, [], 'an empty poll must not release the retained pause');
  await h.playEvents(batch(movement(1, [point(1), point(2), point(3), point(2), point(4)])));
  h.renderTokens(); assert.deepEqual(h.drawn, []);
  h.render(h.state(1, point(4))); assert.deepEqual(h.drawn, [point(4)]);
});

test('repeated-square continuation uses its route index rather than the first x/y match', async () => {
  const h = harness(); h.app.prompts = [];
  h.setMapPick({positions: new Map([['a', point(2)]]),
    cursors: new Map([['a', {event_sequence: 1, path_index: 3}]]), cells: []});
  h.renderTokens(); h.setMapPick(null); h.drawn.length = 0;
  h.app.nextResponse = {status: 'COMMITTED', state: h.state(1, point(4)),
    events: batch(movement(1, [point(1), point(2), point(3), point(2), point(4)]))};
  await h.resumePendingAction({request: {}, reaction: {context: {}}});
  assert.deepEqual(h.drawn, [point(4)]);
});

test('committing a choice with no movement releases its snapshot before the next action', async () => {
  const h = harness(); h.app.prompts = [];
  h.setMapPick({positions: new Map([['a', point(1)]]), cells: []}); h.setMapPick(null);
  h.app.nextResponse = {status: 'COMMITTED', state: h.state(1),
    events: batch({event_sequence: 1, event_type: 'INTENT_ACCEPTED'})};
  await h.resumePendingAction({request: {}, reaction: {context: {}}});
  assert.equal(h.app.movePositions.size, 0);
  await h.playEvents(batch(movement(2, [point(1), point(2), point(3)])));
  assert.deepEqual(h.drawn, [point(2), point(3)]);
});

test('recorded real table OA pause/reload response walks its actual route once',
  {skip: !process.env.SOL156_RECORDING}, async () => {
    const recording = JSON.parse(readFileSync(process.env.SOL156_RECORDING, 'utf8'));
    const move = recording.committed.events.find(row => row.event_type === 'MOVEMENT_COMMITTED');
    assert.ok(move, 'real table recorded a move');
    const path = move.raw.payload.path;
    for (const entry of ['withReactions', 'resumePendingAction']) {
      const h = harness(); h.app.state = h.state(0, path[0]); h.renderTokens(); h.drawn.length = 0;
      h.app.prompts = [];
      h.app.nextResponse = {status: 'COMMITTED', events: {...recording.committed, events: [{...move, actor_id: 'a'}]},
        state: h.state(recording.committed.last_sequence, path.at(-1))};
      if (entry === 'resumePendingAction') await h.resumePendingAction(recording.pending);
      else {
        const result = await h.withReactions(async answers => answers.length ? h.app.nextResponse
          : {status: 'REACTION_REQUIRED', reaction: {reaction: 'Opportunity Attack'}, events: recording.paused});
        await h.playEvents(result.events);
    }
    h.renderTokens();
    h.render(h.state(recording.committed.last_sequence, path.at(-1)));
    assert.deepEqual(h.drawn, path.slice(1).map(({x, y}) => ({x, y})));
    }
  });
