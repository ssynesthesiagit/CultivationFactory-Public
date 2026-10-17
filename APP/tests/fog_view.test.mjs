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
const FIXTURE = process.env.FOG_VIEW_FIXTURE || process.argv[2] || null;
if (process.env.FOG_VIEW_FIXTURE_REQUIRED && !FIXTURE) {
  throw new Error('FOG_VIEW_FIXTURE_REQUIRED=1 but FOG_VIEW_FIXTURE is not set: the real-fight '
    + 'case must run (node --test does not forward positional arguments to this file)');
}
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {DEFAULT_FOG_VIEW, FOG_VIEWS, NO_FOG_VIEW, fogOn, fogView, fogViewers}
  from '../static/tabletop/fog_view.js';
import {blockerSegments, fogPointVisible, visibilityPolygons} from '../static/tabletop/fog_polygon.js';
import {wallSightCells} from '../static/tabletop/zones.js';
import {lineOfSight, opacityGrid, perceivedCells, tokenHiddenByFog} from '../static/tabletop/vision.js';
import {modelOwner} from '../static/tabletop/seats.js';

const SOURCE = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');

// The table's fog functions, lifted out of the real source so the wiring under test is the
// shipped one (the same technique tests/newcomer_text.test.mjs uses for renderTokens).
function sourceOf(name) {
  const start = SOURCE.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `find ${name} in tabletop.js`);
  return SOURCE.slice(start, SOURCE.indexOf('\n}', start) + 2);
}

// A top-level `const NAME = ...` line out of the real source, restated as `var` so the vm context
// carries it: the shipped ownership rule itself (isManualActor, PLAYER_SIDE, isOwnedActor) is what
// these cases run, not a copy of it written here.
function constOf(name) {
  const line = SOURCE.split('\n').find(row => row.startsWith(`const ${name} = `));
  assert.ok(line, `find const ${name} in tabletop.js`);
  return line.replace('const ', 'var ');
}

