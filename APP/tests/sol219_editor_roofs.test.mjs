// Real editor entry point under a deterministic DOM; no browser is started.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';

test('building overrides, styles, undo/redo and save use the production editor',async()=>{
  const dom=installDOM(readFileSync(new URL('../static/tabletop/mapeditor.html',import.meta.url),'utf8'));
  const map=JSON.parse(readFileSync(new URL('../combat/maps/builtin-willow-village-compound.json',import.meta.url),'utf8'));
  let saved;
  globalThis.fetch=async(path,options={})=>{
    let result;
    if (path==='/api/session') result={token:'test'};
    else if (path==='/api/tabletop/terrains') result={terrains:[],ground:{}};
    else if (path==='/api/tabletop/maps' && options.body) {
      saved=JSON.parse(options.body).map;result={...saved,map_id:'roof-copy'};
    } else if (path==='/api/tabletop/maps') result={maps:[],builtin:[],object_defaults:{presets:{},groups:{},materials:{},sizes:{}}};
    else if (path==='/api/tabletop/maps/roof-copy') result=saved || map;
    else throw Error('Unexpected test API '+path);
    return {ok:true,status:200,text:async()=>JSON.stringify(result),json:async()=>result};
  };
  await import('../static/tabletop/mapeditor.js?sol219-test');
  for(let i=0;i<100&&!window.mapEditor;i++) await tick();
  assert.ok(window.mapEditor);
  await window.mapEditor.open('map:roof-copy');
  const {editor,board}=window.mapEditor;
  const building=dom.querySelector('#meRoofBuilding');
  assert.equal(building.options.length,6,'all plus five buildings');
  building.value='4,4';await building.dispatch('change');
  const enabled=dom.querySelector('#meRoofEnabled');enabled.checked=false;await enabled.dispatch('change');
  assert.deepEqual(editor.doc.roofs.regions,[{x:4,y:4,enabled:false}]);
  const style=dom.querySelector('#meRoofStyle');style.value='red';await style.dispatch('change');
  assert.equal(editor.doc.roofs.regions[0].style,'red');
  assert.equal(board.element.querySelectorAll('[data-roof]')[0].style.opacity,'0');
  await dom.querySelector('#meUndo').click();assert.equal(editor.doc.roofs.regions[0].style,undefined);
  await dom.querySelector('#meRedo').click();assert.equal(editor.doc.roofs.regions[0].style,'red');
  await window.mapEditor.save();assert.deepEqual(saved.roofs,editor.doc.roofs);
  building.value='all';await building.dispatch('change');enabled.checked=false;await enabled.dispatch('change');
  assert.equal(editor.doc.roofs.enabled,false);
  assert.ok(board.element.querySelectorAll('[data-roof]').every(n=>n.style.opacity==='0'));

  // A colour edit while globally hidden must not save a local hide.
  building.value='30,5';await building.dispatch('change');
  style.value='red';await style.dispatch('change');
  await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');
  assert.deepEqual(editor.doc.roofs.regions.find(r=>r.x===30),{x:30,y:5,style:'red'});
  building.value='all';await building.dispatch('change');enabled.checked=true;await enabled.dispatch('change');
  assert.equal(board.element.querySelectorAll('[data-roof]')[2].style.opacity,'0.28');

  // An enabled-only edit must keep inheriting future global colours.
  building.value='15,4';await building.dispatch('change');
  enabled.checked=false;await enabled.dispatch('change');
  enabled.checked=true;await enabled.dispatch('change');
  await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');
  assert.deepEqual(editor.doc.roofs.regions.find(r=>r.x===15),{x:15,y:4,enabled:true});
  building.value='all';await building.dispatch('change');style.value='red';await style.dispatch('change');
  await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');
  building.value='15,4';await building.dispatch('change');
  assert.equal(style.value,'red');
});
