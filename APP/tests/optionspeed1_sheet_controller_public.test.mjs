// MMX95f1 review fixes. MMX95 made the pop-out sheet name a real refusal reason and share the table's
// open choice. The review found two defects in that work, and both are locked here:
//
//  1. A choice that was ANSWERED stayed open. Only cancelTargeting cleared app.pendingChoice, so
//     picking a target (pickTarget) or a square (onCellClick) cleared app.targeting and then rendered
//     and broadcast with the old choice still set. The sheet kept saying "press Cancel (Esc)" for a
//     placement that was already committed, and refusalFor() preferred that ghost over the real turn.
//     Every way a choice now ends -- answered, cancelled, replaced, or lost with the fight -- goes
//     through closeChoice(), and the tests below drive the real completion handlers and then read the
//     message that actually goes over the BroadcastChannel, not just the local object.
//
//  2. The augment path was invented. The test fabricated an augment button carrying "shape", but
//     production combat/tabletop.py _augment_button() emits "augment": true and NO "shape", so the new
//     lookup sat behind `if (button.shape && button.variant_of)` and no real augment could reach it.
//     Real augments go down the ordinary action path. These controller tests use a minimal synthetic
//     button/menu pair with the public schema, while the paired Python regression exercises production data.

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import * as seats from '../static/tabletop/seats.js';
import {createViewerStore, resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';
import {DEFAULT_FOG_VIEW, NO_FOG_VIEW} from '../static/tabletop/fog_view.js';
import {movesAtHeight, heightMovement, startHeightLevel} from '../static/tabletop/flight-ui.js';
import {compactStatePath, expandMovementGrid} from '../static/tabletop/movement-grid.js';
import {draftButtonStates, overlayButtonStates} from '../static/tabletop/option-composition.js';
import {retainMenuInspection} from '../static/tabletop/assisted-menu.js';

const source = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");


function declaration(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is present`);
  const body = source.slice(0, start).endsWith("async ") ? start - 6 : start;  // keep "async"
  const open = source.indexOf(") {", start) + 2;
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}" && --depth === 0) return source.slice(body, i + 1);
  }
  throw new Error(`Unclosed function ${name}`);
}

const TABIK = "actor:factory.tabik";
const FOE = "actor:factory.foe";

// combat/zones.py _shaped publishes talents in "options" and augment toggles in "augments".
const SHAPES = {[TABIK]: [{
  base: "darkness", zone: "DARK_BASE_DARKNESS", name: "Darkness", current: null,
  options: [{label: "Numbing Darkness", talents: ["Numbing Darkness"], cost: "", active: false,
             button_id: "act:typed.numbing", candidate_id: "cand-numbing"}],
  augments: [], augments_label: null, clear_candidate: "cand-clear",
}]};

const MENU = {actor_id: TABIK, decision_id: "d1", state_version: 7, manual: true, end_turn: "cand-end", moves: [],
              actions: [{source_definition_id: "act:darkness", options: [{candidate_id: "cand-area", target_ids: []}]}]};

const DARKNESS = {id: "act:darkness", label: "Darkness", kind: "action", combat: {source_definition_id: "act:darkness"}};

// A talent button, exactly as combat/tabletop.py _shape_button() builds one: it HAS a shape.
const NUMBING = {id: "act:typed.numbing", label: "Shape Darkness: Numbing Darkness", kind: "combat",
                 variant_of: "act:darkness", shape: {zone: "DARK_BASE_DARKNESS", zone_name: "darkness",
                                                     talents: ["Numbing Darkness"], default: false},
                 modifier: {id: "TAL_DARK_NUMBING_DARKNESS", name: "Numbing Darkness"}};

// The augment buttons, exactly as production builds them (see the fixture header).
const CAND_CLINGING = "candidate:clinging";
const CLINGING = {id: "act:darkness:clinging", label: "Clinging Darkness", kind: "combat",
                 augment: true, variant_of: "act:darkness",
                 combat: {source_definition_id: "act:darkness:clinging"}};

// A minimal public-schema fixture: the action and issued candidate are synthetic, not owner data.
const MENU_WITH_AUGMENTS = {
  actor_id: TABIK, decision_id: "d1", state_version: 7, manual: true, end_turn: "cand-end",
  actions: [
    {source_definition_id: "act:darkness", options: [{candidate_id: "cand-area", target_ids: []}]},
    {source_definition_id: CLINGING.combat.source_definition_id, label: CLINGING.label,
     options: [{candidate_id: CAND_CLINGING}]},
  ],
};

function harness({menu = MENU, currentActor = TABIK, state = true, shapes = SHAPES} = {}) {
  const calls = [];
  const posts = [];
  const actors = [
    {entity_id: TABIK, display_name: "Tabik Damu", controller: "MANUAL", primary_combatant: true,
     hit_points: {current: 10, maximum: 10, temporary: 0}, defenses: [], speed_ft: 30, resources: [],
     conditions: [], turn_state: {}, active: true, position: {x: 3, y: 4}},
    {entity_id: FOE, display_name: "Foe", controller: "MANUAL", primary_combatant: true,
     hit_points: {current: 10, maximum: 10, temporary: 0}, defenses: [], speed_ft: 30, resources: [],
     conditions: [], turn_state: {}, active: true, position: {x: 5, y: 4}},
  ];
  const app = {
    matchId: "m1", busy: false, selected: new Set(), lastTarget: null, targeting: null, hoverTarget: null,
    pendingChoice: null, fog: "off", lastSequence: 0, showShape: null, showMoves: true,
    channel: {postMessage: message => posts.push(message)},
    state: state ? {menu, shapes, pending_action: null, objects: [],
                    presentation: {actors, current_actor_id: currentActor, terminal: false}} : null,
    menu: state ? menu : null,
  };
  // Choice/cursor fixtures explicitly use GM presentation across their two
  // fights; per-player disclosure is covered by the production identity suite.
  const viewerStore=createViewerStore({viewId:'sheet-choice-test'});
  viewerStore.bindGM('m1'); viewerStore.bindGM('m2');
  const currentViewer=()=>resolveViewerIdentity(viewerStore.read(app.matchId),actors,{seats:{}});
  const context = {
    URLSearchParams,
    compactStatePath, expandMovementGrid, draftButtonStates, overlayButtonStates, retainMenuInspection,
    // readTableState also reads the browser's remembered token ids through preferenceStorage.
    preferenceStorage: {getItem: () => null},
    app, calls, posts, refreshes: 0, freshMenu: null, actors: () => actors,
    viewerStore, currentViewer, DEFAULT_FOG_VIEW, NO_FOG_VIEW, isGMView:()=>currentViewer().status === 'gm',
    reconcileViewerIdentity:()=>false, resetViewerPresentation() {}, renderViewerIdentity() {},
    synchronizePresets: async () => {},
    enc: v => v, escapeHtml: v => String(v), sleep: async () => {}, isManualActor: () => true, toast() {}, hint(text) { context.hintText = text; },
    // Model seats (seats.js): none in this fight.
    ...seats, resumeServerPrompt() {}, scheduleSeatPoll() {}, modelTurnNow: () => false, loadSeats: async () => {}, loadProviders: async () => {},
    shownCondition: () => false, conditionTone: () => "neutral", conditionText: () => "",
    renderHighlights() {}, chooseFromList() {}, localRoll: async () => {}, reasonFor: () => "REASON",
    moveTo: async () => true,
    actorById: id => actors.find(actor => actor.entity_id === id),
    presentation: () => context.app?.state?.presentation,
    refresh: async () => {
      context.refreshes++;
      if (context.freshMenu) {
        context.app.menu = context.freshMenu;
        context.app.state = {...context.app.state, menu: context.freshMenu,
                             presentation: {...context.app.state.presentation, current_actor_id: TABIK}};
      }
    },
    act: async candidate => { calls.push(candidate); return true; },
    sheetFor: async () => ({buttons: [DARKNESS]}),
    preferredTargets: () => [],
    $: () => ({replaceChildren() {}, remove() {}, classList:{contains:()=>false}}),
    document: {body: {classList: {remove() {}}}}, clearTimeout() {}, squareFogDebug: () => false,
    mapFromState: () => ({width: 8, height: 8, walls: [], background: {}, cells: {blocked: [], sight: []}, floors: []}),
    board: {setMap() {}, setRoofView() {}, setTokens() {}, setZones() {}, setHighlights() {}, setMovementExplanation() {}, setFog() {}}, wallSightCells: () => [], opacityGrid: () => [],
    renderTokens() {}, renderZones() {}, renderInitiative() {}, renderRoster() {}, renderInspector() {},
    renderActionBar() {}, renderItemsPanel() {}, renderShapePanel() {}, scheduleAutoPlay() {}, renderPip() {},
    loadConditionInfo() {}, renderCommitNotice() {}, tabletopUrl: id => `?match=${id}`,
    history: {replaceState() {}}, feedFollow: {},
    readTableState: async () => { throw new Error("test stops after replacing the fight"); }, openLobby() {},
  };
  runInNewContext("let refreshSequence = 0; let seatReadSequence = 0;", context);
  for (const name of ["refuseCoveredView", "closeChoice", "invalidateTargeting", "reconcileOptionDraft", "render", "closeLoadedFight", "handleUnavailableFight", "loadMatch", "actOnce", "pendingChoiceText", "refusalFor", "draftOptionRows", "chooseLocalOption", "runButton", "useGroup",
                      "tokenIdsKey", "rememberedTokenIds", "targetChoiceAt", "takeTargetChoice",
                      "cancelTargeting", "pickTarget", "onCellClick", "actorMessage", "sheetButtonStates", "broadcastActors"]) {
    runInNewContext(declaration(name), context);
  }
  // The pop-out sheet's own reading of the message, so the test sees what the player would.
  context.lastChoiceOnChannel = () => {
    const messages = posts.filter(row => row.type === "actor" && row.actor_id === TABIK);
    return messages.length ? messages[messages.length - 1].pending_choice : undefined;
  };
  return {app, calls, posts, context};
}

// A group that needs the player to choose: one square and one creature, as an area ability offers.
const PLACEMENT = {label: "Darkness", options: [
  {candidate_id: "cand-area", target_ids: [], area: {center: {x: 3, y: 4}}},
  {candidate_id: "cand-foe", target_ids: [FOE], area: null, destination: null},
]};

// Use the actual action/read/refresh/render pipeline, hint and highlight functions. Only the
// transport, board and DOM surfaces are fakes; this is client coverage, not a browser check.
function transportHarness() {
  const h = harness({menu: {...MENU, actions: [PLACEMENT]}});
  const {app, context} = h;
  const nodes = new Map();
  context.$ = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: true, firstChild: {}, lastChild: {addEventListener() {}},
      classList:{contains:()=>false},
      replaceChildren() { this.firstChild = {}; },
    });
    return nodes.get(selector);
  };
  context.document = {body: {classList: {add() {}, remove() {}}}};
  context.tokenGeometry = () => ({});
  context.board.setHighlights = value => { context.highlights = value; };
  context.board.setMovementExplanation = () => {};
  context.withReactions = fn => fn({});
  context.playEvents = async () => {};
  context.gmNotice = () => {};
  context.requests = [];
  context.api = async (url, options) => {
    context.requests.push({url, body: options?.body});
    if (url.endsWith("/prepare")) return {status: "PREPARED"};
    if (url.endsWith("/act")) return {state: context.nextState, events: {events: []}};
    if (url.includes("/state?")) return context.nextState;
    if (url.includes("/events?")) return {events: []};
    throw new Error(`Unexpected request: ${url}`);
  };
  Object.assign(context, {movesAtHeight, heightMovement, startHeightLevel});
  for (const name of ["hint", "moveHeight", "selectedMoves", "renderHighlights", "act", "readTableState", "eventsThroughState", "refresh"]) {
    runInNewContext(declaration(name), context);
  }
  context.choiceFor = actorId => h.posts.filter(row => row.actor_id === actorId).at(-1)?.pending_choice;
  context.assertClosed = () => {
    assert.equal(app.targeting, null);
    assert.equal(app.pendingChoice, null);
    assert.equal(app.hoverTarget, null);
    assert.equal(context.$("#ttHint").hidden, true, "the actual hint is hidden");
    assert.equal(context.highlights.areas, undefined, "placement squares are cleared");
    assert.equal(context.highlights.targets, undefined, "target highlights are cleared");
    for (const actorId of [TABIK, FOE]) assert.equal(context.choiceFor(actorId), null);
    assert.doesNotMatch(context.refusalFor(TABIK), /Cancel/, "no obsolete recovery instruction");
  };
  return h;
}

test("sheet End turn settles and clears a placement before submitting, then renders the next turn", async () => {
  const {app, context, posts} = transportHarness();
  const open = context.useGroup(PLACEMENT);
  app.hoverTarget = FOE;
  context.nextState = {...app.state, menu: {...MENU, actor_id: FOE, decision_id: "d2", actions: []},
                       presentation: {...app.state.presentation, current_actor_id: FOE}};
  const api = context.api;
  context.api = (url, options) => {
    if (url.endsWith("/act")) {
      assert.equal(app.targeting, null, "End turn closes before the response arrives");
      assert.equal(context.choiceFor(TABIK), null, "removal has already been broadcast");
    }
    return api(url, options);
  };
  const result = await context.runButton({combat: {end_turn: true}}, TABIK);
  assert.equal(result.ok, true);
  assert.equal(await open, false, "the obsolete placement settles");
  assert.equal(context.requests[0].body.candidate_id, "cand-end");
  context.assertClosed();
  assert.match(context.refusalFor(TABIK), /It is Foe's turn/);
  assert.ok(posts.some(row => row.pending_choice?.label === "Darkness"));
  const refused = await context.runButton(DARKNESS, TABIK);
  assert.match(refused.message, /It is Foe's turn/);
  assert.equal(context.requests.filter(row => row.url.endsWith("/act")).length, 1);
});

for (const reason of ["turn", "decision", "version", "candidate", "no menu", "presentation turn"]) {
  test(`external refresh clears and settles obsolete targeting after ${reason} changes`, {timeout: 1500}, async () => {
    const {app, context} = transportHarness();
    const open = context.useGroup(PLACEMENT);
    app.hoverTarget = FOE;
    context.nextState = {...app.state, menu: {...app.menu}, presentation: {...app.state.presentation}};
    if (reason === "turn") {
      context.nextState.menu.actor_id = FOE;
      context.nextState.presentation.current_actor_id = FOE;
    }
    if (reason === "presentation turn") context.nextState.presentation.current_actor_id = FOE;
    if (reason === "decision") context.nextState.menu.decision_id = "d2";
    if (reason === "version") context.nextState.menu.state_version++;
    if (reason === "candidate") context.nextState.menu.actions = [];
    if (reason === "no menu") context.nextState.menu = null;
    await context.refresh();
    context.assertClosed();
    assert.equal(await open, false);
    assert.ok(context.requests.some(row => row.url.includes("/state?")));
    assert.ok(context.requests.some(row => row.url.includes("/events?")));
  });
}

test("external refresh preserves a still-legal targeting choice", async () => {
  const {app, context} = transportHarness();
  const open = context.useGroup(PLACEMENT);
  context.nextState = {...app.state};
  await context.refresh();
  assert.ok(app.targeting);
  assert.equal(context.$("#ttHint").hidden, false);
  assert.equal(context.highlights.areas.length, 1);
  assert.equal(context.choiceFor(TABIK).label, "Darkness");
  context.cancelTargeting();
  assert.equal(await open, false);
});

test("all table End turn entry points use the common choice-closing action path", () => {
  assert.doesNotMatch(source, /\bact\((?:app\.)?menu\.end_turn\)/);
  // R25X2 adds the Dying/Stable End turn entry; all five use the common path.
  assert.equal((source.match(/actOnce\((?:app\.)?menu\.end_turn\)/g) || []).length, 5);
});

// ---------------------------------------------------------------- the refusal must name its real cause

test("an open choice is not reported as a finished turn", async () => {
  const {app, context} = harness();
  app.menu = null; app.state = {...app.state, menu: null};
  app.targeting = {group: {label: "Darkness"}, resolve() {}};
  app.pendingChoice = {kind: "placement", label: "Darkness", actor_id: TABIK, prompt: "what to do with Darkness"};

  const result = await context.runButton(DARKNESS, TABIK);
  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message, /not .*'s turn to act/,
    "an open choice must never be reported as somebody else's turn");
  assert.match(result.message, /waiting for you to choose what to do with Darkness/);
  assert.match(result.message, /Cancel \(Esc\)/, "say how to clear it");
});

test("a saved Ask-me question is named as a question, not as a turn", async () => {
  const {app, context} = harness();
  app.menu = null; app.state = {...app.state, menu: null, pending_action: {request: {decision_id: "d1"}}};

  const result = await context.runButton(DARKNESS, TABIK);
  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message, /turn to act/);
  assert.match(result.message, /question it asked/);
});

test("a genuine other-turn refusal names the fighter who is acting", async () => {
  const {app, context} = harness({menu: null, currentActor: FOE});
  app.menu = null; app.state = {...app.state, menu: null};

  const result = await context.runButton(DARKNESS, TABIK);
  assert.equal(result.ok, false);
  assert.match(result.message, /It is Foe's turn to act, not Tabik Damu's/);
});

test("a fight that is still loading is named as loading, not as a finished turn", async () => {
  const {context} = harness({menu: null, currentActor: null, state: false});
  const result = await context.runButton(DARKNESS, TABIK);
  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message, /turn to act/);
  assert.match(result.message, /still loading/);
});

test("each cause produces its own wording, so the message always matches the cause", async () => {
  const seen = new Map();
  const cases = {
    "open placement": () => {
      const h = harness();
      h.app.menu = null; h.app.state = {...h.app.state, menu: null};
      h.app.pendingChoice = {kind: "placement", label: "Darkness", prompt: "what to do with Darkness"};
      return h;
    },
    "other turn": () => { const h = harness({menu: null, currentActor: FOE}); h.app.menu = null; h.app.state = {...h.app.state, menu: null}; return h; },
    "still loading": () => harness({menu: null, currentActor: null, state: false}),
    "table moved on": () => { const h = harness({menu: null, currentActor: null}); h.app.menu = null; h.app.state = {...h.app.state, menu: null}; return h; },
  };
  for (const [name, build] of Object.entries(cases)) {
    const h = build();
    const {message} = await h.context.runButton(DARKNESS, TABIK);
    assert.ok(message, `${name} says something`);
    for (const [other, text] of seen) assert.notEqual(text, message, `"${name}" must differ from "${other}"`);
    seen.set(name, message);
  }
  assert.equal(seen.size, 4);
});

test("a window that is simply behind re-reads the table instead of refusing", async () => {
  const {app, context, calls} = harness({menu: null, currentActor: null});
  app.menu = null; app.state = {...app.state, menu: null};
  context.freshMenu = MENU;  // the table is fine; this window was behind

  const result = await context.runButton(DARKNESS, TABIK);
  assert.equal(result.ok, true, "a stale window must not refuse");
  assert.equal(context.refreshes, 1, "it re-reads once");
  assert.ok(calls.length, "and then acts");
});

test("a window that is behind does not re-read forever", async () => {
  const {app, context} = harness({menu: null, currentActor: null});
  app.menu = null; app.state = {...app.state, menu: null};
  const result = await context.runButton(DARKNESS, TABIK);
  assert.equal(result.ok, false);
  assert.equal(context.refreshes, 1, "exactly one re-read, then an honest refusal");
});

// ---------------------------------------------------------------- an ANSWERED choice closes and is published

test("choosing a creature closes the choice and tells the sheet", async () => {
  const {app, context} = harness();
  const open = context.useGroup(PLACEMENT);
  assert.ok(app.pendingChoice, "the placement is open");

  await context.pickTarget(FOE);  // the player clicks a creature token

  assert.equal(app.pendingChoice, null, "the answered choice is not left behind");
  assert.equal(app.targeting, null);
  assert.equal(context.lastChoiceOnChannel(), null,
    "the last thing posted to the sheet is that nothing is open -- not the old choice");
  await open;
});

test("choosing a square closes the choice and tells the sheet", async () => {
  const {app, context, calls} = harness();
  const open = context.useGroup(PLACEMENT);

  await context.onCellClick({x: 3, y: 4});  // the player clicks a floor square

  assert.equal(app.pendingChoice, null, "the answered choice is not left behind");
  assert.ok(calls.includes("cand-area"), "and the ability was used");
  assert.equal(context.lastChoiceOnChannel(), null);
  assert.equal(context.hintText, null, "the old table placement hint is removed too");
  await open;
});

test("the sheet is told the choice is open, then told it is finished", async () => {
  const {app, context} = harness();
  context.useGroup(PLACEMENT);
  const whileOpen = context.lastChoiceOnChannel();
  assert.ok(whileOpen, "the open choice reaches the channel");
  assert.match(whileOpen.prompt, /a creature or object or a centre square for Darkness/);

  await context.pickTarget(FOE);
  assert.equal(context.lastChoiceOnChannel(), null, "and the closing reaches it too");
  await Promise.resolve();
});

test("an action that needs no further choice closes a placement that is already open", async () => {
  const {app, context, calls} = harness();
  const stranded = context.useGroup(PLACEMENT);
  assert.ok(app.pendingChoice, "a placement is open");

  // The pop-out sheet presses a button that needs no target of its own.
  const group = {label: "Shrug Off", options: [{candidate_id: "cand-shrug", target_ids: [TABIK]}]};
  await context.useGroup(group);

  assert.equal(app.pendingChoice, null, "the old placement is not left on screen");
  assert.equal(await stranded, false, "and it settles instead of hanging");
  assert.ok(calls.includes("cand-shrug"), "the new action still went through");
  assert.equal(context.lastChoiceOnChannel(), null);
  assert.equal(context.hintText, null, "the replaced placement's table hint is cleared");
  assert.equal(app.hoverTarget, null);
});

test("cancelling clears the shared choice and publishes the clearing", async () => {
  const {app, context} = harness();
  const open = context.useGroup(PLACEMENT);
  assert.ok(app.pendingChoice);

  context.cancelTargeting();

  assert.equal(app.pendingChoice, null);
  assert.equal(app.targeting, null);
  assert.equal(await open, false, "the open choice settles");
  assert.equal(context.lastChoiceOnChannel(), null, "the sheet is told it is no longer waiting");
});

test("an action started from the other window replaces the open choice instead of stranding it", async () => {
  const {app, context} = harness();
  const first = context.useGroup(PLACEMENT);
  const pending = context.useGroup(PLACEMENT);
  assert.equal(await first, false, "the replaced choice resolves as not used, instead of hanging");
  assert.equal(app.pendingChoice.label, "Darkness", "the new choice is the shared one");
  assert.ok(app.targeting, "the new choice is the open one");

  context.cancelTargeting();
  assert.equal(app.pendingChoice, null, "cancelling clears the shared choice");
  assert.equal(app.targeting, null);
  assert.equal(await pending, false, "the open choice settles too");
});

// Render is the real refresh/action completion entry point. Exercise invalidation through it,
// including the actorMessage broadcasts it delivers, rather than only calling the new helper.
for (const reason of ["decision", "version", "actor", "terminal", "automatic", "missing candidate", "question"]) {
  test(`render invalidates a placement after ${reason} changes and broadcasts its removal`, async () => {
    const {app, context} = harness();
    const open = context.useGroup(PLACEMENT);
    const state = {...app.state, menu: {...MENU, actions: [PLACEMENT]},
                   presentation: {...app.state.presentation}};
    if (reason === "decision") state.menu.decision_id = "d2";
    if (reason === "version") state.menu.state_version++;
    if (reason === "actor") { state.menu.actor_id = FOE; state.presentation.current_actor_id = FOE; }
    if (reason === "terminal") state.presentation.terminal = true;
    if (reason === "automatic") state.menu.manual = false;
    if (reason === "missing candidate") state.menu.actions = [];
    if (reason === "question") state.pending_action = {request: {decision_id: "d1"}};

    context.render(state);

    assert.equal(app.targeting, null);
    assert.equal(app.pendingChoice, null);
    assert.equal(await open, false, "the invalidated choice settles");
    const delivered = context.lastChoiceOnChannel();
    if (reason === "question") assert.equal(delivered.kind, "question", "only the saved question remains");
    else assert.equal(delivered, null, "the sheet receives the removal");
    assert.doesNotMatch(context.refusalFor(TABIK), /Cancel/, "no stale placement recovery instruction");
  });
}

test("render preserves a placement while the same decision remains legal", async () => {
  const {app, context} = harness();
  const open = context.useGroup(PLACEMENT);
  context.render({...app.state, menu: {...MENU, actions: [PLACEMENT]}});
  assert.ok(app.targeting);
  assert.equal(context.lastChoiceOnChannel().label, "Darkness");
  context.cancelTargeting();
  assert.equal(await open, false);
});

test("a failed fight replacement settles the old placement and clears the table", async () => {
  const {app, context} = harness();
  const open = context.useGroup(PLACEMENT);
  await context.loadMatch("m2");
  assert.equal(app.matchId, null);
  assert.equal(app.state, null);
  assert.equal(app.menu, null);
  assert.equal(await open, false);
  assert.equal(app.targeting, null);
  assert.equal(context.lastChoiceOnChannel(), null);
});

// ---------------------------------------------------------------- the augment, with production's own payload

test("a production augment button carries no shape, so the talent path must not claim it", () => {
  // This is the fact the invented fixture hid. If production ever starts sending a shape on an
  // augment, the ordinary path below would stop working and this test says so first.
  assert.equal(CLINGING.augment, true);
  assert.equal("shape" in CLINGING, false, "_augment_button() sends no shape");
  assert.ok(CLINGING.variant_of, "it still points at the ability it augments");
  assert.ok(CLINGING.combat.source_definition_id, "and carries its own toggle action");
  assert.equal("shape" in NUMBING, true, "a talent does carry one, which is what separates the two paths");
});

test("the talent path carries no second, unreachable augment interpretation", () => {
  // The removed code looked up entry.augments behind `if (button.shape && button.variant_of)`. An
  // augment has no shape, so it could never arrive: dead code beside a path that already worked.
  // One implementation per press (checklist 4) means it must not come back.
  const start = source.indexOf("if (button.shape && button.variant_of)");
  assert.notEqual(start, -1, "the talent path is present");
  const branch = source.slice(start, start + 1600);
  assert.doesNotMatch(branch, /\.augments\b/, "the talent path must not read the augment list");
  assert.match(branch, /entry\?\.options\.find\(/, "it reads the talent list");
});

test("pressing an augment on the sheet submits that augment's own free toggle", async () => {
  const {calls, context} = harness({menu: MENU_WITH_AUGMENTS});
  const result = await context.runButton(CLINGING, TABIK);
  assert.equal(result.ok, true);
  assert.deepEqual(calls, [CAND_CLINGING],
    "the toggle candidate is submitted; it is not treated as a talent and then cast as a spell");
});

test("an augment that is already on is toggled off, not skipped", async () => {
  // The sheet advertises "turn on or off" (sheet.js:480), so the client always submits the toggle and
  // the server decides the direction. Skipping an augment that is on would make the button dead.
  const {calls, context} = harness({menu: MENU_WITH_AUGMENTS});
  // The same production toggle is submitted on repeated presses. The paired Python regression
  // executes these candidates on the real engine and verifies on/off/on rather than inventing
  // an "on" menu or shape row here.
  await context.runButton(CLINGING, TABIK);
  const result = await context.runButton(CLINGING, TABIK);
  assert.equal(result.ok, true);
  assert.deepEqual(calls, [CAND_CLINGING, CAND_CLINGING], "both presses submit the production toggle");
});

test("an augment whose ability is not on offer is refused, never reported as chosen", async () => {
  // No group in the menu: the fight no longer offers this toggle (a stale sheet).
  const {calls, context} = harness({menu: MENU});  // MENU has no augment groups
  const result = await context.runButton(CLINGING, TABIK);
  assert.equal(result.ok, false);
  assert.equal(result.message, "REASON", "the server's own reason for that button is shown");
  assert.doesNotMatch(result.message, /chosen/);
  assert.equal(calls.length, 0, "nothing was committed");
});

test("a talent on the sheet is still chosen first, then the ability it shapes is aimed", async () => {
  const {calls, context} = harness();
  const result = await context.runButton(NUMBING, TABIK);
  assert.equal(result.ok, true);
  assert.deepEqual(calls, ["cand-numbing", "cand-area"],
    "the talent is chosen first, then the ability it shapes is used");
});

test("a talent that is already active is not chosen again, only the ability is aimed", async () => {
  const activeShapes = {[TABIK]: [{base: "darkness", options: [
    {label: "Numbing Darkness", talents: ["Numbing Darkness"], cost: "", active: true,
     button_id: NUMBING.id, candidate_id: "cand-numbing"}], augments: [], clear_candidate: null}]};
  const {calls, context} = harness({shapes: activeShapes});
  const result = await context.runButton(NUMBING, TABIK);
  assert.equal(result.ok, true);
  assert.deepEqual(calls, ["cand-area"], "only the ability itself is used");
});
