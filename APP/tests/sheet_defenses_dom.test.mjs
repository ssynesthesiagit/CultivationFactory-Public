// Runs the actual table message builder and sheet DOM renderer without a live
// service: the Defences card's Resistances, Vulnerabilities and Immunities
// (owner 2026-10-12, RESIST) come from the same defence rows the fight's
// damage resolution weighs, each with the ability or condition that grants it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const table = fs.readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
const sheet = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
function section(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `Missing source boundary: ${start}`);
  return source.slice(from, to);
}

class Element {
  constructor(tag) {
    this.tagName = tag; this.attributes = {}; this.children = [];
    this.dataset = {}; this.style = {setProperty() {}}; this.classList = {toggle() {}};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(""); }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      if (selector.startsWith(".") && child.className?.split(" ").includes(selector.slice(1))) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}

function renderer(actor) {
  const defenses = new Element("div");
  const state = {
    summary: {armor_class: 17, armor_note: "Cover and defenses against a particular attack are checked when that attack resolves."},
    connected: true, actor: null,
  };
  const context = vm.createContext({
    Node: Element,
    document: {createElement: tag => new Element(tag)},
    $: id => id === "defenses" ? defenses : null,
    state, app: {state: null, matchId: "test-match"}, conditionInfo: {rows: {}},
    presentation: () => null, conditionTone: () => "buff", isManualActor: () => true,
  });
  vm.runInContext([
    section(table, "const shownCondition =", "// Buffs green"),
    section(table, "const TONE_MEANING =", "function conditionText(row)"),
    section(table, "function conditionText(row)", "// The combat log"),
    section(table, "function actorMessage(actor)", "function broadcastActors()"),
    section(sheet, "function h(tag, attrs, ...kids)", "function icon("),
    section(sheet, "const norm = ", "\n"),
    section(sheet, "function resourcePools(s)", "function renderSaves()"),
    section(sheet, "function defenseTip(row)", "function renderDefenses()"),
    section(sheet, "function renderDefenses()", "function renderSkills()"),
  ].join("\n"), context);
  context.actor = actor;
  const message = vm.runInContext("actorMessage(actor)", context);
  // JSON round trip also guards against relying on references across the channel.
  state.actor = JSON.parse(JSON.stringify(message));
  vm.runInContext("renderDefenses()", context);
  return {state, defenses};
}

const actor = {
  entity_id: "actor:test", hit_points: {current: 10, maximum: 10},
  conditions: [], resources: [], speed_ft: 30,
  damage_defenses: {
    resistances: [
      {damage_type: "Fire", source: "Inner Demon Incarnation", until: null, note: null},
      {damage_type: "Cold", source: "Diamond Rime Body", until: "until the start of your next turn", note: null},
    ],
    vulnerabilities: [{damage_type: "Lightning", source: "Shock Weakness", until: null, note: null}],
    immunities: [
      {damage_type: "Poison", source: "Stone Skin", until: null, note: null},
      {condition: "Frightened", source: "Iron Will", until: null, note: null},
    ],
    reductions: [{damage_type: "Bludgeoning damage reduced by 4", source: "Body Conditioning", until: null, note: null}],
  },
};

test("the Defences card lists Resistances, Vulnerabilities and Immunities with their source", () => {
  const {state, defenses} = renderer(actor);
  // the table message carries the card's data across the channel
  assert.deepEqual(state.actor.damage_defenses, actor.damage_defenses);
  const labels = defenses.querySelectorAll(".def-label").map(el => el.textContent);
  assert.ok(labels.includes("Resistances"), `no Resistances section: ${labels}`);
  assert.ok(labels.includes("Vulnerabilities"), `no Vulnerabilities section: ${labels}`);
  assert.ok(labels.includes("Immunities"), `no Immunities section: ${labels}`);
  assert.ok(labels.includes("Damage reduction"), `no Damage reduction section: ${labels}`);
  const pills = defenses.querySelectorAll(".cond");
  const byText = Object.fromEntries(pills.map(pill => [pill.textContent, pill]));
  assert.deepEqual(pills.map(pill => pill.textContent),
    ["Fire", "Cold", "Lightning", "Poison", "Frightened", "Bludgeoning damage reduced by 4"]);
  assert.equal(byText["Bludgeoning damage reduced by 4"].dataset.tip, "from Body Conditioning");
  assert.equal(byText["Fire"].dataset.tip, "from Inner Demon Incarnation");
  assert.equal(byText["Cold"].dataset.tip, "from Diamond Rime Body — until the start of your next turn");
  assert.equal(byText["Lightning"].dataset.tip, "from Shock Weakness");
  assert.equal(byText["Poison"].dataset.tip, "from Stone Skin");
  assert.equal(byText["Frightened"].dataset.tip, "from Iron Will");
  // a resistance reads as a good thing, a vulnerability as a bad one
  assert.ok(byText["Fire"].className.split(" ").includes("beneficial"));
  assert.ok(byText["Lightning"].className.split(" ").includes("harmful"));
  // the card says a particular attack can still ignore or pierce the resistances, and only those
  const notes = defenses.querySelectorAll(".def-note").map(el => el.textContent);
  assert.equal(notes.filter(text => /may ignore or pierce these/.test(text)).length, 1);
  const pierceAt = defenses.children.findIndex(el => /may ignore or pierce/.test(el.textContent));
  const reductionAt = defenses.children.findIndex(el => el.querySelector?.(".def-label")?.textContent === "Damage reduction");
  assert.ok(pierceAt >= 0 && pierceAt < reductionAt, "pierce note must not sit on the reduction group");
});

test("a sheet with only a flat reduction shows no pierce note", () => {
  const {defenses} = renderer({...actor, damage_defenses: {
    resistances: [], vulnerabilities: [], immunities: [],
    reductions: [{damage_type: "Bludgeoning damage reduced by 4", source: "Body Conditioning", until: null, note: null}]}});
  const labels = defenses.querySelectorAll(".def-label").map(el => el.textContent);
  assert.deepEqual(labels.filter(label => !label.startsWith("Armor Class") && label !== "Conditions"), ["Damage reduction"]);
  assert.doesNotMatch(defenses.textContent, /may ignore or pierce/);
});

test("the Defences card hides the new sections when the creature has none", () => {
  const {defenses} = renderer({...actor, damage_defenses: {resistances: [], vulnerabilities: [], immunities: []}});
  const labels = defenses.querySelectorAll(".def-label").map(el => el.textContent);
  assert.ok(!labels.includes("Resistances") && !labels.includes("Vulnerabilities") && !labels.includes("Immunities")
    && !labels.includes("Damage reduction"),
    `empty sections still shown: ${labels}`);
  assert.doesNotMatch(defenses.textContent, /A particular attack may ignore or pierce these/);
  // a sheet that never got the payload (an older table) renders as nothing to list
  const bare = renderer({...actor, damage_defenses: null});
  assert.doesNotMatch(bare.defenses.textContent, /Resistances|Vulnerabilities|Immunities/);
});
