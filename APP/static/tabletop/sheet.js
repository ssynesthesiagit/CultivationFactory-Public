import { initGrow, loadGrow } from "./grow.js";
import "../sheet_view_model.js?v=sol192";
import {PresetQueue} from "./preset-queue.mjs?v=live-b3";
import {layoutText} from "./presentation.js?v=mmx104r2";
import {groupOptionRows} from "./option-groups.js?v=blossommenu-1";
import {attackGroupView, groupAttackRows, readAttack, groupVariantRows, renderVariantGroups} from "./attack-groups.js?v=variants1";
import { liveStats } from "./live-stats.mjs?v=r24";
import {heightFeet} from "./flight-ui.js?v=rel6-2";
import {unavailableRowsHidden} from "./sheet-polish.js?v=rel6-2";
import { cleanRules, ruleSummary, renderRules, actionSummary, actionHoverText, actionTipCard, renderTipCard, uniqueRuleBlocks, additionalRuleText } from "./rules.js?v=sol192";
import {glossaryDefinitions, installGlossary, resourceText} from "./newcomer.js?v=sol192";
import {playerError, sheetLoadMessage} from "./error-text.js?v=sheetpick1-1";
import {bindTipTargets, createHoverCard} from "./hovercard.js?v=tipdelay-1";
import { markActive } from "./active.js?v=c1-4";
import { PoweringPicker } from "./powering_picker.js";
import { initItems, renderItems } from "./items.js";
import { initTokens, openToken, showToken } from "./portrait.js";
import "../character_search.js?v=search1-1";
installGlossary();
// The shared hover card (owner 2026-10-03), the same one the map's zone and token cards use. h() above sends every
// sheet row's hover text here instead of to the browser's own tooltip, so a row can be read, scrolled and copied.
const sheetHoverCard = createHoverCard({doc: document, win: window});
const sheetTipTargets = bindTipTargets(sheetHoverCard, document, {glossary: text => glossaryDefinitions(text, false)});
/* Tianxia tabletop pop-out character sheet (ES module, no dependencies).
 *
 * Opens beside the combat table (/tabletop/sheet?project=<id>&theme=<name>). Checks, saves, skills and
 * initiative roll here with the 3D dice tray; combat buttons and combos are sent to the table over a
 * BroadcastChannel and resolved there by the rules engine.
 *
 * Channel "tianxia-tabletop"
 *   sends    {type:"sheet-hello", project_id, actor_id}
 *            {type:"button", project_id, actor_id, button_id, button}
 *            {type:"roll", project_id, actor_id, label, expression, result:{total, groups, modifier}}
 *   handles  {type:"actor", actor_id, hp, resources, conditions, turn, legal_button_ids,
 *             pending_choice: null | {kind, label, actor_id, prompt} | {kind:"question"}}
 *            {type:"result", actor_id, button_id, ok, message}
 */

const DICE_FOR_STYLE = { lacquer: "crimson", celestial: "midnight", ember: "crimson", classic: "jade" };
const CHANNEL_NAME = "tianxia-tabletop";
const HELLO_WAIT_MS = 2000;
const REHELLO_MS = 5000;
const MAX_STEPS = 8;
const DICE_RE = /^[0-9d+\-\s]+(adv|dis)?$/i; // mirrors the server's check
const SWATCHES = ["#b3261e", "#d9822b", "#d9ad55", "#3f9d6b", "#2f8fa3", "#3b6fd1", "#7b4fc9", "#c2447e", "#6b7280"];

const GROUPS = [
  { key: "attacks", filter: "attack", pill: "Attack", title: "Attacks" },
  { key: "actions", filter: "action", pill: "Action", title: "Actions" },
  { key: "bonus", filter: "bonus", pill: "Bonus Action", title: "Bonus Actions" },
  { key: "reactions", filter: "reaction", pill: "Reaction", title: "Reactions" },
  { key: "free", filter: "free", pill: "Free", title: "Free uses" },
  { key: "no_action", filter: "no_action", pill: "No action", title: "No action" },
  { key: "movement", filter: "movement", pill: "Move", title: "Movement" },
  { key: "basic", filter: "basic", pill: "Basic", title: "Basic Actions" },
  { key: "custom", filter: "custom", pill: "Custom", title: "Custom Combos" },
];
const GROUP_ORDER = ["attacks", "actions", "bonus", "reactions", "free", "no_action", "movement", "basic", "custom", "checks", "saves", "skills"];
const GROUP_NAMES = { attacks: "Attack", actions: "Action", bonus: "Bonus", reactions: "Reaction", basic: "Basic",
  free: "Free", no_action: "No action", movement: "Move", custom: "Combo", checks: "Check", saves: "Save", skills: "Skill" };
const ECONOMY = { ACTION: "Action", BONUS_ACTION: "Bonus Action", REACTION: "Reaction", FREE: "Free", NONE: "No action", MOVE: "Move", MOVEMENT: "Movement" };
const TARGETS = { HOSTILE_ENTITY: "Enemy", ALLY_OR_SELF: "Ally or self", SELF: "Self", CELL: "Point", ANY_ENTITY: "Any creature",
  ALLY: "Ally", ENTITY: "Creature" };

const ICONS = {
  d20: "M12 2 3 7v10l9 5 9-5V7l-9-5zm0 2.3 6.3 3.6L12 11.3 5.7 7.9 12 4.3zM5 9.6l6 3.4v6.6l-6-3.3V9.6zm8 10v-6.6l6-3.4v6.7l-6 3.3z",
  up: "M7.4 15.4 12 10.8l4.6 4.6L18 14l-6-6-6 6z",
  down: "M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z",
  trash: "M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
  close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  ok: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-2 15-5-5 1.4-1.4 3.6 3.6 7.6-7.6L19 8l-9 9z",
  error: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z",
  edit: "M4 17.25V20h2.75L17.8 8.94l-2.75-2.75L4 17.25zm15.7-9.04a1 1 0 0 0 0-1.41l-2.5-2.5a1 1 0 0 0-1.41 0l-1.83 1.83 3.91 3.91 1.83-1.83z",
  pin: "M16 3H8v2h1v6l-2 3v2h4.2v5h1.6v-5H17v-2l-2-3V5h1z",
};

const params = new URLSearchParams(location.search);
const state = {
  projectId: params.get("project") || params.get("project_id") || "",
  sheet: null,
  summary: null,
  buttons: [],
  byId: new Map(),
  hidden: new Set(),
  pinned: [],
  actor: null,
  connected: null, // null while waiting for the table's first answer
  showUnavailable: (() => { try { return localStorage.getItem("tianxia-sheet-show-unavailable") === "true"; } catch { return false; } })(),
  legal: null,
  unavailable: {},
  tab: "actions",
  filter: "all",
  featureQuery: "",
  rolls: [],
  libQuery: "",
  libGroup: "all",
  libStatus: "all",
  libOpen: new Set(),
};
let channel = null;
let presetWindow = crypto.randomUUID();
let presetToken;
const presetQueue = new PresetQueue({
  send: async (scope, values) => {
    presetToken ||= fetchJson("/api/session");
    const session = await presetToken;
    const url = scope ? `/api/tabletop/matches/${encodeURIComponent(scope)}/settings`
      : `/api/tabletop/characters/${encodeURIComponent(state.projectId)}/settings`;
    const options = {method: "POST", headers: {"Content-Type": "application/json", "X-Foundry-Token": session.token},
      body: JSON.stringify({actor_id: state.sheet.actor_id, request_id: crypto.randomUUID(), sources: values.map(v => v.replace(/^act:/, ""))})};
    let response;
    try { response = await fetchJson(url, options); }
    catch (error) {
      // A lost reply may follow a durable COMMIT. Retry that exact receipt once;
      // never create a second intent or retry a validation refusal.
      if (scope && (!error.status || error.status >= 500)) response = await fetchJson(url, options);
      else throw error;
    }
    const view = scope ? (state.actor?.match_id === scope ? state.actor : null) : state.sheet;
    if (view && response.modifier_rows) {
      const changed = new Map(response.modifier_rows.map(row => [row.button_id, row]));
      view.attack_modifier_rows = [...(view.attack_modifier_rows || []).filter(row => !changed.has(row.button_id)), ...changed.values()];
    }
    return response;
  },
  changed: presetChanged,
  error: presetError,
  pending: presetPending,
});

// A No-action rider dropdown is drawn with whatever fight scope was known when the row was drawn. The table's
// "actor" message can arrive later (the sheet was opened before the fight, or the previous fight just closed), so a
// control is found by the row and field it shows, not by the scope prefix in front of them. The live scope is
// adopted onto the control by syncModifierRow, which keeps later picks, their receipts and the server's row on the
// same control.
function riderKey(buttonId, field) {
  return `${state.actor?.match_id || ""}|${buttonId}/${field}`;
}

function riderKeySuffix(key) {
  const stored = String(key || "");
  return stored.slice(stored.indexOf("|") + 1);
}

function riderControls(root, key) {
  const suffix = riderKeySuffix(key);
  return [...root.querySelectorAll("[data-rider-key]")].filter(el => riderKeySuffix(el.dataset.riderKey) === suffix);
}

function presetChanged(key, value) {
  for (const select of riderControls(document, key)) select.value = value;
}

function presetError(key, error) {
  const control = riderControls(document, key)[0];
  toast("error", `${control?.getAttribute("aria-label") || "Preset"} not saved`, `The previous choice was restored. ${error.message}`, 5200);
}

// A saved setting changes only its own row (owner 2026-10-20: "clicking on the no action options on the character
// sheet still reloads the whole list, is this on purpose?" -- it was not). Sync the rows the server says changed,
// in place: the list, scroll, open sections, search and the active tab/filter all stay exactly as they were. A
// refused save never reaches this branch; PresetQueue restores the old control and shows the existing toast.
function presetPending(scope, pending, response, error) {
  if (response && (!scope || state.actor?.match_id === scope)) {
    presetQueue.acceptRefresh(scope, response.state_version);
    syncModifierRows((response.modifier_rows || []).map(row => row.button_id));
  }
  if (scope) post({type: pending ? "settings-pending" : "settings-saved", match_id: scope,
    actor_id: state.sheet.actor_id, sheet_id: presetWindow, ok: !error, state_version: response?.state_version,
    unsaved: Boolean(error) || [...presetQueue.next.values()].some(e => e.scope === scope)});
}
let helloTimer = 0;
let rehelloTimer = 0;
let diceModule = null;
let tray = null;
let rollSeq = 0;

// "Which pool pays" (owner 2026-09-25, Q19): optimistic + batched saves. null until the first
// edit, then seeded from the compiled sheet and kept authoritative for the dropdowns.
let poweringPicker = null;
let poweringRefreshTimer = 0;
const POWERING_REFRESH_MS = 350;

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ small helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value;
      // Every sheet row is built here, so this is the one place that decides what a row's hover text IS. It goes to
      // the shared hover card (hovercard.js) rather than the browser's own tooltip, which cannot be scrolled or
      // reached (owner 2026-10-03). The card points the row at itself with aria-describedby while it is open, so a
      // screen reader still gets the same words. Pass "data-tip" directly to opt in without the rewrite.
      else if (key === "title") el.dataset.tip = String(value);
      else if (key === "dataset") Object.assign(el.dataset, value);
      // A structured hover card (rules.js actionTipCard / the AC card); data-tip keeps the plain text.
      else if (key === "tipCard") el.tipCard = value;
      else if (key === "style") for (const [prop, v] of Object.entries(value)) el.style.setProperty(prop, v);
      else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
      else if (value === true) el.setAttribute(key, "");
      else el.setAttribute(key, String(value));
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false || kid === "") continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

function icon(name, cls = "icon") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

const signed = (n) => {
  const v = Number(n) || 0;
  return v >= 0 ? `+${v}` : `−${Math.abs(v)}`;
};
const spoken = (n) => { const v = Number(n) || 0; return v >= 0 ? `plus ${v}` : `minus ${Math.abs(v)}`; };
const clamp01 = (v) => Math.max(0, Math.min(1, v));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const norm = (text) => String(text || "").trim().toLowerCase();

const SMALL_WORDS = new Set(["of", "the", "and", "a", "an", "in", "on", "to", "for", "at", "by", "with", "from", "or"]);
function titleCase(words) {
  return words.filter(Boolean).map((w, i) => {
    const lower = w.toLowerCase();
    return i > 0 && SMALL_WORDS.has(lower) ? lower : lower.charAt(0).toUpperCase() + lower.slice(1);
  }).join(" ");
}
const words = (text) => String(text || "").split(/[_\s-]+/);

/** "tianxia.path.body_refining.feature.stamina_guard" -> {name:"Stamina Guard", source:"Body Refining path"}. */
function featureInfo(id) {
  const raw = String(id || "");
  if (/^TAL_/i.test(raw)) {
    const parts = raw.slice(4).split("_");
    const sphere = parts.length > 1 ? parts.shift() : "";
    return { name: titleCase(parts), source: sphere ? `${titleCase([sphere])} talent` : "Talent" };
  }
  if (raw.includes(".") && !raw.includes(" ")) {
    const segs = raw.split(".");
    const name = titleCase(words(segs[segs.length - 1]));
    const at = (key, offset) => { const i = segs.indexOf(key); return i >= 0 ? segs[i + offset] : null; };
    let source = "";
    if (at("subpath", 2)) source = `${titleCase(words(at("subpath", 2)))} subpath`;
    else if (at("path", 1)) source = `${titleCase(words(at("path", 1)))} path`;
    else if (at("talent", 1)) source = `${titleCase(words(at("talent", 1)))} talent`;
    return { name, source };
  }
  return { name: raw.includes(" ") ? raw : titleCase(words(raw)), source: "" };
}

const economyLabel = (e) => ECONOMY[e] || (e ? titleCase(words(e)) : "");
const targetLabel = (t) => TARGETS[t] || (t ? titleCase(words(t)) : "");

// ------------------------------------------------------------------ dice
function fallbackRollLocal(expression) {
  // Used only if dice3d.js fails to load: NdX terms, flat modifiers, "adv"/"dis" on a d20.
  const text = String(expression || "").trim();
  const mode = /\badv$/i.test(text) ? "advantage" : /\bdis$/i.test(text) ? "disadvantage" : "normal";
  const body = text.replace(/\s*(adv|dis)$/i, "").replace(/\s+/g, "");
  if (!body || !/^[+-]?(\d*d\d+|\d+)([+-](\d*d\d+|\d+))*$/i.test(body)) throw new Error(`Not dice notation: ${expression}`);
  const rand = (sides) => { const a = new Uint32Array(1); crypto.getRandomValues(a); return 1 + (a[0] % sides); };
  const groups = [], discarded = [];
  let modifier = 0;
  for (const term of body.match(/[+-]?[^+-]+/g)) {
    const sign = term.startsWith("-") ? -1 : 1;
    const t = term.replace(/^[+-]/, "");
    if (/d/i.test(t)) {
      const [n, s] = t.toLowerCase().split("d");
      const sides = Number(s);
      for (let i = 0; i < (Number(n) || 1); i++) {
        const a = rand(sides);
        if (sides === 20 && mode !== "normal") {
          const b = rand(20), keep = mode === "advantage" ? Math.max(a, b) : Math.min(a, b);
          groups.push({ sides, value: keep });
          discarded.push({ sides, value: keep === a ? b : a });
        } else groups.push({ sides, value: a });
      }
    } else modifier += sign * Number(t);
  }
  const total = groups.reduce((s, g) => s + g.value, 0) + modifier;
  return { groups, discarded, modifier, total, text: `${text}: ${total}` };
}

const rollLocal = (expression) => (diceModule?.rollLocal ? diceModule.rollLocal(expression) : fallbackRollLocal(expression));

async function loadDice() {
  try {
    diceModule = await import("/static/tabletop/dice3d.js?v=rollreason1");
    tray = diceModule.createDiceTray({ theme: diceModule.THEMES?.[currentTheme()] || diceModule.THEMES?.crimson });
  } catch (error) {
    diceModule = null;
    tray = null;
    console.warn("3D dice unavailable; rolling without animation.", error);
  }
}

// ------------------------------------------------------------------ theme
// The sheet follows the app style (Settings > Appearance; /static/appearance-boot.js). Its picker
// changes that shared style; the dice keep their own four skins, chosen to match.
function currentTheme() {
  const style = window.TianxiaAppearance?.current().style || "lacquer";
  return DICE_FOR_STYLE[style] || "crimson";
}

