"""Internal Echo detonates on a Reaction and on a Cultivation Point spend outside any Action (combat/ext/tripwires.py)."""
import pytest

from tests.test_riders_c7 import DRUM, FOE, ME, _drum, script, turn, unarmed, use
from combat.ext import tripwires

ECHOING = "condition:typed.echoing"


def _echoed():
    # Public CI substitutes a minimal authority; install the test's resource pool
    # explicitly rather than relying on private compiled resource rows.
    engine, me, foe = _drum(["internal_echo"], picks={"path_hit." + DRUM + "internal_echo": ["Use Internal Echo"]}, beats=0)
    me.resources["resource:named.body_beat"] = 2
    me.resource_maximums["resource:named.body_beat"] = 2
    foe.resources["resource:core.stamina"] = 10
    foe.resource_maximums["resource:core.stamina"] = 10
    script(engine, [18, *([1] * 80)])
    use(engine, unarmed(engine), target=FOE)
    held = next(c for c in foe.conditions.values() if c.condition_id == ECHOING)
    return engine, me, foe, held


def _thunder(engine, start):
    return [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and str((e.payload or {}).get("damage_type")).upper() == "THUNDER"]


def test_the_echo_carries_every_trigger_kind():
    _, _, _, held = _echoed()
    assert set(held.data["trips_on"]) == {"action", "bonus_action", "reaction", "cp_spend"}


def test_paid_reaction_detonates_after_cost_and_before_effects():
    from combat.typed_reactions import _open, _spend_generic

    engine, me, foe, _ = _echoed()
    resource = next(key for key in ("resource:core.stamina", "resource:core.qi", "resource:core.resonance") if foe.resources.get(key, 0) > 0)
    row = {"feature_id": "test.reaction", "name": "Test reaction", "costs": [{"resource_id": resource, "amount": 1}]}
    before = foe.resources[resource]
    start, hp = len(engine.events), foe.current_hp
    _open(engine, row, foe, (me.entity_id,), "TEST")
    can_continue = _spend_generic(engine, foe, row)
    thunder = _thunder(engine, start)
    debit = next(i for i, e in enumerate(engine.events[start:], start) if e.event_type == "RESOURCE_SPENT" and (e.payload or {}).get("resource_id") == resource)
    assert foe.resources[resource] == before - 1 and foe.current_hp < hp
    assert len(thunder) == 1 and debit < engine.events.index(thunder[0])
    assert not any(c.condition_id == ECHOING for c in foe.conditions.values())
    assert can_continue == foe.active


def test_lethal_reaction_detonation_spends_cost_but_stops_pending_effect():
    from combat.typed_reactions import _open, _spend_generic

    engine, me, foe, _ = _echoed()
    foe.current_hp = 1
    resource = next(key for key in ("resource:core.stamina", "resource:core.qi", "resource:core.resonance") if foe.resources.get(key, 0) > 0)
    row = {"feature_id": "test.reaction", "name": "Test reaction", "costs": [{"resource_id": resource, "amount": 1}]}
    before = foe.resources[resource]
    _open(engine, row, foe, (me.entity_id,), "TEST")
    pending_effect = []
    if _spend_generic(engine, foe, row):
        pending_effect.append("applied")
    assert pending_effect == []
    assert foe.resources[resource] == before - 1
    assert not foe.active
    assert me.active  # another ally keeps the fight from ending around the interruption


def test_a_cultivation_point_spend_outside_an_action_detonates_it_after_the_points_are_spent():
    engine, me, foe, _ = _echoed()
    resource = next(key for key in ("resource:core.stamina", "resource:core.qi", "resource:core.resonance") if foe.resources.get(key, 0) > 0)
    before = foe.resources[resource]
    start, hp = len(engine.events), foe.current_hp
    engine._spend_resource(foe, resource, 1, "test")
    assert foe.resources[resource] == before - 1 and foe.current_hp < hp
    assert len(_thunder(engine, start)) == 1 and not any(c.condition_id == ECHOING for c in foe.conditions.values())


def test_free_passive_trigger_does_not_count_as_taking_a_reaction():
    from combat.typed_reactions import reaction_paid

    engine, _, foe, _ = _echoed()
    hp, start = foe.current_hp, len(engine.events)
    assert reaction_paid(engine, foe, {"feature_id": "test.free_passive", "free": True, "costs": []})
    assert foe.current_hp == hp and any(c.condition_id == ECHOING for c in foe.conditions.values())
    assert not _thunder(engine, start)


def test_plugin_open_reaction_dispatches_tripwire():
    from combat.typed_reactions import open_reaction

    engine, me, foe, _ = _echoed()
    hp, start = foe.current_hp, len(engine.events)
    assert open_reaction(engine, {"feature_id": "athletics:sure_grip_catch", "name": "Sure Grip"},
                         foe, (me.entity_id,), "SURE_GRIP_FALL")
    assert foe.current_hp < hp and len(_thunder(engine, start)) == 1
    assert not any(c.condition_id == ECHOING for c in foe.conditions.values())


def test_zero_cost_reaction_detonates_echo():
    from combat.typed_reactions import reaction_paid

    engine, _, foe, _ = _echoed()
    hp, start = foe.current_hp, len(engine.events)
    assert reaction_paid(engine, foe, {"feature_id": "test.free_reaction", "costs": []})
    assert foe.current_hp < hp and len(_thunder(engine, start)) == 1
    assert not any(c.condition_id == ECHOING for c in foe.conditions.values())


def test_native_paid_reaction_completion_dispatches_reaction_trigger():
    from combat.activation_payments import reaction_completed

    engine, _, foe, _ = _echoed()
    hp, start = foe.current_hp, len(engine.events)
    assert reaction_completed(engine, foe, "reaction:an_eui.sheath_bone_guard")
    assert foe.current_hp < hp and len(_thunder(engine, start)) == 1
    assert not any(c.condition_id == ECHOING for c in foe.conditions.values())


@pytest.mark.parametrize("inner_result", [True, False])
def test_native_attack_scope_forwards_the_attack_continuation_result(monkeypatch, inner_result):
    from combat import native_reactions, typed_reactions

    engine, me, foe, _ = _echoed()
    monkeypatch.setattr(typed_reactions, "reaction_paid", lambda *_args, **_kwargs: inner_result)
    with native_reactions.attack_scope(engine, foe, me, "system:combat.opportunity_attack",
                                      "Opportunity Attack") as can_continue:
        assert can_continue is inner_result


def test_spending_something_that_is_not_a_cultivation_point_does_not_detonate_it():
    engine, me, foe, _ = _echoed()
    hp = foe.current_hp
    engine._append_event("RESOURCE_SPENT", "test", actor_id=FOE, payload={"resource_id": "resource:named.body_beat", "amount": 1, "remaining": 0})
    assert foe.current_hp == hp and any(c.condition_id == ECHOING for c in foe.conditions.values())
