// node --test APP/tests/fog_view.test.mjs
//
// The Fog picker decides whose eyes the table shows you (owner 2026-10-04, live round 25:
// "I want the default vision mode to not share vision with your allies, but keep that as an option as
// allies view"). No browser and no canvas: the real fog_view.js module, the real tabletop.js fog
// functions and the real visibility-polygon and line-of-sight code are driven over a small
// hand-built map, so a regression that goes back to revealing a side's whole sight fails here.
//
// Given FOG_VIEW_FIXTURE=<fixture.json> (written by tests/test_ocf6_own_vision.py) the last case
// runs the same code over a REAL fight's actors and a REAL TabletopService fog_perception answer,
// so the mixed-control fight the service actually builds is checked, not only a hand-written
// stand-in.
//
// How the fixture is delivered, and why (OCF6r1 review finding):
//   * `node --test` treats every positional argument as another TEST FILE and does not forward any
//     of them to the file under test (verified on node 26: `node --test this.mjs fix.json` leaves
//     process.argv at just the script path and runs fix.json as a test file, which "passes" with
//     zero tests). A fixture passed that way never arrives, the real-fight case skips, and the
//     green suite proves nothing -- so the path travels in the environment instead, which the test
//     runner does pass through to the test process.
//   * For a human running the file directly, `node APP/tests/fog_view.test.mjs fixture.json` still
//     works: process.argv[2] is used when the environment is silent.
//   * FOG_VIEW_FIXTURE_REQUIRED=1 makes the fixture non-optional: a missing or unreadable one throws
//     while this module loads, so `node --test` exits non-zero instead of skipping the case. That is
//     what the Python gate sets, and it is why the real-fight coverage cannot be lost again.
// With --test-isolation=none a multi-file invocation may expose another test
// path in argv[2]. The documented direct-script fallback accepts a JSON fixture,
// never an adjacent .mjs test file.
const FIXTURE = process.env.FOG_VIEW_FIXTURE || (/\.json$/i.test(process.argv[2] || '') ? process.argv[2] : null);
if (process.env.FOG_VIEW_FIXTURE_REQUIRED && !FIXTURE) {
  throw new Error('FOG_VIEW_FIXTURE_REQUIRED=1 but FOG_VIEW_FIXTURE is not set: the real-fight '
    + 'case must run (node --test does not forward positional arguments to this file)');
}
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DEFAULT_FOG_VIEW, FOG_VIEWS, NO_FOG_VIEW, fogOn, fogView, fogViewers}
  from '../static/tabletop/fog_view.js';
