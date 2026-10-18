"""Guard ordinary scalar damage against accidental component-pipeline opt-in."""
from types import SimpleNamespace

from combat.attack_components import collect, needs_component_settlement
from combat.ext.dreamweaver import REFUGE_ON, refuge_resistance_scalar


def test_homogeneous_unarmed_damage_keeps_legacy_scalar_settlement():
    parts = collect(3, "BLUDGEONING", [{"amount": 5, "damage_type": "BLUDGEONING"}])
    assert sum(part["amount"] for part in parts) == 8
    assert not needs_component_settlement(parts)


def test_ordinary_unarmed_hit_settles_homogeneous_components_through_engine():
    # Exercise the confirmed-hit engine path, not just the component selector:
    # defenses and HP settlement must retain the ordinary scalar result.
    from combat.gate2_runtime_models import ActionIntent, DiceSpec
    from tests.h1_support import FOE, ME, duel, script

    engine = duel([], seed="STONE-FIST-HOMOGENEOUS-UNARMED")
    striker, target = engine.state.actors[ME], engine.state.actors[FOE]
    hp_before = target.current_hp
    script(engine, [10, 4])
    intent = ActionIntent(
        intent_id="ordinary-unarmed", decision_id="test", candidate_id="test",
        state_version=engine.state.state_version, actor_id=ME, target_ids=(FOE,),
    )
    hit = engine._resolve_attack_spec(
        striker, target,
        {
            "attack_bonus": 100, "damage": DiceSpec(count=1, sides=4, modifier=0),
            "damage_type": "BLUDGEONING", "attack_kind": "unarmed",
            "damage_components": [{"amount": 2, "damage_type": "BLUDGEONING"}],
            "reach_ft": 5,
        },
        intent, source_definition_id="action:core.unarmed_strike",
    )
    assert hit
    assert target.current_hp == hp_before - 6
    damage = [event for event in engine.events if event.event_type == "DAMAGE_APPLIED"][-1]
    assert damage.payload["amount"] == 6


def test_mixed_or_explicitly_permitted_damage_uses_component_settlement():
    mixed = collect(3, "BLUDGEONING", [{"amount": 5, "damage_type": "FORCE"}])
    permitted = collect(3, "BLUDGEONING", [{"amount": 5, "damage_type": "BLUDGEONING",
                                             "ignore_resistance": True}])
    assert needs_component_settlement(mixed)
    assert needs_component_settlement(permitted)


def test_dream_refuge_scalar_resistance_is_gated_to_its_condition():
    engine = object()
    target = SimpleNamespace(conditions={"refuge": SimpleNamespace(condition_id=REFUGE_ON)})
    assert refuge_resistance_scalar(engine, target, 7, "BLUDGEONING", "attack", "attacker") == 4
    assert refuge_resistance_scalar(engine, target, 7, "FORCE", "attack", "attacker") is None
    target.conditions.clear()
    assert refuge_resistance_scalar(engine, target, 7, "BLUDGEONING", "attack", "attacker") is None
