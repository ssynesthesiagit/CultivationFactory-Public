"""Per-activation flat bonuses (Qi Technique Potency) land on one damage roll for the whole activation."""
import pytest

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


def _add_mixed_delivery_probe(bundles):
    from combat.canonical import canonical_sha256
    from tests import r1i_service_support as support

    source = "tianxia.path.qi_cultivation.feature.test_mixed_potency"
    owner = next(bundle for bundle in bundles if bundle["actor_id"] == support.OWNER)
    owner["action_catalog"].append({
        "source_definition_id": source, "display_name": "Mixed Potency Technique",
        "owner_id": support.OWNER, "economy": "ACTION", "resolution_kind": "TYPED",
        "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "parameters": {"typed": {
            "source": source,
            "numbers": {"cl": 6, "pb": 4, "save_dc": 18, "attack_bonus": 100, "potency": 4},
            "weapon": {"damage": {"count": 1, "sides": 4, "modifier": 0}, "damage_type": "SLASHING"},
            "duration": {"kind": "instant"},
            "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": [
                {"type": "damage", "weapon_damage": True},
                {"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6},
                 "damage_types": ["force"]}]}]},
            "expected_damage": 8}})
    owner["actor_template"]["action_ids"].append(source)
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)


@pytest.mark.parametrize(("packet", "expression"), [
    ("technique damage roll", "1d6"),
    ("weapon damage roll", "1d4"),
])
def test_mixed_delivery_potency_choice_commits_and_survives_reload(tmp_path, packet, expression):
    from tests import r1i_service_support as support
    from tests.test_devil_qi_augment_service import cold, chosen_response

    combat, table, mid, _, _ = support.fixture(
        tmp_path, [], bundle_transform=_add_mixed_delivery_probe)
    candidate = support.candidate(table, mid, "Mixed Potency Technique", support.FOE)
    answers = []
    for _ in range(8):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, answers)
        answers = []
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert "Qi Technique Potency" in str(prompt)
        answers = [chosen_response(result, packet)]
    else:
        raise AssertionError("mixed packet decision did not commit")

    engine = cold(combat, tmp_path, mid)
    rolls = [roll for roll in engine.rolls if str(roll.reason).startswith("DAMAGE")]
    assert len(rolls) == 2
    assert sum(roll.modifier == 4 for roll in rolls) == 1
    assert next(roll for roll in rolls if roll.expression.startswith(expression)).modifier == 4


def test_the_once_per_activation_clause_is_automated_not_a_gm_rider():
    # The attack-path clause above is automated by the typed record, so the authority must not still ask the GM to add it.
    from combat.typed_numbers import authority_mechanics

    row = authority_mechanics()["tianxia.path.qi_cultivation.feature.qi_technique_potency"]
    assert not any(rider.startswith("Once per activation, when a Qi-powered feature deals damage") for rider in row.get("riders") or [])
    assert row.get("effects"), "the potency clause must stay typed as an effect"
