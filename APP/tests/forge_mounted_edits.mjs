// Offline DOM contract for Grow Forge. No browser, network or model server.
import fs from "node:fs";
import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";

class Element {
  constructor(tag, props = {}, children = []) {
    this.tag = tag;
    this.dataset = props.dataset || {};
    this.children = [];
    this.parentElement = null;
    Object.assign(this, props);
    this.hidden = Boolean(props.hidden);
    this.checked = Boolean(props.checked);
    this.disabled = Boolean(props.disabled);
    this.append(...children.flat(Infinity).filter(x => x != null && x !== false));
  }
  append(...children) {
    for (const child of children) this.appendChild(child);
  }
  appendChild(child) {
    if (child && typeof child === "object") {
      if (child.parentElement) {
        const previous = child.parentElement.children;
        previous.splice(previous.indexOf(child), 1);
      }
      child.parentElement = this;
    }
    this.children.push(child);
    return child;
  }
  replaceChildren(...children) {
    for (const child of this.children) if (child && typeof child === "object") child.parentElement = null;
    this.children = [];
    this.append(...children);
  }
  querySelectorAll(selector) {
    const matches = (node) => {
      if (selector.startsWith("#")) return node.id === selector.slice(1);
      const m = selector.match(/^(\w+)?\[data-([a-z-]+)\]$/);
      if (!m) throw new Error("Unsupported test selector: " + selector);
      const key = m[2].replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return (!m[1] || node.tag === m[1]) && Object.hasOwn(node.dataset, key);
    };
    const out = [];
    function walk(node) {
      for (const child of node.children || []) {
        if (!child || typeof child !== "object") continue;
        if (matches(child)) out.push(child);
        walk(child);
      }
    }
    walk(this);
    return out;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const h = (tag, props, ...children) => new Element(tag, props || {}, children);
const text = (node) => typeof node === "object" ? (node.children || []).map(text).join("") : String(node);
const visible = (node) => node && !node.hidden && (!node.parentElement || visible(node.parentElement));

(async () => {
  let source = fs.readFileSync(process.argv[2], "utf8");
  source += '\n;globalThis.__grow = { setDeps: v => { deps = v; }, setData: v => { data = v; },' +
    ' setForge: v => { forge = v; }, setPreview: v => { preview = v; }, forgeBlock, refreshForgeInPlace, onChange };';
  global.fetch = () => { throw new Error("Forge edits must not fetch"); };
  await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
  const G = globalThis.__grow;
  const fixture = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
  const host = h("main", { id: "grow-root" });
  host.replaceChildren = () => { throw new Error("Forge edits must not render/replace Grow"); };
  const sibling = h("details", { open: false, scrollTop: 17 });
  host.appendChild(sibling);
  let gmOn = false;
  G.setDeps({ h, $: id => id === "grow-gm" ? { checked: gmOn } : id === "grow-root" ? host : host.querySelector("#" + id),
    fetchJson: () => { throw new Error("Forge edits must not post"); } });
  const state = { name: "Persistent name", base_form: "strike", primary_talent_id: "FIRE_TAL_FLAME_LASH",
    secondary_talent_ids: [], augment_ids: [], drawback_ids: [], choices: {} };
  G.setForge(state);
  G.setData({ forge: fixture });
  const root = G.forgeBlock();
  host.appendChild(root);
  G.refreshForgeInPlace();
  const byId = id => host.querySelector("#" + id);
  const controls = ["forge-form", "forge-primary", "forge-name"].map(byId);
  const [form, primary, name] = controls;
  const inputs = root.querySelectorAll("input[data-forge-pick]");
  const secondary = id => inputs.find(x => x.dataset.forgePick === "secondary" && x.dataset.id === id);
  const augmented = inputs.find(x => x.dataset.forgePick === "augment");
  const preview = byId("grow-forge-preview");
  root.open = false;
  root.scrollTop = 211;
  name.value = "Persistent name";
  function unchanged() {
    assert.equal(byId("grow-forge"), root);
    assert.equal(root.open, false);
    assert.equal(root.scrollTop, 211);
    assert.equal(sibling.open, false);
    assert.equal(sibling.scrollTop, 17);
    assert.equal(name.value, "Persistent name");
    controls.forEach((el, i) => assert.equal(byId(["forge-form", "forge-primary", "forge-name"][i]), el));
    inputs.forEach(el => assert.ok(root.querySelectorAll("input[data-forge-pick]").includes(el)));
  }
  function checkedPreview() {
    G.setPreview({ error: "Old Check result" });
    preview.appendChild(h("p", {}, "Old Check result"));
  }
  // First edit after Check must not render the tab, including an Augment edit.
  checkedPreview();
  augmented.checked = true;
  G.onChange({ target: augmented });
  assert.equal(preview.children.length, 0);
  const choice = byId("grow-forge-choices").querySelector("[data-forge-choice]");
  assert.ok(choice);
  choice.value = "blinded";
  G.onChange({ target: choice });
  unchanged();

  checkedPreview();
  form.value = "ward";
  G.onChange({ target: form });
  assert.equal(preview.children.length, 0);
  assert.equal(byId("grow-forge-choices").querySelector("[data-forge-choice]"), choice);
  assert.equal(choice.value, "blinded");
  const arrow = secondary("TAL_AIR_ARROW_TURNING_BREATH");
  assert.ok(!visible(arrow.parentElement), "dropped Ward payload must be hidden");
  assert.match(byId("grow-forge-hidden").textContent, /effects? hidden/);
  unchanged();

  checkedPreview();
  primary.value = "DISEASE_BASE_SOW_THE_FEVER_SEED";
  G.onChange({ target: primary });
  assert.equal(preview.children.length, 0);
  const poison = secondary("POISON_BASE_DELIVER_THE_DOSE");
  const disease = secondary("DISEASE_BASE_SOW_THE_FEVER_SEED");
  assert.ok(!visible(disease.parentElement), "Primary Sphere must be excluded from Secondaries");
  assert.ok(!visible(poison.parentElement), "unsupported Poison consequence must be hidden");
  assert.match(poison.parentElement.title, /Constitution save/);
  assert.equal(poison.parentElement.dataset.tip, poison.parentElement.title);
  assert.match(text(poison.parentElement), /\(base ability\)/);
  assert.match(text(primary), /Sow the Fever Seed \(base ability\)/);
  assert.match(text(primary), /Deliver the Dose \(base ability\)/);
  unchanged();

  // The very same hidden input remains reachable under GM override.
  gmOn = true;
  G.refreshForgeInPlace();
  assert.ok(visible(poison.parentElement));
  assert.equal(poison.parentElement.parentElement, byId("grow-forge-gm-chips"));
  assert.equal(poison.disabled, false);
  checkedPreview();
  poison.checked = true;
  G.onChange({ target: poison });
  assert.deepEqual(state.secondary_talent_ids, ["POISON_BASE_DELIVER_THE_DOSE"]);
  assert.equal(preview.children.length, 0);
  unchanged();

  // Form changes preserve GM choices even when the ordinary fit table hides them.
  form.value = "movement";
  G.onChange({ target: form });
  assert.equal(poison.checked, true);
  unchanged();
  // Time the ordinary (non-GM) path, including limit arithmetic, actual change
  // handlers and mounted DOM updates over >=60 chips, not just arithmetic.
  gmOn = false;
  state.secondary_talent_ids = ["TAL_AIR_ARROW_TURNING_BREATH"];
  form.value = "strike";
  G.onChange({ target: form });
  assert.ok(fixture.sources.length >= 60);
  const times = [];
  for (let i = 0; i < 9; i++) {
    augmented.checked = !augmented.checked;
    const start = performance.now();
    G.onChange({ target: augmented });
    times.push(performance.now() - start);
  }
  const median = times.sort((a, b) => a - b)[4];
  assert.ok(median < 16, "60-chip mounted handler took " + median + "ms");
  unchanged();
  console.log("mounted Forge edits: PASS; median handler " + median.toFixed(3) + " ms");
})().catch(error => { console.error(error.stack || error); process.exit(1); });
