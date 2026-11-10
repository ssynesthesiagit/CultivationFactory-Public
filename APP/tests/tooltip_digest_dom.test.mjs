// SOL192: reviewed card HTML and live button context through the shipped renderer.
import test from 'node:test';
import assert from 'node:assert/strict';
import {actionCardModel, actionTipCard, renderTipCard} from '../static/tabletop/rules.js';
import {bindTipTargets, createHoverCard} from '../static/tabletop/hovercard.js';
import {glossaryDefinitions} from '../static/tabletop/newcomer.js';
import TianxiaSheetViewModel from '../static/sheet_view_model.js';

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.style = {};
    this.className = ''; this.listeners = {}; this.hidden = false; this.innerHTML = '';
    this.classList = {add: c => { if (!this.className.split(' ').includes(c)) this.className = `${this.className} ${c}`.trim(); },
      remove: c => { this.className = this.className.split(' ').filter(x => x !== c).join(' '); }}; }
  get nodeType() { return 1; }
  append(...kids) { for (const kid of kids) { if (typeof kid === 'object') kid.parentElement = this; this.children.push(kid); } }
  prepend(kid) { kid.parentElement = this; this.children.unshift(kid); }
  appendChild(kid) { this.append(kid); return kid; }
  replaceChildren(...kids) { this.children = []; this.innerHTML = ''; this.append(...kids); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  hasAttribute(k) { return k in this.attributes; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  removeEventListener() {}
  set textContent(v) { this.innerHTML = ''; this.children = [String(v)]; }
  get textContent() { return this.children.map(k => typeof k === 'object' ? k.textContent : k).join('') + this.innerHTML.replace(/<[^>]*>/g, ''); }
  matches(s) { return s === '[data-tip]' ? 'tip' in this.dataset : false; }
  closest(s) { return this.matches(s) ? this : this.parentElement?.closest?.(s) || null; }
  contains(k) { return k === this || this.children.some(c => typeof c === 'object' && c.contains(k)); }
  querySelectorAll(s) { return this.children.filter(k => typeof k === 'object').flatMap(k => [...(k.matches(s) ? [k] : []), ...k.querySelectorAll(s)]); }
  getBoundingClientRect() { return {left: 10, top: 10, right: 200, bottom: 40, width: 190, height: 30}; }
}
const doc = {createElement: tag => new Node(tag), createTextNode: text => String(text)};
const visible = node => typeof node !== 'object' ? node
  : node.tagName === 'details' && !node.hasAttribute('open')
    ? visible(node.children.find(k => k.tagName === 'summary'))
    : node.children.map(visible).join('') + node.innerHTML.split('<details>')[0].replace(/<[^>]*>/g, '');

// Synthetic server projection; Python tests feed real records through this same path.
const challengeCard = {
  record_id: 'GUARDIAN_BASE_CHALLENGE_PRACTICE',
  facts: [['Action', 'Bonus Action'], ['Range', '60 feet'], ['Duration', '1 minute']],
  text: 'Target: One creature that can perceive your challenge. Failed save: The creature becomes Challenged by you for the duration.',
  html: '<article class="player-card"><h3>Challenge</h3><p>Target: One creature that can perceive your challenge.</p>'
    + '<p>Failed save: The creature becomes Challenged by you for the duration.</p>'
    + '<p>While a creature is Challenged by you: it has Disadvantage on attack rolls that do not include you as a target.</p>'
    + '<abbr title="Martial Focus is one available use">Martial Focus</abbr>'
    + '<details><summary>Rules</summary><pre>Issue a challenge ... You cultivate the art.</pre></details></article>'
};
const fullChallenge = 'Challenge Practice\nYou cultivate the art.\nIssue a challenge ...';
const swift = {label: 'Challenge (Swift Guardian: no action; spend Martial Focus, your readiness point)', economy: 'NONE',
  detail: {cost: '1 Martial Focus', range: '65 ft', save: 'Charisma save, DC 15'}, hover: {player_card: challengeCard}};

test('live button values accompany the reviewed facts and outcomes', () => {
  const model = actionCardModel(swift, {rules: fullChallenge});
  assert.match(model.context, /Action: No action/);
  assert.match(model.context, /Cost: 1 Martial Focus/);
  assert.match(model.context, /Save DC: 15/);
  assert.doesNotMatch(model.context, /Save: Charisma/);
  assert.match(model.context, /Range: 65 ft/);
  assert.match(model.player_card.html, /One creature that can perceive your challenge/);
  assert.deepEqual(Object.fromEntries(model.player_card.facts).Duration, '1 minute');
  assert.match(model.player_card.html, /Failed save: The creature becomes Challenged/);
  assert.match(model.player_card.html, /<details><summary>Rules<\/summary>/);
});

test('rendered card: visible text, complete rules once behind the expander, no raw markdown', () => {
  const card = actionTipCard(swift, {rules: fullChallenge})(doc, {terms: glossaryDefinitions('1 Martial Focus', false)});
  const text = visible(card);
  assert.match(text, /Failed save: The creature becomes Challenged/);
  assert.match(text, /While a creature is Challenged by you:/);
  assert.match(card.innerHTML, /<details><summary>Rules<\/summary>/);
  assert.doesNotMatch(text, /You cultivate the art/);
  assert.doesNotMatch(text, /^\s*#/m);
  assert.match(text, /Martial Focus/);
  assert.equal(card.innerHTML.split('Martial Focus is one available use').length - 1, 1);
  const full = card.innerHTML.split('<details>')[1];
  assert.ok(full.startsWith('<summary>Rules</summary>'));
  assert.equal(full.split('Issue a challenge').length - 1, 1);
  assert.doesNotMatch(full, /#/);
});

test('a changed rule shows current unreviewed text, never a stale summary', () => {
  const current = {...challengeCard, facts: [], text: 'The current range is 35 feet.',
    html: '<article class="player-card"><p>The current range is 35 feet.</p><details><summary>Rules</summary><pre>Range: 35 feet</pre></details></article>'};
  const model = actionCardModel({...swift, hover: {player_card: current}}, {rules: 'Range: 35 feet'});
  assert.deepEqual(model.player_card.facts, []);
  assert.match(model.player_card.text, /35 feet/);
  assert.doesNotMatch(model.player_card.text, /60 feet/);
  const rendered = renderTipCard(doc, model);
  assert.match(visible(rendered), /35 feet/);
  assert.doesNotMatch(visible(rendered), /60 feet/);
  assert.match(rendered.innerHTML, /<details><summary>Rules<\/summary>/);
});

test('no printed record: full rules stay open alongside live button facts', () => {
  const row = {label: 'Guard', economy: 'BONUS_ACTION', detail: {cost: '2 Qi', range: '5 feet'}};
  const model = actionCardModel(row, {rules: 'Guard\nAction Type: Bonus Action\nRange: 15 feet\nGain +2 AC.'});
  const facts = Object.fromEntries(model.facts);
  assert.equal(facts.Action, 'Bonus Action');
  assert.equal(facts.Range, '5 feet');
  assert.equal(facts.Cost, '2 Qi');
  assert.equal(model.title, 'Guard');
  assert.equal(model.full.open, true);
  assert.match(model.full.text, /Gain \+2 AC/);
});

test('reaction cards keep their trigger and reaction help accessible', () => {
  const reaction = {...challengeCard, facts: [['Action', 'Reaction']],
    html: '<article class="player-card"><p>Trigger: A creature bearing your Beauty Mark targets you with an attack.</p><p>Failed save: The triggering attack has Disadvantage.</p></article>'};
  const model = actionCardModel({label: 'Turn the Blade Aside', economy: 'REACTION', detail: {},
    hover: {player_card: reaction}}, {rules: 'x'});
  assert.deepEqual(model.player_card.facts[0], ['Action', 'Reaction']);
  assert.match(model.player_card.html, /Trigger: A creature bearing your Beauty Mark/);
  const card = renderTipCard(doc, model);
  assert.match(visible(card), /Reactions happen when their trigger occurs/);
  assert.match(card.textContent, /With Ask me, choose Use or Pass/);
});

test('the shared card builds the structured card; data-tip stays the plain text key', () => {
  const host = new Node('div'); host.createElement = doc.createElement; host.createTextNode = doc.createTextNode;
  const card = createHoverCard({doc: {...doc, body: new Node('body')}, win: {innerWidth: 1280, innerHeight: 860}, setTimer: () => 1, clearTimer() {}});
  bindTipTargets(card, host, {setTimer: fn => { fn(); return 1; }, clearTimer() {}, glossary: text => glossaryDefinitions(text, false)});
  const button = new Node('button'); button.dataset.tip = 'Challenge plain text'; button.tipCard = actionTipCard(swift, {rules: fullChallenge});
  host.append(button);
  for (const fn of host.listeners.focusin) fn({target: button});
  assert.equal(card.isOpen, true);
  assert.match(card.node.className, /tt-tipcard/);
  assert.match(visible(card.node), /Failed save: The creature becomes Challenged/);
  assert.equal(button.dataset.tip, 'Challenge plain text');
});

test('Armor Class card: one equation first, the full calculation under an expander', () => {
  const breakdown = {effective_value: 12, formula_trace: {root: {op: 'add', value: 12, terms: [{op: 'constant', value: 10}, {op: 'ability_modifier', ability: 'DEX', value: 2}]}},
    combat_terms: [{source: 'unarmored calculation', value: 12}], conditional_note: 'Qi Armor: +3 AC while it is active.'};
  const model = TianxiaSheetViewModel.armorCard(breakdown, {armor_class: 17, armor_base: 12, armor_modifiers: [{source: 'Shield spell', value: 5}]});
  assert.equal(model.headline, 'AC 17 = 10 + 2 Dex + 5 Shield spell (this fight).');
  assert.equal(model.lines[0], 'Only sometimes: Qi Armor: +3 AC while it is active.');
  const text = visible(renderTipCard(doc, model));
  assert.match(text, /Full calculation/);
  assert.doesNotMatch(text, /Use one base calculation/);
  assert.match(model.full.text, /Use one base calculation/);
  const sheetOnly = TianxiaSheetViewModel.armorCard(breakdown, null);
  assert.equal(sheetOnly.headline, 'AC 12 = 10 + 2 Dex.');
  const unexplained = TianxiaSheetViewModel.armorCard(breakdown, {armor_class: 19, armor_modifiers: [{source: 'Shield spell', value: 5}]});
  assert.equal(unexplained.headline, 'AC 19 = 10 + 2 Dex + 5 Shield spell (this fight) + 2 other active defenses.');
});

test('reviewed Starbolt card keeps live range and no misleading save chip', () => {
  const card = {facts: [['Action', 'Action'], ['Range', '90 feet']], html: '<article>Target: One creature or object you can target.<details><summary>Rules</summary>Range: 90 feet</details></article>'};
  const model = actionCardModel({label: 'Starbolt (Aligned: marked target, +30 ft)', economy: 'ACTION',
    detail: {range: '120 ft', cost: '0 CP', to_hit: '+7', save: 'Wisdom save, DC 15'}, hover: {player_card: card}}, {rules: 'Starbolt'});
  const facts = Object.fromEntries(model.player_card.facts);
  assert.match(model.context, /Range: 120 ft/);
  assert.match(model.context, /Cost: 0 CP/);
  assert.match(model.player_card.html, /Target: One creature or object you can target/);
  assert.equal(facts.Save, undefined); assert.equal(facts.Attack, undefined);
  assert.match(model.context, /Save DC: 15/);
  assert.match(model.player_card.html, /<details><summary>Rules<\/summary>/);
});
