"""MGR-T14-ling-cloud-knees-speed-1: Refined Open-Cloud Knees replaces the
Cloud-Step Crane Vessel's Speed contribution.

The printed clause "its Speed bonus becomes +10 feet" replaces (never adds
to) the Vessel's own +5-feet Speed contribution when the actual Refined
owner is compiled: one native motion row, one effective contribution, no
action, no Reaction and no Crane Breath spend. The Awakened stage is the
Basic control (+5); wearing armor fails the printed footwork condition, and
restraints that prevent light footwork already make Speed 0 natively.
"""
import copy
import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.speed_contributions import effective_speed
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, OWNER, FOE, reload, turn

VESSEL = "foundation.white_crane_cloud_step_v0_2B.cloud_step_crane_vessel"
REFINED = "foundation.white_crane_cloud_step_v0_2B.refined_open_cloud_knees"
FOUNDATION = "white_crane_cloud_step_v0_2B"
CRANE_BREATH = "resource:foundation.crane_breath"

ARMORED = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "quantity": 1}]}}


def crane_bundle(stage: str, kit: dict | None = None) -> dict:
    """A White Crane Cloud-Step character at ``stage``; the Foundation resolves the stage's features."""
    doc = sheet([VESSEL], foundation={
        "foundation_id": FOUNDATION, "stage": stage,
        "resource": {"name": "Crane Breath", "resource_id": "foundation.resource.white_crane_cloud_step_v0_2B",
                     "current": 0, "initial_current": 0, "maximum": 1}}, kit=kit)
    return compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})


def contributions(bundle: dict) -> list[dict]:
    """The compiled Cloud-Step Crane Vessel Speed contribution rows."""
    return [row for row in bundle.get("typed_passives") or []
            if isinstance(row, dict) and row.get("feature_id") == VESSEL
            and row.get("block") == "motion" and row.get("kind") == "speed_bonus"]


def test_crane_vessel_compiles_its_base_speed_contribution():
    """Basic control: the Awakened Vessel contributes its own +5 feet as one native motion row."""
    bundle = crane_bundle("Awakened")
    rows = contributions(bundle)
    assert len(rows) == 1, bundle.get("typed_passives")
    assert rows[0]["ft"] == 5
    assert rows[0]["feature_id"] == VESSEL
    assert not {name for kind in ("passive", "reaction")
                for name in (bundle["diagnostics"]["skipped"].get(kind) or [])
                if name == "Cloud-Step Crane Vessel"}


def test_refined_open_cloud_knees_replaces_the_contribution_with_ten_feet():
    """The Refined owner's clause replaces the base contribution: one row, +10, never +5 and +10."""
    bundle = crane_bundle("Refined")
    rows = contributions(bundle)
    assert len(rows) == 1, rows  # one effective contribution, not a second +10
    assert rows[0]["ft"] == 10, rows[0]  # replaces the base +5; never 15 feet in total
    modifier = next(row for row in bundle.get("modifiers") or [] if row.get("id") == REFINED)
    assert modifier["status"] == "applied"
    assert modifier["targets"] == ["Cloud-Step Crane Vessel"] == modifier["applied"]
    assert not modifier["not_automated_targets"]


def test_the_replacement_needs_no_action_reaction_or_crane_breath():
    """The contribution is a passive chassis row: no economy, no cost, no Crane Breath spend."""
    bundle = crane_bundle("Refined")
    row = contributions(bundle)[0]
    assert not row.get("costs") and not row.get("resource_id")
    assert not row.get("optional")  # never a choice the table has to make
    # The Refined owner itself is a no-action passive rider, and the Crane
    # Breath pool it does not touch is still compiled for the character.
    from combat.typed_numbers import authority_mechanics

    record = authority_mechanics()[REFINED]
    assert record["activation"]["economy"] == "no_action"
    assert record["activation"]["trigger"] == "Refined Foundation active."
    resources = {definition["resource_id"] for definition in bundle["actor_template"]["resources"]}
    assert CRANE_BREATH in resources, resources


@pytest.mark.parametrize("stage", ["Awakened", "Refined"])
def test_worn_armor_fails_the_printed_footwork_condition(stage: str):
    """Wearing armor fails the Vessel's footwork condition: no contribution, Speed unchanged."""
    bundle = crane_bundle(stage, kit=ARMORED)
    assert contributions(bundle) == []
    assert "Cloud-Step Crane Vessel" in bundle["diagnostics"]["skipped"]["passive"]


