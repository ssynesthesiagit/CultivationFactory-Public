import test from 'node:test';
import assert from 'node:assert/strict';
import {performance} from 'node:perf_hooks';
import {blockerSegments, fogPointVisible, fogPresentationGeometry, paintFogMask, visibilityPolygons} from './fog_polygon.js';
import {altitudeVisibilityPolygons} from './fog-altitude.js';

const bounds = (segments, x) => segments.some(([a, b]) => Math.abs(a[0] - x) < 0.001 && Math.abs(b[0] - x) < 0.001);
const maxX = points => Math.max(...points.map(point => point[0]));

test('continuous visibility ends at the bound wall centre run instead of a wall square edge', () => {
  const walls = [{shape: 'line', points: [[5, 0], [5, 10]],
    cells: Array.from({length: 10}, (_, y) => [5, y])}];
  const blockers = blockerSegments({walls, width: 10, height: 10});
  const [poly] = visibilityPolygons([{entity_id: 'viewer', position: {x: 2.5, y: 5.5}}], blockers, 10, 10);
  assert.equal(maxX(poly.points), 5.5);
  assert.deepEqual(blockers, [[[5.5, 0], [5.5, 10]], [[5, 0], [6, 0]], [[5, 10], [6, 10]]]);
  assert.ok(bounds(blockers, 5.5));
});

test('doors, windows, and tree trunks add opaque geometry', () => {
  const blockers = blockerSegments({width: 12, height: 8,
    objects: [{kind: 'door', x: 4, y: 2, hp: 10, blocks: true}, {kind: 'window', x: 8, y: 2, hp: 10, blocks: true}],
    trees: [{x: 6, y: 2, size: 1}]});
  const polygons = visibilityPolygons([{x: 1.5, y: 2.5}], blockers, 12, 8);
  // The square behind the door is dark because the door's own geometry stops the
  // rays, not because of a square gate: the whole grid is approved here.
  assert.equal(fogPointVisible(5.5, 2.5, 12, 8, new Uint8Array(96).fill(1), polygons), false, 'door hides the square behind it');
  assert.deepEqual(blockers.filter(s => s.occluderCell?.join(',') === '6,2').map(s => [...s]),
    [[[6, 2.5], [7, 2.5]], [[6.5, 2], [6.5, 3]]], 'tree blocks on its two bound centre arms');
  assert.ok(blockers.some(([a, b]) => a[0] === 8 && b[0] === 8), 'window edge is a blocker');
});

test('visibility polygons union over two viewers', () => {
  const blockers = blockerSegments({walls: [{shape: 'line', points: [[5, 0], [5, 10]]}], width: 10, height: 10});
  const polygons = visibilityPolygons([
    {entity_id: 'left', position: {x: 2.5, y: 5}},
    {entity_id: 'right', position: {x: 7.5, y: 5}},
  ], blockers, 10, 10);
  assert.equal(polygons.length, 2);
  const none = new Uint8Array(100);
  assert.equal(fogPointVisible(7.5, 5.5, 10, 10, none, [polygons[0]]), false,
    'one viewer does not light the other side of the wall');
  assert.ok(fogPointVisible(2.5, 5.5, 10, 10, none, polygons));
  assert.ok(fogPointVisible(7.5, 5.5, 10, 10, none, polygons), 'the union lights both rooms');
  // The service's approved squares are the token decision, not a gate on the
  // drawn shape: with the contract in the fog_polygon header, the polygon is
  // what gets drawn and the squares only reach tokens.
  const seen = new Uint8Array(100);
  seen[5 * 10 + 2] = 1; seen[5 * 10 + 7] = 1;
  assert.ok(fogPointVisible(0.5, 0.5, 10, 10, seen, polygons),
    'an approved square list does not clip the drawn polygon');
});

test('a reverse duplicate of a drawn wall does not remove its barrier', () => {
  const blockers = blockerSegments({walls: [
    {shape: 'line', points: [[5, 0], [5, 10]]},
    {shape: 'line', points: [[5, 10], [5, 0]]},
  ]});
  assert.equal(blockers.length, 1);
  const polygons = visibilityPolygons([{x: 2.5, y: 5.5}], blockers, 10, 10);
  // Every square is approved, so the darkness here is the barrier's doing.
  assert.equal(fogPointVisible(5.5, 5.5, 10, 10, new Uint8Array(100).fill(1), polygons), false);
});

test('large circular walls approximate the drawn shape within half a display pixel', () => {
  const radius = 8;
  const blockers = blockerSegments({walls: [{shape: 'circle', points: [[10, 10], [10 + radius, 10]]}]});
  for (const [a, b] of blockers) {
    const midpointRadius = Math.hypot((a[0] + b[0]) / 2 - 10, (a[1] + b[1]) / 2 - 10);
    assert.ok((radius - midpointRadius) * 64 <= 0.5);
  }
});

