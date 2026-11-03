// SOL192: the compact ability / Armor Class card, from the server digest and the button's live values.
// Run: node --test APP/tests/tooltip_digest_dom.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {actionCardModel, actionTipCard, renderTipCard} from '../static/tabletop/rules.js';
import {bindTipTargets, createHoverCard} from '../static/tabletop/hovercard.js';
import {glossaryDefinitions} from '../static/tabletop/newcomer.js';
import TianxiaSheetViewModel from '../static/sheet_view_model.js';

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.style = {};
    this.className = ''; this.listeners = {}; this.hidden = false;
    this.classList = {add: c => { if (!this.className.split(' ').includes(c)) this.className = `${this.className} ${c}`.trim(); },
      remove: c => { this.className = this.className.split(' ').filter(x => x !== c).join(' '); }}; }
  get nodeType() { return 1; }
  append(...kids) { for (const kid of kids) { if (typeof kid === 'object') kid.parentElement = this; this.children.push(kid); } }
  appendChild(kid) { this.append(kid); return kid; }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  hasAttribute(k) { return k in this.attributes; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  removeEventListener() {}
  set textContent(v) { this.children = [String(v)]; }
  get textContent() { return this.children.map(k => typeof k === 'object' ? k.textContent : k).join(''); }
  matches(s) { return s === '[data-tip]' ? 'tip' in this.dataset : false; }
  closest(s) { return this.matches(s) ? this : this.parentElement?.closest?.(s) || null; }
  contains(k) { return k === this || this.children.some(c => typeof c === 'object' && c.contains(k)); }
  querySelectorAll(s) { return this.children.filter(k => typeof k === 'object').flatMap(k => [...(k.matches(s) ? [k] : []), ...k.querySelectorAll(s)]); }
  all(cls) { return this.children.filter(k => typeof k === 'object').flatMap(k => [...(String(k.className).split(' ').includes(cls) ? [k] : []), ...k.all(cls)]); }
  getBoundingClientRect() { return {left: 10, top: 10, right: 200, bottom: 40, width: 190, height: 30}; }
}
const doc = {createElement: tag => new Node(tag), createTextNode: text => String(text)};
// Visible text: a closed <details> shows only its summary.
const visible = node => typeof node !== 'object' ? node
  : node.tagName === 'details' && !node.hasAttribute('open')
    ? visible(node.children.find(k => k.tagName === 'summary'))
    : node.children.map(visible).join('');

// SYNTHETIC compact digest shaped like the generator's output (words from GUARDIAN_BASE_CHALLENGE_PRACTICE
// "Challenge"). It exercises the compact-card branch only: the real served digest for Challenge is now
// {status: "open"} (SOL192r5 allowlist). The open branch is covered with real served data below and in
// tests/test_sol192_tooltip_digest.py (Aligned Starbolt, Crown of the Inferno, Black Sun ...).
const challengeDigest = {status: 'full', name: 'Challenge', record: 'GUARDIAN_BASE_CHALLENGE_PRACTICE',
  summary: 'Issue a challenge through words, stance, weapon intent, a visible gesture, killing pressure, or another method the target can perceive.',
  facts: [['Action', 'Bonus Action'], ['Range', '60 feet'], ['Target', 'One creature that can perceive your challenge'],
    ['Duration', '1 minute'], ['Cost', 'None']],
  outcomes: [['Failed save', 'The creature becomes Challenged by you for the duration.'], ['Successful save', 'No effect.']],
  groups: [{lead: 'While a creature is Challenged by you:', items: ['it has Disadvantage on attack rolls that do not include you as a target;']}],
  rules: ['An unwilling creature makes a Charisma saving throw.'], fine_print: 2};
const fullChallenge = '### Challenge Practice\nYou cultivate the art of becoming the enemy’s most immediate problem.\n#### Challenge\nAction Type: Bonus Action\nRange: 60 feet\nCost: None\nIssue a challenge ...';
const swift = {label: 'Challenge (Swift Guardian: no action; spend Martial Focus, your readiness point)', economy: 'NONE',
  detail: {cost: '1 Martial Focus', range: '60 ft', save: 'Charisma save, DC 15'}, hover: {digest: challengeDigest}};

test('live button values win over the printed header; digest adds target, duration and outcomes', () => {
  const model = actionCardModel(swift, {rules: fullChallenge});
  const facts = Object.fromEntries(model.facts);
  assert.equal(facts.Action, 'No action');          // the Swift Guardian button, not the base Bonus Action
  assert.equal(facts.Cost, '1 Martial Focus');      // the charged cost, not "None"
  assert.equal(facts.Save, 'Charisma save, DC 15');
  assert.equal(facts.Range, '60 ft');
  assert.equal(facts.Target, 'One creature that can perceive your challenge');
  assert.equal(facts.Duration, '1 minute');
  assert.deepEqual(model.outcomes[0], ['Failed save', 'The creature becomes Challenged by you for the duration.']);
  assert.equal(model.full.open, false);
});

