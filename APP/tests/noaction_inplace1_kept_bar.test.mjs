// NOACTIONINPLACE1: a free setting choice keeps the live action bar when its controls are unchanged.
// Run: node --test APP/tests/noaction_inplace1_kept_bar.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {barSignature, copySelection} from '../static/tabletop/kept-bar.js';

// A small element model: enough of the DOM for the bar's tags, classes, attributes, text and children.
function element(tag, {cls = '', attrs = {}, text = '', children = []} = {}) {
  const node = {
    tagName: tag.toUpperCase(), attrs: {...attrs}, text, children: [], parent: null, disabled: false,
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
    get title() { return this.attrs.title ?? ''; }, set title(v) { this.attrs.title = v; },
    get textContent() { return this.text + this.children.map(c => c.textContent).join(''); },
    set textContent(v) { this.text = v; this.children = []; },
    get ownerDocument() { return doc; },
    appendChild(child) { child.parent = this; this.children.push(child); return child; },
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

function bar(options) {
  return element('footer', {cls: 'tt-actionbar', children: [
    element('div', {cls: 'tt-ab-group', children: [
      element('h3', {text: 'Options'}),
      element('button', {attrs: {'data-option-family': 'pressure'}, text: 'Pressure-Point Strike', children: [element('small', {text: options.now})]}),
      element('button', {attrs: {'data-option-family': 'pressure-off'}, text: 'Open the Gate', children: [element('small', {text: 'plain'})]}),
    ]}),
    element('button', {attrs: {'data-act': 'cand-1'}, text: 'Attack', cls: options.attackCls || ''}),
  ]});
}

test('the same controls with a new selection have the same signature', () => {
  const live = bar({now: 'plain'});
  const probe = bar({now: 'Golden Core'});
  probe.querySelectorAll('button')[0].classList.toggle('is-choice-active', true);
  assert.equal(barSignature(live), barSignature(probe));
});

test('a changed control (availability, class, attribute) gives another signature', () => {
  const live = bar({now: 'plain'});
  assert.notEqual(barSignature(live), barSignature(bar({now: 'plain', attackCls: 'is-disabled'})));
  const changed = bar({now: 'plain'}); changed.querySelectorAll('button')[2].attrs['data-act'] = 'cand-2';
  assert.notEqual(barSignature(live), barSignature(changed));
});

test('copySelection moves the selection marker and the Options detail onto the live bar', () => {
  const live = bar({now: 'plain'});
  const probe = bar({now: 'Golden Core'});
  probe.querySelectorAll('button')[0].classList.toggle('is-choice-active', true);
  copySelection(live, probe);
  const [pressure] = live.querySelectorAll('button');
  assert.equal(pressure.classList.contains('is-choice-active'), true);
  assert.equal(pressure.querySelector('small').textContent, 'Golden Core');
  assert.equal(pressure.querySelectorAll('.choice-active-tag').length, 1);
});
