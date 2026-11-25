"""Review r4: object lifecycle and exact area identities through persisted intents."""
import pytest
from combat import carry, armour
from combat.ext import hand_occupancy, scoundrel_riders, shield_wielding
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import auto11_service_support as S
from tests.cw2_service_support import add_action
from tests.test_a2_scoundrel_service import cold, TALENTS, reply
from tests.test_a2_scoundrel_fix_service import victim_turn
from tests.test_a2_scoundrel_shield_service import SHIELD_KEY, SHIELD, STEAL, ac


def fresh(combat, mid):
    service = CombatService(combat.source_root, combat.userdata_root)
    assert service.replay(mid)['status'] == 'PASS'
    return service, TabletopService(service, combat.userdata_root)


@pytest.mark.parametrize('kit,key,name', [(SHIELD, SHIELD_KEY, 'Shield'),
                                         (S.PACK, S.PACK_KEY, "Explorer's Pack"),
                                         (S.SWORD, 'tianxia.mortal.weapon.qiang', 'Qiang')])
def test_relocation_normal_drop_theft_and_pickup_have_one_location(tmp_path, kit, key, name):
    combat, table, mid = S.fight(tmp_path, STEAL, victim_kit=kit)
    before = cold(combat, mid)
    original_weight = carry.weight(before, before.state.actors[S.VICTIM])
    item_weight = float(carry.item_of(carry.carrying_of(before, S.VICTIM), key=key)['weight_lb'])
    initial_ac = ac(before)
    def relocate(prompt):
        source = prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'): return 'reposition:' + key
        if source.endswith('steal_location'):
            return next(o['id'] for o in prompt['choice']['options'] if o['id'].startswith('hand:'))
        return None
    result, _ = S.play(table, mid, S.candidate(table, mid, 'STEAL', S.VICTIM), answer=relocate)
    assert result['status'] == 'COMMITTED'
    assert len(S.records(cold(combat, mid), key)) == 1
    combat, table = victim_turn(combat, table, mid)
    result, _ = S.play(table, mid, S.candidate(table, mid, 'Drop ' + name))
    assert result['status'] == 'COMMITTED'
    committed = S.engine(combat, mid)
    reloaded = cold(combat, mid)
    assert committed.state.model_dump(mode='json') == reloaded.state.model_dump(mode='json')
    for engine in (committed, reloaded):
        victim = engine.state.actors[S.VICTIM]
        records = S.records(engine, key)
        assert len(records) == 1, records
        assert records[0][1]['dropped_at'] == {'x': 4, 'y': 6}
        assert not records[0][1].get('held_by') and not records[0][1].get('object_location')
        assert not carry.holds(engine, victim, key)
        assert not scoundrel_riders.possessions(engine, victim)
        assert hand_occupancy.occupancy(engine, victim) == {}
        assert carry.weight(engine, victim) == original_weight - item_weight
        if key == SHIELD_KEY:
            assert not shield_wielding.shield_in_hand(engine, victim)
            assert not shield_wielding.wielding_a_shield(engine, victim)
            assert armour.shield_bonus_earning(engine, victim) == 0
            assert ac(engine) == initial_ac - 2
    # Another real Steal cannot claim an object that is already on the floor.
    combat, table = fresh(combat, mid)
    S.to_thief(table, mid)
    result, prompts = S.play(table, mid, S.candidate(table, mid, 'STEAL', S.VICTIM), answer=None)
    assert result['status'] == 'COMMITTED'
    for prompt in prompts:
        if prompt['context']['reaction_source_id'].endswith('steal_objects'):
            assert all(not o['id'].startswith(('take:', 'fall:', 'reposition:'))
                       for o in prompt['choice']['options'])
    assert len(S.records(cold(combat, mid), key)) == 1
    combat, table = victim_turn(combat, table, mid)
    result, _ = S.play(table, mid, S.candidate(table, mid, 'Pick up ' + name))
    assert result['status'] == 'COMMITTED'
    committed = S.engine(combat, mid)
    reloaded = cold(combat, mid)
    assert committed.state.model_dump(mode='json') == reloaded.state.model_dump(mode='json')
    for engine in (committed, reloaded):
        victim = engine.state.actors[S.VICTIM]
        assert not S.records(engine, key)  # original inventory is once again authoritative
        assert carry.holds(engine, victim, key)
        assert [p['object'] for p in scoundrel_riders.possessions(engine, victim)] == [scoundrel_riders.object_id(S.VICTIM, key)]
        assert carry.weight(engine, victim) == original_weight
        if key == SHIELD_KEY:
            assert sum(len(v) for v in hand_occupancy.occupancy(engine, victim).values()) == 1
            assert shield_wielding.shield_in_hand(engine, victim)
            assert armour.shield_bonus_earning(engine, victim) == 2
            assert ac(engine) == initial_ac


