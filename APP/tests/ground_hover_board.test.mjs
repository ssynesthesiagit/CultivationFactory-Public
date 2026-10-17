// node --test APP/tests/ground_hover_board.test.mjs
// The board's ground hover, at the level the bug showed: the real board, real map data and the real
// card (MMX96f1; owner 2026-09-30: "hovering over the types of ground for a ... second should bring up
// the type of material and its effects on movement or anything else", then "2 seconds actually").
//
// The pure card builder is covered by static/tabletop/ground-text.test.mjs and the wording by
// tests/test_ground_text_matches_engine.py. Neither touches board.js, so neither would notice a deleted
// rebuildGroundIndex(), a restored pointer guard or 2000 changed to 900. This file drives createBoard
// itself: it builds the per-square index from map data, arms the rest timer, and checks the card only
// appears once the pointer has actually rested for its delay.
//
// The clock is a shim installed only around the pointermove dispatch and removed immediately after, so
// node:test's own timers are never intercepted (corkboard #141).
import test from 'node:test';
import assert from 'node:assert/strict';

import {installDOM} from './objects_dom_stub.mjs';
import {CELL, createBoard} from '../static/tabletop/board.js';
import {previewTerrainZones} from '../static/tabletop/mapeditor-zones.js';

const GROUND = {
  'floor:marble': {name: 'Marble floor', lines: ['Painted ground: the material itself changes nothing.']},
  'cell:difficult': {name: 'Difficult ground', lines: ['Difficult terrain: entering these squares costs twice as much movement.']},
  'cell:cover': {name: 'Cover', lines: ['Cover: that creature\'s Armor Class is 2 higher.',
    'The cover square itself is worth nothing -- the cover has to be BETWEEN the creature and the attacker.']},
  'cell:hazard': {name: 'Hazard', lines: ['Hazard: any creature that moves through these squares makes a Dexterity saving throw of 12.',
    'On a failure it takes 1d4 damage; on a success nothing happens. Each creature is only affected once per turn.']},
  'cell:sight': {name: 'Blocks sight', lines: ['This square blocks line of sight: a creature on one side cannot be seen from the other.',
    'It is not a wall. A creature can walk straight through it.']},
  'structure:wall': {name: 'Wall', lines: ['A wall: it blocks movement and sight, and no creature can be standing in it.']},
  'terrain:fire terrain': {name: 'Fire Terrain', lines: [
    'A hostile creature entering it, or starting its turn inside, makes a Dexterity save and, on a failure, takes Fire damage.',
  ]},
};

// One 8x8 map carrying every kind of square, as a real map's document would.
const MAP = {
  width: 8, height: 8,
  background: {url: null, opacity: 1, style: 'flagstone', seed: 7},
  walls: [], trees: [],
  floors: [{style: 'marble', cells: [[1, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6], [7, 1]]}],
  cells: {
    cover: [{x: 3, y: 3}], hazard: [{x: 4, y: 4}], sight: [{x: 5, y: 5}],
    blocked: [{x: 6, y: 6}], difficult: [{x: 2, y: 2}],
  },
  ground: GROUND,
};
const ASH_ZONE = {
  zone_id: 'zone:typed:actor:factory.x:412', source_definition_id: 'action:typed.factory.x.ASH', owner_id: 'actor:factory.x',
  center: {x: 7, y: 7}, radius_cells: 1, affected_cells: [{x: 7, y: 7}, {x: 7, y: 6}, {x: 6, y: 7}],
  duration_rounds: 10, created_round: 1, active: true,
  trigger_profile: {kind: 'TYPED', name: 'Ashfall', difficult: 'hostile', obscured: 'light', shape: 'sphere', size_ft: 15,
    visual: {material: 'ash', obscured: 'light'}},
};

const cards = new WeakMap();

function build({tokens = [], zones = []} = {}) {
  const document = installDOM('<html><body><div id="v"></div></body></html>');
  const viewport = document.getElementById('v');
  const board = createBoard(viewport, {});
  cards.set(viewport, document.body.querySelector('.tt-hovercard'));
  board.setMap(structuredClone(MAP));
  if (tokens.length) board.setTokens(tokens);
  if (zones.length) board.setZones(zones, {round: 1});
  board.fit();
  return {document, viewport, board};
}

// Client coordinates of the middle of a square, from the board's own current view.
const at = (board, x, y) => {
  const view = board.view;
  return {clientX: view.x + (x + 0.5) * CELL * view.zoom, clientY: view.y + (y + 0.5) * CELL * view.zoom};
};

