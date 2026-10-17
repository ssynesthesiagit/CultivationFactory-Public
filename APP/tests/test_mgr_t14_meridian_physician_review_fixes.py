"""Service regressions for travel authority and replacement protocol grants.

These qualify clinical producers, not the five incomplete Physician records.
"""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_mgr_t14_clinical_native import (
    A, B, C, game, anatomy, engine, use, next_round, act,
    final_native_mechanical_replay,
)
from tests.test_mgr_t14_meridian_physician_floor58 import NATIVE_TEST_RESOURCES


def encounter(cold, jid, rounds=20):
    state = cold().journey_state(jid)
    return cold().journey_start_combat(jid, state['revision'],
        {aid: 'team:b' if aid == B else 'team:a' for aid in state['actors']},
        maximum_rounds=rounds)['match_id']


def resume(cold, table, jid, mid):
    for _ in range(90):
        if engine(cold, mid).state.terminal_result is not None:
            break
        state = table.state(mid)
        act(cold, table, mid, state, state['menu']['end_turn'], lambda p, ids: [])
    assert engine(cold, mid).state.terminal_result is not None
    state = cold().journey_state(jid)
    result = cold().journey_resume(jid, state['revision'])
    assert result == cold().journey_state(jid)
    return result


def test_native_bitter_breath_seal_cannot_be_rewritten_in_travel(tmp_path, monkeypatch):
    from combat.clinical_sources import metadata
    from combat.ext.stacking_marks import count
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('poison',))
    anatomy(world)
    mid = encounter(cold, jid)
    for _ in range(10):
        loaded = engine(cold, mid)
        if count(loaded, loaded.state.actors[A], loaded.state.actors[B], 'Dose Mark') >= 2:
            break
        use(cold, table, mid, 'Deliver the Dose')
        next_round(cold, table, mid)
    before_qi = engine(cold, mid).state.actors[A].resources['resource:core.qi']
    use(cold, table, mid, 'Ingrain the Toxin: Bitter Breath',
        choose=lambda p, ids: ['Bitter Breath'] if 'Bitter Breath' in ids else ids[:1])
    loaded = engine(cold, mid)
    assert loaded.state.actors[A].resources['resource:core.qi'] == before_qi - 2
    toxin = next(c for c in loaded.state.actors[B].conditions.values()
                 if c.data.get('choice') == 'Bitter Breath')
    assert toxin.data['clinical_source_cl'] == 10
    assert 'source_cl' not in toxin.data['clinical']
    before = resume(cold, table, jid, mid)
    saved = json.loads(before['actors'][B]['encounter_snapshot']['conditions'][toxin.instance_id])
    assert saved['data']['clinical_source_cl'] == 10
    annotation = {'condition_instances': [toxin.instance_id], 'label': 'Lingering toxin',
                  'category': 'poison', 'ongoing': 0, 'excluded': [], 'source_cl': 3}
    with pytest.raises(ValueError, match='known native Source CL'):
        world('clinical_annotation', annotation, scope='incorrect authority')
    assert cold().journey_state(jid) == before
    # Same authority is legal and must not create another ailment.
    world('clinical_annotation', {**annotation, 'source_cl': 10}, scope='known authority')
    mid2 = encounter(cold, jid)
    loaded = engine(cold, mid2)
    restored = loaded.state.actors[B].conditions[toxin.instance_id]
    assert metadata(loaded, loaded.state.actors[B], restored)['source_cl'] == 10
    assert restored.data['clinical_source_cl'] == 10
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'
    assert cold()._load_session(mid2).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize(('source_deadline', 'now', 'restored'), [(20, 25, False), (40, 15, True)])
