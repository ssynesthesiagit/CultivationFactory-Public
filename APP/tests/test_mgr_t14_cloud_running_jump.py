"""Fast table regression for Feather's running-start long-jump distance."""
from combat.flight import horizontal_jump_feet
from tests.worker2_support import fixture, reload, settle, OWNER
from combat.ext.qi_subpaths_five import CLOUD


def test_native_running_start_triples_long_jump_and_offers_the_destination(tmp_path):
    combat, table, match_id = fixture(
        tmp_path, [], cl=3, owner_features=[CLOUD + 'light_as_a_feather'],
        owner_speed=60, ask=False,
    )
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    run = next(row for row in engine.legal_candidates()
               if row.kind.value == 'MOVE'
               and engine.grid.distance_ft(actor.position, row.destination) == 10
               and row.destination.z == actor.position.z)
    settle(table, match_id, run.candidate_id)

    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    assert horizontal_jump_feet(engine, actor) == actor.strength_score * 3
    jumps = [row for row in engine.legal_candidates()
             if row.kind.value == 'MOVE' and row.metadata.get('movement_mode') == 'jump']
    assert any(engine.grid.distance_ft(actor.position, row.destination)
               >= actor.strength_score * 3 for row in jumps)
