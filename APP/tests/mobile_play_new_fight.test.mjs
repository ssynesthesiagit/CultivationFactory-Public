import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

const text=n=>[n.textContent,...(n.children || []).map(text)].join(' ');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function harness(handle=()=>undefined) {
  const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
  doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
  const calls=[], changes=[], viewerStore=createViewerStore({viewId:'playnew1-test'});
  const actor={entity_id:'actor:factory.a',display_name:'Ada',primary_combatant:true,controller:'MANUAL',active:true,
    team_index:0,position:{x:0,y:0,z:0},hit_points:{current:20,maximum:20},conditions:[],resources:[]};
  const snapshot={last_sequence:1,presentation:{match_id:'f',display_name:'A fight',current_actor_id:actor.entity_id,
    round_number:1,actors:[actor],zones:[],battlefield:{width_squares:2,height_squares:2,terrain_regions:[]}},
    map:{},objects:[],items:[],fog_perception:{[actor.entity_id]:{cells:[[0,0]],creatures:[actor.entity_id]}}};
  const request=async(path,options={})=>{
    calls.push({path,...options});
    const custom=handle(path,options); if(custom!==undefined) return custom;
    if(path==='/api/combat/matches') return [{match_id:'f',display_name:'A fight'}];
    if(path==='/api/combat/factory-characters') return ['a','b','c'].map((project_id,i)=>({project_id,actor_id:`actor:factory.${project_id}`,display_name:['Ada','Bo','Cy'][i]}));
    if(path==='/api/combat/factory-arenas') return [{arena_id:'map1',display_name:'Courtyard',description:'An open courtyard.'},{arena_id:'map2',display_name:'River',description:'A narrow bridge.'}];
    if(path==='/api/combat/factory-matches') return {match_id:'created'};
    if(path.includes('/state?')) return structuredClone(snapshot);
    if(path.endsWith('/seat-status')) return {seats:{}};
    if(path.includes('/events?')) return {events:[],last_sequence:1};
    if(path.endsWith('/controller-mode')) {actor.controller=options.body.controller_mode;return {};}
    throw new Error(`Unexpected request ${path}`);
  };
  const board={element:new Element(),map:{width:2,height:2},view:{x:0,y:0,zoom:1},closeHoverCard(){},fit(){}};
  for(const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
  const client=createPlay({doc,request,board,viewerStore,onMatchChange:id=>changes.push(id),frame:()=>{},
    controlStore:{read:()=> 'MANUAL'},memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false}});
  return {client,doc,calls,changes,$:id=>doc.getElementById(id)};
}

test('slow fight selection immediately shows loading, spinner and back; cancel ignores stale success',async()=>{
  const wait=deferred();const h=harness(path=>path.includes('/state?') ? wait.promise : undefined);
  const loading=h.client.load('f');
  assert.equal(h.$('loadCard').open,true);
  assert.match(h.$('loadMessage').textContent,/Loading fight… this can take up to a minute/);
  assert.equal(h.$('loadSpinner').hidden,false);
  assert.equal(h.$('bind').disabled,true);
  await h.$('cancelLoad').click();
  assert.equal(h.$('loadCard').open,false);assert.equal(h.$('bindingCard').open,true);
  wait.resolve({});assert.equal(await loading,false);
  assert.equal(h.client.state,null);assert.equal(h.$('mapCover').hidden,false);
  assert.deepEqual(h.changes,['f','']);
  assert.equal(h.calls.some(c=>c.path.includes('/events?')),false);
});

test('a canceled read cannot overwrite a newer fight or its read lock',async()=>{
  const wait=deferred();let first=true;
  const h=harness(path=>{if(path.includes('/state?') && first) {first=false;return wait.promise;}});
  const old=h.client.load('old');await h.$('cancelLoad').click();
  assert.equal(await h.client.load('new'),true);
  const state=h.client.state;wait.reject(new Error('old connection failed'));await old;
  assert.equal(h.client.state,state);assert.equal(h.$('loadCard').open,false);
  assert.doesNotMatch(h.$('status').textContent,/old connection failed/);
});

