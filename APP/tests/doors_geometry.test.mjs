import test from 'node:test';
import assert from 'node:assert/strict';
import {wallMount, wallPieces, openingRotation, openingOffset, rotateObject} from '../static/tabletop/wall-openings.js';
import {rasterizeWalls, mapCenterlines} from '../static/tabletop/vision.js';
import {objectArt} from '../static/tabletop/object-art.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';

for (const axis of ['h','v']) test(`one-square ${axis} opening, flush ends and thin-occluder parity`,()=>{
  const wall={shape:'line',points:axis==='h'?[[1,4],[7,4]]:[[4,1],[4,7]],blocks:'sight_and_movement',occluder:'centerline'};
  const o={kind:'door',x:4,y:4};
  Object.assign(o,wallMount(o,[wall]));
  assert.equal(o.mount_axis,axis);
  assert.equal(openingRotation(o),axis==='h'?0:90);
  assert.deepEqual(wallPieces(wall,[o]).map(w=>w.points),axis==='h'?[[[1,4],[4,4]],[[5,4],[7,4]]]:[[[4,1],[4,4]],[[4,5],[4,7]]]);
  assert.ok(wallPieces(wall,[o]).every(w=>w.door_join));
  assert.ok(!rasterizeWalls([wall],8,8,[o]).blocked.some(([x,y])=>x===4&&y===4));
  const thin=mapCenterlines({width_squares:8,height_squares:8,walls:[wall],objects:[o]});
  assert.ok(!thin.some(([x,y])=>x===4&&y===4));
  assert.deepEqual(openingOffset(o),axis==='h'?{offsetY:-.5}:{offsetX:-.5});
  rotateObject(o); rotateObject(o,-90); assert.equal(o.rotation,axis==='h'?0:90);
  for(let i=0;i<4;i++) rotateObject(o);
  assert.equal(o.rotation,axis==='h'?0:90);
  const token=tableObjectTokens([o],new Set(),[],null,8)[0];
  assert.equal(token.rotation,o.rotation);
  o.rotation=0;
  assert.equal(tableObjectTokens([o],new Set(),[],null,8)[0].rotation,0,'manual orientation overrides auto-orientation');
});
test('legacy walls and unrelated placements are unchanged',()=>{
  const wall={shape:'line',points:[[0,3],[3,3],[3,6]]};
  assert.deepEqual(wallPieces(wall,[{kind:'door',x:2,y:3}]),[wall]);
  assert.equal(wallMount({kind:'crate',x:2,y:3},[wall]),null);
  for(const kind of ['door','gate','window']) assert.equal(wallMount({kind,x:2,y:3},[wall]).mount_axis,'h');
  assert.deepEqual(rasterizeWalls([wall],8,8),rasterizeWalls([wall],8,8,[{kind:'door',x:2,y:3}]));
});
test('an opening only clears its segment in a self-crossing polyline',()=>{
  const wall={shape:'line',points:[[0,6],[12,6],[4,0],[4,12]],occluder:'centerline'};
  const door={kind:'door',x:4,y:6,mount_axis:'h',mount_line:600};
  assert.ok(wallPieces(wall,[door]).some(w=>JSON.stringify(w.points)===JSON.stringify([[4,0],[4,12]])));
  for (const cells of [rasterizeWalls([wall],20,14,[door]).blocked,
      mapCenterlines({width_squares:20,height_squares:14,walls:[wall],objects:[door]})]) {
    assert.ok(cells.some(([x,y])=>x===4&&y===6),'crossing segment remains a barrier');
    assert.ok(cells.some(([x,y])=>x===3&&y===6),'adjacent wall remains a barrier');
  }
});
for (const axis of ['h','v']) test(`a partially overlapping ${axis} return segment stays drawn and blocked`,()=>{
  const point = (along,cross) => axis==='h'?[along,cross]:[cross,along];
  const wall={shape:'line',points:[point(0,6),point(12,6),point(4.5,6)],occluder:'centerline'};
  const door={kind:'door',x:axis==='h'?4:6,y:axis==='h'?6:4,mount_axis:axis,mount_line:600};
  const pieces=wallPieces(wall,[door]);
  assert.deepEqual(pieces.map(w=>w.points),[
    [point(0,6),point(4,6)], [point(5,6),point(12,6)], [point(12,6),point(4.5,6)],
  ],'only the fully containing segment receives an aperture');
  assert.ok(!pieces[2].door_join,'uncut return segment has ordinary wall ends');
  const map={width_squares:20,height_squares:20,walls:[wall],objects:[door]};
  for (const cells of [rasterizeWalls([wall],20,20,[door]).blocked,
      rasterizeWalls(pieces,20,20).blocked, mapCenterlines(map)]) {
    assert.ok(cells.some(([x,y])=>x===door.x&&y===door.y),'partial return remains a barrier in rendering and rules');
  }
});
test('all drawn objects honor rotation and openings show a swung leaf',()=>{
  // The bell is the one exception: it is drawn from a little to the south (SOL196) so it always hangs upright.
  for(const kind of ['cart','chest','barrel','statue','door','gate','window'])
    assert.match(objectArt(kind,{rotation:90}),/rotate\(90 32 32\)/);
  assert.doesNotMatch(objectArt('bell',{rotation:90}),/rotate\(90 32 32\)/);
  for(const kind of ['door','gate','window']) {
    assert.notEqual(objectArt(kind),objectArt(kind,{open:true}));
    assert.match(objectArt(kind,{open:true}),/tt-art-arc/);
  }
});
