// DOORMARK1 (owner 2026-10-21, looking at a building map: "i cant see any doors, we should make the door knobs or some
// kind of thing sticking out so we can tell theres a door in the location from overhead"). These pin the drawn door
// markers (leaf, hinge edge, handle, threshold, padlock, bar), the table's door state reaching that drawing, the plain
// hover sentence, and the fog rule that a door may only be lifted above a drawn roof while the server says it is seen.
import test from 'node:test';
import assert from 'node:assert/strict';
import {objectArt} from '../static/tabletop/object-art.js';
import {doorMarkerAboveRoof, tableObjectTokens} from '../static/tabletop/object-presentation.js';
import {doorDetail} from '../static/tabletop/door-interaction.js';
import {createBoard} from '../static/tabletop/board.js';
import {installDOM} from './objects_dom_stub.mjs';

const door = (extra = {}) => ({
  id: 'object:map.1', kind: 'door', x: 4, y: 3, mount_axis: 'h', mount_line: 300,
  name: 'Ancestral hall door', interaction: 'simple_door', hp: 18, max_hp: 18, ac: 15,
  open: false, door_locked: 0, door_jammed: 0, ...extra,
});
const marked = (art, cls) => art.includes(`class="${cls}"`);
const token = (object, {seen = null, perceived = null} = {}) =>
  tableObjectTokens([object], new Set([object.id]), [], seen, 8, '', perceived)[0];

test('every door draws a leaf, a hinge edge, a handle and a threshold line from straight overhead', () => {
  const art = objectArt('door');
  for (const cls of ['tt-door-leaf', 'tt-door-hinge', 'tt-door-handle', 'tt-door-threshold']) {
    assert.ok(marked(art, cls), `the closed door must draw ${cls}`);
  }
  // The handle and hinge stand outside the leaf, not only inside the wall band, so they are visible at one square.
  assert.match(art, /<circle[^>]*cx="50.2"[^>]*cy="40.6"/, 'the knob reaches into the room past the leaf');
  assert.match(art, /<circle[^>]*cy="22.6"/, 'a hinge knuckle stands proud of the leaf');
});

test('the open door swings the leaf on its hinge and leaves the gap clear', () => {
  const closed = objectArt('door'), open = objectArt('door', {open: true});
  assert.notEqual(open, closed);
  assert.ok(marked(open, 'tt-door-leaf') && marked(open, 'tt-door-handle'));
  assert.match(open, /class="tt-art-arc"/, 'the swing is drawn');
  assert.match(open, /rotate\(90 9 32\)/, 'the leaf turns about the west hinge');
  assert.match(open, /class="tt-door-threshold"/, 'the threshold stays across the empty gap');
});

test('locked and jammed doors carry a padlock or a wedged bar', () => {
  assert.ok(marked(objectArt('door', {locked: true}), 'tt-door-lock'));
  assert.ok(marked(objectArt('door', {jammed: true}), 'tt-door-bar'));
  // The table's saved state text works too (objectArt maps it onto the same mark).
  assert.ok(marked(objectArt('door', {state: 'locked'}), 'tt-door-lock'));
  assert.ok(marked(objectArt('door', {state: 'jammed'}), 'tt-door-bar'));
  assert.ok(!marked(objectArt('door'), 'tt-door-lock'));
  assert.ok(!marked(objectArt('door'), 'tt-door-bar'));
});

test('the door drawing follows the map facing and mount rotation', () => {
  assert.match(objectArt('door', {facing: 'south'}), /rotate\(90 32 32\)/);
  assert.match(objectArt('door', {rotation: 180}), /rotate\(180 32 32\)/);
  const vertical = token(door({mount_axis: 'v', mount_line: 400, x: 4, y: 3}));
  assert.equal(vertical.rotation, 90);
  const art = objectArt('door', {rotation: vertical.rotation});
  assert.ok(marked(art, 'tt-door-handle'), 'a vertical door still draws its handle');
});

test('the table row state reaches the token and the drawing', () => {
  const locked = token(door({door_locked: 1}));
  assert.equal(locked.door_locked, 1);
  assert.equal(locked.interaction, 'simple_door');
  assert.ok(marked(objectArt('door', {locked: locked.door_locked}), 'tt-door-lock'));
  const jammed = token(door({door_jammed: 1}));
  assert.equal(jammed.door_jammed, 1);
  assert.ok(marked(objectArt('door', {jammed: jammed.door_jammed}), 'tt-door-bar'));
});

