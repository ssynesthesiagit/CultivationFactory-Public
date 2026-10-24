import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {emptyMemory} from '../static/tabletop/fog_memory.js';
import {createBoard} from '../static/tabletop/board.js';
import {playerView, eligibleFighters, ownedMenu, ownPrompt, optionsAt, pendingSubmission, reactionAnswer, mapFromState, optionText} from '../static/play/play-model.js';
import * as playModel from '../static/play/play-model.js';
import {renderActions, renderOptions, renderReaction, renderCharacter} from '../static/play/play-ui.js';
import {renderMap, fitFighters} from '../static/play/play-board.js';
import {createPlay} from '../static/play/play-client.js';
import {installTouch} from '../static/play/play-touch.js';

const mine='actor:factory.phone', enemy='actor:enemy', ally='actor:ally', summon='actor:summon';
const makeActor=(id,name,team=0,extra={})=>({entity_id:id,display_name:name,team_index:team,primary_combatant:true,controller:'MANUAL',
  active:true,position:{x:0,y:0,z:0},hit_points:{current:20,maximum:30},resources:[],conditions:[],...extra});
const seats={seats:{}};
const binding={version:1,role:'player',actor_ids:[mine]};
function fixture() {
  return {last_sequence:2,presentation:{match_id:'phone-fight',display_name:'Frozen lake',round_number:1,current_actor_id:mine,
    battlefield:{width_squares:4,height_squares:3,blocked_cells:[],terrain_regions:[]},zones:[],actors:[
      makeActor(mine,'Player'),makeActor(enemy,'Unseen enemy',1,{position:{x:3,y:2}}),makeActor(ally,'Ally',0,{position:{x:2,y:0}}),
      makeActor(summon,'My summon',0,{primary_combatant:false,owner_id:mine,position:{x:1,y:0}})]},
    map:{background:{style:'flagstone',seed:1}},objects:[],items:[],
    fog_perception:{[mine]:{cells:[[0,0]],creatures:[mine]},[summon]:{cells:[[1,0]],creatures:[summon]},[ally]:{cells:[[3,2]],creatures:[enemy]}},
    menu:{actor_id:mine,manual:true,decision_id:'d1',state_version:1,moves:[{candidate_id:'move1',destination:{x:1,y:0,z:0},cost_ft:5,path:[{x:1,y:0,z:0}]}],
      actions:[{source_definition_id:'attack',label:'Strike',economy:'ACTION',cost_label:'Action · no resource cost',description:'Strike one creature in reach.',
        options:[{candidate_id:'strike1',target_ids:[enemy],label:'Strike Unseen enemy'}]}],end_turn:'end1'}};
}
function dom() {
  const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
  doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
  return doc;
}
const text=n=>[n.textContent,...(n.children || []).map(text)].join(' ');
const memory={read:()=>emptyMemory(),ready:()=>false,save() {}};

test('F12 guided turn without optional ranking confirms an exact legal step and keeps all alternatives',async()=>{
  for (const ranking of [undefined, {Action:[],Movement:[], 'Bonus action':[]}]) {
    const h=clientHarness({preferred:'SUGGESTED'}), state=fixture();
    state.presentation.actors[0].controller='SUGGESTED';
    Object.assign(state.menu,{control_mode:'SUGGESTED',ranked_slots:ranking});
    state.menu.actions.push({label:'Self aid',options:[{candidate_id:'aid',target_ids:[mine],label:'Help yourself'}]});
    h.setState(state); await h.client.load('phone-fight');
    assert.equal(h.doc.getElementById('actionsButton').disabled,false);
    const confirm=h.doc.getElementById('actionList').querySelectorAll('button').find(b=>text(b)==='Confirm this step');
    assert.ok(confirm,'Optional ranking must not prevent confirmation');
    await h.client.change();
    assert.ok(text(h.doc.getElementById('actionList')).includes('Strike'));
    assert.ok(text(h.doc.getElementById('actionList')).includes('Self aid'));
    await confirm.click();
    const writes=h.calls.filter(c=>c.body);
    assert.equal(writes.length,1);
    assert.equal(writes[0].body.candidate_id,'aid','Never propose an unseen target as a fallback');
    assert.ok(writes[0].path.endsWith('/act'));
  }
});

test('F12 resource summary stays compact and details are collapsed without duplicate sentences',()=>{
  const doc=dom(), actor=fixture().presentation.actors[0], host=doc.getElementById('characterBody');
  actor.resources=[{display_name:'Martial Focus',current:1,maximum:1},{display_name:'Qi',current:16,maximum:16}];
  renderCharacter(host,actor,{buttons:[{label:'Wind',description:'Move a willing creature.'}],
    library:{groups:[{entries:[{name:'Wind',text:'Move a willing creature.'}]}]}});
  assert.equal((text(host).match(/Move a willing creature\./g)||[]).length,1,'Library and button copies share one card');
  const sections=host.querySelectorAll('.play-resource');
  assert.equal(sections.length,2);
  for (const section of sections) {
    const details=section.querySelector('details');
    assert.equal(text(details.querySelector('summary')),'Details');
    assert.ok(!details.open);
    const visible=section.children.filter(c=>c!==details).map(text).join(' ');
    assert.ok(visible.length<180,visible);
    assert.equal((visible.match(/\d+ \/ \d+/g)||[]).length,1);
    const lines=text(details).split(/\n+|(?<=[.!?])\s+/).map(s=>s.trim()).filter(Boolean);
    assert.equal(new Set(lines).size,lines.length,'Exact sentences should appear once');
  }
});

