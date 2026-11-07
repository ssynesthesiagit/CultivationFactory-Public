import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import source from './sheetbars_source.cjs';
import dom from './gm_sheet_dom_stub/domstub.js';

// The app stub ignores append(string); this renderer uses native text nodes.
class Element extends dom.FakeElement {
  constructor(tag) { super(tag); this.style = {setProperty(prop, value) { this[prop] = value; }}; }
  appendChild(node) {
    if (typeof node === 'string') { this.children.push(node); return node; }
    return super.appendChild(node);
  }
  set textContent(value) { this.children = value === '' ? [] : [String(value)]; }
  get textContent() { return this.children.map(child => typeof child === 'string' ? child : child.textContent).join(''); }
}

test('top stat row has no cultivation pool panel', () => {
  const roots = new Map(['abilities', 'vitals'].map(id => [id, new Element('div')]));
  const document = {getElementById: id => roots.get(id), createElement: tag => new Element(tag),
    createElementNS: (_ns, tag) => new Element(tag)};
  const context = vm.createContext({document, Node: Element});
  vm.runInContext(source, context);
  context.names = ['Qi', 'Stamina'];
  vm.runInContext(`state.summary = {hit_points: {maximum: 9}, resources: names.map(name => ({name, maximum: 9}))}; renderStats();`, context);
  const vitals = roots.get('vitals');
  assert.equal(vitals.querySelectorAll('.res-pool').length, 0);
  assert.equal(vitals.querySelectorAll('#res-box').length, 0);
  assert.equal([...vitals.querySelectorAll('.hp-cell')][0].querySelector('.hp-num').textContent, '9');
});

test('CSS protects numeric widths and has no top pool panel styles', () => {
  const css = fs.readFileSync(new URL('../static/tabletop/sheet.css', import.meta.url), 'utf8');
  const rule = selector => {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const matches = [...css.matchAll(new RegExp(`^${escaped} \\{([^}]+)\\}`, 'gm'))];
    assert.equal(matches.length, 1, selector);
    return matches[0][1];
  };
  assert.match(rule('.hp-num'), /white-space: nowrap/);
  assert.match(rule('.hp-num'), /flex-shrink: 0/);
  assert.match(rule('.meter-head .stat-label'), /overflow-wrap: anywhere/);
  assert.match(rule('.hp-grid'), /minmax\(max-content, 1fr\)/);
  assert.doesNotMatch(css, /\.res-line|\.res-pool|#res-box|meter-box\.res/);
});

test('Resources list shows every pool once, with bars and hints, and no top panel', () => {
  const sheet = fs.readFileSync(new URL('../static/tabletop/sheet.js', import.meta.url), 'utf8');
  const section = (from, to) => sheet.slice(sheet.indexOf(from), sheet.indexOf(to, sheet.indexOf(from)));
  const roots = new Map(['defenses', 'vitals'].map(id => [id, new Element('div')]));
  const document = {getElementById: id => roots.get(id), createElement: tag => new Element(tag),
    createElementNS: (_ns, tag) => new Element(tag)};
  const context = vm.createContext({document, Node: Element, $: id => roots.get(id) || document.getElementById(id),
    norm: text => String(text || '').trim().toLowerCase(), clamp01: v => Math.max(0, Math.min(1, v)),
    resourceText: () => 'tip', state: {buttons: [], connected: true}});
  vm.runInContext(source.split('\nconst $ =')[0] + '\n' + section('function h(tag, attrs, ...kids)', 'function icon(') +
    '\n' + section('function resourcePools(', 'function renderSaves()') + '\n' +
    section('function renderDefenses()', 'function renderSkills()'), context);
  vm.runInContext(`state.summary = {resources: [{name: 'Qi', maximum: 9}, {name: 'Stamina', maximum: 4}], armor_class: 12, hit_points: {maximum: 9}};
    state.actor = {resources: [{display_name: 'Qi', current: 9, maximum: 9}, {display_name: 'Stamina', current: 1, maximum: 4}]};
    renderDefenses();`, context);
  const rows = [...roots.get('defenses').querySelectorAll('.res-row')];
  assert.deepEqual(rows.map(row => row.children[0].textContent), ['QiFull', 'Stamina3 spent']);
  assert.deepEqual(rows.map(row => row.children[1].textContent), ['9 / 9', '1 / 4']);
  assert.equal(rows[1].querySelector('.meter-fill').style.width, '25%');
  assert.equal(roots.get('vitals').querySelectorAll('.res-pool').length, 0);
  vm.runInContext(`state.summary = {resources: [{name: 'Cultivation', maximum: 9}]};
    state.actor = {resources: [{display_name: 'Qi', current: 5, maximum: 9}]}; renderDefenses();`, context);
  const names = [...roots.get('defenses').querySelectorAll('.res-row')].map(row => row.children[0].textContent);
  assert.deepEqual(names, ['Qi4 spent']);
});

test('Resources list shows sheet-only pools when there is no live actor, and unmatched secondary pools beside one', () => {
  const sheet = fs.readFileSync(new URL('../static/tabletop/sheet.js', import.meta.url), 'utf8');
  const section = (from, to) => sheet.slice(sheet.indexOf(from), sheet.indexOf(to, sheet.indexOf(from)));
  const render = (summary, actor) => {
    const roots = new Map(['defenses', 'vitals'].map(id => [id, new Element('div')]));
    const document = {getElementById: id => roots.get(id), createElement: tag => new Element(tag),
      createElementNS: (_ns, tag) => new Element(tag)};
    const context = vm.createContext({document, Node: Element, $: id => roots.get(id) || document.getElementById(id),
      norm: text => String(text || '').trim().toLowerCase(), clamp01: v => Math.max(0, Math.min(1, v)),
      resourceText: () => 'tip', state: {buttons: [], connected: false, summary, actor}});
    vm.runInContext(source.split('\nconst $ =')[0] + '\n' + section('function h(tag, attrs, ...kids)', 'function icon(') +
      '\n' + section('function resourcePools(', 'function renderSaves()') + '\n' +
      section('function renderDefenses()', 'function renderSkills()'), context);
    vm.runInContext('renderDefenses();', context);
    return [...roots.get('defenses').querySelectorAll('.res-row')];
  };
  const offline = render({resources: [{name: 'Qi', maximum: 9}, {name: 'Stamina', maximum: 4}], armor_class: 12, hit_points: {maximum: 9}}, null);
  assert.deepEqual(offline.map(row => row.children[0].textContent), ['QiFull', 'StaminaFull']);
  assert.deepEqual(offline.map(row => row.children[1].textContent), ['9 / 9', '4 / 4']);
  assert.equal(offline[1].querySelector('.meter-fill').style.width, '100%');
  const mixed = render({resources: [{name: 'Cultivation', maximum: 9}, {name: 'Stamina', maximum: 4}], hit_points: {maximum: 9}},
    {resources: [{display_name: 'Qi', current: 5, maximum: 9}]});
  assert.deepEqual(mixed.map(row => row.children[0].textContent), ['Qi4 spent', 'StaminaFull']);
});

test('stat boxes keep their own height when a resource panel is tall', () => {
  const css = fs.readFileSync(new URL('../static/tabletop/sheet.css', import.meta.url), 'utf8');
  const statRow = css.match(/^\.stats \{([^}]+)\}/m);
  assert.ok(statRow, '.stats rule');
  assert.match(statRow[1], /align-items: start/);
});

