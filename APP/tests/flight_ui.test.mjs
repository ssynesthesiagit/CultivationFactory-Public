import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {createHoverCard, bindTipTargets} from '../static/tabletop/hovercard.js';
import {appendTip, heightControl, heightControlText, altitudeBadge, heightFeet, flightText, heightOptions, movesAtHeight, heightMovement, startHeightLevel, movementVerb, routeText} from '../static/tabletop/flight-ui.js';

const moves = [0, 1, 2].map(z => ({candidate_id: `move-${z}`, destination: {x: 3, y: 4, z}, cost_ft: z * 5, path: []}));
const timers = {setTimeout: globalThis.setTimeout, setInterval: globalThis.setInterval};
function dom() { installDOM('<body></body>'); Object.assign(globalThis, timers); }

test('compact height labels separate current altitude from the chosen destination', () => {
  const text = heightControlText({position: {z: 0}, fly_speed_ft: 30}, 6, true);
  assert.equal(text.caption, 'Fly to height:');
  assert.equal(text.current, 'Now 0 ft');
  assert.match(text.tip, /Selected destination: 30 ft/);
  assert.match(text.tip, /Route cost appears on hover/);
  assert.equal(heightControlText({altitude_ft: 30}, 0, false).current, 'Now 30 ft');
  assert.equal(heightFeet({position: {z: 6}}), 30);
  assert.equal(heightFeet({altitude_ft: 0, position: {z: 6}}), 0);
});

test('altitude decorations are positive-height only and respect token visibility', () => {
  assert.equal(altitudeBadge({altitudeFt: 30}), '↑30 ft');
  for (const altitudeFt of [undefined, 0, -5]) assert.equal(altitudeBadge({altitudeFt}), '');
  assert.equal(altitudeBadge({altitudeFt: 30, hidden: true}), '');
  for (const flag of ['item', 'object']) assert.equal(altitudeBadge({altitudeFt: 30, [flag]: true}), '↑30 ft');
});

test('engine routes at the same square remain distinct and their quoted costs are shown', () => {
  assert.deepEqual(heightOptions(moves), [0, 1, 2]);
  assert.equal(movesAtHeight(moves, 2)[0].candidate_id, 'move-2');
  assert.deepEqual(movesAtHeight(moves, 3), []);
  const cards = heightMovement({summary: {}, destinations: {'8,8': {available: true}}}, moves, 2);
  assert.equal(cards.destinations['8,8'].available, false);
  assert.match(cards.destinations['3,4'].reasons[0].message, /height 10 ft.*Costs 10 ft/);
  assert.equal(heightFeet({position: {z: 2}}), 10);
});

test('real height control offers only issued levels and the current level', async () => {
  dom();
  const chosen = [];
  const control = heightControl(moves, 1, true, z => chosen.push(z));
  const select = control.querySelector('select');
  assert.equal(select.getAttribute('aria-label'), 'Fly to height');
  assert.deepEqual([...select.children].map(row => row.textContent), ['0 ft', '5 ft', '10 ft']);
  assert.equal(select.value, '1');
  select.value = '2';
  await select.dispatch('change');
  assert.deepEqual(chosen, [2]);
  const planned = heightControl(moves, 2, true, () => {}, {position: {z: 0}});
  assert.equal(planned.querySelector('.tt-flight-now').textContent, 'Now 0 ft');
  assert.equal(planned.querySelector('p'), null);
});

test('focusing the height selector opens flight instructions in the shared card', async () => {
  dom();
  for (const flying of [true, false]) {
    const control = heightControl(moves, 2, flying, () => {}, {position: {z: 0}, fly_speed_ft: flying ? 30 : 0});
    document.body.appendChild(control);
    const select = control.querySelector('select');
    const instructions = select.getAttribute('aria-description');
    assert.match(instructions, /Choose a height, then a blue square\. Route cost appears on hover\./);
    assert.match(instructions, /Selected destination: 10 ft/);
    assert.equal(select.dataset.tip, instructions);
    assert.equal(control.title || '', '', 'no native tooltip');
    assert.equal(select.getAttribute('title'), null);
    assert.equal(control.children.length, 3, 'instructions add no visible row');
    // This stub does not reflect dataset writes into attributes as a browser does.
    select.setAttribute('data-tip', select.dataset.tip);
    const card = createHoverCard({doc: document, win: window, setTimer: () => 1, clearTimer() {}});
    const binding = bindTipTargets(card, document);
    // Model the bubbling focus event from the actual production select, not its label.
    await document.dispatch('focusin', {target: select});
    assert.equal(card.isOpen, true);
    assert.equal(card.trigger, select);
    assert.equal(card.node.textContent, instructions);
    assert.equal(select.getAttribute('aria-describedby'), card.node.id);
    card.close();
    assert.equal(select.getAttribute('aria-description'), instructions, 'description survives card dismissal');
    binding.dispose();
    control.remove();
  }
});