// What the shipped page would decide is owned, straight from its own ownership rule.
const ownsAFighter = roster => {
  const context = vm.createContext({app: {seatStatus: null}, modelOwner, presentation: () => ({actors: roster}),
    teamIndex: actor => Number(actor?.team_index ?? 0)});
  vm.runInContext([OWNERSHIP, sourceOf('playsAFighterHere')].join('\n'), context);
  return context.playsAFighterHere();
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
// over by hand, so its controller mark is identical to yours and only the side tells them apart.
const GM_FOE = ACTORS.map(actor => (actor.entity_id === FOE ? {...actor, controller: 'MANUAL'} : actor));
// Two of your own fighters, one of them a summon: a summon keeps its summoner's side and the same
// hand-driven control mode, which is what the service does (combat/summons.py).
const TWO_OWNED = [...GM_FOE, {entity_id: 'actor:mine-2', display_name: 'Summoned', controller: 'MANUAL',
  team_index: 0, active: true, position: {x: 2, y: 3}, footprint: {width_cells: 1, height_cells: 1}}];
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
const OWNERSHIP = [constOf('isManualActor'), constOf('PLAYER_SIDE'), constOf('isOwnedActor')].join('\n');

function table(view, {selected = new Set(), roster = ACTORS, perception = PERCEPTION, width = WIDTH, height = HEIGHT} = {}) {
  const app = {fog: view, selected, explored: new Uint8Array(width * height), state: {
    presentation: {actors: roster, zones: [], battlefield: {blocked_cells: []}},
    fog_perception: perception, objects: [],
  }};
  const context = vm.createContext({
    app, modelOwner, perceivedCells, tokenHiddenByFog, blockerSegments, visibilityPolygons, fogViewers, fogOn, wallSightCells,
    board: {map: {width, height, walls: WALL, trees: [], cells: {blocked: [], sight: []}}},
    actors: () => roster.filter(actor => actor.active !== false),
    presentation: () => app.state.presentation,
    teamIndex: actor => Number(actor?.team_index ?? 0),
    wallCells: () => new Set(), treeCells: () => [],
    squareFogDebug: () => false,
  });
  vm.runInContext([OWNERSHIP, sourceOf('fogAudience'), sourceOf('visibility'), sourceOf('fogGeometry'),
    sourceOf('viewerIds'), sourceOf('unseenByViewers')].join('\n'), context);
  // What the shipped page would decide is owned, straight from its own ownership rule.
  context.ownedOf = rows => rows.filter(row => context.isOwnedActor(row));
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
  // by hand on the other side. Only the control mark and the side differ from the case above.
  const ctx = table('own', {roster: GM_FOE, perception: buildPerception(GM_FOE)});
  assert.deepEqual([...ctx.viewerIds()], [ME],
    'a foe marked MANUAL on the other side is still the enemy, and its territory stays hidden');
  const seen = ctx.visibility();
  assert.equal(lit(seen, MY_SQUARE), 1, 'your own fighter still shows you its own corner of the map');
  assert.equal(lit(seen, ALLY_ONLY_SQUARE), 0, "the Game Master's foe's corner stays dark");
  assert.equal(ctx.unseenByViewers(GM_FOE[2]), true, 'and its token is off your map');
  assert.equal(ctx.unseenByViewers(GM_FOE[1]), false, 'your own ally is still a known teammate');
  // Ownership is a side rule, not "however many fighters are marked MANUAL".
  assert.equal(ctx.isOwnedActor(GM_FOE[2]), false, 'the enemy side is never yours');
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
  assert.equal(empty.visibility(), null, 'nothing picked means no fog, as before');
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
    'nothing of yours in the fight means the whole map, exactly as the Game Master view does');
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

test('the choice is remembered per device and an unknown choice is not a choice', () => {
  const html = readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  for (const view of FOG_VIEWS) {
    assert.ok(html.includes(`<option value="${view.value}"`), view.value);
    assert.ok(html.includes(`>${view.label}</option>`), view.label);
    assert.ok(html.includes(view.help), `${view.value} keeps its own hover explanation in the picker`);
    assert.equal(fogView(view.value), view);
  }
  // The picker shows the chosen view's help on hover, from the same table.
  const store = new Map();
  const localStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value)};
  const app = {fog: NO_FOG_VIEW};
  const picker = {};
  const context = vm.createContext({app, localStorage, fogView, $: () => picker});
  vm.runInContext([sourceOf('rememberFogView'), sourceOf('setFogPicker')].join('\n'), context);
  assert.equal(context.rememberFogView(), null, 'a new device has no choice yet');
  store.set('tt-fog', 'team');
  assert.equal(context.rememberFogView().value, 'team');
  app.fog = context.rememberFogView().value;
  context.setFogPicker();
  assert.equal(picker.value, 'team');
  assert.equal(picker.title, FOG_VIEWS.find(view => view.value === 'team').help);
  store.set('tt-fog', 'view-from-another-version');
  assert.equal(context.rememberFogView(), null, 'an unknown stored choice is not a choice');
  assert.equal(fogOn('view-from-another-version'), true);
  assert.deepEqual(fogViewers('view-from-another-version', ACTORS, {owned: [ACTORS[0]]}), []);
});

