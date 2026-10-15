"""One-Breath's published object action commits and reloads like a creature hit."""
import pytest

from combat.ext import insights6 as ix
from tests.test_a2_group_insights6 import fight
from tests.auto_worker1_support import LEFT, RIGHT, act, reload, resolve, turn


@pytest.mark.parametrize('owned,artifact,unattended,threshold', [(False,False,True,0),(True,False,True,0),
    (True,False,True,10),(True,True,True,0),(True,False,False,0),(True,False,True,30)])
def test_siege_triple_threshold_and_protection(tmp_path,owned,artifact,unattended,threshold):
    def objects(arena):
        arena['map_objects']=[{'id':600,'kind':'crate','x':3,'y':7,'hp':200,'threshold':threshold,
                              'ac':1,'unattended':unattended,'artifact':artifact}]
    combat,table,mid=fight(tmp_path,['tianxia.path.body_refining.feature.iron_fist'] + (['insight.living-siege-engine'] if owned else []),arena_edit=objects,left_attack_bonus=100)
    # Use the ordinary published unarmed object action and the real session journal.
    state=table.state(mid);engine=combat._load_session(mid).engine
    action=next(a for a in engine.action_catalog.values() if a.owner_id==LEFT and
                (a.parameters.get('typed') or {}).get('object_weapon_group')=='unarmed')
    candidate=next(c for c in engine.legal_candidates() if c.source_definition_id==action.source_definition_id and 'object:map.600' in c.target_ids)
    from combat.gate2_runtime_models import ActionIntent
    session=combat._load_session(mid)
    session.mechanical.execute_intent(ActionIntent(intent_id='intent:siege',actor_id=LEFT,candidate_id=candidate.candidate_id,
        decision_id=candidate.decision_id,state_version=candidate.state_version,target_ids=candidate.target_ids))
    engine=reload(combat,mid)
    hit=next(e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.target_ids==('object:map.600',))
    assert hit.payload['provisional_hit']
    raw=sum(int(r.total) for r in engine.rolls if str(r.reason).startswith('DAMAGE:') and ':object:' in str(r.reason))
    qualifies=owned and not artifact and unattended
    expected=(raw*(3 if qualifies else 1)) if raw>=max(0,threshold-(10 if qualifies else 0)) else 0
    assert 200-engine.state.objects['object:map.600'].current_hp==expected


@pytest.mark.parametrize('owned,distance', [(True, 0), (True, 5), (True, 10), (False, 0)])
def test_one_breath_object_hit_spends_first_hit_across_table_reload(tmp_path, owned, distance):
    def reliable_object_attack(bundle):
        for action in bundle['action_catalog']:
            if action['parameters'].get('object_attack'):
                action['parameters']['typed']['numbers']['attack_bonus'] = 100
            if action['display_name'] == 'Follow-up unarmed strike':
                action['parameters']['typed']['numbers']['attack_bonus'] = 100

    preparation = []
    if distance:
        preparation.append({'type': 'rider_step', 'distance_ft': distance, 'no_oa': True})
    combat, table, mid = fight(
        tmp_path, [ix.ONE] if owned else [], left_kit={'items': []},
        prepare=preparation, prepare_target='SELF', bundle_edit=reliable_object_attack,
        extra_actions=[('Follow-up unarmed strike', {
            'target_kind': 'HOSTILE_ENTITY',
            'effects': [{'type': 'attack', 'attack_kind': 'unarmed',
                         'dice': {'count': 1, 'sides': 4}, 'damage_types': ['bludgeoning']}],
        })],
        arena_edit=lambda arena: arena.update(map_objects=[
            {'id': 1, 'kind': 'crate', 'x': 2, 'y': 6-distance//5, 'hp': 999, 'ac': 1}]),
    )
    if distance:
        resolve(lambda answers: act(table, mid, 'Prepare', answers),
                {'choice:needle.rider_step': [f'cell:3,{6-distance//5}']})
    before = reload(combat, mid)
    resolve(lambda answers: act(table, mid, 'Attack an object', answers, target_id='object:map.1'))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    eligible = owned and distance <= 5
    roll = [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:')][-1]
    assert roll.modifier == (2 if eligible else 0)  # Strength is in fixed_damage
    assert before.state.objects['object:map.1'].current_hp - engine.state.objects['object:map.1'].current_hp == roll.total
    assert len([m for m in actor.modifiers.values() if m.target_field == 'armor_class']) == int(eligible)
    assert ('insights6_one_round_turn' in actor.turn_flags) == eligible
    # The real object action spent the Action; a legal synthetic free strike
    # tests the same-turn allowance without changing the actor's turn flags.
    resolve(lambda answers: act(table, mid, 'Follow-up unarmed strike', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:')][-1].modifier == 0
    assert len([m for m in engine.state.actors[LEFT].modifiers.values() if m.target_field == 'armor_class']) == int(eligible)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not any(m.target_field == 'armor_class' for m in reload(combat, mid).state.actors[LEFT].modifiers.values())
    resolve(lambda answers: act(table, mid, 'Follow-up unarmed strike', answers, target_id=RIGHT))
    assert [r for r in reload(combat, mid).rolls if str(r.reason).startswith('DAMAGE:')][-1].modifier == (2 if owned else 0)
