"""Review regressions through table session execution, journal commit and cold reload."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import hand_occupancy
from tests import auto11_service_support as S
from tests.test_a2_scoundrel_service import cold, TALENTS, reply

KEY = 'tianxia.mortal.weapon.qiang'
STEAL = ['TAL_SCOUNDREL_STEAL', 'TAL_SCOUNDREL_DIRTY_TRICK']


def victim_turn(combat, table, mid):
    # Continue through a genuinely new service/session after the relocation.
    fresh = CombatService(combat.source_root, combat.userdata_root)
    assert fresh.replay(mid)['status'] == 'PASS'
    table = TabletopService(fresh, combat.userdata_root)
    for _ in range(16):
        if table.state(mid)['menu']['actor_id'] == S.VICTIM:
            return fresh, table
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    pytest.fail('Victim turn never arrived')


def relocate(table, mid, location):
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'):
            return 'reposition:' + KEY
        if source.endswith('steal_location'):
            if location == 'hand':
                return next(o['id'] for o in prompt['choice']['options'] if o['id'].startswith('hand:'))
            return location
        return None
    response, _ = S.play(table, mid, S.candidate(table, mid, 'STEAL', target=S.VICTIM), answer=answer)
    assert response['status'] == 'COMMITTED'


def test_carried_owner_weapon_can_draw_and_attack_after_cold_reload(tmp_path):
    combat, table, mid = S.fight(tmp_path, STEAL, victim_kit=S.SWORD)
    relocate(table, mid, 'carried')
    combat, table = victim_turn(combat, table, mid)
    assert not any(g['label'].startswith('Qiang') for g in table.state(mid)['menu']['actions'])
    response, _ = S.play(table, mid, S.candidate(table, mid, 'Draw Qiang'))
    assert response['status'] == 'COMMITTED'
    engine = cold(combat, mid)
    assert hand_occupancy.weapon_grips(engine, engine.state.actors[S.VICTIM])
    response, _ = S.play(table, mid, S.candidate(table, mid, 'Qiang', target=S.THIEF))
    assert response['status'] == 'COMMITTED'
    engine = cold(combat, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == S.VICTIM for e in engine.events)


def test_owner_weapon_in_hand_is_one_grip_and_can_stow_after_cold_reload(tmp_path):
    combat, table, mid = S.fight(tmp_path, STEAL, victim_kit=S.SWORD)
    relocate(table, mid, 'hand')
    engine = cold(combat, mid)
    victim = engine.state.actors[S.VICTIM]
    assert len(hand_occupancy.free_hands(engine, victim)) == 1
    record = S.records(engine, KEY)[0][1]
    occupied = hand_occupancy.occupancy(engine, victim)
    assert record['object_location'].removeprefix('hand:') in occupied
    assert len([who for owners in occupied.values() for who in owners]) == 1
    combat, table = victim_turn(combat, table, mid)
    response, _ = S.play(table, mid, S.candidate(table, mid, 'Qiang', target=S.THIEF))
    assert response['status'] == 'COMMITTED'
    response, _ = S.play(table, mid, S.candidate(table, mid, 'Stow Qiang'))
    assert response['status'] == 'COMMITTED'
    engine = cold(combat, mid)
    assert len(hand_occupancy.free_hands(engine, engine.state.actors[S.VICTIM])) == 2
    assert not hand_occupancy.weapon_grips(engine, engine.state.actors[S.VICTIM])


def test_large_thief_can_place_object_in_visible_single_cell_gap(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.targeting import line_of_effect
    combat, table, mid = S.fight(tmp_path, TALENTS, thief_size='Large', seed='A2SCOUNDRE-area-B')
    before = cold(combat, mid)
    actor = before.state.actors[S.THIEF]
    assert actor.transformed_size_category == 'Large'
    assert before._footprint(actor).width_cells == 2
    occupied = {cell for creature in before.state.actors.values() if creature.active
                for cell in before.grid.footprint_cells(creature.position, before._footprint(creature))}
    # A real map square where the small object fits but a Large body does not.
    gaps = [Position(x=x,y=y) for y in range(before.grid.height) for x in range(before.grid.width)
            if before.grid.placement_legal((x,y), occupied_cells=occupied)
            and not before.grid.placement_legal((x,y), footprint=before._footprint(actor))
            and before.grid.distance_ft(actor.position, Position(x=x,y=y)) <= 30
            and before._line_of_sight_actor_to_cell(actor, Position(x=x,y=y))
            and line_of_effect(before, actor, destination=Position(x=x,y=y))]
    assert gaps
    gap = gaps[0]
    def answer(prompt):
        if prompt['context']['reaction_source_id'].endswith('steal_spot'):
            wanted = f'cell:{gap.x},{gap.y}'
            assert wanted in {o['id'] for o in prompt['choice']['options']}
            return wanted
        return reply('drop')(prompt)
    response, _ = S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=answer)
    assert response['status'] == 'COMMITTED'
    records = S.records(cold(combat, mid), S.PACK_KEY)
    assert len(records) == 1 and records[0][1]['dropped_at'] == gap.model_dump(mode='json')


@pytest.mark.parametrize('location', ['carried', 'hand'])
def test_planting_location_retains_identity_weight_and_actual_hands(tmp_path, location):
    from combat import carry
    combat, table, mid = S.fight(tmp_path, STEAL)
    before = cold(combat, mid)
    weight = carry.weight(before, before.state.actors[S.VICTIM])
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'): return 'plant:' + S.PACK_KEY
        if source.endswith('steal_tiny'): return 'yes'
        if source.endswith('steal_location'):
            return 'carried' if location == 'carried' else next(o['id'] for o in prompt['choice']['options'] if o['id'].startswith('hand:'))
        return None
    response, prompts = S.play(table, mid, S.candidate(table, mid, 'STEAL', target=S.VICTIM), answer=answer)
    assert response['status'] == 'COMMITTED'
    assert any(p['context']['reaction_source_id'].endswith('steal_location') for p in prompts)
    engine = cold(combat, mid)
    records = S.records(engine, S.PACK_KEY)
    assert len(records) == 1
    owner, data = records[0]
    assert owner == S.THIEF and data['owner'] == S.THIEF and data['held_by'] == S.VICTIM
    assert data['object_location'] == ('carried' if location == 'carried' else 'hand:' + data['hand'])
    assert len(hand_occupancy.free_hands(engine, engine.state.actors[S.VICTIM])) == (2 if location == 'carried' else 1)
    assert carry.weight(engine, engine.state.actors[S.VICTIM]) > weight
    assert len([p for p in S.scoundrel_riders.possessions(engine, engine.state.actors[S.VICTIM]) if p['key'] == S.PACK_KEY]) == 2
