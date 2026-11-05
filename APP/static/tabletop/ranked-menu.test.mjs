import assert from 'node:assert/strict';
import {test} from 'node:test';
import {renderRankedMenu, slotRows} from './ranked-menu.js';
import {setupControlHtml, splitSetupControl} from './seats.js';
import {economySections} from './action-economy.js';

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
  get parentNode() { return this.parent; }
  click() { this.listeners.click(); }
}
test('no-action, free, reaction and move uses retain all choices in their own slots', () => {
  const actions = ['NONE', 'FREE', 'REACTION', 'MOVE'].map(economy => ({economy, label: economy,
    options: Array.from({length: 8}, (_, i) => ({candidate_id: `${economy}${i}`}))}));
  const rows = slotRows({actions});
  const sections = economySections(actions);
  assert.deepEqual(sections.map(([slot]) => slot), ['No action', 'Free', 'Reaction', 'Movement']);
  assert.equal(sections.flatMap(([, groups]) => groups).length, actions.length);
  assert.equal(rows.Action.length, 0);
  for (const slot of ['No action', 'Free', 'Reaction', 'Movement']) assert.equal(rows[slot].length, 8);
  const selected = [];
  const root = renderRankedMenu({actions, ranked_slots: {'No action': ['NONE0']}}, {
    doc: {createElement: tag => new Node(tag)}, onAct: id => selected.push(id), onMove: () => assert.fail('action is not a move route')});
  const section = root.children.find(group => group.children[0].textContent === 'No action');
  section.children[1].children[1].click(); // More reveals every remaining option
  section.children[1].children[7].click();
  assert.deepEqual(selected, ['NONE7']);
});
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
  const {readFileSync} = await import('node:fs');
  const {renderRankedMenu} = await import('./ranked-menu.js');
  const source = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('export function appendActionBarRankedChoice');
  assert.ok(start >= 0);
  const code = source.slice(start).replace(/^export /m, '');
  class Node {
    constructor(tag = 'div') { this.tag = tag; this.children = []; this.parent = null; this.listeners = {}; this.textContent = ''; this.className = ''; this.dataset = {}; }
    appendChild(child) { child.parent = this; this.children.push(child); return child; }
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); }
    click() { (this.listeners.click || []).forEach(fn => fn()); }
    querySelector(sel) {
      if (sel === '.tt-muted') return this._muted || null;
      const walk = node => {
        const out = [];
        for (const child of (node.children || [])) { if (child instanceof Node) { out.push(child); out.push(...walk(child)); } }
        return out;
      };
      return walk(this).find(node => (node.className || '').split(' ').includes(sel.replace(/^\./, ''))) || null;
    }
  }
  const headings = (node) => {
    const out = [];
    if (node && typeof node === 'object') {
      if (node.tag === 'h3') out.push(node.textContent);
      for (const child of node.children || []) out.push(...headings(child));
    }
    return out;
  };
  const hasText = (node, text) => {
    if (!node || typeof node !== 'object') return false;
    if (String(node.textContent || '').includes(text)) return true;
    return (node.children || []).some(child => hasText(child, text));
  };
  const append = new Function('document', 'renderRankedMenu', code + '\nreturn appendActionBarRankedChoice;')(
    { createElement: tag => new Node(tag) }, renderRankedMenu);
  const menu = {ranked_slots: {Movement: ['move'], Action: ['a0','a1','a2','a3','a4'], 'Bonus action': ['b']},
    moves: [{candidate_id: 'move', destination: {x: 2,y: 3}, cost_ft: 10}], actions: [
      {label: 'Strike', economy: 'ACTION', cost_label: 'Action · no CP', options:
        Array.from({length: 8}, (_, i) => ({candidate_id: `a${i}`, label: `target ${i}`}))},
      {label: 'Heal', economy: 'BONUS_ACTION', cost_label: 'Bonus action · 1 CP', options: [{candidate_id: 'b',label: 'yourself'}]},
    ]};
  const makeBar = (turnMode) => {
    const doc = { createElement: tag => new Node(tag) };
    const bar = doc.createElement('div');
    const html = doc.createElement('div');
    html.className = 'tt-ab-groups';
    const showMoves = doc.createElement('button');
    showMoves.textContent = 'Show moves';
    html.appendChild(showMoves);
    const who = doc.createElement('div');
    who.className = 'tt-ab-who';
    const muted = doc.createElement('span');
    muted.className = 'tt-muted';
    who.appendChild(muted);
    who._muted = muted;
    const m = {...menu, turn_mode: turnMode};
    append(bar, m, {doc, html, who});
    return bar;
  };
  const manual = makeBar('Manual');
  assert.ok(hasText(manual, 'Show moves'), 'Manual keeps normal controls');
  assert.ok(!headings(manual).includes('Movement'), 'Manual has no ranked slot group');
  const assisted = makeBar('Assisted');
  assert.ok(headings(assisted).includes('Movement'), 'Assisted has ranked slots');
  assert.ok(headings(assisted).includes('Action'), 'Assisted has ranked Action slot');
});
