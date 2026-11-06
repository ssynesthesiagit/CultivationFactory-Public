// Drive the real dialog/API mapper and the table's load/action/poll paths. Only
// transport, DOM and board drawing are fakes; no saves are deleted by opening it.
import assert from "node:assert/strict";
import {test} from "node:test";
import {readFileSync} from "node:fs";
import {createContext, runInContext} from "node:vm";
import {api, ApiError} from "../static/tabletop/api.js?v=p20261010-06";
import {SAVED_FIGHT_UNSUPPORTED_MESSAGE, playerError} from "../static/tabletop/error-text.js?v=p20261010-06";
import {compactStatePath} from "../static/tabletop/movement-grid.js";
import {offerSavedFightRemoval} from "../static/saved_fight_unavailable.js";

const nodes = [];
class Element {
  constructor(tag) { this.tag = tag; this.listeners = {}; this.children = []; this.disabled = false; nodes.push(this); }
  setAttribute(name, value) { this[name] = value; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  replaceChildren(...children) { this.children = children; }
  set innerHTML(value) {
    this.children = value === "<span></span><small></small>" ? [new Element("span"), new Element("small")] : [];
  }
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }
  addEventListener(kind, handler) { this.listeners[kind] = handler; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() { this.removed = true; }
}
const document = {createElement: tag => new Element(tag), body: {append() {}, classList: {add() {}, remove() {}}}, hidden: false};
globalThis.document = document;
const tick = () => new Promise(resolve => setImmediate(resolve));
const json = (status, body) => ({ok: status >= 200 && status < 300, status,
  text: async () => JSON.stringify(body), json: async () => body});
function transport(respond = () => json(200, {deleted: true})) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url, method: options.method || "GET"});
    if (url === "/api/session") return json(200, {token: "test-session"});
    return respond(url, options);
  };
  return calls;
}
function dialog() {
  const page = nodes.findLast(node => node.tag === "dialog");
  return {page, explanation: page.children[1], note: page.children[2], keep: page.children[3], remove: page.children[4]};
}

test("unsupported-save API errors give the newcomer message before the stale-state fallback", async () => {
  transport(() => json(409, {error: {code: "COMBAT_SAVED_FIGHT_UNSUPPORTED", message: "private diagnostic", details: {path: "private/path"}}}));
  await assert.rejects(api("/api/tabletop/matches/old/state?fog=false"), error => {
    assert.equal(error.code, "COMBAT_SAVED_FIGHT_UNSUPPORTED");
    assert.equal(error.message, SAVED_FIGHT_UNSUPPORTED_MESSAGE);
    assert.doesNotMatch(error.message, /private|schema|token|compatibility|refresh/i);
    return true;
  });
  assert.match(playerError({code: "COMBAT_STATE_VERSION_MISMATCH", status: 409}), /choices have changed/);
  assert.match(playerError({code: "COMBAT_CONTENT_NOT_READY", status: 409}), /still being saved/);
});

test("opening, keeping, or escaping the notice preserves the save without any request", async () => {
  for (const choice of ["keep", "escape"]) {
    const calls = transport();
    const pending = offerSavedFightRemoval("match:old");
    const d = dialog();
    assert.equal(d.explanation.textContent, SAVED_FIGHT_UNSUPPORTED_MESSAGE);
    assert.match(d.note.textContent, /until you choose Delete saved fight/);
    assert.match(d.note.textContent, /cannot be undone/);
    assert.equal(d.keep.autofocus, true);
    assert.equal(d.remove.textContent, "Delete saved fight");
    assert.deepEqual(calls, []);
    if (choice === "keep") d.keep.onclick();
    else d.page.listeners.cancel({preventDefault() {}});
    assert.equal(await pending, false);
    await d.remove.onclick(); // A detached button cannot delete after dismissal.
    assert.deepEqual(calls, []);
    assert.equal(d.page.removed, true);
  }
});

