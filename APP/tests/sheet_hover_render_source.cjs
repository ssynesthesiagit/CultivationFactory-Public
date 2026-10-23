// Real action-row renderer and owner-backed fixture, shared by DOM/browser checks.
const fs = require('node:fs');
const path = require('node:path');
const sheet = fs.readFileSync(path.join(__dirname, '../static/tabletop/sheet.js'), 'utf8');
function section(start, end) {
  const from = sheet.indexOf(start), to = sheet.indexOf(end, from + start.length);
  if (from < 0 || to <= from) throw new Error(`Missing source boundary: ${start}`);
  return sheet.slice(from, to);
}
const rules = JSON.parse(fs.readFileSync(path.join(__dirname, '../authority/typed_mechanics/rules_text.json')));
const text = rules['tianxia.talent.chains.chain_armor'].replace(/^### /, '')
  .replace('Action Type:', 'Action:').replace('Cost: 3 CP', 'Cost: 3 Resonance (your Path resource)');
const row = {id: 'act:chain-armor', label: 'Chain Armor', economy: 'BONUS_ACTION',
  group: 'bonus', combat: {target_kind: 'SELF'}, detail: {cost: '3 Resonance', gm_riders: 3},
  description: text.replace(/\n/g, ' '), hover: {title: 'Chain Armor', text}};
const source = [
  `const state = {actor: null, byId: new Map(), textByName: new Map(), textByButton: new Map()};
   const norm = s => String(s).toLowerCase();
   const economyLabel = () => 'Bonus Action', targetLabel = () => 'Self';
   const GROUP_NAMES = {};
   const row = ${JSON.stringify(row)};`,
  section('function h(tag, attrs, ...kids)', 'function icon('),
  section('function hitCell(d)', '// Hover text'),
  section('function plainRules(text)', '// Talents that change another ability'),
].join('\n');
module.exports = {source, row};
if (require.main === module) process.stdout.write(JSON.stringify({source, row}));
