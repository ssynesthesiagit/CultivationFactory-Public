// Tianxia Table (owner 2026-09-25): human-played and AI combat on one grid.
//
// The engine decides every rule.  The table shows the state, offers the engine's legal
// choices for the fighter whose turn it is as buttons, sends back the chosen candidate
// and animates what happened (paths, dice, damage).  Fog of war uses the engine's own
// line of sight (vision.js).  A pop-out character sheet (sheet.html) talks to the table
// over BroadcastChannel "tianxia-tabletop".

import {api, enc} from "./api.js?v=menuspeed6f3";
import {compactStatePath, expandMovementGrid} from './movement-grid.js?v=menuspeed6f3';
import {OptionDraft, draftButtonStates, overlayButtonStates} from "./option-composition.js?v=optdraft1";
import {doorMenu} from "./door-interaction.js";
import {renderRankedMenu} from "./ranked-menu.js?v=embedmenus-3";
import {expandSource, checkMove, confirmRouteQuote, retainMenuInspection, menuInspectionKey, moveKey, copyMoveInspection} from './assisted-menu.js';
import {economySections, economyPills} from "./action-economy.js";
import {attackGroupView, groupAttackRows} from "./attack-groups.js?v=attacklist1-2";
import {heightControl, heightFeet, flightText, movesAtHeight, heightMovement, startHeightLevel, roofLevelsAt, movementVerb, routeText, movementControl, appendTip} from "./flight-ui.js?v=rel6-2";
import {mapObjectFeed} from "./feed-presentation.js?v=sol212g";
import {rollModeHover, rollModeLabel, rollModeWord} from "./roll_mode_display.js?v=rollreason1";
import "../sheet_view_model.js?v=sol192";
import {concentrationCard} from "./concentration.js?v=sol179";
import {renderInformation} from "./information.js?v=bloodsense-1";
import {layoutText} from "./presentation.js?v=mmx104r2";
import {glossaryDefinitions, installGlossary, resourceText} from "./newcomer.js?v=sol192";
import { cleanRules, renderRules, actionSummary, actionHoverText, actionTipCard, renderTipCard, rulesTextFor, riderNotice, additionalRuleText } from "./rules.js?v=sol192";
import {bindTipTargets, createHoverCard} from "./hovercard.js?v=tipdelay-1";
import {decisionChanged} from "./pending-decision.js?v=live-b3";
import {offerSavedFightRemoval} from "../saved_fight_unavailable.js?v=p20261010-06";
import { markActive } from "./active.js?v=c1-4";
import { barSignature, bindPress, copySelection } from "./kept-bar.js?v=speedreuse2-3";
import {CELL, createBoard, initials, treeCells} from "./board.js?v=ruler2";
import {opacityGrid, lineOfSight, perceivedCells, perceivedObjects, tokenHiddenByFog, tokenSensePresentation, wallCells, centerlineTerrain} from "./vision.js?v=rel6-2";
import {wallSightCells} from "./zones.js?v=sol124-r25x2";
import {emptyMemory, ghostCells, memoryKey, recordSeen} from "./fog_memory.js?v=ghostmark1bf2";
import {createFogMemoryStore, indexedMemoryBackend} from "./fog_memory_store.js";
import {tableObjectTokens} from "./object-presentation.js?v=afterimage-ghost-1";
import {createPrefightRow} from "./prefight_row.js?v=l40-1";
import {automaticTurn} from "./automatic-turn.js";
import {controlOf, decisionsHtml, isModelSeat, modelOwner, pickerHtml, playedByHtml, providerLabel, serverDriving, styleHtml, styleToSend, MODEL_PREFIX, setupControlHtml, splitSetupControl, refreshSetupControl} from "./seats.js?v=setup-models-r2";
import {createProviderList} from "./provider-list.js";
import {fightSummaryHtml, summaryAutoOpen} from "./fight-summary.js?v=sol143-2";
import {canAddFighter} from "./limits.js?v=r25";
import {applyPick, fighterPicker} from "./fighter-picker.js?v=sol197";
import {blockerSegments, visibilityPolygons} from "./fog_polygon.js?v=loslines3f5";
import {altitudeVisibilityPolygons, altitudeFogKey, viewerEye} from './fog-altitude.js?v=loslines3f8';
import {DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView, fogViewers} from "./fog_view.js?v=uirel-1";
import {createViewerStore, isPrimaryFighter, isValidViewId, mintViewId, resolveViewerIdentity} from "./viewer-identity.js?v=uirel-1";
import {createMapRuler} from "./ruler.js?v=ruler2";

installGlossary();

// The shared hover card (owner 2026-10-03: "there needs to be a way to hover over the tooltip to scroll down with
// middle mouse roll button. wait for it to pop up, then move over to the box and select things or scroll down etc.").
// The condition pills, the action buttons and the sheet rows used to hang their text off the browser's own tooltip,
// which cannot be scrolled, cannot be selected and closes the moment you move towards it. They now go through the
// same card as the map's zone and token cards, so all of them wait, keep still while the pointer travels onto them,
// scroll, take a selection, and close on Escape. The words are unchanged; only the way they are shown moved.
const hoverCard = createHoverCard({doc: document, win: window});
const tableTipTargets = bindTipTargets(hoverCard, document, {glossary: text => glossaryDefinitions(text, false)});

const $ = selector => document.querySelector(selector);
const TEAM_COLORS = ["var(--team-0)", "var(--team-1)", "var(--team-2)", "var(--team-3)"];
const TEAM_HEX = {0: "#5fb8e8", 1: "#e8795f", 2: "#c9a2ff", 3: "#e8d25f"};
const FACTORY = "actor:factory.";
// GM_RIDER lines are rules text the engine can't apply yet; the fight skips them, so they only show
// with "details" on (owner 2026-09-25: fights shouldn't be filled with GM rulings).
const NOISE = new Set(["REACTION_WINDOW_OPENED", "INTENT_ACCEPTED", "RESOURCE_SPENT", "TURN_ENDED", "MATCH_CREATED", "GM_RIDER"]);

// What each condition does (owner 2026-09-27: "hover over conditions and have a mechanical description of its effects"),
// loaded once from /api/tabletop/conditions; the hover card and the mini sheet's condition pills show it.
const conditionInfo = {rows: {}, loading: null};
function loadConditionInfo() {
  conditionInfo.loading ||= fetch("/api/tabletop/conditions").then(response => (response.ok ? response.json() : null))
    .then(body => { conditionInfo.rows = body?.conditions || {}; if (app.state) { renderTokens(); } }).catch(() => {});
  return conditionInfo.loading;
}
// Bookkeeping conditions are not shown as conditions: a dropped item lies on the map, and being back under capacity
// is simply normal Speed (combat/carry.py). Encumbered is shown.
// A mark named after a benefit ("Temporary Hit Point") is a misread line of a technique's text, not a mark any rule reads
// (owner 2026-09-28, Bell Strike): it is not shown.
// A player's standing pick for a choose-one ability ("Hammer Rebuke: <choice>", "... _choice") is a setting, not a condition.
const shownCondition = row => !row?.hidden && !/\.(dropped_item|unburdened|shaping|augments|[a-z_]+_(?:choice|pick)|destruction_(?:blast|tether)_type|open_the_gate)$/.test(String(row?.condition_id || ""))
  && !/^condition:typed\.mark\.temporary_hit_points?\./.test(String(row?.condition_id || ""));
// Buffs green, hindrances red, bookkeeping grey (owner 2026-09-28: "buffs should be green debuffs red"; 2026-09-30:
// "debuffs shouldnt be green. green is for buffs not debuffs").
//
// The table decides this, in combat/condition_tone.py, and ships the answer as each condition's `tone` ("harmful",
// "beneficial" or "neutral"), worked out from what the condition does to the creature carrying it and from which side
// applied it. It used to be worked out here from three hand-kept lists of condition names, which is how an enemy's
// "Lethargic" came out green: the list had never been told about that condition. One answer, read by every surface.
const TONE_MEANING = {harmful: "red: this works against it", beneficial: "green: this helps it", neutral: "grey: a note for play"};
function conditionTone(row) {
  const tone = String(row?.tone || "");
  return tone in TONE_MEANING ? tone : "harmful";  // a condition whose tone is unknown is read as a drawback
}
function conditionText(row) {
  const what = conditionTextBody(row);
  if (!what) return "";
  return `${what}. Pill colour: ${TONE_MEANING[conditionTone(row)]}.`;
}
function conditionTextBody(row) {
  const key = String(row?.condition_id || "").split(".").pop();
  if (row?.detail) return row.detail;  // what an area's talent does to those inside (Numbing Darkness)
  const info = conditionInfo.rows[key];
  if (!info) return "";
  const lines = (info.mechanics || []).map(line => line.replace(/\.$/, ""));
  return [lines.join("; "), info.reading].filter(Boolean).join(". ");
}
// The combat log follows new entries unless the owner has scrolled up to read (settleFeed below).
const feedFollow = {on: true, unseen: 0};
const app = {
  matchId: null, state: null, menu: null, lastSequence: 0, busy: false, playing: false,
  selected: new Set(), pendingTurnSelection: null, fog: DEFAULT_FOG_VIEW, explored: null, fogGeometryKey: "", fogPolygons: [], dice: null, diceOn: true, speed: 0.7,
  viewerKey: "", viewerPromptKey: "",
  targeting: null, mapPick: null, showMoves: true, sheets: new Map(), hoverCell: null, dragMove: null, mapKey: "", opaqueKey: "",
  // One open choice for the whole table, shared by the main window and every pop-out sheet. The
  // sheet asks the table to act, so the choice lives here and both windows see the same one
  // (owner playtest 2026-10-03 23:01: a sheet click was refused as "not your turn" while the table
  // was waiting for the player to choose where to centre a Darkness).
  pendingChoice: null,
  // Model seats (seats.js): installed providers and this fight's saved seats / "is deciding" status.
  providers: [], seatStatus: null, seatPoll: null,
  channel: "BroadcastChannel" in window ? new BroadcastChannel("tianxia-tabletop") : null,
};
let refreshSequence = 0;
let seatReadSequence = 0;

// A logical view is local to this tab and match. The URL handle is not authority;
// only a choice made on this screen supplies the binding in sessionStorage.
function browserStorage(name) {
  try { return window[name] || null; } catch { return null; }
}
const requestedView = new URLSearchParams(location.search).get("view");
const viewerStore = createViewerStore({
  viewId: isValidViewId(requestedView) ? requestedView : mintViewId(),
  storage: browserStorage("sessionStorage"),
});
const preferenceStorage = browserStorage("localStorage");
const fogMemoryStore = createFogMemoryStore({
  storage: preferenceStorage,
  backend: indexedMemoryBackend(browserStorage("indexedDB")),
  onReady: () => { if (app.state) render(app.state); },
  onError: () => toast("Remembered squares could not be saved on this device. Keep this tab open; reloading may lose recent memories. Free browser storage to save them.", true),
});
function readPreference(key) {
  try { return preferenceStorage?.getItem(key) ?? null; } catch { return null; }
}
function writePreference(key, value) {
  try { preferenceStorage?.setItem(key, value); } catch { /* optional appearance preference */ }
}

// ------------------------------------------------------------------ setup
const board = createBoard($("#ttViewport"), {
  onCellClick: cell => onCellClick(cell),
  onCellHover: cell => onCellHover(cell),
  onTokenClick: (id, event) => onTokenClick(id, event),
  onTokenDoubleClick: id => { if (!String(id).startsWith("item:") && !String(id).startsWith("object:")) openSheetFor(id); },
  onTokenPointerDown: (id, event) => onTokenPointerDown(id, event),
  onFloorReady: () => refreshFloorMemory(),
}, {rightDragMeasures: true});

// RULER1 (owner feedback desk FD-17): "a ruler tool when you right click on a square and drag it to
// another square it has a line to it and says the length". The ruler reads the same squares the
// engine measures from, using the engine's own distance rule (ruler.js), and writes nothing.
function wireMapRuler(viewport) {
  return createMapRuler({
    viewport,
    // Each end carries the height of the token standing in that square (board.heightAtCell), because
    // the engine counts height as a third axis: a flyer four squares up is 20 ft from the square next
    // to it, not 5 ft. Without it the ruler would report ground distance for an airborne token.
    cellAt: (x, y) => {
      const cell = board.cellAt(x, y);
      if (!cell) return null;
      const z = board.heightAtCell(cell.x, cell.y) || 0;
      return z ? {...cell, z} : cell;
    },
    // Square centres in viewport pixels; the layer is not scaled with the map, so the tag stays readable.
    toPixels: cell => {
      const view = board.view;
      return {x: view.x + (cell.x + 0.5) * CELL * view.zoom, y: view.y + (cell.y + 0.5) * CELL * view.zoom};
    },
    squareSizeFt: () => board.map.square_size_ft || 5,
    onPlainRightClick: () => { if (abilityChoiceActive()) cancelAbilityChoice(); },
  });
}
const ruler = wireMapRuler($("#ttViewport"));

// Ground-image decoding can finish between table renders. Snapshot through the
// normal path using only the latest seen squares, identity and perceived objects.
function refreshFloorMemory() {
  if (app.fogMemoryInputs) board.setRemembered(rememberFog(...app.fogMemoryInputs));
}

