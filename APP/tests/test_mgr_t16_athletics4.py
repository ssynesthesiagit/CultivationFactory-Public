"""Owned Athletics rows at the table transaction and cold-session boundary."""
import pytest

from combat import typed_reactions
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD
from tests.test_lock2_persistence import act
from tests.h1_support import ROOT

PURSUIT = "TAL_ATHLETICS_UNBROKEN_PURSUIT"


def complete(table, mid, source=HOLD, *, pick_last=False):
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"]
               if g["source_definition_id"].startswith(source))
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            options = prompt["choice"]["options"]
            answer["option_ids"] = [options[-1 if pick_last else 0]["id"]]
        answers.append(answer)
    raise AssertionError("Unfinished Athletics choice")


@pytest.mark.parametrize("subject", [RIGHT, ALLY])
def test_pursuit_any_creature_and_player_destination_survive_reload(tmp_path, monkeypatch, subject):
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[],
        starts={"team1": [[1, 3], [6, 4]], "team2": [[6, 3]]})
    on_hold(monkeypatch, lambda e: typed_reactions.on_creature_event(e, e.state.actors[subject], "moved", moved_ft=5))
    before = combat._load_session(mid).engine.state.actors[LEFT].position
    result, prompts = complete(table, mid, pick_last=True)
    choice = next(p for p in prompts if p.get("choice"))
    assert choice["reaction"] == "Unbroken Pursuit"
    assert len(choice["choice"]["options"]) > 1
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.position != before
    assert actor.resources["resource:core.martial_focus"] == 0
    assert not actor.reaction_available
    assert actor.movement_remaining_ft == 30
    assert loaded.engine._distance_actor_to_actor(actor, loaded.engine.state.actors[subject]) < 25
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == LEFT for e in loaded.engine.events)


@pytest.mark.parametrize("speed,expected", [(20, False), (30, True)])
def test_pursuit_uses_live_speed_range_at_table(tmp_path, monkeypatch, speed, expected):
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[],
        starts={"team1": [[1, 3], [1, 4]], "team2": [[6, 3]]})
    def move(e):
        e._apply_condition(e.state.actors[LEFT], "condition:typed.test_speed", "test:speed", LEFT,
                           expires_on="END_OF_CURRENT_TURN", data={"speed_delta": speed - 30})
        typed_reactions.on_creature_event(e, e.state.actors[RIGHT], "moved", moved_ft=5)
    on_hold(monkeypatch, move)
    result, prompts = complete(table, mid)
    assert bool(prompts) is expected
    from tests.h1_support import ROOT
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT]
    assert actor.resources["resource:core.martial_focus"] == (0 if expected else 1)


@pytest.mark.parametrize("kind", ["reaction", "teleport"])
def test_pursuit_observes_other_willing_sources(tmp_path, monkeypatch, kind):
    from combat.ext import athletics
    from combat.gate2_runtime_models import Position
    combat, table, mid = table_fight(tmp_path, [PURSUIT], ask=True, ally_talents=[],
        starts={"team1": [[1, 3], [1, 4]], "team2": [[6, 3]]})
    def moved(e):
        target = e.state.actors[RIGHT]
        start = target.position
        end = Position(x=start.x+1, y=start.y)
        target.position = end
        if kind == "reaction":
            e._append_event("MOVEMENT_COMMITTED", "test:reaction", actor_id=RIGHT,
                payload={"reaction": True, "forced": False, "destination": end.model_dump(),
                         "cost_ft": 0, "path": [start.model_dump(), end.model_dump()]})
        else:
            from types import SimpleNamespace
            e._append_event("MOVEMENT_COMMITTED", "test:teleport", actor_id=RIGHT,
                payload={"teleport": True, "forced": False, "destination": end.model_dump(),
                         "cost_ft": 0, "path": [start.model_dump(), end.model_dump()]})
            athletics.pursuit_after_teleport(SimpleNamespace(engine=e), target, start, end, False)
    on_hold(monkeypatch, moved)
    result, prompts = complete(table, mid)
    assert any(p.get("choice") for p in prompts)
    from tests.h1_support import ROOT
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT].position.x > 1


SPIDER = "TAL_ATHLETICS_SPIDER_S_TOUCH"
GRIP = "TAL_ATHLETICS_SURE_GRIP"


def test_spider_climb_speed_and_vertical_route_already_automated_on_main(tmp_path):
    from combat import roof_movement
    from tests.test_walkable_roofs import roof_fight, route, cold, OWNER
    combat, table, mid = roof_fight(tmp_path, owner_talents=(SPIDER,), owner_start=(3, 2))
    route(combat, table, mid, [(3, 2, 0), (3, 2, 1), (3, 2, 2)], mode="climb")
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert roof_movement.profile(session.engine, actor).speed_ft == session.engine._effective_speed(actor) == 30
    assert actor.position.z == 2 and actor.movement_remaining_ft == 20


@pytest.mark.parametrize("sure_grip", [False, True])
def test_spider_ceiling_requires_sure_grip_and_retains_free_hand(tmp_path, sure_grip):
    from combat import roof_movement, falling
    from combat.ext.hand_occupancy import free_hands
    from tests.test_walkable_roofs import roof_fight, route, cold, OWNER
    combat, table, mid = roof_fight(tmp_path, owner_talents=(SPIDER, GRIP) if sure_grip else (SPIDER,),
                                   owner_start=(5, 2))
    path = [(5, 2, 0), (5, 2, 1), (6, 2, 1), (6, 3, 1)]
    if not sure_grip:
        with pytest.raises(ValueError):
            route(combat, table, mid, path, mode="climb")
        return
    route(combat, table, mid, path, mode="climb")
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position.z == 1 and actor.climbing
    assert roof_movement.can_hold(session.engine, actor)
    assert not falling.required(session.engine, actor)
    assert free_hands(session.engine, actor)


def test_spider_sure_grip_climb_refuses_when_no_hand_can_stay_free(tmp_path, monkeypatch):
    from combat.ext import hand_occupancy
    from tests.test_walkable_roofs import roof_fight, route, cold, OWNER
    combat, table, mid = roof_fight(tmp_path, owner_talents=(SPIDER, GRIP), owner_start=(3, 2))
    monkeypatch.setattr(hand_occupancy, "free_hands", lambda engine, actor: ())
    with pytest.raises(ValueError):
        route(combat, table, mid, [(3, 2, 0), (3, 2, 1)], mode="climb")
    _, _, session = cold(combat, tmp_path, mid)
    assert session.engine.state.actors[OWNER].position.z == 0