test("only explicit Delete saved fight sends one encoded DELETE, even with repeated clicks", async () => {
  let finishDelete;
  const calls = transport(() => new Promise(resolve => { finishDelete = resolve; }));
  const pending = offerSavedFightRemoval("match:old/one");
  const d = dialog();
  const click = d.remove.onclick();
  await tick();
  assert.equal(d.keep.disabled, true);
  assert.equal(d.remove.disabled, true);
  await d.remove.onclick();
  d.keep.onclick();
  d.page.listeners.cancel({preventDefault() {}});
  assert.equal(d.page.open, true);
  assert.deepEqual(calls.filter(call => call.method !== "GET"), [{url: "/api/tabletop/matches/match%3Aold%2Fone", method: "DELETE"}]);
  finishDelete(json(200, {deleted: true}));
  await click;
  assert.equal(await pending, true);
  assert.equal(d.page.removed, true);
});

test("a failed delete closes the dialog and surfaces a plain error without retrying", async () => {
  const calls = transport(() => json(500, {error: {code: "DELETE_FAILED", message: "private path"}}));
  const pending = offerSavedFightRemoval("match:old");
  const rejected = assert.rejects(pending, error => error.status === 500 && !error.message.includes("private"));
  await dialog().remove.onclick();
  await rejected;
  assert.equal(dialog().page.removed, true);
  assert.equal(calls.filter(call => call.method === "DELETE").length, 1);
});

const source = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
function declaration(name, text = source) {
  const start = text.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return text.slice(start, text.indexOf("\n}", start) + 2);
}
const unsupported = () => new ApiError("old saved shape", "COMBAT_SAVED_FIGHT_UNSUPPORTED", 409);

function tableHarness() {
  const oldActor = {entity_id: "actor:old", display_name: "Old fighter"};
  const oldMenu = {actor_id: oldActor.entity_id, state_version: 1, moves: [], actions: [], end_turn: "old-turn"};
  const app = {matchId: "old-fight", state: {menu: oldMenu, presentation: {match_id: "old-fight", actors: [oldActor]}},
    menu: oldMenu, selected: new Set([oldActor.entity_id]), fog: "off", busy: false, playing: false,
    lastSequence: 1, seatPoll: 42, seatStatus: {old: true}, pendingChoice: null, sheets: new Map()};
  const slots = new Map(), boardState = {}, messages = [], requests = [], toasts = [], clearedTimers = [];
  app.channel = {postMessage: msg => messages.push(msg)};
  const board = {};
  for (const name of ["setTokens", "setZones", "setHighlights", "setMovementExplanation", "setFog"]) {
    board[name] = value => { boardState[name] = value; };
  }
  const context = createContext({app, board, document, URLSearchParams, refreshSequence: 0, seatReadSequence: 0, feedFollow: {}, enc: encodeURIComponent,
    compactStatePath,
    // The state read also asks which creatures this browser remembers; a fresh screen remembers none.
    preferenceStorage: {getItem: () => null, setItem() {}},
    // This transport harness represents an opened GM view. Viewer ownership
    // and covered-turn refusal have their separate real-client regressions.
    viewerStore: {read: () => ({role: 'gm'}), readFog: () => 'off'},
    NO_FOG_VIEW: 'off', DEFAULT_FOG_VIEW: 'off', currentViewer: () => ({ready: true, status: 'gm'}),
    resetViewerPresentation() {}, renderViewerIdentity() {}, refuseCoveredView: () => false, resumeServerPrompt() {},
    renderObservedState: state => { app.state = state; app.menu = state.menu; context.renders++; },
    history: {replaceState: (_a, _b, url) => { context.lastUrl = url; }},
    $: selector => { if (!slots.has(selector)) slots.set(selector, new Element("section")); return slots.get(selector); },
    clearTimeout: id => clearedTimers.push(id),
    offerSavedFightRemoval, squareFogDebug: () => false, tabletopUrl: id => `/tabletop?match=${encodeURIComponent(id)}`,
    presentation: () => app.state?.presentation,
    actors: () => app.state?.presentation?.actors || [],
    actorById: id => app.state?.presentation?.actors?.find(row => row.entity_id === id),
    loadConditionInfo() {}, loadSeats: async () => {}, loadProviders: async () => {},
    render: state => { app.state = state; app.menu = state.menu; context.renders++; },
    renderInspector() {}, renderItemsPanel() {}, renderShapePanel() {}, renderActionBar() {}, renderPip() {},
    renderHighlights() {}, hint() {}, appendTableLine() {}, appendFeed() {}, broadcastActors() {},
    openLobby: () => { context.lobbies++; }, toast: message => toasts.push(message),
    scheduleAutoPlay: () => { context.autoplays++; }, rememberFogView: () => true,
    serverDriving: () => false, modelTurnNow: () => false, isManualActor: () => true,
    synchronizePresets: async () => {}, withReactions: send => send([]),
    playEvents: async () => {}, gmNotice() {}, eventsThroughState: async events => events,
    sleep: async () => { context.retries++; },
    api: async (url, options) => { requests.push({url, options}); throw unsupported(); },
    renders: 0, lobbies: 0, autoplays: 0, retries: 0,
  });
  for (const name of ["closeChoice", "cancelTargeting", "closeLoadedFight", "handleUnavailableFight", "loadMatch",
    "readTableState", "refresh", "pollTable", "act", "autoStep", "refusalFor", "onCellClick", "onTokenClick", "selectActor",
    "savedFightLabel", "tokenIdsKey", "rememberedTokenIds", "playedAgo"]) {
    runInContext(declaration(name), context);
  }
  return {app, context, slots, boardState, messages, requests, toasts, clearedTimers};
}

