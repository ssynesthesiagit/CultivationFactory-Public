import test from 'node:test';
import assert from 'node:assert/strict';
import {expandMovementGrid, compactStatePath} from '../static/tabletop/movement-grid.js';
import {expandTableTexts} from '../static/tabletop/table-text-pool.js';

test('compact movement keeps all squares, heights, prices and alternative modes', () => {
  const grid = [[1, 2, 0, 5, 'walk', false], [1, 2, 1, 10, 'fly', true], [1, 2, 0, 10, 'jump', false]];
  const menu = {moves: [], movement_grid: grid};
  const expanded = expandMovementGrid(menu);
  assert.equal(expanded.moves.length, grid.length);
  assert.equal(menu.moves.length, 0);
  assert.deepEqual(expanded.moves.map(m => [m.destination.x, m.destination.y, m.destination.z,
    m.cost_ft, m.movement_mode, m.can_jump_down]), grid);
  assert.ok(expanded.moves.every(m => m.deferred_route && m.candidate_id.startsWith('route:')));
});

test('pooled rules text expands without losing nesting, Unicode or values', () => {
  const text = 'Move 10 feet — then choose a creature. '.repeat(20);
  assert.deepEqual(expandTableTexts({table_texts: [text], menu: {description: {$table_text: 0}},
    rows: [{$table_text: 0}, null, false, 0]}), {menu: {description: text}, rows: [text, null, false, 0]});
});

test('layer packing retains all native movement modes and cheapest endpoint first', () => {
  const menu = expandMovementGrid({movement_grid: {format: 'layers-v1', layers: [
    [0, 10, 'jump', false, [1, 2]], [0, 5, 'walk', false, [1, 2, 3, 4]],
    [1, 10, 'fly', true, [1, 2]],
  ]}});
  assert.equal(menu.moves.length, 4);
  assert.equal(menu.moves.find(m => m.destination.x === 1 && m.destination.z === 0).cost_ft, 5);
  assert.ok(menu.moves.some(m => m.movement_mode === 'jump'));
  assert.ok(menu.moves.some(m => m.can_jump_down && m.destination.z === 1));
});

test('browser requests opt into compact state without altering other routes or explicit compatibility reads', () => {
  assert.equal(compactStatePath('/api/tabletop/matches/m/state'), '/api/tabletop/matches/m/state?compact=true');
  assert.equal(compactStatePath('/api/tabletop/matches/m/state?fog=true'), '/api/tabletop/matches/m/state?fog=true&compact=true');
  assert.equal(compactStatePath('/api/tabletop/matches/m/state?compact=false'), '/api/tabletop/matches/m/state?compact=false');
  assert.equal(compactStatePath('/api/tabletop/matches/m/events'), '/api/tabletop/matches/m/events');
});
