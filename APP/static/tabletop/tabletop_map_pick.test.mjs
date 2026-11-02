// node --test APP/static/tabletop/tabletop_map_pick.test.mjs
// MMX108: a teleport's destination is clicked on the main map (owner 2026-10-03, round 24: "you can just click
// on an available square on the grid rather than a tooltip"). This drives the real tabletop.js code out of
// tabletop.test.mjs's own harness: the highlighted squares, the click that answers, Esc that cancels, and the
// fall back to the old dialog for a choice the engine did not mark.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {heightMovement, movesAtHeight} from './flight-ui.js';

const source = readFileSync(new URL('./tabletop.js?v=rel6-2', import.meta.url), 'utf8');
const slice = (from, to) => {
  const start = source.indexOf(from);
  assert.ok(start >= 0, `find ${from}`);
  const end = source.indexOf(to, start);
  assert.ok(end > start, `find ${to} after ${from}`);
  return source.slice(start, end);
};

// A DOM element with just enough of the interface these functions use: innerHTML rebuilds firstChild/lastChild,
// because hint() writes markup and then talks to the button it just created.
const el = () => {
  const node = {hidden: true, children: [], listeners: {},
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
    addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); },
    click() { for (const handler of this.listeners.click || []) handler(); },
    querySelectorAll: () => [], querySelector: () => null, showModal() {}, close() {}};
  // A button keeps its visible label and its click handlers, so a test can press the button it finds.
  const button = label => {
    const b = el(); b.tag = 'button'; b.textContent = label; return b;
  };
  Object.defineProperty(node, 'innerHTML', {get() { return this._html || ''; }, set(value) {
    this._html = value;
    const span = el(); span.tag = 'span'; span.textContent = '';
    this.children = [span];
    for (const m of (value.match(/<button[^>]*>[^<]*<\/button>/g) || [])) {
      this.children.push(button(m.replace(/<[^>]*>/g, '')));
    }
  }});
  Object.defineProperty(node, 'firstChild', {get() { return this.children[0]; }});
  Object.defineProperty(node, 'lastChild', {get() { return this.children[this.children.length - 1]; }});
  return node;
};

function harness(actors = {}) {
  const hint = el(), reaction = el(), highlights = [], keydowns = [], bodyClasses = new Set(), broadcasts = [], requests = [];
  // The list dialog ends by opening #ttReaction with showModal(); count the opens so a test can see the list was reached.
  reaction.modalOpens = 0;
  reaction.showModal = () => { reaction.modalOpens += 1; };
  const app = {mapPick: null, targeting: null, pendingMove: null, menu: null, hoverCell: null, showMoves: true,
               state: {}, lastSequence: 0};
  const classList = {add: name => bodyClasses.add(name), remove: name => bodyClasses.delete(name),
                     contains: name => bodyClasses.has(name),
                     toggle: (name, force) => {
                       const on = force ?? !bodyClasses.has(name);
                       if (on) bodyClasses.add(name); else bodyClasses.delete(name);
                       return on;
                     }};
  const bindings = {
    app, hint, reaction, highlights, heightMovement, movesAtHeight,
    board: {setHighlights: value => highlights.push(value), setMovementExplanation() {}, zoomBy() {}},
    api: async (url, options = {}) => { requests.push({url, body: options.body}); return {}; },
    enc: text => encodeURIComponent(String(text)),
    playEvents: () => {},
    // Prose and markup helpers the list dialog calls; these tests check the dialog's wiring, not its wording.
    decisionText: () => '', spaceGrid: () => '', spaceOptionLabel: option => option.label,
    escapeHtml: text => String(text ?? ''),
    document: {createElement: () => el(), addEventListener: (event, handler) => { if (event === 'keydown') keydowns.push(handler); },
               fullscreenElement: null, exitFullscreen() {}, body: {classList}},
    $: selector => (selector === '#ttHint' ? hint : selector === '#ttReaction' ? reaction : el()),
    cleanRules: text => String(text || '').replace(/<[^>]*>/g, '').trim(),
    escapeHtml: text => String(text ?? ''),
    toast() {}, renderTokens() {}, renderShapePanel() {}, renderActionBar() {}, actors: () => [], actorById: id => actors[id] || null, objectById: () => null,
    presentation: () => null, lineOfSight: () => true, askReaction: () => Promise.resolve(null),
    currentViewer: () => ({ready: true}), // these existing picker cases use a visible, ready view
    refuseCoveredView: () => false, // a visible view never refuses a cancel
    broadcastActors: () => broadcasts.push(app.pendingChoice ? {...app.pendingChoice} : null),
  };
  const code = [
    slice('function moveHeight()', 'function renderHighlights()'),
    slice('function renderHighlights()', '// A fresh board selection'),
    slice('async function onCellClick(cell)', 'async function moveTo(move)'),
    slice('function askChoice(prompt)', 'async function askReaction(prompt'),
    slice('async function withReactions(', '// A reload has no withReactions closure'),
    slice('document.addEventListener("keydown"', '// Keep a watching table in step'),
    slice('function resumeViewerDialogs()', 'function resetViewerPresentation()'),
    'return {askChoice, onCellClick, answerMapPick, cancelMapPick, renderHighlights, pendingChoiceText, withReactions};',
  ].join('\n');
  const api = new Function(...Object.keys(bindings), code)(...Object.values(bindings));
  return {...api, app, hint, reaction, highlights, bodyClasses, broadcasts, requests,
          escape: event => keydowns.forEach(handler => handler(event))};
}

