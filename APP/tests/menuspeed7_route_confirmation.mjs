import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {confirmRouteQuote} from '../static/tabletop/assisted-menu.js';
import {expandMovementGrid} from '../static/tabletop/movement-grid.js';

const desktop = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
assert.match(desktop, /confirmRouteQuote\(deferred, quote\)/,
  'Manual desktop movement must confirm the native preview before commit');

const compact = expandMovementGrid({movement_grid:{format:'layers-v2',layers:[[0,15,'walk',false,false,[4,6]]]}}).moves[0];
assert.equal(compact.hazard_exposure, false,
  'compact grid rows without a known hazard are explicitly safe, not undefined');
const move = {destination:{x:4,y:6,z:0}, cost_ft:15};
const quote = {candidate:{candidate_id:'native-route', movement_cost_ft:10,
  canonical_path:[{x:3,y:6,z:0},{x:4,y:6,z:0}], metadata:{hazard_exposure:true,
    expected_opportunity_attacks:[{display_name:'hidden creature'}]}}};
let prompt = '';
assert.equal(confirmRouteQuote(move, quote, message => { prompt = message; return true; }), true);
assert.match(prompt, /Move to \(4, 6\)/);
assert.match(prompt, /Movement cost: 15 ft/);
assert.match(prompt, /Warning: this route crosses a known hazard/);
assert.ok(!prompt.includes('hidden creature'));
// The dialog is plain text in a confirm box: its lines must be real newlines, not
// the two characters backslash and "n" (owner screenshot, 2026-10-22).
assert.ok(!prompt.includes('\\n'), 'the route confirmation must not show a literal backslash-n');
assert.ok(prompt.split('\n').length >= 4, 'route, movement cost and the hazard warning each start a new line');
assert.match(prompt, /^Move to \(4, 6\), height 0 ft\?\nRoute: /);
assert.match(prompt, /\nMovement cost: 15 ft\.\nWarning: this route crosses a known hazard\.$/);

let declined = '';
assert.equal(confirmRouteQuote(move, quote, message => { declined = message; return false; }), false);
assert.equal(declined, prompt);
quote.candidate.metadata.hazard_exposure = false;
assert.equal(confirmRouteQuote(move, quote, message => !message.includes('known hazard')), true);
console.log('desktop deferred movement discloses native route/hazard and honors confirmation');
