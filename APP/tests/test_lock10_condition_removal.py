"""Typed cures cancel matching delayed conditions before their due turn."""
import pytest

from combat import typed_executor as te
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT
from tests.test_lock2_persistence import act

DELAY = "condition:typed.test_delayed_condition"
DURABLE = "TAL_GUARDIAN_DURABLE"
COLD_IRON = "TAL_GUARDIAN_COLD_IRON_CALL"


def context(engine, target, source="test:cure"):
    caster = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id=source, display_name="Cure Poisoned", owner_id=caster.entity_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ALLY_ENTITY")
    return te.Context(engine, caster, action, getattr(engine, "_active_intent", None), {}, [target], target)


def reserve(engine, actor, name, source, amount):
    engine._apply_condition(actor, DELAY, source, actor.entity_id, expires_on="END_OF_TARGET_NEXT_TURN",
                            data={"condition": name, "reserve": amount, "due": actor.turns_started + 1})


def cancel_pending(ctx, subject, name, cause):
    if cause != "cure":
        return
    for iid, condition in list(subject.conditions.items()):
        if condition.condition_id == DELAY and condition.data.get("condition") == name:
            # Representative pool-owner contract: removing this exact ledger
            # releases its reserved capacity, without deleting other delays.
            del subject.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(subject.entity_id,), payload={"condition_id": DELAY, "instance_id": iid})


@pytest.mark.parametrize("source,amount", [(DURABLE, 10), (COLD_IRON, 15)])
@pytest.mark.parametrize("active", [True, False])
def test_cure_releases_only_matching_delays_and_reloads(monkeypatch, tmp_path, source, amount, active):
    combat, table, mid = table_fight(tmp_path, [source], ally_talents=[])
    install(monkeypatch, "te.condition_removal", cancel_pending)
    def cure(engine):
        target = engine.state.actors[LEFT]
        reserve(engine, target, "poisoned", source, amount)
        reserve(engine, target, "poisoned", source, amount)
        reserve(engine, target, "stunned", source, amount)
        other = next(a for a in engine.state.actors.values() if a.entity_id != LEFT)
        reserve(engine, other, "poisoned", source, amount)
        if active:
            engine._apply_condition(target, "condition:typed.poisoned", "test:poison", LEFT, expires_on=None)
        te.block_remove_condition(context(engine, target), {"condition": " Poisoned ", "applies_to": "target"})
    on_hold(monkeypatch, cure)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[LEFT]
    pending = [c for c in target.conditions.values() if c.condition_id == DELAY]
    assert [(c.data["condition"], c.data["reserve"]) for c in pending] == [("stunned", amount)]
    assert not any(c.condition_id == "condition:typed.poisoned" for c in target.conditions.values())
    assert sum(c.condition_id == DELAY for a in loaded.engine.state.actors.values() for c in a.conditions.values()) == 2
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("spelling", ["POISONED", " condition:typed.poisoned "])
def test_request_is_normalized_before_active_condition_deleted(monkeypatch, spelling):
    e = duel([])
    actor = e.state.actors[ME]
    e._apply_condition(actor, "condition:typed.poisoned", "test:poison", FOE, expires_on=None)
    observed = []
    def inspect(ctx, target, name, cause):
        observed.append((target.entity_id, name, cause, ctx.source))
        assert any(c.condition_id == "condition:typed.poisoned" for c in target.conditions.values())
    install(monkeypatch, "te.condition_removal", inspect)
    te.block_remove_condition(context(e, actor), {"condition": spelling, "applies_to": "target", "cause": " DISPEL "})
    assert observed == [(ME, "poisoned", "dispel", "test:cure")]
    assert not any(c.condition_id == "condition:typed.poisoned" for c in actor.conditions.values())


@pytest.mark.parametrize("failure", ["pause", "invalid"])
def test_request_failure_rolls_back_reservation_release_and_cure(monkeypatch, failure):
    e = duel([])
    actor = e.state.actors[ME]
    reserve(e, actor, "poisoned", DURABLE, 10)
    e._apply_condition(actor, "condition:typed.poisoned", "test:poison", FOE, expires_on=None)
    class NeedsChoice(Exception):
        pass
    def fail(ctx, target, name, cause):
        cancel_pending(ctx, target, name, cause)
        if failure == "pause":
            raise NeedsChoice()
        return True
    install(monkeypatch, "te.condition_removal", fail)
    before = e.state.model_dump(mode="json")
    with pytest.raises(NeedsChoice if failure == "pause" else ValueError):
        with e._transaction("test:cure", "test:cure", ME):
            te.block_remove_condition(context(e, actor), {"condition": "poisoned", "applies_to": "target"})
    assert e.state.model_dump(mode="json") == before


def test_different_cause_and_empty_request_do_not_cancel_pending(monkeypatch):
    e = duel([])
    actor = e.state.actors[ME]
    reserve(e, actor, "poisoned", DURABLE, 10)
    install(monkeypatch, "te.condition_removal", cancel_pending)
    for name, cause in [("poisoned", "expiry"), ("none", "cure"), ("", "cure")]:
        te.block_remove_condition(context(e, actor), {"condition": name, "cause": cause, "applies_to": "target"})
    assert len([c for c in actor.conditions.values() if c.condition_id == DELAY]) == 1
