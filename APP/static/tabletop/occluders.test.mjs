import test from 'node:test';
import assert from 'node:assert/strict';
import {opacityGrid,lineOfSight,crossBlocks,centerlineTerrain,mapCenterlines} from './vision.js';
import {blockerSegments,visibilityPolygons} from './fog_polygon.js';
import {cellSegments} from './sight-lines.js';

test('crosses block each arm, leave corner gaps and visible endpoint cells',()=>{
  assert.equal(crossBlocks(0,2,5,2,2,2),true);
  assert.equal(crossBlocks(2,0,2,5,2,2),true);
  assert.equal(crossBlocks(0,0,4,3,1,0),false);
  const mask=opacityGrid(8,8,[[[2,2]]],[[2,2]]);
  assert.equal(lineOfSight(8,mask,0,2,5,2),false);
  assert.equal(lineOfSight(8,mask,0,2,2,2),true);
});

test('one cross per cell, neighbouring tips join, solid cells retain centre runs and end caps',()=>{
  const seg=blockerSegments({centerlineCells:[[2,2],[3,2]],blockedCells:[[2,2],[3,2],[5,5]]});
  assert.ok(seg.some(([a,b])=>a[0]===2 && a[1]===2.5 && b[0]===3 && b[1]===2.5));
  assert.ok(seg.some(([a,b])=>a[0]===3 && a[1]===2.5 && b[0]===4 && b[1]===2.5));
  assert.equal(seg.length,7); // four cross arms and one solid run with two caps
  assert.deepEqual(seg.filter(s=>!s.occluderCell),cellSegments([[5,5]]));
});

test('fog reaches the near half of bamboo, ends at its cross, keeps shadow behind it',()=>{
  const polygons=visibilityPolygons([{entity_id:'eye',position:{x:0.5,y:2.5}}],
    blockerSegments({centerlineCells:[[2,2]],blockedCells:[[2,2]]}),8,8);
  const points=polygons[0].points;
  // The east cardinal ray used to end at x=2, the square perimeter.
  assert.ok(points.some(([x,y])=>Math.abs(x-2.5)<1e-6 && Math.abs(y-2.5)<1e-6));
  assert.ok(!points.some(([x,y])=>x>2.50001 && Math.abs(y-2.5)<1e-6));
});

test('fight policy and explicit overrides win over tree/bamboo defaults',()=>{
  const rows=[{terrain_type:'SIGHT_BLOCKED',occluder:'centerline',cells:[{x:2,y:2}]}];
  assert.deepEqual(centerlineTerrain(rows,'cell-v1'),[]);
  assert.deepEqual(centerlineTerrain(rows,'cross-v1'),[[2,2]]);
  assert.deepEqual(centerlineTerrain([...rows,{terrain_type:'BLOCKED',cells:[{x:2,y:2}]}],'cross-v1'),[]);
  const doc={width_squares:8,height_squares:8,walls:[],trees:[{x:5,y:5,size:1}],materials:[
    {material:'terrain:bamboo thicket',cells:[[2,2],[2,3],[3,2],[3,3]]}]};
  assert.equal(mapCenterlines(doc).length,5);
  doc.materials[0].occluder='cell';doc.trees[0].occluder='cell';
  assert.deepEqual(mapCenterlines(doc),[]);
});

test('viewer inside bamboo keeps outward sight; dynamic obscurement stays full',()=>{
  const blockers=blockerSegments({centerlineCells:[[2,2]],blockedCells:[[2,2]]});
  const [p]=visibilityPolygons([{x:2.5,y:2.5}],blockers,8,8);
  assert.ok(p.points.some(([x])=>x===8));
  const dynamic=blockerSegments({centerlineCells:[[2,2]],blockedCells:[[2,2]],dynamicCells:[[2,2]]});
  const [q]=visibilityPolygons([{x:0.5,y:2.5}],dynamic,8,8);
  assert.ok(q.points.some(([x,y])=>Math.abs(x-2)<1e-6 && Math.abs(y-2.5)<1e-6));
});
