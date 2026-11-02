// The real table identity/roof/fog functions and real board animation, not a
// manually injected owned array. A Python gate adds real commit/cold-load data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setTimeout as wait} from 'node:timers/promises';
import {createTableHarness, tableState, memoryStorage, actor, OUT, IN}
  from './viewer_identity_harness.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {installDOM} from './objects_dom_stub.mjs';
import {decisionChanged} from '../static/tabletop/pending-decision.js';

const pair = () => [actor('A',OUT),actor('B',IN)];
const zero = mask => mask !== null && mask.every(value=>value === 0);
const move = (sequence, actorId, path, extra = {}) => ({events:[{
  event_sequence:sequence,event_type:'MOVEMENT_COMMITTED',actor_id:actorId,
  raw:{payload:{path,destination:path.at(-1),...extra}},
}],dice:[],last_sequence:sequence});

test('two explicit human bindings on one side open a roof in exactly one browser and swapping reverses it',()=>{
  const a = createTableHarness({viewId:'browser-a',roster:pair()});
  const b = createTableHarness({viewId:'browser-b',roster:pair()});
  assert.equal(a.savePlayerView(['A']),true);
  assert.equal(b.savePlayerView(['B']),true);
  assert.equal(a.opacity(),'1'); assert.equal(b.opacity(),'0');
  assert.deepEqual([...a.currentViewer().ownedIds],['A']);
  assert.deepEqual([...b.currentViewer().ownedIds],['B']);
  a.savePlayerView(['B']); b.savePlayerView(['A']);
  assert.equal(a.opacity(),'0'); assert.equal(b.opacity(),'1');
  assert.deepEqual(a.calls,[],'choosing identity never changes a global controller');
  assert.deepEqual(b.calls,[]);
});

test('the shipped My fighters controls bind checked fighters and Open another player view starts with a new handle',async()=>{
  const roster=[...pair(),actor('summon',IN,{owner_id:'A',primary_combatant:false,summon_status:'present'})];
  const h=createTableHarness({roster});
  const picker=h.document.querySelector('#ttViewerPicker');
  assert.equal(picker.open,true);
  const inputs=h.document.querySelector('#ttViewerChoices').querySelectorAll('input');
  assert.deepEqual(inputs.map(input=>input.value),['A','B']);
  inputs.find(input=>input.value === 'B').checked=true;
  await h.document.querySelector('#ttViewerApply').click();
  assert.equal(picker.open,false);
  assert.deepEqual(h.viewerStore.read('match').actor_ids,['B']);
  assert.equal(h.opacity(),'0');
  assert.match(h.document.querySelector('#ttViewerStatus').textContent,/Viewing as: B/);
  assert.deepEqual(roster.map(row=>row.controller),['MANUAL','MANUAL','MANUAL']);
  await h.document.querySelector('#ttViewerAnother').click();
  const [url,target,features]=h.opens[0];
  const next=new URL(url,'http://localhost');
  assert.equal(next.searchParams.get('match'),'match');
  assert.notEqual(next.searchParams.get('view'),h.viewerStore.viewId);
  assert.equal(next.searchParams.has('actor_ids'),false);
  assert.equal(target,'_blank'); assert.equal(features,'noopener');
  const fresh=createTableHarness({viewId:next.searchParams.get('view'),roster});
  assert.equal(fresh.currentViewer().status,'unbound');
});

test('unbound, stale and missing seat information stay fully covered and hide every creature',()=>{
  for (const options of [{}, {boundIds:['missing']}, {boundIds:['A','missing']}, {boundIds:['A'],seats:null}]) {
    const h = createTableHarness({roster:pair(),...options});
    assert.ok(zero(Array.from(h.visibility())));
    assert.equal(h.opacity(),'1');
    assert.ok(h.tokenFrames.flat().every(row=>row.hidden));
    assert.ok(h.fogFrames.every(frame=>zero(frame.seen)),'no frame uses the GM null mask');
    assert.ok(h.document.body.classList.contains('is-viewer-pending'));
    assert.equal(h.isGMView(),false);
  }
});

