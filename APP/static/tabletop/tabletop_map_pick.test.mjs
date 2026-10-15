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
    addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); },
    click() { for (const handler of this.listeners.click || []) handler(); }};
  Object.defineProperty(node, 'innerHTML', {get() { return this._html || ''; }, set(value) {
    this._html = value;
    this.children = [{tag: 'span', textContent: '', addEventListener: () => {}}];
    for (const _ of (value.match(/<button/g) || [])) this.children.push({tag: 'button', addEventListener() {}});
  }});
  Object.defineProperty(node, 'firstChild', {get() { return this.children[0]; }});
  Object.defineProperty(node, 'lastChild', {get() { return this.children[this.children.length - 1]; }});
  return node;
};

function harness() {
  const hint = el(), reaction = el(), highlights = [], keydowns = [], bodyClasses = new Set(), broadcasts = [];
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
    document: {addEventListener: (event, handler) => { if (event === 'keydown') keydowns.push(handler); },
               fullscreenElement: null, exitFullscreen() {}, body: {classList}},
    $: selector => (selector === '#ttHint' ? hint : selector === '#ttReaction' ? reaction : null),
    cleanRules: text => String(text || '').replace(/<[^>]*>/g, '').trim(),
    escapeHtml: text => String(text ?? ''),
    toast() {}, renderTokens() {}, actors: () => [], actorById: () => null, objectById: () => null,
    presentation: () => null, lineOfSight: () => true, askReaction: () => Promise.resolve(null),
    currentViewer: () => ({ready: true}), // these existing picker cases use a visible, ready view
    broadcastActors: () => broadcasts.push(app.pendingChoice ? {...app.pendingChoice} : null),
  };
  const code = [
    slice('function moveHeight()', 'function renderHighlights()'),
    slice('function renderHighlights()', '// A fresh board selection'),
    slice('async function onCellClick(cell)', 'async function moveTo(move)'),
    slice('function askChoice(prompt)', 'async function askReaction(prompt)'),
    slice('document.addEventListener("keydown"', '// Keep a watching table in step'),
    'return {askChoice, onCellClick, cancelMapPick, renderHighlights, pendingChoiceText};',
  ].join('\n');
  const api = new Function(...Object.keys(bindings), code)(...Object.values(bindings));
  return {...api, app, hint, reaction, highlights, bodyClasses, broadcasts,
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
  assert.match(h.hint.innerHTML, /Stay here \(Esc\)/, 'the way out is spelled out, not just "Cancel"');
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
  assert.equal(await pending, 'DECLINE');
});

test('clicking a token on a legal destination chooses its square', () => {
  const start = source.indexOf('function onTokenClick(');
  const end = source.indexOf('\nfunction selectActor(', start);
  assert.ok(start >= 0 && end > start, 'find production token-click handler');
  const committed = [], closed = [], messages = [];
  const destination = {candidate_id: 'blossom-at-enemy', destination: {x: 4, y: 6}};
  const targeting = {byTarget: new Map(), destinations: [destination], resolve: value => committed.push(value)};
  const app = {state: {}, busy: false, targeting};
  const onTokenClick = new Function('app', 'board', 'hint', 'closeChoice', 'act', 'toast', 'objectById',
    source.slice(start, end) + '\nreturn onTokenClick;')(
      app, {cellAt: () => ({x: 4, y: 6})}, () => {}, () => closed.push(true), id => id,
      message => messages.push(message), () => null);
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
  assert.equal(await pending, 'DECLINE');
  assert.equal(h.app.mapPick, null, 'Esc must close the pick on every path, not leave the sheet asking');
  assert.equal(h.hint.hidden, true);
});

test('a map choice that cannot be declined offers no Cancel and ignores Esc', async () => {
  const h = harness();
  const pending = h.askChoice(teleportPrompt(['cell:4,6'], false));
  assert.doesNotMatch(h.pendingChoiceText(), /Cancel|Esc/, 'mandatory choices do not promise a way to decline');
  assert.equal(h.hint.children.filter(child => child.tag === 'button').length, 0, 'no Cancel button to click');
  h.escape({key: 'Escape', target: {closest: () => null}});
  assert.ok(h.app.mapPick, 'a choice with no decline must keep waiting rather than answer for the player');
  h.onCellClick({x: 4, y: 6});
  assert.deepEqual(await pending, {selection: 'USE', option_ids: ['cell:4,6']});
});

test('a choice the engine did not mark keeps the old list dialog', () => {
  const h = harness();
  const prompt = teleportPrompt();
  delete prompt.choice.map_pick;
  // The dialog path is exercised by the table's own tests; here the point is only that nothing is hijacked:
  // askChoice goes straight to the dialog (which needs a real document), and the map picker is never armed.
  assert.throws(() => h.askChoice(prompt), /textContent/, 'an unmarked choice must not touch the map picker');
  assert.equal(h.app.mapPick, null);
  assert.equal(h.highlights.at(-1)?.moves, undefined);
});

test('a marked choice with no square falls back to the list rather than trapping the player', () => {
  const h = harness();
  assert.throws(() => h.askChoice(teleportPrompt([])), /textContent/,
    'nothing to click means the list, not a dead end');
  assert.equal(h.app.mapPick, null);
  assert.equal(h.highlights.at(-1)?.moves, undefined);
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
