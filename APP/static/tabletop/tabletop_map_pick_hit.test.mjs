// node --test APP/static/tabletop/tabletop_map_pick_hit.test.mjs
// MMX108f1: a teleport's landing square has to be *clickable* on the real page while the fight is working the action
// that asked for it. The first version of this picker passed its tests and still could not be played: askChoice armed
// the squares correctly, onCellClick answered correctly, and the action that raised the question held body.is-working
// for the whole request -- which tabletop.css turns into pointer-events: none on the board and on the hint. The
// squares were lit up on a board that refused every click, and only Esc (a key handler) still worked.
//
// Drives act()/resumePendingAction() -> askChoice(), the real renderTokens()/board.js
// nodes, and board/token event listeners. The CSS resolver gates delivery using the
// shipped stylesheet. This is headless DOM/event evidence, not browser layout evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from '../../tests/objects_dom_stub.mjs';
import {parseSheet, computedValue, hitTestable} from '../../tests/css_cascade.mjs';
import {createBoard, initials, treeCells, CELL} from './board.js';
import {createViewerStore, resolveViewerIdentity} from './viewer-identity.js';
import {heightFeet, flightText, heightMovement, movesAtHeight} from './flight-ui.js';
import {tokenSensePresentation, wallCells} from './vision.js?v=rel6-2';
import {blockerSegments, visibilityPolygons} from './fog_polygon.js';
import {altitudeFogKey, altitudeVisibilityPolygons, viewerEye} from './fog-altitude.js';
import {wallSightCells} from './zones.js';

const here = new URL('./', import.meta.url);
const source = readFileSync(new URL('tabletop.js', here), 'utf8');
const sheet = parseSheet(readFileSync(new URL('tabletop.css', here), 'utf8'));

const slice = (from, to) => {
  const start = source.indexOf(from);
  assert.ok(start >= 0, `find ${from}`);
  const end = source.indexOf(to, start);
  assert.ok(end > start, `find ${to} after ${from}`);
  return source.slice(start, end);
};

// The two elements the picker needs, and the page they sit in. The real markup is parsed, so this test cannot drift
// away from the page that ships.
function page() {
  const realTimer = globalThis.setTimeout;
  const document = installDOM(readFileSync(new URL('tabletop.html', here), 'utf8'));
  globalThis.setTimeout = realTimer;
  const hint = document.getElementById('ttHint');
  // The stub keeps `hidden` as a plain property; a browser reflects it onto the attribute the stylesheet matches
  // ([hidden] -> display: none), so the test does it too and the hit test stays honest.
  let reflected = hint.hasAttribute('hidden');
  Object.defineProperty(hint, 'hidden', {
    get: () => reflected,
    set(value) {
      reflected = Boolean(value);
      if (reflected) hint.setAttribute('hidden', ''); else hint.removeAttribute('hidden');
    },
  });
  return {document, body: document.body, viewport: document.getElementById('ttViewport'), hint};
}

const teleportPrompt = (ids = ['cell:4,6', 'cell:4,8', 'cell:2,6']) => ({
  title: 'Empty Step: choose a space', reaction: 'Empty Step', reactor: 'Mei Jiang', trigger: 'teleports',
  cost: 'the Bonus Action', summary: 'Teleport to an unoccupied square you can see.',
  choice: {minimum: 1, maximum: 1, allow_decline: true,
            map_pick: {cells: ids.map(id => ({x: Number(id.split(':')[1].split(',')[0]), y: Number(id.split(':')[1].split(',')[1])})),
                        instruction: 'Click a highlighted square to land there, or press Esc to stay where you are.',
                        cancel_label: 'Stay here'},
            options: ids.map(id => ({id, label: `Teleport to ${id.split(':')[1]}`,
                                     cell: {x: Number(id.split(':')[1].split(',')[0]), y: Number(id.split(':')[1].split(',')[1])}}))},
});

// The server the table would be talking to: it pauses once for the destination, then commits the move.
function server(prompts = [teleportPrompt()]) {
  const sent = [];
  let next = 0;
  return {
    sent,
    api: async (url, options) => {
      sent.push({url, body: options.body});
      if (next < prompts.length) return {status: 'REACTION_REQUIRED', reaction: prompts[next++]};
      return {status: 'COMMITTED', events: [], state: {menu: null}};
    },
  };
}

