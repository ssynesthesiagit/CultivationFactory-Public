"""Native Reaction consumers must stop when Internal Echo incapacitates the reactor."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_riders_c7 import FOE, ME, _typed_foe, bundle, fight
from combat.ext import flowing_river, qi_tempered, thread_correction, weapons_second_pass


DRUM = "tianxia.subpath.body.heaven_thunder_drum_body.feature."
ECHOING = "condition:typed.echoing"


def _engine():
    engine = fight(bundle([DRUM + "internal_echo"]), foe=_typed_foe(), foe_at=(10, 6))
    source, reactor = engine.state.actors[ME], engine.state.actors[FOE]
    engine._apply_condition(reactor, ECHOING, DRUM + "internal_echo", FOE,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(reactor.turns_started) + 1}",
                            data={"label": "lethal Echo", "pb": 4, "save_dc": 50, "cl": 18})
    return engine, source, reactor


def test_flowing_control_stops_when_reaction_window_is_interrupted(monkeypatch):
    from combat import typed_reactions

    engine, source, reactor = _engine()
    row = {"feature_id": "test:flowing_response"}
    monkeypatch.setattr(flowing_river, "_response_row", lambda *args: row)
    monkeypatch.setattr(engine, "_distance_actor_to_actor", lambda *args: 5)
    monkeypatch.setattr(flowing_river, "_available", lambda *args: True)
    monkeypatch.setattr(typed_reactions, "_consent", lambda *args: True)
    monkeypatch.setattr(typed_reactions, "_open", lambda *args: None)
    reactor.current_hp = 1
    monkeypatch.setattr(flowing_river, "activation", lambda *args, **kwargs: nullcontext())
    from combat import ext
    result = ext.invoke_strict(flowing_river.yield_control, SimpleNamespace(engine=engine, actor=source),
                               reactor, "STR", ["prone"])
    assert result is None
    assert not reactor.turn_flags.get("flowing_response_turn_round_1")
    assert not getattr(engine, "_flowing_control", {})


def test_thread_correction_does_not_adjust_roll_after_interrupted_reaction(monkeypatch):
    engine, _source, weaver = _engine()
    roller = engine.state.actors[ME]
    talent = thread_correction.BORROW
    rc = SimpleNamespace(kind="check", roller=roller, source_id="test:check", ability="STR",
                         engine=engine)
    roll = SimpleNamespace(natural_result=10)
    monkeypatch.setattr(thread_correction, "context_of", lambda *args: rc)
    monkeypatch.setattr(thread_correction, "_answers", lambda *args: [(weaver, talent, "test:cp")])
    monkeypatch.setattr(thread_correction, "_weaver_agrees", lambda *args: True)
    monkeypatch.setattr(thread_correction, "_is_willing", lambda *args: True)
    monkeypatch.setattr(weaver, "resources", {**weaver.resources, "test:cp": 3})
    paid = []
    monkeypatch.setattr(engine, "_spend_resource", lambda *args: paid.append(args))
    weaver.current_hp = 1
    monkeypatch.setattr(thread_correction, "note", lambda *args: (_ for _ in ()).throw(AssertionError("bonus applied")))
    assert thread_correction.line_correction(engine, roll, None) is None
    assert paid == [(weaver, "test:cp", thread_correction.COST[talent], talent)]
    assert not weaver.active and not weaver.reaction_available
    assert not any(c.condition_id == ECHOING for c in weaver.conditions.values())
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "THUNDER"
               for e in engine.events)
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == talent for e in engine.events)


def test_thread_correction_accepts_surviving_committed_reaction(monkeypatch):
    engine, _source, weaver = _engine()
    roller = engine.state.actors[ME]
    talent = thread_correction.BORROW
    rc = SimpleNamespace(kind="check", roller=roller, source_id="test:check", ability="STR",
                         engine=engine)
    roll = SimpleNamespace(natural_result=10)
    monkeypatch.setattr(thread_correction, "context_of", lambda *args: rc)
    monkeypatch.setattr(thread_correction, "_answers", lambda *args: [(weaver, talent, "test:cp")])
    monkeypatch.setattr(thread_correction, "_weaver_agrees", lambda *args: True)
    monkeypatch.setattr(thread_correction, "_is_willing", lambda *args: True)
    monkeypatch.setattr(weaver, "resources", {**weaver.resources, "test:cp": 3})
    monkeypatch.setattr(engine, "_spend_resource", lambda *args: None)
    result = thread_correction.line_correction(engine, roll, None)
    assert result["bonus"] == int(weaver.proficiency_bonus)
    assert weaver.active and not weaver.reaction_available
    assert not any(c.condition_id == ECHOING for c in weaver.conditions.values())
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "THUNDER"
               for e in engine.events)


@pytest.mark.parametrize("lethal", [True, False])
def test_qi_tempered_does_not_apply_bonus_after_interrupted_reaction(monkeypatch, lethal):
    from combat import ext

    engine, _source, actor = _engine()
    actor.resources[qi_tempered.QI] = 2
    row = {"feature_id": qi_tempered.FEATURE, "pb": 4,
           "block": qi_tempered.BLOCK, "kind": qi_tempered.KIND}
    monkeypatch.setattr(qi_tempered, "context_of", lambda *args: SimpleNamespace(
        kind="save", ability="CON", source_id=qi_tempered.CONCENTRATION, roller=actor,
        dc=15, total=8, succeeded=lambda: False))
    monkeypatch.setattr(qi_tempered, "holder_row", lambda *args: row)
    monkeypatch.setattr(qi_tempered, "qi_powered_feature", lambda *args: "Qi feature")
    asked = []
    def accept(*args, **kwargs):
        asked.append(kwargs["feature_id"])
        return ["maintain"]
    monkeypatch.setattr(qi_tempered, "ask", accept)
    actor.current_hp = 1 if lethal else actor.maximum_hp
    if lethal:
        monkeypatch.setattr(qi_tempered, "note", lambda *args: (_ for _ in ()).throw(AssertionError("bonus applied")))
    roll = SimpleNamespace(natural_result=10)
    result = ext.invoke_strict(qi_tempered.tempered_save, engine, roll, None)
    assert asked == [qi_tempered.FEATURE]  # Reached the real accepted/paid scope, not an admission early return.
    assert result == (None if lethal else {"source_id": qi_tempered.FEATURE, "bonus": 4})
    assert actor.resources[qi_tempered.QI] == 0
    assert not actor.reaction_available and actor.active is not lethal
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == qi_tempered.FEATURE
               for e in engine.events)
    assert any(e.event_type == "RESOURCE_SPENT" and e.source_definition_id == qi_tempered.FEATURE
               for e in engine.events)
    assert not any(c.condition_id == ECHOING for c in actor.conditions.values())


def test_later_reach_guard_still_gets_opportunity_attack_after_first_is_interrupted(monkeypatch):
    from combat import ext, movement_steps, relations, target_knowledge, targeting, paid_relocation
    from combat import typed_reactions as tr, weapon_delivery
    from combat.ext import hand_occupancy, rider_choices

    engine, _source, first = _engine()
    mover = engine.state.actors[ME]
    second = deepcopy(first)
    second.entity_id = "zz-second-guard"
    second.conditions.clear()
    second.turn_flags.clear()
    engine.state.actors[second.entity_id] = second
    action = SimpleNamespace(parameters={"typed": {"weapon": {"properties": "Reach"}}, "requires_hands": 1},
                             source_definition_id="test:reach")
    row = {"feature_id": "test:long_weapon_measure", "action_id": "test:long_weapon_measure"}
    monkeypatch.setattr(relations, "relation", lambda *args: relations.ENEMY)
    monkeypatch.setattr(weapons_second_pass, "owned", lambda *args: row)
    monkeypatch.setattr(movement_steps, "opportunity_exempt", lambda *args: False)
    monkeypatch.setattr(target_knowledge, "can_see", lambda *args: True)
    monkeypatch.setattr(targeting, "line_of_effect", lambda *args, **kwargs: True)
    monkeypatch.setattr(tr, "opportunity_reach", lambda *args: 10)
    monkeypatch.setattr(tr, "opportunity_profile", lambda *args: (row, action, 10))
    monkeypatch.setattr(weapon_delivery, "weapon_identity", lambda *args, **kwargs: "test:weapon")
    monkeypatch.setattr(hand_occupancy, "weapon_grips", lambda *args: {"test:weapon"})
    monkeypatch.setattr(hand_occupancy, "weapon_capacity", lambda *args: 1)
    distances = iter([15, 5, 15, 5])
    monkeypatch.setattr(engine, "_distance_actor_to_actor", lambda *args, **kwargs: next(distances))
    monkeypatch.setattr(tr, "wants_opportunity_attack", lambda *args, **kwargs: True)
    monkeypatch.setattr(rider_choices, "pick", lambda *args, **kwargs: True)
    monkeypatch.setattr(ext, "any_false", lambda *args: False)
    monkeypatch.setattr(paid_relocation, "activation", lambda *args, **kwargs: nullcontext())
    calls = []

    first.current_hp = 1
    monkeypatch.setattr(tr, "opportunity_attack", lambda _engine, guard, *args, **kwargs: calls.append(guard.entity_id))
    weapons_second_pass.entering_reach(engine, mover, mover.position, mover.position, None)
    assert calls == [second.entity_id]
