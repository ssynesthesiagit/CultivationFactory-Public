"""Shield relocation and area history through table/session execution and cold replay."""
import pytest
from combat import armour, carry
from combat.ext import hand_occupancy, shield_wielding, scoundrel_riders
from tests import auto11_service_support as S
from tests.test_a2_scoundrel_service import cold, TALENTS, reply

SHIELD_KEY = 'tianxia.mortal.armor.shield'
SHIELD = {'items': [{'item_id': SHIELD_KEY, 'name': 'Shield', 'quantity': 1}]}
STEAL = ['TAL_SCOUNDREL_STEAL', 'TAL_SCOUNDREL_DIRTY_TRICK']


def ac(engine):
    victim = engine.state.actors[S.VICTIM]
    return victim.armor_class + engine._ac_modifier(victim)


@pytest.mark.parametrize('location', ['carried', 'hand'])
def test_owner_shield_relocation_has_one_authoritative_location(tmp_path, location):
    combat, table, mid = S.fight(tmp_path, STEAL, victim_kit=SHIELD)
    before = cold(combat, mid)
    victim = before.state.actors[S.VICTIM]
    initial_ac, initial_weight = ac(before), carry.weight(before, victim)
    free = hand_occupancy.free_hands(before, victim)
    assert len(free) == 1
    assert shield_wielding.wielding_a_shield(before, victim)
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'): return 'reposition:' + SHIELD_KEY
        if source.endswith('steal_location'):
            return 'carried' if location == 'carried' else 'hand:' + free[0]
        return None
    response, prompts = S.play(table, mid, S.candidate(table, mid, 'STEAL', target=S.VICTIM), answer=answer)
    assert response['status'] == 'COMMITTED'
    assert any(p['context']['reaction_source_id'].endswith('steal_location') for p in prompts)
    committed = S.engine(combat, mid)
    reloaded = cold(combat, mid)
    assert committed.state.model_dump(mode='json') == reloaded.state.model_dump(mode='json')
    for engine in (committed, reloaded):
        victim = engine.state.actors[S.VICTIM]
        record = S.records(engine, SHIELD_KEY)
        assert len(record) == 1
        assert record[0][1]['held_by'] == S.VICTIM
        assert carry.weight(engine, victim) == initial_weight
        assert carry.holds(engine, victim, SHIELD_KEY)
        assert any(p['key'] == SHIELD_KEY for p in scoundrel_riders.possessions(engine, victim))
        occupied = hand_occupancy.occupancy(engine, victim)
        if location == 'carried':
            assert occupied == {}
            assert len(hand_occupancy.free_hands(engine, victim)) == 2
        else:
            assert occupied == {free[0]: ('shield:' + SHIELD_KEY,)}
            assert len(hand_occupancy.free_hands(engine, victim)) == 1
        assert shield_wielding.wielding_a_shield(engine, victim) == (location == 'hand')
        assert armour.shield_bonus_earning(engine, victim) == (2 if location == 'hand' else 0)
        assert ac(engine) == initial_ac - (2 if location == 'carried' else 0)


def test_area_can_choose_held_shield_and_drop_it_after_cold_reload(tmp_path):
    combat, table, mid = S.fight(tmp_path, TALENTS, victim_kit=SHIELD, seed='A2SCOUNDRE-area-B')
    before = cold(combat, mid)
    initial_ac = ac(before)
    assert hand_occupancy.occupancy(before, before.state.actors[S.VICTIM])
    response, prompts = S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=reply('held'))
    assert response['status'] == 'COMMITTED'
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.wrong_place_object')
    assert {o['label'] for o in menu['choice']['options']} == {'Shield'}
    committed = S.engine(combat, mid)
    reloaded = cold(combat, mid)
    assert committed.state.model_dump(mode='json') == reloaded.state.model_dump(mode='json')
    for engine in (committed, reloaded):
        victim = engine.state.actors[S.VICTIM]
        record = S.records(engine, SHIELD_KEY)
        assert len(record) == 1 and record[0][1]['dropped_at'] == {'x': 6, 'y': 6}
        assert not carry.holds(engine, victim, SHIELD_KEY)
        assert not scoundrel_riders.possessions(engine, victim)
        assert len(hand_occupancy.free_hands(engine, victim)) == 2
        assert not shield_wielding.wielding_a_shield(engine, victim)
        assert ac(engine) == initial_ac - 2


def test_area_object_history_names_actual_ability_after_cold_reload(tmp_path):
    combat, table, mid = S.fight(tmp_path, TALENTS, seed='A2SCOUNDRE-area-B')
    response, _ = S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=reply('drop'))
    assert response['status'] == 'COMMITTED'
    for engine in (S.engine(combat, mid), cold(combat, mid)):
        logs = [e.payload for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED']
        assert any('EVERYTHING IN THE WRONG PLACE:' in str(p).upper() and 'lets it fall' in str(p) for p in logs), logs