function toast(message, error = false) {
  const node = document.createElement("div");
  node.className = `tt-toast${error ? " is-error" : ""}`;
  node.textContent = message;
  $("#ttToasts").appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

// The table follows the app style (Settings > Appearance, /static/appearance-boot.js); its picker
// changes that shared style, so the Factory, the pop-out sheet and the map editor match.
const appearance = window.TianxiaAppearance;
function currentStyle() { return appearance?.current().style || "lacquer"; }

function setTheme(style) {
  if (appearance && style !== currentStyle()) appearance.setStyle(style);
  else showStyle();
}

function showStyle() {
  $("#ttTheme").value = currentStyle();
  app.dice?.setTheme?.(diceTheme());
  if (app.pip && !app.pip.closed) copyAppearance(app.pip.document);
  if (board.map?.background?.style === 'plain') {
    board.setMap(board.map);
    refreshFloorMemory();
  }
}

// Copy the page's style (data-theme and friends, plus custom colours) onto another document.
function copyAppearance(target) {
  const from = document.documentElement, to = target.documentElement;
  for (const name of ["data-theme", "data-heading-font", "data-text-size", "data-motion", "style"]) {
    if (from.hasAttribute(name)) to.setAttribute(name, from.getAttribute(name));
    else to.removeAttribute(name);
  }
}

function diceTheme() {
  const themes = app.diceThemes || {};
  return themes[{lacquer: "crimson", celestial: "midnight", ember: "crimson", classic: "jade"}[currentStyle()]] || themes.crimson;
}

async function loadDice() {
  try {
    const module = await import('./dice3d.js?v=rollreason1');
    app.diceThemes = module.THEMES || {};
    app.dice = module.createDiceTray({theme: diceTheme(), durationMs: 1100});
    app.rollLocal = module.rollLocal;
  } catch (error) {
    console.info("3D dice unavailable", error);
  }
}

// ------------------------------------------------------------------ helpers over the state
const presentation = () => app.state?.presentation;
// A summoned creature that is not out (waiting to be called, dismissed or destroyed) is off the map (combat/summons.py).
const offMap = actor => Boolean(actor.summon_status && actor.summon_status !== "present");
const actors = () => (presentation()?.actors || []).filter(actor => !offMap(actor));
const actorById = id => actors().find(actor => actor.entity_id === id);
const objectById = id => (app.state?.objects || []).find(object => object.id === id);
const projectOf = id => (String(id).startsWith(FACTORY) ? String(id).slice(FACTORY.length) : null);
const teamIndex = actor => Number(actor?.team_index ?? 0);
// Global manual control, independent of this screen's fighter binding. Models
// submit through the engine's manual path but keep their own action controls.
const isManualActor = actor => ["MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"].includes(actor?.controller) && !modelOwner(app.seatStatus, actor);
const automaticSlot = actor => actor && actor.active === false;
// Global controller choice and this screen's identity are separate. Fog and roofs
// share one resolver over the complete roster, including inactive/off-map owners.
const isOwnedActor = actor => currentViewer().isOwned(actor);

function currentViewer() {
  return resolveViewerIdentity(app.matchId ? viewerStore.read(app.matchId) : null, presentation()?.actors || [], app.seatStatus);
}

function isGMView() {
  return currentViewer().status === "gm";
}

function suspendViewerDialogs() {
  // A hidden showModal dialog would still make the page inert. Close only its
  // presentation; keep the exact outstanding answer promise and its handlers.
  const reaction = $("#ttReaction");
  if (reaction?.open) {
    app.viewerSuspendedReaction = {waiting: app.waitingReaction, finish: app.finishReaction, matchId: app.matchId};
    reaction.close();
  }
  for (const id of ["#ttSummary", "#ttSeat", "#ttSeatLog"]) {
    const dialog = $(id);
    if (dialog?.open) dialog.close();
  }
  hoverCard.close();
}

function resumeViewerDialogs() {
  const held = app.viewerSuspendedReaction;
  if (!held || !currentViewer().ready) return;
  app.viewerSuspendedReaction = null;
  if (held.matchId !== app.matchId || held.waiting !== app.waitingReaction
      || held.finish !== app.finishReaction || !held.finish) return;
  const reaction = $("#ttReaction");
  if (reaction && !reaction.open) reaction.showModal();
}

function resetViewerPresentation() {
  const count = (board.map?.width || 0) * (board.map?.height || 0);
  app.explored = count ? new Uint8Array(count) : null;
  app.fogGeometryKey = "";
  app.fogPolygons = [];
  app.selected.clear();
  app.lastTarget = null;
  document.body.classList.add("is-viewer-pending");
  suspendViewerDialogs();
  board.closeHoverCard();
  if (app.pip && !app.pip.closed) {
    const root = app.pip.document.querySelector(".tt-pip-root");
    if (root) root.textContent = "Choose My fighters on the table to see this fight.";
  }
}

function renderViewerIdentity(view = currentViewer()) {
  const names = view.primaryActors.map(actor => actor.display_name || "Unnamed fighter");
  const label = view.status === "gm" ? "Game Master"
    : view.status === "player" ? names.join(", ") : "Choose your fighters";
  const status = $("#ttViewerStatus");
  if (status) status.textContent = `Viewing as: ${label}`;
  const gate = $("#ttViewerGateText");
  if (gate) gate.textContent = !app.matchId ? "Open a fight to choose your view."
    : view.status === "stale" ? "Your saved fighter choice no longer matches this fight. Choose your fighters again."
    : view.reason === "seats-unavailable" ? "Checking who plays these fighters. The map stays covered until their controls are known."
    : "Which fighters do you play on this screen? Choose My fighters to see through their eyes.";
  if (!view.ready) document.body.classList.add("is-viewer-pending");
  const change = $("#ttViewerChange"), another = $("#ttViewerAnother"), retry = $("#ttViewerRetry");
  if (change) change.disabled = !app.state;
  if (another) another.disabled = !app.matchId;
  if (retry) retry.hidden = view.reason !== "seats-unavailable";
  const roofs = $("#ttRoofs");
  if (roofs) { roofs.disabled = view.status !== "gm"; roofs.hidden = view.status !== "gm"; }
  setFogPicker();
}

// Revalidate before every scene, including controller-only and playback refreshes.
// Remembered exploration belongs to the effective identity that acquired it.
function reconcileViewerIdentity() {
  const view = currentViewer();
  const key = JSON.stringify([viewerStore.viewId, app.matchId, view.status, view.ready,
    view.primaryActors.map(actor => actor.entity_id).sort(), [...view.ownedIds].sort(), [...view.teams].sort()]);
  const changed = key !== app.viewerKey;
  if (changed) {
    app.viewerKey = key;
    resetViewerPresentation();
  }
  if (view.status === "gm") app.fog = NO_FOG_VIEW;
  else if (!view.ready || !fogOn(app.fog)) app.fog = DEFAULT_FOG_VIEW;
  renderViewerIdentity(view);
  if (app.state && ["unbound", "stale"].includes(view.status) && app.viewerPromptKey !== key) {
    app.viewerPromptKey = key;
    openViewerPicker();
  }
  return changed;
}

function applyViewerChange() {
  // Remove the prior view's pixels synchronously. State/event reads remain valid:
  // they always include perception and every render resolves the current binding.
  // Fencing those reads here would discard initial history when the picker is
  // confirmed while loadMatch is still fetching it.
  app.viewerKey = "";
  app.viewerPromptKey = "";
  resetViewerPresentation();
  app.fog = currentViewer().status === "gm" ? NO_FOG_VIEW : (viewerStore.readFog(app.matchId) || DEFAULT_FOG_VIEW);
  if (app.state) {
    // A committed animation can be ahead of the last state snapshot. Repaint the
    // displayed positions without asking render() to accept an older snapshot.
    renderTokens();
    renderRoster();
    renderInspector();
    renderHighlights();
    renderActionBar();
    broadcastActors();
    renderPip();
    resumeServerPrompt(app.state);
  } else renderViewerIdentity();
}

function savePlayerView(ids) {
  const candidate = {version: 1, role: "player", actor_ids: ids};
  if (resolveViewerIdentity(candidate, presentation()?.actors || [], app.seatStatus).status !== "player") {
    toast("Choose at least one fighter still in this fight.", true);
    return false;
  }
  viewerStore.bindPlayer(app.matchId, ids);
  $("#ttViewerPicker")?.close();
  applyViewerChange();
  return true;
}

function selectGMView() {
  if (!app.matchId) return;
  viewerStore.bindGM(app.matchId);
  $("#ttViewerPicker")?.close();
  applyViewerChange();
}

function openViewerPicker() {
  const dialog = $("#ttViewerPicker"), choices = $("#ttViewerChoices");
  if (!dialog || !choices || !app.state) return;
  const binding = viewerStore.read(app.matchId);
  const checked = new Set(binding?.role === "player" && Array.isArray(binding.actor_ids) ? binding.actor_ids : []);
  const roster = (presentation()?.actors || []).filter(isPrimaryFighter);
  choices.replaceChildren();
  for (const actor of roster) {
    const row = document.createElement("label"), box = document.createElement("input"), text = document.createElement("span");
    row.className = "tt-viewer-choice";
    box.type = "checkbox";
    box.name = "my-fighters";
    box.value = actor.entity_id;
    box.checked = checked.has(actor.entity_id);
    const name = document.createElement("strong"), detail = document.createElement("span");
    name.textContent = actor.display_name || "Unnamed fighter";
    detail.className = "tt-sub";
    detail.textContent = `Side ${teamIndex(actor) + 1}${actor.active === false ? " · Fallen" : ""}`
      + (isModelSeat(app.seatStatus, actor.entity_id) ? " · Played by a model" : !isManualActor(actor) ? " · Played by AI" : "");
    text.append(name, detail);
    row.append(box, text);
    choices.appendChild(row);
  }
  const note = $("#ttViewerPickerNote");
  if (note) note.textContent = roster.length
    ? "Your summoned creatures follow their summoner automatically. Fighters played by AI or a model remain selected, but do not provide your view until manual play returns."
    : "There are no primary fighters to choose in this fight. You can keep the map covered or explicitly open Game Master view.";
  const apply = $("#ttViewerApply");
  if (apply) apply.disabled = !roster.length;
  if (!dialog.open) dialog.showModal();
}

function mapFromState(state) {
  const battlefield = state.presentation.battlefield;
  const table = state.map || {};
  const scale = table.scale || 1;
  const regions = battlefield.terrain_regions || [];
  const background = table.background || {};
  return {
    width: battlefield.width_squares, height: battlefield.height_squares,
    background: background.asset ? {url: `/api/tabletop/map-assets/${background.asset}`, opacity: (background.opacity_pct ?? 100) / 100, fit: background.fit}
      : {url: null, opacity: 1, style: background.style || "flagstone", seed: background.seed || 1},
    display: {gridOpacity: (table.display?.grid_opacity_pct ?? 35) / 100, detail: (table.display?.detail_pct ?? 100) / 100, gridColor: table.display?.grid_color,
              blend: (table.display?.blend_pct ?? 0) / 100},
    walls: (table.walls || []).map(wall => ({...wall, points: wall.points.map(([x, y]) => [x / scale, y / scale])})),
    openings: table.openings || [],
    objects: table.objects || [],  // authored layout, independent of breaches/fog
    roofs: table.roofs,
    floors: table.floors || [],  // floor patches painted in the map editor (owner 2026-09-28)
    ruleTerrain: table.terrain || [],
    materials: table.materials || [],
    // What every ground material and named terrain is called and what it does, so hovering a square
    // can name its material (owner 2026-09-30; combat/ground_text.py on the state payload).
    ground: state.ground || {},
    trees: table.trees || [],  // trees planted in the map editor (their trunks are in blocked_cells)
    decor: table.decor || [],  // map decoration (decor-art.js): only the look, never a rule
    centerlineCells: centerlineTerrain(regions, state.terrain_occlusion_policy),
    cells: {
      blocked: battlefield.blocked_cells || [], cover: battlefield.cover_cells || [], hazard: battlefield.hazard_cells || [],
      difficult: battlefield.difficult_cells || [],
      // A bamboo stand painted on the map shows that it blocks sight by its own look; the sight tint over it made a box
      // around it (owner 2026-09-29: "there is a green box around it").
      // Every square that blocks sight, for the fog; sightGhost is the ones drawn with a tint (not under a painted bamboo
      // stand, whose own look shows it; owner 2026-09-29: "there is a green box around it").
      sight: regions.filter(region => region.terrain_type === "SIGHT_BLOCKED").flatMap(region => region.cells),
      sightGhost: regions.filter(region => region.terrain_type === "SIGHT_BLOCKED").flatMap(region => region.cells)
        .filter(cell => !groveCells(state).has(`${cell.x},${cell.y}`)),
    },
  };
}

function groveCells(state) {
  return new Set((state.presentation.zones || []).filter(zone => zone.trigger_profile?.shape === "painted" && zone.trigger_profile?.visual?.material === "bamboo")
    .flatMap(zone => zone.affected_cells || []).map(cell => `${cell.x},${cell.y}`));
}

// ------------------------------------------------------------------ loading and rendering
// True only after the table and its event history opened; busy, stale and failed reads return false.
async function loadMatch(matchId) {
  if (app.busy) return false;
  // Reserve the page before the first await/render can schedule autoplay or a click.
  app.busy = true;
  app.playing = false;
  void loadConditionInfo();
  // Opening a different fight throws away any choice this window was holding. Settle its promise
  // instead of dropping it, so nothing is left waiting for a cell in a fight that no longer exists.
  if (app.targeting) cancelTargeting();
  closeChoice();
  app.matchId = matchId;
  seatReadSequence++;
  // Viewer reset clears the old state before this load can fail. Keep its
  // sheet bindings until the load completes so failure can disconnect them.
  app.loadingPresentation = app.state?.presentation;
  app.state = null;
  app.menu = null;
  app.viewerKey = "";
  app.viewerPromptKey = "";
  app.viewerDeferredPrompt = false;
  resetViewerPresentation();
  const binding = viewerStore.read(matchId);
  app.fog = binding?.role === "gm" ? NO_FOG_VIEW : (viewerStore.readFog(matchId) || DEFAULT_FOG_VIEW);
  renderViewerIdentity();
  app.lastSequence = 0;
  app.playedSequence = 0;
  app.movePositions = new Map();
  const loadRequest = ++refreshSequence, fog = app.fog;
  app.selected.clear();
  app.explored = null;
  app.mapKey = "";
  history.replaceState(null, "", tabletopUrl(matchId));
  $("#ttFeed").replaceChildren();
  Object.assign(feedFollow, {on: true, unseen: 0});
  $("#ttFeedJump").hidden = true;
  let loaded = false;
  try {
    // readTableState retries a transient save-in-progress once. A rejected saved
    // format has its own code and opens the notice below without retrying.
    app.seatStatus = null;
    // Seats and providers load beside the state; neither can fail the fight's opening (each catches its own errors).
    const seats = Promise.all([loadSeats(), app.providers?.length ? null : loadProviders()]);
    const state = await readTableState(matchId, fog);
    await seats;
    if (loadRequest !== refreshSequence || app.matchId !== matchId || app.fog !== fog) return false;
    // render resolves the stored binding before the first map or token is drawn.
    // A legacy, empty or stale view stays covered and asks for an explicit choice.
    render(state, {fit: true});
    const eventsRequest = refreshSequence;
    const everything = await api(`/api/tabletop/matches/${enc(matchId)}/events?after=0`);
    if (eventsRequest !== refreshSequence || app.matchId !== matchId) return false;
    const first = state.presentation.initiative_order?.map(actorById).filter(Boolean).map(actor => actor.display_name).join(", ");
    appendTableLine(`Fight started on ${state.presentation.battlefield.display_name}. Initiative: ${first || "—"}.`);
    appendFeed(everything.events);
    app.lastSequence = Math.max(app.lastSequence, everything.last_sequence);
    if (state.pending_action) {
      if (currentViewer().ready) await resumePendingAction(state.pending_action, true);
      else app.viewerDeferredPrompt = true;
    }
    loaded = app.matchId === matchId && Boolean(app.state);
  } catch (error) {
    if (app.matchId !== matchId) return false;
    if (await handleUnavailableFight(error, matchId)) return false;
    closeLoadedFight();
    toast(error.code === "COMBAT_CONTENT_NOT_READY"
      ? "This fight is still being saved or cannot be opened with these rules. Open it again from Fights; if it still fails, keep the saved fight and ask the GM for help."
      : `Could not open the fight: ${error.message}`, true);
    openLobby();
  } finally {
    app.busy = false;
    app.loadingPresentation = null;
    renderActionBar();
    if (loaded) { scheduleAutoPlay(); resumeServerPrompt(app.state); }
  }
  return loaded;
}

// Failed loads must not leave the previous fight's buttons, actors or pending
// choices live. Invalidate in-flight reads before opening any recovery dialog.
function closeLoadedFight() {
  const previous = app.state?.presentation || app.loadingPresentation;
  refreshSequence++;
  clearTimeout(app.seatPoll);
  if (app.targeting) cancelTargeting();
  app.waitingReaction?.stop(null);
  app.finishReaction?.("DECLINE");
  app.mapPick?.close?.("DECLINE");
  closeChoice();
  for (const id of ["#ttSeat", "#ttSeatLog", "#ttSummary"]) {
    const dialog = $(id);
    if (dialog?.open) dialog.close();
  }
  Object.assign(app, {matchId: null, state: null, menu: null, loadingPresentation: null, playing: false, seatStatus: null,
    seatPoll: null, targeting: null, mapPick: null, pendingChoice: null, waitingReaction: null,
    finishReaction: null, dragMove: null, pendingMove: null, hoverCell: null, hoverTarget: null,
    lastTarget: null, lastCurrent: null, pendingTurnSelection: null, lastSequence: 0, playedSequence: 0, explored: null,
    mapKey: "", opaqueKey: "", showItems: false, showShape: null, movePositions: new Map()});
  app.selected.clear();
  document.body.classList.remove("is-working", "is-map-pick");
  hint(null);
  board.setTokens([]);
  board.setZones([]);
  board.setHighlights({});
  board.setMovementExplanation(null);
  board.setFog(null);
  for (const id of ["#ttInitiative", "#ttRoster", "#ttFeed"]) $(id).replaceChildren();
  $("#ttMatchName").textContent = "No fight open";
  $("#ttRound").textContent = "";
  $("#ttFeedJump").hidden = true;
  $("#ttCommitNotice")?.remove();
  history.replaceState(null, "", `/tabletop${squareFogDebug() ? "?fogSquares=1" : ""}`);
  renderInspector(); renderItemsPanel(); renderShapePanel(); renderActionBar(); renderPip();
  for (const actor of previous?.actors || []) {
    app.channel?.postMessage({type: "fight-closed", actor_id: actor.entity_id, match_id: previous.match_id});
  }
}

async function handleUnavailableFight(error, matchId = app.matchId) {
  if (error.code !== "COMBAT_SAVED_FIGHT_UNSUPPORTED" || !matchId || app.matchId !== matchId) return false;
  closeLoadedFight();
  try {
    if (await offerSavedFightRemoval(matchId)) toast("Saved fight deleted.");
  } catch (deleteError) { toast(deleteError.message, true); }
  openLobby();
  return true;
}

function renderCommitNotice(state) {
  let panel = document.getElementById("ttCommitNotice");
  const diagnostic = state.divergence_diagnostic;
  if (!diagnostic?.notice) { panel?.remove(); return; }
  if (!panel) {
    panel = document.createElement("section");
    panel.id = "ttCommitNotice";
    panel.className = "tt-card";
    panel.setAttribute("role", "status");
    document.querySelector(".tt-left").insertAdjacentElement("afterbegin", panel);
  }
  // Only plain player prose is displayed, never structured hashes or ids.
  panel.textContent = [diagnostic.notice, diagnostic.persistence_notice].filter(Boolean).join(" ");
}

// A native action may commit before its menu is built. Keep only the local
// settings across that gap; never carry candidates or choices into another turn.
function reconcileOptionDraft(state) {
  if (app.optionDraft && !app.optionDraft.matches(app.menu, app.matchId)) {
    app.optionDraft = null;
    app.composedAction = null;
  }
  const pending = app.pendingOptionDraft;
  if (pending) {
    const sameTurn = pending.matchId === app.matchId
      && pending.draft.actorId === state.presentation?.current_actor_id
      && pending.round === state.presentation?.round_number && !state.presentation?.terminal;
    if (!sameTurn || !state.menu_pending) {
      app.pendingOptionDraft = null;
      if (sameTurn) app.optionDraft = pending.draft.rebase(app.menu, app.matchId);
    }
  }
}

function render(state, {fit = false, keepBar = false} = {}) {
  // Keep what the server actually sent: a poll delivers the compact movement grid, and the copy
  // rendered below has it expanded. The poll comparison must use the received form or it never matches.
  const received = state;
  if (state.menu?.movement_grid) state = {...state, menu: expandMovementGrid(state.menu)};
  // A state read can precede the events read that follows it. Never redraw an older
  // snapshot over movement we have already played; the next normal refresh catches up.
  if (state.presentation?.match_id === app.matchId && state.last_sequence < (app.playedSequence || 0)) return;
  retainMenuInspection(app.state, state);
  app.state = state;
  app.receivedState = {shown: state, received};
  reconcileViewerIdentity();
  if (!state.pending_action) {
    for (const [id, move] of app.movePositions || []) if (move.pause) app.movePositions.delete(id);
  }
  renderCommitNotice(state);
  // A model plays this decision on the server; its menu is not this player's to press.
  const menuActor = state.menu && (state.presentation?.actors || []).find(a => a.entity_id === state.menu.actor_id);
  app.menu = state.menu && state.menu.manual && !modelOwner(app.seatStatus, menuActor) ? state.menu : null;
  const reconciledDraft = app.optionDraft;
  reconcileOptionDraft(state);
  if (reconciledDraft && reconciledDraft !== app.optionDraft) broadcastDraftStates(reconciledDraft.actorId);
  invalidateTargeting();
  app.lastSequence = Math.max(app.lastSequence, state.last_sequence || 0);
  const p = state.presentation;
  $("#ttMatchName").textContent = p.display_name || "Fight";
  $("#ttRound").textContent = p.terminal ? "Fight over" : `Round ${p.round_number} · ${actorById(p.current_actor_id)?.display_name || "—"}'s turn`;
  const map = mapFromState(state);
  // The shared board defaults to GM for map-editor previews. Supply the table's
  // explicit role before setMap/setTokens can use that default, even under cover.
  board.setRoofView({gm: isGMView(), viewers: [], enabled: !isGMView() || !$("#ttRoofs")?.classList.contains('is-off'),
    seen: isGMView() ? null : new Uint8Array(map.width * map.height)});
  const key = JSON.stringify([map.width, map.height, map.walls, map.objects, map.trees, map.decor, map.background.url, map.cells.blocked, map.cells.sight, map.centerlineCells, map.floors.length]);
  if (key !== app.mapKey) {
    board.setMap(map);
    app.mapKey = key;
    app.explored = new Uint8Array(map.width * map.height);
    if (fit) requestAnimationFrame(() => board.fit());
  }
  // What hides sight: the map's walls and screens, and the walls fighters have raised (owner 2026-09-27),
  // rebuilt when the map changes or a wall rises, falls or has a fighter step into or out of it.
  const owners = new Map((p.actors || []).map(actor => [actor.entity_id, actor]));
  const walls = wallSightCells(p.zones || [], {occupied: (p.actors || []).filter(actor => actor.active && actor.position).map(actor => actor.position),
    hostile: zone => { const owner = owners.get(zone.owner_id); return !owner || teamIndex(owner) !== 0; }});
  const opaqueKey = JSON.stringify([key, walls]);
  if (opaqueKey !== app.opaqueKey) {
    app.opaqueKey = opaqueKey;
    app.opaque = opacityGrid(map.width, map.height, [map.cells.blocked, map.cells.sight], map.centerlineCells);
    for (const [x,y] of walls) app.opaque[y * map.width + x] = 1;
  }
  // When your fighter's turn starts, show its mini sheet; otherwise keep the owner's selection.
  if (p.current_actor_id !== app.lastCurrent) {
    app.lastCurrent = p.current_actor_id;
    app.pendingTurnSelection = null;
    // Chosen-token perception follows only actual clicks, not an automatic turn
    // selection. The normal action/inspector selection still follows turns.
    if (app.fog !== "selected") {
      if (app.menu || app.selected.size === 0) { app.selected.clear(); app.selected.add(p.current_actor_id); }
      else if (state.menu_pending) app.pendingTurnSelection = p.current_actor_id;
    }
  } else if (app.pendingTurnSelection === p.current_actor_id && (app.menu || !state.menu_pending)) {
    // The committed snapshot can precede this human's menu. Complete its turn
    // selection once choices arrive, unless a deliberate token click cancelled
    // it during loading. AI turns and chosen-token perception keep their selection.
    app.pendingTurnSelection = null;
    if (app.menu && app.fog !== "selected") { app.selected.clear(); app.selected.add(p.current_actor_id); }
  }
  // Zones first: the fog-memory snapshot taken inside renderTokens() reads the board's current zone index.
  renderZones();
  renderTokens();
  if (app.fogMemoryInputs) board.setRemembered(rememberFog(...app.fogMemoryInputs));
  renderInitiative();
  renderRoster();
  renderInspector();
  if (keepBar) keepActionBar(); else renderActionBar();
  renderItemsPanel();  // the Items panel follows the fight (it closes when it isn't your fighter's turn)
  renderShapePanel();
  scheduleAutoPlay();
  renderHighlights();
  broadcastActors();
  renderPip();
  scheduleSeatPoll();
  if (state.menu_pending && isManualActor(actorById(p.current_actor_id))
      && actorById(p.current_actor_id)?.active !== false) requestDeferredMenu();
}

let deferredMenuRead = null;
function requestDeferredMenu() {
  // Only choices wait for this read. The committed tokens/feed are already
  // visible, and render cleared the previous candidate/decision binding.
  const stateVersion = app.state?.menu_pending?.state_version;
  if (deferredMenuRead?.matchId === app.matchId && deferredMenuRead.stateVersion === stateVersion)
    return deferredMenuRead.promise;
  const read = {matchId: app.matchId, stateVersion};
  const cancellation = new Promise(resolve => {
    read.stop = () => {
      read.cancelled = true;
      // Release ownership now, not when the abandoned transport eventually settles.
      if (deferredMenuRead === read) deferredMenuRead = null;
      resolve();
    };
  });
  // Deferred state reads also run during AI/model turns. Only a manual
  // player waiting for their menu has choices to cancel here.
  const current = app.state?.presentation?.actors?.find(actor => actor.entity_id === app.state.presentation.current_actor_id);
  read.loadingHint = !!app.state?.menu_pending && !app.menu && current
    && isManualActor(current) && current.active !== false;
  if (read.loadingHint) hint("Loading your turn choices…", () => cancelAbilityChoice());
  read.promise = Promise.race([refresh({choiceRead: read}), cancellation]).finally(() => {
    if (deferredMenuRead === read) {
      deferredMenuRead = null;
      if (read.loadingHint && !app.abilityChoice && !app.targeting && !app.mapPick && !app.listPick) hint(null);
    }
  });
  deferredMenuRead = read;
  return read.promise;
}

// The creatures whose perception the chosen Fog view shows (fog_view.js): this
// screen's bound eligible fighters, their allies, or explicitly chosen tokens.
// Shared perception follows the bound fighters' sides without granting ownership.
function fogAudience() {
  const view = currentViewer();
  if (view.status !== "player" || !view.ready) return [];
  const rows = actors();
  const owned = rows.filter(isOwnedActor);
  if (app.fog === "team") {
    const shared = new Map();
    for (const team of view.teams) for (const actor of fogViewers("team", rows, {owned, team})) shared.set(actor.entity_id, actor);
    return [...shared.values()];
  }
  return fogViewers(app.fog, rows, {owned, selected: app.selected});
}

// Roof occupancy is independent of whose eyes the Fog picker shows. Consume the same
// displayed positions as tokens, but only active, present, positioned owned creatures.
// isOwnedActor resolves this tab's confirmed fighters and their owner chains.
function roofAudience(displayedActors = actors()) {
  return displayedActors.filter(actor => actor && actor.active !== false && actor.position
    && !offMap(actor) && isOwnedActor(actor));
}

function visibility() {
  if (isGMView()) return null;
  const map = board.map;
  if (!map) return new Uint8Array(0);
  const count = map.width * map.height;
  if (!app.explored || app.explored.length !== count) app.explored = new Uint8Array(count);
  app.savedExplored = new Uint8Array(count);
  if (!app.state) return new Uint8Array(count);
  for (const index of Object.keys(rememberedCells().cells)) {
    app.explored[Number(index)] = 1;
    app.savedExplored[Number(index)] = 1;
  }
  const viewers = fogAudience();
  if (!viewers.length) return new Uint8Array(count);
  // The service applies grid LOS, obscurement, directional rules, conditions and senses.
  // The browser only unions each chosen viewer's already-decided perception.
  const perception = app.state.fog_perception || {};
  const seen = perceivedCells(map.width, map.height, viewers, perception);
  for (let index = 0; index < seen.length; index += 1) if (seen[index]) app.explored[index] = 1;
  return seen;
}

// The saved remembered-fog record for this viewer and map (fog_memory.js), read once per page state.
function rememberedCells() {
  if (!app.matchId) return emptyMemory();
  const width = board.map.width;
  const key = memoryKey(app.matchId, `${viewerStore.viewId}:${app.fog}`, width, board.map.height);
  return fogMemoryStore.read(key);
}

// ?fogSquares=1 is a local visual diagnostic for the pre-polygon square mask.
function squareFogDebug() {
  return new URLSearchParams(location.search).get("fogSquares") === "1";
}

// Loading a fight rewrites the address bar to the canonical match address. Local
// visual diagnostics are kept across that rewrite, or ?fogSquares=1 would silently
// stop working on the first refresh.
function tabletopUrl(matchId, viewId = viewerStore.viewId) {
  return `/tabletop?match=${enc(matchId)}&view=${enc(viewId)}${squareFogDebug() ? "&fogSquares=1" : ""}`;
}

function fogGeometry(seen) {
  // Only GM view may use live blocker sources without a perception mask.
  if ((!seen && !isGMView()) || !app.state) return {polygons: []};
  const map = board.map, p = presentation();
  const viewers = fogAudience().filter(actor => actor.position)
    .map(actor => ({entity_id: actor.entity_id, team_index: actor.team_index, altitude_ft: actor.altitude_ft,
      footprint: actor.footprint, position: {
      x: actor.position.x + (actor.footprint?.width_cells || 1) / 2,
      y: actor.position.y + (actor.footprint?.height_cells || 1) / 2,
      z: actor.position.z ?? 0,
    }}));
  const treeKeys = new Set(map.trees.flatMap(treeCells).map(([x, y]) => `${x},${y}`));
  const wallKeys = new Set();
  const walls = map.walls.map(wall => {
    const cells = [...wallCells(wall, map.width, map.height)].map(index => [index % map.width, Math.floor(index / map.width)]);
    cells.forEach(([x, y]) => wallKeys.add(`${x},${y}`));
    return {...wall, occluder: app.state.terrain_occlusion_policy === 'cross-v1' ? wall.occluder : 'cell', cells};
  });
  // Physical walls already have authoritative bound geometry, including
  // occupied-cell exemptions. Only obscures-only walls need a supplement.
  const zoneRows = Object.values(p.zones || {});
  const dynamicZones = app.state.fog_geometry?.lines ? zoneRows.filter(zone =>
    !zone?.trigger_profile?.wall?.blocks_movement && !zone?.trigger_profile?.wall?.blocks_sight) : zoneRows;
  const dynamicCells = wallSightCells(dynamicZones, {occupied: [], hostile: () => true});
  const owners = new Map((p.actors || []).map(actor => [actor.entity_id, actor]));
  const viewerCells = viewers.map(viewer => wallSightCells(dynamicZones, {occupied: [],
    hostile: zone => { const owner = owners.get(zone.owner_id);
      return !owner || Number(owner.team_index ?? 0) !== Number(viewer.team_index ?? 0); }}));
  const blockedCells = [...map.cells.blocked, ...map.cells.sight]
    .filter(cell => { const x = Array.isArray(cell) ? cell[0] : cell.x, y = Array.isArray(cell) ? cell[1] : cell.y;
      return !wallKeys.has(`${x},${y}`) && !treeKeys.has(`${x},${y}`); });
  const objects = (app.state.objects || []).filter(row => row.hp > 0);
  const renderTreeCells = [...treeKeys];
  const bambooCells = (map.materials || []).filter(row => row.material === 'terrain:bamboo thicket')
    .flatMap(row => row.cells || []).map(cell => `${cell[0]},${cell[1]}`);
  const key = JSON.stringify([altitudeFogKey(viewers, app.state.fog_geometry),
    walls, map.trees, map.materials, objects, blockedCells, dynamicCells, viewerCells, map.centerlineCells, map.width, map.height]);
  if (key !== app.fogGeometryKey) {
    app.fogGeometryKey = key;
    const bound=app.state.fog_geometry;
    const centerlineCells=bound?.lines ? (bound.volumes || []).filter(r=>r.mode==='centerline' && r.bottom_ft<=0 && (r.top_ft==null || r.top_ft>0)).map(r=>[r.x,r.y]) : map.centerlineCells;
    const geometry = {walls, trees: map.trees, objects, blockedCells, dynamicCells, sources:bound?.lines, centerlineCells, width: map.width, height: map.height};
    app.fogBlockerGeometry = geometry;
    const airborne = app.state.fog_geometry ? viewers.filter(v=>viewerEye(v)>0) : [];
    const altitudeGeometry={...(app.state.fog_geometry || {}),treeCells:renderTreeCells,bambooCells,trees:map.trees};
    app.fogPolygons = [...viewers.flatMap((viewer,index)=>airborne.includes(viewer) ? [] :
      visibilityPolygons([viewer], blockerSegments({...geometry,dynamicCells:viewerCells[index]}), map.width, map.height)),
      ...altitudeVisibilityPolygons(airborne, altitudeGeometry, map.width, map.height)];
  }
  // ?fogSquares=1 is a local visual diagnostic for the pre-polygon square mask.
  const marks = {blockerGeometry:app.fogBlockerGeometry, blockerHeights:app.state.fog_geometry};
  return squareFogDebug()
    ? {squareFog: true,...marks} : {polygons: app.fogPolygons,...marks};
}

// Remembered fog (fog_memory.js): snapshot what each viewer perceives on the squares they see now,
// and return the greyed copies of squares they saw earlier. GM view and fog-off return nothing.
// A snapshot holds only what was perceived on that square: its terrain and zones as the board showed them,
// and the enemies and objects the viewers could see there.
function rememberFog(seen, displayedActors, perceivedObjectIds) {
  if (!seen || isGMView() || !app.matchId || !app.state) return null;
  const width = board.map.width;
  const key = memoryKey(app.matchId, `${viewerStore.viewId}:${app.fog}`, width, board.map.height);
  const memory = rememberedCells();
  if (!fogMemoryStore.ready(key)) return null;
  const enemies = displayedActors.filter(actor => !isOwnedActor(actor) && !unseenByViewers(actor));
  const objects = (app.state.objects || []).filter(row => row.hp > 0 && perceivedObjectIds?.has(row.id));
  const next = recordSeen(memory, seen, index => {
    const x = index % width, y = Math.floor(index / width);
    return {
      terrain: board.terrainAt(x, y),
      zones: board.zonesAt(x, y),
      blockers: board.blockersAt(x, y),
      floor: board.floorRecordAt(x, y),
      scenery: board.sceneryRecordAt(x, y),
      tokens: enemies.filter(actor => Math.floor(actor.position.x) === x && Math.floor(actor.position.y) === y)
        .map(actor => ({id: actor.entity_id, name: actor.display_name, label: initials(actor.display_name),
          color: TEAM_HEX[teamIndex(actor)] || TEAM_HEX[0], image: tokenImage(actor), x, y})),
      objects: objects.filter(row => row.x === x && row.y === y).map(row => {
        const art = board.objectArtRecordAt(row.id);
        return {id: row.id, name: row.name, kind: row.kind, x, y, ...(art ? {art} : {})};
      }),
    };
  }, {visibleTokenIds: displayedActors.filter(actor => !unseenByViewers(actor)).map(actor => actor.entity_id),
    // Ids the service confirmed are in this fight, plus the creatures the viewer sees now. Without a confirmation
    // (no snapshot recorded yet) nothing is purged by identity.
    validTokenIds: app.state.remembered_in_match
      ? new Set([...app.state.remembered_in_match, ...displayedActors.filter(actor => !unseenByViewers(actor)).map(actor => actor.entity_id)])
      : null,
    // Names come only from creatures the viewer sees right now. The full roster also names creatures outside sight,
    // and using it would rewrite an unseen creature's remembered alias with its real name (a leak).
    rosterNames: new Map(displayedActors.filter(actor => !unseenByViewers(actor)).map(actor => [actor.entity_id,
      {name: actor.display_name, label: initials(actor.display_name)}]))});
  app.fogMemory = {key, memory: next};
  fogMemoryStore.save(key, next);
  const rememberedIds = new Set();
  for (const cell of Object.values(next.cells)) for (const token of cell.tokens || []) if (token.id) rememberedIds.add(token.id);
  try { preferenceStorage?.setItem(tokenIdsKey(app.matchId, app.fog), JSON.stringify([...rememberedIds].slice(0, 400))); }
  catch { /* optional: the next read then asks for nothing and purges nothing by identity */ }
  const ghosts = ghostCells(next, seen);
  // A remembered square the viewer no longer sees is drawn from its record only if what is perceived there has changed.
  const changed = ghosts.filter(index => {
    const record = next.cells[index], x = index % width, y = Math.floor(index / width);
    // Compare with what is really there now, not with what is perceived now: an unseen square perceives no objects, so a
    // perceived-only list would mark every remembered square with objects as changed. Equal state means the live art
    // shows exactly the remembered look, so this reveals nothing.
    const liveObjects = (app.state.objects || []).filter(row => row.hp > 0 && row.x === x && row.y === y)
      .map(row => ({id: row.id, name: row.name, kind: row.kind, x, y}));
    // A zone is compared by its id, owner and name, not by colour: the colour an area is outlined in depends on whether
    // its owner is on the roster, which is not something the viewer saw on the square. A different area (another
    // caster's Darkness, same name) is a real change and keeps the remembered square over the live one.
    const zoneIdentity = zones => zones.map(zone => [zone.id, zone.owner, zone.name]);
    const objectIdentity = rows => (rows || []).map(row => [row.id, row.name, row.kind, row.x, row.y]);
    return (Object.hasOwn(record, 'scenery') && record.scenery !== board.sceneryRecordAt(x, y)) ||
      JSON.stringify([record.terrain, zoneIdentity(record.zones || []), objectIdentity(record.objects)])
      !== JSON.stringify([board.terrainAt(x, y), zoneIdentity(board.zonesAt(x, y)), objectIdentity(liveObjects)]);
  });
  return {cells: next.cells, ghosts, changed, width};
}

// Invisible or Hidden (owner 2026-09-29): with fog on, a fighter off the viewing side is left off the map unless one of the
// viewers perceives it according to the server's shared perception result.
function viewerIds() {
  if (isGMView()) return null;
  return new Set(fogAudience().map(actor => actor.entity_id));
}

function unseenByViewers(actor) {
  const viewers = viewerIds();
  if (viewers === null) return false;
  // The shared vision helper's legacy empty-list behavior is permissive. A
  // player with no effective viewer must hide every creature, including tokens
  // drawn above the fog canvas.
  if (!viewers.size) return true;
  const selected = actors().filter(row => viewers?.has(row.entity_id));
  return tokenHiddenByFog(actor, selected, app.state?.fog_perception || {}, true);
}

// Initials, numbered when two fighters share them (Lian Feng / Lingyue Frostveil -> LF1, LF2).
function tokenLabels() {
  const counts = new Map(), seen = new Map(), labels = new Map();
  for (const actor of actors()) counts.set(initials(actor.display_name), (counts.get(initials(actor.display_name)) || 0) + 1);
  for (const actor of actors()) {
    const base = initials(actor.display_name);
    if (counts.get(base) > 1) { seen.set(base, (seen.get(base) || 0) + 1); labels.set(actor.entity_id, `${base}${seen.get(base)}`); }
    else labels.set(actor.entity_id, base);
  }
  return labels;
}

// Use the projected creature footprint, with a smaller rider centred over its mount.
// This geometry also anchors target outlines to the creature the player chose.
function tokenGeometry(actor, displayedActors = actors()) {
  const bond = (actor.conditions || []).find(row => row.condition_id === "condition:typed.mounted" && row.source_actor_id);
  const mount = bond && displayedActors.find(row => row.entity_id === bond.source_actor_id);
  const width = actor.footprint?.width_cells || 1, height = actor.footprint?.height_cells || 1;
  const scale = mount ? 0.8 : 1;
  return {width, height, scale, ridingOn: mount?.entity_id || null,
    offsetX: mount ? mount.position.x + ((mount.footprint?.width_cells || 1) - width * scale) / 2 - actor.position.x : 0,
    offsetY: mount ? mount.position.y + ((mount.footprint?.height_cells || 1) - height * scale) / 2 - actor.position.y : 0};
}

function renderTokens() {
  reconcileViewerIdentity();
  const p = presentation();
  if (!p) return;
  const labels = tokenLabels();
  const seen = visibility();
  const width = board.map.width;
  const targetable = new Set(app.targeting ? app.targeting.byTarget.keys() : []);
  // The request rolls back while waiting for an answer. Show its pause snapshot without
  // changing committed state; mounted offsets must use the same temporary positions.
  const displayedActors = actors().map(actor => {
    const move = app.movePositions?.get(actor.entity_id);
    if (move && app.state.last_sequence >= move.sequence) app.movePositions.delete(actor.entity_id);
    const position = app.mapPick?.positions?.get(actor.entity_id)
      || (app.movePositions?.get(actor.entity_id)?.position);
    return position ? {...actor, position} : actor;
  }).filter(actor => actor.position);
  const objectPerceived = seen ? perceivedObjects(fogAudience(), app.state.fog_perception, app.state.objects) : null;
  board.setTokens(displayedActors.map(actor => {
    const geometry = tokenGeometry(actor, displayedActors);
    const hiddenByFog = unseenByViewers(actor);
    return {
      // Presentation positions may contain only x/y; altitude_ft supplies their height.
      // Explicit event/placement z still wins while showing a temporary position.
      id: actor.entity_id, x: actor.position.x, y: actor.position.y, z: actor.position.z ?? heightFeet(actor) / 5, name: actor.display_name, label: labels.get(actor.entity_id),
      altitudeFt: heightFeet(actor), flightDetail: flightText({...actor, altitude_ft: heightFeet(actor)}, board.map),
      fly_speed_ft: actor.fly_speed_ft, hover: actor.hover,
      movementSummary: !app.targeting && app.state?.menu?.movement_explanation?.summary?.actor_id === actor.entity_id
        ? app.state.menu.movement_explanation.summary : null,
      color: TEAM_HEX[teamIndex(actor)] || TEAM_HEX[0], hp: actor.hit_points.current, maxHp: actor.hit_points.maximum,
      current: actor.entity_id === p.current_actor_id && !p.terminal, selected: app.selected.has(actor.entity_id),
      targetable: targetable.has(actor.entity_id), down: !actor.active, hidden: hiddenByFog, yours: isOwnedActor(actor),
      ...tokenSensePresentation(actor, fogAudience(), app.state?.fog_perception || {}, !isGMView()),
      lifeStatus: actor.life_status_text || "",
      unseen: (actor.conditions || []).some(row => ["condition:typed.invisible", "condition:typed.hidden"].includes(row.condition_id)),
      badge: actor.life_status_text === "Dead" ? "Dead" : actor.life_state === "DYING" ? "Dying" : actor.life_state === "STABLE" ? "Stable" : actor.life_state === "CONSCIOUS" ? "Conscious at 0 HP" : "",
      size: geometry.width, height: geometry.height, scale: geometry.scale,
      ridingOn: geometry.ridingOn, offsetX: geometry.offsetX, offsetY: geometry.offsetY,
      // Its conditions (owner 2026-09-27: "When I hover over enemies id like to see what conditions they have"),
      // shown on hover and marked on the token.
      conditions: hiddenByFog || actor.life_status_text === "Dead" ? [] : (actor.conditions || []).filter(shownCondition).map(row => ({
        name: row.display_name || "Condition",
        stacks: row.stacks || 1, until: row.expires_on || null, text: conditionText(row), tone: conditionTone(row)}))
        .concat((actor.roll_effects || []).map(text => ({name: "Roll effect", text, stacks: 1}))),
      temp: actor.hit_points.temporary || 0,
      // Its circle token (owner 2026-09-27: combat/portraits.py), else a token image the fight carries.
      image: tokenImage(actor),
      // A fighter that sheds light ({radius_ft, color, level}, e.g. a Ghost Lantern) glows on the floor.
      light: actor.light || null,
    };
  }).concat((app.state.items || []).map(item => ({
    // A weapon knocked away by a Disarm, lying where it fell until its owner picks it up.
    // (A formation array's Eye, Node or Anchor is drawn the same way, with its own symbol and colour.)
    id: item.id, x: item.x, y: item.y, name: item.name, label: item.label || "⚔", item: true, color: item.color || "#9aa3ad", hp: 1, maxHp: 1,
    hidden: Boolean(seen && !seen[item.y * width + item.x]),
  }))).concat(tableObjectTokens(app.state.objects, targetable, app.state.presentation.battlefield.blocked_cells || [], seen, width, String(app.state.map?.background?.seed ?? app.state.map?.map_id ?? ""), objectPerceived)));
  board.setRoofView({viewers: roofAudience(displayedActors),
    gm: isGMView(), enabled: !isGMView() || !$("#ttRoofs")?.classList.contains('is-off'), seen});
  board.setFog(seen, app.explored, fogGeometry(seen), app.savedExplored);
  app.fogMemoryInputs = [seen, displayedActors, objectPerceived];  // snapshot taken by refresh after zones and tokens
  // This is the only release of the HTML's initial cover, after tokens, fog and
  // roofs all reflect the same validated identity in this synchronous render.
  document.body.classList.toggle("is-viewer-pending", !currentViewer().ready);
  resumeViewerDialogs();
}

// Lasting zones (owner 2026-09-27): each drawn with its own material, haze, darkness or light,
// edged in its owner's team colour.  The engine decides what a zone does; this only shows it.
function renderZones() {
  const p = presentation();
  const everyone = p?.actors || [];  // including summons off the map: a zone outlives its caster's position
  board.setZones(p?.zones || [], {
    round: p?.round_number ?? 0,
    teamOf: ownerId => {
      const owner = everyone.find(actor => actor.entity_id === ownerId);
      return owner ? {color: TEAM_HEX[teamIndex(owner)] || TEAM_HEX[0], owner: owner.display_name, foe: teamIndex(owner) !== 0} : null;
    },
  });
}

// A creature's token art: its circle portrait (combat/portraits.py), else an image the fight carries.
function tokenImage(actor) {
  return (app.state.tokens || {})[actor.entity_id] || (actor.visual && actor.visual.kind === "image" ? actor.visual.public_url : null);
}

function renderInitiative() {
  const list = $("#ttInitiative");
  list.replaceChildren();
  const p = presentation();
  for (const id of p.initiative_order || []) {
    const actor = actorById(id);
    if (!actor) continue;
    const item = document.createElement("li");
    item.className = `${!p.terminal && id === p.current_actor_id ? "is-current" : ""} ${actor.active ? "" : "is-down"}`;
    const button = document.createElement("button");
    button.type = "button";
    // Its token art when it has one (owner 2026-10-06), else its initials, ringed in its team colour.
    const dot = document.createElement("span");
    dot.className = "tt-init-dot";
    dot.style.setProperty("--team", TEAM_COLORS[teamIndex(actor)] || TEAM_COLORS[0]);
    const image = tokenImage(actor);
    if (image) {
      const img = document.createElement("img");
      img.src = image;
      img.alt = "";
      img.addEventListener("error", () => { dot.replaceChildren(initials(actor.display_name)); });
      dot.appendChild(img);
    } else dot.textContent = initials(actor.display_name);
    button.append(dot, document.createElement("span"));
    // Labelled so a newcomer can read it: hit points, and the initiative it rolled (owner 2026-10-06).
    const init = actor.initiative ?? null;
    button.lastChild.textContent = `${actor.display_name} · HP ${actor.hit_points.current}${init === null ? "" : ` · Init ${init}`}${actor.life_state ? ` · ${actor.life_state === "DYING" ? "Dying" : actor.life_state === "CONSCIOUS" ? "Conscious at 0 HP" : "Stable"}` : ""}`;
    button.title = `${actor.display_name} — ${isManualActor(actor) ? "played by you" : "AI"}`;
    button.addEventListener("click", () => { selectActor(id); board.centerOn(actor.position.x, actor.position.y); });
    item.appendChild(button);
    list.appendChild(item);
  }
}

function renderRoster() {
  const host = $("#ttRoster");
  host.replaceChildren();
  const teams = presentation().teams || [];
  for (const team of teams) {
    const heading = document.createElement("div");
    heading.className = "tt-roster-team";
    heading.textContent = team.display_name;
    host.appendChild(heading);
    for (const id of team.actor_ids) {
      const actor = actorById(id);
      if (!actor) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = app.selected.has(id) ? "is-selected" : "";
      button.innerHTML = `<span class="tt-init-dot" style="--team:${TEAM_COLORS[teamIndex(actor)]}">${initials(actor.display_name)}</span><span><strong></strong><br><small></small></span><small></small>`;
      button.querySelector("strong").textContent = actor.display_name;
      button.querySelectorAll("small")[0].textContent = playedByWord(actor);
      button.querySelectorAll("small")[1].textContent = actor.life_status_text || (actor.life_state ? (actor.life_state === "DYING" ? "Dying" : actor.life_state === "CONSCIOUS" ? "Conscious at 0 HP" : "Stable") : actor.active ? `${actor.hit_points.current}/${actor.hit_points.maximum}` : "Defeated");
      button.addEventListener("click", () => { selectActor(id); board.centerOn(actor.position.x, actor.position.y); });
      host.appendChild(button);
    }
  }
}

function pct(current, maximum) { return maximum ? Math.max(0, Math.min(100, (current / maximum) * 100)) : 0; }
function movementLeft(actor) {
  const walking = actor.walking_distance_remaining_ft == null ? `${actor.movement_remaining_ft} ft` :
    `Crawl up to ${actor.walking_distance_remaining_ft} ft (${actor.movement_remaining_ft} ft movement)`;
  return walking + (actor.fly_speed_ft ? ` · fly up to ${actor.flying_movement_remaining_ft} ft` : "");
}

function renderInspector() {
  renderInformation($("#ttInformation"), app.state,
    currentViewer().status === "player" && currentViewer().ready ? actors().filter(isOwnedActor) : []);
  const host = $("#ttInspector");
  const acWasOpen = hoverCard.isOpen && hoverCard.trigger?.hasAttribute("data-ac-breakdown") && host.contains(hoverCard.trigger);
  const id = [...app.selected].at(-1);
  const actor = id && actorById(id);
  if (!actor) { host.innerHTML = `<p class="tt-muted">Click a token to see its mini sheet.</p>`; return; }
  const primary = Boolean(actor.primary_combatant);
  const ac = (actor.defenses || []).find(row => row.defense_id === "defense:armor_class")?.value ?? "—";
  const turn = actor.turn_state || {};
  const resources = (actor.resources || []).filter(row => !String(row.resource_id).startsWith("resource:uses.") && row.maximum > 0);
  const project = projectOf(id);
  host.innerHTML = `
    <div class="tt-mini-head">
      <span class="tt-mini-portrait" style="--team:${TEAM_COLORS[teamIndex(actor)]}">${initials(actor.display_name)}</span>
      <div><h2></h2><div class="tt-sub"></div></div>
    </div>
    <div class="tt-sub">HP ${actor.hit_points.current} / ${actor.hit_points.maximum}${actor.hit_points.temporary ? ` (+${actor.hit_points.temporary} temp)` : ""}</div>
    <div class="tt-bar"><i style="width:${pct(actor.hit_points.current, actor.hit_points.maximum)}%"></i></div>
    ${concentrationCard(actor, !unseenByViewers(actor))}
    ${actor.death_saves ? `<div class="tt-sub">Death saving throws: ${actor.death_saves.ok} successes, ${actor.death_saves.bad} failures (3 successes: Stable; 3 failures: dies).</div>` : ""}
    ${resources.map(row => `<div class="tt-sub" tabindex="0" data-tip="${escapeHtml(resourceText(row))}">${escapeHtml(row.display_name)} ${row.current} / ${row.maximum}</div><div class="tt-bar res"><i style="width:${pct(row.current, row.maximum)}%"></i></div>`).join("")}
    <div class="tt-mini-stats">
      <div class="tt-stat" tabindex="0" role="button" data-ac-breakdown data-tip-click aria-label="Armor Class. Show breakdown." data-tip="${escapeHtml(TianxiaSheetViewModel.armorBreakdown({}, {...actor, armor_class: ac}))}"><b>${ac}</b><span>AC</span></div>
      <div class="tt-stat"><b>${actor.speed_ft}</b><span>Speed</span></div>
      <div class="tt-stat" title="${movementLeft(actor)}"><b>${actor.walking_distance_remaining_ft ?? actor.movement_remaining_ft}</b><span>${actor.walking_distance_remaining_ft == null ? "Move left" : "Crawl left (ft)"}</span></div>
    </div>
    ${flightText(actor, board.map) ? `<div class="tt-sub">${escapeHtml(flightText(actor, board.map))}</div>` : ""}
    <div class="tt-pills">
      ${economyPills(turn)}
      ${(actor.conditions || []).filter(shownCondition).map(row => `<span class="tt-pill is-condition is-${conditionTone(row)}" data-tip="${escapeHtml(conditionText(row))}">${escapeHtml(row.display_name || "Condition")}</span>`).join("")}
    </div>
    ${(actor.roll_effects || []).map(text => `<div class="tt-sub">${escapeHtml(text)}</div>`).join("")}
    ${primary ? `<div class="tt-select-label">Played by
      ${playedByHtml(app.providers)}
    </div>${modelOwner(app.seatStatus, actor) ? `<div class="tt-sub tt-seat-note">Played by ${escapeHtml(providerLabel(app.providers, app.seatStatus.seats[modelOwner(app.seatStatus, actor)].provider_id))} · <button class="tt-link" type="button" data-seat-log>What it decided</button></div>` : ""}` : ""}
    ${primary ? `<div class="tt-select-label">${escapeHtml(actor.ai_label || "AI: Tricky")} — this fight only
      <button class="tt-tool" type="button" data-ai-tier="TRICKY">Tricky</button>
      <button class="tt-tool" type="button" data-ai-tier="MASTERMIND" title="Mastermind currently uses Tricky tactics.">Mastermind</button></div>` : ""}
    <div class="tt-mini-actions">
      ${primary && project ? `<button class="tt-tool" data-sheet type="button">Open full sheet</button>` : ""}
      <button class="tt-tool" data-center type="button">Center</button>
    </div>`;
  host.querySelector("h2").textContent = actor.display_name;
  host.querySelector(".tt-mini-head .tt-sub").textContent = `${actor.team_display_name || ""}${actor.controller ? ` · ${playedByWord(actor)}` : ""}`;
  // Buttons, not a dropdown: a focused <select> changed on a mouse-wheel turn or a typed "a" and handed a played
  // character to the AI (owner 2026-09-29, Tabik). Only a click on the other button changes who plays.
  const current = modelOwner(app.seatStatus, actor) ? "MODEL" : actor.controller === "SUGGESTED" ? "SUGGESTED" : controlOf(app.seatStatus, id, isManualActor(actor));
  for (const control of host.querySelectorAll("[data-control]")) {
    const mine = control.dataset.control === current;
    control.classList.toggle("is-active", mine);
    control.setAttribute("aria-pressed", String(mine));
    control.disabled = Boolean(presentation().terminal);
    control.addEventListener("click", () => {
      if (control.dataset.control === "MODEL") openSeatPicker(id);
      else if (!mine) setControl(id, control.dataset.control);
    });
  }
  for (const button of host.querySelectorAll("[data-ai-tier]")) {
    button.disabled = Boolean(presentation().terminal);
    button.setAttribute("aria-pressed", String(button.dataset.aiTier === actor.ai_tier));
    button.addEventListener("click", async () => {
      try {
        // Presentation labels (including model seats) are not stored control modes.
        // Read the fight's current assignment; a tier click must not change who plays.
        const match = await api(`/api/combat/matches/${enc(app.matchId)}`);
        const mode = match.metadata?.participant_control_modes?.[id] || "MANUAL";
        await api(`/api/combat/matches/${enc(app.matchId)}/controller-mode`, {body: {
          actor_id: id, controller_mode: mode, ai_tier: button.dataset.aiTier}});
        await refresh();
      } catch (error) { toast(error.message, true); }
    });
  }
  host.querySelector("[data-sheet]")?.addEventListener("click", () => openSheetFor(id));
  host.querySelector("[data-seat-log]")?.addEventListener("click", openSeatLog);
  host.querySelector("[data-center]").addEventListener("click", () => board.centerOn(actor.position.x, actor.position.y));
  const acTrigger = host.querySelector("[data-ac-breakdown]");
  if (acTrigger) {
    const acModel = TianxiaSheetViewModel.armorCard({}, {...actor, armor_class: ac});
    acTrigger.tipCard = (doc, options) => renderTipCard(doc, acModel, options);
  }
  if (acWasOpen) tableTipTargets.show(acTrigger);
  if (primary) void sheetFor(id).then(sheet => {
    // An asynchronous sheet response must not overwrite a newly selected actor.
    if (acTrigger?.isConnected && sheet) {
      acTrigger.dataset.tip = TianxiaSheetViewModel.armorBreakdown(sheet.summary?.armor_breakdown || {}, {...actor, armor_class: ac});
      const acModel = TianxiaSheetViewModel.armorCard(sheet.summary?.armor_breakdown || {}, {...actor, armor_class: ac});
      acTrigger.tipCard = (doc, options) => renderTipCard(doc, acModel, options);
      if (hoverCard.isOpen && hoverCard.trigger === acTrigger) tableTipTargets.show(acTrigger);
    }
  });
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
}

// ------------------------------------------------------------------ action bar
async function sheetFor(actorId) {
  const project = projectOf(actorId);
  if (!project) return null;
  if (!app.sheets.has(project)) {
    app.sheets.set(project, api(`/api/tabletop/characters/${enc(project)}/sheet`).catch(() => null));
  }
  return app.sheets.get(project);
}

function reasonFor(actor, button) {
  const serverReason = typeof app !== "undefined" ? app.state?.unavailable_reasons?.[button.id] : null;
  if (serverReason) return serverReason;
  const turn = actor.turn_state || {};
  if (button.economy === "ACTION" && !turn.action) return "Action already used this turn";
  if (button.economy === "BONUS_ACTION" && !turn.bonus_action) return "Bonus action already used this turn";
  // Reaction sheet help predates turn-action availability. Keep its warning;
  // the actual reaction checkpoint still decides payment and legal choices.
  const cost = button.detail?.cost;
  if (cost && button.economy === "REACTION") {
    const [amount, ...rest] = String(cost).split(",")[0].trim().split(" ");
    const resource = (actor.resources || []).find(row => row.display_name.toLowerCase().includes(rest.join(" ").toLowerCase()));
    if (resource && Number(amount) > resource.current) return `Needs ${cost} (you have ${resource.current})`;
  }
  // Trigger/control help is in the shared summary, including when cost is unavailable.
  if (button.economy === "REACTION") return "";
  return "Unavailable now: this action has no legal option under the current combat rules.";
}

function actionRules(text, summary) {
  const help = document.createElement("details");
  help.className = "tt-action-rules";
  const head = document.createElement("summary");
  head.textContent = "Full rules";
  head.title = summary;
  help.appendChild(head);
  const lead = document.createElement("p");
  lead.textContent = summary;
  help.appendChild(lead);
  const h = (tag, attrs, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    node.append(...children.flat());
    return node;
  };
  help.appendChild(renderRules(text, h, line => [line.replace(/\*\*|`/g, "")]));
  return help;
}

function buttonDetail(button) {
  const detail = button.detail || {};
  return [detail.to_hit && `${detail.to_hit} to hit${detail.attacks > 1 ? ` ×${detail.attacks}` : ""}`, detail.save, detail.damage, detail.cost]
    .filter(Boolean).join(" · ") || ({ACTION: "Action", BONUS_ACTION: "Bonus action", FREE: "Free"}[button.economy] || "");
}

// What a fight button costs, in words: "Action", "Bonus", "Free", "Hold".
// The compiled economy is the truth about cost: a free setting (an augment toggle, a stance, a setup pick) is
// offered as a free action, so its kind says "free" and not what it costs.  Rows with no compiled economy (a
// prepared attack, a reaction) fall back to the kind, which is all they have.
function costTag(row) {
  return (row.cost_label || {ACTION: "Action", BONUS_ACTION: "Bonus", NONE: "Free", REACTION: "Reaction"}[row.economy]
    || {ACTION: "Action", BONUS_ACTION: "Bonus", HOLD_POSITION: "Hold"}[row.kind] || row.kind);
}

// The end-of-fight summary: every fighter's recorded damage, healing, hits, saves and costs (fight-summary.js).
function openFightSummary() {
  const p = presentation();
  const dialog = $("#ttSummary");
  if (!p || !dialog || !currentViewer().ready) return;
  const teamOf = id => (p.teams || []).find(team => team.team_id === id || team.runtime_team_ids?.includes(id));
  const result = p.terminal_result || {};
  $("#ttSummaryBody").innerHTML = fightSummaryHtml(app.state?.summary, {
    // Every actor, including summons that have left the map, so a departed summon keeps its name and portrait.
    nameOf: id => (p.actors || []).find(actor => actor.entity_id === id)?.display_name,
    imageOf: id => { const actor = (p.actors || []).find(row => row.entity_id === id); return actor ? tokenImage(actor) : null; },
    initials, teamName: id => teamOf(id)?.display_name || "Team",
    teamColor: id => TEAM_COLORS[Math.max(0, (p.teams || []).indexOf(teamOf(id)))] || TEAM_COLORS[0],
    winner: result.winning_team_id || null,
  });
  if (!dialog.open) dialog.showModal();
}

// ------------------------------------------------------------------ model seats (seats.js)
// Who plays a fighter, in one word for the roster and the inspector.
function playedByWord(actor) {
  if (modelOwner(app.seatStatus, actor)) return "Model";
  if (actor?.controller === "SUGGESTED") return "Assisted";
  return isManualActor(actor) ? "You" : "AI";
}

// Installed models for the setup "Who plays" menus. A failed fetch keeps the last list and retries (provider-list.js, SEATLIST1).
const providerList = createProviderList({fetchProviders: () => api("/api/tabletop/providers"), onChange: refreshSetupProviders});
let renderedProviderKey = null;
async function loadProviders() { await providerList.load(); }

// Keeps the open setup screen in step with the model list: menus gain the models when the list arrives, and the note
// "Model list unavailable, retrying…" shows only while no list has loaded yet.
function refreshSetupProviders(state) {
  app.providers = state.providers;
  const key = JSON.stringify(state.providers.map(p => p.id));
  if (key !== renderedProviderKey) {
    renderedProviderKey = key;
    document.querySelectorAll("#ttBuilder [data-setup-control]").forEach(select => refreshSetupControl(select, app.providers));
  }
  const note = document.querySelector("#ttBuilder .tt-providers-note");
  if (note) note.hidden = !state.unavailable;
}

// The fight's seats and whether a model is deciding right now. Cheap and read-only; it also wakes the server's
// runner for a model turn, so a model fighter keeps playing while this table is open.
async function loadSeats() {
  if (!app.matchId) return;
  const matchId = app.matchId, request = ++seatReadSequence;
  const isCurrent = () => app.matchId === matchId && request === seatReadSequence;
  try {
    const status = await api(`/api/tabletop/matches/${enc(matchId)}/seat-status`);
    if (isCurrent()) {
      app.seatStatus = status;
      if (status.paused || status.status === "ERROR") app.userPaused = true;
      else if (status.running) app.userPaused = false;
      // An idle read must not clear a local stop after an uncertain POST.
      // Only explicit Play, another confirmed run or a human turn resumes it.
      if (status.running) {
        app.playing = true;
        // A tab that discovers another tab's run must take over observing its end.
        scheduleSeatPoll();
      }
    }
  } catch {
    // A model seat is projected through the engine's MANUAL path. Without the
    // seat read, treating it as human would expose another controller's view.
    if (isCurrent()) app.seatStatus = null;
  }
  if (isCurrent() && app.state && reconcileViewerIdentity()) renderTokens();
}

function modelTurnNow() {
  const p = presentation();
  return Boolean(p && !p.terminal && (modelOwner(app.seatStatus, actorById(p.current_actor_id)) || app.seatStatus?.status === "DECIDING"));
}

// While the server advances a fight with a model seat, refresh on a short timer so its moves (and the built-in AI's
// turns between them) appear without anyone pressing a button. Human menus can be suspended by server reactions,
// so they keep observing too. Busy moments (loading, an action, an open prompt) skip a tick, and a failed
// refresh tries again on the next tick.
function scheduleSeatPoll() {
  clearTimeout(app.seatPoll);
  app.seatPoll = null;
  const p = presentation();
  if (!serverDriving(app.seatStatus, {terminal: Boolean(p?.terminal)})) return;
  app.seatPoll = setTimeout(async () => {
    try {
      if (!app.busy && !app.automaticRun) {
        await loadSeats();
        if (!app.seatStatus?.running) { app.playing = false; await refresh({observe: true}); }
      }
    } catch { /* the next tick tries again */ }
    finally { scheduleSeatPoll(); }
  }, 1500);
}

// A server-driven turn can stop on this player's own reaction (a model attacks your fighter, you chose Ask me). No
// click of this page owns that request, so open it here. Only an open dialog is de-duplicated: if answering fails,
// the next refresh shows the same outstanding prompt again for an explicit retry (nothing is resubmitted blindly).
// Model-owned prompts never reach the page.
function resumeServerPrompt(state) {
  const pending = state?.pending_action;
  if (!pending?.reaction || app.busy || !currentViewer().ready
      ) return;
  const key = JSON.stringify([pending.method, pending.request, pending.reaction.context]);
  if (app.promptInFlight === key) return;
  app.promptInFlight = key;
  app.viewerDeferredPrompt = false;
  Promise.resolve(resumePendingAction(pending)).catch(() => {}).finally(() => {
    if (app.promptInFlight === key) app.promptInFlight = null;
    scheduleSeatPoll();
  });
}

// The same Play/Pause buttons control both server-owned and browser-owned AI turns.
// Only update the server flag through the session-authorized write endpoint.
async function toggleAIPlayback() {
  if (app.playbackInFlight) return;
  if (!app.playing && !app.seatStatus?.running) {
    app.userPaused = false;
    return play();
  }
  app.playbackInFlight = true;
  const matchId = app.matchId;
  try {
    const status = await api(`/api/tabletop/matches/${enc(matchId)}/playback`, {body: {paused: true}});
    if (app.matchId !== matchId) return;
    app.seatStatus = status;
    app.userPaused = Boolean(status.paused);
    // The observer finishes at the committed Pause boundary.
    if (!app.automaticRun) { app.playing = false; await refresh(); }
  } catch (error) { toast(error.message, true); }
  finally { app.playbackInFlight = false; }
}

function openSeatPicker(actorId) {
  const dialog = $("#ttSeat");
  const actor = actorById(actorId);
  if (!dialog || !actor) return;
  dialog.querySelector("h2").textContent = `Who plays ${actor.display_name}?`;
  const seat = app.seatStatus?.seats?.[actorId];
  const current = seat?.provider_id;
  const providerById = id => (app.providers || []).find(p => p.id === id);
  $("#ttSeatProviders").innerHTML = pickerHtml(app.providers, current);
  // The style follows the picked model's suggestion; a saved override is kept only for that same model.
  const renderStyle = id => {
    $("#ttSeatStyle").innerHTML = styleHtml(providerById(id), id === current ? seat?.style : null);
  };
  renderStyle(dialog.querySelector("input[name=ttSeatProvider]:checked")?.value);
  $("#ttSeatProviders").onchange = event => {
    if (event.target?.name === "ttSeatProvider") renderStyle(event.target.value);
  };
  const apply = dialog.querySelector("[data-seat-apply]");
  apply.disabled = !app.providers.length;
  apply.onclick = async () => {
    const chosen = dialog.querySelector("input[name=ttSeatProvider]:checked")?.value;
    if (!chosen) return;
    const style = styleToSend(providerById(chosen), dialog.querySelector("input[name=ttSeatStyle]:checked")?.value);
    apply.disabled = true;
    try {
      await api(`/api/tabletop/matches/${enc(app.matchId)}/seat`, {body: {actor_id: actorId, control: "MODEL", provider_id: chosen, style}});
      dialog.close();
      toast(`${actor.display_name} is now played by ${providerLabel(app.providers, chosen)}.`);
      await loadSeats();
      await refresh();
    } catch (error) { toast(error.message, true); apply.disabled = false; }
  };
  if (!dialog.open) dialog.showModal();
}

async function openSeatLog() {
  const dialog = $("#ttSeatLog");
  if (!dialog || !app.matchId) return;
  $("#ttSeatLogBody").innerHTML = `<p class="tt-muted">Loading…</p>`;
  if (!dialog.open) dialog.showModal();
  try {
    const rows = (await api(`/api/tabletop/matches/${enc(app.matchId)}/seat-decisions?limit=30`)).decisions || [];
    const names = id => (presentation()?.actors || []).find(a => a.entity_id === id)?.display_name || "A fighter";
    $("#ttSeatLogBody").innerHTML = decisionsHtml(rows, names);
  } catch (error) { $("#ttSeatLogBody").innerHTML = `<p class="tt-muted">${escapeHtml(error.message)}</p>`; }
}

// A free choice changes the menu's selection, not its controls: draw the new bar detached and keep the live
// buttons (kept-bar.js) unless the controls differ. The bar then redraws in place; no state read is involved.
async function keepActionBar() {
  const bar = $("#ttActionBar");
  const probe = document.createElement("footer");
  probe.className = bar.className;
  await renderActionBar(probe);
  if (barSignature(bar) === barSignature(probe)) copySelection(bar, probe);
  else bar.replaceChildren(...probe.childNodes);
}

let menuLoadingTimer = null;
let menuLoadingActor = null;

// ------------------------------------------------------------------ ATTACKLIST1: the Attacks section, one card per weapon
// Owner-approved (feedback desk FD-18): the Attacks list used to be one button per weapon copy per mode. A Long
// Tongling carrying a Jian, a Xi Jian and four javelins filled about fifty buttons -- "Biao Qiang (Javelin) attack",
// "... thrown", "Batter: ... thrown", "Batter: ... thrown + Brutal Strike", "Batter: ...", each javelin one also
// saying "(one attack; choose the rest)" -- and no weapon could be picked out of them.
//
// Now one card per weapon: identical copies merge (x4), the weapon's modes and add-ons are chips under it showing only
// the numbers that differ from its plain attack, and an unavailable mode stays in the card, greyed, with the table's
// reason on hover. The reading is attack-groups.js, shared with the pop-out sheet, so both surfaces agree. Presentation
// only: each chip presses the exact button the server compiled.
//
// ctx = {makeButton, used, groups, actor, sheet, menu} from renderActionBar.
function attackWeaponCard(ctx, weapon) {
  const {makeButton, used, groups, actor, sheet, menu} = ctx;
  for (const row of weapon.rows) {
    const source = row.combat?.source_definition_id;
    if (source) used.add(source);
    if (groups.get(source)) used.add(groups.get(source).source_definition_id);  // the chosen augment combination it stands for
  }
  const spent = Number(app.attackSpent?.get(weapon.key) || 0);
  const usable = row => row.kind === "combo" ? true : groups.has(row.combat?.source_definition_id)
    || Boolean(app.optionDraft?.dirty && Object.values(app.menu?.composition || {})
      .some(choice => choice.family === row.combat?.source_definition_id));
  const hover = row => {
    const mod = row.variant_of ? row.modifier || {} : null;
    const extraRules = mod ? additionalRuleText(rulesTextFor(sheet, row), mod.description) : "";
    const reason = reasonFor(actor, row);
    const legal = usable(row) && !reason;
    return {legal, options: {rules: rulesTextFor(sheet, row), extra: [
      extraRules ? `${mod.name}: ${extraRules}${mod.precondition ? `\nOnly when: ${mod.precondition}` : ""}` : "",
      legal ? "" : reason].filter(Boolean)}};
  };
  const view = attackGroupView(weapon, {usable, spent});
  const plain = view.chips[0]?.row || weapon.rows[0];
  const card = document.createElement("div");
  card.className = "tt-action-card tt-attack-group";
  card.dataset.attackGroup = weapon.key;
  const head = document.createElement("div");
  head.className = "tt-attack-head";
  const name = document.createElement("b");
  name.textContent = view.name;
  const detail = plain.detail || {};
  const meta = document.createElement("small");
  meta.textContent = [
    view.copies > 1 ? (view.copiesUsed === view.copies ? `\u00d7${view.copies}` : `\u00d7${view.copiesUsed} of ${view.copies}`) : "",
    [detail.to_hit ? `${detail.to_hit.replace("-", "\u2212")} to hit` : "", detail.damage].filter(Boolean).join(" \u00b7 "),
    view.attacks <= 1 ? "" : !view.leftKnown ? "attacks left"
      : view.left >= view.attacks ? `${view.left} attacks left` : `${view.left} of ${view.attacks} attacks left`,
  ].filter(Boolean).join(" \u00b7 ");
  head.appendChild(name);
  head.appendChild(meta);
  head.dataset.tip = actionHoverText(plain, hover(plain).options);
  head.tipCard = actionTipCard(plain, hover(plain).options);
  card.appendChild(head);
  const chips = document.createElement("div");
  chips.className = "tt-attack-chips";
  for (const chip of view.chips) {
    const row = chip.row;
    if (!row) continue;
    const rowHover = hover(row);
    const button = makeButton(chip.label, chip.detail || "", {
      disabled: !rowHover.legal,
      cls: `tt-chip ${chip.kind === "addon" ? "is-variant" : ""} ${row.group === "attacks" ? "is-attack" : ""}`,
      title: actionHoverText(row, rowHover.options),
      tipCard: actionTipCard(row, rowHover.options),
      onClick: () => {
        // More than one attack in the Attack action: the first click asks once whether every attack lands on this one
        // or each is chosen as it comes (owner-approved). One attack, or an Action already spent: straight through.
        if (chip.ask) {
          const open = app.attackAsk && app.attackAsk.group === weapon.key && app.attackAsk.chip === chip.key;
          app.attackAsk = open ? null : {group: weapon.key, chip: chip.key, actor: menu.actor_id};
          renderActionBar();
          return;
        }
        noteAttackSent(weapon, chip.choice, view.attacks);
        runButton(row, menu.actor_id);
      },
    });
    // The option draft highlights and greys the button of every source it knows (OPTIONCOMPOSITION); a chip is that
    // button, so it carries the same two marks as a flat one.
    const source = row.combat?.source_definition_id;
    if (source) {
      button.dataset.compositionSource = source;
      button.dataset.baseLegal = String(groups.has(source));
    }
    if (chip.ask) button.dataset.askable = "1";
    markActive(button, app.state.button_states?.[menu.actor_id]?.[row.id]?.active);
    chips.appendChild(button);
  }
  const asked = app.attackAsk && app.attackAsk.group === weapon.key && app.attackAsk.actor === menu.actor_id
    ? view.chips.find(chip => chip.key === app.attackAsk.chip) : null;
  if (asked && asked.ask) chips.appendChild(attackAskPanel(ctx, view, asked));
  card.appendChild(chips);
  card.appendChild(actionRules([rulesTextFor(sheet, plain)].filter(Boolean).join("\n\n"), actionSummary(plain)));
  return card;
}

// How many attacks this bar has seen sent for one weapon since its Attack action was last free (a reload forgets).
// It counts only so the card can say "1 of 2 attacks left" instead of a bare "attacks left"; what is legal is still the
// table's menu. The pop-out sheet counts its own sends the same way.
function noteAttackSent(weapon, choice, attacks) {
  const row = choice && choice.row;
  if (!row) return;
  if (!(app.attackSpent instanceof Map)) app.attackSpent = new Map();
  if (row === choice.rest) {
    app.attackSpent.set(weapon.key, Math.min(attacks, Number(app.attackSpent.get(weapon.key) || 0) + 1));
  } else if (row === choice.begin) {
    app.attackSpent.set(weapon.key, Math.min(attacks, 1));
  } else {
    app.attackSpent.delete(weapon.key);
  }
}

// "Use all N attacks on this, or choose each?": both answers are real buttons the server compiled -- the whole Attack
// action spent on one target, or the "choose each" start (combat/ext/special_attacks.py compiles it only for a
// character with an Extra Attack, which is why it is the only way the question can come up).
function attackAskPanel(ctx, view, chip) {
  const {makeButton, menu} = ctx;
  const ask = chip.ask;
  const panel = document.createElement("div");
  panel.className = "tt-attack-ask";
  const question = document.createElement("p");
  question.textContent = `You have ${ask.attacks} attacks with ${view.name}. Use them all on this one, or choose each attack?`;
  const press = (label, detail, choice) => makeButton(label, detail, {
    onClick: () => {
      app.attackAsk = null;
      noteAttackSent({key: view.key}, choice, ask.attacks);
      runButton(choice.row, menu.actor_id);
    },
  });
  panel.appendChild(question);
  panel.appendChild(press(`All ${ask.attacks} on this`, "Every attack this turn lands on this one target",
    {row: ask.allRow, full: ask.allRow}));
  panel.appendChild(press("Choose each", "Start the Attack action and pick every attack as it comes",
    {row: ask.eachRow, begin: ask.eachRow}));
  panel.appendChild(makeButton("Cancel", "", {onClick: () => { app.attackAsk = null; renderActionBar(); }}));
  return panel;
}

async function renderActionBar(target = $("#ttActionBar")) {
  const bar = target;
  const p = presentation();
  if (p && !currentViewer().ready) { bar.textContent = "Choose My fighters to open your view."; return; }
  if (!p) { bar.innerHTML = `<div class="tt-ab-who"><strong>No fight open</strong><span class="tt-muted">Open or create a fight from Fights.</span></div>`; return; }
  if (p.terminal) {
    const result = p.terminal_result || {};
    bar.innerHTML = `<div class="tt-ab-who"><strong>Fight over</strong><span class="tt-muted"></span></div><div class="tt-ab-auto"><button class="tt-tool" type="button" data-summary>Fight summary</button><button class="tt-tool tt-primary" type="button" data-lobby>New fight</button></div>`;
    bar.querySelector("[data-summary]").addEventListener("click", openFightSummary);
    // Shown once when a fight ends (owner 2026-10-06); the button reopens it.
    if (summaryAutoOpen(app, p.match_id)) openFightSummary();
    bar.querySelector(".tt-muted").textContent = `${result.reason || ""} ${result.winning_team_id ? `Winner: ${(p.teams || []).find(team => team.runtime_team_ids?.includes(result.winning_team_id) || team.team_id === result.winning_team_id)?.display_name || "Winning team"}` : ""}`;
    bar.querySelector("[data-lobby]").addEventListener("click", openLobby);
    return;
  }
  const current = actorById(p.current_actor_id);
  const modelSeatOwner = modelOwner(app.seatStatus, current);
  const serverAI = serverDriving(app.seatStatus);
  const aiPlaying = serverAI ? !app.seatStatus.paused : app.playing;
  const waitingForOwnMenu = !app.menu && !!app.state?.menu_pending
    && isManualActor(current) && !automaticSlot(current);
  if (!waitingForOwnMenu) {
    if (menuLoadingTimer !== null) clearTimeout(menuLoadingTimer);
    menuLoadingTimer = null;
    menuLoadingActor = null;
  }
  if (modelSeatOwner) {
    const seat = app.seatStatus.seats[modelSeatOwner];
    bar.innerHTML = `<div class="tt-ab-who"><strong></strong><span class="tt-muted"></span></div>
      <div class="tt-ab-auto"><button class="tt-tool tt-primary" type="button" data-play>${aiPlaying ? "⏸ Pause" : "▶ Play AI turns"}</button><button class="tt-tool" type="button" data-seat-log>What it decided</button></div>`;
    bar.querySelector("strong").textContent = current?.display_name || "—";
    bar.querySelector(".tt-muted").textContent = app.seatStatus.paused ? "Paused"
      : app.seatStatus.status === "DECIDING"
      ? `is deciding… (played by ${providerLabel(app.providers, seat.provider_id)})`
      : `is played by ${providerLabel(app.providers, seat.provider_id)}`;
    bar.querySelector("[data-seat-log]").addEventListener("click", openSeatLog);
    bar.querySelector("[data-play]").addEventListener("click", toggleAIPlayback);
    return;
  }
  if (!app.menu && isManualActor(current) && !automaticSlot(current)) {
    bar.replaceChildren();
    const actorId = p.current_actor_id;
    if (waitingForOwnMenu) {
      if (menuLoadingActor !== actorId) {
        if (menuLoadingTimer !== null) clearTimeout(menuLoadingTimer);
        menuLoadingActor = actorId;
        menuLoadingTimer = setTimeout(() => {
          menuLoadingTimer = null;
          if (app.state?.menu_pending && !app.menu && presentation()?.current_actor_id === actorId
              && isManualActor(actorById(actorId)) && !automaticSlot(actorById(actorId))) renderActionBar();
        }, 400);
      } else if (menuLoadingTimer === null) {
        bar.innerHTML = `<div class="tt-ab-who"><strong></strong><span class="tt-muted">Loading your choices…</span></div>`;
        bar.querySelector("strong").textContent = current?.display_name || "—";
      }
    }
    return;
  }
  if (!app.menu) {
    bar.innerHTML = `
      <div class="tt-ab-who"><strong></strong><span class="tt-muted">is acting (AI, following their Dao)</span></div>
      <div class="tt-ab-auto">
        <button class="tt-tool" type="button" data-step title="Run automatic turns until a player must choose (S)">Run turn</button>
        <button class="tt-tool tt-primary" type="button" data-play>${aiPlaying ? "⏸ Pause" : "▶ Play AI turns"}</button>
        <label class="tt-select-label">Speed <input type="range" min="0" max="1.5" step="0.1" data-speed title="Movement playback speed; AI decisions do not wait for animation"></label>
        <button class="tt-tool" type="button" data-take title="Play this fighter yourself from now on">Take control</button>
      </div>`;
    bar.querySelector("strong").textContent = current?.display_name || "—";
    bar.querySelector("[data-step]").disabled = aiPlaying || serverAI;
    bar.querySelector("[data-step]").addEventListener("click", () => autoStep());
    bar.querySelector("[data-play]").addEventListener("click", toggleAIPlayback);
    if (serverAI && app.seatStatus.paused) bar.querySelector(".tt-muted").textContent = "Paused";
    const speed = bar.querySelector("[data-speed]");
    speed.value = String(1.5 - app.speed);
    speed.addEventListener("input", () => { app.speed = 1.5 - Number(speed.value); });
    bar.querySelector("[data-take]").addEventListener("click", () => setControl(p.current_actor_id, "MANUAL"));
    if (automaticSlot(current)) {
      bar.querySelector(".tt-muted").textContent = "is down; this turn passes automatically";
      bar.querySelector("[data-step]").title = "Advance this turn (S)";
      bar.querySelector("[data-play]").textContent = aiPlaying ? "⏸ Pause" : "▶ Advance turns";
      if (serverAI && app.seatStatus.paused) bar.querySelector(".tt-muted").textContent = "Paused";
      bar.querySelector("[data-take]").disabled = true;
    }
    return;
  }
  // A fighter you play: buttons from the character sheet, legal ones enabled.
  if (["DYING", "STABLE"].includes(current?.life_state)) {
    bar.innerHTML = `<div class="tt-ab-who"><strong></strong><span class="tt-muted"></span></div><button class="tt-tool is-end" type="button" data-end>End turn</button>`;
    bar.querySelector("strong").textContent = current.display_name;
    bar.querySelector(".tt-muted").textContent = current.life_state === "STABLE"
      ? "Unconscious and Stable: no actions, reactions, or movement; no death saving throws unless damaged."
      : "Unconscious and dying: no actions, reactions, or movement. The death saving throw is rolled at the start of this turn.";
    bar.querySelector("[data-end]").disabled = app.busy || Boolean(app.state?.pending_action);
    bar.querySelector("[data-end]").addEventListener("click", () => actOnce(app.menu.end_turn));
    return;
  }
  const menu = app.menu;
  const actor = actorById(menu.actor_id);
  const sheet = await sheetFor(menu.actor_id);
  if (app.menu !== menu || !currentViewer().ready) return;  // state or local view changed while the sheet loaded
  const groups = new Map(menu.actions.map(group => [group.source_definition_id, group]));
  // An ability with chosen augments casts that combination (combat/loadout.py): its button stands for it.
  for (const group of menu.actions) if (group.alias_of && !groups.has(group.alias_of)) groups.set(group.alias_of, group);
  const used = new Set();
  const hidden = new Set(sheet?.layout?.hidden || []);
  const sections = [
    ["Attacks", ["attacks"]], ["Actions", ["actions"]], ["Bonus actions", ["bonus"]],
    ["Reactions", ["reactions"]], ["Free", ["free"]], ["No action", ["no_action"]], ["Movement", ["movement"]],
    ["Basic", ["basic"]], ["Combos", ["custom"]],
    // A feature's standing choice ("Flowing Response: Empty Step"): free, kept until changed (owner 2026-09-30).
    ["Choices (free, kept until changed)", ["choice"]],
  ];
  const html = document.createElement("div");
  html.className = "tt-ab-groups";
  const makeButton = (label, detail, {disabled = false, title = "", cls = "", onClick, tipCard = null}) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tt-btn ${cls}`;
    button.innerHTML = "<b></b><small></small>";
    button.querySelector("b").textContent = label;
    button.querySelector("small").textContent = detail;
    button.disabled = disabled;
    // The shared hover card, not a native tooltip: the owner can read it, scroll it and copy it (owner 2026-10-03).
    button.dataset.tip = title || label;
    if (tipCard) button.tipCard = tipCard;  // the compact ability card (rules.js actionTipCard)
    bindPress(button, onClick);
    return button;
  };
  const moveGroup = document.createElement("div");
  moveGroup.className = "tt-ab-group";
  moveGroup.innerHTML = `<h3>Move</h3><div class="tt-ab-buttons"></div>`;
  moveGroup.lastChild.appendChild(makeButton(app.showMoves ? "Hide moves" : "Show moves", `${movementLeft(actor)} left · click a blue square`, {
    cls: app.showMoves ? "is-active" : "", disabled: !menu.moves.length,
    title: menu.movement_preview || "Blue squares are where you can move; click one or drag your token.",
    onClick: () => { app.showMoves = !app.showMoves; renderHighlights(); renderActionBar(); },
  }));
  html.appendChild(moveGroup);
  const level = moveHeight();
  const canJumpDown = menu.moves.some(row => row.can_jump_down);
  const moveButtons = moveGroup.querySelector(".tt-ab-buttons");
  if (actor.on_roof || canJumpDown) {
    moveButtons.appendChild(movementControl(actor.fly_speed_ft > 0, app.moveMode || 'native', canJumpDown, mode => {
      app.moveMode = mode;
      if (mode === 'jump_down') app.moveHeight = actor.position.z || 0;
      app.showMoves = true;
      renderHighlights();
      renderActionBar();
    }));
  }
  const roofLevels = roofLevelsAt(board.map, actor);
  // Movement notes go in the hover card of the control they explain (appendTip), never a visible paragraph.
  if (app.moveMode === 'jump_down') {
    appendTip(moveButtons.lastElementChild, `Jump down from ${heightFeet(actor)} ft. Choose a blue square at the roof edge or an open roof opening. Walk there, then fall to the first support below. Falling can cause damage and knock you prone.`);
  } else if (actor.fly_speed_ft || actor.position?.z || roofLevels.length || menu.moves.some(row => row.destination.z)) {
    const control = heightControl(menu.moves, level, actor.fly_speed_ft > 0, z => {
      app.moveHeight = z;
      renderHighlights();
      renderActionBar();
    }, actor, roofLevels);
    moveButtons.appendChild(control);
    if (roofLevels.length) appendTip(control, 'A solid roof blocks passage; use an open trapdoor or skylight to pass through it.');
    const vertical = selectedMoves().find(row => row.destination.x === actor.position.x && row.destination.y === actor.position.y);
    if (vertical && level !== (actor.position.z || 0)) {
      const verb = movementVerb(vertical);
      moveButtons.appendChild(makeButton(`${verb}${verb === 'Jump down' ? '' : level > (actor.position.z || 0) ? ' up' : ' down'} here to ${level * 5} ft`, routeText(vertical), {
        title: `${verb}${verb === 'Jump down' ? '' : level > (actor.position.z || 0) ? ' up' : ' down'} in your current square to ${level * 5} ft above the battlefield floor. ${routeText(vertical)}`,
        onClick: () => moveTo(vertical),
      }));
    }
  }
  if (menu.movement_explanation?.summary) {
    const hint = document.createElement("small");
    hint.textContent = "Rest your pointer on your token or a square to see movement limits.";
    moveGroup.appendChild(hint);
  }
  // An ability's option pickers (Blossom: Medicinal Blossom, Seed damage: Piercing) sit indented under the ability they
  // belong to, and each button is drawn once: a picker already under its ability is not repeated in Choices.
  // A picker of an ability (Blossom: Medicinal Blossom; Seed damage: Piercing) is listed in that ability's Options panel, as
  // Darkness's talents are, so it is not a bar button.
  // A hidden ability still casts from the bar when it has a VISIBLE picker/talent/augment under it
  // (`parent`): those choices live only in its Options panel, so hiding the ability itself would strand
  // them there with no "Cultivate Blossom"-style button left to cast it (owner 2026-10-13). A child that is
  // itself hidden names no requirement: hiding the whole family keeps the whole family off the bar (review
  // r1, finding 1).
  const neededAsParent = new Set((sheet?.buttons || []).filter(row => row.parent && !hidden.has(row.id)).map(row => row.parent));
  const sheetButtons = (sheet?.buttons || []).filter(row => (!hidden.has(row.id) || neededAsParent.has(row.combat?.source_definition_id))
    && (row.kind === "combat" || row.kind === "combo") && !row.combat?.end_turn
    && !row.shape && !row.augment && !row.attack_modifier && !row.parent);  // the Options button
  const inSection = (row, groupNames) => (groupNames[0] === "choice" ? (row.tags || []).includes("choice")
    : groupNames.includes(row.group) && !(row.tags || []).includes("choice"));
  const drawButton = row => {
    const source = row.combat?.source_definition_id;
    const legal = row.kind === "combo" ? true : groups.has(source) || Boolean(app.optionDraft?.dirty
      && Object.values(app.menu?.composition || {}).some(choice => choice.family === source));
    if (source) used.add(source);
    if (groups.get(source)) used.add(groups.get(source).source_definition_id);  // the chosen augment combination it stands for
    const mod = row.variant_of ? row.modifier || {} : null;  // "Water Lash + Water Whip" reads "+ Water Whip" under Water Lash
    const extraRules = mod ? additionalRuleText(rulesTextFor(sheet, row), mod.description) : "";
    const button = makeButton(mod ? `+ ${mod.name}` : row.label, row.kind === "combo" ? `${row.steps.length} steps` : buttonDetail(row), {
      disabled: !legal, cls: `${row.group === "attacks" ? "is-attack" : ""} ${row.economy === "BONUS_ACTION" ? "is-bonus" : ""} ${row.kind === "combo" ? "is-combo" : ""} ${mod ? "is-variant" : ""}`,
      title: actionHoverText(row, {rules: rulesTextFor(sheet, row), extra: [
        extraRules ? `${mod.name}: ${extraRules}${mod.precondition ? `\nOnly when: ${mod.precondition}` : ""}` : "",
        legal ? "" : reasonFor(actor, row)]}),
      tipCard: actionTipCard(row, {rules: rulesTextFor(sheet, row), extra: [
        extraRules ? `${mod.name}: ${extraRules}${mod.precondition ? ` Only when: ${mod.precondition}` : ""}` : "",
        legal ? "" : reasonFor(actor, row)].filter(Boolean)}),
      onClick: () => runButton(row, menu.actor_id),
    });
    if (source) {
      button.dataset.compositionSource = source;
      button.dataset.baseLegal = String(groups.has(source));
    }
    markActive(button, app.state.button_states?.[menu.actor_id]?.[row.id]?.active);
    const card = document.createElement("div");
    card.className = "tt-action-card";
    card.appendChild(button);
    card.appendChild(actionRules([rulesTextFor(sheet, row), extraRules].filter(Boolean).join("\n\n"), actionSummary(row)));
    return card;
  };
  for (const [title, groupNames] of sections) {
    const buttons = sheetButtons.filter(row => inSection(row, groupNames));
    if (!buttons.length) continue;
    const group = document.createElement("div");
    group.className = "tt-ab-group";
    group.innerHTML = `<h3></h3><div class="tt-ab-buttons"></div>`;
    group.querySelector("h3").textContent = title;
    if (groupNames[0] === "attacks") {
      // One card per weapon (owner-approved ATTACKLIST1): the copies of one weapon are one card, not one button each.
      const ctx = {makeButton, used, groups, actor, sheet, menu};
      for (const weapon of groupAttackRows(buttons)) group.lastChild.appendChild(attackWeaponCard(ctx, weapon));
    } else {
      for (const row of buttons) group.lastChild.appendChild(drawButton(row));
    }
    html.appendChild(group);
  }
  // A picker drawn under its ability is in `used` already; one whose ability was not drawn stays here.
  const extra = menu.actions.filter(group => !used.has(group.source_definition_id) && !group.item && !group.shape);
  // An ability's choices (owner 2026-09-27): the talent its next area carries (Numbing Darkness; Pure Darkness with Pitch
  // Black) and the augments its next use carries (any number, each paid) -- one button per ability, opening the Options
  // panel. Choosing is free and stays until changed.
  const optionRows = draftOptionRows(menu.actor_id);
  if (optionRows.length) {
    const group = document.createElement("div");
    group.className = "tt-ab-group";
    group.innerHTML = `<h3>Options</h3><div class="tt-ab-buttons"></div>`;
    for (const entry of optionRows) {
      const now = [entry.augments_label, entry.current].filter(Boolean).join(" · ") || `plain ${entry.name}`;
      group.lastChild.appendChild(makeButton(entry.name, now, {
        cls: app.showShape === entry.base ? "is-active" : "",
        title: `Your next ${entry.name}: ${now}. Click to prepare different options; they are saved when you use the ability.`,
        onClick: () => { app.showShape = app.showShape === entry.base ? null : entry.base; app.showItems = false; renderItemsPanel(); renderShapePanel(); renderActionBar(); },
      }));
      group.lastChild.lastChild.dataset.optionFamily = entry.base;
    }
    html.insertBefore(group, moveGroup.nextSibling);
    for (const [index, entry] of optionRows.entries()) {
      markActive(group.lastChild.children[index], app.state.button_states?.[menu.actor_id]?.[`act:${entry.base}`]?.active);
    }
  }
  // Items (owner 2026-09-27: "we should have a tab for items and equipment. Dropping things should also be an option"):
  // one button with the load, opening the Items panel (Drop is free; Pick up within 5 ft).
  const load = (app.state.carrying || {})[menu.actor_id];
  if (load) {
    const group = document.createElement("div");
    group.className = "tt-ab-group";
    group.innerHTML = `<h3>Items</h3><div class="tt-ab-buttons"></div>`;
    group.lastChild.appendChild(makeButton("Items", `${load.weight_lb} / ${load.capacity_lb} lb${load.over ? " · over" : ""}`, {
      cls: `${app.showItems ? "is-active" : ""} ${load.over ? "is-over" : ""}`,
      title: load.over ? `Over capacity: Speed is at most 5 ft (from the start of your next turn). Drop something to lighten the load.`
                       : "What you carry: drop things (free) or pick them back up.",
      onClick: () => { app.showItems = !app.showItems; app.showShape = null; renderShapePanel(); renderItemsPanel(); renderActionBar(); },
    }));
    html.insertBefore(group, moveGroup.nextSibling);  // beside Move: always in view
  }
  for (const [slot, rows] of economySections(extra)) {
    const group = document.createElement("div");
    group.className = "tt-ab-group";
    group.innerHTML = `<h3>${slot}</h3><div class="tt-ab-buttons"></div>`;
    for (const row of rows) {
      group.lastChild.appendChild(makeButton(row.label, `${costTag(row)}${row.options.length > 1 ? ` · ${row.options.length} choices` : ""}`, {
        title: layoutText(row.hover) || cleanRules(row.description) || row.label,
        tipCard: actionTipCard(row, {rules: layoutText(row.hover) || cleanRules(row.description) || ""}),
        onClick: () => useGroup(row),
      }));
      const card = document.createElement("div");
      card.className = "tt-action-card";
      card.appendChild(group.lastChild.lastChild);
      card.appendChild(actionRules(layoutText(row.hover) || row.description, row.label));
      group.lastChild.appendChild(card);
    }
    html.appendChild(group);
  }
  bar.replaceChildren();
  const who = document.createElement("div");
  who.className = "tt-ab-who";
  who.innerHTML = `<strong></strong><span class="tt-muted">Your turn</span><span class="tt-pills"></span>`;
  if (serverAI && app.seatStatus.paused) who.querySelector(".tt-muted").textContent = "Your turn · AI turns Paused";
  who.querySelector("strong").textContent = actor.display_name;
  const turn = actor.turn_state || {};
  who.querySelector(".tt-pills").innerHTML = `${economyPills(turn)}<span class="tt-pill">${movementLeft(actor)}</span>`;
  bar.appendChild(who);
  // Ranked top-5 slots replace the bar only in Assisted turns; Manual keeps the full normal controls
  // (Show moves, height picker, board clicks) — owner 2026-10-13.
  const match = app.matchId;
  const inspectionKey = menuInspectionKey(app.state);
  // Compact polls rebuild menu objects even at the same decision. Read-only
  // replies may cross that refresh, but never a changed authority boundary.
  const inspectionCurrent = () => app.matchId === match && app.menu && inspectionKey !== null
    && app.menu === app.state?.menu && menuInspectionKey(app.state) === inspectionKey
    && !app.busy && !refuseCoveredView();
  const loadInspection = (path, options) => api(`/api/tabletop/matches/${enc(match)}${path}`, options);
  appendActionBarRankedChoice(bar, menu, {doc: document, html, who,
    onAct: id => actOnce(id), onMove: move => moveTo(move),
    onSource: async group => {
      const expanded = await expandSource(menu, group, loadInspection, inspectionCurrent);
      if (!expanded || !inspectionCurrent()) return null;
      const row = app.menu.actions.find(g => g.source_definition_id === group.source_definition_id);
      if (!row) return null;
      if (row !== expanded) {
        Object.assign(row, expanded);
        renderActionBar();
      }
      return row;
    },
    onPreviewMove: async move => {
      const checked = await checkMove(menu, move, loadInspection, inspectionCurrent);
      if (!checked || !inspectionCurrent()) return null;
      const row = app.menu.moves.find(m => m.deferred_route && moveKey(m) === moveKey(move));
      if (!row) return null;
      if (row !== checked) {
        // Preserve the fresh local handle and effective price after reordering.
        copyMoveInspection(row, checked);
        renderActionBar();
      }
      return row;
    }});
  if (menu.end_turn) {
    bar.appendChild(makeButton("End turn", "Space", {cls: "is-end", onClick: () => actOnce(menu.end_turn)}));
  }
}

// ------------------------------------------------------------------ highlights, targeting and movement
function moveHeight() {
  const menu = app.menu;
  if (app.moveHeightDecision !== menu?.decision_id) {
    app.moveHeightDecision = menu?.decision_id;
    app.moveHeight = startHeightLevel(actorById(menu?.actor_id));
    app.moveMode = 'native';
  }
  return app.moveHeight || 0;
}

function selectedMoves() {
  const moves = movesAtHeight(app.menu?.moves || [], moveHeight());
  // Retain each native destination and its exact offered path. The deliberate
  // drop is quoted separately on click; it is not a second native candidate.
  return app.moveMode === 'jump_down'
    ? moves.filter(row => row.can_jump_down).map(row => ({...row, movement_mode: 'jump_down'})) : moves;
}

function renderHighlights() {
  const highlights = {};
  const menu = app.menu;
  if (app.targeting) {
    const targeting = app.targeting;
    highlights.areas = targeting.areas.map(option => option.area.center);
    highlights.moves = targeting.destinations.map(option => option.destination);
    const hovered = app.hoverCell && targeting.areas.find(option => option.area.center.x === app.hoverCell.x && option.area.center.y === app.hoverCell.y);
    if (hovered) highlights.areaCells = hovered.area.affected_cells || [];
    highlights.targets = [...targeting.byTarget.keys()].map(id => {
      const target = actorById(id);
      if (target) return {...target.position, ...tokenGeometry(target)};
      const object = objectById(id);
      return object ? {x: object.x, y: object.y} : null;
    }).filter(Boolean);
    const actor = actorById(targeting.actorId);
    if (app.hoverTarget && actor) {
      const target = actorById(app.hoverTarget);
      const object = objectById(app.hoverTarget);
      const position = target?.position || (object && {x: object.x, y: object.y});
      // Only issued legal targets reach this preview. The engine checks height,
      // sight, effect paths and remembered-square policy; a 2D ray cannot override it.
      if (position) highlights.line = {from: actor.position, to: position, blocked: false};
    }
  } else if (app.mapPick) {
    highlights.moves = app.mapPick.cells;  // the squares the player may click to answer a place choice
    highlights.targets = app.mapPick.prompt.choice.options.filter(option => option.target_id).map(option => option.cell);
    // Restore native hover shading for deferred areas. Each legal altitude has
    // its own footprint captured at the pause; no client geometry or eager menu.
    const heights = app.hoverCell && app.mapPick.altitudes?.get(`${app.hoverCell.x},${app.hoverCell.y}`);
    const hovered = heights && (heights.find(option => (option.cell.z || 0) === moveHeight()) || heights[0]);
    highlights.areaCells = (hovered && app.mapPick.prompt.choice.map_pick?.areas?.[hovered.id])
      || (app.hoverCell && app.mapPick.options.has(`${app.hoverCell.x},${app.hoverCell.y}`) ? [app.hoverCell] : []);
    if (app.mapPick.selected?.size) highlights.areaCells = [...highlights.areaCells,
      ...app.mapPick.prompt.choice.options.filter(option => option.cell && app.mapPick.selected.has(option.id)).map(option => option.cell)];
  } else if (app.pendingMove) {
    highlights.pending = app.pendingMove;  // the move just clicked, while the fight works it out
  } else if (menu && app.showMoves) {
    highlights.moves = selectedMoves().map(move => move.destination);
    const hovered = app.hoverCell && selectedMoves().find(move => move.destination.x === app.hoverCell.x && move.destination.y === app.hoverCell.y);
    if (hovered) highlights.path = hovered.path;
  }
  board.setHighlights(highlights);
  board.setMovementExplanation(app.targeting ? null : heightMovement(app.state?.menu?.movement_explanation,
    selectedMoves(), moveHeight()));
  renderTokens();
}

// skip ({label, onClick}) is an optional rider's own answer (Pass / Stay here). It sits after Cancel and never replaces it.
function hint(text, onCancel = () => cancelAbilityChoice(), label = "Cancel (Esc)", skip = null) {
  const node = $("#ttHint");
  if (!text) { node.hidden = true; node.replaceChildren(); return; }
  node.hidden = false;
  node.innerHTML = `<span></span>${onCancel ? `<button type="button">${escapeHtml(label)}</button>` : ""}`
    + (skip ? `<button type="button">${escapeHtml(skip.label)}</button>` : "");
  node.firstChild.textContent = text;
  if (onCancel) (skip ? node.children[1] : node.lastChild).addEventListener("click", () => onCancel());
  if (skip) node.lastChild.addEventListener("click", () => skip.onClick());
}

// Close the table's open choice and tell every window. Every way a choice ends -- answered, cancelled,
// replaced, or thrown away with the fight -- comes through here, so no window is ever left telling the
// player to press Cancel for a placement that is already gone (owner playtest 2026-10-03 23:01).
function closeChoice() {
  if (!app.pendingChoice) return;
  app.pendingChoice = null;
  broadcastActors();  // the choice is closed; the pop-out sheet should stop saying it is waiting
}

// A refresh can replace the decision while the player is aiming. Never keep candidates from an
// older decision, another actor's turn, or a fight that ended. Re-reading the same legal decision
// preserves the player's choice; invalidation settles it and broadcasts its removal.
function invalidateTargeting() {
  const targeting = app.targeting;
  // An empty local picker cannot be answered. Retire it (and any orphaned
  // local notice) on the next poll; never discard a saved server question.
  const empty = targeting && !targeting.byTarget?.size && !targeting.areas?.length && !targeting.destinations?.length;
  const orphan = !targeting && !app.listPick && !app.mapPick && !app.state?.pending_action
    && ["target", "placement", "list"].includes(app.pendingChoice?.kind);
  if (empty || orphan) {
    cancelTargeting();
    toast("That choice has no legal targets or options. Choose an action again.", true);
    return;
  }
  if (!targeting) return;
  const menu = app.menu;
  const legal = new Set((menu?.actions || []).flatMap(group => group.options.map(option => option.candidate_id)));
  if (app.state?.presentation?.terminal || app.state?.pending_action || !menu
      || menu.actor_id !== targeting.actorId || menu.decision_id !== targeting.decisionId
      || app.state?.presentation?.current_actor_id !== targeting.actorId
      || menu.state_version !== targeting.stateVersion
      || targeting.group.options.some(option => !legal.has(option.candidate_id))) cancelTargeting();
}

function cancelTargeting(result = false) {
  app.lazyChoiceSerial = (app.lazyChoiceSerial || 0) + 1;
  app.listPick?.cancel();
  const targeting = app.targeting;
  app.targeting = null;
  app.hoverTarget = null;
  hint(null);
  renderHighlights();
  closeChoice();
  targeting?.resolve(result);
}

// Esc, Cancel and right-click. Until the chosen action is sent, cancelling abandons the attempt; nothing has been
// reserved, so the table is left as it was. Once the action is sent, or for a prompt the table already saved, the
// table holds it: Cancel cannot undo it. Only an optional rider can still be passed (its own Pass / Stay here
// button); a required choice keeps waiting for its answer. Tokens survive awaits so a late response cannot reopen a picker.
function abilityChoiceActive() {
  return Boolean(app.abilityChoice || app.targeting || app.mapPick || app.listPick
    || app.waitingReaction || app.showShape || app.state?.menu_pending);
}

// True once the table holds the action or a saved prompt, so Cancel can no longer abandon it.
function abilityReserved() {
  return Boolean(app.abilityChoice?.submitted || app.waitingReaction?.reserved);
}

// A square the server saved with a cancel_action (Cultivate Blossom placement) is undone on the server first,
// so the attempt is discarded there as well as on the table. Other square choices close locally.
function releaseMapPick() {
  const pick = app.mapPick;
  if (!pick) return;
  if (pick.prompt?.cancel_action) {
    if (pick.cancelling) return;
    pick.cancelling = true;
    api(`/api/tabletop/matches/${enc(app.matchId)}/placement/cancel`, {body: pick.prompt.cancel_action})
      .then(result => pick.close({cancelled: true, ...result}))
      .catch(error => { pick.cancelling = false; toast(error.message, true); });
    return;
  }
  pick.close({cancelled: true});
}

function cancelAbilityChoice() {
  // A covered table still receives key presses and the last menu on screen. Escape, right-click
  // and the Cancel button are player input, so while the view is covered they answer nothing:
  // a saved prompt stays open and the hidden choice is not discarded (the guard cancelMapPick
  // used to apply, before this path shared cancelAbilityChoice).
  if (!currentViewer().ready) return;
  // A saved prompt is already a table decision. Escape may answer an optional
  // reaction as Pass, but must not dismiss a required prompt locally.
  if (app.waitingReaction?.reserved) {
    app.declineReaction?.();
    return;
  }
  if (app.abilityChoice?.submitted) return;
  if (app.abilityChoice) {
    app.abilityChoice.cancelled = true;
    app.abilityChoice.stop?.();
    if (app.abilityChoice.working) {
      app.busy = false;
      document.body.classList.remove("is-working");
    }
  }
  if (typeof deferredMenuRead !== "undefined") deferredMenuRead?.stop();
  app.finishReaction?.({cancelled: true});
  releaseMapPick();
  app.closeReactionMenu?.();
  for (const [id, move] of app.movePositions || []) if (move.pause) app.movePositions.delete(id);
  cancelTargeting();
  app.showShape = null;
  renderShapePanel();
  renderActionBar();
}

// The table's one open choice in plain words, for a refusal and for the pop-out sheet. A player who
// is told only "it is not your turn" cannot tell a finished turn from an open prompt. "prompt" says
// what the player is being asked to pick, because it is a creature for some abilities and a square
// for others (item 13: describe the choice, not the mechanism).
function pendingChoiceText() {
  const choice = app.pendingChoice;
  if (choice?.kind === "map") {
    const pick = abilityReserved() ? "" : ", or press Cancel (Esc)";
    const skip = app.mapPick?.allow_decline ? ", or use its skip button" : "";
    return `The table is waiting for you to choose a square for ${choice.label}. Click a highlighted square on the table${pick || skip}.`;
  }
  if (choice?.prompt) return `The table is waiting for you to choose ${choice.prompt}. Press Cancel (Esc) on the table, then press the action again.`;
  if (choice || app.state?.pending_action) return "The table is waiting for an answer to a question it asked. Answer it on the table first.";
  return "";
}

// A choice whose options are places is answered by clicking a square on the main map, never from a list
// (owner 2026-10-03, round 24: "For any teleportation you can just click on an available square on the grid
// rather than a tooltip"). This is the point-placement picker Darkness and the area placements already use:
// the legal squares light up, the click answers, Esc (or Cancel) keeps you where you are. The engine still owns
// the squares and the answer binding -- choice.map_pick only says how to ask.
// The squares a place choice can be answered on: the engine's own list, and only those that still match an option.
function mapPickCells(choice) {
  const spatial = (choice.options || []).filter(option => option.cell);
  const options = new Map(spatial.map(option => [`${option.cell.x},${option.cell.y}`, option]));
  const altitudes = new Map();
  for (const option of spatial) {
    const key = `${option.cell.x},${option.cell.y}`;
    if (!altitudes.has(key)) altitudes.set(key, []);
    altitudes.get(key).push(option);
  }
  // Offered option IDs are the answer authority. Display metadata must never
  // hide an offered square (including on an older stored prompt).
  const squares = spatial.map(option => option.cell);
  return {options, altitudes, cells: (squares || []).filter(cell => options.has(`${cell.x},${cell.y}`))};
}

// A place choice is always raised from inside a request the fight is still working out (act()/autoStep() hold
// body.is-working for the whole call), and that state switches the map and the hint off to clicks in
// tabletop.css. Arming the picker therefore has to say so on the body as well, or the squares it lit up and the
// way out of it cannot be clicked while the only moment they matter is on screen. It is a presentation state only:
// app.busy still refuses a second action, so nothing else about the working turn changes.
const MAP_PICK_BODY_CLASS = "is-map-pick";

function setMapPick(pick) {
  // The engine replays an uncommitted request after this answer. Keep its pause
  // snapshot visible until that replay commits, rather than redrawing the origin
  // as soon as the picker closes. This is display-only, never fight state.
  if (pick?.positions?.size) {
    app.movePositions ||= new Map();
    for (const [id, position] of pick.positions) {
      app.movePositions.set(id, {position, sequence: Infinity, pause: true,
        cursor: pick.cursors?.get(id)});
    }
  }
  app.mapPick = pick;
  document.body.classList.toggle(MAP_PICK_BODY_CLASS, Boolean(pick));
}

// What the prompt has to say before it asks for a square: whose choice this is,
// what set it off, and what the ability does and costs. The choice dialog showed all of that through
// decisionText(); a prompt that only said "click a square" left the player answering for the wrong creature, which
// a reaction teleport asks during someone else's turn.
function mapPickContext(prompt) {
  // The per-ability square line (choice.map_pick.prompt) leads, and the
  // chooser/trigger/summary/cost text assembled below stays beside it: the concise
  // line alone left the player clicking without knowing whose square it is, what the
  // choice does or what it spends. A marked prompt
  // that carries no line, and every unmarked one, show only the context, as before.
  const who = cleanRules(prompt.reactor || "");
  const doing = cleanRules(prompt.reaction || prompt.title || "Choose a space");
  const when = cleanRules(prompt.trigger || prompt.moment || "");
  const why = cleanRules(prompt.summary || "");
  const cost = cleanRules(prompt.cost || "");
  const parts = [who && `${who}:`, doing, when && `(${when})`, why, cost && `Cost now: ${cost}`].filter(Boolean).join(" ");
  const pick = cleanRules(prompt.choice?.map_pick?.prompt || "");
  return [pick, parts].filter(Boolean).join("\n");
}

function mapPickChoice(prompt) {
  const choice = prompt.choice, pick = choice.map_pick || {}, {options, altitudes, cells} = mapPickCells(choice);
  const reserved = abilityReserved();
  const how = "Click a highlighted square on the map to choose it. "
    + (reserved ? "" : "Press Esc to cancel the ability.");
  return new Promise(resolve => {
    let settled = false;
    const declineHere = () => close("DECLINE");
    const close = answer => {
      if (settled) return;
      settled = true;
      if (app.declineReaction === declineHere) app.declineReaction = null;
     setMapPick(null);
      closeChoice();
      hint(null);
      renderHighlights();
      resolve(answer);
    };
    const snapshot = choice.space_map;
    const positions = new Map((snapshot?.tokens || []).map(token => [token.id, token.position]));
    if (snapshot?.chooser_id && snapshot.origin) positions.set(snapshot.chooser_id, snapshot.origin);
    const cursors = new Map((snapshot?.tokens || []).filter(token => token.movement_cursor)
      .map(token => [token.id, token.movement_cursor]));
    setMapPick({cells, options, altitudes, prompt, positions, cursors, close,
      selected: new Set(), allow_decline: Boolean(choice.allow_decline)});
    app.mapPick.choose = id => {
      if (app.mapPick?.close !== close || app.mapPick.cancelling || !currentViewer().ready) return;
      if (choice.maximum <= 1) return close({selection: 'USE', option_ids: [id]});
      const selected = app.mapPick.selected;
      if (selected.has(id)) selected.delete(id);
      else if (selected.size < choice.maximum) selected.add(id);
      else { toast(`Choose at most ${choice.maximum}. Unselect one first.`, true); return; }
      app.mapPick.update(); renderHighlights();
    };
    app.pendingChoice = {kind: "map", label: cleanRules(prompt.reaction || prompt.title || "Choose a space"),
      actor_id: snapshot?.chooser_id || prompt.context?.reactor_id || ""};
    broadcastActors();
    const skip = choice.allow_decline ? {label: pick.cancel_label || 'Skip this choice',
      // A covered table still shows the last hint. Its skip button is player input, so it answers
      // nothing until the view is available again (remote cleanup still calls close directly).
      onClick: () => { if (currentViewer().ready) close('DECLINE'); }} : null;
    app.declineReaction = skip ? declineHere : null;
    const text = (mapPickContext(prompt) + '\n' + how + ' ' + cleanRules(pick.instruction || '')).trim();
    // Shown again after each selection: the hint names the count and lists the choices that are not squares.
    const update = () => {
      const count = choice.maximum > 1
        ? ' Choose ' + choice.minimum + '\u2013' + choice.maximum + '; ' + app.mapPick.selected.size + ' selected. Click again to unselect.'
        : '';
      hint(text + count, reserved ? null : cancelAbilityChoice, 'Cancel ability (Esc)', skip);
      for (const option of choice.options.filter(option => !option.cell)) {
        const button = document.createElement('button');
        button.type = 'button'; button.textContent = option.label || 'Use';
        button.addEventListener('click', () => {
          if (app.mapPick?.close === close) app.mapPick.choose(option.id);
        });
        $('#ttHint').appendChild(button);
      }
      if (choice.maximum > 1) {
        const done = document.createElement('button');
        done.type = 'button'; done.textContent = 'Confirm selection';
        done.disabled = app.mapPick.selected.size < choice.minimum;
        done.addEventListener('click', () => {
          if (!currentViewer().ready || done.disabled || app.mapPick?.close !== close || app.mapPick.cancelling) return;
          close({selection: 'USE', option_ids: [...app.mapPick.selected]});
        });
        $('#ttHint').appendChild(done);
      }
    };
    app.mapPick.update = update;
    update();
    renderHighlights();
  });
}

function answerMapPick(cell, targetId = null) {
  const pick = app.mapPick;
  // The cover retains the exact picker/continuation. Check at settlement, not
  // only when it opens: keyboard, hint and board callbacks can outlive a view.
  if (!pick || pick.cancelling || !currentViewer().ready) return false;
  const option = (targetId && pick.prompt.choice.options.find(row => row.target_id === targetId))
    || pick.options.get(`${cell.x},${cell.y}`);
  if (!option) return false;
  const heights = targetId && option.target_id ? [option] : pick.altitudes?.get(`${cell.x},${cell.y}`) || [option];
  const select = answer => {
    if (answer?.cancel_initial) return cancelMapPick();
    if (!answer || typeof answer === 'string' || pick.prompt.choice.maximum <= 1) return pick.close(answer);
    pick.choose(answer.option_ids[0]);
  };
  if (heights.length > 1 || heights.some(row => /Hits allies too:|Allies you can choose:/.test(row.label || ""))) {
    if (pick.choosingHeight) return false;
    pick.choosingHeight = true;
    showChoiceDialog({...pick.prompt, title: heights.length > 1 ? 'Choose the height for this square' : 'Confirm this square',
      choice: {...pick.prompt.choice, map_pick: null, space_map: null, minimum: 1, maximum: 1,
        options: heights.map(row => ({...row,
          label: row.label || (row.cell.z ? `${row.cell.z * 5} feet above ground` : 'At ground level')}))}})
      .then(answer => { pick.choosingHeight = false; select(answer); });
    return true;
  }
  select({selection: "USE", option_ids: [option.id]});
  return true;
}

// Esc and Cancel go through the ability's cancel rule; an optional square is skipped by its own button.
function cancelMapPick() {
  // This is user input. Remote supersession/cleanup uses pick.close directly
  // and must still be able to retire an obsolete choice while covered.
  if (!app.mapPick || !currentViewer().ready) return;
  cancelAbilityChoice();
}

// A fresh board selection takes priority; otherwise keep the last explicitly aimed-at target for combos.
function preferredTargets() {
  return app.selected.size ? [...app.selected] : (app.lastTarget ? [app.lastTarget] : []);
}

// The cover hides the map and every control with it, but key presses and late callbacks still
// arrive here and the last menu stays on the page. A user action made while the view is unavailable
// would spend a turn the player cannot see, so it is refused here. Remote cleanup retires its own
// choices without coming through this path, and automatic AI driving never does either.
function refuseCoveredView() {
  if (currentViewer().ready) return false;
  toast("The fight is covered right now. Nothing was sent.", true);
  return true;
}

// Act on one candidate that needs no further choice. A placement may already be open -- the pop-out
// sheet can press a button while the table is still waiting for a cell -- and that choice is answered
// by acting, so it is closed and settled here instead of being left on screen telling the player to
// press Cancel for a placement that no longer exists.
function actOnce(candidateId) {
  // Refuse before the outstanding choice is cancelled: a covered press is not the player's
  // answer, so it must leave the question exactly as it found it.
  if (refuseCoveredView()) return Promise.resolve(false);
  if (app.targeting || app.pendingChoice) cancelTargeting();
  return act(candidateId);
}

// Choose among an action's legal options (targets, area centres, destinations).
async function useGroup(group, {preferTargets = [], composed = false} = {}) {
  if (app.busy) { toast("Still working on your last action…"); return Promise.resolve(false); }
  if (group.options?.length === 1 && app.menu?.composition?.[group.options[0].candidate_id]
      && chooseLocalOption(group.options[0].candidate_id)) return Promise.resolve(true);
  // Native system actions (including movement-only standing) use their issued
  // candidates, not the catalog-only ability composition endpoint.
  if (!composed && app.optionDraft?.dirty && !group.source_definition_id?.startsWith('system:')) return aimComposedAction(group, preferTargets);
  // Missing options are not an invitation to aim at an empty map. Expand
  // source headers even if an older menu omitted the explicit lazy flag.
  const needsExpansion = !composed && (group.lazy || (!group.options?.length && group.source_definition_id));
  if (needsExpansion && refuseCoveredView()) return false;
  if (needsExpansion && (app.targeting || app.listPick || app.pendingChoice)) cancelTargeting();
  const serial = app.lazyChoiceSerial = (app.lazyChoiceSerial || 0) + 1;
  if (needsExpansion) {
    const match = app.matchId, menu = app.menu;
    toast(`Loading ${group.label} choices…`);
    try {
      const query = new URLSearchParams({source: group.source_definition_id,
        decision_id: menu.decision_id, state_version: menu.state_version});
      const result = await api(`/api/tabletop/matches/${enc(match)}/action-options?${query}`);
      if (app.lazyChoiceSerial !== serial || app.matchId !== match || app.menu?.decision_id !== menu.decision_id
          || app.menu?.state_version !== menu.state_version || refuseCoveredView()) return false;
      const expanded = result.actions?.find(row => row.source_definition_id === group.source_definition_id);
      if (!Array.isArray(expanded?.options) || !expanded.options.length) {
        toast(result.message || 'No legal options right now. Choose another action.', true);
        return false;
      }
      Object.assign(group, expanded, {lazy: false, expanded_from_lazy: true});
      const current = app.menu.actions?.find(row => row.source_definition_id === group.source_definition_id);
      if (current && current !== group) Object.assign(current, group);
    } catch (error) { toast(error.message, true); return false; }
  }
  const options = group.options;
  if (!Array.isArray(options) || !options.length) {
    cancelTargeting();
    toast("No legal options right now. Choose another action.", true);
    return false;
  }
  if (group.placement_picker && options.length > 1) return chooseFromList(group, options);
  // The resolving choice owns these landing squares. Submit one representative
  // candidate, then use its exact map choice; selected-token shortcuts must not
  // bind a default square or make the player choose the destination twice.
  if (group.destination_choice && options.length) return actOnce(options[0].candidate_id);
  if (options.length === 1) return Object.keys(options[0].roll_previews || {}).length
    ? chooseFromList(group, options) : actOnce(options[0].candidate_id);
  const preferred = preferTargets.length && options.find(option => option.target_ids.some(id => preferTargets.includes(id)));
  if (preferred) return Object.keys(preferred.roll_previews || {}).length
    ? chooseFromList(group, [preferred]) : actOnce(preferred.candidate_id);
  const actorId = app.menu?.actor_id;
  const byTarget = new Map();
  for (const option of options) {
    for (const id of option.target_ids) {
      if (id === actorId && option.target_ids.length === 1 && !option.area) continue;
      if (!byTarget.has(id)) byTarget.set(id, []);
      byTarget.get(id).push(option);
    }
  }
  const areas = options.filter(option => option.area && option.area.center);
  const destinations = options.filter(option => option.destination && !option.area);
  const selfOnly = options.filter(option => !option.area && !option.destination && option.target_ids.every(id => id === actorId));
  if (!byTarget.size && !areas.length && !destinations.length && selfOnly.length) return chooseFromList(group, selfOnly);
  return new Promise(resolve => {
    // One open choice for the table, whichever window started it. A new choice replaces the open
    // one cleanly: the older prompt resolves as "not used" instead of hanging, so clicking an
    // action in the pop-out sheet can no longer strand a placement on the main window.
    const open = app.targeting;
    const what = [byTarget.size && "a creature or object", areas.length && "a centre square", destinations.length && "a destination square"].filter(Boolean).join(" or ");
    app.targeting = {group, actorId, decisionId: app.menu?.decision_id, stateVersion: app.menu?.state_version,
                     byTarget, areas, destinations, resolve, hintText: `${group.label}: choose ${what}`};
    app.pendingChoice = {kind: areas.length || destinations.length ? "placement" : "target", label: group.label, actor_id: actorId,
                         prompt: `${what} for ${group.label}`};
    if (open) open.resolve(false);
    hint(`${group.label}: choose ${what}`);
    renderHighlights();
    broadcastActors();  // the pop-out sheet shows what the table is waiting for
  });
}

function chooseFromList(group, options) {
  return new Promise(resolve => {
    let submitted = false;
    const cancelPick = () => {
      if (submitted) return;
      submitted = true;
      app.listPick = null;
      hint(null);
      closeChoice();
      resolve(false);
    };
    app.listPick = {cancel: cancelPick};
    app.pendingChoice = {kind: "list", label: group.label, actor_id: app.menu?.actor_id,
      prompt: `an option for ${group.label}`};
    broadcastActors();
    const node = $("#ttHint");
    node.hidden = false;
    node.innerHTML = `<span></span>`;
    node.firstChild.textContent = `${group.label}:`;
    const addOption = (option, before) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = option.label || option.option_ids.join(", ") || "Use";
      // Pre-commit preview (owner 2026-10-15 04:39Z): a visible Advantage/Disadvantage label
      // whose hover lists each source on its own line, cancellation explained.The prose is
      // still on the button and the map hints; the label does not replace legal options.
      const previews = Object.values(option.roll_previews || {});
      const labeled = previews.filter(row => row.mode === "NORMAL" || row.mode === "ADVANTAGE" || row.mode === "DISADVANTAGE");
      if (labeled.length) {
        const modes = [...new Set(labeled.map(row => row.mode))];
        button.title = [...new Set(labeled.map(row => rollModeHover(row.mode, row.mode_sources)))].join("\n");
        for (const mode of modes) {
          const sources = labeled.filter(row => row.mode === mode).flatMap(row => row.mode_sources || []);
          button.appendChild(rollModeLabel(mode, sources));
        }
      }
      button.addEventListener("click", async () => {
        if (submitted) return;
        if (app.busy) { toast("Still working on your last action…"); return; }
        submitted = true;
        app.listPick = null;
        hint(null);
        closeChoice();
        resolve(await act(option.candidate_id));
      });
      node.insertBefore(button, before || null);
    };
    // Quick bar (owner 2026-10-13): the server already ranked these best-first
    // (combat/menu_rank.py); show only the top options_shown, with the rest one
    // click away behind "More…" so nothing here becomes unreachable.
    const shown = Math.min(group.options_shown ?? options.length, options.length);
    for (const option of options.slice(0, shown)) addOption(option);
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", cancelPick);
    if (shown < options.length) {
      const more = document.createElement("button");
      more.type = "button";
      more.textContent = `More… (+${options.length - shown})`;
      more.addEventListener("click", () => {
        for (const option of options.slice(shown)) addOption(option, more);
        more.remove();
      });
      node.appendChild(more);
    }
    node.appendChild(cancel);
  });
}

async function pickTarget(targetId) {
  if (app.busy) return;
  const targeting = app.targeting;
  const options = targeting.byTarget.get(targetId);
  if (!options) return;
  app.targeting = null;
  hint(null);
  closeChoice();  // the player answered: the sheet must stop saying the table is waiting for a target
  const result = options.length === 1 ? await act(options[0].candidate_id) : await chooseFromList(targeting.group, options);
  app.lastTarget = targetId;
  targeting.resolve(result);
}

// Several objects can share a square (object-arrange.js). Aiming at one of them asks which, in plain words, so a
// click near the crate never hits the barrel beside it by mistake; a lone object is picked at once.
function pickObjectInSquare(object, clickedId) {
  const targeting = app.targeting;
  const here = (app.state?.objects || []).filter(row => row.x === object.x && row.y === object.y && targeting.byTarget.has(row.id));
  if (here.length < 2) return pickTarget(here[0]?.id || object.id);
  if (clickedId) here.sort((a, b) => (b.id === clickedId) - (a.id === clickedId));
  const node = $("#ttHint");
  node.hidden = false;
  node.innerHTML = `<span></span>`;
  node.firstChild.textContent = `${targeting.group.label}: which object in this square?`;
  for (const row of here) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.objectChoice = row.id;
    button.textContent = `${row.name || "Object"} (${row.hp} of ${row.max_hp} hit points${row.blocks ? ", blocks the square" : ""})`;
    button.addEventListener("click", () => { if (app.targeting === targeting) pickTarget(row.id); });
    node.appendChild(button);
  }
  const back = document.createElement("button");
  back.type = "button";
  back.textContent = "Back";
  back.addEventListener("click", () => { if (app.targeting === targeting) hint(targeting.hintText); });
  node.appendChild(back);
}

// While a target is being chosen, decide what a pointer at `cell` is aimed at. A token covers the square
// under it, so a click on the token and a click on the square are the same aim and must answer the same way:
// an area centre first (the square belongs to the area even when a creature stands there), then a legal
// creature, then a legal object in the square, then a destination square. Both click handlers call this one
// function so the two answers cannot drift apart (Shatter Earth on a character's square, 2026-10-20).
function targetChoiceAt(cell) {
  const targeting = app.targeting;
  const area = targeting.areas.find(option => option.area.center.x === cell.x && option.area.center.y === cell.y);
  const destination = targeting.destinations.find(option => option.destination.x === cell.x && option.destination.y === cell.y);
  const occupant = actors().find(actor => actor.active && actor.position.x === cell.x && actor.position.y === cell.y);
  if (occupant && targeting.byTarget.has(occupant.entity_id) && !area) return {targetId: occupant.entity_id};
  const object = !occupant && !area && !destination
    && (app.state?.objects || []).find(row => row.x === cell.x && row.y === cell.y && targeting.byTarget.has(row.id));
  if (object) return {object};
  const option = area || destination;
  return option ? {option, area: Boolean(area)} : null;
}

// Commit the answer targetChoiceAt found. `clickedId` is the token the pointer landed on, when there was one,
// so an object sharing its square is picked before its neighbours.
function takeTargetChoice(choice, clickedId = null) {
  if (choice.targetId) {
    const object = objectById(choice.targetId);
    return object ? pickObjectInSquare(object, clickedId) : pickTarget(choice.targetId);
  }
  if (choice.object) return pickObjectInSquare(choice.object, clickedId);
  const targeting = app.targeting;
  app.targeting = null;
  hint(null);
  closeChoice();
  return targeting.resolve(act(choice.option.candidate_id));
}

function onTokenClick(id, event) {
  if (!app.state) return;
  // Tokens cover squares too (including a Large chooser's own legal destination).
  // Board token events stop propagation, so answer using the pointer's grid cell here.
  if (app.mapPick) {
    const cell = board.cellAt(event.clientX, event.clientY);
    return cell ? answerMapPick(cell, id) : false;
  }
  if (app.busy) return;
  if (String(id).startsWith("item:")) return;  // a dropped weapon marker
  if (String(id).startsWith("object:") && !app.targeting) {
    if (refuseCoveredView()) return false;
    const door = doorMenu(objectById(id), app.menu, app.state);
    if (!door) return;
    const node = $("#ttHint");
    node.hidden = false;
    node.replaceChildren();
    const text = document.createElement('span');
    text.textContent = door.message;
    node.appendChild(text);
    for (const option of door.options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = option.label;
      button.addEventListener('click', () => {
        if (app.busy || refuseCoveredView()) return;
        hint(null);
        void actOnce(option.candidate_id);
      });
      node.appendChild(button);
    }
    return;
  }
  if (app.targeting) {
    const targeting = app.targeting;
    const cell = board.cellAt(event.clientX, event.clientY);
    const choice = cell && targetChoiceAt(cell);
    // The token itself wins when it is a legal target and no area is aimed at its square; otherwise the
    // square decides, exactly as onCellClick does. Tokens cover the grid, so a click on a character's square
    // is often a click on its token.
    if (targeting.byTarget.has(id) && !choice?.area) {
      const object = objectById(id);
      if (object) return pickObjectInSquare(object, id);
      pickTarget(id);
    } else if (choice) takeTargetChoice(choice, id);
    else toast("That token is not a legal target for this action.", true);
    return;
  }
  // A ground token covers a blue square that can be a legal flight destination
  // above it. Use the selected height there too, including straight ascent.
  const occupied = app.menu && app.showMoves && !event.shiftKey ? actorById(id)?.position : null;
  if (occupied && app.menu && app.showMoves && !event.shiftKey && moveHeight() !== (occupied.z || 0)) {
    const cell = board.cellAt(event.clientX, event.clientY);
    const move = cell && selectedMoves().find(row => row.destination.x === cell.x && row.destination.y === cell.y);
    if (move) return moveTo(move);
  }
  app.pendingTurnSelection = null;
  if (event.shiftKey) { app.selected.has(id) ? app.selected.delete(id) : app.selected.add(id); }
  else { app.selected.clear(); app.selected.add(id); }
  app.lastTarget = null;
  renderTokens();
  renderRoster();
  renderInspector();
}

function selectActor(id) {
  if (!app.state || app.busy) return;
  app.pendingTurnSelection = null;
  app.selected.clear();
  app.selected.add(id);
  app.lastTarget = null;
  renderTokens();
  renderRoster();
  renderInspector();
}

async function onCellClick(cell) {
  if (!cell) return;
  // A place choice is answered by clicking its square, and it is open while the fight is working on the last
  // action, so it is routed before the busy guard below. Any other click during that time is still ignored.
  if (app.mapPick) return answerMapPick(cell);
  if (app.busy) return;
  if (app.targeting) {
    // The square is answered by the same function a token covering it uses, so an area centre, a creature,
    // an object and a destination square resolve alike on occupied and empty squares.
    const choice = targetChoiceAt(cell);
    if (choice) takeTargetChoice(choice);
    return;
  }
  const menu = app.menu;
  if (menu && app.showMoves) {
    const move = selectedMoves().find(row => row.destination.x === cell.x && row.destination.y === cell.y);
    if (move) return moveTo(move);
  }
}

// A move is shown the moment it is clicked -- its path and a pulsing outline where the token is going -- and the
// token itself only breathes, because the fight has not agreed to the move yet. It walks once, when the fight commits
// the move (owner 2026-09-28: "theres lag when i choose to move but it doesn't show anything").
async function moveTo(move) {
  if (app.busy) return false;
  app.pendingMove = {actorId: app.menu?.actor_id, path: move.path || [], destination: move.destination};
  renderHighlights();
  try {
    return await act(move.candidate_id, app.moveMode === 'jump_down' ? {movement_mode: 'jump_down'} : null);
  } finally {
    app.pendingMove = null;
    renderHighlights();
  }
}

function onCellHover(cell) {
  const changed = (cell?.x !== app.hoverCell?.x) || (cell?.y !== app.hoverCell?.y);
  app.hoverCell = cell;
  if (app.targeting) {
    const actor = cell && actors().find(row => row.active && row.position.x === cell.x && row.position.y === cell.y);
    const object = cell && (app.state?.objects || []).find(row => row.x === cell.x && row.y === cell.y);
    const id = actor?.entity_id || object?.id;
    app.hoverTarget = id && app.targeting.byTarget.has(id) ? id : null;
    const previews = (app.targeting.byTarget.get(app.hoverTarget) || [])
      .map(option => option.roll_previews?.[app.hoverTarget]?.text).filter(Boolean);
    hint(previews.length ? `${app.targeting.group.label}: ${[...new Set(previews)].join("; ")}` : app.targeting.hintText);
  }
  if (changed) renderHighlights();
}

// Drag your own token to a blue square to move.
function onTokenPointerDown(id, event) {
  if (app.busy || app.mapPick) return;
  const menu = app.menu;
  if (!menu || app.targeting || id !== menu.actor_id || event.button !== 0) return;
  app.dragMove = {id, startX: event.clientX, startY: event.clientY, moved: false};
  const move = moveEvent => {
    if (!app.dragMove) return;
    if (Math.hypot(moveEvent.clientX - app.dragMove.startX, moveEvent.clientY - app.dragMove.startY) > 6) app.dragMove.moved = true;
    if (app.dragMove.moved) onCellHover(board.cellAt(moveEvent.clientX, moveEvent.clientY));
  };
  const up = upEvent => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    const drag = app.dragMove;
    app.dragMove = null;
    if (drag?.moved) {
      const cell = board.cellAt(upEvent.clientX, upEvent.clientY);
      const target = cell && selectedMoves().find(row => row.destination.x === cell.x && row.destination.y === cell.y);
      if (target) moveTo(target);
      else if (cell) toast("You cannot move there this turn.", true);
    }
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

// ------------------------------------------------------------------ doing things
// Ask me reactions (owner 2026-09-26, step 16): "when a reaction can happen it stops and hands priority over to the
// player who then hits something to keep going". Nothing is committed until every prompt is answered; the same call
// is sent again with the answers so far.
function decisionText(prompt) {
  // Both dialogs share the same complete, escaped decision explanation.
  const paragraph = text => escapeHtml(text || "").replace(/\n/g, "<br>");
  return `<strong>${escapeHtml(prompt.reactor)}</strong>: <strong>${escapeHtml(prompt.reaction)}</strong>`
    + `<p>${paragraph(prompt.trigger || prompt.moment)}</p>`
    + `<p><strong>Cost now:</strong> ${paragraph(prompt.cost)}</p>`
    + `<p>${paragraph(prompt.summary)}</p>`
    + (prompt.limits ? `<p><strong>Limits:</strong> ${paragraph(prompt.limits)}</p>` : "")
    + (prompt.table_note ? `<p><strong>At this table:</strong> ${paragraph(prompt.table_note)}</p>` : "")
    + (prompt.rules ? `<details><summary>Full rules, targets and duration</summary><p>${paragraph(prompt.rules)}</p></details>` : "");
}

function spaceTokenCells(token) {
  // Legacy map payloads supplied only the anchor; newer pauses preserve footprints.
  return token.cells?.length ? token.cells : [token.position];
}

function spaceDescription(cell, map) {
  const dx = cell.x - map.origin.x, dy = cell.y - map.origin.y;
  const chooser = map.tokens.find(token => token.id === map.chooser_id);
  const ownSpace = chooser && spaceTokenCells(chooser).some(position => position.x === cell.x && position.y === cell.y);
  // Exact offsets distinguish equal-cost destinations, including moves that overlap
  // a large chooser's current footprint. Occupancy alone is not a destination.
  const large = chooser && spaceTokenCells(chooser).length > 1;
  const offset = (value, negative, positive) => value ? `${Math.abs(value)} square${Math.abs(value) === 1 ? "" : "s"} ${value < 0 ? negative : positive}` : "";
  const direction = [offset(dy, "north", "south"), offset(dx, "west", "east")].filter(Boolean).join(" and ");
  const where = direction
    ? `${direction} of ${large ? "your current top-left square" : "you"}${ownSpace ? ", currently part of your space" : ""}`
    : large ? "your current top-left square" : "your current square";
  const distanceTo = token => Math.min(...spaceTokenCells(token).map(position =>
    Math.max(Math.abs(position.x - cell.x), Math.abs(position.y - cell.y))));
  const occupants = map.tokens.filter(token => token.id !== map.chooser_id && distanceTo(token) === 0);
  const nearby = map.tokens.filter(token => token.id !== map.chooser_id
    && distanceTo(token) === 1);
  return where + (occupants.length ? `, occupied by ${occupants.map(token => token.name).join(", ")}`
    : nearby.length ? `, beside ${nearby.map(token => token.name).join(", ")}` : "");
}

function spaceOptionLabel(option, map) {
  const description = spaceDescription(option.cell, map);
  if (!option.label || option.label === option.id) return description;
  // Preserve a route's distance, costs and effects while replacing its coordinates.
  const coordinates = new RegExp(`(?<![\\d-])(?:cell:)?${option.cell.x}\\s*,\\s*${option.cell.y}(?!\\d)`, "g");
  const label = option.label.replace(coordinates, description);
  return label === option.label ? `${description}: ${label}` : label;
}

function spaceGrid(choice, many) {
  const map = choice.space_map;
  if (!map) return "";
  const chooser = map.tokens.find(token => token.id === map.chooser_id);
  const positions = [...(chooser ? spaceTokenCells(chooser) : [map.origin]), ...choice.options.map(option => option.cell)];
  const minX = Math.max(0, Math.min(...positions.map(cell => cell.x)) - 1);
  const minY = Math.max(0, Math.min(...positions.map(cell => cell.y)) - 1);
  const maxX = Math.min(map.width - 1, Math.max(...positions.map(cell => cell.x)) + 1);
  const maxY = Math.min(map.height - 1, Math.max(...positions.map(cell => cell.y)) + 1);
  const legal = new Map(choice.options.map(option => [`${option.cell.x},${option.cell.y}`, option]));
  const blocked = new Set(map.blocked.map(cell => `${cell.x},${cell.y}`));
  let squares = "";
  for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) {
    const key = `${x},${y}`, option = legal.get(key);
    const tokens = map.tokens.filter(token => spaceTokenCells(token).some(cell => cell.x === x && cell.y === y));
    const face = tokens.map(token => token.name.split(/\s+/).filter(Boolean).slice(0, 2).map(word => word[0]).join("")).join(" / ");
    const label = (option ? spaceOptionLabel(option, map) : spaceDescription({x, y}, map)) + (blocked.has(key) ? ", wall" : "");
    const attributes = option ? `${many ? 'data-space-option' : 'data-option'}="${escapeHtml(option.id)}"${many ? ' aria-pressed="false"' : ''}` : "disabled";
    squares += `<button type="button" class="tt-space${option ? " is-legal" : ""}${blocked.has(key) ? " is-wall" : ""}${tokens.some(token => token.id === map.chooser_id) ? " is-chooser" : ""}" ${attributes} aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${escapeHtml(face || (option ? "●" : ""))}</button>`;
  }
  return `<p class="tt-muted">North is up. Highlighted spaces are available. Your token has a gold outline. Each square is ${escapeHtml(map.square_size_ft || 5)} feet. Large creatures fill several squares; destinations are measured from their current top-left square.</p>`
    + `<div class="tt-space-scroll"><div class="tt-space-grid" role="group" aria-label="Choose a space on the map" style="grid-template-columns:repeat(${maxX - minX + 1},2.5rem)">${squares}</div></div>`
    + `<p class="tt-muted">Tokens: ${map.tokens.filter(token => spaceTokenCells(token).some(cell => cell.x >= minX && cell.x <= maxX && cell.y >= minY && cell.y <= maxY)).map(token => escapeHtml(token.name)).join(", ")}. You can also choose from the descriptions below.</p>`;
}

function askChoice(prompt) {
  // A choice riding the reaction transport (Exploit, Footwork...) is picked by name.
  // A choice is spatial only when the engine gave an option a square (its own cell or a square ID). Then the
  // map answers it, and a creature option in that choice is its token's square. A creature-only list, or a
  // text list, keeps its dialog. Older pending prompts may lack map_pick (or even cell). Decode only the
  // established transport shapes, never coordinates scraped from player text.
  const choice = prompt.choice;
  const explicitCell = option => option.cell || option.position || option.destination || option.area?.center;
  const idCell = option => {
    const match = /^(?:cell:)?(-?\d+),(-?\d+)(?:,(-?\d+))?$/.exec(option.id);
    return match ? {x: Number(match[1]), y: Number(match[2]), z: Number(match[3] || 0)} : null;
  };
  let options = (choice?.options || []).map(option => {
    const position = explicitCell(option) || idCell(option);
    return position ? {...option, cell: position} : option;
  });
  if (!options.some(option => option.cell)) return showChoiceDialog(prompt);
  options = options.map(option => {
    if (option.cell) return option;
    const actor = actorById(option.id);
    return actor?.position ? {...option, cell: actor.position, target_id: option.id} : option;
  });
  return mapPickChoice({...prompt, choice: {...choice, options}});
}

// Shared modal lifecycle for all reaction prompt renderers.
function wireReactionDialog(dialog, done, decline) {
  const cancelButton = dialog.querySelector("[data-cancel-ability]");
  const cancel = event => { event.preventDefault(); cancelAbilityChoice(); };
  const cancelOnMap = event => {
    if (!abilityChoiceActive() || abilityReserved()) return;
    event.preventDefault(); cancelAbilityChoice();
  };
  dialog.addEventListener("cancel", cancel);
  dialog.addEventListener("contextmenu", cancelOnMap);
  if (cancelButton) {
    cancelButton.hidden = abilityReserved();
    cancelButton.onclick = () => { if (!abilityReserved()) cancelAbilityChoice(); };
  }
  if (!abilityReserved()) hint("Choose a response, or cancel this ability.", () => cancelAbilityChoice());
  app.finishReaction = done;
  app.declineReaction = decline || null;
  return () => {
    dialog.removeEventListener("cancel", cancel);
    dialog.removeEventListener("contextmenu", cancelOnMap);
    if (cancelButton) { cancelButton.hidden = true; cancelButton.onclick = null; }
    if (app.finishReaction === done) app.finishReaction = null;
    if (app.declineReaction === decline) app.declineReaction = null;
  };
}

function showChoiceDialog(prompt) {
  const dialog = $("#ttReaction"), choice = prompt.choice;
  const many = choice.maximum > 1;
  $("#ttReactionTitle").textContent = prompt.title || prompt.reaction;
  $("#ttReactionText").innerHTML = decisionText(prompt)
    + (many ? ` <span class="tt-muted">(choose ${choice.minimum === choice.maximum ? choice.maximum : `${choice.minimum}–${choice.maximum}`})</span>` : "")
    + spaceGrid(choice, many)
    + `<div class="tt-choice-list" aria-label="${choice.space_map ? "Choose a space by description" : "Choices"}">${choice.options.map(option => {
      const label = choice.space_map ? spaceOptionLabel(option, choice.space_map) : option.label;
      const description = option.description && option.description !== option.label ? `<br>${escapeHtml(option.description)}` : "";
      return many
        ? `<label><input type="checkbox" value="${escapeHtml(option.id)}"> ${escapeHtml(label)}${description}</label>`
        : `<button type="button" class="tt-tool" data-option="${escapeHtml(option.id)}">${escapeHtml(label)}${description}</button>`;
    }).join("")}</div>`;
  const buttons = [...dialog.querySelectorAll("[data-answer]")];
  const hidden = buttons.map(button => button.hidden);
  return new Promise(resolve => {
    let settled = false, cleanup;
    const declineHere = () => { if (choice.allow_decline) done("DECLINE"); };
    const done = answer => {
      if (settled) return;
      settled = true;
      cleanup();
      dialog.close();
      buttons.forEach((button, index) => { button.hidden = hidden[index]; });
      resolve(answer);
    };
    cleanup = wireReactionDialog(dialog, done, choice.allow_decline ? declineHere : null);
    dialog.querySelectorAll("[data-option]").forEach(button => { button.onclick = () => done({selection: "USE", option_ids: [button.dataset.option]}); });
    if (many && choice.space_map) {
      const sync = () => dialog.querySelectorAll("[data-space-option]").forEach(button => {
        const input = [...dialog.querySelectorAll(".tt-choice-list input")].find(input => input.value === button.dataset.spaceOption);
        button.setAttribute("aria-pressed", String(!!input?.checked));
      });
      dialog.querySelectorAll(".tt-choice-list input").forEach(input => { input.onchange = sync; });
      dialog.querySelectorAll("[data-space-option]").forEach(button => { button.onclick = () => {
        const input = [...dialog.querySelectorAll(".tt-choice-list input")].find(input => input.value === button.dataset.spaceOption);
        input.checked = !input.checked; sync();
      }; });
    }
    for (const button of buttons) {
      if (button.dataset.answer === "USE") {
        button.hidden = !many;
        button.onclick = () => {
          const picked = [...dialog.querySelectorAll(".tt-choice-list input:checked")].map(input => input.value);
          if (picked.length < choice.minimum || picked.length > choice.maximum) { toast(`Choose ${choice.minimum}–${choice.maximum}.`, true); return; }
          done({selection: "USE", option_ids: picked});
        };
      } else {
        button.hidden = !choice.allow_decline;
        button.onclick = declineHere;
      }
    }
    // Register even a newly arriving prompt with the identity lifecycle. Its
    // answer/handlers stay pending while covered, just like an open suspension.
    app.viewerSuspendedReaction = {waiting: app.waitingReaction, finish: done, matchId: app.matchId};
    resumeViewerDialogs();
  });
}

function askReactionInput(prompt) {
  app.restoreReactionButtons?.();
  $("#ttReaction").querySelectorAll("[data-answer]").forEach(button => { button.disabled = false; });
  if (prompt.alternatives) return askReactionMenu(prompt);
  if (prompt.choice) return askChoice(prompt);
  const dialog = $("#ttReaction");
  $("#ttReactionTitle").textContent = prompt.title || "Reaction";
  $("#ttReactionText").innerHTML = decisionText(prompt);
  return new Promise(resolve => {
    let cleanup;
    const done = answer => { cleanup?.(); dialog.close(); resolve(answer); };
    cleanup = wireReactionDialog(dialog, done, () => done("DECLINE"));
    dialog.querySelectorAll("[data-answer]").forEach(button => { button.onclick = () => done(button.dataset.answer); });
    app.viewerSuspendedReaction = {waiting: app.waitingReaction, finish: done, matchId: app.matchId};
    resumeViewerDialogs();
  });
}

function reactionMenuAnswers(prompt, index, answer = "DECLINE") {
  const alternatives = prompt.alternatives || [prompt];
  const decisions = [];
  for (let i = 0; i < alternatives.length; i += 1) {
    decisions.push({...alternatives[i].context,
      ...(i === index ? (typeof answer === "string" ? {selection: answer} : answer) : {selection: "DECLINE"})});
    if (i === index) break;
  }
  return decisions;
}

// The answer for a map square picked from the reaction menu. A cancelled pick takes the menu's own cancel route
// (the same all-DECLINE answer as Skip), never a decision without a selection.
function reactionMenuMapAnswer(prompt, index, picked) {
  if (picked?.cancelled) return reactionMenuAnswers(prompt, -1);
  return reactionMenuAnswers(prompt, index, picked);
}

function reactionMenuRows(prompt) {
  const groups = [];
  prompt.alternatives.forEach((row, index) => {
    const source = row.context.reaction_source_id;
    const base = source.replace(/:mode:\d+$/, "");
    const key = `${row.context.reactor_id}:${row.context.checkpoint}:${base}:${row.useful_now !== false}`;
    let group = groups.find(value => value.key === key);
    if (!group) {
      group = {key, label: source === base ? row.reaction : row.reaction.split(" — ")[0], modes: []};
      groups.push(group);
    }
    group.modes.push({row, index});
  });
  // Preserve transport indexes even as the visible list and inline modes rank.
  for (const group of groups) {
    group.modes.sort((a, b) => Number(b.row.useful_now !== false) - Number(a.row.useful_now !== false)
      || (b.row.menu_priority || 0) - (a.row.menu_priority || 0));
    group.useful = group.modes.some(({row}) => row.useful_now !== false);
    group.priority = Math.max(...group.modes.map(({row}) => row.menu_priority || 0));
  }
  return groups.sort((a, b) => Number(b.useful) - Number(a.useful) || b.priority - a.priority);
}

function reactionMenuChoice(row, index) {
  const choice = row.choice;
  if (!choice) return "";
  if (choice.map_pick || choice.options.some(option => option.cell)) {
    return '<p>After pressing Use, choose the highlighted squares or creatures on the map.</p>';
  }
  const label = option => choice.space_map ? spaceOptionLabel(option, choice.space_map) : option.label;
  const options = choice.options.map(option => {
    const text = label(option) + (option.description && option.description !== option.label ? ` — ${option.description}` : "");
    return choice.maximum > 1
      ? `<label><input type="checkbox" value="${escapeHtml(option.id)}"> ${escapeHtml(text)}</label>`
      : `<option value="${escapeHtml(option.id)}">${escapeHtml(text)}</option>`;
  }).join("");
  return `<div data-reaction-choice="${index}"><label>Choose ${choice.maximum > 1 ? `${choice.minimum}–${choice.maximum}` : "one"} for ${escapeHtml(row.reaction)}</label>`
    + (choice.maximum > 1 ? options : `<select aria-label="${escapeHtml(row.reaction)} choice"><option value="">Choose one…</option>${options}</select>`)
    + `</div>`;
}

function askReactionMenu(prompt) {
  app.restoreReactionButtons?.();
  const dialog = $("#ttReaction"), groups = reactionMenuRows(prompt);
  $("#ttReactionTitle").textContent = "Choose your reaction";
  const entry = (group, groupIndex) =>
      `<section class="tt-reaction-entry" data-reaction-entry="${groupIndex}"><h3>${escapeHtml(group.label)}</h3>`
      + (group.modes.length > 1 ? `<label>Choose one mode <select data-reaction-mode="${groupIndex}" aria-label="${escapeHtml(group.label)} mode">${group.modes.map(({row, index}) =>
        `<option value="${index}">${escapeHtml(row.reaction.split(" — ").slice(1).join(" — "))}</option>`).join("")}</select></label>` : "")
      + group.modes.map(({row, index}, modeIndex) => `<div data-reaction-detail="${index}"${modeIndex ? " hidden" : ""}>`
        + (row.expected_effect ? `<p class="tt-reaction-expected">${escapeHtml(row.expected_effect)}</p>` : "")
        + decisionText(row) + reactionMenuChoice(row, index) + `</div>`).join("")
      + `<button type="button" class="tt-tool" data-reaction-use="${groupIndex}">Use ${escapeHtml(group.label)}</button></section>`;
  const relevant = groups.map((group, index) => group.useful ? entry(group, index) : "").join("");
  const other = groups.map((group, index) => !group.useful ? entry(group, index) : "").join("");
  $("#ttReactionText").innerHTML = `<p>Choose a reaction, or Skip to keep your remaining Reaction and resources.</p>`
    + `<div class="tt-choice-list tt-reaction-list">${relevant || '<p>No reaction has a known useful effect now.</p>'}</div>`
    + (other ? `<details data-other-reactions><summary>Other reactions</summary>${other}</details>` : "");
  const buttons = [...dialog.querySelectorAll("[data-answer]")];
  buttons.forEach(button => { button.disabled = false; });
  const previous = buttons.map(button => ({hidden: button.hidden, text: button.textContent, onclick: button.onclick}));
  app.restoreReactionButtons = () => {
    buttons.forEach((button, i) => {
      button.hidden = previous[i].hidden; button.textContent = previous[i].text;
      button.onclick = previous[i].onclick; button.disabled = false;
    });
    app.restoreReactionButtons = null;
  };
  app.closeReactionMenu = () => { dialog.close(); app.restoreReactionButtons?.(); app.closeReactionMenu = null; };
  return new Promise(resolve => {
    let settled = false;
    const done = answer => {
      if (settled) return;
      settled = true;
      buttons.forEach(button => { button.disabled = true; });
      // The loop updates this very card if more responses remain. Keep it open
      // while the request is in flight; its caller closes it on commit/error.
      if (!Array.isArray(answer) || answer.every(row => row.selection === "DECLINE")) app.closeReactionMenu();
      dialog.querySelectorAll("[data-reaction-use]").forEach(button => { button.disabled = true; });
      resolve(answer);
    };
    const decline = () => finish(reactionMenuAnswers(prompt, -1));
    let cleanup;
    const finish = answer => { cleanup?.(); done(answer); };
    cleanup = wireReactionDialog(dialog, finish, decline);
    const selectedIndex = groupIndex => {
      const select = dialog.querySelector(`[data-reaction-mode="${groupIndex}"]`);
      return select ? Number(select.value) : groups[groupIndex].modes[0].index;
    };
    dialog.querySelectorAll("[data-reaction-mode]").forEach(select => { select.onchange = () => {
      const group = groups[Number(select.dataset.reactionMode)];
      group.modes.forEach(({index}) => { dialog.querySelector(`[data-reaction-detail="${index}"]`).hidden = index !== Number(select.value); });
    }; });
    let choosingMap = false;
    dialog.querySelectorAll("[data-reaction-use]").forEach(button => { button.onclick = async () => {
      if (settled || choosingMap) return;
      const index = selectedIndex(Number(button.dataset.reactionUse)), row = prompt.alternatives[index];
      const answer = {selection: "USE"};
      if (row.choice) {
        if (row.choice.map_pick || row.choice.options.some(option => option.cell)) {
          choosingMap = true;
          dialog.close();
          const picked = await askChoice(row);
          choosingMap = false;
          // Cancelling the square follows the menu's cancel route, never a decision without a selection.
          finish(reactionMenuMapAnswer(prompt, index, picked));
          return;
        }
        const inputs = dialog.querySelector(`[data-reaction-choice="${index}"]`);
        answer.option_ids = row.choice.maximum > 1
          ? [...inputs.querySelectorAll("input")].filter(input => input.checked).map(input => input.value)
          : [inputs.querySelector("select").value].filter(Boolean);
        if (answer.option_ids.length < row.choice.minimum || answer.option_ids.length > row.choice.maximum) {
          toast(`Choose ${row.choice.minimum}–${row.choice.maximum} for ${row.reaction}.`, true); return;
        }
      }
      finish(reactionMenuAnswers(prompt, index, answer));
    }; });
    buttons.forEach(button => {
      button.hidden = button.dataset.answer === "USE";
      if (!button.hidden) { button.textContent = "Skip"; button.onclick = decline; }
    });
    app.viewerSuspendedReaction = {waiting: app.waitingReaction, finish, matchId: app.matchId};
    resumeViewerDialogs();
  });
}

function appendReactionAnswer(reactions, prompt, answer) {
  reactions.push(...(Array.isArray(answer) ? answer :
    [{...prompt.context, ...(typeof answer === "string" ? {selection: answer} : answer)}]));
}

async function askReaction(prompt, reserved = false) {
  const waiting = {prompt, matchId: app.matchId, reserved};
  // Preparation has no saved pending_action. Keep it while the decision it
  // previews is current; saved/submitted prompts instead follow the server's answer keys.
  const binding = !reserved && !app.abilityChoice?.submitted ? app.abilityChoice?.binding : null;
  waiting.changed = state => binding
    ? app.matchId !== waiting.matchId || Boolean(state?.pending_action) || Boolean(state?.presentation?.terminal)
      || !state?.menu || Object.keys(binding).some(key => state.menu[key] !== binding[key])
    : decisionChanged(prompt, state?.pending_action);
  const superseded = new Promise(resolve => {
    waiting.stop = state => resolve({superseded: true, state, preparation: Boolean(binding)});
  });
  app.waitingReaction = waiting;
  try {
    return await Promise.race([askReactionInput(prompt), superseded]);
  } finally {
    if (app.viewerSuspendedReaction?.waiting === waiting) app.viewerSuspendedReaction = null;
    if (app.waitingReaction === waiting) app.waitingReaction = null;
    app.finishReaction?.("DECLINE");
    app.finishReaction = null;
    app.declineReaction = null;
    app.mapPick?.close?.("DECLINE");
    closeChoice();
  }
}

// The caller passes the choice it started with: a late continuation must never
// adopt a newer action's choice (or close its reaction dialog) through the global.
// reserved: the answers belong to a prompt the table already saved (auto-step, or a submitted choice).
async function withReactions(send, choice = app.abilityChoice, {reserved = false} = {}) {
  const cancelled = () => Boolean(choice?.cancelled);
  const reactions = [];
  try {
    for (let asked = 0; asked < 40; asked += 1) {
      // Preparation is read-only. Release its caller on Cancel even when the
      // transport never settles; the abandoned response cannot present choices.
      const result = await (choice?.cancellation
        ? Promise.race([send(reactions), choice.cancellation]) : send(reactions));
      if (cancelled()) return {status: "CANCELLED"};
      if (result.status !== "REACTION_REQUIRED") return result;
      await playEvents(result.events);
      if (cancelled()) return {status: "CANCELLED"};
      const answer = await askReaction(result.reaction, reserved || Boolean(choice?.submitted));
      if (answer?.cancelled) return {status: "CANCELLED"};
      if (answer?.superseded) {
        // A remote change can invalidate a preview, but cannot commit this unsent action.
        if (answer.preparation) {
          await reconcileRemoteDecision(answer.state, true);
          return {status: "CANCELLED"};
        }
        return reconcileRemoteDecision(answer.state, false);
      }
      appendReactionAnswer(reactions, result.reaction, answer);
    }
    throw new Error("This action could not finish resolving choices. Reopen the fight to check its current turn before choosing another action. If it happens again, ask the GM for help.");
  } finally {
    if (app.abilityChoice === choice) app.closeReactionMenu?.();
  }
}

// A reload has no withReactions closure, so continue from the exact saved request and prompt.
async function resumePendingAction(pending, reserved = false, present = true) {
  if (!pending?.request || !pending?.reaction || (app.busy && !reserved)) return;
  if (!currentViewer().ready) { app.viewerDeferredPrompt = true; return; }
  app.busy = true;
  try {
    const reactions = [...(pending.reactions || [])];
    let prompt = pending.reaction;
    for (let asked = 0; asked < 40; asked += 1) {
      const answer = await askReaction(prompt, true);
      if (answer?.cancelled) return {status: "CANCELLED"};
      if (answer?.superseded) {
        return await reconcileRemoteDecision(answer.state, present);
      }
      appendReactionAnswer(reactions, prompt, answer);
      const {movement_path, ...request} = pending.request;
      const endpoint = pending.method === "auto_step" ? "auto-step" : movement_path ? "movement-path/commit" : "act";
      if (movement_path) request.waypoints = movement_path;
      // The saved request binds the action, not this client's journal cursor.
      // Catch-up may have consumed events after the other client's saved after.
      const result = await api(`/api/tabletop/matches/${enc(app.matchId)}/${endpoint}`, {body: {...request, after: app.lastSequence, reactions}});
      if (result.status !== "REACTION_REQUIRED") {
        if (present) {
          await playEvents(result.events, {finalizePause: true});
          render(result.state);
          gmNotice(result.events?.events || []);
        }
        return result;
      }
      await playEvents(result.events);
      prompt = result.reaction;
    }
    throw new Error("This action could not finish resolving choices. Reopen the fight to check its current turn before choosing another action.");
  } catch (error) {
    if (!await handleUnavailableFight(error)) {
      toast(error.message, true);
      await refresh();
    }
  } finally {
    app.closeReactionMenu?.();
    if (!reserved) app.busy = false;
  }
}

// State reads do not consume the journal. Catch up before render advances its
// cursor, including when another client has reached a different pending choice.
// An act/autoStep caller presents the final result itself; a reload does it here.
async function reconcileRemoteDecision(state, present) {
  if (!state || !app.matchId) return {status: "CANCELLED", state: null, events: {events: []}};
  const events = await api(`/api/tabletop/matches/${enc(app.matchId)}/events?after=${app.lastSequence}`);
  if (state.pending_action) {
    await playEvents(events);
    render(state);
    gmNotice(events.events || []);
    return resumePendingAction(state.pending_action, true, present);
  }
  const result = {status: "COMMITTED", state, events};
  if (present) {
    await playEvents(events);
    render(state);
    gmNotice(events.events || []);
  }
  return result;
}

// The Items panel over the action bar: what the fighter whose turn it is carries, Drop / Pick up, and weapons lying
// within reach (their own Pick up).
function renderItemsPanel() {
  let panel = document.getElementById("ttItems");
  const menu = app.menu, load = menu?.manual ? (app.state?.carrying || {})[menu.actor_id] : null;
  if (!app.showItems || !load) { panel?.remove(); return; }
  if (!panel) { panel = document.createElement("section"); panel.id = "ttItems"; panel.className = "tt-items tt-card"; document.body.appendChild(panel); }
  const weaponPickups = (menu.actions || []).filter(group => group.item === "weapon_pickup");
  const row = item => {
    const button = item.drop ? `<button type="button" class="tt-tool" data-act="${escapeHtml(item.drop)}">Drop</button>`
      : item.pickup ? `<button type="button" class="tt-tool tt-primary" data-act="${escapeHtml(item.pickup)}">Pick up</button>` : "";
    const state = item.worn ? "worn" : item.held ? "" : "on the ground";
    return `<li class="${item.held || item.worn ? "" : "is-dropped"}"><span>${escapeHtml(item.name)}${item.quantity > 1 ? ` ×${item.quantity}` : ""}`
      + `${state ? ` <em class="tt-muted">${state}</em>` : ""}</span><span class="tt-muted">${escapeHtml(item.weight_lb)} lb</span>${button}</li>`;
  };
  panel.innerHTML = `<div class="tt-items-head"><h2 class="tt-card-title">Items</h2>`
    + `<span class="${load.over ? "tt-items-over" : "tt-muted"}">${escapeHtml(load.weight_lb)} / ${load.capacity_lb} lb`
    + `${load.over ? " · over capacity: Speed at most 5 ft" : ""}</span><button type="button" class="tt-tool" data-close>✕</button></div>`
    + `<p class="tt-muted tt-items-note">Dropping is free. A dropped item lies at your feet until you pick it up (within 5 ft). Speed follows the load from the start of your next turn.</p>`
    + `<ul class="tt-items-list">${load.items.map(row).join("")}</ul>`
    + (weaponPickups.length ? `<h3 class="tt-items-sub">Within reach</h3><ul class="tt-items-list">${weaponPickups.map(group =>
      `<li><span>${escapeHtml(group.label)}</span><span></span><button type="button" class="tt-tool tt-primary" data-act="${escapeHtml(group.options[0].candidate_id)}">Pick up</button></li>`).join("")}</ul>` : "");
  panel.querySelector("[data-close]").addEventListener("click", () => { app.showItems = false; renderItemsPanel(); renderActionBar(); });
  panel.querySelectorAll("[data-act]").forEach(button => button.addEventListener("click", () => { button.disabled = true; void act(button.dataset.act); }));
}

function draftOptionRows(actorId) {
  const rows = (app.state?.shapes || {})[actorId] || [];
  return app.optionDraft?.matches(app.menu, app.matchId) ? app.optionDraft.project(rows) : rows;
}

function chooseLocalOption(candidateId) {
  if (!app.menu?.composition?.[candidateId]) return false;
  if (refuseCoveredView() || app.busy) return true;
  if (!app.optionDraft?.matches(app.menu, app.matchId)) app.optionDraft = new OptionDraft(app.menu, app.matchId);
  app.optionDraft.choose(candidateId);
  app.composedAction = null;
  cancelTargeting();
  renderShapePanel();
  renderDraftSummary();
  return true;
}

function useOptionCandidate(candidateId) {
  if (chooseLocalOption(candidateId)) return Promise.resolve(true);
  // Options panels can also contain the real activation (e.g. bloom at once).
  // It must aim/fire the draft through the same path as the main action bar.
  const group = app.menu?.actions.find(row => row.options.some(option => option.candidate_id === candidateId));
  return group ? useGroup(group) : act(candidateId);
}

function useOptionActivation(buttonId) {
  const draft = app.optionDraft;
  if (!draft?.dirty || !draft.matches(app.menu, app.matchId)) return Promise.resolve(false);
  const family = draftOptionRows(app.menu.actor_id).find(entry => (entry.choices || [])
    .some(choice => choice.activation && choice.button_id === buttonId));
  if (!family || !buttonId.startsWith('act:')
      || !Object.values(app.menu.composition || {}).some(choice => choice.family === family.base)) return Promise.resolve(false);
  const choice = family.choices.find(row => row.button_id === buttonId);
  // This is only an aiming entry. The scoped preview, never a saved parent
  // candidate, supplies the secondary activation's legal targets and costs.
  return useGroup({source_definition_id: buttonId.slice(4), label: choice.label, options: []});
}

function renderDraftSummary() {
  broadcastDraftStates();  // the pop-out sheet re-marks Active rows in place
  const entries = draftOptionRows(app.menu?.actor_id);
  for (const button of document.querySelectorAll('[data-option-family]')) {
    const entry = entries.find(row => row.base === button.dataset.optionFamily);
    if (entry) button.querySelector('small').textContent = [entry.augments_label, entry.current].filter(Boolean).join(' · ') || `plain ${entry.name}`;
  }
  for (const button of document.querySelectorAll('[data-composition-source]')) {
    // Draft costs/shape can make a previously unavailable ability legal. Its
    // targeted preview checks that without rebuilding every action button.
    button.disabled = !app.optionDraft?.dirty && button.dataset.baseLegal !== 'true';
  }
}

async function aimComposedAction(group, preferTargets) {
  if (refuseCoveredView()) return false;
  const draft = app.optionDraft;
  const revision = draft.revision;
  const request = draft.request(group.alias_of || group.source_definition_id, crypto.randomUUID());
  // This first preview is preparation too: own a cancellable token before the
  // transport starts, so a late response cannot reopen targeting or submit.
  const choice = {cancelled: false, working: true};
  if (app.abilityChoice) cancelAbilityChoice();
  choice.cancellation = new Promise(resolve => { choice.stop = () => resolve({status: "CANCELLED"}); });
  app.abilityChoice = choice;
  app.busy = true;
  refreshSequence++;
  document.body.classList.add("is-ability-choice", "is-working");
  hint("Preparing your ability options…", () => cancelAbilityChoice());
  let result;
  try {
    result = await Promise.race([
      api(`/api/tabletop/matches/${enc(app.matchId)}/composition/preview`, {body: request}), choice.cancellation,
    ]);
    if (choice.cancelled || app.abilityChoice !== choice || refuseCoveredView()
        || app.optionDraft !== draft || draft.revision !== revision
        || !draft.matches(app.menu, app.matchId)) return false;
  } catch (error) {
    if (!choice.cancelled) toast(error.message, true);
    return false;
  } finally {
    // Only this preparation may release its busy state and loading hint.
    // The target picker / act below will take ownership after a valid preview.
    if (app.abilityChoice === choice) {
      app.abilityChoice = null;
      app.busy = false;
      document.body.classList.remove("is-ability-choice", "is-working");
      hint(null);
    }
  }
  const groups = result.menu?.actions || [];
  if (!groups.length) { toast('This ability cannot be used with these choices right now. Change your options.', true); return false; }
  app.composedAction = {request, menu: result.menu};
  // All target variants remain reachable, using the existing local target/list chooser.
  const combined = {...group, ...groups[0], options: groups.flatMap(row => row.options),
    // The preview already issued the drafted candidates. Do not inherit the
    // base header's lazy flag and replace these with unmodified native ones.
    lazy: false, expanded_from_lazy: false,
    destination_choice: groups.every(row => row.destination_choice),
    placement_picker: groups.some(row => row.placement_picker), options_shown: undefined};
  return useGroup(combined, {preferTargets, composed: true});
}

function renderShapePanel() {
  let panel = document.getElementById("ttShape");
  const menu = app.menu;
  const entry = menu?.manual ? draftOptionRows(menu.actor_id).find(row => row.base === app.showShape) : null;
  if (!entry) { panel?.remove(); return; }
  if (!app.abilityChoice && !app.targeting && !app.mapPick && !app.listPick)
    hint(`${entry.name}: choose your ability options, or cancel.`, () => cancelAbilityChoice());
  if (!panel) { panel = document.createElement("section"); panel.id = "ttShape"; panel.className = "tt-items tt-card"; document.body.appendChild(panel); }
  const row = option => `<li data-button-id="${escapeHtml(option.button_id)}"><span>${escapeHtml(option.label)}</span>`
    + `<span class="tt-muted">${escapeHtml(option.cost || "")}</span>`
    + (option.active ? "<span></span>" : option.candidate_id ? `<button type="button" class="tt-tool tt-primary" data-act="${escapeHtml(option.candidate_id)}">Choose</button>`
      : `<span class="tt-muted" title="Not enough to pay for it now">—</span>`) + "</li>";
  const augment = row_ => `<li data-button-id="${escapeHtml(row_.button_id)}"><span>${escapeHtml(row_.name)}</span>`
    + `<span class="tt-muted">${escapeHtml(row_.cost || "")}</span>`
    + (row_.candidate_id ? `<button type="button" class="tt-tool ${row_.on ? "" : "tt-primary"}" data-act="${escapeHtml(row_.candidate_id)}">${row_.on ? "Turn off" : "Turn on"}</button>` : "<span></span>")
    + "</li>";
  const augments = entry.augments.length
    ? `<h3 class="tt-items-sub">Augments <span class="tt-muted">(any number; each costs extra when you use ${escapeHtml(entry.name)})</span>${entry.augments_label && entry.clear_candidate ? ` <button type="button" class="tt-tool" data-act="${escapeHtml(entry.clear_candidate)}">Clear</button>` : ""}</h3>`
      + `<ul class="tt-items-list">${entry.augments.map(augment).join("")}</ul>` : "";
  const talents = entry.options.length
    ? `<h3 class="tt-items-sub">${escapeHtml(entry.name)} talent <span class="tt-muted">(one per ${escapeHtml(entry.name)}; a pair only with the talent that allows it, like Pitch Black)</span></h3>`
      + `<ul class="tt-items-list">${entry.options.map(row).join("")}</ul>` : "";
  const canDraftActivation = Object.values(menu.composition || {}).some(choice => choice.family === entry.base)
    && app.optionDraft?.dirty && app.optionDraft.matches(menu, app.matchId);
  const choices = (entry.choices || []).length
    ? `<h3 class="tt-items-sub">${escapeHtml(entry.name)} choices <span class="tt-muted">(one choice per setting; saved when you use the ability)</span></h3>`
      + `<ul class="tt-items-list">${entry.choices.map(option => `<li data-button-id="${escapeHtml(option.button_id)}"><span>${escapeHtml(option.label)}</span>`
        + (option.active ? "<span></span>" : option.candidate_id ? `<button type="button" class="tt-tool tt-primary" data-act="${escapeHtml(option.candidate_id)}">Choose</button>`
        : option.activation && option.button_id?.startsWith('act:') && canDraftActivation
          ? `<button type="button" class="tt-tool tt-primary" data-option-activation="${escapeHtml(option.button_id)}" title="Check costs and legal targets for these choices before use">Aim</button>`
          : `<span class="tt-muted">—</span>`) + "</li>").join("")}</ul>` : "";
  const modifiers = (entry.modifiers || []).map(modifier => `<li class="tt-modifier-row" title="${escapeHtml(modifier.description || "")}"><span>${escapeHtml(modifier.name)} · ${modifier.on ? "On" : "Off"}</span>`
    + `<span>${escapeHtml(modifier.cost)} on a hit; a miss costs nothing.</span>`
    + `<button type="button" class="tt-tool" data-act="${escapeHtml(modifier.candidate_id || "")}" ${modifier.candidate_id ? "" : "disabled"}>Turn ${modifier.on ? "off" : "on"}</button>`
    + modifier.selectors.map(selector => `<label>${escapeHtml(selector.label)} <select data-modifier-choice>`
      + selector.options.map(option => `<option value="${escapeHtml(option.candidate_id || "")}" ${option.value === selector.current ? "selected" : ""} ${option.candidate_id ? "" : "disabled"}>${escapeHtml(option.label)}</option>`).join("") + `</select></label>`).join("") + `</li>`).join("");
  panel.innerHTML = `<div class="tt-items-head"><h2 class="tt-card-title">${escapeHtml(entry.name)} options</h2>`
    + `<span class="tt-muted">now: ${escapeHtml([entry.augments_label, entry.current].filter(Boolean).join(" · ") || `plain ${entry.name}`)}</span><button type="button" class="tt-tool" data-close>✕</button></div>`
    + `<p class="tt-muted tt-items-note">Choose your options here, then use the ability to aim it. Choices are saved when you fire; costs are paid when the ability applies.</p>`
    + augments + talents + choices + (modifiers ? `<h3 class="tt-items-sub">On-hit talents</h3><p>Turn talents on to apply them when this attack hits. Choices are free and stay until changed.</p><ul class="tt-items-list">${modifiers}</ul>` : "");
  for (const element of panel.querySelectorAll("[data-button-id]")) {
    const local = [...entry.options, ...(entry.choices || []), ...entry.augments].find(row => row.button_id === element.dataset.buttonId);
    markActive(element, local ? Boolean(local.active ?? local.on) : app.state.button_states?.[menu.actor_id]?.[element.dataset.buttonId]?.active);
  }
  panel.querySelector("[data-close]").addEventListener("click", () => { app.showShape = null; renderShapePanel(); renderActionBar(); });
  panel.querySelectorAll("[data-act]").forEach(button => button.addEventListener("click", () => { void useOptionCandidate(button.dataset.act); }));
  panel.querySelectorAll("[data-option-activation]").forEach(button => button.addEventListener("click", () => { void useOptionActivation(button.dataset.optionActivation); }));
  panel.querySelectorAll("[data-modifier-choice]").forEach(select => select.addEventListener("change", () => {
    if (select.value) void useOptionCandidate(select.value);
  }));
}

async function act(candidateId, route = null) {
  const composition = app.composedAction?.menu.actions.some(g => g.options.some(o => o.candidate_id === candidateId))
    ? app.composedAction : null;
  // Assisted confirmations and list/sheet buttons also arrive here directly.
  // A saved candidate cannot authorize ignoring a newer local configuration.
  if (!composition && !route && app.optionDraft?.dirty) {
    if (chooseLocalOption(candidateId)) return true;
    const group = app.menu?.actions.find(g => g.options.some(o => o.candidate_id === candidateId));
    if (group && !group.source_definition_id?.startsWith('system:')) {
      const option = group.options.find(o => o.candidate_id === candidateId);
      return useGroup(group, {preferTargets: option.target_ids || []});
    }
  }
  const choice = {cancelled: false};
  // A newer press retires an unsent preparation only; a sent action is always applied.
  if (app.busy || app.abilityChoice?.submitted) { toast("Still working on your last action…"); return false; }
  if (app.abilityChoice) cancelAbilityChoice();
  choice.cancellation = new Promise(resolve => { choice.stop = () => resolve({status: "CANCELLED"}); });
  app.abilityChoice = choice;
  document.body.classList.add("is-ability-choice");
  hint("Preparing your ability…", () => cancelAbilityChoice());
  try {
  // Retain the exact player's target/options while refreshing a settings-only
  // version change. Never guess a different target if the fight also moved on.
  const oldMenu = app.state?.menu;
  const choiceMatchId = app.matchId;
  const oldGroup = oldMenu?.actions?.find(g => g.options?.some(o => o.candidate_id === candidateId));
  const oldOption = oldGroup?.options.find(o => o.candidate_id === candidateId);
  const oldMove = oldMenu?.moves?.find(o => o.candidate_id === candidateId);
  const nativeDraft = !composition && (oldGroup?.source_definition_id?.startsWith('system:') || oldMove) ? app.optionDraft : null;
  const draftRound = app.state?.presentation?.round_number;
  // A setting choice (a shape row) changes only the saved selection: ask for the complete committed state in the
  // same response, so the menu needs no second read, and keep the live bar when the controls are unchanged.
  const freeChoice = !composition && !route && !oldMove && Boolean(oldGroup?.shape) && !oldGroup.source_definition_id?.startsWith("system:");
  const versionBefore = oldMenu?.state_version;
  try { await Promise.race([synchronizePresets(), choice.cancellation]); }
  catch (error) { toast(error.message, true); return false; }
  if (choice.cancelled || app.abilityChoice !== choice || app.matchId !== choiceMatchId) return false;
  // The view can go covered during that await (a failed seat read reconciles the viewer).
  // Recheck here, immediately before the request, so nothing reaches /act unseen.
  if (refuseCoveredView()) return false;
  if (versionBefore !== app.state?.menu?.state_version) {
    if (composition) { toast("The fight changed. Choose your options again.", true); return false; }
    if (oldMenu?.actor_id !== app.state?.menu?.actor_id) {
      toast("The fight changed. Choose your action again.", true); return false;
    }
    if (candidateId === oldMenu?.end_turn) candidateId = app.state?.menu?.end_turn;
    else if (oldMove) {
      const move = app.state?.menu?.moves?.find(o => JSON.stringify(o.destination) === JSON.stringify(oldMove.destination));
      if (!move || (route && (!move.can_jump_down || JSON.stringify(move.path) !== JSON.stringify(oldMove.path)))) {
        toast("The fight changed. Choose where to move again.", true); return false;
      }
      candidateId = move.candidate_id;
    }
    else {
      const matches = app.state?.menu?.actions?.find(g => g.source_definition_id === oldGroup?.source_definition_id)?.options.filter(o =>
        ["target_ids", "option_ids", "destination", "label"].every(k => JSON.stringify(o[k]) === JSON.stringify(oldOption?.[k]))) || [];
      if (matches.length !== 1) { toast("The fight changed. Choose the attack and its target again.", true); return false; }
      candidateId = matches[0].candidate_id;
    }
  }
  if (app.busy) { toast("Still working on your last action…"); return false; }
  if (!app.state?.menu) return false;
  const menu = composition?.menu || app.state.menu;
  // The disposable composition menu has already advanced for its settings.
  // Invalidate against the original live decision, not that projected version;
  // keep the projected menu below for preparing and submitting the candidate.
  const liveDecision = composition?.request || menu;
  choice.binding = {actor_id: liveDecision.actor_id, decision_id: liveDecision.decision_id, state_version: liveDecision.state_version};
  app.busy = true;
  choice.working = true;
  refreshSequence++;
  document.body.classList.add("is-working");  // a slow step shows as working, not as a click that did nothing
  try {
    const actionMatchId = app.matchId;
    const base = `/api/tabletop/matches/${enc(actionMatchId)}`;
    let endpoint = 'act';
    let actionRequest = {candidate_id: candidateId, decision_id: menu.decision_id, state_version: menu.state_version};
    if (composition) actionRequest.composition = composition.request;
    if (freeChoice) actionRequest.menu_read = menuReadFor(actionMatchId);
    const deferred = menu.moves?.find(row => row.candidate_id === candidateId && row.deferred_route);
    if (deferred) {
      // Like the Jump down quote, Cancel releases this preview at once; a late answer is ignored.
      const quote = await Promise.race([api(`${base}/movement-destination/preview`, {body: {
        decision_id: menu.decision_id, state_version: menu.state_version, actor_id: menu.actor_id,
        destination: deferred.destination, movement_mode: deferred.movement_mode,
      }}), choice.cancellation]);
      if (choice.cancelled || app.abilityChoice !== choice) return false;
      if (refuseCoveredView()) return false;
      if (app.matchId !== actionMatchId || app.state?.menu?.decision_id !== menu.decision_id
          || app.state?.menu?.state_version !== menu.state_version) {
        toast('The fight changed. Choose where to move again.', true); return false;
      }
      if (!quote.candidate?.candidate_id || !confirmRouteQuote(deferred, quote)) return false;
      deferred.path = quote.candidate.canonical_path;
      deferred.route_candidate_id = quote.candidate.candidate_id;
      endpoint = 'movement-path/commit';
      actionRequest = {...actionRequest, candidate_id: quote.candidate.candidate_id,
        actor_id: menu.actor_id, waypoints: deferred.path, movement_mode: deferred.movement_mode};
      if (app.pendingMove) app.pendingMove.path = deferred.path;
      renderHighlights();
    }
    if (route) {
      const move = menu.moves?.find(row => row.candidate_id === candidateId);
      if (route.movement_mode !== 'jump_down' || !move?.can_jump_down) {
        throw new Error('Choose an available Jump down route again.');
      }
      const quoteRequest = {decision_id: menu.decision_id, state_version: menu.state_version,
        actor_id: menu.actor_id, waypoints: move.path, movement_mode: 'jump_down'};
      const quote = await Promise.race([
        api(`${base}/movement-path/preview`, {body: quoteRequest}), choice.cancellation,
      ]);
      if (choice.cancelled) return false;
      // Quoting is read-only, but the local view or active decision can change
      // during the round trip. Recheck before committing any deliberate fall.
      if (refuseCoveredView()) return false;
      if (app.matchId !== actionMatchId || app.state?.menu?.decision_id !== menu.decision_id
          || app.state?.menu?.state_version !== menu.state_version) {
        toast('The fight changed. Choose where to jump down again.', true); return false;
      }
      if (!quote.candidate?.candidate_id) throw new Error('The fight could not confirm this Jump down route. Choose it again.');
      endpoint = 'movement-path/commit';
      actionRequest = {...quoteRequest, candidate_id: quote.candidate.candidate_id};
    }
    hint("Loading ability choices…", () => cancelAbilityChoice());
    const result = await withReactions(async reactions => {
      if (choice.cancelled) return {status: "CANCELLED"};
      // Gather area/augment/variant choices without reserving an action. A
      // reload has nothing to resume until the player actually submits it. Once submitted, answers go straight to the commit.
      if (endpoint === 'act' && !choice.submitted) {
        const prepared = await api(`${base}/prepare`, {body: {
          ...actionRequest, after: app.lastSequence, reactions,
        }});
        if (choice.cancelled) return {status: "CANCELLED"};
        if (prepared.status !== "PREPARED") return prepared;
      }
      // Submitting is the point of no return: the table reserves the action from here. Cancel is no longer
      // offered, and whatever the server answers (commit, or a further choice) is always applied below.
      choice.submitted = true;
      hint("Applying your ability…", null);
      return api(`${base}/${endpoint}`, {body: {
        ...actionRequest, after: app.lastSequence, reactions,
      }});
    }, choice);
    if (result.status === "CANCELLED") {
      // The final submission may have saved its standing choices before a reaction was declined. Retire that draft
      // rather than replaying toggles.
      if (composition) await refresh();
      else if (result.state) render(result.state);
      return false;
    }
    if (app.matchId !== actionMatchId) return false;
    refreshSequence++;
    if (freeChoice && result.status === "COMMITTED" && result.state?.menu) {
      // Keep the menu on screen while its events play; the busy flag blocks a second press meanwhile.
      await playEvents(result.events, {finalizePause: true});
      if (app.matchId !== actionMatchId) return false;
      render(result.state, {keepBar: true});
      gmNotice(result.events?.events || []);
      return true;
    }
    app.menu = null;
    app.state = {...app.state, menu: null};
    invalidateTargeting();
    renderActionBar();
    await playEvents(result.events, {finalizePause: true});
    if (app.matchId !== actionMatchId) return false;
    if (result.status === "COMMITTED") {
      if (nativeDraft) app.pendingOptionDraft = {draft: nativeDraft, matchId: actionMatchId, round: draftRound};
      render(result.state);
    } else await refresh();
    gmNotice(result.events?.events || []);
    return true;
  } catch (error) {
    if (choice.cancelled) return false;
    if (!await handleUnavailableFight(error)) {
      toast(error.message, true);
      await refresh();
    }
    return false;
  } finally {
    if (app.abilityChoice === choice) {
      app.busy = false;
      document.body.classList.remove("is-working");
    }
  }
  } finally {
    if (app.abilityChoice === choice) {
      app.abilityChoice = null;
      document.body.classList.remove("is-ability-choice");
      if (!app.targeting && !app.mapPick && !app.listPick) hint(null);
    }
  }
}

// An ability the fight runs nothing for (owner 2026-09-28: "when i click them nothing happens"): its GM note stays out of
// the log unless details are on, so a player's own use of one says so on screen.
function gmNotice(events) {
  const notice = riderNotice(events, NOISE);
  if (notice) toast(notice);
}

async function autoStep() { return play(); }

async function play() {
  if (app.automaticRun || app.busy || !app.matchId || !app.state
      || app.state.pending_action || app.menu || presentation()?.terminal) return false;
  const current = actorById(presentation()?.current_actor_id);
  if (current?.active !== false && isManualActor(current)) return false;
  const matchId = app.matchId;
  const run = {matchId};
  app.automaticRun = run;
  app.playing = true;
  renderActionBar();
  try {
    const result = await automaticTurn({
      start: () => api(`/api/tabletop/matches/${enc(matchId)}/automatic-run`, {body: {}}),
      observe: () => api(`/api/tabletop/matches/${enc(matchId)}/seat-status`),
      wait: sleep,
      current: () => app.matchId === matchId && app.automaticRun === run,
      status: value => { app.seatStatus = value; app.userPaused = Boolean(value.paused); },
    });
    if (result?.status === "ERROR") {
      app.userPaused = true;
      toast(result.text, true);
    }
    return !!result && result.status !== "ERROR";
  } catch (error) {
    app.userPaused = true; // an uncertain command is never resubmitted
    if (!await handleUnavailableFight(error)) toast(error.message, true);
    return false;
  } finally {
    if (app.automaticRun === run) {
      app.automaticRun = null;
      app.playing = false;
      if (app.matchId === matchId) await refresh();
    }
  }
}

// Owner 2026-09-25: "for the ai i have to hit step for each action it does, it should be automatic."
// In a fight with a fighter you play, AI turns run by themselves; Pause holds them until your next turn.
// All-AI fights still wait for Play, so opening a saved fight just shows it.
function hasManualFighter() {
  return (presentation()?.actors || []).some(actor => actor.active !== false && isManualActor(actor));
}

// Whether this view has an eligible fighter, including an inactive bound owner.
// An empty result never grants Game Master visibility.
function playsAFighterHere() {
  return (presentation()?.actors || []).some(actor => isOwnedActor(actor));
}

function scheduleAutoPlay() {
  if (serverDriving(app.seatStatus)) return;  // the server honours this fight's persisted Pause
  if (app.menu) app.userPaused = false;
  setTimeout(() => {
    if (!serverDriving(app.seatStatus) && !app.userPaused && !app.playing && !app.busy && app.matchId && app.state && !app.state.pending_action && !app.menu
        && !presentation()?.terminal && ((automaticSlot(actorById(presentation()?.current_actor_id))
          && isManualActor(actorById(presentation()?.current_actor_id)))
          || (!isManualActor(actorById(presentation()?.current_actor_id)) && hasManualFighter()))) play();
  }, 60);
}

// The ids of creatures in the browser's remembered squares, kept beside the memory (same match, viewer and fog).
function tokenIdsKey(matchId, fog) { return `tt-fog-token-ids:${matchId}:${viewerStore.viewId}:${fog}`; }
function rememberedTokenIds(matchId, fog) {
  try {
    const ids = JSON.parse(preferenceStorage?.getItem(tokenIdsKey(matchId, fog)) ?? "null");
    return Array.isArray(ids) ? ids.slice(0, 400).map(String) : null;
  } catch { return null; }
}

// The state read a free choice's /act answer must match: the same fog audience and compact transport as readTableState.
function menuReadFor(matchId, fog = app.fog) {
  const read = {fog: true, compact: true};
  const binding = viewerStore.read(matchId);
  if (binding?.role === "player") {
    if (fog === "own") read.fog_view = "own";
    read.fog_actor_ids = [...(binding.actor_ids || [])];
  }
  return read;
}

async function readTableState(matchId, fog = app.fog) {
  // Always retain server perception, even for an explicit GM. A local change
  // back to a player can then mask the cached state immediately, before any await.
  const query = new URLSearchParams({fog: "true"});
  // In the common own-view mode, the server only needs eyes owned by this
  // screen. It expands the bound fighters to their active summons and applies
  // the existing fallen-fighter ally fallback from the same fight state.
  const binding = viewerStore.read(matchId);
  if (binding?.role === "player") {
    // The binding is also the private information audience, independently of
    // which eyes the player chooses for the map geometry.
    if (fog === "own") query.set("fog_view", "own");
    for (const actorId of binding.actor_ids || []) query.append("fog_actor_ids", actorId);
  }
  // Creatures this browser remembers in the fight. The server answers only which of them are still in it, so
  // no other creature's id is ever published. Absent until the browser has recorded a snapshot (then nothing is purged).
  const remembered = rememberedTokenIds(matchId, fog);
  if (remembered) for (const id of remembered) query.append("remembered_ids", id);
  // Only this desktop renderer expands compact route grids; every other client keeps full moves.
  const path = compactStatePath(`/api/tabletop/matches/${enc(matchId)}/state?${query}`);
  try { return await api(path); }
  catch (error) {
    if (error.status !== 409 || error.code !== "COMBAT_CONTENT_NOT_READY") throw error;
    await sleep(250);
    return api(path);  // read only; never replay an action after a failed response
  }
}

// Observing an unchanged human menu must not cancel an in-progress target pick.
// Compare the whole public state so changes without an event (prompts, seats,
// sight or a suspended action) still get the normal render path.
function renderObservedState(state) {
  if (reconcileViewerIdentity() && app.state) renderTokens();
  // Compare against the state as received, not the movement-expanded copy render() stored.
  const shown = app.receivedState?.shown === app.state ? app.receivedState.received : app.state;
  if (app.menu?.manual && app.state && JSON.stringify(state) === JSON.stringify(shown)) {
    // Keep the player's rules, focus, scroll and target pick intact. Playback
    // is separate from combat state; only its existing status text can change.
    const status = $("#ttActionBar")?.querySelector(".tt-ab-who .tt-muted");
    const text = serverDriving(app.seatStatus) && app.seatStatus.paused
      ? "Your turn · AI turns Paused" : "Your turn";
    if (status && status.textContent !== text) status.textContent = text;
    return;
  }
  render(state);
}

// The two read endpoints are independent. If a commit lands between them, fetch
// only the missing tail before rendering its state, and leave later events for
// the next poll. Usually their cursors agree: no extra read or delay is added.
async function eventsThroughState(events, state, matchId) {
  // A broken/older feed must never prevent displaying the authoritative snapshot.
  // Do not animate unsequenced rows repeatedly or invent their journal positions.
  if (!Number.isSafeInteger(events.last_sequence) || !Array.isArray(events.events)
      || events.events.some(row => !Number.isSafeInteger(row.event_sequence))) {
    return {events: [], dice: [], last_sequence: state.last_sequence};
  }
  if (state.last_sequence <= (events.last_sequence || 0)) return events;
  const tail = await api(`/api/tabletop/matches/${enc(matchId)}/events?after=${events.last_sequence || 0}`);
  if (!Number.isSafeInteger(tail.last_sequence) || !Array.isArray(tail.events)
      || tail.events.some(row => !Number.isSafeInteger(row.event_sequence))) {
    return {...events, last_sequence: state.last_sequence};
  }
  return {...events, events: [...(events.events || []), ...(tail.events || [])]
    .filter(row => row.event_sequence <= state.last_sequence),
    dice: [...(events.dice || []), ...(tail.dice || [])], last_sequence: state.last_sequence};
}

async function refresh({observe = false, choiceRead = null} = {}) {
  if (!app.matchId || app.automaticRun) return;
  if (observe && app.optionDraft && !app.waitingReaction) return pollTable();
  // Do not supersede a slow on-demand menu read on every poll tick.
  if (observe && deferredMenuRead?.matchId === app.matchId) return deferredMenuRead.promise;
  const request = ++refreshSequence;
  const matchId = app.matchId, fog = app.fog;
  const isCurrent = () => !choiceRead?.cancelled && request === refreshSequence && app.matchId === matchId && app.fog === fog;
  try {
    const events = await api(`/api/tabletop/matches/${enc(matchId)}/events?after=${app.lastSequence}`);
    if (!isCurrent()) return;
    // Read the state after its event prefix, so a concurrent commit cannot make
    // that prefix newer than the snapshot we are about to display. Same two reads.
    const [state] = await Promise.all([readTableState(matchId, fog), loadSeats()]);
    if (!isCurrent()) return;
    const complete = await eventsThroughState(events, state, matchId);
    if (!isCurrent()) return;
    await playEvents(complete, {fast: true});
    if (!isCurrent()) return;
    if (app.waitingReaction?.changed(state)) {
      app.waitingReaction.stop(state);
    }
    if (observe) renderObservedState(state);
    else render(state);
    resumeServerPrompt(state);
  } catch (error) {
    if (isCurrent() && !await handleUnavailableFight(error, matchId)) toast(error.message, true);
  }
}

async function setControl(actorId, mode) {
  if (app.busy) { toast("Still working on your last action…"); return; }
  const actor = actorById(actorId);
  if (!actor?.primary_combatant) return;
  try {
    if (isModelSeat(app.seatStatus, actorId)) {
      // Taking a fighter back from a model is a seat change, so the server stops driving it.
      await api(`/api/tabletop/matches/${enc(app.matchId)}/seat`, {body: {actor_id: actorId, control: ["MANUAL", "SUGGESTED"].includes(mode) ? "MANUAL" : "AI"}});
      await loadSeats();
      if (mode === "SUGGESTED") await api(`/api/combat/matches/${enc(app.matchId)}/controller-mode`, {body: {actor_id: actorId, controller_mode: mode}});
    } else {
      await api(`/api/combat/matches/${enc(app.matchId)}/controller-mode`, {body: {actor_id: actorId, controller_mode: mode}});
    }
    toast(`${actorById(actorId)?.display_name} is now played by ${mode === "SUGGESTED" ? "you with ranked suggestions" : mode === "MANUAL" ? "you" : "the AI"}.`);
    await refresh();
    // A fighter handed to Local AI on its current turn should not wait for Play
    // or another refresh cycle before the AI starts acting.
    if (mode === "LOCAL_AUTO" && presentation()?.current_actor_id === actorId) await autoStep();
  } catch (error) { toast(error.message, true); }
}

// Owner playtest 2026-10-03 23:01: the pop-out sheet was told "It is not Tabik Damu's turn to act."
// while the table was waiting for that same fighter to choose where to centre a Darkness. This
// window's cached state cannot tell a finished turn from an open prompt, a window that is simply
// behind, or a fight still loading, so name the real reason in plain words.
function refusalFor(actorId) {
  if (!app.matchId) return "No fight is open. Open a fight from Fights.";
  const name = actorById(actorId)?.display_name || "that character";
  if (app.pendingChoice || app.state?.pending_action) return pendingChoiceText();
  const current = presentation()?.current_actor_id;
  if (current && current !== actorId) {
    const whose = actorById(current)?.display_name;
    return whose ? `It is ${whose}'s turn to act, not ${name}'s. Wait until it is your turn.`
                 : `It is not ${name}'s turn to act.`;
  }
  if (!app.state) return "The table is still loading this fight. Try again in a moment.";
  return "The table has moved on since this window last updated. Press the action again.";
}

// Buttons from the action bar or the pop-out sheet; combos run their steps in order.
async function runButton(button, actorId, reread = false) {
  try { await synchronizePresets(); }
  catch (error) { return {ok: false, message: error.message}; }
  if (app.busy) return {ok: false, message: "Still working on your last action…"};
  const menu = app.menu;
  const actor = actorById(actorId);
  if (actor && !isManualActor(actor)) {
    return {ok: false, message: `${actor.display_name} is played by the AI - take control with the You/AI switch.`};
  }
  if (!menu || menu.actor_id !== actorId) {
    // The table window and every pop-out sheet hold their own copy of the fight, so this one can be
    // simply behind. Re-read it once before refusing, so a stale window is not told its fighter
    // may not act. The retry is bounded, so a real refusal still names its real reason.
    if (!reread) { await refresh(); return runButton(button, actorId, true); }
    return {ok: false, message: refusalFor(actorId)};
  }

  if (button.kind === "combo") {
    for (const step of button.steps || []) {
      if (step.roll) { await localRoll(actorId, step.label || button.label, step.roll); continue; }
      const sheet = await sheetFor(actorId);
      const inner = (sheet?.buttons || []).find(row => row.id === step.button);
      if (!inner) return {ok: false, message: `Unknown step ${step.button}`};
      const result = await runButton(inner, actorId);
      if (!result.ok) return {ok: false, message: `${button.label} stopped at ${inner.label}: ${result.message}`};
    }
    return {ok: true, message: `${button.label} done`};
  }
  if (button.combat?.end_turn) {
    return menu.end_turn && (await actOnce(menu.end_turn)) ? {ok: true, message: "Turn ended"} : {ok: false, message: "Cannot end the turn now"};
  }
  if (button.shape && button.variant_of) {
    // A talent for an area, clicked on the sheet (owner 2026-09-27: "hitting the pure darkness numbing darkness action
    // didnt do anything"): choose it unless it already is, then aim the ability it shapes.
    //
    // Only area TALENTS arrive here. An augment is a different payload -- combat/tabletop.py _augment_button gives it
    // "augment: true" and no "shape" -- so it never matches this guard and goes down the ordinary action path below,
    // where its own free toggle candidate is submitted. Reading the "augments" list here as well would be a second,
    // unreachable interpretation of the same press.
    const base = button.variant_of.replace(/^act:/, "");
    const entry = draftOptionRows(actorId).find(row => row.base === base);
    const option = entry?.options.find(row => JSON.stringify(row.talents) === JSON.stringify(button.shape.talents));
    if (option && !option.active && !(option.candidate_id && (chooseLocalOption(option.candidate_id) || await act(option.candidate_id)))) {
      return {ok: false, message: `Could not choose ${button.modifier?.name || button.label} now`};
    }
    const sheet = await sheetFor(actorId);
    const baseButton = (sheet?.buttons || []).find(row => row.id === button.variant_of);
    return baseButton ? runButton(baseButton, actorId) : {ok: true, message: `${button.modifier?.name || button.label} chosen`};
  }
  const source = button.combat?.source_definition_id;
  const group = menu.actions.find(row => row.source_definition_id === source) || menu.actions.find(row => row.alias_of === source)
    || (app.optionDraft?.dirty && source ? {source_definition_id: source, label: button.label, options: []} : null);
  if (!group) return {ok: false, message: reasonFor(actorById(actorId), button)};
  const done = await useGroup(group, {preferTargets: preferredTargets()});
  return done ? {ok: true, message: `${button.label} used`} : {ok: false, message: app.busy ? "Still working on your last action…" : `${button.label} not used`};
}

async function localRoll(actorId, label, expression) {
  if (!app.rollLocal) return;
  try {
    const result = app.rollLocal(expression);
    if (app.dice && app.diceOn) app.dice.roll(result.groups, {label, modifier: result.modifier, total: result.total, kind: "check", discarded: result.discarded});
    appendTableLine(`${actorById(actorId)?.display_name || "Table"} rolled ${label}: ${result.text || result.total}`);
  } catch (error) { toast(`Roll failed: ${error.message}`, true); }
}

// ------------------------------------------------------------------ events: feed, paths, dice, damage
function feedClass(row) {
  const type = row.event_type;
  if (type === "DAMAGE_COMMITTED") return "is-damage";
  if (/_ROLLED$/.test(type)) return "is-roll";
  if (type === "HEALING_APPLIED") return "is-heal";
  if (type === "GM_RIDER") return "is-gm";
  if (type === "MATCH_ENDED" || type === "VICTORY_DECLARED") return "is-end";
  return "";
}

function appendFeed(rows) {
  const feed = $("#ttFeed");
  const detail = $("#ttFeedDetail").checked;
  for (const row of mapObjectFeed(rows, detail)) {
    if (row.event_type === "INTENT_ACCEPTED") {
      const item = document.createElement("li");
      item.className = "is-step";
      item.textContent = row.summary;
      feed.appendChild(item);
      continue;
    }
    if (!detail && NOISE.has(row.event_type) && !["RESOURCE_SPENT", "GM_RIDER"].includes(row.event_type)) continue;
    const item = document.createElement("li");
    item.className = feedClass(row);
    item.dataset.type = row.event_type;
    const text = String(row.summary || "");
    if (text.length > 240) {  // long GM riders: first line, click for the rest
      item.textContent = `${text.slice(0, 220)}… (more)`;
      item.title = "Click to show the full text";
      item.style.cursor = "pointer";
      item.addEventListener("click", () => { item.textContent = text; item.style.cursor = ""; }, {once: true});
    } else item.textContent = text;
    if (row.hover) item.title = row.hover;
    if (/_ROLLED$/.test(row.event_type)) {
      // Owner 2026-10-15 04:39Z: a visible Advantage/Disadvantage label whose hover
      // lists the reasons underneath, one line per source, cancellation explained.
      const payload = row.raw?.payload || {};
      const sources = Array.isArray(payload.mode_sources) ? payload.mode_sources : null;
      const mode = payload.mode || "NORMAL";
      item.title = sources ? rollModeHover(mode, sources) : text;
      if (sources) {
        if (mode !== "NORMAL") item.textContent = text.replace(/\s*—\s*with (Advantage|Disadvantage)( \(.+\))?$/, "");
        item.prepend(rollModeLabel(mode, sources), document.createTextNode(" "));
      }
    }
    feed.appendChild(item);
  }
  settleFeed(rows.length);
}

function appendTableLine(text) {
  const item = document.createElement("li");
  item.className = "is-table";
  item.textContent = text;
  $("#ttFeed").appendChild(item);
  settleFeed(1);
}

// The log follows new entries like a chat (owner 2026-09-27: "Id like to be able to scroll up on the feed and not be
// brought down to the bottom automatically ... a small button that hovers over the bottom of the feed to push to have it
// go back down to the auto follow on the new updates ... much like how twitchs chat works").
function settleFeed(added) {
  const feed = $("#ttFeed");
  // Keep what you are reading where it is (owner 2026-09-28: "it still drops down just not all the way"): the first line
  // on screen stays at the same height while old lines are trimmed. (Subtracting the trimmed height doubled the
  // browser's own scroll anchoring once the log passed 600 lines.)
  const anchor = !feedFollow.on && [...feed.children].find(li => li.offsetTop + li.offsetHeight > feed.scrollTop);
  const offset = anchor ? anchor.offsetTop - feed.scrollTop : 0;
  while (feed.children.length > 600 && feed.firstChild !== anchor) feed.firstChild.remove();
  if (feedFollow.on) {
    feed.scrollTop = feed.scrollHeight;
    return;
  }
  if (anchor) feed.scrollTop = anchor.offsetTop - offset;
  feedFollow.unseen += added;
  const jump = $("#ttFeedJump");
  jump.textContent = `↓ ${feedFollow.unseen} new ${feedFollow.unseen === 1 ? "entry" : "entries"}`;
  jump.hidden = false;
}
function resumeFeed() {
  const feed = $("#ttFeed");
  feedFollow.on = true;
  feedFollow.unseen = 0;
  $("#ttFeedJump").hidden = true;
  feed.scrollTo({top: feed.scrollHeight, behavior: "smooth"});
}
$("#ttFeed").addEventListener("scroll", () => {
  const feed = $("#ttFeed");
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 24;
  if (atBottom) {
    feedFollow.on = true;
    feedFollow.unseen = 0;
    $("#ttFeedJump").hidden = true;
  } else feedFollow.on = false;
}, {passive: true});
$("#ttFeedJump").addEventListener("click", resumeFeed);

// All callers (actions, AI and refresh) share one playback queue. Overlapping event
// responses are filtered only when their turn begins, after the previous run finishes.
function playEvents(result, options = {}) {
  const matchId = app.matchId;
  const next = (app.eventPlayback || Promise.resolve()).then(() => {
    if (app.matchId === matchId) return playEventBatch(result, options);
  });
  app.eventPlayback = next.catch(() => {});
  return next;
}

async function playEventBatch(result, {fast = false, finalizePause = false} = {}) {
  if (!result) return;
  const matchId = app.matchId;
  const events = (result.events || []).filter(row => row.event_sequence == null || row.event_sequence > app.lastSequence);
  appendFeed(events);
  const dice = new Map((result.dice || []).map(row => [row.roll_id, row]));
  const positions = new Map(actors().map(actor => [actor.entity_id, actor.position]));
  let rolled = 0;
  for (const row of events) {
    if (app.matchId !== matchId) return;
    const payload = row.raw?.payload || {};
    if (row.event_type === "MOVEMENT_COMMITTED" && Array.isArray(payload.path)) {
      // The fight has committed this move, so it is drawn once along the path it recorded: a steady walk, or a blink
      // for a teleport. Nothing moves before this, so there is no jump and no replay (owner 2026-10-03).
      // Hold the event's destination until an equally recent state arrives. Board
      // animation owns intermediate frames; selection/hover renders cannot rewind it.
      app.movePositions ||= new Map();
      const pause = app.movePositions.get(row.actor_id);
      // Keep the boundary across the entire replay prefix, not just its first
      // movement event. Event/index identity also distinguishes repeated squares
      // and altitude; never infer an occurrence from x/y.
      const cursor = pause?.pause && pause.cursor;
      if (pause?.pause && (!cursor || row.event_sequence < cursor.event_sequence
          || (row.event_sequence === cursor.event_sequence && cursor.path_index >= payload.path.length - 1))) {
        if (payload.destination) positions.set(row.actor_id, payload.destination);
        continue;
      }
      const path = cursor && row.event_sequence === cursor.event_sequence
        ? payload.path.slice(cursor.path_index) : payload.path;
      app.movePositions.set(row.actor_id, {position: payload.destination || payload.path.at(-1),
        sequence: row.event_sequence ?? result.last_sequence});
      await board.animateMove(row.actor_id, path, {stepMs: fast ? Math.round(60 * (app.speed ?? 0.7) / 0.7) : 110, teleport: Boolean(payload.teleport)});
      if (payload.destination) positions.set(row.actor_id, payload.destination);
    } else if (row.roll_id && dice.has(row.roll_id) && app.dice && app.diceOn && rolled < (fast ? 2 : 4)) {
      const roll = dice.get(row.roll_id);
      dice.delete(row.roll_id);
      rolled += 1;
      const natural = roll.natural;
      const meta = {label: roll.label, modifier: roll.modifier, total: roll.total, kind: roll.kind, discarded: roll.discarded,
                    critical: roll.kind === "attack" && natural === 20, fumble: roll.kind === "attack" && natural === 1,
                    mode: roll.mode || "NORMAL", mode_sources: roll.mode_sources || []};
      if (row.event_type === "ATTACK_ROLLED") {
        const from = positions.get(row.actor_id), to = positions.get(row.target_ids?.[0]);
        if (from && to) board.flashLine(from, to, "attack");
      }
      const rolling = app.dice.roll(roll.groups, meta);
      if (!fast) await rolling;
      if (row.event_type === "ATTACK_ROLLED" && payload.provisional_hit === false) {
        const to = positions.get(row.target_ids?.[0]);
        if (to) board.floatText(to.x, to.y, "Miss", "miss");
      }
    } else if (row.event_type === "ATTACK_ROLLED" && payload.provisional_hit === false) {
      const to = positions.get(row.target_ids?.[0]);
      if (to) board.floatText(to.x, to.y, "Miss", "miss");
    }
    if (row.event_type === "DAMAGE_COMMITTED") {
      const to = positions.get(row.target_ids?.[0]);
      if (to) board.floatText(to.x, to.y, payload.hp_damage ? `−${payload.hp_damage}` : "0", payload.hp_damage ? "damage" : "miss");
    } else if (row.event_type === "HEALING_APPLIED") {
      const to = positions.get(row.target_ids?.[0] || row.actor_id);
      if (to) board.floatText(to.x, to.y, `+${payload.amount ?? payload.healed ?? ""}`, "heal");
    }
  }
  if (app.matchId !== matchId) return;
  // Legacy snapshots have no reliable cursor. Hold their pause instead of
  // replaying a guessed prefix; the next committed state supplies the endpoint.
  for (const [id, move] of app.movePositions || []) {
    if (move.pause && (finalizePause || (events.some(row => row.event_type === "MOVEMENT_COMMITTED" && row.actor_id === id)
        && (!move.cursor || result.last_sequence >= move.cursor.event_sequence)))) {
      move.sequence = result.last_sequence ?? app.lastSequence;
    }
  }
  app.lastSequence = Math.max(app.lastSequence, result.last_sequence || 0);
  app.playedSequence = Math.max(app.playedSequence || 0, result.last_sequence || 0);
}

// ------------------------------------------------------------------ sheets over BroadcastChannel
const pendingPresets = new Map();
const presetWaiters = new Map();
const retiredPresetSheets = new Set();
let presetsDirty = false;
function retirePresetSheet(sheetId) {
  if (!sheetId) return;
  retiredPresetSheets.add(sheetId);
  if (pendingPresets.delete(sheetId)) presetsDirty = true;
  for (const waiter of presetWaiters.values()) {
    if (waiter.sheetId === sheetId) waiter({ok: true});
  }
}
function handlePresetMessage(message) {
  // Several live sheets may edit the same character. A hello is not evidence
  // that another window closed; only its explicit close retires that UUID.
  if (message.match_id !== app.matchId) return false;
  if (message.type === "sheet-closed") {
    retirePresetSheet(message.sheet_id);
    return true;
  }
  if (retiredPresetSheets.has(message.sheet_id)) {
    // A closed sheet's HTTP reply may arrive after the replacement opened.
    if (message.type === "settings-saved") presetsDirty = true;
    return message.type.startsWith("settings-");
  }
  if (message.type === "settings-pending") {
    pendingPresets.set(message.sheet_id, {actorId: message.actor_id, matchId: message.match_id}); return true;
  }
  if (message.type === "settings-saved") {
    if (message.ok) presetsDirty = true;
    if (!message.ok || message.unsaved) pendingPresets.set(message.sheet_id, {actorId: message.actor_id, matchId: message.match_id});
    else pendingPresets.delete(message.sheet_id);
    return true;
  }
  if (message.type === "settings-flushed") {
    presetWaiters.get(message.request_id)?.(message); return true;
  }
  return false;
}
async function synchronizePresets() {
  for (const [sheetId, {actorId, matchId}] of pendingPresets) {
    if (matchId !== app.matchId) continue;
    const requestId = crypto.randomUUID();
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { presetWaiters.delete(requestId); reject(new Error("A sheet has unsaved presets. Reopen that sheet and save them before attacking.")); }, 10000);
      const waiter = msg => { clearTimeout(timer); presetWaiters.delete(requestId);
        if (msg.ok) { pendingPresets.delete(sheetId); resolve(); } else reject(new Error(msg.message || "A preset was not saved.")); };
      waiter.sheetId = sheetId;
      presetWaiters.set(requestId, waiter);
      app.channel?.postMessage({type: "settings-flush", actor_id: actorId, sheet_id: sheetId, request_id: requestId, match_id: app.matchId});
    });
  }
  if (presetsDirty) { await refresh(); presetsDirty = false; }
}