function harness(prompts) {
  const dom = page();
  const {document, body, viewport, hint} = dom;
  const {api, sent} = server(prompts);
  const highlights = [];
  const app = {busy: false, mapPick: null, targeting: null, pendingMove: null, menu: null, hoverCell: null,
               showMoves: true, opaque: null, selected: new Set(), lastTarget: null, lastSequence: 0, matchId: 'm1',
               fog: 'off', state: {menu: {decision_id: 'd1', state_version: 3, moves: []},
                 presentation: {current_actor_id: 'chooser', battlefield: {blocked_cells: []}, actors: [
                   {entity_id: 'chooser', display_name: 'Mei Jiang', position: {x: 1, y: 1},
                    footprint: {width_cells: 2, height_cells: 2}, active: true, conditions: [],
                    hit_points: {current: 10, maximum: 10}},
                   {entity_id: 'foe', display_name: 'Other fighter', position: {x: 7, y: 1},
                    active: true, conditions: [], hit_points: {current: 10, maximum: 10}},
                 ]}}};
  // These picker/gesture tests deliberately use the explicit GM role, retaining
  // their complete-map fixture without inferring a role from an empty owner set.
  const viewerStore = createViewerStore({viewId: 'map-pick-test'});
  viewerStore.bindGM(app.matchId);
  const currentViewer = () => resolveViewerIdentity(viewerStore.read(app.matchId), app.state.presentation.actors, {seats: {}});
  let client;
  const board = createBoard(viewport, {
    onCellClick: cell => client.onCellClick(cell),
    onTokenClick: (id, event) => client.onTokenClick(id, event),
    onTokenPointerDown: (id, event) => client.onTokenPointerDown(id, event),
  });
  // fogGeometry reads the map's trees, walls and blocked cells; the picker fixtures are empty.
  board.setMap({width: 20, height: 14, background: {style: 'plain'},
    walls: [], trees: [], cells: {blocked: [], sight: []}});
  const bindings = {
    app, document, heightFeet, flightText, heightMovement, movesAtHeight, tokenSensePresentation, highlightSink: null,
    board: {...board, setHighlights(value) { highlights.push(value); board.setHighlights(value); }},
    initials, TEAM_HEX: ['#abcdef'], treeCells, wallCells, visibilityPolygons, altitudeVisibilityPolygons, altitudeFogKey, viewerEye, blockerSegments, wallSightCells,
    $: selector => document.querySelector(selector),
    cleanRules: text => String(text || '').replace(/<[^>]*>/g, '').trim(),
    escapeHtml: text => String(text ?? ''),
    toast() {}, renderActionBar() {}, render() {
      // This clickability fixture commits no movement and leaves the original
      // positions in place. Model arrival of that final snapshot: real render()
      // discards pause overlays when no pending_action remains (SOL156).
      for (const [id, move] of app.movePositions || []) if (move.pause) app.movePositions.delete(id);
      client.renderTokens();
    }, gmNotice() {}, async refresh() {}, renderRoster() {}, renderInspector() {},
    broadcastActors() {}, renderShapePanel() {}, renderActionBar() {},
    actors: () => app.state.presentation.actors, actorById: id => app.state.presentation.actors.find(a => a.entity_id === id),
    objectById: () => null, presentation: () => app.state.presentation,
    visibility: () => null, unseenByViewers: () => false, teamIndex: () => 0, isManualActor: () => true,
    currentViewer, isOwnedActor: actor => currentViewer().isOwned(actor), isGMView: () => currentViewer().status === 'gm',
    roofAudience: () => [], fogAudience: () => [], reconcileViewerIdentity: () => false, resumeViewerDialogs() {},
    squareFogDebug: () => false, visibleCells: () => [], rememberedCells: () => null,
    shownCondition: () => false, tableObjectTokens: () => [],
    lineOfSight: () => true, enc: value => value, api,
    synchronizePresets: async () => {},
    playEvents: async () => {}, readTableState: async () => ({menu: null}), refreshSequence: 0,
  };
  const code = [
    // LIVE renderTokens also calls this helper; these picker fixtures use fog off.
    slice('function fogGeometry(seen)', '// Invisible or Hidden'),
    slice('function tokenLabels()', '// Lasting zones'),
    slice('function tokenImage(actor)', 'function renderInitiative()'),
    slice('function moveHeight()', '// A fresh board selection'),
    slice('function onTokenClick(id, event)', 'async function onCellClick(cell)'),
    slice('async function onCellClick(cell)', 'async function moveTo(move)'),
    slice('function onTokenPointerDown(id, event)', '// ------------------------------------------------------------------ doing things'),
    slice('function askChoice(prompt)', 'async function askReaction(prompt'),
    slice('async function askReaction(prompt', 'async function withReactions(send'),
    slice('async function withReactions(send', '// A reload has no withReactions closure'),
    slice('async function resumePendingAction(pending', '// The Items panel'),
    slice('function refuseCoveredView(', '// Act on one candidate that needs no further choice'),
    slice('function invalidateTargeting()', 'function cancelTargeting('),
    slice('async function handleUnavailableFight(', 'function renderCommitNotice('),
    slice('async function act(', '// An ability the fight runs nothing for'),
    'return {act, onCellClick, onTokenClick, onTokenPointerDown, renderTokens, renderHighlights, cancelMapPick, resumePendingAction};',
  ].join('\n');
  const api_ = client = new Function(...Object.keys(bindings), code)(...Object.values(bindings));
  client.renderTokens();

  // Model viewport gesture delivery using real board coordinates and listeners.
  const clickSquare = cell => {
    if (!hitTestable(sheet, viewport)) return false;
    const {x, y, zoom} = board.view;
    const details = {clientX: x + (cell.x + 0.5) * CELL * zoom, clientY: y + (cell.y + 0.5) * CELL * zoom, pointerId: 1};
    viewport.dispatch('pointerdown', details);
    viewport.dispatch('pointerup', details);
    return true;
  };
  const clickStayHere = () => {
    const button = hint.lastChild;
    if (!button || !hitTestable(sheet, hint) || !hitTestable(sheet, button)) return false;
    button.click();
    return true;
  };
  return {...api_, ...dom, board, app, highlights, sent, clickSquare, clickStayHere};
}