test('same-profile view handles, context reloads, copied URLs and match changes keep separate bindings',()=>{
  const storage = memoryStorage();
  const a = createTableHarness({viewId:'tab-a',storage,roster:pair(),boundIds:['A']});
  const b = createTableHarness({viewId:'tab-b',storage,roster:pair(),boundIds:['B']});
  a.viewerStore.writeFog('match','team');
  const reopened = createTableHarness({viewId:'tab-a',storage,roster:pair()});
  assert.deepEqual(reopened.viewerStore.read('match').actor_ids,['A']);
  assert.equal(reopened.app.fog,'team');
  assert.equal(reopened.opacity(),'1');
  assert.equal(b.app.fog,'own'); assert.equal(b.opacity(),'0');
  const copied = createTableHarness({viewId:'tab-a',storage:memoryStorage(),roster:pair()});
  assert.equal(copied.currentViewer().status,'unbound');
  const newMatch = createTableHarness({viewId:'tab-a',storage,matchId:'different',roster:pair()});
  assert.equal(newMatch.currentViewer().status,'unbound');
  assert.equal(newMatch.app.fog,'own');
  // A duplicate tab can intentionally clone the same logical view. The new-view
  // action changes the handle instead of treating that browser clone as a claim.
  const duplicate = createTableHarness({viewId:'tab-b',storage:memoryStorage([...storage.values]),roster:pair()});
  assert.deepEqual(duplicate.viewerStore.read('match').actor_ids,['B']);
  assert.equal(duplicate.opacity(),'0');
});

test('binding changes discard exploration, geometry and token selection before the next scene',()=>{
  const state = tableState(pair(),{perception:{A:{cells:[[20,15]],creatures:['A']},B:{cells:[[4,4]],creatures:['B']}}});
  const h = createTableHarness({state,boundIds:['A']});
  const oldCell = 15 * h.board.map.width + 20, newCell = 4 * h.board.map.width + 4;
  assert.equal(h.app.explored[oldCell],1);
  h.app.selected.add('A'); h.app.fogGeometryKey = 'old geometry'; h.app.fogPolygons = ['old'];
  h.savePlayerView(['B']);
  assert.equal(h.app.explored[oldCell],0);
  assert.equal(h.app.explored[newCell],1);
  assert.equal(h.app.selected.has('A'),false);
  assert.notEqual(h.app.fogGeometryKey,'old geometry');
  h.app.state.presentation.actors = h.app.state.presentation.actors.filter(row=>row.entity_id !== 'B');
  h.renderTokens();
  assert.equal(h.currentViewer().status,'stale');
  assert.ok(h.app.explored.every(value=>value === 0));
  assert.equal(h.document.querySelector('#ttViewerPicker').open,true);
});

test('later owned summons inherit identity while dismissed, down, unpositioned and unrelated summons do not open roofs',()=>{
  const h = createTableHarness({roster:[actor('A',OUT),actor('B',OUT)],boundIds:['A']});
  const summon = actor('summon',{x:2,y:4},{owner_id:'A',primary_combatant:false,summon_status:'present',
    footprint:{width_cells:2,height_cells:2}});
  h.app.state.presentation.actors.push(summon); h.renderTokens();
  assert.equal(h.opacity(),'0','a later arriving footprint enters the owned home');
  assert.equal(h.isOwnedActor(summon),true);
  for (const patch of [{summon_status:'dismissed'}, {summon_status:'present',active:false},
    {active:true,position:null}, {position:IN,owner_id:'B'}]) {
    Object.assign(summon,patch); h.renderTokens(); assert.equal(h.opacity(),'1');
  }
});

test('model or AI controller changes exclude a retained binding without transferring another screen',()=>{
  const h = createTableHarness({roster:pair(),boundIds:['B']});
  assert.equal(h.opacity(),'0');
  h.app.seatStatus={seats:{B:{control:'MODEL'}}}; h.renderTokens();
  assert.equal(h.opacity(),'1'); assert.ok(zero(Array.from(h.visibility())));
  assert.deepEqual(h.viewerStore.read('match').actor_ids,['B']);
  h.app.seatStatus={seats:{}}; h.app.state.presentation.actors[1].controller='LOCAL_AUTO'; h.renderTokens();
  assert.equal(h.opacity(),'1');
  h.app.state.presentation.actors[1].controller='MANUAL'; h.renderTokens(); assert.equal(h.opacity(),'0');
  h.app.seatStatus=null; h.renderTokens();
  assert.ok(zero(Array.from(h.visibility()))); assert.equal(h.opacity(),'1');
  h.app.seatStatus={seats:{}}; h.renderTokens(); assert.equal(h.opacity(),'0');
});