function openSheetFor(actorId) {
  const actor = actorById(actorId);
  if (!actor?.primary_combatant) return;
  const project = projectOf(actorId);
  if (!project) { toast("Only Factory characters have a full sheet."); return; }
  const url = `/tabletop/sheet?project=${enc(project)}`;
  const popup = window.open(url, `tt-sheet-${project}`, "popup=yes,width=1280,height=860");
  if (!popup) toast("Your browser blocked the pop-up; allow pop-ups for this page.", true);
}

// The top bar's Characters button: the same pop-out sheet window, opened on the character list so a
// player can reach any saved sheet, in or out of a fight and even for a character not on the map.
function openCharacterList() {
  const popup = window.open("/tabletop/sheet?pick=1", "tt-sheet-characters", "popup=yes,width=1280,height=860");
  if (!popup) toast("Your browser blocked the pop-up; allow pop-ups for this page.", true);
}

function actorMessage(actor) {
  const menu = app.state?.menu;
  const isCurrent = actor.entity_id === presentation()?.current_actor_id && !presentation()?.terminal;
  // The server's own refusals for this menu. A compact/lazy menu lists an action header before its choices are
  // checked, so the header can be in menu.actions while the server already knows it has nothing to offer (a
  // rest-of-the-Attack row after its attacks are spent, say). The sheet greys those rows and shows the reason.
  const reasons = isCurrent ? (app.state?.unavailable_reasons || {}) : {};
  // An augmented variant ("Darkness + Directional Darkness") stands in for its base on the sheet (alias_of), so the base
  // button is usable while an augment is on (owner 2026-09-29: Darkness showed greyed out).
  const legal = isCurrent && menu?.manual ? [...menu.actions.flatMap(group => [`act:${group.source_definition_id}`, ...(group.alias_of ? [`act:${group.alias_of}`] : [])]),
    ...(menu.end_turn ? ["turn:end"] : [])].filter(id => !reasons[id]) : [];
  return {
    type: "actor", actor_id: actor.entity_id, match_id: app.matchId,
    state_version: app.state?.menu?.state_version,
    hp: {current: actor.hit_points.current, maximum: actor.hit_points.maximum, temporary: actor.hit_points.temporary || 0},
    armor_class: actor.defenses?.find(row => row.defense_id === "defense:armor_class")?.value,
    armor_base: actor.armor_base,
    armor_modifiers: actor.armor_modifiers || [],
    // The creature's current Resistances, Vulnerabilities and Immunities with
    // their sources, read from the same defence rows the fight's damage
    // resolution weighs (the Defences card lists them; combat/typed_reactions.py).
    damage_defenses: actor.damage_defenses || null,
    speed_ft: actor.speed_ft,
    fly_speed_ft: actor.fly_speed_ft, altitude_ft: actor.altitude_ft, hover: actor.hover,
    on_roof: actor.on_roof, roof_height_ft: actor.roof_height_ft,
    resources: (actor.resources || []).filter(row => !String(row.resource_id).startsWith("resource:uses.")),
    // Same filter, names and colours as the map's hover card (owner 2026-09-29: the sheet showed "Shaping" and every
    // condition red; buffs green, debuffs red).
    conditions: (actor.conditions || []).filter(shownCondition).map(row => ({
      condition_id: row.condition_id, display_name: row.display_name || row.condition_id, tone: conditionTone(row), text: conditionText(row)})),
    turn: {is_current: isCurrent, manual: isManualActor(actor), action: Boolean(actor.turn_state?.action), bonus_action: Boolean(actor.turn_state?.bonus_action),
           reaction: Boolean(actor.turn_state?.reaction), movement_ft: actor.movement_remaining_ft},
    // The table's one open choice, so the sheet tells the player what the table is waiting for
    // instead of leaving a button that looks dead (owner playtest 2026-10-03 23:01). null once the
    // choice is answered, cancelled, replaced or lost with the fight; "prompt" is the plain phrase
    // the sheet reads out (sheet.js renderLive).
    pending_choice: app.pendingChoice || (app.state?.pending_action ? {kind: "question"} : null),
    legal_button_ids: legal,
    unavailable_reasons: reasons,
    // Physical weapon copies still carried (drawn or stowed), so the sheet groups
    // one row per weapon kind and its count falls when a copy is thrown.
    weapon_copies: Array.isArray(actor.weapon_copies) ? actor.weapon_copies : [],
    button_states: sheetButtonStates(actor.entity_id),
    attack_modifier_rows: (app.state?.shapes?.[actor.entity_id] || []).flatMap(entry => entry.modifiers || []),
  };
}