import {blockerSegments, fogPointVisible, visibilityPolygons} from '../static/tabletop/fog_polygon.js';
import {wallSightCells} from '../static/tabletop/zones.js';
import {lineOfSight, opacityGrid, perceivedCells, tokenHiddenByFog} from '../static/tabletop/vision.js';
import {createTableHarness, tableState, memoryStorage, functionSource} from './viewer_identity_harness.mjs';
import {createViewerStore, resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';

// The production ownership function resolves only the explicitly named fighters.
const ownsAFighter = (roster, ids = [ME]) => {
  const view = resolveViewerIdentity({version:1,role:'player',actor_ids:ids},roster,{seats:{}});
  return new Function('presentation','isOwnedActor',functionSource('playsAFighterHere')+';return playsAFighterHere();')(
    ()=>({actors:roster}),actor=>view.isOwned(actor));
};

// A 12x5 yard. Your fighter stands at (1, 1); your ally stands at (10, 3); a foe waits at
// (10, 1), across the wall from you and in the open for your ally. A filled wall runs down
// x=6, so the far side of the yard is only ever revealed through somebody else's eyes.
const WIDTH = 12, HEIGHT = 5;
const ME = 'actor:mine', ALLY = 'actor:ally', FOE = 'actor:foe';
const ACTORS = [
  {entity_id: ME, display_name: 'Mine', controller: 'MANUAL', team_index: 0, active: true, position: {x: 1, y: 1}, footprint: {width_cells: 1, height_cells: 1}},
  {entity_id: ALLY, display_name: 'Ally', controller: 'LOCAL_AUTO', team_index: 0, active: true, position: {x: 10, y: 3}, footprint: {width_cells: 1, height_cells: 1}},
  {entity_id: FOE, display_name: 'Foe', controller: 'API_AUTO', team_index: 1, active: true, position: {x: 10, y: 1}, footprint: {width_cells: 1, height_cells: 1}},
];
// The same yard with the foe played by a person instead of the AI: the Game Master took that fighter
// over by hand. Explicit local identity now distinguishes it from yours.
const GM_FOE = ACTORS.map(actor => (actor.entity_id === FOE ? {...actor, controller: 'MANUAL'} : actor));
// Two of your own fighters, one of them a summon: a summon keeps its summoner's side and the same
// hand-driven control mode, which is what the service does (combat/summons.py).
const TWO_OWNED = [...GM_FOE, {entity_id: 'actor:mine-2', display_name: 'Summoned', controller: 'MANUAL',
  team_index: 0, owner_id: ME, primary_combatant:false, active: true, position: {x: 2, y: 3}, footprint: {width_cells: 1, height_cells: 1}}];
const WALL = [{shape: 'rect', points: [[6, 0], [6, 4]], filled: true}];

// The service's answer for a roster: what each creature actually perceives. Built from the engine's
// own line of sight (vision.js opacityGrid / lineOfSight), so the fixture cannot claim a square the
// engine would refuse.
const OPAQUE = opacityGrid(WIDTH, HEIGHT, [[[6, 0], [6, 1], [6, 2], [6, 3], [6, 4]]]);

function perceptionFor(viewer, roster) {
  const {x: vx, y: vy} = viewer.position;
  const cells = [];
  for (let y = 0; y < HEIGHT; y += 1) for (let x = 0; x < WIDTH; x += 1) {
    if (lineOfSight(WIDTH, OPAQUE, vx, vy, x, y)) cells.push([x, y]);
  }
  const creatures = [viewer.entity_id];
  for (const actor of roster) {
    if (actor.entity_id !== viewer.entity_id && actor.team_index === viewer.team_index) {
      creatures.push(actor.entity_id);   // teammates stay known, as the engine's target knowledge keeps them
    } else if (cells.some(([x, y]) => x === actor.position.x && y === actor.position.y)) {
      creatures.push(actor.entity_id);
    }
  }
  return {cells, creatures};
}

const buildPerception = roster => Object.fromEntries(roster.map(actor => [actor.entity_id, perceptionFor(actor, roster)]));
const PERCEPTION = buildPerception(ACTORS);
function table(view, {selected = new Set(), roster = ACTORS, perception = PERCEPTION,
    width = WIDTH, height = HEIGHT, boundIds = [ME]} = {}) {
  const rows=roster.map(row=>({conditions:[],hit_points:{current:10,maximum:10},...row}));
  const map={width,height,walls:WALL,trees:[],objects:[],floors:[],background:{style:'plain'}};
  const state=tableState(rows,{perception,map});
  const context=createTableHarness({state,boundIds:view === 'off' ? null : boundIds,
    gm:view === 'off',fog:view === 'off'?null:view});
  context.app.selected=selected;
  // Geometry checks use the real polygon path, not the optional square debug mode.
  context.location.search='?match=match&view=view-one';
  context.ownedOf = records => {
    const resolved=resolveViewerIdentity(context.viewerStore.read('match'),records,{seats:{}});
    return records.filter(row=>resolved.isOwned(row));
  };
  return context;
}

// A square you can see from your own fighter, and one only your ally can see (the foe's square).
const MY_SQUARE = [2, 1], ALLY_ONLY_SQUARE = [10, 1];
const lit = (seen, [x, y]) => seen[y * WIDTH + x];

test('the default view is your own fighter, not your side', () => {
  assert.equal(DEFAULT_FOG_VIEW, 'own');
  assert.equal(FOG_VIEWS[0].value, DEFAULT_FOG_VIEW);
  assert.deepEqual(FOG_VIEWS.map(view => view.value), ['own', 'team', 'selected', 'off']);
});

test("your own fighter's view hides what only an ally can see", () => {
  const ctx = table('own');
  const seen = ctx.visibility();
  assert.ok(seen, 'fog is on for a fight you play');
  assert.equal(lit(seen, MY_SQUARE), 1);
  assert.equal(lit(seen, ALLY_ONLY_SQUARE), 0, "your ally's corner of the yard stays dark");
  assert.deepEqual([...ctx.viewerIds()], [ME], 'only the creature the player controls perceives');
  // The drawn mask agrees with the service's squares: the ally's corner stays dark.
  const geometry = ctx.fogGeometry(seen);
  assert.equal(fogPointVisible(10.5, 1.5, WIDTH, HEIGHT, seen, geometry.polygons), false);
  assert.equal(fogPointVisible(2.5, 1.5, WIDTH, HEIGHT, seen, geometry.polygons), true);
});

test('a foe the Game Master drives by hand is not one of your viewers', () => {
  // Mixed control: your fighter on your side, an AI ally beside it, and a foe the Game Master plays
  // by hand on the other side. This view still explicitly binds only ME.
  const ctx = table('own', {roster: GM_FOE, perception: buildPerception(GM_FOE)});
  assert.deepEqual([...ctx.viewerIds()], [ME],
    'a foe marked MANUAL on the other side is still the enemy, and its territory stays hidden');
  const seen = ctx.visibility();
  assert.equal(lit(seen, MY_SQUARE), 1, 'your own fighter still shows you its own corner of the map');
  assert.equal(lit(seen, ALLY_ONLY_SQUARE), 0, "the Game Master's foe's corner stays dark");
  assert.equal(ctx.unseenByViewers(GM_FOE[2]), true, 'and its token is off your map');
  assert.equal(ctx.unseenByViewers(GM_FOE[1]), false, 'your own ally is still a known teammate');
  // Ownership is an explicit binding, independent of team/controller coincidence.
  assert.equal(ctx.isOwnedActor(GM_FOE[2]), false, 'an unbound fighter is never yours');
  assert.equal(ctx.isOwnedActor(GM_FOE[0]), true);
  // Every fighter you drive on your side is yours, a summon included, and none of the others.
  const several = table('own', {roster: TWO_OWNED, perception: buildPerception(TWO_OWNED)});
  assert.deepEqual([...several.viewerIds()].sort(), ['actor:mine', 'actor:mine-2'].sort(),
    'two fighters you drive (one summoned) are both your own view');
  assert.equal(several.unseenByViewers(TWO_OWNED[2]), true, 'the hand-driven foe is still excluded');
  // "Allies' view" is the deliberate way to share a side, and who plays the fight does not change it.
  const allies = table('team', {roster: GM_FOE, perception: buildPerception(GM_FOE)});
  assert.deepEqual([...allies.viewerIds()].sort(), [ME, ALLY].sort());
  assert.equal(lit(allies.visibility(), ALLY_ONLY_SQUARE), 1);
  // The fight-opens-on-a-default check reads the same ownership rule, so a Game Master running the
  // enemy's fighters by hand is not treated as a player who has to see the fog of war.
  assert.equal(ownsAFighter(GM_FOE), true, 'you own a fighter on your side');
  assert.equal(ownsAFighter(GM_FOE.filter(row => row.team_index !== 0)), false,
    "driving only the enemy's fighters is not playing your own character");
  assert.equal(ownsAFighter(ACTORS), true);
  assert.equal(ownsAFighter(ACTORS.map(row => ({...row, controller: 'API_AUTO'}))), false,
    'an all-AI fight you only watch');
});

test("the allies' view shows what the ally can see, and the Game Master's view shows everything", () => {
  const allies = table('team');
  const seen = allies.visibility();
  assert.equal(lit(seen, ALLY_ONLY_SQUARE), 1, 'the allies view keeps the old shared sight');
  assert.deepEqual([...allies.viewerIds()].sort(), [ME, ALLY].sort());
  const geometry = allies.fogGeometry(seen);
  assert.equal(fogPointVisible(10.5, 1.5, WIDTH, HEIGHT, seen, geometry.polygons), true);

  const gm = table('off');
  assert.equal(gm.visibility(), null, 'no fog at all is drawn or asked of the service');
  assert.equal(gm.viewerIds(), null, 'nothing is hidden from the Game Master');
  assert.equal(gm.unseenByViewers(ACTORS[2]), false, 'a foe out of sight is still on the map for the GM');
  assert.equal(fogOn('off'), false);
});

test('a foe only your ally can see is off your map, and your own ally token stays known', () => {
  const ctx = table('own');
  assert.equal(ctx.unseenByViewers(ACTORS[2]), true, 'your own view decides the foe');
  const allies = table('team');
  assert.equal(allies.unseenByViewers(ACTORS[2]), false);
  // A teammate is in every viewer's creature list, so the ally's token is never lost.
  assert.equal(ctx.unseenByViewers(ACTORS[1]), false);
});

test('the chosen tokens view follows the tokens you picked', () => {
  const mine = table('selected', {selected: new Set([ME])});
  const seen = mine.visibility();
  assert.equal(lit(seen, MY_SQUARE), 1);
  assert.equal(lit(seen, ALLY_ONLY_SQUARE), 0);
  assert.deepEqual([...mine.viewerIds()], [ME]);
  const foe = table('selected', {selected: new Set([FOE])});
  const foeSeen = foe.visibility();
  assert.equal(lit(foeSeen, MY_SQUARE), 0, "the picked foe sees nothing of your square");
  assert.equal(lit(foeSeen, ALLY_ONLY_SQUARE), 1, 'the picked token sees its own square');
  const empty = table('selected');
  assert.ok(empty.visibility().every(value=>value === 0), 'nothing picked keeps every square covered');
});

test("while your fighter is down you look through your allies' eyes, not through the enemy's", () => {
  const ctx = table('own');
  const downed = ACTORS.map(actor => (actor.entity_id === ME ? {...actor, active: false} : actor));
  const rows = fogViewers('own', downed, {owned: ctx.ownedOf(downed), team: 0});
  assert.deepEqual(rows.map(row => row.entity_id), [ALLY],
    'a downed fighter cannot see, and the map must not simply open up');
  assert.deepEqual(fogViewers('own', GM_FOE, {owned: ctx.ownedOf(GM_FOE), team: 0}).map(row => row.entity_id), [ME],
    "the Game Master's hand-driven foe is never one of your viewers, standing or not");
  assert.deepEqual(fogViewers('own', [], {owned: [], team: 0}), [], 'a fight you only watch has no fog view');
  const theirs = ACTORS.map(actor => ({...actor, controller: 'API_AUTO'}));
  assert.deepEqual(fogViewers('own', theirs, {owned: ctx.ownedOf(theirs), team: 0}), [],
    'nothing eligible of yours supplies no viewers; production keeps the map covered');
  assert.deepEqual(fogViewers('own', ACTORS, {owned: ctx.ownedOf(ACTORS), team: 0}).map(row => row.entity_id), [ME]);
  assert.match(FOG_VIEWS[0].help, /down[\s\S]*allies' eyes/i, 'the player is told about the fallback');
  // The fallback side is read off your own fighters, so it follows ownership rather than assuming
  // the first side -- and it is never the enemy's, whichever side the player is on.
  const elsewhere = [
    {...ACTORS[1], team_index: 2, active: false},                                    // your fighter, down, third side
    {...ACTORS[1], entity_id: 'actor:ally-3', team_index: 2, active: true},          // its ally, third side
    {...ACTORS[2], team_index: 0, controller: 'MANUAL'},                              // the enemy, first side
  ];
  assert.deepEqual(fogViewers('own', elsewhere, {owned: [elsewhere[0]], team: 0}).map(row => row.entity_id),
    ['actor:ally-3'], 'the side comes from your own fighter, never from the first side in the fight');
});

test('every fog choice explains its view in plain, player-directed words', () => {
  const html = readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  for (const view of FOG_VIEWS) {
    assert.ok(view.help.length > 40, `${view.value}: help must explain what the view does`);
    assert.doesNotMatch(view.label + view.help, /\b(team_index|entity_id|viewer|fog_perception|perception|LOCAL_AUTO|MANUAL)\b/,
      `${view.value}: labels and help speak to players without internal identifiers or jargon`);
    assert.match(view.help, /\byou\b/i, `${view.value}: help addresses the player`);
    // Inspect the actual shipped picker text as well as the module's wording.
    const option = html.match(new RegExp(`<option value="${view.value}"[^>]*>([^<]*)</option>`));
    assert.ok(option, `${view.value}: the shipped picker includes this view`);
    assert.doesNotMatch(option[0], /\b(team_index|entity_id|viewer|fog_perception|perception|LOCAL_AUTO|MANUAL)\b/,
      `${view.value}: the shipped option also avoids internal identifiers and jargon`);
    assert.match(option[0], /\byou\b/i, `${view.value}: the shipped help addresses the player`);
  }
  for (const [view, explanation, message] of [
    [FOG_VIEWS[0], /only an ally can see stays hidden/i, 'own sight explains what remains hidden'],
    [FOG_VIEWS[0], /dimly visible as memory/i, 'explored squares remain visible as memory'],
    [FOG_VIEWS[0], /fighters chosen in My fighters[\s\S]*summoned creatures[\s\S]*manually/i,
      'own sight explains the explicit fighter binding, summons and manual eligibility'],
    [FOG_VIEWS[1], /allies\x27 sight combined/i, 'shared sight explains the combined view'],
    [FOG_VIEWS[3], /Game Master/, 'full-map sight explains its Game Master purpose'],
  ]) {
    assert.match(view.help, explanation, message);
    const option = html.match(new RegExp(`<option value="${view.value}"[^>]*>([^<]*)</option>`));
    assert.match(option[0], explanation, `shipped picker: ${message}`);
  }
});

test('fog labels and help stay in the newcomer picker, and the preference belongs to one view and match', () => {
  const html = readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  for (const view of FOG_VIEWS) {
    assert.ok(html.includes(`<option value="${view.value}"`), view.value);
    assert.ok(html.includes(`>${view.label}</option>`), view.label);
    assert.ok(html.includes(view.help), `${view.value} has its hover explanation`);
    assert.equal(fogView(view.value), view);
  }
  const storage=memoryStorage([['tt-fog','off']]);
  const one=createViewerStore({viewId:'one',storage}),two=createViewerStore({viewId:'two',storage});
  one.bindPlayer('match',[ME]); two.bindPlayer('match',[ALLY]); one.writeFog('match','team');
  assert.equal(one.readFog('match'),'team'); assert.equal(two.readFog('match'),'own');
  assert.equal(one.readFog('new-match'),'own');
  assert.equal(createViewerStore({viewId:'one',storage}).readFog('match'),'team');
  assert.equal(fogView('view-from-another-version'),null);
  assert.equal(fogOn('view-from-another-version'),true);
  assert.deepEqual(fogViewers('view-from-another-version',ACTORS,{owned:[ACTORS[0]]}),[]);
});

test('a fresh or all-AI player view stays covered until an explicit Game Master choice', () => {
  const unbound=table('own',{boundIds:null});
  assert.ok(unbound.visibility().every(value=>value === 0));
  assert.equal(unbound.isGMView(),false);
  const ai=table('own',{roster:ACTORS.map(row=>({...row,controller:'API_AUTO'}))});
  assert.ok(ai.visibility().every(value=>value === 0));
  ai.selectGMView(); assert.equal(ai.visibility(),null);
});

test('a real mixed-control fight shows only your own fighter',
  {skip: FIXTURE ? false : 'no FOG_VIEW_FIXTURE / fixture.json supplied'}, () => {
    const fixture = JSON.parse(readFileSync(FIXTURE, 'utf8'));
    const roster = fixture.actors;
    const mine = roster.find(row => row.controller === 'MANUAL' && row.team_index === 0);
    const ally = roster.find(row => row.team_index === 0 && row.controller !== 'MANUAL');
    const foe = roster.find(row => row.team_index === 1);
    assert.ok(mine && ally && foe, 'the fixture is the mixed-control fight it claims to be');
    assert.equal(foe.controller, 'MANUAL', 'the foe is the one the Game Master drives by hand');
    // The real map's size, read under the names TabletopService sends them. If these were missing or
    // renamed the mask would be built at the harness default and every square read below would be
    // out of range, which is how the first version of this case passed without covering anything.
    const {width_squares: width, height_squares: height} = fixture.battlefield;
    assert.ok(Number.isInteger(width) && width > 0 && Number.isInteger(height) && height > 0,
      `the fixture carries the service's battlefield size, not the harness default (got ${width}x${height})`);
    assert.equal(width, 16, 'the walled yard this fight is built on is 16 squares wide');
    assert.equal(height, 8, '... and 8 tall');
    assert.equal(fixture.fog_perception[mine.entity_id].creatures.includes(foe.entity_id), false,
      'the service says your fighter cannot perceive the foe across the wall');

    const ctx = table('own', {roster, perception: fixture.fog_perception, width, height, boundIds:[mine.entity_id]});
    assert.deepEqual([...ctx.viewerIds()], [mine.entity_id],
      'the enemy the Game Master drives is not one of your viewers');
    const seen = ctx.visibility();
    assert.equal(seen.length, width * height,
      'the mask is the real map, so the square reads below are inside it');
    const litReal = ([x, y]) => {
      const index = y * width + x;
      assert.ok(Number.isInteger(index) && index >= 0 && index < seen.length,
        `[${x}, ${y}] is a square of this fight's map`);
      return seen[index];
    };
    assert.equal(litReal([mine.position.x, mine.position.y]), 1, "you see your own fighter's square");
    assert.equal(litReal([foe.position.x, foe.position.y]), 0, "the foe's square stays hidden in your own view");
    assert.equal(ctx.unseenByViewers(foe), true, 'the foe token is off your map');
    assert.equal(ctx.unseenByViewers(ally), false, 'your own ally stays a known teammate');
    assert.equal(ctx.unseenByViewers(mine), false, 'your own fighter is never hidden from you');
    assert.equal(ownsAFighter(roster,[mine.entity_id]), true, 'and the real fight opens on the fog of war for you');

    const allies = table('team', {roster, perception: fixture.fog_perception, width, height, boundIds:[mine.entity_id]});
    const shared = [...allies.viewerIds()];
    assert.ok(shared.includes(mine.entity_id), "the allies' view still looks through your fighter");
    assert.ok(!shared.includes(foe.entity_id), 'and never through the enemy');
    assert.equal(allies.unseenByViewers(foe), false,
      'the ally can see the foe, so the shared view keeps the behaviour it always had');
  });
