// Execute the actual Items renderer with a tiny DOM adapter; no browser needed.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../static/tabletop/items.js', import.meta.url), 'utf8');
const { initItems, renderItems } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const sheet = JSON.parse(readFileSync(0, 'utf8'));
const root = { addEventListener() {}, replaceChildren(...children) { this.children = children; } };
const h = (tag, attrs, ...children) => ({tag, attrs, children});
initItems({h, $: () => root, sheet: () => sheet});
renderItems();
assert.ok(JSON.stringify(root.children).includes(sheet.equipment.armor_note));
assert.ok(sheet.equipment.items.some(item => !item.worn && item.kind === 'armor'));
console.log('Items renderer: carried-armour note visible');