// Sheet Active marks for the creature whose option draft is open. Other creatures,
// no draft, or a draft for an older decision all keep the server's saved states.
function sheetButtonStates(actorId) {
  const server = app.state?.button_states?.[actorId] || {};
  if (!app.optionDraft?.matches(app.menu, app.matchId) || app.optionDraft.actorId !== actorId) return server;
  return overlayButtonStates(server, draftButtonStates(app.optionDraft, (app.state?.shapes || {})[actorId] || []));
}

function broadcastDraftStates(actorId = app.optionDraft?.actorId) {
  if (!app.channel || !app.state || !actorId) return;
  app.channel.postMessage({type: "draft-states", actor_id: actorId, match_id: app.matchId, button_states: sheetButtonStates(actorId)});
}

function broadcastActors() {
  if (!app.channel || !app.state) return;
  for (const actor of actors()) app.channel.postMessage(actorMessage(actor));
}

app.channel?.addEventListener("message", async event => {
  const message = event.data || {};
  if (handlePresetMessage(message)) return;
  if (message.type === "sheet-hello") {
    const actor = actorById(message.actor_id);
    if (actor) app.channel.postMessage(actorMessage(actor));
  } else if (message.type === "button" && message.button) {
    const result = await runButton(message.button, message.actor_id);
    app.channel.postMessage({type: "result", actor_id: message.actor_id, button_id: message.button_id, ok: result.ok, message: result.message});
    if (!result.ok) toast(result.message, true);
  } else if (message.type === "roll" && actorById(message.actor_id)) {
    appendTableLine(`${actorById(message.actor_id).display_name} rolled ${message.label}: ${message.result?.total}`);
  }
});

