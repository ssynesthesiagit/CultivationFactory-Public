"""World shelter traverses hostile Ash Terrain through committed service moves."""
import pytest
from combat import zones
from combat.typed_executor import condition_rules
from tests.auto_worker1_support import fight, act, reload, settle, turn, cell_send, LEFT, RIGHT, ALLY
from tests.test_a2_ash_service import WORLD, cast

ASHFALL = 'ASH_BASE_ASHFALL'


def independent_damage(bundle):
    if bundle['actor_template']['entity_id'] == RIGHT:
        # Keep this hostile source's Concentration through World's damage,
        # so subsequent turns still exercise the same terrain.
        bundle['actor_template']['saving_throws']['CON'] = 1000
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Ashfall':
                # Test-only sealed ability damage, independent of the actual
                # named terrain rule. Never alter a running engine or its hooks.
                action['parameters']['typed']['zone_spec']['triggers'] = [{
                    'id': 'independent_damage', 'name': 'Independent ability damage',
                    'on': ['enter', 'start'], 'who': 'hostile',
                    'effects': [{'type': 'damage', 'flat': 11,
                                 'damage_types': ['force'], 'applies_to': 'target'}]}]


def move_to(c, t, m, xy):
    def send(answers):
        state = t.state(m)
        menu = state['menu']
        candidate = next(row for row in c._load_session(m).engine.legal_candidates()
                         if row.kind.value == 'MOVE' and row.destination is not None
                         and (row.destination.x, row.destination.y) == xy
                         and row.metadata.get('movement_mode', 'walk') not in ('fly', 'teleport'))
        return t.act(m, candidate.candidate_id, menu['decision_id'], menu['state_version'],
                     state['last_sequence'], answers)
    return settle(send)


@pytest.mark.parametrize('sheltered', [True, False])
@pytest.mark.parametrize('enter', [False, True])
def test_world_traversal_immunity_keeps_independent_enter_start_damage(tmp_path, sheltered, enter):
    start = (3, 8) if enter else (3, 5)
    end = (3, 2)
    c, t, m = fight(tmp_path, [WORLD], cl=17, ally=[],
        spheres=['tianxia.sphere.ash'], right_talents=[ASHFALL],
        right_spheres=['tianxia.sphere.ash'], bundle_edit=independent_damage,
        positions={LEFT: {'x': 2, 'y': 6}, RIGHT: {'x': 6, 'y': 6},
                   ALLY: {'x': start[0], 'y': start[1]}})
    if sheltered:
        cast(c, t, m, WORLD)
    turn(t, m, RIGHT)
    settle(cell_send(t, m, 'Ashfall', (3, 4)))
    turn(t, m, ALLY)
    if enter:
        # Native entry damage ends this path at its checkpoint. Continue on a
        # fresh turn, rather than assume a damaged mover finishes the path.
        sequence = reload(c, m).state.event_sequence
        move_to(c, t, m, (3, 5))
        entered = reload(c, m)
        area = next(z for z in zones.typed_zones(entered) if z.owner_id == RIGHT)
        assert zones._inside(entered, entered.state.actors[ALLY], area)
        assert entered.state.actors[ALLY].current_hp == 989
        assert any(e.sequence > sequence and e.event_type == 'PASSIVE_TRIGGERED'
                   and e.target_ids == (ALLY,) and e.payload.get('moment') == 'enter'
                   and e.payload.get('zone_id') == area.zone_id for e in entered.events)
        turn(t, m, LEFT)
        turn(t, m, ALLY)
    before = reload(c, m)
    ally = before.state.actors[ALLY]
    terrain = next(z for z in zones.typed_zones(before) if z.owner_id == RIGHT)
    assert terrain.trigger_profile['terrain'] == ['ash terrain']
    assert zones._inside(before, ally, terrain)
    assert any(r.get('terrain_immunity', {}).get('owner') == 'any'
               for r in condition_rules(ally)) == sheltered
    assert ((3, 5) in zones.difficult_cells(before, ally)) == (not sheltered)
    assert ally.reaction_available
    hp = 978 if enter else 989
    assert ally.current_hp == hp
    end = (ally.position.x, ally.position.y - 3)
    sequence = before.state.event_sequence
    move_to(c, t, m, end)
    after = reload(c, m)  # Fresh CombatService, persisted state equality and mechanical replay.
    ally = after.state.actors[ALLY]
    terrain = after.state.zones[terrain.zone_id]
    assert (ally.position.x, ally.position.y) == end
    moves = [e for e in after.events if e.sequence > sequence
             and e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY]
    assert moves and sum((len(e.payload['path']) - 1) * after.grid.square_size_ft for e in moves) > 10
    traversal = [e for e in after.events if e.sequence > sequence
                 and e.event_type == 'PASSIVE_TRIGGERED' and e.target_ids == (ALLY,)
                 and e.payload.get('zone_id') == terrain.zone_id
                 and e.payload.get('moment') == 'move_through']
    saves = [e for e in after.events if e.sequence > sequence and e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == terrain.source_definition_id and e.actor_id == ALLY]
    denied = any(r.condition_id == 'condition:typed.reaction_denied' for r in ally.conditions.values())
    assert len(traversal) == (0 if sheltered else 1)
    assert len(saves) == (0 if sheltered else 1)
    assert denied == (not sheltered)
    assert (terrain.zone_id + ':move_through:' + ALLY in terrain.per_turn_triggered) == (not sheltered)
    damage = [e for e in after.events if e.sequence > sequence
              and e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (ALLY,)
              and e.source_definition_id == terrain.source_definition_id]
    assert not damage
    assert ally.current_hp == hp  # Shelter never suppresses independent Force damage.
    turn(t, m, LEFT)
    turn(t, m, ALLY)
    final = reload(c, m)
    assert final.state.actors[ALLY].current_hp == hp - 11
    assert any(e.event_type == 'PASSIVE_TRIGGERED' and e.target_ids == (ALLY,)
               and e.payload.get('zone_id') == terrain.zone_id and e.payload.get('moment') == 'start'
               for e in final.events if e.sequence > after.state.event_sequence)


