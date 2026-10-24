import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {groupVariantRows, renderVariantGroups} from '../static/tabletop/attack-groups.js';
import {FakeElement} from './attacklist1_dom.mjs';
import {renderActions} from '../static/play/play-ui.js';
import {createPrefightRow} from '../static/tabletop/prefight_row.js';
import {actionCardModel, actionHoverText} from '../static/tabletop/rules.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';

class Element extends FakeElement { get parentNode() { return this.parent; } }
const doc = {createElement: tag => new Element(tag), createTextNode: text => String(text)};
const base = 'action:test.darkvision';
const rows = [[], ['Persistent — no Concentration'], ['Stronger — 120-foot Darkvision'], ['Persistent — no Concentration', 'Stronger — 120-foot Darkvision']].map((labels, i) => ({
  source_definition_id: base + '.' + i, label: 'opaque unrelated label ' + i, options: [{candidate_id: 'candidate-' + i}],
  cost_label: [0, 2, 2, 4][i] + ' Qi',
  variant: {base_key: base, base_label: 'Meld: Darkvision', choices: labels.map((label, n) => ({axis: ['duration', 'strength'][n], key: String(n), label, costs: [['resource:core.qi', 2]]}))},
}));

test('one family, four independently executable choices; names are not parsed', () => {
  const clicked = [];
  const nodes = renderVariantGroups(doc, rows, row => {
    const b = new FakeElement('button'); b.textContent = row.label + ' · ' + row.cost_label;
    b.addEventListener('click', () => clicked.push(row.source_definition_id)); return b;
  });
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].querySelector('summary').textContent, 'Meld: Darkvision');
  assert.match(nodes[0].textContent, /Persistent.*2 Qi/);
  assert.match(nodes[0].textContent, /Stronger.*4 Qi/);
  for (const b of nodes[0].querySelectorAll('button')) b.listeners.click();
  assert.deepEqual(clicked, rows.map(r => r.source_definition_id));
  assert.equal(rows[0].label, 'opaque unrelated label 0');
});

test('legal children remain reachable without an affordable or owned base row', () => {
  const only = {...rows[3], label: 'no parsing possible'};
  assert.equal(groupVariantRows([only])[0].rows[0], only);
  const untyped = {source_definition_id: base, label: 'Darkvision base'};
  assert.equal(groupVariantRows([only, untyped]).length, 1);
  assert.equal(groupVariantRows([{label:'look-alike'}, {label:'look-alike'}]).length, 2);
});

test('/play uses the same nesting and each original choice remains executable', () => {
  const host = new FakeElement('div'); host.ownerDocument = doc;
  const picked = [];
  renderActions(host, {actions: rows}, null, {choose: g => { assert.ok(rows.includes(g)); picked.push(g.source_definition_id); }});
  assert.equal(host.querySelectorAll('summary').filter(n => n.textContent === 'Meld: Darkvision').length, 1);
  for (const b of host.querySelectorAll('button')) b.listeners.click();
  assert.deepEqual(picked, rows.map(r => r.source_definition_id));
});

test('owner screenshot: one pre-fight Meld family with four real checkboxes and correct Qi costs', () => {
  const options = rows.map(row => ({...row, action_id: row.source_definition_id, name: row.label, duration: 'up to 1 hour'}));
  const nodes = renderVariantGroups(doc, options, row => createPrefightRow(row, row.cost_label, doc).row);
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].querySelector('summary').textContent, 'Meld: Darkvision');
  assert.equal(nodes[0].querySelectorAll('input').length, 4);
  assert.match(nodes[0].textContent, /Persistent.*2 Qi/);
  assert.match(nodes[0].textContent, /Stronger.*4 Qi/);
  assert.ok(!nodes[0].textContent.includes('(2 CP)'));
});

test('tooltips name the ability and actual choices, not legacy CP suffixes', () => {
  const row = {...rows[3], label: 'Meld: Darkvision (Persistent) (2 CP)', detail: {cost: '4 Qi'}, economy: 'ACTION'};
  const model = actionCardModel(row, {rules: 'Touch one creature. Lasts up to 1 hour.'});
  assert.match(model.title, /Meld: Darkvision.*Persistent.*Stronger/);
  assert.ok(!model.title.includes('(2 CP)'));
  const hover = actionHoverText(row, {rules: 'Touch one creature. Lasts up to 1 hour.'});
  assert.match(hover, /4 Qi/);
  assert.ok(!hover.includes('(2 CP)'));
});

test('Assisted More keeps one family and exposes every candidate, not just the top five', async () => {
  const actions = rows.map((row, i) => ({...row, economy: 'ACTION',
    options: [0, 1].map(n => ({candidate_id: i + '-' + n, label: 'Target ' + n}))}));
  actions[0] = {...actions[0], variant: undefined, source_definition_id: base, label: 'Meld: Darkvision'};
  const ids = actions.flatMap(row => row.options.map(o => o.candidate_id));
  const picked = [];
  const root = renderRankedMenu({actions, ranked_slots: {Action: ids.slice(0, 5)}},
    {doc, onAct: id => picked.push(id)});
  const more = root.querySelectorAll('button').find(b => b.textContent.startsWith('More'));
  assert.ok(more);
  await more.listeners.click();
  assert.equal(root.querySelectorAll('summary').filter(n => n.textContent === 'Meld: Darkvision').length, 1);
  for (const b of root.querySelectorAll('button')) await b.listeners.click();
  assert.deepEqual(picked, ids);
});

test('sheet and table bar use the same structured renderer as /play', () => {
  for (const file of ['sheet.js', 'tabletop.js']) {
    const source = fs.readFileSync(new URL('../static/tabletop/' + file, import.meta.url), 'utf8');
    assert.match(source, /renderVariantGroups\(document,/);
    assert.match(source, /attack-groups\.js\?v=variants1/);
  }
});
