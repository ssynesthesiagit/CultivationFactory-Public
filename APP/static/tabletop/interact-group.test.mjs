// node --test APP/static/tabletop/interact-group.test.mjs
// A map object the actor can use (the Meditation room door) is drawn in an "Interact" group right after Move,
// not in the "No action" economy bucket. Runs the shipped renderActionBar through the shared bar fixture.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {FakeElement} from '../../tests/attacklist1_dom.mjs';
import {renderBarFixture} from '../../tests/actionbar_fixture.mjs';

class Element extends FakeElement {
  set innerHTML(markup) {
    this.markup = markup;
    this.replaceChildren();
    for (const [, tag, attrs, text] of markup.matchAll(/<(\w+)\b([^>]*)>([^<]*)/g)) {
      const node = new Element(tag);
      node.className = /class="([^"]*)"/.exec(attrs)?.[1] || '';
      if (tag === 'h3') node.textContent = text;  // the group title is set through innerHTML, as in the shipped code
      this.appendChild(node);
    }
  }
  get nextSibling() {
    const siblings = this.parent ? this.parent.children : [];
    return siblings[siblings.indexOf(this) + 1] ?? null;
  }
  get innerHTML() { return this.markup || ''; }
  get lastChild() { return this.children.at(-1); }
  hasAttribute(name) {
    if (name.startsWith('data-')) return this.matches('[' + name + ']');
    return super.hasAttribute(name);
  }
  getBoundingClientRect() { return {left: 0, top: 0, width: 100, height: 40}; }
  insertBefore(node, before) {
    const at = before ? this.children.indexOf(before) : -1;
    node.parent = this;
    if (at === -1) this.children.push(node); else this.children.splice(at, 0, node);
    return node;
  }
}

const door = {source_definition_id: 'system:door.open.free', label: 'Open Door (free interaction)', economy: 'NONE',
  target_kind: 'OBJECT', description: 'Open an unlocked, unstuck door within 5 feet.',
  options: [{candidate_id: 'open-1', target_ids: ['object:map.1']}]};

async function drawBar(extraRows) {
  const document = {createElement: tag => new Element(tag), createTextNode: text => String(text)};
  const bar = document.createElement('footer');
  bar.id = 'ttActionBar';
  bar.ownerDocument = document;
  const source = readFileSync(new URL('./tabletop.js', import.meta.url), 'utf8');
  const hover = {player_card: {text: 'card text', html: '<b>card text</b>'}};
  await renderBarFixture(document, bar, source, hover, extraRows);
  return bar;
}

// Each group is an .tt-ab-group; its title is the h3 text, its buttons are the .tt-btn labels.
const groupsOf = bar => bar.querySelectorAll('.tt-ab-group').map(group => ({
  title: group.querySelector('h3').textContent,
  node: group,
  labels: group.querySelectorAll('button').map(button => button.querySelector('b').textContent),
}));

test('the door is drawn in an Interact group that sits right after Move, not in No action', async () => {
  const bar = await drawBar([door]);
  const groups = groupsOf(bar);
  const interact = groups.find(group => group.title === 'Interact');
  assert.ok(interact, 'an Interact group exists for the OBJECT row');
  assert.deepEqual(interact.labels, ['Open Door (free interaction)']);
  const titles = groups.map(group => group.title);
  assert.equal(titles[titles.indexOf('Interact') - 1], 'Move', 'Interact is the next sibling of Move');
  assert.equal(groups.find(group => group.title === 'No action'), undefined, 'the door is not a No action row');
  for (const group of groups.filter(group => group.title !== 'Interact')) {
    assert.ok(!group.labels.includes('Open Door (free interaction)'), group.title + ' must not hold the door');
  }
});

test('no Interact group is drawn when no OBJECT row is legal', async () => {
  const bar = await drawBar([]);
  assert.equal(groupsOf(bar).some(group => group.title === 'Interact'), false);
});
