// Exercise production desktop inspection callbacks, observed-state polling and
// ranked controls against native service responses. No browser or network runs.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Element} from './objects_dom_stub.mjs';
import * as assisted from '../static/tabletop/assisted-menu.js';
import {expandMovementGrid} from '../static/tabletop/movement-grid.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';

const {state, source, expansion, quote} = JSON.parse(readFileSync(0, 'utf8'));
const kind = process.argv[2];
assert.ok(['source', 'move'].includes(kind));
const clone = x => structuredClone(x);
const text = n => [n.textContent, ...(n.children || []).map(text)].join(' ');
const desktop = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const callbackStart = desktop.indexOf('  const match = app.matchId;', desktop.indexOf('  // Ranked top-5 slots'));
const callbackEnd = desktop.indexOf('  if (menu.end_turn)', callbackStart);
assert.ok(callbackStart >= 0 && callbackEnd > callbackStart);
const callbacks = desktop.slice(callbackStart, callbackEnd);
const renderStart = desktop.indexOf('function render(state,');
const renderEnd = desktop.indexOf('  invalidateTargeting();', renderStart);
assert.ok(renderStart >= 0 && renderEnd > renderStart);
const observedStart = desktop.indexOf('function renderObservedState(state)');
const observedEnd = desktop.indexOf('\n}\n', observedStart) + 3;
assert.ok(observedStart >= 0 && observedEnd > observedStart);
const appendStart = desktop.indexOf('export function appendActionBarRankedChoice(');
assert.ok(appendStart >= 0);

function compile(env, code) {
  return new Function(...Object.keys(env), code)(...Object.values(env));
}

const changes = {
  unchanged() {},
  reordered(s) {s.menu.movement_grid.reverse(); s.menu.actions.reverse();},
  match(s) {s.presentation.match_id += '-other';},
  decision(s) {s.menu.decision_id += '-other';},
  version(s) {s.menu.state_version++;},
  actor(s) {s.menu.actor_id += '-other';},
  control(s) {s.menu.control_mode = 'MANUAL';},
  turnMode(s) {s.menu.turn_mode = 'Manual';},
  automatic(s) {s.menu.manual = false;},
  pending(s) {s.pending_action = {method: 'act'};},
  terminal(s) {s.presentation.terminal = true;},
  busy(s, app) {app.busy = true;},
  covered(s, app) {app.covered = true;},
  modelSeat(s, app) {app.model = true;},
  missing(s) {
    if (kind === 'source') s.menu.actions = s.menu.actions.filter(g => g.source_definition_id !== source);
    else s.menu.movement_grid.shift();
  },
  mode(s) {if (kind === 'move') s.menu.movement_grid[0][4] += '-other';
    else s.menu.actions = s.menu.actions.filter(g => g.source_definition_id !== source);},
};