def test_native_suppression_keeps_original_deadline_across_travel(source_deadline, now, restored):
    """Purify's travel deadline must not replace a native source's own clock."""
    from combat.ext.clinical_treatment import clinical_elapsed
    from combat.clinical_sources import SUPPRESSION
    original = {
        'instance_id': 'native-condition',
        'condition_id': 'condition:typed.poisoned',
        'source_definition_id': 'native:poison',
        'source_actor_id': A,
        'target_id': B,
        'applied_sequence': 1,
        'expires_on': 'UNTIL_REMOVED',
        'data': {},
    }
    retained = {
        'instance_id': 'retained-native-condition',
        'condition_id': 'condition:typed.clinical_component',
        'source_definition_id': 'native:poison',
        'source_actor_id': A,
        'target_id': B,
        'applied_sequence': 2,
        'expires_on': 'UNTIL_REMOVED',
        'data': {
            'clinical_retained_source': {'source_instance': 'native-source'},
            'clinical_suppressed_until': 10,
            'clinical_source_expires_at': source_deadline,
            'model': original,
        },
    }
    marker = {
        'instance_id': 'suppression',
        'condition_id': SUPPRESSION,
        'source_definition_id': 'life:purify',
        'data': {'source_instance': 'native-source', 'clinical_suppressed_until': 10},
    }
    state = {'actors': {B: {'encounter_snapshot': {'conditions': {
        c['instance_id']: json.dumps(c) for c in (retained, marker)
    }}}}}
    events = []
    session = SimpleNamespace(state=state, clock=lambda: now,
                              emit=lambda *args, **kwargs: events.append((args, kwargs)))
    clinical_elapsed(session, B, now - 5, 5, True)
    conditions = state['actors'][B]['encounter_snapshot']['conditions']
    restored_models = [json.loads(encoded) for encoded in conditions.values()
                       if json.loads(encoded)['instance_id'] == 'native-condition']
    assert bool(restored_models) is restored
    if restored:
        # The saved native source clock remains explicit after the wrapper and
        # suppression marker have been removed and the journey state serialized.
        saved = json.loads(json.dumps(restored_models[0]))
        assert saved['data']['clinical_source_expires_at'] == source_deadline
        from combat.ext.clinical_treatment import clinical_external_clock
        loaded_condition = SimpleNamespace(data=saved['data'], expires_on=saved['expires_on'],
                                           instance_id=saved['instance_id'])
        actor = SimpleNamespace(conditions={loaded_condition.instance_id: loaded_condition})
        engine = SimpleNamespace(
            state=SimpleNamespace(actors={B: actor}, round_number=1, current_slot_index=0),
            typed_bundle_documents=[{'actor_id': B, 'journey_setup': {'elapsed_seconds': now}}],
        )
        clinical_external_clock(engine)
        assert loaded_condition.expires_on == 'START_OF_SLOT_AT:6:0'
    else:
        assert 'native-condition' not in conditions


@pytest.mark.parametrize('retained', [False, True])
def test_serialized_seal_wins_over_editable_document_and_blocks_annotation(retained):
    """Boundary control for suppression models as well as ordinary snapshots."""
    from combat.clinical_sources import metadata
    from combat.ext.clinical_treatment import annotation_models
    from combat.gate2_runtime_models import ConditionInstance
    facts = {'source_instance': 'native-toxin', 'source': 'native:toxin', 'owner': A,
             'category': 'poison', 'ongoing': 0, 'excluded': []}
    original = ConditionInstance(instance_id='native-condition', condition_id='condition:typed.poisoned',
        source_definition_id='native:toxin', source_actor_id=A, target_id=B,
        applied_sequence=1, expires_on='UNTIL_REMOVED',
        data={'clinical': facts, 'clinical_source_cl': 10})
    condition = original.model_copy(deep=True)
    if retained:
        condition.data = {'clinical_retained_source': deepcopy(facts),
                          'model': original.model_dump(mode='json'),
                          'rule': {'save_mode': 'DISADVANTAGE'}}
    state = {'actors': {B: {'encounter_snapshot': {'conditions': {
        condition.instance_id: condition.model_dump_json(exclude_none=True)}}}}}
    session = SimpleNamespace(state=state)
    annotation = {'condition_instances': [condition.instance_id], 'label': 'Native poison',
                  'category': 'poison', 'ongoing': 0, 'excluded': [], 'source_cl': 3}
    before = deepcopy(state)
    with pytest.raises(ValueError, match='known native Source CL'):
        annotation_models(session, B, annotation)
    assert state == before
    key = 'clinical_retained_source' if retained else 'clinical'
    condition.data[key]['source_cl'] = 3  # A stale editable document cannot outrank the seal.
    assert metadata(None, None, condition, retained=retained)['source_cl'] == 10