test('F12 Fit map frames perceived fighters at playable zoom without hidden-position influence',async()=>{
  const state=fixture(), view=playerView(binding,state,seats), doc=dom(), viewport=doc.getElementById('map');
  viewport.getBoundingClientRect=()=>({left:0,top:0,width:390,height:500});
  const board=createBoard(viewport);
  board.setMap({...mapFromState(state),width:180,height:120});
  fitFighters(board,state,view);
  assert.ok(board.view.zoom*64>=28);
  const before=board.view;
  state.presentation.actors[1].position={x:170,y:110};
  fitFighters(board,state,view);
  assert.deepEqual(board.view,before);
  assert.deepEqual(board.cellAt(195,250),{x:1,y:0});
  const zoom=board.view.zoom;
  board.zoomBy(1.3); assert.ok(board.view.zoom>zoom);
});
function fakeBoard() {
  const b={element:new Element(),map:{width:4,height:3},view:{x:0,y:0,zoom:1},calls:[],
    terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null,sceneryRecordAt:()=>null,objectArtRecordAt:()=>null,
    fit(){},zoomBy(){},centerOn(){},closeHoverCard(){},cellAt:()=>({x:1,y:0})};
  for (const method of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) b[method]=(...args)=>{
    b.calls.push([method,...args]); if(method==='setMap') b.map=args[0];
  };
  return b;
}
function clientHarness({preferred = 'MANUAL', reply = () => undefined} = {}) {
  const doc=dom(), board=fakeBoard(), viewerStore=createViewerStore({viewId:'phone-test'});
  viewerStore.bindPlayer('phone-fight',[mine]);
  const calls=[];
  let current=fixture(), control=seats, failPost=false, deferredRead=null;
  const request=async(path,options={})=>{
    calls.push({path,...options});
    const custom = reply(path, options);
    if (custom !== undefined) return custom;
    if(options.body) {
      if(failPost) throw new Error('Lost reply — action not resent');
      if(path.endsWith('/controller-mode')) {
        const actor=current.presentation.actors.find(a=>a.entity_id===options.body.actor_id);
        actor.controller=options.body.controller_mode;
        if(current.menu.actor_id===actor.entity_id) {
          current.menu.control_mode=actor.controller;
          current.menu.turn_mode=actor.controller==='SUGGESTED' ? 'Assisted' : 'Manual';
          current.menu.ranked_slots={Action:['strike1'],Movement:['move1']};
        }
      }
      return {status:'COMMITTED'};
    }
    if(path.includes('/state?')) {const read=deferredRead;deferredRead=null;if(read) await read;return structuredClone(current);}
    if(path.endsWith('/seat-status')) {if(control===null) throw new Error('Seat read failed'); return control;}
    if(path.includes('/events?')) return {events:[],last_sequence:current.last_sequence};
    if(path.endsWith('/sheet')) return {buttons:[],library:{groups:[]}};
    if(path==='/api/tabletop/conditions') return {conditions:{prone:{reading:'You are prone.',mechanics:['Crawl to move']}}};
    if(path==='/api/combat/matches') return [{match_id:'phone-fight',display_name:'Frozen lake'}];
    throw new Error(`Unexpected fake request: ${path}`);
  };
  const preferences=new Map();
  const client=createPlay({doc,request,board,viewerStore,memoryStore:memory,frame:()=>{},
    controlStore:{read:key=>preferences.get(key) ?? preferred,write:(key,mode)=>preferences.set(key,mode)}});
  return {client,doc,board,calls,setState:x=>current=x,setSeats:x=>control=x,failPost:()=>failPost=true,
    deferRead:()=>{let release;deferredRead=new Promise(r=>release=r);return release;}};
}

test('lazy phone action expands once and survives the unchanged-state refresh before commit',async()=>{
  const state=fixture();
  state.menu.actions[0].lazy=true;state.menu.actions[0].options=[];
  const h=clientHarness({reply:(path)=>path.includes('/action-options?') ? {
    actions:[{source_definition_id:'attack',label:'Strike',options:[{candidate_id:'exact-strike',target_ids:[mine]}]}]
  } : undefined});
  h.setState(state);await h.client.load('phone-fight');
  await h.client.choose(h.client.state.menu.actions[0]);
  await h.client.refresh();
  assert.equal(h.client.state.menu.actions[0].lazy,false);
  assert.equal(await h.client.submit('exact-strike'),true);
  assert.equal(h.calls.filter(c=>c.path.includes('/action-options?')).length,1);
  assert.ok(h.calls.some(c=>c.path.endsWith('/act') && c.body.candidate_id==='exact-strike'));
});

test('phone compact movement previews the native path and waits for confirmation before submitting it',async()=>{
  const state=fixture(), path=[{x:0,y:0,z:0},{x:1,y:0,z:0}];
  state.menu.moves=[];state.menu.movement_grid={format:'layers-v1',layers:[[0,5,'walk',false,[1,0]]]};
  const h=clientHarness({reply:(url)=>url.endsWith('/movement-destination/preview') ? {
    candidate:{candidate_id:'native-route',canonical_path:path}
  } : undefined});
  h.setState(state);await h.client.load('phone-fight');
  assert.equal(h.client.state.menu.moves.length,1);
  const candidate = h.client.state.menu.moves[0].candidate_id;
  assert.equal(await h.client.submit(candidate),false);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/movement-path/commit')).length,0);
  assert.equal(await h.client.submit(candidate),true);
  const writes=h.calls.filter(c=>c.body);
  assert.equal(writes.length,2);
  assert.ok(writes[0].path.endsWith('/movement-destination/preview'));
  assert.ok(writes[1].path.endsWith('/movement-path/commit'));
  assert.equal(writes[1].body.candidate_id,'native-route');
  assert.deepEqual(writes[1].body.waypoints,path);
});

