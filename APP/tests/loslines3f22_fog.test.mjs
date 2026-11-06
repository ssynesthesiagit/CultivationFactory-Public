import test from 'node:test';
import assert from 'node:assert/strict';
import {actor, createTableHarness, tableState} from './viewer_identity_harness.mjs';
import {fogPointVisible} from '../static/tabletop/fog_polygon.js';

function setup(gm = false) {
  const own = actor('own', {x: 1, y: 1});
  const map = {width_squares: 10, height_squares: 10,
    walls: [{shape: 'line', points: [[0, 3], [9, 3]]}], trees: [], terrain: [], materials: []};
  const state = tableState([own], {map, perception: {own: {cells: [[1, 1]], creatures: ['own']}}});
  state.fog_geometry = {volumes: [], roofs: [], lines: [{
    kind: 'BLOCKED', name: 'Occluding wall', bottom_ft: 0, top_ft: null,
    cells: Array.from({length: 10}, (_, x) => [x, 3]), segments: [[[0, 7], [20, 7]]],
  }, {
    kind: 'BLOCKED', name: 'Unseen wall', bottom_ft: 0, top_ft: null,
    cells: [[7, 7]], segments: [[[14, 15], [16, 15]]],
  }]};
  const h = createTableHarness({gm, boundIds: gm ? null : ['own'], roster: [own], state});
  h.location.search = '?match=match&view=view-one'; // production polygon fog, not square diagnostic
  return h;
}

test('non-GM fog without a perception mask keeps main\'s empty geometry', () => {
  const h = setup();
  assert.equal(h.isGMView(), false);
  // Main returns exactly this value when !seen. Do not publish live sources
  // when a player refresh has not yet supplied a perception mask.
  assert.deepEqual(h.fogGeometry(null), {polygons: []});
});

test('non-GM unseen area stays dark and reveals no live blocker before or after a hidden edit', () => {
  const h = setup();
  const seen = h.visibility();
  assert.equal(seen[7 * 10 + 7], 0);
  for (const x of [7, 8]) {
    const row = h.app.state.fog_geometry.lines[1];
    row.cells = [[x, 7]];
    row.segments = [[[2 * x, 15], [2 * x + 2, 15]]];
    const geometry = h.fogGeometry(seen);
    assert.equal(fogPointVisible(7.5, 7.5, 10, 10, seen, geometry.polygons), false,
      'main expectation: unseen area stays dark');
    h.board.setFog(seen, null, geometry);
    assert.equal(h.document.querySelector('.tt-sight-lines').querySelectorAll('.tt-sight-current').length, 0,
      'no live wall line is shown in an unseen area');
  }
});

test('GM fog without a perception mask still supplies live blocker lines', () => {
  const h = setup(true);
  assert.equal(h.visibility(), null);
  const geometry = h.fogGeometry(null);
  assert.deepEqual(geometry.blockerGeometry.sources, h.app.state.fog_geometry.lines);
  h.board.setFog(null, null, geometry);
  assert.ok(h.document.querySelector('.tt-sight-lines').querySelector('.tt-sight-line'));
});
