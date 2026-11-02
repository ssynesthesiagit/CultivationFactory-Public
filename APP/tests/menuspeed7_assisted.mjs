// Deterministic DOM/controller checks fed an actual TabletopService menu.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Element, installDOM} from './objects_dom_stub.mjs';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';
import {expandMovementGrid} from '../static/tabletop/movement-grid.js';
import {expandSource, checkMove, sourceRankId} from '../static/tabletop/assisted-menu.js';
import {suggestedOption} from '../static/play/play-model.js';
import {createPlay} from '../static/play/play-client.js';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {emptyMemory} from '../static/tabletop/fog_memory.js';

const data = JSON.parse(readFileSync(0, 'utf8'));
const text = n => [n.textContent, ...(n.children || []).map(text)].join(' ');
const buttons = n => n.querySelectorAll('button');
const find = (n, label) => buttons(n).find(b => text(b).includes(label));
const clone = x => structuredClone(x);
const sourceId = 'source:' + data.source;
assert.ok(data.all_ranked.includes(sourceId));
assert.deepEqual(data.state.menu.ranked_slots.Movement, ['movement:compact']);

// Desktop: initial slots include a legal attack AND compact routes. Opening
// one header is read-only; only the later concrete target press can submit.
const menu = expandMovementGrid(clone(data.state.menu));
const group = menu.actions.find(g => g.source_definition_id === data.source);
const doc = {createElement: tag => new Element(tag)};
const acts = [], moves = [], requests = [];
const load = async (path, options) => {
  requests.push({path, options});
  if (path.startsWith('/action-options?')) {
    assert.equal(new URLSearchParams(path.split('?')[1]).get('source'), data.source);
    return clone(data.expansion);
  }
  assert.equal(path, '/movement-destination/preview');
  return clone(data.quote);
};
const root = renderRankedMenu(menu, {doc, onAct: id => acts.push(id), onMove: m => moves.push(m),
  onSource: g => expandSource(menu, g, load, () => true),
  onPreviewMove: m => checkMove(menu, m, load, () => true)});
const actionSlot = root.children.find(n => n.children[0].textContent === 'Action');
assert.ok(!text(actionSlot).includes('No choices available'));
if (!buttons(actionSlot).some(b => b.children[0]?.textContent === group.label))
  await find(actionSlot, 'More…').click();
await buttons(actionSlot).find(b => b.children[0]?.textContent === group.label).click();
assert.equal(requests.length, 1);
assert.deepEqual(acts, []);
const target = group.options.find(o => o.target_ids.includes('actor:factory.worker2-foe'));
await buttons(actionSlot).find(b => text(b).includes(target.label) && text(b).includes('Confirm')).click();
assert.deepEqual(acts, [target.candidate_id]);
const movementSlot = root.children.find(n => n.children[0].textContent === 'Movement');
const moveButton = buttons(movementSlot)[0];
await moveButton.click();
assert.equal(moves.length, 0);
assert.ok(text(moveButton).includes('Confirm'));
await moveButton.click();
assert.equal(moves.length, 1);
assert.ok(moves[0].route_checked);

// Source expansion is exhaustive; a source ref still works once it is cached.
assert.equal(group.options.length, data.expansion.actions[0].options.length);
assert.ok(suggestedOption({...menu, ranked_slots:{Action:[sourceId]}}, data.state).option);
const stale = clone(data.state.menu.actions.find(g => g.source_definition_id === data.source));
assert.equal(await expandSource(menu, stale, load, () => false), null);
assert.ok(stale.lazy);
const empty = clone(stale);
await expandSource(menu, empty, async () => ({actions:[]}), () => true);
assert.equal(empty.lazy, false);
assert.deepEqual(empty.options, []);
const denied = clone(menu.moves[0]); delete denied.route_checked;
await assert.rejects(checkMove(menu, denied, async () => {throw Error('No legal route');}, () => true));
assert.ok(!denied.route_checked);

