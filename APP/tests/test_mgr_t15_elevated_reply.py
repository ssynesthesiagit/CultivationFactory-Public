"""Full-coordinate Mirror-Water Reply choices survive table commit and replay."""
import pytest
from combat.gate2_runtime_models import Position
from tests.test_mgr_t15_close_mirror_water_reply import (
    ROOT, REPLY, OWNER, ALLY, FOE, native, cold, turn, candidate, settle, dice,
)

AUTHORITY_DEPENDENCIES = (REPLY, 'WATER_BASE_SHAPE_CURRENT', 'WATER_BASE_WATER_LASH',
                          'WATER_BASE_WATER_INITIATION', 'WATER_BASE_RETURN_THE_FLOW')


@pytest.mark.parametrize('height,goal', [(1, Position(x=6, y=5, z=0)),
                                        (3, Position(x=6, y=5, z=3))])
def test_elevated_attacker_uses_exact_real_menu_landing_after_reload(tmp_path, monkeypatch, height, goal):
    # Reuse only portable synthetic characters, then create a native saved match
    # with an elevated starting position (not an unjournalled state mutation).
    service, _, initial = native(tmp_path, walls=[])
    bundles = tuple(service._load_session(initial).engine.typed_bundle_documents)
    session = service.persistence.create_match(match_seed='REPLY-ELEVATED', typed_bundles=bundles,
        battlefield={'width_squares': 10, 'height_squares': 9, 'square_size_ft': 5,
                     'starting_positions': {}, 'terrain_regions': []},
        roster_setup={'primary_actor_ids': [OWNER, ALLY, FOE],
                      'team_by_actor': {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
                      'starting_positions': {OWNER: {'x': 3, 'y': 4}, ALLY: {'x': 3, 'y': 5},
                                             FOE: {'x': 4, 'y': 5, 'z': height}}})
    mid = session.match_id
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    from combat.ext.needle import cell_id
    seen = []
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if source == f'reaction:typed.{REPLY}:mode:0':
            return ''
        if source == 'choice:needle.subject_destination':
            options = {o['id'] for o in prompt['choice']['options']}
            assert cell_id(goal) in options
            # Same horizontal square, different heights are separate choices.
            assert cell_id(Position(x=6, y=5, z=height)) in options
            seen.append(prompt)
            return cell_id(goal)
        return None
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Water Lash', ALLY), choose)
    engine = cold(tmp_path, mid)[2]
    assert seen
    assert engine.state.actors[FOE].position == goal
    movement = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                and e.actor_id == FOE and e.source_definition_id == REPLY]
    assert movement
    assert Position.model_validate(movement[-1].payload['destination']) == goal
