"""On 2026-11-14 zone names came from prose: scrambled Lava Burst lost
Molten Terrain and a field merely mentioning terrain acquired it."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import factory_compiler as c
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, settle

AUTHORITY = json.loads((Path(__file__).resolve().parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
CREATES = {
    "ASH_BASE_ASHFALL": ["ash terrain"],
    "tianxia.talent.ash.court_of_the_last_ember": ["ash terrain"],
    "tianxia.talent.ash.heaven_cremating_ashstorm": ["ash terrain"],
    "tianxia.talent.ash.world_after_the_fire": ["ash terrain"],
    "FIRE_BASE_CONFLAGRATION": ["fire terrain"],
    "tianxia.talent.beauty.world_adorning_gesture": ["adorned terrain"],
    "TAL_MAGMA_BLACKGLASS_RIVER": ["molten terrain"],
    "TAL_MAGMA_CINDERGLASS_SHARDS": ["obsidian terrain"],
    "TAL_MAGMA_LAVA_BURST": ["molten terrain"],
    "TAL_MAGMA_LAVA_FLOW": ["molten terrain"],
    "TAL_MAGMA_OBSIDIAN_RAIN": ["obsidian terrain"],
    "TAL_MAGMA_VOLCANIC_ERUPTION": ["molten terrain"],
    "TAL_MAGMA_WORLD_BREAKING_ERUPTION": ["molten terrain"],
    "SAND_BASE_GATHER_SAND": ["shallow sand terrain"],
    "TAL_SAND_DEVOURING_DUNE_MOUTH": ["deep sand terrain"],
    "TAL_SAND_GLASS_DESERT_JUDGMENT": ["glass terrain"],
    "TAL_SAND_QUICKSAND_GATE": ["deep sand terrain"],
    "TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY": ["storming sand terrain"],
}
OPTIONS = {
    ("SAND_BASE_GATHER_SAND", "Gather Sand: move a square of sand"): [],
    ("TAL_SAND_DEVOURING_DUNE_MOUTH", "Devouring Dune Mouth: compress the dune"): [],
    ("FIRE_BASE_IGNITE", "Fire Terrain Square"): ["fire terrain"],
    ("TAL_SAND_THE_MOUNTAIN_REMEMBERS_IT_IS_DUST", "Bury the Line"): ["deep sand terrain", "storming sand terrain"],
    ("TAL_SAND_THE_MOUNTAIN_REMEMBERS_IT_IS_DUST", "Claim the Desert"): ["sand terrain"],
}
MENTIONS = {
    "TAL_GLASS_GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS", "TAL_GLASS_THOUSAND_PANE_PALACE",
    "TAL_MAGMA_SHAPE_THE_CRUST", "TAL_MAGMA_COURT_OF_THE_LIVING_VOLCANO",
    "TAL_MAGMA_FURNACE_STEP", "TAL_MAGMA_MAGMA_PRISON", "TAL_MAGMA_MANTLE_DRAGON_EMERGES",
    "TAL_SAND_COURT_OF_TEN_THOUSAND_DUNES", "TAL_SAND_DUNE_SEA_ADVANCE", "TAL_SAND_DUNE_SLIDE",
    "TAL_SAND_SAND_CLONE_DECOY", "TAL_SAND_SAND_DRAG", "TAL_SAND_SAND_NEEDLE_VOLLEY",
    "TAL_SAND_SAND_SOVEREIGN_INCARNATION", "tianxia.talent.ash.ash_clone",
    "tianxia.talent.fire.first_spark_that_burned_the_sky", "tianxia.talent.fire.phoenix_step",
    "tianxia.talent.fire.sun_devouring_firestorm", "tianxia.talent.magma.sea_of_molten_heaven",
}


def compile_zones(monkeypatch, ids):
    result = []
    original = c._zone_spec

    def capture(row, mechanic, sphere_names):
        zone = original(row, mechanic, sphere_names)
        typed = row.parameters.get("typed") or {}
        result.append((mechanic["mechanic_id"], typed.get("option_label") or row.display_name, zone["terrain"] if zone else None))
        return zone

    monkeypatch.setattr(c, "_zone_spec", capture)
    for mid in sorted(ids):
        m = AUTHORITY["mechanics"][mid]
        sphere = m["sphere_id"]
        sheet = {
            "identity": {"proficiency_bonus": 6, "cultivation_level": 20, "path": "Qi Cultivation", "key_ability": "CON"},
            "ability_scores_and_statistics": {
                "abilities": [{"ability": x, "score": 14, "modifier": 2} for x in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
                "primary_resource": {"name": "Qi", "maximum": 100}, "armor_class": {"base_value": 14},
                "hit_points": {"maximum": 100}, "speed": {"walking_ft": 30},
                "technique_save_dc": 16, "technique_attack_bonus": 8,
            },
            "spheres_and_talents": {
                "sphere_record_ids": [sphere], "learned_talent_record_ids": [mid],
                "automatic_sphere_component_record_ids": [k for k, v in AUTHORITY["mechanics"].items()
                    if v.get("sphere_id") == sphere and v.get("kind") == "base_ability"],
            },
        }
        c.compile_character(sheet, actor_id="actor:terrain-test")
    return [row for row in result if row[0] in ids]


def test_lava_burst_terrain_survives_scrambled_printed_text(monkeypatch):
    monkeypatch.setattr(c, "_texts", lambda *args, **kwargs: "scrambled")
    rows = compile_zones(monkeypatch, {"TAL_MAGMA_LAVA_BURST"})
    assert rows and all(names == ["molten terrain"] for _, _, names in rows)
    ignite = compile_zones(monkeypatch, {"FIRE_BASE_IGNITE"})
    assert any(option == "Fire Terrain Square" and names == ["fire terrain"]
               for _, option, names in ignite)


def test_only_mentioned_terrain_is_not_created(monkeypatch):
    rows = compile_zones(monkeypatch, {"TAL_MAGMA_COURT_OF_THE_LIVING_VOLCANO"})
    assert rows and all(not names for _, _, names in rows)


@pytest.mark.parametrize("prose", ["printed", "scrambled"])
def test_catalog_terrain_matches_reviewed_table(monkeypatch, prose):
    if prose == "scrambled":
        monkeypatch.setattr(c, "_texts", lambda *args, **kwargs: "scrambled")
    ids = set(CREATES) | MENTIONS | {key[0] for key in OPTIONS}
    rows = compile_zones(monkeypatch, ids)
    assert ids <= {mid for mid, _, _ in rows}
    assert set(OPTIONS) <= {(mid, option) for mid, option, _ in rows}
    assert any(mid == "TAL_SAND_DEVOURING_DUNE_MOUTH" and option == "Devouring Dune Mouth: compress the dune" and names is None
               for mid, option, names in rows)
    mismatches = []
    for mid, option, names in rows:
        expected = OPTIONS.get((mid, option), CREATES.get(mid, []))
        # A missing zone creates no terrain; creators must still have a zone.
        if (names or []) != expected:
            mismatches.append((mid, option, names, expected))
    assert not mismatches


def test_eruption_strike_patch_is_carried_by_its_failed_save(tmp_path):
    mechanic = AUTHORITY["mechanics"]["TAL_MAGMA_ERUPTION_STRIKE"]
    options = mechanic["modifier"]["options"]
    patch = next(option for option in options if option["label"] == "Molten Terrain Patch")
    typed = {"effects": patch["effects"], "area": None, "duration": {"kind": "minutes", "amount": 1},
             "numbers": {"cl": 20, "pb": 6}, "option_label": patch["label"]}
    row = SimpleNamespace(parameters={"typed": typed}, display_name=mechanic["name"],
                          source_definition_id=mechanic["mechanic_id"], target_kind="ANY_CREATURE", radius_ft=None)
    zone = c._zone_spec(row, mechanic, AUTHORITY["sphere_names"])
    assert zone["terrain"] == ["molten terrain"]
    assert zone["size_ft"] == 10

    # Use the parent attack's hit-time loadout, not the legacy explicit variant:
    # the former has no action zone_spec to hide a lost modifier profile.
    glob = "TAL_MAGMA_MAGMA_GLOB#opt2"
    combat, table, mid = fight(tmp_path, [mechanic["mechanic_id"], "TAL_MAGMA_MAGMA_GLOB"],
                               spheres=[mechanic["sphere_id"]], left_attack_bonus=100)
    engine = combat._load_session(mid).engine
    (toggle,) = [a.source_definition_id for a in engine.action_catalog.values()
                 if (setting := a.parameters.get("attack_modifier_setting"))
                 and setting["family"].endswith("." + glob) and setting["field"] == "on"]
    state = table.state(mid)
    menu = state["menu"]
    (candidate,) = [c for c in engine.legal_candidates() if c.source_definition_id == toggle]
    assert table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])["status"] == "COMMITTED"

    def pick(prompt):
        options = prompt["choice"]["options"]
        if prompt["context"]["reaction_source_id"] == "choice:needle.magma_glob_expression":
            return ["Push 5 Feet"]
        return [next((o["id"] for o in options if o["label"].startswith("Molten Terrain Patch")), options[0]["id"])]

    settle(lambda answers: act(table, mid, glob, answers, target_id=RIGHT), pick)
    engine = reload(combat, mid)
    (patch,) = [z for z in engine.state.zones.values() if z.owner_id == LEFT]
    assert patch.trigger_profile["terrain"] == ["molten terrain"]
    assert patch.trigger_profile["size_ft"] == 10


@pytest.mark.parametrize("option,target,terrain", [
    pytest.param(1, RIGHT, ["deep sand terrain", "storming sand terrain"], id="Bury the Line"),
    pytest.param(3, None, ["sand terrain"], id="Claim the Desert"),
])
def test_mountain_option_creates_its_reviewed_terrain(tmp_path, option, target, terrain):
    mechanic = AUTHORITY["mechanics"]["TAL_SAND_THE_MOUNTAIN_REMEMBERS_IT_IS_DUST"]
    combat, table, mid = fight(tmp_path, [mechanic["mechanic_id"]], cl=20, spheres=[mechanic["sphere_id"]])
    source = f"{mechanic['mechanic_id']}#opt{option}"
    settle(lambda answers: act(table, mid, source, answers, target_id=target))
    engine = reload(combat, mid)
    (zone,) = [z for z in engine.state.zones.values() if z.owner_id == LEFT]
    assert zone.trigger_profile["terrain"] == terrain