function applyTheme(name, persist) {
  const appearance = window.TianxiaAppearance;
  if (persist && appearance && name !== appearance.current().style) { appearance.setStyle(name); return; }
  $("theme-select").value = appearance?.current().style || "lacquer";
  if (tray && diceModule?.THEMES) tray.setTheme(diceModule.THEMES[currentTheme()] || diceModule.THEMES.crimson);
}

// ------------------------------------------------------------------ data
function indexButtons(buttons, layout) {
  state.buttons = Array.isArray(buttons) ? buttons : [];
  state.byId = new Map(state.buttons.map((b) => [b.id, b]));
  state.hidden = new Set(layout?.hidden || []);
  state.pinned = [...(layout?.pinned || [])];
}

const customButtons = () => state.buttons.filter((b) => b.source === "custom" || b.group === "custom");
const autoButtons = () => state.buttons.filter((b) => b.source !== "custom" && b.group !== "custom");
const isCombatish = (b) => b && (b.kind === "combat" || b.kind === "combo");

async function fetchJson(url, options) {
  let response;
  try { response = await fetch(url, options); }
  catch (_error) { throw new Error(playerError()); }
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const err = new Error(playerError({code: body?.error?.code, status: response.status}));
    err.body = body;
    err.status = response.status;
    throw err;
  }
  return body;
}

// ------------------------------------------------------------------ rendering: header and stats
function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function renderHeader() {
  const s = state.summary;
  document.title = `${s.name} · Character Sheet`;
  $("portrait-text").textContent = state.sheet.token_url ? "" : initials(s.name);
  showToken();
  $("char-name").textContent = s.name;
  const paths = s.path_summary || (s.paths && s.paths.length ? s.paths : [s.path]).filter(Boolean).join(" / ");
  $("char-sub").textContent = [`CL ${s.cultivation_level}`, paths, s.realm, state.actor?.ai_label || s.ai_label].filter(Boolean).join(" · ");
  const meta = $("char-meta");
  meta.replaceChildren(
    [s.species, s.size].filter(Boolean).join(" · "),
    s.concept ? h("span", { class: "concept" }, ` — ${s.concept}`) : null,
  );
  meta.title = s.concept || "";
}

// 2024 Carrying Capacity (owner 2026-09-26): the kit's weight against 15 x Strength, shown under Speed; past it, Speed
// is 5 ft in combat.
// The Fly line is empty unless the live actor flies; renderLive fills it (flight comes from the fight, not the sheet).
function walkingBox(speed, carrying) {
  const big = [String(speed ?? "—"), h("span", { class: "unit" }, "ft")];
  const fly = h("span", { class: "stat-fly", id: "walk-fly" });
  if (!carrying) return statBox({ label: "Walking", big, sub: fly, caption: "Speed" });
  const unweighed = (carrying.unweighed || []).length ? ` Not weighed: ${carrying.unweighed.join(", ")}.` : "";
  return statBox({ cls: carrying.over ? "is-over" : "", label: "Walking", big, sub: fly,
    caption: carrying.over ? "Over capacity: 5 ft" : `Speed · ${carrying.weight_lb}/${carrying.capacity_lb} lb`,
    title: `Carrying ${carrying.weight_lb} lb of ${carrying.capacity_lb} lb (15 x Strength).${unweighed}` });
}

// The compact Armor Class card (SOL192): the equation first, the full calculation under an expander.
function armorTipCard(breakdown, actor) {
  const model = TianxiaSheetViewModel.armorCard(breakdown, actor);
  return (doc, options) => renderTipCard(doc, model, options);
}

function statBox({ tag = "div", cls = "", label, big, sub, caption, buttonId, aria, title, tipCard, extra }) {
  const attrs = { class: `stat ${cls}`.trim(), title, tipCard };
  if (tag === "button") Object.assign(attrs, { type: "button", "data-button-id": buttonId, "aria-label": aria });
  return h(tag, attrs,
    tag === "button" && buttonId ? icon("d20", "roll-hint") : null,
    extra || null,
    h("span", { class: "stat-label" }, label),
    h("span", { class: "stat-big" }, big),
    sub || null,
    caption ? h("span", { class: "stat-caption" }, caption) : null,
  );
}

function acShield() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "ac-shape");
  svg.setAttribute("viewBox", "0 0 100 120");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = `<defs><linearGradient id="ac-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" class="stop-a"/><stop offset="1" class="stop-b"/></linearGradient></defs>
    <path class="outer" vector-effect="non-scaling-stroke" d="M50 1 L97 12 L97 58 C97 88 74 108 50 119 C26 108 3 88 3 58 L3 12 Z"/>
    <path class="inner" vector-effect="non-scaling-stroke" d="M50 7 L91 16.5 L91 58 C91 84 71 101.5 50 111.5 C29 101.5 9 84 9 58 L9 16.5 Z"/>`;
  return svg;
}

function renderStats() {
  const s = state.summary;
  const abilities = $("abilities");
  abilities.replaceChildren(...(s.abilities || []).map((a) => {
    const box = statBox({
      tag: "button", cls: `ability${a.ability === s.key_ability ? " is-key" : ""}`,
      label: a.ability, big: signed(a.modifier), buttonId: `check:${a.ability}`,
      aria: `${a.name} check, ${spoken(a.modifier)}, score ${a.score}. Roll.`,
      title: `${a.name}${a.ability === s.key_ability ? " (key ability)" : ""} — click to roll a check`,
    });
    box.append(h("span", { class: "stat-score" }, a.score));
    return box;
  }));

  const hpMax = s.hit_points?.maximum ?? 0;
  const vitals = $("vitals");
  vitals.replaceChildren(
    statBox({ label: "Proficiency", big: signed(s.proficiency_bonus), caption: "Bonus" }),
    walkingBox(s.speed_ft, state.sheet.carrying),
    statBox({ tag: "button", label: "Initiative", big: signed(s.initiative), caption: "Roll", buttonId: "roll:initiative",
      aria: `Initiative, ${spoken(s.initiative)}. Roll.`, title: "Click to roll initiative" }),
    statBox({ tag: "button", cls: "ac", label: "Armor", big: String(s.armor_class ?? "—"), caption: "Class",
      aria: "Armor Class. Show breakdown.", title: TianxiaSheetViewModel.armorBreakdown(s.armor_breakdown || {}, state.actor),
      tipCard: armorTipCard(s.armor_breakdown || {}, state.actor), extra: acShield() }),
    h("div", { class: "stat meter-box hp", id: "hp-box", role: "group", "aria-label": "Hit points" },
      h("div", { class: "meter-head" },
        h("span", { class: "stat-label" }, "Hit Points"),
        h("span", { class: "meter-note", id: "hp-note" }, "Full")),
      h("div", { class: "hp-grid" },
        h("div", { class: "hp-cell" }, h("span", { class: "hp-cap" }, "Current"), h("span", { class: "hp-num", id: "hp-cur" }, hpMax)),
        h("span", { class: "hp-slash", "aria-hidden": "true" }, "/"),
        h("div", { class: "hp-cell" }, h("span", { class: "hp-cap" }, "Max"), h("span", { class: "hp-num", id: "hp-max" }, hpMax)),
        h("span", { class: "hp-rule", "aria-hidden": "true" }),
        h("div", { class: "hp-cell hp-temp", id: "hp-temp-cell" }, h("span", { class: "hp-cap" }, "Temp"), h("span", { class: "hp-num", id: "hp-temp" }, "—"))),
      h("div", { class: "meter", "aria-hidden": "true" }, h("span", { class: "meter-fill", id: "hp-fill" }), h("span", { class: "meter-temp", id: "hp-temp-fill" }))),
    h("div", { class: "stat height-box", id: "height-box", role: "group", "aria-label": "Height above the ground" },
      h("span", { class: "stat-label" }, "Height"),
      h("span", { class: "stat-big" }, h("span", { id: "height-num" }, "0"), h("span", { class: "unit" }, "ft")),
      h("span", { class: "stat-caption" }, "Above ground")),
  );
  vitals.querySelector(".ac")?.setAttribute("data-tip-click", "");
}

// Every cultivation pool, primary first (a two-Path character has two).
function resourcePools(s) {
  return s.resources?.length ? s.resources : s.resource ? [s.resource] : [];
}

// The one Resources list: the actor's live resources, then sheet pools with no live row (outside a fight).
// The primary sheet pool falls back to the live rows, as the old top panel did, so it is never listed twice.
function poolRows(s, actor) {
  const live = actor?.resources || [];
  const rows = live.map((r) => ({ ...r }));
  resourcePools(s).forEach((pool, i) => {
    if (live.some((r) => norm(r.display_name) === norm(pool.name))) return;
    if (i === 0 && live.length) return;
    rows.push({ name: pool.name, current: pool.maximum, maximum: pool.maximum });
  });
  return rows;
}

function renderSaves() {
  const s = state.summary;
  const names = Object.fromEntries((s.abilities || []).map((a) => [a.ability, a.name]));
  $("saves").replaceChildren(...(s.saves || []).map((row) => h("button", {
    type: "button", class: "save-btn", "data-button-id": `save:${row.ability}`,
    "aria-label": `${names[row.ability] || row.ability} saving throw, ${spoken(row.bonus)}. Roll.`,
    title: `${names[row.ability] || row.ability} save — click to roll`,
  }, h("span", null, row.ability), h("span", { class: "chip" }, signed(row.bonus)))));
}

function renderSenses() {
  const p = state.summary.passive || {};
  const rows = [["perception", "Perception", "WIS"], ["investigation", "Investigation", "INT"], ["insight", "Insight", "WIS"]];
  $("senses").replaceChildren(...rows.map(([key, name, ab]) => h("div", { class: "sense" },
    h("span", { class: "sense-num" }, p[key] ?? "—"),
    h("span", { class: "sense-name" }, "Passive ", h("strong", null, name), ` (${ab})`))));
}

function defenseTip(row) {
  // Each defence says where it comes from, and a temporary one says
  // when it ends (owner 2026-10-12: the Defences card's new sections).
  const parts = [row.source ? `from ${row.source}` : "innate to this creature"];
  if (row.until) parts.push(row.until);
  if (row.note) parts.push(row.note);
  return parts.join(" — ");
}

function renderDefenses() {
  const s = state.summary;
  const actor = state.actor;
  // A choice for an ability (the talents or augments its next use carries) is not a condition to show.
  // The table sends only what its hover card shows, with each one's tone (buff green, debuff red, bookkeeping grey).
  const conditions = (actor?.conditions || []).filter((c) => !/\.(shaping|augments|dropped_item|unburdened|[a-z_]+_(?:choice|pick)|destruction_(?:blast|tether)_type|open_the_gate)$/.test(String(c?.condition_id || "")));
  const blocks = [
    h("div", { class: "def-block" },
      h("div", { class: "def-label" }, "Conditions"),
      conditions.length
        ? h("div", { class: "cond-list" }, conditions.map((c) => h("span", { class: `cond ${c.tone || "harmful"}`, title: c.text || "" },
            c.display_name || c.condition_id || String(c))))
        : h("div", { class: "def-note" }, state.connected ? "None" : "None — no fight in progress")),
  ];
  // What the creature resists, is vulnerable to and is immune to: the
  // same defence rows the fight's damage resolution weighs, each with
  // the ability or condition that grants it, temporary ones included.
  // A section with nothing to list stays hidden.
  const defenses = actor?.damage_defenses || {};
  // Flat damage reductions are their own group: a Resistance-piercing attack does not bypass them.
  for (const [key, label, tone] of [["resistances", "Resistances", "beneficial"],
                                     ["vulnerabilities", "Vulnerabilities", "harmful"],
                                     ["immunities", "Immunities", "beneficial"],
                                     ["reductions", "Damage reduction", "beneficial"]]) {
    const rows = defenses[key] || [];
    if (!rows.length) continue;
    blocks.push(h("div", { class: "def-block" },
      h("div", { class: "def-label" }, label),
      h("div", { class: "cond-list" }, rows.map((row) => h("span", { class: `cond ${tone}`, title: defenseTip(row) },
        row.damage_type || row.condition || String(row))))));
    if (key === "resistances") {
      blocks.push(h("div", { class: "def-note" }, "A particular attack may ignore or pierce these — checked when that attack lands."));
    }
  }
  const rows = poolRows(s, actor);
  if (rows.length) {
    blocks.push(h("div", { class: "def-block" }, h("div", { class: "def-label" }, "Resources"),
      rows.map((r) => {
        const max = Number(r.maximum) || 0, cur = Number(r.current ?? max) || 0;
        const hint = cur >= max ? "Full" : cur <= 0 ? "Empty" : `${max - cur} spent`;
        return h("div", { class: "res-row", tabindex: "0", title: resourceText(r, state.buttons) },
          h("span", null, r.display_name || r.name || r.resource_id, h("span", { class: "res-hint" }, hint)),
          h("b", null, `${r.current ?? "?"} / ${r.maximum ?? "?"}`),
          h("div", { class: "meter" }, h("span", { class: "meter-fill res", style: { width: `${100 * clamp01(max ? cur / max : 0)}%` } })));
      })));
  }
  if (s.starting_loadout?.note) {
    blocks.push(h("div", { class: "def-block" }, h("div", { class: "def-label" }, "Starting equipment"),
      h("p", { class: "def-note" }, s.starting_loadout.note)));
  }
  if (s.armor_note) {
    const open = $("ac-details")?.open ? true : null;
    blocks.push(h("details", { class: "def-block def-details", id: "ac-details", open },
      h("summary", null, h("span", { class: "def-label" }, `Armor Class ${actor?.armor_class ?? s.armor_class}`)), h("p", { class: "def-note" }, s.armor_note)));
  }
  $("defenses").replaceChildren(...blocks);
}

function renderSkills() {
  $("skills").replaceChildren(...(state.summary.skills || []).map((row) => {
    const id = `skill:${norm(row.skill).replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}`;
    const buttonId = state.byId.has(id) ? id : (state.buttons.find((b) => b.group === "skills" && b.label === row.skill)?.id || id);
    const prof = row.proficiency || "none";
    const profText = prof === "expertise" ? "Expertise" : prof === "proficient" ? "Proficient" : "Not proficient";
    return h("button", {
      type: "button", class: `skill-row prof-${prof}`, "data-button-id": buttonId,
      "aria-label": `${row.skill} (${row.ability}), ${profText}, ${spoken(row.bonus)}. Roll.`, title: `${row.skill} — ${profText}`,
    }, h("span", { class: "prof-dot" }), h("span", { class: "skill-ab" }, row.ability), h("span", { class: "skill-name" }, row.skill),
    h("span", { class: "chip" }, signed(row.bonus)));
  }));
}

// ------------------------------------------------------------------ actions tab
function groupButtons(key) {
  // A weapon stack is drawn once per kind; its other physical copies keep their ids in `copies`
  // for the table/AI/saves (SHEETHANDS1: no "Biao Qiang (Javelin) (copy 2)" row).
  const items = state.buttons.filter((b) => b.group === key && !b.copy_of);
  // A hidden ability still shows its own row when a VISIBLE picker or talent/augment (`parent`) sits under
  // it: hiding it would leave that choice indented under nothing (owner 2026-10-13, "Cultivate Blossom" and
  // "Fragrance" vanished from the sheet while their own choices stayed, orphaned under an unrelated row).
  // A child that is itself hidden names no requirement: hiding the whole family (the ability and every row
  // under it) keeps the whole family hidden, not just the children (review r1, finding 1).
  const neededAsParent = new Set(items.filter((b) => b.parent && !state.hidden.has(b.id)).map((b) => b.parent));
  return items.filter((b) => !state.hidden.has(b.id) || neededAsParent.has(b.combat?.source_definition_id));
}

function renderFilters() {
  // Attacks are counted as weapons: that is how many rows the section now shows (ATTACKLIST1).
  const counts = Object.fromEntries(GROUPS.map((g) => [g.key, g.key === "attacks"
    ? groupAttackRows(groupButtons(g.key)).length
    : groupVariantRows(groupButtons(g.key)).length]));
  const total = GROUPS.reduce((n, g) => n + counts[g.key], 0);
  const pill = (filter, text, n) => h("button", {
    type: "button", class: "filter", "aria-pressed": state.filter === filter ? "true" : "false", "data-filter": filter,
  }, text, h("span", { class: "n" }, n));
  $("action-filters").replaceChildren(pill("all", "All", total), ...GROUPS.map((g) => pill(g.filter, g.pill, counts[g.key])));
}

