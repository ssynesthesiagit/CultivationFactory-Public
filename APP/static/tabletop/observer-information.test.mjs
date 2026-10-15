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

test('source declarations and spoken words remain with their actual observer', () => {
  const viewer = {entity_id: 'listener'};
  const scoped = {listener: {information: [
    {viewer_id: 'listener', kind: 'declaration', details: {summary: 'You understand.', words: 'The tea is ready.'}},
    {viewer_id: 'other', kind: 'declaration', details: {summary: 'Secret from another seat.', words: 'Hidden.'}}
  ]}};
  assert.deepEqual(observerInformationLines(viewer, scoped), ['You understand. The tea is ready.']);
});