async function waitFor(predicate, tries = 200) {
  for (let index = 0; index < tries; index += 1) {
    if (predicate()) return true;
    await new Promise(resolve => globalThis.setTimeout(resolve, 0));
  }
  return predicate();
}

// Let the action finish, and fail rather than hang. A click the stylesheet swallows leaves the fight waiting for an
// answer that never comes -- which is the regression itself, and must read as a failure and not as a stuck test.
async function finish(h, acting) {
  const settled = await waitFor(() => !h.app.busy, 200);
  assert.equal(settled, true, 'the action finished once the player answered the question');
  return acting;
}

test('the hit test resolves the shipped stylesheet instead of guessing', () => {
  // Guard on the guard: if these two rules stopped being understood, every hit test below would silently pass.
  assert.deepEqual(sheet.unparsed.filter(selector => /#ttViewport|#ttHint/.test(selector)), [],
    'a rule that decides whether the map can be clicked must be one this resolver actually reads');
  for (const atRule of sheet.atRules) {
    for (const selector of atRule.body.split('}')) {
      assert.doesNotMatch(selector, /#ttViewport|#ttHint[^{]*\{[^}]*pointer-events/,
        `an @media rule the hit test cannot evaluate decides clicks: ${atRule.prelude} ${selector.trim().slice(0, 80)}`);
    }
  }
});

test('a teleport square can be clicked while the fight is working the action that asked for it', async () => {
  const h = harness();
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);

  assert.equal(h.body.classList.contains('is-working'), true, 'the action is still being worked out');
  assert.ok(h.app.mapPick, 'the destination question is open');
  assert.deepEqual(h.highlights.at(-1).moves, [{x: 4, y: 6}, {x: 4, y: 8}, {x: 2, y: 6}],
    'the legal squares are the ones lit up on the main map');
  assert.equal(h.hint.hidden, false, 'the prompt is on screen');

  assert.equal(h.clickSquare({x: 4, y: 8}), true, 'the click must reach the board');
  assert.deepEqual(h.app.mapPick, null);
  assert.equal(await finish(h, acting), true);
  assert.deepEqual(h.sent[1].body.reactions.at(-1),
    {selection: 'USE', option_ids: ['cell:4,8']}, 'the square that was clicked is the square the fight is told about');
});

