import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

async function phone({aliased = false, assisted = false, secondary = false} = {}) {
  const id='actor:factory.options', requests=[], family=secondary ? 'action:blossom' : 'action:darkness';
  const source=secondary ? `${family}.immediate` : family;
  const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
  doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
  const viewerStore=createViewerStore({viewId:'phone-reachability'});
  viewerStore.bindPlayer('fight',[id]);
  const setting={label:'Clear Darkness augments',source_definition_id:'action:clear',
    options:[{candidate_id:'clear',target_ids:[id]}]};
  const attack={label:'Darkness + Greater Darkness',source_definition_id:'action:darkness.greater',alias_of:family,
    options:[{candidate_id:'old-target',target_ids:[]}]};
  const snapshot={last_sequence:1,presentation:{display_name:'Option test',current_actor_id:id,round_number:1,zones:[],
    battlefield:{width_squares:2,height_squares:2,terrain_regions:[]},
    actors:[{entity_id:id,display_name:'Player',primary_combatant:true,controller:assisted ? 'SUGGESTED' : 'MANUAL',
      active:true,team_index:0,position:{x:0,y:0,z:0}}]},
    menu:{actor_id:id,manual:true,decision_id:'d',state_version:1,control_mode:assisted ? 'SUGGESTED' : 'MANUAL',
      actions:[setting,...(aliased ? [attack] : []),...(secondary ? [{label:'Cultivate Blossom',
        source_definition_id:family,options:[{candidate_id:'dormant',target_ids:[id]}]}] : [])],moves:[],end_turn:'end',
      composition:{clear:{key:['augment',family,null],mode:'clear',family,source:setting.source_definition_id}}},
    shapes:{[id]:[{base:family,name:secondary ? 'Cultivate Blossom' : 'Darkness',options:[],augments:[],
      choices:secondary ? [{label:'Cultivate Blossom (bloom at once)',button_id:`act:${source}`,activation:true},
        {label:'Unaffordable setting',button_id:'act:unavailable-setting',activation:false}] : []},
      {base:'action:unrelated',name:'Unrelated ability'}],other:[{base:'action:other',name:'Another creature’s ability'}]},
    fog_perception:{[id]:{cells:[[0,0]],creatures:[id]}}};
  const request=async(path,options={})=>{
    requests.push({path,body:options.body});
    if (path.includes('/state?')) return structuredClone(snapshot);
    if (path.endsWith('/seat-status')) return {seats:{}};
    if (path.includes('/events?')) return {events:[],last_sequence:snapshot.last_sequence};
    if (path.endsWith('/sheet')) return {buttons:[]};
    if (path.endsWith('/composition/preview')) {
      // A stale compiled alias is filtered out after clearing its augments.
      return {menu:{decision_id:'preview',state_version:2,actions:options.body.source_definition_id===source
        ? [{label:'Darkness',source_definition_id:family,options:[{candidate_id:'plain-target',target_ids:[id]}]}] : []}};
    }
    if (path.endsWith('/act')) { snapshot.last_sequence=2; snapshot.menu.state_version=2; return {status:'COMMITTED'}; }
    throw new Error(`Unexpected fake request ${path}`);
  };
  const board={element:new Element(),map:{width:2,height:2},view:{zoom:1},closeHoverCard(){},fit(){},
    terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
  for (const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
  const client=createPlay({doc,request,board,viewerStore,frame:()=>{},
    memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},
    controlStore:{read:()=>assisted ? 'SUGGESTED' : 'MANUAL',write(){}}});
  await client.load('fight');
  await Promise.resolve();
  const list=doc.getElementById('actionList');
  if (assisted) await list.querySelectorAll('button').find(b=>b.textContent.startsWith('Change')).click();
  requests.length=0;
  return {client,doc,list,requests,setting,attack,family,source,snapshot};
}

for (const assisted of [false,true]) test(`phone can aim and fire a draft-enabled missing family (${assisted ? 'Assisted' : 'Manual'})`, async () => {
  const {client,doc,list,requests,setting,family,snapshot}=await phone({assisted});
  assert.ok(!snapshot.menu.actions.some(g=>(g.alias_of || g.source_definition_id)===family));
  const activation=list.querySelectorAll('button').find(b=>b.textContent==='Darkness');
  assert.ok(activation,'An owned family missing from the saved legal menu needs an aiming entry');
  assert.equal(activation.disabled,true);
  assert.ok(!list.querySelectorAll('button').some(b=>b.textContent.includes('Unrelated ability') || b.textContent.includes('Another creature')));
  const before=[...list.children];
  await list.querySelectorAll('button').find(b=>b.textContent===setting.label).click();
  assert.equal(activation.disabled,false);
  assert.equal(requests.length,0);
  assert.deepEqual([...list.children],before,'Changing a setting must not rebuild the action list');
  await client.refresh();
  assert.equal(activation.disabled,false,'Light polling must keep the draft-enabled entry usable');
  assert.ok(!requests.some(r=>r.path.includes('/state?')));
  requests.length=0;
  await activation.click();
  assert.equal(requests.length,1);
  assert.equal(requests[0].body.source_definition_id,family);
  const target=doc.getElementById('actionList').querySelectorAll('button').find(b=>b.dataset.candidate==='plain-target');
  assert.ok(target,'The phone must offer the newly legal target');
  await target.click();
  const writes=requests.filter(r=>r.body);
  assert.equal(writes.length,2);
  assert.ok(writes[0].path.endsWith('/composition/preview'));
  assert.ok(writes[1].path.endsWith('/act'));
  assert.deepEqual(writes[1].body.composition,writes[0].body);
  assert.equal(writes[1].body.candidate_id,'plain-target');
  assert.equal(requests.findIndex(r=>r.path.includes('/state?'))>requests.findIndex(r=>r.path.endsWith('/act')),true);
});

test('phone changes a persisted non-base augment combination using its base identity', async () => {
  const {client,doc,list,requests,setting,attack,family}=await phone({aliased:true});
  assert.equal(list.querySelectorAll('button').filter(b=>b.textContent.startsWith('Darkness')).length,1,
    'An aliased activation already represents its family');
  await client.choose(setting);
  assert.equal(requests.length,0);
  await client.choose(attack);
  assert.equal(requests[0].body.source_definition_id,family);
  const target=doc.getElementById('actionList').querySelectorAll('button').find(b=>b.dataset.candidate==='plain-target');
  assert.ok(target,'Clearing a saved combination must return the plain ability’s targets');
  await target.click();
  assert.equal(requests.filter(r=>r.path.endsWith('/act')).length,1);
});

test('phone discovers a missing secondary activation even when its parent is already available', async () => {
  const {client,doc,list,requests,setting,source}=await phone({secondary:true});
  const activation=list.querySelectorAll('button').find(b=>b.textContent==='Cultivate Blossom (bloom at once)');
  assert.ok(activation,'An owned family missing from the saved legal menu needs an aiming entry for secondary activations too');
  assert.equal(activation.disabled,true);
  assert.ok(!list.querySelectorAll('button').some(b=>b.textContent==='Unaffordable setting'));
  await client.choose(setting);
  assert.equal(activation.disabled,false);
  assert.equal(requests.length,0);
  await activation.click();
  assert.equal(requests[0].body.source_definition_id,source);
  await doc.getElementById('actionList').querySelectorAll('button').find(b=>b.dataset.candidate==='plain-target').click();
  assert.equal(requests.filter(r=>r.body).length,2);
  assert.ok(requests[1].path.endsWith('/act'));
});
