import test from 'node:test';
import assert from 'node:assert/strict';
import {createTableHarness, actor, tableState} from './viewer_identity_harness.mjs';
import {fogPointVisible, paintFogMask} from '../static/tabletop/fog_polygon.js';
import {altitudeVisibilityPolygons} from '../static/tabletop/fog-altitude.js';
import {detectRoofRegions} from '../static/tabletop/roof-regions.js';
import {readFileSync} from 'node:fs';

test('the two owner maps have no inferred roof regions', () => {
  for (const name of ['builtin-realm-waterfall-gorge','builtin-frontier-bamboo-imperial-tomb']) {
    const map=JSON.parse(readFileSync(new URL(`../combat/maps/${name}.json`,import.meta.url),'utf8'));
    const floors=(map.materials || []).filter(r=>r.material.startsWith('floor:'))
      .map(r=>({style:r.material.slice(6),cells:r.cells}));
    assert.deepEqual(detectRoofRegions({...map,width:map.width_squares,height:map.height_squares,floors}),[]);
  }
});

test('the canvas painter uses finite bound tree shadows, not decorative canopy circles', () => {
  const polygons=altitudeVisibilityPolygons([{position:{x:1.5,y:1.5,z:8}}],{
    volumes:[{x:4,y:4,mode:'centerline',bottom_ft:0,top_ft:25}],
    treeCells:['4,4'],trees:[{x:4,y:4,size:1}],roofs:[]},16,16)
    .filter(p=>p.surface_ft===0);
  // Execute the production canvas commands on three sparse sample pixels.
  // This tests the painted paths, independently of sampleShadows.
  const samples=[[7.5,4.5],[8.5,8.5],[12.5,12.5]];
  const inside=(point,path)=>{
    let value=false;
    for (let i=0,j=path.length-1;i<path.length;j=i++) {
      const [x,y]=point,[xi,yi]=path[i],[xj,yj]=path[j];
      if ((yi>y)!==(yj>y) && x<(xj-xi)*(y-yi)/(yj-yi)+xi) value=!value;
    }
    return value;
  };
  let paths=[], mask=samples.map(()=>true), stack=[];
  const lit=samples.map(()=>false);
  const context={beginPath(){paths=[];},moveTo(x,y){paths.push([[x,y]]);},
    lineTo(x,y){paths.at(-1).push([x,y]);},closePath(){},
    save(){stack.push([...mask]);},restore(){mask=stack.pop();},
    clip(){mask=mask.map((allowed,i)=>allowed && paths.filter(p=>inside(samples[i],p)).length%2===1);},
    fill(){samples.forEach((point,i)=>{if(mask[i] && paths.some(p=>inside(point,p)))lit[i]=true;});},
    fillRect(){throw new Error('no token or square fallback expected');}};
  paintFogMask(context,16,16,[],{polygons},1);
  assert.deepEqual(lit,[true,false,true],
    'clear side ground stays visible; near ground is hidden; far ground clears the tree top');
});

test('production fog ascent over a 10 ft wall keeps only its finite ground shadow', () => {
  const viewer=actor('eye',{x:1,y:3,z:0},{altitude_ft:0});
  const state=tableState([viewer],{map:{width_squares:12,height_squares:8,
    walls:[{shape:'rect',points:[[4,0],[5,8]],filled:true,blocks:'sight_and_movement',height_ft:10}],trees:[]}});
  state.fog_geometry={volumes:Array.from({length:8},(_,y)=>
    ({x:4,y,mode:'cell',bottom_ft:0,top_ft:10,solid:true})),roofs:[]};
  const h=createTableHarness({boundIds:['eye'],roster:[viewer],state});
  h.location.search='?match=match';
  const floor=()=>h.fogGeometry(new Uint8Array(96)).polygons
    .filter(p=>p.surface_ft===0 || p.surface_ft==null).map(({covered,...p})=>p);
  const visible=(x,polygons)=>fogPointVisible(x,3.5,12,8,[],polygons);
  assert.equal(visible(8.5,floor()),false,'ground eye cannot see behind the wall');
  viewer.position.z=8;
  viewer.altitude_ft=40;
  const high=floor();
  // Far wall face is d=3.5 cells from the eye. Its shadow ends at
  // x=1.5 + 3.5 * 40/(40-10) = 6 1/6, not the map edge.
  assert.equal(visible(5.5,high),false,'near ground remains hidden');
  assert.equal(visible(6.5,high),true,'far ground clears the wall top');
  assert.equal(visible(8.5,high),true);
  const painted=high.map(({sampleShadows,...p})=>p);
  assert.equal(visible(5.5,painted),false);
  assert.equal(visible(6.5,painted),true,'painted and sampled shadows agree');
});
