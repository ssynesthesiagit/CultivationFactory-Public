"""Review regressions through committed service intents, cold reload and replay."""
import json

import pytest

from tests.auto_worker1_support import LEFT, RIGHT, fight, act, turn, reload, settle
from tests.test_a2_pressure_points import P, USED, conditions, send_prefix, option


@pytest.mark.parametrize('perception', ['visible', 'blinded', 'invisible_caster'])
@pytest.mark.parametrize('ai', [False, True])
def test_diagnosis_recipient_can_refuse_even_without_perceiving_caster(tmp_path, perception, ai):
    prep = []
    if perception != 'visible':
        prep = [{'type': 'condition', 'condition': 'blinded' if perception == 'blinded' else 'invisible',
                 'applies_to': 'target' if perception == 'blinded' else 'self', 'duration': 'until_removed'}]
    c, t, m = fight(tmp_path, [P+'pulse_diagnosis'], prepare=prep)
    if prep:
        settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    from combat.senses import perceives
    e = reload(c, m)
    assert perceives(e, e.state.actors[RIGHT], e.state.actors[LEFT]) == (perception == 'visible')
    _, prompts = settle(send_prefix(c, t, m, 'Pulse Diagnosis', target=RIGHT, ai=ai), choose=option('refuse'))
    (tmp_path/'prompts.json').write_text(json.dumps(prompts, indent=2)+'\n')
    e = reload(c, m)
    consent = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:willing.consent']
    assert len(consent) == 1
    assert consent[0]['context']['reactor_id'] == RIGHT
    assert not [v for v in e.events if v.event_type == 'CHECK_ROLLED']
    assert not [v for v in e.events if v.payload.get('diagnosis')]


@pytest.mark.parametrize('ability,choice', [('pulse_diagnosis', 'diagnosis_dc'),
                                          ('the_point_between_heartbeats', 'heartbeat_damage')])
def test_caster_decisions_identify_the_affected_creature(tmp_path, ability, choice):
    c, t, m = fight(tmp_path, [P+ability], left_score=50)
    prefix = 'Pulse Diagnosis' if ability == 'pulse_diagnosis' else 'The Point Between Heartbeats'
    _, prompts = settle(send_prefix(c, t, m, prefix, target=RIGHT))
    (tmp_path/'prompts.json').write_text(json.dumps(prompts, indent=2)+'\n')
    e = reload(c, m)
    owned = [p for p in prompts if p['context']['reaction_source_id'].startswith('choice:needle.pp2.')]
    assert any(p['context']['reaction_source_id'].endswith(choice) for p in owned)
    assert all(p['context']['reactor_id'] == LEFT and p['affected'] == 'Visitor' for p in owned)
    assert any(v.event_type == ('CHECK_ROLLED' if ability == 'pulse_diagnosis' else 'SAVE_ROLLED') for v in e.events)


def automatic_reactions(bundle):
    # Seal the minimal Auto plan at compilation; never mutate a live engine.
    bundle['reaction_plan']['mode'] = 'auto'
    for row in bundle.get('typed_reactions', []):
        row.pop('ask', None)
    for row in bundle.get('typed_passives', []):
        row.pop('choice_owner', None)
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Opportunity Attack':
            action['parameters']['typed']['numbers']['attack_bonus'] = 100


