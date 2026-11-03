// Deterministic production board/height-picker/controller checks. This stub
// checks DOM state and event wiring, not rendered browser pixels.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {detectRoofRegions, roofSettings, roofWalkFt, roofOpacity, belowRoof, roofLevelsAt, onRoof} from '../static/tabletop/roof-regions.js';
import {heightControl, heightOptions, heightMovement, flightText, movesAtHeight, movementVerb, routeText, startHeightLevel} from '../static/tabletop/flight-ui.js';
import {editRoofField, writeRoofOpening, removeRoofOpening} from '../static/tabletop/roof-editor.js';

const timers = {setTimeout: globalThis.setTimeout, setInterval: globalThis.setInterval};
function dom() {
  const document = installDOM('<body></body>');
  Object.assign(globalThis, timers);
  globalThis.requestAnimationFrame = callback => setTimeout(callback, 0);
  return document;
}
function house(overrides = {}) {
  return {width: 10, height: 10, background: {style: 'grass', opacity: 1},
    walls: [{shape: 'rect', points: [[2, 2], [7, 7]], blocks: 'movement', filled: false}],
    floors: [{style: 'wood', cells: Array.from({length: 16}, (_, i) => [3 + i % 4, 3 + Math.floor(i / 4)])}], ...overrides};
}
function token(x, y, z, extra = {}) {
  return {id: 'own', name: 'Rooftop walker', x, y, z, position: {x, y, z}, altitudeFt: z * 5,
    fly_speed_ft: 0, hp: 10, maxHp: 10, conditions: [], ...extra};
}
function boardFor(map = house(), at = token(3, 3, 3)) {
  dom();
  const board = createBoard(document.body);
  board.setMap(map); board.setTokens([at]);
  board.setRoofView({gm: false, viewers: [{entity_id: at.id, position: at.position}]});
  return {board, node: board.tokenNode(at.id), roof: board.element.querySelector('[data-roof]')};
}

test('roof height defaults to enclosing finite walls, with global and building overrides', () => {
  const [legacy] = detectRoofRegions(house());
  assert.equal(roofSettings(legacy).height_ft, 15, 'no walls: the roof sits 5 ft above the default wall height');
  const map = house(); map.walls[0].height_ft = 12;
  const [region] = detectRoofRegions(map);
  assert.equal(roofSettings(region).height_ft, 17, 'sight uses the exact whole-foot roof top');
  assert.equal(roofWalkFt(region), 15, 'standing on the roof rounds the top to the nearest 5 ft');
  assert.equal(roofSettings(region, {height_ft: 20}).height_ft, 20);
  assert.equal(roofSettings(region, {height_ft: 20, regions: [{x: 3, y: 3, height_ft: 25}]}).height_ft, 25);
  assert.equal(roofSettings(region, {height_ft: 7}).height_ft, 7, 'an authored whole-foot roof height is kept exactly');
});

test('the same roof square fades only for a viewer below its height', () => {
  const map = house(), [region] = detectRoofRegions(map);
  for (const z of [0, 1, 2, 3, 4]) {
    const viewer = {position: {x: 3, y: 3, z}};
    assert.equal(roofOpacity(region, {viewers: [viewer]}), z < 3 ? 0 : 1);
    assert.equal(belowRoof(region, viewer), z < 3);
    assert.equal(roofOpacity(region, {viewers: [{position: {x: 0, y: 0, z: 0}}]}), 1, 'another seat stays outside');
  }
  assert.equal(roofOpacity(region, {gm: true, viewers: [{position: {x: 3, y: 3, z: 3}}]}), .28);
});

test('standing requires exact height and some solid footprint support; an open hatch is not a surface', () => {
  const map = house(), actor = token(3, 3, 3);
  assert.equal(onRoof(map, actor), true);
  assert.equal(onRoof(map, token(3, 3, 4)), false, 'flying above a roof is not standing on it');
  assert.deepEqual(roofLevelsAt(map, actor), [3]);
  map.roofs = {openings: [{x: 3, y: 3, kind: 'trapdoor', open: true}]};
  assert.equal(onRoof(map, actor), false);
  assert.deepEqual(roofLevelsAt(map, actor), [3], 'opening retains the building reference height');
  assert.equal(onRoof(map, {...actor, footprint: {width_cells: 2, height_cells: 1}}), true);
  map.roofs.openings[0] = {x: 3, y: 3, kind: 'skylight', open: false};
  assert.equal(onRoof(map, actor), true, 'closed glass uses the documented load-bearing convention');
  assert.match(flightText(actor, map), /on the roof \(15 ft\)/);
  assert.doesNotMatch(flightText(token(3, 3, 4), map), /on the roof/);
});

