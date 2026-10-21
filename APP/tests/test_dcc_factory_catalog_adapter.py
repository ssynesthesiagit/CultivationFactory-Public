"""Focused tests for the inactive Factory-to-DCC publication compiler."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Sequence
from unittest.mock import patch

import pytest

from app.core import sha256_json
from character_creation.creative_controller import (
    CreativeControllerError,
    PROFILE_REGISTRY_SCHEMA,
    REVIEWED_SEMANTIC_OVERLAY_SCHEMA,
    SOURCE_RIGHTS_RECEIPT_SCHEMA,
    build_reviewed_semantic_overlay,
    build_semantic_profile_registry,
    compile_factory_catalog_publication,
    seal_source_rights_receipt,
    validate_factory_catalog_publication_candidate,
)
from contracts.canonical import canonical_record_hash


CONTENT_KINDS = {
    "path": "path",
    "cultivation_method": "method",
    "foundation": "foundation",
    "background": "background",
    "origin_insight": "origin",
    "sphere": "sphere",
    "talent": "talent",
    "cultivation_insight": "insight",
    "path_feature": "milestone",
    "background_sphere": "sphere",
    "background_talent": "talent",
    "item": "item",
    "subpath": "path",
    "tradition": "path",
}


def _digest(label: str) -> str:
    return sha256_json({"dcc_factory_adapter_fixture": label})


def _active_rights_trust() -> dict:
    unsigned = {
        "schema": "TianxiaFoundry.SourceRightsAuthorityTrustManifest.v1",
        "version": 1,
        "status": "ACTIVE",
        "active_rights_authority_sha256": _digest("owner-rights-authority"),
        "revoked_rights_authority_sha256s": [],
    }
    return {**unsigned, "manifest_sha256": sha256_json(unsigned)}


def _fragment(*, theme: str = "disciplined", resource: str = "qi") -> dict:
    return {
        "theme_tags": [theme],
        "role_tags": ["controller"],
        "capability_families": ["shaping"],
        "combat_functions": ["control"],
        "resource_loop": {"consumes": [resource], "produces": [], "cadence": "per_turn", "setup": "light"},
        "progression": {
            "minimum_cl": 1,
            "identity_online_cl": 1,
            "signature_cl": 5,
            "late_progression_tags": ["scales_late"],
        },
        "synergy_edges": [],
        "redundancy_groups": [],
        "tradeoffs": [],
        "complexity": {"band": "moderate", "factors": ["resource_timing"]},
    }


def _registry() -> dict:
    return build_semantic_profile_registry(
        {
            "schema": PROFILE_REGISTRY_SCHEMA,
            "version": 1,
            "adapter_version_sha256": _digest("adapter-v1"),
            "vocabularies": {
                "theme_tags": ["disciplined", "chakra_cycle", "gu_ecology"],
                "role_tags": ["controller"],
                "capability_families": ["shaping"],
                "combat_functions": ["control"],
                "resource_families": ["qi", "chakra", "gu_essence"],
                "late_progression_tags": ["scales_late"],
                "complexity_factors": ["resource_timing"],
                "tradeoff_codes": [],
            },
            "profiles": [
                {
                    "profile_id": "profile.system.base",
                    "inherits": [],
                    "source_fact_ids": ["fact.profile.base"],
                    **_fragment(),
                }
            ],
        }
    )


def _catalog_record(record_id: str, content_type: str, *, status: str = "published", minimum_cl: int = 1) -> dict:
    record = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": content_type,
        "display_name": "Prose must never become controller semantics",
        "aliases": ["also ignored"],
        "tags": ["generic"],
        "publication": {"status": status, "published_version": "fixture.1", "replaced_by": None},
        "content_binding": {"pack_id": "fixture.system.pack", "pack_version": "1", "pack_hash": _digest("pack")},
        "source": {
            "source_id": "source.fixture",
            "path": "private fixture prose",
            "anchor": f"record:{record_id}",
            "source_hash": _digest(f"source:{record_id}"),
            "source_text": "This prose is deliberately not semantic authority.",
        },
        "summary": "Ignored prose.",
        "legality": {
            "acquisition_channels": ["advancement"],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": minimum_cl,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": [],
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": "Ignored.",
            "full_description": "Ignored prose.",
            "surfaces": ["rules_catalog"],
            "sort_key": record_id,
        },
        "compatibility": {"factory": {"stage2_authority": {"minimum_cl": minimum_cl}}, "gm_screen": {}},
        "revision_history": [{"version": "1", "summary": "fixture", "previous_record_hash": None}],
        "regression_tests": [{"test_id": f"{record_id}.fixture", "kind": "fixture", "input": {}, "expected": True}],
        "record_hash": "0" * 64,
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def _overlay(records: list[dict], registry: dict, *, themes: dict[str, tuple[str, str]] | None = None) -> dict:
    themes = themes or {}
    facts = [
        {"source_fact_id": "fact.profile.base", "status": "VERIFIED", "source_projection_sha256": _digest("profile-fact")}
    ]
    receipts = []
    rows = []
    for record in records:
        fact_id = f"fact.record.{record['record_id']}"
        receipt_id = f"rights.{record['record_id']}"
        facts.append({"source_fact_id": fact_id, "status": "VERIFIED", "source_projection_sha256": _digest(fact_id)})
        receipts.append(
            seal_source_rights_receipt(
                {
                    "schema": SOURCE_RIGHTS_RECEIPT_SCHEMA,
                    "receipt_id": receipt_id,
                    "status": "VERIFIED",
                    "source_id": record["source"]["source_id"],
                    "source_hash": record["source"]["source_hash"],
                    "allowed_uses": ["DCC_SEMANTIC_PUBLICATION"],
                    "rights_authority_id": "authority.owner.review",
                    "rights_authority_sha256": _digest("owner-rights-authority"),
                }
            )
        )
        theme, resource = themes.get(record["record_id"], ("disciplined", "qi"))
        rows.append(
            {
                "choice_id": record["record_id"],
                "choice_record_sha256": record["record_hash"],
                "source_rights_receipt_id": receipt_id,
                "profile_ids": ["profile.system.base"],
                "source_fact_ids": [fact_id],
                "semantics": _fragment(theme=theme, resource=resource),
            }
        )
    return build_reviewed_semantic_overlay(
        {
            "schema": REVIEWED_SEMANTIC_OVERLAY_SCHEMA,
            "version": 1,
            "semantic_profile_registry_sha256": registry["registry_sha256"],
            "source_facts": facts,
            "source_rights_receipts": receipts,
            "records": rows,
        }
    )


def _compile(records: list[dict], registry: dict | None = None, overlay: dict | None = None) -> dict:
    registry = registry or _registry()
    overlay = overlay or _overlay(records, registry)
    with patch(
        "character_creation.creative_controller.factory_catalog_adapter.load_factory_source_rights_authority_trust",
        return_value=_active_rights_trust(),
    ):
        return compile_factory_catalog_publication(records, registry, overlay)


def test_all_factory_families_compile_with_generic_type_mapping() -> None:
    records = [_catalog_record(f"fixture.{content_type}", content_type) for content_type in CONTENT_KINDS]
    candidate = _compile(records)
    assert candidate["status"] == "READY_FOR_OWNER_REVIEW"
    assert candidate["activation_policy"] == "INACTIVE_REQUIRES_OWNER_PUBLICATION"
    assert candidate["diagnostics"] == []
    assert candidate["authority_bundle"] is not None
    assert {row["choice_id"]: row["choice_kind"] for row in candidate["typed_records"]} == {
        record["record_id"]: CONTENT_KINDS[record["content_type"]] for record in records
    }
    with patch(
        "character_creation.creative_controller.factory_catalog_adapter.load_factory_source_rights_authority_trust",
        return_value=_active_rights_trust(),
    ):
        assert validate_factory_catalog_publication_candidate(candidate) == candidate


def test_chakra_and_gu_use_data_only_and_preserve_explicit_semantics() -> None:
    registry = _registry()
    records = [
        _catalog_record("chakra.sphere.eight_gates", "sphere"),
        _catalog_record("gu.sphere.living_arsenal", "sphere"),
    ]
    overlay = _overlay(
        records,
        registry,
        themes={
            "chakra.sphere.eight_gates": ("chakra_cycle", "chakra"),
            "gu.sphere.living_arsenal": ("gu_ecology", "gu_essence"),
        },
    )
    candidate = _compile(records, registry, overlay)
    semantics = {row["choice_id"]: row["semantics"] for row in candidate["typed_records"]}
    assert semantics["chakra.sphere.eight_gates"]["theme_tags"] == ["chakra_cycle"]
    assert semantics["gu.sphere.living_arsenal"]["resource_loop"]["consumes"] == ["gu_essence"]


def test_compilation_is_permutation_deterministic_and_detached() -> None:
    records = [_catalog_record("fixture.path", "path"), _catalog_record("fixture.sphere", "sphere")]
    registry = _registry()
    overlay = _overlay(records, registry)
    original_records = deepcopy(records)
    original_overlay = deepcopy(overlay)
    first = _compile(records, registry, overlay)
    reversed_overlay = build_reviewed_semantic_overlay(
        {key: list(reversed(value)) if key in {"records", "source_facts"} else value for key, value in overlay.items() if key != "overlay_sha256"}
    )
    second = _compile(list(reversed(records)), registry, reversed_overlay)
    assert first == second
    assert records == original_records
    assert overlay == original_overlay


def test_missing_stale_or_orphan_overlay_blocks_without_bundle() -> None:
    records = [_catalog_record("fixture.path", "path")]
    registry = _registry()
    missing = _overlay([], registry)
    blocked = _compile(records, registry, missing)
    assert blocked["status"] == "BLOCKED"
    assert blocked["authority_bundle"] is None
    assert [row["code"] for row in blocked["diagnostics"]] == ["DCC_REVIEWED_OVERLAY_MISSING"]

    stale_input = _overlay(records, registry)
    stale_input["records"][0]["choice_record_sha256"] = _digest("old-record")
    stale = build_reviewed_semantic_overlay({key: value for key, value in stale_input.items() if key != "overlay_sha256"})
    assert _compile(records, registry, stale)["diagnostics"][0]["code"] == "DCC_REVIEWED_OVERLAY_STALE"

    orphan_records = [_catalog_record("fixture.orphan", "sphere")]
    orphan = _overlay(orphan_records, registry)
    assert _compile(records, registry, orphan)["status"] == "BLOCKED"
    assert {row["code"] for row in _compile(records, registry, orphan)["diagnostics"]} == {
        "DCC_REVIEWED_OVERLAY_MISSING",
        "DCC_REVIEWED_OVERLAY_ORPHAN",
    }


def test_unverified_facts_unknown_profiles_and_unresolved_dependencies_block() -> None:
    records = [_catalog_record("fixture.path", "path")]
    registry = _registry()
    overlay = _overlay(records, registry)
    overlay["source_facts"][0]["status"] = "DRAFT"
    overlay = build_reviewed_semantic_overlay({key: value for key, value in overlay.items() if key != "overlay_sha256"})
    assert "DCC_SEMANTIC_SOURCE_FACT_UNVERIFIED" in {row["code"] for row in _compile(records, registry, overlay)["diagnostics"]}

    dependent = _catalog_record("fixture.dependent", "talent")
    dependent["dependencies"] = ["fixture.absent"]
    dependent["record_hash"] = canonical_record_hash(dependent)
    result = _compile([dependent])
    assert result["status"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "DCC_FACTORY_DEPENDENCY_UNRESOLVED"


def test_incomplete_semantics_semantic_targets_and_dependency_cycles_block() -> None:
    registry = _registry()
    record = _catalog_record("fixture.path", "path")
    overlay_input = {key: value for key, value in _overlay([record], registry).items() if key != "overlay_sha256"}
    overlay_input["records"][0]["profile_ids"] = []
    overlay_input["records"][0]["semantics"]["role_tags"] = []
    incomplete = build_reviewed_semantic_overlay(overlay_input)
    result = _compile([record], registry, incomplete)
    assert result["status"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "DCC_CHOICE_SEMANTICS_INCOMPLETE"

    target_input = {key: value for key, value in _overlay([record], registry).items() if key != "overlay_sha256"}
    fact_id = target_input["records"][0]["source_fact_ids"][0]
    target_input["records"][0]["semantics"]["synergy_edges"] = [
        {"target_choice_id": "fixture.absent", "relation": "role_reinforcement", "source_fact_ids": [fact_id]}
    ]
    target = build_reviewed_semantic_overlay(target_input)
    assert _compile([record], registry, target)["diagnostics"][0]["code"] == "DCC_SEMANTIC_TARGET_UNRESOLVED"

    first = _catalog_record("fixture.first", "sphere")
    second = _catalog_record("fixture.second", "talent")
    first["dependencies"] = [second["record_id"]]
    second["dependencies"] = [first["record_id"]]
    first["record_hash"] = canonical_record_hash(first)
    second["record_hash"] = canonical_record_hash(second)
    cycle = _compile([first, second])
    assert cycle["status"] == "BLOCKED"
    assert [row["code"] for row in cycle["diagnostics"]] == ["DCC_FACTORY_DEPENDENCY_CYCLE", "DCC_FACTORY_DEPENDENCY_CYCLE"]


def test_tampered_or_duplicate_canonical_records_fail_closed() -> None:
    record = _catalog_record("fixture.path", "path")
    tampered = deepcopy(record)
    tampered["legality"]["minimum_cl"] = 15
    with pytest.raises(CreativeControllerError) as error:
        _compile([tampered])
    assert error.value.code == "DCC_FACTORY_CATALOG_RECORD_HASH_INVALID"
    registry = _registry()
    overlay = _overlay([record], registry)
    with pytest.raises(CreativeControllerError) as error:
        _compile([record, deepcopy(record)], registry, overlay)
    assert error.value.code == "DCC_CONTENT_DUPLICATE_CHOICE_ID"


def test_unsupported_type_and_missing_rights_receipt_fail_closed() -> None:
    record = _catalog_record("fixture.unknown", "unmapped_exotic_type")
    candidate = _compile([record])
    assert candidate["status"] == "BLOCKED"
    assert candidate["diagnostics"][0]["code"] == "DCC_FACTORY_CONTENT_TYPE_UNSUPPORTED"

    registry = _registry()
    overlay_input = {key: value for key, value in _overlay([_catalog_record("fixture.path", "path")], registry).items() if key != "overlay_sha256"}
    del overlay_input["records"][0]["source_rights_receipt_id"]
    with pytest.raises(CreativeControllerError) as error:
        build_reviewed_semantic_overlay(overlay_input)
    assert error.value.code == "DCC_SCHEMA_MISSING_FIELD"


def test_action_content_type_is_not_a_factory_semantic_choice() -> None:
    record = _catalog_record("fixture.action", "action")
    candidate = _compile([record])
    assert candidate["status"] == "BLOCKED"
    assert candidate["diagnostics"][0]["code"] == "DCC_FACTORY_CONTENT_TYPE_UNSUPPORTED"


def test_rights_receipt_existence_status_source_use_and_fixed_authority_are_gated() -> None:
    registry = _registry()
    record = _catalog_record("fixture.path", "path")
    base = {key: value for key, value in _overlay([record], registry).items() if key != "overlay_sha256"}

    missing = deepcopy(base)
    missing["source_rights_receipts"] = []
    result = _compile([record], registry, build_reviewed_semantic_overlay(missing))
    assert result["diagnostics"][0]["code"] == "DCC_SOURCE_RIGHTS_RECEIPT_MISSING"

    invalid = deepcopy(base)
    receipt_input = {key: value for key, value in invalid["source_rights_receipts"][0].items() if key != "receipt_sha256"}
    receipt_input["status"] = "REVOKED"
    receipt_input["source_hash"] = _digest("different-source")
    receipt_input["allowed_uses"] = ["SOME_OTHER_USE"]
    receipt_input["rights_authority_sha256"] = _digest("untrusted-rights-authority")
    invalid["source_rights_receipts"] = [seal_source_rights_receipt(receipt_input)]
    result = _compile([record], registry, build_reviewed_semantic_overlay(invalid))
    assert result["status"] == "BLOCKED"
    assert result["diagnostics"][0] == {
        "code": "DCC_SOURCE_RIGHTS_RECEIPT_INVALID",
        "choice_id": "fixture.path",
        "values": ["allowed_uses", "rights_authority_sha256", "source_hash", "status"],
    }


def test_fixed_rights_trust_is_checked_against_the_current_owner_authority() -> None:
    registry = _registry()
    record = _catalog_record("fixture.path", "path")
    result = compile_factory_catalog_publication([record], registry, _overlay([record], registry))
    assert result["status"] == "BLOCKED"
    assert result["source_rights_authority_sha256"] is not None
    assert "DCC_SOURCE_RIGHTS_AUTHORITY_UNPUBLISHED" not in {row["code"] for row in result["diagnostics"]}


def test_candidate_validator_rejects_rehashed_bundle_or_registry_substitution() -> None:
    registry = _registry()
    first_record = _catalog_record("fixture.first", "sphere")
    second_record = _catalog_record("fixture.second", "talent")
    first = _compile([first_record], registry, _overlay([first_record], registry))
    second = _compile([second_record], registry, _overlay([second_record], registry))

    substituted = deepcopy(first)
    substituted["authority_bundle"] = second["authority_bundle"]
    substituted["candidate_sha256"] = sha256_json({key: value for key, value in substituted.items() if key != "candidate_sha256"})
    with patch(
        "character_creation.creative_controller.factory_catalog_adapter.load_factory_source_rights_authority_trust",
        return_value=_active_rights_trust(),
    ), pytest.raises(CreativeControllerError) as error:
        validate_factory_catalog_publication_candidate(substituted)
    assert error.value.code == "DCC_FACTORY_PUBLICATION_CANDIDATE_AUTHORITY_UNBOUND"

    substituted = deepcopy(first)
    substituted["semantic_profile_registry_sha256"] = _digest("different-registry")
    substituted["candidate_sha256"] = sha256_json({key: value for key, value in substituted.items() if key != "candidate_sha256"})
    with patch(
        "character_creation.creative_controller.factory_catalog_adapter.load_factory_source_rights_authority_trust",
        return_value=_active_rights_trust(),
    ), pytest.raises(CreativeControllerError) as error:
        validate_factory_catalog_publication_candidate(substituted)
    assert error.value.code == "DCC_FACTORY_PUBLICATION_CANDIDATE_AUTHORITY_UNBOUND"


def test_ready_candidate_validator_rechecks_fixed_rights_trust() -> None:
    registry = _registry()
    record = _catalog_record("fixture.path", "path")
    candidate = _compile([record], registry, _overlay([record], registry))

    with pytest.raises(CreativeControllerError) as error:
        validate_factory_catalog_publication_candidate(candidate)
    assert error.value.code == "DCC_SOURCE_RIGHTS_AUTHORITY_TRUST_MISMATCH"

    different = _active_rights_trust()
    different["active_rights_authority_sha256"] = _digest("different-fixed-authority")
    different["manifest_sha256"] = sha256_json({key: value for key, value in different.items() if key != "manifest_sha256"})
    with patch(
        "character_creation.creative_controller.factory_catalog_adapter.load_factory_source_rights_authority_trust",
        return_value=different,
    ):
        with pytest.raises(CreativeControllerError) as error:
            validate_factory_catalog_publication_candidate(candidate)
    assert error.value.code == "DCC_SOURCE_RIGHTS_AUTHORITY_TRUST_MISMATCH"

def test_add_remove_retire_and_rebalance_are_hash_visible_data_updates() -> None:
    registry = _registry()
    base_record = _catalog_record("gu.sphere.base", "sphere")
    added_record = _catalog_record("gu.sphere.flight", "sphere")
    base_records = [base_record, added_record]
    base = _compile(base_records, registry, _overlay(base_records, registry))

    third_record = _catalog_record("gu.sphere.venom", "sphere")
    added_records = [*base_records, third_record]
    added = _compile(added_records, registry, _overlay(added_records, registry))
    assert added["candidate_sha256"] != base["candidate_sha256"]

    retired_record = _catalog_record("gu.sphere.base", "sphere", status="deprecated")
    retired = _compile([retired_record], registry, _overlay([retired_record], registry))
    assert retired["typed_records"][0]["lifecycle"] == "RETIRED"
    assert retired["typed_records"][0]["eligible_for_new_builds"] is False

    rebalanced_record = _catalog_record("gu.sphere.base", "sphere", minimum_cl=7)
    rebalanced = _compile([rebalanced_record], registry, _overlay([rebalanced_record], registry))
    assert rebalanced["candidate_sha256"] not in {base["candidate_sha256"], retired["candidate_sha256"]}
    base_by_id = {row["choice_id"]: row for row in base["typed_records"]}
    assert rebalanced["typed_records"][0]["typed_authority_sha256"] != base_by_id["gu.sphere.base"]["typed_authority_sha256"]

    removed = _compile([base_record], registry, _overlay([base_record], registry))
    assert removed["candidate_sha256"] != base["candidate_sha256"]
    assert [row["choice_id"] for row in removed["typed_records"]] == ["gu.sphere.base"]


def test_overlay_collection_bound_is_enforced_before_iteration() -> None:
    registry = _registry()
    with pytest.raises(CreativeControllerError) as error:
        build_reviewed_semantic_overlay(
            {
                "schema": REVIEWED_SEMANTIC_OVERLAY_SCHEMA,
                "version": 1,
                "semantic_profile_registry_sha256": registry["registry_sha256"],
                "source_facts": [None] * 16385,
                "source_rights_receipts": [],
                "records": [],
            }
        )
    assert error.value.code == "DCC_SCHEMA_LIMIT"


def test_catalogue_bound_is_checked_before_materialization() -> None:
    class OversizedBomb(Sequence):
        def __len__(self) -> int:
            return 8193

        def __getitem__(self, index: int) -> object:
            raise AssertionError("oversized input was materialized")

    registry = _registry()
    with pytest.raises(CreativeControllerError) as error:
        compile_factory_catalog_publication(OversizedBomb(), registry, _overlay([], registry))
    assert error.value.code == "DCC_SCHEMA_LIMIT"