test('failed opening stays readable with Retry, including another failure and successful retry',async()=>{
  let failed=true;
  const h=harness(path=>{if(path.includes('/state?') && failed) throw new Error('Server restarted.');});
  assert.equal(await h.client.load('f'),false);
  assert.match(h.$('loadMessage').textContent,/Could not load.*Server restarted/);
  assert.equal(h.$('retryLoad').hidden,false);assert.equal(h.$('loadSpinner').hidden,true);
  await h.client.refresh();assert.equal(h.$('retryLoad').hidden,false,'another failed poll keeps Retry visible');
  await h.$('retryLoad').click();assert.equal(h.$('loadCard').open,true);
  failed=false;await h.$('retryLoad').click();
  assert.equal(h.$('loadCard').open,false);assert.ok(h.client.state);
  assert.equal(h.$('fighters').options.length,1);
  assert.equal(h.$('bindingCard').open,true,'a direct link without a player must offer character selection after Retry');
});

test('new fight includes every character, map descriptions, sides and You/AI; opens chosen player',async()=>{
  const h=harness();await h.client.lobby();await h.$('newFight').click();
  assert.equal(h.$('newFightCard').open,true);
  const cards=h.$('newFightRoster').children;assert.equal(cards.length,3);
  assert.match(text(cards[0]),/Ada.*Side.*You.*AI/);
  h.$('newFightMap').value='map2';await h.$('newFightMap').dispatch('change');
  assert.equal(h.$('newFightMapDescription').textContent,'A narrow bridge.');
  cards[0].querySelector('input').checked=true;cards[1].querySelector('input').checked=true;
  await h.$('createFight').click();
  const write=h.calls.find(c=>c.path==='/api/combat/factory-matches');
  assert.deepEqual(write.body,{project_ids:['a'],opponent_actor_ids:['actor:factory.b'],arena_id:'map2',
    control_modes:{'actor:factory.a':'MANUAL','actor:factory.b':'LOCAL_AUTO'}});
  assert.ok(h.calls.some(c=>c.path.includes('/created/state?') && c.path.includes('fog_actor_ids=actor%3Afactory.a')));
  assert.equal(h.$('newFightCard').open,false);assert.equal(h.$('loadCard').open,false);
  assert.equal(h.$('bindingCard').open,false);assert.equal(h.$('mapCover').hidden,true);
});

test('empty side is rejected; creation is single flight, cannot be canceled midway and reports uncertain failures',async()=>{
  const wait=deferred();const h=harness(path=>path==='/api/combat/factory-matches' ? wait.promise : undefined);
  await h.$('newFight').click();await h.$('createFight').click();
  assert.match(h.$('newFightStatus').textContent,/at least one fighter/);
  assert.equal(h.calls.some(c=>c.body),false);
  const cards=h.$('newFightRoster').children;for(const card of cards.slice(0,2)) card.querySelector('input').checked=true;
  const create=h.$('createFight').click();
  assert.match(h.$('newFightStatus').textContent,/Creating fight.*up to a minute/);
  await h.$('createFight').click();await h.$('newFightCard').dispatch('cancel');
  assert.equal(h.$('newFightCard').open,true);assert.equal(h.$('closeNewFight').disabled,true);
  wait.reject(new Error('Connection lost'));await create;
  assert.match(h.$('newFightStatus').textContent,/Check the saved fights.*already.*saved/);
  assert.equal(h.calls.filter(c=>c.path==='/api/combat/factory-matches').length,1);
  assert.equal(h.$('closeNewFight').disabled,false);
});

test('roster request failure has Retry and Back',async()=>{
  let fail=true;const h=harness(path=>{if(path==='/api/combat/factory-characters' && fail) throw new Error('Disconnected');});
  await h.$('newFight').click();assert.match(h.$('newFightStatus').textContent,/Could not load.*Disconnected/);
  assert.equal(h.$('retryNewFight').hidden,false);assert.equal(h.$('createFight').disabled,true);
  fail=false;await h.$('retryNewFight').click();assert.equal(h.$('createFight').disabled,false);
  await h.$('closeNewFight').click();assert.equal(h.$('newFightCard').open,false);
});

test('a roster response arriving after Back cannot replace a reopened form',async()=>{
  const wait=deferred();let old=true;
  const h=harness(path=>{if(path==='/api/combat/factory-characters' && old) return wait.promise;});
  const loading=h.$('newFight').click();await h.$('closeNewFight').click();
  old=false;await h.$('newFight').click();
  wait.resolve([{project_id:'stale',display_name:'Stale fighter'}]);await loading;
  assert.equal(h.$('newFightRoster').children.length,3);
  assert.doesNotMatch(text(h.$('newFightRoster')),/Stale fighter/);
});
