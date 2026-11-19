"""SPEEDREUSE2: a summon still waiting to be called is drawn as a light row until the read after it appears.

The engine's marker is the summon record's status "waiting" (combat/summons.py never_entered_play). Defeated,
dismissed and hidden creatures keep their full rows. Synthetic fight from the summon lifetime regressions.
"""
import json

import pytest

from combat import summons
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_summon_lifetime_saves_and_geometry import OWNER, PAPER, _call_summon, _fight

LIGHT = ("action_definitions", "action_availability", "features")


def _rows(state):
    return {row["entity_id"]: row for row in state["presentation"]["actors"]}


def _dragon(engine):
    return next(a for a in engine.state.actors.values() if a.summon and a.summon["group"] == "paper_dragon")


def test_waiting_summon_is_light_until_the_read_after_it_is_summoned(tmp_path):
    combat, table, mid = _fight(tmp_path, PAPER)
    dragon = _dragon(combat._load_session(mid).engine)
    assert summons.never_entered_play(dragon) and not dragon.active
    for state in (table.state(mid), table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,), compact_moves=True)):
        row = _rows(state)[dragon.entity_id]
        # Who and where it is stays (the roster, viewer binding and initiative read these), nothing it cannot use.
        assert row["summon_status"] == "waiting" and row["active"] is False
        assert row["owner_id"] == OWNER and row["team_id"] == _rows(state)[OWNER]["team_id"]
        assert row["display_name"] and row["position"] and row["hit_points"]["maximum"] > 0
        assert all(row[field] == [] for field in LIGHT)
        assert _rows(state)[OWNER]["action_definitions"]
    loaded = _call_summon(combat, table, mid, PAPER)
    appeared = _dragon(loaded.engine)
    assert appeared.summon["status"] == "present" and appeared.active
    row = _rows(table.state(mid))[appeared.entity_id]
    assert row["summon_status"] == "present"
    assert row["action_definitions"] and row["action_availability"]
    assert len(row["action_availability"]) == len(row["action_definitions"])
    # The same full row a fresh service builds from the saved fight.
    fresh = _rows(TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid))[appeared.entity_id]
    assert json.dumps(fresh) == json.dumps(row)


@pytest.mark.parametrize("status,active", [("destroyed", False), ("dismissed", False), ("present", True), (None, False)])
def test_defeated_dismissed_and_hidden_creatures_keep_their_full_rows(tmp_path, status, active):
    combat, table, mid = _fight(tmp_path, PAPER)
    session = combat._load_session(mid)
    engine = session.engine
    full = combat.presentation(mid, feed=False, session=combat._load_session(mid))
    owner_row = next(row for row in full["actors"] if row["entity_id"] == OWNER)
    dragon = _dragon(engine)
    if status is None:
        # A defeated primary fighter has no summon record: never a placeholder.
        target = engine.state.actors[OWNER]
        target.active, target.current_hp = False, 0
    else:
        target = dragon
        target.summon = {**target.summon, "status": status}
        target.active = active
        if status == "present":
            # A hidden creature is present and simply unseen; the presentation hides it, not this shortcut.
            from combat.gate2_runtime_models import ConditionInstance
            target.conditions["hidden-test"] = ConditionInstance(
                instance_id="hidden-test", condition_id="condition:core.invisible", source_definition_id="test",
                source_actor_id=target.entity_id, target_id=target.entity_id, applied_sequence=0,
                expires_on="UNTIL_REMOVED")
    assert not summons.never_entered_play(target)
    rows = {row["entity_id"]: row for row in combat.presentation(mid, feed=False, session=session)["actors"]}
    row = rows[target.entity_id]
    # Every action and reaction it owns is still described, as for any creature on the table.
    assert len(row["action_definitions"]) >= len(set(target.action_ids) | set(target.reaction_ids)) > 0
    assert len(row["action_availability"]) == len(row["action_definitions"])
    if status is None:  # the defeated fighter keeps the feature rows it had before
        assert row["features"] == owner_row["features"]
