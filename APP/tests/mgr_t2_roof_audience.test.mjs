// Production table functions with real board/fog/seat dependencies, without page boot or a browser.
// Explicit local binding uses the same resolver as production; movement playback has its own gate.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createTableHarness, tableState, actor, OUT, IN} from './viewer_identity_harness.mjs';
import {CELL} from '../static/tabletop/board.js';

const fromStdin = process.env.MGR_T2_TABLE_STDIN === '1';
const source = readFileSync(fromStdin ? 0 : new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
console.log('Production table source:', fromStdin ? 'assigned base supplied on stdin' : 'worktree');
function table(roster, fog = 'own') {
  const perception=Object.fromEntries(roster.map(a=>[a.entity_id,{cells:[[4,4]],creatures:['seen']}]));
  return createTableHarness({state:tableState(roster,{perception}),fog,boundIds:['own'],source});
}

test('Allies view retains allied perception but only owned occupants open roofs',()=>{
  const t=table([actor('own',OUT),actor('ally',IN,{controller:'LOCAL_AUTO'})], 'team');
  t.renderTokens();
  assert.deepEqual(t.fogAudience().map(a=>a.entity_id),['own','ally']);
  assert.equal(t.opacity(),'1');
});
test('Chosen non-owned token cannot open roofs, even a manually driven foe',()=>{
  const t=table([actor('own',OUT),actor('foe',IN,{team_index:1})], 'selected');
  t.app.selected.add('foe'); t.renderTokens();
  assert.deepEqual(t.fogAudience().map(a=>a.entity_id),['foe']);
  assert.equal(t.opacity(),'1');
});
test('all-owned-down allied fog fallback does not become roof ownership',()=>{
  const t=table([actor('own',IN,{active:false}),actor('ally',IN,{controller:'LOCAL_AUTO'})]);
  t.renderTokens();
  assert.deepEqual(t.fogAudience().map(a=>a.entity_id),['ally']);
  assert.equal(t.opacity(),'1');
});
test('owned entry/exit uses displayed moves, pause/forced snapshots, teleports and committed refreshes',()=>{
  const own=actor('own',OUT), t=table([own,actor('ally',OUT,{controller:'LOCAL_AUTO'})],'selected');
  t.app.selected.add('ally'); // Looking through somebody outside must not suppress owned entry.
  t.renderTokens(); assert.equal(t.opacity(),'1');
  own.position=IN; t.renderTokens(); assert.equal(t.opacity(),'0','committed entry');
  own.position=OUT; t.renderTokens(); assert.equal(t.opacity(),'1','committed exit');
  t.app.movePositions.set('own',{position:IN,sequence:2});
  t.renderTokens(); assert.equal(t.opacity(),'0','event destination while state lags');
  assert.equal(t.board.tokenNode('own').style.transform,`translate(${4*CELL}px, ${4*CELL}px)`);
  t.app.mapPick={positions:new Map([['own',OUT]])};
  t.renderTokens(); assert.equal(t.opacity(),'1','placement takes display precedence');
  t.app.mapPick=null;
  t.app.movePositions.set('own',{position:IN,sequence:Infinity,pause:true});
  t.renderTokens(); assert.equal(t.opacity(),'0','pause snapshot');
  t.app.movePositions.set('own',{position:OUT,sequence:3});
  t.renderTokens(); assert.equal(t.opacity(),'1','next destination/teleport snapshot');
  own.position=IN; t.app.state.last_sequence=3;
  t.renderTokens(); assert.equal(t.opacity(),'0','fresh committed snapshot retires old destination');
  assert.equal(t.app.movePositions.size,0);
});
test('owned present summons and large footprints count; down/off-map/unpositioned/model actors do not',()=>{
  const own=actor('own',OUT), summon=actor('summon',{x:2,y:4},{owner_id:'own',primary_combatant:false,summon_status:'present',
    footprint:{width_cells:2,height_cells:2}}), t=table([own,summon]);
  t.renderTokens(); assert.equal(t.opacity(),'0');
  summon.summon_status='dismissed'; t.renderTokens(); assert.equal(t.opacity(),'1');
  assert.ok(!t.board.tokenNode('summon'));
  summon.summon_status='present'; summon.active=false;
  t.renderTokens(); assert.equal(t.opacity(),'1');
  summon.active=true; t.app.seatStatus={seats:{own:{control:'MODEL'}}};
  t.renderTokens(); assert.equal(t.opacity(),'1');
  t.app.seatStatus={seats:{}};
  // The pre-fix source has no separate helper. Its mode regressions above still exercise
  // renderTokens; once present, also check this helper's defensive input contract.
  if (t.roofAudience) assert.deepEqual(t.roofAudience([own,actor('missing',null),
    actor('absent',IN,{summon_status:'waiting'}),actor('down',IN,{active:false})])
    .map(a=>a.entity_id),['own']);
});
test('GM transparency/toggle and perceived/unperceived masks remain on existing fog audience',async()=>{
  const roster=[actor('own',OUT),actor('ally',IN,{controller:'LOCAL_AUTO'}),
    actor('seen',IN,{team_index:1}),actor('unseen',{x:5,y:4},{team_index:1})];
  const t=table(roster,'team');
  t.app.state.fog_perception.own={cells:[],creatures:[]};
  t.renderTokens();
  assert.equal(t.opacity(),'1');
  assert.equal(t.board.tokenNode('seen').classList.contains('is-hidden'),false);
  assert.equal(t.board.tokenNode('unseen').classList.contains('is-hidden'),true);
  assert.equal(t.board.tokenNode('seen').parentNode.classList.contains('tt-roof-interior'),false);
  const seen=t.board.element.querySelectorAll('[data-roof]')[0];
  assert.equal(t.app.explored[4*t.board.map.width+4],1);
  assert.equal(t.visibility()[4*t.board.map.width+4],1,'allied cells still contribute perception');
  t.app.fog='own'; t.renderTokens();
  assert.equal(t.opacity(),'1');
  assert.equal(t.visibility()[4*t.board.map.width+4],0,'own fog does not acquire allied cells');
  assert.equal(t.board.tokenNode('seen').classList.contains('is-hidden'),true);
  t.app.fog='selected'; t.app.selected.add('ally'); t.renderTokens();
  assert.equal(t.opacity(),'1','chosen ally contributes perception only');
  assert.equal(t.board.tokenNode('seen').classList.contains('is-hidden'),false);
  t.selectGMView(); t.renderTokens(); assert.equal(t.opacity(),'0.28');
  assert.equal(t.board.tokenNode('unseen').classList.contains('is-hidden'),false);
  const button=t.document.querySelector('#ttRoofs');
  await button.dispatch('click',{currentTarget:button});
  assert.equal(t.opacity(),'0');
  assert.equal(t.document.querySelector('#ttRoofs').getAttribute('aria-pressed'),'false');
  await button.dispatch('click',{currentTarget:button});
  assert.equal(t.opacity(),'0.28');
  await button.dispatch('click',{currentTarget:button});
  t.savePlayerView(['own']); t.app.fog='team'; t.renderTokens(); assert.equal(t.opacity(),'1','GM switch does not disable character roofs');
  roster[0].position=IN; t.renderTokens(); assert.equal(t.opacity(),'0');
  assert.equal(t.board.tokenNode('unseen').classList.contains('is-hidden'),true);
  assert.strictEqual(t.board.element.querySelectorAll('[data-roof]')[0],seen,'roof cache survives audience/position changes');
});
