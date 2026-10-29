import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {actionCardModel, actionHoverText, actionTipCard, renderTipCard, rulesTextFor} from '../static/tabletop/rules.js';

const hover = JSON.parse(fs.readFileSync(0, 'utf8'));
const row = {label: 'Sample', hover, variant_of: 'base'};
const display = hover.player_card;
assert.equal(rulesTextFor({library: {groups: []}}, row), display.text);
assert.equal(actionHoverText(row), display.text);
const document = {createElement: () => ({innerHTML: '', prepend() {}})};
assert.equal(renderTipCard(document, actionCardModel(row)).innerHTML, display.html);
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
