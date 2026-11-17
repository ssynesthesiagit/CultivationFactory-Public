"""Accepted-reaction failures undo the action, not just its last effect.

Synthetic Gate4 submissions exercise persistence; no owner fixtures or history.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from combat import ext, gate2_engine, typed_executor
from combat.diagnostics import CombatGate1Error
from combat.gate2_runtime_models import (
    ActionDefinition, ActionIntent, ActorTemplate, EconomyKind, ResourceDefinition,
)
from combat.history_feed import format_history_feed
from combat.gate3_storage import Gate3Persistence
from combat.gate4_persistence import Gate4Persistence
from tests.replay_assertions import assert_replay_equal

ROOT = Path(gate2_engine.__file__).resolve().parents[1]
ATTACKER = "actor:synthetic.late_attacker"
REACTOR = "actor:synthetic.late_reactor"
ACTION = "test:atomic.late_trigger"
RESPONSE = "test:atomic.late_response"
QI = "resource:core.qi"
D20 = "test:atomic.d20_response"


def _bundle(actor_id, case):
    damage = {"type": "damage", "flat": 31 if case == "after_damage" else 2, "damage_types": ["force"]}
    effects = ([{"type": "save", "ability": "dex", "on_fail": [damage], "on_success": [damage]}]
               if case.startswith("d20_") else [damage])
    action = ActionDefinition(source_definition_id=ACTION, display_name="Synthetic late trigger",
        owner_id=ATTACKER, economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="HOSTILE_ENTITY", range_ft=60, parameters={"typed": {
            "effects": effects, "numbers": {"pb": 2, "save_dc": 15},
            "duration": {"kind": "instant"}, "riders": []}})
    template = ActorTemplate(entity_id=actor_id, display_name=actor_id, team_id=actor_id,
        primary_combatant=True, armor_class=12, maximum_hp=30, speed_ft=30,
        initiative_bonus=100 if actor_id == ATTACKER else 0, dexterity_score=12,
        proficiency_bonus=2, saving_throws={key: 0 for key in ("STR", "DEX", "CON", "INT", "WIS", "CHA")},
        resources=(ResourceDefinition(resource_id=QI, initial=3, maximum=3),
                   *([ResourceDefinition(resource_id="resource:core.resonance", initial=3, maximum=3)]
                     if case == "omen_glimpse_preparation" else [])),
        action_ids=(ACTION,) if actor_id == ATTACKER else (), reaction_ids=())
    rows = []
    if actor_id == REACTOR and not case.startswith("d20_") and case != "strict_state_event":
        row = {"feature_id": RESPONSE, "name": RESPONSE, "block": "generic",
               "kind": "drop_to_zero" if case == "after_damage" else "technique_targets",
               "costs": [{"resource_id": QI, "amount": 1}], "range_ft": 60, "once": "turn"}
        if case == "after_damage":
            row["requires_not_killed_outright"] = False
            row["effects"] = [{"type": "hold_at_1hp", "keep": 1},
                              {"type": "temp_hp", "flat": 3, "applies_to": "self"}]
        else:
            if case == "after_technique":
                row["after"] = "event"
            row["effects"] = [
                {"type": "damage", "flat": 2, "damage_types": ["force"], "applies_to": "attacker"},
                {"type": "temp_hp", "flat": 3, "applies_to": "self"},
                {"type": "condition", "condition": "prone", "applies_to": "attacker"}]
        rows.append(row)
    return {"actor_id": actor_id, "actor_template": template.model_dump(mode="json"),
            "action_catalog": [action.model_dump(mode="json")] if actor_id == ATTACKER else [],
            "typed_reactions": rows or [{"feature_id": actor_id + ":synthetic_inert", "block": "synthetic_inert"}],
            "typed_passives": ([{"feature_id": D20, "block": "d20_rewrite",
                                 "kind": case.removesuffix("_preparation")}]
                               if actor_id == REACTOR and case.endswith("_preparation") else
                               [{"feature_id": actor_id + ":synthetic_inert", "block": "synthetic_inert"}])}


def _automatic_reactions(engine):
    engine.typed_ask_reactors = {REACTOR}
    engine.typed_control_modes = {REACTOR: "LOCAL_AUTO"}


def _session(path, case, *, ask=False):
    bundles = tuple(_bundle(actor_id, case) for actor_id in (ATTACKER, REACTOR))
    if ask:
        for bundle in bundles:
            bundle["typed_reactions"] = [{**row, "ask": True} for row in bundle["typed_reactions"]]
    return Gate4Persistence(ROOT, path, engine_inputs=_automatic_reactions if ask else None).create_match(
        match_seed="SYNTHETIC-LATE-REACTION-ATOMIC", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [ATTACKER, REACTOR],
                      "starting_positions": {ATTACKER: {"x": 3, "y": 6}, REACTOR: {"x": 4, "y": 6}}})


def _intent(candidate, intent_id="test:atomic.late_intent"):
    return ActionIntent(intent_id=intent_id, decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination)


def _submit(session, intent):
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=None, for_ai=False)


def _submit_refused(session, intent):
    with pytest.raises(CombatGate1Error) as refused:
        _submit(session, intent)
    assert "refus" in str(refused.value).lower()


def _state(engine):
    return engine.state.model_dump(mode="json", by_alias=True)


def _round_trip(session, expected_state, expected_rolls):
    loaded = Gate4Persistence(ROOT, session.persistence.userdata_root).load_match(session.match_id)
    assert_replay_equal(_state(loaded.engine), expected_state, "cold-loaded refusal state")
    replay = loaded.mechanical.replay()
    assert_replay_equal(replay["state"], expected_state, "replayed refusal state")
    assert_replay_equal(replay["rolls"], expected_rolls, "replayed refusal rolls")
    assert loaded.verify()["status"] == "PASS"
    return loaded, replay



def _success(path, case):
    session = _session(path, case)
    choice = next(c for c in session.engine.legal_candidates() if c.source_definition_id == ACTION
                  and c.target_ids == (REACTOR,))
    _submit(session, _intent(choice))
    reactor = session.engine.state.actors[REACTOR]
    assert reactor.resources[QI] == 2 and not reactor.reaction_available
    assert not any(e.event_type == "GM_RIDER" for e in session.engine.events)
    _round_trip(session, _state(session.engine), [r.model_dump(mode="json") for r in session.engine.rolls])


def _shared_snapshot(engine):
    return {"state": _state(engine), "events": [e.model_dump(mode="json") for e in engine.events],
            "rolls": [r.model_dump(mode="json") for r in engine.rolls], "counter": engine.roller.counter}


def _assert_refused(session, before, trace, monkeypatch, failure):
    """A refused action leaves only one durable explanation and is never repaired by replay."""
    engine = session.engine
    assert len(trace) == 1
    events = [e.model_dump(mode="json") for e in engine.events]
    assert events[:len(before["events"])] == before["events"]
    refusal = events[len(before["events"]):]
    assert len(refusal) == 1 and refusal[0]["event_type"] == "GM_RIDER"
    assert "refus" in refusal[0]["payload"]["rider"].lower()
    assert failure in refusal[0]["payload"]["rider"]
    expected = copy.deepcopy(before["state"])
    expected["event_sequence"] += 1
    assert_replay_equal(_state(engine), expected, "whole action undone")
    assert [r.model_dump(mode="json") for r in engine.rolls] == before["rolls"]
    assert engine.roller.counter == before["counter"]
    with monkeypatch.context() as no_recompute:
        def unexpected_execute(*args, **kwargs):
            raise AssertionError("loading a refused action must not execute it again")
        no_recompute.setattr(Gate3Persistence, "execute_recorded_intent", staticmethod(unexpected_execute))
        loaded, replay = _round_trip(session, expected, before["rolls"])
        feed = format_history_feed([loaded.engine.events[-1].model_dump(mode="json")], [],
                                   pre_state=None, post_state={}, actor_names={}, definition_names={})
        assert len(feed) == 1
        summary = feed[0]["summary"]
        assert summary.startswith("Action refused:") and failure in summary
        assert "No part of the action was kept." in summary
        assert "additional effect reminder" not in summary and "Rule reminder" not in summary
        _, again = _round_trip(loaded, expected, before["rolls"])
    assert_replay_equal(again, replay, "repeat load is stable")
    assert loaded.verify()["controller_open_transactions"] == []
    next_choice = next(c for c in loaded.engine.legal_candidates() if c.kind.value == "END_TURN")
    _submit(loaded, _intent(next_choice, "test:atomic.continue"))
    assert loaded.engine.state.state_version > before["state"]["state_version"]
    assert len([e for e in loaded.engine.events if e.event_type == "GM_RIDER"]) == 1
    assert len(trace) == 1


@pytest.mark.parametrize("stage", ["payment", "first_effect", "later_effect", "open", "resolved", "hook", "runtime"])
def test_accepted_reaction_failure_refuses_whole_action(tmp_path, monkeypatch, stage):
    _success(tmp_path / "healthy", "immediate")
    session = _session(tmp_path / "failed", "immediate")
    engine = session.engine
    choice = next(c for c in engine.legal_candidates() if c.source_definition_id == ACTION
                  and c.target_ids == (REACTOR,))
    before = _shared_snapshot(engine)
    blocked = set(engine.grid.blocked)
    catalog = dict(engine.action_catalog)
    trace = []
    failure = "synthetic accepted reaction failure"
    append = engine._append_event
    spend = engine._spend_resource

    def fail():
        trace.append(stage)
        raise RuntimeError(failure)

    def spend_then_fail(actor, resource, amount, source, *args, **kwargs):
        result = spend(actor, resource, amount, source, *args, **kwargs)
        if source == RESPONSE and stage == "payment":
            fail()
        return result

    def append_then_fail(event_type, source, **kwargs):
        result = append(event_type, source, **kwargs)
        if source == RESPONSE and ((stage == "open" and event_type == "REACTION_WINDOW_OPENED")
                                   or (stage == "resolved" and event_type == "REACTION_RESOLVED")):
            fail()
        return result

    monkeypatch.setattr(engine, "_spend_resource", spend_then_fail)
    monkeypatch.setattr(engine, "_append_event", append_then_fail)
    for kind in ("damage", "temp_hp"):
        block = typed_executor.BLOCKS[kind]
        def effect_then_fail(ctx, effect, *, block=block, kind=kind):
            block(ctx, effect)
            if ctx.source != RESPONSE:
                return
            if stage == "runtime" and kind == "temp_hp":
                engine.grid.blocked.add((0, 0))
                engine.action_catalog["test:atomic.created"] = engine.action_catalog[ACTION]
                fail()
            if (stage == "first_effect" and kind == "damage") or (stage == "later_effect" and kind == "temp_hp"):
                fail()
        monkeypatch.setitem(typed_executor.BLOCKS, kind, effect_then_fail)

    if stage == "hook":
        def hook_then_fail(current, event):
            if current is engine and event.source_definition_id == RESPONSE:
                current._grant_temp_hp(current.state.actors[REACTOR], 7, RESPONSE, REACTOR)
                # A nested observational callback need not receive an engine.
                ext.invoke("reaction_resolved", fail)
        ext.effects()
        monkeypatch.setitem(ext._HOOKS, "reaction_resolved",
                            [*ext._HOOKS.get("reaction_resolved", ()), hook_then_fail])
    _submit_refused(session, _intent(choice))
    _assert_refused(session, before, trace, monkeypatch, failure)
    assert engine.grid.blocked == blocked
    assert engine.action_catalog == catalog


@pytest.mark.parametrize("kind", ["omen_glimpse", "stored_glimpse"])
def test_scene_die_preparation_failure_refuses_whole_response(tmp_path, monkeypatch, kind):
    ext.effects()

    def nested_roll(engine, event):
        if event.source_definition_id == RESPONSE:
            engine._roll_save(engine.state.actors[REACTOR], "DEX", 15, D20)

    monkeypatch.setitem(ext._HOOKS, "reaction_resolved",
                        [*ext._HOOKS.get("reaction_resolved", ()), nested_roll])
    case = kind + "_preparation"
    healthy = _session(tmp_path / "healthy", case)
    choice = next(c for c in healthy.engine.legal_candidates()
                  if c.source_definition_id == ACTION and c.target_ids == (REACTOR,))
    _submit(healthy, _intent(choice))
    assert healthy.engine.state.actors[REACTOR].resources[QI] == (1 if kind == "stored_glimpse" else 2)
    _round_trip(healthy, _state(healthy.engine),
                [r.model_dump(mode="json") for r in healthy.engine.rolls])

    session = _session(tmp_path / "failed", case)
    engine = session.engine
    choice = next(c for c in engine.legal_candidates()
                  if c.source_definition_id == ACTION and c.target_ids == (REACTOR,))
    before = _shared_snapshot(engine)
    spend = engine._spend_resource
    trace = []
    failure = "synthetic scene die preparation failure"

    def paid_then_fail(actor, resource, amount, source, *args, **kwargs):
        result = spend(actor, resource, amount, source, *args, **kwargs)
        if source == D20:
            trace.append(actor.resources[resource])
            raise RuntimeError(failure)
        return result

    monkeypatch.setattr(engine, "_spend_resource", paid_then_fail)
    _submit_refused(session, _intent(choice))
    assert trace == [1 if kind == "stored_glimpse" else 2]
    _assert_refused(session, before, trace, monkeypatch, failure)


def test_d20_eligibility_does_not_create_a_four_hand_turn_record(tmp_path):
    from types import SimpleNamespace
    from combat.ext.d20_rewrite import Holder, RULES, eligible
    from combat.ext.hundred_hands import HANDS

    session = _session(tmp_path, "immediate")
    engine = session.engine
    actor = engine.state.actors[ATTACKER]
    actor.resources[HANDS] = actor.resource_maximums[HANDS] = 2
    engine.typed_passive_rows[ATTACKER].append(
        {"block": "path_rider", "kind": "hundred_hands", "role": "four_hand"})
    action = engine.action_catalog[ACTION]
    engine.action_catalog[ACTION] = action.model_copy(update={"parameters": {
        **action.parameters, "typed": {**action.parameters["typed"], "attack_action": True}}})
    holder = Holder(actor, D20, {}, D20)
    rc = SimpleNamespace(kind="attack", roller=actor, ac=3, source_id=ACTION,
                         natural=1, total=1, ability=None, target=None, succeeded=lambda: False)
    before = _state(engine)
    assert eligible(engine, RULES["four_hand_sequence"], holder, rc) == (("battle_hand", 1),)
    assert _state(engine) == before, "eligibility queries cannot leave a partial turn record"