function assertClosed(h) {
  assert.equal(h.app.matchId, null);
  assert.equal(h.app.state, null);
  assert.equal(h.app.menu, null);
  assert.equal(h.app.seatStatus, null);
  assert.equal(h.app.playing, false);
  assert.equal(h.app.pendingChoice, null);
  assert.equal(h.app.targeting, null);
  assert.equal(h.app.selected.size, 0);
  for (const name of ["setTokens", "setZones"]) assert.equal(h.boardState[name].length, 0);
  assert.equal(Object.keys(h.boardState.setHighlights).length, 0);
  assert.equal(h.boardState.setMovementExplanation, null);
  assert.equal(h.boardState.setFog, null);
  assert.equal(h.context.lastUrl, "/tabletop");
}

test("opening an old-format fight clears previous controls, stops autoplay, and keeps the save", async () => {
  const calls = transport();
  const h = tableHarness();
  for (const id of ["#ttSeat", "#ttSeatLog", "#ttSummary"]) h.context.$(id).showModal();
  const pending = h.context.loadMatch("old-format-fight");
  await tick();
  assertClosed(h);
  for (const id of ["#ttSeat", "#ttSeatLog", "#ttSummary"]) assert.equal(h.context.$(id).open, false);
  assert.equal(h.clearedTimers[0], 42);
  assert.deepEqual(JSON.parse(JSON.stringify(h.messages)), [{type: "fight-closed", actor_id: "actor:old", match_id: "old-fight"}]);
  assert.equal(h.context.retries, 0, "an unsupported format is not a transient save-in-progress");
  assert.equal(h.app.busy, true);
  dialog().keep.onclick();
  assert.equal(await pending, false);
  assert.equal(h.app.busy, false);
  assert.equal(h.context.lobbies, 1);
  assert.equal(h.context.autoplays, 0);
  await h.context.onCellClick({x: 1, y: 1});
  h.context.onTokenClick("actor:old", {});
  h.context.selectActor("actor:old");
  assert.equal(await h.context.act("old-turn"), false);
  assert.equal(await h.context.autoStep(), false);
  await h.context.pollTable();
  assert.equal(h.requests.length, 1, "old controls and polling must not send another fight request");
  assert.deepEqual(calls, [], "the dialog made no mutation");
});

test("a supported fight loads and current event history still opens without a dialog", async () => {
  const h = tableHarness(), before = nodes.filter(node => node.tag === "dialog").length;
  const current = {last_sequence: 2, menu: {manual: true}, presentation: {match_id: "current", actors: [],
    battlefield: {display_name: "Current arena"}}};
  h.context.api = async url => url.includes("/events?") ? {events: [], last_sequence: 2} : current;
  assert.equal(await h.context.loadMatch("current"), true);
  assert.equal(h.app.state, current);
  assert.equal(h.app.matchId, "current");
  assert.equal(h.context.autoplays, 1);
  assert.equal(nodes.filter(node => node.tag === "dialog").length, before);
});

