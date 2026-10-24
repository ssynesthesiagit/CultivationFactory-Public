// FIGHTSORT1: the fight lobby renders the API's order (newest played first) and says when each fight was played.
// Runs the real openLobby/playedAgo source from tabletop.js; only the DOM, api and dialog are small fakes.
import assert from "node:assert/strict";
import {test} from "node:test";
import {readFileSync} from "node:fs";
import {createContext, runInContext} from "node:vm";

const source = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
function declaration(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf("\n}", start) + 2);
}

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.open = false; this.disabled = false; this.text = undefined; }
  get textContent() { return this.text ?? this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this.text = String(value); this.children = []; }
  set innerHTML(value) { this.text = undefined; this.children = value === "<span></span><small></small>" ? [new El("span"), new El("small")] : []; }
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(kind, handler) { this.listeners[kind] = handler; }
  setAttribute(name, value) { this[name] = value; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

function lobby(rows, now) {
  const slots = new Map(), remembered = [];
  const slot = selector => { if (!slots.has(selector)) slots.set(selector, new El("section")); return slots.get(selector); };
  const context = createContext({
    $: slot, enc: encodeURIComponent, app: {matchId: null}, document: {createElement: tag => new El(tag)},
    api: async url => { assert.equal(url, "/api/combat/matches"); return rows; },
    fighterPicker: {rememberFights: list => remembered.push(list)},
    buildFightBuilder: async () => {}, toast() {}, confirm: () => false, loadMatch() {},
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
  });
  runInContext(["playedAgo", "savedFightLabel", "openLobby"].map(declaration).join("\n"), context);
  return {context, slot, remembered};
}

const local = (...parts) => new Date(...parts);  // local wall-clock time, like the table's own dates

test("playedAgo gives plain words for minutes, hours, yesterday and older days", () => {
  const now = local(2026, 9, 19, 12, 0, 0).getTime();
  const {context} = lobby([], now);
  const ago = iso => runInContext(`playedAgo(${JSON.stringify(iso)}, ${now})`, context);
  assert.equal(ago(local(2026, 9, 19, 11, 55).toISOString()), "played 5 min ago");
  assert.equal(ago(local(2026, 9, 19, 9, 0).toISOString()), "played 3 hours ago");
  assert.equal(ago(local(2026, 9, 18, 20, 0).toISOString()), "played yesterday");
  assert.equal(ago(local(2026, 9, 15, 20, 0).toISOString()), "played 3 days ago");
  assert.equal(ago(null), "");
  assert.equal(ago("not a time"), "");
});

test("the lobby renders saved fights in the order the API sends them, with their activity time", async () => {
  const now = local(2026, 9, 19, 12, 0, 0).getTime();
  // The API has already sorted by last_played_at (newest first). This fight's updated_at is older than its newest journal write.
  const rows = [
    {match_id: "match:new", display_name: "Newest", state_version: 38, status: "ACTIVE",
      updated_at: local(2026, 9, 19, 5, 27).toISOString(), last_played_at: local(2026, 9, 19, 11, 55).toISOString()},
    {match_id: "match:mid", display_name: "Middle", state_version: 4, status: "ACTIVE",
      updated_at: local(2026, 9, 18, 21, 0).toISOString(), last_played_at: local(2026, 9, 18, 20, 0).toISOString()},
    {match_id: "match:old", display_name: "Oldest", status: "COMPLETE", last_played_at: null},
  ];
  const {context, slot, remembered} = lobby(rows, now);
  await context.openLobby();
  const labels = slot("#ttSaved").children.map(line => line.children[0].children[0].textContent);
  assert.deepEqual(labels, ["Newest", "Middle", "Oldest"]);
  const small = index => slot("#ttSaved").children[index].children[0].children[1].textContent;
  assert.equal(small(0), "step 38 · played 5 min ago");
  assert.equal(small(1), "step 4 · played yesterday");
  assert.equal(small(2), "finished");
  assert.deepEqual(remembered[0], rows, "the fighter picker's Recent list gets the same rows");
});
