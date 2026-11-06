"""A paid mark-collapse rider is optional and commits exactly once through the table."""
import pytest

from combat.gate5_service import CombatService
from combat.typed_executor import bears_mark
from tests.test_carry import KIT
from tests.worker2_support import ROOT, OWNER, FOE, fixture, candidate, act, turn

TALENT = 'TAL_YIN_STILLNESS_HAS_TEETH'


@pytest.mark.parametrize('owned,damage_type', [(True, 'cold'), (True, 'necrotic'), (True, None), (False, None)])
def test_stillness_after_diminish_force_preview_commit_reload(tmp_path, owned, damage_type):
    combat, table, mid = fixture(tmp_path, [TALENT] if owned else ['TAL_YIN_WOUND_THAT_REFUSES_DAWN'],
                               seed='H5-CHOICES', owner_ac=1, foe_kit={'starting_kit': KIT},
                               foe_position={'x': 3, 'y': 5})
    mark = candidate(combat, mid, 'Mark the Waning', target=FOE)
    assert act(table, mid, mark.candidate_id)['status'] == 'COMMITTED'
    turn(table, mid, FOE)
    attack = candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    answers = []
    def send():
        return act(table, mid, attack.candidate_id, answers)
    result = send()
    while result['status'] == 'REACTION_REQUIRED' and 'receive_overextension' in result['reaction']['context']['reaction_source_id']:
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        result = send()
    if owned:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == 'choice:needle.stillness_has_teeth'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        assert send()['reaction'] == prompt
        answer = {**prompt['context'], 'selection': 'USE' if damage_type else 'DECLINE'}
        if damage_type:
            answer['option_ids'] = [next(o['id'] for o in prompt['choice']['options'] if damage_type in o['id'])]
        answers.append(answer)
        result = send()
    assert result['status'] == 'COMMITTED', result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner, foe = loaded.engine.state.actors[OWNER], loaded.engine.state.actors[FOE]
    assert not bears_mark(foe, OWNER, 'Waning Mark')
    assert foe.current_hp == 60 - (6 if damage_type else 0)
    assert owner.resources['resource:core.qi'] == 100 - bool(damage_type)
    receipts = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED'
                and e.actor_id == OWNER and e.target_ids == (FOE,)]
    assert len(receipts) == bool(damage_type)
    if receipts:
        assert damage_type.upper() in str(receipts[0].payload).upper()
        assert TALENT in str(receipts[0].payload)
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('accept', [True, False])
def test_stillness_after_recovery_is_asked_off_turn_and_reloads(tmp_path, accept):
    # This shared service harness prepares a wound with a real typed action,
    # then heals 20 HP. Only preparation/dice are fixed; reactions are shipped code.
    from tests.test_c15_healing_choices import healing_table
    from tests.r1i_service_support import OWNER as marker, FOE as patient, candidate as pick
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = healing_table(tmp_path, TALENT, 'hp', 'foe')
    commit(pick(table, mid, 'Mend the Pulse', patient))
    while table.state(mid)['menu']['actor_id'] != patient:
        commit(table.state(mid)['menu']['end_turn'])
    initial = reload(tmp_path, mid)
    hp = initial.state.actors[patient].current_hp
    qi = initial.state.actors[marker].resources['resource:core.qi']
    _, prompts = resolve(combat, mid, send, pick(table, mid, 'Mend the Pulse', patient), {
        'choice:needle.diminish_recovery': 'spend',
        'choice:needle.stillness_has_teeth': 'cold' if accept else None})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.stillness_has_teeth']
    assert len(asked) == 1
    assert asked[0]['context']['reactor_id'] == marker
    assert 'Diminish Recovery' in str(asked[0])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner, foe = loaded.engine.state.actors[marker], loaded.engine.state.actors[patient]
    assert not bears_mark(foe, marker, 'Waning Mark')
    assert foe.current_hp == hp + 14 - (6 if accept else 0)
    assert owner.resources['resource:core.qi'] == qi - accept
    assert loaded.mechanical.replay()['status'] == 'PASS'
