"""Pure tests for the sealed Dao Aspect Immortal Art constructor."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import FoundryError  # noqa: E402
from character_creation.constructed_arts.immortal_art import (  # noqa: E402
    IMMORTAL_ART_REQUEST_SCHEMA,
    compile_immortal_art,
    construct_immortal_art,
    load_immortal_art_authority,
)
from character_creation.constructed_arts.records import immortal_art_record_text  # noqa: E402


def _action(resource: str, cost: int, *, tags: list[str], effect: object, area: str | None = None) -> dict:
    return {
        "action_type": "action",
        "range": "90 feet",
        "target": "one legal source target",
        "area": area,
        "duration": "1 minute",
        "trigger": "on activation",
        "trigger_frequency": "once per activation",
        "save_or_check": "source-defined save or check",
        "attack_roll": "none",
        "dc_basis": "source-defined resolution DC",
        "effect": effect,
        "success": "the complete source effect resolves",
        "failure": "the target resists and the source effect does not resolve",
        "success_by_5": "none",
        "failure_by_5": "none",
        "counterplay": "use the source-defined save, check, suppression, or break route",
        "cleanup": "the source-defined duration or cleanup ends the effect",
        "limits": ["one source-defined activation"],
        "resource_name": resource,
        "resource_cost": cost,
        "source_tags": tags,
        "normalized_procedure": ["Resolve the complete source action.", "Apply its printed effect and limits."],
        "cross_references": ["synthetic source action used only by this pure test"],
    }


def _source(record_id: str, *, kind: str = "path_feature", resource: str = "Stamina", cost: int = 5, tags: list[str] | None = None, progression_cl: int = 10, action: dict | None = None) -> dict:
    tags = tags or ["body", "construct", "manifest"]
    supported = ["destructive_damage"] if kind == "talent" else []
    if {"body", "construct", "manifest"} <= set(tags):
        supported.append("construct_puppet_body_creation")
    if {"boundary", "division", "crossing"} <= set(tags):
        supported.append("domain_lock")
    row = {
        "record_id": record_id,
        "record_hash": (record_id.encode().hex() * 64)[:64],
        "display_name": record_id.rsplit(".", 1)[-1].replace("_", " ").title(),
        "content_type": kind,
        "known": True,
        "acquired_at_cl": 1 if kind == "talent" else progression_cl,
        "path_id": "tianxia.path.body_refining" if resource == "Stamina" else "tianxia.path.qi_cultivation",
        "owning_path_id": "tianxia.path.body_refining" if resource == "Stamina" else "tianxia.path.qi_cultivation",
        "source": {
            "source_id": f"source.{record_id}",
            "path": "synthetic/published-source.md",
            "anchor": "lines:1-20",
            "source_hash": "c" * 64,
        },
        "source_tags": tags,
        "supported_factor_ids": supported,
        "action_surface": action or _action(resource, cost, tags=tags, effect={"summary": "complete source mechanics", "cost": cost}),
    }
    if kind != "talent":
        row["progression"] = {
            "owning_path_id": row["owning_path_id"],
            "granted_at_cl": progression_cl,
            "source": {"source_file_sha256": "c" * 64, "section_sha256": "d" * 64},
        }
    return row


def _request(*, source_rows: list[dict] | None = None, cl: int = 15, path_kind: str = "body_refining", realm: str = "Nascent Soul", ordinal: int = 0, **extra) -> dict:
    resource = "Stamina" if path_kind == "body_refining" else "Qi"
    path_id = "tianxia.path.body_refining" if path_kind == "body_refining" else "tianxia.path.qi_cultivation"
    request = {
        "schema": IMMORTAL_ART_REQUEST_SCHEMA,
        "seed": "immortal-art-pure-test",
        "project_id": "project.immortal-art-pure-test",
        "cl": cl,
        "pb": 5 if cl < 20 else 6,
        "path_id": path_id,
        "path_kind": path_kind,
        "path_name": "Body Refining" if path_kind == "body_refining" else "Qi Cultivation",
        "key_ability": "CON" if path_kind == "body_refining" else "INT",
        "key_ability_modifier": 4 if path_kind == "body_refining" else 3,
        "owning_path_cl": 14 if path_kind != "body_refining" else 10,
        "path_realm": realm,
        "known_spheres": [],
        "known_sources": source_rows or [_source("tianxia.feature.bone_guard")],
        "art_ordinal": ordinal,
    }
    request.update(extra)
    return request


@pytest.fixture(scope="module")
def authority() -> dict:
    return load_immortal_art_authority(ROOT)


def test_sealed_authority_carries_all_active_chassis_and_shared_tables(authority):
    assert len(authority["aspects"]) == 17
    assert {row["display_name"] for row in authority["aspects"]} == {
        "Destruction", "Binding", "Revelation", "Concealment", "Fortification", "Restoration", "Transformation", "Command", "Transport", "Reflection", "Domain", "Creation", "Entropy", "Fate", "Time", "Soul", "Heaven"
    }
    assert all(row["chassis_complete"] and row["factors"] for row in authority["aspects"])
    destruction = next(row for row in authority["aspects"] if row["display_name"] == "Destruction")
    factor = next(row for row in destruction["factors"] if row["factor_id"] == "destructive_damage")
    assert factor["mandate_cost"] == factor["cp_cost"] == 2
    creation = next(row for row in authority["aspects"] if row["display_name"] == "Creation")
    permanent = next(row for row in creation["factors"] if row["factor_id"] == "permanent_creation")
    assert permanent["mandate_cost"] is None and permanent["cp_cost"] is None and permanent["requires_gm_review"] is True
    assert [row["mandate_threshold"] for row in authority["shared_rules"]["realm_thresholds"]] == [3, 6, 9, 12, 15]
    assert all("minimum_cl" not in row for row in authority["shared_rules"]["realm_thresholds"])


def test_bone_guard_creation_walks_twelve_steps_and_recompiles(authority):
    art = construct_immortal_art(authority, _request())
    assert art["dao_aspect"]["display_name"] == "Creation"
    assert art["pb_at_creation"] == 5
    assert art["factors"][0]["factor_id"] == "construct_puppet_body_creation"
    assert art["mandate_complexity"] == 7
    assert art["mandate_threshold"] == 3
    assert art["heaven_pressure"] == 8
    assert art["factor_escalation"] == 1
    assert art["refinement_dc"] == 28
    assert art["activation_cp"] == 12
    assert [row["step"] for row in art["steps"]] == list(range(1, 13))
    assert art["action_surface"]["factor_application"]["mode"] == "created_construct_or_puppet_body"
    assert art["action_surface"]["resource_cost"] == art["activation_cp"]
    assert art["activation_cp_breakdown"]["base_source_cp"] == 5
    assert art["action_surface"]["factor_application"]["created_subject_frame"]["action_capacity"] == "none unless Commanded or Autonomous"
    assert art["action_surface"]["factor_application"]["effective_effect"]["base_source_effect"] == art["source"]["action_surface"]["effect"]
    assert art["automatic_construction"]["roll"] is None
    assert compile_immortal_art(
        authority,
        art,
        cl=15,
        pb=5,
        known_source_ids={art["source_record_id"]},
        known_sources=[art["source"]],
    )["immortal_art_id"] == art["art_id"]


def test_divide_source_uses_bounded_domain_lock_adapter(authority):
    source = _source(
        "tianxia.feature.divide_heaven_and_earth",
        resource="Qi",
        cost=6,
        tags=["boundary", "division", "crossing"],
        progression_cl=14,
        action=_action("Qi", 6, tags=["boundary", "division", "crossing"], area="a plane up to 60 feet long, 30 feet high, and 1 inch thick", effect={"relation": "Division of Passage", "resolution": "Strength or Charisma save; failure stops crossing; success crosses and takes 4d8 Force damage"}),
    )
    art = construct_immortal_art(authority, _request(source_rows=[source], path_kind="qi_cultivation", cl=20, realm="Immortal"))
    assert art["dao_aspect"]["display_name"] == "Domain"
    assert art["pb_at_creation"] == 6
    assert art["factors"][0]["factor_id"] == "domain_lock"
    assert art["mandate_complexity"] == 7
    assert art["mandate_threshold"] == 6
    assert art["heaven_pressure"] == 2
    assert art["factor_escalation"] == 1
    assert art["refinement_dc"] == 22
    assert art["activation_cp"] == 13
    assert art["action_surface"]["factor_application"]["mode"] == "bounded_domain_lock"
    assert art["action_surface"]["area"].startswith("a plane")
    assert art["action_surface"]["factor_application"]["crossing_resolution"]["failure"] == art["source"]["action_surface"]["failure"]
    assert art["action_surface"]["factor_application"]["effective_effect"]["domain_lock_rule"]["check_or_save"] == art["source"]["action_surface"]["save_or_check"]
    compile_immortal_art(authority, art)


def test_default_aspect_follows_authenticated_factor_when_source_tags_overlap(authority):
    tags = ["body", "heal", "repair", "restore"]
    source = _source(
        "tianxia.feature.body_marrow_healing",
        tags=tags,
        action=_action(
            "Stamina",
            2,
            tags=tags,
            effect={"healing": {"base_dice": "2d10", "ability_modifier": "Constitution"}},
        ),
    )
    # Body is a valid semantic tag for Creation too, but the sealed source
    # adapter proves only Restoration's complete Factor for this source.
    source["supported_factor_ids"] = ["hp_restoration"]
    art = construct_immortal_art(authority, _request(source_rows=[source]))
    assert art["dao_aspect"]["display_name"] == "Restoration"
    assert art["factors"][0]["factor_id"] == "hp_restoration"
    assert art["action_surface"]["factor_application"]["mode"] == "restoration_hp_package"


def test_complete_learned_sphere_action_is_the_only_fallback(authority):
    source = _source(
        "tianxia.talent.fire_bolt",
        kind="talent",
        resource="Qi",
        cost=2,
        tags=["damage"],
        action=_action("Qi", 2, tags=["damage"], effect="4d8 fire damage"),
    )
    art = construct_immortal_art(authority, _request(source_rows=[source], path_kind="qi_cultivation", realm="Nascent Soul"))
    assert art["dao_aspect"]["display_name"] == "Destruction"
    assert art["factors"][0]["factor_id"] == "destructive_damage"
    assert art["action_surface"]["factor_application"]["mode"] == "complete_learned_source_factor"


def test_unused_known_candidates_do_not_change_derived_figures(authority):
    selected = _source("tianxia.feature.selected")
    unrelated = _source("tianxia.feature.unrelated", tags=["damage"], action=_action("Stamina", 1, tags=["damage"], effect="one source-defined damage packet"))
    base = _request(source_rows=[selected], source_record_id=selected["record_id"], known_spheres=[])
    with_candidate = _request(
        source_rows=[selected, unrelated],
        source_record_id=selected["record_id"],
        known_spheres=[
            {"sphere_id": "tianxia.sphere.selected", "display_name": "Selected"},
            {"sphere_id": "tianxia.sphere.unused", "display_name": "Unused"},
        ],
    )
    first = construct_immortal_art(authority, base)
    second = construct_immortal_art(authority, with_candidate)
    for field in ("mandate_complexity", "mandate_threshold", "heaven_pressure", "factor_escalation", "refinement_dc", "activation_cp", "research_days", "material_cost_gp"):
        assert first[field] == second[field]


@pytest.mark.parametrize("mutation", [
    lambda art: art["steps"][5]["payload"].update(final=art["steps"][5]["payload"]["final"] + 1),
    lambda art: art["action_surface"].update(resource_cost=art["action_surface"]["resource_cost"] + 1),
    lambda art: art["action_surface"]["factor_application"].update(mode="unrelated"),
])
def test_recompile_rejects_nested_or_action_surface_drift(authority, mutation):
    art = construct_immortal_art(authority, _request())
    drifted = deepcopy(art)
    mutation(drifted)
    with pytest.raises(FoundryError) as excinfo:
        compile_immortal_art(authority, drifted)
    assert excinfo.value.code == "IMMORTAL_ART_REDERIVATION_MISMATCH"


def test_recompile_rejects_same_id_external_source_snapshot_drift(authority):
    art = construct_immortal_art(authority, _request())
    changed_source = deepcopy(art["source"])
    changed_source["source"]["source_hash"] = "0" * 64
    with pytest.raises(FoundryError) as excinfo:
        compile_immortal_art(
            authority,
            art,
            cl=15,
            pb=5,
            known_source_ids={art["source_record_id"]},
            known_sources=[changed_source],
        )
    assert excinfo.value.code == "IMMORTAL_ART_SOURCE_SNAPSHOT_MISMATCH"


def test_passive_generic_or_unapproved_gm_routes_fail_closed(authority):
    generic = _request(source_rows=[_source("tianxia.talent.generic", kind="talent", tags=["damage"], action={**_action("Stamina", 1, tags=["damage"], effect="generic effect"), "range": "as Primary Sphere prints"})])
    with pytest.raises(FoundryError) as generic_error:
        construct_immortal_art(authority, generic)
    assert generic_error.value.code == "IMMORTAL_ART_SOURCE_ACTION_INCOMPLETE"
    review = _request(
        special_scale_cost=1,
        gm_review_approved=True,
        gm_review_authority={
            "approved": True,
            "record_id": "gm.review.special-scale",
            "record_hash": "a" * 64,
            "scopes": ["special_scale"],
            "project_id": "project.immortal-art-pure-test",
        },
    )
    with pytest.raises(FoundryError) as review_error:
        construct_immortal_art(authority, review)
    assert review_error.value.code == "IMMORTAL_ART_GM_REVIEW_REQUIRED"


def test_aspect_wide_tags_cannot_select_an_unsupported_factor(authority):
    request = _request(factor_ids=["object_creation"])
    with pytest.raises(FoundryError) as error:
        construct_immortal_art(authority, request)
    assert error.value.code in {"IMMORTAL_ART_FACTOR_SOURCE_MISMATCH", "IMMORTAL_ART_FACTOR_UNSUPPORTED"}


def test_second_ordinal_requires_a_distinct_complete_source(authority):
    only = _request(cl=20, realm="Immortal", ordinal=1, source_rows=[_source("tianxia.feature.only")])
    with pytest.raises(FoundryError) as missing:
        construct_immortal_art(authority, only)
    assert missing.value.code == "IMMORTAL_ART_SECOND_UNAVAILABLE"
    second = _source("tianxia.feature.second", tags=["body", "construct", "manifest"])
    art = construct_immortal_art(authority, _request(cl=20, realm="Immortal", ordinal=1, source_rows=[_source("tianxia.feature.first"), second]))
    assert art["source_record_id"] == "tianxia.feature.second"

def test_record_text_keeps_source_chassis_riders_dependency_and_step_contents(authority):
    art = construct_immortal_art(authority, _request())
    art["source"]["published_text"] = "Published Bone Guard source block: manifest one complete Bone Guard."
    art["source"]["source_dependencies"] = [{
        "purpose": "severance_mark_definition",
        "published_text": "Severance Mark: maximum three marks; lasts until the scene ends; relationships remain visible.",
    }]
    text = immortal_art_record_text(art)
    assert "Published Bone Guard source block" in text
    assert "Severance Mark: maximum three marks" in text
    assert "mechanical chassis" in text
    assert "factor application" in text
    assert "complete action surface and resolution" in text
    for step in art["steps"]:
        assert f"Step {step['step']}: {step['name'].replace('_', ' ')}" in text
    assert "resource cost: 5" in text
