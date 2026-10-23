// The objart contact sheet (static/tabletop/objart.browser.test.mjs) places every object kind and expects each to be
// drawn. A destructible wall piece (wall_section, sandbag_wall) is painted by the wall painter (wall-object-art.js),
// not the prop painter, so a board-level count must include both -- the mistake the browser test made. This is the
// non-browser half of that check: it runs the real board and asserts which painter draws each placed kind.
import test from 'node:test';
import assert from 'node:assert/strict';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';

// The unique object kinds the objart sheet places (SHEET_OBJECTS in objart.browser.test.mjs).
const KINDS = ['barricade', 'wall_section', 'pillar', 'statue', 'ice_block', 'crate', 'barrel', 'chest', 'cart',
  'banner', 'rope', 'vine', 'bell', 'custom'];
const WALL_PAINTED = new Set(['wall_section', 'sandbag_wall']);

test('board art: wall pieces paint as wall tiles, every other placed kind paints as a prop', () => {
  installDOM('<body></body>');
  const board = createBoard(document.body, {});
  const objects = KINDS.map((kind, i) => ({id: `object:map.${i + 1}`, kind, x: 1 + (i % 7) * 2, y: 1 + Math.floor(i / 7) * 2,
    name: kind, hp: 5, max_hp: 5}));
  board.setMap({width: 14, height: 9, objects});
  board.setTokens(tableObjectTokens(objects, new Set(), [], null, 14));
  const faces = board.element.querySelectorAll('.tt-token.is-object .tt-token-face').map(face => face.innerHTML);
  assert.equal(faces.length, KINDS.length);
  const wall = faces.filter(html => /class="[^"]*tt-wall-object-art/.test(html)).length;
  const prop = faces.filter(html => /class="[^"]*tt-prop-art/.test(html)).length;
  assert.equal(wall, KINDS.filter(kind => WALL_PAINTED.has(kind)).length, 'wall pieces use the wall painter');
  assert.equal(prop, KINDS.length - wall, 'every other placed kind uses the prop painter');
});
