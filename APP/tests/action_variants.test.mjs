import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {attackSource, groupAttackRows, groupVariantRows, renderVariantGroups} from '../static/tabletop/attack-groups.js';
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

test('each choice is tagged with its executable id (browser opt-in locator contract, no Chromium)', () => {
  const nodes = renderVariantGroups(doc, rows, row => {
    const b = new FakeElement('button'); b.textContent = row.label; return b;
  });
  const tagged = nodes[0].querySelectorAll('button').map(b => b.dataset.variantChoice);
  assert.deepEqual(tagged, rows.map(r => r.source_definition_id));
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

test('legacy weapon grouping ignores action_id: only the variant path reads it', () => {
  // A weapon row with no combat/source/id must not gain a source from a stray action_id (shared ATTACKS grouping).
  assert.equal(attackSource({label: 'Dagger attack', action_id: 'legacy.dagger'}), '');
  assert.equal(attackSource({label: 'Sword attack', id: 'act:weapon.sword', action_id: 'other.key'}), 'weapon.sword');
  const weapon = {label: 'Sword attack', id: 'act:weapon.sword', group: 'attacks', kind: 'action'};
  const groups = groupAttackRows([weapon, {...weapon, label: 'Sword attack (copy 2)', id: 'act:weapon.sword'}, {label: 'Dagger attack', action_id: 'legacy.dagger', group: 'attacks'}]);
  assert.equal(groups.length, 2, 'the sword copies merge; the sourceless dagger row stays its own group');
  assert.ok(groups.every(g => !g.rows?.some?.(r => r.action_id === 'legacy.dagger') || g.rows.length === 1));
});

test('variant grouping still reads action_id for prefight options', () => {
  const base = {base_key: 'action:x', base_label: 'X', choices: []};
  const groups = groupVariantRows([{action_id: 'action:x.a', label: 'A', variant: base}, {action_id: 'action:x', label: 'base'}]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].rows.length, 2);
});

test('a singleton pre-fight buff keeps its ability name outside a family heading', () => {
  // Meld: Feed on Darkness without Persistent Meld: no choices, so no family heading. The row must name the ability,
  // not show the choice label "Standard".
  const feed = {action_id: 'action:meld.feed_on_darkness', name: 'Meld: Feed on Darkness', meld: 'feed_on_darkness', concentration: false,
    costs: [['resource:core.qi', 2]], duration: 'up to 1 hour', description: 'Feed on darkness.',
    variant: {base_key: 'action:meld.feed_on_darkness', base_label: 'Meld: Feed on Darkness', choices: []}};
  const nodes = renderVariantGroups(doc, [feed], option => createPrefightRow(option, '2 Qi', doc).row);
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].tagName, 'LABEL', 'no family card for a singleton');
  assert.equal(nodes[0].querySelectorAll('span')[0].textContent, 'Meld: Feed on Darkness · 2 Qi · up to 1 hour');
  assert.ok(!nodes[0].textContent.includes('Standard'));
});

test('a family chip in pre-fight keeps its choice label under the family heading', () => {
  const base = {base_key: 'action:meld.darkvision', base_label: 'Meld: Darkvision'};
  const rows = [
    {action_id: 'action:meld.darkvision.short', name: 'Meld: Darkvision', costs: [['resource:core.qi', 2]], duration: 'up to 1 hour', concentration: false,
      variant: {...base, choices: [{axis: 'duration', key: 'short', label: 'Short', costs: []}]}},
    {action_id: 'action:meld.darkvision.long', name: 'Meld: Darkvision', costs: [['resource:core.qi', 2]], duration: 'up to 8 hours', concentration: false,
      variant: {...base, choices: [{axis: 'duration', key: 'long', label: 'Long', costs: []}]}},
  ];
  const nodes = renderVariantGroups(doc, rows, option => createPrefightRow(option, '2 Qi', doc).row);
  assert.equal(nodes.length, 1);
  const chips = nodes[0].querySelectorAll('label').map(label => label.querySelectorAll('span')[0].textContent);
  assert.deepEqual(chips, ['Short · 2 Qi · up to 1 hour', 'Long · 2 Qi · up to 8 hours']);
});

test('F5R: a one-row, no-choice family (plain Protection) is a direct button, not a closed card', () => {
  // Protection without persistence: the family has one row and an empty choices list. Before this fix it was wrapped in a
  // <details> the player had to open, then labelled "Standard". It must render as the original button, with the original
  // label and handler row, exactly as before the variant cards existed.
  const protection = {source_definition_id: 'action:protection.aegis', label: 'Protection: Aegis (Protection)', economy: 'ACTION',
    variant: {base_key: 'action:protection', base_label: 'Protection', choices: []}};
  const clicked = [];
  const nodes = renderVariantGroups(doc, [protection], (row, action = row) => {
    const b = new FakeElement('button'); b.textContent = row.label;
    b.addEventListener('click', () => clicked.push(action.source_definition_id)); return b;
  });
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].tagName, 'BUTTON', 'a single no-choice row is a plain button, not a card');
  assert.equal(nodes[0].textContent, 'Protection: Aegis (Protection)');
  nodes[0].listeners.click();
  assert.deepEqual(clicked, ['action:protection.aegis']);
});

test('F5R: a one-row family that does have a choice keeps its card', () => {
  const persistentOnly = {source_definition_id: 'action:x.p', label: 'X (Persistent)', economy: 'ACTION',
    variant: {base_key: 'action:x', base_label: 'X', choices: [{axis: 'duration', key: 'p', label: 'Persistent', costs: []}]}};
  const nodes = renderVariantGroups(doc, [persistentOnly], row => new FakeElement('button'));
  assert.equal(nodes[0].tagName, 'DETAILS');
  assert.equal(nodes[0].querySelector('summary').textContent, 'X');
});
