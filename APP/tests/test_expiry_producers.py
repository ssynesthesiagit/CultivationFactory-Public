"""Relevant-only expiry contracts at shipped-data and saved-bundle boundaries."""
import json
from pathlib import Path

import pytest

from combat import summons, typed_executor as te, zones
from combat.gate2_engine import Gate2Engine
from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.saved_fight_format import UnsupportedSavedFight

ROOT = Path(__file__).resolve().parents[1]
EXPIRY_TYPES = (
    "ac_bonus",
    "adorn_aura",
    "advantage",
    "alchemy_saint_con_save",
    "apply_slam",
    "blacksmith_temper",
    "blood_moon_execution",
    "brute_daze",
    "compass_approach_rider",
    "compass_depart_rider",
    "compass_turn_field",
    "condition",
    "conditional_damage",
    "cost_reduction",
    "deny_invisible",
    "deny_reactions_against",
    "deny_temp_hp",
    "destructive_blast_damage",
    "directed_forced_movement",
    "disadvantage",
    "dream_confront",
    "dream_curse_intervene",
    "dream_seed",
    "dreamweaver_refuge_sleep",
    "drowsy",
    "exposed",
    "flustered",
    "form_rider",
    "guard_against",
    "hammer_rebuke_no_oa",
    "handspan_palm",
    "harvest_execute",
    "harvest_pulse",
    "heal_to_half",
    "healing_reduction",
    "heaven_clinch_save",
    "ignore_oa_from_target",
    "immunity",
    "jester_foil",
    "jester_foil_pair",
    "mandate_vessel",
    "mantra_silence_relief",
    "mark",
    "next_d20_mode",
    "ongoing",
    "plant_dream_seed",
    "poison_next_check",
    "pp_dazed",
    "pressure_point_attack",
    "protection_aegis",
    "qi_pulse_calm",
    "qi_pulse_rage",
    "qi_pulse_sorrow",
    "reaction_denied",
    "resist_ability",
    "resistance",
    "resource_capacity",
    "rider_repeat_group",
    "shadow_long_road",
    "singleton_benefit",
    "soul_contract_procedure",
    "speed",
    "spiritual_pressure",
    "standing_burden",
    "state",
    "suppress_regeneration",
    "suppress_resistance",
    "temp_hp",
    "thorn_bleeding",
    "treasure_dream_damage",
    "treasure_flame_damage",
    "treasure_frost",
    "treasure_frost_damage",
    "treasure_spirit_damage",
    "veil_escape_move",
    "vessel_tension",
    "void_pressure",
    "vulnerability",
    "warleader_reservoir",
    "water_healing_denial",
    "weapons_item_disrupted",
    "yang_completion_damage",
)


def _objects(node, pointer=""):
    if isinstance(node, dict):
        yield pointer, node
        for key, child in node.items():
            yield from _objects(child, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _objects(child, f"{pointer}/{index}")


def _bundle(actor_id, typed):
    source = f"action:{actor_id}"
    return {
        "actor_id": actor_id,
        "actor_template": {
            "entity_id": actor_id, "display_name": actor_id, "team_id": f"team:{actor_id}",
            "primary_combatant": True, "armor_class": 10, "maximum_hp": 100,
            "speed_ft": 30, "initiative_bonus": 0, "dexterity_score": 10,
            "proficiency_bonus": 2,
            "saving_throws": {ability: -100 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")},
            "resources": [], "action_ids": [source], "reaction_ids": [],
        },
        "action_catalog": [{
            "source_definition_id": source, "display_name": "Synthetic action",
            "owner_id": actor_id, "economy": "ACTION", "resolution_kind": "TYPED",
            "target_kind": "HOSTILE_ENTITY", "range_ft": 5, "parameters": {"typed": typed},
        }],
    }


def test_shipped_rules_are_sealed_and_their_effects_reach_resolution():
    # This census includes data producers, not just Python dict literals.
    rows = []
    for path in sorted((ROOT / "combat/rules").rglob("*.json")):
        for pointer, row in _objects(json.loads(path.read_text())):
            if "type" in row:
                assert "expiry_turn" in row, (path.name, pointer)
                assert row["expiry_turn"] is None or isinstance(row["expiry_turn"], dict), (path.name, pointer)
                rows.append(row)
    assert rows

    typed = {"source": "synthetic:rules", "effects": [], "riders": [],
             "duration": {"kind": "instant"}, "numbers": {"pb": 2, "save_dc": 1000}}
    bundles = tuple(_bundle(actor_id, typed) for actor_id in ("owner", "target"))
    engine = Gate2Engine(ROOT, match_seed="EXPIRY-RULE-PRODUCERS", typed_bundles=bundles,
                        roster_setup={"primary_actor_ids": ["owner", "target"],
                                      "team_by_actor": {"owner": "a", "target": "b"},
                                      "starting_positions": {"owner": {"x": 3, "y": 6}, "target": {"x": 4, "y": 6}}})
    owner, target = (engine.state.actors[key] for key in ("owner", "target"))
    action = engine.action_catalog["action:owner"]
    ctx = te.Context(engine, owner, action, None, typed, [target], target)
    terrains = zones.terrain_rules()["terrains"]
    fire = terrains["fire terrain"]["enter_start"]
    te.run_effects(ctx, fire["on_fail"])
    te.run_effects(ctx, fire["on_success"])
    te.run_effects(ctx, terrains["ash terrain"]["move_through"]["on_fail"])
    for name in ("burning", "kindled", "reaction_denied"):
        assert any(c.condition_id == te.CONDITION_PREFIX + name for c in target.conditions.values())

    creature = next(row for row in summons.rules()["creatures"].values()
                    if any(special["id"] == "grapple" for special in row.get("specials", [])))
    grapple = next(row for row in creature["specials"] if row["id"] == "grapple")
    te.run_effects(ctx, grapple["effects"])
    assert any(c.condition_id == te.CONDITION_PREFIX + "grappled" and c.expires_on == "UNTIL_REMOVED"
               for c in target.conditions.values())

    features = json.loads((ROOT / "combat/rules/feature_blocks.d/auto40_lightning.json").read_text())["features"]
    source = "TAL_LIGHTNING_SKY_FIRE_NERVE_NET"
    net = features[source]["effects"]
    te.run_effects(ctx.with_source(source), net)
    assert any(c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "reaction_denied"
               for c in target.conditions.values())
    assert any(c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "concentration_mode"
               for c in target.conditions.values())
    assert not any(event.event_type == "GM_RIDER" for event in engine.events)


@pytest.mark.parametrize("kind", EXPIRY_TYPES)
@pytest.mark.parametrize("location", ["action", "nested", "option", "rider"])
def test_saved_effect_requires_expiry_turn(tmp_path, kind, location):
    effect = {"type": kind}
    typed = {"source": "synthetic:saved_expiry", "effects": []}
    if location == "action":
        typed["effects"] = [effect]
    elif location == "nested":
        typed["effects"] = [{"type": "attack", "on_hit": [{"type": "save", "on_fail": [effect]}]}]
    elif location == "option":
        typed["options"] = [{"effects": [effect]}]
    else:
        typed["riders"] = [{"effects": [effect]}]
    bundle = _bundle("owner", typed)
    path = tmp_path / TYPED_BUNDLES_FILE
    path.write_text(json.dumps([bundle]))
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert f"effect {kind}" in str(caught.value.__cause__)
    assert "expiry_turn" in str(caught.value.__cause__)

    effect["expiry_turn"] = None
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)
