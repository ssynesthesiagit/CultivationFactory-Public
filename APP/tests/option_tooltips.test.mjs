// Node-only regression tests. No browser/GUI is launched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {rulesTextFor, uniqueRuleBlocks, additionalRuleText} from '../static/tabletop/rules.js';
import {layoutText} from '../static/tabletop/presentation.js';
// Python test_option_tooltips supplies fresh real compiled rows in memory.
const hasRowsInput = Object.hasOwn(process.env, 'SOL155_ROWS');
const rows = JSON.parse(process.env.SOL155_ROWS || '[]');
const source = readFileSync(new URL('../static/tabletop/sheet.js', import.meta.url), 'utf8');
const describe = new Function('layoutText', 'uniqueRuleBlocks', 'plainRules', 'state', 'norm',
  source.slice(source.indexOf('function describe('), source.indexOf('\n// Not a GM process:')) + '; return describe;')
  (layoutText, uniqueRuleBlocks, x => String(x || ''), {}, x => String(x).toLowerCase());
const cases = [
  ['Open the Gate: Breath-Checking Strike', 'cannot take Opportunity Attacks'],
  ['Open the Gate: Centerline Impact', 'add your Proficiency Bonus'],
  ['Open the Gate: Hooking Step', 'Move yourself 5 feet'],
  ['Shape Darkness: Numbing Darkness', 'Numbing Darkness'],
  ['Augment Darkness: Persistent Darkness', 'without Concentration'],
  ['Nullifying Strike: Ask me when it hits', 'The target makes a Constitution saving throw'],
  ['Nullifying Strike: No Reactions — the target cannot take Reactions until the start of its next turn', 'cannot take Reactions until the start of its next turn'],
  ['Overdraw: ready', 'add bonus Ruin damage'],
];
for (const [label, effect] of cases) {
  test(`sheet and table builders retain printed option: ${label}`, {skip: !hasRowsInput}, () => {
    const row = rows.find(r => r.label === label);
    assert.ok(row, `Real row missing: ${label}`);
    for (const build of [describe, r => rulesTextFor({library: {groups: []}}, r)]) {
      const text = build(row);
      assert.ok(text.includes(effect), text);
      assert.equal(text.split('Choosing this option takes no action').length - 1, 1, text);
      assert.ok(text.indexOf(effect) < text.indexOf('Choosing this option'), text);
      const duplicated = {...row, hover: null, description: `${text}\n\n${text}`};
      assert.equal(build(duplicated), text);
      assert.equal(additionalRuleText(text, row.description), '');
    }
  });
}
