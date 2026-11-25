// Execute the real turn UI functions in Node; no browser, server, or GUI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createSeatContext} = require('./tabletop_seats_harness.cjs');
const source = fs.readFileSync(path.join(__dirname, '../static/tabletop/tabletop.js'), 'utf8');
function fn(name, async = false) {
  const start = source.indexOf(`${async ? 'async ' : ''}function ${name}(`);
  assert.ok(start >= 0, `${name} is present`);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
const constants = ['isManualActor', 'automaticSlot'].map(name =>
  source.match(new RegExp(`const ${name} = [^\\n]+`))[0]).join('\n');
// renderActionBar's module-level loading timer (the "Loading your choices" delay), declared beside it in tabletop.js.
const loadingState = source.match(/^let menuLoadingTimer = null;\nlet menuLoadingActor = null;$/m)[0];
// Counted rather than assumed: if the bar ever stops offering Play, these cases say so instead of skipping the check.
let playPauseCases = 0;
async function check(life, active, paused, expected, controller = 'MANUAL') {
  const actor = {entity_id:'human', display_name:'Tabik Damu', controller, active, life_state:life};
  const nodes = new Map();
  const node = name => {
    if (!nodes.has(name)) nodes.set(name, {textContent:'', disabled:false, addEventListener(event, handler){this[event] = handler;}});
    return nodes.get(name);
  };
  const bar = {innerHTML:'', querySelector:node, replaceChildren() { this.innerHTML = ''; }};
  let plays = 0;
  const context = createSeatContext({
    app:{matchId:'test', menu:active && life ? {end_turn:'end'} : null, state:{}, playing:false, busy:false, userPaused:paused, speed:0.5},
    presentation:() => ({current_actor_id:actor.entity_id, terminal:false}), actorById:() => actor,
    hasManualFighter:() => active, setTimeout:fn => fn(), play:() => plays++, autoStep(){},
    $:() => bar, setControl(){},
    // Pause is the fight's saved flag on the server (Slice A, f6c9aa84b): the handler posts it and then refreshes.
    api: async (_url, {body}) => ({paused: body.paused, running: false, seats: {}}), enc: encodeURIComponent,
    refresh: async () => {}, toast(message) { throw new Error(message); },
    openSeatLog(){},
    useGroup(){},  // inert: these cases have no fight-setup owners (that path is in fight-setup-prompt.test.mjs)
  });
  // The real fight-setup binding, the same module tabletop.js imports (export keyword stripped as in tabletop_seats_harness.cjs).
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/tabletop/fight-setup-prompt.js'), 'utf8').replace(/^export /mg, ''), context);
  vm.runInContext(constants + '\n' + loadingState + '\n' + fn('scheduleAutoPlay') + '\n' + fn('toggleAIPlayback', true) + '\n' + fn('renderActionBar', true), context);
  vm.runInContext('scheduleAutoPlay()', context);
  assert.equal(plays, expected);
  await vm.runInContext('renderActionBar()', context);
  if (expected) {
    assert(!bar.innerHTML.includes('Loading your choices'));
    assert(node('.tt-muted').textContent.includes('this turn passes automatically'));
    assert(node('[data-take]').disabled);
  }
  if (active && life) {
    assert(node('.tt-muted').textContent.includes('no actions, reactions, or movement'));
    assert(bar.innerHTML.includes('End turn'));
  }
  if (bar.innerHTML.includes('data-play')) {
    // Exercise the real shared Play/Pause handler wherever the bar offers it, rather than merely binding a missing stub.
    // (A human's own turn with no menu yet shows no AI controls: an empty bar, then "Loading your choices".)
    playPauseCases += 1;
    context.app.playing = true;
    await node('[data-play]').click();
    assert.equal(context.app.playing, false);
    assert.equal(context.app.userPaused, true);
    await node('[data-play]').click();
    assert.equal(context.app.userPaused, false);
    assert.equal(plays, expected + 1);
  }
}
(async () => {
  await check(null, false, false, 1);
  await check('DYING', true, false, 0);
  await check('STABLE', true, false, 0);
  await check(null, true, false, 0); // conscious human retains control
  await check(null, false, true, 0); // explicit Pause is respected
  await check(null, false, false, 0, 'LOCAL_AUTO'); // opening all-AI saves still waits for Play
  assert.ok(playPauseCases > 0, 'at least one case offered the bar Play/Pause, so its handler ran');
  console.log(`SOL113 turn UI: 6 cases passed (Play/Pause exercised in ${playPauseCases})`);
})().catch(error => { console.error(error); process.exitCode = 1; });
