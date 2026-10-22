"""Focused tests for the deterministic Factory semantic library."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import quote

import pytest

from app.core import sha256_json
from character_creation.creative_controller import (
    CreativeControllerError,
    NON_CHOICE_DEPENDENCY_AUTHORITY_SCHEMA,
    build_factory_semantic_library,
    compile_factory_catalog_publication,
)
from character_creation.creative_controller.factory_catalog_adapter import _choice_kind
from contracts.canonical import canonical_record_hash


def _digest(label: str) -> str:
    return sha256_json({"dcc_semantic_library_fixture": label})


def _record(
    record_id: str,
    content_type: str,
    *,
    minimum_cl: int | None = 1,
    dependencies: list[str] | None = None,
    raw_record: dict | None = None,
    source_id: str = "source.fixture",
) -> dict:
    record = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": content_type,
        "display_name": "Ignored display prose",
        "aliases": [],
        "tags": [],
        "publication": {"status": "published", "published_version": "fixture.1", "replaced_by": None},
        "content_binding": {"pack_id": "fixture.pack", "pack_version": "1", "pack_hash": _digest("pack")},
        "source": {
            "source_id": source_id,
            "path": "fixture prose path",
            "anchor": f"record:{record_id}",
            "source_hash": _digest("source"),
            "source_text": "Ignored source prose",
        },
        "summary": "Ignored summary prose",
        "legality": {
            "acquisition_channels": ["advancement"],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": minimum_cl,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": list(dependencies or []),
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": "Ignored prose",
            "full_description": "Ignored prose",
            "surfaces": ["rules_catalog"],
            "sort_key": record_id,
        },
        "compatibility": {
            "factory": {
                "raw_projection": {"raw_record": deepcopy(raw_record or {})},
            },
            "gm_screen": {},
        },
        "revision_history": [{"version": "1", "summary": "fixture", "previous_record_hash": None}],
        "regression_tests": [{"test_id": f"{record_id}.fixture", "kind": "fixture", "input": {}, "expected": True}],
        "record_hash": "0" * 64,
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def _build(records: list[dict]) -> dict:
    return build_factory_semantic_library(
        records,
        rights_authority_id="authority.owner.review",
        rights_authority_sha256=_digest("owner-rights"),
    )


def _non_choice_authority(bindings: list[dict]) -> dict:
    unsigned = {
        "schema": NON_CHOICE_DEPENDENCY_AUTHORITY_SCHEMA,
        "version": 1,
        "bindings": sorted(bindings, key=lambda row: row["record_id"]),
    }
    return {**unsigned, "authority_sha256": sha256_json(unsigned)}


def _binding(record: dict, dependency_ids: list[str]) -> dict:
    return {
        "record_id": record["record_id"],
        "content_type": record["content_type"],
        "record_hash": record["record_hash"],
        "source_id": record["source"]["source_id"],
        "source_hash": record["source"]["source_hash"],
        "non_choice_dependency_ids": sorted(dependency_ids),
    }


def _compile(records: list[dict], library: dict, *, non_choice_authority: dict | None = None) -> dict:
    with patch(
        "character_creation.creative_controller.factory_catalog_adapter.load_factory_source_rights_authority_trust",
        return_value=library["source_rights_trust"],
    ):
        if non_choice_authority is None:
            return compile_factory_catalog_publication(records, library["registry"], library["overlay"])
        with patch(
            "character_creation.creative_controller.factory_catalog_adapter.load_factory_non_choice_dependency_authority",
            return_value=non_choice_authority,
        ):
            return compile_factory_catalog_publication(records, library["registry"], library["overlay"])


def test_library_is_deterministic_under_record_reordering_and_rights_are_deduplicated() -> None:
    sphere = _record("tianxia.sphere.chakra", "sphere", raw_record={"canonical_sphere_id": "tianxia.sphere.chakra"})
    talent = _record(
        "chakra.talent.flow",
        "talent",
        dependencies=[sphere["record_id"]],
        raw_record={"owning_canonical_sphere_id": sphere["record_id"], "access_category": "Open", "realm_band": "Mortal", "minimum_cl": 1},
    )
    first = _build([sphere, talent])
    second = _build([deepcopy(talent), deepcopy(sphere)])
    assert first == second
    assert len(first["overlay"]["source_rights_receipts"]) == 1


def test_library_canonical_bytes_match_across_cold_hash_seeded_processes() -> None:
    repository = Path(__file__).resolve().parents[2]
    test_module = Path(__file__).resolve()
    script = f"""