test('binding uses the shared resolver: no GM mode, model seat, broken owner or missing seats grants sight',()=>{
  const state=fixture(), view=playerView(binding,state,seats);
  assert.deepEqual([...view.ownedIds],[mine,summon]);
  assert.equal(view.seen[0],1); assert.equal(view.seen[1],1); assert.equal(view.seen[11],0);
  assert.equal(view.visible(state.presentation.actors[1]),false);
  for(const bad of [null,{version:1,role:'gm',actor_ids:[]},{...binding,actor_ids:['missing']}]) {
    const v=playerView(bad,state,seats); assert.equal(v.ready,false); assert.equal(v.seen.some(Boolean),false);
  }
  for(const status of [null,{seats:{[mine]:{control:'MODEL'}}}]) {
    const v=playerView(binding,state,status); assert.equal(v.ownedIds.size,0); assert.equal(v.visible(state.presentation.actors[0]),false);
  }
  assert.equal(eligibleFighters(state,{seats:{[mine]:{control:'MODEL'}}}).some(a=>a.entity_id===mine),false);
  state.presentation.actors[3].owner_id='missing';
  assert.equal(playerView(binding,state,seats).isOwned(summon),false);
});

test('a fallen fighter inherits allies’ sight without seeing enemies’ side; no-view stays fogged',()=>{
  const state=fixture(); state.presentation.actors[0].active=false;state.presentation.actors[3].active=false;
  const v=playerView(binding,state,seats);assert.equal(v.visible(state.presentation.actors[1]),true);
  state.presentation.actors[2].active=false;
  assert.equal(playerView(binding,state,seats).seen.some(Boolean),false);
});

test('only owned manual menus are actionable; owned Ask-me cards appear on other actors’ turns',()=>{
  const state=fixture(), v=playerView(binding,state,seats);
  assert.equal(ownedMenu(state,v),state.menu);
  state.menu.actor_id=enemy;assert.equal(ownedMenu(state,v),null);
  assert.equal(ownPrompt({reaction:{context:{reactor_id:mine}}},v),true);
  assert.equal(ownPrompt({reaction:{context:{reactor_id:enemy}}},v),false);
});

test('phone action DOM retains every legal group and option, including low-ranked items and settings',async()=>{
  const doc=dom(), host=doc.getElementById('actionList'), state=fixture();
  const options=Array.from({length:81},(_,i)=>({candidate_id:`c${i}`,target_ids:[],label:`Option ${i}`}));
  const groups=Array.from({length:18},(_,i)=>({label:`Ability ${i}`,source_definition_id:`source${i}`,options,options_shown:3,item:i===16,shape:i===17,cost_label:'Bonus Action · 2 Stamina'}));
  const menu={...state.menu,actions:groups,actions_shown:3};
  const chosen=[];renderActions(host,menu,{buttons:[]},{choose:g=>chosen.push(g),move(){},end(){}});
  assert.equal(host.querySelectorAll('details').length,groups.length);
  const last=host.querySelectorAll('button').find(b=>text(b).includes('Ability 17'));assert.ok(last);await last.click();assert.equal(chosen[0],groups[17]);
  renderOptions(host,options,state,playerView(binding,state,seats),o=>chosen.push(o),()=>{});
  const candidates=host.querySelectorAll('button').filter(b=>b.dataset.candidate);
  assert.equal(candidates.length,options.length);
  await candidates.at(-1).click();assert.equal(chosen.at(-1),options.at(-1));
  assert.equal(text(host).includes('Unseen enemy'),false);
});

test('map taps retain all target, route, height and area variants and offer Jump down separately',()=>{
  const options=[{candidate_id:'a',target_ids:[enemy]},{candidate_id:'b',target_ids:[enemy]},
    {candidate_id:'low',destination:{x:2,y:1,z:0},can_jump_down:true},{candidate_id:'high',destination:{x:2,y:1,z:2}},
    {candidate_id:'area',area:{center:{x:2,y:1}},target_ids:[]}];
  assert.deepEqual(optionsAt(options,null,enemy).map(o=>o.candidate_id),['a','b']);
  assert.deepEqual(optionsAt(options,{x:2,y:1}).map(o=>o.candidate_id),['low','high','area']);
  const doc=dom();renderOptions(doc.getElementById('actionList'),options,fixture(),playerView(binding,fixture(),seats),()=>{},()=>{});
  assert.ok(text(doc.getElementById('actionList')).includes('Jump down (falling can hurt you)'));
});

