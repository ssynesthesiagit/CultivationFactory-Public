"""Review 1F7: exact physical destruction and whole-volume Prison exits."""
import re

import pytest

from combat import carry, zones
from combat.ext.silken_whip import cloth_items
from combat.gate2_runtime_models import Position
from tests.h1_support import sheet
from tests.test_mgr_t14_iron_cloth import PRISON, CHOICE, play, use
from tests.test_mgr_t14_iron_cloth_travel_reactivation import (
    A, B, KEY, road, start, resume, infuse, command, infusion_at_genesis,
)
from tests.worker2_support import OWNER, ALLY, FOE, reload, settle, turn


def test_destroying_borrowed_bonded_robe_preserves_holders_identical_robe(tmp_path, monkeypatch):
    cold, jid = road(tmp_path, monkeypatch, steal=True)
    borrowed = B + '|' + KEY
    own = A + '|' + KEY
    mid, table = start(cold, jid)
    for _ in range(6):
        turn(table, mid, A)
        e = cold()._load_session(mid).engine
        candidate = next(c for c in e.legal_candidates() if c.target_ids == (B,) and
                         (a := e.action_catalog.get(c.source_definition_id)) is not None and
                         (a.parameters.get('typed') or {}).get('source') == 'TAL_SCOUNDREL_STEAL')
        settle(table, mid, candidate.candidate_id)
        e = cold()._load_session(mid).engine
        if any(i['object'] == borrowed for i in cloth_items(e, e.state.actors[A])):
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert any(i['object'] == borrowed for i in cloth_items(e, e.state.actors[A]))
    resume(cold, jid, mid, table)
    infuse(cold, jid, A, borrowed)
    command(cold, jid, A, 'iron_cloth_bind', {'item_key': KEY})
    mid, table = start(cold, jid, rounds=12)
    turn(table, mid, A)
    use(cold(), table, mid, 'Silken Whip: end infusion')
    use(cold(), table, mid, 'Silken Whip', choices={CHOICE + 'fabric': [own]})
    oid = 'object:iron_cloth:' + borrowed
    e = cold()._load_session(mid).engine
    assert e.state.objects[oid].owner_id == A
    assert e.state.objects[oid].component['inventory_identity'] == borrowed
    assert any(c.condition_id == 'condition:typed.iron_cloth_bond' and c.data['item_object'] == borrowed
               for c in e.state.actors[A].conditions.values())
    for _ in range(10):
        turn(table, mid, A)
        use(cold(), table, mid, 'Silken Whip: attack an object', target=oid,
            choices={CHOICE + 'object_damage_type': ['FORCE']})
        e = cold()._load_session(mid).engine
        if e.state.objects[oid].destroyed:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert e.state.objects[oid].destroyed
    # Both queries must distinguish B's destroyed robe from A's intact robe.
    item = next(i for i in carry.carrying_of(e, A)['items'] if i['key'] == KEY)
    assert carry.remaining_quantity(e, e.state.actors[A], item) == 1
    assert own in {i['object'] for i in cloth_items(e, e.state.actors[A])}
    assert borrowed not in {i['object'] for i in cloth_items(e, e.state.actors[A])}
    assert not any(c.condition_id == 'condition:typed.iron_cloth_bond' and c.data['item_object'] == borrowed
                   for actor in e.state.actors.values() for c in actor.conditions.values())
    assert any(c.condition_id == 'condition:typed.iron_cloth_broken' and c.data['item_object'] == borrowed
               for c in e.state.actors[B].conditions.values())
    turn(table, mid, A)
    use(cold(), table, mid, 'Silken Whip: end infusion')
    # The intact copy is available through the real table prompt after reload.
    prompts = use(cold(), table, mid, 'Silken Whip', choices={CHOICE + 'fabric': [own]})
    fabric = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'fabric')
    assert own in {o['id'] for o in fabric['choice']['options']}
    assert borrowed not in {o['id'] for o in fabric['choice']['options']}
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'
    state = resume(cold, jid, mid, table)
    assert not state['actors'][A]['bundle'].get('iron_cloth_bond')
    command(cold, jid, A, 'iron_cloth_end', {})
    infuse(cold, jid, A, own)
    e = infusion_at_genesis(cold, jid, A, own, bound=0)
    assert e.state.objects[oid].destroyed
    assert not e.state.objects['object:iron_cloth:' + own].destroyed


