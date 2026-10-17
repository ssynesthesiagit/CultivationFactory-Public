// A blocked continuation, driven through the real "Reopen saved fight" dialog, the real ApiError
// and the real playerError mapper, with only fetch and document stubbed. No browser: the dialog
// touches nothing else, and the backend envelope is exactly what the service raises
// (CombatServiceError.to_dict -> {"error": {code, message, ...}}).
//
// This is the level the MMX74f1 review asked for: a mapper-only assertion cannot show that the
// player is handed recovery advice, because these two codes come out of the dialog, not out of a
// page load.
import assert from "node:assert/strict";
import {test} from "node:test";

const nodes = [];
class Element {
  constructor(tag) { this.tag = tag; this.listeners = {}; nodes.push(this); }
  setAttribute() {}
  append() {}
  addEventListener(kind, handler) { this.listeners[kind] = handler; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() { this.removed = true; }
}
globalThis.document = {createElement: tag => new Element(tag), body: {append() {}}};

const {offerSavedFightContinuation} = await import("../static/saved_fight_compat.js");
const tick = () => new Promise(resolve => setImmediate(resolve));

const json = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(body),
  json: async () => body,
});

function stubFetch({report, blocked, continued}) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const method = options.method || "GET";
    calls.push({url, method});
    if (url === "/api/session") return json(200, {token: "session-token"});
    if (method === "GET") return json(200, report);
    if (continued) return json(200, continued);
    return json(409, {error: blocked});
  };
  return calls;
}

const REPORT = {mode: "REPLAY_MATCHED", token: "proof-token", later_commits: 0};

test("a blocked continuation tells the player the fight is kept and can be tried again", async () => {
  nodes.length = 0;
  const calls = stubFetch({report: REPORT, blocked: {
    code: "COMBAT_COMPATIBILITY_BLOCKED",
    message: "The save or engine changed; inspect the fight again before continuing.",
    details: {match_id: "match:old"},
  }});
  const pending = offerSavedFightContinuation("match:old");
  await tick();
  const [dialog, , explanation, proceed] = nodes;
  assert.match(explanation.textContent, /current rules/);
  assert.match(explanation.textContent, /original fight stays unchanged/);
  assert.equal(proceed.textContent, "Reopen with current rules");

  proceed.onclick();
  await assert.rejects(pending, error => {
    // The table toasts this rejection, so this is the text the player reads.
    assert.equal(error.code, "COMBAT_COMPATIBILITY_BLOCKED");
    assert.equal(error.status, 409);
    assert.match(error.message, /did not finish/, "not told the check is what failed");
    assert.match(error.message, /original fight is kept exactly as it was/, "not told the fight is kept");
    assert.match(error.message, /ask the GM for help/, "given no way forward");
    assert.doesNotMatch(error.message, /cannot be reopened/, "a recoverable fight called unreopenable");
    assert.doesNotMatch(error.message, /different version of the rules/, "invents a cause");
    // Raw diagnostics stay on the Error object; the toast text carries none of it.
    assert.doesNotMatch(error.message, /inspect the fight again/);
    return true;
  });
  assert.ok(dialog.removed, "the dialog must close on failure rather than hang");
  assert.deepEqual(calls.map(call => call.url), [
    "/api/combat/matches/match%3Aold/compatibility",
    "/api/session",
    "/api/combat/matches/match%3Aold/continue-saved",
  ]);
});

test("the same dialog still reopens a fight that is not blocked", async () => {
  // Control: the failed-check branch must not take over the working path.
  nodes.length = 0;
  stubFetch({report: REPORT, blocked: {code: "COMBAT_COMPATIBILITY_BLOCKED", message: "unused"},
    continued: {match_id: "continued"}});
  const pending = offerSavedFightContinuation("match:old");
  await tick();
  nodes[3].onclick();
  assert.equal(await pending, "continued");
  assert.ok(nodes[0].removed, "the dialog must close once the fight is reopened");
});
