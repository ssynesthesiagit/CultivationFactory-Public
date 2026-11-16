import test from 'node:test';
import assert from 'node:assert/strict';
import {altitudeVisibilityPolygons, altitudeFogKey, viewerEye} from '../static/tabletop/fog-altitude.js';
import {fogPointVisible, paintFogMask, fogTokenCells, roofPresentationPolygons} from '../static/tabletop/fog_polygon.js';
import {createTableHarness, actor, tableState} from './viewer_identity_harness.mjs';
import {perceivedObjects} from '../static/tabletop/vision.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';

const eye={entity_id:'eye',position:{x:1.5,y:3.5,z:16}};
const visible=(polygons,x,y=3.5)=>fogPointVisible(x,y,12,8,[],polygons);
const polygons=(geometry,viewers=[eye])=>altitudeVisibilityPolygons(viewers,geometry,12,8);
const inPolygon=(x,y,points)=>{
  let inside=false;
  for(let i=0,j=points.length-1;i<points.length;j=i++){
    const [xi,yi]=points[i],[xj,yj]=points[j];
    if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi) inside=!inside;
  }
  return inside;
};

test('80 ft eye sees over finite walls and objects, retaining the near shadow',()=>{
  const p=polygons({volumes:[{x:4,y:3,bottom_ft:0,top_ft:15}]});
  assert.equal(visible(p,5.1),false);
  assert.equal(visible(p,5.9),true);
  assert.equal(visible(p,9.5),true);
  assert.equal(visible(p,5.5,5.5),true,'around the wall corner');
  assert.equal(visible(polygons({volumes:[{x:4,y:3,bottom_ft:0,top_ft:null}]}),9.5),false);
});

test('roof surface is contiguous and visible; the floor below remains hidden',()=>{
  const geometry={volumes:[],roofs:Array.from({length:3},(_,i)=>({x:3+i,y:3,top_ft:23}))};
  const p=polygons(geometry), floor=p.filter(r=>r.surface_ft===0);
  for (const x of [3.5,4.5,5.5]) assert.equal(visible(p,x),true);
  assert.equal(visible(floor,4.5),false);
  assert.equal(visible(p,10.5),true);
});

test('altitude field names and cache inputs include a vertical-only ascent',()=>{
  assert.equal(viewerEye(eye),80);
  assert.equal(viewerEye({...eye,altitude_ft:85}),85);
  assert.notEqual(altitudeFogKey([eye],{}),altitudeFogKey([{...eye,position:{...eye.position,z:0}}],{}));
  const a=actor('eye',{x:1,y:3,z:16},{altitude_ft:80});
  const state=tableState([a],{map:{width_squares:12,height_squares:8,walls:[],trees:[]}});
  state.fog_geometry={volumes:[{x:4,y:3,bottom_ft:0,top_ft:15}],roofs:[]};
  const h=createTableHarness({boundIds:['eye'],roster:[a],state});
  h.location.search='?match=match';
  const before=h.fogGeometry(new Uint8Array(96)).polygons;
  assert.equal(visible(before,9.5),true);
  h.app.state.presentation.actors[0].position.z=1;
  h.app.state.presentation.actors[0].altitude_ft=5;
  const after=h.fogGeometry(new Uint8Array(96)).polygons;
  assert.notEqual(after,before);
  assert.equal(visible(after,9.5),false);
});

test('painter clips separate footprints, then restores before the next viewer',()=>{
  const calls=[];
  const context=new Proxy({}, {get:(_,key)=>(...args)=>calls.push([key,...args]),set:()=>true});
  // Adjacent equal-height cells share one smoothed footprint; these separated
  // blockers retain two clips so this still checks isolation and restoration.
  const p=polygons({volumes:[{x:4,y:3,bottom_ft:0,top_ft:15},{x:7,y:3,bottom_ft:0,top_ft:15}]});
  paintFogMask(context,12,8,[],{polygons:p});
  assert.equal(calls.filter(c=>c[0]==='clip'&&c[1]==='evenodd').length,2);
  assert.equal(calls.filter(c=>c[0]==='save').length,1);
  assert.equal(calls.filter(c=>c[0]==='restore').length,1);
});

test('connected blocker ring leaves its clear courtyard out of the painted shadows',()=>{
  const ring=[];
  for(let x=2;x<=4;x++) for(let y=2;y<=4;y++)
    if(x===2||x===4||y===2||y===4) ring.push({x,y,bottom_ft:0,top_ft:20});
  const floor=polygons({volumes:ring},[{position:{x:3.5,y:3.5,z:8}}])[0];
  assert.equal(visible([floor],3.5,3.5),true,'exact per-cell perception still sees the ground below the viewer');
  assert.equal(floor.shadows.some(shadow=>inPolygon(3.5,3.5,shadow)),false,
    'the renderer must not fill the open courtyard with a convex hull');
});

