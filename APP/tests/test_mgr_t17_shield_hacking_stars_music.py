"""Real Stars/Music AC providers qualify and lose only their next application."""
import pytest

from combat.ext import music, stars
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_mgr_t17_shield_hacking_rhythm as base

CONSTELLATION = "tianxia.talent.stars.constellation_guard"
COURAGE = "tianxia.talent.music.soul_stirring_refrain"
GUARD = "condition:typed.state.constellation_guard"


def _fight(monkeypatch, *, guard_owner=True):
    foe_bundle = (compile_character(base.t._sheet("tianxia.sphere.stars", [CONSTELLATION], {}), actor_id=base.AN)
                  if guard_owner else base._foe_bundle(shield=False))
    engine = Gate4ControllerEngine(
        base.ROOT, match_seed="MGR17-STARS-MUSIC",
        typed_bundles=(base._saber_bundle(), foe_bundle),
        roster_setup={"primary_actor_ids": [base.ME, base.AN],
                      "team_by_actor": {base.ME: "team:a", base.AN: "team:b"},
                      "starting_positions": {base.ME: {"x": 3, "y": 6}, base.AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(base.ME)
    engine.state.current_actor_id = base.ME
    engine._system_start_turn()
    me, foe = engine.state.actors[base.ME], engine.state.actors[base.AN]
    me.resources[base.EDGE] = 1
    foe.armor_class = -50
    foe.maximum_hp = foe.current_hp = 1000

    def die(sides):
        counter = engine.roller.counter
        engine.roller.counter += 1
        return (10 if sides == 20 else 1), counter

    monkeypatch.setattr(engine.roller, "_die", die)
    return engine, me, foe


def _grant(engine, foe, provider, *, stars_left=7):
    # Synthetic active-state fixtures use the native providers, including the
    # owned Stars row, instance-bound star count, and Courage condition rule.
    if provider == "stars":
        engine._apply_condition(foe, GUARD, CONSTELLATION, base.AN,
                                expires_on="CONCENTRATION_END", data={"label": "Constellation Guard"})
        held = next(c for c in foe.conditions.values() if c.condition_id == GUARD)
        foe.turn_flags[stars.GUARD_STARS] = f"{held.instance_id}:{stars_left}"
    else:
        engine._apply_condition(foe, "condition:typed.music_courage", COURAGE, base.AN,
                                expires_on="CONCENTRATION_END",
                                data={"label": "Courage", "rule": {"music_ac": 1, "condition_immunities": ["frightened"]}})


def _bonus(engine, foe, provider):
    return stars.guard_ac(engine, foe) if provider == "stars" else music.music_ac(engine, foe)


def _attack(engine, name="Forward Cut"):
    base._ready(engine)
    start = len(engine.events)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name == name and tuple(c.target_ids) == (base.AN,))
    engine.execute_intent(ActionIntent(
        intent_id=f"intent:stars-music:{start}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=base.ME, target_ids=candidate.target_ids))
    events = engine.events[start:]
    assert any(e.event_type == "DAMAGE_COMMITTED" and base.AN in e.target_ids for e in events)
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == base.ME)
    return roll, events


def _denied(foe):
    return any(c.condition_id == base.CONDITION for c in foe.conditions.values())


@pytest.mark.parametrize("provider, amount", [("stars", 2), ("courage", 1)])
@pytest.mark.parametrize("configured", [False, True], ids=["variant", "configured"])
def test_provider_qualifies_and_only_the_consuming_attack_loses_ac(monkeypatch, provider, amount, configured):
    engine, me, foe = _fight(monkeypatch)
    _grant(engine, foe, provider)
    assert _bonus(engine, foe, provider) == amount
    assert engine._ac_modifier(foe) == amount
    assert base.RHYTHM in base._names(engine)
    if configured:
        base._configure_shield_hacking(engine)

    first, events = _attack(engine, "Forward Cut" if configured else base.RHYTHM)

    assert first.payload["target_ac"] == foe.armor_class + amount
    assert me.resources[base.EDGE] == 0
    assert any(e.event_type == "SAVE_ROLLED" and not e.payload["success"] for e in events)
    assert _denied(foe)
    consuming, events = _attack(engine)
    assert consuming.payload["target_ac"] == foe.armor_class
    assert len([e for e in events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("condition_id") == base.CONDITION]) == 1
    assert not _denied(foe)
    assert _bonus(engine, foe, provider) == amount
    following, _ = _attack(engine)
    assert following.payload["target_ac"] == foe.armor_class + amount


@pytest.mark.parametrize("provider, amount", [("stars", 2), ("courage", 1)])
def test_held_denial_takes_a_provider_added_after_a_different_qualifying_defense(monkeypatch, provider, amount):
    engine, me, foe = _fight(monkeypatch)
    old_guard = "test:earlier_guard"
    base._add_defence(engine, foe, 3, source=old_guard)
    _attack(engine, base.RHYTHM)
    assert _denied(foe) and me.resources[base.EDGE] == 0
    for iid, modifier in list(foe.modifiers.items()):
        if modifier.source_definition_id == old_guard:
            del foe.modifiers[iid]
    _grant(engine, foe, provider)
    assert _bonus(engine, foe, provider) == amount

    consuming, _ = _attack(engine)

    assert consuming.payload["target_ac"] == foe.armor_class
    assert not _denied(foe)
    assert _bonus(engine, foe, provider) == amount


@pytest.mark.parametrize("inactive", ["exhausted-stars", "unowned-guard", "suppressed-courage"])
def test_inactive_provider_neither_qualifies_nor_consumes_a_held_denial(monkeypatch, inactive):
    engine, me, foe = _fight(monkeypatch, guard_owner=inactive != "unowned-guard")
    if inactive == "suppressed-courage":
        _grant(engine, foe, "courage")
        next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.music_courage").data["suppressed"] = True
    else:
        _grant(engine, foe, "stars", stars_left=0 if inactive == "exhausted-stars" else 7)
        assert stars.guard_ac(engine, foe) is None
    assert engine._ac_modifier(foe) == 0
    assert base.RHYTHM not in base._names(engine)
    base._configure_shield_hacking(engine)

    _, events = _attack(engine)

    assert me.resources[base.EDGE] == 1
    assert not any(e.event_type == "SAVE_ROLLED" for e in events)
    assert not _denied(foe)
    engine._apply_condition(foe, base.CONDITION, base.TALENT, base.ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Shield-Hacking Rhythm"})
    consuming, _ = _attack(engine)
    assert consuming.payload["target_ac"] == foe.armor_class
    assert _denied(foe)  # No real bonus was applied, so the denial is still held.
    if inactive == "exhausted-stars":
        held = next(c for c in foe.conditions.values() if c.condition_id == GUARD)
        foe.turn_flags[stars.GUARD_STARS] = f"{held.instance_id}:1"
        assert stars.guard_ac(engine, foe) == 2
        consuming, _ = _attack(engine)
        assert consuming.payload["target_ac"] == foe.armor_class
        assert not _denied(foe)
        assert stars.guard_stars(engine, foe) == 0  # Damage extinguishes the final star normally.
