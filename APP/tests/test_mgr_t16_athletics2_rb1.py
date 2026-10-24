"""Both Athletics lanes remain compiled together through table commits."""
import pytest
from combat.breath_clock import CLOCK
from combat.ext.athletics_grip_lungs import catch_faces
from combat.roof_movement import ClimbSurface
from tests.test_mgr_t16_athletics2_wall import game, action, move
from tests.worker2_support import OWNER, reload


def test_wall_close_quarters_grip_and_lungs_coexist_after_reload(tmp_path):
    talents = (
        'TAL_ATHLETICS_WALL_STUNT',
        'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING',
        'TAL_ATHLETICS_SURE_GRIP',
        'TAL_ATHLETICS_STRONG_LUNGS',
        'TAL_ATHLETICS_SHARK_SWIM',
    )
    combat, table, mid = game(tmp_path, talents=talents)
    engine = combat._load_session(mid).engine
    rows = engine.typed_passive_rows[OWNER]
    for block, kind in (
        ('athletics', 'wall_stunt'),
        ('athletics', 'close_quarters'),
        ('athletics_grip_lungs', 'sure_grip'),
        ('athletics_grip_lungs', 'strong_lungs'),
    ):
        assert sum(r.get('block') == block and r.get('kind') == kind for r in rows) == 1

    action(table, mid, 'hold your breath')
    action(table, mid, 'run up or along a wall')
    assert move(table, mid, (3, 3, 1)).movement_cost_ft == 10
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position.z == 1
    # Main's Sure Grip queries this lane's Wall Stunt surfaces during a fall.
    # Without an authored difficulty, they offer no catch rather than crashing.
    assert catch_faces(engine, actor) == ()
    assert any(c.condition_id == CLOCK and c.data['remaining_seconds'] > 0
               for c in actor.conditions.values())
    assert {r.get('kind') for r in engine.typed_passive_rows[OWNER]} >= {
        'wall_stunt', 'close_quarters', 'sure_grip', 'strong_lungs', 'shark_swim',
    }


@pytest.mark.parametrize('dc', [None, 0, 12])
def test_provider_climb_surfaces_accept_only_authored_catch_difficulty(dc):
    surface = ClimbSurface('test-wall', 15, frozenset({(4, 3)}), catch_dc=dc)
    assert surface.catch_dc == dc


@pytest.mark.parametrize('dc', [-1, True, 2.5, '12'])
def test_provider_climb_surfaces_reject_invalid_catch_difficulty(dc):
    with pytest.raises(ValueError, match='catch DC'):
        ClimbSurface('test-wall', 15, frozenset({(4, 3)}), catch_dc=dc)


def test_paid_scale_foe_entry_does_not_repeat_close_quarters_contest(tmp_path):
    from combat.creature_attachment import carrier
    from tests.test_mgr_t16_athletics2_scale import game as scale_game, climb
    from tests.worker2_support import FOE

    combat, table, mid = scale_game(tmp_path, trained=True)
    climb(table, mid)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert carrier(engine, actor) is engine.state.actors[FOE]
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED']
    assert len(checks) == 1
    assert checks[0].source_definition_id.endswith('.scale_foe')
    assert actor.movement_remaining_ft == actor.speed_ft - 5
    assert not any(c.condition_id == 'condition:typed.close_quarters_shared'
                   for c in actor.conditions.values())
