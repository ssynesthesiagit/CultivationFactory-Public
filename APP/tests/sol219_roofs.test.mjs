import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {detectRoofRegions, insideRoof, roofOpacity, roofSettings} from '../static/tabletop/roof-regions.js';
import {EAVE, roofGeometry, roofMarkup} from '../static/tabletop/roof-art.js';
import {createBoard} from '../static/tabletop/board.js';
import {installDOM} from './objects_dom_stub.mjs';
import {fogViewers} from '../static/tabletop/fog_view.js';
import {perceivedCells, tokenHiddenByFog} from '../static/tabletop/vision.js';

const directory = new URL('../combat/maps/', import.meta.url);
function load(name) {
  const d = JSON.parse(readFileSync(new URL(name+'.json', directory)));
  return {...d, width:d.width_squares, height:d.height_squares,
    floors:(d.materials||[]).filter(r=>r.material.startsWith('floor:')).map(r=>({style:r.material.slice(6),cells:r.cells}))};
}
const expected = {
  'builtin-bamboo-forest-ravine':0, 'builtin-cloudwater-crossing':0, 'builtin-emerald-canopy':0,
  'builtin-frontier-bamboo-imperial-tomb':0,
  'builtin-frontier-bandit-camp':0,
  'builtin-frontier-fortress-wall':0,
  'builtin-frontier-frozen-fishing-lake':0,
  'builtin-frontier-salt-caravanserai':0,
  'builtin-realm-maple-shrine':0,
  'builtin-realm-market-quarter':2,
  'builtin-realm-sunken-marsh':2,
  'builtin-realm-waterfall-gorge':0,
  'builtin-ricefield-bamboo-valley':0,
  'builtin-river-delta-isles':0,
  'builtin-ruined-sect-terraces':0,
  'builtin-sunken-cavern-lake':0,
  'builtin-jade-sutra-hall':1, 'builtin-mist-courtyard':0, 'builtin-mountain-pass':0,
  'builtin-pillar-arena':0, 'builtin-ruined-spirit-shrine':0, 'builtin-sect-trial-platform':0,
  'builtin-willow-village-compound':5,
};
test('every built-in map has its expected buildings; courtyards and bridges stay open',()=>{
  assert.deepEqual(readdirSync(directory).filter(f=>f.endsWith('.json')).sort(),Object.keys(expected).map(f=>f+'.json').sort());
  for (const [name,count] of Object.entries(expected)) {
    const map=load(name), before=JSON.stringify(map), regions=detectRoofRegions(map);
    assert.equal(regions.length,count,name);
    assert.strictEqual(detectRoofRegions({...map}),regions,'cached across table refreshes');
    assert.equal(JSON.stringify(map),before);
  }
  const village=detectRoofRegions(load('builtin-willow-village-compound'));
  assert.deepEqual(village.map(r=>r.cells.length),[36,60,36,28,28]);
  assert.ok(village.every(r=>r.footprint.length<150),'no courtyard-wide roof');
});
test('viewer-specific fade, summons/large footprints and GM transparency',()=>{
  const [home,hall]=detectRoofRegions(load('builtin-willow-village-compound'));
  const own={position:{x:4,y:4}}, outside={position:{x:20,y:15}};
  assert.equal(roofOpacity(home,{viewers:[own]}),0);
  assert.equal(roofOpacity(home,{viewers:[outside]}),1);
  assert.equal(roofOpacity(hall,{viewers:[own]}),1,'other buildings stay roofed');
  assert.equal(roofOpacity(home,{viewers:[outside,own]}),0,'union of seat/summon viewers');
  assert.equal(roofOpacity(home,{gm:true}),.28);
  assert.equal(roofOpacity(home,{gm:true,enabled:false}),0);
  assert.ok(insideRoof(home,{position:{x:2,y:4},footprint:{width_cells:2,height_cells:2}}));
  assert.equal(roofOpacity(home,{}, {regions:[{x:4,y:4,enabled:false}]}),0);
  assert.equal(roofSettings(home,{style:'grey',regions:[{x:4,y:4,style:'red'}]}).style,'red');
});
test('authored open doors/breaches retain roofs; editor removal changes detection',()=>{
  const map=load('builtin-willow-village-compound');
  const regions=detectRoofRegions(map);
  const opened={...map,objects:map.objects.map(o=>o.kind==='door'?{...o,door_open:1}:o)};
  assert.deepEqual(detectRoofRegions(opened).map(r=>r.cells),regions.map(r=>r.cells));
  installDOM('<body></body>');
  const board=createBoard(document.body);
  board.setMap(map);
  const roofs=board.element.querySelectorAll('[data-roof]');
  board.setTokens([]); // service can omit every destroyed section: authored roof remains
  assert.deepEqual(board.element.querySelectorAll('[data-roof]'),roofs);
  board.setMap({...map,walls:map.walls.filter(w=>!w.id.startsWith('west-home'))});
  assert.equal(board.element.querySelectorAll('[data-roof]').length,4);
});
test('real board layers respect fog, perceived tokens, viewer and GM switches',()=>{
  installDOM('<body></body>');
  const board=createBoard(document.body), map=load('builtin-willow-village-compound');
  board.setMap(map);
  board.setTokens([{id:'inside',x:4,y:4,hp:10,maxHp:10}, {id:'outside',x:20,y:15,hp:10,maxHp:10},
    {id:'furniture',x:4,y:5,object:true,kind:'dining_table',hp:10,maxHp:10},
    {id:'unseen',x:5,y:5,hp:10,maxHp:10,hidden:true}]);
  const node=board.tokenNode('inside'), roofs=board.element.querySelectorAll('[data-roof]');
  board.setRoofView({gm:true});
  assert.equal(roofs[0].style.opacity,'0.28');
  assert.ok(node.parentNode.classList.contains('tt-roof-interior'));
  assert.ok(!board.tokenNode('outside').parentNode.classList.contains('tt-roof-interior'));
  const seen=new Uint8Array(map.width*map.height);seen[4*map.width+4]=1;
  board.setFog(seen,null,{squareFog:true});
  board.setRoofView({gm:false,viewers:[{x:20,y:15}],seen});
  assert.equal(roofs[0].style.opacity,'1');
  assert.ok(!node.parentNode.classList.contains('tt-roof-interior'),'perceived through an opening stays visible');
  assert.ok(board.tokenNode('furniture').parentNode.classList.contains('tt-roof-interior'),'furniture stays under eaves');
  assert.ok(board.tokenNode('unseen').classList.contains('is-hidden'),'roof never un-hides an unperceived creature');
  board.setRoofView({viewers:[{x:4,y:4}]});
  assert.equal(roofs[0].style.opacity,'0');assert.equal(roofs[1].style.opacity,'1');
  board.setMap({...map});assert.strictEqual(board.element.querySelectorAll('[data-roof]')[0],roofs[0]);
  board.setRoofView({gm:true,enabled:false});assert.ok(roofs.every(n=>n.style.opacity==='0'));
  const siblings=board.element.children;
  assert.ok(siblings.indexOf(node.parentNode)>siblings.indexOf(board.element.querySelector('.tt-fog')));
  assert.ok(siblings.indexOf(board.element.querySelector('.tt-roofs'))<siblings.indexOf(board.element.querySelector('.tt-fog')));
});
test('hip ridge rotates on long axis; eaves and tile patterns are board-space geometry',()=>{
  const region={footprint:[[3,4],[4,4],[5,4],[3,5],[4,5],[5,5]]};
  const g=roofGeometry(region);
  assert.equal(g.x,3-EAVE);assert.equal(g.y,4-EAVE);
  assert.equal(g.w,3+2*EAVE);assert.equal(g.h,2+2*EAVE);
  assert.equal(g.ridge[0][1],g.ridge[1][1]);assert.equal(g.vertical,false);
  const rotated={footprint:region.footprint.map(([x,y])=>[y,x])};
  const r=roofGeometry(rotated);
  assert.equal(r.ridge[0][0],r.ridge[1][0]);assert.equal(r.vertical,true);
  assert.match(roofMarkup(rotated,'red','test'),/patternTransform="rotate\(90\)"/);
  assert.match(roofMarkup(region,'grey','test'),/patternUnits="userSpaceOnUse"/);
  assert.match(roofMarkup(region,'grey','test'),/feGaussianBlur/);
});
test('separate seat audiences follow position refreshes without revealing unperceived occupants',()=>{
  installDOM('<body></body>');
  const map=load('builtin-willow-village-compound');
  const boards=[createBoard(document.body),createBoard(document.body)];
  boards.forEach(b=>b.setMap(map));
  const own={entity_id:'own',position:{x:20,y:15},active:true};
  const other={entity_id:'other',position:{x:20,y:15},active:true};
  const actors=[own,other];
  const perception={own:{cells:[[4,4]],creatures:['visible']},other:{cells:[],creatures:[]}};
  function refresh() {
    boards.forEach((b,i)=>{
      const viewers=fogViewers('own',actors,{owned:[actors[i]]});
      const seen=perceivedCells(map.width,map.height,viewers,perception);
      b.setTokens(['visible','unseen'].map((id,j)=>({id,x:4+j,y:4,hp:10,maxHp:10,
        hidden:tokenHiddenByFog({entity_id:id},viewers,perception)})));
      b.setFog(seen,null,{squareFog:true});b.setRoofView({gm:false,viewers,seen});
    });
  }
  // The normal/forced/teleport render path consumes updated positions alike.
  for(const position of [{x:20,y:15},{x:4,y:4},{x:20,y:15},{x:5,y:5}]) {
    own.position=position;refresh();
    assert.equal(boards[0].element.querySelectorAll('[data-roof]')[0].style.opacity,position.x===20?'1':'0');
    assert.equal(boards[1].element.querySelectorAll('[data-roof]')[0].style.opacity,'1');
    assert.ok(boards.every(b=>b.tokenNode('unseen').classList.contains('is-hidden')));
    assert.equal(boards[0].tokenNode('visible').classList.contains('is-hidden'),false);
    assert.equal(boards[1].tokenNode('visible').classList.contains('is-hidden'),true);
  }
});
test('table/editor production projections carry roof overrides without booting a UI',()=>{
  const source=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const projection=source.slice(source.indexOf('function mapFromState(state) {'),source.indexOf('\nfunction groveCells(state)'));
  const fromState=new Function('centerlineTerrain','groveCells',`${projection};return mapFromState;`)(()=>[],()=>new Set());
  const roofs={enabled:false,style:'red'};
  assert.deepEqual(fromState({map:{roofs},presentation:{battlefield:{width_squares:20,height_squares:20}}}).roofs,roofs);
  const editor=readFileSync(new URL('../static/tabletop/mapeditor.js',import.meta.url),'utf8');
  const expression=/board\.setMap\((\{[\s\S]*?\n  \})\);/.exec(editor)[1];
  const projected=new Function('doc','width','height','centerlineCells','cells','$','cellsFromTerrain','GROUND',`return (${expression});`)(
    {roofs,walls:[],materials:[]},20,20,[],{blocked:[],sight:[]},()=>({checked:false}),()=>[],{});
  assert.deepEqual(projected.roofs,roofs);
});
