// Real action-row renderer and synthetic carded fixture, shared by DOM/browser checks.
// Synthetic replacement for the card fixture introduced in 9facb904ef05afe4b2eecf6cb952f82a20ffa48f.
const fs = require('node:fs');
const path = require('node:path');
const sheet = fs.readFileSync(path.join(__dirname, '../static/tabletop/sheet.js'), 'utf8');
const rules = fs.readFileSync(path.join(__dirname, '../static/tabletop/rules.js'), 'utf8');
function section(start, end, source = sheet) {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length);
  if (from < 0 || to <= from) throw new Error(`Missing source boundary: ${start}`);
  return source.slice(from, to);
}
// Keep presentation checks independent of authority prose/public-export rewrites.
const effects = ['a blue lantern appears;', 'gain a lantern glow;',
  'shed light for 10 feet;',
  'a nearby ally can see the glowing marker.'];
const summary = 'A test lantern glows around the bearer.';
const facts = [['Action', 'Bonus Action'], ['Duration', 'Until the next bell'],
  ['Cost', '7 Resonance']];
const printed = ['Lantern Parade', ...facts.map(([key, value]) => `${key}: ${value}`),
  summary, 'Lantern details:', ...effects].join('\n');
const text = [summary, ...facts.map(([key, value]) => `${key}: ${value}`), ...effects].join('\n');
const player_card = {title: 'Lantern Parade', text, facts,
  html: `<article class="player-card"><h3>Lantern Parade</h3><p>${summary}</p>
    <p class="card-facts">${facts.map(([key, value]) => key === 'Action' ? value : `${key}: ${value}`).join(' · ')}</p>
    <section><h4>Effects</h4><ul>${effects.map(effect => `<li>${effect}</li>`).join('')}</ul></section>
    <details><summary>Rules</summary><pre>${printed}</pre></details></article>`};
const row = {id: 'act:lantern-parade', label: 'Lantern Parade', economy: 'BONUS_ACTION',
  group: 'bonus', combat: {target_kind: 'SELF'}, detail: {cost: '7 Resonance', gm_riders: 3},
  description: text.replace(/\n/g, ' '), hover: {title: 'Lantern Parade', text, player_card}};
const source = [
  `const state = {actor: null, byId: new Map(), textByName: new Map(), textByButton: new Map()};
   const norm = s => String(s).toLowerCase();
   const economyLabel = () => 'Bonus Action', targetLabel = () => 'Self';
   const GROUP_NAMES = {};
   const row = ${JSON.stringify(row)};`,
  section('export function rulesTextFor(', 'export function ruleSummary(', rules).replace('export ', ''),
  section('function h(tag, attrs, ...kids)', 'function icon('),
  section('function hitCell(d)', '// Hover text'),
  section('function plainRules(text)', '// Talents that change another ability'),
].join('\n');
module.exports = {source, row};
if (require.main === module) process.stdout.write(JSON.stringify({source, row}));