@pytest.mark.parametrize('readers', [[A], [], [C]])
def test_replaced_protocol_retires_old_readers_and_paid_progress_after_travel(tmp_path, monkeypatch, readers):
    from combat.ext.clinical_procedures import PROTOCOL, PROGRESS, action_id
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=(), ally=True)
    source = world('clinical_source', {'label': 'Poison requiring treatment', 'category': 'poison',
        'conditions': ['poisoned'], 'ongoing': 0, 'excluded': [], 'dc': 12}, readers=[A, C])
    group = source['fact_consent_admission'][-1]['receipt_id']
    value = {'method': 'Medicine', 'ability': 'WIS', 'skill': 'medicine', 'seconds': 60,
             'costs': {'resource:core.qi': 1}, 'operation': 'treat', 'source_instance': group}
    old = world('clinical_protocol', value, scope='appropriate medicine')['fact_consent_admission'][-1]
    unrelated = world('clinical_protocol', {**value, 'operation': 'identify'},
                      scope='separate examination')['fact_consent_admission'][-1]
    mid = encounter(cold, jid, rounds=1)
    use(cold, table, mid, 'Begin Medicine treatment')
    loaded = engine(cold, mid)
    assert any(c.condition_id == PROGRESS and c.data['receipt'] == old['receipt_id']
               for c in loaded.state.actors[A].conditions.values())
    resumed = resume(cold, table, jid, mid)
    assert any(json.loads(c)['condition_id'] == PROGRESS
               for c in resumed['actors'][A]['encounter_snapshot']['conditions'].values())
    updated = world('clinical_protocol', {**value, 'seconds': 120, 'costs': {'resource:core.qi': 3}},
                    scope='appropriate medicine', readers=readers)
    new = updated['fact_consent_admission'][-1]
    from combat.fact_consent_admission import read
    session = cold().journeys.load(jid)
    assert (read(session, 'clinical_source', B, 'clinical_protocol', 'appropriate medicine', A) is not None) == (A in readers)
    for actor in updated['actors'].values():
        for encoded in actor.get('encounter_snapshot', {}).get('conditions', {}).values():
            c = json.loads(encoded)
            assert not (c['condition_id'] == PROGRESS and c['data']['receipt'] == old['receipt_id'])
            if c['condition_id'] == PROTOCOL:
                assert json.loads(c['data']['record'])['receipt_id'] != old['receipt_id']
    mid2 = encounter(cold, jid)
    loaded = engine(cold, mid2)
    assert not any(action_id(old, s) in loaded.action_catalog for s in ('begin', 'continue', 'stop'))
    assert action_id(unrelated, 'begin') in loaded.action_catalog
    for aid in (A, B, C):
        actor = loaded.state.actors[aid]
        receipts = {json.loads(c.data['record'])['receipt_id'] for c in actor.conditions.values()
                    if c.condition_id == PROTOCOL}
        assert (new['receipt_id'] in receipts) == (aid in readers)
        assert old['receipt_id'] not in receipts
        assert not any(c.condition_id == PROGRESS for c in actor.conditions.values())
    if A in readers:
        before_qi = loaded.state.actors[A].resources['resource:core.qi']
        use(cold, table, mid2, 'Begin Medicine treatment')
        loaded = engine(cold, mid2)
        assert loaded.state.actors[A].resources['resource:core.qi'] == before_qi - 3
        progress = next(c for c in loaded.state.actors[A].conditions.values() if c.condition_id == PROGRESS)
        assert progress.data['receipt'] == new['receipt_id']
        assert progress.data['remaining_steps'] == 19
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'
    assert cold()._load_session(mid2).mechanical.replay()['status'] == 'PASS'