// A teleport pause exactly as combat/choice_presentation.py publishes it: one option per legal square, the
// engine's own option ids, and the squares the map must light up.
const teleportPrompt = (ids = ['cell:4,6', 'cell:4,8', 'cell:2,6'], decline = true) => ({
  context: {reactor_id: 'actor:mei'},
  title: 'Empty Step: choose a space', reaction: 'Empty Step', reactor: 'Mei Jiang', trigger: 'teleports',
  cost: 'the Bonus Action', summary: 'Teleport to an unoccupied square you can see.',
  choice: {minimum: 1, maximum: 1, allow_decline: decline,
            map_pick: {cells: ids.map(id => ({x: Number(id.split(':')[1].split(',')[0]), y: Number(id.split(':')[1].split(',')[1])})),
                        instruction: 'Click a highlighted square to land there, or press Esc to stay where you are.',
                        cancel_label: 'Stay here'},
            options: ids.map(id => ({id, label: `Teleport to ${id.split(':')[1]}`, cell: {x: Number(id.split(':')[1].split(',')[0]), y: Number(id.split(':')[1].split(',')[1])}}))},
});

test('a teleport lights up its legal squares on the main map instead of opening a dialog', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt());
  assert.equal(h.app.pendingChoice.actor_id, 'actor:mei');
  assert.equal(h.broadcasts.at(-1).label, 'Empty Step', 'the sheet knows which choice is open');
  assert.match(h.pendingChoiceText(), /highlighted square.*Cancel/);
  const shown = h.highlights.at(-1);
  assert.deepEqual(shown.moves, [{x: 4, y: 6}, {x: 4, y: 8}, {x: 2, y: 6}], 'the main map must highlight every legal square');
  assert.equal(shown.areas, undefined);
  assert.equal(h.hint.hidden, false);
  assert.match(h.hint.firstChild.textContent, /click a highlighted square on the map/i);
  assert.match(h.hint.firstChild.textContent, /Empty Step/, 'the hint names the ability');
  assert.equal(h.reaction.hidden, true, 'the list dialog must stay closed');
  assert.equal(h.reaction.innerHTML, '', 'no list of squares and no tooltip grid');
  assert.match(h.hint.innerHTML, /Cancel ability \(Esc\)/, 'Esc says what it does: it cancels the ability');
  assert.match(h.hint.innerHTML, /<button[^>]*>Stay here<\/button>/, 'an optional square has its own skip answer');
  h.cancelMapPick();
  await pending;
  assert.equal(h.app.pendingChoice, null);
  assert.equal(h.broadcasts.at(-1), null, 'the sheet learns the choice has closed');
});

test('clicking a highlighted square answers with that square\'s own option id', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt());
  h.onCellClick({x: 4, y: 8});
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['cell:4,8']});
  assert.equal(h.app.mapPick, null, 'the pick must close once it is answered');
  assert.equal(h.hint.hidden, true);
  assert.deepEqual(h.highlights.at(-1).moves, undefined, 'the squares are cleared after answering');
});

test('clicking a square that is not legal answers nothing', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt());
  h.onCellClick({x: 19, y: 19});
  assert.ok(h.app.mapPick, 'the player keeps choosing');
  h.cancelMapPick();
  assert.deepEqual(await pending, {cancelled: true});
});