function hitCell(d) {
  const cells = [];
  if (d.to_hit) cells.push(h("span", { class: "chip", title: "Attack bonus" }, d.to_hit.replace("-", "−")));
  if (d.save) {
    const m = /DC\s*(\d+)\s*([A-Z]{3})?/i.exec(d.save);
    cells.push(m
      ? h("span", { class: "chip chip-save", title: `${d.save} saving throw` }, h("span", { class: "chip-cap" }, (m[2] || "SAVE").toUpperCase()), h("span", { class: "chip-dc" }, m[1]))
      : h("span", { class: "chip chip-sm" }, d.save));
  }
  if (d.attacks && d.attacks > 1) cells.push(h("span", { class: "x" }, `×${d.attacks} attacks`));
  return cells.length ? cells : [h("span", { class: "none" }, "—")];
}

function stepText(step) {
  if (step.roll) return step.label && step.label !== step.roll ? `${step.label} ${step.roll}` : step.roll;
  return state.byId.get(step.button)?.label || step.button;
}

function modifierRowFor(buttonId) {
  return (state.actor?.attack_modifier_rows || state.sheet?.attack_modifier_rows || []).find(row => row.button_id === buttonId);
}

function modifierRowText(b, row) {
  return `+ ${b.label}: ${row?.on ? "On" : "Off"} · turn ${row?.on ? "off" : "on"}`;
}

function modifierRowNode(buttonId) {
  const list = $("action-list");
  if (!list) return null;
  return [...list.querySelectorAll("[data-button-id]")].find(node => node.dataset.buttonId === buttonId) || null;
}

// Update one rider row after its setting was saved (or the table sent new live state). Only this row's On/Off
// text and its own dropdowns are touched: no other row, section, scroll position, search or filter moves.
function syncModifierRow(buttonId) {
  const b = state.byId.get(buttonId);
  const node = b?.attack_modifier ? modifierRowNode(buttonId) : null;
  if (!node) return false;
  const row = modifierRowFor(buttonId);
  node.textContent = modifierRowText(b, row);
  const holder = node.parentElement;
  for (const selector of row?.selectors || []) {
    const key = riderKey(b.id, selector.field);
    const select = holder ? riderControls(holder, key)[0] : null;
    if (!select) continue;
    const storedKey = select.dataset.riderKey || key;
    // A row drawn before this fight connected carries no (or an old) scope. Adopt the live one so the next pick,
    // its save receipt and this sync all address the same control; keep reading a pick already queued under the
    // old key so an unsaved choice is not flickered back by the server's older value.
    if (storedKey !== key) select.setAttribute("data-rider-key", key);
    const authoritative = selector.options.find(option => option.value === selector.current)?.button_id;
    const wanted = presetQueue.value(storedKey, authoritative);
    const shown = [...(select.options || [])].map(option => [option.value, option.textContent]);
    const fresh = selector.options.map(option => [String(option.button_id), String(option.label)]);
    if (shown.length !== fresh.length || shown.some((pair, index) => pair[0] !== fresh[index][0] || pair[1] !== fresh[index][1])) {
      select.replaceChildren(...selector.options.map(option => h("option", {value: option.button_id}, option.label)));
    }
    select.value = wanted ?? "";
  }
  return true;
}

function syncModifierRows(buttonIds) {
  for (const id of new Set(buttonIds)) syncModifierRow(id);
}

// The table's "actor" message carries the live active marks, modifier rows and carried weapon copies.
// Apply those where they are drawn instead of rebuilding the list, so a No-action setting picked from the
// sheet leaves the sheet where it was; only a changed weapon count (one was thrown) redraws the list.
function refreshActionRowsInPlace() {
  syncModifierRows(state.buttons.filter(b => b.attack_modifier).map(b => b.id));
  if (weaponCopySignature() !== state.copySignature) { renderActions(); return; }
  applyLegal();
}

function actionRow(b) {
  const d = b.detail || {};
  if (b.attack_modifier) {
    const row = modifierRowFor(b.id);
    const riderTip = [describe(b), additionalRuleText(describe(b), b.modifier?.description)].filter(Boolean).join("\n\n");
    return h("div", {class: "arow arow-variant arow-rider", title: riderTip, tipCard: actionTipCard(b, {rules: riderTip})},
      h("button", {type: "button", "data-button-id": b.id}, modifierRowText(b, row)),
      h("span", null, `${d.cost || "Free"} on a hit; a miss costs nothing.`),
      ...(row?.selectors || []).map(selector => h("label", null, selector.label,
        h("select", {"data-rider-select": "true", "data-rider-key": riderKey(b.id, selector.field),
          "aria-label": `${state.byId.get(b.variant_of)?.label || "This attack"} — ${b.label}: ${selector.label}`},
          ...selector.options.map(option => h("option", {value: option.button_id,
            selected: option.button_id === presetQueue.value(riderKey(b.id, selector.field),
              selector.options.find(o => o.value === selector.current)?.button_id)}, option.label))))));
  }
  if (b.kind === "combo") {
    const steps = b.steps || [];
    return h("button", {
      type: "button", class: "arow arow-combo", "data-button-id": b.id, style: b.color ? { "--tint": b.color } : null,
      title: steps.map(stepText).join(" → "),
    },
    h("span", { class: "arow-name" }, h("span", { class: "arow-label" }, b.label),
      h("span", { class: "arow-sub" }, h("span", { class: "eco" }, "Combo"), ` · ${steps.length} step${steps.length === 1 ? "" : "s"}`)),
    h("span", { class: "arow-range" }, h("span", { class: "none" }, "—")),
    h("span", { class: "arow-hit" }, h("span", { class: "none" }, "—")),
    h("span", { class: "arow-dmg" }, steps.map(stepText).join(" → ")),
    h("span", { class: "arow-flags" }));
  }
  const sub = [h("span", { class: "eco" }, b.shape ? `${b.shape.zone_name} talent` : b.augment ? "Augment" : economyLabel(b.economy) || GROUP_NAMES[b.group] || "")];
  if (d.cost) sub.push(` · ${d.cost}`);
  const target = b.combat?.target_kind;
  // An area talent (owner 2026-09-27): a free choice for the next area, not an action of its own.
  if (b.shape) sub.push(` · choose and cast${b.shape.default ? " · default" : ""}`);
  else if (b.augment) sub.push(" · turn on or off · any number");
  else if (target) sub.push(` · ${targetLabel(target)}`);
  const gm = Number(d.gm_riders) || 0;
  // A choice made by an optional modifier (owner 2026-09-25): "Water Lash + Water Whip" sits under Water Lash.
  const mod = b.variant_of ? b.modifier || {} : null;
  if (mod?.precondition) sub.push(` · only ${mod.precondition.replace(/^if /i, "if ")}`);
  const extraRules = mod ? additionalRuleText(describe(b), mod.description) : "";
  const modText = mod ? [extraRules ? `${mod.name}: ${plainRules(extraRules)}` : "", mod.precondition ? `Only when: ${mod.precondition}` : ""] : [];
  return h("button", {
    type: "button", class: `arow${mod ? " arow-variant" : ""}`, "data-button-id": b.id,
    title: actionHoverText(b, {rules: describe(b), extra: modText, note: gm ? partialNote(gm) : ""}),
    tipCard: actionTipCard(b, {rules: describe(b), extra: modText, note: gm ? partialNote(gm) : ""}),
  },
  h("span", { class: "arow-name" }, h("span", { class: "arow-label", ...(b.copies ? {"data-copy-label": "1"} : {}) },
    mod && !b.variant ? `+ ${mod.name}` : (b.copies ? weaponCopyText(b) : b.label)), h("span", { class: "arow-sub" }, sub)),
  h("span", { class: "arow-range" }, d.range || h("span", { class: "none" }, "—"), d.area ? h("small", null, d.area) : null),
  h("span", { class: "arow-hit" }, hitCell(d)),
  h("span", { class: "arow-dmg" }, d.damage || h("span", { class: "none" }, "—")),
  h("span", { class: "arow-flags" }, gm ? h("span", { class: "badge badge-gm", "aria-label": partialNote(gm) }, "Partial") : null));
}

// ------------------------------------------------------------------ ATTACKLIST1: attacks grouped by weapon
// Owner-approved (feedback desk FD-18): the ATTACKS list was one flat row per weapon copy per mode. A Long Tongling
// carrying a Jian, a Xi Jian and four javelins filled about fifty rows -- "Biao Qiang (Javelin) attack", "...
// thrown", "Batter: ... thrown", "Batter: ... thrown + Brutal Strike", "Batter: ...", each of the javelin ones
// saying "(one attack; choose the rest)" -- and no weapon could be picked out of them. Now there is one row per
// weapon: identical copies merge (x4) and the weapon's modes and add-ons are chips under it, each chip showing only
// the numbers that differ from the weapon's plain attack.
//
// The reading lives in attack-groups.js, which the table's action bar uses too, so both surfaces say the same
// thing. Presentation only: a chip carries the exact button id the server compiled (no id is rebuilt or renamed
// here), so legality, cost, the server's reasons and the table's answer are exactly what they were.

function attackStateKey(family) {
  return (state.actor?.match_id || "") + "|" + family;
}

// How many attacks of this weapon this sheet has seen sent since its Attack action was last free. It counts this
// sheet's own clicks only (a reload forgets), so a group with a single attack never counts.
function attackSpent(family) {
  return Number((state.attackSpent instanceof Map ? state.attackSpent.get(attackStateKey(family)) : 0) || 0);
}

function noteAttackSent(b) {
  const source = String(b?.combat?.source_definition_id || b?.id || "").replace(/^act:/, "");
  if (!source) return;
  const read = readAttack(source);
  if (!read.rest && !read.begin) { state.attackSpent?.delete(attackStateKey(read.family)); return; }
  if (!(state.attackSpent instanceof Map)) state.attackSpent = new Map();
  const attacks = Math.max(1, Number(b?.detail?.attacks) || 1);
  const sent = read.begin ? 1 : attackSpent(read.family) + 1;
  state.attackSpent.set(attackStateKey(read.family), Math.min(attacks, sent));
}

function attackUsable(b) {
  if (state.connected !== true) return true;
  return state.legal.has(b.id) && !unavailableReason(b.id);
}

function attackChipHover(b) {
  const mod = b.variant_of ? b.modifier || {} : null;
  const extraRules = mod ? additionalRuleText(describe(b), mod.description) : "";
  const extra = mod ? [extraRules ? mod.name + ": " + plainRules(extraRules) : "", mod.precondition ? "Only when: " + mod.precondition : ""] : [];
  return {rules: describe(b), extra};
}

function attackChipNode(group, chip) {
  const b = chip.row || {};
  const hover = attackChipHover(b);
  const reason = chip.available ? "" : unavailableReason(chip.rowId);
  return h("button", {
    type: "button",
    class: "attack-chip" + (chip.kind === "addon" ? " attack-chip-addon" : "") + (chip.available ? "" : " is-illegal"),
    "data-button-id": chip.rowId || "",
    "data-attack-chip": chip.key,
    "aria-label": [group.name + ": " + chip.label, chip.detail, chip.available ? "" : "not available"].filter(Boolean).join(", "),
    title: actionHoverText(b, {...hover, note: reason ? "Not available: " + reason : ""}),
    tipCard: actionTipCard(b, hover),
  },
  h("span", {class: "attack-chip-label"}, chip.label),
  chip.detail ? h("span", {class: "attack-chip-detail"}, chip.detail) : null,
  chip.ask ? h("span", {class: "attack-chip-more", "aria-hidden": "true"}, "choose") : null);
}

// "Use all N attacks on this, or choose each?": asked on the first click only when the Attack action really holds
// more than one attack and both answers exist (combat/ext/special_attacks.py compiles the "choose each" start row
// only for a character with an Extra Attack).
function attackAskNode(group, chip) {
  const ask = chip.ask;
  return h("div", {class: "attack-ask", role: "group", "aria-label": "How to use the attacks of " + group.name},
    h("p", {class: "attack-ask-q"}, "You have " + ask.attacks + " attacks with " + group.name + ". Use them all on this one, or choose each attack?"),
    h("button", {type: "button", class: "attack-ask-btn attack-ask-all", "data-button-id": ask.allRow.id, "data-attack-answer": "all"},
      h("span", {class: "attack-ask-label"}, "All " + ask.attacks + " on this"),
      h("span", {class: "attack-ask-note"}, "Every attack this turn lands on this one target")),
    h("button", {type: "button", class: "attack-ask-btn attack-ask-each", "data-button-id": ask.eachRow.id, "data-attack-answer": "each"},
      h("span", {class: "attack-ask-label"}, "Choose each"),
      h("span", {class: "attack-ask-note"}, "Start the Attack action and pick every attack as it comes")),
    h("button", {type: "button", class: "attack-ask-cancel", "data-attack-ask": "cancel"}, "Cancel"));
}

function attackGroupStats(view) {
  const d = (view.chips[0]?.row || {}).detail || {};
  const bits = [];
  if (d.to_hit) bits.push(String(d.to_hit).replace("-", "\u2212") + " to hit");
  if (d.save) bits.push(String(d.save));
  if (d.damage) bits.push(String(d.damage));
  return bits.join(" \u00b7 ");
}

function paintAttackGroup(record) {
  const group = record.group;
  const view = attackGroupView(group, {usable: attackUsable, spent: attackSpent(group.key)});
  record.view = view;
  const askKey = state.attackAsk && state.attackAsk.group === group.key ? state.attackAsk.chip : "";
  const askChip = view.chips.find(chip => chip.key === askKey) || null;
  const copies = view.copies > 1
    ? (view.copiesUsed === view.copies ? "\u00d7" + view.copies : "\u00d7" + view.copiesUsed + " of " + view.copies)
    : "";
  const left = view.attacks <= 1 ? "" : !view.leftKnown ? "attacks left"
    : view.left >= view.attacks ? view.left + " attacks left" : view.left + " of " + view.attacks + " attacks left";
  const switches = record.children.map(b => b.id + ":" + (modifierRowFor(b.id)?.on ? 1 : 0));
  const signature = [view.name, copies, left, askKey, attackGroupStats(view), switches.join(","),
    ...view.chips.map(chip => [chip.key, chip.rowId, chip.label, chip.detail, chip.available ? 1 : 0, chip.ask ? 1 : 0].join(":"))].join("|");
  if (signature === record.signature) return view;
  record.signature = signature;
  const stats = attackGroupStats(view);
  record.node.replaceChildren(...[
    h("div", {class: "attack-head"},
      h("span", {class: "attack-name"}, view.name),
      copies ? h("span", {class: "attack-copies", title: "Identical copies still ready: " + view.copiesUsed + " of " + view.copies}, copies) : null,
      stats ? h("span", {class: "attack-stats"}, stats) : null,
      left ? h("span", {class: "attack-left"}, left) : null),
    h("div", {class: "attack-chips", role: "group", "aria-label": "Ways to attack with " + view.name},
      ...view.chips.map(chip => attackChipNode(group, chip))),
    askChip && askChip.ask ? attackAskNode(group, askChip) : null,
    // A talent that changes this weapon ("Heaven-Shaking Batter") is a switch per attack row in the engine, so it
    // keeps one small row each, under the weapon it changes.
    record.children.length
      ? h("div", {class: "attack-switches"}, ...record.children.map(b => h("div", {class: "arow-child"}, actionRow(b))))
      : null,
  ].filter(Boolean));
  return view;
}

// The click on a weapon's chip. True when the chip asked its question instead of pressing its button, so the caller
// leaves the click alone; false when the row's own handler must send the exact button the chip stands for.
function attackChipClick(chipNode) {
  const groupNode = chipNode && chipNode.closest ? chipNode.closest("[data-attack-group]") : null;
  const record = groupNode && state.attackGroups instanceof Map ? state.attackGroups.get(groupNode.dataset.attackGroup) : null;
  const chip = record ? (record.view?.chips || []).find(entry => entry.key === chipNode.dataset.attackChip) : null;
  if (!chip || !chip.ask) return false;
  const open = state.attackAsk && state.attackAsk.group === record.group.key && state.attackAsk.chip === chip.key;
  state.attackAsk = open ? null : {group: record.group.key, chip: chip.key};
  updateAttackGroups();
  return true;
}

function updateAttackGroups() {
  if (!(state.attackGroups instanceof Map)) return;
  for (const record of state.attackGroups.values()) paintAttackGroup(record);
}

