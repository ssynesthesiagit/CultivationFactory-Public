"""Void Step recovery may land beyond the range of its original destination."""
from combat.ext import void_touched_cultivator as void
from combat.gate2_runtime_models import Position
from tests.void_family_support import acquired, bundle, step_action, step_context
from tests.worker2_support import ALLY, FOE, OWNER, fixture, reload


def test_recovery_reaches_legal_space_beyond_original_range(acquired, tmp_path, monkeypatch):
    service, project = acquired
    _, _, mid = fixture(
        tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
        positions={OWNER: {"x": 2, "y": 6}, ALLY: {"x": 8, "y": 6}, FOE: {"x": 15, "y": 12}},
        # Recovery geometry is isolated from the owner-editable arena pillars.
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]),
        seed="VOID-STEP-RANGE-EDGE",
    )
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    landing = Position(x=9, y=6)
    grid_type = type(engine.grid)
    original = grid_type.placement_legal

    def only_landing(grid, position, **kwargs):
        return position == landing and original(grid, position, **kwargs)

    monkeypatch.setattr(grid_type, "placement_legal", only_landing)
    assert void.void_step_recovery(step_context(engine, actor, action), actor, actor.position,
                                   Position(x=8, y=6)) == landing