test('clicking a token on a legal destination chooses its square', () => {
  const start = source.indexOf('function targetChoiceAt(cell)');
  const end = source.indexOf('\nfunction selectActor(', start);
  assert.ok(start >= 0 && end > start, 'find production token-click handler');
  const committed = [], closed = [], messages = [];
  const destination = {candidate_id: 'blossom-at-enemy', destination: {x: 4, y: 6}};
  const targeting = {byTarget: new Map(), areas: [], destinations: [destination], resolve: value => committed.push(value)};
  const app = {state: {}, busy: false, targeting};
  const onTokenClick = new Function('app', 'board', 'hint', 'closeChoice', 'act', 'toast', 'objectById',
    'actors', 'pickTarget', 'pickObjectInSquare',
    source.slice(start, end) + '\nreturn onTokenClick;')(
      app, {cellAt: () => ({x: 4, y: 6})}, () => {}, () => closed.push(true), id => id,
      message => messages.push(message), () => null, () => [], () => {}, () => {});
  onTokenClick('enemy-token', {clientX: 10, clientY: 20});
  assert.deepEqual(committed, ['blossom-at-enemy']);
  assert.deepEqual(closed, [true]);
  assert.deepEqual(messages, []);
  assert.equal(app.targeting, null);
});

test('Esc cancels and leaves the player where they are', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt());
  h.escape({key: 'Escape', target: {closest: () => null}});
  assert.deepEqual(await pending, {cancelled: true});
  assert.equal(h.app.mapPick, null, 'Esc must close the pick on every path, not leave the sheet asking');
  assert.equal(h.hint.hidden, true);
});

test('a required map choice can abandon the ability without submitting DECLINE', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt(['cell:4,6'], false));
  assert.match(h.pendingChoiceText(), /Cancel|Esc/);
  assert.equal(h.hint.children.filter(child => child.tag === 'button').length, 1);
  h.escape({key: 'Escape', target: {closest: () => null}});
  assert.equal(h.app.mapPick, null);
  assert.deepEqual(await pending, {cancelled: true});
});

test('an unmarked spatial pending choice uses the map instead of a coordinate list', async () => {
  const h = harness();
  const prompt = teleportPrompt();
  delete prompt.choice.map_pick;
  for (const option of prompt.choice.options) delete option.cell;
  const pending = h.askChoice(prompt);
  assert.equal(h.highlights.at(-1).moves.length, 3);
  assert.equal(h.reaction.innerHTML, '');
  h.onCellClick({x: 4, y: 8});
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['cell:4,8']});
});

test('non-spatial choices retain their ordinary dialog', () => {
  const h = harness();
  // Only the routing is checked here: the list dialog itself needs a real document.
  const prompt = {
    context: {reactor_id: 'actor:mei'},
    title: 'Healing touch: restore HP',
    reaction: 'Healing touch', reactor: 'Mei Jiang', trigger: 'healing',
    cost: '1 Stamina', summary: 'Restore up to 10 HP to one creature.',
    choice: {minimum: 1, maximum: 1, allow_decline: true, options: [{id: 'heal:1', label: 'Heal 10 HP'}]},
  };
  const pending = h.askChoice(prompt);
  assert.equal(h.app.mapPick, null, 'mapPick must remain null for non-spatial choices');
  assert.equal(h.reaction.modalOpens, 1, 'the ordinary list dialog opens');
  assert.equal(h.highlights.at(-1)?.moves, undefined, 'no squares are lit for a non-spatial choice');
  pending.catch(() => {});
});

test('a map answer resolves its choice and closes the picker, leaving the prompt context untouched', async () => {
  const h = harness(), prompt = teleportPrompt();
  prompt.context = {reactor_id: 'actor:mei', checkpoint: 'pause:1', reaction_source_id: 'choice:test'};
  const pending = h.askChoice(prompt);
  h.onCellClick({x: 4, y: 8});
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['cell:4,8']});
  assert.equal(h.app.mapPick, null, 'the picker closes after the answer');
  assert.deepEqual(prompt.context, {reactor_id: 'actor:mei', checkpoint: 'pause:1', reaction_source_id: 'choice:test'});
});

// A real lazy placement pause (combat/ext/placement_picker.py) carries the ability's own concise
// square line AND the shared context fields; the picker must show them beside it, not instead of
// it: the player still needs to know whose square this is, what the choice does and what it spends.
const bloomPrompt = () => {
  const prompt = teleportPrompt(['cell:3,6']);
  prompt.context = {reactor_id: 'actor:guo'};
  prompt.reactor = 'Guo Yuan';
  prompt.reaction = 'Cultivate Blossom (bloom at once)';
  prompt.trigger = 'Choose a square for Guo Yuan to use Cultivate Blossom (bloom at once).';
  prompt.summary = 'A flower blooms in the chosen square.';
  prompt.cost = '1 Stamina';
  prompt.choice.map_pick.prompt = 'Cultivate Blossom: choose where the blossom blooms.';
  return prompt;
};

