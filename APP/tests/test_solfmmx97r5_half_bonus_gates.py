"""Relocated plain bonuses retain dispatch gates on both half-damage save paths.

The authoring fixtures execute real candidates; test-only hooks isolate Evasion and
effect veto/scope contracts without requiring an unrelated ability's resource setup.
"""
from contextlib import contextmanager

import pytest

from combat import ext
from combat.effect_eligibility import modifier_key
from combat.factory_compiler import _attach
from tests.test_solfmmx97r2_damage_stages import dealt, save
from tests.test_typed_executor import _engine_with, _intent


def setup(monkeypatch, *, evasion=False, gate=None, area=False, random=False):
    branch = save()
    branch["on_success"] = [{"type": "half_damage"}]
    rider = {"type": "damage", "applies_to": "target", **(gate or {})}
    rider.update({"dice": {"count": 1, "sides": 100}} if random else {"formula": "pb"})
    tree = _attach([branch], [rider], "use")
    typed = {"effects": tree, "numbers": {"pb": 6, "cl": 5, "save_dc": 15}}
    if area:
        typed["area"] = {"shape": "sphere", "size_ft": 500,
                         "centered_on_self": True, "recipients": "enemies"}
    engine, actor_id = _engine_with(typed, "SOLFMMX97R5")
    # Free authoring action permits two legal uses in one turn without resetting
    # flags, advancing the turn, or bypassing action execution.
    action = engine.action_catalog["action:typed.test"]
    from combat.gate2_runtime_models import EconomyKind
    engine.action_catalog[action.source_definition_id] = action.model_copy(update={"economy": EconomyKind.NONE})
    for subject in engine.state.actors.values():
        subject.maximum_hp = subject.current_hp = 1000
        subject.temporary_hp = 0
    if evasion:
        original = ext.run

        def hooks(name, *args, **kwargs):
            return [True] if name == "evasion" else original(name, *args, **kwargs)

        monkeypatch.setattr(ext, "run", hooks)
    return engine, actor_id, tree[0]["on_fail"][-1]


def use(engine, outcome):
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine._typed_roll_outcome = ({who: outcome for who in engine.state.actors}
                                 if isinstance(outcome, str) else outcome.copy())
    before = len(engine.events)
    engine.execute_intent(_intent(candidate))
    events = engine.events[before:]
    recipients = [e.actor_id for e in events if e.event_type == "SAVE_ROLLED"]
    assert recipients
    return events, recipients


@pytest.mark.parametrize("evasion", [False, True])
@pytest.mark.parametrize("gate", [{"min_cl": 10}, {"max_cl": 3},
                                  {"menu": "unselected", "option": "Bonus"},
                                  {"deferred": True}])
def test_half_damage_skips_ineligible_bonus(monkeypatch, evasion, gate):
    engine, _, _ = setup(monkeypatch, evasion=evasion, gate=gate)
    events, recipients = use(engine, "failure" if evasion else "success")
    assert [dealt(events, who) for who in recipients] == [10] * len(recipients)


@pytest.mark.parametrize("evasion", [False, True])
@pytest.mark.parametrize("period", [None, "turn", "owner_turn"])
def test_half_damage_respects_already_spent_modifier(monkeypatch, evasion, period):
    gate = {"modifier_once": "half-save-bonus"}
    if period:
        gate["modifier_once_period"] = period
    engine, actor, rider = setup(monkeypatch, evasion=evasion, gate=gate)
    engine.state.actors[actor].turn_flags[modifier_key(rider)] = True
    events, recipients = use(engine, "failure" if evasion else "success")
    assert [dealt(events, who) for who in recipients] == [10] * len(recipients)