test('editor data helpers keep inheritance, validate heights and round-trip open/closed apertures', () => {
  const map = house(), regions = detectRoofRegions(map), doc = {width_squares: 10, height_squares: 10};
  editRoofField(doc, null, 'height_ft', 20);
  editRoofField(doc, regions[0], 'height_ft', 15);
  assert.equal(roofSettings(regions[0], doc.roofs).height_ft, 15);
  editRoofField(doc, regions[0], 'height_ft', null);
  assert.equal(roofSettings(regions[0], doc.roofs).height_ft, 20);
  writeRoofOpening(doc, regions, {x: 3, y: 3, kind: 'trapdoor'});
  assert.equal(doc.roofs.openings[0].open, false);
  writeRoofOpening(doc, regions, {x: 4, y: 3, kind: 'skylight', open: true}, '3,3');
  assert.deepEqual(JSON.parse(JSON.stringify(doc)).roofs.openings, [{x: 4, y: 3, kind: 'skylight', open: true}]);
  assert.throws(() => writeRoofOpening(doc, regions, {x: 0, y: 0, kind: 'trapdoor', open: true}), /enabled building roof/);
  assert.throws(() => writeRoofOpening(doc, regions, {x: 3, y: 3, kind: 'hole'}), /trapdoor or skylight/);
  removeRoofOpening(doc, '4,3'); assert.deepEqual(doc.roofs.openings, []);
});

test('real height picker marks local roof height without inventing a move through a solid roof', async () => {
  dom();
  const actor = token(3, 3, 0), moves = [{destination: {x: 4, y: 3, z: 0}, candidate_id: 'walk', cost_ft: 5}];
  const levels = roofLevelsAt(house(), actor), chosen = [];
  assert.deepEqual(heightOptions(moves, 0, levels), [0, 3]);
  const control = heightControl(moves, 0, false, z => chosen.push(z), actor, levels);
  const picker = control.querySelector('select');
  assert.deepEqual(picker.options.map(row => row.textContent), ['0 ft', '15 ft · roof']);
  picker.value = '3'; await picker.dispatch('change');
  assert.deepEqual(chosen, [3]); assert.deepEqual(movesAtHeight(moves, 3), []);
  const cards = heightMovement({destinations: {'4,3': {available: true}}}, moves, 3);
  assert.equal(cards.destinations['4,3'].available, false);
});

test('real board keeps a non-flyer above a visible roof, with height badge and roof hover text', async () => {
  const {node, roof} = boardFor();
  assert.equal(roof.style.opacity, '1');
  assert.equal(node.parentNode.classList.contains('tt-roof-interior'), false);
  assert.equal(node.querySelector('.tt-token-height').hidden, false);
  assert.equal(node.querySelector('.tt-token-height').textContent, '↑15 ft');
  assert.match(node.getAttribute('aria-label'), /on the roof \(15 ft\)/);
  await node.dispatch('pointerenter');
  await new Promise(resolve => setTimeout(resolve, 550));  // token cards open after the 500 ms hover delay
  assert.match(document.querySelector('.tt-token-card').innerHTML, /on the roof \(15 ft\)/);
});

test('legal roof destinations and paths render above roofs but beneath fog and tokens', () => {
  const {board, roof} = boardFor();
  board.setHighlights({moves: [{x: 3, y: 3, z: 0}, {x: 4, y: 3, z: 3}],
    path: [{x: 0, y: 3, z: 0}, {x: 1, y: 3, z: 0}, {x: 2, y: 3, z: 3}, {x: 4, y: 3, z: 3}]});
  const high = board.element.querySelector('.tt-roof-marks'), low = board.element.querySelector('.tt-marks');
  assert.equal(high.querySelectorAll('.tt-mark-move').length, 1);
  assert.equal(low.querySelectorAll('.tt-mark-move').length, 1, 'ground destinations remain under the roof');
  assert.equal(high.querySelectorAll('.tt-mark-path').length, 1);
  assert.equal(low.querySelectorAll('.tt-mark-path').length, 1, 'mixed-height routes change layers at the roof edge');
  const siblings = board.element.children;
  assert.ok(siblings.indexOf(high) > siblings.indexOf(roof.parentNode));
  assert.ok(siblings.indexOf(high) < siblings.indexOf(board.element.querySelector('.tt-fog')));
  assert.ok(siblings.indexOf(high) < siblings.indexOf(board.tokenNode('own').parentNode));
});