test('allied, chosen and fallen-owner perception never grants roof occupancy and sides come from bindings',()=>{
  const roster=[actor('own',OUT,{team_index:2}),actor('ally',IN,{team_index:2,controller:'LOCAL_AUTO'}),
    actor('zero',IN,{team_index:0})];
  const h=createTableHarness({roster,boundIds:['own'],fog:'team'});
  assert.deepEqual(h.fogAudience().map(row=>row.entity_id),['own','ally']);
  assert.equal(h.opacity(),'1');
  h.app.fog='selected'; h.app.selected=new Set(['zero']); h.renderTokens();
  assert.deepEqual(h.fogAudience().map(row=>row.entity_id),['zero']);
  assert.equal(h.opacity(),'1');
  h.app.selected.clear(); h.renderTokens();
  assert.ok(zero(Array.from(h.visibility())),'empty chosen-token view remains covered');
  roster[0].active=false; roster[0].position=IN; h.app.fog='own'; h.renderTokens();
  assert.deepEqual(h.fogAudience().map(row=>row.entity_id),['ally']);
  assert.equal(h.opacity(),'1','fallen owner cannot open the home');
});

test('Game Master requires an explicit role and retains transparent roofs and its toggle',async()=>{
  const h=createTableHarness({roster:pair(),boundIds:['A']});
  h.app.fog='off'; h.renderTokens();
  assert.equal(h.isGMView(),false); assert.notEqual(h.visibility(),null);
  h.selectGMView();
  assert.equal(h.isGMView(),true); assert.equal(h.visibility(),null); assert.equal(h.opacity(),'0.28');
  const button=h.document.querySelector('#ttRoofs');
  await button.dispatch('click',{currentTarget:button}); assert.equal(h.opacity(),'0');
  h.savePlayerView(['A']);
  assert.equal(h.opacity(),'1','the GM toggle does not hide a player roof');
  assert.equal(h.app.fog,'own'); assert.notEqual(h.visibility(),null);
});

test('storage errors retain an explicit in-memory view without enabling another context',()=>{
  const blocked={getItem(){throw Error('storage denied');},setItem(){throw Error('storage denied');}};
  const h=createTableHarness({roster:pair(),storage:blocked});
  assert.equal(h.savePlayerView(['B']),true); assert.equal(h.opacity(),'0');
  h.renderTokens(); assert.equal(h.opacity(),'0');
  const fresh=createTableHarness({roster:pair(),storage:blocked});
  assert.equal(fresh.currentViewer().status,'unbound'); assert.equal(fresh.opacity(),'1');
});

test('board preferences tolerate a localStorage getter and writer that throw',()=>{
  installDOM('<body></body>');
  const original=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  try {
    Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){throw Error('storage denied');}});
    const board=createBoard(document.body);
    assert.doesNotThrow(()=>board.setRulesOverlay(true));
  } finally {Object.defineProperty(globalThis,'localStorage',original);}
});

test('switching fighters closes ground cards and cancels a delayed card from the previous view',async()=>{
  const state=tableState(pair());
  state.ground={'floor:grass_meadow':{name:'Meadow grass',lines:['Grass changes no movement cost.']}};
  // Fighter A must see the two squares it hovers; unseen ground shows no card (fog memory, board.js).
  state.fog_perception={A:{cells:[[0,0],[1,0]],creatures:['A']},B:{cells:[[IN.x,IN.y]],creatures:['B']}};
  const h=createTableHarness({state,boundIds:['A']});
  const card=h.document.querySelector('.tt-hovercard');
  await h.board.viewport.dispatch('pointermove',{clientX:48,clientY:48});
  await wait(8);
  assert.equal(card.hidden,false,'a real ground hover card is open without a token owner');
  h.savePlayerView(['B']);
  assert.equal(card.hidden,true);
  await h.board.viewport.dispatch('pointermove',{clientX:112,clientY:48});
  h.savePlayerView(['A']);
  await wait(8);
  assert.equal(card.hidden,true,'the previous view cannot reopen a queued ground card');
});