test('bamboo altitude shadows use deterministic server-bound cross arms', () => {
  const geometry={volumes:[
    {x:5,y:3,mode:'centerline',bottom_ft:0,top_ft:20},
  ],bambooCells:['5,3']};
  const polygons=altitudeVisibilityPolygons([{altitude_ft:40,position:{x:1.5,y:3.5}}],geometry,12,8);
  const floor=polygons.find(p=>p.surface_ft===0);
  assert.equal(floor.shadows.length,2,'both bound cross arms remain blockers');
  assert.deepEqual(floor.shadows,floor.sampleShadows,
    'decorative stalk circles must not replace authoritative sight geometry');
  const again=altitudeVisibilityPolygons([{altitude_ft:40,position:{x:1.5,y:3.5}}],geometry,12,8)[0];
  assert.deepEqual(floor.shadows,again.shadows,'projection is stable for the same blocker cell');
});

test('vegetation shadows retain the full stalk height below, at, and above its top', () => {
  const geometry={volumes:[{x:5,y:3,mode:'centerline',bottom_ft:0,top_ft:20}],bambooCells:['5,3']};
  for (const eyeFt of [10,20,40]) {
    const floor=altitudeVisibilityPolygons([{altitude_ft:eyeFt,position:{x:1.5,y:3.5}}],geometry,12,8)[0];
    assert.equal(floor.shadows.length,2,'the full stalk span casts both cross-arm shadows');
    assert.ok(floor.shadows.some(shape=>Math.max(...shape.map(([x])=>x))>6.5),
      `the near stalk volume shadow reaches ground beyond the stand at ${eyeFt} ft`);
  }
});

test('dense vegetation retains every bound blocker without a drawing budget', () => {
  const rows=Array.from({length:400},(_,i)=>({x:i*2+5,y:1,mode:'centerline',bottom_ft:0,top_ft:20}));
  const bambooCells=rows.map(({x,y})=>`${x},${y}`);
  const floor=altitudeVisibilityPolygons([{altitude_ft:40,position:{x:1.5,y:1.5}}],
    {volumes:rows,bambooCells},810,4)[0];
  assert.equal(floor.shadows.length,rows.length*2,
    'every cell retains both authoritative arms');
});

test('tree altitude shadows use the authored height without inventing a canopy plane', () => {
  const geometry={volumes:[{x:5,y:3,mode:'centerline',bottom_ft:0,top_ft:40}],
    treeCells:['5,3'],trees:[{x:5,y:3,size:1}]};
  const floor=altitudeVisibilityPolygons([{altitude_ft:60,position:{x:1.5,y:3.5}}],geometry,12,8)[0];
  assert.equal(floor.shadows.length,2);
  assert.deepEqual(floor.shadows,floor.sampleShadows,
    'tree art cannot create additional sight blockers');
});

test('only service-perceived token squares override a polygon edge', () => {
  // The drawn mask is the polygon; the service's squares reach it only through a
  // token the service reports as perceived.
  const seen = new Uint8Array(100); seen[5 * 10 + 5] = 1;
  assert.equal(fogPointVisible(5.05, 5.05, 10, 10, seen, []), false, 'an approved floor square alone lights nothing');
  assert.equal(fogPointVisible(5.05, 5.05, 10, 10, seen, [], [[5, 5]]), true, 'a perceived token lights its own square');
  assert.equal(fogPointVisible(5.05, 5.05, 10, 10, seen, [], [], true), true, 'old square debug view');
});

