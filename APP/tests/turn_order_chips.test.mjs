// Turn-order chips (owner 2026-10-06): token art, labelled HP, the rolled initiative. Runs the page's real renderer.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const page = fs.readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function body(name) {
  const start = page.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  return page.slice(start, page.indexOf('\n}', start) + 2);
}

function node(tag) {
  const n = {tag, children: [], style: {props: {}, setProperty(k, v) { this.props[k] = v; }}, events: {}, className: '', textContent: '',
    append(...kids) { this.children.push(...kids); }, appendChild(kid) { this.children.push(kid); },
    replaceChildren(...kids) { this.children = kids; }, addEventListener(type, fn) { this.events[type] = fn; },
    get lastChild() { return this.children[this.children.length - 1]; }};
  return n;
}

function render(rows, {tokens = {}, currentActorId = rows[0].entity_id, terminal = false} = {}) {
  const list = node('ol'), calls = [];
  const ctx = vm.createContext({
    $: () => list, document: {createElement: node},
    presentation: () => ({initiative_order: rows.map(a => a.entity_id), current_actor_id: currentActorId, terminal}),
    actorById: id => rows.find(a => a.entity_id === id), TEAM_COLORS: ['red'], teamIndex: () => 0,
    initials: n => n.slice(0, 2).toUpperCase(), isManualActor: () => false, app: {state: {tokens}},
    selectActor: id => calls.push(['select', id]), board: {centerOn: (x, y) => calls.push(['center', x, y])},
  });
  vm.runInContext(body('tokenImage') + '\n' + body('renderInitiative'), ctx);
  ctx.renderInitiative();
  return {chips: list.children.map(li => li.children[0]), classes: list.children.map(li => li.className), calls};
}

const actor = (id, extra = {}) => ({entity_id: id, display_name: `Name ${id}`, active: true, hit_points: {current: 40},
  position: {x: 3, y: 4}, ...extra});

test('chip uses the token map first, then the fight image, else initials', () => {
  const {chips} = render([actor('a', {visual: {kind: 'image', public_url: '/v/a.png'}}),
    actor('b', {visual: {kind: 'image', public_url: '/v/b.png'}}), actor('c')], {tokens: {a: '/t/a.png'}});
  assert.equal(chips[0].children[0].children[0].src, '/t/a.png');
  assert.equal(chips[1].children[0].children[0].src, '/v/b.png');
  assert.equal(chips[2].children[0].textContent, 'NA');
});

test('a broken image falls back to initials', () => {
  const {chips} = render([actor('a')], {tokens: {a: '/missing.png'}});
  const dot = chips[0].children[0];
  dot.children[0].events.error();
  assert.deepEqual(dot.children, ['NA']);
});

test('HP is labelled and initiative shows only when rolled, zero included', () => {
  const {chips} = render([actor('a', {initiative: 17}), actor('b', {initiative: 0}), actor('c'), actor('d', {initiative: null})]);
  assert.equal(chips[0].lastChild.textContent, 'Name a · HP 40 · Init 17');
  assert.equal(chips[1].lastChild.textContent, 'Name b · HP 40 · Init 0');
  assert.equal(chips[2].lastChild.textContent, 'Name c · HP 40');
  assert.equal(chips[3].lastChild.textContent, 'Name d · HP 40');
});

test('clicking a chip still selects and centres on the creature', () => {
  const {chips, calls} = render([actor('a')]);
  chips[0].events.click();
  assert.deepEqual(calls, [['select', 'a'], ['center', 3, 4]]);
});

test('a skipped defeated slot stays visible but never has the acting highlight', () => {
  const {chips, classes} = render([actor('dead', {active: false, hit_points: {current: 0}}), actor('living')],
    {currentActorId: 'living'});
  assert.equal(chips.length, 2);
  assert.ok(classes[0].includes('is-down'));
  assert.ok(!classes[0].includes('is-current'));
  assert.ok(classes[1].includes('is-current'));
});

test('a terminal fight never highlights its last nominal slot as acting', () => {
  const {classes} = render([actor('dead', {active: false})], {terminal: true});
  assert.ok(classes[0].includes('is-down'));
  assert.ok(!classes[0].includes('is-current'));
});
