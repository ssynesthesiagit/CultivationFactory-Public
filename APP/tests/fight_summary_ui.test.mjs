// End-of-fight summary layout (owner 2026-10-06): renders the recorded numbers, never computes them.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {fightSummaryHtml, idLabel, summaryAutoOpen} from '../static/tabletop/fight-summary.js';
import {resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';
import {bindPress} from '../static/tabletop/kept-bar.js?v=speedreuse2-3';

const metrics = (over = {}) => ({damage_dealt: {total: 0, by_type: {}}, damage_taken: {rolled: 0, applied: 0, hp_damage: 0, temporary_hp_absorbed: 0},
  healing_done: 0, healing_received: 0, temporary_hp_granted: 0, attacks: {made: 0, hits: 0, misses: 0, critical_hits: 0, concealment_misses: 0},
  saves_forced: {total: 0, failed: 0}, saves_made: {passed: 0, failed: 0}, creatures_downed: [], times_downed: 0, resources_spent: {},
  reactions_used: 0, turns_taken: 0, conditions_applied_to_enemies: {}, ...over});
const row = (id, team, extra = {}) => ({entity_id: id, display_name: `Name <${id}>`, team, summoner: null, final_hp: 10, maximum_hp: 20,
  life_state: 'CONSCIOUS', active: true, metrics: metrics(), ...extra});

const summary = {
  actors: [
    row('a', 't1', {metrics: metrics({damage_dealt: {total: 50, by_type: {FIRE: 30, NECROTIC: 20}},
      damage_taken: {rolled: 40, applied: 25, hp_damage: 25, temporary_hp_absorbed: 0},
      attacks: {made: 4, hits: 3, misses: 1, critical_hits: 1, concealment_misses: 1}, resources_spent: {'resource:core.stamina': 6},
      creatures_downed: ['c'], turns_taken: 5})}),
    row('s', 't1', {summoner: 'a', display_name: 'Spirit'}),
    row('b', 't1', {metrics: metrics({damage_dealt: {total: 70, by_type: {}}})}),
    row('c', 't2', {final_hp: 0, life_state: 'DEAD', active: false, metrics: metrics({healing_done: 12, temporary_hp_granted: 5})}),
  ],
  teams: [{team: 't1', metrics: metrics({damage_dealt: {total: 120, by_type: {}}})}, {team: 't2', metrics: metrics()}],
  highlights: {most_damage_dealt: {value: 70, entity_ids: ['b']}, most_healing: {value: 12, entity_ids: ['c']}, most_damage_taken: {value: 0, entity_ids: []}},
};
const ctx = {nameOf: id => ({b: 'Bao', c: 'Chen'}[id] || id), teamName: id => ({t1: 'Allies', t2: 'Foes'}[id]), initials: n => n.slice(0, 2), winner: 't1'};

test('labels ids readably', () => {
  assert.equal(idLabel('resource:core.stamina'), 'Stamina');
  assert.equal(idLabel('condition:typed.hungry_darkness'), 'Hungry Darkness');
  assert.equal(idLabel('x', {x: 'Printed'}), 'Printed');
});

test('shows recorded numbers per fighter, team totals, winner and highlights', () => {
  const html = fightSummaryHtml(summary, ctx);
  assert.match(html, /<h3>Allies <span class="tt-sum-tag">winner<\/span><\/h3>/);
  assert.match(html, /<h3>Foes<\/h3>/);
  assert.match(html, />50<\/td>/);
  assert.match(html, /title="30 fire, 20 necrotic"/);
  assert.match(html, /25<span class="tt-sub"> −15 soaked<\/span>/);
  assert.match(html, /3 \/ 4 \(75%\)<span class="tt-sub"> · 1 crit<\/span><span class="tt-sub"> · 1 lost to concealment<\/span>/);
  assert.match(html, /6 Stamina/);
  assert.match(html, />120<\/td>/);
  assert.match(html, /HP 0 \/ 20 · Dead/);
  assert.match(html, /12<span class="tt-sub"> \+5 temp<\/span>/);
  assert.match(html, /Most damage dealt<\/span><strong>Name &lt;b&gt;<\/strong>/);
  assert.match(html, /Most healing<\/span><strong>Name &lt;c&gt;<\/strong>/);
  assert.doesNotMatch(html, /Most damage taken/);   // nobody: zero-valued highlights are left out
});

test('summons follow their summoner and names are escaped', () => {
  const html = fightSummaryHtml(summary, ctx);
  const allies = html.slice(html.indexOf('<h3>Allies'), html.indexOf('<h3>Foes'));
  const tbody = allies.slice(allies.indexOf('<tbody>'), allies.indexOf('</tbody>'));
  const order = ['Name &lt;b&gt;', 'Name &lt;a&gt;', 'Spirit'].map(name => tbody.indexOf(name));
  assert.ok(order.every(i => i >= 0) && order[0] < order[1] && order[1] < order[2]);
  assert.match(html, /<tr class="is-summon">/);
  assert.doesNotMatch(html, /<a>/);
});

test('a fight without a recorded summary says so', () => {
  assert.match(fightSummaryHtml(null), /No summary was recorded/);
});

test('incomplete older logs are flagged next to the numbers', () => {
  const html = fightSummaryHtml({...summary, limitations: ['Some healing events lack before/after HP & <more>.']}, ctx);
  assert.match(html, /Some numbers are incomplete for this fight/);
  assert.match(html, /<li>Some healing events lack before\/after HP &amp; &lt;more&gt;\.<\/li>/);
  assert.doesNotMatch(fightSummaryHtml(summary, ctx), /incomplete/);
});

test('a departed summon leading a highlight keeps its recorded name, never an id', () => {
  const gone = {...summary, highlights: {most_damage_dealt: {value: 9, entity_ids: ['s']}}};
  const html = fightSummaryHtml(gone, {...ctx, nameOf: () => undefined});
  assert.match(html, /Most damage dealt<\/span><strong>Spirit<\/strong>/);
  assert.doesNotMatch(html, /<strong>s<\/strong>/);
});

test('the summary opens by itself once per finished fight', () => {
  const app = {state: {summary: {actors: []}}};
  assert.equal(summaryAutoOpen(app, 'm1'), true);
  assert.equal(summaryAutoOpen(app, 'm1'), false);   // re-renders and the button do not reopen it by themselves
  assert.equal(summaryAutoOpen(app, 'm2'), true);    // another finished fight does
  assert.equal(summaryAutoOpen({state: {}}, 'm3'), false);   // no recorded summary: nothing to open
});

// The real table code: the finished-fight action bar and openFightSummary(), with DOM stubs (no browser).
function table(state) {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const from = source.indexOf('function openFightSummary()');
  const to = source.indexOf('\n}', source.indexOf('async function renderActionBar(')) + 2;
  const el = () => ({listeners: {}, textContent: '', addEventListener(type, fn) { this.listeners[type] = fn; }});
  const bar = {html: '', parts: {}, set innerHTML(value) { this.html = value; this.parts = {}; }, get innerHTML() { return this.html; },
    querySelector(selector) { return (this.parts[selector] ||= el()); }};
  const dialog = {open: false, showModal() { this.open = true; }, close() { this.open = false; }};
  const body = {innerHTML: ''};
  const app = {state};
  const $ = selector => ({'#ttActionBar': bar, '#ttSummary': dialog, '#ttSummaryBody': body}[selector]);
  const presentation = () => app.state.presentation;
  const actors = () => app.state.presentation.actors.filter(actor => actor.summon_status !== 'gone');
  // Summary wording/open-once behavior is exercised with an explicit GM view.
  const currentViewer = () => resolveViewerIdentity({version:1,role:'gm',actor_ids:[]},[],{seats:{}});
  const fns = new Function('$', 'app', 'presentation', 'actorById', 'tokenImage', 'initials', 'TEAM_COLORS', 'openLobby', 'fightSummaryHtml', 'summaryAutoOpen', 'currentViewer', 'bindPress', 'createProviderList',
    source.slice(from, to) + '\nreturn {openFightSummary, renderActionBar};')(
    $, app, presentation, id => actors().find(actor => actor.entity_id === id), actor => actor.portrait || null, n => n.slice(0, 2), ['red', 'blue'],
    () => {}, fightSummaryHtml, summaryAutoOpen, currentViewer, bindPress,
    // The extracted span also declares the setup model list (provider-list.js, SEATLIST1); it is
    // inert here because the summary tests never open the fight builder.
    () => ({state: {unavailable: false}, load: async () => ({})}));
  return {...fns, app, bar, dialog, body};
}

const finished = (matchId) => ({
  presentation: {match_id: matchId, terminal: true, terminal_result: {}, teams: [{team_id: 't1', display_name: 'Allies'}],
    actors: [{entity_id: 'a', display_name: 'Ana'}, {entity_id: 's', display_name: 'Spirit', summon_status: 'gone', portrait: '/p/spirit.png'}]},
  summary: {actors: [row('a', 't1'), row('s', 't1', {summoner: 'a', display_name: 'Spirit'})], teams: [],
    highlights: {most_damage_dealt: {value: 9, entity_ids: ['s']}}},
});

test('the finished-fight bar opens the summary once, the button reopens it, a new fight opens it again', async () => {
  const t = table(finished('m1'));
  await t.renderActionBar();
  assert.equal(t.dialog.open, true);
  assert.match(t.bar.innerHTML, /data-summary>Fight summary</);
  t.dialog.close();
  await t.renderActionBar();
  assert.equal(t.dialog.open, false);          // a re-render does not pop it up again
  t.bar.parts['[data-summary]'].listeners.click();
  assert.equal(t.dialog.open, true);           // the button does
  t.dialog.close();
  t.app.state = finished('m2');
  await t.renderActionBar();
  assert.equal(t.dialog.open, true);           // another finished fight opens it by itself
});

test('a summon that has left the map keeps its recorded name and its portrait in the card', async () => {
  const t = table(finished('m1'));
  await t.renderActionBar();
  assert.match(t.body.innerHTML, /Most damage dealt<\/span><strong>Spirit<\/strong>/);
  assert.match(t.body.innerHTML, /<img src="\/p\/spirit.png"/);
});