@pytest.mark.parametrize('size,altitude,center_z', [
    ('Large', 0, 0), ('Medium', 3, 3), ('Medium', 2, 3),
])
def test_successful_prison_save_offers_every_nearest_whole_volume_exit(tmp_path, size, altitude, center_z):
    foe = sheet([], cl=18, key='CHA', name='Mara')
    foe['identity']['size'] = size
    # For the elevated cases, block the immediate lateral exits at the right
    # corner. A vertical exit is five feet away; any planar exit is ten feet.
    blocked = [{'x': x, 'y': y} for x, y in ((7, 5), (7, 6), (7, 7), (5, 7), (6, 7))]
    arena = {'stable_id': 'battlefield:cloth_volume_exit', 'display_name': 'Cloth court',
             'width_squares': 12, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': ([{'terrain_type': 'BLOCKED',
                 'movement_cost': 0, 'cells': blocked}] if altitude else []),
             'roof_surfaces': ([{'id': 'support', 'height_ft': altitude * 5,
                 'cells': [{'x': x, 'y': y} for x in range(5, 7) for y in range(5, 7)]},
                 {'id': 'caster_support', 'height_ft': center_z * 5, 'cells': [{'x': 3, 'y': 6}]}]
                 if altitude else [])}
    positions = {OWNER: {'x': 3, 'y': 6, 'z': center_z}, ALLY: {'x': 2, 'y': 2},
                 FOE: {'x': 6 if altitude else 5, 'y': 6 if altitude else 5, 'z': altitude}}
    combat, table, mid = play(tmp_path, [PRISON], owner_dc=1, foe_sheet=foe,
                              positions=positions, battlefield=arena)
    before = reload(tmp_path, mid)
    origin = before.state.actors[FOE].position
    candidates = [c for c in before.legal_candidates()
                  if (a := before.action_catalog.get(c.source_definition_id)) is not None
                  and a.display_name == 'Silken Prison' and c.destination == Position(x=6, y=6, z=center_z)]
    assert candidates, 'The native service must offer the elevated cube placement'
    prompts = settle(table, mid, candidates[0].candidate_id)
    e = reload(tmp_path, mid)
    actor = e.state.actors[FOE]
    assert actor.size_category == size
    zone = next(z for z in e.state.zones.values() if z.active and
                z.trigger_profile.get('profile', {}).get('iron_cloth_prison'))
    assert zones.actor_inside_zone(e, actor, zone, position=origin)
    assert not zones.actor_inside_zone(e, actor, zone)
    assert not any(c.data.get('iron_cloth_prison') for c in actor.conditions.values())
    exits = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'prison_exit']
    assert len(exits) == 1
    offered = set()
    for option in exits[0]['choice']['options']:
        x, y, height = map(int, re.search(r'to (\d+), (\d+), height (\d+) feet', option['label']).groups())
        offered.add(Position(x=x, y=y, z=height // 5))
    # Independent exhaustive check of the nearby volume. These scenarios all
    # have a five-foot exit; no legal nearest tie may disappear from the menu.
    expected = {Position(x=x, y=y, z=z)
                for x in range(origin.x - 1, origin.x + 2)
                for y in range(origin.y - 1, origin.y + 2)
                for z in range(max(0, origin.z - 1), origin.z + 2)
                if e.grid.volume_legal(Position(x=x, y=y, z=z), footprint=e._footprint(actor),
                    occupied_cells=e._occupied_volumes_except(FOE))
                and not zones.actor_inside_zone(e, actor, zone, position=Position(x=x, y=y, z=z))}
    assert expected and offered == expected
    assert actor.position in expected
    if altitude:
        assert actor.position.z != origin.z
        assert any(p.z == (4 if altitude == 3 else 1) for p in offered)
    movements = [x for x in e.events if x.event_type == 'MOVEMENT_COMMITTED' and x.actor_id == FOE]
    assert movements[-1].payload['cost_ft'] == 0 and movements[-1].payload['footprint_step']