// The ATTACKS section: one group node per weapon (or per non-weapon source), the rows that already sit under another
// row kept under the weapon they change, and anything left over still drawn so nothing can vanish.
function attackSectionNodes(items) {
  state.attackGroups = new Map();
  const groups = groupAttackRows(items);
  const families = new Set(groups.map(group => group.key));
  const children = new Map();
  const orphans = [];
  for (const b of items) {
    if (!b.parent) continue;
    const family = readAttack(String(b.parent).replace(/^act:/, "")).family;
    if (!families.has(family)) { orphans.push(b); continue; }
    if (!children.has(family)) children.set(family, []);
    children.get(family).push(b);
  }
  const nodes = groups.map(group => {
    const record = {group, children: children.get(group.key) || [], signature: ""};
    record.node = h("div", {class: "attack-group", "data-attack-group": group.key});
    paintAttackGroup(record);
    state.attackGroups.set(group.key, record);
    return record.node;
  });
  for (const b of orphans) nodes.push(h("div", {class: "arow-child"}, actionRow(b)));
  return nodes;
}

// Hover text (owner 2026-09-25): "when you hover over an action it should show the description of
// that action so the player can know what they are doing."  Rules text comes from the library.
function indexLibraryText(lib) {
  state.textByButton = new Map();
  state.textByName = new Map();
  state.digestByName = new Map();
  state.libraryById = new Map();
  const visit = (item) => {
    const text = layoutText(item.hover) || plainRules(item.text || item.summary);
    if (!text) return;
    if (item.button_id) state.textByButton.set(item.button_id, text);
    if (!state.textByName.has(norm(item.name))) state.textByName.set(norm(item.name), text);
    if (item.hover?.digest && !state.digestByName.has(norm(item.name))) state.digestByName.set(norm(item.name), item.hover.digest);
    if (item.id) state.libraryById.set(String(item.id), {name: item.name, text, digest: item.hover?.digest});
  };
  for (const g of lib?.groups || []) {
    for (const s of g.spheres || []) { visit(s); (s.entries || []).forEach(visit); }
    (g.entries || []).forEach(visit);
  }
}

function plainRules(text) {
  const lines = cleanRules(text).split("\n")
    .filter((line) => !/^\s*#{1,6}\s/.test(line))
    .map((line) => line.replace(/\*\*|`|^\s*[-*•]\s+/g, "").trim());
  const plain = lines.join("\n").replace(/\n{2,}/g, "\n").trim();
  return plain;
}

function describe(b) {
  const presented = layoutText(b.hover);
  if (presented) return uniqueRuleBlocks(presented);
  // A choice made by a plug-in ("Saint-Body Rebuke: Frame Advantage") has no text of its own: show its feature's
  // (owner 2026-09-29: foundation toggles had no description).
  const feature = b.label.includes(":") ? state.textByName?.get(norm(b.label.split(":")[0])) : "";
  const own = plainRules(b.description);
  const printed = state.textByButton?.get(b.id) || state.textByName?.get(norm(b.label)) || state.textByName?.get(norm(b.label.replace(/ attack$/i, ""))) || feature || "";
  return uniqueRuleBlocks(own && printed && own !== printed ? `${own}\n\n${printed}` : own || printed);
}

// Not a GM process: lines of rules text the engine cannot apply yet are skipped by the fight.
function partialNote(count) {
  return `Partly automated: the table runs the roll, damage and movement; ${count} extra effect line${count === 1 ? " isn't" : "s aren't"} automated yet and the fight skips ${count === 1 ? "it" : "them"}.`;
}

// Talents that change another ability (owner 2026-09-25): always-on ones are built into that ability,
// optional ones ("you may...") are their own choice under it on the Actions tab.
function modifierSection(rows, q) {
  const shown = rows.filter((r) => !q || norm(`${r.name} ${(r.targets || []).join(" ")}`).includes(q));
  if (!shown.length) return null;
  const how = (r) => r.status !== "applied"
    ? (r.not_automated_targets?.length ? `changes ${r.not_automated_targets.join(", ")} (not automated yet)` : r.status === "no matching ability" ? "you don't have the ability it changes" : "nothing it adds is automated yet")
    : r.applied?.length ? `always part of ${r.applied.join(", ")}` : `a choice under ${(r.targets || []).join(", ")}`;
  const card = (r) => h("div", { class: "fcard", role: "listitem", title: [r.name, state.textByName?.get(norm(r.name)) || ""].filter(Boolean).join("\n\n") },
    h("span", null, h("span", { class: "fcard-name" }, r.name), h("span", { class: "fcard-src" }, how(r))),
    h("span", { class: `badge badge-${r.status === "applied" ? "auto" : "gm"}` }, r.status === "applied" ? (r.applied?.length ? "Auto" : "Choice") : "Not yet"));
  return h("section", { class: "fgroup fgroup-mod", "aria-label": "Modifiers" },
    h("h3", { class: "agroup-title" }, "Modifiers", h("span", { class: "count" }, shown.length), h("span", { class: "note" }, "Talents that change another ability")),
    h("div", { class: "fgrid", role: "list" }, shown.map(card)));
}

// Every reaction the character has, automatic or not, so a player can see them all.
function reactionRows() {
  const f = state.sheet.features || {};
  const rows = [
    ...(f.automated_reactions || []).map((id) => ({ id, name: featureInfo(id).name, auto: true })),
    ...(f.gm_reactions || []).map((name) => ({ id: name, name: featureInfo(name).name, auto: false })),
  ].map((r) => {
    // The library entry with this id carries the printed name, rules and compact card (SOL192).
    const entry = state.libraryById?.get(String(r.id).split("#")[0]);
    return entry ? { ...r, name: entry.name || r.name, text: entry.text, digest: entry.digest } : r;
  });
  const how = r => r.auto ? "Fires by itself when its trigger happens." : "Not automated yet: the fight skips it.";
  return rows.map((r) => h("div", {
    class: "arow arow-static", role: "listitem",
    title: [r.name, r.text || state.textByName?.get(norm(r.name)) || "", how(r)].filter(Boolean).join("\n\n"),
    tipCard: actionTipCard({label: r.name, economy: "REACTION", hover: {digest: r.digest || state.digestByName?.get(norm(r.name))}},
      {rules: r.text || state.textByName?.get(norm(r.name)) || "", note: how(r)}),
  },
  h("span", { class: "arow-name" }, h("span", { class: "arow-label" }, r.name),
    h("span", { class: "arow-sub" }, h("span", { class: "eco" }, "Reaction"), r.auto ? " · fires automatically" : " · not automated yet")),
  h("span", { class: "arow-range" }, h("span", { class: "none" }, "—")),
  h("span", { class: "arow-hit" }, h("span", { class: "none" }, "—")),
  h("span", { class: "arow-dmg" }, r.auto ? "Automatic" : h("span", { class: "none" }, "Not automated yet")),
  h("span", { class: "arow-flags" })));
}

function actionGroupSection(g, items) {
  let note = null;
  if (g.key === "attacks") {
    const most = Math.max(0, ...items.map((b) => Number(b.detail?.attacks) || 0));
    if (most > 1) note = `Attacks per Action: ${most}`;
  }
  // Every reaction the character has sits here, next to the clickable ones (owner 2026-09-30: "nothing is being listed
  // under reactions" -- Opportunity Attack alone hid Flowing Response, Stamina Guard and the rest).
  const shownNames = new Set(items.map((b) => norm(b.label)));
  // An ability's option pickers sit indented under it (owner 2026-10-12: "Blossom: Medicinal Blossom (1 CP)" listed as its own row).
  // Owner-approved (ATTACKLIST1): the attacks list is grouped by weapon (attack-groups.js), not one flat row per copy
  // and per mode. Every other section keeps its rows and its indented choices.
  const rows = g.key === "attacks"
    ? attackSectionNodes(items)
    : g.key === "reactions"
      ? [...items.map(actionRow), ...reactionRows().filter((row) => !shownNames.has(norm(row.querySelector(".arow-label")?.textContent || "")))]
      : renderVariantGroups(document, groupOptionRows(items, (b) => b.combat?.source_definition_id, (b) => b.parent)
          .map(({group, children}) => ({...group, optionChildren: children})), row => h("div", null,
          actionRow(row),
          ...renderVariantGroups(document, row.optionChildren, child => h("div", {class: "arow-child"}, actionRow(child)))));
  // A grouped section has no columns to head: each weapon says its own numbers on its own row (ATTACKLIST1).
  const counted = g.key === "attacks" ? (state.attackGroups?.size ?? 0) : rows.length;
  const body = rows.length
    ? [g.key === "attacks" ? null : h("div", { class: "arow-head", "aria-hidden": "true" }, h("span", null, "Name"), h("span", null, "Range"), h("span", null, "Hit / DC"), h("span", null, g.key === "custom" ? "Steps" : g.key === "reactions" ? "Damage / How" : "Damage"), h("span")),
      ...rows].filter(Boolean)
    : [h("p", { class: "empty" }, g.key === "reactions" ? reactionsNote() : g.key === "custom" ? "No combos yet — use Edit buttons to build one." : "Nothing here.")];
  return h("section", { class: "agroup", "aria-label": g.title },
    h("h3", { class: "agroup-title" }, g.title, h("span", { class: "count" }, counted), note ? h("span", { class: "note" }, note) : null),
    body);
}

function reactionsNote() {
  const auto = (state.sheet.features?.automated_reactions || []).map((id) => featureInfo(id).name);
  return auto.length
    ? `No manual reactions. The table triggers these automatically: ${auto.join(", ")}.`
    : "No reactions to click.";
}

function renderActions() {
  renderFilters();
  const s = state.summary;
  $("technique-line").replaceChildren(
    h("span", null, "Technique attack ", h("b", null, signed(s.technique_attack_bonus))),
    h("span", null, "Technique save ", h("b", null, `DC ${s.technique_save_dc ?? "—"}`)),
    h("span", null, "Key ability ", h("b", null, s.key_ability || "—")),
    h("span", null, "Proficiency ", h("b", null, signed(s.proficiency_bonus))),
  );
  renderPowering();
  renderReactions();
  renderCompanions();
  const groups = state.filter === "all" ? GROUPS : GROUPS.filter((g) => g.filter === state.filter);
  const sections = groups
    .map((g) => [g, groupButtons(g.key)])
    .filter(([g, items]) => items.length || state.filter !== "all" || g.key === "reactions")
    .map(([g, items]) => actionGroupSection(g, items));
  $("action-list").replaceChildren(...sections);
  state.copySignature = weaponCopySignature();
  applyLegal();
}

// "Which pool pays" (owner 2026-09-25, Q19): only a multi-Path character has anything to choose.
// The picker is the live source of the selected pool after the first edit (optimistic); before
// that, the dropdowns read straight off the compiled sheet. A single "Set all to" control lets a
// player push every technique onto one pool at once -- the common case when a fight is set up.
function poweringChoices() {
  const powering = state.sheet.powering || { pools: [], choices: {} };
  const source = (poweringPicker && poweringPicker.choices) || powerChoiceFallback(powering);
  return { pools: powering.pools || [], entries: Object.entries(powering.choices || {}), view: source };
}

function powerChoiceFallback(powering) {
  return Object.fromEntries(Object.entries(powering.choices || {}).map(([id, info]) => [id, info.pool]));
}

function renderPowering() {
  const { pools, entries, view } = poweringChoices();
  const panel = $("powering-panel");
  if (!entries.length) { panel.replaceChildren(); return; }
  const wasOpen = $("powering-details")?.open ?? true;
  const row = ([actionId, info]) => h("div", { class: "powering-row" },
    h("span", null, info.name),
    h("select", {
      class: "input powering-select", dataset: { actionId }, "aria-label": `Which pool pays for ${info.name}`,
    }, ...pools.map((pool) => h("option", { value: pool, selected: pool === (view[actionId] || info.pool) || null }, pool))));
  panel.replaceChildren(h("details", { class: "def-block def-details", id: "powering-details", open: wasOpen || null },
    h("summary", null, h("span", { class: "def-label" }, "Which pool pays")),
    h("div", { class: "powering-rows" },
      h("div", { class: "powering-setall" }, h("span", { class: "def-label" }, "Set all to:"),
        ...pools.map((pool) => h("button", {
          type: "button", class: "btn setall-btn", dataset: { setall: pool },
          "aria-label": `Set every technique to pay from ${pool}`,
        }, pool))),
      ...entries.map(row)),
    h("p", { class: "def-note" }, "Applies to fights started after this is saved; a fight already under way keeps the bundle it began with.")));
}

// Reactions (owner 2026-09-26): Auto, or the character's own order of importance with some turned off.
function renderReactions() {
  const plan = state.sheet.reaction_plan || { mode: "auto", order: [], off: [], choices: [] };
  const panel = $("reactions-panel");
  const choices = plan.choices || [];
  if (!choices.length) { panel.replaceChildren(); return; }
  const wasOpen = $("reactions-details")?.open ?? true;
  const byId = Object.fromEntries(choices.map((row) => [row.id, row]));
  const custom = plan.mode === "custom";
  const ask = plan.mode === "ask";
  const mode = h("select", { class: "input reaction-mode", "aria-label": "How your Reaction is used" },
    h("option", { value: "auto", selected: custom || ask ? null : true }, "Auto (recommended)"),
    h("option", { value: "custom", selected: custom || null }, "My order"),
    h("option", { value: "ask", selected: ask || null }, "Ask me"));
  const ordered = [...(plan.order || []), ...(plan.off || [])].filter((id) => byId[id]);
  const off = new Set(plan.off || []);
  const rows = custom ? ordered.map((id, index) => h("div", { class: "powering-row reaction-row" + (off.has(id) ? " is-off" : "") },
    h("span", null, h("b", null, off.has(id) ? "—" : `${index + 1}.`), " ", byId[id].name,
      h("small", { class: "muted" }, byId[id].when ? ` · ${byId[id].when}` : "")),
    h("span", { class: "reaction-tools" },
      h("button", { type: "button", class: "btn reaction-move", dataset: { id, step: "-1" }, disabled: index === 0 || null,
                    "aria-label": `Move ${byId[id].name} up` }, "↑"),
      h("button", { type: "button", class: "btn reaction-move", dataset: { id, step: "1" }, disabled: index === ordered.length - 1 || null,
                    "aria-label": `Move ${byId[id].name} down` }, "↓"),
      h("label", null, h("input", { type: "checkbox", class: "reaction-use", dataset: { id }, checked: off.has(id) ? null : true }), " use")))) : [];
  // Manual seats choose the mode when triggered. Presets belong to Auto/My order.
  const menus = choices.filter((row) => !ask && (row.options || []).length > 1).map((row) => h("div", { class: "powering-row reaction-row" },
    h("span", null, row.name, h("small", { class: "muted" }, " · choose one")),
    h("select", { class: "input powering-select reaction-option", dataset: { id: row.id }, "aria-label": `${row.name}: option` },
      ...row.options.map((label, index) => h("option", { value: String(index), selected: index === row.option || null }, label)))));
  panel.replaceChildren(h("details", { class: "def-block def-details", id: "reactions-details", open: wasOpen || null },
    h("summary", null, h("span", { class: "def-label" }, "Reactions")),
    h("div", { class: "powering-rows" }, h("div", { class: "powering-row" }, h("span", null, "Use my Reaction by"), mode), ...rows, ...menus),
    h("p", { class: "def-note" }, ask
      ? "When you play this character at the table, the fight stops whenever one of its reactions can be used, and you " +
        "choose Use or Pass. When the AI plays it, it reacts as Auto. Applies to fights started after this is saved."
      : custom
      ? "Most important first. When a reaction's moment comes, it waits if one higher on the list can still answer the same " +
        "attack (a hit, the damage); if that one can't (no stamina left, damage too small), the lower one fires. " +
        "Unticked reactions are never used; free triggers still happen. A reaction that answers only your marked creature " +
        "keeps your Reaction for it (while it stands) from those ranked below it. Applies to fights started after this is saved."
      : "Auto uses a reaction when its trigger comes up, but keeps your Reaction for a damage soak or reduction (like Stamina " +
        "Guard) instead of spending it on one that fires before the attack roll or only strikes back. While a creature bearing " +
        "your mark stands, a reaction that answers only that creature keeps your Reaction for it. Choose My order to rank " +
        "them yourself. Applies to fights started after this is saved.")));
}

// Companions (owner 2026-09-27): how many of its summoned creatures the character brings, and a Tamer's beasts.
function renderCompanions() {
  const plan = state.sheet.summons || { groups: [], tamer: false };
  const panel = $("companions-panel");
  const brought = (plan.groups || []).filter((row) => row.arrives !== "action" && row.max > 0);
  const rides = "mount" in plan;  // a Rider Package: the steed it starts the fight on (combat/ext/mounts.py)
  if (!brought.length && !plan.tamer && !rides) { panel.replaceChildren(); return; }
  const wasOpen = $("companions-details")?.open ?? true;
  const counts = brought.map((row) => h("div", { class: "powering-row" },
    h("span", null, row.name),
    h("select", { class: "input companion-count", dataset: { group: row.group }, "aria-label": `How many: ${row.name}` },
      ...Array.from({ length: row.max + 1 }, (_, n) => h("option", { value: String(n), selected: n === row.count || null }, String(n))))));
  const picked = plan.picked || [];
  const beasts = plan.tamer ? Array.from({ length: plan.beast_limit || 1 }, (_, index) => h("div", { class: "powering-row" },
    h("span", null, `Beast ${index + 1}`),
    h("select", { class: "input companion-beast", "aria-label": `Beast ${index + 1}` },
      h("option", { value: "", selected: picked[index] ? null : true }, "—"),
      ...(plan.beasts || []).map((row) => h("option", { value: row.key, selected: picked[index] === row.key || null }, `${row.name} (CR ${row.cr})`))))) : [];
  const steed = rides ? [h("div", { class: "powering-row" },
    h("span", null, "Mount"),
    h("select", { class: "input companion-mount", "aria-label": "The mount the character starts the fight on" },
      h("option", { value: "", selected: plan.mount ? null : true }, "None (on foot)"),
      ...(plan.mounts || []).map((row) => h("option", { value: row.key, selected: plan.mount === row.key || null }, row.name))))] : [];
  panel.replaceChildren(h("details", { class: "def-block def-details", id: "companions-details", open: wasOpen || null },
    h("summary", null, h("span", { class: "def-label" }, "Companions")),
    h("div", { class: "powering-rows" }, ...steed, ...counts, ...beasts),
    h("p", { class: "def-note" }, "These are with the character when a fight begins, on its side, and act right after its turn. A Bonus " +
      "Action commands a group (tamed beasts need no command); uncommanded, they Dodge. A creature an ability calls, like the " +
      "Painted Beast, comes when that ability is used. Numbers are in combat/rules/summons.json. Applies to fights started after this is saved.")));
}

// Rename for the table and fights (owner 2026-09-27: a rename saved while finalizing never reached the character).
async function renameCharacter() {
  const current = state.summary?.name || "";
  const name = window.prompt("Name at the table (empty = the sheet's own name):", current);
  if (name === null) return;
  try {
    const session = await fetchJson("/api/session");
    await fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/name`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token },
      body: JSON.stringify({ display_name: name.trim() || null }),
    });
    await reloadSheet();
    toast("ok", "Renamed", "New fights use the new name.", 2200);
  } catch (error) {
    toast("error", "Not renamed", error.message, 3200);
  }
}

