"""Review regressions through service intents, commits and cold replay."""
import pytest
from combat.ext import placed
from combat.gate5_service import CombatService
from tests.test_a2_trap_service import setup, pick, move, cold, AERIAL, ROAD
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn


@pytest.fixture
def platforms(monkeypatch):
    arenas = CombatService.factory_arenas
    def physical_arena(service, *args, **kwargs):
        service.tabletop_maps.save({'display_name': 'Review platform', 'width_squares': 14,
            'height_squares': 14, 'walls': [{'shape': 'rect', 'points': [[4, 7], [7, 8]],
                'blocks': 'sight_and_movement', 'height_ft': 15}],
            'starts': {'team1': [[3, 6]], 'team2': [[8, 7]]}})
        available = arenas(service, *args, **kwargs)
        return {**available, 'battlefield:factory_pillar_arena': available['battlefield:map.review-platform']}
    monkeypatch.setattr(CombatService, 'factory_arenas', physical_arena)


def prepare_road(combat, table, mid):
    from tests.test_hunt25_mantle_setup import send
    answers = []
    for _ in range(12):
        result = send(table, mid, answers)
        if result['status'] == 'COMMITTED':
            turn(table, mid, OWNER)
            return
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        options = p.get('choice', {}).get('options', [])
        ids = [o['id'] for o in options][-4:] if p['context']['reaction_source_id'].endswith('trap_scatter') else []
        answers.append({**p['context'], 'selection': 'USE', 'option_ids': ids})
    pytest.fail('Road preparation did not commit')


def raised_trap(combat, table, mid, *, second=None):
    answers = {'choice:needle.trap_raised_space': 'cell:4,7,3'}
    if second:
        answers['choice:needle.trap_second_trigger'] = second
    settle(table, mid, candidate(combat, mid, 'Set Trap on a raised surface').candidate_id, answers)


def test_raised_relocation_commits_platform_geometry_and_readable_height(tmp_path, platforms):
    combat, table, mid = setup(tmp_path, [AERIAL, ROAD], raised=True, height=3, hover=True, foe_x=8)
    prepare_road(combat, table, mid)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Aerial Rigging: on')
    raised_trap(combat, table, mid)
    e = cold(tmp_path, mid)
    zone = next(z for z in placed.of(e, 'trap') if z.center.z == 3)
    key = f'{zone.zone_id}@5,7,3'
    prompts = move(combat, table, mid, FOE, (7, 7, 3), picks={'choice:needle.trap_relocate': key})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('trap_relocate'))
    label = next(o['label'] for o in p['choice']['options'] if o['id'] == key)
    assert label.count('15 feet above ground') == 2
    e = cold(tmp_path, mid)
    moved = e.state.zones[zone.zone_id]
    assert (moved.center.x, moved.center.y, moved.center.z) == (5, 7, 3)
    assert [(p.x, p.y, p.z) for p in moved.affected_cells] == [(5, 7, 3)]
    assert moved.trigger_profile['footprint_height_ft'] == 35
    assert any('15 feet above ground' in str(v.payload.get('text', '')) for v in e.events if v.event_type == 'PASSIVE_TRIGGERED')


def test_raised_false_within_warns_places_child_and_reloads(tmp_path, platforms):
    combat, table, mid = setup(tmp_path, [AERIAL, ROAD, 'TAL_TRAP_FALSE_TRIGGER',
        'TAL_TRAP_TRAP_WITHIN_THE_TRAP'], raised=True, height=3, hover=True, foe_x=5)
    prepare_road(combat, table, mid)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Trap trigger: False Trigger')
    raised_trap(combat, table, mid, second='within')
    parent = next(z for z in placed.of(cold(tmp_path, mid), 'trap') if z.center.z == 3)
    prompts = move(combat, table, mid, FOE, (4, 7, 3), picks={
        'choice:needle.trap_within_cell': 'cell:5,7,3', 'choice:needle.trap_relocate': None})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('trap_within_cell'))
    assert '15 feet above ground' in next(o['label'] for o in p['choice']['options'] if o['id'] == 'cell:5,7,3')
    # Vertical neighbors use distinct IDs and occupied/unsupported spaces are excluded.
    ids = {o['id'] for o in p['choice']['options']}
    assert 'cell:4,7,3' not in ids and 'cell:5,7,2' not in ids
    e = cold(tmp_path, mid)
    assert placed.data(e.state.zones[parent.zone_id])['false_used']
    child = next(z for z in placed.of(e, 'trap') if placed.data(z).get('within_child'))
    assert (child.center.x, child.center.y, child.center.z) == (5, 7, 3)
    assert placed.data(child)['triggers'] == []
    assert not any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('mode', ['SUGGESTED', 'MANUAL_AI_BRIDGE'])
def test_off_turn_chain_player_can_choose_trap_affecting_ally(tmp_path, mode):
    combat, table, mid = setup(tmp_path, [AERIAL, ROAD, 'TAL_TRAP_CHAINED_MECHANISM', 'TAL_TRAP_FALSE_TRIGGER'], height=0, restore_focus=True)
    prepare_road(combat, table, mid)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Trap trigger: False Trigger')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(3, 7)).candidate_id)
    move(combat, table, mid, ALLY, (3, 7, 0))
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Prepare focus').candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    pick(combat, table, mid, 'Trap trigger: Chained Mechanism')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 6)).candidate_id)
    second = next(z for z in placed.of(cold(tmp_path, mid), 'trap') if (z.center.x, z.center.y) == (3, 7))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = move(combat, table, mid, FOE, (4, 6, 0), picks={'choice:needle.trap_chained_pick': second.zone_id})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('trap_chained_pick'))
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].display_name in next(o['label'] for o in p['choice']['options'] if o['id'] == second.zone_id)
    assert placed.data(e.state.zones[second.zone_id])['chain_turn'] == e.state.round_number * 1000 + e.state.current_slot_index
    # Empty Road still spares an aware ally; the player's chain choice is committed.
    assert not any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[ALLY].conditions.values())