test("unsupported list entries retain their open route and confirmed manual delete", async () => {
  const h = tableHarness(), old = {match_id: "match:old/one", status: "UNSUPPORTED", unavailable_message: SAVED_FIGHT_UNSUPPORTED_MESSAGE};
  // The API lists fights newest-played first (cb02185f); the lobby renders them in that order.
  // This fixture keeps the unsupported save first so the first line is the one under test.
  const rows = [old, {match_id: "current", state_version: 4}], calls = [], opened = [];
  h.context.api = async (url, options = {}) => { calls.push({url, method: options.method || "GET"}); return rows; };
  h.context.fighterPicker = {rememberFights() {}};
  h.context.buildFightBuilder = async () => {};
  h.context.confirm = () => false;
  h.context.loadMatch = id => opened.push(id);
  runInContext(declaration("openLobby"), h.context);
  await h.context.openLobby();
  const line = h.context.$("#ttSaved").firstChild, [open, remove] = line.children;
  assert.equal(open.lastChild.textContent, SAVED_FIGHT_UNSUPPORTED_MESSAGE);
  assert.deepEqual(calls, [{url: "/api/combat/matches", method: "GET"}]);
  open.listeners.click();
  assert.deepEqual(opened, [old.match_id]);
  await remove.listeners.click();
  assert.equal(calls.length, 1, "cancelling deletion sends no request");
  h.context.confirm = () => true;
  await remove.listeners.click();
  await remove.listeners.click();
  assert.equal(line.removed, true);
  assert.deepEqual(calls.slice(1), [{url: "/api/tabletop/matches/match%3Aold%2Fone", method: "DELETE"}]);
});

test("a malformed saved fight is listed and confirmed by a readable name, never its internal ID", async () => {
  const h = tableHarness();
  const old = {match_id: "match:abc123", status: "UNSUPPORTED",
    unavailable_message: SAVED_FIGHT_UNSUPPORTED_MESSAGE, display_name: "Unreadable older fight (saved 2026-01-02)"};
  h.context.api = async () => [old];
  h.context.fighterPicker = {rememberFights() {}};
  h.context.buildFightBuilder = async () => {};
  let confirmed = "";
  h.context.confirm = message => { confirmed = message; return false; };
  runInContext(declaration("openLobby"), h.context);
  await h.context.openLobby();
  const [open, remove] = h.context.$("#ttSaved").firstChild.children;
  assert.equal(open.firstChild.textContent, "Unreadable older fight (saved 2026-01-02)");
  assert.doesNotMatch(open.firstChild.textContent, /match:/);
  assert.equal(remove["aria-label"], "Delete Unreadable older fight (saved 2026-01-02)");
  await remove.listeners.click();
  assert.doesNotMatch(confirmed, /match:/);
  assert.match(confirmed, /Unreadable older fight/);
});

test("a saved fight whose own name is an internal ID is shown with a plain fallback", async () => {
  const h = tableHarness();
  const old = {match_id: "match:abc123", status: "UNSUPPORTED", display_name: "match:abc123"};
  h.context.api = async () => [old];
  h.context.fighterPicker = {rememberFights() {}};
  h.context.buildFightBuilder = async () => {};
  let confirmed = "";
  h.context.confirm = message => { confirmed = message; return false; };
  runInContext(declaration("openLobby"), h.context);
  await h.context.openLobby();
  const [open, remove] = h.context.$("#ttSaved").firstChild.children;
  assert.equal(open.firstChild.textContent, "Saved fight");
  assert.equal(remove["aria-label"], "Delete Saved fight");
  await remove.listeners.click();
  assert.doesNotMatch(confirmed, /match:/);
});

