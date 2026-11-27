"""Chain Counter reads usable Swim movement on the combat map, not journey regions."""
import pytest

from combat import flight
from combat.gate2_runtime_models import Position
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, turn
from tests.test_auto98_chains_counter import COUNTER, LOOSE_SAVE_DC, attack, cell, counter_prompts
from tests.worker2_support import settle


@pytest.mark.parametrize('water_x,spent_ft,swim_left,can_withhold', [
    (4, 10, 20, True),
    (4, 30, 0, False),
    (5, 10, 20, True),
    (6, 10, 20, False),
], ids=['swimming', 'exhausted', 'adjacent-water', 'distant-water'])
def test_chain_counter_uses_swim_only_when_a_first_step_can_spend_it(
        tmp_path, monkeypatch, water_x, spent_ft, swim_left, can_withhold):
    monkeypatch.setenv('CF_EMBED_MENU', '0')

    def swimmer(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template'].update(speed_ft=10, swim_speed_ft=30)

    def combat_water(arena):
        rows = range(8) if water_x == 4 else [6]
        arena['terrain_regions'] = [{'region_id': 'water', 'terrain_type': 'WATER', 'movement_cost': 1,
                                    'cells': [{'x': water_x, 'y': y} for y in rows]}]

    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC,
        bundle_edit=swimmer, arena_edit=combat_water,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6 - spent_ft // 5}})
    turn(table, mid, RIGHT)
    move = next(row for row in table.state(mid)['menu']['moves']
                if cell(row['destination']) == (4, 6, 0))
    assert int(move['cost_ft']) == spent_ft
    # Decline the counter on entering reach; use it on the ensuing melee attack.
    settle(table, mid, move['candidate_id'])

    before = reload(combat, mid)
    target = before.state.actors[RIGHT]
    assert target.position == Position(x=4, y=6)
    assert (target.speed_ft, target.swim_speed_ft) == (10, 30)
    assert flight.remaining(before, target, 'walk') == 0
    assert flight.remaining(before, target, 'swim') == swim_left

    (prompt,) = counter_prompts(attack(table, mid, 'withhold'))
    assert {o['id'] for o in prompt['choice']['options']} == (
        {'pull', 'withhold'} if can_withhold else {'pull'})
    after = reload(combat, mid)
    target = after.state.actors[RIGHT]
    reductions = [e.payload['distance_ft'] for e in after.events if e.event_type == 'MOVEMENT_GRANTED'
                  and e.source_definition_id == COUNTER and e.actor_id == RIGHT]
    assert reductions == ([-5] if can_withhold else [])
    assert flight.remaining(after, target, 'swim') == swim_left - (5 if can_withhold else 0)
    if can_withhold:
        assert any(e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == COUNTER
                   and e.payload.get('log') == f'Chain Counter: {target.display_name} has 15 feet of movement left this turn.'
                   for e in after.events)
