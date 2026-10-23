import test from 'node:test';
import assert from 'node:assert/strict';
import {sightBlockerLines, blockerCellStrokes} from '../static/tabletop/los-lines.js';

test('boulder footprint remains sight geometry without visible H-shaped rule strokes', () => {
  const row = {cells:[[4,3]], kind:'SIGHT_BLOCKED', tag:'terrain', name:'Tall scenery: blocks sight below its top.',
    bottom_ft:0, top_ft:10, segments:[[[8,6],[10,6]],[[8,6],[8,8]],[[10,6],[10,8]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.ok(lines.length, 'the footprint still supplies the sight/fog geometry');
  assert.ok(lines.every(line => line.kind === 'terrain'), 'scenery source is not misclassified as a wall');
  assert.equal(blockerCellStrokes(lines, 10, 8).size, 0, 'no visible strokes over the boulder art');
});

test('centre-cross scenery geometry stays invisible', () => {
  const lines = sightBlockerLines({centerlineCells:[[4,3]]});
  assert.equal(lines.length, 2, 'the shared sight geometry is still a plus');
  assert.equal(blockerCellStrokes(lines, 10, 8).size, 0, 'neither arm is painted over the scenery');
});

test('real wall geometry remains visible', () => {
  const row = {cells:[[4,3]], kind:'BLOCKED', name:'Stone wall',
    bottom_ft:0, top_ft:null, segments:[[[8,6],[10,6]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.equal(lines[0].kind, 'wall');
  assert.ok(blockerCellStrokes(lines, 10, 8).size > 0);
});
