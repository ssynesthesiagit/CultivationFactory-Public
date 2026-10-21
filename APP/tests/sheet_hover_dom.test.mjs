import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fixture from './sheet_hover_render_source.cjs';
import {actionHoverText, actionTipCard, cleanRules, uniqueRuleBlocks} from '../static/tabletop/rules.js';
import {layoutText} from '../static/tabletop/presentation.js';
import {glossaryDefinitions, installGlossary, resourceText} from '../static/tabletop/newcomer.js';
import {bindTipTargets, createHoverCard} from '../static/tabletop/hovercard.js';

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {};
    this.style = {}; this.listeners = {}; this.text = ''; this.hidden = false;
    this.classList = {add() {}, remove() {}};
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  hasAttribute(k) { return k in this.attributes; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  removeEventListener(k, fn) { this.listeners[k] = (this.listeners[k] || []).filter(listener => listener !== fn); }
  append(...kids) { for (const kid of kids.flat()) { if (kid instanceof Element) kid.parentElement = this; this.children.push(kid); } }
  appendChild(kid) { this.append(kid); return kid; }
  replaceChildren(...kids) { for (const child of this.children) if (child instanceof Element) child.parentElement = null; this.children = []; this.text = ''; this.append(...kids); }
  set textContent(v) { this.children = []; this.text = String(v); }
  get textContent() { return this.text + this.children.map(k => k instanceof Element ? k.textContent : k).join(''); }
  matches(s) {
    return s.split(',').some(q => q === '[data-tip]' ? 'tip' in this.dataset
      : q === '[data-hover-card]' ? this.hasAttribute('data-hover-card')
      : q === '[title]' ? this.hasAttribute('title')
      : q === '.tt-hovercard' ? this.className === 'tt-hovercard'
      : q === 'button' ? this.tagName === 'button' : false);
  }
  closest(s) { return this.matches(s) ? this : this.parentElement?.closest(s) || null; }
  querySelectorAll(s) { return this.children.filter(k => k instanceof Element).flatMap(k => [...(k.matches(s) ? [k] : []), ...k.querySelectorAll(s)]); }
  querySelector(s) { return this.querySelectorAll(s)[0] || null; }
  contains(k) { return k === this || this.children.some(c => c instanceof Element && c.contains(k)); }
  getBoundingClientRect() { return {left: 20, top: 80, right: 690, bottom: 130, width: 670, height: 50}; }
}
function setup() {
  const doc = new Element();
  doc.createElement = tag => new Element(tag); doc.createTextNode = text => String(text);
  doc.body = new Element(); doc.documentElement = new Element(); doc.append(doc.body);
  doc.getElementById = () => null;
  const ctx = vm.createContext({document: doc, Node: Element, actionHoverText, actionTipCard, cleanRules, uniqueRuleBlocks, layoutText});
  vm.runInContext(fixture.source, ctx);
  const row = vm.runInContext('actionRow(row)', ctx); doc.body.append(row);
  installGlossary(doc);
  const card = createHoverCard({doc, win: {innerWidth: 1100, innerHeight: 900}, setTimer: () => 1, clearTimer() {}});
  // Same binding as sheet.js/tabletop.js: glossary help lives in the one app card.
  bindTipTargets(card, doc, {setTimer: fn => { fn(); return 1; }, clearTimer() {}, glossary: text => glossaryDefinitions(text, false)});
  const fire = (type, target) => { for (const fn of doc.listeners[type] || []) fn({target}); };
  return {doc, row, card, fire};
}
test('real sheet row and all descendants have one hover popup on pointer and keyboard entry', () => {
  const {row, card, fire} = setup();
  const descendants = [row, ...row.querySelectorAll('button'), row.children[0], row.children[0].children[1]];
  for (const target of descendants) {
    target.setAttribute('title', 'Resonance'); // stale native title must be removed too
    for (const type of ['pointerover', 'focusin']) {
      fire(type, target);
      assert.equal(target.hasAttribute('title'), false);
      assert.equal(row.hasAttribute('title'), false);
      assert.equal(card.isOpen, true);
    }
  }
  // The Resonance definition is kept, inside the one card, exactly once.
  assert.equal(card.node.textContent.split('Resonance is the Spirit Awakening').length - 1, 1);
});
test('rendered Chain Armor card states each effect, action, cost and duration once, with automation note', () => {
  const {row, card, fire} = setup(); fire('pointerover', row);
  const text = card.node.textContent;
  // The activation badge is deliberately kept above the complete printed record
  // (1ca93764: "retain activation badges, even when Full rules repeats it"), so it is
  // stated once in the compact card and once in the full rules -- not twice in either.
  const [compact, full] = text.split('Full rules');
  assert.ok(full, `the complete printed rules are shown: ${text}`);
  assert.equal(compact.split('Bonus Action').length - 1, 1, `compact: ${text}`);
  assert.equal(full.split('Bonus Action').length - 1, 1, `full: ${text}`);
  for (const part of ['Chain Armor', '3 Resonance', 'Concentration, up to 1 minute',
    'Chains coil around your body', '+2 AC;', 'reduce forced movement affecting you by 10 feet', 'Partly automated:']) {
    // 1ca93764 (owner): the activation badge is always shown even when the printed
    // Full rules repeat it, so the action is stated once as the badge and once verbatim.
    const expected = part === 'Bonus Action' ? 2 : 1;
    assert.equal(text.split(part).length - 1, expected, `${part}: ${text}`);
  }
});
test('shared table card preserves distinct modifier, refusal and reaction help without repeating rules', () => {
  const text = actionHoverText({...fixture.row, economy: 'REACTION'}, {extra: ['Only when: holding a chain.', 'You have no action left.']});
  assert.equal(text.split('Chains coil around your body').length - 1, 1);
  assert.match(text, /Only when: holding a chain/); assert.match(text, /no action left/);
  assert.match(text, /With Ask me, choose Use or Pass/);
});
test('legacy rules keep their whole effect and missing action metadata; unrelated native help still works', () => {
  const text = actionHoverText({label: 'Guard', economy: 'BONUS_ACTION', detail: {cost: '2 Qi', range: 'Self'},
    description: 'For 1 minute, gain +2 AC. This ends when you drop your shield.'});
  assert.match(text, /Bonus Action · Cost: 2 Qi · Range: Self/);
  assert.equal(text.split('gain +2 AC').length - 1, 1);
  assert.match(text, /ends when you drop your shield/);
  const {doc, fire} = setup();
  const control = new Element('button'); control.textContent = 'Spend Qi'; doc.body.append(control);
  fire('pointerover', control);
  assert.match(control.getAttribute('title'), /Qi is the Qi Cultivation energy pool/);
});
test('resource and condition cards, nested labels and custom map cards never get glossary titles', () => {
  const {doc, fire} = setup();
  for (const marker of ['data-tip', 'data-hover-card']) {
    const target = new Element();
    if (marker === 'data-tip') target.dataset.tip = resourceText({name: 'Resonance', current: 2, maximum: 10});
    else target.setAttribute(marker, '');
    const child = new Element('span'); child.textContent = 'Resonance'; target.append(child); doc.body.append(target);
    fire('pointerover', child); fire('focusin', child);
    assert.equal(child.hasAttribute('title'), false); assert.equal(target.hasAttribute('title'), false);
    if (marker === 'data-tip') assert.match(target.dataset.tip, /Short rest: regain your Spirit Awakening/);
  }
});