test('real board renders and clears height badge independently of condition and life badges', async () => {
  dom();
  const host = document.createElement('div');
  document.body.appendChild(host);
  const board = createBoard(host);
  const actor = {id: 'a', x: 3, y: 4, name: 'Flyer', hp: 10, maxHp: 10, altitudeFt: 10,
    badge: 'Stable', conditions: [], flightDetail: flightText({altitude_ft: 10, fly_speed_ft: 20})};
  board.setTokens([actor]);
  const node = board.tokenNode('a');
  assert.equal(node.querySelector('.tt-token-height').textContent, '↑10 ft');
  assert.equal(node.querySelector('.tt-token-height').hidden, false);
  assert.ok(node.classList.contains('is-airborne'));
  assert.match(node.getAttribute('aria-label'), /height 10 feet/);
  assert.match(actor.flightDetail, /Height: 10 ft.*Fly speed: 20 ft/);
  await node.dispatch('pointerenter');
  await new Promise(resolve => setTimeout(resolve, 550));  // token cards open after the 500 ms hover delay (owner 2026-10-11)
  // This DOM stub records assigned markup, but does not parse text nodes.
  assert.match(document.querySelector('.tt-token-card').innerHTML, /Height: 10 ft.*Fly speed: 20 ft/);
  board.setTokens([{...actor, altitudeFt: 0}]);
  assert.equal(node.querySelector('.tt-token-height').hidden, true);
  assert.equal(node.classList.contains('is-airborne'), false);
  board.setTokens([{...actor, hidden: true}]);
  assert.equal(node.querySelector('.tt-token-height').textContent, '');
  assert.equal(node.classList.contains('is-airborne'), false);
});

test('Move group puts flight controls and the vertical card in its existing button row', () => {
  dom();
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  // Owner-approved since this test was written: the height control and vertical card sit in a roof-aware block
  // that starts at the appendTip note (roof levels and jump-down added by f583b198 and later).
  const start = source.indexOf('  // Movement notes go in the hover card of the control they explain (appendTip)');
  const block = source.slice(start, source.indexOf('  if (menu.movement_explanation', start));
  const moveGroup = document.createElement('div');
  moveGroup.innerHTML = '<h3>Move</h3><div class="tt-ab-buttons"></div>';
  const moveButtons = moveGroup.querySelector('.tt-ab-buttons');
  const actor = {position: {x: 3, y: 4, z: 0}, fly_speed_ft: 30};
  const app = {};
  new Function('actor', 'menu', 'moveGroup', 'moveButtons', 'board', 'roofLevelsAt', 'heightControl', 'moveHeight', 'app',
    'renderHighlights', 'renderActionBar', 'selectedMoves', 'makeButton', 'moveTo', 'heightFeet', 'movementVerb', 'routeText', 'level', 'roofLevels', 'appendTip', block)(
    actor, {moves}, moveGroup, moveButtons, {map: null}, () => [], heightControl, () => 2, app, () => {}, () => {},
    () => movesAtHeight(moves, 2), () => document.createElement('button'), () => {}, heightFeet, movementVerb, routeText, 2, [], appendTip);
  assert.equal(moveGroup.children.length, 2, 'no extra stacked flight rows');
  const row = moveGroup.querySelector('.tt-ab-buttons');
  assert.equal(row.children.length, 2);
  assert.equal(row.children[0].className, 'tt-flight-control');
  assert.equal(row.children[1].tagName, 'BUTTON');
});

test('table click sends the chosen height candidate and actor messages carry sheet flight values', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const block = name => {
    const start = source.indexOf(`function ${name}(`);
    return source.slice(start, source.indexOf('\n}', start) + 2);
  };
  const actor = {position: {x: 3, y: 4, z: 0}};
  const app = {menu: {actor_id: 'a', decision_id: 'd', moves}, showMoves: true};
  const sent = [];
  const harness = new Function('app', 'actorById', 'movesAtHeight', 'moveTo', 'startHeightLevel',
    `${block('moveHeight')}\n${block('selectedMoves')}\nasync ${block('onCellClick')}\nreturn {moveHeight, click: onCellClick};`
  )(app, () => actor, movesAtHeight, row => sent.push(row.candidate_id), startHeightLevel);
  harness.moveHeight();
  app.moveHeight = 2;
  await harness.click({x: 3, y: 4});
  assert.deepEqual(sent, ['move-2']);
  assert.match(block('actorMessage'), /fly_speed_ft: actor.fly_speed_ft, altitude_ft: actor.altitude_ft/);
  app.menu = {...app.menu, decision_id: 'next'};
  actor.position.z = 1;
  assert.equal(harness.moveHeight(), 1, 'a new decision starts at the committed height');
});

