"""Real installed-source Forge projections and project-bound Command4 proofs."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from character_builder import CharacterBuilderService
from character_creation.constructed_arts.forged_technique import construct_forged_technique
from character_creation.constructed_arts.forging_authority import load_forging_authority
from character_creation.constructed_arts.records import build_forged_technique_record
from character_creation.constructed_arts.sources import published_block
from character_creation.service import CharacterCreationExecutionService
from factory_authoring.command4_provider import Command4ProviderAuthoring
from factory_authoring.forged_action_mechanics import (
    forged_action_projection, load_forged_action_binding, validate_forged_action_candidate,
)
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def forged_environment(catalog_environment):
    env = catalog_environment
    db = env["db"]
    created = CharacterBuilderService(db).create_project(
        working_name="Explicit source-preserving Forge", concept="Air control",
        target_cl=20, power_band="standard", source_reference=None,
        creation_mode="detailed", ability_scores={}, generation_route="ai_bootstrap",
        selections={"path_choice": ["tianxia.path.body_refining"]},
    )
    project_id = created["project_id"]
    store = ProjectStore(db)
    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None, project_store=store)
    creator._complete_request(project_id, execution_mode="MANUAL_CHAT", idempotency_key=f"forge-profile:{project_id}")
    records = creator._locked_records_for_project(project_id)
    techniques = []
    for tid, form in (("TAL_AIR_DOWNBURST_SEAL", "burst"), ("TAL_AIR_HEAVEN_SPLITTING_GALE", "line")):
        record = records[tid]
        request = {
            "seed": f"{project_id}:{tid}", "project_id": project_id, "cl": 20, "pb": 6,
            "path_id": "tianxia.path.body_refining", "key_ability": "CON",
            "known_spheres": [{"sphere_id": "tianxia.sphere.air", "display_name": "Air"}],
            "known_talents": [{"talent_id": tid, "sphere_id": "tianxia.sphere.air", "display_name": record["display_name"], "record_hash": record["record_hash"], "source": record["source"], "published_text": published_block(env["root"], record["source"])}],
            "concept": {"name": f"Measured {record['display_name']}", "primary_talent_id": tid, "base_form": form, "secondary_talent_ids": [], "augment_ids": ["ignore_resistance"], "drawback_ids": []},
        }
        technique = construct_forged_technique(load_forging_authority(ROOT), request, generator_version=3)
        locked = build_forged_technique_record(technique)
        with db.transaction() as conn:
            store.insert_constructed_art_records(conn, project_id, [locked])
        techniques.append((technique, locked))
    return {**env, "project_id": project_id, "techniques": techniques}


@pytest.mark.parametrize("index", [0, 1])
def test_source_preserving_air_profile(forged_environment, index):
    env = forged_environment
    technique, record = env["techniques"][index]
    result = forged_action_projection(technique, env["root"])
    text = result["full_description"]
    assert "Cost: 4 Stamina" in text and "Timing: Action" in text
    assert "not Immunity" in text and "successful save" in text
    assert technique["complexity"]["final"] == 4
    if index == 0:
        assert "4d8 + your CON modifier" in text
        assert "not its attack roll or Vector riders" in text
        assert "10-foot-radius, 30-foot-high cylinder" in text
        assert "ordinary condition rules" in text
        assert "Limit: The printed source defines no separate use limit for Downburst Seal." in text
        assert len(result["published_source_dependencies"]) == 3
    else:
        assert "8d8 slashing" in text and "pushed 10 feet" in text
        assert "300-foot line, 10 feet wide" in text
        assert "only at the GM's discretion" in text
        assert "Limit: The printed source defines no separate use limit for Heaven-Splitting Gale." in text
        assert len(result["published_source_dependencies"]) == 2
    assert load_forged_action_binding(env["db"], env["project_id"], record["record_id"])["full_description"] == text


@pytest.mark.parametrize("mutation", ["source_hash", "published_text", "form", "augment", "cost", "version"])
def test_profile_rejects_unsupported_or_changed_design(forged_environment, mutation):
    env = forged_environment
    technique = deepcopy(env["techniques"][0][0])
    if mutation == "source_hash":
        technique["primary_sphere_effect"]["source"]["source_hash"] = "0" * 64
    elif mutation == "published_text":
        technique["primary_sphere_effect"]["published_text"] += "\nDeal extra damage."
    elif mutation == "form":
        technique["base_form"]["form_id"] = "strike"
    elif mutation == "augment":
        technique["augments"].append({"augment_id": "increased_damage"})
    elif mutation == "cost":
        technique["cp_cost"]["final"] = 0
    else:
        technique["construction"]["generator_version"] = 2
    with pytest.raises(FoundryError) as error:
        forged_action_projection(technique, env["root"])
    assert error.value.code == "COMMAND4_FORGED_MECHANICS_UNRESOLVED"


@pytest.mark.parametrize("index", [0, 1])
def test_provider_rederives_forge_record_and_acquisition(forged_environment, tmp_path, index):
    env = forged_environment
    record = env["techniques"][index][1]
    binding = load_forged_action_binding(env["db"], env["project_id"], record["record_id"])
    candidate = {key: binding[key] for key in ("record_id", "record_hash", "source", "name", "full_description")}
    candidate.update(constructed_forged_source_binding=binding, source_packet_ids=["creation"], missing_fields=["unambiguous_locked_mechanics_source"])
    (tmp_path / "Command_1").mkdir()
    (tmp_path / "Command_1/Build_Request.json").write_text(json.dumps({"project_id": env["project_id"]}))
    source = binding["source"]
    packet = {"record_id": record["record_id"], "record_hash": record["record_hash"], "advancement_kind": "forged_technique_creation", "source_evidence": [{"source_path": source["path"], "source_hash": source["sha256"], "source_anchor": source["anchor"]}]}
    author = Command4ProviderAuthoring(workspace_service=SimpleNamespace(db=env["db"]))
    assert author._resolve_locked_source_proof(tmp_path, candidate, {"creation": packet}, ())["constructed_forged_source_binding"] == binding
    forged = deepcopy(candidate)
    forged["full_description"] = forged["full_description"].replace("Cost: 4", "Cost: 0")
    forged["constructed_forged_source_binding"]["full_description"] = forged["full_description"]
    with pytest.raises(FoundryError):
        validate_forged_action_candidate(env["db"], env["project_id"], forged)
    packet["source_evidence"][0]["source_hash"] = "0" * 64
    with pytest.raises(FoundryError) as error:
        author._resolve_locked_source_proof(tmp_path, candidate, {"creation": packet}, ())
    assert error.value.code == "COMMAND4_FORGED_ACQUISITION_MISMATCH"
