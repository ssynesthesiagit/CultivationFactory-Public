// Fix round r1 for the owner's 2026-10-08 object catalog expansion (SON198.review.md findings 1 and 2):
// the map editor's object picker must never let the Objects tool place a blank/unmatched preset (an empty
// search leaves the <select> on its disabled "No matches" option; the server otherwise quietly saves that as
// an unrelated "custom" object -- combat/tabletop.py _objects), and it must show a preset's own damage
// threshold default rather than claiming "Blank: none" for presets that carry one (combat/object_rules.py
// presets). Both regressions fail against the pre-fix mapeditor.js/mapeditor.html (empty kind gets placed;
// threshold text/placeholder stay silent), and pass after it.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';

const staticURL = new URL('../static/tabletop/', import.meta.url);
async function until(check) { for (let i = 0; i < 100; i++) { if (check()) return; await tick(); } assert.ok(check(), 'editor settled'); }
function mockAPI(handler) {
  globalThis.fetch = async (path, options = {}) => {
    const result = await handler(path, options.body ? JSON.parse(options.body) : null);
    return {ok: true, status: 200, text: async () => JSON.stringify(result), json: async () => result};
  };
}

// Two presets, one group each, distinct enough names to filter on; "bronze_ding" carries a preset-level
// damage threshold (the exact shape combat/object_rules.editor_defaults() sends), "market_stall" has none.
const DEFAULTS = {
  presets: {
    bronze_ding: {hp: 27, ac: 19, size: 'large', resilient: true, threshold: 5,
      name: 'Bronze ding cauldron', description: 'A three-legged ritual cauldron.', group: 'temple'},
    market_stall: {hp: 5, ac: 15, size: 'small', resilient: false,
      name: 'Market stall', description: 'A wooden stall with a striped awning.', group: 'village'},
  },
  groups: {temple: 'Temple / sect', village: 'Village / market'},
  materials: {wood: 15, bronze: 19},
  sizes: {small: {0: 3, 1: 10}, large: {0: 5, 1: 27}},
};

function boot() {
  const dom = installDOM(readFileSync(new URL('mapeditor.html', staticURL), 'utf8'));
  mockAPI((path) => {
    if (path === '/api/session') return {token: 'test'};
    if (path === '/api/tabletop/terrains') return {terrains: [], ground: {}};
    if (path === '/api/tabletop/maps') return {maps: [], builtin: [], object_defaults: DEFAULTS};
    throw Error(`Unexpected API ${path}`);
  });
  return dom;
}
const clickCell = (viewport, x, y) => viewport.dispatch('pointerdown', {clientX: x * 64 + 10, clientY: y * 64 + 10, button: 0});

test('the picker refuses to place with no valid preset selected, recovers once the search clears, and keeps a still-matching selection', async () => {
  const dom = boot();
  await import('../static/tabletop/mapeditor.js');
  await until(() => window.mapEditor);
  const {editor} = window.mapEditor;
  dom.querySelector('[data-tool="object"]').click();
  const search = dom.querySelector('#meObjectSearch');
  const kindSelect = dom.querySelector('#meObjectKind');
  const viewport = dom.querySelector('#meViewport');

  // Baseline: with a real preset selected, placing on open ground works.
  assert.ok(kindSelect.value in DEFAULTS.presets, `expected a real preset selected, got ${JSON.stringify(kindSelect.value)}`);
  await clickCell(viewport, 2, 2);
  assert.equal(editor.doc.objects.length, 1);
  // A large cauldron fills its square, so a second one is refused there (SOL201 shared squares), then the
  // selected one is removed to get back to empty for the real test.
  await clickCell(viewport, 2, 2);
  assert.equal(editor.doc.objects.length, 1);
  assert.match(dom.querySelector('.tt-toast.is-error')?.textContent || '', /no room/i);
  dom.querySelectorAll('.tt-toast').forEach(node => node.remove());
  dom.querySelector('#meObjectRemove').click();
  assert.equal(editor.doc.objects.length, 0);

  // An unmatched search leaves no placeable option.
  search.value = 'no such object anywhere';
  await search.dispatch('input');
  assert.equal(kindSelect.value, '', 'the "No matches" option must resolve to an empty, unplaceable value');

  // Clicking open ground must not save a blank-kind object, and must tell the player why.
  await clickCell(viewport, 5, 5);
  assert.equal(editor.doc.objects.length, 0, 'an unmatched search must not place anything');
  const errorToast = dom.querySelector('.tt-toast.is-error');
  assert.ok(errorToast, 'placing with no match selected must show an error toast');
  assert.match(errorToast.textContent, /pick an object/i);

  // Clearing the search must restore a real, placeable preset.
  search.value = '';
  await search.dispatch('input');
  assert.ok(kindSelect.value in DEFAULTS.presets, 'clearing the search must land on a real preset again');
  await clickCell(viewport, 5, 5);
  assert.equal(editor.doc.objects.length, 1);
  assert.ok(editor.doc.objects[0].kind in DEFAULTS.presets, `placed a non-preset kind ${JSON.stringify(editor.doc.objects[0].kind)}`);

  // Selecting a specific preset and narrowing the search to something that still names it must not
  // disturb the selection (the picker must not silently fall back to the first group/option).
  kindSelect.value = 'market_stall';
  search.value = 'market';
  await search.dispatch('input');
  assert.equal(kindSelect.value, 'market_stall', 'a still-matching selection must survive narrowing the search');
});

test('the picker shows a preset\'s own damage threshold default instead of claiming "none"', async () => {
  const dom = boot();
  await import('../static/tabletop/mapeditor.js?picker-threshold-case');
  await until(() => window.mapEditor);
  const kindSelect = dom.querySelector('#meObjectKind');
  const thresholdInput = dom.querySelector('#meObjectThreshold');
  const desc = dom.querySelector('#meObjectDesc');

  kindSelect.value = 'bronze_ding';
  await kindSelect.dispatch('change');
  assert.equal(thresholdInput.placeholder, '5', 'the box must show this preset\'s real default, not a generic placeholder');
  assert.match(desc.textContent, /damage threshold of 5/i);
  assert.match(desc.textContent, /less than 5 damage does nothing/i);

  kindSelect.value = 'market_stall';
  await kindSelect.dispatch('change');
  assert.equal(thresholdInput.placeholder, 'none', 'a preset with no default threshold must still say so');
  assert.doesNotMatch(desc.textContent, /damage threshold/i);
});