test('a fight opens on the default view unless this device already chose one', async () => {
  // start()'s initialization line and loadMatch's default block, both lifted from the real source and
  // run in that order, for every value this device might have stored: nothing, a view that still
  // exists, and a leftover string from another version of the page.
  const initStart = SOURCE.indexOf('  const remembered = rememberFogView();');
  const openStart = SOURCE.indexOf('      if (!rememberFogView()');
  const openEnd = SOURCE.indexOf('} catch (_error) { /* storage off */ }', openStart);
  assert.ok(initStart >= 0 && openStart >= 0 && openEnd > openStart, 'find both blocks in tabletop.js');
  const init = SOURCE.slice(initStart, SOURCE.indexOf('\n', initStart)).trim();
  const opening = SOURCE.slice(openStart, openEnd);

  // [stored value, the view a fight you play opens on, the view a fight you only watch opens on]
  const expected = [
    [null, DEFAULT_FOG_VIEW, NO_FOG_VIEW],          // a device that never chose: your own fighter's view
    ['view-from-another-version', DEFAULT_FOG_VIEW, NO_FOG_VIEW], // a leftover this page cannot read is not a choice
    [DEFAULT_FOG_VIEW, DEFAULT_FOG_VIEW, DEFAULT_FOG_VIEW],
    ['team', 'team', 'team'],
    ['selected', 'selected', 'selected'],
    [NO_FOG_VIEW, NO_FOG_VIEW, NO_FOG_VIEW],        // an explicit Game Master's view is honoured as asked
  ];
  const opened = new Set();
  for (const [stored, playing, watching] of expected) {
    for (const [role, want] of [['playing', playing], ['watching', watching]]) {
      const store = new Map(stored === null ? [] : [['tt-fog', stored]]);
      const localStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value)};
      const app = {fog: NO_FOG_VIEW};
      const picker = {};
      const context = vm.createContext({
        app, localStorage, fogView, $: () => picker, playsAFighterHere: () => role === 'playing',
        refresh: async () => opened.add(app.fog), DEFAULT_FOG_VIEW, NO_FOG_VIEW,
      });
      vm.runInContext([sourceOf('rememberFogView'), sourceOf('setFogPicker'), init].join('\n'), context);
      // start()'s own initialization is in the script above, so app.fog already carries whatever this
      // device stored (or the Game Master's view when it stored nothing this page can read).
      await vm.runInContext(`(async () => {\n${opening}\n})()`, context);
      assert.equal(app.fog, want, `stored ${stored}, ${role}`);
      assert.equal(picker.value, want, `the picker follows the fight, stored ${stored}, ${role}`);
      opened.add(app.fog);
    }
  }
  assert.deepEqual([...opened].sort(), ['off', 'own', 'selected', 'team']);
});

test('every choice is explained in plain words, naming what it shows and who it affects', () => {
  for (const view of FOG_VIEWS) {
    assert.ok(view.help.length > 40, view.value);
    assert.doesNotMatch(view.label + view.help, /\b(team_index|entity_id|viewer|fog_perception|perception|LOCAL_AUTO|MANUAL)\b/,
      `${view.value} speaks to a player, not to the code`);
    assert.match(view.help, /\byou\b|\bYou\b/, view.value);
  }
  assert.match(FOG_VIEWS[0].help, /only an ally can see stays hidden/i);
  assert.match(FOG_VIEWS[0].help, /dimly visible as memory/i, 'explored squares stay revealed as memory');
  assert.match(FOG_VIEWS[0].help, /the fighters you control/i, 'every fighter you drive is your own view');
  assert.match(FOG_VIEWS[1].help, /allies' sight combined/i);
  assert.match(FOG_VIEWS[3].help, /Game Master/);
});

// The service answers per viewer, so both views read one set; tokenHiddenByFog is the reader
// the board uses, so its contract is stated here rather than left to the fixture.
test('token hiding follows the viewers the chosen view names', () => {
  assert.equal(tokenHiddenByFog(ACTORS[2], [ACTORS[0]], PERCEPTION), true);
  assert.equal(tokenHiddenByFog(ACTORS[2], [ACTORS[0], ACTORS[1]], PERCEPTION), false);
  assert.equal(tokenHiddenByFog(ACTORS[2], [], PERCEPTION, false), false);
  assert.equal(perceivedCells(WIDTH, HEIGHT, [ACTORS[0]], PERCEPTION)[1 * WIDTH + 10], 0);
});

// The same viewer selection over a REAL fight: mixed control (the player's fighter, an AI ally on
// the player's side, and a foe the Game Master drives by hand) with a REAL TabletopService answer.
// The fixture carries the service's own field names, including the battlefield's `width_squares`
// and `height_squares` -- the Node side reads those names, so a rename on either side is a failure
// here rather than a silent fall back to the hand-built 12x5 yard (OCF6r1 review finding).
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

    const ctx = table('own', {roster, perception: fixture.fog_perception, width, height});
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
    assert.equal(ownsAFighter(roster), true, 'and the real fight opens on the fog of war for you');

    const allies = table('team', {roster, perception: fixture.fog_perception, width, height});
    const shared = [...allies.viewerIds()];
    assert.ok(shared.includes(mine.entity_id), "the allies' view still looks through your fighter");
    assert.ok(!shared.includes(foe.entity_id), 'and never through the enemy');
    assert.equal(allies.unseenByViewers(foe), false,
      'the ally can see the foe, so the shared view keeps the behaviour it always had');
  });
