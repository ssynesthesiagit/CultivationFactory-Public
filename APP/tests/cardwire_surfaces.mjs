import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {actionCardModel, actionHoverText, actionTipCard, renderTipCard, rulesTextFor} from '../static/tabletop/rules.js';

const hover = JSON.parse(fs.readFileSync(0, 'utf8'));
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
if (process.argv[2] === 'builder') {
  const source = fs.readFileSync('static/app.js', 'utf8');
  const declaration = source.match(/function recordCard\(display\) \{[\s\S]*?\n\}/)[0];
  const context = vm.createContext({document});
  vm.runInContext(declaration, context);
  assert.equal(context.recordCard(display).innerHTML, display.html);
}