test('door hover text says the state and the free way through it', () => {
  assert.equal(doorDetail(door()),
    'Door — closed. Within 5 ft: open it as a free object interaction or an Action. (AC 15, 18 HP).');
  assert.match(doorDetail(door({open: true})), /Door — open\. Within 5 ft: close it/);
  assert.match(doorDetail(door({door_locked: 1})), /Door — closed and locked\. This door cannot be opened or closed by hand/);
  assert.match(doorDetail(door({door_jammed: 1})), /Door — closed and stuck\. This door cannot be opened or closed by hand/);
  // The table token uses that sentence for the hover card.
  assert.match(token(door()).detail, /^Door — closed\. Within 5 ft: open it/);
  assert.match(token(door({door_locked: 1})).detail, /^Door — closed and locked\./);
});

test('a door marker is lifted above a drawn roof only while the server says it is perceived', () => {
  const width = 8, seen = new Uint8Array(width * 8).fill(1), unseen = new Uint8Array(width * 8);
  const visible = token(door(), {seen, perceived: new Set(['object:map.1'])});
  assert.equal(visible.hidden, false);
  assert.equal(doorMarkerAboveRoof(visible), true);

  const fogged = token(door(), {seen: unseen, perceived: new Set()});
  assert.equal(fogged.hidden, true);
  assert.equal(doorMarkerAboveRoof(fogged), false, 'fog must never be lifted for an unseen door');

  const notInPerceived = token(door(), {seen, perceived: new Set()});
  assert.equal(notInPerceived.hidden, true);
  assert.equal(doorMarkerAboveRoof(notInPerceived), false);

  assert.equal(doorMarkerAboveRoof({...visible, kind: 'crate'}), false, 'only a door is a building-outline marker');
  assert.equal(doorMarkerAboveRoof({...visible, interaction: null}), false, 'only a usable simple door is marked');
});

test('the real board keeps a perceived door above a drawn roof and never lifts an unseen one', () => {
  installDOM('<body></body>');
  const board = createBoard(document.body);
  const indoor = [];
  for (let y = 2; y <= 5; y += 1) for (let x = 2; x <= 7; x += 1) indoor.push([x, y]);
  const map = {
    width: 10, height: 8, background: {style: 'flagstone'},
    materials: [{material: 'floor:wood', cells: indoor}],
    walls: [
      {id: 'north', shape: 'line', points: [[1, 1], [9, 1]]},
      {id: 'east', shape: 'line', points: [[9, 1], [9, 7]]},
      {id: 'south', shape: 'line', points: [[9, 7], [1, 7]]},
      {id: 'west', shape: 'line', points: [[1, 7], [1, 1]]},
    ],
    objects: [],
  };
  board.setMap(map);
  assert.ok(board.element.querySelectorAll('[data-roof]').length, 'the indoor room is roofed');
  const seen = new Uint8Array(map.width * map.height).fill(1);
  const row = extra => ({
    id: 'object:map.1', x: 4, y: 6, name: 'Ancestral hall door', kind: 'door', interaction: 'simple_door',
    hp: 18, maxHp: 18, open: false, door_locked: 0, door_jammed: 0, ...extra,
  });
  board.setTokens([
    {...row({id: 'door', hidden: false}), object: true},
    {id: 'crate', x: 4, y: 4, object: true, kind: 'crate', name: 'Crate', hp: 5, maxHp: 5, hidden: false},
  ]);
  board.setFog(seen, null, {squareFog: true});
  board.setRoofView({gm: false, viewers: [{x: 9, y: 0}], seen});
  const doorNode = board.tokenNode('door');
  assert.ok(!doorNode.parentNode.classList.contains('tt-roof-interior'), 'a perceived door stays above the drawn roof');
  assert.ok(doorNode.classList.contains('is-roof-marker'));
  assert.ok(board.tokenNode('crate').parentNode.classList.contains('tt-roof-interior'), 'other objects stay under the eaves');

  // The server says this door is not perceived: it must stay hidden under the roof, never lifted out of the fog.
  board.setTokens([{...row({id: 'door', hidden: true}), object: true}]);
  board.setRoofView({gm: false, viewers: [{x: 9, y: 0}], seen});
  const fogged = board.tokenNode('door');
  assert.ok(fogged.parentNode.classList.contains('tt-roof-interior'));
  assert.ok(!fogged.classList.contains('is-roof-marker'));
  assert.ok(fogged.classList.contains('is-hidden'));
});
