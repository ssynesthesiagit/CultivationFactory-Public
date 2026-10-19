import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {TERRAIN_LOOKS, terrainCellMarkup, terrainLook, terrainPresentation, terrainTooltip} from './terrain-art.js';
import {ruleTerrainEntriesAt, ruleTerrainTransform} from './board.js';

const types = ['DIFFICULT', 'SIMPLE_COVER', 'QI_HAZARD'];
const hasStrokeDeclaration = rule => /stroke(?:-width)?\s*:/.test(rule);

test('border assertion recognizes ordinary SVG stroke declarations', () => {
  assert.equal(hasStrokeDeclaration('stroke: red'), true);
  assert.equal(hasStrokeDeclaration('stroke-width: 1.92'), true);
  assert.equal(hasStrokeDeclaration('fill: none'), false);
});

test('each rule terrain type paints natural art without a rules frame, hatch, or label by default', () => {
  for (const type of types) {
    const presentation = terrainPresentation(type);
    const markup = terrainCellMarkup(type, terrainLook({type}, 'mountain'));
    assert.deepEqual([presentation.edge, presentation.hatch, presentation.label], [false, false, false]);
    assert.match(markup, /<g class="tt-rule-terrain/);
    assert.doesNotMatch(markup, /tt-cell-|tt-zone-(?:outline|halo|hatch|label)|<rect/);
  }
});

test('the rules overlay marks rules squares without restoring the removed border grid', () => {
  for (const type of types) {
    const presentation = terrainPresentation(type, true);
    const markup = terrainCellMarkup(type, 'stones', true);
    assert.deepEqual([presentation.edge, presentation.hatch, presentation.label], [true, type === 'DIFFICULT', false]);
    assert.match(markup, new RegExp(`class="tt-cell-${type === 'SIMPLE_COVER' ? 'cover' : type === 'QI_HAZARD' ? 'hazard' : 'difficult'}"`));
    assert.match(markup, /<rect x="0" y="0" width="64" height="64"/);
  }
  const css = readFileSync(new URL('./tabletop.css', import.meta.url), 'utf8');
  for (const cls of ['cover', 'hazard', 'difficult']) {
    const rule = new RegExp(`\\.tt-cell-${cls}\\s*\\{([^}]*)`).exec(css)?.[1] || '';
    assert.equal(hasStrokeDeclaration(rule), false, `.tt-cell-${cls} remains borderless`);
  }
  assert.equal(ruleTerrainTransform(6, 2), 'translate(6 2) scale(0.015625)');
});

test('the loaded Sect Trial Platform board keeps every overlapping terrain rule for hover', () => {
  const map = JSON.parse(readFileSync(new URL('../../combat/maps/builtin-sect-trial-platform.json', import.meta.url), 'utf8'));
  const terrain = [...map.terrain, {type: 'DIFFICULT', cells: [[6, 2]]}];
  assert.deepEqual(ruleTerrainEntriesAt(terrain, 6, 2, map.background?.style).map(entry => entry.type), ['SIMPLE_COVER', 'DIFFICULT']);
});

test('all built-in map rule terrain entries declare a supported look without changing their rules', () => {
  const names = ['bamboo-forest-ravine', 'mist-courtyard', 'mountain-pass', 'pillar-arena', 'ruined-spirit-shrine', 'sect-trial-platform'];
  for (const name of names) {
    const map = JSON.parse(readFileSync(new URL(`../../combat/maps/builtin-${name}.json`, import.meta.url), 'utf8'));
    for (const row of map.terrain) {
      assert.ok(TERRAIN_LOOKS.includes(row.look), `${name}: unsupported or missing ${row.type} look`);
      assert.ok(types.includes(row.type), `${name}: unknown rule terrain type ${row.type}`);
      assert.ok(Array.isArray(row.cells) && row.cells.length > 0);
    }
  }
});

test('floor materials choose sensible default art for each rules terrain type', () => {
  assert.equal(terrainLook({type: 'DIFFICULT'}, 'mountain'), 'scree');
  assert.equal(terrainLook({type: 'DIFFICULT'}, 'bamboo'), 'roots');
  assert.equal(terrainLook({type: 'SIMPLE_COVER'}, 'shrine'), 'pillar_rubble');
  assert.equal(terrainLook({type: 'SIMPLE_COVER'}, 'pillar'), 'statue_plinth');
});

test('terrain hover explains movement, cover, and hazard rules in player language', () => {
  assert.match(terrainTooltip('DIFFICULT').line, /each foot of movement.*one extra foot/i);
  assert.match(terrainTooltip('SIMPLE_COVER').line, /creature protected.*\+2 AC/i);
  assert.match(terrainTooltip('QI_HAZARD').line, /trigger and save rules/i);
});
