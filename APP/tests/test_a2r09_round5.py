"""Array Tremorsense contact and Sovereign player guidance review regressions."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import tabik_ninpo as ninpo
from combat.surface_contact import connected
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE
from tests.test_a2r09_review_fixes import add_fixture_action, NINPO


@pytest.mark.parametrize("surface", ["floor", "joined_platform", "separate_platforms",
                                     "airborne_defender", "airborne_attacker"])
def test_array_tremorsense_requires_shared_contact_table_reload(tmp_path, surface):
    identifies = surface in {"floor", "joined_platform"}
    raised = "platform" in surface
    owner_z = 2 if raised or surface == "airborne_defender" else 0
    foe_z = 2 if raised or surface == "airborne_attacker" else 0

    def setup(bundles):
        foe = bundles[2]
        # Real printed Heaven-Drum Circulation supplies ordinary Tremorsense.
        from combat.factory_compiler import compile_character
        from tests.h1_support import sheet
        doc = sheet([], cl=18)
        doc["path_and_subpath"] = {"path_feature_record_ids": [
            "tianxia.subpath.body.heaven_thunder_drum_body.feature.heaven_drum_circulation"]}
        foe.update(compile_character(doc, actor_id=FOE, reaction_plan={"ask": False}))
        add_fixture_action(foe, "Enemy attack", [{"type": "attack", "attack_kind": "ranged",
                           "no_damage": True, "on_hit": []}], target="HOSTILE_ENTITY")
        foe["action_catalog"][-1]["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        for bundle, airborne in ((bundles[0], surface == "airborne_defender"),
                                 (foe, surface == "airborne_attacker")):
            if airborne:
                bundle["actor_template"].update(fly_speed_ft=30, hover=True)
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    def arena_edit(arena):
        cells = [{"x": 3, "y": 6}, {"x": 5, "y": 6}]
        if surface == "joined_platform":
            cells.append({"x": 4, "y": 6})
        arena["terrain_regions"] = ([{"region_id": "platforms", "terrain_type": "BLOCKED",
            "movement_cost": 0, "height_ft": 10, "cells": cells}] if raised else [])

    combat, table, mid = fixture(tmp_path, [], cl=18, ask=False, owner_path="Qi Cultivation",
        seed="A2R09F5-" + surface, owner_features=[NINPO + "shadow_clone_array"],
        bundle_transform=setup, battlefield_transform=arena_edit,
        positions={OWNER: {"x": 3, "y": 6, "z": owner_z},
                   ALLY: {"x": 2, "y": 6}, FOE: {"x": 5, "y": 6, "z": foe_z}})
    settle(table, mid, candidate(combat, mid, "Shadow Clone Array").candidate_id)
    engine = reload(tmp_path, mid)
    assert connected(engine, engine.state.actors[FOE], engine.state.actors[OWNER]) == identifies
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, "Enemy attack", target=OWNER).candidate_id,
                     picks={"choice:needle.clone_interposition": "interpose"})
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.clone_interposition"]
    assert len(choices) == (0 if identifies else 1)
    engine = reload(tmp_path, mid)
    actor, attacker = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert actor.position.z == owner_z and attacker.position.z == foe_z
    assert ninpo.clone_count(engine, actor) == (2 if identifies else 1)
    assert ninpo.identifies_true_body(engine, attacker, actor) == identifies
    assert ninpo.clone_opportunity(engine, attacker, actor) == (None if identifies else False)


def test_sovereign_rider_explains_flight_limitation_without_internal_lane():
    from tests.test_auto_a2r11_residual import riders, BEAST
    text = " ".join(riders(BEAST + "sovereign_of_ten_thousand_beasts"))
    assert "SKYSOV" not in text and "lane" not in text
    assert "does not yet grant" in text and "Fly Speed with Hover" in text
    assert "ask the GM" in text and "current Speed" in text and "one-minute" in text
