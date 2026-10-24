// Real service cards supplied by test_flight_ui.py, through the adapter and board tooltip.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {heightMovement} from '../static/tabletop/flight-ui.js';
import {runMovementHover} from './movement_tooltip_hover.mjs';

const {movement, moves} = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const original = structuredClone(movement.destinations['4,4']);
assert.equal(original.available, true);
assert.ok(original.reasons.length);
const adapted = heightMovement(movement, moves, 0);
assert.deepEqual(adapted.destinations['4,4'].reasons.slice(0, -1), original.reasons);
const route = moves.find(row => row.destination.x === 4 && row.destination.y === 4 && !row.destination.z);
assert.match(adapted.destinations['4,4'].reasons.at(-1).message, new RegExp(`Costs ${route.cost_ft} ft`));
await runMovementHover(adapted);
const elevated = heightMovement(movement, [{...route, destination: {...route.destination, z: 2}}], 2);
assert.equal(elevated.destinations['4,4'].reasons.length, 1, 'ground penalties must not be copied onto flight');
assert.match(elevated.destinations['4,4'].reasons[0].message, /height 10 ft/);
assert.deepEqual(movement.destinations['4,4'], original, 'service cards are not mutated');
console.log('real ground reasons and height quotes: PASS');