test('reaction DOM includes all eligible options, enforces counts, preserves exact context and mandatory choice',async()=>{
  const doc=dom(), host=doc.getElementById('reactionBody'), answers=[], errors=[];
  const prompt={reactor:'Player',reaction:'Parry',trigger:'Enemy strikes Player',cost:'Reaction · 1 Stamina',summary:'Reduce the damage.',rules:'Until the end of this attack.',
    context:{reactor_id:mine,event_id:'hit-1'},choice:{minimum:2,maximum:3,allow_decline:false,options:Array.from({length:25},(_,i)=>({id:`o${i}`,label:`Choice ${i}`}))}};
  renderReaction(host,prompt,{answer:a=>answers.push(a),error:e=>errors.push(e)});
  assert.equal(host.querySelectorAll('input').length,25);
  assert.equal(text(host).includes('Decline'),false);
  const confirm=host.querySelectorAll('button').at(-1);await confirm.click();assert.equal(answers.length,0);assert.equal(errors.length,1);
  for(const input of host.querySelectorAll('input').slice(-2)) {input.checked=true;await input.dispatch('change');}
  await confirm.click();assert.deepEqual(answers[0],{reactor_id:mine,event_id:'hit-1',selection:'USE',option_ids:['o23','o24']});
  assert.throws(()=>reactionAnswer(prompt,['o1','o1']));
  prompt.choice={minimum:1,maximum:1,allow_decline:true,options:[{id:'tail',label:'Last eligible option'}]};
  renderReaction(host,prompt,{answer:a=>answers.push(a),error:()=>{}});
  await host.querySelectorAll('button').at(-1).click();assert.equal(answers.at(-1).selection,'DECLINE');
});

test('saved act, auto-step and movement Ask-me transport resumes exact request with accumulated answers',()=>{
  const answer={selection:'USE',reactor_id:mine}, pending={method:'act',request:{candidate_id:'c1',decision_id:'d1',state_version:5},reactions:[{selection:'DECLINE'}]};
  assert.deepEqual(pendingSubmission(pending,answer,30),{endpoint:'act',body:{...pending.request,after:30,reactions:[{selection:'DECLINE'},answer]}});
  assert.equal(pendingSubmission({...pending,method:'auto_step'},answer,30).endpoint,'auto-step');
  const move=pendingSubmission({...pending,request:{...pending.request,movement_path:[{x:1,y:0}]}},answer,30);
  assert.equal(move.endpoint,'movement-path/commit');assert.deepEqual(move.body.waypoints,[{x:1,y:0}]);assert.equal('movement_path' in move.body,false);
});

test('real shared board draws terrain, tokens, player roofs and exact server fog without hidden creatures',()=>{
  const doc=dom(), board=createBoard(doc.getElementById('map')), state=fixture();
  const v=playerView(binding,state,seats);
  renderMap(board,state,v,{matchId:'f',actorId:mine,memoryStore:memory});
  const labels=doc.querySelectorAll('.tt-token').map(n=>n.getAttribute('aria-label'));
  assert.ok(labels.some(n=>n?.includes('Player')));assert.ok(labels.some(n=>n?.includes('My summon')));
  assert.equal(labels.some(n=>n?.includes('Unseen enemy')),false);assert.equal(labels.some(n=>n?.includes('Ally')),false);
  assert.equal(doc.querySelector('.tt-fog').hidden,false);
  assert.deepEqual(mapFromState(state).cells.blocked,[]);
});

test('remembered map snapshots reuse shared memory and record only perceived enemies and objects',()=>{
  dom(); const board=fakeBoard(),state=fixture();
  const old={version:3,cells:{11:{terrain:[],zones:[],floor:null,tokens:[],objects:[]}}};
  let saved;
  const store={read:()=>old,ready:()=>true,save:(_,m)=>saved=m};
  renderMap(board,state,playerView(binding,state,seats),{matchId:'f',actorId:mine,memoryStore:store});
  assert.deepEqual(saved.cells[0].tokens,[]);assert.equal(saved.cells[11],old.cells[11]);
  const remembered=board.calls.find(c=>c[0]==='setRemembered')[1];assert.deepEqual(remembered.ghosts,[11]);assert.deepEqual(remembered.changed,[11]);
});

test('character panel shows live HP/resources, condition mechanics and full printed library text',()=>{
  const doc=dom(), actor=fixture().presentation.actors[0];
  actor.conditions=[{condition_id:'condition:typed.prone',display_name:'Prone',expires_on:'until_end_of_turn'}];
  actor.resources=[{display_name:'Stamina',current:7,maximum:10}];
  renderCharacter(doc.getElementById('characterBody'),actor,{buttons:[],library:{groups:[{name:'Air',spheres:[{name:'Wind',text:'Full source rules.',entries:[{name:'Lift',text:'Lift a willing creature for one turn.'}]}]}]}},
    {prone:{mechanics:['Crawl to move'],reading:'Attacks nearby have Advantage.'}});
  const content=text(doc.getElementById('characterBody'));
  for(const value of ['HP 20 / 30','Stamina','7 / 10','Crawl to move','Full source rules.','Lift a willing creature','until the end of the current turn']) assert.ok(content.includes(value),value);
  assert.equal(content.includes('condition:typed'),false);
});

test('client scopes state to binding, reads events, sends one exact candidate and closes stale target picks',async()=>{
  const h=clientHarness();await h.client.load('phone-fight');
  assert.ok(h.calls.find(c=>c.path.includes('fog_actor_ids=actor%3Afactory.phone')));
  assert.ok(h.calls.find(c=>c.path.includes('/events?after=')));
  h.client.choose(h.client.state.menu.actions[0]);
  const next=fixture();next.menu.decision_id='d2';h.setState(next);await h.client.refresh();
  assert.ok(text(h.doc.getElementById('actionList')).includes('Strike'));
  assert.equal(await h.client.submit('end1'),true);
  assert.deepEqual(h.calls.filter(c=>c.body).map(c=>c.body),[{candidate_id:'end1',decision_id:'d2',state_version:1,after:2}]);
});