def test_unrelated_passives_and_movement_modifiers_are_preserved():
    """Only the Vessel's own row changes: the Refined stage's other features and every
    unrelated motion row compile exactly as they did without this automation."""
    bundle = crane_bundle("Refined")
    others = {row.get("feature_id"): row for row in bundle.get("typed_passives") or []
              if isinstance(row, dict) and row.get("feature_id") != VESSEL}
    # The Refined stage's own printed features are still compiled beside the replaced row.
    for feature in ("foundation.white_crane_cloud_step_v0_2B.crane_wing_cut",
                    "foundation.white_crane_cloud_step_v0_2B.generate_crane_breath",
                    "foundation.white_crane_cloud_step_v0_2B.refined_wings_remember_ground"):
        assert feature in others, (feature, sorted(others))
    # Default-inert control: another Foundation's motion row keeps its own number.
    from tests.h1_support import ME

    doc = sheet(["foundation.dragon_wind_vessel_v0_2E.wind_opened_body"],
                foundation={"foundation_id": "dragon_wind_vessel_v0_2E", "stage": "Awakened"})
    dragon = compile_character(doc, actor_id=ME)
    dragon_rows = [row for row in dragon.get("typed_passives") or []
                   if row.get("feature_id") == "foundation.dragon_wind_vessel_v0_2E.wind_opened_body"]
    assert [(row.get("block"), row.get("kind"), row.get("ft")) for row in dragon_rows] == [("motion", "speed_bonus", 10)]


@pytest.mark.parametrize("stage,expected", [("Awakened", 35), ("Refined", 40)])
def test_the_legal_movement_budget_commits_cold_reloads_and_replays(tmp_path, stage: str, expected: int):
    """A real table fight: the standing fighter's native Speed and legal movement budget are
    30 + the one contribution; the committed fight cold-reloads and mechanically replays with
    the same budget (the sheet's own walking speed is the fixed 30)."""
    combat, table, mid = fixture(tmp_path, [], owner_bundle=crane_bundle(stage),
                                  seed="MGRT14CLOUDKNEES")
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert actor.speed_ft == 30  # the fixed walking speed: the contribution is never baked in
    assert effective_speed(engine, actor) == expected
    assert actor.movement_remaining_ft == expected  # the legal native budget at turn start
    before_round = engine.state.round_number
    # Actually commit OWNER's end turn through the table (not a no-op when OWNER
    # is already current), advance back to OWNER through the intervening turns,
    # and verify initiative/round progression refreshed the movement budget.
    from tests.test_r9i_karma_persistence import end_turn
    end_turn(table, mid)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    assert engine.state.current_actor_id == OWNER
    assert engine.state.round_number > before_round
    assert engine.state.actors[OWNER].movement_remaining_ft == expected
    engine = reload(tmp_path, mid)  # cold reload; asserts the mechanical replay passes
    actor = engine.state.actors[OWNER]
    assert effective_speed(engine, actor) == expected
    assert actor.movement_remaining_ft == expected
    # The opponent is untouched by this owner's contribution.
    assert effective_speed(engine, engine.state.actors[FOE]) == 30


def test_refined_uses_selected_compilation_authority_not_default_file():
    """The Refined replacement reads the selected authority's modifier data, not the
    on-disk default: an injected authority whose REFINED modifier carries a different
    Speed value (and a renamed Vessel) compiles that value and reports that name."""
    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    authority = copy.deepcopy(authority)
    authority["mechanics"][REFINED]["modifier"]["effects"][0]["flat"] = 7
    authority["mechanics"][VESSEL]["name"] = "Renamed Cloud Vessel"
    # Keep the modifier naming the chassis so the replacement still applies.
    authority["mechanics"][REFINED]["modifier"]["targets"] = ["Cloud-Step Crane Vessel"]

    doc = sheet([VESSEL], foundation={
        "foundation_id": FOUNDATION, "stage": "Refined",
        "resource": {"name": "Crane Breath", "resource_id": "foundation.resource.white_crane_cloud_step_v0_2B",
                      "current": 0, "initial_current": 0, "maximum": 1}})
    bundle = compile_character(doc, actor_id=OWNER, typed_authority=authority,
                               reaction_plan={"ask": True})
    rows = [row for row in bundle.get("typed_passives") or []
            if isinstance(row, dict) and row.get("feature_id") == VESSEL
            and row.get("block") == "motion" and row.get("kind") == "speed_bonus"]
    assert len(rows) == 1, rows
    assert rows[0]["ft"] == 7, rows[0]  # selected modifier value, not the default +10
    modifier = next(row for row in bundle.get("modifiers") or [] if row.get("id") == REFINED)
    assert modifier["status"] == "applied"
    assert modifier["targets"] == ["Renamed Cloud Vessel"] == modifier["applied"]