test('rendered card: compact visible text, full rules once behind the expander, no raw markdown', () => {
  const card = actionTipCard(swift, {rules: fullChallenge})(doc, {terms: glossaryDefinitions('1 Martial Focus', false)});
  const text = visible(card);
  assert.match(text, /Failed save: The creature becomes Challenged/);
  assert.match(text, /While a creature is Challenged by you:/);
  assert.match(text, /Full rules \(2 more details\)/);
  assert.doesNotMatch(text, /You cultivate the art/);          // flavour and the full printed text are collapsed
  assert.doesNotMatch(text, /^\s*#/m);
  // Glossary help stays in this one card, folded: the word is named, its definition is present once.
  assert.match(text, /Words used: Martial Focus/);
  assert.equal(card.textContent.split('Martial Focus is one available use').length - 1, 1);
  const full = card.all('tc-full')[0];
  assert.equal(full.tagName, 'details');
  assert.equal(full.textContent.split('Issue a challenge').length - 1, 1);
  assert.doesNotMatch(full.textContent, /#/);                 // headings rendered, never "###"
});

test('a changed rule shows "Summary pending" and the full rules open, never a stale summary', () => {
  const pending = {...swift, hover: {digest: {status: 'pending', record: 'GUARDIAN_BASE_CHALLENGE_PRACTICE'}}};
  const model = actionCardModel(pending, {rules: fullChallenge});
  assert.match(model.pending, /Summary pending/);
  assert.equal(model.summary, ''); assert.deepEqual(model.outcomes, []);
  assert.equal(model.full.open, true);
  const text = visible(renderTipCard(doc, model));
  assert.match(text, /Summary pending/);
  assert.match(text, /Issue a challenge/);
});

test('no printed record: the full rules are shown open and a header fact with the same value is not repeated', () => {
  const row = {label: 'Guard', economy: 'BONUS_ACTION', detail: {cost: '2 Qi', range: '5 feet'}};
  const model = actionCardModel(row, {rules: 'Guard\nAction Type: Bonus Action\nRange: 15 feet\nGain +2 AC.'});
  const facts = Object.fromEntries(model.facts);
  assert.equal(facts.Action, 'Bonus Action'); // activation badge stays visible beside Full rules
  assert.equal(facts.Range, '5 feet');        // printed differently: the live value survives
  assert.equal(facts.Cost, '2 Qi');
  assert.equal(model.title, '');              // the open text already starts with the name
});

test('reaction cards keep the reaction help one click away', () => {
  const model = actionCardModel({label: 'Turn the Blade Aside', economy: 'REACTION', detail: {},
    hover: {digest: {status: 'full', facts: [['Action', 'Reaction'], ['Trigger', 'A creature bearing your Beauty Mark targets you with an attack']],
      outcomes: [['Failed save', 'The triggering attack has Disadvantage.']]}}}, {rules: 'x'});
  assert.deepEqual(model.facts.slice(0, 2), [['Action', 'Reaction'], ['Trigger', 'A creature bearing your Beauty Mark targets you with an attack']]);
  const card = renderTipCard(doc, model);
  assert.match(visible(card), /How reactions work/);
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
});

test('Armor Class card: one equation first, the full calculation under an expander', () => {
  const breakdown = {effective_value: 12, formula_trace: {root: {op: 'add', value: 12, terms: [{op: 'constant', value: 10}, {op: 'ability_modifier', ability: 'DEX', value: 2}]}},
    combat_terms: [{source: 'unarmored calculation', value: 12}], conditional_note: 'Qi Armor: +3 AC while it is active.'};
  const model = TianxiaSheetViewModel.armorCard(breakdown, {armor_class: 17, armor_base: 12, armor_modifiers: [{source: 'Shield spell', value: 5}]});
  assert.equal(model.headline, 'AC 17 = 10 + 2 Dex + 5 Shield spell (this fight).');
  assert.equal(model.lines[0], 'Only sometimes: Qi Armor: +3 AC while it is active.');
  const text = visible(renderTipCard(doc, model));
  assert.match(text, /Full calculation/);
  assert.doesNotMatch(text, /Use one base calculation/);       // the long explanation is collapsed
  assert.match(model.full.text, /Use one base calculation/);    // but kept, complete
  const sheetOnly = TianxiaSheetViewModel.armorCard(breakdown, null);
  assert.equal(sheetOnly.headline, 'AC 12 = 10 + 2 Dex.');
  const unexplained = TianxiaSheetViewModel.armorCard(breakdown, {armor_class: 19, armor_modifiers: [{source: 'Shield spell', value: 5}]});
  assert.equal(unexplained.headline, 'AC 19 = 10 + 2 Dex + 5 Shield spell (this fight) + 2 other active defenses.');
});

test('open card (real served status): live Range/Area/Cost win over printed values; no save chip', () => {
  const rules = 'Starbolt\nAction Type: Action\nRange: 90 feet\nCost: 0 CP\nTarget: One creature or object you can target\nMake a ranged Cultivation Attack roll.';
  const model = actionCardModel({label: 'Starbolt (Aligned: marked target, +30 ft)', economy: 'ACTION',
    detail: {range: '120 ft', to_hit: '+7', save: 'Wisdom save, DC 15'}, hover: {digest: {status: 'open', record: 'STARS_BASE_STARBOLT'}}}, {rules});
  const facts = Object.fromEntries(model.facts);
  assert.equal(facts.Range, '120 ft');            // the button's live range, not the printed 90 feet
  assert.equal(facts.Cost, '0 CP');               // no live cost: printed once, used as fallback
  assert.equal(facts.Target, 'One creature or object you can target');
  assert.equal(facts.Save, undefined); assert.equal(facts.Attack, undefined);
  assert.equal(model.full.open, true);
});
