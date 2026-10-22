import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as seats from '../static/tabletop/seats.js';
import {glossaryText, resourceText, GLOSSARY} from '../static/tabletop/newcomer.js';
import {RESOURCE_RULES} from '../static/tabletop/newcomer-data.js';
import {playerError} from '../static/tabletop/error-text.js';
import {api, ApiError} from '../static/tabletop/api.js';
import {installGlossary} from '../static/tabletop/newcomer.js';
import TianxiaSheetViewModel from '../static/sheet_view_model.js';
import {renderTipCard} from '../static/tabletop/rules.js';
import {effectText, durationText} from '../static/tabletop/zone-text.js';
import {MARK_DURATIONS} from '../static/tabletop/zone-text-data.js';
import {zoneTooltip, zoneLook} from '../static/tabletop/zones.js';
import {liveStats} from '../static/tabletop/live-stats.mjs';
import {concentrationCard} from '../static/tabletop/concentration.js';
import {economyPills} from '../static/tabletop/action-economy.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js?v=rel6-2';
import {resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';
import {heightFeet, flightText} from '../static/tabletop/flight-ui.js';
import {creatureHeightFt, onRoof} from '../static/tabletop/roof-regions.js?v=rel6-2';
import {tokenSensePresentation} from '../static/tabletop/vision.js?v=rel6-2';

test('token hover condition projection uses a neutral label when display text is missing', () => {
  const source = fs.readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function renderTokens(');
  assert.notEqual(start, -1);
  const end = source.indexOf('\n}', start) + 2;
  const renderTokens = source.slice(start, end);
  const actor = {entity_id: 'foe', display_name: 'Foe', position: {x: 1, y: 2}, hit_points: {current: 4, maximum: 5},
    active: true, conditions: [{condition_id: 'condition:typed.internal_only_suffix'}]};
  let rendered;
  const app = {state: {tokens: {}, presentation: {battlefield: {blocked_cells: []}}}, selected: new Set(), targeting: {byTarget: new Map()}};
  // This condition-wording fixture explicitly uses the GM role. Independent
  // player bindings and covered frames have their own production wiring tests.
  const currentViewer = () => resolveViewerIdentity({version:1,role:'gm',actor_ids:[]},[],{seats:{}});
  const ctx = vm.createContext({app, heightFeet, flightText, tokenSensePresentation, fogAudience:()=>[], currentViewer, isGMView:()=>true, isOwnedActor:()=>false,
    reconcileViewerIdentity:()=>false, resumeViewerDialogs() {}, roofAudience:()=>[], $:()=>null,
    document:{body:{classList:{toggle() {}}}},
    board: {map: {width: 10}, setTokens: rows => {rendered = rows;}, setFog() {}, setRoofView() {}},
    presentation: () => ({actors: [actor], current_actor_id: 'foe'}), tokenLabels: () => new Map(), visibility: () => null,
    actors: () => [actor], tokenGeometry: () => ({}), teamIndex: () => 0, TEAM_HEX: ['#fff'], unseenByViewers: () => false,
    isManualActor: () => false, shownCondition: () => true, conditionText: () => '', conditionTone: () => 'debuff', OBJECT_FACE: {}, tableObjectTokens,
    fogGeometry: () => [], tokenImage: () => null});
  vm.runInContext(renderTokens, ctx);
  ctx.renderTokens();
  assert.equal(rendered[0].conditions[0].name, 'Condition');
  assert.ok(!rendered[0].conditions[0].name.includes('internal_only_suffix'));

  const boardSource = fs.readFileSync(new URL('../static/tabletop/board.js', import.meta.url), 'utf8');
  const cardStart = boardSource.indexOf('  function showCard(');
  const cardEnd = boardSource.indexOf('\n  }', cardStart) + 4;
  const cardNode = {style: {}, classList: {toggle() {}}, innerHTML: '', offsetHeight: 40};
  const hoverCtx = vm.createContext({card: {node: cardNode}, tokens: new Map(), window: {innerWidth: 800},
    hover: {open({build}) {build(cardNode);}},
    escapeText: text => String(text ?? ''), hideCard() {}, creatureHeightFt, onRoof, flightText, heightFeet, map: {width: 10, height: 10}});
  const displayedStart = boardSource.indexOf('  function displayedCreature(');
  const displayedEnd = boardSource.indexOf('\n  }', displayedStart) + 4;
  vm.runInContext(boardSource.slice(displayedStart, displayedEnd), hoverCtx);
  vm.runInContext(boardSource.slice(cardStart, cardEnd), hoverCtx);
  hoverCtx.showCard({data: rendered[0], node: {getBoundingClientRect: () => ({left: 10, top: 50, width: 40, bottom: 90})}});
  assert.match(cardNode.innerHTML, /<span class="tt-card-cond">Condition<\/span>/);
  assert.ok(!cardNode.innerHTML.includes('internal_only_suffix'));
});

test('terms have whole-word, case-insensitive help without changing text', () => {
  for (const row of GLOSSARY) for (const term of row.terms) {
    assert.ok(glossaryText(`Cost: ${term.toLowerCase()}!`).includes(row.text), term);
  }
  assert.equal(glossaryText('equipment, recharge, resonanceful, domainless, bookmark'), '');
  assert.match(glossaryText('2 CP'), /cultivation points/);
  assert.match(glossaryText('Meld'), /one Action.*costs no CP.*Persistent Meld costs 2 CP/);
  assert.doesNotMatch(glossaryText('Meld'), /Rapid Meld|10 minutes/);
  assert.match(glossaryText('Black Vein Strain'), /named counter or effect.*Printed examples/s);
  assert.match(glossaryText('Heavens Notice'), /Fate techniques/);
});

test('resources explain live amounts and distinct recovery, never infer an unknown rule', () => {
  for (const name of ['Qi', 'Stamina', 'Resonance']) {
    const text = resourceText({display_name: name, current: 0, maximum: 51});
    assert.match(text, /0 current \/ 51 maximum/);
    assert.match(text, /Short Rest|Short rest/);
    assert.match(text, /Long Rest|Long rest/);
    assert.match(text, /outside this fight/);
    assert.match(text, /spend|Spend/);
  }
  assert.match(resourceText({name: 'Stamina', current: 23, maximum: 51}), /twice between long rests/);
  assert.match(resourceText({name: 'Resonance'}), /half your maximum/);
  assert.match(resourceText({name: 'Black Vein Strain', current: 2, maximum: 3}), /Printed examples.*only if you have/s);
  assert.match(resourceText({name: 'Unknown resource'}), /no matching spending or recovery summary.*Ask the GM/s);
  assert.match(resourceText({name: 'Martial Focus'}), /hold more than one/);
  const abilities = [{label: 'Technique', detail: {cost: '2 Qi, 1 use'}}, {label: 'Other', detail: {cost: '2 Devil Qi'}}];
  const help = resourceText({name: 'Qi'}, abilities);
  assert.match(help, /Your sheet's listed costs:\nTechnique: 2 Qi, 1 use/);
  assert.doesNotMatch(help, /Other: 2 Devil Qi/);
  assert.match(resourceText({name: 'CP'}), /Ask the GM which of Qi, Stamina or Resonance pays/);
  assert.match(resourceText({name: 'Edict Seal'}), /Generation Limit: Once per round/);
  assert.match(resourceText({name: 'Edict Seal'}), /Printed spending examples.*Cost: 1 Edict Seal/s);
  assert.doesNotMatch(resourceText({name: 'Edict Seal'}), /\|---|\| Maximum/);
});

test('errors give a next step without displaying backend ids or paths', () => {
  for (const status of [0, 400, 403, 404, 409, 413, 422, 500]) {
    const error = new ApiError('SECRET /private/path action:typed.internal', 'OTHER', status);
    assert.doesNotMatch(error.message, /SECRET|private|action:typed/);
    assert.match(error.message, /Check|check|Reload|choose|Choose|Return|Reopen|reopen/);
    assert.equal(error.diagnosticMessage, 'SECRET /private/path action:typed.internal');
  }
  assert.match(playerError({code: 'COMBAT_CONTENT_NOT_READY'}), /keep the saved fight/);
});

test('a busy table says wait and try again, not that the fight changed', () => {
  // MMX112f1. The server already answers a busy table with TABLETOP_BUSY/409 and a plain "try again" sentence
  // (APP/combat/tabletop_service.py TABLE_BUSY_MESSAGE), but the page displays ApiError.message, which is built by
  // playerError -- and a bare 409 fell into the generic "the fight or its choices have changed" branch. The player was
  // told their turn had moved on when nothing had changed at all. This drives the real adapter the page uses.
  const busy = new ApiError('Another action on this table is still finishing. Wait a moment, then try again.',
                             'TABLETOP_BUSY', 409);
  assert.match(busy.message, /try again/i);
  assert.doesNotMatch(busy.message, /choices have changed/i, 'a busy table must not claim the fight changed');
  assert.doesNotMatch(busy.message, /choose from the current turn/i, 'a busy table must not send the player to re-pick');
  // Newcomer-readable (rule 13): no code names, no HTTP jargon, and it says what to do next.
  assert.doesNotMatch(busy.message, /TABLETOP_BUSY|409|state_version|flock|gate3|action:typed/i);
  // The server's own sentence is kept off the screen and only on the diagnostic field, as for every other error.
  assert.equal(busy.diagnosticMessage, 'Another action on this table is still finishing. Wait a moment, then try again.');
  // What reaches the player is chosen by CODE, never interpolated from the server, so internal detail cannot leak
  // even when the server sends some.
  const noisy = new ApiError('MATCH_STORAGE_LOCKED /var/lib/matches/abc/.tabletop_action.lock',
                             'TABLETOP_BUSY', 409);
  assert.doesNotMatch(noisy.message, /MATCH_STORAGE_LOCKED|\/var\/lib|tabletop_action\.lock/);
  assert.equal(noisy.diagnosticMessage, 'MATCH_STORAGE_LOCKED /var/lib/matches/abc/.tabletop_action.lock');

  // The specific code must win regardless of the status the page happens to see, and the other 409s (a genuinely
  // changed decision) must keep their own message -- this is an added branch, not a replaced one.
  assert.match(playerError({code: 'TABLETOP_BUSY'}), /try again/i);
  assert.match(playerError({code: 'DECISION_STALE', status: 409}), /choices have changed/i);
  assert.match(playerError({code: 'STATE_VERSION', status: 409}), /choices have changed/i);
});

test('friendly messages preserve the one-time session-token retry', async () => {
  const original = globalThis.fetch;
  let sessions = 0, mutations = 0;
  globalThis.fetch = async path => {
    if (path === '/api/session') return {json: async () => ({token: `token-${++sessions}`})};
    mutations++;
    return mutations === 1
      ? {ok: false, status: 403, text: async () => JSON.stringify({error: {message: 'A valid local session token is required', code: 'TOKEN_REQUIRED'}})}
      : {ok: true, text: async () => '{"saved":true}'};
  };
  try {
    assert.deepEqual(await api('/test-only', {body: {test: true}}), {saved: true});
    assert.equal(sessions, 2);
    assert.equal(mutations, 2);
    globalThis.fetch = async () => {throw new TypeError('Failed to fetch');};
    await assert.rejects(api('/test-only'), /Check your connection/);
  } finally {globalThis.fetch = original;}
});

test('glossary enriches the one native tooltip instead of opening its own popup', () => {
  const events = new Map();
  function element(text = '', title = null) {
    const attributes = new Map(title === null ? [] : [['title', title]]);
    return {textContent: text, children: [],
      getAttribute: name => attributes.get(name) ?? null,
      setAttribute: (name, value) => attributes.set(name, value), hasAttribute: name => attributes.has(name),
      closest(selector) {return selector.startsWith('[title]') && attributes.has('title') ? this : null;}, querySelector: () => null};
  }
  let created = 0;
  const doc = {createElement: () => {created++; return element();}, body: element(), documentElement: element(),
    addEventListener: (name, handler) => events.set(name, handler)};
  installGlossary(doc);
  assert.equal(created, 0, 'no second tooltip element');
  assert.deepEqual([...events.keys()].sort(), ['focusin', 'pointerover']);
  const button = element('Spend 2 CP', 'Existing cost explanation');
  events.get('pointerover')({target: button});
  assert.match(button.getAttribute('title'), /^Existing cost explanation\n\nCP means cultivation points/);
  assert.equal(button.textContent, 'Spend 2 CP');
  // Hovering again (or focusing) does not append twice.
  const once = button.getAttribute('title');
  events.get('pointerover')({target: button});
  events.get('focusin')({target: button});
  assert.equal(button.getAttribute('title'), once);
  // A re-render that replaces the title is enriched again from the new text.
  button.setAttribute('title', 'New cost text');
  events.get('pointerover')({target: button});
  assert.match(button.getAttribute('title'), /^New cost text\n\nCP means/);
  // Plain text with a term gets a title; text without one is left alone.
  const pill = element('Martial Focus');
  events.get('pointerover')({target: pill});
  assert.match(pill.getAttribute('title'), /hold more than one/);
  const plain = element('Longsword');
  events.get('pointerover')({target: plain});
  assert.equal(plain.getAttribute('title'), null);
  // A container is never titled: its title would show on every control inside it (a prompt's option buttons).
  const prompt = element('Hollowed (2 Stamina) damages Bonded Spirit');
  prompt.children = [element('17,10'), element('18,12')];
  events.get('pointerover')({target: prompt});
  assert.equal(prompt.getAttribute('title'), null);
  // A dropdown inside a label: only the chosen option counts, not every option listed (owner 2026-09-30).
  const picker = element('Tabik Damu · BodyShi Xunyun · Resonance user', null);
  picker.closest = function (selector) { return selector.startsWith('[title]') ? this : null; };
  picker.querySelectorAll = () => [{textContent: 'Tabik Damu · BodyShi Xunyun · Resonance user', selectedOptions: [{textContent: 'Tabik Damu · Body'}]}];
  events.get('pointerover')({target: picker});
  assert.equal(picker.getAttribute('title'), null);
  // Definitions already in the title are not repeated; the native limit is respected.
  const explained = element('Qi', resourceText({name: 'Qi', current: 2, maximum: 5}));
  const before = explained.getAttribute('title');
  events.get('pointerover')({target: explained});
  assert.equal(explained.getAttribute('title'), before);
  const long = element('Stamina Qi Resonance Mark Meld Court Trace Charge Stance', 'x');
  events.get('pointerover')({target: long});
  assert.ok(long.getAttribute('title').length <= 1000);
});

test('every canonical duration uses the engine deadline in player language', () => {
  const rules = JSON.parse(fs.readFileSync(new URL('../combat/rules/typed_conditions.json', import.meta.url)));
  const expected = {
    instant: '', until_end_of_turn: 'until the end of the current turn',
    until_start_of_next_turn: "until the start of its creator's next turn",
    until_start_of_your_next_turn: "until the start of its creator's next turn",
    until_end_of_your_next_turn: "until the end of its creator's next turn",
    until_end_of_next_turn: "until the end of the affected creature's next turn",
    target_next_turn: "until the end of the affected creature's next turn",
    rounds: 'for 2 rounds', minutes: 'for 2 minutes', hours: 'for 2 hours',
    special: 'deadline not shown here; ask the GM when it ends',
    until_removed: "until removed by the ability's stated rules",
  };
  assert.deepEqual(Object.keys(expected).sort(), Object.keys(rules.durations).sort());
  for (const [kind, text] of Object.entries(expected)) {
    assert.equal(durationText({kind, amount: 2}), text, kind);
    if (!['rounds', 'minutes', 'hours'].includes(kind)) assert.equal(durationText(kind), text, kind);
  }
  assert.equal(rules.durations.target_next_turn, 'END_OF_HOLDER_NEXT_TURN');
  assert.equal(rules.durations.until_end_of_turn, 'END_OF_CURRENT_TURN');
  const known = fs.readFileSync(new URL('./test_expiry_names.py', import.meta.url), 'utf8');
  for (const expiry of Object.values(rules.durations).filter(Boolean)) assert.ok(known.includes(expiry), expiry);
});

// Minimal element for the sheet's h() helper; renderDefenses only builds rows and reads their dataset.
class Rendered {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.style = {setProperty(prop, v) { this[prop] = v; }}; this.className = ''; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener() {}
}

test('actual table and sheet resource renderers explain changing amounts without mutating the actor', () => {
  function body(file, name) {
    const source = fs.readFileSync(new URL(`../static/tabletop/${file}`, import.meta.url), 'utf8');
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0);
    return source.slice(start, source.indexOf('\n}', start) + 2);
  }
  function node() {return {textContent: '', innerHTML: '', style: {}, dataset: {}, classList: {toggle() {}}, children: [],
    setAttribute(name, value) {this[name] = value;}, removeAttribute(name) {delete this[name];}, addEventListener() {}, querySelector() {return node();}, querySelectorAll() {return [];},
    append(...kids) {this.children.push(...kids);}, replaceChildren(...kids) {this.children = kids;},
    get childNodes() {return this.children;}, ownerDocument: {createElement: tag => new Rendered(tag)}};}
  const nodes = new Map();
  const $ = key => {if (!nodes.has(key)) nodes.set(key, node()); return nodes.get(key);};
  const defenses = new Rendered('div');
  nodes.set('defenses', defenses);
  const actor = {display_name: 'Test', hit_points: {current: 10, maximum: 20},
    conditions: [{condition_id: 'condition:typed.internal_secret_condition'}],
    resources: [{resource_id: 'resource:core.qi', display_name: 'Qi', current: 7, maximum: 51}]};
  const before = JSON.stringify(actor);
  const context = vm.createContext({$, resourceText, liveStats, concentrationCard, flightText, heightFeet, economyPills, Node: Rendered,
    document: {querySelector: () => null, createElement: tag => new Rendered(tag)}, app: {selected: new Set(['test'])}, actorById: () => actor,
    // renderInspector() also paints the private-findings panel (information.js) for the current view.
    currentViewer: () => ({status: 'gm', ready: true}), isOwnedActor: () => false, actors: () => [actor],
    projectOf: () => null, unseenByViewers: () => false, TEAM_COLORS: ['blue'], teamIndex: () => 0, initials: () => 'T',
    shownCondition: () => true, conditionTone: () => 'neutral', conditionText: () => '', isManualActor: () => true,
    state: {summary: {resources: [{name: 'Qi', maximum: 51}], hit_points: actor.hit_points}, sheet: {},
      actor: {...actor, hp: actor.hit_points}, connected: true, buttons: []},
    showToken() {},
    norm: value => String(value).toLowerCase(), clamp01: n => Math.max(0, Math.min(1, n)),
    applyLegal() {},
    // Model seats (seats.js): no model plays this actor.
    ...seats, openSeatPicker() {}, openSeatLog() {},

    // The inspector's AC card and the shared card it refreshes (tabletop.js/sheet.js module bindings).
    TianxiaSheetViewModel, renderTipCard, hoverCard: {isOpen: false, trigger: null}, tableTipTargets: {show() {}},
    sheetHoverCard: {isOpen: false, trigger: null}, sheetTipTargets: {show() {}}, sheetFor: async () => null,
    armorTipCard: () => () => null, board: {centerOn() {}}});
  vm.runInContext(['escapeHtml', 'pct', 'renderInspector'].map(name => body('tabletop.js', name)).join('\n') +
    body('information.js', 'renderInformation') + '\n' +
    ['h', 'renderHeader', 'resourcePools', 'poolRows', 'renderDefenses', 'renderLive'].map(name => body('sheet.js', name)).join('\n'), context);
  context.renderInspector();
  assert.match($('#ttInspector').innerHTML, /data-tip="Qi: 7 current \/ 51 maximum/);
  assert.match($('#ttInspector').innerHTML, />Condition<\/span>/);
  assert.doesNotMatch($('#ttInspector').innerHTML, /internal_secret_condition/);
  assert.match($('#ttInspector').innerHTML, /Short rest/);
  // The sheet's Resources list: real rows, each tooltip from resourceText, spent amounts refreshed by renderLive.
  const rows = () => {
    const found = [];
    const walk = el => { for (const child of el.children) if (child instanceof Rendered) { if (child.className === 'res-row') found.push(child); walk(child); } };
    walk(defenses);
    return found;
  };
  const textOf = el => typeof el === 'string' ? el : el.children.map(textOf).join('');
  context.renderLive();
  assert.equal(rows().length, 1);
  assert.match(rows()[0].dataset.tip, /7 current \/ 51 maximum/);
  assert.equal(textOf(rows()[0].children[0]), 'Qi44 spent');
  actor.resources[0].current = 2;
  context.renderLive();
  assert.match(rows()[0].dataset.tip, /2 current \/ 51 maximum/);
  assert.equal(textOf(rows()[0].children[0]), 'Qi49 spent');
  actor.resources[0].current = 7;
  assert.equal(JSON.stringify(actor), before);
});

if (process.argv[2]) {
  const roster = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  test('owner roster resources and applicable glossary terms have help', () => {
    assert.ok(roster.length >= 50, 'read-only owner copies supplied');
    for (const actor of roster) {
      for (const row of actor.resources) {
        const text = resourceText(row);
        assert.match(text, /current \/ .* maximum/, actor.name);
        assert.doesNotMatch(text, /see its source/i, actor.name);
        const normalized = value => value.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
        const rules = RESOURCE_RULES[Object.keys(RESOURCE_RULES).find(key => normalized(key) === normalized(row.name))];
        assert.ok(rules?.length || /Ask the GM which of your abilities changes it/.test(text), `${actor.name}: ${row.name}`);
      }
      for (const zone of actor.zones || []) {
        const before = JSON.stringify(zone);
        const tooltip = zoneTooltip(zone, zoneLook(zone)).lines.join('\n');
        assert.doesNotMatch(tooltip, /:\s*mark(?:,|$)|forced_movement|temp_hp|STR_OR_DEX|undefined|NaN|None ft/, actor.name);
        assert.equal(JSON.stringify(zone), before, 'zone text never changes compiled rules');
      }
      for (const entry of GLOSSARY) for (const term of entry.terms) {
        if (actor.text.includes(term)) assert.ok(glossaryText(term), `${actor.name}: ${term}`);
      }
    }
  });
}

test('zone text shows named Marks, precise clocks and the actual trigger limit', () => {
  const compiled = JSON.parse(fs.readFileSync(new URL('../combat/rules/typed_conditions.json', import.meta.url), 'utf8')).mark_durations;
  assert.deepEqual(MARK_DURATIONS, Object.fromEntries(Object.entries(compiled).filter(([key]) => !key.startsWith('_'))));
  const effects = [{type: 'mark', mark: 'Charged', duration: {kind: 'until_start_of_your_next_turn'}}];
  assert.match(effectText(effects), /gain the “Charged” Mark.*start of its creator's next turn/s);
  assert.match(effectText([{type: 'mark', mark: 'Shadow Mark', duration: {kind: 'until_removed'}}]), /start of its creator's next turn/);
  assert.match(effectText([{type: 'mark', mark: 'Faultline Mark', duration: {kind: 'until_end_of_next_turn'}}]), /affected creature's next turn/);
  assert.match(effectText([{type: 'unexplained_private_kind'}]), /The Game Master resolves this additional effect/);
  assert.doesNotMatch(effectText([{type: 'unexplained_private_kind'}]), /unexplained_private_kind/);
  assert.match(effectText([{type: 'forced_movement', direction: 'toward_center', distance_ft: 10}]), /pulled 10 feet toward the area's center/);
  assert.match(effectText([{type: 'save', ability: 'STR_OR_DEX', on_fail: [{type: 'damage', flat: 4, damage_types: ['fire']}]}]), /Strength or Dexterity \(target chooses\) save: 4 fire damage/);
  assert.match(durationText({kind: 'minutes', amount: 2, concentration: true}), /2 minutes, while its creator concentrates/);
  const make = trigger => ({trigger_profile: {kind: 'TYPED', name: 'Test zone', triggers: [{on: ['enter'], who: 'hostile', effects, ...trigger}]}});
  for (const [trigger, expected] of [[{}, /once per turn per creature/], [{per_round: true}, /once per round per creature/],
    [{first_each_round: true}, /only the first qualifying creature each round/]]) {
    const zone = make(trigger);
    assert.match(zoneTooltip(zone, zoneLook(zone)).lines.join('\n'), expected);
  }
  assert.doesNotMatch(zoneLook({source_definition_id: 'action:typed.private.TAL_INTERNAL_123'}).name, /TAL_INTERNAL|123/);
});

test('map labels explain fields and omit source paths', () => {
  const html = fs.readFileSync(new URL('../static/tabletop/mapeditor.html', import.meta.url), 'utf8');
  assert.match(html, /Terrain proficiency bonus/);
  assert.match(html, /Terrain saving throw DC/);
  assert.match(html, /calculate damage/);
  assert.doesNotMatch(html, /Terrain PB|combat\/rules\//);
});
