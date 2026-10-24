"""Per-activation flat bonuses (Qi Technique Potency) land on one damage roll for the whole activation."""
from tests.test_typed_executor import _engine_with, _intent


def _activation(attacks, extra=()):
    cut = {"effects": [{"type": "attack", "attack_kind": "weapon", "count": attacks,
                        "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["FORCE"]}, *extra]}],
           "numbers": {"pb": 6, "save_dc": 17, "attack_bonus": 30, "key_mod": 4, "potency": 4},
           "weapon": {"damage": {"count": 1, "sides": 4, "modifier": 0}, "damage_type": "SLASHING"},
           "duration": {"kind": "instant"}}
    engine, _ = _engine_with(cut, "POTENCY-ONCE")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    return [r for r in engine.rolls if str(r.reason).startswith("DAMAGE") and r.expression.startswith("1d6")]


def test_a_multi_attack_activation_adds_potency_to_one_damage_roll():
    rolls = _activation(3)
    assert len(rolls) >= 2
    assert sum(1 for r in rolls if r.modifier == 4) == 1


def test_a_single_attack_still_gets_potency():
    rolls = _activation(1)
    assert [r.modifier for r in rolls] == [4]


def test_a_later_damage_effect_of_the_same_activation_does_not_add_it_again():
    cut = {"effects": [{"type": "attack", "attack_kind": "weapon", "count": 1,
                        "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["FORCE"]}]},
                       {"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["COLD"]}],
           "numbers": {"pb": 6, "save_dc": 17, "attack_bonus": 30, "key_mod": 4, "potency": 4},
           "weapon": {"damage": {"count": 1, "sides": 4, "modifier": 0}, "damage_type": "SLASHING"},
           "duration": {"kind": "instant"}}
    engine, _ = _engine_with(cut, "POTENCY-ONCE")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    rolls = [r for r in engine.rolls if str(r.reason).startswith("DAMAGE")]
    assert len(rolls) == 2 and sum(r.modifier for r in rolls) == 4


def test_the_once_per_activation_clause_is_automated_not_a_gm_rider():
    # The attack-path clause above is automated by the typed record, so the authority must not still ask the GM to add it.
    from combat.typed_numbers import authority_mechanics

    row = authority_mechanics()["tianxia.path.qi_cultivation.feature.qi_technique_potency"]
    assert not any(rider.startswith("Once per activation, when a Qi-powered feature deals damage") for rider in row.get("riders") or [])
    assert row.get("effects"), "the potency clause must stay typed as an effect"
