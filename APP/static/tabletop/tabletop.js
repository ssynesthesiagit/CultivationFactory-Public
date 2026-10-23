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
import {attackGroupView, groupAttackRows, renderVariantGroups} from "./attack-groups.js?v=variants1";
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

[Showing lines 1-923 of 5128 (50.0KB limit). Use offset=924 to continue.]