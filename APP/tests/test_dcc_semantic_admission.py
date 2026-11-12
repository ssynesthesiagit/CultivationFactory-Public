"""Focused data-driven semantic-admission tests for the DCC."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

import pytest

from app.core import sha256_json
from character_creation.creative_controller import (
    CreativeControllerError,
    PROFILE_REGISTRY_SCHEMA,
    SEMANTIC_AUTHORITY_BUNDLE_SCHEMA,
    SEMANTIC_RECORD_AUTHORITY_SCHEMA,
    TYPED_SEMANTIC_RECORD_SCHEMA,
    admit_typed_semantics,
    build_semantic_authority_bundle,
    build_creative_predicate_menu,
    build_semantic_profile_registry,
    load_factory_semantic_authority_bundle_sha256,
    seal_typed_semantic_record,
    validate_typed_semantic_record,
)


def _d(label: str) -> str:
    return sha256_json({"semantic_admission_fixture": label})


def _fragment(
    *,
    themes: list[str] | None = None,
    roles: list[str] | None = None,
    capabilities: list[str] | None = None,
    functions: list[str] | None = None,
    consumes: list[str] | None = None,
    produces: list[str] | None = None,
    cadence: str | None = None,
    setup: str | None = None,
    minimum_cl: int | None = None,
    identity_cl: int | None = None,
    signature_cl: int | None = None,
    late: list[str] | None = None,
    complexity: str | None = None,
    factors: list[str] | None = None,
) -> dict:
    return {
        "theme_tags": themes or [],
        "role_tags": roles or [],
        "capability_families": capabilities or [],
        "combat_functions": functions or [],
        "resource_loop": {
            "consumes": consumes or [],
            "produces": produces or [],
            "cadence": cadence,
            "setup": setup,
        },
        "progression": {
            "minimum_cl": minimum_cl,
            "identity_online_cl": identity_cl,
            "signature_cl": signature_cl,
            "late_progression_tags": late or [],
        },
        "synergy_edges": [],
        "redundancy_groups": [],
        "tradeoffs": [],
        "complexity": {"band": complexity, "factors": factors or []},
    }


def _profile(profile_id: str, *, inherits: list[str] | None = None, facts: list[str] | None = None, **fragment: object) -> dict:
    return {
        "profile_id": profile_id,
        "inherits": inherits or [],
        "source_fact_ids": facts or [f"fact.{profile_id}"],
        **_fragment(**fragment),
    }


def _registry_input(*, chakra: bool = False, gu: bool = False, rebalance: bool = False) -> dict:
    vocabularies = {
        "theme_tags": ["guardianship", "fire", "patient_craft"],
        "role_tags": ["protector", "striker"],
        "capability_families": ["defense", "ally_protection", "damage", "control"],
        "combat_functions": ["defense", "support", "offense", "control"],
        "resource_families": ["heat"],
        "late_progression_tags": ["late_mastery"],
        "complexity_factors": ["conditional_timing"],
        "tradeoff_codes": ["setup_required"],
    }
    profiles = [
        _profile(
            "profile.base.protector",
            themes=["guardianship"],
            roles=["protector"],
            capabilities=["defense", "ally_protection"],
            functions=["defense", "support"],
            cadence="per_scene",
            setup="light",
            minimum_cl=1,
            identity_cl=1,
            signature_cl=5,
            late=["late_mastery"],
            complexity="moderate",
            factors=["conditional_timing"],
        ),
        _profile(
            "profile.sphere.fire",
            inherits=["profile.base.protector"],
            themes=["fire", "patient_craft"],
            capabilities=["damage", "control"] if rebalance else ["damage"],
            functions=["offense", "control"] if rebalance else ["offense"],
            consumes=["heat"],
            produces=["heat"],
        ),
    ]
    if chakra:
        for key, values in {
            "theme_tags": ["chakra_discipline"],
            "role_tags": ["chakra_guardian"],
            "capability_families": ["chakra_channeling"],
            "combat_functions": ["chakra_control"],
            "resource_families": ["chakra"],
        }.items():
            vocabularies[key].extend(values)
        profiles.append(
            _profile(
                "profile.system.chakra",
                facts=["source://fixture/chakra/profile"],
                themes=["chakra_discipline"],
                roles=["chakra_guardian"],
                capabilities=["chakra_channeling", "defense"],
                functions=["chakra_control", "defense"],
                consumes=["chakra"],
                produces=["chakra"],
                cadence="per_turn",
                setup="moderate",
                minimum_cl=1,
                identity_cl=1,
                signature_cl=7,
                late=["late_mastery"],
                complexity="complex",
                factors=["conditional_timing"],
            )
        )
    if gu:
        for key, values in {
            "theme_tags": ["gu_cultivation", "living_arsenal"],
            "role_tags": ["gu_artificer"],
            "capability_families": ["gu_breeding", "parasitic_adaptation"],
            "combat_functions": ["gu_command", "attrition"],
            "resource_families": ["gu_essence", "brood"],
        }.items():
            vocabularies[key].extend(values)
        profiles.append(
            _profile(
                "profile.system.gu",
                facts=["source://fixture/gu/profile"],
                themes=["gu_cultivation", "living_arsenal"],
                roles=["gu_artificer"],
                capabilities=["gu_breeding", "parasitic_adaptation"],
                functions=["gu_command", "attrition"],
                consumes=["gu_essence"],
                produces=["brood"],
                cadence="per_scene",
                setup="heavy",
                minimum_cl=1,
                identity_cl=3,
                signature_cl=7,
                late=["late_mastery"],
                complexity="complex",
                factors=["conditional_timing"],
            )
        )
    return {
        "schema": PROFILE_REGISTRY_SCHEMA,
        "version": 1,
        "adapter_version_sha256": _d("semantic-adapter-v1"),
        "vocabularies": vocabularies,
        "profiles": profiles,
    }


def _record(
    choice_id: str,
    choice_kind: str,
    profile_id: str,
    *,
    lifecycle: str = "ACTIVE",
    record_version: str = "v1",
    dependencies: list[str] | None = None,
) -> dict:
    return seal_typed_semantic_record(
        {
            "schema": TYPED_SEMANTIC_RECORD_SCHEMA,
            "choice_id": choice_id,
            "choice_kind": choice_kind,
            "lifecycle": lifecycle,
            "eligible_for_new_builds": lifecycle == "ACTIVE",
            "catalogue_schema": "fixture_catalogue",
            "catalogue_schema_version": 1,
            "choice_record_sha256": _d(f"record:{choice_id}:{record_version}"),
            "typed_authority_sha256": _d(f"authority:{choice_id}:{record_version}"),
            "source_rights_receipt_sha256": _d(f"rights:{choice_id}"),
            "profile_ids": [profile_id],
            "source_fact_ids": [f"fact.record.{choice_id}.{record_version}"],
            "semantics": _fragment(),
            "dependency_ids": dependencies or [],
        }
    )


def _baseline_records() -> list[dict]:
    return [
        _record("path.guardian", "path", "profile.base.protector"),
        _record("sphere.fire", "sphere", "profile.sphere.fire", dependencies=["path.guardian"]),
        _record("talent.fire_ward", "talent", "profile.sphere.fire", dependencies=["sphere.fire"]),
    ]


def _semantic_facts(records: list[dict], registry: dict) -> set[str]:
    facts = {
        fact
        for profile in registry["profiles"]
        for fact in [
            *profile["source_fact_ids"],
            *(fact for edge in profile["synergy_edges"] for fact in edge["source_fact_ids"]),
            *(fact for tradeoff in profile["tradeoffs"] for fact in tradeoff["source_fact_ids"]),
        ]
    }
    facts.update(
        fact
        for record in records
        for fact in [
            *record["source_fact_ids"],
            *(fact for edge in record["semantics"]["synergy_edges"] for fact in edge["source_fact_ids"]),
            *(fact for tradeoff in record["semantics"]["tradeoffs"] for fact in tradeoff["source_fact_ids"]),
        ]
    )
    return facts


def _authority_bundle(
    records: list[dict],
    registry: dict,
    *,
    fact_statuses: dict[str, str] | None = None,
    record_statuses: dict[str, str] | None = None,
) -> dict:
    fact_statuses = fact_statuses or {}
    record_statuses = record_statuses or {}
    return build_semantic_authority_bundle(
        {
            "schema": SEMANTIC_AUTHORITY_BUNDLE_SCHEMA,
            "version": 1,
            "semantic_profile_registry_sha256": registry["registry_sha256"],
            "source_facts": [
                {
                    "source_fact_id": fact_id,
                    "status": fact_statuses.get(fact_id, "VERIFIED"),
                    "source_projection_sha256": _d(f"source-projection:{fact_id}"),
                }
                for fact_id in sorted(_semantic_facts(records, registry))
            ],
            "record_authorities": [
                {
                    "schema": SEMANTIC_RECORD_AUTHORITY_SCHEMA,
                    "status": record_statuses.get(record["choice_id"], "VERIFIED"),
                    "choice_id": record["choice_id"],
                    "choice_record_sha256": record["choice_record_sha256"],
                    "typed_authority_sha256": record["typed_authority_sha256"],
                    "source_rights_receipt_sha256": record["source_rights_receipt_sha256"],
                    "record_projection_sha256": record["record_projection_sha256"],
                    "profile_ids": record["profile_ids"],
                    "source_fact_ids": record["source_fact_ids"],
                }
                for record in records
            ],
        }
    )


def _admit(records: list[dict], registry: dict, *, parent=None, authority_bundle: dict | None = None, expected_authority: str | None = None):
    authority = authority_bundle or _authority_bundle(records, registry)
    # Only tests replace the fixed Factory trust-manifest loader. Production
    # admission has no caller-supplied trust-digest parameter.
    with patch(
        "character_creation.creative_controller.semantic_admission.load_factory_semantic_authority_bundle_sha256",
        return_value=expected_authority or authority["authority_bundle_sha256"],
    ):
        return admit_typed_semantics(
            records,
            registry,
            authority,
            catalogue_schema_versions={"fixture_catalogue": 1},
            rules_authority_sha256=_d("rules-v1"),
            required_compiler_profile_sha256=_d("compiler-v1"),
            parent=parent,
        )


def test_admission_is_deterministic_detached_and_exactly_bound() -> None:
    registry = build_semantic_profile_registry(_registry_input())
    records = _baseline_records()
    first = _admit(records, registry)
    second = _admit(deepcopy(records), deepcopy(registry))
    assert first.to_dict() == second.to_dict()
    assert first.snapshot.catalogue_set_sha256 == first.semantics["sphere.fire"].value["catalogue_binding"]["catalogue_sha256"]
    assert first.snapshot.choice_semantics_set_sha256 == first.receipt["choice_semantics_set_sha256"]
    assert first.receipt["active_choice_ids"] == ["path.guardian", "sphere.fire", "talent.fire_ward"]
    detached = first.to_dict()
    detached["registry"]["profiles"][0]["source_fact_ids"].append("fact.mutation")
    assert first.to_dict() == second.to_dict()


def test_checked_in_factory_trust_manifest_exposes_the_current_active_bundle() -> None:
    assert load_factory_semantic_authority_bundle_sha256()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda data: data["profiles"][1]["inherits"].append("profile.missing"), "DCC_SEMANTIC_PROFILE_UNKNOWN"),
        (lambda data: data["profiles"][0]["inherits"].append("profile.sphere.fire"), "DCC_SEMANTIC_PROFILE_CYCLE"),
        (lambda data: data["profiles"][1]["theme_tags"].append("not_admitted"), "DCC_SEMANTIC_VOCABULARY_UNKNOWN"),
        (lambda data: data["profiles"][0].update(source_fact_ids=[]), "DCC_CHOICE_SEMANTICS_INCOMPLETE"),
        (lambda data: data["profiles"][0].update(description="forbidden prose inference"), "DCC_SCHEMA_UNKNOWN_FIELD"),
    ],
)
def test_registry_fails_closed_on_untyped_or_incomplete_semantics(mutation, expected_code: str) -> None:
    data = _registry_input()
    mutation(data)
    with pytest.raises(CreativeControllerError) as failure:
        build_semantic_profile_registry(data)
    assert failure.value.code == expected_code


def test_record_hash_unknown_profile_schema_and_scalar_conflict_fail_closed() -> None:
    registry = build_semantic_profile_registry(_registry_input())
    stale = _record("sphere.fire", "sphere", "profile.sphere.fire")
    stale["profile_ids"] = ["profile.base.protector"]
    with pytest.raises(CreativeControllerError) as failure:
        _admit([stale], registry)
    assert failure.value.code == "DCC_TYPED_SEMANTIC_RECORD_HASH_INVALID"

    unknown = _record("sphere.unknown", "sphere", "profile.unknown")
    with pytest.raises(CreativeControllerError) as failure:
        _admit([unknown], registry)
    assert failure.value.code == "DCC_SEMANTIC_PROFILE_UNKNOWN"

    wrong_schema = _record("sphere.fire", "sphere", "profile.sphere.fire")
    wrong_schema["catalogue_schema_version"] = 2
    wrong_schema = seal_typed_semantic_record({key: value for key, value in wrong_schema.items() if key != "record_projection_sha256"})
    with pytest.raises(CreativeControllerError) as failure:
        _admit([wrong_schema], registry)
    assert failure.value.code == "DCC_SEMANTIC_CATALOGUE_SCHEMA_STALE"

    conflict_data = _registry_input()
    conflict_data["profiles"][1]["resource_loop"]["cadence"] = "per_rest"
    with pytest.raises(CreativeControllerError) as failure:
        build_semantic_profile_registry(conflict_data)
    assert failure.value.code == "DCC_SEMANTIC_PROFILE_CONFLICT"


def test_add_retire_and_rebalance_create_children_without_mutating_parent() -> None:
    registry = build_semantic_profile_registry(_registry_input())
    records = _baseline_records()
    root = _admit(records, registry)
    root_bytes = root.to_dict()

    added_records = [*records, _record("sphere.ember", "sphere", "profile.sphere.fire", dependencies=["path.guardian"])]
    added = _admit(added_records, registry, parent=root.snapshot)
    assert "sphere.ember" in added.receipt["active_choice_ids"]
    assert added.snapshot.content_snapshot_sha256 != root.snapshot.content_snapshot_sha256
    assert root.to_dict() == root_bytes

    retired_records = [
        _record("talent.fire_ward", "talent", "profile.sphere.fire", lifecycle="RETIRED", dependencies=["sphere.fire"])
        if row["choice_id"] == "talent.fire_ward"
        else row
        for row in records
    ]
    retired = _admit(retired_records, registry, parent=root.snapshot)
    assert "talent.fire_ward" not in retired.receipt["active_choice_ids"]
    assert root.to_dict() == root_bytes

    rebalanced_registry = build_semantic_profile_registry(_registry_input(rebalance=True))
    rebalanced_records = [
        _record("sphere.fire", "sphere", "profile.sphere.fire", record_version="v2", dependencies=["path.guardian"])
        if row["choice_id"] == "sphere.fire"
        else row
        for row in records
    ]
    rebalanced = _admit(rebalanced_records, rebalanced_registry, parent=root.snapshot)
    assert rebalanced.semantics["sphere.fire"].semantics_sha256 != root.semantics["sphere.fire"].semantics_sha256
    assert rebalanced.snapshot.content_snapshot_sha256 != root.snapshot.content_snapshot_sha256
    assert root.to_dict() == root_bytes


def test_chakra_system_is_added_by_registry_and_record_data_only() -> None:
    ordinary_registry = build_semantic_profile_registry(_registry_input())
    ordinary = _admit(_baseline_records(), ordinary_registry)
    chakra_registry = build_semantic_profile_registry(_registry_input(chakra=True))
    chakra_records = [
        *_baseline_records(),
        _record("path.chakra_adept", "path", "profile.system.chakra"),
        _record("sphere.chakra_flow", "sphere", "profile.system.chakra", dependencies=["path.chakra_adept"]),
        _record("talent.chakra_guard", "talent", "profile.system.chakra", dependencies=["sphere.chakra_flow"]),
    ]
    chakra = _admit(chakra_records, chakra_registry, parent=ordinary.snapshot)
    assert {"path.chakra_adept", "sphere.chakra_flow", "talent.chakra_guard"} <= set(chakra.semantics)
    chakra_semantics = chakra.semantics["talent.chakra_guard"].value
    assert chakra_semantics["resource_loop"] == {
        "consumes": ["chakra"],
        "produces": ["chakra"],
        "cadence": "per_turn",
        "setup": "moderate",
    }
    assert "chakra_guardian" in chakra_semantics["role_tags"]
    assert ordinary.to_dict()["snapshot"] == ordinary.snapshot.to_dict()

    menu = build_creative_predicate_menu(chakra.vocabulary_authority, maximum_options=96)
    options = menu.public_menu["options"]
    assert len(options) <= 96
    labels = {(row["kind"], row["label"]) for row in options}
    assert ("role_tag", "chakra guardian") in labels
    assert ("capability_family", "chakra channeling") in labels


def test_gu_system_uses_the_same_generic_admission_contract() -> None:
    ordinary_registry = build_semantic_profile_registry(_registry_input())
    ordinary = _admit(_baseline_records(), ordinary_registry)
    gu_registry = build_semantic_profile_registry(_registry_input(gu=True))
    gu_records = [
        *_baseline_records(),
        _record("path.gu_master", "path", "profile.system.gu"),
        _record("sphere.gu_breeding", "sphere", "profile.system.gu", dependencies=["path.gu_master"]),
        _record("talent.gu_symbiosis", "talent", "profile.system.gu", dependencies=["sphere.gu_breeding"]),
    ]
    gu = _admit(gu_records, gu_registry, parent=ordinary.snapshot)
    semantics = gu.semantics["talent.gu_symbiosis"].value
    assert semantics["resource_loop"] == {
        "consumes": ["gu_essence"],
        "produces": ["brood"],
        "cadence": "per_scene",
        "setup": "heavy",
    }
    assert semantics["role_tags"] == ["gu_artificer"]
    assert semantics["capability_families"] == ["gu_breeding", "parasitic_adaptation"]
    assert gu.receipt["registry_sha256"] != ordinary.receipt["registry_sha256"]

    menu = build_creative_predicate_menu(gu.vocabulary_authority, maximum_options=96)
    labels = {(row["kind"], row["label"]) for row in menu.public_menu["options"]}
    assert ("role_tag", "gu artificer") in labels
    assert ("capability_family", "gu breeding") in labels


def test_authority_trust_anchor_rejects_stale_registry_records_and_unverified_facts() -> None:
    registry = build_semantic_profile_registry(_registry_input())
    records = _baseline_records()
    authority = _authority_bundle(records, registry)

    with pytest.raises(CreativeControllerError) as failure:
        _admit(records, registry, authority_bundle=authority, expected_authority=_d("not-the-frozen-authority"))
    assert failure.value.code == "DCC_SEMANTIC_AUTHORITY_TRUST_MISMATCH"

    rebalanced_registry = build_semantic_profile_registry(_registry_input(rebalance=True))
    with pytest.raises(CreativeControllerError) as failure:
        _admit(records, rebalanced_registry, authority_bundle=authority)
    assert failure.value.code == "DCC_SEMANTIC_PROFILE_AUTHORITY_STALE"

    changed = [
        *records[:-1],
        _record("talent.fire_ward", "talent", "profile.sphere.fire", record_version="forged", dependencies=["sphere.fire"]),
    ]
    with pytest.raises(CreativeControllerError) as failure:
        _admit(changed, registry, authority_bundle=authority)
    assert failure.value.code == "DCC_SEMANTIC_RECORD_AUTHORITY_STALE"

    profile_fact = registry["profiles"][0]["source_fact_ids"][0]
    draft_authority = _authority_bundle(records, registry, fact_statuses={profile_fact: "DRAFT"})
    with pytest.raises(CreativeControllerError) as failure:
        _admit(records, registry, authority_bundle=draft_authority)
    assert failure.value.code == "DCC_SEMANTIC_SOURCE_FACT_UNVERIFIED"


def test_record_collections_are_canonical_and_order_independent() -> None:
    registry = build_semantic_profile_registry(_registry_input())
    raw = {
        "schema": TYPED_SEMANTIC_RECORD_SCHEMA,
        "choice_id": "talent.combined_guard",
        "choice_kind": "talent",
        "lifecycle": "ACTIVE",
        "eligible_for_new_builds": True,
        "catalogue_schema": "fixture_catalogue",
        "catalogue_schema_version": 1,
        "choice_record_sha256": _d("record:talent.combined_guard:v1"),
        "typed_authority_sha256": _d("authority:talent.combined_guard:v1"),
        "source_rights_receipt_sha256": _d("rights:talent.combined_guard"),
        "profile_ids": ["profile.sphere.fire", "profile.base.protector"],
        "source_fact_ids": ["fact.record.combo.z", "fact.record.combo.a"],
        "semantics": _fragment(
            themes=["patient_craft", "fire"],
            roles=["striker", "protector"],
            capabilities=["control", "damage"],
            functions=["control", "offense"],
        ),
        "dependency_ids": ["sphere.fire", "path.guardian"],
    }
    raw["semantics"]["synergy_edges"] = [
        {"target_choice_id": "sphere.fire", "relation": "shared_resource", "source_fact_ids": ["fact.edge.z"]},
        {"target_choice_id": "path.guardian", "relation": "role_reinforcement", "source_fact_ids": ["fact.edge.a"]},
    ]
    raw["semantics"]["tradeoffs"] = [
        {"code": "setup_required", "severity": "light", "source_fact_ids": ["fact.tradeoff.z", "fact.tradeoff.a"]}
    ]
    permuted = deepcopy(raw)
    for key in ("profile_ids", "source_fact_ids", "dependency_ids"):
        permuted[key].reverse()
    for key in ("theme_tags", "role_tags", "capability_families", "combat_functions"):
        permuted["semantics"][key].reverse()
    permuted["semantics"]["synergy_edges"].reverse()
    permuted["semantics"]["tradeoffs"][0]["source_fact_ids"].reverse()

    sealed = seal_typed_semantic_record(raw)
    resealed = seal_typed_semantic_record(permuted)
    assert sealed == resealed

    baseline = _baseline_records()
    first = _admit([*baseline, sealed], registry)
    second = _admit([*baseline, resealed], registry)
    assert first.semantics["talent.combined_guard"].to_dict() == second.semantics["talent.combined_guard"].to_dict()
    assert first.snapshot.to_dict() == second.snapshot.to_dict()

    noncanonical = deepcopy(sealed)
    noncanonical["profile_ids"].reverse()
    unsigned = {key: value for key, value in noncanonical.items() if key != "record_projection_sha256"}
    noncanonical["record_projection_sha256"] = sha256_json(unsigned)
    with pytest.raises(CreativeControllerError) as failure:
        validate_typed_semantic_record(noncanonical)
    assert failure.value.code == "DCC_TYPED_SEMANTIC_RECORD_NONCANONICAL"