test('compact stat layout starts before the desktop track minima exceed the sheet width', () => {
  const css = fs.readFileSync(new URL('../static/tabletop/sheet.css', import.meta.url), 'utf8');
  const tracks = css.match(/\.stats \{[^}]*grid-template-columns: ([^;]+);/)[1];
  const groups = [...tracks.matchAll(/(?:repeat\((\d+), )?minmax\((\d+)px,/g)];
  const count = groups.reduce((sum, group) => sum + Number(group[1] || 1), 0);
  const minimum = groups.reduce((sum, group) => sum + Number(group[1] || 1) * Number(group[2]), 0);
  const gap = Number(css.match(/\.stats \{[^}]*gap: (\d+)px/)[1]);
  const padding = Number(css.match(/\.sheet \{[^}]*padding: \d+px (\d+)px/)[1]);
  const compactMedia = [...css.matchAll(/@media \(max-width: (\d+)px\) \{([\s\S]*?)\n\}/g)]
    .find(match => /\.stats \{ grid-template-columns: repeat\(8, minmax\(0, 1fr\)\)/.test(match[2]));
  assert.ok(compactMedia, 'eight-column stat layout must have a responsive breakpoint');
  const breakpoint = Number(compactMedia[1]);
  // Twelve tracks: the last one is the Height box, next to Hit Points.
  assert.equal(count, 12);
  assert.ok(breakpoint >= minimum + (count - 1) * gap + 2 * padding,
    'compact layout must cover every width too small for the desktop tracks and padding');
});

test('fly speed sits under Walking and altitude is its own box after Hit Points', () => {
  const roots = new Map(['abilities', 'vitals'].map(id => [id, new Element('div')]));
  const document = {getElementById: id => roots.get(id), createElement: tag => new Element(tag),
    createElementNS: (_ns, tag) => new Element(tag)};
  const context = vm.createContext({document, Node: Element, TianxiaSheetViewModel: {armorBreakdown: () => '', armorCard: () => ({})}});
  vm.runInContext(source, context);
  vm.runInContext(`state.summary = {hit_points: {maximum: 9}, speed_ft: 30, abilities: []};
    state.sheet = {}; renderStats();`, context);
  const vitals = roots.get('vitals');
  const boxes = vitals.children.filter(child => child instanceof Element && child.className.includes('stat'));
  assert.deepEqual(boxes.map(box => box.querySelector('.stat-label').textContent),
    ['Proficiency', 'Walking', 'Initiative', 'Armor', 'Hit Points', 'Height']);
  assert.equal(boxes[1].querySelector('.stat-fly').attributes.id, 'walk-fly');
  assert.equal(boxes[1].querySelector('.stat-fly').textContent, '');
  assert.equal(boxes[5].querySelector('.stat-big').textContent, '0ft');
  assert.equal(vitals.querySelectorAll('.flight-live').length, 0);
});

