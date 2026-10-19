import assert from 'node:assert/strict';
import {test} from 'node:test';
import {renderRankedMenu, slotRows} from './ranked-menu.js';
import {setupControlHtml, splitSetupControl} from './seats.js';

const menu = {ranked_slots: {Movement: ['move'], Action: ['a0','a1','a2','a3','a4'], 'Bonus action': ['b']},
  moves: [{candidate_id: 'move', destination: {x: 2,y: 3}, cost_ft: 10}], actions: [
    {label: 'Strike', economy: 'ACTION', cost_label: 'Action · no CP', options:
      Array.from({length: 8}, (_, i) => ({candidate_id: `a${i}`, label: `target ${i}`}))},
    {label: 'Heal', economy: 'BONUS_ACTION', cost_label: 'Bonus action · 1 CP', options: [{candidate_id: 'b',label: 'yourself'}]},
  ]};
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {}; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  remove() { this.parent.children = this.parent.children.filter(c => c !== this); }
  click() { this.listeners.click(); }
}
test('three slots have top five with More preserving every candidate and exact click ids', () => {
  const acts = [], moves = [];
  const root = renderRankedMenu(menu, {doc: {createElement: tag => new Node(tag)},
    onAct: id => acts.push(id), onMove: move => moves.push(move.candidate_id)});
  assert.deepEqual(root.children.map(group => group.children[0].textContent), ['Movement','Action','Bonus action']);
  const actions = root.children[1].children[1];
  assert.equal(actions.children.length, 6); // five options and More
  actions.children[0].click();
  actions.children[5].click();
  assert.equal(actions.children.length, 8);
  actions.children[7].click();
  root.children[0].children[1].children[0].click();
  assert.deepEqual(acts, ['a0','a7']); assert.deepEqual(moves, ['move']);
  assert.equal(slotRows(menu)['Bonus action'][0].detail, 'yourself · Bonus action · 1 CP');
});
test('Assisted maps to existing player-owned SUGGESTED mode', () => {
  assert.match(setupControlHtml([]), /SUGGESTED.*Assisted/);
  assert.deepEqual(splitSetupControl('SUGGESTED'), {mode:'SUGGESTED',provider:null});
});

test('same square movement shows height, route mode and exact movement cost', () => {
  const rows = slotRows({moves: [
    {candidate_id: 'ground', destination: {x: 2, y: 3, z: 0}, cost_ft: 5},
    {candidate_id: 'air', destination: {x: 2, y: 3, z: 2}, movement_mode: 'fly', cost_ft: 15},
    {candidate_id: 'climb', destination: {x: 2, y: 3, z: 2}, movement_mode: 'climb', cost_ft: 20},
  ]}).Movement;
  assert.equal(new Set(rows.map(row => row.label)).size, 3);
  assert.match(rows[0].label, /height 0 ft/);
  assert.match(rows[1].label, /Fly.*height 10 ft/);
  assert.match(rows[2].label, /Climb.*height 10 ft/);
  assert.match(rows[1].detail, /Costs 15 ft of movement/);
  assert.match(rows[2].detail, /Costs 20 ft of movement.*includes climbing/);
});

test('Manual turns keep the normal action bar; ranked slots replace it only in Assisted turns (owner 2026-10-13)', async () => {
  const {readFile} = await import('node:fs/promises');
  const src = await readFile(new URL('./tabletop.js', import.meta.url), 'utf8');
  assert.match(src, /if \(menu\.ranked_slots && menu\.turn_mode === "Assisted"\) \{/);
});