test('failed POST is never replayed; controller validation loss covers map and closes private panels',async()=>{
  const h=clientHarness();await h.client.load('phone-fight');await h.client.character();
  assert.equal(h.doc.getElementById('characterCard').open,true);
  h.failPost();assert.equal(await h.client.submit('end1'),false);assert.equal(h.calls.filter(c=>c.body).length,1);
  h.setSeats(null);await h.client.refresh();
  assert.equal(h.doc.getElementById('mapCover').hidden,false);assert.equal(h.doc.getElementById('map').hidden,true);
  assert.equal(h.doc.getElementById('characterCard').open,false);
  assert.equal(await h.client.submit('end1'),false);assert.equal(h.calls.filter(c=>c.body).length,1);
});

test('pending choice survives refresh; prompt supersession discards old answer on AI turns',async()=>{
  const h=clientHarness(),state=fixture();state.menu.manual=false;state.menu.actor_id=enemy;state.presentation.current_actor_id=enemy;
  state.pending_action={method:'auto_step',request:{decision_id:'d1',state_version:1},reactions:[],reaction:{reactor:'Player',reaction:'Shield',
    context:{reactor_id:mine,hit:'1'},choice:{minimum:1,maximum:2,options:[{id:'one',label:'Shield yourself'}]}}};
  h.setState(state);await h.client.load('phone-fight');assert.equal(h.doc.getElementById('reactionCard').open,true);
  const input=h.doc.getElementById('reactionBody').querySelector('input');input.checked=true;await input.dispatch('change');
  await h.client.refresh();assert.equal(h.doc.getElementById('reactionBody').querySelector('input'),input);
  const button=h.doc.getElementById('reactionBody').querySelector('button');
  state.pending_action.reaction.context.hit='2';h.setState(state);await h.client.refresh();await button.click();
  assert.equal(h.calls.filter(c=>c.body).length,0);
  const now=h.doc.getElementById('reactionBody').querySelector('input');now.checked=true;await now.dispatch('change');
  await h.doc.getElementById('reactionBody').querySelector('button').click();
  const writes=h.calls.filter(c=>c.body);assert.equal(writes.length,1);assert.ok(writes[0].path.endsWith('/auto-step'));
  assert.deepEqual(writes[0].body.reactions,[{reactor_id:mine,hit:'2',selection:'USE',option_ids:['one']}]);
});

test('open character panel follows committed HP changes and unchanged polling does not repaint the map',async()=>{
  const h=clientHarness();await h.client.load('phone-fight');await h.client.character();
  const paints=h.board.calls.filter(c=>c[0]==='setFog').length;
  await h.client.refresh();assert.equal(h.board.calls.filter(c=>c[0]==='setFog').length,paints);
  const next=fixture();next.presentation.actors[0].hit_points.current=9;h.setState(next);await h.client.refresh();
  assert.ok(text(h.doc.getElementById('characterBody')).includes('HP 9 / 30'));
});

test('rebinding during an in-flight read waits for the old read then fetches the new viewer scope',async()=>{
  const doc=dom(),viewerStore=createViewerStore({viewId:'inflight'});viewerStore.bindPlayer('f',[mine]);
  let unblock, waitOnce=false;
  const paths=[];
  const request=async (path,options={})=>{
    paths.push(path);
    if(options.body && path.endsWith('/controller-mode')) return {};
    if(path.includes('/state?')) {if(waitOnce){waitOnce=false;await new Promise(r=>unblock=r);}return fixture();}
    if(path.endsWith('/seat-status'))return seats;
    if(path.includes('/events?'))return {events:[]};
    if(path.endsWith('/sheet'))return {buttons:[]};
    throw new Error(path);
  };
  const c=createPlay({doc,request,board:fakeBoard(),viewerStore,memoryStore:memory,frame:()=>{}});
  await c.load('f');waitOnce=true;const read=c.refresh();
  const rebind=c.bind(ally);unblock();await Promise.all([read,rebind]);
  assert.ok(paths.filter(p=>p.includes('/state?')).at(-1).includes('fog_actor_ids=actor%3Aally'));
  assert.equal(viewerStore.read('f').actor_ids[0],ally);
  assert.equal(doc.getElementById('mapCover').hidden,true);
});

const findButton=(host,label)=>host.querySelectorAll('button').find(b=>text(b).includes(label));
function reactionFixture() {
  const state=fixture();state.menu.manual=false;state.menu.actor_id=enemy;state.presentation.current_actor_id=enemy;
  const names=['Reduce Healing','Reduce Temporary HP','Deny Reactions','Mark the Target','Grave Tax'];
  const alternatives=names.map((name,i)=>({reactor:'Player',affected:'Enemy',reaction:name,trigger:'Enemy heals Enemy',
    cost:`Reaction · ${i+1} Stamina`,summary:`Effect of ${name} until the end of the turn.`,rules:`Printed ${name} rules.`,
    context:{reactor_id:mine,event_id:'healing',reaction_source_id:`reaction:${i}`}}));
  state.pending_action={method:'auto_step',request:{decision_id:'d1',state_version:1},reactions:[{selection:'USE',earlier:'saved'}],
    reaction:{...alternatives[0],alternatives}};
  return state;
}