// ------------------------------------------------------------------ always-on-top mini sheet (Document Picture-in-Picture)
async function openPip() {
  if (!currentViewer().ready) { openViewerPicker(); return; }
  if (!("documentPictureInPicture" in window)) {
    toast("This browser cannot keep a window on top; opening the full sheet instead.");
    const id = app.menu?.actor_id || [...app.selected].at(-1);
    if (id) openSheetFor(id);
    return;
  }
  if (app.pip && !app.pip.closed) { app.pip.focus(); return; }
  const pip = await window.documentPictureInPicture.requestWindow({width: 440, height: 660});
  app.pip = pip;
  for (const link of document.querySelectorAll('link[rel="stylesheet"]')) {
    const copy = pip.document.createElement("link");
    copy.rel = "stylesheet";
    copy.href = link.href;
    pip.document.head.appendChild(copy);
  }
  pip.document.title = "Tianxia — on top";
  pip.document.body.className = "tt-app tt-pip";
  copyAppearance(pip.document);
  pip.document.body.innerHTML = `<div class="tt-pip-root"></div>`;
  installGlossary(pip.document);
  // The pop-out has its own document, so it gets its own card from the same shared helper.
  bindTipTargets(createHoverCard({doc: pip.document, win: pip}), pip.document, {glossary: text => glossaryDefinitions(text, false)});
  pip.addEventListener("pagehide", () => { app.pip = null; });
  renderPip();
}

