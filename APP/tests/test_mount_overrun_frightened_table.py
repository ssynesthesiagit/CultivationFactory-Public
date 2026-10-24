"""Mounted Overrun applies the shared willing-movement fear rule at the table boundary."""

import pytest

from combat.ext import mounts
from combat.gate5_service import CombatService
from combat.gate2_runtime_models import Position
from tests.hunt19_support import fight, send
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT
from tests.test_tabletop_hunt6 import on_hold
from tests.r10_fixup_support import fixed_dice


@pytest.mark.parametrize("frightened_member", ["rider", "mount", "none"])
def test_mount_overrun_respects_frightened_rider_and_mount_through_table_commit_reload(
        tmp_path, monkeypatch, frightened_member):
    combat, table, mid = fight(tmp_path, ["TAL_BEASTMASTERY_RUN_DOWN"], rider=True)
    staged = {}

    def stage(engine):
        rider = engine.state.actors[LEFT]
        mount = mounts.mount_of(engine, rider)
        target = engine.state.actors[RIGHT]
        source = engine.state.actors[ALLY]
        # The target lies along the mount's route and the visible fear source
        # lies beyond it, so the Overrun route would move both creatures closer.
        for actor, at in ((target, (6, 4)), (source, (10, 4))):
            start = actor.position
            actor.position = Position(x=at[0], y=at[1])
            engine._append_event("MOVEMENT_COMMITTED", "test:overrun-layout", actor_id=actor.entity_id,
                payload={"destination": actor.position.model_dump(mode="json"), "cost_ft": 0,
                         "forced": True, "path": [start.model_dump(mode="json"), actor.position.model_dump(mode="json")]})
        staged.update(rider=rider.entity_id, mount=mount.entity_id, target=target.entity_id, source=source.entity_id)
        frightened = {"rider": rider, "mount": mount}.get(frightened_member)
        if frightened is not None:
            engine._apply_condition(frightened, "condition:typed.frightened", "test:visible-fear",
                                    source.entity_id, expires_on="UNTIL_REMOVED")

    on_hold(monkeypatch, stage)
    from tests.test_tabletop_hunt6 import HOLD
    from tests.test_lock2_persistence import act
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    fixed_dice(monkeypatch, [19, 1, 19, 1])
    assert any(group["label"] == "Mount: Overrun (Action)" for group in table.state(mid)["menu"]["actions"]), \
        [(group["label"], [option.get("display_name") for option in group.get("options", [])])
         for group in table.state(mid)["menu"]["actions"]]
    sender = send(table, mid, "Mount: Overrun (Action)", target=RIGHT)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = sender([])
    assert result["status"] == "COMMITTED", result

    reloaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    loaded = reloaded.engine
    assert reloaded.mechanical.replay()["status"] == "PASS"
    rider, mount = loaded.state.actors[LEFT], mounts.mount_of(loaded, loaded.state.actors[LEFT])
    target = loaded.state.actors[RIGHT]
    assert mounts.rider_of(loaded, mount) is rider
    blocked = frightened_member != "none"
    assert (rider.position == Position(**before["actors"][LEFT]["position"])) is blocked
    assert (mount.position == Position(**before["actors"][staged["mount"]]["position"])) is blocked
    assert (rider.movement_remaining_ft == before["actors"][LEFT]["movement_remaining_ft"]) is blocked
    assert bool(rider.turn_flags.get("mount_overrun_target")) is not blocked
    assert reloaded.verify()["status"] == "PASS"
    moves = [e for e in loaded.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.sequence > before["event_sequence"] and e.actor_id in {LEFT, staged["mount"]}]
    assert bool(moves) is not blocked
    loaded._assert_invariants()
