// Exercise the actual Items renderer and command submission without a browser.
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
const source = await readFile(new URL("../static/tabletop/items.js", import.meta.url), "utf8");
const {initItems, renderItems} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const elements = new Map();
function h(tag, props, ...children) {
  const node = {tag, props: props || {}, children: children.flat().filter(x => x != null), events: {},
    addEventListener(name, callback) { this.events[name] = callback; },
    replaceChildren(...values) { this.children = values; },
    querySelectorAll(selector) { const out = []; const visit = n => {
      if (!n || typeof n !== "object") return;
      if (n.tag === selector) out.push(n);
      n.children.forEach(visit);
    }; this.children.forEach(visit); return out; }};
  if (props?.id) elements.set(props.id, node);
  return node;
}
elements.set("items-root", h("div"));
const commands = Array.from({length: 80}, (_, n) => ({operation: "armor.fit.start",
  parameters: {item_key: `given.${n}`}, label: `Fit named suit ${n}: begin 10 minutes of fitting`}));
commands.push({operation: "armor.ease.choose", parameters: {category: "medium"}, label: "Armor Ease: medium armor"});
let revision = 7;
const posts = [];
const errors = [];
initItems({h, $: id => elements.get(id), projectId: () => "hero", sheet: () => ({equipment: {items: []}}),
  toast: (...args) => errors.push(args), fetchJson: async (url, options) => {
    if (url === "/api/session") return {token: "test-token"};
    assert.equal(url, "/api/tabletop/characters/hero/preparation");
    if (options) { posts.push(JSON.parse(options.body)); revision++; }
    return {state: {revision, armor: {ready: posts.length ? 1 : 0}}, commands};
  }});
renderItems();
await new Promise(resolve => setImmediate(resolve));
const panel = elements.get("preparation-root");
assert.equal(panel.querySelectorAll("button").length, 81, "Every suit remains reachable, including an empty creation kit");
panel.querySelectorAll("button")[79].events.click();
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(posts, [{operation: "armor.fit.start", parameters: {item_key: "given.79"}, expected_revision: 7}]);
assert.equal(errors.length, 0);
assert.equal(panel.querySelectorAll("button").length, 81);
console.log("PASS Items preparation renders every named choice and submits revision-checked commands");