import importlib.util
from app.core import canonical_json
module_spec = importlib.util.spec_from_file_location('dcc_semantic_library_fixture', {str(test_module)!r})
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
sphere = module._record('cold.sphere', 'sphere', raw_record={{'canonical_sphere_id': 'cold.sphere'}})
talent = module._record('cold.talent', 'talent', dependencies=['cold.sphere'], raw_record={{'owning_canonical_sphere_id': 'cold.sphere', 'minimum_cl': 1}})
print(canonical_json(module._build([talent, sphere])))
"""
    outputs: list[str] = []
    for seed in ("17", "2718"):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository / "APP")
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=repository,
                env=environment,
                text=True,
            )
        )
    assert outputs[0] == outputs[1]


def test_prose_mutation_does_not_change_derived_semantics_or_source_facts() -> None:
    record = _record("gu.sphere.living_arsenal", "sphere", raw_record={"canonical_sphere_id": "gu.sphere.living_arsenal", "full_description": "ignored"})
    first = _build([record])
    mutated = deepcopy(record)
    mutated["display_name"] = "Different prose"
    mutated["summary"] = "Different prose"
    mutated["source"]["source_text"] = "Different prose"
    mutated["compatibility"]["factory"]["raw_projection"]["raw_record"]["full_description"] = "Different prose"
    mutated["record_hash"] = canonical_record_hash(mutated)
    second = _build([mutated])
    assert first["registry"] == second["registry"]
    assert first["overlay"]["source_facts"] == second["overlay"]["source_facts"]
    assert first["overlay"]["records"][0]["semantics"] == second["overlay"]["records"][0]["semantics"]


def test_typed_fact_mutation_changes_fact_and_overlay_hashes() -> None:
    record = _record("chakra.talent.flow", "talent", raw_record={"owning_canonical_sphere_id": "tianxia.sphere.chakra", "minimum_cl": 1})
    first = _build([record])
    mutated = deepcopy(record)
    mutated["compatibility"]["factory"]["raw_projection"]["raw_record"]["minimum_cl"] = 2
    mutated["record_hash"] = canonical_record_hash(mutated)
    second = _build([mutated])
    assert first["overlay"]["source_facts"][0]["source_projection_sha256"] != second["overlay"]["source_facts"][0]["source_projection_sha256"]
    assert first["overlay"]["overlay_sha256"] != second["overlay"]["overlay_sha256"]


def test_synthetic_chakra_and_gu_ids_are_data_only_theme_tokens() -> None:
    records = [
        _record("chakra.sphere.eight_gates", "sphere", raw_record={"canonical_sphere_id": "chakra.sphere.eight_gates"}),
        _record("gu.sphere.living_arsenal", "sphere", raw_record={"canonical_sphere_id": "gu.sphere.living_arsenal"}),
    ]
    library = _build(records)
    assert library["registry"]["vocabulary_authority"]["vocabularies"]["theme_tags"] == [
        "chakra.sphere.eight_gates",
        "gu.sphere.living_arsenal",
    ]


def test_builder_accepts_item_as_an_exact_semantic_choice_kind() -> None:
    record = _record("fixture.item", "item")
    record["compatibility"]["factory"]["stage2_authority"] = {
        "authority_complete": True,
        "allowed_kinds": ["typed_none"],
    }
    record["record_hash"] = canonical_record_hash(record)
    library = _build([record])
    assert library["overlay"]["records"][0]["choice_id"] == "fixture.item"
    assert _choice_kind(record) == "item"


def test_typed_background_and_shared_rule_dependencies_are_non_choice_but_unknown_is_not() -> None:
    background = _record(
        "fixture.background",
        "background",
        dependencies=["tianxia.background_sphere.example", "tianxia.background_talent.example", "tianxia.origin_insight.example"],
        raw_record={
            "sphere_ids": ["tianxia.background_sphere.example"],
            "talent_ids": ["tianxia.background_talent.example"],
            "origin_insight_ids": ["tianxia.origin_insight.example"],
        },
    )
    milestone = _record(
        "fixture.milestone",
        "path_feature",
        dependencies=["fixture.shared.rule"],
        raw_record={"feature_kind": "milestone", "granted_at_cl": 1, "minimum_cl": 1, "shared_rule_id": "fixture.shared.rule"},
    )
    authority = _non_choice_authority(
        [
            _binding(background, [
                "tianxia.background_sphere.example",
                "tianxia.background_talent.example",
                "tianxia.origin_insight.example",
            ]),
            _binding(milestone, ["fixture.shared.rule"]),
        ]
    )
    allowed = _build([background, milestone])
    candidate = _compile([background, milestone], allowed, non_choice_authority=authority)
    assert candidate["status"] == "READY_FOR_OWNER_REVIEW"
    assert candidate["diagnostics"] == []

    unknown = deepcopy(background)
    unknown["dependencies"] = ["fixture.arbitrary_unknown"]
    unknown["record_hash"] = canonical_record_hash(unknown)
    blocked_library = _build([unknown])
    blocked = _compile([unknown], blocked_library, non_choice_authority=authority)
    assert blocked["status"] == "BLOCKED"
    assert {row["code"] for row in blocked["diagnostics"]} == {"DCC_FACTORY_DEPENDENCY_UNRESOLVED"}

    forged_background = deepcopy(background)
    forged_background["dependencies"] = ["tianxia.background_sphere.forged"]
    forged_background["compatibility"]["factory"]["raw_projection"]["raw_record"]["sphere_ids"] = [
        "tianxia.background_sphere.forged"
    ]
    forged_background["record_hash"] = canonical_record_hash(forged_background)
    forged_background_result = _compile(
        [forged_background],
        _build([forged_background]),
        non_choice_authority=authority,
    )
    assert forged_background_result["status"] == "BLOCKED"
    assert {row["code"] for row in forged_background_result["diagnostics"]} == {"DCC_FACTORY_DEPENDENCY_UNRESOLVED"}

    forged_projection_background = deepcopy(background)
    forged_projection_background["dependencies"] = ["tianxia.background_sphere.forged"]
    forged_projection_background["compatibility"]["factory"]["raw_projection"]["sphere_ids"] = ["tianxia.background_sphere.forged"]
    forged_projection_background["compatibility"]["factory"]["raw_projection"]["raw_record"] = {}
    forged_projection_background["record_hash"] = canonical_record_hash(forged_projection_background)
    forged_projection_result = _compile(
        [forged_projection_background],
        _build([forged_projection_background]),
        non_choice_authority=authority,
    )
    assert forged_projection_result["status"] == "BLOCKED"
    assert {row["code"] for row in forged_projection_result["diagnostics"]} == {
        "DCC_FACTORY_DEPENDENCY_UNRESOLVED"
    }

    forged_path_feature = _record(
        "fixture.path_feature.example",
        "path_feature",
        dependencies=["fixture.shared.forged"],
        raw_record={"feature_kind": "milestone", "granted_at_cl": 1, "minimum_cl": 1, "shared_rule_id": "fixture.shared.forged"},
    )
    sealed_path_feature = _record(
        "fixture.path_feature.example",
        "path_feature",
        dependencies=["fixture.shared.rule"],
        raw_record={"feature_kind": "milestone", "granted_at_cl": 1, "minimum_cl": 1, "shared_rule_id": "fixture.shared.rule"},
    )
    stale_authority = _non_choice_authority(
        [
            _binding(sealed_path_feature, ["fixture.shared.rule"]),
        ]
    )
    forged_path_result = _compile(
        [forged_path_feature],
        _build([forged_path_feature]),
        non_choice_authority=stale_authority,
    )
    assert forged_path_result["status"] == "BLOCKED"
    assert {row["code"] for row in forged_path_result["diagnostics"]} == {"DCC_FACTORY_DEPENDENCY_UNRESOLVED"}

    stale_source = deepcopy(sealed_path_feature)
    stale_source["dependencies"] = ["fixture.shared.forged"]
    stale_source["compatibility"]["factory"]["raw_projection"]["raw_record"]["shared_rule_id"] = "fixture.shared.forged"
    stale_source["source"]["source_hash"] = _digest("changed-source")
    stale_source["record_hash"] = canonical_record_hash(stale_source)
    stale_source_binding = _binding(stale_source, ["fixture.shared.forged"])
    stale_source_binding["source_hash"] = sealed_path_feature["source"]["source_hash"]
    stale_source_authority = _non_choice_authority([stale_source_binding])
    stale_source_result = _compile(
        [stale_source],
        _build([stale_source]),
        non_choice_authority=stale_source_authority,
    )
    assert stale_source_result["status"] == "BLOCKED"
    assert {row["code"] for row in stale_source_result["diagnostics"]} == {
        "DCC_FACTORY_DEPENDENCY_UNRESOLVED"
    }


def test_current_live_catalog_compiles_read_only_with_generated_active_trust() -> None:
    configured_database = os.environ.get("CULTIVATION_FACTORY_LIVE_DB")
    if not configured_database:
        pytest.skip("set CULTIVATION_FACTORY_LIVE_DB to run the opt-in live fixture")
    database = Path(configured_database)
    if not database.is_file():
        pytest.skip("configured live fixture is not accessible")
    uri = f"file:{quote(str(database.resolve()), safe='/')}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT data_json FROM catalog_records WHERE contract_status='valid' ORDER BY record_id"
        ).fetchall()
    all_records = [json.loads(row[0]) for row in rows]
    records = [record for record in all_records if _choice_kind(record) is not None]
    expected_family_counts = {
        "background": 31,
        "background_sphere": 30,
        "background_talent": 77,
        "cultivation_insight": 547,
        "cultivation_method": 80,
        "foundation": 30,
        "item": 318,
        "origin_insight": 50,
        "path": 3,
        "path_feature": 56,
        "sphere": 85,
        "subpath": 122,
        "talent": 2988,
        "tradition": 34,
    }
    assert {record["content_type"] for record in records} == {
        "background",
        "cultivation_insight",
        "cultivation_method",
        "foundation",
        "origin_insight",
        "path",
        "path_feature",
        "sphere",
        "talent",
        "background_sphere",
        "background_talent",
        "subpath",
        "tradition",
        "item",
    }
    assert {
        content_type: sum(record["content_type"] == content_type for record in records)
        for content_type in expected_family_counts
    } == expected_family_counts
    assert len(records) == 4451
    assert hashlib.sha256(database.read_bytes()).hexdigest() == "531a61021542035f7d7404e513dbc2f8af9296cc2d854503d2392cece34feed3"
    library = _build(records)
    candidate = _compile(records, library)
    assert candidate["status"] == "READY_FOR_OWNER_REVIEW"
    assert candidate["diagnostics"] == []
    assert len(candidate["typed_records"]) == 4451
