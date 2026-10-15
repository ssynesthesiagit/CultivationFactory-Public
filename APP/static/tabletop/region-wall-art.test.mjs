import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {regionWallRows, regionWallIndex, regionWallCellMarkup} from './region-wall-art.js';

const row = {region_id: 'wall.height.south-rim', terrain_type: 'BLOCKED', height_ft: 10,
  cells: [{x: 0, y: 0}, {x: 1, y: 0}, {x: 0, y: 1}, {x: 1, y: 1}]};

test('table state carries arena regions with their heights to the board', () => {
  const source = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function mapFromState(');
  const body = source.slice(start, source.indexOf('\n}\n', start) + 3);
  const convert = new Function('centerlineTerrain', 'groveCells', `${body}; return mapFromState;`)(() => [], () => new Set());
  const map = convert({presentation: {battlefield: {width_squares: 4, height_squares: 4, terrain_regions: [row]}}});
  assert.deepEqual(map.terrainRegions, [row]);
});

test('all built-in maps with natural finite wall regions use the same renderer', () => {
  const folder = new URL('../../combat/maps/', import.meta.url);
  const affected = [];
  for (const file of readdirSync(folder).filter(name => name.startsWith('builtin-') && name.endsWith('.json'))) {
    const map = JSON.parse(readFileSync(new URL(file, folder), 'utf8'));
    // normalize_map supplies the default height before creating arena regions.
    const walls = (map.walls || []).filter(w => (w.height_ft ?? 10) > 0 && w.blocks === 'sight_and_movement' && (!w.look || w.look === 'rock_cliff'));
    if (!walls.length) continue;
    affected.push(map.map_id);
    const rows = walls.map(w => ({...row, region_id: `wall.height.${w.id}`, height_ft: w.height_ft ?? 10}));
    assert.equal(regionWallRows(rows, walls).length, walls.length, map.map_id);
  }
  assert.deepEqual(affected.sort(), [
    'builtin-bamboo-forest-ravine', 'builtin-mist-courtyard', 'builtin-mountain-pass',
    'builtin-pillar-arena', 'builtin-realm-waterfall-gorge', 'builtin-ruined-spirit-shrine',
    'builtin-sect-trial-platform', 'builtin-sunken-cavern-lake',
  ]);
});

test('finite natural region walls preserve architectural looks, trunks and roofs', () => {
  const rows = [row, {...row, region_id: 'tree.height.1'}, {...row, region_id: 'roof.wall.house.10'},
    {...row, terrain_type: 'SIGHT_BLOCKED'}, {...row, height_ft: 0}];
  assert.deepEqual(regionWallRows(rows), [row]);
  assert.deepEqual(regionWallRows([row], [{id: 'south-rim', look: 'grey_brick'}]), []);
  assert.deepEqual(regionWallRows([row], [{id: 'south-rim', look: 'rock_cliff'}]), [row]);
});

test('cliff caps follow the region perimeter, faces scale with height and rocks never stamp', () => {
  const index = regionWallIndex([row]);
  assert.deepEqual(index.get('0,0').edges, [true, false, false, true]);
  assert.deepEqual(index.get('1,1').edges, [false, true, true, false]);
  const first = regionWallCellMarkup(index.get('0,0'));
  assert.match(first, /tt-cliff-top-edge/);
  assert.match(first, /#e3ddcb/); // shared rock helper's NW-lit facet
  assert.doesNotMatch(first, /pattern|tt-stone/);
  assert.equal(new Set([...index.values()].map(regionWallCellMarkup)).size, 4);
  const low = regionWallCellMarkup(index.get('1,1'));
  const high = regionWallCellMarkup({...index.get('1,1'), height_ft: 20});
  assert.match(low, /data-face-depth="12"/);
  assert.match(high, /data-face-depth="24"/);
  assert.equal(first, regionWallCellMarkup(JSON.parse(JSON.stringify(index.get('0,0')))));
});
