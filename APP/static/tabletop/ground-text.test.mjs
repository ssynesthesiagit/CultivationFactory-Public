// node --test APP/static/tabletop/ground-text.test.mjs
// The ground hover card (owner 2026-09-30: "hovering over the types of ground ... should bring up the
// type of material and its effects on movement or anything else"). The pure builder: a square's kinds
// are named and their effects listed, in the words the server catalog supplies, and a kind the catalog
// does not know stays quiet rather than guessing a rule.
//
// The card itself is a pure assembler -- it writes out no mechanic of its own. The wording is pinned to
// the engine in tests/test_ground_text_matches_engine.py, and the board's hover wiring and its
// two-second rest are covered by tests/ground_hover_board.test.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';

import {groundCard} from './ground-text.js';

// The keys combat/ground_text.py publishes. A test must not invent a key the server does not send.
const CATALOG = {
  'floor:marble': {name: 'Marble floor', lines: ['Painted ground: the material itself changes nothing.']},
  'floor:sand': {name: 'Sand floor', lines: ['Painted ground: the material itself changes nothing.']},
  'cell:difficult': {name: 'Difficult ground', lines: ['Difficult terrain: entering these squares costs twice as much movement.']},
  'cell:cover': {name: 'Cover', lines: ['Cover: that creature\'s Armor Class is 2 higher.',
    'The cover square itself is worth nothing -- the cover has to be BETWEEN the creature and the attacker.']},
  'cell:hazard': {name: 'Hazard', lines: ['Hazard: any creature that moves through these squares makes a Dexterity saving throw of 12.']},
  'cell:sight': {name: 'Blocks sight', lines: ['This square blocks line of sight.',
    'It is not a wall. A creature can walk straight through it.']},
  'structure:wall': {name: 'Wall', lines: ['A wall: it blocks movement and sight.']},
  'structure:tree': {name: 'Tree', lines: ['A tree: its trunk blocks movement and sight exactly as a wall does.']},
};

test('a painted floor is named from the server catalog and says what it does', () => {
  const card = groundCard({x: 3, y: 2}, {style: 'marble', catalog: CATALOG});
  assert.equal(card.title, 'Marble floor');
  assert.deepEqual(card.lines, ['Painted ground: the material itself changes nothing.']);
});

test('a square with a rule on it is headed by that rule, with the floor beneath it', () => {
  const card = groundCard({x: 3, y: 2}, {style: 'sand', difficult: true, catalog: CATALOG});
  assert.equal(card.title, 'Difficult ground', 'the heading names what the square does');
  assert.deepEqual(card.lines, [
    'Material: Sand floor',
    'Painted ground: the material itself changes nothing.',
    'Difficult terrain: entering these squares costs twice as much movement.',
  ]);
});

for (const kind of ['difficult', 'cover', 'hazard', 'blocked', 'sight']) {
  test(`a ${kind} square keeps the visible material name from the catalog`, () => {
    for (const [style, name] of [['sand', 'Sand floor'], ['marble', 'Marble floor']]) {
      const card = groundCard({x: 3, y: 2}, {style, [kind]: true, catalog: CATALOG});
      assert.ok(card.lines.includes(`Material: ${name}`));
    }
  });
}

test('cover is described from the catalog, so the card cannot advise a player wrongly', () => {
  const card = groundCard({x: 5, y: 5}, {cover: true, catalog: CATALOG});
  assert.equal(card.title, 'Cover');
  assert.match(card.lines.join(' '), /BETWEEN the creature and the attacker/);
  // The advice the pre-merge review found wrong: standing in the cover square protects nobody.
  assert.doesNotMatch(card.lines.join(' '), /standing in it is harder to hit/);
});

test('a hazard square states the save from the catalog', () => {
  const card = groundCard({x: 5, y: 5}, {hazard: true, catalog: CATALOG});
  assert.equal(card.title, 'Hazard');
  assert.match(card.lines.join(' '), /Dexterity saving throw of 12/);
});

test('a wall names itself and says it blocks movement and sight', () => {
  const card = groundCard({x: 7, y: 4}, {blocked: true, catalog: CATALOG});
  assert.equal(card.title, 'Wall');
  assert.ok(card.lines.some(line => /blocks movement and sight/.test(line)));
});

test('a tree trunk reads as a tree, not a wall', () => {
  const card = groundCard({x: 1, y: 1}, {blocked: true, tree: true, catalog: CATALOG});
  assert.equal(card.title, 'Tree');
  assert.ok(card.lines.some(line => /trunk blocks movement and sight/.test(line)));
});

test('a sight-only square is described as a blocker of sight, never as a solid wall', () => {
  const card = groundCard({x: 2, y: 6}, {sight: true, catalog: CATALOG});
  assert.equal(card.title, 'Blocks sight');
  assert.match(card.lines.join(' '), /walk straight through it/);
  assert.doesNotMatch(card.lines.join(' '), /no creature can be standing in it/);
});

test('a solid wall is not also described as a sight-only square', () => {
  // map.cells.sight can list a wall square too; the card must not say both.
  const card = groundCard({x: 7, y: 4}, {blocked: true, sight: true, catalog: CATALOG});
  assert.equal(card.title, 'Wall');
  assert.doesNotMatch(card.lines.join(' '), /walk straight through it/);
});

test('a square whose kinds the catalog does not know says nothing rather than guessing', () => {
  assert.equal(groundCard({x: 0, y: 0}, {catalog: CATALOG}), null);
  assert.equal(groundCard({x: 0, y: 0}, {style: 'not-a-real-style', catalog: CATALOG}), null);
  assert.equal(groundCard(null, {style: 'marble', catalog: CATALOG}), null);
  // Every kind the builder can be given is answered from the catalog alone; with no catalog at all it
  // stays quiet rather than inventing a rule. Both surfaces (table and map editor) send the catalog.
  assert.equal(groundCard({x: 1, y: 1}, {blocked: true, catalog: {}}), null);
  assert.equal(groundCard({x: 1, y: 1}, {style: 'marble', catalog: {}}), null);
});

// A named terrain painted on the map is a rule, not a texture (OC13: a Fire Terrain square read
// "Graveyard floor -- the material itself changes nothing", and every terrain:* reading the server
// publishes was unreachable). The card names it and says what it does, in the server's own words.
const TERRAIN_CATALOG = {
  ...CATALOG,
  'terrain:fire terrain': {name: 'Fire Terrain', lines: [
    'A hostile creature entering it, or starting its turn inside, makes a Dexterity save and, on a failure, takes Fire damage.',
  ]},
};

test('a named terrain heads the card and states its rule, with the painted floor beneath it', () => {
  const card = groundCard({x: 3, y: 2}, {style: 'marble', terrain: 'fire terrain', catalog: TERRAIN_CATALOG});
  assert.equal(card.title, 'Fire Terrain', 'the heading names what the square does');
  assert.deepEqual(card.lines, [
    'Material: Marble floor',
    'Painted ground: the material itself changes nothing.',
    'A hostile creature entering it, or starting its turn inside, makes a Dexterity save and, on a failure, takes Fire damage.',
  ]);
});

test('a named terrain is named even on a square with no painted floor of its own', () => {
  const card = groundCard({x: 9, y: 4}, {terrain: 'fire terrain', catalog: TERRAIN_CATALOG});
  assert.equal(card.title, 'Fire Terrain');
  assert.match(card.lines.join(' '), /Dexterity save/);
});

test('a terrain the catalog does not know stays quiet rather than guessing a rule', () => {
  assert.equal(groundCard({x: 9, y: 4}, {terrain: 'not-a-real-terrain', catalog: TERRAIN_CATALOG}), null);
});