// Darkness regression: the owner screenshot's dark cells and viewer (6.5,5.5).
// Main's presentation lit (3.03,6.03) inside dark cell (3,6); the shadow pass
// simplified the ray hits along the darkness face away.
function litInPresentation(pres, x, y) {
  const inside = (points) => {
    let c = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [xi, yi] = points[i], [xj, yj] = points[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  return pres.some(p => inside(p.points) && !(p.shadows || []).some(inside) && !(p.wideShadows || []).some(inside));
}
function darkSamples(cells) {
  const samples = [];
  for (const [x, y] of cells) for (let sx = x + 0.03; sx < x + 1; sx += 0.1) for (let sy = y + 0.03; sy < y + 1; sy += 0.1) samples.push([sx, sy]);
  return samples;
}

test('darkness faces are never lit by the presentation outline (leak fixture from randomized search)', () => {
  // Found by a seeded search: main lit (3.03,6.03) inside dark cell (3,6) for this viewer.
  const dynamicCells = [[5,7],[6,7],[6,6],[5,6],[5,5],[4,5],[3,5],[3,6],[3,7],[4,7]];
  const W = 12, H = 12, viewer = {x: 6.5, y: 5.5};
  const polygons = visibilityPolygons([viewer], blockerSegments({dynamicCells, width: W, height: H}), W, H);
  const pres = fogPresentationGeometry(polygons, W, H, 32);
  assert.equal(litInPresentation(pres, 3.03, 6.03), false);
  for (const [x, y] of darkSamples(dynamicCells)) {
    assert.equal(litInPresentation(pres, x, y), false, `dark sample (${x.toFixed(2)},${y.toFixed(2)}) must stay unlit`);
  }
});

for (const sources of [undefined, []]) test(`obscurement keeps its full footprint and pinned faces with bound sources=${!!sources}`, () => {
  const dynamicCells = [[6, 6], [6, 7], [5, 6]];
  const blockers = blockerSegments({sources, dynamicCells, width: 12, height: 12});
  const polygons = visibilityPolygons([{x: 6.5, y: 5.5}], blockers, 12, 12);
  assert.ok(polygons[0].pinned.some(Boolean), 'bound and legacy inputs preserve dynamic provenance');
  const pres = fogPresentationGeometry(polygons, 12, 12);
  for (const [x, y] of darkSamples(dynamicCells)) {
    assert.equal(fogPointVisible(x, y, 12, 12, [], polygons), false, 'exact mask cannot see into darkness');
    assert.equal(litInPresentation(pres, x, y), false, 'presentation cannot see into darkness');
  }
  assert.equal(fogPointVisible(6.5, 5, 12, 12, [], polygons), true, 'clear ground before its edge remains visible');
});

test('randomized darkness shapes never light a dark sample for a viewer outside them', () => {
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const W = 12, H = 12;
  let trials = 0;
  for (let t = 0; t < 120; t++) {
    const cells = new Set();
    let cx = 3 + Math.floor(rnd() * 6), cy = 3 + Math.floor(rnd() * 6);
    for (let k = 0; k < 12 + Math.floor(rnd() * 20); k++) {
      cells.add(`${cx},${cy}`);
      const d = Math.floor(rnd() * 4);
      cx = Math.max(1, Math.min(W - 2, cx + [1, -1, 0, 0][d])); cy = Math.max(1, Math.min(H - 2, cy + [0, 0, 1, -1][d]));
    }
    const list = [...cells].map(s => s.split(',').map(Number));
    for (let q = 0; q < 6; q++) {
      const viewer = {x: Math.floor(rnd() * W) + 0.5, y: Math.floor(rnd() * H) + 0.5};
      if (cells.has(`${Math.floor(viewer.x)},${Math.floor(viewer.y)}`)) continue;
      trials++;
      const pres = fogPresentationGeometry(visibilityPolygons([viewer], blockerSegments({dynamicCells: list, width: W, height: H}), W, H), W, H, 32);
      for (const [x, y] of darkSamples(list)) assert.equal(litInPresentation(pres, x, y), false, `viewer ${viewer.x},${viewer.y} lit a dark sample`);
    }
  }
  assert.ok(trials > 300);
});

test('walls-only and viewer-inside-darkness polygons carry no darkness flags', () => {
  const walls = blockerSegments({walls: [{shape: 'line', points: [[5, 0], [5, 10]]}], width: 10, height: 10});
  assert.equal(visibilityPolygons([{x: 2.5, y: 2.5}], walls, 10, 10)[0].pinned, undefined);
  const dark = blockerSegments({dynamicCells: [[2, 2], [3, 2]], width: 10, height: 10});
  assert.equal(visibilityPolygons([{x: 2.5, y: 2.5}], dark, 10, 10)[0].pinned, undefined, 'viewer inside darkness keeps the main path');
  assert.ok(visibilityPolygons([{x: 6.5, y: 2.5}], dark, 10, 10)[0].pinned.some(Boolean), 'an outside viewer gets the dark-face flags');
});

test('polygon calculation benchmark: 40x20 map and 10 viewers', () => {
  const walls = Array.from({length: 20}, (_, i) => ({shape: 'line', points: [[10 + i % 4, 0], [10 + i % 4, 20]]}));
  const trees = Array.from({length: 20}, (_, i) => ({x: i % 40, y: 2 + Math.floor(i / 4), size: i % 3 === 0 ? 2 : 1}));
  const blockers = blockerSegments({walls, trees, width: 40, height: 20});
  const viewers = Array.from({length: 10}, (_, i) => ({entity_id: String(i), position: {x: 2 + i * 3.5, y: 3 + (i % 5) * 3}}));
  const samples = [];
  for (let i = 0; i < 8; i++) {
    const start = performance.now();
    visibilityPolygons(viewers, blockers, 40, 20);
    if (i > 0) samples.push(performance.now() - start);
  }
  samples.sort((a, b) => a - b);
  console.log(`fog polygon benchmark median: ${samples[Math.floor(samples.length / 2)].toFixed(2)} ms; 40x20, 10 viewers, ${blockers.length} segments`);
  assert.ok(samples.every(Number.isFinite));
});
