// Production editor DOM round-trip. Never starts a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';

test('wall, building and roof height controls save, undo and reload',async()=>{
  const dom=installDOM(readFileSync(new URL('../static/tabletop/mapeditor.html',import.meta.url),'utf8'));
  const map=JSON.parse(readFileSync(new URL('../combat/maps/builtin-willow-village-compound.json',import.meta.url)));
  map.objects.push({id:'test-window',kind:'window',x:3,y:4,axis:'v',height_ft:10});
  let saved;
  globalThis.fetch=async(path,options={})=>{
    let result;
    if(path==='/api/session') result={token:'test'};
    else if(path==='/api/tabletop/terrains') result={terrains:[],ground:{}};
    else if(path==='/api/tabletop/maps'&&options.body) {
      saved=JSON.parse(options.body).map;result={...saved,map_id:'height-copy'};
    } else if(path==='/api/tabletop/maps') result={maps:[],object_defaults:{presets:{},groups:{},materials:{},sizes:{}}};
    else if(path==='/api/tabletop/maps/height-copy') result=saved||map;
    else throw Error('Unexpected API '+path);
    return {ok:true,status:200,text:async()=>JSON.stringify(result),json:async()=>result};
  };
  await import('../static/tabletop/mapeditor.js?wallheight-test');
  for(let i=0;i<100&&!window.mapEditor;i++) await tick();
  await window.mapEditor.open('map:height-copy');
  const {editor}=window.mapEditor;
  const wall=dom.querySelector('.me-wall-height');
  assert.equal(Number(wall.value),10);
  wall.value='23';await wall.dispatch('change');
  assert.equal(editor.doc.walls[0].height_ft,23);
  await dom.querySelector('#meUndo').click();assert.equal(editor.doc.walls[0].height_ft,10);
  await dom.querySelector('#meRedo').click();assert.equal(editor.doc.walls[0].height_ft,23);
  const picker=dom.querySelector('#meRoofBuilding');
  picker.value='4,4';await picker.dispatch('change');
  assert.equal(Number(dom.querySelector('#meBuildingHeight').value),10);
  assert.equal(Number(dom.querySelector('#meRoofHeight').value),15);
  const building=dom.querySelector('#meBuildingHeight');building.value='20';await building.dispatch('change');
  assert.ok(editor.doc.walls.filter(w=>w.id.startsWith('west-home')).every(w=>w.height_ft===20));
  assert.equal(editor.doc.objects.find(o=>o.id==='test-window').height_ft,20);
  assert.equal(editor.doc.walls[0].height_ft,23,'perimeter remains independent');
  assert.equal(Number(dom.querySelector('#meRoofHeight').value),25,'unwritten roof peak follows walls');
  const roof=dom.querySelector('#meRoofHeight');roof.value='32';await roof.dispatch('change');
  assert.deepEqual(editor.doc.roofs.regions,[{x:4,y:4,height_ft:32}]);
  await window.mapEditor.save();await window.mapEditor.open('map:height-copy');
  assert.equal(editor.doc.walls[0].height_ft,23);
  picker.value='4,4';await picker.dispatch('change');
  assert.equal(Number(building.value),20);assert.equal(Number(roof.value),32);
  assert.equal(editor.doc.objects.find(o=>o.id==='test-window').height_ft,20,'window height persists after save and reopen');
  assert.equal(saved.roofs.regions[0].height_ft,32);
  roof.value='-1';await roof.dispatch('change');
  assert.equal(editor.doc.roofs.regions[0].height_ft,32,'invalid inputs preserve saved height');
});