test('the way out of the pick can be clicked too, not just the keyboard', async () => {
  const h = harness();
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);

  const button = h.hint.lastChild;
  assert.match(h.hint.innerHTML, /<button[^>]*>Stay here<\/button>/, 'the prompt says plainly what the button does');
  assert.equal(h.clickStayHere(), true, 'the click must reach the button inside the hint');
  await finish(h, acting);
  assert.deepEqual(h.sent.at(-1).body.reactions.at(-1), {selection: 'DECLINE'}, 'Stay here is the optional rider\'s own answer');
});

test('the prompt says whose choice this is, what set it off, and what it costs', async () => {
  const h = harness();
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);

  const shown = h.hint.firstChild.textContent;
  assert.match(shown, /Mei Jiang/, 'the player is told whose teleport this is');
  assert.match(shown, /Empty Step/, 'and which ability is asking');
  assert.match(shown, /teleports/, 'and what set it off');
  assert.match(shown, /Teleport to an unoccupied square you can see\./, 'and what the choice does');
  assert.match(shown, /Cost now: the Bonus Action/, 'and what it costs');
  assert.match(shown, /Click a highlighted square on the map/, 'then how to answer');
  assert.match(shown, /Press Esc to cancel the ability\./, 'and how to change your mind');
  assert.doesNotMatch(shown, /choice:|reaction_source|cell:/, 'no internal ids in a player-facing prompt');

  h.clickSquare({x: 2, y: 6});
  await finish(h, acting);
});

test('the picker is closed again once it is answered, and the body stops claiming one', async () => {
  const h = harness();
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);
  h.clickSquare({x: 4, y: 6});
  await finish(h, acting);

  assert.equal(h.app.mapPick, null);
  assert.equal(h.hint.hidden, true, 'the prompt is gone');
  assert.equal(h.body.classList.contains('is-map-pick'), false, 'the picker said so on the body, and stops saying so');
  assert.equal(h.body.classList.contains('is-working'), false, 'and the turn finished, so the board is the player\'s again');
  assert.equal(hitTestable(sheet, h.viewport), true, 'an idle board takes clicks, as it always did');
});

test('a working turn with no picker armed is still switched off, so the tests above have teeth', async () => {
  const h = harness();
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);
  h.clickSquare({x: 4, y: 8});
  await finish(h, acting);

  // The same page, mid-action, with nothing to choose: this is the state the bug shipped in. The squares were lit up
  // and the board still swallowed every click, which no amount of calling onCellClick by hand could have shown.
  h.body.classList.add('is-working');
  assert.equal(h.body.classList.contains('is-map-pick'), false);
  assert.equal(computedValue(sheet, h.viewport, 'pointer-events'), 'none',
    'the shipped stylesheet really does switch the board off while the fight is working');
  assert.equal(h.clickSquare({x: 4, y: 8}), false, 'so the click is swallowed and the player is not answered');
  h.body.classList.remove('is-working');
});

test('a turn stays non-submittable while the picker is open', async () => {
  const h = harness();
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);

  assert.equal(h.app.busy, true, 'the action is still in flight');
  assert.equal(await h.act('candidate:2'), false, 'a second action is still refused while the question is open');
  assert.equal(h.sent.length, 1, 'and it never reaches the fight');

  h.clickSquare({x: 4, y: 8});
  await finish(h, acting);
});

// Snapshots use the exact wire shape from choice_presentation.space_choice(). The
// committed board intentionally differs: the server rolled the transaction back.
function pauseAt(x, y, foeX = 7) {
  const prompt = teleportPrompt([`cell:${x + 1},${y}`, `cell:${x},${y + 1}`]);
  prompt.choice.space_map = {chooser_id: 'chooser', origin: {x, y}, tokens: [
    {id: 'chooser', position: {x, y}, cells: [{x, y}, {x: x + 1, y}, {x, y: y + 1}, {x: x + 1, y: y + 1}]},
    {id: 'foe', position: {x: foeX, y: 5}, cells: [{x: foeX, y: 5}]},
  ]};
  return prompt;
}

function assertTokenAt(h, id, x, y) {
  assert.equal(h.board.tokenNode(id).style.transform, `translate(${x * CELL}px, ${y * CELL}px)`);
}