def two_packs(tmp_path):
    """Sealed setup rows invoke production transfer effects, then shipped area row."""
    ids = [S.THIEF, S.VICTIM]
    bundles = [compile_character(S._doc(TALENTS if who == S.THIEF else [], kit=S.PACK,
               name='Thief' if who == S.THIEF else 'Victim'), actor_id=who,
               reaction_plan={'ask': True} if who == S.THIEF else None) for who in ids]
    add_action(bundles[0], 'Prepare two packs', [
        {'type': 'transfer_object', 'from': 'victim', 'as': 'reposition', 'item': S.PACK_KEY,
         'object': scoundrel_riders.object_id(S.VICTIM, S.PACK_KEY)},
        {'type': 'transfer_object', 'from': 'thief', 'as': 'plant', 'object_locations': True,
         'item': S.PACK_KEY, 'object': scoundrel_riders.object_id(S.THIEF, S.PACK_KEY)}])
    combat = CombatService(S.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids, {S.THIEF:'team:a', S.VICTIM:'team:b'},
        {S.THIEF:{'x':3,'y':6}, S.VICTIM:{'x':4,'y':6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [S.THIEF], [S.VICTIM], control_modes={who:'MANUAL' for who in ids},
        match_seed='A2SCOUNDRE-area-B', display_name='Two physical packs', maximum_rounds=10)['match_id']
    S.to_thief(table, mid)
    return combat, table, mid


@pytest.mark.parametrize('result,both_held', [('held', False), ('held', True), ('drop', False)])
def test_area_exact_held_copy_and_duplicate_labels_survive_reload(tmp_path, result, both_held):
    combat, table, mid = two_packs(tmp_path)
    own = scoundrel_riders.object_id(S.VICTIM, S.PACK_KEY)
    received = scoundrel_riders.object_id(S.THIEF, S.PACK_KEY)
    calls = 0
    def placement(prompt):
        nonlocal calls
        if prompt['context']['reaction_source_id'].endswith('steal_location'):
            calls += 1
            if calls == 1 and not both_held: return 'carried'
            return next(o['id'] for o in prompt['choice']['options'] if o['id'].startswith('hand:'))
        return None
    response, _ = S.play(table, mid, S.candidate(table, mid, 'Prepare two packs', S.VICTIM), answer=placement)
    assert response['status'] == 'COMMITTED' and calls == 2
    combat, table = fresh(combat, mid)
    before = cold(combat, mid)
    assert {p['object'] for p in scoundrel_riders.possessions(before, before.state.actors[S.VICTIM])} == {own, received}
    before_own = next(data for who,data in S.records(before, S.PACK_KEY) if data['object_id'] == own)
    def choose(prompt):
        if prompt['context']['reaction_source_id'] == 'choice:needle.wrong_place_object': return received
        return reply(result)(prompt)
    response, prompts = S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=choose)
    assert response['status'] == 'COMMITTED'
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.wrong_place_object')
    options = menu['choice']['options']
    assert {o['id'] for o in options} == ({received} if result == 'held' and not both_held else {own, received})
    if len(options) == 2:
        assert len({o['label'] for o in options}) == 2
        assert any('Thief' in o['label'] for o in options)
        assert any('Victim' in o['label'] for o in options)
        assert all('actor:' not in o['label'] for o in options)
    committed = S.engine(combat, mid)
    reloaded = cold(combat, mid)
    assert committed.state.model_dump(mode='json') == reloaded.state.model_dump(mode='json')
    for engine in (committed, reloaded):
        rows = {data['object_id']:data for who,data in S.records(engine, S.PACK_KEY)}
        assert len(rows) == 2 and rows[own] == before_own
        assert rows[received]['dropped_at'] == {'x':6,'y':6}
        assert {p['object'] for p in scoundrel_riders.possessions(engine, engine.state.actors[S.VICTIM])} == {own}
