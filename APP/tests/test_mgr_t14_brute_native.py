"""Source-built Brute maneuvers through the native table and cold reload."""
import pytest
from tests.worker2_support import fixture, settle, candidate, reload, OWNER, ALLY, FOE
from tests.h1_support import sheet
from combat.factory_compiler import compile_character

SOURCE = 'BRUTE_BASE_BRUTE_MANEUVERS'


def brute(tmp_path, *, foe_size='Tiny'):
    doc = sheet([SOURCE], cl=6, key='STR', score=30)
    foe = sheet([], cl=6, score=1)
    foe['identity']['size'] = foe_size
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    return fixture(tmp_path, [], cl=6, owner_bundle=bundle, foe_sheet=foe,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 3, 'y': 5}})


@pytest.mark.parametrize('action', ['Overrun', 'Overrun (Bonus Action)'])
def test_overrun_uses_true_size_categories_and_grants_one_paid_crossing(tmp_path, action):
    combat, table, mid = brute(tmp_path)
    settle(table, mid, candidate(combat, mid, action, target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    roll = next(e for e in engine.events if e.event_type == 'CHECK_ROLLED'
                and e.payload.get('contest') == 'overrun')
    # Tiny and Medium both occupy one square; printed size still grants Advantage.
    assert roll.payload['actor']['mode'] == 'ADVANTAGE'
    assert roll.payload['target_skill'] == 'Athletics' and roll.payload['success']
    assert engine.state.actors[OWNER].action_available == (action != 'Overrun')
    assert engine.state.actors[OWNER].bonus_action_available == (action == 'Overrun')
    assert not any(c.kind.value == 'MOVE' and c.destination == engine.state.actors[FOE].position
                   for c in engine.legal_candidates())
    selected = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                    and c.destination.x == 3 and c.destination.y == 4)
    menu = table.state(mid)['menu']
    result = table.act(mid, selected.candidate_id, menu['decision_id'], menu['state_version'], 0,
        movement_path=[{'x': 3, 'y': 6}, {'x': 3, 'y': 5}, {'x': 3, 'y': 4}], movement_mode='walk', actor_id=OWNER)
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    move = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    assert move.payload['path'] == [{'x': 3, 'y': 6, 'z': 0}, {'x': 3, 'y': 5, 'z': 0}, {'x': 3, 'y': 4, 'z': 0}]
    assert move.payload['cost_ft'] == 15
    assert any(c.condition_id == 'condition:typed.named_creature_passage' and c.data['entered'] == 1
               for c in engine.state.actors[OWNER].conditions.values())
    from combat.ext.creature_passage import named_permission
    assert named_permission(engine, engine.state.actors[OWNER], engine.state.actors[FOE]) is None


def test_shove_aside_uses_disadvantage_and_the_selected_legal_space_in_reach(tmp_path):
    from combat.gate5_service import CombatServiceError
    combat, table, mid = brute(tmp_path, foe_size='Medium')
    try:
        settle(table, mid, candidate(combat, mid, 'Shove Aside', target=FOE).candidate_id,
               picks={'choice:needle.brute_contest_skill': 'Athletics', 'choice:needle.shove_aside': 'cell:4,6'})
    except CombatServiceError as exc:
        raise AssertionError(f'Shove Aside runtime rejection: {exc.diagnostic.details}') from exc
    engine = reload(tmp_path, mid)
    roll = next(e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.payload.get('contest') == 'shove')
    assert roll.payload['actor']['mode'] == 'DISADVANTAGE' and roll.payload['success']
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4, 6)
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], engine.state.actors[FOE]) <= 5
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE]
    assert moves and moves[-1].payload['forced'] and not moves[-1].payload.get('teleport')
