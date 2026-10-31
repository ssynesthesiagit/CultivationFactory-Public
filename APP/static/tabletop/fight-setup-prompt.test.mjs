import test from "node:test";
import assert from "node:assert/strict";
import {renderFightSetup} from "./fight-setup-prompt.js";

test("pending setup names the other owner and invokes the issued action", () => {
  class Element {
    constructor(doc) { this.ownerDocument = doc; this.children = []; this.handlers = {}; }
    setAttribute() {}
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
  }
  const doc = {createElement: () => new Element(doc)};
  const bar = new Element(doc);
  const group = {source_definition_id: "system:combat.fight_setup", options: [{candidate_id: "issued"}]};
  let submitted;
  assert.equal(renderFightSetup(bar, ["other"], {actions: [group]},
    id => ({other: {display_name: "Gongsun"}}[id]), row => { submitted = row; }, false), true);
  const [title, detail, button] = bar.children[0].children;
  assert.equal(title.textContent, "Finish fight setup");
  assert.match(detail.textContent, /Gongsun/);
  button.handlers.click();
  assert.equal(submitted, group);
  assert.equal(renderFightSetup(bar, [], {actions: [group]}, () => null, () => {}, false), false);
});