test('centerline scenery paints its cross arms instead of a solid cell square',()=>{
  const row={x:10,y:10,mode:'centerline',bottom_ft:0,top_ft:8};
  const p=altitudeVisibilityPolygons([{position:{x:1.5,y:1.5,z:16}}],{volumes:[row]},12,12);
  assert.equal(fogPointVisible(11.5,11.5,12,12,[],p),true,
    'the exact cross arms do not block this diagonal target');
  assert.equal(p[0].shadows.some(shadow=>inPolygon(11.5,11.5,shadow)),false,
    'the painted mask must leave the same diagonal target visible');
});

test('server sense limits affect their own surface and viewer only',()=>{
  const geometry={volumes:[],roofs:[{x:4,y:3,top_ft:23}],limits:{eye:[[8,3,0],[4,3,23]]}};
  const p=polygons(geometry);
  assert.equal(visible(p,8.5),false);
  assert.equal(visible(p,4.5),false);
  assert.equal(visible(polygons(geometry,[{...eye,entity_id:'ally'}]),8.5),true);
});

test('under-eave floor and furniture cannot light isolated closed roof tiles',()=>{
  const geometry={volumes:[],roofs:[{x:4,y:3,top_ft:23}],limits:{eye:[[4,3,23]]}};
  const p=polygons(geometry);
  const floor=p.filter(r=>r.surface_ft===0).map(({covered,...plane})=>plane);
  assert.equal(visible(floor,4.5),true,'floor near the eave is geometrically visible');
  assert.equal(visible(p,4.5),false,'that floor does not reveal the obscured roof top');
  const closed=new Map([['4,3',23]]), table={x:4,y:3,object:true,hidden:false};
  assert.deepEqual(fogTokenCells([table],closed),[]);
  assert.deepEqual(fogTokenCells([{...table,altitudeFt:25}],closed),[[4,3]]);
  assert.deepEqual(fogTokenCells([{x:4,y:3}],closed),[[4,3]],'perceived creature exception stays');
  assert.equal(visible(roofPresentationPolygons(p,new Set(['4,3'])),4.5),true,'open roof reveals only its floor ray');
});

test('viewer exactly at roof height sees its surface and cannot look down through it',()=>{
  const p=polygons({volumes:[],roofs:[{x:1,y:3,top_ft:80}]});
  assert.equal(visible(p,1.5),true);
  const floor=p.filter(r=>r.surface_ft===0).map(({covered,...plane})=>plane);
  assert.equal(visible(floor,1.5),false);
  assert.equal(visible(floor,8.5),false,'downward ray begins on the opaque roof');
});

test('finite solid wall top is visible separately from its hidden floor',()=>{
  const p=polygons({volumes:[{x:4,y:3,bottom_ft:0,top_ft:15,mode:'cell',solid:true}]});
  assert.equal(visible(p,4.5),true);
  assert.equal(visible(p.filter(r=>r.surface_ft===0).map(({covered,...r})=>r),4.5),false);
  assert.equal(visible(roofPresentationPolygons(p,new Set(['4,3'])),4.5),true,'roof toggle does not erase a wall top');
});

test('above a finite object, its top is shown even though its floor is hidden',()=>{
  const object={id:'box',x:4,y:3,hp:5,height_ft:10};
  const perception={eye:{cells:[],objects:['box']}};
  const ids=perceivedObjects([eye],perception,[object]);
  const [token]=tableObjectTokens([object],new Set(),[],new Uint8Array(96),12,'',ids);
  assert.equal(token.hidden,false);
  assert.equal(perceivedObjects([{entity_id:'ground'}],{ground:{cells:[[4,3]]}},[object]).has('box'),true);
});

test('finite cross top is exclusive, parallel arms keep their full 3D interval',()=>{
  const row={x:10,y:3,mode:'centerline',bottom_ft:0,top_ft:8};
  assert.equal(visible(polygons({volumes:[row]}),11.5),false,'parallel arm continues below the midpoint height');
  const diagonal=altitudeVisibilityPolygons([{position:{x:1.5,y:1.5,z:16}}],{volumes:[{...row,y:10}]},12,12);
  assert.equal(fogPointVisible(11.5,11.5,12,12,[],diagonal),true,'both arms touched only at the exclusive top');
  assert.equal(visible(polygons({volumes:[{...row,x:1}]}),1.5),false,'vertical ray hits the cross below the viewer');
});