for (const [name, change] of Object.entries(changes)) {
  const initial = clone(state);
  const sourceGroup = initial.menu.actions.find(g => g.source_definition_id === source);
  assert.ok(sourceGroup?.lazy);
  // Guarantee that the requested source is visible independently of ranking.
  initial.menu.ranked_slots = {Action: [assisted.sourceRankId(sourceGroup)], Movement: ['movement:compact']};
  const app = {matchId: initial.presentation.match_id, busy: false, playedSequence: 0};
  const doc = {createElement: tag => new Element(tag)};
  let bar, release;
  const calls = [], commits = [];
  const reply = clone(kind === 'source' ? expansion : quote);
  if (kind === 'move') {
    // Disclosure and allowlisting controls; never display arbitrary quote metadata.
    reply.candidate.metadata.hazard_exposure = true;
    reply.candidate.metadata.expected_opportunity_attacks = [{display_name: 'Hidden spy'}];
  }
  const env = {app, document: doc, ...assisted, expandMovementGrid, renderRankedMenu,
    reconcileViewerIdentity: () => false, renderCommitNotice() {}, renderTokens() {},
    // These inspection scenarios have no option draft; main now reconciles it during render.
    reconcileOptionDraft() {}, broadcastDraftStates() {},
    modelOwner: () => app.model, serverDriving: () => false, $: () => null,
    api: async (path, options) => {
      calls.push({path, options});
      return new Promise(resolve => {release = resolve;});
    },
    enc: encodeURIComponent, refuseCoveredView: () => app.covered,
    actOnce: id => commits.push({id}), moveTo: move => commits.push({move}),
    renderActionBar: () => paint()};
  const append = compile(env, `${desktop.slice(appendStart).replace('export ', '')}\nreturn appendActionBarRankedChoice;`);
  function paint() {
    bar = new Element('section');
    if (!app.menu) return;
    const who = new Element('div'), muted = new Element('span');
    muted.className = 'tt-muted'; who.appendChild(muted);
    compile({...env, bar, menu: app.menu, html: new Element('div'), who,
      appendActionBarRankedChoice: append}, callbacks);
  }
  const install = compile(env, `${desktop.slice(renderStart, renderEnd)}\nreturn state;\n}\nreturn render;`);
  const render = s => {install(s); paint();};
  const observe = compile({...env, render}, `${desktop.slice(observedStart, observedEnd)}\nreturn renderObservedState;`);
  render(clone(initial));
  const before = app.menu;
  const oldRow = kind === 'source' ? before.actions.find(g => g.source_definition_id === source) : before.moves[0];
  const button = bar.querySelectorAll('button').find(b => text(b).includes(kind === 'source' ? sourceGroup.label :
    `to (${oldRow.destination.x}, ${oldRow.destination.y})`));
  assert.ok(button, `${kind}: initial inspection control`);
  const checking = button.click();
  assert.equal(calls.length, 1);
  assert.equal(commits.length, 0);
  const next = clone(initial); change(next, app);
  observe(next); // Actual normal poll with the response still unresolved.
  assert.notEqual(app.menu, before, 'Compact raw and expanded local menus must exercise replacement');
  const currentMenu = app.menu;
  const fresh = kind === 'source' ? currentMenu?.actions.find(g => g.source_definition_id === source) :
    currentMenu?.moves.find(m => assisted.moveKey(m) === assisted.moveKey(oldRow));
  const freshId = fresh?.candidate_id, freshCost = fresh?.cost_ft;
  release(reply); await checking;
  assert.equal(commits.length, 0, 'An inspection never commits');
  const valid = ['unchanged', 'reordered'].includes(name);
  if (!valid) {
    assert.ok(!fresh?.expanded_from_lazy && !fresh?.route_checked, `${kind} ${name}: reject late response`);
    continue;
  }
  assert.ok(fresh && fresh !== oldRow);
  // Reordering may put the inspected route outside the first five. It must
  // remain explicitly confirmable through the normal More control.
  for (const more of bar.querySelectorAll('button').filter(b => text(b).startsWith('More…'))) await more.click();
  let confirm;
  if (kind === 'source') {
    assert.equal(fresh.lazy, false, `${name}: response must expand the CURRENT source`);
    const native = expansion.actions.find(g => g.source_definition_id === source);
    assert.deepEqual(fresh.options, native.options, 'Every native option remains reachable');
    for (const option of native.options) assert.ok(bar.querySelectorAll('button').some(b =>
      text(b).includes(sourceGroup.label) && text(b).includes(option.label)), 'More exposes every inspected option');
    confirm = bar.querySelectorAll('button').find(b => text(b).includes(sourceGroup.label) && text(b).includes(native.options[0].label));
    assert.ok(confirm, 'The CURRENT visible action bar must offer the inspected target');
    await confirm.click();
    assert.deepEqual(commits, [{id: native.options[0].candidate_id}]);
  } else {
    assert.ok(fresh.route_checked, `${name}: response must check the CURRENT route`);
    assert.equal(fresh.candidate_id, freshId, 'Retain the fresh local handle after reordering');
    assert.equal(fresh.cost_ft, freshCost, 'Retain the current effective movement cost');
    assert.deepEqual(fresh.path, quote.candidate.canonical_path);
    assert.equal(fresh.route_candidate_id, quote.candidate.candidate_id);
    assert.equal(new Set(currentMenu.moves.map(m => m.candidate_id)).size, currentMenu.moves.length);
    confirm = bar.querySelectorAll('button').find(b => text(b).startsWith(' Confirm') &&
      text(b).includes(`to (${fresh.destination.x}, ${fresh.destination.y})`));
    assert.ok(confirm, 'The CURRENT visible action bar must offer explicit route confirmation');
    assert.match(text(confirm), /Warning: this route crosses a known hazard/);
    assert.ok(!text(bar).includes('Hidden spy'));
    await confirm.click();
    assert.equal(commits.length, 1); assert.equal(commits[0].move, fresh);
  }
  assert.equal(calls.length, 1, 'No second inspection after a poll');
  console.log(`desktop ${kind}: ${name} in-flight poll -> current row -> explicit confirmation PASS`);
}
console.log(`desktop ${kind}: changed boundaries, missing rows, busy/covered/model seats reject late replies PASS`);