test('drawn x/y/z govern roof visibility and layering through stale-state ascent and a hatch descent', async () => {
  const map = house({roofs: {openings: [{x: 3, y: 3, kind: 'trapdoor', open: true}]}});
  const origin = token(0, 3, 3), {board, node, roof} = boardFor(map, origin);
  await board.animateMove('own', [{x: 0, y: 3, z: 3}, {x: 3, y: 3, z: 3}, {x: 4, y: 3, z: 3}], {stepMs: 1});
  assert.equal(roof.style.opacity, '1', 'stale origin z and x/y do not fade a rooftop viewer');
  assert.equal(node.parentNode.classList.contains('tt-roof-interior'), false);
  assert.match(node.querySelector('.tt-token-height').title, /on the roof \(15 ft\)/);
  await node.dispatch('pointerenter');
  await new Promise(resolve => setTimeout(resolve, 550));  // token cards open after the 500 ms hover delay
  assert.match(document.querySelector('.tt-token-card').innerHTML, /on the roof \(15 ft\)/);
  await board.animateMove('own', [{x: 4, y: 3, z: 3}, {x: 3, y: 3, z: 3}, {x: 3, y: 3, z: 2}, {x: 3, y: 3, z: 0}], {stepMs: 1});
  assert.equal(roof.style.opacity, '0', 'the drawn viewer is now inside below the roof');
  assert.equal(node.querySelector('.tt-token-height').hidden, true);
  board.setRoofView({gm: true});
  assert.equal(node.parentNode.classList.contains('tt-roof-interior'), true, 'stale nested origin cannot put a below-roof token above the roof');
  await board.animateMove('own', [{x: 3, y: 3, z: 0}, {x: 4, y: 3, z: 3}], {teleport: true});
  board.setRoofView({gm: false});
  assert.equal(roof.style.opacity, '1', 'a blink lands with its recorded height before fresh state arrives');
  assert.equal(node.parentNode.classList.contains('tt-roof-interior'), false);
  assert.equal(node.querySelector('.tt-token-height').textContent, '↑15 ft');
});

test('production table click and moveTo submit engine-issued climb/jump-down candidates unchanged', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const block = name => { const at = source.indexOf(`function ${name}(`); assert.ok(at >= 0); return source.slice(at, source.indexOf('\n}', at) + 2); };
  const actor = token(3, 3, 0), up = {candidate_id: 'climb-roof', movement_mode: 'climb', destination: {x: 4, y: 3, z: 3}, cost_ft: 30, path: []};
  const down = {candidate_id: 'jump-roof', movement_mode: 'jump_down', destination: {x: 1, y: 3, z: 3}, cost_ft: 10,
    path: [{x: 3, y: 3, z: 3}, {x: 2, y: 3, z: 3}, {x: 1, y: 3, z: 3}]};
  const app = {menu: {actor_id: 'own', decision_id: 'up', moves: [up]}, showMoves: true, busy: false};
  const sent = [], bindings = {app, actorById: () => actor, movesAtHeight, startHeightLevel, renderHighlights() {}, act: async id => { sent.push(id); return true; }};
  const harness = new Function(...Object.keys(bindings), `${block('moveHeight')}\n${block('selectedMoves')}\nasync ${block('onCellClick')}\nasync ${block('moveTo')}\nreturn {click:onCellClick, height:moveHeight};`)(...Object.values(bindings));
  harness.height(); app.moveHeight = 3; await harness.click(up.destination);
  assert.deepEqual(sent, ['climb-roof']); assert.equal(app.pendingMove, null);
  actor.position.z = 3; app.menu = {actor_id: 'own', decision_id: 'down', moves: [down]};
  harness.height(); app.moveHeight = 3; await harness.click(down.destination);
  assert.deepEqual(sent, ['climb-roof', 'jump-roof']);
  assert.equal(movementVerb(up), 'Climb'); assert.equal(movementVerb(down), 'Jump down');
  assert.match(routeText(up), /Costs 30 ft.*includes climbing/);
  assert.match(routeText(down), /Falling can cause damage/);
  assert.match(heightMovement({destinations: {}}, [down], 3).destinations['1,3'].reasons[0].message, /Jump down/);
});