@pytest.mark.parametrize('enter', [False, True])
def test_world_boundary_uses_landed_square_for_traversal(tmp_path, enter):
    # World has its real 60-foot radius: x=14 is inside, x=15 outside.
    # Hostile Ashfall spans both sides. Three landed steps cross the traversal
    # threshold exactly on the boundary step, never on an earlier step.
    start, end = ((17, 6), (14, 6)) if enter else ((12, 6), (15, 6))
    def open_yard(arena):
        arena['terrain_regions'] = []
    c, t, m = fight(tmp_path, [WORLD], cl=17, ally=[],
        spheres=['tianxia.sphere.ash'], right_talents=[ASHFALL],
        right_spheres=['tianxia.sphere.ash'], bundle_edit=independent_damage,
        arena_edit=open_yard,
        positions={LEFT: {'x': 2, 'y': 6}, RIGHT: {'x': 16, 'y': 3},
                   ALLY: {'x': start[0], 'y': start[1]}})
    settle(cell_send(t, m, 'World After the Fire', (2, 6)))
    turn(t, m, RIGHT)
    settle(cell_send(t, m, 'Ashfall', (15, 6)))
    turn(t, m, ALLY)
    before = reload(c, m)
    ally = before.state.actors[ALLY]
    world = next(z for z in zones.typed_zones(before) if z.owner_id == LEFT)
    terrain = next(z for z in zones.typed_zones(before) if z.owner_id == RIGHT)
    assert zones._inside(before, ally, world) == (not enter)
    assert zones._inside(before, ally, terrain)
    assert ally.current_hp == 989  # Independent start damage still applies.
    assert ally.reaction_available
    sequence = before.state.event_sequence
    move_to(c, t, m, end)
    after = reload(c, m)  # CombatService cold reload, exact state and mechanical replay.
    ally = after.state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == end
    assert zones._inside(after, ally, after.state.zones[world.zone_id]) == enter
    assert zones._inside(after, ally, after.state.zones[terrain.zone_id])
    assert any(r.get('terrain_immunity', {}).get('owner') == 'any'
               for r in condition_rules(ally)) == enter
    moves = [e for e in after.events if e.sequence > sequence
             and e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY]
    assert sum((len(e.payload['path']) - 1) * after.grid.square_size_ft for e in moves) == 15
    traversal = [e for e in after.events if e.sequence > sequence
                 and e.event_type == 'PASSIVE_TRIGGERED' and e.target_ids == (ALLY,)
                 and e.payload.get('zone_id') == terrain.zone_id
                 and e.payload.get('moment') == 'move_through']
    saves = [e for e in after.events if e.sequence > sequence and e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == terrain.source_definition_id and e.actor_id == ALLY]
    assert len(traversal) == (0 if enter else 1)
    assert len(saves) == (0 if enter else 1)
    assert any(r.condition_id == 'condition:typed.reaction_denied'
               for r in ally.conditions.values()) == (not enter)
    assert (terrain.zone_id + ':move_through:' + ALLY
            in after.state.zones[terrain.zone_id].per_turn_triggered) == (not enter)
    assert ally.current_hp == 989
    turn(t, m, LEFT)
    turn(t, m, ALLY)
    final = reload(c, m)
    assert final.state.actors[ALLY].current_hp == 978  # Shelter preserves independent damage.
