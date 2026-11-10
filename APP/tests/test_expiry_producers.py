"""Relevant-only expiry contracts at shipped-data and saved-bundle boundaries."""
import copy
import json
from pathlib import Path

import pytest

from combat import factory_compiler as compiler, summons, typed_executor as te, zones
from combat.expiry_data import derive_expiry, derive_expiry_turn, seal_expiry_data, seal_rules_expiry_data
from combat.gate2_runtime_models import ActionDefinition
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
            if key != "expiry":  # producer metadata is not a recursively sealed input
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
    # Match the producer's tagged-record contract (not an inference that every
    # type-bearing object is an executable effect), excluding expiry metadata.
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
    net = copy.deepcopy(features[source]["effects"])
    # Expiry metadata and all outcomes remain shipped data. Only this unrelated
    # prose selector is synthetic: public export scrambles the original "on".
    net[0]["on_fail"][1]["on"] = "next Concentration saving throw"
    te.run_effects(ctx.with_source(source), net)
    assert any(c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "reaction_denied"
               for c in target.conditions.values())
    assert any(c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "concentration_mode"
               for c in target.conditions.values())
    assert not any(event.event_type == "GM_RIDER" for event in engine.events)
    reaction = next(c for c in target.conditions.values()
                    if c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "reaction_denied")
    concentration = next(c for c in target.conditions.values()
                         if c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "concentration_mode")
    from combat.ext import effect_durations
    assert reaction.expires_on == effect_durations.token("start", target.entity_id, target.turns_started + 1)
    assert concentration.expires_on == effect_durations.token("end", target.entity_id, target.turns_started + 1)


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


def test_rules_seals_refresh_after_prose_edits(tmp_path):
    path = tmp_path / "rules.json"
    document = {
        "duration": {"kind": "special", "text": "The scene", "expiry": {}},
        "effects": [{"type": "condition", "condition": "frightened",
                     "evidence": "before your next turn", "expiry_turn": None}],
        "expiry": {"type": "not_an_effect"},
    }
    for text, duration_text in [("before your next turn", "The scene"),
                                ("until the end of your next turn", "Until destroyed"),
                                ("", "")]:
        document["effects"][0]["evidence"] = text
        document["duration"]["text"] = duration_text
        path.write_text(json.dumps(document))
        seal_rules_expiry_data(tmp_path)
        document = json.loads(path.read_text())
        effect = document["effects"][0]
        assert effect["expiry_turn"] == derive_expiry_turn(effect)
        assert document["duration"]["expiry"] == derive_expiry(
            {"kind": "special", "text": duration_text}, duration=True)["expiry"]
        assert document["expiry"] == {"type": "not_an_effect"}
        assert not any(pointer.startswith("/expiry") for pointer, _row in _objects(document))
        before = path.read_bytes()
        seal_rules_expiry_data(tmp_path)
        assert path.read_bytes() == before


def test_terrain_seals_include_typed_option_labels_and_diagnose_missing_data(monkeypatch):
    source = "synthetic:terrain_options"
    monkeypatch.setattr(compiler, "_rules_text", lambda: {
        source: "Choose one:\nPrinted: Creates difficult terrain."
    })
    mechanic = {
        "mechanic_id": source, "name": "Synthetic terrain",
        "description": ["Printed: Creates difficult terrain until the end of this turn."],
        "effects": [],
        "options": [{"label": "Reviewed", "effects": [
            {"type": "rider", "evidence": "Creates rubble until the start of your next turn."}
        ]}],
    }
    typed = {"option_label": "Reviewed", "duration": {"kind": "instant"},
             "effects": mechanic["options"][0]["effects"]}
    row = ActionDefinition.model_validate(_bundle("owner", typed)["action_catalog"][0])
    with pytest.raises(ValueError, match="terrain lifetime from synthetic:terrain_options: unsealed sentence"):
        compiler._zone_spec(row, mechanic, {})
    seal_expiry_data(mechanic)
    assert compiler._zone_spec(row, mechanic, {})["duration"]["kind"] == "until_start_of_next_turn"
    mechanic["options"] = []
    mechanic["description"] = []
    seal_expiry_data(mechanic)
    assert "terrain_expiry" not in mechanic["duration"]


@pytest.mark.parametrize("location", ["action", "effect", "nested", "option", "rider", "scaled"])
@pytest.mark.parametrize("text, expected", [("The scene", "UNTIL_REMOVED"), ("Until destroyed", None)])
def test_saved_special_duration_requires_expiry(tmp_path, location, text, expected):
    duration = {"kind": "special", "text": text}
    effect = {"type": "condition", "condition": "frightened", "expiry_turn": None, "duration": duration}
    typed = {"source": "synthetic:saved_duration", "effects": []}
    if location == "action":
        typed["duration"] = duration
    elif location == "effect":
        typed["effects"] = [effect]
    elif location == "nested":
        typed["effects"] = [{"type": "save", "on_fail": [effect]}]
    elif location == "option":
        typed["options"] = [{"duration": duration, "effects": []}]
    elif location == "rider":
        typed["riders"] = [{"duration": duration, "effects": []}]
    else:
        effect.pop("duration")
        effect["duration_by_cl"] = [[1, 20, duration]]
        typed["effects"] = [effect]
    bundle = _bundle("owner", typed)
    path = tmp_path / TYPED_BUNDLES_FILE
    path.write_text(json.dumps([bundle]))
    before = path.read_bytes()
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "duration special from action:owner: missing expiry" in str(caught.value.__cause__)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="duration special from action:owner: missing expiry"):
        te.duration_expiry(None, duration, source_id="action:owner")

    duration.update(derive_expiry(duration, duration=True))
    path.write_text(json.dumps([bundle]))
    loaded = load_typed_bundles(tmp_path)
    assert loaded == (bundle,)
    loaded_duration = next(row for _pointer, row in _objects(loaded[0]) if row.get("kind") == "special")
    assert te.duration_expiry(None, loaded_duration, source_id="action:owner") == expected
