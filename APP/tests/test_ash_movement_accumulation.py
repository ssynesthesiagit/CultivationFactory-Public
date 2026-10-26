"""Saved-table regression for movement split across multiple accepted moves."""

from combat.gate5_service import CombatService
from tests.r1i_service_support import fixture, OWNER, FOE, SECOND
from tests.h1_support import ROOT


def _turn(table, match_id, commit, actor_id):
    for _ in range(30):
        if table.state(match_id)["menu"]["actor_id"] == actor_id:
            return
        commit(table.state(match_id)["menu"]["end_turn"])
    raise AssertionError("actor turn unavailable")


def _move(table, match_id, commit, x, y):
    move = next(row for row in table.state(match_id)["menu"]["moves"]
                if row["destination"] == {"x": x, "y": y})
    commit(move["candidate_id"])


def test_ash_distance_accumulates_across_saved_movement_events(tmp_path):
    combat, table, match_id, _send, commit = fixture(
        tmp_path, ["ASH_BASE_ASHFALL"],
        positions={OWNER: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 4}, SECOND: {"x": 17, "y": 12}},
        seed="ASH-SPLIT-MOVEMENT-REGRESSION",
    )
    ashfall = next(option for group in table.state(match_id)["menu"]["actions"]
                   if group["label"] == "Ashfall" for option in group["options"]
                   if option["destination"] == {"x": 4, "y": 6})
    commit(ashfall["candidate_id"])
    _turn(table, match_id, commit, FOE)

    for y in (5, 6, 7):
        _move(table, match_id, commit, 4, y)

    engine = combat._load_session(match_id).engine
    triggers = [event for event in engine.events
                if event.event_type == "PASSIVE_TRIGGERED"
                and event.payload.get("moment") == "move_through"
                and FOE in event.target_ids]
    assert triggers, "three committed 5-foot moves through Ash Terrain exceed its 10-foot threshold"

    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert fresh.engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