@pytest.mark.parametrize("evasion", [False, True])
def test_all_halved_first_use_spends_gate_before_second_use(monkeypatch, evasion):
    engine, actor, rider = setup(monkeypatch, evasion=evasion,
                                gate={"modifier_once": "half-save-bonus"}, area=True)
    outcome = "failure" if evasion else "success"
    first, recipients = use(engine, outcome)
    assert len(recipients) > 1
    assert [dealt(first, who) for who in recipients] == [13] * len(recipients)
    spent_after_first = bool(engine.state.actors[actor].turn_flags.get(modifier_key(rider)))
    turn = (engine.state.round_number, engine.state.current_actor_id)
    second, others = use(engine, outcome)
    assert others == recipients
    assert [dealt(second, who) for who in others] == [10] * len(others)
    assert spent_after_first
    assert (engine.state.round_number, engine.state.current_actor_id) == turn


@pytest.mark.parametrize("evasion", [False, True])
@pytest.mark.parametrize("veto", [False, True])
def test_half_bonus_runs_effect_veto_and_scope(monkeypatch, evasion, veto):
    engine, actor, rider = setup(monkeypatch, evasion=evasion,
                                gate={"modifier_once": "half-save-bonus"})
    original = ext.run_strict
    seen = []

    @contextmanager
    def scope(ctx):
        seen.append("entered")
        yield
        seen.append("exited")

    def hooks(name, *args, **kwargs):
        if name in ("effect_allowed", "effect_resolution_scope"):
            ctx, effect = args[:2]
        else:
            return original(name, *args, **kwargs)
        if effect.get("damage_bonus_packet"):
            if name == "effect_allowed":
                seen.append("allowed")
                if veto:
                    return [False]
            if name == "effect_resolution_scope":
                return [scope(ctx)]
        return original(name, *args, **kwargs)

    monkeypatch.setattr(ext, "run_strict", hooks)
    events, recipients = use(engine, "failure" if evasion else "success")
    assert seen == (["allowed"] if veto else ["allowed", "entered", "exited"])
    assert dealt(events, recipients[0]) == (10 if veto else 13)
    assert bool(engine.state.actors[actor].turn_flags.get(modifier_key(rider))) is not veto


@pytest.mark.parametrize("first_failure", [False, True])
def test_mixed_area_outcomes_share_gated_random_bonus(monkeypatch, first_failure):
    engine, actor, rider = setup(monkeypatch, gate={"modifier_once": "area-bonus"},
                                area=True, random=True)
    opponents = [who for who in engine.state.actors if who != actor]
    outcomes = {who: "failure" if (index == 0) == first_failure else "success"
                for index, who in enumerate(opponents)}
    events, recipients = use(engine, outcomes)
    assert len(recipients) > 1
    full = [dealt(events, who) - 20 for who in recipients if outcomes[who] == "failure"]
    half = [dealt(events, who) - 10 for who in recipients if outcomes[who] == "success"]
    assert full and half and len(set(full)) == 1 and half == [full[0] // 2] * len(half)
    assert engine.state.actors[actor].turn_flags[modifier_key(rider)]
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert len(rolls) == 1  # flat base emits no roll; the random bonus rolls only once


@pytest.mark.parametrize("first_evasion", [False, True])
def test_mixed_evasion_area_shares_gated_random_bonus(monkeypatch, first_evasion):
    engine, actor, rider = setup(monkeypatch, gate={"modifier_once": "area-bonus"},
                                area=True, random=True)
    opponents = [who for who in engine.state.actors if who != actor]
    evades = {who for index, who in enumerate(opponents) if (index == 0) == first_evasion}
    original = ext.run

    def hooks(name, *args, **kwargs):
        if name == "evasion":
            return [True] if args[1].entity_id in evades else []
        return original(name, *args, **kwargs)

    monkeypatch.setattr(ext, "run", hooks)
    events, recipients = use(engine, "failure")
    full = [dealt(events, who) - 20 for who in recipients if who not in evades]
    half = [dealt(events, who) - 10 for who in recipients if who in evades]
    assert full and half and len(set(full)) == 1 and half == [full[0] // 2] * len(half)
    assert engine.state.actors[actor].turn_flags[modifier_key(rider)]
    assert len([e for e in events if e.event_type == "DAMAGE_ROLLED"]) == 1