async function saveCompanions() {
  const panel = $("companions-panel");
  const counts = Object.fromEntries([...panel.querySelectorAll(".companion-count")].map((el) => [el.dataset.group, Number(el.value)]));
  const beasts = [...panel.querySelectorAll(".companion-beast")].map((el) => el.value).filter(Boolean);
  const tamer = Boolean((state.sheet.summons || {}).tamer);
  const mountPick = panel.querySelector(".companion-mount");
  panel.querySelectorAll("select").forEach((el) => { el.disabled = true; });
  try {
    const session = await fetchJson("/api/session");
    await fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/summons`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token },
      body: JSON.stringify({ counts, ...(tamer ? { beasts } : {}), ...(mountPick ? { mount: mountPick.value } : {}) }),
    });
    await reloadSheet();
    toast("ok", "Companions saved", "New fights use them.", 2200);
  } catch (error) {
    toast("error", "Not saved", error.message, 3200);
    renderCompanions(); // put the panel back to the saved pick
  }
}

function currentReactionPlan() {
  const plan = state.sheet.reaction_plan || { mode: "auto", order: [], off: [] };
  return { mode: plan.mode, order: [...(plan.order || [])], off: [...(plan.off || [])], options: { ...(plan.options || {}) } };
}

async function saveReactions(plan) {
  const panel = $("reactions-panel");
  panel.querySelectorAll("select, button, input").forEach((el) => { el.disabled = true; });
  try {
    const session = await fetchJson("/api/session");
    await fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/reactions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token },
      body: JSON.stringify(plan),
    });
    await reloadSheet();
    toast("ok", "Reactions saved", plan.mode === "custom" ? "Your order is used in new fights."
      : plan.mode === "ask" ? "You'll be asked at the table in new fights." : "Auto picks your reactions.", 2200);
  } catch (error) {
    toast("error", "Not saved", error.message, 3200);
    renderReactions(); // put the panel back to the saved plan
  }
}

function changeReactions(event) {
  const plan = currentReactionPlan();
  const mode = event.target.closest(".reaction-mode");
  if (mode) {
    // Switching to My order starts from Auto's own order (combat/factory_compiler.py _reaction_plan).
    saveReactions(mode.value === "custom" ? { mode: "custom", order: plan.order, off: [], options: plan.options }
                                          : { mode: mode.value, order: [], off: [], options: plan.options });
    return true;
  }
  const option = event.target.closest(".reaction-option");
  if (option) {
    plan.options[option.dataset.id] = Number(option.value);
    saveReactions(plan.mode === "custom" ? plan : { mode: plan.mode === "ask" ? "ask" : "auto", order: [], off: [], options: plan.options });
    return true;
  }
  const move = event.target.closest(".reaction-move");
  const use = event.target.closest(".reaction-use");
  if (!move && !use) return false;
  const all = [...plan.order, ...plan.off];
  const off = new Set(plan.off);
  if (move) {
    const from = all.indexOf(move.dataset.id);
    const to = from + Number(move.dataset.step);
    if (from < 0 || to < 0 || to >= all.length) return true;
    [all[from], all[to]] = [all[to], all[from]];
  } else if (use.checked) off.delete(use.dataset.id);
  else off.add(use.dataset.id);
  saveReactions({ mode: "custom", order: all.filter((id) => !off.has(id)), off: all.filter((id) => off.has(id)), options: plan.options });
  return true;
}

// Build the choices map (action_id -> pool display name) straight off the current sheet.
function poweringChoicesFromSheet() {
  const powering = state.sheet.powering || { choices: {} };
  return Object.fromEntries(Object.entries(powering.choices || {}).map(([id, info]) => [id, info.pool]));
}

function ensurePoweringPicker() {
  if (!poweringPicker) {
    poweringPicker = new PoweringPicker({
      choices: poweringChoicesFromSheet(),
      post: postPowering,
      onSaved: () => schedulePoweringRefresh(),
      onRollback: () => renderPowering(),
      toast: (message, ms) => toast("error", "Not saved", message, ms),
    });
  }
  return poweringPicker;
}

// Apply one dropdown change optimistically, then let the picker batch the save in the background.
function changePowering(actionId, pool) {
  ensurePoweringPicker().set(actionId, pool);
}

// Push every choosable ability onto one pool at once (the common case): optimistic, then batched.
function setAllPools(pool) {
  const picker = ensurePoweringPicker();
  picker.setAll(pool);
  renderPowering(); // repaint every select to the new optimistic value at once
}

// POST the full current choices for the character; the server replaces the saved set and
// rejects anything not choosable. Returns the saved document on success.
async function postPowering(choices) {
  const session = await fetchJson("/api/session");
  return fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/powering`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token },
    body: JSON.stringify({ choices }),
  });
}

// After a saved change, refresh the compiled sheet once (the action list's printed costs move
// with the pool) -- debounced to a single pass once the player has stopped editing. Pending edits
// are flushed first so none are lost on the reload.
function schedulePoweringRefresh() {
  clearTimeout(poweringRefreshTimer);
  poweringRefreshTimer = setTimeout(reloadSheet, POWERING_REFRESH_MS);
}

// Re-fetches the compiled sheet (costs move to the newly chosen pool) and redraws everything.
async function reloadSheet() {
  clearTimeout(poweringRefreshTimer);
  await poweringPicker?.flush?.();          // save any un-acked edits before the sheet changes
  const sheet = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/sheet`);
  state.sheet = sheet;
  state.summary = sheet.summary || {};
  indexLibraryText(sheet.library);
  indexButtons(sheet.buttons, sheet.layout);
  if (poweringPicker && !poweringPicker.hasPending) poweringPicker.adopt(poweringChoicesFromSheet());
  renderAll();
}

// ------------------------------------------------------------------ features tab
function renderFeatures() {
  const f = state.sheet.features || {};
  const q = norm(state.featureQuery);
  const card = (info, kind) => h("div", { class: "fcard", role: "listitem" },
    h("span", null, h("span", { class: "fcard-name" }, info.name), info.source ? h("span", { class: "fcard-src" }, info.source) : null),
    h("span", { class: `badge badge-${kind}` }, { auto: "Auto", build: "In build", outside: "Outside fights", definition: "Definition", table: "Not on the table" }[kind] || "Not yet"));
  const section = (title, list, kind, blurb) => {
    const infos = list.map((x) => featureInfo(x)).filter((i) => !q || norm(`${i.name} ${i.source}`).includes(q));
    if (!infos.length && q) return null;
    return h("section", { class: `fgroup fgroup-${kind}`, "aria-label": title },
      h("h3", { class: "agroup-title" }, title, h("span", { class: "count" }, infos.length), h("span", { class: "note" }, blurb)),
      infos.length ? h("div", { class: "fgrid", role: "list" }, infos.map((i) => card(i, kind))) : h("p", { class: "empty" }, "None."));
  };
  const sections = [
    section("Automated Passives", f.automated_passives || [], "auto", "Always on; the engine applies them"),
    section("Automated Reactions", f.automated_reactions || [], "auto", "The table triggers them for you"),
    modifierSection(f.modifiers || [], q),
    section("Passives not automated yet", f.gm_passives || [], "gm", "The fight skips these for now"),
    section("Reactions not automated yet", f.gm_reactions || [], "gm", "The fight skips these for now"),
    (f.build_features || []).length ? section("Chosen when the character was built", f.build_features, "build", "Already part of the build; nothing to run in a fight") : null,
    (f.outside_fights || []).length ? section("Outside fights", f.outside_fights, "outside", "Rituals and other uses away from the table's fights") : null,
    (f.definitions || []).length ? section("Rules definitions", f.definitions, "definition", "Terms other features use; nothing of their own to run") : null,
    (f.table_limits || []).length ? section("Needs the table to model more", f.table_limits, "table", "Climbing, elevation, falling or mounts: not on the table yet") : null,
  ].filter(Boolean);
  $("feature-list").replaceChildren(...(sections.length ? sections : [h("p", { class: "empty" }, "No features match that filter.")]));
}

// ------------------------------------------------------------------ abilities library (owner 2026-09-25)
// Every Sphere, talent, base ability, Path feature, technique and art the character has, with its
// full rules text, searchable, so a player can read what they can do and plan a turn.
const LIB_STATUS = {
  action: { label: "Button", cls: "lib-st-action", title: "A button runs it through the rules engine" },
  partial: { label: "Partly automated", cls: "lib-st-partial", title: "The button runs the roll, damage and movement; some extra lines aren't automated yet" },
  auto: { label: "Automatic", cls: "lib-st-auto", title: "Always on, or fires by itself; the engine applies it" },
  gm: { label: "Not automated yet", cls: "lib-st-gm", title: "The fight skips it for now" },
  info: { label: "Reference", cls: "lib-st-info", title: "Not a combat rule" },
};
const LIB_STATUS_FILTERS = [["all", "Everything"], ["usable", "Usable as buttons"], ["auto", "Automatic"], ["gm", "Not automated yet"], ["info", "Reference"]];

function libMatches(item, query) {
  if (!query) return true;
  return norm(`${item.name} ${item.kind} ${item.economy || ""} ${cleanRules(item.summary)} ${cleanRules(item.text)}`).includes(query);
}

function libStatusOk(item) {
  const f = state.libStatus;
  if (f === "all") return true;
  if (f === "usable") return item.status === "action" || item.status === "partial";
  return item.status === f;
}

// Plain-text rules with light markdown (headings, **bold**, *italic*, `code`, lists), built as DOM
// nodes so no rules text is ever parsed as HTML.
function inlineMd(text, query) {
  const out = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) out.push(...highlight(text.slice(last, match.index), query));
    const token = match[0];
    if (token.startsWith("**")) out.push(h("strong", null, ...highlight(token.slice(2, -2), query)));
    else if (token.startsWith("`")) out.push(h("code", null, token.slice(1, -1)));
    else out.push(h("em", null, ...highlight(token.slice(1, -1), query)));
    last = match.index + token.length;
  }
  if (last < text.length) out.push(...highlight(text.slice(last), query));
  return out;
}

function highlight(text, query) {
  if (!query) return [text];
  const lower = text.toLowerCase();
  const out = [];
  let from = 0, at;
  while ((at = lower.indexOf(query, from)) >= 0) {
    if (at > from) out.push(text.slice(from, at));
    out.push(h("mark", null, text.slice(at, at + query.length)));
    from = at + query.length;
  }
  out.push(text.slice(from));
  return out;
}

function rulesText(text, query) {
  return renderRules(text, h, line => inlineMd(line, query));
}