test('a real placement prompt keeps the concise line beside its chooser, effect and cost', async () => {
  const h = harness();
  const pending = h.askChoice(bloomPrompt());
  const shown = h.hint.firstChild.textContent;
  assert.match(shown, /Cultivate Blossom: choose where the blossom blooms\./, "the ability's concise instruction stays");
  assert.match(shown, /Guo Yuan/, 'the hint names whose choice this is');
  assert.match(shown, /A flower blooms in the chosen square\./, 'the effect text stays');
  assert.match(shown, /Cost now: 1 Stamina/, 'the cost stays beside the instruction');
  h.onCellClick({x: 3, y: 6});
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['cell:3,6']});
});

test('cancelling an initial aim uses the guarded cancel API, never DECLINE on a mandatory choice', async () => {
  const h = harness(), prompt = teleportPrompt(['cell:4,6'], false);
  prompt.cancel_action = {candidate_id: 'candidate:aim', decision_id: 'decision:1', state_version: 3,
    pending_id: 'attempt:7'}; // the fresh aim's own attempt id travels with the request unchanged
  h.app.matchId = 'match:test';
  const pending = h.askChoice(prompt);
  await h.cancelMapPick();
  assert.equal((await pending).cancelled, true);
  assert.deepEqual(h.requests, [{url: '/api/tabletop/matches/match%3Atest/placement/cancel', body: prompt.cancel_action}]);
});

test('mixed spatial and text options retain the text option as a button', async () => {
  const h = harness(), prompt = teleportPrompt();
  prompt.choice.options.push({id: 'stay', label: 'Stay here'});
  const pending = h.askChoice(prompt);
  assert.equal(h.highlights.at(-1).moves.length, 3);
  assert.equal(h.hint.lastChild.textContent, 'Stay here');
  h.hint.lastChild.click();
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['stay']});
});

test('creature options highlight tokens and submit the creature id', async () => {
  const h = harness();
  const pending = h.askChoice({reaction: 'Healing touch', choice: {minimum: 1, maximum: 1,
    options: [{id: 'actor:ally', target_id: 'actor:ally', cell: {x: 4, y: 6}}]}});
  assert.deepEqual(h.highlights.at(-1).targets, [{x: 4, y: 6}]);
  h.answerMapPick({x: 4, y: 6}, 'actor:ally');
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['actor:ally']});
});

test('multiple spatial selections stay on the map and preserve every option', async () => {
  const h = harness(), prompt = teleportPrompt();
  prompt.choice.minimum = 2; prompt.choice.maximum = 2;
  const pending = h.askChoice(prompt);
  h.onCellClick({x: 4, y: 6});
  h.onCellClick({x: 4, y: 8});
  assert.deepEqual([...h.app.mapPick.selected], ['cell:4,6', 'cell:4,8']);
  h.onCellClick({x: 2, y: 6});
  assert.equal(h.app.mapPick.selected.size, 2, 'the native maximum is enforced');
  h.onCellClick({x: 4, y: 6});
  h.onCellClick({x: 2, y: 6});
  h.hint.lastChild.click();
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['cell:4,8', 'cell:2,6']});
  assert.equal(h.reaction.innerHTML, '');
});

test('hover previews an unmarked point and clears on an illegal square', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt());
  h.app.hoverCell = {x: 4, y: 8}; h.renderHighlights();
  assert.deepEqual(h.highlights.at(-1).areaCells, [{x: 4, y: 8}]);
  h.app.hoverCell = {x: 99, y: 99}; h.renderHighlights();
  assert.deepEqual(h.highlights.at(-1).areaCells, []);
  h.cancelMapPick(); await pending;
});

test('a marked choice with no square falls back to the list rather than trapping the player', () => {
  const h = harness();
  // The list dialog needs a real document; reaching it is the proof (it fails on textContent, after routing).
  const pending = h.askChoice(teleportPrompt([]));
  assert.equal(h.app.mapPick, null, 'nothing to click means no map picker');
  assert.equal(h.reaction.modalOpens, 1, 'the list dialog opens instead');
  assert.equal(h.highlights.at(-1)?.moves, undefined, 'no squares are lit');
  pending.catch(() => {});
});

