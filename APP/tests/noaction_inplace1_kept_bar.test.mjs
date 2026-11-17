
// NOACTIONINPLACE1: a free setting choice keeps the live action bar when its controls are unchanged.
// Run: node --test APP/tests/noaction_inplace1_kept_bar.test.mjs
// The fixtures copy the attributes tabletop.js really draws: Options buttons carry data-tip (the hover text naming the
// current selection) and a small detail; command buttons carry their handler through bindPress (kept-bar.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import {barSignature, bindPress, copySelection, reconcileBar} from '../static/tabletop/kept-bar.js';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {OptionDraft} from '../static/tabletop/option-composition.js';
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
    get childNodes() { return this.children; },
    replaceChildren(...nodes) { this.children = []; nodes.forEach(n => this.appendChild(n)); },
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

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');

function activationHarness({modifier = false} = {}) {
  const requests = [], submitted = [], renders = [];
  const setting = {source_definition_id:'setting:point', label:'Touch the Point: Numb Leg',
    economy:'NONE', options:[{candidate_id:'point', target_ids:['me']}]};
  const attack = {source_definition_id:'attack:sword', label:'Sword', economy:'ACTION',
    options:[{candidate_id:'base-hit', target_ids:['foe']}]};
  const menu = {actor_id:'me', decision_id:'d1', state_version:1, manual:true,
    actions:[setting, attack], moves:[], composition:modifier ? {
      point:{key:['point'], mode:'select', source:setting.source_definition_id, attacks:'melee'},
    } : {}};
  const app = {menu, state:{menu, presentation:{round_number:1}}, matchId:'fight', lastSequence:0};
  const live = bar({menu:{attack:'a1',end_turn:'e1'}, submitted});
  const group = element('div', {cls:'tt-ab-groups', children:[
    element('details', {attrs:{'data-variant-group':'standing-talents', open:''}, text:'Talents'}),
  ]});
  live.appendChild(group);
  live.scrollTop=61; live.scrollLeft=3; group.scrollTop=5; group.scrollLeft=418;
  const context = {app, OptionDraft, refreshSequence:0, crypto:{randomUUID:()=> 'draft-1'},
    document:{body:{classList:{add(){},remove(){}}}}, enc:encodeURIComponent,
    refuseCoveredView:()=>false, synchronizePresets:async()=>{}, hint(){}, cancelTargeting(){},
    renderShapePanel(){}, renderDraftSummary(){}, invalidateTargeting(){}, gmNotice(){},
    playEvents:async()=>{}, menuReadFor:()=>({compact:true,fog:true}),
    toast(message){throw Error(message);}, refresh(){throw Error('Unexpected full state/menu refetch');},
    renderActionBar(){renders.push('rebuild');},
    render(state, options={}) {
      renders.push(options);
      app.menu=state.menu; app.state=state;
      if (options.keepBar) {
        const probe=bar({menu:{attack:'a2',end_turn:'e2'},submitted});
        // Changed legal controls exercise replacement as well as the selection-only path.
        probe.appendChild(element('div',{cls:'tt-ab-groups',children:[
          element('details',{attrs:{'data-variant-group':'standing-talents'},text:'Talents'}),
          element('button',{text:'Newly legal talent'}),
        ]}));
        reconcileBar(live,probe);
      }
    },
    withReactions:callback=>callback([]),
    async api(path, {body}={}) {
      requests.push({path,body});
      if (path.endsWith('/composition/preview')) return {menu:{
        ...menu,decision_id:'projected',state_version:2,actions:[
          {...attack,options:[{candidate_id:'composed-hit',target_ids:['foe']}]},
        ]}};
      if (path.endsWith('/prepare')) return {status:'PREPARED'};
      if (path.endsWith('/act')) return {status:'COMMITTED', events:{events:[]},
        state:{menu:{...menu,decision_id:'d3',state_version:3}}};
      throw Error('Unexpected menu read: '+path);
    },
  };
  for (const [start,end] of [
    ['function chooseLocalOption(', '\nfunction useOptionCandidate'],
    ['async function useGroup(', '\nfunction chooseFromList'],
    ['async function aimComposedAction(', '\nfunction renderShapePanel'],
    ['async function act(', '\n// An ability the fight runs nothing for'],
  ]) {
    const offset=source.indexOf(start);
    assert.ok(offset>=0);
    vm.runInNewContext(source.slice(offset,source.indexOf(end,offset)),context);
  }
  context.actOnce=id=>context.act(id);
  return {context,app,requests,renders,live,setting,attack};
}

test('No-action activation returns its menu with the commit, preserving scroll and open nesting', async () => {
  const {context,requests,renders,live,setting}=activationHarness();
  assert.equal(await context.useGroup(setting),true);
  assert.deepEqual(requests.map(r=>r.path.split('/').pop()),['prepare','act'],
    'No second GET of state, decision, menu or ranking');
  assert.deepEqual(requests[1].body.menu_read,{compact:true,fog:true});
  assert.deepEqual(JSON.parse(JSON.stringify(renders)),[{keepBar:true}]);
  assert.equal(live.scrollTop,61);
  assert.equal(live.scrollLeft,3);
  const scroller=live.querySelector('.tt-ab-groups');
  assert.equal(scroller.scrollLeft,418);
  assert.equal(scroller.scrollTop,5);
  assert.equal(scroller.querySelector('[data-variant-group]').hasAttribute('open'),true);
});

test('a No-action hit preference drafts locally and rides the attack composition', async () => {
  const {context,app,requests,renders,live,setting,attack}=activationHarness({modifier:true});
  const before=live.childNodes.slice(), scroll=live.querySelector('.tt-ab-groups').scrollLeft;
  assert.equal(await context.useGroup(setting),true);
  assert.deepEqual(requests,[]);
  assert.deepEqual(renders,[]);
  assert.deepEqual(live.childNodes,before);
  assert.equal(live.querySelector('.tt-ab-groups').scrollLeft,scroll);
  assert.equal(app.menu.state_version,1);
  assert.equal(await context.useGroup(attack),true);
  assert.deepEqual(requests.map(r=>r.path.split('/').pop()),['preview','prepare','act']);
  assert.deepEqual([...requests[0].body.sources],['setting:point']);
  assert.equal(requests[0].body.source_definition_id,'attack:sword');
  assert.deepEqual(requests[2].body.composition,requests[0].body);
  assert.equal(requests[2].body.candidate_id,'composed-hit');
});
