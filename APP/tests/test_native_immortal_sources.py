"""Shared native-source coverage and adversarial causal-boundary checks."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core import FoundryError
from character_creation.constructed_arts.immortal_art import construct_immortal_art, load_immortal_art_authority
from character_creation.constructed_arts.native_immortal_sources import (
    NATIVE_COMMITMENT_KIND, NATIVE_SOURCE_IDS, native_source_row, validate_native_source,
)
from character_creation.constructed_arts.records import build_immortal_art_record, validate_constructed_art_record
from character_creation.constructed_arts.sources import installed_factory_root
from character_creation.path_attainment import native_path_progressions
from stage2.service import _binding
from factory_authoring.immortal_art_mechanics import immortal_action_text
from tests.test_constructed_immortal_art_integration import _immortal_environment, _event, _compile_art, _project_immortal_art

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("body_refining", "tianxia.subpath.body.bone_monarch", "CON"),
    ("qi_cultivation", "tianxia.subpath.qi.heaven_splitting_conceptual_severance", "INT"),
    ("spirit_awakening", "tianxia.tradition.spirit.dreamweaver", "WIS"),
]


@pytest.fixture(scope="module", params=CASES, ids=[x[0] for x in CASES])
def native_env(request, catalog_environment):
    kind, subpath, ability = request.param
    # Source/provenance checks must not depend on a fresh random refinement roll.
    # This supported owner seed keeps the real v2 refinement checks enabled.
    env = _immortal_environment(catalog_environment, "tianxia.path." + kind, subpath, ability,
                               autogen_seed="native-source-authority.3")
    creator, project = env["creator"], env["project"]
    records = creator._locked_records_for_project(project["project_id"])
    path = records["tianxia.path." + kind]
    progression = path["compatibility"]["factory"]["stage2_authority"]["progression_by_cl"]
    rows = [
        {"kind": "starting_state", "effective_cl": 1, "parameters": {"ability_scores": env["state"]["ability_scores"]}},
        {"kind": "path_acquisition", "effective_cl": 1, "record_id": path["record_id"]},
    ]
    rows += [{"kind": "level_advance", "effective_cl": cl, "record_id": progression[str(cl)]["feature_record_ids"][0]} for cl in range(1, 21)]
    # No Subpath row: native coverage must be independent of Subpath choice.
    arts = creator._immortal_art_constructions(env["run"], project, {}, rows, records, 20, intent_hash=env["run"]["request"]["request_sha256"])
    assert len(arts) == 2
    assert all(art["source"]["feature_record_hash_kind"] == NATIVE_COMMITMENT_KIND for art, _ in arts)
    art, record = arts[0]
    prefix = [_event("event.path.native", "path_acquisition", path["record_id"], path["record_hash"], cl=1)]
    for cl in range(1, 16):
        ids = progression[str(cl)]["feature_record_ids"]
        event = _event(f"event.native.level.{cl}", "level_advance", ids[0], records[ids[0]]["record_hash"], cl=cl,
                       outputs={"native_path_progressions": native_path_progressions([path], cl)})
        event["advancement"]["authority_bindings"] = [_binding(records[rid], "path_automatic_feature_authority", None) for rid in ids]
        prefix.append(event)
    state = deepcopy(env["state"])
    state["subpaths"] = []
    state["record_event_ids"] = {path["record_id"]: "event.path.native"}
    return {**env, "arts": arts, "art": art, "record": record, "prefix": prefix, "state": state,
            "path": path, "records": records, "rows": rows, "kind": kind}


def test_every_native_path_constructs_two_distinct_source_arts(native_env):
    env = native_env
    assert len({art["source_record_id"] for art, _ in env["arts"]}) == 2
    assert [art["cl_created"] for art, _ in env["arts"]] == [15, 20]
    for art, record in env["arts"]:
        verified = validate_constructed_art_record(record, root_dir=ROOT, factory_root=installed_factory_root(env["db"].settings.vendor_dir))
        assert verified == art
        factor = art["action_surface"]["factor_application"]
        assert factor["mode"] == "native_path_source_factor_v1"
        assert factor["factor_rules"]["text"]
        assert factor["effective_effect"]["base_source_effect"] == art["source"]["action_surface"]["effect"]
        rendered = immortal_action_text(art)
        assert "Action Type: " + art["action_surface"]["activation"] in rendered
        assert '"factor_rules"' in rendered
        assert f"Cost: {art['activation_cp']} " in rendered
        if art["action_surface"].get("area"):
            assert "Area: " + art["action_surface"]["area"] in rendered
        if art["source"]["source_dependencies"]:
            assert "Source Dependencies:" in rendered


def test_native_art_passes_real_causal_stage2_boundary(native_env):
    blockers, outputs, bindings, _ = _compile_art(native_env)
    assert blockers == []
    assert outputs
    assert any(row["role"] == "immortal_art_native_feature_authority" for row in bindings)
    rows, indexes = _project_immortal_art(native_env, record=native_env["record"], outputs=outputs, bindings=bindings)
    assert indexes and rows[0]["record_id"] == native_env["art"]["art_id"]


def test_native_art_still_refuses_an_unreachable_refinement_check(native_env):
    """A deterministic fixture must never bypass checked refinement."""
    env = native_env
    art = deepcopy(env["art"])
    modifier = art["construction"]["request"]["key_ability_modifier"]
    art["refinement_dc"] = 20 + art["pb_at_creation"] + modifier + 1
    with pytest.raises(FoundryError) as caught:
        env["creator"]._immortal_art_creation_parameters(
            env["run"], art, env["record"], index=0,
            intent_hash=env["run"]["request"]["request_sha256"],
        )
    assert caught.value.code == "CG1_IMMORTAL_ART_REFINEMENT_EXHAUSTED"
    assert len(caught.value.details["attempts"]) == 8


def test_native_projection_rejects_missing_feature_acquisition_binding(native_env):
    blockers, outputs, bindings, _ = _compile_art(native_env)
    assert blockers == []
    bindings = [row for row in bindings if row["role"] != "immortal_art_native_feature_authority"]
    with pytest.raises(FoundryError) as error:
        _project_immortal_art(native_env, record=native_env["record"], outputs=outputs, bindings=bindings)
    assert error.value.code == "PROJECTION_IMMORTAL_ART_FEATURE_RECORD_INVALID"


@pytest.mark.parametrize("mutation", ["missing_grant", "wrong_grant_hash", "wrong_path", "future_grant"])
def test_native_art_rejects_unearned_or_changed_feature_grant(native_env, mutation):
    prefix = deepcopy(native_env["prefix"])
    fid = native_env["art"]["source_record_id"]
    grant = native_env["art"]["source"]["acquired_at_cl"]
    event = next(row for row in prefix if row["advancement"]["target_cl"] == grant and row["advancement"]["kind"] == "level_advance")
    adv = event["advancement"]
    entry = adv["calculation"]["outputs"]["native_path_progressions"][0]
    if mutation == "missing_grant":
        entry["automatic_feature_record_ids"].remove(fid)
    elif mutation == "wrong_grant_hash":
        next(row for row in adv["authority_bindings"] if row["record_id"] == fid)["record_hash"] = "0" * 64
    elif mutation == "wrong_path":
        entry["path_id"] = "tianxia.path.unselected"
    else:
        adv["target_cl"] = 20
    blockers, *_ = _compile_art(native_env, prefix=prefix)
    assert "IMMORTAL_ART_NATIVE_FEATURE_GRANT_REQUIRED" in {b["code"] for b in blockers}


@pytest.mark.parametrize("mutation", ["action", "source_text", "dependency", "parent", "authored_placeholder"])
def test_native_record_rejects_coherently_reconstructed_source_tampering(native_env, mutation):
    request = deepcopy(native_env["art"]["construction"]["request"])
    source = next(row for row in request["known_sources"] if row["record_id"] == native_env["art"]["source_record_id"])
    if mutation == "action":
        source["action_surface"]["resource_cost"] += 1
    elif mutation == "source_text":
        source["published_text"] += "Changed source."
    elif mutation == "dependency":
        source["source_dependencies"].append({"dependency_id": "invented", "published_text": "Invented rule."})
    elif mutation == "parent":
        source["progression"]["parent_record_hash"] = "0" * 64
    else:
        source["action_surface"]["effect"] = "unknown"
    with pytest.raises(FoundryError):
        art = construct_immortal_art(load_immortal_art_authority(ROOT), request)
        validate_constructed_art_record(build_immortal_art_record(art), root_dir=ROOT,
                                       factory_root=installed_factory_root(native_env["db"].settings.vendor_dir))


def test_source_adapters_preserve_costs_target_bounds_and_causal_scaling(native_env):
    env = native_env
    factory = installed_factory_root(env["db"].settings.vendor_dir)
    for fid in NATIVE_SOURCE_IDS:
        if not fid.startswith(env["path"]["record_id"] + "."):
            continue
        row = native_source_row(ROOT, factory, feature_id=fid, parent_record=env["path"], owning_path_cl=15, construction_cl=15)
        action = row["action_surface"]
        assert action["source_mechanics"]["published_section"] == row["published_text"]
        assert action["resource_cost"] in (1, 2)
        if fid.endswith("domain_pressure"):
            assert action["area"].startswith("30-foot")
            assert len(row["source_dependencies"]) == 1
            assert "Heavy Soul" in row["source_dependencies"][0]["published_text"]
        if fid.endswith("featherfall"):
            assert action["target"].startswith("One falling creature")
        if fid.endswith("stamina_guard"):
            assert action["effect"]["damage_reduction"] == "1d10"
        with pytest.raises(FoundryError):
            native_source_row(ROOT, factory, feature_id=fid, parent_record=env["path"], owning_path_cl=1, construction_cl=15)


def test_registered_native_sources_cover_every_catalogued_subpath_owner():
    catalogue = json.loads((ROOT / "non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json").read_text())
    entries = catalogue["entries"]
    assert len(entries) == 156
    for entry in entries:
        pid = entry.get("owning_path_id") or entry.get("parent_path_id") or entry.get("path_id")
        assert len([fid for fid in NATIVE_SOURCE_IDS if fid.startswith(pid + ".feature.")]) == 2, entry["canonical_id"]
