// Exercise the real Items renderer without a browser. Native replaceChildren
// converts null to text, unlike the application h helper's child filtering.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../static/tabletop/items.js', import.meta.url), 'utf8');
const { initItems, renderItems } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const root = {
  addEventListener() {},
  replaceChildren(...children) { this.children = children.map(child => child && typeof child === 'object' ? child : String(child)); }
};
const h = (tag, attrs, ...children) => ({ tag, attrs, children: children.filter(child => child !== null && child !== undefined) });
for (const notes of [false, true]) {
  const sheet = {
    equipment: { items: [{ key: 'bow', name: 'Bow', quantity: 1, weight_lb: 2 }],
                 ...(notes ? { armor_note: 'Carried armour is not worn.' } : {}) },
    carrying: { unweighed: notes ? ['Quiver'] : [] }
  };
  initItems({ h, $: () => root, sheet: () => sheet });
  renderItems();
  assert.ok(root.children.every(child => typeof child !== 'string'), 'replaceChildren received an absent note as literal text');
  const content = JSON.stringify(root.children);
  assert.ok(content.includes('Bow'));
  assert.equal(content.includes('Carried armour is not worn.'), notes);
  assert.equal(content.includes('Not weighed: Quiver.'), notes);
}
