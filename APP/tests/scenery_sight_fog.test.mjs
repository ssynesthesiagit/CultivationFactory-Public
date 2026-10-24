import test from 'node:test';
import assert from 'node:assert/strict';
import {blockerSegments, visibilityPolygons, fogPointVisible} from '../static/tabletop/fog_polygon.js';

// A scenery object blocks sight through the shared centre plus (owner 2026-10-23) and a target standing in that
// cell is seen at its near face -- the engine's near_endpoint exemption (combat/sight_lines.py hit). The board's
// fog must follow that same rule, or the exact sampler hides a creature the engine can target.
const plus_source = () => ({sources: [{cells: [[4, 3]], kind: 'BLOCKED', tag: 'object', name: 'Scenery',
  bottom_ft: 0, top_ft: 10, occluder: 'centerline', segments: [[[8, 7], [10, 7]], [[9, 6], [9, 8]]]}]});
const near = (x, y, geometry) => fogPointVisible(x, y, 10, 8, [], visibilityPolygons([{x: 1.5, y: 3.5}],
  blockerSegments(geometry), 10, 8));

test('the centre plus blocks what is behind it and leaves the target cell at its near face visible', () => {
  const geometry = plus_source();
  assert.equal(near(6.5, 3.5, geometry), false, 'the row behind the plus stays dark');
  assert.equal(near(4.5, 3.5, geometry), true, 'a target inside the plus cell is seen, as the engine allows');
  assert.equal(near(1.5, 3.5, geometry), true, 'the viewer is never hidden by the geometry under it');
});

test('a square-filling object (a door) still hides its whole cell', () => {
  const door = {sources: [{cells: [[4, 3]], kind: 'BLOCKED', tag: 'door', name: 'Wooden door', bottom_ft: 0,
    top_ft: 10, occluder: 'cell', segments: [[[8, 7], [10, 7]], [[8, 6], [8, 8]], [[10, 6], [10, 8]]]}]};
  assert.equal(near(6.5, 3.5, door), false, 'nothing is seen straight through the closed door');
});
