// CHARLIST1: the table's top bar has a Characters button that opens the pop-out sheet window on the
// character list (?pick=1), so any saved character's sheet is reachable in and out of a fight.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const tabletopHtml = fs.readFileSync(new URL("../static/tabletop/tabletop.html", import.meta.url), "utf8");
const tabletopSource = fs.readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
const sheetSource = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");

function between(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.ok(start >= 0, `missing ${startMarker}`);
  const end = source.indexOf(endMarker, start);
  assert.ok(end > start, `missing ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

function fnSource(source, startMarker) {
  return between(source, startMarker, "\n}\n") + "\n}\n";
}

test("the top bar has an always-enabled Characters button beside Fights", () => {
  const button = tabletopHtml.match(/<button\b[^>]*id="ttCharacters"[^>]*>/);
  assert.ok(button, "tabletop.html has a button with id ttCharacters");
  const tag = button[0];
  assert.match(tag, /class="tt-tool"/);
  assert.match(tag, /type="button"/);
  assert.ok(tag.includes('title="Open a character sheet — pick any saved character"'), tag);
  assert.doesNotMatch(tag, /\bdisabled\b/);
  // Focusable keyboard control, no global hotkey was added.
  const tools = between(tabletopHtml, '<div class="tt-top-tools">', '<select id="ttTheme"');
  assert.ok(tools.includes('id="ttCharacters"'));
  assert.ok(tools.indexOf('id="ttCharacters"') < tools.indexOf('id="ttLobbyOpen"'));
  assert.equal(tools.match(/id="ttCharacters"/g).length, 1);
  // Nothing disables it later (it works in and out of a fight, player and Game Master views).
  assert.doesNotMatch(tabletopSource, /\$\("#ttCharacters"\)[^\n]*\.disabled/);
  assert.match(tabletopSource, /\$\("#ttCharacters"\)\.addEventListener\("click", openCharacterList\)/);
});

function openCharacterList(windowOpen) {
  const toasts = [];
  const src = fnSource(tabletopSource, "function openCharacterList(");
  const ctx = {window: {open: windowOpen}, toast: (message, bad) => toasts.push({message, bad}), console};
  vm.createContext(ctx);
  vm.runInContext(`${src}\n;openCharacterList`, ctx)();
  return toasts;
}

test("the button opens the pop-out sheet window on the character list", () => {
  const calls = [];
  const toasts = openCharacterList((...args) => { calls.push(args); return {}; });
  assert.deepEqual(calls, [["/tabletop/sheet?pick=1", "tt-sheet-characters", "popup=yes,width=1280,height=860"]]);
  assert.deepEqual(toasts, []);
  // Same window size as a character's own sheet.
  const sheetWindow = fnSource(tabletopSource, "function openSheetFor(");
  const size = /"(popup=yes,width=\d+,height=\d+)"/.exec(sheetWindow)?.[1];
  assert.equal(calls[0][2], size);
});

test("a blocked pop-up tells the player what to do", () => {
  const toasts = openCharacterList(() => null);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].message, "Your browser blocked the pop-up; allow pop-ups for this page.");
  assert.equal(toasts[0].bad, true);
});

function runMain(search, projectId) {
  const messages = [];
  const ctx = {
    params: new URLSearchParams(search),
    state: {projectId},
    applyTheme() {}, wireSheet() {}, wireEditor() {},
    loadDice: async () => {},
    showPicker: async (message) => { messages.push(message); },
    $: () => ({setAttribute() {}}),
    window: {},
    console,
  };
  vm.createContext(ctx);
  const main = vm.runInContext(`${between(sheetSource, "async function main()", "\nmain();")}\n;main`, ctx);
  return main().then(() => messages);
}

test("?pick=1 shows the character list first, even with no character chosen", async () => {
  const messages = await runMain("?pick=1", "");
  assert.deepEqual(messages, ["Choose a character to open their sheet in this window:"]);
});

test("?pick=1 is list-only even when a project is in the address", async () => {
  const messages = await runMain("?pick=1&project=ann-1", "ann-1");
  assert.deepEqual(messages, ["Choose a character to open their sheet in this window:"]);
});

test("the sheet with no character and no pick still offers the list", async () => {
  const messages = await runMain("", "");
  assert.deepEqual(messages, ["Open this sheet from the combat table, or choose a character:"]);
});

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.className = ""; this.parentElement = null; this.style = {}; this.value = ""; }
  addEventListener() {}
  append(...kids) { for (const kid of kids) { if (kid instanceof El) kid.parentElement = this; this.children.push(kid); } }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); this.parentElement = null; }
  get textContent() { return this.children.map(c => (c instanceof El ? c.textContent : c)).join(""); }
  set textContent(value) { this.children = [String(value)]; }
  matches(part) { return part.startsWith(".") ? this.className.split(/\s+/).includes(part.slice(1)) : this.tagName === part; }
  *descendants() { for (const c of this.children) if (c instanceof El) { yield c; yield* c.descendants(); } }
  querySelectorAll(selector) {
    let scope = [this];
    for (const part of selector.trim().split(/\s+/)) {
      const next = [];
      for (const s of scope) for (const d of s.descendants()) if (d.matches(part) && !next.includes(d)) next.push(d);
      scope = next;
    }
    return scope;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}

test("the list has a search box and picking a character leaves list mode", async () => {
  const elements = {};
  const $ = id => (elements[id] ||= new El("div"));
  const h = (tag, attrs, ...kids) => {
    const el = new El(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value; else el.attributes[key] = value === true ? "" : String(value);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false && kid !== "") el.append(kid instanceof El ? kid : String(kid));
    return el;
  };
  const list = [
    {project_id: "ann-1", display_name: "Ann", cultivation_level: 3, path: "Body Refining"},
    {project_id: "bo-2", display_name: "Bo", cultivation_level: 1, path: ""},
  ];
  const ctx = {
    h, $, URL, URLSearchParams, console,
    location: {href: "http://factory.test/tabletop/sheet?pick=1", pathname: "/tabletop/sheet", search: "?pick=1"},
    CharacterSearch: {matches: () => true},
    fetch: async () => ({ok: true, status: 200, json: async () => list}),
  };
  vm.createContext(ctx);
  vm.runInContext(`${fnSource(sheetSource, "async function fetchJson")}\n${fnSource(sheetSource, "async function showPicker")}\n;showPicker`, ctx, {filename: "sheet.js"});
  await vm.runInContext("showPicker", ctx)("Choose a character to open their sheet in this window:");
  const body = $("body");
  assert.equal(body.querySelectorAll("input").length, 1);
  assert.match(body.textContent, /Search characters/);
  const links = body.querySelectorAll("ul a");
  assert.equal(links.length, 2);
  assert.equal(links[0].attributes.href, "/tabletop/sheet?project=ann-1");
  assert.equal(links[1].attributes.href, "/tabletop/sheet?project=bo-2");
  assert.doesNotMatch(links[0].attributes.href, /pick=1/);
});
