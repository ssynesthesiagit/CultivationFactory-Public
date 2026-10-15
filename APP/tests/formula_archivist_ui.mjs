// Minimal DOM contract harness for the actual production Grow/procedure modules.
// No Chromium, Playwright, network, model, timers or application server.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const menus = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag, attrs = {}, children = []) {
    this.tag = tag; Object.assign(this, attrs); this.attrs = attrs || {};
    this.children = children.filter(x => x != null); this.listeners = {};
    this.value ??= tag === 'select' ? this.children[0]?.value || '' : '';
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  append(...children) { this.children.push(...children.filter(x => x != null)); }
  replaceChildren(...children) { this.children = children; }
  reportValidity() { return true; }
  reset() { for (const e of walk(this)) if (e.tag === 'input') e.value = ''; }
}
function h(tag, attrs, ...children) { return new Element(tag, attrs, children); }
function walk(root) { return [root, ...root.children.filter(c => c instanceof Element).flatMap(walk)]; }
const root = h('div', {id: 'grow-root'});
let menu = menus[0], reloads = 0;
const requests = [];
const fetchJson = async (url, options) => {
  requests.push({url, options});
  if (url === '/api/session') return {token: 'offline'};
  if (url.endsWith('/advancement')) return {cl: 8, realm: 'Foundation', paths: [], forge: {available: false}};
  if (url.endsWith('/providers')) return {providers: []};
  if (!options) return {procedures: [menu]};
  if (url.endsWith('/suggest')) return {values: {formula_id: menu.grants[0].options.at(-1).id}};
  return {status: JSON.parse(options.body).preview ? 'PREVIEW' : 'COMMITTED'};
};
const context = vm.createContext({console, crypto: webcrypto});
vm.runInContext(fs.readFileSync(new URL('../static/tabletop/procedures.js', import.meta.url), 'utf8').replace(/^export /mg, ''), context);
vm.runInContext(fs.readFileSync(new URL('../static/tabletop/grow.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/mg, '').replace(/^export /mg, ''), context);
const deps = {h, $: id => walk(root).find(n => n.id === id), fetchJson, projectId: () => 'aaaaaaaa',
  toast: () => {}, reloadSheet: async () => { reloads++; }};
context.initGrow(deps);
await context.loadGrow();
function formWith(label) { return walk(root).find(n => n.tag === 'form' && n.children[0].children[0].includes(label)); }
let form = formWith('additional Common');
let select = walk(form).find(n => n.name === 'formula_id');
assert.equal(select.children.length, menu.grants[0].options.length);
select.value = select.children.at(-1).value;
await form.listeners.submit({preventDefault() {}});
await new Promise(resolve => setImmediate(resolve));
let posted = requests.find(r => r.options && r.url.endsWith('/procedures'));
assert.equal(JSON.parse(posted.options.body).payload.formula_id, menu.grants[0].options.at(-1).id);
assert.equal(reloads, 1);
assert.equal(JSON.parse(posted.options.body).gm, false);
form = formWith('additional Common');
const before = requests.filter(r => r.options).length;
walk(form).find(n => n.tag === 'button' && n.children[0] === 'Cancel / clear').listeners.click();
assert.equal(requests.filter(r => r.options).length, before);
await walk(form).find(n => n.tag === 'button' && n.children[0] === 'Preview without saving').listeners.click();
await new Promise(resolve => setImmediate(resolve));
assert.equal(JSON.parse(requests.filter(r => r.options && r.url.endsWith('/procedures')).at(-1).options.body).preview, true);
assert.equal(reloads, 1);
await walk(form).find(n => n.tag === 'button' && n.children[0] === 'Ask preparation seat to choose').listeners.click();
assert.equal(walk(form).find(n => n.name === 'formula_id').value, menu.grants[0].options.at(-1).id);
menu = menus[1]; await context.loadGrow();
form = formWith('report the crafting check');
assert.deepEqual(walk(form).find(n => n.name === 'ability').children.map(n => n.value), ['INT', 'WIS']);
menu = menus[2]; await context.loadGrow();
form = formWith('decide before failure');
assert.deepEqual(walk(form).find(n => n.name === 'decision').children.map(n => n.value), ['reroll', 'decline']);
console.log('Production Grow UI: complete choices, submit, preview/cancel, seat suggestions and Path forms PASS');
