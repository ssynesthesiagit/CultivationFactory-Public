"""Source-bound action regressions for the additional Subpath Art adapters."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core import FoundryError
from character_creation.constructed_arts.immortal_art import (
    construct_immortal_art,
    immortal_art_progression_child_hash,
    load_immortal_art_authority,
)
from character_creation.service import (
    CharacterCreationExecutionService,
    _IMMORTAL_FEATURE_SOURCE_ADAPTERS,
)


ROOT = Path(__file__).resolve().parents[1]
P2B_PATH = ROOT / "non_sphere_authority" / "authority" / "Tianxia_Subpath_Tradition_Index_Master_P2B.json"

_CASES = {
    "tianxia.subpath.body.mantis_style.feature.eye_of_the_mantis": {
        "parent_id": "tianxia.subpath.body.mantis_style",
        "path_id": "tianxia.path.body_refining",
        "owning_path_cl": 14,
        "construction_cl": 14,
        "resource": "Stamina",
        "cost": 3,
    },
    "tianxia.tradition.spirit.dreamweaver.feature.unreality_bites_back": {
        "parent_id": "tianxia.tradition.spirit.dreamweaver",
        "path_id": "tianxia.path.spirit_awakening",
        "owning_path_cl": 6,
        "construction_cl": 6,
        "resource": "Resonance",
        "cost": 2,
    },
}


def _sealed_rows() -> tuple[dict[str, dict], dict[str, dict]]:
    authority = json.loads(P2B_PATH.read_text(encoding="utf-8"))
    parents: dict[str, dict] = {}
    features: dict[str, dict] = {}
    for parent in authority["entries"]:
        parent_id = parent.get("canonical_id")
        if parent_id not in {case["parent_id"] for case in _CASES.values()}:
            continue
        parents[parent_id] = parent
        for feature in parent.get("feature_progression") or []:
            feature_id = feature.get("canonical_id")
            if feature_id in _CASES:
                features[feature_id] = feature
    return parents, features


def _source_row(feature_id: str, catalog_environment: dict) -> tuple[dict, dict]:
    parents, features = _sealed_rows()
    case = _CASES[feature_id]
    parent = parents[case["parent_id"]]
    feature = features[feature_id]
    parent_record = {
        # The source row helper receives this from the proof-bound project
        # resolver.  The test uses a fixed-format commitment while the P2B
        # feature and installed source remain the real sealed inputs.
        "record_id": case["parent_id"],
        "record_hash": "a" * 64,
        "content_type": "subpath",
    }
    row = CharacterCreationExecutionService._immortal_feature_source_row(
        object(),
        feature_id=feature_id,
        feature=feature,
        feature_record=None,
        parent_record=parent_record,
        path_id=case["path_id"],
        owning_path_cl=case["owning_path_cl"],
        construction_cl=case["construction_cl"],
        factory_root=catalog_environment["root"],
    )
    return row, feature


@pytest.fixture(scope="module")
def immortal_authority() -> dict:
    return load_immortal_art_authority(ROOT)


@pytest.mark.parametrize("feature_id", tuple(_CASES))
def test_additional_subpath_actions_are_bound_to_exact_installed_source(feature_id, catalog_environment):
    row, feature = _source_row(feature_id, catalog_environment)
    case = _CASES[feature_id]
    adapter = _IMMORTAL_FEATURE_SOURCE_ADAPTERS[feature_id]
    action = row["action_surface"]

    assert row["record_id"] == feature_id
    assert row["record_hash"] == immortal_art_progression_child_hash(
        case["parent_id"], "a" * 64, feature
    )
    assert row["source"]["source_id"] == adapter["source_id"]
    assert row["source"]["source_hash"] == adapter["source_file_sha256"]
    assert row["source"]["anchor"] == f"line:{adapter['line_start']}"
    assert row["published_text"] == action["source_mechanics"]["published_section"]
    assert action["resource_name"] == case["resource"]
    assert action["resource_cost"] == case["cost"]
    assert action["action_type"] in {"bonus action", "reaction"}
    assert action["normalized_procedure"]
    assert action["source_tags"] == sorted(action["source_tags"])

    if feature_id.endswith("eye_of_the_mantis"):
        assert action["resource_name"] == "Stamina"
        assert "current and maximum Hit Points" in action["effect"]["information_learned"]
        assert "Strength, Dexterity, and Constitution" in action["effect"]["lowest_physical_save"]
        assert "detect" in action["source_tags"]
    else:
        assert "3d10" in action["effect"]["failed_save"]
        assert "Wisdom saving throw" in action["save_or_check"]
        assert action["source_mechanics"]["feature_id"] == feature_id


def test_additional_subpath_source_bounds_fail_closed_when_rewritten():
    _parents, features = _sealed_rows()
    feature_id = "tianxia.subpath.body.mantis_style.feature.eye_of_the_mantis"
    feature = deepcopy(features[feature_id])
    feature["source"]["section_sha256"] = "0" * 64
    case = _CASES[feature_id]
    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._immortal_feature_source_row(
            object(),
            feature_id=feature_id,
            feature=feature,
            feature_record=None,
            parent_record={"record_id": case["parent_id"], "record_hash": "a" * 64, "content_type": "subpath"},
            path_id=case["path_id"],
            owning_path_cl=case["owning_path_cl"],
            construction_cl=case["construction_cl"],
            factory_root=Path("/var/tmp/does-not-supply-authority"),
        )
    assert error.value.code == "CG1_IMMORTAL_ART_SOURCE_AUTHORITY_INVALID"


@pytest.mark.parametrize(
    "feature_id",
    (
        "tianxia.subpath.body.mantis_style.feature.eye_of_the_mantis",
        "tianxia.tradition.spirit.dreamweaver.feature.unreality_bites_back",
    ),
)
def test_path_feature_adapter_uses_only_its_explicit_factor(immortal_authority, feature_id, catalog_environment):
    source_row, _feature = _source_row(feature_id, catalog_environment)
    case = _CASES[feature_id]
    request = {
        "schema": "TianxiaFoundry.ImmortalArtRequest.v1",
        "seed": f"adapter-test:{feature_id}",
        "project_id": "project.adapter-feature-test",
        "cl": 15,
        "pb": 5,
        "path_id": case["path_id"],
        "path_kind": "body_refining" if case["resource"] == "Stamina" else "spirit_awakening",
        "path_name": case["path_id"],
        "key_ability": "CON" if case["resource"] == "Stamina" else "WIS",
        "key_ability_modifier": 3,
        "owning_path_cl": case["owning_path_cl"],
        "path_realm": "Nascent Soul",
        "known_spheres": [],
        "known_sources": [source_row],
        "source_record_id": feature_id,
        "art_ordinal": 0,
    }
    art = construct_immortal_art(immortal_authority, request)
    assert art["source_record_id"] == feature_id
    assert len(art["factors"]) == 1
    assert art["factors"][0]["factor_id"] == _IMMORTAL_FEATURE_SOURCE_ADAPTERS[feature_id]["supported_factor_ids"][0]
    assert art["action_surface"]["factor_application"]["mode"] in {
        "path_feature_detect_presence",
        "path_feature_destructive_damage",
    }


def test_dreamweaver_destructive_damage_adds_authenticated_standard_package(immortal_authority, catalog_environment):
    feature_id = "tianxia.tradition.spirit.dreamweaver.feature.unreality_bites_back"
    source_row, _feature = _source_row(feature_id, catalog_environment)
    case = _CASES[feature_id]
    request = {
        "schema": "TianxiaFoundry.ImmortalArtRequest.v1",
        "seed": "adapter-test:dreamweaver-destructive-package",
        "project_id": "project.adapter-feature-test",
        "cl": 15,
        "pb": 5,
        "path_id": case["path_id"],
        "path_kind": "spirit_awakening",
        "path_name": case["path_id"],
        "key_ability": "WIS",
        "key_ability_modifier": 3,
        "owning_path_cl": case["owning_path_cl"],
        "path_realm": "Nascent Soul",
        "known_spheres": [],
        "known_sources": [source_row],
        "source_record_id": feature_id,
        "art_ordinal": 0,
    }
    art = construct_immortal_art(immortal_authority, request)
    factor_application = art["action_surface"]["factor_application"]
    destruction_factor = factor_application["destruction_factor"]
    assert destruction_factor["package"]["formula"] == "PBd8"
    assert destruction_factor["package"]["damage_type"] == "Psychic"
    assert destruction_factor["native_damage_expression"] == "3d10 Psychic"
    assert destruction_factor["effective_damage_expression"] == (
        "3d10 Psychic + PBd8 Psychic on a failed save; "
        "half of the combined damage on a successful save"
    )
    assert factor_application["effective_effect"]["damage_expression"] == destruction_factor["effective_damage_expression"]
    assert destruction_factor["definition_source"]["binding"]["anchor"] == "line:162"
    assert destruction_factor["definition_source"]["binding"]["source_hash"]

    tampered = deepcopy(source_row)
    tampered["factor_adapters"]["destructive_damage"]["source_record_hash"] = "f" * 64
    request["known_sources"] = [tampered]
    with pytest.raises(FoundryError) as error:
        construct_immortal_art(immortal_authority, request)
    assert error.value.code == "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH"