test("an event-history load failure also clears the partially displayed fight", async () => {
  const h = tableHarness();
  h.context.api = async url => {
    if (url.includes("/events?")) throw unsupported();
    return {menu: {}, presentation: {match_id: "old-format", actors: [], battlefield: {display_name: "Arena"}}};
  };
  const pending = h.context.loadMatch("old-format");
  await tick();
  assertClosed(h);
  assert.equal(h.context.renders, 1);
  dialog().keep.onclick();
  assert.equal(await pending, false);
  assert.equal(h.context.autoplays, 0);
});

test("an unrelated failed load clears controls without offering to delete a save", async () => {
  const h = tableHarness(), before = nodes.filter(node => node.tag === "dialog").length;
  h.context.api = async () => { throw new ApiError("connection failed", "NETWORK_ERROR", 0); };
  assert.equal(await h.context.loadMatch("unreachable"), false);
  assertClosed(h);
  assert.equal(h.app.busy, false);
  assert.equal(h.context.autoplays, 0);
  assert.equal(h.context.lobbies, 1);
  assert.match(h.toasts[0], /Could not open the fight/);
  assert.equal(nodes.filter(node => node.tag === "dialog").length, before);
});

test("refresh, idle polling, and an action after a server upgrade all remove stale controls", async () => {
  for (const operation of ["refresh", "pollTable", "act", "autoStep"]) {
    const h = tableHarness();
    // The body class methods are the real action path's only extra DOM needs.
    document.body.classList.add = () => {};
    const pending = operation === "act" ? h.context.act("old-turn") : h.context[operation]();
    await tick();
    assertClosed(h);
    dialog().keep.onclick();
    await pending;
    assert.equal(h.context.lobbies, 1, operation);
    assert.equal(h.requests.length, 1, operation);
  }
});

test("a late table refresh or poll cannot restore a closed fight or offer another deletion", async () => {
  for (const operation of ["refresh", "pollTable"]) for (const failed of [false, true]) {
    const h = tableHarness(), before = nodes.filter(node => node.tag === "dialog").length;
    let finish, fail;
    h.context.api = async () => new Promise((resolve, reject) => { finish = resolve; fail = reject; });
    const pending = h.context[operation]();
    await tick();
    h.context.closeLoadedFight();
    if (failed) fail(unsupported());
    else finish({events: [{event_sequence: 2}], last_sequence: 2});
    await pending;
    assertClosed(h);
    assert.equal(h.context.renders, 0);
    assert.equal(nodes.filter(node => node.tag === "dialog").length, before);
  }
});

test("an old reaction-poll error is ignored after that prompt is replaced", async () => {
  const h = tableHarness(), before = nodes.filter(node => node.tag === "dialog").length;
  let fail;
  h.app.waitingReaction = {matchId: "old-fight", prompt: {}, stop() {}};
  h.context.api = async () => new Promise((_resolve, reject) => { fail = reject; });
  const pending = h.context.pollTable();
  await tick();
  h.app.waitingReaction = null;
  fail(unsupported());
  await pending;
  assert.equal(h.app.matchId, "old-fight");
  assert.equal(nodes.filter(node => node.tag === "dialog").length, before);
});

test("losing a save while awaiting a reaction cancels without submitting an answer", async () => {
  const h = tableHarness();
  for (const name of ["askReaction", "withReactions", "reconcileRemoteDecision"]) runInContext(declaration(name), h.context);
  h.context.askReactionInput = () => new Promise(() => {});
  let sends = 0;
  const pending = h.context.withReactions(async () => {
    sends++;
    return {status: "REACTION_REQUIRED", reaction: {context: {}}, events: {events: []}};
  });
  await tick();
  const handled = h.context.handleUnavailableFight(unsupported());
  assert.equal((await pending).status, "CANCELLED");
  assert.equal(sends, 1);
  assert.equal(h.requests.length, 0);
  dialog().keep.onclick();
  assert.equal(await handled, true);
  assertClosed(h);
});

