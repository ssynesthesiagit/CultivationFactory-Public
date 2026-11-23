import test from 'node:test';
import assert from 'node:assert/strict';
import {sightBlockerLines, blockerCellStrokes} from '../static/tabletop/los-lines.js';

// The server sends a structured kind with every sight source (combat/sight_lines.py tag) and the resolved sight
// shape (combat/tabletop.py, combat/object_rules.py). The renderer must never read a name, a description or a shape.

const drawn = entries => (entries || []).some(stroke => stroke.center || stroke.ticks || stroke.art);
const cellStrokes = row => blockerCellStrokes(sightBlockerLines({sources: [row]}), 10, 8);

test('an object source (the default centre plus) is geometry only, with its hover name kept', () => {
  // A placed object's wall zone: one square, the plus segments zones.sync_walls builds from the preset.
  const row = {cells: [[4, 3]], kind: 'BLOCKED', tag: 'object', name: 'Boulder pile', bottom_ft: 0, top_ft: 10,
    segments: [[[8, 7], [10, 7]], [[9, 6], [9, 8]]]};
  const lines = sightBlockerLines({sources: [row]});
  assert.equal(lines.length, 2, 'both arms of the plus stay in the sight/fog geometry');
  assert.ok(lines.every(line => line.kind === 'object'));
  const entries = cellStrokes(row).get(3 * 10 + 4);
  assert.ok(entries?.length, 'the square keeps a blocker entry for hover');
  assert.ok(entries.every(entry => entry.name), 'the entry still names the blocker');
  assert.equal(drawn(entries), false, 'no rule stroke is painted over the object art');
});

test('a wall source still draws its centre run and end ticks', () => {
  const row = {cells: [[4, 3]], kind: 'BLOCKED', tag: 'wall', name: 'Stone wall', bottom_ft: 0, top_ft: null,
    segments: [[[8, 6], [10, 6]], [[8, 6], [8, 8]], [[10, 6], [10, 8]]]};
  assert.equal(drawn(cellStrokes(row).get(3 * 10 + 4)), true, 'a real wall keeps its visible rule stroke');
});

test('a door source still draws the stroke it shares with the wall line', () => {
  const row = {cells: [[4, 3]], kind: 'BLOCKED', tag: 'door', name: 'Wooden door', bottom_ft: 0, top_ft: 10,
    segments: [[[8, 7], [10, 7]], [[8, 6], [8, 8]], [[10, 6], [10, 8]]]};
  assert.equal(drawn(cellStrokes(row).get(3 * 10 + 4)), true);
});

test('the tag decides the kind: identical descriptions classify differently', () => {
  const prose = 'Tall scenery: blocks sight below its top.';
  const scenery = {cells: [[4, 3]], kind: 'SIGHT_BLOCKED', tag: 'terrain', name: prose,
    bottom_ft: 0, top_ft: 10, segments: [[[8, 6], [10, 6]]]};
  const wall = {cells: [[4, 3]], kind: 'BLOCKED', tag: 'wall', name: prose,
    bottom_ft: 0, top_ft: null, segments: [[[8, 6], [10, 6]]]};
  assert.equal(sightBlockerLines({sources: [scenery]})[0].kind, 'terrain');
  assert.equal(sightBlockerLines({sources: [wall]})[0].kind, 'wall');
  assert.equal(drawn(cellStrokes(scenery).get(3 * 10 + 4)), false);
  assert.equal(drawn(cellStrokes(wall).get(3 * 10 + 4)), true);
});

test('the centre plus from the bound volumes stays invisible and keeps its own name', () => {
  const lines = sightBlockerLines({sources: []}, [], {volumes: [
    {x: 4, y: 3, mode: 'centerline', bottom_ft: 0, top_ft: 10,
     name: 'Tall scenery: blocks sight below its top.', tag: 'terrain'}]});
  const arm = lines.filter(line => line.kind === 'terrain');
  assert.equal(arm.length, 2, 'the shared sight geometry is still a plus');
  const entries = blockerCellStrokes(lines, 10, 8).get(3 * 10 + 4);
  assert.equal(drawn(entries), false, 'neither arm is painted over the scenery');
  assert.match(entries[0].name, /Tall scenery/, 'the plus keeps the region name, not a tree label');
});

test('the geometry.walls fallback reads the server kind and occluder', () => {
  const boulder = {shape: 'circle', filled: true, sight_class: 'object', occluder: 'centerline',
    points: [[4.5, 3.5], [5.3, 3.5]], cells: [[4, 3]]};
  const wall = {shape: 'rect', filled: true, sight_class: 'wall', occluder: 'cell',
    points: [[1, 1], [2, 2]], cells: [[1, 1]]};
  const lines = sightBlockerLines({walls: [boulder, wall], centerlineCells: []});
  const boulderArms = lines.filter(line => line.kind === 'object');
  assert.equal(boulderArms.length, 2, 'the fallback builds the same centre plus');
  const at = blockerCellStrokes(lines, 8, 6);
  assert.equal(drawn(at.get(3 * 8 + 4)), false, 'no stroke over the boulder art');
  assert.equal(drawn(at.get(1 * 8 + 1)), true, 'the wall keeps its stroke');
});
