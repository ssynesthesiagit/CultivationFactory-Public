import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {OptionDraft, draftButtonStates, overlayButtonStates} from '../static/tabletop/option-composition.js';
import {markActive} from '../static/tabletop/active.js';

// Sheet rows for two creatures. "plain" and "pure" are alternatives under one slot
// (same key), as the server issues them; the augments toggle independently.
const manifest = {
  pureC: {key: ['choice', 'darkness'], mode: 'select', source: 'pure', family: 'darkness'},
  plainC: {key: ['choice', 'darkness'], mode: 'select', source: 'plain', family: 'darkness'},
  eternalC: {key: ['augment', 'darkness', 'eternal'], mode: 'toggle', source: 'eternal', family: 'darkness'},
  greaterC: {key: ['augment', 'darkness', 'greater'], mode: 'toggle', source: 'greater', family: 'darkness'},
  clearC: {key: ['augment', 'darkness', null], mode: 'clear', source: 'clear', family: 'darkness'},
};
const shapes = {
  me: [{base: 'darkness', name: 'Darkness', options: [], modifiers: [],
    choices: [
      {label: 'Pure Darkness', button_id: 'act:pure', active: false, candidate_id: 'pureC'},
      {label: 'plain Darkness', button_id: 'act:plain', active: true, candidate_id: 'plainC'},
    ],
    augments: [
      {name: 'Eternal Darkness', button_id: 'act:eternal', on: false, candidate_id: 'eternalC'},
      {name: 'Greater Darkness', button_id: 'act:greater', on: true, candidate_id: 'greaterC'},
    ]}],
  other: [{base: 'darkness', name: 'Darkness', options: [], modifiers: [],
    choices: [
      {label: 'Pure Darkness', button_id: 'act:pure', active: false, candidate_id: 'pureC'},
      {label: 'plain Darkness', button_id: 'act:plain', active: true, candidate_id: 'plainC'},
    ], augments: []}],
};
const serverStates = {
  me: {'act:pure': {active: false}, 'act:plain': {active: true}, 'act:eternal': {active: false}, 'act:greater': {active: true}},
  other: {'act:pure': {active: false}, 'act:plain': {active: true}},
};
const menu = {actor_id: 'me', decision_id: 'decision:1', state_version: 4, manual: true, composition: manifest, actions: []};
const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const start = source.indexOf('// Sheet Active marks for the creature');
const end = source.indexOf('\nfunction broadcastActors()', start);
assert.ok(start > 0 && end > start, 'overlay helpers exist in tabletop.js');

function harness(draft) {
  const posted = [];
  const app = {
    menu, matchId: 'match', optionDraft: draft,
    state: {button_states: serverStates, shapes},
    channel: {postMessage: message => posted.push(message)},
  };
  const context = {app, OptionDraft, draftButtonStates, overlayButtonStates};
  vm.runInNewContext(source.slice(start, end), context);
  return {app, posted, sheetButtonStates: context.sheetButtonStates, broadcastDraftStates: context.broadcastDraftStates};
}

// The sheet's applyLegal marks every data-button-id element with markActive(el, state).
function sheetMarks(states, ids) {
  return Object.fromEntries(ids.map(id => {
    const classes = new Set();
    const el = {
      classList: {toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)), contains: name => classes.has(name)},
      querySelector: () => null, appendChild() {}, ownerDocument: {createElement: () => ({})},
    };
    markActive(el, states[id]?.active);
    return [id, el.classList.contains('is-choice-active')];
  }));
}
const ids = ['act:pure', 'act:plain', 'act:eternal', 'act:greater'];

test('without a draft the sheet keeps the server saved states', () => {
  const h = harness(null);
  assert.equal(h.sheetButtonStates('me'), serverStates.me);
  assert.deepEqual(sheetMarks(h.sheetButtonStates('me'), ids),
    {'act:pure': false, 'act:plain': true, 'act:eternal': false, 'act:greater': true});
});

test('a draft pick marks the chosen row Active, unmarks the default and toggles augments on the draft creature sheet', () => {
  const draft = new OptionDraft(menu, 'match');
  draft.choose('pureC');
  draft.choose('eternalC');
  draft.choose('greaterC'); // toggles the server-on augment off
  const h = harness(draft);
  const states = h.sheetButtonStates('me');
  assert.deepEqual(sheetMarks(states, ids),
    {'act:pure': true, 'act:plain': false, 'act:eternal': true, 'act:greater': false});
  // The server copy is untouched; only the sheet's view is overlaid.
  assert.equal(serverStates.me['act:plain'].active, true);
  assert.equal(h.app.state.button_states.me['act:greater'].active, true);
});

