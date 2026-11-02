// node --test tests/grow_learning.test.mjs (run by tests/test_mgr15_saber_learning.py)
// Saber-Line Method's Grow round trip (MGR-T15 review finding 1). The real grow.js renders the server's learning
// selectors through a small DOM double. The GM's correction of an unsealed ruling must be offered and posted.
// The payload has the shape GET /advancement returns (learning_options in combat/ext/saber_learning.py).
import test from 'node:test';
import assert from 'node:assert/strict';

import { initGrow, loadGrow } from '../static/tabletop/grow.js';

const METHOD = 'SABERS_BASE_SABER_LINE_METHOD';
const DAO = 'tianxia.mortal.weapon.dao';
const BLADE = 'synthetic.weapon.guandao_fixture';

const byId = new Map();

function matches(el, selector) {
  return selector.split(',').some(part => {
    const m = part.trim().match(/^\[data-([a-z-]+)\]$/);
    if (!m) return false;
    const key = m[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    return el.dataset[key] !== undefined;
  });
}

class El {
  constructor(tag, props, kids) {
    this.tag = tag;
    this.props = props || {};
    this.id = this.props.id || '';
    this.dataset = this.props.dataset || {};
    this.value = this.props.value;
    this.checked = Boolean(this.props.checked);
    this.parent = null;
    this.children = [];
    this.listeners = {};
    if (this.id) byId.set(this.id, this);
    this.append(...(kids || []));
    if (tag === 'select' && this.value === undefined) {
      const first = this.children.find(c => c instanceof El);
      this.value = first ? first.value : '';
    }
  }
  append(...items) {
    for (const item of items.flat()) {
      if (item === null || item === undefined || item === false) continue;
      if (item instanceof El) item.parent = this;
      this.children.push(item);
    }
  }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  closest(selector) {
    for (let el = this; el instanceof El; el = el.parent) if (matches(el, selector)) return el;
    return null;
  }
}

const h = (tag, props, ...kids) => new El(tag, props, kids);

function find(el, pred) {
  if (!(el instanceof El)) return null;
  if (pred(el)) return el;
  for (const child of el.children) {
    const hit = find(child, pred);
    if (hit) return hit;
  }
  return null;
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

function advancement() {
  return {
    cl: 10, realm: 'Mortal', paths: [], spheres: [], talents: [], forge: { available: false },
    added: { spheres: [], talents: [], forged: [] },
    learning_choices: [{
      source_id: METHOD, name: 'Saber-Line Method', selected: null,
      description: 'Choose one qualifying weapon to learn proficiency with, at no cost.',
      options: [{ item_id: DAO, name: 'Dao' }],
      // A GM Sabers ruling on a non-printed blade stays correctable, so it must be offered here.
      ambiguous: [{ item_id: BLADE, name: 'Fixture blade' }],
    }],
  };
}

test('Grow offers the learning choice and the GM correction of an unsealed ruling, and posts them', async () => {
  const data = advancement();
  const posts = [];
  const toasts = [];
  const deps = {
    h,
    $: id => byId.get(id) ?? null,
    toast: (...args) => toasts.push(args),
    reloadSheet: async () => {},
    projectId: () => 'abadcafe-0000-4000-8000-000000000015',
    fetchJson: async (url, opts) => {
      if (url === '/api/session') return { token: 'T' };
      if (url.endsWith('/advancement')) return data;
      if (url.endsWith('/learning-choice')) { posts.push(JSON.parse(opts.body)); return data; }
      throw new Error('unexpected request ' + url);
    },
  };
  const root = new El('div', { id: 'grow-root' });
  byId.set('grow-root', root);
  initGrow(deps);
  await loadGrow();

  // The player's own choice, without the GM override.
  const choose = find(root, el => el.dataset.learningSource === METHOD);
  assert.ok(choose, 'the learning choice button is shown');
  root.listeners.click({ target: choose });
  await tick();
  assert.deepEqual(posts.at(-1), { source_id: METHOD, item_id: DAO, gm: false, gm_sphere: '' });

  // The GM correction: the blade the GM ruled Sabers must be offered and re-rulable.
  const gmBox = byId.get('grow-gm');
  assert.ok(gmBox, 'the GM override is shown');
  gmBox.checked = true;
  root.listeners.change({ target: gmBox });
  const itemSelect = byId.get('ruling-item-' + METHOD);
  assert.ok(itemSelect, 'the GM correction selector is shown');
  assert.ok(itemSelect.children.some(o => o.props.value === BLADE), 'the unsealed blade is correctable');
  itemSelect.value = BLADE;
  byId.get('ruling-sphere-' + METHOD).value = 'axes';
  const record = find(root, el => el.dataset.rulingSource === METHOD);
  assert.ok(record, 'the GM record button is shown');
  root.listeners.click({ target: record });
  await tick();
  assert.deepEqual(posts.at(-1), { source_id: METHOD, item_id: BLADE, gm: true, gm_sphere: 'axes' });
  assert.deepEqual(toasts, []);
});


test('an owner who has not chosen sees the no-proficiency notice (finding 2) and plain GM wording (finding 5)', async () => {
  const data = advancement();
  data.learning_choices[0].notice = 'You have not chosen your Saber-Line Method weapon yet, so it gives you no proficiency. Choose one qualifying saber below. Choosing does not give you the weapon.';
  const deps = {
    h,
    $: id => byId.get(id) ?? null,
    toast: () => {},
    reloadSheet: async () => {},
    projectId: () => 'abadcafe-0000-4000-8000-000000000015',
    fetchJson: async (url) => {
      if (url === '/api/session') return { token: 'T' };
      if (url.endsWith('/advancement')) return data;
      throw new Error('unexpected request ' + url);
    },
  };
  const root = new El('div', { id: 'grow-root' });
  byId.set('grow-root', root);
  initGrow(deps);
  await loadGrow();

  const notice = find(root, el => el.tag === 'p' && el.props.class === 'grow-learning-notice');
  assert.ok(notice, 'the learning row shows the notice when no choice is made');
  assert.match(notice.children.join(''), /no proficiency/);

  const gmSummary = find(root, el => el.tag === 'summary' && el.children.some(c => typeof c === 'string' && c.includes('GM:')));
  assert.ok(gmSummary, 'the GM ruling panel is shown');
  const text = gmSummary.children.join(' ');
  assert.doesNotMatch(text, /curved|chopping/, 'the GM text drops the jargon');
  assert.match(text, /Sabers talents/);
});
