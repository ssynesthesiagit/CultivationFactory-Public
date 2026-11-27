// Offline render/data regressions for the lead's four round-2 findings. No DOM or live services.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const baseline = process.env.MAPART2_BASELINE === '1';
const baselineSources = baseline ? JSON.parse(readFileSync(process.env.MAPART2_BASELINE_SOURCES, 'utf8')) : null;
const source = path => baseline && baselineSources[path] !== undefined ? baselineSources[path]
  : readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
async function moduleAt(name) {
  return import(baseline ? new URL(`./${name}.mjs`, `file://${process.env.MAPART2_BASELINE_SOURCES}`).href
    : new URL(`../static/tabletop/${name}.js`, import.meta.url).href);
}
const {wallLookMarkup, wallPatternDefs} = await moduleAt('wall-art');
const {painter} = await moduleAt('textures');
const {terrainCellMarkup} = await moduleAt('terrain-art');
const map = name => JSON.parse(source(`combat/maps/builtin-${name}.json`));

test('natural ravine, gorge and cavern boundaries are authored as rock cliffs', () => {
  for (const name of ['mountain-pass', 'bamboo-forest-ravine', 'realm-waterfall-gorge', 'sunken-cavern-lake']) {
    const m = map(name);
    const rims = m.walls.filter(w => /cliff|rim|^(north|south|west|east)-wall$/.test(w.id));
    assert.ok(rims.length > 0, name);
    for (const wall of rims) assert.equal(wall.look, 'rock_cliff', `${name}: ${wall.id}`);
  }
});

test('maple shrine has separated stands, varied trunk sizes and no long rectangular rows', () => {
  const m = map('realm-maple-shrine');
  assert.ok(m.trees.length >= 40 && m.trees.length < 100, 'open stands instead of a solid forest mass');
  assert.deepEqual(new Set(m.trees.map(t => t.size)), new Set([1, 2]));
  for (const axis of ['x', 'y']) {
    const counts = new Map();
    for (const tree of m.trees) counts.set(tree[axis], (counts.get(tree[axis]) || 0) + 1);
    assert.ok(Math.max(...counts.values()) < 12, `${axis}: no solid row across a clearing`);
  }
  assert.ok(m.trees.every(t => t.look === 'maple'));
});

test('worn marble slabs do not alternate a pale and green checker palette', () => {
  const paint = painter('marble', 11, 24, 24), groups = [[], []];
  for (let y = 0; y < 12; y++) for (let x = 0; x < 12; x++) {
    groups[(x + y) % 2].push(paint(x * 2 + 1, y * 2 + 1).reduce((a, b) => a + b) / 3);
  }
  const mean = xs => xs.reduce((a, b) => a + b) / xs.length;
  assert.ok(Math.abs(mean(groups[0]) - mean(groups[1])) < 8, 'slab colour must not track checker parity');
  assert.ok(new Set(groups.flat().map(x => Math.round(x))).size > 12, 'retain weathering and veins');
});

test('bamboo walls resolve seeded stalk art with individual node rings and top leaves', () => {
  const defs = new Map([...wallPatternDefs().matchAll(/<pattern id="([^"]+)"[^>]*>(.*?)<\/pattern>/g)].map(m => [m[1], m[2]]));
  const bodies = new Set();
  for (let i = 0; i < 20; i++) {
    const wall = {id: `fence-${i}`, shape: 'rect', points: [[1, 1], [7, 2]], filled: true, look: 'bamboo_fence'};
    const markup = wallLookMarkup(wall);
    assert.equal(markup, wallLookMarkup(wall), 'deterministic across redraws');
    const id = /fill="url\(#([^)]*)\)"/.exec(markup)[1], body = defs.get(id);
    assert.ok(body, 'chosen bank exists');
    assert.ok((body.match(/<ellipse /g) || []).length >= 32, 'each stalk has its own rings');
    assert.match(body, /q-.18-.13/, 'leaf fans at the tops');
    assert.ok(new Set([...body.matchAll(/width="([\d.]+)"/g)].map(m => m[1])).size > 6, 'varied stalk widths');
    bodies.add(body);
  }
  assert.ok(bodies.size >= 6, 'different walls choose different banks');
});

test('ricefield huts face four directions and break the identical aligned grid', () => {
  const m = map('ricefield-bamboo-valley'), signatures = new Set(), centers = [];
  for (const group of ['nw', 'ne', 'sw', 'se']) {
    const walls = m.walls.filter(w => w.id.startsWith(`hut-${group}-`));
    const points = walls.flatMap(w => w.points), minX = Math.min(...points.map(p => p[0])), minY = Math.min(...points.map(p => p[1]));
    signatures.add(JSON.stringify(walls.map(w => w.points.map(([x, y]) => [x - minX, y - minY]))));
    centers.push([minX, minY]);
  }
  assert.equal(signatures.size, 4, 'four different entrance orientations');
  assert.ok(new Set(centers.map(p => p[0])).size > 2 && new Set(centers.map(p => p[1])).size > 2, 'ragged hut layout');
});

test('paddies show seeded rice blades over water instead of a grid of gravel dots', () => {
  const m = map('ricefield-bamboo-valley');
  const paddy = m.terrain.find(t => t.type === 'DIFFICULT');
  assert.equal(paddy.look, 'rice_tufts');
  const waters = new Set(m.materials.filter(r => r.material === 'floor:shallows').flatMap(r => r.cells.map(c => c.join(','))));
  assert.ok(paddy.cells.every(c => waters.has(c.join(','))), 'water under every rice cell');
  const a = terrainCellMarkup('DIFFICULT', paddy.look, false, 11), b = terrainCellMarkup('DIFFICULT', paddy.look, false, 39);
  assert.match(a, /stroke-linecap="round"/);
  assert.doesNotMatch(a, /<circle|<ellipse|<rect/);
  assert.notEqual(a, b, 'irregular seeded rows');
});

test('largest built-in map and affected paddy art costs are recorded for the lead', () => {
  for (const name of ['frontier-fortress-wall', 'ricefield-bamboo-valley']) {
    const m = map(name);
    wallPatternDefs();
    let bytes = 0;
    const start = performance.now();
    for (let run = 0; run < 100; run++) {
      for (const wall of m.walls) bytes += wallLookMarkup(wall, m.walls)?.length || 0;
      for (const row of m.terrain) for (const [x, y] of row.cells)
        bytes += terrainCellMarkup(row.type, row.look, false, x * 73856093 ^ y * 19349663).length;
    }
    console.log(`MAPART2 ${baseline ? 'BEFORE' : 'AFTER'} ${name} wall+terrain markup: ${((performance.now() - start) / 100).toFixed(3)} ms/map; ${bytes} bytes/100 maps`);
  }
  const start = performance.now();
  for (let run = 0; run < 100; run++) wallPatternDefs();
  console.log(`MAPART2 ${baseline ? 'BEFORE' : 'AFTER'} shared wall definitions: ${((performance.now() - start) / 100).toFixed(3)} ms/board`);
});