// A controlled clock, installed only while the pointermove listener runs. `elapse` advances a virtual
// now and fires whatever the board has armed that has come due, so "only after two seconds" is a real
// assertion rather than a sleep.
function installClock() {
  const realSet = globalThis.setTimeout, realClear = globalThis.clearTimeout;
  const armed = {delays: [], cancelled: 0, virtual: 0};
  const pending = new Map();
  let next = 1;
  globalThis.setTimeout = (callback, delay = 0) => {
    const id = next++;
    pending.set(id, {callback, delay: Number(delay) || 0});
    armed.delays.push(Number(delay) || 0);
    return id;
  };
  globalThis.clearTimeout = id => { if (pending.delete(id)) armed.cancelled += 1; };
  armed.restore = () => { globalThis.setTimeout = realSet; globalThis.clearTimeout = realClear; };
  armed.elapse = ms => {
    armed.virtual += ms;
    for (const [id, timer] of [...pending]) {
      if (armed.virtual < timer.delay) continue;
      pending.delete(id);
      timer.callback();
    }
  };
  armed.pending = () => pending.size;
  return armed;
}

async function hover(viewport, board, x, y, extra = {}) {
  const armed = installClock();
  // The shared card tracks document capture before the board's pointer listener.
  await document.dispatch('pointermove', {...at(board, x, y), target: viewport, buttons: 0, ...extra});
  const done = viewport.dispatch('pointermove', {...at(board, x, y), buttons: 0, ...extra});
  armed.restore();
  await done;
  return armed;
}

const tipOf = viewport => cards.get(viewport);
const groundItemOf = viewport => tipOf(viewport).querySelector('.tt-ground-tip');
const itemText = item => (item ? item.children.map(child => child.textContent).join(' | ') : '');

test('ground hover uses bound cross geometry and resets to whole-cell predecessor wording', async () => {
  // Catalog assembly/actual wording is checked by the Python regression; this drives board wiring.
  const geometry = 'Sight stops at two crossing centre lines; gaps near the corners allow sight; the near side stays visible.';
  const catalog = {...GROUND,
    'structure:tree': {name: 'Tree', lines: ['The trunk blocks movement and sight exactly as a wall does.']},
    'cell:sight:centerline': {name: 'Blocks sight', lines: [geometry, 'A creature can walk straight through it.']},
    'structure:tree:centerline': {name: 'Tree', lines: [geometry, 'The trunk blocks movement.']},
  };
  const {viewport, board} = build();
  const map = structuredClone(MAP);
  map.ground = catalog;
  map.centerlineCells = [[5, 5], [6, 6]];
  map.trees = [{x: 6, y: 6, size: 1}];
  for (const thin of [true, false]) {
    map.centerlineCells = thin ? [[5, 5], [6, 6]] : [];
    board.setMap(map);
    for (const [x, y] of [[5, 5], [6, 6]]) {
      const armed = await hover(viewport, board, x, y);
      armed.elapse(2000);
      const text = itemText(groundItemOf(viewport));
      if (thin) {
        assert.match(text, /two crossing centre lines/);
        assert.match(text, /gaps near the corners/);
        assert.match(text, /near side stays visible/);
        assert.doesNotMatch(text, /exactly as a wall|nobody can attack or target/);
      } else {
        assert.doesNotMatch(text, /crossing centre lines|gaps near the corners/);
        assert.match(text, x === 5 ? /cannot be seen from the other/ : /exactly as a wall/);
      }
      assert.match(text, x === 5 ? /walk straight through/ : /blocks movement/);
    }
  }
});

test('a ground square names its material only after the pointer has rested two seconds', async () => {
  const {viewport, board} = build();
  const armed = await hover(viewport, board, 1, 1);
  assert.deepEqual(armed.delays, [2000], 'ground alone waits the two seconds the owner asked for');
  armed.elapse(1999);
  assert.equal(tipOf(viewport).hidden, true, 'the card must not flash before the rest is over');
  armed.elapse(1);
  assert.equal(tipOf(viewport).hidden, false, 'at two seconds the card is up');
  assert.equal(itemText(groundItemOf(viewport)), 'Marble floor | Painted ground: the material itself changes nothing.');
});

