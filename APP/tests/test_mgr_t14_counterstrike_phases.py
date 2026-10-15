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
    settle(table, mid, selected.candidate_id, picks={REACTION: 'first'})
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