// Phone uses its real controller and refresh-before-commit flow. Every HTTP
// response is an offline saved service result; no browser/server is launched.
function phone(snapshot, reply) {
  const doc = installDOM(readFileSync(new URL('../static/play/play.html', import.meta.url), 'utf8'));
  doc.createTextNode = s => Object.assign(new Element('span'), {textContent:s, nodeType:3});
  const id = snapshot.presentation.match_id, owner = snapshot.menu.actor_id;
  const viewerStore = createViewerStore({viewId:'menuspeed7f2'});
  viewerStore.bindPlayer(id, [owner]);
  const calls = [];
  let state = clone(snapshot);
  const request = async (path, options = {}) => {
    calls.push({path, ...options});
    const result = reply?.(path, options);
    if (result !== undefined) return result;
    if (path.includes('/state?')) return clone(state);
    if (path.endsWith('/seat-status')) return {seats:{}};
    if (path.includes('/events?')) return {events:[], last_sequence:state.last_sequence};
    if (path.endsWith('/sheet')) return {buttons:[],library:{groups:[]}};
    if (path.endsWith('/act') || path.endsWith('/movement-path/commit')) return {status:'COMMITTED'};
    throw Error(`Unexpected offline request ${path}`);
  };
  const board = {element:new Element(), map:{width:30,height:30}, view:{x:0,y:0,zoom:1},
    terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null,sceneryRecordAt:()=>null,objectArtRecordAt:()=>null,
    fit(){},zoomBy(){},centerOn(){},closeHoverCard(){},cellAt:()=>({x:1,y:0})};
  for (const key of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights'])
    board[key] = (...args) => {if (key === 'setMap') board.map = args[0];};
  const client = createPlay({doc,request,board,viewerStore,frame:()=>{},
    memoryStore:{read:()=>emptyMemory(),ready:()=>false,save(){}},
    controlStore:{read:()=> 'SUGGESTED',write(){}}});
  return {client,doc,calls,id,setState:s=>{state=clone(s);}};
}
const snapshot = clone(data.state);
// Focus the server's actual ranked attack source. Other legal sources remain
// in actions, so Change can still reach every alternative and every target.
snapshot.menu.ranked_slots.Action = [sourceId, ...snapshot.menu.ranked_slots.Action.filter(id => id !== sourceId)];
const p = phone(snapshot, path => path.includes('/action-options?') ? clone(data.expansion) : undefined);
await p.client.load(p.id);
const host = p.doc.getElementById('actionList');
assert.ok(text(host).includes(group.label));
assert.ok(!find(host, 'Confirm this step'), 'An inspection handle cannot be confirmed');
await find(host, 'Check targets for this step').click();
assert.equal(p.calls.filter(c => c.body).length, 0);
assert.ok(find(host, 'Confirm this step'));
const proposed = suggestedOption(p.client.state.menu, p.client.state);
await find(host, 'Change —').click();
for (const g of snapshot.menu.actions) assert.ok(text(host).includes(g.label));
await find(host, 'Confirm this step').click();
assert.equal(p.calls.filter(c => c.path.endsWith('/act')).length, 1);
assert.equal(p.calls.find(c => c.path.endsWith('/act')).body.candidate_id, proposed.option.candidate_id);
assert.equal(p.calls.filter(c => c.path.includes('/action-options?')).length, 1);

let release;
const stalePhone = phone(snapshot, path => path.includes('/action-options?')
  ? new Promise(resolve => {release = resolve;}) : undefined);
await stalePhone.client.load(stalePhone.id);
const checking = find(stalePhone.doc.getElementById('actionList'), 'Check targets for this step').click();
const newer = clone(snapshot); newer.menu.state_version++;
stalePhone.setState(newer); await stalePhone.client.refresh();
release(clone(data.expansion)); await checking;
assert.ok(!find(stalePhone.doc.getElementById('actionList'), 'Confirm this step'));
assert.equal(stalePhone.calls.filter(c => c.body).length, 0);

const moving = clone(snapshot);
moving.menu.ranked_slots = {Movement:['movement:compact']};
moving.menu.actions = [];
const m = phone(moving, path => path.endsWith('/movement-destination/preview') ? clone(data.quote) : undefined);
await m.client.load(m.id);
const mh = m.doc.getElementById('actionList');
assert.ok(!find(mh, 'Confirm this step'));
await find(mh, 'Check route for this step').click();
assert.ok(find(mh, 'Confirm this step'));
assert.equal(m.calls.filter(c => c.path.endsWith('/movement-path/commit')).length, 0);
await find(mh, 'Confirm this step').click();
assert.equal(m.calls.filter(c => c.path.endsWith('/movement-path/commit')).length, 1);
assert.equal(m.calls.find(c => c.path.endsWith('/movement-path/commit')).body.candidate_id, data.quote.candidate.candidate_id);
console.log('desktop and phone: real lazy attack, compact route, confirmation, alternatives, stale and denied checks passed');