test('F1 reaction alternatives show all five costs/effects and submit the ordered answer array on an AI turn',async()=>{
  const h=clientHarness(),state=reactionFixture();h.setState(state);await h.client.load('phone-fight');
  const host=h.doc.getElementById('reactionBody');
  for(const row of state.pending_action.reaction.alternatives) {
    assert.ok(text(host).includes(row.reaction));assert.ok(text(host).includes(row.cost));assert.ok(text(host).includes(row.summary));
  }
  await findButton(host,'Choose Mark the Target').click();
  const post=h.calls.filter(c=>c.body).at(-1);
  assert.ok(post.path.endsWith('/auto-step'));
  assert.deepEqual(post.body.reactions,[state.pending_action.reactions[0],...state.pending_action.reaction.alternatives.slice(0,4)
    .map((row,i)=>({...row.context,selection:i===3 ? 'USE' : 'DECLINE'}))]);
  assert.equal(post.body.reactions.some(Array.isArray),false);
});

test('F1 choosing an alternative keeps mandatory ability choices and Back; Pass declines every alternative',async()=>{
  const h=clientHarness(),state=reactionFixture();
  state.pending_action.reaction.alternatives[4].choice={minimum:1,maximum:1,allow_decline:false,options:[{id:'target',label:'Mark Player'}]};
  h.setState(state);await h.client.load('phone-fight');const host=h.doc.getElementById('reactionBody');
  await findButton(host,'Choose Grave Tax').click();
  assert.equal(h.calls.filter(c=>c.body).length,0);
  assert.ok(findButton(host,'Mark Player'));assert.equal(findButton(host,'Decline'),undefined);
  await findButton(host,'Back — compare all reactions').click();
  await findButton(host,'Choose Grave Tax').click();await findButton(host,'Mark Player').click();
  const answers=h.calls.filter(c=>c.body).at(-1).body.reactions;
  assert.deepEqual(answers.at(-1),{...state.pending_action.reaction.alternatives[4].context,selection:'USE',option_ids:['target']});
  await findButton(host,'Pass — keep your Reaction').click();
  assert.deepEqual(h.calls.filter(c=>c.body).at(-1).body.reactions.slice(1),state.pending_action.reaction.alternatives.map(row=>({...row.context,selection:'DECLINE'})));
});

test('F2 action button and target tap wait for an in-flight poll, then commit once',async()=>{
  for(const via of ['button','tap']) {
    const h=clientHarness();await h.client.load('phone-fight');
    if(via==='tap') h.client.choose({label:'Move',options:h.client.state.menu.moves},true);
    const release=h.deferRead(),read=h.client.refresh();
    const send=via==='button' ? findButton(h.doc.getElementById('actionList'),'End turn').click() : h.client.tap({x:1,y:0});
    assert.equal(h.client.busy,true);assert.equal(h.calls.filter(c=>c.body).length,0);
    assert.ok(text(h.doc.getElementById('status')).includes('Finishing the fight update'));
    release();await Promise.all([read,send]);
    assert.equal(h.calls.filter(c=>c.body).length,1);
    assert.equal(h.calls.filter(c=>c.body)[0].body.candidate_id,via==='button' ? 'end1' : 'move1');
  }
});

test('F2 queued action revalidates a changed turn rather than sending a stale candidate',async()=>{
  const h=clientHarness();await h.client.load('phone-fight');
  const release=h.deferRead(),read=h.client.refresh(),send=h.client.submit('end1');
  const next=fixture();next.menu.decision_id='new-turn';h.setState(next);release();
  await read;assert.equal(await send,false);assert.equal(h.calls.filter(c=>c.body).length,0);
  assert.ok(text(h.doc.getElementById('status')).includes('fight changed'));
});

test('F2 reaction buttons wait for polling and reject a superseded decision',async()=>{
  for(const stale of [false,true]) {
    const h=clientHarness(),state=reactionFixture();h.setState(state);await h.client.load('phone-fight');
    const release=h.deferRead(),read=h.client.refresh();
    const answer=findButton(h.doc.getElementById('reactionBody'),'Choose Grave Tax').click();
    assert.equal(h.client.busy,true);
    if(stale) {const next=structuredClone(state);next.pending_action.request.state_version++;h.setState(next);}
    release();await Promise.all([read,answer]);
    assert.equal(h.calls.filter(c=>c.body).length,stale ? 0 : 1);
  }
});

test('F2 next-step button waits for polling and rejects a changed automatic turn',async()=>{
  for(const stale of [false,true]) {
    const h=clientHarness(),state=fixture();state.menu.manual=false;state.menu.actor_id=enemy;state.presentation.current_actor_id=enemy;
    h.setState(state);await h.client.load('phone-fight');
    const release=h.deferRead(),read=h.client.refresh(),send=h.doc.getElementById('nextStep').click();
    assert.equal(h.client.busy,true);
    if(stale) {const next=structuredClone(state);next.menu.decision_id='new-auto';h.setState(next);}
    release();await Promise.all([read,send]);
    assert.equal(h.calls.filter(c=>c.body).length,stale ? 0 : 1);
  }
});

