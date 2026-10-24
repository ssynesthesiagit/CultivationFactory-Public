"""Paired relocation uses the same resting grips as Draw, through real sessions."""
import pytest
from combat.ext import hand_occupancy
from tests import auto11_service_support as S
from tests.test_a2_scoundrel_service import cold
from tests.test_a2_scoundrel_fix_service import STEAL, victim_turn

PAIRED = [
    ('emei_ci', 'Emei Ci (Emei Piercers)'),
    ('gou_shuang_gou', 'Gou / Shuang Gou (Hook Sword / Double Hooks)'),
    ('hu_die_dao', 'Hu Die Dao (Butterfly Sabers)'),
    ('zi_wu', 'Zi-Wu (Deer Horn Knives)'),
]


@pytest.mark.parametrize('suffix,name', PAIRED)
@pytest.mark.parametrize('free_count', [1, 2])
def test_paired_relocation_requires_all_resting_hands_and_reloads(tmp_path, suffix, name, free_count):
    key = 'tianxia.mortal.weapon.' + suffix
    kit = {'items': [*S.SWORD['items'], {'item_id': key, 'name': name, 'quantity': 1}]}
    combat, table, mid = S.fight(tmp_path, STEAL, victim_kit=kit)
    before = cold(combat, mid)
    victim = before.state.actors[S.VICTIM]
    qiang = next(k for k in before.action_catalog if k.endswith('.weapon.qiang'))
    paired = next(a for k, a in before.action_catalog.items() if k.endswith('.weapon.' + suffix))
    assert hand_occupancy.resting_hands(paired) == 2
    # Catalog ordering can ready the Paired weapon first. Use the victim's
    # actual Stow/Draw intents to create the reviewed state, never edit grips.
    combat, table = victim_turn(combat, table, mid)
    for identity in hand_occupancy.weapon_grips(before, victim):
        label = before.action_catalog[identity].display_name.removesuffix(' attack')
        response, _ = S.play(table, mid, S.candidate(table, mid, 'Stow ' + label))
        assert response['status'] == 'COMMITTED'
    if free_count == 1:
        response, _ = S.play(table, mid, S.candidate(table, mid, 'Draw Qiang'))
        assert response['status'] == 'COMMITTED'
    S.to_thief(table, mid)
    before = cold(combat, mid)
    assert len(hand_occupancy.free_hands(before, before.state.actors[S.VICTIM])) == free_count
    assert paired.source_definition_id not in hand_occupancy.weapon_grips(before, before.state.actors[S.VICTIM])

    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'):
            wanted = S.offered([o['id'] for o in prompt['choice']['options']], 'reposition:' + key)
            assert wanted in {o['id'] for o in prompt['choice']['options']}
            return wanted
        if source.endswith('steal_location'):
            options = [o['id'] for o in prompt['choice']['options']]
            hands = [o for o in options if o.startswith('hand:')]
            if free_count == 1:
                assert options == ['carried'], 'Paired weapon cannot fit in the single free hand'
                return 'carried'
            assert len(hands) == 2
            assert all('2 empty hands' in o['label'] for o in prompt['choice']['options'] if o['id'] in hands)
            return hands[-1]  # Also exercise the explicitly chosen right-hand anchor.
        return None

    response, prompts = S.play(table, mid, S.candidate(table, mid, 'STEAL', target=S.VICTIM), answer=answer)
    assert response['status'] == 'COMMITTED'
    assert any(p['context']['reaction_source_id'].endswith('steal_location') for p in prompts)
    live = S.engine(combat, mid)
    assert S.checks_succeeded(live)
    engine = cold(combat, mid)
    assert live.state.model_dump(mode='json') == engine.state.model_dump(mode='json')
    victim = engine.state.actors[S.VICTIM]
    occupied = hand_occupancy.occupancy(engine, victim)
    assert not any(p.startswith('occupied:overflow:') for p in occupied)
    record = S.records(engine, key)[0][1]
    grips = hand_occupancy.weapon_grips(engine, victim)
    if free_count == 1:
        assert record['object_location'] == 'carried'
        assert paired.source_definition_id not in grips
        assert qiang in grips
        assert hand_occupancy.weapon_allowed(engine, victim, engine.action_catalog[qiang])
        combat, table = victim_turn(combat, table, mid)
        response, _ = S.play(table, mid, S.candidate(table, mid, 'Qiang', target=S.THIEF))
        assert response['status'] == 'COMMITTED'
        engine = cold(combat, mid)
        assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == S.VICTIM for e in engine.events)
    else:
        assert record['object_location'].startswith('hand:')
        assert grips == {paired.source_definition_id: 2}
        assert hand_occupancy.free_hands(engine, victim) == ()
        assert set(occupied) == set(hand_occupancy.hand_parts(engine, victim))
        assert all(owners == ('weapon:' + paired.source_definition_id,) for owners in occupied.values())
        assert record['object_location'].removeprefix('hand:') in occupied