def test_stolen_step_only_owner_gets_offturn_player_distance_and_destination(tmp_path):
    c, t, m = fight(tmp_path, [P+'stolen_pulse_step'], bundle_edit=automatic_reactions,
        prepare=[{'type':'mark','mark':'Pressure Point','applies_to':'target','duration':{'kind':'until_removed'}}])
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    settle(lambda a: act(t, m, 'Touch the Point: Stolen Pulse Step', a))
    e = reload(c, m)
    assert not any(r.get('ask') for rows in e.typed_reaction_rows.values() for r in rows)
    assert not any(r.get('choice_owner') for rows in e.typed_passive_rows.values() for r in rows)
    assert {r['feature_id'] for r in e.typed_passive_rows[LEFT] if r.get('block') == 'shi_pp_point'} == {P+'stolen_pulse_step'}
    turn(t, m, RIGHT)
    e = reload(c, m)
    move = next(k for k in e.legal_candidates() if k.destination is not None
                and (k.destination.x, k.destination.y) == (5, 6)
                and k.metadata.get('movement_mode', 'walk') == 'walk')
    from tests.test_r4_integration import auto_candidate
    auto_candidate(c, m, RIGHT, move.candidate_id)
    def choose(p):
        ids = [o['id'] for o in p.get('choice', {}).get('options', [])]
        if 'half_speed' in ids:
            return ['half_speed']
        dest = next((o['id'] for o in p.get('choice', {}).get('options', [])
                     if o['label'].startswith('Walk to 3,3 ')), None)
        return [dest] if dest else ids[:1]
    _, prompts = settle(lambda a: t.auto_step(m, t.state(m)['last_sequence'], a), choose=choose)
    (tmp_path/'prompts.json').write_text(json.dumps(prompts, indent=2)+'\n')
    e = reload(c, m)
    distance = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.pp2.step_distance']
    destination = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.rider_step']
    assert len(distance) == len(destination) == 1
    assert all(p['context']['reactor_id'] == LEFT and p['affected'] == 'Visitor' for p in distance+destination)
    assert 'Visitor' in distance[0]['moment'] and 'Opportunity Attack' in distance[0]['moment']
    assert (e.state.actors[LEFT].position.x, e.state.actors[LEFT].position.y) == (3, 3)
    assert e.state.actors[LEFT].reaction_available is False
    assert any(v.event_type == 'ATTACK_ROLLED' and v.actor_id == LEFT
               and v.source_definition_id.endswith('.opportunity_attack') and v.payload['provisional_hit'] for v in e.events)


@pytest.mark.parametrize('name', ['poisoned', 'frightened'])
def test_gentle_release_success_removes_selected_instance_and_preserves_other(tmp_path, name):
    poison = {'type': 'save', 'ability': 'dex', 'on_fail': [
        {'type': 'condition', 'condition': name, 'applies_to': 'target', 'duration': 'until_removed'}], 'on_success': []}
    c, t, m = fight(tmp_path, [P+'gentle_release'], right_team='team:factory',
        # Paralysis guarantees the two original DEX failures. Ending it before
        # recovery leaves a native +102 save modifier, guaranteeing success.
        prepare=[{'type': 'condition', 'condition': 'paralyzed', 'applies_to': 'target',
                  'duration': 'until_removed'}, poison], prepare_target='ANY_CREATURE',
        left_save_dc=100, right_score=214,
        extra_actions=(('Second condition', {'target_kind': 'ANY_CREATURE', 'effects': [poison]}),
                       ('Restore movement', {'target_kind': 'ANY_CREATURE', 'effects': [
                           {'type': 'remove_condition', 'condition': 'paralyzed', 'applies_to': 'target'}]})))
    for label in ('Prepare', 'Second condition'):
        settle(lambda a: act(t, m, label, a, target_id=RIGHT))
    e = reload(c, m)
    held = conditions(e, RIGHT, 'condition:typed.'+name)
    assert len(held) == 2
    selected, preserved = [h.instance_id for h in held]
    assert all(h.data['origin_save']['dc'] == 100 for h in held)
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED' and not v.payload['success']]) == 2
    settle(lambda a: act(t, m, 'Restore movement', a, target_id=RIGHT))
    before = len(reload(c, m).events)
    _, prompts = settle(send_prefix(c, t, m, 'Gentle Release', target=RIGHT), choose=option('repeat:'+selected))
    e = reload(c, m)
    saves = [v for v in e.events[before:] if v.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and saves[0].payload['dc'] == 100 and saves[0].payload['success']
    assert [h.instance_id for h in conditions(e, RIGHT, 'condition:typed.'+name)] == [preserved]
    removed = [v for v in e.events[before:] if v.event_type == 'CONDITION_REMOVED']
    assert [v.payload['instance_id'] for v in removed] == [selected]
    assert e.state.actors[RIGHT].temporary_hp == 0 and conditions(e, RIGHT, USED+'gentle')
