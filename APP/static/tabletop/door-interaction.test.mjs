import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {doorMenu} from './door-interaction.js';
const door = {id: 'object:map.1', name: 'Wooden door', interaction: 'simple_door', open: false, door_locked: 0, door_jammed: 0};
const menu = (economy = 'NONE') => ({manual: true, actions: [{source_definition_id: 'system:door.open.free', economy,
  options: [{candidate_id: 'open-1', target_ids: [door.id]}, {candidate_id: 'open-2', target_ids: ['other']}]}]});
test('door click offers only the exact server-authorized door and its price', () => {
  assert.deepEqual(doorMenu(door, menu()).options, [{candidate_id: 'open-1', label: 'Open Wooden door (free interaction)'}]);
  assert.equal(doorMenu({...door, open: true}, menu('ACTION')).options[0].label, 'Close Wooden door (Utilize action)');
});
test('locked and stuck doors explain why and never submit an action', () => {
  for (const [flag, word] of [['door_locked', 'Locked'], ['door_jammed', 'Stuck']]) {
    const result = doorMenu({...door, [flag]: 1}, menu());
    assert.match(result.message, new RegExp(word));
    assert.deepEqual(result.options, []);
  }
});
test('unavailable turns and out-of-reach doors have no fabricated choice', () => {
  assert.deepEqual(doorMenu(door, {...menu(), manual: false}).options, []);
  assert.deepEqual(doorMenu(door, {manual: true, actions: []}).options, []);
  assert.equal(doorMenu({...door, interaction: null}, menu()), null);
});
test('unavailable doors describe opening and closing separately', () => {
  const unavailable = {manual: true, actions: []};
  assert.match(doorMenu(door, unavailable).message, /To open this door/);
  assert.doesNotMatch(doorMenu(door, unavailable).message, /space to close/);
  assert.match(doorMenu({...door, open: true}, unavailable).message, /To close this door/);
  assert.match(doorMenu({...door, open: true}, unavailable).message, /opening must be clear/);
});
test('an actual unavailable door table response shows its refusal and offers no choice', {skip: !process.env.DOOR_TABLE_RESPONSE_PATH}, () => {
  const response = JSON.parse(readFileSync(process.env.DOOR_TABLE_RESPONSE_PATH, 'utf8'));
  const actualDoor = response.objects.find(object => object.id === (process.env.DOOR_TABLE_DOOR_ID || 'object:map.1'));
  assert.ok(actualDoor, 'the real table response must contain the requested door');
  const shown = doorMenu(actualDoor, response.menu, response);
  const operation = actualDoor.open ? 'close' : 'open';
  const reasons = response.unavailable_reasons;
  const key = [`act:system:door.${operation}.free:${actualDoor.id}`,
    `act:system:door.${operation}.utilize:${actualDoor.id}`];
  const actualRefusal = key.map(candidate => reasons[candidate]).find(value => value && !/^No eligible target or position/i.test(value));
  if (actualRefusal) {
    assert.match(shown.message, new RegExp(actualRefusal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(shown.message, /within 5 feet/i);
  assert.doesNotMatch(shown.message, /No eligible target or position/i);
  assert.deepEqual(shown.options, []);
});
test('real multi-door response offers a legal door but explains the distant door', {skip: !process.env.DOOR_MULTI_TABLE_RESPONSE_PATH}, () => {
  const response = JSON.parse(readFileSync(process.env.DOOR_MULTI_TABLE_RESPONSE_PATH, 'utf8'));
  const near = response.objects.find(object => object.id === 'object:map.1');
  const far = response.objects.find(object => object.id === 'object:map.2');
  const crate = response.objects.find(object => object.id === 'object:map.3');
  const nearShown = doorMenu(near, response.menu, response);
  const farShown = doorMenu(far, response.menu, response);
  assert.ok(nearShown.options.length, 'the legal nearby door should remain usable');
  assert.deepEqual(farShown.options, [], 'the distant door must not borrow the nearby door choice');
  assert.match(farShown.message, /within 5 feet/i);
  assert.equal(doorMenu(crate, response.menu, response), null);
  assert.ok(!Object.keys(response.unavailable_reasons).some(key => key.endsWith(`:${crate.id}`)),
    'an unrelated object must not inherit a source-wide door refusal');
});
test('a door without a legal option names the fighter whose turn it is', () => {
  const state = {presentation: {current_actor_id: 'current', actors: [
    {entity_id: 'owner', display_name: 'Rin'}, {entity_id: 'current', display_name: 'Bo'}]}};
  assert.match(doorMenu(door, {manual: true, actions: []}, state).message,
    /It is Bo's turn\./);
});