function renderPip() {
  const pip = app.pip;
  if (!pip || pip.closed) return;
  const root = pip.document.querySelector(".tt-pip-root");
  if (!root) return;
  if (!currentViewer().ready) { root.textContent = "Choose My fighters on the table to see this fight."; return; }
  const p = presentation();
  const id = app.menu?.actor_id || [...app.selected].at(-1);
  const actor = id && actorById(id);
  root.replaceChildren();
  if (!p || !actor) { root.innerHTML = `<p class="tt-muted">Open a fight on the table.</p>`; return; }
  const head = pip.document.createElement("div");
  head.className = "tt-pip-head";
  head.innerHTML = `<strong></strong><span class="tt-sub"></span><div class="tt-bar"><i></i></div><div class="tt-pills"></div>`;
  head.querySelector("strong").textContent = actor.display_name;
  head.querySelector(".tt-sub").textContent = `${p.terminal ? "Fight over" : `Round ${p.round_number}`} · HP ${actor.hit_points.current}/${actor.hit_points.maximum}`
    + (actor.death_saves ? ` · Death saving throws: ${actor.death_saves.ok} successes, ${actor.death_saves.bad} failures` : "")
    + (actor.resources || []).filter(row => !String(row.resource_id).startsWith("resource:uses.") && row.maximum > 1).map(row => ` · ${row.display_name} ${row.current}/${row.maximum}`).join("");
  head.querySelector(".tt-sub").dataset.tip = (actor.resources || []).filter(row => !String(row.resource_id).startsWith("resource:uses.") && row.maximum > 1).map(row => resourceText(row)).join("\n\n");
  head.querySelector(".tt-bar i").style.width = `${pct(actor.hit_points.current, actor.hit_points.maximum)}%`;
  const turn = actor.turn_state || {};
  head.querySelector(".tt-pills").innerHTML = `${economyPills(turn)}<span class="tt-pill">${movementLeft(actor)}</span>`;
  root.appendChild(head);
  const mine = app.menu && app.menu.actor_id === actor.entity_id;
  const note = pip.document.createElement("p");
  note.className = "tt-muted";
  note.textContent = mine ? "Your turn — press an action (targets are picked on the table)." : `${actorById(p.current_actor_id)?.display_name || "—"} is acting.`;
  root.appendChild(note);
  if (!mine) return;
  const list = pip.document.createElement("div");
  list.className = "tt-pip-buttons";
  for (const group of app.menu.actions) {
    const button = pip.document.createElement("button");
    button.type = "button";
    button.className = "tt-btn";
    button.innerHTML = "<b></b><small></small>";
    button.querySelector("b").textContent = group.label;
    button.dataset.tip = group.description || group.label;
    button.tipCard = actionTipCard({label: group.label, hover: group.hover}, {rules: layoutText(group.hover) || cleanRules(group.description) || ""});
    markActive(button, app.state.button_states?.[actor.entity_id]?.[`act:${group.source_definition_id}`]?.active);
    button.querySelector("small").textContent = `${costTag(group)}${group.options.length > 1 ? ` · ${group.options.length} choices` : ""}`;
    button.addEventListener("click", () => { window.focus(); useGroup(group); });
    list.appendChild(button);
  }
  if (app.menu.end_turn) {
    const end = pip.document.createElement("button");
    end.type = "button";
    end.className = "tt-btn is-end";
    end.innerHTML = "<b>End turn</b>";
    end.addEventListener("click", () => actOnce(app.menu.end_turn));
    list.appendChild(end);
  }
  root.appendChild(list);
}