test('a square the map painted is read through the per-square index rebuilt on setMap', async () => {
  const {viewport, board} = build();
  const cases = [
    [3, 3, 'Cover', /BETWEEN the creature and the attacker/],
    [4, 4, 'Hazard', /Dexterity saving throw of 12/],
    [2, 2, 'Difficult ground', /twice as much movement/],
    [5, 5, 'Blocks sight', /walk straight through it/],
    [6, 6, 'Wall', /blocks movement and sight/],
  ];
  for (const [x, y, title, pattern] of cases) {
    const armed = await hover(viewport, board, x, y);
    armed.elapse(2000);
    const item = groundItemOf(viewport);
    assert.equal(item.children[0].textContent, title, `square ${x},${y}`);
    assert.match(itemText(item), /Material: Marble floor/, `square ${x},${y} must name its painted floor`);
    assert.match(itemText(item), pattern, `square ${x},${y}`);
  }
});

test('a sight-only square is described as blocking sight, not as a wall', async () => {
  const {viewport, board} = build();
  const armed = await hover(viewport, board, 5, 5);
  armed.elapse(2000);
  const item = groundItemOf(viewport);
  assert.ok(item, 'a map.cells.sight square must reach the card');
  assert.equal(item.children[0].textContent, 'Blocks sight');
  assert.match(itemText(item), /walk straight through it/);
  assert.doesNotMatch(itemText(item), /no creature can be standing in it/);
});

test('a solid wall is still a wall, and says so rather than claiming a creature can stand there', async () => {
  const {viewport, board} = build();
  const armed = await hover(viewport, board, 6, 6);
  armed.elapse(2000);
  assert.equal(groundItemOf(viewport).children[0].textContent, 'Wall');
});

test('leaving the board or pressing cancels the card and it never appears late', async () => {
  for (const event of ['pointerleave', 'pointerdown']) {
    const {viewport, board} = build();
    // One clock across the arm and the cancel, so the board's own clearTimeout is the one observed.
    const clock = installClock();
    const arming = viewport.dispatch('pointermove', {...at(board, 1, 1), buttons: 0});
    const cancelling = viewport.dispatch(event, {...at(board, 1, 1), buttons: 0});
    clock.restore();
    await Promise.all([arming, cancelling]);
    assert.deepEqual(clock.delays, event === 'pointerleave' ? [2000, 300] : [2000], `${event}: the rest timer was armed first; leaving also arms the shared card's grace timer`);
    assert.equal(clock.cancelled, 1, `${event} should cancel the rest timer`);
    assert.equal(tipOf(viewport).hidden, true, `${event} should hide the card`);
    clock.elapse(5000);
    assert.equal(tipOf(viewport).hidden, true, `${event} must not let a stale card flash`);
  }
});

test('moving to another square cancels the card it had and starts a fresh rest', async () => {
  const {viewport, board} = build();
  const clock = installClock();
  const arming = viewport.dispatch('pointermove', {...at(board, 1, 1), buttons: 0});
  const moving = viewport.dispatch('pointermove', {...at(board, 4, 4), buttons: 0});
  clock.restore();
  await Promise.all([arming, moving]);
  assert.equal(clock.cancelled, 1, 'moving must cancel the timer the previous square armed');
  assert.equal(tipOf(viewport).hidden, true, 'the old card goes away at once, before the new rest');
  assert.deepEqual(clock.delays, [2000, 2000], 'the new square gets its own two-second rest');
  clock.elapse(2000);
  assert.equal(groundItemOf(viewport).children[0].textContent, 'Hazard', 'and it is the new square that answers');
});

test('an active area and a movement destination keep the shorter zone delay', async () => {
  const {viewport, board} = build({zones: [ASH_ZONE]});
  const zoned = await hover(viewport, board, 7, 7);
  assert.deepEqual(zoned.delays, [900], 'an active area answers at the zone delay');
  zoned.elapse(900);
  assert.equal(tipOf(viewport).hidden, false);

  const {viewport: other, board: otherBoard} = build();
  otherBoard.setMovementExplanation({destinations: {'2,2': {available: true, movement_cost_ft: 10, reasons: []}}});
  const moving = await hover(other, otherBoard, 2, 2);
  assert.deepEqual(moving.delays, [900], 'a movement destination answers at the zone delay');
  moving.elapse(900);
  assert.equal(tipOf(other).hidden, false);
});

