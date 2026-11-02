import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Element} from './objects_dom_stub.mjs';
import {checkMove} from '../static/tabletop/assisted-menu.js';
import {expandMovementGrid} from '../static/tabletop/movement-grid.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';

globalThis.window = {confirm: () => { throw new Error('movement must not open a confirmation dialog'); }};
const desktop = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
assert.doesNotMatch(desktop, /confirmRouteQuote|window?\.confirm\(/,
  'manual desktop movement commits without a confirmation popup');
const compact = expandMovementGrid({movement_grid:{format:'layers-v2',layers:[[0,15,'walk',false,false,[4,6]]]}}).moves[0];
assert.equal(compact.hazard_exposure, false,
  'compact grid rows without a known hazard are explicitly safe, not undefined');

const move = {candidate_id:'deferred:4,6', destination:{x:4,y:6,z:0}, cost_ft:15,
  movement_mode:'walk', deferred_route:true, hazard_exposure:false, path:[]};
const menu = {actions:[], moves:[move], ranked_slots:{Movement:[move.candidate_id]}};
const quote = {candidate:{candidate_id:'route-1',canonical_path:[{x:3,y:6,z:0},{x:4,y:6,z:0}],
  metadata:{hazard_exposure:true}}};
const submitted = [];
const root = renderRankedMenu(menu, {doc:{createElement:tag => new Element(tag)},
  onMove: row => submitted.push(row),
  onPreviewMove: row => checkMove(menu,row,async () => quote,() => true)});
const button = root.querySelectorAll('button')[0];
await button.click();
assert.equal(submitted.length,0,'initial selection shows the route preview');
assert.equal(move.hazard_exposure,true);
assert.match(button.textContent,/Warning: this route crosses a known hazard/,
  'the move preview warns about the known hazard');
await button.click();
assert.deepEqual(submitted,[move],'the reviewed route commits on the next action click without a dialog');
console.log('desktop deferred movement previews hazard and commits without a confirmation dialog');