test('SOL187 fix: current activation survives a different printed activation or an incidental "use an action"', () => {
  const reaction = actionHoverText({label: 'Chain Catch', economy: 'REACTION', detail: {}},
    {rules: 'Action Type: Bonus Action\nCatch the falling blade.'});
  assert.match(reaction, /^Chain Catch\n\nReaction\n/);
  assert.match(reaction, /Action Type: Bonus Action/);
  const bonus = actionHoverText({label: 'Iron Skin', economy: 'BONUS_ACTION', detail: {}},
    {rules: 'Gain +2 AC. You can use an action to end this effect.'});
  assert.match(bonus, /\n\nBonus Action\n\n/);
  const same = actionHoverText({label: 'Ward', economy: 'BONUS_ACTION', detail: {range: '60 ft'}},
    {rules: 'Action Type: Bonus Action\nRange: 60 feet\nGain +2 AC.'});
  assert.equal(same.split('Bonus Action').length - 1, 1, same);
  assert.doesNotMatch(same, /Range: 60 ft/);
});
test('SOL187 fix: same-label facts with different numbers both survive', () => {
  const text = actionHoverText({label: 'Lash', economy: 'ACTION', detail: {range: '5 feet', cost: '3 Qi', save: 'Strength save, DC 14'}},
    {rules: 'Action Type: Action\nRange: 15 feet\nCost: 13 Qi\nSave: Strength\nA chain lashes out.'});
  assert.match(text, /Range: 5 feet/); assert.match(text, /Range: 15 feet/);
  assert.match(text, /Cost: 3 Qi/); assert.match(text, /Cost: 13 Qi/);
  assert.match(text, /Save: Strength save, DC 14/);
});
test('SOL187 fix: glossary help for named terms appears once in the one app card', () => {
  const {doc, card, fire} = setup();
  const target = new Element('button');
  target.dataset.tip = actionHoverText({label: 'Guard', economy: 'BONUS_ACTION', detail: {cost: '2 Qi, 1 Martial Focus'},
    description: 'For 1 minute, gain +2 AC.'});
  doc.body.append(target);
  fire('pointerover', target);
  const text = card.node.textContent;
  assert.equal(text.split('Qi is the Qi Cultivation energy pool').length - 1, 1, text);
  assert.equal(text.split('Martial Focus is one available use').length - 1, 1, text);
  assert.equal(target.hasAttribute('title'), false);
});
test('SOL187 fix: keyboard focus alone opens a fresh, closed card', () => {
  const {row, card, fire} = setup();
  assert.equal(card.isOpen, false);
  fire('focusin', row);
  assert.equal(card.isOpen, true);
  assert.match(card.node.textContent, /Chains coil around your body/);
});

