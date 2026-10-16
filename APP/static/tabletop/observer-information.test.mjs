import test from 'node:test';
import assert from 'node:assert/strict';
import {observerInformationLines} from './observer-information.js';

test('private direction does not reveal a position or another observer reading', () => {
  const data={a:{information:[{kind:'direction',viewer_id:'a',details:{direction:'east',position:{x:9,y:4}}}]},
    b:{information:[{kind:'direction',viewer_id:'b',details:{direction:'west'}}]}};
  assert.equal(observerInformationLines({entity_id:'a'},data).length,1);
  assert.match(observerInformationLines({entity_id:'a'},data)[0],/east/);
  assert.doesNotMatch(observerInformationLines({entity_id:'a'},data)[0],/west|9|4/);
  assert.deepEqual(observerInformationLines({entity_id:'unknown'},data),[]);
});

test('wrong-viewer rows are not displayed even in a malformed projection', () => {
  assert.deepEqual(observerInformationLines({entity_id:'a'},{a:{information:[
    {kind:'concealment_exists',viewer_id:'b',details:{}}]}}),[]);
});

test('failed revelation and field notices use only their permitted facts', () => {
  const lines=observerInformationLines({entity_id:'a'},{a:{information:[
    {kind:'concealment_exists',viewer_id:'a',details:{position:{x:8},nature:'secret'}},
    {kind:'field_event',viewer_id:'a',details:{event_type:'enters',direction:'north',allegiance:'unknown',creature_name:'secret'}}]}});
  assert.equal(lines.length,2);
  assert.match(lines[0],/location and nature remain unknown/);
  assert.match(lines[1],/north.*unidentified/);
  assert.doesNotMatch(lines.join(' '),/secret|8/);
});

test('source-scoped direction and distance stay with their observer', () => {
  const row = {kind:'direction',viewer_id:'owner',details:{target:'Marked creature',direction:'north',distance_ft:45}};
  const projection = {owner:{information:[row]},other:{information:[row]}};
  assert.deepEqual(observerInformationLines({entity_id:'owner'},projection),['Marked creature is north, 45 feet away.']);
  assert.deepEqual(observerInformationLines({entity_id:'other'},projection),[]);
});
