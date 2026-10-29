import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {actionCardModel, actionHoverText, renderTipCard, rulesTextFor} from '../static/tabletop/rules.js';

const hover = JSON.parse(fs.readFileSync(0, 'utf8'));
const row = {label: 'Sample', hover, variant_of: 'base'};
const display = hover.player_card;
assert.equal(rulesTextFor({library: {groups: []}}, row), display.text);
assert.equal(actionHoverText(row), display.text);
const document = {createElement: () => ({innerHTML: '', prepend() {}})};
assert.equal(renderTipCard(document, actionCardModel(row)).innerHTML, display.html);
if (process.argv[2] === 'builder') {
  const source = fs.readFileSync('static/app.js', 'utf8');
  const declaration = source.match(/function recordCard\(display\) \{[\s\S]*?\n\}/)[0];
  const context = vm.createContext({document});
  vm.runInContext(declaration, context);
  assert.equal(context.recordCard(display).innerHTML, display.html);
}
