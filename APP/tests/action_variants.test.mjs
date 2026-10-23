import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {groupVariantRows, renderVariantGroups} from '../static/tabletop/attack-groups.js';
import {FakeElement} from './attacklist1_dom.mjs';
import {renderActions} from '../static/play/play-ui.js';

const doc = {createElement: tag => new FakeElement(tag)};
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
  renderActions(host, {actions: rows}, null, {choose: g => picked.push(g.source_definition_id)});
  assert.equal(host.querySelectorAll('summary').filter(n => n.textContent === 'Meld: Darkvision').length, 1);
  for (const b of host.querySelectorAll('button')) b.listeners.click();
  assert.deepEqual(picked, rows.map(r => r.source_definition_id));
});

test('sheet and table bar use the same structured renderer as /play', () => {
  for (const file of ['sheet.js', 'tabletop.js']) {
    const source = fs.readFileSync(new URL('../static/tabletop/' + file, import.meta.url), 'utf8');
    assert.match(source, /renderVariantGroups\(document,/);
    assert.match(source, /attack-groups\.js\?v=variants1/);
  }
});