test("a closed table disconnects only the pop-out sheet for that saved fight", () => {
  const sheetSource = readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
  const state = {sheet: {actor_id: "actor:old"}, actor: {match_id: "old-fight"}, connected: true, legal: new Set(["act:old"])};
  const ctx = createContext({state, renderActions() {}, renderLive() {}});
  runInContext(declaration("onMessage", sheetSource), ctx);
  ctx.onMessage({type: "fight-closed", actor_id: "actor:old", match_id: "other-fight"});
  assert.equal(state.connected, true);
  ctx.onMessage({type: "fight-closed", actor_id: "actor:old", match_id: "old-fight"});
  assert.equal(state.connected, false);
  assert.equal(state.actor, null);
  assert.equal(state.legal.size, 0);
});

const combatSource = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
function combatHarness() {
  const elements = new Map(), requests = [];
  const ctx = createContext({
    combatMatch: {match_id: "old-fight", state: {}}, combatHistory: {boundaries: []}, combatPresentation: {},
    combatDecision: {old: true}, combatPendingIntentDraft: {old: true}, combatInteractionDraft: {old: true},
    combatAutoRunning: true, combatExecutionEpoch: 0, combatHistoryTransitionPending: false,
    combatHistoryTransitionSerial: 0, combatHistoryIndex: null, combatAIValidationToken: "old",
    combatSelectedCandidateId: "old", combatSelectedActorId: "old", combatPinnedActorId: "old",
    combatFollowCurrentTurn: false, combatPanPointer: null,
    document: {getElementById: id => {
      if (!elements.has(id)) {
        const element = new Element("section");
        element.classList = {add() {}, remove() {}, toggle() {}};
        element.scrollIntoView = () => {};
        elements.set(id, element);
      }
      return elements.get(id);
    }},
    combatId: encodeURIComponent, combatSetInteractionMode() {}, closeCombatDialog() {}, renderCombatBoard() {}, renderCombatSheets() {},
    setCombatWorkspaceView() {}, renderCombatMatch() { ctx.renders++; }, refreshCombatDecision: async () => {},
    combatSetDiagnostic() {}, plainAPIError: error => ctx.parseAPIError(error).message,
    combatIsHistorical: () => false, combatDraftBlocksAutomaticExecution: () => false, combatActorName: () => "Fighter",
    loadCombatMatches: async () => { ctx.lists++; }, offerSavedFightRemoval,
    api: async url => { requests.push(url); throw new Error(JSON.stringify({error: {code: "COMBAT_SAVED_FIGHT_UNSUPPORTED", message: SAVED_FIGHT_UNSUPPORTED_MESSAGE}})); },
    renders: 0, lists: 0,
  });
  for (const name of ["parseAPIError", "combatError", "resetCombatInteractionState", "cancelCombatPendingIntent",
    "setCombatWorkspaceActive", "closeCombatMatch", "showUnavailableCombatFight", "loadCombatHistory", "openCombatMatch", "runOneLocalStep"]) {
    // The original screen is a classic script. Resolve its dynamic module import
    // to the same real dialog already imported above, keeping its body unchanged.
    const code = declaration(name, combatSource).replace('await import("./saved_fight_unavailable.js?v=p20261010-06")', "({offerSavedFightRemoval})");
    runInContext(code, ctx);
  }
  return {ctx, elements, requests};
}

test("the original combat screen also clears old controls and offers the manual-delete notice", async () => {
  const calls = transport(), h = combatHarness();
  const pending = h.ctx.openCombatMatch("unsupported");
  await tick();
  assert.equal(h.ctx.combatMatch, null);
  assert.equal(h.ctx.combatHistory, null);
  assert.equal(h.ctx.combatPresentation, null);
  assert.equal(h.ctx.combatDecision, null);
  assert.equal(h.ctx.combatPendingIntentDraft, null);
  assert.equal(h.ctx.combatInteractionDraft, null);
  assert.equal(h.ctx.combatAIValidationToken, null);
  assert.equal(h.ctx.combatAutoRunning, false);
  assert.equal(h.elements.get("combatWorkspace").hidden, true);
  assert.equal(dialog().explanation.textContent, SAVED_FIGHT_UNSUPPORTED_MESSAGE);
  dialog().keep.onclick();
  await pending;
  assert.equal(h.ctx.lists, 1);
  assert.deepEqual(calls, []);
});

