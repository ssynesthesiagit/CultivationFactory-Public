"""Printed Foundation stages grant cumulative features through both consumers."""
import json
import os
from pathlib import Path
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.tabletop import sheet_library
from non_sphere_authority import foundation_mechanics as fm
from non_sphere_authority.foundation_features import features_for_stage, foundation_feature_blocks
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, sealed_native_attack, settle, turn

ASH = "ash_born_remnant_core_v0_2B"
DRAGON = "dragon_wind_vessel_v0_2E"
BOWL = "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
MIRROR = "dream_mirror_soul_anchor_v0_2B"


def names(fid, stage):
    return {row["name"] for row in features_for_stage(fid, stage)}


@pytest.mark.parametrize("fid,rider", [(BOWL, "Integrated Nourishment Rider"), (DRAGON, "Sky-Marrow Conversion")])
def test_integrated_progression_is_cumulative_and_includes_printed_rider(fid, rider):
    awakened = names(fid, "Awakened")
    integrated = names(fid, "Integrated")
    assert integrated == awakened | {rider}
    assert names(fid, "Intermediate") == integrated
    assert integrated < names(fid, "Refined") < names(fid, "Perfected")
    doc = sheet([])
    doc["foundation"] = {"foundation_id": fid, "stage": "Integrated"}
    library = sheet_library(doc, [], set())
    group = next(g for g in library["groups"] if g["key"] == "cultivation")
    assert {row["name"] for row in group["entries"]} == integrated
    assert all(row["text"] for row in group["entries"])


@pytest.mark.parametrize("stage", [None, "", "Unknown", "Unstable", "Latent", [], {}])
def test_pre_feature_or_unknown_stages_do_not_grant_awakened_features(stage):
    assert features_for_stage(ASH, stage) == []
    assert features_for_stage(MIRROR, stage) == []


def test_common_expression_uses_earliest_printed_availability():
    assert names(MIRROR, "Common Expression") == {"Mirror-Root Reserve"}
    assert names(DRAGON, "Common Expression") == {"Wind-Opened Body"}
    assert names("weak_reed_tendons_v0_2B", "Common Expression") == set()
    assert names(MIRROR, "Common Expression") < names(MIRROR, "Awakened")


def test_all_catalog_foundations_grant_each_stage_cumulatively_without_duplicates():
    for fid in fm.verified_foundation_records():
        common = names(fid, "Common Expression")
        awakened = names(fid, "Awakened")
        integrated = names(fid, "Integrated")
        refined = names(fid, "Refined")
        perfected = names(fid, "Perfected")
        assert common <= awakened <= integrated <= refined <= perfected, fid
        assert names(fid, "Intermediate") == integrated, fid
        assert perfected == {row["name"] for row in foundation_feature_blocks(fm.verified_foundation_records()[fid])}
        for stage in ("Common Expression", "Awakened", "Integrated", "Intermediate", "Refined", "Perfected"):
            rows = features_for_stage(fid, stage)
            assert len(rows) == len({r["id"] for r in rows}), (fid, stage)
        assert names(fid, "Unstable") == names(fid, "Latent") == set(), fid


def test_feature_availability_can_raise_but_not_lower_progression_tier():
    record = {"semantic_surfaces": {"features": "", "resource": "", "progression": (
        "### Integrated or Intermediate Expressions\n"
        "#### Intermediate Gift\n**Type:** Passive\n**Available At:** Intermediate or higher\n"
        "#### Later Gift\n**Type:** Passive\n**Available At:** Refined or higher\n"
        "### Refined\n#### Refined Gift\n**Type:** Passive\n**Available At:** Awakened or higher\n"
    )}}
    assert [(r["name"], r["stage"]) for r in foundation_feature_blocks(record)] == [
        ("Intermediate Gift", "Integrated"), ("Later Gift", "Refined"), ("Refined Gift", "Refined")]


def test_weak_reed_evolutions_keep_their_printed_progression_floor():
    fid = "weak_reed_tendons_v0_2B"
    awakened = names(fid, "Awakened")
    refined = names(fid, "Refined")
    perfected = names(fid, "Perfected")
    evolutions = {"Refined: Wind-Reed Body", "Refined: River-Reed Flexibility", "Refined: Verdant Sinews", "Refined: Wire Tendons"}
    assert not evolutions & awakened
    assert evolutions <= refined
    assert "Perfected: Unbroken Reed" not in refined
    assert "Perfected: Unbroken Reed" in perfected


@pytest.mark.skipif(not os.environ.get("CF_FOUNDATION_ROSTER"), reason="Opt-in read-only owner roster audit")
def test_all_thirteen_integrated_roster_characters_compile_their_foundation_features():
    """Keep owner sheets outside the repository; point at the hunt's frozen input."""
    checked = []
    for path in sorted(Path(os.environ["CF_FOUNDATION_ROSTER"]).rglob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            member = "Tianxia_Owner_Character_Sheet_v1.json"
            if member not in archive.namelist():
                continue
            doc = json.loads(archive.read(member))
        foundation = doc.get("foundation") or {}
        if foundation.get("stage") != "Integrated":
            continue
        fid = foundation["foundation_id"]
        bundle = compile_character(doc, actor_id="actor:factory." + path.parent.name)
        # The two shared consumers must agree on the complete feature inventory;
        # executable rows, modifiers and explicit manual diagnostics all count.
        expected = names(fid, "Awakened")
        assert expected, path.parent.name
        assert expected <= names(fid, "Integrated"), path.parent.name
        granted = {r.get("name") for key in ("typed_reactions", "typed_passives", "modifiers") for r in bundle.get(key, [])}
        granted.update(r["display_name"] for r in bundle["action_catalog"])
        granted.update(n for values in bundle["diagnostics"]["skipped"].values() for n in values)
        assert names(fid, "Integrated") <= granted, (path.parent.name, names(fid, "Integrated") - granted)
        checked.append(path.parent.name)
    assert len(checked) == 13, checked


def test_mei_jiang_integrated_last_cinder_guard_through_table_and_cold_reload(tmp_path):
    doc = sheet([], name="Mei Jiang")
    doc["foundation"] = {"foundation_id": ASH, "stage": "Integrated", "resource": {
        "name": "Remnant Cinder", "resource_id": "tianxia.resource.foundation." + ASH, "maximum": 1, "current": 1}}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    guard = "reaction:typed.foundation." + ASH + ".last_cinder_guard"

    def delivery(bundles):
        sealed_native_attack(bundles[2], "Hostile strike", damage_type="FORCE", sides=2, modifier=11, attack_bonus=100)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, bundle_transform=delivery, seed="FOUNDSTAGE1")
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources["resource:foundation.remnant_cinder"] == 1
    hp = before.state.actors[ALLY].current_hp
    prompts = settle(table, mid, candidate(combat, mid, "Hostile strike", target=ALLY).candidate_id, picks={guard: "first"})
    assert any(p["context"]["reaction_source_id"] == guard for p in prompts), prompts
    after = reload(tmp_path, mid)
    damage = next(e for e in after.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == FOE)
    assert after.state.actors[ALLY].current_hp == hp - (damage.payload["total"] - 6)
    assert after.state.actors[OWNER].resources["resource:foundation.remnant_cinder"] == 0
    assert after.state.actors[OWNER].reaction_available is False
