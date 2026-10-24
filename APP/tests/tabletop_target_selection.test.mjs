import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import {reactionCardHarness} from './reaction_card_harness.mjs';

const source = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
const diceSource = readFileSync(new URL("../static/tabletop/dice3d.js", import.meta.url), "utf8");

function declaration(name) {
  let start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is present`);
  // Keep the keyword: pickTarget awaits the action, and a slice without it is not valid source.
  if (source.slice(start - 6, start) === "async ") start -= 6;
  const open = source.indexOf(") {", start) + 2;
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`Unclosed function ${name}`);
}

function harness() {
  const calls = [];
  // useGroup closes the table's open choice when an action needs no further choice, and announces an
  // open one on the BroadcastChannel. This file tests target selection, so the channel is a no-op --
  // but closeChoice and actOnce are the real ones, so the target logic under test is not faked.
  const app = {busy: false, state: {}, menu: {actor_id: "actor"}, selected: new Set(), lastTarget: "old-target",
               targeting: null, pendingChoice: null};
  const context = {
    app, calls, messages: [], actors: () => [], board: {cellAt: () => null}, objectById: () => null,
    act: async candidate => { calls.push(candidate); return true; },
    // The player's view is available here, so the covered-view guard stands aside.
    currentViewer: () => ({ready: true}),
    toast(message) { context.messages.push(message); }, hint(text) { context.hintText = text; }, renderHighlights() {}, renderTokens() {}, renderRoster() {}, renderInspector() {},
    broadcastActors() {}, renderShapePanel() {}, renderActionBar() {},
    chooseFromList() { throw new Error("unexpected list"); },
  };
  for (const name of ["refuseCoveredView", "closeChoice", "cancelTargeting", "abilityChoiceActive", "abilityReserved", "releaseMapPick", "cancelAbilityChoice", "reactionMenuAnswers", "reactionMenuMapAnswer", "actOnce", "preferredTargets", "useGroup", "onTokenClick", "selectActor", "pickTarget", "pickObjectInSquare", "targetChoiceAt", "takeTargetChoice"]) {
    runInNewContext(declaration(name), context);
  }
  return {app, calls, context};
}

for (const preferred of [false, true]) {
  test(`roll reasons are reviewed before ${preferred ? 'preferred' : 'single'} target commits`, async () => {
    const {context, calls} = harness();
    let reviewed;
    context.chooseFromList = async (group, options) => { reviewed = options; return false; };
    const option = {candidate_id: 'canopy-shot', target_ids: ['target'],
      roll_previews: {target: {mode: 'DISADVANTAGE', text: 'Disadvantage: canopy between you and the target'}}};
    const group = {label: 'Dagger thrown', options: preferred
      ? [option, {candidate_id: 'other', target_ids: ['other']}] : [option]};
    await context.useGroup(group, preferred ? {preferTargets: ['target']} : {});
    assert.equal(reviewed[0], option);
    assert.deepEqual(calls, []);
  });
}

test('roll labels expose each source and explain cancellation on hover', () => {
  globalThis.document = {createElement: () => ({className: '', textContent: '', title: ''})};
  const sources = [
    {kind: 'advantage', effect: 'Rallying Standard', owner: 'Mira', why: 'the banner grants Advantage'},
    {kind: 'disadvantage', effect: 'Poisoned', owner: 'Oren', why: 'the attacker is Poisoned'},
  ];
  const label = rollModeLabel('NORMAL', sources);
  assert.equal(label.textContent, 'Normal roll');
  assert.match(label.title, /Advantage.*cancels Disadvantage/);
  assert.match(label.title, /Rallying Standard \(Mira\)/);
  assert.match(label.title, /Poisoned \(Oren\)/);
  assert.match(rollModeHover('DISADVANTAGE', sources), /Disadvantage — Poisoned/);
});

test('hovering a legal target shows its roll sources before commitment', () => {
  const {app, context, calls} = harness();
  context.actors = () => [{entity_id: 'target', active: true, position: {x: 3, y: 4}}];
  app.targeting = {group: {label: 'Dagger thrown'}, hintText: 'Choose target',
    byTarget: new Map([['target', [{roll_previews: {target: {text: 'Disadvantage from Canopy of Ten Thousand Leaves'}}}]]])};
  runInNewContext(declaration('onCellHover'), context);
  context.onCellHover({x: 3, y: 4});
  assert.match(context.hintText, /Canopy of Ten Thousand Leaves/);
  assert.deepEqual(calls, []);
});

test("selecting a different token discards the cached target and uses the legal selection", async () => {
  const {app, calls, context} = harness();
  context.onTokenClick("new-target", {shiftKey: false});
  assert.equal(app.lastTarget, null);
  assert.deepEqual(Array.from(context.preferredTargets()), ["new-target"]);

  const group = {label: "Test action", options: [
    {candidate_id: "old-candidate", target_ids: ["old-target"]},
    {candidate_id: "new-candidate", target_ids: ["new-target"]},
  ]};
  await context.useGroup(group, {preferTargets: context.preferredTargets()});
  assert.deepEqual(calls, ["new-candidate"]);
  assert.equal(app.targeting, null);
});

for (const kind of ["target", "area", "destination"]) {
  for (const focused of [null, "select", "input", "dialog"]) {
    test(`Escape cancels ${kind} picking with ${focused || 'map'} focus and spends nothing`, async () => {
      const {app, calls, context} = harness();
      let keydown;
      context.document = {addEventListener: (_, handler) => { keydown = handler; }};
      const start = source.indexOf('document.addEventListener("keydown", event => {');
      runInNewContext(source.slice(start, source.indexOf('// Keep a watching table in step', start)), context);
      const options = [1, 2].map(i => ({candidate_id: `choice-${i}`, target_ids: kind === "target" ? [`foe-${i}`] : [],
        ...(kind === "area" ? {area: {center: {x: i, y: 1}}} : {}),
        ...(kind === "destination" ? {destination: {x: i, y: 1}} : {})}));
      const pending = context.useGroup({label: "Test ability", options});
      assert.ok(app.targeting);
      let prevented = false;
      keydown({key: "Escape", target: {closest: () => focused}, preventDefault() { prevented = true; }});
      assert.equal(await pending, false);
      assert.equal(app.targeting, null);
      assert.equal(app.pendingChoice, null);
      assert.equal(context.hintText, null);
      assert.deepEqual(calls, []);
      assert.equal(prevented, true);
    });
  }
}

test("reaction menu answers preserve every Pass and bind a later mode to its own source", () => {
  const context = {};
  runInNewContext(declaration("reactionMenuAnswers"), context);
  const alternatives = ["guard", "corrupt:mode:0", "corrupt:mode:3"].map(reaction_source_id => ({
    context: {checkpoint: "TYPED:HEALED@8", reactor_id: "player", reaction_source_id}}));
  const pass = context.reactionMenuAnswers({alternatives}, -1);
  assert.equal(pass.length, 3);
  assert.ok(pass.every(d => d.selection === "DECLINE"));
  const picked = context.reactionMenuAnswers({alternatives}, 1, "USE");
  assert.equal(picked.length, 2);
  assert.equal(picked[0].selection, "DECLINE");
  assert.equal(picked[1].reaction_source_id, "corrupt:mode:0");
  assert.equal(picked[1].selection, "USE");
});

test("the reaction menu renders the complete set and Pass without an automatic answer", async () => {
  const {context, root, dialog} = reactionCardHarness();
  const alternatives = Array.from({length: 25}, (_, i) => ({reaction: `Reaction ${i}`, trigger: "Enemy heals",
    summary: "Affects Enemy until your next turn.", cost: "Reaction; 5 Qi",
    limits: "Cannot suppress artifact protections.", table_note: "The GM applies this effect manually.",
    rules: "The target makes a Charisma saving throw.",
    context: {checkpoint: "TYPED:HEALED@8", reactor_id: "player", reaction_source_id: `reaction:${i}`}}));
  let settled = false;
  const pending = context.askReactionMenu({alternatives}).then(answer => { settled = true; return answer; });
  await Promise.resolve();
  assert.equal(settled, false, "the player must explicitly answer");
  const entries = dialog.querySelectorAll('[data-reaction-entry]');
  assert.equal(entries.length, 25, "no top-N or hidden cutoff");
  const html = root.querySelector('#ttReactionText').innerHTML;
  for (const text of ['Cannot suppress artifact protections', 'GM applies this effect manually', 'Charisma saving throw']) {
    assert.equal(html.split(text).length - 1, 25, 'each response retains its qualifications');
  }
  assert.equal(dialog.querySelector('[data-answer="DECLINE"]').textContent, 'Skip');
  assert.equal(dialog.querySelector('[data-answer="USE"]').hidden, true, 'no default reaction is presented as chosen');
  dialog.querySelector('[data-reaction-use="24"]').onclick();
  const answers = await pending;
  assert.equal(answers.length, 25);
  assert.equal(answers.at(-1).reaction_source_id, "reaction:24");
  assert.equal(answers.at(-1).selection, "USE");
});

test('a reaction with spatial options opens the map, without a coordinate dropdown', async () => {
  const {context, root, dialog} = reactionCardHarness();
  const row = {reaction: 'Free step', reactor: 'Mei', cost: 'No additional cost',
    context: {checkpoint: 'step:1', reactor_id: 'actor:mei', reaction_source_id: 'choice:step'},
    choice: {minimum: 1, maximum: 1, map_pick: {},
      options: [{id: 'cell:4,6', label: 'Square 4, 6', cell: {x: 4, y: 6}}]}};
  const seen = [];
  context.askChoice = async prompt => {
    assert.equal(dialog.open, false, 'the modal must uncover the main map');
    seen.push(prompt);
    return {selection: 'USE', option_ids: ['cell:4,6']};
  };
  const pending = context.askReactionMenu({alternatives: [row]});
  assert.doesNotMatch(root.querySelector('#ttReactionText').innerHTML, /Square 4, 6|<select/);
  await dialog.querySelector('[data-reaction-use="0"]').onclick();
  const answers = await pending;
  assert.equal(seen[0], row);
  assert.deepEqual(Array.from(answers[0].option_ids), ['cell:4,6']);
  assert.equal(answers[0].reaction_source_id, 'choice:step');
});

test("Escape on the hint-bar list uses the same cancellation as its Cancel button", async () => {
  const {app, calls, context} = harness();
  const element = () => ({firstChild: {textContent: ""}, children: [],
    addEventListener(name, handler) { this[name] = handler; },
    insertBefore(child) { this.children.push(child); }, appendChild(child) { this.children.push(child); }});
  const node = element();
  context.$ = () => node;
  let keydown;
  context.document = {createElement: () => element(), addEventListener: (_, handler) => { keydown = handler; }};
  runInNewContext(declaration("chooseFromList"), context);
  const start = source.indexOf('document.addEventListener("keydown", event => {');
  runInNewContext(source.slice(start, source.indexOf('// Keep a watching table in step', start)), context);
  const pending = context.chooseFromList({label: "Ability mode"}, [{candidate_id: "one", label: "One"}]);
  assert.ok(app.listPick);
  keydown({key: "Escape", target: {closest: () => "select"}, preventDefault() {}});
  assert.equal(await pending, false);
  assert.equal(app.listPick, null);
  assert.equal(app.pendingChoice, null);
  assert.deepEqual(calls, []);
  node.children.at(-1).click();
  assert.deepEqual(calls, [], "a stale Cancel handler cannot spend anything");
});

test("Ask me hides the preset mode; automatic plans keep it", () => {
  const sheet = readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
  const start = sheet.indexOf("function renderReactions()");
  let rendered;
  const context = {
    state: {sheet: {reaction_plan: {mode: "ask", order: ["menu"], choices: [
      {id: "menu", name: "Menu reaction", options: ["First", "Second"], option: 1}]}}},
    $: id => id === "reactions-panel" ? {replaceChildren: tree => { rendered = tree; }} : null,
    h: (tag, attrs, ...children) => ({tag, attrs, children})};
  runInNewContext(sheet.slice(start, sheet.indexOf("// Companions", start)), context);
  const countPreset = tree => tree && typeof tree === "object"
    ? (tree.attrs?.class?.includes("reaction-option") ? 1 : 0) + (tree.children || []).reduce((n, c) => n + countPreset(c), 0) : 0;
  context.renderReactions();
  assert.equal(countPreset(rendered), 0);
  context.state.sheet.reaction_plan.mode = "auto";
  context.renderReactions();
  assert.equal(countPreset(rendered), 1);
});

test("an illegal current selection opens the picker instead of using the old target", async () => {
  const {app, calls, context} = harness();
  context.onTokenClick("unrelated-token", {shiftKey: false});
  const group = {label: "Test action", options: [
    {candidate_id: "old-candidate", target_ids: ["old-target"]},
    {candidate_id: "legal-candidate", target_ids: ["legal-target"]},
  ]};
  context.useGroup(group, {preferTargets: context.preferredTargets()});
  assert.deepEqual(calls, []);
  assert.ok(app.targeting);
  assert.deepEqual(Array.from(app.targeting.byTarget.keys()), ["old-target", "legal-target"]);
});

// Shatter Earth (TAL_BERSERKER_SHATTER_EARTH#opt2, a 15-ft line) offers area centres and no creature target
// per square. A character standing on one of those squares covers the square with its token, so the pointer
// lands on the token: the click must answer that square's area, not refuse it as an illegal creature target
// (owner feedback FD-9, "shatter earth isnt working on characters squares which it should").
test("a token on an occupied square resolves the area aimed at that square", () => {
  const {app, calls, context} = harness();
  const area = {candidate_id: "shatter-earth-line", target_ids: [], area: {center: {x: 3, y: 4}}};
  const resolved = [];
  app.targeting = {group: {label: "Shatter Earth"}, hintText: "choose", byTarget: new Map(),
    areas: [area], destinations: [], resolve: value => resolved.push(value)};
  context.actors = () => [{entity_id: "bystander", active: true, position: {x: 3, y: 4}}];
  context.board = {cellAt: () => ({x: 3, y: 4})};
  context.onTokenClick("bystander", {clientX: 10, clientY: 20});
  assert.deepEqual(calls, ["shatter-earth-line"], "the occupied square's area candidate is used");
  assert.equal(resolved.length, 1, "the choice settles");
  assert.deepEqual(context.messages, [], "a legal square must not be refused");
  assert.equal(app.targeting, null);
});

test("a legal creature target still wins on a token click when no area covers its square", () => {
  const {app, calls, context} = harness();
  const creature = {candidate_id: "sword-cut", target_ids: ["target"]};
  app.targeting = {group: {label: "Sword cut"}, hintText: "choose",
    byTarget: new Map([["target", [creature]]]), areas: [], destinations: [], resolve: () => {}};
  context.actors = () => [{entity_id: "target", active: true, position: {x: 5, y: 2}}];
  context.board = {cellAt: () => ({x: 5, y: 2})};
  context.onTokenClick("target", {clientX: 10, clientY: 20});
  assert.deepEqual(calls, ["sword-cut"], "the creature candidate is submitted");
  assert.deepEqual(context.messages, []);
  assert.equal(app.targeting, null);
});

test("an area aimed at an occupied square wins over the creature target there, as a square click does", () => {
  const {app, calls, context} = harness();
  const creature = {candidate_id: "sword-cut", target_ids: ["target"]};
  const area = {candidate_id: "shatter-earth-line", target_ids: ["target"], area: {center: {x: 5, y: 2}}};
  app.targeting = {group: {label: "Shatter Earth"}, hintText: "choose",
    byTarget: new Map([["target", [creature]]]), areas: [area], destinations: [], resolve: () => {}};
  context.actors = () => [{entity_id: "target", active: true, position: {x: 5, y: 2}}];
  context.board = {cellAt: () => ({x: 5, y: 2})};
  context.onTokenClick("target", {clientX: 10, clientY: 20});
  assert.deepEqual(calls, ["shatter-earth-line"], "the aimed-at area owns that square");
  assert.equal(app.targeting, null);
});

test("roster selection invalidates a cached target while an untouched combo can retain it", () => {
  const {app, context} = harness();
  assert.deepEqual(Array.from(context.preferredTargets()), ["old-target"]);
  context.selectActor("actor");
  assert.equal(app.lastTarget, null);
  assert.deepEqual(Array.from(context.preferredTargets()), ["actor"]);
  app.selected.clear();
  app.lastTarget = "combo-target";
  assert.deepEqual(Array.from(context.preferredTargets()), ["combo-target"]);
});

// Roll-mode label and hover (owner 2026-10-15 04:39Z): a visible Advantage/Disadvantage
// label on every roll surface, hovering it listing the reasons one line per source.
import {rollModeWord, rollModeHover, rollModeLabel} from "../static/tabletop/roll_mode_display.js";

const CANOPY_SOURCE = {kind: "disadvantage", effect: "Canopy of Ten Thousand Leaves", owner: "Guo Yuan",
  why: "ranged attack passes through 10+ feet of canopy"};

function constBlock(name) {
  const start = source.indexOf(`const ${name} = `);
  assert.notEqual(start, -1, `${name} is present`);
  const open = source.indexOf("{", start) + 1;
  let depth = 1;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}" && --depth === 0) return source.slice(start, i + 2);
  }
  throw new Error(`Unclosed block ${name}`);
}

test("the roll-mode label reads Advantage/Disadvantage and hovers one line per source", () => {
  assert.equal(rollModeWord("ADVANTAGE"), "Advantage");
  assert.equal(rollModeWord("DISADVANTAGE"), "Disadvantage");
  assert.equal(rollModeWord("NORMAL"), "Normal roll");
  const hover = rollModeHover("NORMAL", [CANOPY_SOURCE,
    {kind: "advantage", effect: "Rallying Standard", owner: "Left", why: "the banner answer gives this attack Advantage"}]);
  assert.match(hover, /Advantage \(from Rallying Standard \(Left\): the banner answer[^)]*\) cancels Disadvantage \(from Canopy/);
  const lines = hover.split("\n");
  assert.equal(lines.length, 3, "one cancellation line plus one line per source");
  assert.match(lines[1], /^Advantage — Rallying Standard \(Left\): the banner answer gives this attack Advantage$/);
  assert.match(lines[2], /^Disadvantage — Canopy of Ten Thousand Leaves \(Guo Yuan\): ranged attack passes through 10\+ feet of canopy$/);
  assert.match(rollModeHover("DISADVANTAGE", [CANOPY_SOURCE]), /^Disadvantage — Canopy of Ten Thousand Leaves/);
  assert.match(rollModeHover("NORMAL", []), /no Advantage or Disadvantage source applies/);
});

test("the dice tray renders cancellation reasons on its Normal roll label", () => {
  const start = diceSource.indexOf("function showChip()");
  assert.notEqual(start, -1, "showChip is present");
  const open = diceSource.indexOf("{", start);
  let depth = 0, end = -1;
  for (let i = open; i < diceSource.length; i++) {
    if (diceSource[i] === "{") depth++;
    if (diceSource[i] === "}" && --depth === 0) { end = i + 1; break; }
  }
  assert.notEqual(end, -1, "showChip is closed");
  const children = [];
  const chip = {className: "", dataset: {}, style: {setProperty() {}}, classList: {add() {}},
    replaceChildren(...items) { children.splice(0, children.length, ...items); }, offsetWidth: 0};
  const context = {
    summary: {label: "", dice: ["7"], dropped: [], modifier: 0, showTotal: true, total: 7,
      crit: false, fumble: false, mode: "NORMAL", sources: [CANOPY_SOURCE,
        {kind: "advantage", effect: "Rallying Standard", owner: "Left", why: "the banner offsets the canopy penalty"}]},
    chip, dice: [{x1: 100, y1: 100, size: 20}], doc: {createElement: () => ({className: "", textContent: "", style: {}})},
    rollModeWord, rollModeHover, theme: {glow: "", edge: ""}, W: 400, clamp: value => value,
  };
  runInNewContext(diceSource.slice(start, end), context);
  context.showChip();
  const label = children.find(item => item.className === "d3-tag d3-mode");
  assert.ok(label, "the dice tray includes a mode label");
  assert.equal(label.textContent, "Normal roll");
  assert.match(label.title, /Advantage .* cancels Disadvantage .* so the roll is made normally/);
  assert.match(label.title, /Rallying Standard/);
  assert.match(label.title, /Canopy of Ten Thousand Leaves/);
});

test("the label span keeps the hover reasons on its title", () => {
  let span;
  globalThis.document = {createElement: () => {
    span = {className: "", textContent: "", title: ""};
    return span;
  }};
  try {
    const label = rollModeLabel("DISADVANTAGE", [CANOPY_SOURCE]);
    assert.equal(label, span);
    assert.equal(span.className, "tt-roll-mode is-disadvantage");
    assert.equal(span.textContent, "Disadvantage");
    assert.match(span.title, /^Disadvantage — Canopy of Ten Thousand Leaves \(Guo Yuan\): /);
  } finally {
    delete globalThis.document;
  }
});

test("the dice tray receives each roll's mode and its source list", () => {
  const start = source.indexOf("const meta = {label: roll.label");
  const slice = source.slice(start, source.indexOf("};", start));
  assert.match(slice, /mode: roll\.mode \|\| "NORMAL"/);
  assert.match(slice, /mode_sources: roll\.mode_sources \|\| \[\]/);
});

test("feed roll rows show the visible label whose hover lists the reasons", () => {
  const harness = (rows) => {
    const makeNode = () => ({className: "", dataset: {}, style: {}, title: "", textContent: "",
      children: [], addEventListener() {},
      prepend(...kids) { for (const kid of [...kids].reverse()) this.children.unshift(kid); },
      appendChild(child) { this.children.push(child); }});
    const feed = makeNode();
    const context = {
      $: id => id === "#ttFeed" ? feed : {checked: true},
      mapObjectFeed: (mapped) => mapped,
      NOISE: new Set(),
      feedClass: () => "is-roll",
      settleFeed() {},
      rollModeHover, rollModeLabel,
      document: {createElement: makeNode, createTextNode: () => " "},
    };
    globalThis.document = context.document; // rollModeLabel runs in the imported module scope
    try {
      runInNewContext(declaration("appendFeed"), context);
      context.appendFeed(rows);
    } finally {
      delete globalThis.document;
    }
    return [...feed.children];
  };
  const rows = [{event_type: "ATTACK_ROLLED", summary: "1d20+6 [4, 10] · modifier +6 · total 10 — Miss.",
    raw: {payload: {mode: "DISADVANTAGE", mode_sources: [CANOPY_SOURCE]}}}];
  const items = harness(rows);
  assert.equal(items.length, 1);
  const item = items[0];
  assert.match(item.title, /^Disadvantage — Canopy of Ten Thousand Leaves \(Guo Yuan\): ranged attack passes through 10\+ feet of canopy$/);
  const label = item.children[0];
  assert.equal(label.className, "tt-roll-mode is-disadvantage");
  assert.equal(label.textContent, "Disadvantage");
  assert.match(label.title, /Canopy of Ten Thousand Leaves/);
  assert.match(item.textContent, /1d20\+6 \[4, 10\]/);
  assert.doesNotMatch(item.textContent, /with Disadvantage/, "the prose tail yields to the structured label");
});

test("preview buttons carry the visible label and the per-source hover before committing", () => {
  const slice = constBlock("addOption");
  assert.match(slice, /rollModeLabel\(/, "the button renders the visible mode label");
  assert.match(slice, /rollModeHover\(row\.mode, row\.mode_sources\)/, "the hover lists each source on its own line");
  assert.doesNotMatch(slice, /rollReasons/, "no prose tail replaced the structured label");
});
