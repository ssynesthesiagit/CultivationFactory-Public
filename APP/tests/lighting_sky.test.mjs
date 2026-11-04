import test from 'node:test';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {sky, skyOffset} from '../static/tabletop/sky.js';
import {treeMarkup, treeScene} from '../static/tabletop/tree-art.js';
import {objectArt} from '../static/tabletop/object-art.js';

test('sky casts longer shadows away from the low sun, with weak moon and no underground sun', () => {
  assert.deepEqual(sky('dawn').direction, [1, 0]);
  assert.deepEqual(sky('dusk').direction, [-1, 0]);
  assert.ok(skyOffset(sky('dawn'))[0] < 0);
  assert.ok(skyOffset(sky('dusk'))[0] > 0);
  assert.ok(sky('dawn').length > sky('day').length);
  assert.ok(sky('dusk').length > sky('day').length);
  assert.ok(sky('night').strength < sky('day').strength);
  assert.equal(sky('underground').strength, 0);
  assert.equal(sky('underground').length, 0);
});

test('tree and prop shadows follow the same sky including cached sprites', () => {
  const tree = {x: 0, y: 0, look: 'broadleaf'};
  const dawn = treeMarkup(tree, sky('dawn')), dusk = treeMarkup(tree, sky('dusk'));
  assert.match(dawn, /opacity="0.85" cx="-0.6" cy="0.5"/);
  assert.match(dusk, /opacity="0.85" cx="1.6" cy="0.5"/);
  assert.match(treeMarkup(tree, sky('underground')), /opacity="0"/);
  const a = treeScene([tree], sky('dawn')), b = treeScene([tree], sky('dusk'));
  assert.notEqual([...a.shapes.values()][0].markup, [...b.shapes.values()][0].markup);
  assert.notEqual(a.placements[0].id, b.placements[0].id);
  assert.match(objectArt('barrel', {skyModel: sky('dawn')}), /translate\(-6.6000000000000005 0\)/);
  assert.match(objectArt('barrel', {skyModel: sky('dusk')}), /translate\(6.6000000000000005 0\)/);
});

test('wall shadow renderer uses the same sky direction and strength', () => {
  const board = readFileSync('static/tabletop/board.js', 'utf8');
  assert.match(board, /skyOffset\(model, wall.kind === "solid"/);
  assert.match(board, /0\.55\) \* model.strength/);
  assert.match(board, /zone.radius_cells, map.ambient\?\.time_of_day/);
});
