"""Opportunity attacks after the 2026-09-27 playtest ("there has been multiple times where attacks of opportunity werent
taken"): a "move without provoking" ability frees only the movement it grants, and a reactor whose Reaction is spent
says so in the log instead of silently letting the creature go."""

from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position
from tests.test_reaction_effects_r6 import REACTOR, _engine


def _engine_with_oa():
    engine = _engine([])
    action_id = next(key for key in engine.action_catalog if key.endswith(".opportunity_attack") and engine.action_catalog[key].owner_id == REACTOR)
    engine.typed_reaction_rows[REACTOR] = [{"feature_id": "opportunity_attack", "name": "Opportunity Attack", "block": "opportunity",
                                            "resource_id": "", "action_id": action_id, "reach_ft": 5}]
    return engine


def _walk_away(engine, mover_id: str) -> list:
    mover = engine.state.actors[mover_id]
    before = len(engine.events)
    engine._resolve_leave_reach(mover, mover.position, Position(x=mover.position.x + 1, y=mover.position.y), None)
    return engine.events[before:]


def test_granted_movement_is_free_only_for_its_own_feet():
    engine = _engine_with_oa()
    engine.state.actors[AN].position = Position(x=6, y=6)  # beside the reactor at 5,6
    foe = engine.state.actors[AN]
    foe.turn_flags["oa_free_ft"] = 5
    assert not [e for e in _walk_away(engine, AN) if e.event_type == "REACTION_WINDOW_OPENED"]
    assert foe.turn_flags["oa_free_ft"] == 0
    foe.position = Position(x=6, y=6)
    assert [e for e in _walk_away(engine, AN) if e.event_type == "REACTION_WINDOW_OPENED"]  # the rest provokes


def test_a_spent_reaction_is_named_in_the_log():
    engine = _engine_with_oa()
    engine.state.actors[AN].position = Position(x=6, y=6)
    engine.state.actors[REACTOR].reaction_available = False
    [declined] = [e for e in _walk_away(engine, AN) if e.event_type == "REACTION_DECLINED"]
    assert declined.actor_id == REACTOR and "already used" in declined.payload["reason"]
