"""Failures after an accepted reaction must refuse, persist once, and never reroll."""
from __future__ import annotations

import json

import pytest

from combat import ext, gate2_engine
from combat.ext import CheckpointError
from combat.history_feed import format_history_feed
from combat.gate3_storage import Gate3InjectedCrash
from combat.gate4_persistence import Gate4Persistence
from tests.test_reaction_atomic import (
    ROOT, ATTACKER, REACTOR, ACTION, RESPONSE, D20, QI,
    _session, _state, _intent, _submit, _submit_refused, _success,
    _shared_snapshot, _assert_refused, _automatic_reactions,
)


def _register_d20(monkeypatch, stage, callback):
    from combat.ext.d20_rewrite import Holder, Rule, RULES

    additive = stage in {"bonus", "after_bonus"}
    rule = Rule("synthetic_atomic_d20", "Synthetic reaction", rolls=("save",), when="any",
        op="bonus" if additive else "choose", choose=lambda e, h, rc: 17,
        costs=((("qi", 1),),), reaction=True, limit="fight",
        finder=lambda e: [Holder(e.state.actors[REACTOR], D20, {}, D20)],
        ai=lambda e, h, rc: True,
        **({"bonus": lambda e, h, rc: 2} if stage == "after_bonus" else {}),
        **{stage: callback})
    ext.effects()
    monkeypatch.setitem(RULES, rule.kind, rule)


def _choice(engine):
    return next(c for c in engine.legal_candidates() if c.source_definition_id == ACTION
                and c.target_ids == (REACTOR,))


@pytest.mark.parametrize("case", ["after_damage", "after_technique", "d20_after", "d20_after_bonus"])
def test_deferred_failure_refuses_without_reexecution(tmp_path, monkeypatch, case):
    def grant(engine, holder, rc, result, *amount):
        engine._grant_temp_hp(holder.actor, 3, D20, holder.actor.entity_id)

    with monkeypatch.context() as healthy:
        if case.startswith("d20_"):
            _register_d20(healthy, case.removeprefix("d20_"), grant)
        _success(tmp_path / "healthy", case)
    session = _session(tmp_path / "failed", case)
    engine = session.engine
    choice = _choice(engine)
    before = _shared_snapshot(engine)
    trace = []
    diagnostic_callbacks = []
    failure = "synthetic delayed reaction failure"

    def diagnostic_hook(current, event_type, kwargs):
        if event_type == "GM_RIDER":
            diagnostic_callbacks.append(event_type)
            current.state.actors[REACTOR].temporary_hp = 7

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), diagnostic_hook])
    if case.startswith("d20_"):
        def fails(e, holder, rc, result, *amount):
            grant(e, holder, rc, result, *amount)
            trace.append(holder.actor.temporary_hp)
            raise RuntimeError(failure)
        _register_d20(monkeypatch, case.removeprefix("d20_"), fails)
    else:
        original = engine._grant_temp_hp
        def grant_then_fail(target, amount, source_id, source_actor_id, **kwargs):
            result = original(target, amount, source_id, source_actor_id, **kwargs)
            if source_id == RESPONSE:
                assert any(e.event_type == "REACTION_RESOLVED"
                           and e.source_definition_id == RESPONSE for e in engine.events)
                trace.append(target.temporary_hp)
                raise RuntimeError(failure)
            return result
        monkeypatch.setattr(engine, "_grant_temp_hp", grant_then_fail)
    _submit_refused(session, _intent(choice))
    assert trace == [3]
    assert diagnostic_callbacks == [], "a refusal must not dispatch more gameplay effects"
    _assert_refused(session, before, trace, monkeypatch, failure)


@pytest.mark.parametrize("stage", ["on_use", "bonus", "additive_save_bonus"])
def test_paid_d20_failure_refuses_whole_action(tmp_path, monkeypatch, stage):
    def grant(engine, holder, rc):
        engine._grant_temp_hp(holder.actor, 3, D20, holder.actor.entity_id)
        return 2

    with monkeypatch.context() as healthy:
        _register_d20(healthy, stage, grant)
        _success(tmp_path / "healthy", "d20_after")
    session = _session(tmp_path / "failed", "d20_after")
    engine = session.engine
    choice = _choice(engine)
    before = _shared_snapshot(engine)
    trace = []
    failure = "synthetic paid d20 failure"

    def fails(e, holder, rc):
        grant(e, holder, rc)
        trace.append(holder.actor.temporary_hp)
        raise RuntimeError(failure)

    _register_d20(monkeypatch, stage, fails)
    _submit_refused(session, _intent(choice))
    _assert_refused(session, before, trace, monkeypatch, failure)


