// Real service quote -> compact inspection -> desktop and phone warning.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Element} from './objects_dom_stub.mjs';
import {expandMovementGrid} from '../static/tabletop/movement-grid.js';
import {checkMove} from '../static/tabletop/assisted-menu.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';
import {optionText} from '../static/play/play-model.js';

const {state, quote, native} = JSON.parse(readFileSync(0, 'utf8'));
const desktop = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
globalThis.window = {confirm: () => { throw new Error('movement must not ask for confirmation'); }};
const start = desktop.indexOf('async function renderActionBar(');
assert.ok(start >= 0);
assert.doesNotThrow(() => new Function(desktop.slice(start, desktop.indexOf('\n}', start) + 2)),
  'The real desktop handler must compile before it can show any choices');
const text = n => [n.textContent, ...(n.children || []).map(text)].join(' ');
const original = expandMovementGrid(state.menu).moves.find(m =>
  m.destination.x === 4 && m.destination.y === 6 && !m.destination.z && m.movement_mode === 'walk');
assert.ok(original);
assert.equal(original.hazard_exposure, false);
assert.doesNotMatch(desktop, /confirmRouteQuote|window?\.confirm\(/,
  'real desktop deferred-route commits must not show a confirmation popup');
const view = {visible: () => true};
assert.match(optionText(native, state, view), /Warning: this route crosses a known hazard/);

for (const hazard of [true, false]) {
  const move = structuredClone(original);
  const reply = structuredClone(quote);
  reply.candidate.metadata.hazard_exposure = hazard;
  reply.candidate.metadata.expected_opportunity_attacks = [{actor_id:'secret', display_name:'Hidden spy'}];
  const menu = {...state.menu, actions:[], moves:[move], ranked_slots:{Movement:[move.candidate_id]}};
  const submissions = [];
  const root = renderRankedMenu(menu, {doc:{createElement:tag => new Element(tag)},
    onMove: m => submissions.push(m), onPreviewMove: m => checkMove(menu, m, async () => reply, () => true)});
  const button = root.querySelectorAll('button')[0];
  await button.click();
  assert.equal(submissions.length, 0, 'The first click displays the existing route preview');
  assert.ok(text(button).includes('Confirm'));
  assert.equal(move.hazard_exposure, hazard);
  assert.equal(/Warning: this route crosses a known hazard/.test(text(button)), hazard);
  assert.equal(/Warning: this route crosses a known hazard/.test(button.dataset.tip), hazard);
  assert.equal(/Warning: this route crosses a known hazard/.test(optionText(move, state, view)), hazard);
  assert.deepEqual(move.path, quote.candidate.canonical_path);
  assert.equal(move.cost_ft, native.cost_ft);
  assert.equal(move.expected_opportunity_attacks, undefined, 'Only player-facing movement fields are projected');
  assert.ok(!text(root).includes('Hidden spy'));
  // A later safe quote must clear a previously checked hazard, not retain it.
  const safe = structuredClone(reply); delete safe.candidate.metadata.hazard_exposure;
  const copy = {...move};
  await checkMove(menu, copy, async () => safe, () => true);
  assert.equal(copy.hazard_exposure, false);
  const stale = {...original};
  assert.equal(await checkMove(menu, stale, async () => reply, () => false), null);
  assert.equal(stale.hazard_exposure, false);
  await button.click();
  assert.equal(submissions.length, 1);
}
console.log('native hazard quote disclosed in the move preview; safe/stale/privacy controls passed');
