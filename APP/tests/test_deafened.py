"""Deafened (owner 2026-09-26: "deafened does what in 5.5e? apply it").

2024 Deafened: "You can't hear and automatically fail any ability check that requires hearing." Tianxia's own books
do not define it. In combat: an ability whose targets must hear the user ("One creature that can hear you": Iron
Voice, Kiai, Heaven-Silencing Word) can't target or reach a Deafened creature, and a reaction whose trigger the
reactor has to hear ("a creature you can hear ...") can't be used while Deafened.
"""

from pathlib import Path

from combat import typed_executor, typed_reactions
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position

ROOT = Path(__file__).resolve().parents[1]
DEAF = "condition:typed.deafened"


def _engine(typed: dict, target_kind: str = "HOSTILE_ENTITY") -> tuple[Gate2Engine, str]:
    engine = Gate2Engine(ROOT, match_seed="DEAFENED")
    actor = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id="action:typed.voice", display_name="Voice", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=target_kind,
                              range_ft=500, radius_ft=(typed.get("area") or {}).get("size_ft"), parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    return engine, actor.entity_id


_VOICE = {"effects": [{"type": "condition", "condition": "frightened", "applies_to": "target"}],
          "numbers": {"pb": 4}, "duration": {"kind": "instant"}, "weapon": None, "requires_hearing": True}


def test_a_deafened_creature_cannot_be_the_target_of_an_ability_that_needs_hearing():
    engine, actor_id = _engine(_VOICE)
    offered = {c.target_ids[0] for c in engine.legal_candidates() if c.source_definition_id == "action:typed.voice"}
    deaf = sorted(offered)[0]
    engine._apply_condition(engine.state.actors[deaf], DEAF, "test:setup", actor_id, expires_on="UNTIL_REMOVED")
    assert typed_executor.cant_hear(engine.state.actors[deaf])
    now = {c.target_ids[0] for c in engine.legal_candidates() if c.source_definition_id == "action:typed.voice"}
    assert deaf not in now and now == offered - {deaf}

    plain, _ = _engine({**_VOICE, "requires_hearing": False})
    plain._apply_condition(plain.state.actors[deaf], DEAF, "test:setup", actor_id, expires_on="UNTIL_REMOVED")
    assert deaf in {c.target_ids[0] for c in plain.legal_candidates() if c.source_definition_id == "action:typed.voice"}


def test_an_area_that_needs_hearing_skips_a_deafened_creature_inside_it():
    typed = {**_VOICE, "area": {"shape": "sphere", "size_ft": 30}}
    engine, actor_id = _engine(typed, target_kind="CELL")
    actor = engine.state.actors[actor_id]
    actor.position = Position(x=2, y=6)
    foes = [a for a in engine.state.actors.values() if a.team_id != actor.team_id][:2]
    foes[0].position, foes[1].position = Position(x=8, y=6), Position(x=9, y=6)
    engine._apply_condition(foes[0], DEAF, "test:setup", actor_id, expires_on="UNTIL_REMOVED")
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == "action:typed.voice" and c.destination == Position(x=8, y=6))
    from combat.gate2_runtime_models import ActionIntent
    engine.execute_intent(ActionIntent(intent_id="voice", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, destination=candidate.destination))
    frightened = "condition:typed.frightened"
    assert not any(c.condition_id == frightened for c in foes[0].conditions.values())  # deafened: not reached
    assert any(c.condition_id == frightened for c in foes[1].conditions.values())


def test_a_deafened_reactor_cannot_use_a_reaction_it_would_have_to_hear():
    engine, actor_id = _engine(_VOICE)
    reactor = engine.state.actors[actor_id]
    row = {"block": "generic", "feature_id": "HEARD", "kind": "technique_used", "reactor_hears": True, "costs": [], "effects": []}
    assert typed_reactions._can_trigger(engine, reactor, row)
    engine._apply_condition(reactor, DEAF, "test:setup", actor_id, expires_on="UNTIL_REMOVED")
    assert not typed_reactions._can_trigger(engine, reactor, row)
    assert typed_reactions._can_trigger(engine, reactor, {**row, "reactor_hears": False})