@pytest.mark.parametrize("stage", ["after", "after_bonus"])
def test_returned_d20_journal_failure_refuses_whole_action(tmp_path, monkeypatch, stage):
    def grant(engine, holder, rc, result, *amount):
        engine._grant_temp_hp(holder.actor, 3, D20, holder.actor.entity_id)

    _register_d20(monkeypatch, stage, grant)
    _success(tmp_path / "healthy", "d20_" + stage)
    session = _session(tmp_path / "failed", "d20_" + stage)
    engine = session.engine
    choice = _choice(engine)
    before = _shared_snapshot(engine)
    trace = []
    failure = "synthetic returned reaction journal failure"
    append = engine._append_event

    def append_then_fail(event_type, source, **kwargs):
        result = append(event_type, source, **kwargs)
        if event_type == "D20_REWRITTEN" and source == D20:
            assert engine.state.actors[REACTOR].resources[QI] == 2
            trace.append(event_type)
            raise RuntimeError(failure)
        return result

    monkeypatch.setattr(engine, "_append_event", append_then_fail)
    _submit_refused(session, _intent(choice))
    _assert_refused(session, before, trace, monkeypatch, failure)


@pytest.mark.parametrize("checkpoint", [False, True])
def test_nonreaction_roll_bonus_refusal_is_plain_in_reloaded_history(tmp_path, monkeypatch, checkpoint):
    session = _session(tmp_path, "d20_after")
    engine = session.engine
    choice = _choice(engine)
    failure = "synthetic roll bonus failure"

    def bonus_provider(engine, roll, intent):
        def answers():
            try:
                yield {"bonus": "invalid"}
            finally:
                if checkpoint:
                    raise CheckpointError(failure)
        return answers()

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_bonus", [bonus_provider])
    _submit_refused(session, _intent(choice))
    loaded = Gate4Persistence(ROOT, session.persistence.userdata_root).load_match(session.match_id)
    event = loaded.engine.events[-1].model_dump(mode="json")
    feed = format_history_feed([event], [], pre_state=None, post_state={}, actor_names={}, definition_names={})
    assert len(feed) == 1
    summary = feed[0]["summary"]
    assert summary.startswith("Action refused: a roll bonus could not finish")
    assert "No part of the action was kept." in summary
    assert "reaction" not in summary.lower()
    assert "reminder" not in summary.lower() and "d20 rewrite" not in summary.lower()
    if checkpoint:
        assert failure in summary


def test_deferred_failure_survives_strict_state_event_dispatch(tmp_path, monkeypatch):
    def save_after_damage(engine, event):
        if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ACTION:
            engine._roll_save(engine.state.actors[REACTOR], "DEX", 15, ACTION)

    def grant(engine, holder, rc, result):
        engine._grant_temp_hp(holder.actor, 3, D20, holder.actor.entity_id)

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "state_event", [*ext._HOOKS.get("state_event", ()), save_after_damage])
    _register_d20(monkeypatch, "after", grant)
    _success(tmp_path / "healthy", "strict_state_event")
    session = _session(tmp_path / "failed", "strict_state_event")
    choice = _choice(session.engine)
    before = _shared_snapshot(session.engine)
    trace = []
    failure = "synthetic nested strict reaction failure"

    def fails(engine, holder, rc, result):
        grant(engine, holder, rc, result)
        trace.append(holder.actor.temporary_hp)
        raise RuntimeError(failure)

    _register_d20(monkeypatch, "after", fails)
    _submit_refused(session, _intent(choice))
    _assert_refused(session, before, trace, monkeypatch, failure)


@pytest.mark.parametrize("case", ["after_damage", "after_technique"])
def test_prepared_recovery_persists_one_refusal(tmp_path, monkeypatch, case):
    session = _session(tmp_path / "prepared", case, ask=True)
    before = _shared_snapshot(session.engine)

    def crash(stage, context):
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash(stage)

    with pytest.raises(Gate3InjectedCrash):
        session.submit_intent(_intent(_choice(session.engine)), primary_decision_record=None,
                              reaction_provider=None, for_ai=False, failure_injector=crash)
    trace = []
    failure = "synthetic recovered reaction failure"
    original = gate2_engine.Gate2Engine._grant_temp_hp

    def grant_then_fail(engine, target, amount, source_id, source_actor_id, **kwargs):
        result = original(engine, target, amount, source_id, source_actor_id, **kwargs)
        if source_id == RESPONSE:
            trace.append(target.temporary_hp)
            raise RuntimeError(failure)
        return result

    monkeypatch.setattr(gate2_engine.Gate2Engine, "_grant_temp_hp", grant_then_fail)
    recovered = Gate4Persistence(ROOT, session.persistence.userdata_root,
                                 engine_inputs=_automatic_reactions).load_match(session.match_id)
    rows = [json.loads(line) for line in recovered.controller_journal_path.read_text().splitlines()]
    aborts = [row for row in rows if row["record_type"] == "CONTROLLER_ABORT"]
    assert len(aborts) == 1 and aborts[0]["reaction_decision_records"] == []
    _assert_refused(recovered, before, trace, monkeypatch, failure)