test('a token keeps its own creature card and never inherits its square ground', async () => {
  const {document, viewport, board} = build({
    tokens: [{id: 'actor:1', name: 'Fighter', x: 1, y: 1, current_hp: 12, max_hp: 20, team_id: 'team1'}],
  });
  const tokenNode = board.tokenNode('actor:1');
  assert.ok(tokenNode, 'the token should be drawn');
  tokenNode.getBoundingClientRect = () => {
    const point = at(board, 1, 1);
    return {left: point.clientX - 20, top: point.clientY - 20,
      right: point.clientX + 20, bottom: point.clientY + 20, width: 40, height: 40};
  };
  const tokenClock = installClock();
  await tokenNode.dispatch('pointerenter', {});
  tokenClock.elapse(550);  // the creature card opens after the 500 ms hover delay
  tokenClock.restore();
  const tokenCard = document.body.querySelector('.tt-token-card');
  assert.equal(tokenCard.hidden, false, 'a creature card is up');
  assert.match(tokenCard.innerHTML, /Fighter/, 'the card names the creature');
  assert.equal(groundItemOf(viewport), null, "a token's square ground must not take over its card");
  // And the ground card is still there for the rest of the board once the pointer is elsewhere.
  const armed = await hover(viewport, board, 4, 4);
  armed.elapse(2000);
  assert.equal(tipOf(viewport).hidden, false);
  assert.equal(groundItemOf(viewport).children[0].textContent, 'Hazard');
});

// Named terrain the map itself painted (OC13). combat/zones.py map_zones raises one area per painted
// "terrain:<name>" row -- the map editor previews the same areas -- and the ground card had no
// terrain: branch and the board never passed one, so a Fire Terrain square read "Marble floor --
// the material itself changes nothing" while the square burned.
const FIRE_TERRAIN_ZONE = {
  zone_id: 'zone:map:1', source_definition_id: 'system:battlefield.terrain', owner_id: 'system:battlefield.map',
  center: {x: 7, y: 1}, radius_cells: 0, affected_cells: [{x: 7, y: 1}, {x: 7, y: 2}],
  duration_rounds: null, created_round: 0, active: true,
  trigger_profile: {kind: 'TYPED', name: 'Fire Terrain', terrain: ['fire terrain'], map: true,
    difficult: null, obscured: 'light', color: '#e0662e', shape: 'painted', size_ft: 5, triggers: [],
    move_through: null, talents: [], inside: [], natural_haze: false, visual: {material: 'fire'},
    numbers: {save_dc: 13, pb: 2, cl: 1}},
};

test('mixed sight-mode bamboo preview retains both stands and hover effects on repeated board rendering', async () => {
  const materials=['cell','centerline'].map((occluder,i)=>({material:'terrain:bamboo thicket',occluder,cells:[[1+i*3,2]]}));
  const rows=previewTerrainZones(materials,[{name:'bamboo thicket',label:'Bamboo Thicket',difficult:true,obscured:'light',material:'bamboo'}]);
  assert.equal(new Set(rows.map(row=>row.zone_id)).size,2);
  const {viewport,board,document}=build({zones:rows});
  const scenery=document.querySelectorAll('.tt-zone-ground').length;
  assert.ok(scenery>=2,'both stands retain scenery');
  for(let pass=0;pass<3;pass++) {
    board.setZones(pass % 2 ? [...rows].reverse() : rows,{round:1});
    assert.equal(document.querySelectorAll('.tt-zone-ground').length,scenery);
    for(const x of [1,4]) {
      const armed=await hover(viewport,board,x,2); armed.elapse(2000);
      const items=tipOf(viewport).querySelectorAll('.tt-zone-tip-item');
      const text=items.map(itemText).join(' | ');
      assert.match(text,/Bamboo Thicket/);
      assert.match(text,/difficult/i);
      assert.match(text,/light/i);
    }
  }
});

test('a square with map-painted named terrain is named by its terrain, not only by its paint', async () => {
  const {viewport, board} = build({zones: [FIRE_TERRAIN_ZONE]});
  const armed = await hover(viewport, board, 7, 1);
  armed.elapse(2000);
  const item = groundItemOf(viewport);
  assert.ok(item, 'a painted terrain square must reach the ground card');
  assert.equal(item.children[0].textContent, 'Fire Terrain');
  assert.match(itemText(item), /Material: Marble floor/, 'the paint is still named as the material');
  assert.match(itemText(item), /Dexterity save/, 'and the terrain says what it does');
  // A square beside it is still plain ground, so the terrain is read per square and not globally.
  const other = await hover(viewport, board, 1, 1);
  other.elapse(2000);
  assert.equal(groundItemOf(viewport).children[0].textContent, 'Marble floor');
});
