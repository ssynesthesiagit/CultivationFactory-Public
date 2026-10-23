import test from 'node:test';
import assert from 'node:assert/strict';
import {sightBlockerLines, blockerCellStrokes} from '../static/tabletop/los-lines.js';

// The server tags every sight source; the client must not infer the kind from display text.
test('solid blocking terrain is classified by its structured tag, not its description', () => {
  const row = {cells:[[4,3]], kind:'BLOCKED', tag:'terrain',
    name:'Blocking terrain: cannot be entered and blocks line of sight.',
    bottom_ft:0, top_ft:null, segments:[[[8,6],[10,6]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.equal(lines[0].kind, 'terrain');
  assert.equal(blockerCellStrokes(lines, 10, 8).size, 0, 'solid terrain art is not painted over');
});

test('a wall named like scenery but tagged wall stays a visible wall', () => {
  const row = {cells:[[4,3]], kind:'BLOCKED', tag:'wall', name:'Rock wall',
    bottom_ft:0, top_ft:null, segments:[[[8,6],[10,6]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.equal(lines[0].kind, 'wall');
  assert.ok(blockerCellStrokes(lines, 10, 8).size > 0);
});