test('F3 equal-price routes explain walk/fly/climb, exact paths, hazards and native jump-down consequences',()=>{
  const state=fixture(),view=playerView(binding,state,seats),doc=dom(),host=doc.getElementById('actionList');
  const options=['walk','fly','climb','jump_down'].map((movement_mode,i)=>({candidate_id:`route${i}`,movement_mode,
    destination:{x:2,y:1,z:2},cost_ft:10,path:[{x:i%2,y:0,z:2},{x:2,y:1,z:2}],hazard_exposure:i===1}));
  renderOptions(host,options,state,view,()=>{},()=>{});
  const labels=host.querySelectorAll('button').filter(b=>b.dataset.candidate).map(text);
  assert.equal(new Set(labels).size,4);
  for(const mode of ['Move','Fly','Climb','Jump down']) assert.ok(labels.some(t=>t.startsWith(mode)));
  assert.ok(labels[1].includes('known hazard'));assert.ok(labels[1].includes('square 2, 1 at 10 ft'));
  assert.ok(labels[0].includes('square 1, 1 at 10 ft'));assert.ok(labels[2].includes('includes climbing'));
  assert.ok(labels[3].includes('damage and knock you prone'));assert.ok(labels[3].includes('first support below'));
  assert.notEqual(optionText(options[0],state,view),optionText({...options[0],path:options[1].path},state,view));
  assert.equal(optionText({destination:{x:1,y:0},label:'Place a wall'},state,view).includes('undefined'),false);
});

test('F3 destination and area descriptions retain effects without leaking blind-target names or internal IDs',()=>{
  const state=fixture(),view=playerView(binding,state,seats),doc=dom(),host=doc.getElementById('actionList');
  const options=[{candidate_id:'place',destination:{x:1,y:0},label:`Carry Unseen enemy (${enemy}) without Opportunity Attacks`},
    {candidate_id:'area',area:{center:{x:1,y:0}},label:`Affect Unseen enemy (${enemy}) for one turn`}];
  renderOptions(host,options,state,view,()=>{},()=>{});
  const content=text(host);
  assert.ok(content.includes('Carry Unseen creature (target) without Opportunity Attacks'));
  assert.ok(content.includes('Affect Unseen creature (target) for one turn'));
  assert.equal(content.includes('Unseen enemy'),false);
  assert.equal(content.includes('actor:'),false);
  assert.deepEqual(host.querySelectorAll('button').filter(b=>b.dataset.candidate).map(b=>b.dataset.candidate),['place','area']);
});

test('F4 real Footwork space choices use one-based squares, snapshot-relative directions, costs and nearby tokens',async()=>{
  const doc=dom(),host=doc.getElementById('reactionBody'),answers=[];
  const prompt={reaction:'Footwork',reactor:'Player',trigger:'Enemy attacks Player',context:{reactor_id:mine},
    choice:{minimum:1,maximum:1,allow_decline:true,space_map:{origin:{x:0,y:0},chooser_id:mine,
      tokens:[{id:mine,name:'Player',position:{x:0,y:0}},{id:ally,name:'Ally',position:{x:1,y:1}}]},
      options:[{id:'cell:0,1',cell:{x:0,y:1},label:'Step to 0,1 (5 ft)'},{id:'cell:1,0',cell:{x:1,y:0},label:'Step to 1,0 (5 ft)'}]}};
  renderReaction(host,prompt,{answer:a=>answers.push(a),error:assert.fail});
  const south=findButton(host,'1 square south of you');assert.ok(south);
  assert.ok(text(south).includes('Square 1, 2'));assert.ok(text(south).includes('(5 ft)'));assert.ok(text(south).includes('beside Ally'));
  assert.ok(findButton(host,'1 square east of you'));assert.equal(text(host).includes('Step to 0,1'),false);
  await south.click();assert.deepEqual(answers[0],{reactor_id:mine,selection:'USE',option_ids:['cell:0,1']});
});

test('F4 large chooser footprint and separate descriptive effects stay understandable',()=>{
  const doc=dom(),host=doc.getElementById('reactionBody');
  renderReaction(host,{reaction:'Choose a space',context:{},choice:{minimum:1,maximum:1,
    space_map:{origin:{x:0,y:0},chooser_id:mine,tokens:[{id:mine,position:{x:0,y:0},cells:[{x:0,y:0},{x:1,y:0}]}]},
    options:[{id:'step',cell:{x:1,y:0},label:'Step to 1,0 (5 ft)',description:'Move to 1,0 without Opportunity Attacks.'}]}},{answer(){},error:assert.fail});
  assert.ok(text(host).includes('your current top-left square, currently part of your space'));
  assert.ok(text(host).includes('without Opportunity Attacks'));assert.equal(text(host).includes('to 1,0'),false);
});

