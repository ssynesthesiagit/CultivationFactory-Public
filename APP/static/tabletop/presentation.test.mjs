// Node-only client regressions: no browser or GUI is launched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {actionTipCard, rulesTextFor, uniqueRuleBlocks} from './rules.js';
const read = name => readFileSync(new URL(name, import.meta.url), 'utf8');
const {layoutText} = await import(`data:text/javascript,${encodeURIComponent(read('./presentation.js'))}`);
const table = read('./tabletop.js'), sheet = read('./sheet.js');
const between = (source, start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const cleanRules = text => String(text || '');

test('floating action card retains unlabelled action body', () => {
  const row = {label: 'Hidden Strike', description: 'Sneak past a guard without being seen.',
    hover: {title: 'Hidden Strike', fields: [], text: 'Hidden Strike\nSneak past a guard without being seen.'}};
  const node = tag => ({tag, children: [], textContent: '', setAttribute() {}, append(...xs) {this.children.push(...xs);}, appendChild(x) {this.children.push(x);}});
  const document = {createElement: node, createTextNode: text => text};
  const text = rulesTextFor(null, row);
  const card = actionTipCard(row)(document);
  const words = node => typeof node === 'string' ? node : node.children.map(words).join(' ');
  assert.match(words(card), /Sneak past a guard without being seen/);
  // Exercise the exact Other action title/card expressions as well.
  assert.ok(table.includes('title: layoutText(row.hover) || cleanRules(row.description) || row.label'));
  assert.ok(table.includes('tipCard: actionTipCard(row, {rules: layoutText(row.hover) || cleanRules(row.description) || ""})'));
  assert.match(layoutText(row.hover) || row.description, /Sneak past a guard/);
  assert.equal(rulesTextFor({library: {groups: []}}, row), text);
  assert.equal(rulesTextFor({library: {groups: [{entries: [{name: row.label, text: 'Complete library rules.'}]}]}},
    {...row, description: '', hover: {title: row.label, text: row.label}}), 'Complete library rules.');
});

test('pop-out sheet description and library index consume the shared layout', () => {
  const state = {};
  const plainRules = cleanRules, norm = x => String(x).toLowerCase();
  const funcs = new Function('layoutText', 'state', 'plainRules', 'norm', 'uniqueRuleBlocks', `${between(sheet, 'function indexLibraryText(', '\nfunction plainRules(')}\n${between(sheet, 'function describe(', '\n// Not a GM process:')}; return {indexLibraryText, describe};`)(layoutText, state, plainRules, norm, uniqueRuleBlocks);
  const hover = {text: 'Path technique\nEffect: Protect an ally.\nOnce per turn: available again next turn.'};
  funcs.indexLibraryText({groups: [{entries: [{name: 'Path technique', button_id: 'path', text: 'old flat text', hover}]}]});
  assert.equal(state.textByButton.get('path'), hover.text);
  assert.equal(funcs.describe({id: 'path', label: 'Path technique', description: 'old flat text', hover}), hover.text);
  assert.ok(sheet.includes('rulesText(layoutText(item.hover) || item.text || item.summary, query)'));
});

test('older payloads and missing hovers still have a complete fallback', () => {
  assert.equal(layoutText(null), '');
  assert.equal(layoutText({title: 'Action', text: 'Action'}), '');
  assert.equal(layoutText({title: 'Action', fields: [{label: 'Cost', value: '1 Stamina'}], body: ['Protect an ally.'], footer: 'Until next turn.'}),
    'Action\nCost: 1 Stamina\nProtect an ally.\nUntil next turn.');
});
