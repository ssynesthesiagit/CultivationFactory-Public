
// NOACTIONINPLACE1: a free setting choice keeps the live action bar when its controls are unchanged.
// Run: node --test APP/tests/noaction_inplace1_kept_bar.test.mjs
// The fixtures copy the attributes tabletop.js really draws: Options buttons carry data-tip (the hover text naming the
// current selection) and a small detail; command buttons carry their handler through bindPress (kept-bar.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import {barSignature, bindPress, copySelection} from '../static/tabletop/kept-bar.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';

// A small element model: enough of the DOM for the bar's tags, classes, attributes, text, children and clicks.
function element(tag, {cls = '', attrs = {}, text = '', children = []} = {}) {
  const node = {
    tagName: tag.toUpperCase(), attrs: {...attrs}, text, children: [], parent: null, disabled: false, listeners: {},
    get className() { return this._cls ?? cls; }, set className(v) { this._cls = String(v); },
    get classList() {
      const self = this;
      const list = () => self.className.split(/\s+/).filter(Boolean);
      return {
        contains: name => list().includes(name),
        toggle(name, force) {
          const has = list().includes(name);
          const want = force ?? !has;
          const next = list().filter(n => n !== name); if (want) next.push(name);
          self.className = next.join(' ');
          return want;
        },
        remove: (...names) => { self.className = list().filter(n => !names.includes(n)).join(' '); },
      };
    },
    get dataset() { return Object.fromEntries(Object.entries(this.attrs).filter(([k]) => k.startsWith('data-')).map(([k, v]) => [k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase()), v])); },
    hasAttribute(name) { return name in this.attrs; },
    getAttribute(name) { return this.attrs[name]; },
    setAttribute(name, v) { this.attrs[name] = String(v); },
    get title() { return this.attrs.title ?? ''; }, set title(v) { this.attrs.title = v; },
    get textContent() { return this.text + this.children.map(c => c.textContent).join(''); },
    set textContent(v) { this.text = v; this.children = []; },
    get ownerDocument() { return doc; },
    appendChild(child) { child.parent = this; this.children.push(child); return child; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach(fn => fn()); },
    get parentNode() { return this.parent; },
    removeAttribute(name) { delete this.attrs[name]; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) { const out = []; const walk = n => n.children.forEach(c => { if (matches(c, sel)) out.push(c); walk(c); }); walk(this); return out; },
    cloneNode(deep) { const n = element(tag, {cls: this.className, attrs: this.attrs, text: this.text}); if (deep) this.children.forEach(c => n.appendChild(c.cloneNode(true))); return n; },
    get innerHTML() { return this.children.map(c => `<${c.tagName} class="${c.className}" ${Object.entries(c.attrs).sort().map(([k, v]) => `${k}="${v}"`).join(' ')}>${c.text}${c.innerHTML}</${c.tagName}>`).join(''); },
  };
  for (const child of children) node.appendChild(child);
  return node;
}

function matches(node, sel) {
  if (sel === 'button' || sel === 'small' || sel === 'span') return node.tagName === sel.toUpperCase();
  if (sel.startsWith('.')) return node.className.split(/\s+/).includes(sel.slice(1));
  if (sel.startsWith('[')) return sel.slice(1, -1) in node.attrs;
  return false;
}

const doc = {createElement: tag => element(tag)};

// makeButton() in tabletop.js: label, detail, the hover text in data-tip, and a handler bound with bindPress.
function commandButton(label, detail, tip, onPress, cls = '') {
  const button = element('button', {cls: `tt-btn ${cls}`, attrs: {'data-tip': tip}, children: [
    element('b', {text: label}), element('small', {text: detail})]});
  bindPress(button, onPress);
  return button;
}

// A bar with Options (its hover text names the current selection) and command buttons whose handlers submit a candidate.
// `submitted` records the candidate ids the handlers send, so a test can see which menu a click acted on.
function bar({now = 'plain', attackCls = '', menu, submitted}) {
  const act = id => submitted.push(id);
  const option = element('button', {attrs: {'data-option-family': 'pressure', 'data-tip': `Your next Pressure-Point Strike: ${now}.`}, text: 'Pressure-Point Strike', children: [element('small', {text: now})]});
  return element('footer', {cls: 'tt-actionbar', children: [
    element('div', {cls: 'tt-ab-group', children: [
      element('h3', {text: 'Options'}),
      option,
      element('button', {attrs: {'data-option-family': 'pressure-off', 'data-tip': 'Your next Open the Gate: plain.'}, text: 'Open the Gate', children: [element('small', {text: 'plain'})]}),
    ]}),
    commandButton('Attack', 'Strike', 'Strike the target', () => act(menu.attack), attackCls),
    commandButton('End turn', 'Space', 'End your turn', () => act(menu.end_turn), 'is-end'),
  ]});
}

