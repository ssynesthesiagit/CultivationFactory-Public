// Exercise the production board placement path without launching a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js?v=rel6-2';
import {CATALOG_KNOWN} from '../static/tabletop/object-art-catalog.js?v=son198r2';

test('two copies of every catalog drawing on one board have unique SVG IDs in every state and turn', () => {
  installDOM('<body></body>');
  const board = createBoard(document.body);
  const states = [{}, {open: false}, {open: true}, {state: 'closed'}, {state: 'open'}];
  const turns = [null, 0, 45, 90, 135, 180, 225, 270, 315, 360, -90].map(rotation => ({rotation}));
  turns.push(...['east', 'south', 'west', 'north'].map(facing => ({facing})));
  for (const kind of CATALOG_KNOWN) for (const state of states) for (const turn of turns) {
    const options = {...state, ...turn}, label = `${kind} ${JSON.stringify(options)}`;
    board.setTokens([1, 2].map(id => ({id: `object:${id}`, object: true, kind, name: kind,
      x: id, y: 1, ...options})));
    const faces = board.element.querySelectorAll('.tt-token-face');
    assert.equal(faces.length, 2, `${label}: both placements must be rendered`);
    const allIds = [];
    for (const face of faces) {
      assert.match(face.innerHTML, /^<svg /, `${label}: drawing missing`);
      const ids = [...face.innerHTML.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
      assert.ok(ids.length > 0, `${label}: no drawing IDs`);
      allIds.push(...ids);
    }
    assert.equal(new Set(allIds).size, allIds.length, `${label}: duplicate ID on the board`);
  }
});
