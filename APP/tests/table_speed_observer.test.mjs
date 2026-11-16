import assert from 'node:assert/strict';
import fs from 'node:fs';

const desktop = fs.readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const opening = desktop.indexOf('async function loadSeats()');
const loadSource = desktop.slice(opening, desktop.indexOf('\n}', opening) + 2);
const scheduleStart = desktop.indexOf('function scheduleSeatPoll()');
const scheduleSource = desktop.slice(scheduleStart, desktop.indexOf('\n}', scheduleStart) + 2);

const app = {matchId: 'm', state: {}, seatStatus: {running: true}, playing: true, busy: false, automaticRun: false};
let tick, refreshes = 0, reads = 0;
const client = Function('app', 'api', 'enc', 'reconcileViewerIdentity', 'renderTokens', 'presentation', 'serverDriving', 'clearTimeout', 'setTimeout', 'refresh',
  'let seatReadSequence=0;\n' + loadSource + '\n' + scheduleSource + '\nreturn {loadSeats, scheduleSeatPoll};')(
    app,
    async () => (++reads === 1 ? {paused: false, running: true, status: 'RUNNING'} : {paused: false, running: false, status: 'IDLE'}),
    encodeURIComponent,
    () => false,
    () => {},
    () => ({terminal: false}),
    () => true,
    () => {},
    callback => { tick = callback; return 1; },
    async () => { refreshes++; },
  );

await client.loadSeats();
assert.equal(app.playing, true);
assert.equal(typeof tick, 'function', 'detecting another tab’s run installs an observer');
await tick();
assert.equal(app.playing, false, 'the observer clears the stale running flag');
assert.equal(refreshes, 1, 'the observer refreshes the completed human/prompt boundary');
