// Production hover and editor DOM checks. No browser or GUI process.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard, CELL} from '../static/tabletop/board.js';
import {sceneryHeightFt, sceneryHeightText} from '../static/tabletop/map-heights.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';

function map() {
  return {map_id:'scenery-copy',display_name:'Scenery yard',width_squares:12,height_squares:8,
    background:{style:'flagstone'},display:{},walls:[],starts:{team1:[[1,1]],team2:[[10,6]]},
    objects:[{id:1,kind:'village_well',x:3,y:3,z:2}, {id:2,kind:'gate',x:6,y:3},
      {id:3,kind:'window',x:7,y:3,blocks:false}],
    trees:[{x:4,y:4,size:1,look:'willow'}],
    terrain:[{type:'SIMPLE_COVER',look:'handcart',cells:[[5,5],[1,6],[2,6]],base_altitude_ft:10}],
    materials:[{material:'terrain:bamboo thicket',cells:[[8,4],[9,4],[8,5],[9,5]]},
      {material:'terrain:bamboo thicket',cells:[[1,2],[2,2],[1,3],[2,3],[8,1],[9,1],[8,2],[9,2]],height_ft:30}]};
}
const text = node => [node?.textContent || '', ...(node?.children || []).map(text)].join(' ');

test('plain heights include raised tops and explicit zero',()=>{
  assert.equal(sceneryHeightFt({kind:'future-furniture'},'object'),5);
  assert.equal(sceneryHeightFt({kind:'village_well',height_ft:0},'object'),0);
  assert.match(sceneryHeightText({kind:'village_well',z:2},'object','Stone well'),/3 ft high above its base · top 13 ft above ground/);
});

test('production board hovers explain raised and zero tree, cover and bamboo spans',async()=>{
  const dom=installDOM('<body></body>'), board=createBoard(dom.body), d=map();
  board.setMap({...d,width:d.width_squares,height:d.height_squares});
  const timers=[], originalTimeout=globalThis.setTimeout;
  globalThis.setTimeout=fn=>{timers.push(fn);return timers.length;};
  try {
    async function hover(x,y) {
      board.closeHoverCard();
      const view=board.view, box=board.viewport.getBoundingClientRect();
      await board.viewport.dispatch('pointermove',{clientX:box.left+view.x+(x+.5)*CELL*view.zoom,
        clientY:box.top+view.y+(y+.5)*CELL*view.zoom,buttons:0});
      for(const fn of timers.splice(0)) fn();
      return text(dom.body.querySelector('.tt-zone-tip'));
    }
    assert.match(await hover(4,4),/Tree \(willow\) · 25 ft high/);
    assert.match(await hover(5,5),/handcart · 5 ft high · top 15 ft above ground/);
    assert.match(await hover(8,4),/Bamboo thicket · 20 ft high/);
    for (const row of [d.trees[0], d.terrain[0], d.materials[0]]) {
      row.base_altitude_ft=10;
      row.height_ft=11;
    }
    board.setMap({...d,width:d.width_squares,height:d.height_squares});
    const interval='from 10 ft up to, but not including, 21 ft above ground';
    assert.ok((await hover(4,4)).includes(`The trunk blocks sight and movement ${interval}.`));
    assert.ok((await hover(5,5)).includes(`Provides cover to a line passing ${interval}.`));
    assert.ok((await hover(8,4)).includes(`Dense stands block sight ${interval}.`));
    for (const base of [0,10]) {
      for (const row of [d.trees[0], d.terrain[0], d.materials[0]]) {
        row.base_altitude_ft=base;
        row.height_ft=0;
      }
      board.setMap({...d,width:d.width_squares,height:d.height_squares});
      assert.match(await hover(4,4),/Zero height: this trunk does not block sight or movement/);
      assert.match(await hover(5,5),/Zero height: this scenery provides no cover/);
      assert.match(await hover(8,4),/Zero height: this bamboo does not block sight/);
    }
    d.trees[0].height_ft=35;
    board.setMap({...d,width:d.width_squares,height:d.height_squares});
    assert.match(await hover(4,4),/35 ft high/,'editing a tree refreshes hover without changing walls');
    board.setTokens(tableObjectTokens([{id:'well',kind:'village_well',name:'Stone well',x:3,y:3,
      height_ft:3,altitude_ft:10}],new Set(),[],null,12));
    await board.tokenNode('well').dispatch('pointerenter');
    for(const fn of timers.splice(0)) fn();
    assert.match(dom.body.querySelector('.tt-token-card').innerHTML,/top 13 ft above ground/);
  } finally {globalThis.setTimeout=originalTimeout;}
});