// ------------------------------------------------------------------ lobby: saved fights and the fight builder
// A saved fight keeps its own name; a save that can't be opened still gets a plain
// label instead of the internal logical ID (never show "match:..." to a player).
function savedFightLabel(row) {
  const name = row && typeof row.display_name === "string" ? row.display_name.trim() : "";
  return name && !name.startsWith("match:") ? name : "Saved fight";
}

// "played 5 min ago" / "played yesterday": the fight list's plain-words activity time (last_played_at, UTC ISO).
function playedAgo(iso, now = Date.now()) {
  const when = iso ? new Date(iso) : null;
  if (!when || Number.isNaN(when.getTime())) return "";
  const seconds = Math.max(0, Math.round((now - when.getTime()) / 1000));
  if (seconds < 60) return "played just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `played ${minutes} min ago`;
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  if (when >= midnight) {
    const hours = Math.floor(minutes / 60);
    return `played ${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  const yesterday = new Date(midnight);
  yesterday.setDate(yesterday.getDate() - 1);
  if (when >= yesterday) return "played yesterday";
  const days = Math.max(2, Math.floor(seconds / 86400));
  if (days < 7) return `played ${days} days ago`;
  return `played on ${when.toLocaleDateString(undefined, {month: "short", day: "numeric"})}`;
}

async function openLobby() {
  const dialog = $("#ttLobby");
  if (!dialog.open) dialog.showModal();
  const saved = $("#ttSaved");
  saved.innerHTML = `<p class="tt-muted">Loading…</p>`;
  try {
    const rows = await api("/api/combat/matches");
    fighterPicker.rememberFights(rows);  // "Recent" in the fighter picker counts the fights each character played
    saved.replaceChildren();
    if (!rows.length) saved.innerHTML = `<p class="tt-muted">No fights yet — make one on the left.</p>`;
    for (const row of rows) {  // the API lists fights newest-played first
      const line = document.createElement("div");
      line.className = "tt-saved-row";
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `<span></span><small></small>`;
      const label = savedFightLabel(row);
      button.firstChild.textContent = label;
      const status = row.unavailable_message || (row.status === "COMPLETE" || row.status === "COMPLETED"
        ? "finished" : row.state_version == null ? "Saved fight" : `step ${row.state_version}`);
      const played = playedAgo(row.last_played_at);
      button.lastChild.textContent = played ? `${status} · ${played}` : status;
      button.addEventListener("click", () => { dialog.close(); loadMatch(row.match_id); });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tt-saved-delete";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", `Delete ${label}`);
      remove.addEventListener("click", async () => {
        if (remove.disabled) return;
        if (!confirm(`Delete the saved fight “${label}”? This cannot be undone.`)) return;
        remove.disabled = true;
        try {
          await api(`/api/tabletop/matches/${enc(row.match_id)}`, {method: "DELETE"});
          line.remove();
          if (app.matchId === row.match_id) location.href = "/tabletop";
        } catch (error) { toast(error.message, true); remove.disabled = false; }
      });
      line.append(button, remove);
      saved.appendChild(line);
    }
  } catch (error) { saved.textContent = error.message; }
  await buildFightBuilder();
}

let builderBuilt = false;
// Buffs cast before the fight (owner 2026-09-29: "allow at the beginning of the fights 2 persistent buffs for each
// entry"): up to two lasting 10 minutes or longer, one with Concentration, paid from the starting CP. The AI's picks are
// checked to begin with.
const POOL_NAMES = {qi: "Qi", stamina: "Stamina", resonance: "Resonance", martial_focus: "Martial Focus"};
function serializePrefight(entry) {
  const picks = entry.prefight ? [...entry.prefight] : [];
  for (const [id, values] of Object.entries(entry.setupChoices || {}))
    picks.push(`setup-choice:${id}:${values.join(",")}`);
  return picks;
}
function prefightCost(costs) {
  return (costs || []).map(([resource, amount]) => {
    const key = String(resource).split(".").pop();
    return `${amount} ${POOL_NAMES[key] || key.replace(/_/g, " ")}`;
  }).join(" + ") || "free";
}

async function loadPrefight(entry, host, saved = null) {
  host.replaceChildren();
  // Keep explicit saved choices (including "cast nothing") if restoration fails.
  entry.prefight = Array.isArray(saved) ? new Set(saved) : null;
  const pid = entry.who.value;
  const request = Symbol();
  entry.prefightRequest = request;
  entry.prefightLoading = Boolean(pid);
  updatePresetSaveButtons(entry.side);
  if (!pid) return true;
  host.textContent = "Loading casts before the fight…";
  let data;
  try { data = await api(`/api/combat/factory-prefight/${enc(pid)}`); } catch (error) {
    if (entry.prefightRequest === request && entry.who.value === pid) {
      host.textContent = `Could not restore casts before the fight: ${error.message}. ${Array.isArray(saved) ? "Saved choices have been kept." : "Choose the fighter again to retry."}`;
    }
    return false;
  } finally {
    if (entry.prefightRequest === request) {
      entry.prefightLoading = false;
      updatePresetSaveButtons(entry.side);
    }
  }
  if (entry.prefightRequest !== request || entry.who.value !== pid) return false;
  const savedRows = Array.isArray(saved) ? saved : [];
  entry.setupChoices = {};
  let setupChanged = false;
  const setupIds = new Set((data.setup_choices || []).map(row => row.id));
  if (savedRows.some(value => typeof value === "string" && value.startsWith("setup-choice:") && !setupIds.has(value.split(":")[1]))) setupChanged = true;
  for (const declaration of data.setup_choices || []) {
    const prefix = `setup-choice:${declaration.id}:`;
    const savedChoice = savedRows.find(value => typeof value === "string" && value.startsWith(prefix));
    const raw = savedChoice ? savedChoice.slice(prefix.length) : null;
    const values = raw === null ? [] : (raw === "" ? [] : raw.split(",").map(value => value.trim() === "" ? NaN : Number(value)));
    entry.setupChoices[declaration.id] = Array.from({length: declaration.count}, (_, index) => {
      const value = values[index];
      return Number.isInteger(value) && value >= declaration.minimum && value <= declaration.maximum
        ? value : (declaration.default?.[index] ?? declaration.minimum);
    });
    if (Array.isArray(saved) && (!savedChoice || values.length !== declaration.count ||
        values.some((value, index) => value !== entry.setupChoices[declaration.id][index]))) setupChanged = true;
  }
  const setupNotice = "Saved setup choices were updated for this fighter. Missing or invalid values use the current defaults; extra choices were removed. Review them before starting the fight.";
  if (!(data.options || []).length && !(data.setup_choices || []).length) { host.textContent = setupChanged ? setupNotice : "No buffs to cast before the fight."; entry.prefight = new Set(); return true; }
  // A saved team setup brings its own picks (those the character still has); otherwise the AI's picks to begin with.
  const known = new Set(data.options.map(option => option.action_id));
  entry.prefight = new Set(Array.isArray(saved) ? savedRows.filter(id => known.has(id)).slice(0, data.max) : (data.picks || []));
  const box = document.createElement("details");
  box.open = true;
  const summary = document.createElement("summary");
  const holds = data.max_concentration || 1;  // Concentrations held at once, by CL (owner 2026-09-29)
  const label = () => { summary.textContent = `Cast before the fight (${entry.prefight.size}/${data.max}, ${holds === 1 ? "one" : `up to ${holds}`} with Concentration)`; };
  label();
  box.appendChild(summary);
  if (setupChanged) {
    const notice = document.createElement("p");
    notice.textContent = setupNotice;
    box.appendChild(notice);
  }
  const byId = Object.fromEntries(data.options.map(option => [option.action_id, option]));
  for (const option of data.options) {
    const {row, tick} = createPrefightRow(option, prefightCost(option.costs));
    tick.checked = entry.prefight.has(option.action_id);
    tick.addEventListener("change", () => {
      if (tick.checked) {
        const chosen = [...entry.prefight].map(id => byId[id]).filter(Boolean);
        const why = chosen.length >= data.max ? `At most ${data.max} buffs before a fight.`
          : option.concentration && chosen.filter(row => row.concentration).length >= holds ? `At most ${holds === 1 ? "one" : holds} of them may use Concentration.`
          : option.meld && chosen.some(row => row.meld === option.meld) ? "That Meld is already chosen." : "";
        if (why) { tick.checked = false; toast(why, true); return; }
        entry.prefight.add(option.action_id);
      } else entry.prefight.delete(option.action_id);
      label();
    });
    box.appendChild(row);
  }
  for (const declaration of data.setup_choices || []) {
    const title = document.createElement("p");
    title.textContent = declaration.label;
    box.appendChild(title);
    if (declaration.help) {
      const help = document.createElement("p");
      help.textContent = declaration.help;
      box.appendChild(help);
    }
    for (let index = 0; index < declaration.count; index++) {
      const row = document.createElement("label");
      row.className = "tt-prefight-row";
      const text = document.createElement("span");
      text.textContent = `${declaration.item_label || declaration.label} ${index + 1}: `;
      const amount = document.createElement("select");
      for (let value = declaration.minimum; value <= declaration.maximum; value++) {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = `${value} ${declaration.unit || ""}`.trim();
        amount.appendChild(option);
      }
      amount.value = String(entry.setupChoices[declaration.id][index]);
      amount.addEventListener("change", () => { entry.setupChoices[declaration.id][index] = Number(amount.value); });
      row.append(text, amount);
      box.appendChild(row);
    }
  }
  host.replaceChildren(box);
  return true;
}

async function buildFightBuilder() {
  if (builderBuilt) return;
  const host = $("#ttBuilder");
  let characters = [], maps = {maps: [], builtin: []};
  try {
    [characters, maps] = await Promise.all([api("/api/combat/factory-characters"), api("/api/tabletop/maps")]);
  } catch (error) { host.textContent = error.message; return; }
  if (!app.providers?.length) await loadProviders();  // installed models join each fighter's "Who plays" list
  builderBuilt = true;
  host.replaceChildren();
  const providersNote = document.createElement("p");
  providersNote.className = "tt-muted tt-providers-note";
  providersNote.textContent = "Model list unavailable, retrying…";
  providersNote.hidden = !providerList.state.unavailable;
  host.appendChild(providersNote);
  if (!characters.length) { host.innerHTML = `<p class="tt-muted">No finished characters yet.</p>`; return; }
  const teams = document.createElement("div");
  teams.className = "tt-teams";
  const sides = [];
  const teamBars = [];
  for (const [index, title] of ["Team 1", "Team 2"].entries()) {
    const box = document.createElement("div");
    box.className = "tt-team";
    box.innerHTML = `<h4></h4><div class="tt-slots"></div><button type="button" class="tt-tool">+ Add fighter</button>`;
    box.querySelector("h4").textContent = title;
    const side = {slots: [], host: box.querySelector(".tt-slots")};
    const addButton = box.querySelector("button");
    const updateAddButton = () => {
      const atLimit = !canAddFighter(side.slots.length);
      addButton.disabled = atLimit;
      addButton.title = atLimit ? "Up to 10 fighters per side" : "";
      addButton.setAttribute("aria-label", atLimit ? "+ Add fighter (up to 10 fighters per side)" : "+ Add fighter");
    };
    const addSlot = () => {
      if (!canAddFighter(side.slots.length)) return;
      const slot = document.createElement("div");
      slot.className = "tt-slot";
      // The slot's fighter is still this dropdown's value (saves, presets and Create read it); the fighter picker
      // (fighter-picker.js, owner 2026-10-04) sets it, and the face button shows the token and opens the picker.
      const who = document.createElement("select");
      who.innerHTML = `<option value="">— choose —</option>` + characters.map(row => `<option value="${escapeHtml(row.project_id)}">${escapeHtml(row.display_name)} · ${escapeHtml(row.path || "")} ${row.cultivation_level ? `CL ${row.cultivation_level}` : ""}</option>`).join("");
      who.hidden = true;
      const face = document.createElement("button");
      face.type = "button";
      face.className = "tt-slot-face";
      const control = document.createElement("select");
      control.innerHTML = setupControlHtml(app.providers);
      control.dataset.setupControl = "";
      control.value = index === 0 ? "MANUAL" : "LOCAL_AUTO";
      control.setAttribute("aria-label", "Who plays this fighter: you, the AI or a model");
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tt-tool";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", "Remove fighter");
      const buffs = document.createElement("div");
      buffs.className = "tt-prefight";
      const entry = {who, control, slot, prefight: null, side};
      entry.showWho = () => fighterPicker.fillSlotFace(face, characters.find(row => row.project_id === who.value), title);
      entry.drop = () => { side.slots.splice(side.slots.indexOf(entry), 1); slot.remove(); updateAddButton(); };
      remove.addEventListener("click", () => { if (side.slots.length > 1) entry.drop(); else { who.value = ""; entry.showWho(); loadPrefight(entry, buffs); } updatePresetSaveButtons(side); });
      entry.buffs = buffs;
      who.addEventListener("change", () => { entry.showWho(); loadPrefight(entry, buffs); });
      face.addEventListener("click", () => choose(entry, false));
      entry.showWho();
      slot.append(who, face, control, remove, buffs);
      side.host.appendChild(slot);
      side.slots.push(entry);
      updateAddButton();
      return entry;
    };
    // Open the picker for a slot. From "+ Add fighter" the new slot goes again if nothing is picked; with "Keep open"
    // each further pick takes a new slot (up to the per-side limit).
    const choose = (entry, added) => {
      let target = entry;
      fighterPicker.open({
        characters, teamName: title, mode: splitSetupControl(entry.control.value).mode,
        taken: new Set(sides.flatMap(other => other.slots)
          .filter(other => other !== entry && other.who.value).map(other => other.who.value)),
        onPick: pick => {
          if (!target) target = addSlot();
          if (!target) return false;
          const prior = target.control.value;
          applyPick(target, pick);
          // The picker only knows You / AI: re-picking a fighter keeps a model chosen in the dropdown.
          if (prior.startsWith(MODEL_PREFIX) && pick.mode === "LOCAL_AUTO") target.control.value = prior;
          target = null;
          return canAddFighter(side.slots.length);
        },
        onCancel: () => { if (added && !entry.who.value && side.slots.length > 1) { entry.drop(); updatePresetSaveButtons(side); } },
      });
    };
    side.addSlot = addSlot;
    addButton.addEventListener("click", () => { const entry = addSlot(); if (entry) choose(entry, true); });
    addSlot();
    box.appendChild(singleTeamBar(side, characters, teamBars, title));
    teams.appendChild(box);
    sides.push(side);
  }
  const foot = document.createElement("div");
  foot.className = "tt-builder-foot";
  const name = document.createElement("input");
  name.placeholder = "Fight name (optional)";
  const mapSelect = document.createElement("select");
  mapSelect.innerHTML = [...(maps.maps || []).map(row => `<option value="${escapeHtml(row.arena_id)}">${escapeHtml(row.display_name)} (${row.width_squares}×${row.height_squares})</option>`),
    ...(maps.builtin || []).map(row => `<option value="${escapeHtml(row.arena_id)}">${escapeHtml(row.display_name)} (built-in)</option>`)].join("");
  if (maps.default_arena_id) mapSelect.value = maps.default_arena_id;
  const arenaDescription = document.createElement("p");
  arenaDescription.className = "tt-muted";
  const describeArena = () => {
    arenaDescription.textContent = [...(maps.maps || []), ...(maps.builtin || [])]
      .find(row => row.arena_id === mapSelect.value)?.description || "";
  };
  mapSelect.addEventListener("change", describeArena);
  describeArena();
  const create = document.createElement("button");
  create.type = "button";
  create.className = "tt-tool tt-primary";
  create.textContent = "Create fight";
  // Retain the created fight across transport errors. Retrying finishes this
  // setup; it must never submit a second factory-create request.
  let pendingSetup = null;
  const openCreated = document.createElement("button");
  openCreated.type = "button";
  openCreated.className = "tt-tool";
  openCreated.textContent = "Open created fight";
  openCreated.hidden = true;
  const recoverSetup = async error => {
    let recovery = "";
    if (pendingSetup.modelSeats.length) {
      try {
        await api(`/api/tabletop/matches/${enc(pendingSetup.matchId)}/playback`, {body: {paused: true}});
        recovery = " Automatic turns are paused.";
      } catch { recovery = " Could not confirm that automatic turns are paused; open the fight to check Play/Pause."; }
    }
    openCreated.hidden = false;
    create.textContent = "Retry fight setup";
    if (!$("#ttLobby").open) openLobby();
    toast(`The fight already exists. Setup could not finish: ${error.message}${recovery} Retry fight setup or open the created fight; retry uses this same fight.`, true);
  };
  openCreated.addEventListener("click", async () => {
    if (!pendingSetup || create.disabled) return;
    create.disabled = openCreated.disabled = true;
    try {
      // Opening an unfinished setup must not start the browser's AI loop either.
      if (pendingSetup.modelSeats.length) app.userPaused = true;
      $("#ttLobby").close();
      if (!await loadMatch(pendingSetup.matchId)) throw Error("Could not open the created fight.");
    }
    catch (error) { await recoverSetup(error); }
    finally { create.disabled = openCreated.disabled = false; }
  });
  create.addEventListener("click", async () => {
    const picked = sides.map(side => side.slots.filter(slot => slot.who.value).map(slot => ({pid: slot.who.value, mode: slot.control.value})));
    if (!pendingSetup && (!picked[0].length || !picked[1].length)) return toast("Choose at least one fighter for each team.", true);
    const all = picked.flat().map(row => row.pid);
    if (!pendingSetup && new Set(all).size !== all.length) return toast("A character can only be in a fight once.", true);
    const modes = Object.fromEntries(picked.flat().map(row => {
      const control = splitSetupControl(row.mode);
      return [FACTORY + row.pid, control.provider ? "MANUAL" : control.mode];
    }));
    const modelSeats = picked.flat().map(row => ({actor_id: FACTORY + row.pid, provider_id: splitSetupControl(row.mode).provider,
      name: characters.find(character => character.project_id === row.pid)?.display_name || "This fighter"}))
      .filter(row => row.provider_id);
    // Buffs cast before the fight: the checklist's picks; a fighter whose list did not load gets the AI's.
    const prefight = Object.fromEntries(sides.flatMap(side => side.slots.filter(slot => slot.who.value && slot.prefight)
      .map(slot => [FACTORY + slot.who.value, serializePrefight(slot)])));
    create.disabled = true;
    try {
      if (!pendingSetup) {
        const view = await api("/api/combat/factory-matches", {body: {
          project_ids: picked[0].map(row => row.pid), opponent_actor_ids: picked[1].map(row => FACTORY + row.pid),
          control_modes: modes, display_name: name.value.trim() || null, arena_id: mapSelect.value || null, prefight,
        }});
        pendingSetup = {matchId: view.match_id, modelSeats, resolved: new Set()};
      }
      const setup = pendingSetup;
      const matchUrl = `/api/tabletop/matches/${enc(setup.matchId)}`;
      // No model seat exists yet, so the runner is inert. Pause before the first seat
      // enables it; all seats must be installed before any fighter can take a turn.
      if (setup.modelSeats.length) await api(`${matchUrl}/playback`, {body: {paused: true}});
      for (const seat of setup.modelSeats) {
        if (setup.resolved.has(seat.actor_id)) continue;
        try {
          await api(`${matchUrl}/seat`, {body: {actor_id: seat.actor_id, control: "MODEL", provider_id: seat.provider_id}});
        } catch (error) {
          // A lost response may follow a committed write. Only persisted seat
          // status can tell us whether the selected model or the player owns it.
          let status;
          try { status = await api(`${matchUrl}/seat-status`); }
          catch { throw Error(`Could not confirm who plays ${seat.name}.`); }
          if (!status?.seats || typeof status.seats !== "object" || Array.isArray(status.seats)) throw Error(`Could not confirm who plays ${seat.name}.`);
          const saved = status.seats[seat.actor_id];
          if (saved?.control === "MODEL" && saved.provider_id === seat.provider_id) {
            toast(`${seat.name}'s selected model is seated; its response was interrupted.`);
          } else if (!saved || saved.control === "MANUAL") {
            toast(`${seat.name}'s model could not be seated: ${error.message} You now play ${seat.name}; choose who plays them on their fighter card.`, true);
          } else {
            throw Error(`Could not confirm the selected model or your control of ${seat.name}.`);
          }
        }
        setup.resolved.add(seat.actor_id);
      }
      if (setup.modelSeats.length) await api(`${matchUrl}/playback`, {body: {paused: false}});
      $("#ttLobby").close();
      if (!await loadMatch(setup.matchId)) throw Error("Could not open the created fight.");
      openCreated.hidden = true;
      pendingSetup = null;
    } catch (error) {
      if (!pendingSetup) toast(error.message, true);
      else await recoverSetup(error);
    }
    finally { create.disabled = false; }
    create.textContent = pendingSetup ? "Retry fight setup" : "Create fight";
  });
  foot.append(name, mapSelect, arenaDescription, openCreated, create);
  host.append(presetBar(sides, name, mapSelect, characters, describeArena), teams, foot);
}