test('the same controls with a new selection have the same signature', () => {
  const live = bar({now: 'plain', menu: {attack: 'a1', end_turn: 'e1'}, submitted: []});
  const probe = bar({now: 'Golden Core', menu: {attack: 'a1', end_turn: 'e1'}, submitted: []});
  probe.querySelectorAll('button')[0].classList.toggle('is-choice-active', true);
  assert.equal(barSignature(live), barSignature(probe));
});

test('a changed control (availability, class, attribute) gives another signature', () => {
  const menu = {attack: 'a1', end_turn: 'e1'};
  const live = bar({now: 'plain', menu, submitted: []});
  assert.notEqual(barSignature(live), barSignature(bar({now: 'plain', attackCls: 'is-disabled', menu, submitted: []})));
  const changed = bar({now: 'plain', menu, submitted: []}); changed.querySelectorAll('button')[2].attrs['data-tip'] = 'Other'; changed.querySelectorAll('button')[2].attrs.extra = '1';
  assert.notEqual(barSignature(live), barSignature(changed));
});

test('copySelection moves the selection marker, the Options hover text and detail onto the live bar', () => {
  const live = bar({now: 'plain', menu: {attack: 'a1', end_turn: 'e1'}, submitted: []});
  const probe = bar({now: 'Golden Core', menu: {attack: 'a1', end_turn: 'e1'}, submitted: []});
  probe.querySelectorAll('button')[0].classList.toggle('is-choice-active', true);
  copySelection(live, probe);
  const [pressure] = live.querySelectorAll('button');
  assert.equal(pressure.classList.contains('is-choice-active'), true);
  assert.equal(pressure.querySelector('small').textContent, 'Golden Core');
  assert.equal(pressure.dataset.tip, 'Your next Pressure-Point Strike: Golden Core.');
  assert.equal(pressure.querySelectorAll('.choice-active-tag').length, 1);
});

test('a kept End turn and attack submit the candidates of the new menu, not the ones drawn first', () => {
  // The setting commit gives the same controls new candidate ids (the menu's state version moved on).
  const submitted = [];
  const live = bar({now: 'plain', menu: {attack: 'a1', end_turn: 'e1'}, submitted});
  const probe = bar({now: 'Golden Core', menu: {attack: 'a2', end_turn: 'e2'}, submitted});
  assert.equal(barSignature(live), barSignature(probe));
  copySelection(live, probe);
  const [, , attack, endTurn] = live.querySelectorAll('button');  // two Options buttons, then Attack and End turn
  attack.click();
  endTurn.click();
  assert.deepEqual(submitted, ['a2', 'e2']);
});

// A ranked Action slot with six candidates: the first five are shown, the sixth sits behind "More…".
function actionMenu(ids) {
  return {ranked_slots: {Action: ids.slice(0, 5)}, actions: [{label: 'Strike', economy: 'ACTION', cost_label: 'Action · no CP',
    options: ids.map((id, i) => ({candidate_id: id, label: `target ${i}`}))}]};
}

test('a kept More… button reveals the rows of the newest menu, with its candidate ids', () => {
  const submitted = [];
  const onAct = id => submitted.push(id), onMove = () => {};
  const live = renderRankedMenu(actionMenu(['a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6']), {doc, onAct, onMove});
  // The setting commit redraws the same controls with new candidate ids (the menu's state version moved on).
  const probe = renderRankedMenu(actionMenu(['b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6']), {doc, onAct, onMove});
  assert.equal(barSignature(live), barSignature(probe));
  copySelection(live, probe);
  const more = () => live.querySelectorAll('button').find(b => b.textContent.startsWith('More'));
  more().click();  // expands in the live bar, not in the menu that was drawn first
  assert.equal(more(), undefined);
  const row = label => live.querySelectorAll('button').find(b => b.textContent.includes(label));
  row('target 5').click();
  row('target 6').click();
  assert.deepEqual(submitted, ['b5', 'b6']);
});
