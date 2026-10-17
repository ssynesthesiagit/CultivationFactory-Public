import test from 'node:test';
import assert from 'node:assert/strict';
import {performance} from 'node:perf_hooks';
import {blockerSegments, fogPointVisible, paintFogMask, visibilityPolygons} from './fog_polygon.js';
import {altitudeVisibilityPolygons} from './fog-altitude.js';

const bounds = (segments, x) => segments.some(([a, b]) => Math.abs(a[0] - x) < 0.001 && Math.abs(b[0] - x) < 0.001);
const maxX = points => Math.max(...points.map(point => point[0]));

test('continuous visibility ends at the actual wall line instead of a wall square edge', () => {
  const walls = [{shape: 'line', points: [[5, 0], [5, 10]], cells: [[5, 0], [5, 1]]}];
  const blockers = blockerSegments({walls, width: 10, height: 10});
  const [poly] = visibilityPolygons([{entity_id: 'viewer', position: {x: 2.5, y: 5.5}}], blockers, 10, 10);
  assert.equal(maxX(poly.points), 5);
  assert.ok(bounds(blockers, 5));
});

test('doors, windows, and tree trunks add opaque geometry', () => {
  const blockers = blockerSegments({width: 12, height: 8,
    objects: [{kind: 'door', x: 4, y: 2, hp: 10, blocks: true}, {kind: 'window', x: 8, y: 2, hp: 10, blocks: true}],
    trees: [{x: 6, y: 2, size: 1}]});
  const polygons = visibilityPolygons([{x: 1.5, y: 2.5}], blockers, 12, 8);
  // The square behind the door is dark because the door's own geometry stops the
  // rays, not because of a square gate: the whole grid is approved here.
  assert.equal(fogPointVisible(5.5, 2.5, 12, 8, new Uint8Array(96).fill(1), polygons), false, 'door hides the square behind it');
  assert.ok(blockers.some(([a, b]) => a[0] === 6 && b[0] === 6), 'tree trunk edge is a blocker');
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
