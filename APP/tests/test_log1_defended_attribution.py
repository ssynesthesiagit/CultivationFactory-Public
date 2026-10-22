"""Named riders preserve catalog defenses across table commit and fresh reload."""
import pytest

from combat.typed_executor import Context
from tests import test_p4_void_needle as fixture


@pytest.mark.parametrize("defense,bypass", [("resistance", False), ("immunity", False),
                                           ("reduction", False), ("resistance", True)])
def test_named_damage_matches_unattributed_delivery(tmp_path, monkeypatch, defense, bypass):
    compile_original = fixture.compile_character
    # Nullifying Strike now retains all three printed damage types; isolate
    # attribution with matching defenses and bypasses for every possible type.
    damage_types = ["PIERCING", "BLUDGEONING", "SLASHING", "FORCE", "NECROTIC", "PSYCHIC"]

    def compile_defended(doc, *, actor_id):
        bundle = compile_original(doc, actor_id=actor_id)
        # Synthetic compiled defense isolates the source-sensitive engine contract.
        if actor_id == fixture.FOE:
            bundle["typed_passives"].append({"feature_id": "test.attack_defense", "block": "defense",
                "kind": defense, "damage_types": damage_types,
                "attacks_only": True, "attack_kinds": ["unarmed", "weapon", "melee"], "amount": 1})
        elif bypass:
            for action in bundle["action_catalog"]:
                action["parameters"]["typed"]["effects"].append({"type": "ignore_resistance",
                    "damage_types": damage_types})
        return bundle

    monkeypatch.setattr(fixture, "compile_character", compile_defended)
    named, _ = fixture.cast(tmp_path / "named", monkeypatch, "Cost Lock", "Hollowed", hidden=True, ruin=True)
    monkeypatch.setattr(Context, "with_source", lambda self, source: self)
    baseline, _ = fixture.cast(tmp_path / "baseline", monkeypatch, "Cost Lock", "Hollowed", hidden=True, ruin=True)
    def damage(boundary):
        return [(e["source_definition_id"], e["payload"]["hp_damage"], e["payload"]["remaining_hp"])
                for e in boundary["events"] if e["event_type"] == "DAMAGE_COMMITTED"]
    assert damage(named) == damage(baseline)
    packets = [e for e in named["events"] if e["event_type"] == "DAMAGE_COMMITTED"]
    riders = [e for e in packets if e["payload"].get("display_source_id") in
              (f"passive:{fixture.HIDDEN}", "passive:TAL_VOID_NULLIFYING_STRIKE")]
    assert len(riders) == 2
    assert all(not e["source_definition_id"].startswith("passive:") for e in riders)
    if defense == "immunity":
        assert all(e["payload"]["hp_damage"] == 0 for e in riders)
    elif bypass:
        assert [e["payload"]["hp_damage"] for e in riders] == [2, 2]
    else:
        assert [e["payload"]["hp_damage"] for e in riders] == [1, 1]