test('load and reload request fog before any player frame, preserve the view URL, and never flash a null mask',async()=>{
  const storage=memoryStorage([['tt-fog','off']]);
  for (const boundIds of [null,['A']]) {
    const h=createTableHarness({roster:pair(),storage,boundIds,viewId:boundIds?'loaded-a':'new-unbound',initialize:false});
    assert.equal(h.app.fog,'own','production app initializer fails closed');
    assert.ok(h.document.body.classList.contains('is-viewer-pending'),'markup gates the scene before scripts run');
    assert.equal(await h.loadMatch('match'),true);
    assert.ok(h.calls.filter(row=>row.url.includes('/state?')).every(row=>/[?&]fog=true(?:&|$)/.test(row.url)));
    assert.ok(h.fogFrames.length && h.fogFrames.every(frame=>frame.seen !== null));
    assert.ok(h.urls.every(url=>new URL(url,'http://localhost').searchParams.get('view') === h.viewerStore.viewId));
    if (!boundIds) {
      assert.ok(h.tokenFrames.flat().every(row=>row.hidden));
      assert.equal(h.document.querySelector('#ttViewerPicker').open,true);
    }
    h.fogFrames.length=0;
    assert.equal(await h.loadMatch('match'),true);
    assert.ok(h.fogFrames.every(frame=>frame.seen !== null));
  }
});

test('confirming the real picker while initial history is loading does not discard that history',async()=>{
  const h=createTableHarness({roster:pair(),initialize:false});
  let finishEvents, eventsRequested=false;
  const delayedEvents=new Promise(resolve=>{finishEvents=resolve;});
  h.api=async url=>{
    if (url.endsWith('/seat-status')) return {seats:{}};
    if (url.includes('/events?')) {eventsRequested=true;return delayedEvents;}
    return h.nextState;
  };
  const loading=h.loadMatch('match');
  for (let turns=0;!eventsRequested && turns<10;turns++) await wait(0);
  assert.equal(eventsRequested,true);
  h.document.querySelector('#ttViewerChoices').querySelectorAll('input')[0].checked=true;
  await h.document.querySelector('#ttViewerApply').click();
  finishEvents({events:[],dice:[],last_sequence:17});
  assert.equal(await loading,true);
  assert.equal(h.app.lastSequence,17);
  assert.equal(h.app.busy,false);
  assert.deepEqual(h.viewerStore.read('match').actor_ids,['A']);
});

test('a late older seat response cannot undo a newer MODEL exclusion',async()=>{
  const h=createTableHarness({roster:pair(),boundIds:['B']});
  const releases=[];
  h.api=url=>{
    assert.ok(url.endsWith('/seat-status'));
    return new Promise(resolve=>releases.push(resolve));
  };
  const old=h.loadSeats(),latest=h.loadSeats();
  releases[1]({seats:{B:{control:'MODEL'}}}); await latest;
  assert.equal(h.opacity(),'1');
  releases[0]({seats:{}}); await old;
  assert.equal(h.app.seatStatus.seats.B.control,'MODEL');
  assert.ok(zero(Array.from(h.visibility()))); assert.equal(h.opacity(),'1');
});

test('idle player polling revalidates controller changes even with the same menu and no new event',async()=>{
  const h=createTableHarness({roster:pair(),boundIds:['B']});
  h.app.menu={manual:true,actor_id:'A'};
  h.nextState=structuredClone(h.app.state);
  h.nextState.presentation.actors.find(row=>row.entity_id === 'B').controller='LOCAL_AUTO';
  await h.pollTable();
  assert.ok(h.calls.some(row=>row.url.includes('/state?')));
  assert.equal(h.opacity(),'1');
  assert.ok(zero(Array.from(h.visibility())));
  assert.deepEqual(h.viewerStore.read('match').actor_ids,['B']);
});

