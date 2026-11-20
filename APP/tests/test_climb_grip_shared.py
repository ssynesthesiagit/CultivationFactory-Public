"""Walking-derived climbing grants at the real table and retained bundle boundary."""

import pytest

from combat import movement_speeds, roof_movement
from tests import test_walkable_roofs
from tests.h1_support import sheet
from tests.test_roof_movement import owned_climber
from tests.test_walkable_roofs import OWNER, cold, roof_fight, route

MONKEY = "TAL_MONKEY_STYLE_MONKEY_GRIP"
SPIDER = "TAL_ATHLETICS_SPIDER_S_TOUCH"


def test_monkey_grip_owned_row_grants_half_live_climb_speed_and_moves(tmp_path):
    combat, table, mid = roof_fight(tmp_path, owner_talents=(MONKEY,), owner_start=(3, 2))
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    rows = engine.typed_passive_rows[OWNER]
    assert any(r.get("feature_id") == MONKEY and r.get("denominator") == 2 for r in rows)
    assert roof_movement.profile(engine, actor).speed_ft == 15
    assert not roof_movement.profile(engine, actor).ceiling
    candidate = route(combat, table, mid, [(3, 2, 0), (3, 2, 1)], mode="climb")
    assert candidate.movement_cost_ft == 5
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position.z == 1
    assert roof_movement.profile(session.engine, actor).speed_ft == 15


@pytest.mark.parametrize("talent,native,expected", [(MONKEY, 25, 25), (SPIDER, 0, 30)])
def test_owned_grants_move_and_replay_with_independent_speed(tmp_path, monkeypatch, talent, native, expected):
    def character(talents, **kwargs):
        document = sheet(talents, **kwargs)
        if talent in talents:
            document["ability_scores_and_statistics"]["speed"]["climbing_ft"] = native
        return document

    monkeypatch.setattr(test_walkable_roofs, "sheet", character)
    combat, table, mid = roof_fight(tmp_path, owner_talents=(talent,), owner_start=(3, 2))
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert roof_movement.profile(engine, actor).speed_ft == expected
    assert not roof_movement.profile(engine, actor).ceiling
    assert not roof_movement.profile(engine, actor).physical_disabled
    before = actor.movement_remaining_ft
    candidate = route(combat, table, mid, [(3, 2, 0), (3, 2, 1)], mode="climb")
    assert candidate.movement_cost_ft == 5
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position.z == 1 and actor.movement_remaining_ft == before - 5
    assert roof_movement.profile(session.engine, actor).speed_ft == expected


def test_monkey_grip_uses_half_speed_not_full():
    engine, actor = owned_climber([MONKEY])
    assert roof_movement.profile(engine, actor).speed_ft == 15
    actor.speed_ft = 35
    assert roof_movement.profile(engine, actor).speed_ft == 17
    actor.climb_speed_ft = 25
    assert roof_movement.profile(engine, actor).speed_ft == 25
    engine.typed_passive_rows[actor.entity_id] = []
    actor.climb_speed_ft = 0
    assert roof_movement.profile(engine, actor).speed_ft == 0


def test_spider_speed_requires_retained_trait(monkeypatch):
    from combat import typed_reactions
    engine, actor = owned_climber([SPIDER])
    assert roof_movement.profile(engine, actor).speed_ft == 30
    assert not roof_movement.profile(engine, actor).ceiling
    monkeypatch.setattr(typed_reactions, "rules", lambda: {"features": {}})
    assert roof_movement.profile(engine, actor).speed_ft == 30
    engine.typed_passive_rows[actor.entity_id] = [
        row for row in engine.typed_passive_rows[actor.entity_id]
        if row.get("kind") != "movement_speed_grant"
    ]
    assert roof_movement.profile(engine, actor).speed_ft == 0


def test_fraction_scales_only_non_bonus_walking_speed(monkeypatch):
    engine, actor = owned_climber([MONKEY])
    actor.speed_ft = 25
    # Isolate the already-restricted live +10 all-Speeds contribution.
    monkeypatch.setattr(movement_speeds, "walking_bonus", lambda engine, actor: 10)
    monkeypatch.setattr(engine, "_effective_speed", lambda actor: 35)
    monkeypatch.setattr(movement_speeds, "all_bonus", lambda engine, actor: 10)
    grant = movement_speeds.land_speed_grant(engine, actor, "climb", 1, 2)
    assert grant == {"climb_speed_ft": 22, "climb_speed_bonus_included_ft": 10,
                     "climb_speed_uses_walk_bonus": 1}
    assert movement_speeds.resolve(engine, actor, "climb", 0, [grant]) == 22