test('F5 binding defaults to existing Assisted, suggests a server-ranked action, confirms once and keeps all alternatives/Manual',async()=>{
  const h=clientHarness({preferred:null});await h.client.load('phone-fight');assert.equal(await h.client.bind(mine),true);
  assert.deepEqual(h.calls.filter(c=>c.body)[0].body,{actor_id:mine,controller_mode:'SUGGESTED'});
  const host=h.doc.getElementById('actionList');
  assert.ok(text(host).includes('Suggested plan — next step'));assert.equal(findButton(host,'End turn'),undefined);
  assert.ok(text(host).includes('Unseen creature'));assert.equal(text(host).includes('Unseen enemy'),false);
  await findButton(host,'Change — edit target').click();
  assert.ok(findButton(host,'Move — tap a square'));assert.ok(findButton(host,'Strike'));assert.ok(findButton(host,'End turn'));
  assert.equal(h.calls.filter(c=>c.body).length,1);
  await findButton(host,'Confirm this step').click();
  assert.equal(h.calls.filter(c=>c.body).at(-1).body.candidate_id,'strike1');
  const select=host.querySelector('select');select.value='MANUAL';await select.dispatch('change');
  assert.equal(h.calls.filter(c=>c.body).at(-1).body.controller_mode,'MANUAL');
  assert.equal(text(host).includes('Suggested plan'),false);assert.ok(findButton(host,'End turn'));
  const writes=h.calls.filter(c=>c.body).length;await h.client.load('phone-fight');
  assert.equal(h.calls.filter(c=>c.body).length,writes);assert.equal(text(host).includes('Suggested plan'),false);
});

test('F5 guided Change retains low-ranked groups/options and movement; unknown ranked IDs never invent an option',async()=>{
  const h=clientHarness({preferred:null}),state=fixture();state.presentation.actors[0].controller='SUGGESTED';state.menu.control_mode='SUGGESTED';state.menu.turn_mode='Assisted';
  state.menu.actions.push({label:'Last alternative',source_definition_id:'last',cost_label:'Bonus Action · 1 Stamina',
    options:Array.from({length:81},(_,i)=>({candidate_id:`last${i}`,label:`Alternative ${i}`}))});
  state.menu.ranked_slots={Action:['invalid','last0'],Movement:['move1']};
  assert.equal(playModel.suggestedOption(state.menu).option.candidate_id,'last0');
  h.setState(state);await h.client.load('phone-fight');const host=h.doc.getElementById('actionList');
  await findButton(host,'Change — edit target').click();await findButton(host,'Last alternative').click();
  assert.equal(host.querySelectorAll('button').filter(b=>b.dataset.candidate).length,81);
  await findButton(host,'Alternative 80').click();assert.equal(h.calls.filter(c=>c.body).at(-1).body.candidate_id,'last80');
  state.menu.ranked_slots={Action:['invalid']};h.setState(state);await h.client.refresh();
  assert.ok(text(host).includes('No ranked suggestion'));await findButton(host,'Change — edit target').click();
  assert.ok(findButton(host,'Last alternative'));assert.ok(findButton(host,'Move — tap a square'));
});

test('F5 suggested move carries its route quote and commits that exact offered candidate',async()=>{
  const h=clientHarness({preferred:null}),state=fixture();state.presentation.actors[0].controller='SUGGESTED';state.menu.control_mode='SUGGESTED';state.menu.ranked_slots={Movement:['move1']};
  h.setState(state);await h.client.load('phone-fight');const host=h.doc.getElementById('actionList');
  assert.ok(text(host).includes('5 ft of movement'));await findButton(host,'Confirm this step').click();
  assert.equal(h.calls.filter(c=>c.body).at(-1).body.candidate_id,'move1');
});

test('F5 default Assisted and mode changes never seize a model-owned creature or an open reaction decision',async()=>{
  const h=clientHarness();await h.client.load('phone-fight');h.setSeats({seats:{[mine]:{control:'MODEL'}}});await h.client.refresh();
  assert.equal(await h.client.bind(mine),false);assert.equal(await h.client.setControl('MANUAL'),false);
  assert.equal(h.calls.filter(c=>c.body).length,0);
  h.setSeats(seats);h.setState(reactionFixture());await h.client.refresh();
  assert.equal(await h.client.setControl('SUGGESTED'),false);assert.equal(h.calls.filter(c=>c.body).length,0);
});

test('touch: tap selects once, drag pans, pinch zooms and cancellation never selects',async()=>{
  const doc=dom(),viewport=doc.getElementById('map'), taps=[];
  const b=fakeBoard(), pans=[],zooms=[];
  b.centerOn=(...p)=>pans.push(p);b.zoomBy=(...p)=>zooms.push(p);
  const remove=installTouch(viewport,b,c=>taps.push(c));
  const e=(id,x,y,type)=>({pointerType:'touch',pointerId:id,clientX:x,clientY:y,type,stopImmediatePropagation(){}});
  await viewport.dispatch('pointerdown',e(1,20,20,'pointerdown'));await viewport.dispatch('pointerup',e(1,20,20,'pointerup'));assert.equal(taps.length,1);
  await viewport.dispatch('pointerdown',e(1,20,20,'pointerdown'));await viewport.dispatch('pointermove',e(1,60,20,'pointermove'));await viewport.dispatch('pointerup',e(1,60,20,'pointerup'));
  assert.equal(taps.length,1);assert.ok(pans.length);
  await viewport.dispatch('pointerdown',e(1,20,20,'pointerdown'));await viewport.dispatch('pointerdown',e(2,80,20,'pointerdown'));
  await viewport.dispatch('pointermove',e(2,140,20,'pointermove'));assert.equal(zooms[0][0],2);
  await viewport.dispatch('pointerup',e(2,140,20,'pointerup'));await viewport.dispatch('pointerup',e(1,20,20,'pointerup'));assert.equal(taps.length,1);
  await viewport.dispatch('pointerdown',e(1,20,20,'pointerdown'));await viewport.dispatch('pointercancel',e(1,20,20,'pointercancel'));assert.equal(taps.length,1);remove();
});