test('waiting-reaction polling revalidates ownership and consumes new events without answering or losing a map pick',async()=>{
  const h=createTableHarness({roster:pair(),boundIds:['B']});
  const prompt={context:{reactor_id:'B',checkpoint:'HIT'},choice:{kind:'RELOCATION'}};
  h.app.state.pending_action={method:'act',request:{candidate_id:'pending'},reaction:prompt};
  const waiting={matchId:'match',prompt,stop:()=>assert.fail('the same prompt cannot be superseded'),
    // askReaction() gives every real prompt its own supersede check; mirror it here so polling reads this promise.
    changed:state=>decisionChanged(prompt,state?.pending_action)};
  const answers=[];
  let resolveAnswer;
  const answer=new Promise(resolve=>{resolveAnswer=resolve;});
  const finish=selection=>{answers.push(selection);resolveAnswer(selection);};
  const pick={options:new Map([['5,4',{id:'square-five-four'}]]),cursor:{x:5,y:4},
    close:()=>assert.fail('observation cannot choose or cancel a square')};
  h.app.waitingReaction=waiting; h.app.finishReaction=finish; h.app.mapPick=pick; h.app.busy=true;
  h.document.querySelector('#ttReaction').showModal();
  h.nextState=structuredClone(h.app.state);
  h.nextState.presentation.actors.find(row=>row.entity_id === 'B').controller='LOCAL_AUTO';
  await h.pollTable();
  assert.equal(h.opacity(),'1'); assert.ok(zero(Array.from(h.visibility())));
  assert.equal(h.app.waitingReaction,waiting); assert.equal(h.app.finishReaction,finish);
  assert.equal(h.app.mapPick,pick); assert.deepEqual(pick.cursor,{x:5,y:4});
  assert.deepEqual(answers,[]); assert.equal(h.app.busy,true);
  assert.equal(h.calls.some(row=>row.url.includes('/events?')),false,'metadata-only changes need no journal playback');

  const previous=h.app.state;
  h.nextState=structuredClone(previous); h.nextState.last_sequence=2;
  h.nextState.presentation.actors.find(row=>row.entity_id === 'B').controller='MANUAL';
  h.nextState.presentation.actors.find(row=>row.entity_id === 'B').hit_points.current=9;
  const effects=[];
  let expectedCursor=1,expectedState=previous;
  h.board.floatText=(x,y,text)=>{
    effects.push({x,y,text});
    assert.equal(h.app.lastSequence,expectedCursor,'journal is consumed before render advances its cursor');
    assert.equal(h.app.state,expectedState,'effect playback precedes the new snapshot');
  };
  h.api=async url=>url.endsWith('/seat-status') ? {seats:{}}
    : url.includes('/events?') ? {events:[{event_sequence:2,event_type:'DAMAGE_COMMITTED',target_ids:['B'],
      raw:{payload:{hp_damage:1}}},{event_sequence:3,event_type:'DAMAGE_COMMITTED',target_ids:['B'],
      raw:{payload:{hp_damage:2}}}],dice:[],last_sequence:3} : h.nextState;
  await h.pollTable();
  assert.deepEqual(effects,[{x:IN.x,y:IN.y,text:'−1'}]);
  assert.equal(h.app.lastSequence,2); assert.equal(h.app.playedSequence,2);
  assert.equal(h.app.state.last_sequence,2,'the concurrent event beyond this snapshot remains for the next poll');
  assert.equal(h.opacity(),'0'); assert.equal(h.app.mapPick,pick);
  assert.equal(h.app.waitingReaction,waiting); assert.equal(h.app.finishReaction,finish);
  expectedCursor=2; expectedState=h.app.state;
  h.nextState=structuredClone(expectedState); h.nextState.last_sequence=3;
  h.nextState.presentation.actors.find(row=>row.entity_id === 'B').hit_points.current=7;
  await h.pollTable();
  assert.deepEqual(effects,[{x:IN.x,y:IN.y,text:'−1'},{x:IN.x,y:IN.y,text:'−2'}]);
  assert.equal(h.app.lastSequence,3); assert.equal(h.app.playedSequence,3);
  assert.equal(h.app.mapPick,pick); assert.equal(h.app.waitingReaction,waiting);
  assert.deepEqual(answers,[]); assert.ok(h.calls.every(row=>!row.options?.body));
  finish('DECLINE'); assert.equal(await answer,'DECLINE','only the explicit answer settles its promise');
});

test('a malformed saved choice opens a usable picker and never renders GM visibility',()=>{
  const key=`tt-viewer:v1:${JSON.stringify(['corrupt','match','binding'])}`;
  const storage=memoryStorage([[key,JSON.stringify({version:1,role:'player',actor_ids:{}})]]);
  const h=createTableHarness({viewId:'corrupt',storage,roster:pair()});
  assert.equal(h.currentViewer().status,'stale');
  assert.equal(h.document.querySelector('#ttViewerPicker').open,true);
  assert.equal(h.document.querySelector('#ttViewerChoices').querySelectorAll('input').length,2);
  assert.ok(zero(Array.from(h.visibility())));
});

