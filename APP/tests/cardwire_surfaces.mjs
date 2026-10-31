import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {actionCardModel, actionHoverText, actionTipCard, renderTipCard, rulesTextFor} from '../static/tabletop/rules.js';
import TianxiaSheetViewModel from '../static/sheet_view_model.js';

const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const hover = payload.hover || payload;
const row = {label: 'Sample', hover, variant_of: 'base'};
const display = hover.player_card;
assert.equal(rulesTextFor({library: {groups: []}}, row), hover.text || display.text);
assert.equal(actionHoverText(row), hover.text || display.text);
const document = {createElement: () => ({innerHTML: '', prepend(node) { this.context = node.textContent; }})};
const rendered = renderTipCard(document, actionCardModel(row));
assert.equal(rendered.innerHTML, [display, ...(hover.related_cards || [])].map(card => card.html).join("\n"));
if (hover.context) assert.equal(rendered.context, `This use: ${hover.context}`);
// Exercise the action bar's actual assembler as well as the shared tip model.
const table = fs.readFileSync("static/tabletop/tabletop.js", "utf8");
const assemble = table.slice(table.indexOf("function actionRules("), table.indexOf("\nfunction buttonDetail("));
const actionRules = new Function("document", "renderTipCard", `${assemble}; return actionRules;`)(document, renderTipCard);
const actionBar = actionRules(hover.text, "Sample", hover);
assert.equal(actionBar.innerHTML, rendered.innerHTML);
if (hover.context) assert.equal(actionBar.context, `This use: ${hover.context}`);
if (process.argv[2] === "live") {
  assert.ok(rendered.context.includes("Once per round"));
  const model = actionCardModel({...row, detail: {range: "30 feet"}});
  assert.ok(model.context.includes("Once per round") && model.context.includes("Range: 30 feet"));
}
if (process.argv[2] === 'reaction') {
  const source = fs.readFileSync('static/tabletop/sheet.js', 'utf8');
  const state = {sheet: {features: {automated_reactions: ['sample']}},
    libraryById: new Map([['sample', {name: 'Sample', text: display.text, hover}]])};
  const context = vm.createContext({state, actionTipCard, featureInfo: () => ({name: 'Sample'}),
    norm: s => s.toLowerCase(), h: (tag, attrs) => ({attrs})});
  vm.runInContext(source.slice(source.indexOf('function reactionRows()'), source.indexOf('function actionGroupSection(')), context);
  const row = context.reactionRows()[0];
  assert.ok(row.attrs.title.includes(display.text));
  assert.equal(row.attrs.tipCard(document).innerHTML, display.html);
}
if (process.argv[2] === 'status') {
  const status = {condition_id: "condition:typed.mark.sample.mei", display_name: "Sample mark",
    detail: payload.detail, hover};
  const actor = {entity_id: "mei", display_name: "Mei", conditions: [status],
    hit_points: {current: 10, maximum: 10}};
  const pill = {};
  const element = {addEventListener() {}};
  const host = {innerHTML: "", contains: () => false,
    querySelector: selector => ["[data-ac-breakdown]", "[data-seat-log]"].includes(selector) ? null : element,
    querySelectorAll: selector => selector === ".is-condition" ? [pill] : []};
  const context = vm.createContext({document, actionTipCard, renderTipCard, TianxiaSheetViewModel,
    $: () => host, app: {selected: new Set(["mei"]), state: {}, seatStatus: null},
    actorById: () => actor, renderInformation() {}, currentViewer: () => ({}),
    shownCondition: () => true, conditionInfo: {rows: {}}, projectOf: () => null,
    initials: () => "M", TEAM_COLORS: [], teamIndex: () => 0, pct: () => 100,
    concentrationCard: () => "", unseenByViewers: () => false, economyPills: () => "",
    flightText: () => "", board: {}, movementLeft: () => "", escapeHtml: s => s,
    hoverCard: {isOpen: false}, modelOwner: () => null, controlOf: () => "MANUAL",
    isManualActor: () => true, presentation: () => null});
  const section = (source, start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
  vm.runInContext(section(table, "const TONE_MEANING", "// The combat log")
    + section(table, "function renderInspector()", "function escapeHtml("), context);
  context.renderInspector();
  assert.ok(host.innerHTML.includes(payload.detail));
  assert.equal(pill.tipCard(document).innerHTML, display.html);
  assert.equal(pill.tipCard(document).context, `This use: ${hover.context}`);

  // Exercise the real message transfer and pop-out condition renderer too.
  const sheet = fs.readFileSync("static/tabletop/sheet.js", "utf8");
  const sheetPills = [];
  Object.assign(context, {actor, state: {summary: {}, connected: true}, poolRows: () => [],
    h: (tag, attrs) => { if (attrs?.class?.startsWith("cond ")) sheetPills.push(attrs); },
    $: () => ({replaceChildren() {}})});
  vm.runInContext(section(table, "function actorMessage(actor)", "function broadcastActors()"), context);
  context.state.actor = JSON.parse(JSON.stringify(context.actorMessage(actor)));
  vm.runInContext(section(sheet, "function renderDefenses()", "function renderSkills()"), context);
  context.renderDefenses();
  assert.ok(sheetPills[0].title.startsWith(payload.detail));
  assert.equal(sheetPills[0].tipCard(document).innerHTML, display.html);
  assert.equal(sheetPills[0].tipCard(document).context, `This use: ${hover.context}`);
  assert.ok(hover.context.includes("Applied by Mei") && hover.context.includes("Lasts until removed."));
  assert.ok(hover.context.includes("The next hit consumes this mark.") && hover.context.includes("Used by: Spend Sample."));
}
if (process.argv[2] === 'builder') {
  const source = fs.readFileSync('static/app.js', 'utf8');
  const declaration = source.match(/function recordCard\(display\) \{[\s\S]*?\n\}/)[0];
  const context = vm.createContext({document});
  vm.runInContext(declaration, context);
  assert.equal(context.recordCard(display).innerHTML, display.html);
}
