import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

test('phone drafts three settings locally, polls without state, aims once and commits once', async () => {
  const id='actor:factory.options', requests=[];
  const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
  doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
  const viewerStore=createViewerStore({viewId:'phone-options'});
  viewerStore.bindPlayer('fight',[id]);
  const settings=['poison','exploding','garden'].map((name,i)=>({label:name,source_definition_id:name,
    options:[{candidate_id:`setting-${i}`,target_ids:[id]}]}));
  const attack={label:'Cultivate Blossom',source_definition_id:'blossom',options:[{candidate_id:'old-target',target_ids:[id]}]};
  const snapshot={last_sequence:1,presentation:{display_name:'Option test',current_actor_id:id,round_number:1,zones:[],
    battlefield:{width_squares:2,height_squares:2,terrain_regions:[]},
    actors:[{entity_id:id,display_name:'Player',primary_combatant:true,controller:'MANUAL',
      active:true,team_index:0,position:{x:0,y:0,z:0}}]},
    menu:{actor_id:id,manual:true,decision_id:'d',state_version:1,control_mode:'MANUAL',
      actions:[...settings,attack],moves:[],end_turn:'end',
      composition:Object.fromEntries(settings.map((g,i)=>[`setting-${i}`,{key:['field',i],mode:i ? 'select' : 'toggle',source:g.source_definition_id}]))},
    fog_perception:{[id]:{cells:[[0,0]],creatures:[id]}}};
  const request=async(path,options={})=>{
    requests.push({path,body:options.body});
    if (path.includes('/state?')) return structuredClone(snapshot);
    if (path.endsWith('/seat-status')) return {seats:{}};
    if (path.includes('/events?')) return {events:[],last_sequence:snapshot.last_sequence};
    if (path.endsWith('/sheet')) return {buttons:[]};
    if (path.endsWith('/composition/preview')) return {menu:{decision_id:'preview',state_version:2,
      actions:[{...attack,options:[{candidate_id:'new-target',target_ids:[id]}]}]}};
    if (path.endsWith('/act')) { snapshot.last_sequence=2; snapshot.menu.state_version=2; return {status:'COMMITTED'}; }
    throw new Error(`Unexpected fake request ${path}`);
  };
  const board={element:new Element(),map:{width:2,height:2},view:{zoom:1},closeHoverCard(){},fit(){},
    terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
  for (const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
  const client=createPlay({doc,request,board,viewerStore,frame:()=>{},
    memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},controlStore:{read:()=> 'MANUAL',write(){}}});
  await client.load('fight');
  await Promise.resolve();
  requests.length=0;
  const list=doc.getElementById('actionList'), before=[...list.children];
  await client.choose(settings[0]);
  await client.choose(settings[0]);
  await client.refresh();
  assert.deepEqual(requests.map(r=>r.path.split('/').pop().split('?')[0]),['events','seat-status'],
    'Toggling back to the starting settings must not restart full state polling');
  requests.length=0;
  for (const group of settings) {
    await client.choose(group);
    assert.equal(requests.length,0,'A modification must not request state, menu, ranking or a commit');
    assert.deepEqual([...list.children],before,'A modification must preserve the action list');
  }
  await client.refresh();
  assert.deepEqual(requests.map(r=>r.path.split('/').pop().split('?')[0]),['events','seat-status']);
  requests.length=0;
  await client.choose(attack);
  assert.equal(requests.length,1);
  assert.ok(requests[0].path.endsWith('/composition/preview'));
  assert.deepEqual(requests[0].body.sources,['poison','exploding','garden']);
  await client.submit('new-target');
  const writes=requests.filter(r=>r.body);
  assert.equal(writes.length,2,'One aiming preview, then one final commit');
  assert.ok(writes[1].path.endsWith('/act'));
  assert.deepEqual(writes[1].body.composition,writes[0].body);
  assert.equal(writes[1].body.decision_id,'preview');
  assert.equal(requests.findIndex(r=>r.path.includes('/state?'))>requests.findIndex(r=>r.path.endsWith('/act')),true,
    'The first full state refresh must follow the final commit');
});