// The pick is asked from inside a request the fight is still working, and that state switches the board off to
// clicks (tabletop.css). So the open pick has to be visible on the page, and has to stop being visible on EVERY way
// out of it -- answered by a square, cancelled by the button, cancelled by Esc -- or the next ordinary action is
// played on a board that never takes clicks again. Whether those clicks really land is hit-tested against the real
// stylesheet in tabletop_map_pick_hit.test.mjs.
test('the open pick is announced on the page, and unannounced on every way out of it', async () => {
  const h = harness();
  const answered = h.askChoice(teleportPrompt());
  assert.equal(h.bodyClasses.has('is-map-pick'), true, 'open: the board is told');
  h.onCellClick({x: 4, y: 8});
  await answered;
  assert.equal(h.bodyClasses.has('is-map-pick'), false, 'answered: the board is told no more');

  const declined = h.askChoice(teleportPrompt());
  assert.equal(h.bodyClasses.has('is-map-pick'), true);
  h.cancelMapPick();
  await declined;
  assert.equal(h.bodyClasses.has('is-map-pick'), false, 'cancelled: the board is told no more');

  const escaped = h.askChoice(teleportPrompt());
  assert.equal(h.bodyClasses.has('is-map-pick'), true);
  h.escape({key: 'Escape', target: {closest: () => null}});
  await escaped;
  assert.equal(h.bodyClasses.has('is-map-pick'), false, 'Esc: the board is told no more');
});

test('a creature-only choice keeps its list dialog and never opens the map (F8R 1)', () => {
  // The creatures are on the board with real squares: the old routing would have turned them into map squares.
  const h = harness({'actor:ally': {position: {x: 4, y: 6}}, 'actor:foe': {position: {x: 9, y: 2}}});
  const prompt = {
    context: {reactor_id: 'actor:mei'},
    title: 'Healing touch: restore HP', reaction: 'Healing touch', reactor: 'Mei Jiang', trigger: 'healing',
    cost: '1 Stamina', summary: 'Restore up to 10 HP to one ally.',
    choice: {minimum: 1, maximum: 1, allow_decline: true,
             options: [{id: 'actor:ally', label: 'Ally'}, {id: 'actor:foe', label: 'Foe'}]},
  };
  // The list dialog needs a real document; here the point is only that the map is never armed.
  const pending = h.askChoice(prompt);
  assert.equal(h.app.mapPick, null, 'a creature-only list must not arm the map picker');
  assert.equal(h.reaction.modalOpens, 1, 'the creature list dialog opens');
  assert.equal(h.highlights.at(-1)?.moves, undefined, 'no squares are lit for a creature-only list');
  pending.catch(() => {});
});

// F8R 2: a cancelled map square from the reaction menu takes the menu's cancel route (all DECLINE, with selection).
const menuSource = readFileSync(new URL('./tabletop.js?v=rel6-2', import.meta.url), 'utf8');
const menuSlice = (from, to) => {
  const start = menuSource.indexOf(from);
  assert.ok(start >= 0, 'find ' + from);
  const end = menuSource.indexOf(to, start);
  assert.ok(end > start, 'find ' + to + ' after ' + from);
  return menuSource.slice(start, end);
};
const menuAnswers = new Function(
  menuSlice('function reactionMenuAnswers(', '// The answer for a map square picked from the reaction menu.') +
  menuSlice('function reactionMenuMapAnswer(', 'function reactionMenuRows(') +
  'return {reactionMenuAnswers, reactionMenuMapAnswer};')();
const reactionPrompt = {alternatives: [
  {reaction: 'Exploit — strike', context: {reaction_source_id: 'react:a'}, choice: {minimum: 1, maximum: 1}},
  {reaction: 'Footwork — step', context: {reaction_source_id: 'react:b'}, choice: {minimum: 1, maximum: 1}},
]};

test('cancelling the map from the reaction menu submits the menu cancel, never a decision without selection (F8R 2)', () => {
  const answer = menuAnswers.reactionMenuMapAnswer(reactionPrompt, 1, {cancelled: true});
  assert.ok(Array.isArray(answer));
  assert.ok(answer.every(row => typeof row.selection === 'string'), 'every decision carries a selection');
  assert.deepEqual(answer.map(row => row.selection), ['DECLINE', 'DECLINE']);
});

test('a map square picked from the reaction menu still answers the chosen alternative', () => {
  const answer = menuAnswers.reactionMenuMapAnswer(reactionPrompt, 0, {selection: 'USE', option_ids: ['cell:4,8']});
  assert.equal(answer[0].selection, 'USE');
  assert.deepEqual(answer[0].option_ids, ['cell:4,8']);
});