async function clickTokenSquare(h, id, cell) {
  const {x, y, zoom} = h.board.view;
  const event = {clientX: x + (cell.x + 0.5) * CELL * zoom,
    clientY: y + (cell.y + 0.5) * CELL * zoom, pointerId: 1};
  const node = h.board.tokenNode(id);
  assert.ok(hitTestable(sheet, h.viewport) && hitTestable(sheet, node));
  // Real board.js listeners intercept these events; no direct onCellClick call.
  await node.dispatch('pointerdown', event);
  await node.dispatch('pointerup', event);
  await node.dispatch('click', event);
}

test('movement before a pause and consecutive hops retain snapshots until the committed state arrives', async () => {
  const h = harness([pauseAt(4, 6, 8), pauseAt(6, 6, 9)]);
  const committed = structuredClone(h.app.state.presentation.actors);
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);
  assertTokenAt(h, 'chooser', 4, 6);
  assertTokenAt(h, 'foe', 8, 5);
  assert.deepEqual(h.app.state.presentation.actors, committed, 'the overlay never edits committed state');
  h.clickSquare({x: 5, y: 6});
  assertTokenAt(h, 'chooser', 4, 6);
  assertTokenAt(h, 'foe', 8, 5);
  await waitFor(() => h.app.mapPick?.positions.get('chooser')?.x === 6);
  assertTokenAt(h, 'chooser', 6, 6);
  assertTokenAt(h, 'foe', 9, 5);
  h.clickStayHere();
  assertTokenAt(h, 'chooser', 6, 6);
  assertTokenAt(h, 'foe', 9, 5);
  await finish(h, acting);
  assertTokenAt(h, 'chooser', 1, 1);
  assertTokenAt(h, 'foe', 7, 1);
  assert.deepEqual(h.sent.at(-1).body.reactions.map(r => r.selection), ['USE', 'DECLINE']);
  assert.deepEqual(h.app.state.presentation.actors, committed);
});

test('reload resumes the saved pause snapshot and replaces it for the next destination', async () => {
  const h = harness([pauseAt(6, 6, 9)]);
  const pending = JSON.parse(JSON.stringify({method: 'act', request: {candidate_id: 'candidate:1'},
    reactions: [], reaction: pauseAt(4, 6, 8)}));
  const acting = h.resumePendingAction(pending);
  assertTokenAt(h, 'chooser', 4, 6);
  assertTokenAt(h, 'foe', 8, 5);
  h.clickSquare({x: 5, y: 6});
  await waitFor(() => h.app.mapPick?.positions.get('chooser')?.x === 6);
  assertTokenAt(h, 'chooser', 6, 6);
  h.cancelMapPick();
  await finish(h, acting);
  assertTokenAt(h, 'chooser', 1, 1);
  assert.equal(h.app.mapPick, null);
  assert.deepEqual(h.sent.at(-1).body.reactions.map(r => r.selection), ['USE', 'DECLINE']);
});

test('a Large chooser token delivers the clicked legal footprint square, including with pan and zoom', async () => {
  const h = harness([pauseAt(4, 6)]);
  h.board.zoomBy(1.5, 100, 100);
  const acting = h.act('candidate:1');
  await waitFor(() => h.app.mapPick);
  assert.equal(h.board.tokenNode('chooser').style.width, `${2 * CELL}px`);
  await clickTokenSquare(h, 'chooser', {x: 4, y: 6});
  assert.ok(h.app.mapPick, 'the exact current anchor is not a legal option');
  assert.equal(h.app.selected.size, 0, 'an invalid square does not select a creature');
  await clickTokenSquare(h, 'chooser', {x: 5, y: 6});
  await finish(h, acting);
  assert.deepEqual(h.sent.at(-1).body.reactions.at(-1), {selection: 'USE', option_ids: ['cell:5,6']});
  assertTokenAt(h, 'chooser', 1, 1);
  await clickTokenSquare(h, 'chooser', {x: 2, y: 1});
  assert.deepEqual([...h.app.selected], ['chooser'], 'ordinary token selection returns after the picker closes');
  await clickTokenSquare(h, 'foe', {x: 7, y: 1});
  assert.deepEqual([...h.app.selected], ['foe']);
});