function snippet(item, query) {
  if (!query) return null;
  const text = cleanRules(item.text).replace(/[#*`>]/g, "").replace(/\s+/g, " ");
  const at = text.toLowerCase().indexOf(query);
  if (at < 0 || norm(item.name).includes(query) || norm(item.summary).includes(query)) return null;
  const start = Math.max(0, at - 70);
  return h("p", { class: "lib-snippet" }, start ? "…" : "", ...highlight(text.slice(start, at + query.length + 110), query), "…");
}

function libCard(item, query) {
  const open = state.libOpen.has(item.id) || (query && state.libOpen.has(`q:${item.id}`));
  const st = LIB_STATUS[item.status] || LIB_STATUS.info;
  const meta = [item.kind, item.economy, item.cl ? `CL ${item.cl}` : null].filter(Boolean).join(" · ");
  const button = item.button_id ? state.byId.get(item.button_id) : null;
  const legal = button && state.legal ? state.legal.has(button.id) : null;
  return h("article", { class: `lib-card${open ? " is-open" : ""}`, "data-lib-id": item.id,
    title: layoutText(item.hover) || plainRules(item.text || item.summary) },
    h("div", { class: "lib-card-head" },
      h("button", { type: "button", class: "lib-toggle", "aria-expanded": open ? "true" : "false", "data-lib-toggle": item.id },
        h("span", { class: "lib-name" }, ...highlight(item.name, query)),
        h("span", { class: "lib-meta" }, meta)),
      h("span", { class: `lib-status ${st.cls}`, title: st.title }, st.label),
      button ? h("button", { type: "button", class: `btn lib-use${legal ? " is-legal" : ""}`, "data-button-id": button.id,
        title: legal === false ? "Not usable right now on the table" : `Use ${button.label}` }, "Use") : null),
    h("p", { class: "lib-summary" }, ...highlight(ruleSummary(item.text) || cleanRules(item.summary), query)),
    // What the table does by itself and what the Game Master still rules, in plain
    // words; only sent for records the compiler knows the boundary of.
    item.automation ? h("p", { class: `lib-auto lib-auto-${item.status}` }, item.automation) : null,
    open ? null : snippet(item, query),
    open ? rulesText(layoutText(item.hover) || item.text || item.summary, query) : null);
}

function renderLibrary() {
  const lib = state.sheet.library || { groups: [] };
  const query = norm(state.libQuery);
  const groupsHost = $("lib-groups");
  const count = (group) => (group.spheres ? group.spheres.reduce((n, sp) => n + sp.entries.length, 0) : group.entries.length);
  groupsHost.replaceChildren(
    h("button", { type: "button", class: "filter", "aria-pressed": state.libGroup === "all" ? "true" : "false", "data-lib-group": "all" }, "All"),
    ...lib.groups.map((g) => h("button", { type: "button", class: "filter", "aria-pressed": state.libGroup === g.key ? "true" : "false", "data-lib-group": g.key },
      g.title, h("span", { class: "n" }, ` ${count(g)}`))));
  $("lib-status").replaceChildren(...LIB_STATUS_FILTERS.map(([key, label]) =>
    h("button", { type: "button", class: "filter filter-small", "aria-pressed": state.libStatus === key ? "true" : "false", "data-lib-status": key }, label)));
  let shown = 0;
  const sections = [];
  for (const group of lib.groups) {
    if (state.libGroup !== "all" && state.libGroup !== group.key) continue;
    if (group.spheres) {
      for (const sphere of group.spheres) {
        const items = sphere.entries.filter((item) => libStatusOk(item) && libMatches(item, query));
        const sphereHit = query && norm(`${sphere.name} ${sphere.text}`).includes(query);
        if (!items.length && !sphereHit) continue;
        shown += items.length;
        const aboutOpen = state.libOpen.has(`sphere:${sphere.id}`);
        sections.push(h("section", { class: "lib-group lib-sphere", "aria-label": `${sphere.name} sphere` },
          h("h3", { class: "agroup-title" }, `${sphere.name}${sphere.id ? " Sphere" : ""}`, h("span", { class: "count" }, items.length),
            sphere.text ? h("button", { type: "button", class: "lib-about", "data-lib-toggle": `sphere:${sphere.id}`, "aria-expanded": aboutOpen ? "true" : "false" },
              aboutOpen ? "Hide sphere rules" : "About this sphere") : null),
          aboutOpen ? h("div", { class: "lib-card is-open lib-sphere-about" }, rulesText(sphere.text, query)) : null,
          !items.length && !aboutOpen ? h("p", { class: "lib-snippet" }, "Found in this sphere's own rules — open “About this sphere”.") : null,
          h("div", { class: "lib-cards" }, items.map((item) => libCard(item, query)))));
      }
      continue;
    }
    const items = group.entries.filter((item) => libStatusOk(item) && libMatches(item, query));
    if (!items.length) continue;
    shown += items.length;
    sections.push(h("section", { class: "lib-group", "aria-label": group.title },
      h("h3", { class: "agroup-title" }, group.title, h("span", { class: "count" }, items.length)),
      h("div", { class: "lib-cards" }, items.map((item) => libCard(item, query)))));
  }
  $("lib-count").textContent = query ? `${shown} match${shown === 1 ? "" : "es"}` : `${shown} abilities`;
  $("lib-list").replaceChildren(...(sections.length ? sections : [h("p", { class: "empty" }, "Nothing matches that search.")]));
}

// ------------------------------------------------------------------ custom tab and quick bar
function renderCustom() {
  const combos = customButtons();
  if (!combos.length) {
    $("custom-list").replaceChildren(h("p", { class: "empty" }, "No combos yet. Build one with New combo — for example an attack followed by a bonus action on the same target."));
    return;
  }
  $("custom-list").replaceChildren(h("div", { class: "combo-grid" }, combos.map((b) => h("div", { class: "combo-wrap" },
    h("button", { type: "button", class: "combo-card", "data-button-id": b.id, style: b.color ? { "--tint": b.color } : null },
      h("span", { class: "combo-title" }, b.label),
      h("span", { class: "combo-steps" }, (b.steps || []).flatMap((st, i) => [
        i ? h("span", { class: "arrow", "aria-hidden": "true" }, "→") : null,
        h("span", { class: `step-chip${st.roll ? " dice" : ""}` }, stepText(st)),
      ]))),
    h("button", { type: "button", class: "icon-btn combo-edit", "aria-label": `Edit ${b.label}`, "data-edit-combo": b.id }, icon("edit"))))));
  applyLegal();
}

function renderQuickbar() {
  const pinned = state.pinned.map((id) => state.byId.get(id)).filter(Boolean);
  const bar = $("quickbar");
  bar.hidden = !pinned.length;
  bar.replaceChildren(
    h("span", { class: "quickbar-label" }, icon("pin"), " Pinned"),
    ...pinned.map((b) => {
      const sub = b.kind === "roll" ? b.roll?.expression : b.kind === "combo" ? "Combo" : economyLabel(b.economy);
      return h("button", { type: "button", class: "qbtn", "data-button-id": b.id, style: b.color ? { "--tint": b.color } : null },
        b.kind === "roll" ? icon("d20") : null, b.label, sub ? h("span", { class: "qsub" }, sub) : null);
    }),
  );
  applyLegal();
}

function renderAll() {
  renderHeader();
  renderStats();
  renderSaves();
  renderSenses();
  renderDefenses();
  renderSkills();
  renderActions();
  renderFeatures();
  renderLibrary();
  renderCustom();
  renderQuickbar();
  renderLive();
}

// ------------------------------------------------------------------ live state from the table
// Grouped weapon rows carry every physical copy id in `copies`, plus the carried action behind each
// row in `copy_keys` (a thrown or Batter row is a variant of that carried action). Count only copies
// the table still reports in the fighter's possession, so throwing one javelin turns "×2" into "×1".
function weaponCopyKeys(b) {
  const ids = b?.copies || [];
  const keys = Array.isArray(b?.copy_keys) ? b.copy_keys : [];
  return ids.map((id, index) => keys[index] || id);
}

function weaponCopyCount(b) {
  const ids = b?.copies || [];
  const reported = state.actor?.weapon_copies;
  if (state.connected !== true || !state.actor || !Array.isArray(reported)) return ids.length;
  const present = new Set(reported);
  return weaponCopyKeys(b).filter(key => present.has(key)).length;
}

function weaponCopyText(b) {
  return `${String(b?.label || "").replace(/\s*×\d+$/, "")} ×${weaponCopyCount(b)}`;
}

function weaponCopySignature() {
  return state.buttons.filter(b => b.copies).map(b => `${b.id}:${weaponCopyCount(b)}`).join("|");
}

function comboLegal(b) {
  const first = (b.steps || []).map((s) => s.button && state.byId.get(s.button)).find((x) => x && x.kind === "combat");
  return !first || state.legal.has(first.id);
}

function applyLegal() {
  // The chips are buttons too: repaint them first (a spent copy hands the chip over to the next one), then let the
  // loop below mark each one legal or greyed and hang the server's reason on it (ATTACKLIST1).
  if (state.attackGroups instanceof Map) updateAttackGroups();
  const active = state.connected === true && state.legal;
  for (const el of document.querySelectorAll("#sheet [data-button-id]")) {
    const drawn = state.byId.get(el.dataset.buttonId);
    if (!isCombatish(drawn) && el.dataset.buttonId !== "turn:end") continue;
    // A grouped weapon row keeps one button per physical copy. Point the drawn row at the copy the
    // table is actually offering: the first usable one, else the first still carried (so its
    // "Draw ..." reason is the one shown), else the first for a recover-it explanation.
    if (drawn?.copies?.length) {
      const present = new Set(state.actor?.weapon_copies || []);
      const keys = weaponCopyKeys(drawn);
      const carried = drawn.copies.filter((id, index) => present.has(keys[index]));
      const pool = carried.length ? carried : drawn.copies;
      const chosen = pool.find(id => active && !unavailableReason(id) && state.legal?.has(id))
        || pool.find(id => unavailableReason(id)) || pool[0];
      if (chosen && chosen !== el.dataset.buttonId) el.dataset.buttonId = chosen;
      const copyLabel = el.querySelector("[data-copy-label]");
      if (copyLabel) copyLabel.textContent = weaponCopyText(drawn);
    }
    const b = state.byId.get(el.dataset.buttonId);
    // One availability rule for every row the table can send (SHEETAVAIL2): a row is an action row because its
    // button id is the table's ("act:<source>"), not because of what kind of row it is, so Bonus Actions,
    // Reactions, techniques, rest-of-Attack rows and weapon rows are greyed by the same rule with no per-ability
    // code. Nothing is hidden here; a row with no row definition of its own is still the server's to refuse.
    if (!isCombatish(b) && el.dataset.buttonId !== "turn:end" && !String(el.dataset.buttonId).startsWith("act:")) continue;
    // The server also refuses lazy action headers it already knows cannot expand (rest-of-the-Attack rows after
    // their attacks are spent). Those headers are in the menu, so legality alone would show them as usable.
    const reason = active ? unavailableReason(el.dataset.buttonId) : "";
    const legal = active ? (reason ? false : (b?.kind === "combo" ? comboLegal(b) : state.legal.has(el.dataset.buttonId))) : null;
    el.classList.toggle("is-legal", legal === true);
    el.classList.toggle("is-illegal", legal === false);
    explainUnavailable(el, legal === false ? reason : "");
    markActive(el, state.connected === true && state.actor?.button_states?.[el.dataset.buttonId]?.active);
    if (legal === false) el.setAttribute("aria-description", reason ? `Not available: ${reason}` : "Not available right now; the table will explain why.");
    else el.removeAttribute("aria-description");
  }
  updateUnavailableRows();
}

const unavailableReason = (id) => String((state.unavailable || {})[id] || "");

// A row the server refuses keeps its own rules card and adds the server's reason, so a greyed row says why
// (owner 2026-10-20: "those shouldnt be clickable if i dont have any actions").
const baseTipCards = new WeakMap();
function explainUnavailable(el, reason) {
  if (!reason) {
    if (el.dataset.baseTip != null) { el.dataset.tip = el.dataset.baseTip; delete el.dataset.baseTip; }
    else if (el.dataset.refusalTip === "1") delete el.dataset.tip;  // the row had no hover text of its own
    delete el.dataset.refusalTip;
    const base = baseTipCards.get(el);
    if (base) el.tipCard = base;
    return;
  }
  if (el.dataset.baseTip == null) {
    if (el.dataset.tip != null) el.dataset.baseTip = el.dataset.tip;
    else el.dataset.refusalTip = "1";
  }
  el.dataset.tip = [el.dataset.baseTip, `Not available: ${reason}`].filter(Boolean).join("\n\n");
  if (typeof el.tipCard === "function" && !baseTipCards.has(el)) baseTipCards.set(el, el.tipCard);
  const base = baseTipCards.get(el);
  if (base) el.tipCard = (doc, options) => {
    const card = base(doc, options);
    const line = doc.createElement("p");
    line.className = "tip-unavailable";
    line.textContent = `Not available: ${reason}`;
    card.prepend(line);
    return card;
  };
}

function updateUnavailableRows() {
  const list = $("action-list");
  if (!list) return;
  const rows = [...list.querySelectorAll("[data-button-id]")];
  for (const row of rows) row.hidden = false;
  // A row immediately followed by its own ".arow-child" rows is a group header (owner 2026-10-13): hiding it
  // while it is individually unavailable (its Action already used, say) would strand its still-available
  // picker/talent choices with no ability row left to sit under.
  const isGroupHeader = (row) => row.nextElementSibling?.classList.contains("arow-child");
  const illegal = [...list.querySelectorAll("[data-button-id].is-illegal")].filter((row) => !isGroupHeader(row));
  // A chip stays where it is and stays greyed with its reason: hiding one mode of a weapon would break the row that
  // lists the weapon's modes (owner-approved ATTACKLIST1), so the hide toggle only ever hides whole rows. The chips
  // still count as unavailable, so the toggle's number is the same number it was.
  const hideable = illegal.filter((row) => !(row.closest && row.closest(".attack-group")));
  const existing = list.querySelector(".unavailable-toggle");
  existing?.remove();
  if (state.connected !== true || !illegal.length) {
    for (const row of hideable) row.hidden = false;
    return;
  }
  const toggle = h("button", {
    type: "button", class: "unavailable-toggle", "aria-expanded": String(state.showUnavailable),
    onclick: () => {
      state.showUnavailable = !state.showUnavailable;
      try { localStorage.setItem("tianxia-sheet-show-unavailable", String(state.showUnavailable)); } catch {}
      updateUnavailableRows();
    },
  }, `${state.showUnavailable ? "Hide" : "Show"} unavailable (${illegal.length})`);
  list.prepend(toggle);
  const hide = unavailableRowsHidden(state.connected, illegal.length, state.showUnavailable);
  for (const row of hideable) row.hidden = hide;
}

function economyPips(turn) {
  const pip = (label, value, extra = "") => {
    const spent = value === false || value === 0 || value == null;
    const count = typeof value === "number" && value > 1 ? ` ×${value}` : "";
    return h("span", { class: `pip${spent ? " spent" : ""}${extra}`, title: `${label}: ${spent ? "used" : "available"}` }, label + count);
  };
  const move = Number(turn.movement_ft);
  return [
    pip("Action", turn.action),
    pip("Bonus", turn.bonus_action),
    pip("Reaction", turn.reaction),
    Number.isFinite(move) ? pip(`${move} ft move`, move > 0, " move") : null,
  ];
}

function renderLive() {
  if (!state.summary) return;
  renderHeader();
  const s = state.summary;
  const actor = state.actor;
  const live = liveStats(actor, s);
  if (live.armorClass != null) {
    const ac = document.querySelector("#vitals .ac .stat-big");
    if (ac) ac.textContent = String(live.armorClass);
    const trigger = document.querySelector("#vitals .ac");
    if (trigger) {
      trigger.dataset.tip = TianxiaSheetViewModel.armorBreakdown(s.armor_breakdown || {}, actor);
      trigger.tipCard = armorTipCard(s.armor_breakdown || {}, actor);
      if (sheetHoverCard.isOpen && sheetHoverCard.trigger === trigger) sheetTipTargets.show(trigger);
    }
  }
  if (live.speedFt != null) {
    const box = [...document.querySelectorAll("#vitals .stat")].find(row => row.querySelector(".stat-label")?.textContent === "Walking");
    const value = box?.querySelector(".stat-big");
    if (value) { value.textContent = String(live.speedFt); value.append(h("span", { class: "unit" }, "ft")); }
  }
  const fly = actor?.fly_speed_ft ?? 0;
  const flyLine = $("walk-fly");
  flyLine.textContent = fly ? `Fly ${fly} ft` : "";
  flyLine.dataset.tip = fly ? `Fly speed: ${fly} ft. How far it can move through the air in one turn${actor.hover ? ", and it can hover in place" : ""}.` : "";
  const feet = heightFeet(actor);
  $("height-num").textContent = String(feet);
  $("height-box").dataset.tip = `Height above the ground: ${feet} ft. It changes when the character moves up or down in a fight.`;
  // link pill + offline banner
  const pill = $("link-pill");
  const turn = actor?.turn || null;
  pill.dataset.state = state.connected === true ? "connected" : state.connected === false ? "offline" : "waiting";
  $("link-text").textContent = state.connected === true
    ? (turn?.is_current ? "Table connected · your turn" : "Table connected")
    : state.connected === false ? "Table not connected" : "Looking for the table…";
  $("conn-banner").hidden = state.connected !== false;

  // hit points
  const max0 = s.hit_points?.maximum ?? 0;
  const hp = actor?.hp || {};
  const max = Number(hp.maximum ?? max0) || 0;
  const cur = Number(hp.current ?? max) || 0;
  const temp = Number(hp.temporary) || 0;
  $("hp-cur").textContent = cur;
  $("hp-max").textContent = max;
  $("hp-temp").textContent = temp > 0 ? temp : "—";
  $("hp-temp-cell").classList.toggle("has-temp", temp > 0);
  $("hp-cur").classList.toggle("low", max > 0 && cur <= max / 4);
  $("hp-fill").style.width = `${100 * clamp01(max ? cur / max : 0)}%`;
  $("hp-temp-fill").style.width = `${100 * clamp01(max ? temp / max : 0)}%`;
  $("hp-note").textContent = !actor ? "Full" : cur <= 0 ? "Down" : cur >= max ? "Full" : `${Math.round(100 * cur / max)}%`;
  $("hp-box").setAttribute("aria-label", `Hit points ${cur} of ${max}${temp ? `, ${temp} temporary` : ""}`);

  // turn banner
  const banner = $("turn-banner");
  if (state.connected === true && turn?.is_current) {
    banner.hidden = false;
    banner.dataset.waiting = "false";
    $("turn-title").textContent = turn.manual === false ? "Your turn · auto-play" : "Your turn";
    $("turn-economy").replaceChildren(...economyPips(turn).filter(Boolean));
    // The table's one open choice, in plain words. Without it a button looks dead while the table
    // waits for the player to pick a target or a square (owner playtest 2026-10-03 23:01). The table
    // sends the sentence's middle, because the choice is a creature for some abilities and a square
    // for others. It sends nothing at all once the choice is answered, so this line cannot outlive it.
    const choice = state.actor?.pending_choice;
    const pending = $("turn-pending");
    pending.hidden = !choice;
    if (choice) pending.textContent = choice.prompt
      ? `The table is waiting for you to choose ${choice.prompt}. Answer it on the table.`
      : "The table is waiting for an answer to a question it asked. Answer it on the table first.";
  } else {
    banner.hidden = true;
  }
  renderDefenses();
  applyLegal();
}

// ------------------------------------------------------------------ channel
function post(message) {
  if (!channel) return;
  try { channel.postMessage(message); } catch (error) { console.warn("Could not post to the table.", error); }
}

function hello() {
  post({ type: "sheet-hello", project_id: state.projectId, actor_id: state.sheet.actor_id, sheet_id: presetWindow });
}

function startHelloTimers() {
  clearTimeout(helloTimer); clearInterval(rehelloTimer);
  helloTimer = setTimeout(() => {
    if (state.connected !== true) { state.connected = false; renderLive(); }
  }, HELLO_WAIT_MS);
  // Keep asking while no table answers, so opening the fight later lights the sheet up.
  rehelloTimer = setInterval(() => { if (state.connected !== true) hello(); }, REHELLO_MS);
}

function startChannel() {
  if (typeof BroadcastChannel === "undefined") {
    state.connected = false;
    renderLive();
    return;
  }
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.addEventListener("message", (event) => onMessage(event.data));
  hello();
  startHelloTimers();
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state.connected !== true) hello(); });
  window.addEventListener("pagehide", () => {
    post({type: "sheet-closed", sheet_id: presetWindow, actor_id: state.sheet.actor_id, match_id: state.actor?.match_id});
    clearInterval(rehelloTimer); clearTimeout(helloTimer);
  });
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    // pagehide retired the old identity even when the browser cached this
    // document. A new identity preserves final-close late-reply suppression.
    presetWindow = crypto.randomUUID();
    state.connected = null;
    presetQueue.announcePending();
    hello();
    startHelloTimers();
  });
}

