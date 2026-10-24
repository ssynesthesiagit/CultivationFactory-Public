import test from 'node:test';
import assert from 'node:assert/strict';
import {sightBlockerLines, blockerCellStrokes} from '../static/tabletop/los-lines.js';

// The server tags every sight source with its structured kind (combat/sight_lines.py); the client must not infer
// the kind from display text. Hover text stays for every blocker; only the drawn strokes depend on the kind.

const drawn = entries => (entries || []).some(stroke => stroke.center || stroke.ticks || stroke.art);

test('solid blocking terrain is classified by its structured tag, not its description', () => {
  const row = {cells:[[4,3]], kind:'BLOCKED', tag:'terrain',
    name:'Blocking terrain: cannot be entered and blocks line of sight.',
    bottom_ft:0, top_ft:null, segments:[[[8,6],[10,6]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.equal(lines[0].kind, 'terrain');
  const entries = blockerCellStrokes(lines, 10, 8).get(3 * 10 + 4);
  assert.equal(drawn(entries), false, 'solid terrain art is not painted over');
  assert.match(entries[0].name, /blocking terrain/i, 'the square still explains that it blocks sight');
});

test('a wall named like scenery but tagged wall stays a visible wall', () => {
  const row = {cells:[[4,3]], kind:'BLOCKED', tag:'wall', name:'Rock cliff',
    bottom_ft:0, top_ft:null, segments:[[[8,6],[10,6]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.equal(lines[0].kind, 'wall');
  assert.ok(drawn(blockerCellStrokes(lines, 10, 8).get(3 * 10 + 4)));
});

test('a tree tag stays art-only while its hover entry remains', () => {
  const row = {cells:[[4,3]], kind:'BLOCKED', tag:'tree', name:'Tree trunk: blocks sight and movement below its top.',
    bottom_ft:0, top_ft:10, segments:[[[8,6],[10,6]],[[9,5],[9,7]]]};
  const lines = sightBlockerLines({sources:[row]});
  assert.equal(lines[0].kind, 'tree');
  const entries = blockerCellStrokes(lines, 10, 8).get(3 * 10 + 4);
  assert.equal(drawn(entries), false);
  assert.ok(entries.every(entry => entry.name));
});