test('clicking either square of a Large token submits that square at the selected height', () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function onTokenClick(');
  const code = source.slice(start, source.indexOf('\n}', start) + 2);
  const sent = [];
  const routes = [3, 4].map(x => ({candidate_id: `above-${x}`, destination: {x, y: 4, z: 2}}));
  const app = {state: {}, menu: {}, showMoves: true, selected: new Set()};
  const board = {cellAt: (x, y) => ({x, y})};
  const click = new Function('app', 'board', 'actorById', 'moveHeight', 'selectedMoves', 'moveTo',
    'renderTokens', 'renderRoster', 'renderInspector', code + '\nreturn onTokenClick;')(
    app, board, () => ({size: 'Large', position: {x: 3, y: 4}}), () => 2, () => routes,
    row => sent.push(row.candidate_id), () => {}, () => {}, () => {});
  click('a', {clientX: 4, clientY: 4});
  click('a', {clientX: 3, clientY: 4});
  assert.deepEqual(sent, ['above-4', 'above-3']);
  routes.shift(); // Only the far footprint square has a legal issued route.
  click('a', {clientX: 4, clientY: 4});
  assert.equal(sent.at(-1), 'above-4');
  assert.equal(sent.length, 3);
  assert.equal(app.selected.size, 0);
  click('a', {clientX: 3, clientY: 4});
  assert.equal(sent.length, 3, 'no route means selection, never a different square');
  assert.ok(app.selected.has('a'));
});

test('table moveHeight starts at an airborne actor\'s altitude when the row has no position.z (owner 2026-10-12)', () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function moveHeight(');
  const body = source.slice(start, source.indexOf('\n}', start) + 2);
  const actor = {position: {x: 3, y: 4}, altitude_ft: 20};
  const app = {menu: {actor_id: 'a', decision_id: 'fresh', moves}};
  const moveHeight = new Function('app', 'actorById', 'startHeightLevel', `${body}\nreturn moveHeight;`)(app, () => actor, startHeightLevel);
  assert.equal(moveHeight(), 4, 'a 20 ft flyer starts its picker at 20 ft, not the ground');
  app.menu = {actor_id: 'a', decision_id: 'next', moves};
  actor.altitude_ft = 0;
  assert.equal(moveHeight(), 0, 'a new decision re-reads the current height');
});

test('Move group instructions stay in hover cards, never a visible paragraph that stretches the action bar', async () => {
  // Owner 2026-10-13: a wrapped height-instructions paragraph in the narrow Move group made the whole bar tall.
  const {readFile} = await import('node:fs/promises');
  const source = await readFile(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('const moveButtons = moveGroup.querySelector(".tt-ab-buttons");');
  const end = source.indexOf('if (menu.movement_explanation?.summary)', start);
  assert.ok(start > 0 && end > start, 'Move group section found');
  const section = source.slice(start, end);
  assert.doesNotMatch(section, /createElement\(['"]p['"]\)/);
  assert.match(section, /appendTip\(control, 'A solid roof blocks passage/);
  assert.match(section, /appendTip\(moveButtons\.lastElementChild, `Jump down from/);
});

test('appendTip adds the note to the control hover card and accessible description without a visible row', () => {
  dom();
  const control = heightControl(moves, 1, true, () => {}, {position: {z: 1}, fly_speed_ft: 30});
  const before = control.children.length;
  const select = appendTip(control, 'A solid roof blocks passage; use an open trapdoor or skylight to pass through it.');
  assert.equal(select, control.querySelector('select'));
  assert.match(select.dataset.tip, /Choose a height, then a blue square\..*A solid roof blocks passage/);
  assert.equal(select.getAttribute('aria-description'), select.dataset.tip);
  assert.equal(control.children.length, before, 'no visible row added');
  const wrap = document.createElement('div');
  const button = document.createElement('button');
  wrap.appendChild(button);
  appendTip(wrap, 'Jump down from 10 ft. Falling can cause damage and knock you prone.');
  assert.match(button.dataset.tip, /^Jump down from 10 ft/);
  assert.equal(button.getAttribute('aria-description'), button.dataset.tip);
});
