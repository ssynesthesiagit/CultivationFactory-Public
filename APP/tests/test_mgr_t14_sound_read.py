"""Owner choices, real Sound dice and clue privacy across native table reload."""
import pytest

from tests.worker2_support import OWNER, ALLY, fixture, candidate, reload, settle, turn
from tests.test_r9i_karma_persistence import act

READ = 'TAL_SOUND_READ_THE_VIBRATION'


@pytest.mark.parametrize('method,skill', [('stealth', 'Stealth'), ('sleight', 'Sleight of Hand'),
    ('perception', 'Perception'), ('cultivation', None), ('gm_dc', None)])
def test_read_all_printed_checks_complete_and_cold_replay(tmp_path, method, skill):
    combat, table, mid = fixture(tmp_path, [READ], seed='T14-read-' + method, named=True)
    c = candidate(combat, mid, 'Read the Vibration')
    before = reload(tmp_path, mid)
    pending = act(table, mid, c.candidate_id)
    assert pending['status'] == 'REACTION_REQUIRED'
    assert len(reload(tmp_path, mid).rolls) == len(before.rolls), 'selection must pause before either check'
    assert pending['reaction']['context']['reaction_source_id'] == 'choice:needle.vibration_clue'
    assert {o['id'] for o in pending['reaction']['choice']['options']} == {'movement', 'structure', 'hidden_sound', 'object', 'influence'}
    prompts = settle(table, mid, c.candidate_id, picks={'choice:needle.vibration_method': method,
        'choice:needle.vibration_opponent': ALLY, 'choice:needle.scene_gm_dc': ('0', 'done'),
        'choice:needle.vibration_clue': 'movement'})
    e = reload(tmp_path, mid)
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED' and READ in v.source_definition_id]
    assert len(checks) == 1
    check = checks[0].payload
    assert check['check_metadata']['method'] == method
    assert check['target_skill'] == skill
    assert bool(check.get('target')) == (method != 'gm_dc')
    assert check['actor']['actor_id'] == OWNER
    assert check['actor']['reason'].startswith('CHECK:')
    method_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.vibration_method')
    assert {o['id'] for o in method_prompt['choice']['options']} == {'gm_dc', 'stealth', 'sleight', 'perception', 'cultivation'}
    assert check['check_metadata']['inquiry'] == 'movement'
    clues = [v for v in e.events if v.payload.get('clue')]
    assert len(clues) == int(check['success'])
    for clue in clues:
        assert not clue.target_ids
        assert clue.payload['check_roll_id'] == check['actor']['roll_id']
        assert clue.payload['exact_location'] == 0
        assert 'destination' not in clue.payload and 'position' not in clue.payload
    assert not e.state.actors[OWNER].action_available


def test_gm_dc_is_entered_before_roll_and_not_replaced_by_cultivation_dc(tmp_path):
    combat, table, mid = fixture(tmp_path, [READ], named=True)
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'gm_dc', 'choice:needle.scene_gm_dc': ('1', '3', '5', 'done')})
    e = reload(tmp_path, mid)
    check = next(v for v in e.events if v.event_type == 'CHECK_ROLLED' and READ in v.source_definition_id)
    assert check.payload['dc'] == 135 and not check.payload['success']
    assert not any(v.payload.get('clue') for v in e.events)


def test_success_returns_bounded_clue_from_real_committed_movement(tmp_path):
    combat, table, mid = fixture(tmp_path, [READ], named=True)
    turn(table, mid, ALLY)
    e = combat._load_session(mid).engine
    move = next(c for c in e.legal_candidates() if c.destination and c.kind == 'MOVE'
                and c.destination.x == 4 and c.destination.y == 7)
    settle(table, mid, move.candidate_id)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'gm_dc', 'choice:needle.scene_gm_dc': ('0', 'done'),
               'choice:needle.vibration_clue': 'movement'})
    e = reload(tmp_path, mid)
    clue = next(v for v in e.events if v.payload.get('clue'))
    assert clue.payload['evidence_sequences']
    assert 'nearby space' in clue.payload['text']
    assert not clue.target_ids and clue.payload['exact_location'] == 0
    assert not any(v.event_type == 'CONDITION_REMOVED' and v.payload.get('reason') == 'found' for v in e.events)


@pytest.mark.parametrize('topic', ['structure', 'hidden_sound', 'object', 'influence'])
def test_success_never_invents_an_unrecorded_scene_fact(tmp_path, topic):
    combat, table, mid = fixture(tmp_path, [READ], named=True)
    settle(table, mid, candidate(combat, mid, 'Read the Vibration').candidate_id,
        picks={'choice:needle.vibration_method': 'gm_dc', 'choice:needle.scene_gm_dc': ('0', 'done'),
               'choice:needle.vibration_clue': topic})
    e = reload(tmp_path, mid)
    clue = next(v for v in e.events if v.payload.get('clue'))
    assert clue.payload['clue'] == topic and 'unknown' in clue.payload['text']
    assert not clue.target_ids and clue.payload['exact_location'] == 0


def test_ai_selected_native_intent_resolves_legal_choices_without_player_answers(tmp_path):
    from combat.gate2_runtime_models import ActionIntent
    combat, table, mid = fixture(tmp_path, [READ], named=True, ask=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    c = candidate(combat, mid, 'Read the Vibration')
    session = combat._load_session(mid)
    # A model seat may select any legal candidate. Its selected native intent
    # then makes the inline choices automatically, with no live model client.
    session.mechanical.execute_intent(ActionIntent(intent_id='t14-ai-read', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=OWNER,
        target_ids=c.target_ids, destination=c.destination))
    e = reload(tmp_path, mid)
    check = next(v for v in e.events if v.event_type == 'CHECK_ROLLED' and READ in v.source_definition_id)
    assert check.payload['check_metadata']['method'] in {'stealth', 'sleight', 'perception', 'cultivation'}
    assert check.target_ids == (ALLY,)
    assert not any(v.payload.get('clue') and (v.target_ids or v.payload.get('exact_location')) for v in e.events)