// SOL211: production creates a page card and a board card in the same document.
// Re-run the real row renderer and delegated setup, including glossary/native help.
for (const renders of [1, 3]) {
  test(`SOL211: one popup after ${renders} sheet render(s), even with glossary and a map card`, () => {
    const {doc, row, card, fire} = setup();
    const parent = new Element(); parent.setAttribute('title', 'Resonance');
    doc.body.replaceChildren(parent, card.node); parent.append(row);
    const mapCard = createHoverCard({doc, win: {innerWidth: 1100, innerHeight: 900}});
    const token = new Element('button'); parent.append(token);
    mapCard.open({trigger: token, build: node => { node.textContent = 'Map creature'; }});
    let current = row;
    for (let i = 1; i < renders; i++) {
      const ctx = vm.createContext({document: doc, Node: Element, actionHoverText, actionTipCard, cleanRules, uniqueRuleBlocks, layoutText});
      vm.runInContext(fixture.source, ctx);
      current = vm.runInContext('actionRow(row)', ctx);
      parent.replaceChildren(current);
      installGlossary(doc);
      bindTipTargets(card, doc, {setTimer: fn => { fn(); return 1; }, clearTimer() {}, glossary: text => glossaryDefinitions(text, false)});
    }
    fire('pointerover', current.children[0]);
    const visible = doc.body.querySelectorAll('.tt-hovercard').filter(node => !node.hidden);
    assert.equal(visible.length, 1, 'exactly one custom popup, including the previous map card');
    assert.equal(visible[0], card.node);
    // A blank title blocks inheritance; removing it exposes the container's native popup.
    let native = current.children[0];
    while (native && !native.hasAttribute('title')) native = native.parentElement;
    assert.equal(native?.getAttribute('title') || '', '', 'no inherited native/glossary popup');
    assert.equal((doc.listeners.pointerover || []).length, 2, 'one glossary and one custom-card listener after renders');
    assert.equal(current.getAttribute('aria-describedby'), card.node.id);
    assert.match(card.node.textContent, /Chains coil around your body/);
  });
}

test('SOL211: glossary and delegated tooltip setup are idempotent', () => {
  const {doc, card} = setup();
  installGlossary(doc); installGlossary(doc);
  bindTipTargets(card, doc); bindTipTargets(card, doc);
  assert.equal(doc.listeners.pointerover.length, 2);
  assert.equal(doc.listeners.focusin.length, 2);
});

test('SOL211: custom sheet help blocks inherited native titles without removing unrelated help', () => {
  const {doc, row, card, fire} = setup();
  const parent = new Element(); parent.setAttribute('title', 'Spend Resonance');
  doc.body.replaceChildren(parent, card.node); parent.append(row);
  fire('pointerover', row.children[0]);
  assert.equal(row.getAttribute('title'), '', 'empty title blocks the native ancestor popup');
  assert.equal(parent.getAttribute('title'), 'Spend Resonance', 'other controls retain their native help');
  assert.equal(row.children[0].hasAttribute('title'), false);
});

test('SOL211: different import versions still share one document card, with owner-scoped callbacks', async () => {
  const {doc, row, card, fire} = setup();
  const {createHoverCard: otherCreate} = await import('../static/tabletop/hovercard.js?sol211-other-version');
  const closed = [], dismissed = [];
  const other = otherCreate({doc, onClose: () => closed.push('map'), onDismiss: reason => dismissed.push(reason)});
  assert.equal(other.node, card.node);
  const token = new Element('button'); doc.body.append(token);
  other.open({trigger: token, build: node => { node.textContent = 'Map creature'; }});
  fire('pointerover', row);
  assert.deepEqual(closed, ['map']);
  assert.deepEqual(dismissed, ['replacement']);
  assert.equal(token.hasAttribute('aria-describedby'), false);
  other.close();
  assert.equal(card.isOpen, true, 'stale map handle cannot dismiss the sheet');
  card.close();
  assert.deepEqual(closed, ['map'], 'closing the sheet does not call the old map callback');
  assert.notEqual(otherCreate({doc: newDoc()}).node, card.node, 'separate pop-out documents retain their own card');
  function newDoc() {
    const doc = new Element(); doc.body = new Element(); doc.createElement = tag => new Element(tag); return doc;
  }
});

test('SOL211: rebinding cancels a pending old-row open and uses only the new row', () => {
  const {doc, row, card, fire} = setup();
  const timers = new Map(); let seq = 0;
  const options = {setTimer: fn => { timers.set(++seq, fn); return seq; }, clearTimer: id => timers.delete(id)};
  bindTipTargets(card, doc, options);
  fire('pointerover', row);
  assert.equal(timers.size, 1);
  doc.body.replaceChildren(card.node);
  bindTipTargets(card, doc, options);
  assert.equal(timers.size, 0);
  const target = new Element('button'); target.dataset.tip = 'New row'; doc.body.append(target);
  fire('pointerover', target);
  for (const fn of timers.values()) fn();
  assert.equal(card.trigger, target);
  assert.equal(card.node.textContent, 'New row');
});
