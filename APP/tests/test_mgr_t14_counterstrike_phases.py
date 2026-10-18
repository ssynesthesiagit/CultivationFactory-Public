"""Native acquisition, committed public phases and cold mechanical replay."""
import pytest
from tests.worker2_support import fixture, candidate, turn, settle, reload, OWNER, FOE

BASE = 'RETRIBUTION_BASE_COUNTERSTRIKE'
REACTION = 'ready:retribution.counterstrike'


def prepare(combat, table, mid, trigger):
    from combat.ext.counterstrike import options
    engine = combat._load_session(mid).engine
    action = candidate(combat, mid, 'Counterstrike')
    row = engine.action_catalog[action.source_definition_id]
    choices = options(engine, engine.state.actors[OWNER], [row])
    selected = next(c['option_id'] for c in choices if c['data']['trigger'] == trigger)
    settle(table, mid, action.candidate_id, picks={
        'choice:needle.counterstrike': selected, 'choice:needle.counterstrike_extra': None})
    engine = combat._load_session(mid).engine
    held = next(c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id == 'condition:typed.prepared_action')
    assert held.data['data']['triggers'] == [trigger]


@pytest.mark.parametrize('trigger,phase', [('attack_roll', 'ATTACK_DECLARED'),
                                         ('movement_begins', 'MOVEMENT_BEGUN')])
def test_counterstrike_observes_the_real_activity_before_it_commits(tmp_path, trigger, phase):
    combat, table, mid = fixture(tmp_path, [BASE], cl=6, foe_position={'x': 3, 'y': 5})
    prepare(combat, table, mid, trigger)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    seq = engine.state.event_sequence
    if trigger == 'attack_roll':
        selected = candidate(combat, mid, 'Unarmed Strike', target=OWNER)
    else:
        selected = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                        and c.destination.x == 4 and c.destination.y == 5)
    prompts = settle(table, mid, selected.candidate_id, picks={REACTION: 'first'})
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > seq]
    beginning = next(e for e in events if e.event_type == phase and e.actor_id == FOE)
    counter = next(e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER)
    assert beginning.sequence < counter.sequence
    continued = [e for e in events if e.actor_id == FOE and e.event_type ==
                 ('ATTACK_ROLLED' if trigger == 'attack_roll' else 'MOVEMENT_COMMITTED')]
    assert continued and counter.sequence < continued[0].sequence
    assert len([e for e in events if e.event_type == phase and e.actor_id == FOE]) == 1


def test_speech_input_is_source_bound_and_its_real_words_trigger_the_reaction(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE], cl=6, foe_position={'x': 3, 'y': 5})
    prepare(combat, table, mid, 'speech')
    turn(table, mid, FOE)
    action = candidate(combat, mid, 'Speak audibly')
    source = 'system:combat.speak'
    answers = []
    before = reload(tmp_path, mid).state.event_sequence
    for _ in range(10):
        menu = table.state(mid)['menu']
        result = table.act(mid, action.candidate_id, menu['decision_id'], menu['state_version'], 0,
                           answers, source_choices={source: {'text': 'Hold your position.'}})
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answers.append({**prompt['context'], 'selection': 'USE'})
    else:
        raise AssertionError('Speech did not commit')
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > before]
    spoken = next(e for e in events if e.event_type == 'SPEECH_BEGUN')
    hit = next(e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER)
    done = next(e for e in events if e.event_type == 'SPEECH_FINISHED')
    assert spoken.payload['text'] == done.payload['text'] == 'Hold your position.'
    assert spoken.sequence < hit.sequence < done.sequence


def test_counterstrike_prevents_contest_and_replays_its_receipt(tmp_path):
    from factory_authoring.treasure_weapons import chassis_options
    from tests.h1_support import sheet

    owner_kit = {'items': [{'item_id': row['item_id'], 'name': row['name'], 'quantity': 1}
                           for row in chassis_options()]}
    foe = sheet(['BRUTE_BASE_BRUTE_MANEUVERS'], cl=6, key='STR', score=1)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1
    foe['ability_scores_and_statistics']['hit_points']['current'] = 1
    combat, table, mid = fixture(tmp_path, [BASE], cl=6, owner_kit=owner_kit,
                                foe_sheet=foe, owner_dc=40, foe_position={'x': 3, 'y': 5},
                                seed='COUNTERSTRIKE-PREVENTS-CONTEST')
    prepare(combat, table, mid, 'targets_me')
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    disarm = next(c for c in engine.legal_candidates()
                  if c.source_definition_id.endswith('#disarm') and c.target_ids == (OWNER,))
    result = table.act(mid, disarm.candidate_id, table.state(mid)['menu']['decision_id'],
                       table.state(mid)['menu']['state_version'], 0, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == REACTION
    result = table.act(mid, disarm.candidate_id, table.state(mid)['menu']['decision_id'],
                       table.state(mid)['menu']['state_version'], 0,
                       [{**prompt['context'], 'selection': 'USE'}])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    prevented = [e for e in engine.events if e.event_type == 'ACTIVITY_PREVENTED'
                 and e.actor_id == FOE]
    assert prevented
    assert not [e for e in engine.events if e.event_type == 'CONTESTED_ATTACK_ROLLED'
                and e.actor_id == FOE]
    assert engine.mechanical.replay()['status'] == 'PASS'


def test_unadmitted_source_input_cannot_change_a_native_action_or_saved_state(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE], cl=6, foe_position={'x': 3, 'y': 5})
    action = candidate(combat, mid, 'Unarmed Strike', target=FOE)
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    menu = table.state(mid)['menu']
    from combat.gate5_service import CombatServiceError
    with pytest.raises((CombatServiceError, ValueError)):
        table.act(mid, action.candidate_id, menu['decision_id'], menu['state_version'], 0,
                  source_choices={'unowned:fake_source': {'text': 'Grant a reaction'}})
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