test('height controls explain multi-cell and disconnected groups, save, undo, redo and reopen',async()=>{
  const dom=installDOM(readFileSync(new URL('../static/tabletop/mapeditor.html',import.meta.url),'utf8'));
  const rules=JSON.parse(readFileSync(new URL('../combat/rules/objects.json',import.meta.url)));
  let saved;
  globalThis.fetch=async(path,options={})=>{
    let result;
    if(path==='/api/session') result={token:'test'};
    else if(path==='/api/tabletop/terrains') result={terrains:[],ground:{}};
    else if(path==='/api/tabletop/maps'&&options.body) {saved=JSON.parse(options.body).map;result=saved;}
    else if(path==='/api/tabletop/maps') result={maps:[],object_defaults:rules};
    else if(path==='/api/tabletop/maps/scenery-copy') result=saved||map();
    else throw Error('Unexpected API '+path);
    return {ok:true,status:200,text:async()=>JSON.stringify(result),json:async()=>result};
  };
  await import('../static/tabletop/mapeditor.js?mapheight-test');
  for(let i=0;i<100&&!window.mapEditor;i++) await tick();
  await window.mapEditor.open('map:scenery-copy');
  const {editor,board}=window.mapEditor;
  async function hoverBamboo() {
    const timers=[], originalTimeout=globalThis.setTimeout;
    globalThis.setTimeout=fn=>{timers.push(fn);return timers.length;};
    try {
      board.closeHoverCard();
      const view=board.view, box=board.viewport.getBoundingClientRect();
      await board.viewport.dispatch('pointermove',{clientX:box.left+view.x+8.5*CELL*view.zoom,
        clientY:box.top+view.y+4.5*CELL*view.zoom,buttons:0});
      for(const fn of timers.splice(0)) fn();
      return text(dom.body.querySelector('.tt-zone-tip'));
    } finally {globalThis.setTimeout=originalTimeout;}
  }
  function input(family,index=0) {
    return dom.querySelectorAll('.me-scenery-height').find(n=>n.dataset.family===family&&Number(n.dataset.index)===index);
  }
  function scope(family,index=0) {
    return text(input(family,index).closest('li'));
  }
  assert.equal(Number(input('object').value),3);
  assert.equal(Number(input('tree').value),25);
  assert.equal(Number(input('terrain').value),5);
  assert.equal(Number(input('material').value),20);
  assert.match(await hoverBamboo(),/Bamboo thicket · 20 ft high/,'production editor forwards bamboo metadata');
  assert.match(text(dom.querySelector('#meSceneryHeightList')),/top 13 ft above ground/);
  assert.match(scope('terrain'),/group · 3 squares · edits all 3 together/,'disconnected cover props share one height control');
  assert.match(scope('material'),/group · 4 squares · edits all 4 together/,'a multi-cell stand explains the full edit scope');
  assert.match(scope('material',1),/group · 8 squares · edits all 8 together/,'separate stands in one row still share a height');
  assert.doesNotMatch(scope('material',1),/· square \d+, \d+/,'a group must not appear to edit just its first square');
  assert.match(input('material',1).getAttribute('aria-label'),/8 squares.*edits all 8 together/);
  for(const [family,value] of [['object',9],['tree',35],['terrain',0],['material',15]]) {
    const field=input(family);field.value=String(value);await field.dispatch('change');
  }
  await dom.querySelector('#meUndo').click();assert.equal(editor.doc.materials[0].height_ft,20);
  await dom.querySelector('#meRedo').click();assert.equal(editor.doc.materials[0].height_ft,15);
  assert.match(await hoverBamboo(),/Bamboo thicket · 15 ft high/,'height edit refreshes the production editor hover');
  const invalid=input('object');invalid.value='-1';await invalid.dispatch('change');
  assert.equal(editor.doc.objects[0].height_ft,9);
  await window.mapEditor.save();await window.mapEditor.open('map:scenery-copy');
  assert.deepEqual([editor.doc.objects[0].height_ft,editor.doc.trees[0].height_ft,
    editor.doc.terrain[0].height_ft,editor.doc.materials[0].height_ft],[9,35,0,15]);
  assert.deepEqual(editor.doc.terrain[0].cells,[[5,5],[1,6],[2,6]],'one height applies to all disconnected cover squares');
  assert.deepEqual(editor.doc.materials[0].cells,[[8,4],[9,4],[8,5],[9,5]],'one height applies to the entire four-square stand');
  assert.equal(editor.doc.objects[2].blocks,false,'height edits preserve transparent/open state');
  assert.equal(editor.doc.objects[1].height_ft,10,'gate gets the shared boundary default');
  const disconnected=input('material',1), cells=structuredClone(editor.doc.materials[1].cells);
  disconnected.value='12';await disconnected.dispatch('change');
  assert.equal(editor.doc.materials[1].height_ft,12);
  assert.equal(editor.doc.materials[0].height_ft,15,'editing a group leaves other groups alone');
  assert.deepEqual(editor.doc.materials[1].cells,cells,'both disconnected stands remain in the edited group');
  await window.mapEditor.save();await window.mapEditor.open('map:scenery-copy');
  assert.equal(editor.doc.materials[1].height_ft,12);
  assert.deepEqual(editor.doc.materials[1].cells,cells);
  assert.match(scope('material',1),/group · 8 squares · edits all 8 together/,'scope remains accurate after save and reopen');
});
