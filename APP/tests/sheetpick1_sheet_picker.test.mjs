// SHEETPICK1: the pop-out sheet's load failure and character picker (static/tabletop/sheet.js).
// sheet.js runs main() on import, so this test pulls showPicker and fetchJson out of its source and runs them
// in a vm with a small fake DOM and a controlled fetch. Real error-text.js is used for every message.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {playerError, sheetLoadMessage, SHEET_NOT_INSTALLED_MESSAGE} from "../static/tabletop/error-text.js";

const sheetSource = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");

function fnSource(name) {
  const start = sheetSource.indexOf(`\n${name}`) < 0 ? -1 : sheetSource.indexOf(`\n${name}`) + 1;
  assert.ok(start >= 0, `sheet.js has no ${name}`);
  const end = sheetSource.indexOf("\n}\n", start);
  return sheetSource.slice(start, end + 3);
}

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.hidden = false; this.className = ""; this.parentElement = null; this.style = {}; this.value = ""; }
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

function makeContext(fetchImpl) {
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
  const ctx = {
    h, $, playerError, URL, URLSearchParams, console,
    location: {href: "http://factory.test/tabletop/sheet?project=none", pathname: "/tabletop/sheet", search: "?project=none"},
    CharacterSearch: {matches: (query, texts) => !query || texts.some(t => t.toLowerCase().includes(String(query).toLowerCase()))},
    fetch: (url, options) => fetchImpl(url, options),
  };
  vm.createContext(ctx);
  vm.runInContext(`${fnSource("async function fetchJson")}\n${fnSource("async function showPicker")}\n;showPicker`, ctx, {filename: "sheet.js"});
  return {ctx, body: $("body")};
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const LIST = [
  {project_id: "ann-1", display_name: "Ann", cultivation_level: 3, path: "Body Refining"},
  {project_id: "bo-2", display_name: "Bo", cultivation_level: 1, path: ""},
];

test("the sheet's not-installed answer gets the sheet line, not the fight wording", async () => {
  const body = {error: {code: "COMBAT_CONTENT_NOT_READY", message: "That character is not installed on this machine."}};
  const {ctx} = makeContext(async () => ({ok: false, status: 404, json: async () => body}));
  const fetchJson = vm.runInContext("fetchJson", ctx);
  let caught = null;
  try { await fetchJson("/api/tabletop/characters/x/sheet"); } catch (error) { caught = error; }
  assert.ok(caught, "fetchJson should reject a 404");
  const message = sheetLoadMessage(caught);
  assert.equal(message, SHEET_NOT_INSTALLED_MESSAGE);
  assert.equal(message, "That character isn't installed here. Finalize it first, or pick another character below.");
  assert.doesNotMatch(message, /still being saved/);
  // Fight contexts keep the fight wording.
  assert.match(playerError({code: "COMBAT_CONTENT_NOT_READY"}), /still being saved/);
});

test("other sheet load failures keep the generic line", () => {
  const error = Object.assign(new Error("The table could not connect."), {body: null});
  assert.equal(sheetLoadMessage(error), "Could not load this character (The table could not connect.). Choose another:");
});

test("the picker shows Loading characters… until the list arrives, then the list", async () => {
  let resolveList;
  const {ctx, body} = makeContext(() => new Promise(resolve => { resolveList = resolve; }));
  const showPicker = vm.runInContext("showPicker", ctx);
  const done = showPicker("Could not load this character. Choose another:");
  await flush();
  let text = body.textContent;
  assert.match(text, /Choose another:/);
  assert.match(text, /Loading characters…/);
  resolveList({ok: true, status: 200, json: async () => LIST});
  await done;
  text = body.textContent;
  assert.doesNotMatch(text, /Loading characters…/);
  const links = body.querySelectorAll("ul a");
  assert.equal(links.length, 2);
  assert.match(links[0].attributes.href, /project=ann-1/);
  assert.match(links[1].textContent, /Bo — CL 1/);
});

for (const [label, fetchImpl] of [
  ["a network failure", async () => { throw new TypeError("Failed to fetch"); }],
  ["a server error", async () => ({ok: false, status: 500, json: async () => ({error: {code: "X", message: "boom"}})})],
]) {
  test(`the picker says how to retry after ${label}`, async () => {
    const {ctx, body} = makeContext(fetchImpl);
    await vm.runInContext("showPicker", ctx)("Choose another:");
    const text = body.textContent;
    assert.match(text, /Could not load the character list\. Reload the page to try again\./);
    assert.doesNotMatch(text, /Loading characters…/);
    assert.equal(body.querySelectorAll("ul a").length, 0);
  });
}