function recordRoofs(h, id) {
  const node=h.board.element.querySelectorAll('[data-roof]')[0], frames=[];
  let opacity=node.style.opacity;
  Object.defineProperty(node.style,'opacity',{configurable:true,get:()=>opacity,set:value=>{
    opacity=value; frames.push({position:h.position(id),opacity:value});
  }});
  return frames;
}

for (const movementKind of ['normal','forced','teleport']) {
  test(`production ${movementKind} playback updates roofs at the drawn waypoint before a state refresh`,async()=>{
    const path=[{x:2,y:4},{x:3,y:4},{x:4,y:4}];
    const roster=[actor('A',path[0]),actor('B',OUT)];
    const a=createTableHarness({viewId:'moving-a',roster:structuredClone(roster),boundIds:['A']});
    const b=createTableHarness({viewId:'watching-b',roster:structuredClone(roster),boundIds:['B']});
    const aFrames=recordRoofs(a,'A'),bFrames=recordRoofs(b,'A');
    const events=move(2,'A',path,{movement_kind:movementKind === 'forced'?'forced':'walk',teleport:movementKind === 'teleport'});
    await a.playEvents(events); await b.playEvents(events);
    assert.deepEqual(a.position('A'),path.at(-1));
    assert.equal(a.app.state.presentation.actors[0].position.x,2,'committed state is still the origin');
    assert.equal(a.opacity(),'0','roof must open during playback before renderTokens');
    assert.equal(b.opacity(),'1');
    assert.ok(aFrames.some(frame=>frame.position.x === 4 && frame.opacity === '0'));
    if (movementKind === 'teleport') assert.ok(aFrames.every(frame=>frame.position.x !== 3),'blink never occupies the intermediate square');
    else assert.ok(aFrames.some(frame=>frame.position.x === 3 && frame.opacity === '0'),'route entry is updated at its first inside waypoint');
    assert.ok(bFrames.every(frame=>frame.opacity === '1'),'another browser keeps its roof throughout the same playback');
    a.renderTokens(); b.renderTokens();
    assert.equal(a.opacity(),'0'); assert.equal(b.opacity(),'1');
    await a.playEvents(move(3,'A',[...path].reverse(),{movement_kind:movementKind,teleport:movementKind === 'teleport'}));
    assert.equal(a.opacity(),'1','exit restores roof during playback');
  });
}

test('a redraw while playback is ahead of state uses the drawn square, not the cached final destination',async()=>{
  const path=[{x:2,y:4},{x:2,y:5},{x:3,y:5},{x:4,y:5}];
  const h=createTableHarness({roster:[actor('A',path[0])],boundIds:['A']});
  const running=h.playEvents(move(2,'A',path));
  await wait(1);
  h.renderTokens();
  const drawn=h.position('A');
  assert.equal(h.opacity(),drawn.x < 3?'1':'0');
  await running;
  assert.equal(h.opacity(),'0');
});

const recordingPath=process.env.VIEWER_IDENTITY_RECORDING;
if (process.env.VIEWER_IDENTITY_RECORDING_REQUIRED === '1' && !recordingPath)
  throw new Error('VIEWER_IDENTITY_RECORDING_REQUIRED needs the real table commit/reload fixture');
test('real Willow commit and cold reload preserve distinct player roofs through production playback',
  {skip:!recordingPath},async()=>{
    const recording=JSON.parse(readFileSync(recordingPath,'utf8'));
    const [first]=recording.steps;
    const storage=memoryStorage();
    const a=createTableHarness({viewId:'recorded-a',storage,state:first.before,matchId:recording.matchId,boundIds:[recording.mine]});
    const b=createTableHarness({viewId:'recorded-b',state:structuredClone(first.before),matchId:recording.matchId,boundIds:[recording.ally]});
    for (const step of recording.steps) {
      await a.playEvents(step.events); await b.playEvents(step.events);
      assert.equal(a.opacity(),step.inside?'0':'1','actual committed path sets its own roof before state refresh');
      assert.equal(b.opacity(),'1','second manual teammate does not acquire occupancy');
      a.render(step.after); b.render(structuredClone(step.after));
      assert.equal(a.opacity(),step.inside?'0':'1'); assert.equal(b.opacity(),'1');
      const cold=createTableHarness({viewId:'recorded-a',storage,state:step.after,matchId:recording.matchId});
      assert.equal(cold.opacity(),step.inside?'0':'1');
    }
  });