test('another creature sheet is unaffected by the open draft', () => {
  const draft = new OptionDraft(menu, 'match');
  draft.choose('pureC');
  draft.choose('eternalC');
  const h = harness(draft);
  assert.equal(h.sheetButtonStates('other'), serverStates.other);
  assert.deepEqual(sheetMarks(h.sheetButtonStates('other'), ['act:pure', 'act:plain']),
    {'act:pure': false, 'act:plain': true});
});

test('a draft for an older decision no longer overlays the sheet', () => {
  const draft = new OptionDraft(menu, 'match');
  draft.choose('pureC');
  const h = harness(draft);
  h.app.menu = {...menu, state_version: 5};
  assert.equal(h.sheetButtonStates('me'), serverStates.me);
});

test('invalidating a draft broadcasts saved server states to clear the sheet overlay', () => {
  const draft = new OptionDraft(menu, 'match');
  draft.choose('pureC');
  const h = harness(draft);
  const reconcileStart = source.indexOf('function reconcileOptionDraft(state)');
  const reconcileEnd = source.indexOf('\nfunction render(state', reconcileStart);
  assert.ok(reconcileStart > 0 && reconcileEnd > reconcileStart);
  const reconcileSource = source.slice(reconcileStart, reconcileEnd);
  const reconcile = new Function('app', reconcileSource + '; return reconcileOptionDraft;') (h.app);
  const previous = h.app.optionDraft;
  h.app.menu = {...menu, state_version: 5};
  reconcile(h.app.state);
  assert.equal(h.app.optionDraft, null);
  h.broadcastDraftStates(previous.actorId);
  assert.deepEqual(h.posted[0].button_states, serverStates.me);
  assert.match(source, /reconciledDraft && reconciledDraft !== app\.optionDraft\) broadcastDraftStates\(reconciledDraft\.actorId\)/);
});

test('each pick posts a draft-states message for the draft creature only', () => {
  const draft = new OptionDraft(menu, 'match');
  const h = harness(draft);
  draft.choose('eternalC');
  h.broadcastDraftStates();
  assert.equal(h.posted.length, 1);
  assert.equal(h.posted[0].type, 'draft-states');
  assert.equal(h.posted[0].actor_id, 'me');
  assert.equal(h.posted[0].match_id, 'match');
  assert.equal(h.posted[0].button_states['act:eternal'].active, true);
  assert.equal(h.posted[0].button_states['act:greater'].active, true);
});

test('draftButtonStates projects draft picks into button Active marks', () => {
  const draft = new OptionDraft(menu, 'match');
  draft.choose('pureC');
  const states = draftButtonStates(draft, shapes.me);
  assert.equal(states['act:pure'], true);
  assert.equal(states['act:plain'], false);
  assert.equal(shapes.me[0].choices[1].active, true, 'input rows are not mutated');
});

// Sheet-side handler: sheet.js receives "draft-states" messages posted by
// broadcastDraftStates in tabletop.js and must re-mark only this actor's rows.
// Extract the handler body from sheet.js and verify it scopes by actor_id/match_id.
const sheetSource = readFileSync(new URL('../static/tabletop/sheet.js', import.meta.url), 'utf8');
const dsMarker = sheetSource.indexOf('msg.type === "draft-states"');
assert.ok(dsMarker > 0, 'draft-states handler exists in sheet.js');
const dsOpen = sheetSource.indexOf('{', dsMarker);
const applyCall = sheetSource.indexOf('applyLegal();', dsOpen);
assert.ok(applyCall > 0, 'draft-states handler calls applyLegal');
const dsClose = sheetSource.indexOf('}', applyCall);
const handleDraftStates = new Function('state', 'msg', 'applyLegal', sheetSource.slice(dsOpen + 1, dsClose));

test('the sheet-side draft-states handler updates button_states and re-marks for the matching actor', () => {
  let reMarked = false;
  const applyLegal = () => { reMarked = true; };
  const actor = {actor_id: 'me', match_id: 'match', button_states: {'act:plain': {active: true}}};
  const msg = {type: 'draft-states', actor_id: 'me', match_id: 'match',
    button_states: {'act:pure': {active: true}, 'act:plain': {active: false}}};
  handleDraftStates({actor}, msg, applyLegal);
  assert.equal(actor.button_states, msg.button_states);
  assert.equal(reMarked, true);
});

test('the sheet-side draft-states handler ignores messages for other actors or stale matches', () => {
  let reMarked = false;
  const applyLegal = () => { reMarked = true; };
  const actor = {actor_id: 'me', match_id: 'match', button_states: {'act:plain': {active: true}}};
  handleDraftStates({actor}, {type: 'draft-states', actor_id: 'other', match_id: 'match', button_states: {}}, applyLegal);
  assert.equal(reMarked, false);
  handleDraftStates({actor}, {type: 'draft-states', actor_id: 'me', match_id: 'other-match', button_states: {}}, applyLegal);
  assert.equal(reMarked, false);
  assert.deepEqual(actor.button_states, {'act:plain': {active: true}});
});