test("the original screen still opens a current fight and its recorded history", async () => {
  const h = combatHarness();
  const match = {match_id: "current", state: {}}, history = {boundaries: [{state_version: 1}]}, presentation = {actors: []};
  h.ctx.api = async url => {
    h.requests.push(url);
    if (url.endsWith("/history")) return history;
    if (url.endsWith("/presentation")) return presentation;
    return match;
  };
  await h.ctx.openCombatMatch("current");
  assert.equal(h.ctx.combatMatch, match);
  assert.equal(h.ctx.combatHistory, history);
  assert.equal(h.ctx.combatPresentation, presentation);
  assert.equal(h.ctx.renders, 1);
  assert.equal(h.elements.get("combatWorkspace").hidden, false);
  assert.deepEqual(h.requests, ["/api/combat/matches/current", "/api/combat/matches/current/history", "/api/combat/matches/current/presentation"]);
});

test("the original fight list describes an unsupported save without calling it ready", async () => {
  const h = combatHarness(), row = {match_id: "old-fight", status: "UNSUPPORTED", unavailable_message: SAVED_FIGHT_UNSUPPORTED_MESSAGE};
  h.ctx.combatCatalog = {};
  h.ctx.loadFactoryFighters = () => {};
  h.ctx.clearNode = element => element.replaceChildren();
  h.ctx.document.createElement = tag => new Element(tag);
  h.ctx.api = async () => [row];
  runInContext(declaration("loadCombatMatches", combatSource), h.ctx);
  await h.ctx.loadCombatMatches();
  const card = h.elements.get("combatMatchList").firstChild;
  assert.equal(card.firstChild.lastChild.textContent, SAVED_FIGHT_UNSUPPORTED_MESSAGE);
  assert.equal(card.lastChild.firstChild.href, "/tabletop?match=old-fight");
});

test("the original screen drops a delayed history or automatic response after closing the fight", async () => {
  for (const operation of ["history", "automatic"]) {
    const h = combatHarness();
    let finish;
    h.ctx.api = async () => new Promise(resolve => { finish = resolve; });
    const pending = operation === "history" ? h.ctx.loadCombatHistory("old-fight") : h.ctx.runOneLocalStep();
    await tick();
    h.ctx.closeCombatMatch();
    finish(operation === "history" ? {boundaries: []} : {status: "COMMITTED", match: {match_id: "old-fight", state: {}}});
    const result = await pending;
    assert.equal(h.ctx.combatMatch, null);
    assert.equal(h.ctx.combatHistory, null);
    assert.equal(h.ctx.combatPresentation, null);
    assert.equal(operation === "history" ? result : result.status, operation === "history" ? null : "FIGHT_CLOSED");
  }
});

test("late original-screen decisions and history transitions cannot repopulate a closed fight", async () => {
  for (const operation of ["refreshCombatDecision", "setCombatHistoryIndex", "returnCombatLive"]) {
    for (const failed of [false, true]) {
      const h = combatHarness(), before = nodes.filter(node => node.tag === "dialog").length;
      h.ctx.combatHistory = {boundaries: [{state_version: 1}]};
      h.ctx.combatAutoStepPromise = null;
      h.ctx.combatSetHistoricalMode = () => {};
      h.ctx.renderCombatHistoryControls = () => {};
      runInContext(declaration(operation, combatSource), h.ctx);
      let finish, fail;
      h.ctx.api = async () => new Promise((resolve, reject) => { finish = resolve; fail = reject; });
      const pending = h.ctx[operation](0);
      await tick();
      h.ctx.closeCombatMatch();
      if (failed) fail(new Error(JSON.stringify({error: {code: "COMBAT_SAVED_FIGHT_UNSUPPORTED"}})));
      else finish({match_id: "old-fight", boundaries: [{state_version: 1}], context: {legal_candidates: []}});
      await pending;
      assert.equal(h.ctx.combatMatch, null);
      assert.equal(h.ctx.combatHistory, null);
      assert.equal(h.ctx.combatPresentation, null);
      assert.equal(h.ctx.combatDecision, null);
      assert.equal(h.ctx.renders, 0);
      assert.equal(nodes.filter(node => node.tag === "dialog").length, before);
    }
  }
});
