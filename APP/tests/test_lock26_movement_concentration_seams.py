"""Lock round 26 item 2: native movement scope, painted-only difficult terrain and the Concentration
rescue seam, through CombatService, persisted execute_intent, cold reload and mechanical replay.

Minimal test hooks stand in for the Shield plug-ins (auto/shield); no ability ID enters core.
"""
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_engine import SYSTEM_OPPORTUNITY
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, Position, ReactionDecision
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from tests.test_auto_docket import ROOT, ME, _sheet
from tests.test_lock_choices import install


def _execute(data, mid, pick=None, reactions=()):
    service = CombatService(ROOT, data)
    session = service._load_session(mid)
    candidates = session.engine.legal_candidates()
    candidate = next(c for c in candidates if (pick(c) if pick else c.kind.value == "END_TURN"))
    intent = ActionIntent(intent_id=f"lock26:{session.engine.state.state_version}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids, reaction_decisions=tuple(reactions))
    session.mechanical.execute_intent(intent)
    cold = CombatService(ROOT, data)._load_session(mid)
    assert cold.mechanical.replay()["status"] == "PASS"
    return cold


def _match(tmp_path, seed, *, me_at=(3, 6), foe_at=(10, 6), battlefield=None):
    bundle = compile_character(_sheet([]), actor_id=ME)
    session = CombatService(ROOT, tmp_path).persistence.create_match(match_seed=seed,
        typed_bundles=(bundle,), battlefield=battlefield, roster_setup={"primary_actor_ids": [ME, AN],
        "team_by_actor": {ME: "team:a", AN: "team:b"},
        "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    mid = session.match_id
    while session.engine.state.current_actor_id != ME:
        session = _execute(tmp_path, mid)
    return mid, session


def _move_to(x, y):
    return lambda c: c.kind.value == "MOVE" and c.destination == Position(x=x, y=y)


def test_movement_scope_covers_steps_and_provoked_opportunity_attacks(tmp_path, monkeypatch):
    """(a) A "during movement" rule (Shield Skate's AC loss) can see the mover's native movement scope while
    an opportunity attack it provoked resolves, and nowhere else."""
    seen = []

    def ac(engine, actor):
        if actor.entity_id == ME:
            seen.append(engine.movement_scope(ME))
        return None

    install(monkeypatch, "ac", ac)
    mid, session = _match(tmp_path, "LOCK26-MOVE", me_at=(5, 6), foe_at=(6, 6))
    assert session.engine.movement_scope(ME) is None
    seen.clear()
    use = ReactionDecision(checkpoint="LEAVE_REACH", reactor_id=AN, reaction_source_id=SYSTEM_OPPORTUNITY, selection="USE")
    session = _execute(tmp_path, mid, _move_to(2, 6), reactions=(use,))
    events = session.engine.events
    assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == AN and e.source_definition_id == SYSTEM_OPPORTUNITY
               for e in events), "moving out of reach must provoke the stock foe's opportunity attack"
    scoped = [s for s in seen if s is not None]
    assert scoped and all(s["actor_id"] == ME and s["mode"] == "walk" and s["granted"] is False for s in scoped)
    assert session.engine.movement_scope(ME) is None  # ended with MOVEMENT_COMMITTED; never saved
    assert "_movement_scopes" not in session.engine.state.model_dump(mode="json")
    # Outside movement the same AC query has no scope.
    seen.clear()
    session.engine._ac_modifier(session.engine.state.actors[ME])
    assert seen
    assert all(s is None for s in seen)


def _bamboo_arena():
    return to_battlefield(normalize_map({
        "display_name": "Bamboo Lane", "width_squares": 20, "height_squares": 14,
        "materials": [{"material": "terrain:bamboo thicket", "cells": [[x, y] for x in (4, 5) for y in range(14)]}],
        "starts": {"team1": [[3, 6]], "team2": [[14, 6]]},
    }))


def test_painted_only_difficult_terrain_costs_extra_movement(tmp_path):
    """(b) Painted map terrain with no typed zone active still doubles the cost of each step."""
    mid, session = _match(tmp_path, "LOCK26-PAINT", foe_at=(14, 6), battlefield=_bamboo_arena())
    engine = session.engine
    assert not any(z.active and z.trigger_profile.get("kind") == "TYPED" for z in engine.state.zones.values())
    assert {(4, 6), (5, 6)} <= engine._hostile_difficult_cells(engine.state.actors[ME])
    before = engine.state.actors[ME].movement_remaining_ft
    # A wall-to-wall band two squares wide: no route avoids it. 10 + 10 + 5 feet.
    session = _execute(tmp_path, mid, _move_to(6, 6))
    commit = next(e for e in reversed(session.engine.events) if e.event_type == "MOVEMENT_COMMITTED")
    assert commit.payload["cost_ft"] == 25
    assert session.engine.state.actors[ME].movement_remaining_ft == before - 25


def _actions(info):
    return [
        ActionDefinition(source_definition_id="action:test.lock26.focus", display_name="Lock26 Focus",
            owner_id=info["actor_id"], economy="NONE", resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"source": "test:lock26.focus", "numbers": info["numbers"],
                "duration": {"kind": "rounds", "amount": 10, "concentration": True}, "effects": []}}),
        ActionDefinition(source_definition_id="action:test.lock26.hurt", display_name="Lock26 Hurt",
            owner_id=info["actor_id"], economy="NONE", resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"source": "test:lock26.hurt", "numbers": info["numbers"],
                "effects": [{"type": "damage", "applies_to": "self", "damage_types": ["FORCE"], "flat": 4}]}}),
    ]


def _concentration_case(tmp_path, monkeypatch, answer):
    install(monkeypatch, "compile_actions", _actions)
    install(monkeypatch, "save_bonus", lambda engine, target, ability, dc, source, intent: -40 if ability == "CON" else None)
    calls = []

    def rescue(engine, actor, roll, dc, context):
        calls.append((actor.entity_id, roll.total < dc, dict(context)))
        return answer

    install(monkeypatch, "concentration_save_failed", rescue)
    mid, session = _match(tmp_path, "LOCK26-CONC-" + str(answer))
    session = _execute(tmp_path, mid, lambda c: c.source_definition_id == "action:test.lock26.focus")
    started = session.engine.state.actors[ME].concentration.started_sequence
    session = _execute(tmp_path, mid, lambda c: c.source_definition_id == "action:test.lock26.hurt")
    return session, calls, started


def test_failed_concentration_save_can_be_rescued_by_one_owner(tmp_path, monkeypatch):
    """(c) The failed-save decision point: an owner answering MAINTAIN keeps Concentration (Never Falls)."""
    session, calls, started = _concentration_case(tmp_path, monkeypatch, "MAINTAIN")
    assert len(calls) == 1 and calls[0][0] == ME and calls[0][1] is True
    assert calls[0][2]["started_sequence"] == started
    assert calls[0][2]["source_definition_id"] == "action:test.lock26.focus"
    me = session.engine.state.actors[ME]
    assert me.concentration is not None and me.concentration.started_sequence == started
    assert not any(e.event_type == "CONCENTRATION_ENDED" for e in session.engine.events)
    assert any(r.actor_id == ME and r.total < 0 for r in session.engine.rolls)  # the failed save stays recorded


def test_failed_concentration_save_without_rescue_keeps_the_old_ending(tmp_path, monkeypatch):
    session, calls, _started = _concentration_case(tmp_path, monkeypatch, None)
    assert len(calls) == 1
    assert session.engine.state.actors[ME].concentration is None
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.payload.get("reason") == "FAILED_DAMAGE_CHECK"
               for e in session.engine.events)