// Both team and whole-setup saves share restoration state and member snapshots.
function updatePresetSaveButtons(side) {
  for (const button of side?.saveButtons || []) {
    button.disabled = button.presetSides.some(item => item.slots.some(entry => entry.prefightLoading));
  }
}

function savedTeamMembers(side) {
  return side.slots.filter(entry => entry.who.value)
    .map(entry => ({pid: entry.who.value, mode: entry.control.value, prefight: entry.prefight ? serializePrefight(entry) : null}));
}

async function fillSavedTeam(side, members, known) {
  for (const entry of side.slots) entry.slot.remove();
  side.slots.length = 0;
  const present = members.filter(member => known.has(member.pid));
  const restores = [];
  for (const member of present.length ? present : [null]) {
    const entry = side.addSlot();
    if (!member) continue;
    entry.who.value = member.pid;
    entry.control.value = member.mode;
    // A saved team may name a model that is no longer installed: that fighter falls back to the built-in AI.
    if (entry.control.value !== member.mode) entry.control.value = "LOCAL_AUTO";
    entry.showWho?.();
    entry.side = side;
    restores.push(loadPrefight(entry, entry.buffs, member.prefight));
  }
  updatePresetSaveButtons(side);
  const results = await Promise.all(restores);
  return {missing: members.length - present.length, failed: results.some(result => result === false)};
}

// Single teams use a separate file/API; either side can load any team without changing the other side or the map.
function singleTeamBar(side, characters, refreshers, sideName) {
  const bar = document.createElement("div");
  bar.className = "tt-presets tt-team-presets";
  bar.innerHTML = `<label class="tt-select-label">Saved teams <select data-team><option value="">— saved teams —</option></select></label>
    <button type="button" class="tt-tool" data-team-load>Load team</button>
    <button type="button" class="tt-tool" data-team-save>Save team…</button>
    <button type="button" class="tt-tool" data-team-delete>Delete saved team</button>`;
  const select = bar.querySelector("[data-team]");
  const saveButton = bar.querySelector("[data-team-save]");
  saveButton.presetSides = [side];
  (side.saveButtons ||= []).push(saveButton);
  updatePresetSaveButtons(side);
  select.setAttribute("aria-label", `${sideName} saved teams`);
  bar.querySelector("[data-team-save]").title = "Save this side's fighters, who controls them, and their casts before the fight.";
  bar.querySelector("[data-team-load]").title = `Replace the fighters on ${sideName} with a saved team. The other side, map and fight name stay as they are.`;
  let savedTeams = [];
  const known = new Set(characters.map(row => row.project_id));
  const refresh = async (pick = select.value) => {
    try {
      savedTeams = (await api("/api/tabletop/saved-teams")).teams || [];
      select.replaceChildren(new Option("— saved teams —", ""), ...savedTeams.map(row => new Option(row.name, row.name)));
      select.value = pick;
    } catch (error) { toast(error.message, true); }
  };
  refreshers.push(refresh);
  bar.querySelector("[data-team-load]").addEventListener("click", async () => {
    const team = savedTeams.find(row => row.name === select.value);
    if (!team) return toast("Choose a saved team first.", true);
    const {missing, failed} = await fillSavedTeam(side, team.members, known);
    if (failed) return toast(`Loaded fighters from “${team.name}” into ${sideName}, but could not restore casts before the fight. Saved cast choices have been kept.`, true);
    toast(missing ? `Loaded “${team.name}”; ${missing} fighter${missing === 1 ? " is" : "s are"} no longer available.` : `Loaded “${team.name}” into ${sideName}.`);
  });
  bar.querySelector("[data-team-save]").addEventListener("click", async () => {
    if (side.slots.some(entry => entry.prefightLoading)) return toast("Wait for casts before the fight to finish loading before saving this team.", true);
    const members = savedTeamMembers(side);
    if (!members.length) return toast("Choose at least one fighter on this side before saving.", true);
    const title = prompt("Name this team (fighters, controls and casts before the fight):", select.value || "");
    const name = (title || "").trim().replace(/\s+/g, " ").slice(0, 60);
    if (!name) return;
    let replace = false;
    if (savedTeams.some(row => row.name === name)) {
      if (!confirm(`Replace the saved team “${name}”?`)) return;
      replace = true;
    }
    try {
      const saved = await api("/api/tabletop/saved-teams", {body: {preset: {name, members, replace}}});
      await Promise.all(refreshers.map(fn => fn(fn === refresh ? saved.name : undefined)));
      toast(`Saved team “${saved.name}”.`);
    } catch (error) {
      // A concurrent save can introduce a collision; refresh before the next attempt, never silently replace it.
      await Promise.all(refreshers.map(fn => fn()));
      toast(error.code === "TEAM_NAME_EXISTS" ? "A team with that name was just saved. Save again to confirm replacing it." : error.message, true);
    }
  });
  bar.querySelector("[data-team-delete]").addEventListener("click", async () => {
    if (!select.value) return toast("Choose a saved team first.", true);
    if (!confirm(`Delete the saved team “${select.value}”?`)) return;
    try {
      await api(`/api/tabletop/saved-teams/${enc(select.value)}`, {method: "DELETE"});
      await Promise.all(refreshers.map(fn => fn()));
    } catch (error) { toast(error.message, true); }
  });
  refresh();
  return bar;
}

// Saved team setups (owner 2026-09-29: "some kind of team saver"): sides, who plays each fighter, their buffs before the
// fight, the map and the fight name, kept by the Factory under its data folder.
function presetBar(sides, fightName, mapSelect, characters, onArenaChange = () => {}) {
  const bar = document.createElement("div");
  bar.className = "tt-presets";
  bar.innerHTML = `<label class="tt-select-label">Whole fight setup <select data-preset><option value="">— saved setups —</option></select></label>
    <button type="button" class="tt-tool" data-preset-load>Load</button>
    <button type="button" class="tt-tool" data-preset-save>Save current…</button>
    <button type="button" class="tt-tool" data-preset-delete>Delete</button>`;
  const select = bar.querySelector("[data-preset]");
  const saveButton = bar.querySelector("[data-preset-save]");
  saveButton.presetSides = sides;
  for (const side of sides) (side.saveButtons ||= []).push(saveButton);
  for (const side of sides) updatePresetSaveButtons(side);
  let presets = [];
  const known = new Set(characters.map(row => row.project_id));
  const refresh = async (pick = "") => {
    try { presets = (await api("/api/tabletop/team-presets")).presets || []; } catch (error) { toast(error.message, true); return; }
    select.replaceChildren(new Option("— saved setups —", ""), ...presets.map(row => new Option(row.name, row.name)));
    select.value = pick;
  };
  bar.querySelector("[data-preset-load]").addEventListener("click", async () => {
    const preset = presets.find(row => row.name === select.value);
    if (!preset) return toast("Choose a saved setup first.", true);
    const restores = preset.teams.map((members, index) => fillSavedTeam(sides[index], members, known));
    if (preset.arena_id && [...mapSelect.options].some(option => option.value === preset.arena_id)) mapSelect.value = preset.arena_id;
    onArenaChange();
    fightName.value = preset.fight_name || "";
    const results = await Promise.all(restores);
    const missing = results.reduce((sum, result) => sum + result.missing, 0);
    if (results.some(result => result.failed)) return toast(`Loaded fighters from “${preset.name}”, but could not restore casts before the fight. Saved cast choices have been kept.`, true);
    toast(missing ? `Loaded “${preset.name}”; ${missing} fighter${missing === 1 ? " is" : "s are"} no longer available.` : `Loaded “${preset.name}”.`);
  });
  bar.querySelector("[data-preset-save]").addEventListener("click", async () => {
    if (sides.some(side => side.slots.some(entry => entry.prefightLoading))) return toast("Wait for casts before the fight to finish loading before saving this setup.", true);
    const teams = sides.map(savedTeamMembers);
    if (!teams[0].length || !teams[1].length) return toast("Choose at least one fighter for each team before saving.", true);
    const title = prompt("Name this team setup:", select.value || fightName.value.trim() || "");
    if (!title || !title.trim()) return;
    if (presets.some(row => row.name === title.trim()) && !confirm(`Replace the saved setup “${title.trim()}”?`)) return;
    try {
      const saved = await api("/api/tabletop/team-presets", {body: {preset: {name: title, teams, arena_id: mapSelect.value || null, fight_name: fightName.value.trim() || null}}});
      await refresh(saved.name);
      toast(`Saved “${saved.name}”.`);
    } catch (error) { toast(error.message, true); }
  });
  bar.querySelector("[data-preset-delete]").addEventListener("click", async () => {
    if (!select.value) return toast("Choose a saved setup first.", true);
    if (!confirm(`Delete the saved setup “${select.value}”?`)) return;
    try {
      await api(`/api/tabletop/team-presets/${enc(select.value)}`, {method: "DELETE"});
      await refresh();
    } catch (error) { toast(error.message, true); }
  });
  refresh();
  return bar;
}

// ------------------------------------------------------------------ top bar, keys, start
$("#ttTheme").addEventListener("change", event => setTheme(event.target.value));
// Fog preferences belong to the same tab/view and match as the fighter binding.
// The old origin-wide tt-fog value deliberately has no part in this choice.
function rememberFogView() {
  return app.matchId ? fogView(viewerStore.readFog(app.matchId)) : null;
}
// Show the chosen view and explain it on hover, in the same words as the Fog picker's options.
function setFogPicker() {
  const picker = $("#ttFog");
  if (!picker) return;
  picker.value = app.fog;
  picker.disabled = !app.matchId || !currentViewer().ready;
  const chosen = fogView(app.fog);
  if (chosen) picker.title = chosen.help;
}

$("#ttFog").addEventListener("change", async event => {
  const mode = event.target.value;
  if (!app.matchId) return;
  if (mode === NO_FOG_VIEW) { selectGMView(); return; }
  if (currentViewer().status !== "player" || !currentViewer().ready) {
    setFogPicker();
    openViewerPicker();
    return;
  }
  app.fog = fogView(mode) && fogOn(mode) ? mode : DEFAULT_FOG_VIEW;
  viewerStore.writeFog(app.matchId, app.fog);
  resetViewerPresentation();
  setFogPicker();
  if (app.state) { renderTokens(); renderInspector(); renderHighlights(); }
});
$("#ttViewerChange").addEventListener("click", openViewerPicker);
$("#ttViewerGateChoose").addEventListener("click", openViewerPicker);
$("#ttViewerRetry").addEventListener("click", () => { void refresh({observe: true}); });
$("#ttViewerApply").addEventListener("click", () => {
  const ids = [...$("#ttViewerChoices").querySelectorAll("input")].filter(input => input.checked).map(input => input.value);
  savePlayerView(ids);
});
$("#ttViewerGM").addEventListener("click", selectGMView);
$("#ttViewerAnother").addEventListener("click", () => {
  if (app.matchId) window.open(tabletopUrl(app.matchId, mintViewId()), "_blank", "noopener");
});
$("#ttZoomIn").addEventListener("click", () => board.zoomBy(1.2));
$("#ttRoofs").addEventListener("click", event => {
  if (!isGMView()) return;
  const off = event.currentTarget.classList.toggle('is-off');
  event.currentTarget.setAttribute('aria-pressed', String(!off));
  if (app.state) renderTokens();
});
$("#ttZoomOut").addEventListener("click", () => board.zoomBy(1 / 1.2));
$("#ttFit").addEventListener("click", () => board.fit());
$("#ttCharacters").addEventListener("click", openCharacterList);
$("#ttLobbyOpen").addEventListener("click", openLobby);
$("#ttPanels").addEventListener("click", () => { document.body.classList.toggle("panels-hidden"); setTimeout(() => board.fit(), 50); });
$("#ttFeedDetail").addEventListener("change", async () => {
  $("#ttFeed").replaceChildren();
  Object.assign(feedFollow, {on: true, unseen: 0});
  $("#ttFeedJump").hidden = true;
  if (app.matchId) appendFeed((await api(`/api/tabletop/matches/${enc(app.matchId)}/events?after=0`)).events);
});
$("#ttDiceToggle").addEventListener("click", event => {
  app.diceOn = !app.diceOn;
  event.currentTarget.classList.toggle("is-on", app.diceOn);
  event.currentTarget.setAttribute("aria-pressed", String(app.diceOn));
  writePreference("tt-dice", app.diceOn ? "on" : "off");
});
$("#ttFullscreen").addEventListener("click", toggleFullscreen);
$("#ttNames").addEventListener("click", event => {
  const on = document.body.classList.toggle("show-names");
  event.currentTarget.classList.toggle("is-on", on);
  writePreference("tt-names", on ? "on" : "off");
});
function syncRulesOverlay(on = readPreference("tt-rules-overlay") === "true") {
  const button = $("#ttRulesOverlay");
  button.classList.toggle("is-on", on);
  button.setAttribute("aria-pressed", String(on));
}
$("#ttRulesOverlay").addEventListener("click", () => {
  const on = !$("#ttRulesOverlay").classList.contains("is-on");
  board.setRulesOverlay(on); syncRulesOverlay(on);
});
syncRulesOverlay();
$("#ttPip").addEventListener("click", () => openPip().catch(error => toast(error.message, true)));

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.().catch(() => toast("Full screen is not allowed here.", true));
}
document.addEventListener("fullscreenchange", () => setTimeout(() => board.fit(), 80));

$("#ttViewport").addEventListener("contextmenu", event => {
  if (!abilityChoiceActive()) return;
  event.preventDefault();
  // A right press that turns into a ruler drag must not cancel the pick, and browsers disagree
  // about whether this event fires on the press or on the release. The ruler decides on release
  // (wireMapRuler's onPlainRightClick); here we only stay out of its way. The typeof guard keeps
  // cut-down harnesses that run this listener on its own (tests/tabletop_esc_cancel.test.mjs) working.
  if (typeof ruler === "object" && ruler.blocksCancel()) return;
  cancelAbilityChoice();
});

document.addEventListener("keydown", event => {
  // Cancellation works from a focused height/target select as well as the map.
  // Run before the shortcut guard, through the exact Cancel-button path.
  if (event.key === "Escape" && abilityChoiceActive()) {
    event.preventDefault?.();
    cancelAbilityChoice();
    return;
  }
  if (event.target.closest("input, select, textarea, dialog")) return;
  if (event.shiftKey && event.key.toLowerCase() === "r") { event.preventDefault(); $("#ttRulesOverlay").click(); }
  if (event.key === "f" || event.key === "F") toggleFullscreen();
  else if (event.key === "Tab") { event.preventDefault(); $("#ttPanels").click(); }
  // A covered view swallows these shortcuts instead of acting on a hidden turn. Space is left
  // unprevented on purpose so it still presses the focused Retry button.
  else if ((event.key === " " || event.code === "Space") && app.menu?.end_turn && currentViewer().ready) { event.preventDefault(); actOnce(app.menu.end_turn); }
  else if ((event.key === "s" || event.key === "S") && app.state && !app.menu && !presentation()?.terminal && currentViewer().ready) autoStep();
  else if (event.key === "+" || event.key === "=") board.zoomBy(1.2);
  else if (event.key === "-") board.zoomBy(1 / 1.2);
});

// Keep a watching table in step with fights driven elsewhere (another tab, the sheet).
async function pollTable() {
  if (app.state?.menu_pending) { requestDeferredMenu(); return; }
  // Waiting for a player is idle work: another client may answer this very pause.
  // Read state only while a prompt is open; normal action/AI polling is unchanged.
  const waiting = app.waitingReaction;
  if (waiting && !app.polling && !document.hidden) {
    const request = refreshSequence, watchedState = app.state;
    const isCurrent = () => app.waitingReaction === waiting && app.matchId === waiting.matchId
      && refreshSequence === request && app.state === watchedState;
    app.polling = true;
    try {
      const [state] = await Promise.all([readTableState(waiting.matchId, app.fog), loadSeats()]);
      if (!isCurrent()) return;
      if (waiting.changed(state)) waiting.stop(state);
      else {
        // Built-in controller changes can update the roster without an event
        // or a different prompt. Keep ownership current while preserving the
        // exact answer promise and map-pick cursor. If a journal prefix did
        // advance, consume it before render can advance the display cursor.
        if (state.last_sequence > app.lastSequence) {
          const events = await api(`/api/tabletop/matches/${enc(waiting.matchId)}/events?after=${app.lastSequence}`);
          if (!isCurrent()) return;
          const complete = await eventsThroughState(events, state, waiting.matchId);
          if (!isCurrent()) return;
          // This branch read state first. A concurrent answer may have added
          // later events since then; leave them for the next poll/answer rather
          // than consuming a cursor beyond the snapshot we are about to show.
          const prefix = (complete.events || []).filter(row => row.event_sequence <= state.last_sequence);
          const rolls = new Set(prefix.map(row => row.roll_id).filter(Boolean));
          await playEvents({...complete, events: prefix,
            dice: (complete.dice || []).filter(roll => rolls.has(roll.roll_id)),
            last_sequence: state.last_sequence}, {fast: true});
          if (!isCurrent()) return;
        }
        renderObservedState(state);
      }
    } catch (error) {
      if (app.waitingReaction === waiting) await handleUnavailableFight(error, waiting.matchId);
    }
    finally { app.polling = false; }
    return;
  }
  if (!app.matchId || app.busy || app.playing || app.seatStatus?.running || app.polling || document.hidden) return;
  const matchId = app.matchId, watchedState = app.state, fog = app.fog, request = refreshSequence;
  const isCurrent = () => !app.busy && !app.playing && app.matchId === matchId && app.state === watchedState
    && app.fog === fog && refreshSequence === request;
  app.polling = true;
  try {
    const [events] = await Promise.all([
      api(`/api/tabletop/matches/${enc(matchId)}/events?after=${app.lastSequence}`), loadSeats(),
    ]);
    if (!isCurrent()) return;
    // A local draft does not invalidate the fight. Poll only the lightweight
    // event/version receipt until something outside this chooser changes it.
    if (app.optionDraft?.matches(app.menu, matchId)
        && events.state_version === app.optionDraft.version && !(events.events || []).length) return;
    // Always reconcile the snapshot, including an empty/nonadvancing feed.
    // Visible prose and seat status are not reliable indicators of a new turn
    // or state_version. renderObservedState preserves an unchanged human menu.
    const state = await readTableState(matchId, fog);
    if (!isCurrent()) return;
    const complete = await eventsThroughState(events, state, matchId);
    if (!isCurrent()) return;
    await playEvents(complete, {fast: true});
    if (!isCurrent()) return;
    renderObservedState(state);
    resumeServerPrompt(state);
  } catch (error) { if (isCurrent()) await handleUnavailableFight(error, matchId); }
  finally { app.polling = false; }
}
setInterval(pollTable, 3000);

(async function start() {
  showStyle();
  appearance?.onChange(showStyle);
  // No legacy preference, roster shape or controller can silently create a view.
  app.fog = DEFAULT_FOG_VIEW;
  renderViewerIdentity();
  app.diceOn = readPreference("tt-dice") !== "off";
  if (readPreference("tt-names") === "on") { document.body.classList.add("show-names"); $("#ttNames").classList.add("is-on"); }
  $("#ttDiceToggle").classList.toggle("is-on", app.diceOn);
  await loadDice();
  const params = new URLSearchParams(location.search);
  const matchId = params.get("match");
  if (matchId) await loadMatch(matchId);
  else { renderActionBar(); openLobby(); }
  window.tabletop = {app, board, act, autoStep, loadMatch, runButton};  // for smoke tests
})();

// Seam exposing the Assisted-vs-Manual action-bar choice for testing; behaviour unchanged.
export function appendActionBarRankedChoice(bar, menu, { doc = document, html, who, onAct, onMove, onSource, onPreviewMove } = {}) {
  if (menu.ranked_slots && menu.turn_mode === "Assisted") {
    bar.appendChild(renderRankedMenu(menu, { doc, onAct: onAct || (() => {}), onMove: onMove || (() => {}), onSource, onPreviewMove }));
    const more = doc.createElement("details");
    const summary = doc.createElement("summary");
    summary.textContent = "More… all abilities, movement controls and sheet choices";
    more.appendChild(summary); more.appendChild(html); bar.appendChild(more);
    who.querySelector(".tt-muted").textContent = `${menu.turn_mode || "Manual"}: choose a move, Action or Bonus action`;
  } else {
    bar.appendChild(html);
  }
}
