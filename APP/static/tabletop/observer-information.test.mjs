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

test('clinical diagnosis is private, readable, and does not print internal source identifiers', () => {
  const perception = {'actor:a': {information: [{kind: 'declaration', viewer_id: 'actor:a',
    source_id: 'private:internal-source', details: {diagnosis: 'Numb Channels', patient_name: 'Patient',
      source_instance: 'internal:receipt', suppressed: 1}}]}};
  const lines = observerInformationLines({entity_id: 'actor:a'}, perception);
  assert.deepEqual(lines, ['Medical diagnosis for Patient: Numb Channels. Its effects are currently suppressed.']);
  assert.deepEqual(observerInformationLines({entity_id: 'actor:b'}, perception), []);
  assert.ok(!lines.join(' ').includes('internal'));
});

test('clinical symptoms do not reveal a diagnosis, caster or DC', () => {
  const perception = {'actor:a': {information: [{kind: 'declaration', viewer_id: 'actor:a',
    source_id: 'clinical_symptoms', details: {symptoms: ['Speed reduced by 5 feet until Long Rest or treatment']}}]}};
  assert.deepEqual(observerInformationLines({entity_id: 'actor:a'}, perception),
    ['Your symptoms: Speed reduced by 5 feet until Long Rest or treatment.']);
});
