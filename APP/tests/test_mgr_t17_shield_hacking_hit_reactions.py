"""Post-roll AC grants must enter Shield-Hacking's one-bonus denial.

Synthetic reaction rows exercise the three native hit-reaction producers through
execute_intent, including final hit/damage resolution rather than only AC hooks.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_mgr_t17_shield_hacking_rhythm as base

ALLY = "actor:test.late_guard_ally"
GUARD = "condition:typed.vessel_guarded"
REACTION = "test:late_guard"
POOL = "resource:core.stamina"
BONUS = 5


def _fight(monkeypatch):
    ally = compile_character(base.t._sheet("", (), {}), actor_id=ALLY)
    engine = Gate4ControllerEngine(
        base.ROOT, match_seed="MGR17-LATE-AC",
        typed_bundles=(base._saber_bundle(), base._foe_bundle(shield=False), ally),
        roster_setup={
            "primary_actor_ids": [base.ME, base.AN, ALLY],
            "team_by_actor": {base.ME: "team:a", base.AN: "team:b", ALLY: "team:b"},
            "starting_positions": {base.ME: {"x": 3, "y": 6}, base.AN: {"x": 4, "y": 6},
                                   ALLY: {"x": 5, "y": 6}}})
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


def _attack(engine, name="Forward Cut"):
    base._ready(engine)
    start = len(engine.events)
    base._use(engine, name)
    events = engine.events[start:]
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == base.ME)
    return roll, events


def _denied(foe):
    return any(c.condition_id == base.CONDITION for c in foe.conditions.values())


def _reaction(engine, kind, *, reduction=0, penalty=0):
    owner = ALLY if kind == "ally_hit" else base.AN
    reactor = engine.state.actors[owner]
    reactor.reaction_available = True
    reactor.resources[POOL] = 10
    row = {"feature_id": REACTION, "name": "Late Guard", "resource_id": POOL}
    if kind == "hit_ac":
        row.update(block="hit_ac", cost=1, ac=BONUS)
    else:
        effects = [{"type": "ac_bonus", "amount": BONUS}]
        if reduction:
            effects.append({"type": "damage_modifier", "applies_to": "self", "amount": reduction})
        if penalty:
            effects.append({"type": "attack_modifier", "applies_to": "attacker", "amount": penalty})
        row.update(block="generic", kind=kind, costs=[{"resource_id": POOL, "amount": 1}],
                   range_ft=30, effects=effects)
    engine.typed_reaction_rows[owner] = [row]
    return reactor


@pytest.mark.parametrize("kind", ["hit_ac", "hit", "ally_hit"])
@pytest.mark.parametrize("denial", [False, True], ids=["ordinary-defense", "paid-denial"])
def test_new_hit_reaction_bonus_is_denied_once_without_destroying_it(monkeypatch, kind, denial):
    engine, me, foe = _fight(monkeypatch)
    # The qualifying one-attack guard disappears on the first hit. Thus the
    # consuming attack has no bonus at roll time: its only defense arrives later.
    engine._apply_condition(foe, GUARD, "system:test.guard", base.AN,
                            expires_on="START_OF_SELF_NEXT_TURN", data={"label": "Guarding Vessel"})
    first, _ = _attack(engine, base.RHYTHM if denial else "Forward Cut")
    assert not any(c.condition_id == GUARD for c in foe.conditions.values())
    assert _denied(foe) is denial
    assert me.resources[base.EDGE] == (0 if denial else 1)
    foe.armor_class = int(first.payload["modified_total"])
    reactor = _reaction(engine, kind)

    roll, events = _attack(engine)

    assert roll.payload["provisional_hit"] is True
    assert roll.payload["target_ac"] == foe.armor_class
    resolved = next(e for e in events if e.event_type == "REACTION_RESOLVED"
                    and e.source_definition_id == REACTION)
    assert resolved.payload["new_ac"] == foe.armor_class + (0 if denial else BONUS)
    assert resolved.payload["hit_after_recheck"] is denial
    assert any(e.event_type == "DAMAGE_COMMITTED" and base.AN in e.target_ids for e in events) is denial
    assert reactor.resources[POOL] == 9 and not reactor.reaction_available
    assert not _denied(foe)
    removed = [e for e in events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("condition_id") == base.CONDITION]
    assert len(removed) == int(denial)
    # The temporary bonus itself survives; only its application to this one
    # attack was lost. The next attack misses against that same grant.
    assert sum(int(m.value) for m in foe.modifiers.values() if m.source_definition_id == REACTION) == BONUS
    following, events = _attack(engine)
    assert following.payload["target_ac"] == foe.armor_class + BONUS
    assert following.payload["provisional_hit"] is False
    assert not any(e.event_type == "DAMAGE_COMMITTED" and base.AN in e.target_ids for e in events)


@pytest.mark.parametrize("kind", ["hit", "ally_hit"])
def test_configured_hit_can_qualify_from_a_defense_raised_after_the_roll(monkeypatch, kind):
    engine, me, foe = _fight(monkeypatch)
    base._configure_shield_hacking(engine)
    # A mixed guard/reduction reaction is worth using even when its AC cannot
    # flip the hit. No guard/shield/temporary AC exists until that reaction.
    _reaction(engine, kind, reduction=1)

    _, events = _attack(engine)

    assert engine.__dict__["_shield_hacking_attack"][3] is False
    resolved = next(e for e in events if e.event_type == "REACTION_RESOLVED"
                    and e.source_definition_id == REACTION)
    assert resolved.payload["hit_after_recheck"] is True
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in events)
    assert me.resources[base.EDGE] == 0
    assert any(e.event_type == "SAVE_ROLLED" and not e.payload["success"] for e in events)
    assert _denied(foe)


def test_denial_does_not_remove_a_reactions_attack_penalty(monkeypatch):
    engine, _, foe = _fight(monkeypatch)
    engine._apply_condition(foe, GUARD, "system:test.guard", base.AN,
                            expires_on="START_OF_SELF_NEXT_TURN", data={"label": "Guarding Vessel"})
    first, _ = _attack(engine, base.RHYTHM)
    foe.armor_class = int(first.payload["modified_total"])
    _reaction(engine, "hit", penalty=2)

    _, events = _attack(engine)

    resolved = next(e for e in events if e.event_type == "REACTION_RESOLVED"
                    and e.source_definition_id == REACTION)
    assert resolved.payload["new_ac"] == foe.armor_class + 2
    assert resolved.payload["hit_after_recheck"] is False
    assert not _denied(foe)
    assert not any(e.event_type == "DAMAGE_COMMITTED" and base.AN in e.target_ids for e in events)