function onMessage(msg) {
  if (!msg || typeof msg !== "object" || !state.sheet) return;
  if (msg.actor_id !== state.sheet.actor_id) return;
  if (msg.type === "settings-flush" && msg.sheet_id === presetWindow) {
    presetQueue.flush(msg.match_id).then(() => post({...msg, type: "settings-flushed", ok: true}),
      error => post({...msg, type: "settings-flushed", ok: false, message: error.message}));
    return;
  }
  if (msg.type === "fight-closed") {
    if (state.actor?.match_id !== msg.match_id) return;
    state.actor = null;
    state.connected = false;
    state.legal = new Set();
    state.unavailable = {};
    renderActions();
    renderLive();
  } else if (msg.type === "draft-states") {
    // The table's open option draft changed one pick: only Active marks move, so re-mark in place.
    if (state.actor?.actor_id !== msg.actor_id || state.actor.match_id !== msg.match_id) return;
    state.actor.button_states = msg.button_states || {};
    applyLegal();
  } else if (msg.type === "actor") {
    const wasConnected = state.connected === true;
    state.actor = msg;
    presetQueue.acceptRefresh(msg.match_id, msg.state_version);
    state.connected = true;
    state.legal = new Set(Array.isArray(msg.legal_button_ids) ? msg.legal_button_ids : []);
    state.unavailable = msg.unavailable_reasons && typeof msg.unavailable_reasons === "object" ? msg.unavailable_reasons : {};
    refreshActionRowsInPlace();
    clearTimeout(helloTimer);
    renderLive();
    if (!wasConnected) {
      for (const stale of document.querySelectorAll('#toasts [data-key="offline"]')) stale.remove();
      toast("ok", "Table connected", "Combat buttons now act on the table.", 2600);
    }
  } else if (msg.type === "result") {
    const b = state.byId.get(msg.button_id);
    toast(msg.ok ? "ok" : "error", b?.label || (msg.ok ? "Done" : "Not allowed"), msg.message || (msg.ok ? "Resolved on the table." : "The table refused that action."));
  }
}

// ------------------------------------------------------------------ activation
function pulse(el) {
  if (!el) return;
  el.classList.remove("sent");
  void el.offsetWidth;
  el.classList.add("sent");
  setTimeout(() => el.classList.remove("sent"), 800);
}

async function activate(id, el) {
  const b = state.byId.get(id);
  if (!b) { toast("error", "Unknown button", id); return; }
  // The table already said this cannot run, so say why here instead of sending the refuse-and-explain round trip.
  const refused = state.connected === true ? unavailableReason(id) : "";
  if (refused) { toast("warn", b.label, refused, 5200); return; }
  if (b.kind === "roll" && b.roll?.expression) { doRoll(b.label, b.roll.expression, b.roll.kind || "check"); pulse(el); return; }
  try { await presetQueue.flush(state.actor?.match_id || ""); }
  catch (error) { toast("error", "Preset not saved", error.message); return; }
  noteAttackSent(b);
  post({ type: "button", project_id: state.projectId, actor_id: state.sheet.actor_id, button_id: b.id, button: b });
  pulse(el);
  if (state.connected !== true) {
    toast("warn", "Table not connected", `“${b.label}” was sent, but no combat table answered. Open a fight on the table, then try again.`, 5200, "offline");
  }
}

async function doRoll(label, expression, kind) {
  let r;
  try { r = rollLocal(expression); } catch (error) { toast("error", `Could not roll ${label}`, String(error.message || error)); return; }
  const entry = { seq: ++rollSeq, label, expression, kind, total: r.total, groups: r.groups, discarded: r.discarded || [], modifier: r.modifier, pending: Boolean(tray) };
  state.rolls.unshift(entry);
  state.rolls.length = Math.min(state.rolls.length, 30);
  renderLog(entry.seq);
  post({ type: "roll", project_id: state.projectId, actor_id: state.sheet.actor_id, label, expression,
    result: { total: r.total, groups: r.groups, modifier: r.modifier } });
  if (tray) {
    try {
      await Promise.race([tray.roll(r.groups, { label, modifier: r.modifier, total: r.total, kind, discarded: r.discarded }), sleep(6000)]);
    } catch (error) { console.warn("Dice animation failed.", error); }
  }
  entry.pending = false;
  renderLog(entry.seq);
}

function renderLog(freshSeq) {
  $("roll-log").replaceChildren(...state.rolls.slice(0, 12).map((e) => {
    const d20 = e.groups.filter((g) => Number(g.sides) === 20).map((g) => g.value);
    const crit = !e.pending && d20.includes(20);
    const fumble = !e.pending && !crit && d20.includes(1);
    const dice = e.groups.map((g) => g.value).join(" + ") + (e.discarded.length ? ` (dropped ${e.discarded.map((g) => g.value).join(", ")})` : "");
    const mod = e.modifier ? ` ${e.modifier > 0 ? "+" : "−"} ${Math.abs(e.modifier)}` : "";
    return h("li", { class: `log-row${e.seq === freshSeq && !e.pending ? " fresh" : ""}${crit ? " crit" : ""}${fumble ? " fumble" : ""}${e.pending ? " pending" : ""}` },
      h("span", { class: "log-label" }, e.label),
      h("span", { class: "log-total", "aria-label": e.pending ? "rolling" : `total ${e.total}` }, e.pending ? "…" : e.total),
      h("span", { class: "log-detail" }, e.pending ? e.expression : `${e.expression} · ${dice}${mod}${crit ? " · natural 20" : fumble ? " · natural 1" : ""}`));
  }));
}

// ------------------------------------------------------------------ toasts
function toast(kind, title, message, ms = 5200, key = null) {
  const box = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status", "data-key": key },
    icon(kind === "ok" ? "ok" : "error", "toast-icon"),
    h("div", null, h("div", { class: "toast-title" }, title), message ? h("div", { class: "toast-msg" }, message) : null),
    h("button", { type: "button", class: "icon-btn", "aria-label": "Dismiss notification", onclick: () => dismiss() }, icon("close")));
  let gone = false;
  const dismiss = () => {
    if (gone) return;
    gone = true;
    box.classList.add("leaving");
    setTimeout(() => box.remove(), 220);
  };
  const stack = $("toasts");
  stack.append(box);
  while (stack.children.length > 4) stack.firstElementChild.remove();
  setTimeout(dismiss, ms);
}

// ------------------------------------------------------------------ tabs
function selectTab(name, focus) {
  state.tab = name;
  for (const tab of document.querySelectorAll("#tablist [role=tab]")) {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    $(tab.getAttribute("aria-controls")).hidden = !on;
    if (on && focus) tab.focus();
  }
  $("tab-panels").scrollTop = 0;
  if (name === "grow") void loadGrow();
  if (name === "items") renderItems();
}

function tabKeys(event, selector, select) {
  const tabs = [...document.querySelectorAll(selector)];
  const i = tabs.indexOf(event.target);
  if (i < 0) return;
  let next = null;
  if (event.key === "ArrowRight") next = tabs[(i + 1) % tabs.length];
  else if (event.key === "ArrowLeft") next = tabs[(i - 1 + tabs.length) % tabs.length];
  else if (event.key === "Home") next = tabs[0];
  else if (event.key === "End") next = tabs[tabs.length - 1];
  if (next) { event.preventDefault(); select(next, true); }
}

// ------------------------------------------------------------------ button editor
const ed = { combos: [], hidden: new Set(), pinned: [], selected: 0, dirty: false, etab: "combos", query: "", layoutQuery: "" };

function newComboId(label) {
  const slug = norm(label).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 28) || "combo";
  return `custom:${slug}-${Date.now().toString(36).slice(-4)}${Math.floor(Math.random() * 1296).toString(36)}`;
}

function openEditor({ comboId = null, create = false } = {}) {
  ed.combos = customButtons().map((b) => ({
    id: b.id, label: b.label, color: b.color || "",
    steps: (b.steps || []).map((s) => (s.button ? { button: s.button, same_target: s.same_target === true } : { roll: s.roll, label: s.label || "" })),
  }));
  ed.hidden = new Set(state.hidden);
  ed.pinned = [...state.pinned];
  ed.selected = Math.max(0, ed.combos.findIndex((c) => c.id === comboId));
  ed.dirty = false;
  ed.query = "";
  ed.layoutQuery = "";
  $("step-search").value = "";
  $("layout-search").value = "";
  $("dice-expr").value = "";
  $("dice-label").value = "";
  $("editor-error").textContent = "";
  selectEditorTab("combos");
  if (create) addCombo(); else renderEditor();
  const dialog = $("editor");
  if (!dialog.open) dialog.showModal();
  if (create) { $("combo-name").focus(); $("combo-name").select(); }
}

function closeEditor(force) {
  if (!force && ed.dirty && !confirm("Discard your unsaved button changes?")) return false;
  $("editor").close();
  return true;
}

function selectEditorTab(name, focus) {
  ed.etab = name;
  for (const tab of document.querySelectorAll(".editor-tabs [role=tab]")) {
    const on = tab.dataset.etab === name;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    $(tab.getAttribute("aria-controls")).hidden = !on;
    if (on && focus) tab.focus();
  }
  if (name === "layout") renderLayoutRows();
}

function markDirty() { ed.dirty = true; $("editor-error").textContent = ""; }
const selectedCombo = () => ed.combos[ed.selected] || null;

function addCombo() {
  const color = SWATCHES[ed.combos.length % SWATCHES.length];
  ed.combos.push({ id: newComboId("new-combo"), label: "New combo", color, steps: [], fresh: true });
  ed.selected = ed.combos.length - 1;
  markDirty();
  renderEditor();
}

function renderEditor() {
  const combo = selectedCombo();
  $("combo-form").hidden = !combo;
  $("combo-empty").hidden = Boolean(combo);
  $("combo-index").replaceChildren(...ed.combos.map((c, i) => h("button", {
    type: "button", class: "combo-pick", role: "option", "aria-selected": i === ed.selected ? "true" : "false", "data-index": i,
  }, h("span", { class: "sw", style: { background: c.color || "var(--accent)" } }), h("span", { class: "nm" }, c.label || "Untitled"),
  h("span", { class: "ct" }, `${c.steps.length}`))));
  if (!combo) return;
  const name = $("combo-name");
  if (document.activeElement !== name) name.value = combo.label;
  renderSwatches(combo);
  renderSteps(combo);
  renderPicker();
}

function renderSwatches(combo) {
  const custom = combo.color && !SWATCHES.includes(combo.color);
  $("swatches").replaceChildren(
    ...SWATCHES.map((c) => h("button", {
      type: "button", class: "swatch", role: "radio", "aria-checked": combo.color === c ? "true" : "false",
      "aria-label": `Colour ${c}`, style: { background: c }, "data-color": c,
    })),
    h("label", { class: "swatch-custom" }, "Custom",
      h("input", { type: "color", id: "swatch-input", value: /^#[0-9a-f]{6}$/i.test(combo.color) ? combo.color : "#888888", "aria-label": "Custom colour",
        "aria-checked": custom ? "true" : null })),
  );
}

function stepDescription(step) {
  if (step.roll) return { title: step.label || "Dice roll", sub: `Roll ${step.roll}`, bad: false };
  const b = state.byId.get(step.button);
  if (!b) return { title: "Unknown button", sub: step.button, bad: true };
  const bits = [GROUP_NAMES[b.group] || b.group];
  if (b.kind === "roll") bits.push(b.roll?.expression);
  else if (b.economy) bits.push(economyLabel(b.economy));
  return { title: b.label, sub: bits.filter(Boolean).join(" · "), bad: false };
}

function renderSteps(combo) {
  $("step-count").textContent = `(${combo.steps.length} of ${MAX_STEPS})`;
  $("steps").replaceChildren(...combo.steps.map((step, i) => {
    const info = stepDescription(step);
    const b = step.button ? state.byId.get(step.button) : null;
    return h("li", { class: "step" },
      h("span", { class: "step-n", "aria-hidden": "true" }, i + 1),
      h("span", { class: "step-desc" }, h("b", { style: info.bad ? { color: "var(--bad)" } : null }, info.title), h("small", null, info.sub)),
      step.button && b?.kind === "combat" && i > 0
        ? h("label", { class: "step-same", title: "Use the same target as the previous step" },
          h("input", { type: "checkbox", "data-same": i, checked: step.same_target ? true : null }), "Same target")
        : h("span"),
      h("span", { class: "step-ctrl" },
        h("button", { type: "button", class: "icon-btn", "aria-label": `Move step ${i + 1} up`, "data-move": `${i}:-1`, disabled: i === 0 ? true : null }, icon("up")),
        h("button", { type: "button", class: "icon-btn", "aria-label": `Move step ${i + 1} down`, "data-move": `${i}:1`, disabled: i === combo.steps.length - 1 ? true : null }, icon("down")),
        h("button", { type: "button", class: "icon-btn", "aria-label": `Remove step ${i + 1}`, "data-remove": i }, icon("trash"))));
  }));
}

function pickerCandidates(query) {
  const q = norm(query);
  const order = (b) => GROUP_ORDER.indexOf(b.group);
  return autoButtons()
    .filter((b) => !q || norm(`${b.label} ${GROUP_NAMES[b.group] || ""} ${b.roll?.expression || ""}`).includes(q))
    .sort((a, b) => order(a) - order(b));
}

function renderPicker() {
  const list = pickerCandidates(ed.query).slice(0, 80);
  $("step-picker").replaceChildren(...(list.length ? list.map((b) => h("button", {
    type: "button", class: "pick", role: "option", "data-add": b.id,
    "aria-label": `Add ${b.label} (${GROUP_NAMES[b.group] || b.group}) as a step`,
  }, h("span", { class: "nm" }, b.label), h("span", { class: "grp" }, GROUP_NAMES[b.group] || b.group)))
    : [h("p", { class: "muted small" }, "No buttons match.")]));
}

function addStep(step) {
  const combo = selectedCombo();
  if (!combo) return;
  if (combo.steps.length >= MAX_STEPS) { $("editor-error").textContent = `A combo can have at most ${MAX_STEPS} steps.`; return; }
  combo.steps.push(step);
  markDirty();
  renderEditor();
}

function addDiceStep() {
  const expr = $("dice-expr").value.trim();
  const label = $("dice-label").value.trim();
  if (!expr) { $("dice-expr").focus(); return; }
  let ok = DICE_RE.test(expr);
  if (ok) { try { rollLocal(expr); } catch { ok = false; } }
  if (!ok) { $("editor-error").textContent = `“${expr}” is not dice notation. Try 2d6+3 or 1d20 adv.`; $("dice-expr").focus(); return; }
  addStep({ roll: expr, label });
  $("dice-expr").value = "";
  $("dice-label").value = "";
  $("dice-expr").focus();
}

function renderLayoutRows() {
  const q = norm(ed.layoutQuery);
  const order = (b) => GROUP_ORDER.indexOf(b.group);
  const combos = ed.combos.map((c) => ({ id: c.id, label: c.label, group: "custom", kind: "combo" }));
  const rows = [...combos, ...autoButtons().sort((a, b) => order(a) - order(b))]
    .filter((b) => !q || norm(`${b.label} ${GROUP_NAMES[b.group] || ""}`).includes(q));
  $("layout-rows").replaceChildren(...rows.map((b) => {
    const hideable = b.kind === "combat" || b.kind === "combo";
    const shown = !ed.hidden.has(b.id);
    return h("tr", { class: shown ? "" : "is-hidden" },
      h("td", null, b.label),
      h("td", null, GROUP_NAMES[b.group] || b.group),
      h("td", null, hideable
        ? h("input", { type: "checkbox", "data-toggle-hidden": b.id, checked: shown ? true : null, "aria-label": `Show ${b.label} on the Actions tab` })
        : h("span", { class: "muted", title: "Checks, saves and skills are always on the sheet" }, "—")),
      h("td", null, h("input", { type: "checkbox", "data-toggle-pin": b.id, checked: ed.pinned.includes(b.id) ? true : null, "aria-label": `Pin ${b.label} to the quick bar` })));
  }));
}

function validateEditor() {
  for (let i = 0; i < ed.combos.length; i++) {
    const c = ed.combos[i];
    const problem = !c.label.trim() ? "needs a name"
      : !c.steps.length ? "needs at least one step"
        : c.steps.length > MAX_STEPS ? `has more than ${MAX_STEPS} steps` : null;
    if (problem) return { index: i, message: `“${c.label.trim() || "Untitled combo"}” ${problem}.` };
  }
  return null;
}

async function saveEditor() {
  const problem = validateEditor();
  if (problem) {
    ed.selected = problem.index;
    selectEditorTab("combos");
    renderEditor();
    $("editor-error").textContent = problem.message;
    return;
  }
  const saveBtn = $("editor-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";
  $("editor-error").textContent = "";
  for (const c of ed.combos.filter((x) => x.fresh)) {
    // Unsaved combos get an id from their final name (the server keeps "custom:" ids as sent).
    const id = newComboId(c.label);
    ed.pinned = ed.pinned.map((x) => (x === c.id ? id : x));
    if (ed.hidden.delete(c.id)) ed.hidden.add(id);
    c.id = id;
  }
  const liveIds = new Set([...ed.combos.map((c) => c.id), ...autoButtons().map((b) => b.id)]);
  const document_ = {
    buttons: ed.combos.map((c) => ({
      id: c.id, label: c.label.trim(), ...(c.color ? { color: c.color } : {}),
      steps: c.steps.map((s) => (s.button ? { button: s.button, same_target: Boolean(s.same_target) } : { roll: s.roll, ...(s.label ? { label: s.label } : {}) })),
    })),
    layout: { hidden: [...ed.hidden].filter((id) => liveIds.has(id)), pinned: ed.pinned.filter((id) => liveIds.has(id)) },
  };
  try {
    const session = await fetchJson("/api/session");
    const saved = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/buttons`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token },
      body: JSON.stringify(document_),
    });
    indexButtons([...autoButtons(), ...(saved.buttons || [])], saved.layout || document_.layout);
    ed.dirty = false;
    closeEditor(true);
    renderActions();
    renderCustom();
    renderQuickbar();
    toast("ok", "Buttons saved", `${(saved.buttons || []).length} combo${(saved.buttons || []).length === 1 ? "" : "s"}, ${state.pinned.length} pinned, ${state.hidden.size} hidden.`, 3200);
  } catch (error) {
    const details = error.body?.error?.details;
    const extra = Array.isArray(details) && details.length ? `\n${details.slice(0, 3).map((d) => `${(d.loc || []).join(".")}: ${d.msg}`).join("\n")}` : "";
    $("editor-error").textContent = `Not saved: ${error.message}${extra}`;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save";
  }
}

function wireEditor() {
  const dialog = $("editor");
  $("edit-buttons").addEventListener("click", () => openEditor());
  $("new-combo").addEventListener("click", () => openEditor({ create: true }));
  $("editor-close").addEventListener("click", () => closeEditor(false));
  $("editor-cancel").addEventListener("click", () => closeEditor(false));
  $("editor-save").addEventListener("click", saveEditor);
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); closeEditor(false); });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) closeEditor(false); });
  $("editor-form").addEventListener("submit", (event) => event.preventDefault());

  for (const tab of document.querySelectorAll(".editor-tabs [role=tab]")) {
    tab.addEventListener("click", () => selectEditorTab(tab.dataset.etab));
    tab.addEventListener("keydown", (event) => tabKeys(event, ".editor-tabs [role=tab]", (t, f) => selectEditorTab(t.dataset.etab, f)));
  }

  $("combo-add").addEventListener("click", () => { addCombo(); $("combo-name").focus(); $("combo-name").select(); });
  $("combo-index").addEventListener("click", (event) => {
    const pick = event.target.closest("[data-index]");
    if (!pick) return;
    ed.selected = Number(pick.dataset.index);
    $("combo-name").value = selectedCombo()?.label || "";
    renderEditor();
  });
  $("combo-name").addEventListener("input", (event) => {
    const combo = selectedCombo();
    if (!combo) return;
    combo.label = event.target.value.slice(0, 40);
    markDirty();
    const row = $("combo-index").querySelector(`[data-index="${ed.selected}"] .nm`);
    if (row) row.textContent = combo.label || "Untitled";
  });
  $("combo-delete").addEventListener("click", () => {
    const combo = selectedCombo();
    if (!combo) return;
    ed.combos.splice(ed.selected, 1);
    ed.hidden.delete(combo.id);
    ed.pinned = ed.pinned.filter((id) => id !== combo.id);
    ed.selected = Math.max(0, Math.min(ed.selected, ed.combos.length - 1));
    $("combo-name").value = selectedCombo()?.label || "";
    markDirty();
    renderEditor();
  });
  $("swatches").addEventListener("click", (event) => {
    const sw = event.target.closest("[data-color]");
    const combo = selectedCombo();
    if (!sw || !combo) return;
    combo.color = sw.dataset.color;
    markDirty();
    renderEditor();
  });
  $("swatches").addEventListener("input", (event) => {
    const combo = selectedCombo();
    if (event.target.id !== "swatch-input" || !combo) return;
    combo.color = event.target.value;
    markDirty();
    const row = $("combo-index").querySelector(`[data-index="${ed.selected}"] .sw`);
    if (row) row.style.background = combo.color;
    for (const sw of $("swatches").querySelectorAll(".swatch")) sw.setAttribute("aria-checked", "false");
  });
  $("steps").addEventListener("click", (event) => {
    const combo = selectedCombo();
    if (!combo) return;
    const move = event.target.closest("[data-move]");
    const remove = event.target.closest("[data-remove]");
    if (move) {
      const [i, dir] = move.dataset.move.split(":").map(Number);
      const j = i + dir;
      if (j < 0 || j >= combo.steps.length) return;
      [combo.steps[i], combo.steps[j]] = [combo.steps[j], combo.steps[i]];
      markDirty();
      renderEditor();
      $("steps").querySelector(`[data-move="${j}:${dir}"]:not([disabled])`)?.focus();
    } else if (remove) {
      combo.steps.splice(Number(remove.dataset.remove), 1);
      markDirty();
      renderEditor();
    }
  });
  $("steps").addEventListener("change", (event) => {
    const combo = selectedCombo();
    if (!combo || event.target.dataset.same == null) return;
    combo.steps[Number(event.target.dataset.same)].same_target = event.target.checked;
    markDirty();
  });
  $("step-search").addEventListener("input", (event) => { ed.query = event.target.value; renderPicker(); });
  $("step-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); const first = pickerCandidates(ed.query)[0]; if (first) addStep({ button: first.id, same_target: true }); }
  });
  $("step-picker").addEventListener("click", (event) => {
    const pick = event.target.closest("[data-add]");
    if (pick) addStep({ button: pick.dataset.add, same_target: true });
  });
  $("dice-add").addEventListener("click", addDiceStep);
  for (const id of ["dice-expr", "dice-label"]) {
    $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); addDiceStep(); } });
  }
  $("layout-search").addEventListener("input", (event) => { ed.layoutQuery = event.target.value; renderLayoutRows(); });
  $("layout-rows").addEventListener("change", (event) => {
    const t = event.target;
    if (t.dataset.toggleHidden) {
      if (t.checked) ed.hidden.delete(t.dataset.toggleHidden); else ed.hidden.add(t.dataset.toggleHidden);
      t.closest("tr").classList.toggle("is-hidden", !t.checked);
      markDirty();
    } else if (t.dataset.togglePin) {
      const id = t.dataset.togglePin;
      ed.pinned = t.checked ? [...ed.pinned.filter((x) => x !== id), id] : ed.pinned.filter((x) => x !== id);
      markDirty();
    }
  });
}

// ------------------------------------------------------------------ wiring
function wireSheet() {
  $("sheet").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit-combo]");
    if (edit) { openEditor({ comboId: edit.dataset.editCombo }); return; }
    const libToggle = event.target.closest("[data-lib-toggle]");
    if (libToggle) {
      const id = libToggle.dataset.libToggle;
      state.libOpen.has(id) ? state.libOpen.delete(id) : state.libOpen.add(id);
      renderLibrary();
      return;
    }
    const libGroup = event.target.closest("[data-lib-group]");
    if (libGroup) { state.libGroup = libGroup.dataset.libGroup; renderLibrary(); $("tab-panels").scrollTop = 0; return; }
    const libStatus = event.target.closest("[data-lib-status]");
    if (libStatus) { state.libStatus = libStatus.dataset.libStatus; renderLibrary(); return; }
    const filter = event.target.closest("[data-filter]");
    if (filter) { state.filter = filter.dataset.filter; renderActions(); $("tab-panels").scrollTop = 0; return; }
    if (event.target.closest("[data-rider-select]")) return;
    if (event.target.closest("[data-attack-ask]")) { state.attackAsk = null; updateAttackGroups(); return; }
    // An answer to "all of them on this, or choose each?" closes the question and presses the row it names.
    const askAnswer = event.target.closest("[data-attack-answer]");
    if (askAnswer) { state.attackAsk = null; updateAttackGroups(); activate(askAnswer.dataset.buttonId, askAnswer); return; }
    // A weapon's chip: with more than one attack in the Attack action the first click asks whether to spend them all
    // on this one or to choose each; otherwise the chip falls through to the row it stands for (owner-approved).
    const chipNode = event.target.closest("[data-attack-chip]");
    if (chipNode && attackChipClick(chipNode)) return;
    const target = event.target.closest("[data-button-id]");
    if (target && !target.disabled) activate(target.dataset.buttonId, target);
  });
  document.addEventListener("change", event => {
    const select = event.target.closest("[data-rider-select]");
    if (!select?.value) return;
    const key = select.dataset.riderKey;
    const [rowId, field] = [key.slice(key.indexOf("|") + 1, key.lastIndexOf("/")), key.slice(key.lastIndexOf("/") + 1)];
    const row = (state.actor?.attack_modifier_rows || state.sheet.attack_modifier_rows || []).find(r => r.button_id === rowId);
    const selector = row?.selectors.find(s => s.field === field);
    const baseline = selector?.options.find(o => o.value === selector.current)?.button_id;
    presetQueue.edit(key, select.value, baseline, state.actor?.match_id || "");
  });
  for (const tab of document.querySelectorAll("#tablist [role=tab]")) {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
    tab.addEventListener("keydown", (event) => tabKeys(event, "#tablist [role=tab]", (t, f) => selectTab(t.dataset.tab, f)));
  }
  $("feature-search").addEventListener("input", (event) => { state.featureQuery = event.target.value; renderFeatures(); });
  let libTimer = 0;
  $("lib-search").addEventListener("input", (event) => {
    clearTimeout(libTimer);
    libTimer = setTimeout(() => { state.libQuery = event.target.value; renderLibrary(); }, 120);
  });
  $("theme-select").addEventListener("change", (event) => applyTheme(event.target.value, true));
  $("rename-btn")?.addEventListener("click", () => { void renameCharacter(); });
  initGrow({ h, $, fetchJson, toast, reloadSheet, projectId: () => state.projectId });
  initTokens({ h, $, fetchJson, toast, reloadSheet, projectId: () => state.projectId, sheet: () => state.sheet });
  initItems({ h, $, fetchJson, toast, reloadSheet, projectId: () => state.projectId, sheet: () => state.sheet });
  $("sheet").addEventListener("click", (event) => {
    const setAll = event.target.closest("[data-setall]");
    if (setAll) { setAllPools(setAll.dataset.setall); return; }
    if (event.target.closest(".reaction-move")) changeReactions(event);
  });
  $("sheet").addEventListener("change", (event) => {
    if (event.target.closest(".companion-count, .companion-beast, .companion-mount")) { saveCompanions(); return; }
    // Only the pool dropdowns carry data-action-id; reaction "choose one" menus reuse the
    // powering-select class but are owned by changeReactions and must not trigger a save.
    const poweringSelect = event.target.closest(".powering-select[data-action-id]");
    if (poweringSelect) changePowering(poweringSelect.dataset.actionId, poweringSelect.value);
    changeReactions(event);
  });
}

async function showPicker(message) {
  const main = $("body");
  const card = h("div", { class: "load-error frame" }, h("h2", null, "Character sheet"), h("p", { class: "muted" }, message));
  main.replaceChildren(card);
  main.style.display = "block";
  for (const id of ["stats", "quickbar"]) $(id).hidden = true;
  $("char-name").textContent = "No character";
  $("link-pill").hidden = true;
  $("edit-buttons").hidden = true;
  // The list can take a few seconds on a busy server, so say so until it arrives (owner 2026-10-18: "i cant get to the other characters").
  const loading = h("p", { class: "muted", role: "status", "aria-live": "polite" }, "Loading characters…");
  card.append(loading);
  let list;
  try { list = await fetchJson("/api/combat/factory-characters"); }
  catch { loading.textContent = "Could not load the character list. Reload the page to try again."; return; }
  loading.remove();
  if (Array.isArray(list) && list.length) {
      const searchWrap = h("div", { class: "sheet-picker-search" });
      const label = h("label", { for: "sheet-character-search" }, "Search characters");
      const controls = h("div", { class: "sheet-picker-search-controls" });
      const input = h("input", { id: "sheet-character-search", class: "input", type: "search", autocomplete: "off" });
      const clear = h("button", { class: "btn", type: "button", "aria-label": "Clear character search", hidden: true }, "×");
      const count = h("p", { class: "muted", role: "status", "aria-live": "polite" });
      searchWrap.append(label, controls); controls.append(input, clear); card.append(searchWrap, count);
      card.append(h("ul", null, list.map((c) => {
        const url = new URL(location.href);
        // Picking a character leaves list mode and opens that character's sheet in this window.
        url.searchParams.delete("pick");
        url.searchParams.set("project", c.project_id);
        return h("li", null, h("a", { href: url.pathname + url.search }, `${c.display_name} — CL ${c.cultivation_level} ${c.path || ""}`));
      })));
      const links = [...card.querySelectorAll("ul a")];
      const filter = () => {
        const query = input.value;
        let visible = 0;
        for (const link of links) { const matches = globalThis.CharacterSearch.matches(query, [link.textContent]); link.parentElement.hidden = !matches; if (matches) visible += 1; }
        count.textContent = `${visible} of ${links.length} ${links.length === 1 ? "character" : "characters"}`;
        clear.hidden = !query;
        let empty = card.querySelector(".sheet-picker-empty");
        if (query && !visible) { if (!empty) { empty = h("p", { class: "muted sheet-picker-empty" }); card.append(empty); } empty.textContent = `No characters match '${query}'`; }
        else empty?.remove();
      };
      input.addEventListener("input", filter);
      clear.addEventListener("click", () => { input.value = ""; filter(); input.focus(); });
      input.addEventListener("keydown", event => { if (event.key === "Escape") { input.value = ""; filter(); } });
      filter();
  }
}

async function main() {
  applyTheme(null, false);
  window.TianxiaAppearance?.onChange(() => applyTheme(null, false));
  wireSheet();
  wireEditor();
  const dicePromise = loadDice();
  // The table's Characters button opens ?pick=1: show the list first even before a character is chosen.
  const listOnly = params.get("pick") === "1";
  if (listOnly || !state.projectId) {
    await showPicker(listOnly
      ? "Choose a character to open their sheet in this window:"
      : "Open this sheet from the combat table, or choose a character:");
    $("sheet").setAttribute("aria-busy", "false");
    return;
  }
  try {
    const sheet = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(state.projectId)}/sheet`);
    state.sheet = sheet;
    state.summary = sheet.summary || {};
    indexLibraryText(sheet.library);
    indexButtons(sheet.buttons, sheet.layout);
  } catch (error) {
    await showPicker(sheetLoadMessage(error));
    $("sheet").setAttribute("aria-busy", "false");
    return;
  }
  renderAll();
  // Owner character sheet entry: ?tab=grow opens the Grow tab; unknown names are ignored.
  const requestedTab = params.get("tab");
  if (requestedTab && [...document.querySelectorAll("#tablist [role=tab]")].some(tab => tab.dataset.tab === requestedTab)) selectTab(requestedTab);
  if (params.get("token") === "1") openToken();  // the builder's "Make a token" (owner 2026-09-27)
  renderLog();
  $("sheet").setAttribute("aria-busy", "false");
  startChannel();
  await dicePromise;
}

main();
