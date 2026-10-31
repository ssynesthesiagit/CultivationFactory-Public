"""Focused deterministic tests for the Stage A shadow controller.

The fixture below is deliberately sanitized: it contains typed commitments
and a one-sentence creative concept only.  It contains no private request
payload, provider response, or rules text.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pytest

from app.core import canonical_json, sha256_bytes, sha256_json
from character_creation.creative_controller import (
    ChoiceSemantics,
    ContentRecordCommitment,
    CreativeControllerError,
    FactoryContentSnapshot,
    IdentifierRegistry,
    LegalPlan,
    ShadowInputs,
    TypedChoiceOption,
    TypedChoiceSlot,
    accept_option,
    affected_dependency_closure,
    aggregate_whole_plan_semantics,
    build_choice_semantics,
    build_content_change_set,
    build_content_snapshot,
    build_creative_intent,
    build_creative_predicate_menu,
    build_diversity_seeds,
    build_vocabulary_authority,
    build_event,
    build_factory_final_validator,
    build_factory_validator_authority_binding,
    build_manifest,
    build_migration_receipt,
    build_replay_receipt,
    categorical_distance,
    continue_manifest,
    derive_controller_id,
    derive_event_id,
    derive_intent_id,
    derive_manifest_id,
    derive_option_id,
    derive_continuation_id,
    domain_digest,
    event_contains_complete_request_bytes,
    evaluate_controlled_preferences,
    migrate_character_revision,
    rank_plans,
    resolve_creative_predicate_selection,
    run_shadow_controller,
    select_diverse_plans,
    signature_for_plan,
    validate_choice_semantics,
    validate_manifest,
    validate_semantics_set,
    verify_event_chain,
    verify_semantics_binding,
)
from character_creation.creative_controller.legal_plan_compiler import (
    SEARCH_AUTO,
    SEARCH_EXHAUSTIVE,
    SEARCH_SEEDED_ROLLOUT,
    compile_legal_plans,
    validate_legal_plan,
)


_VOCABULARY_AUTHORITY = build_vocabulary_authority({
    "theme_tags": ["quiet_craft", "guardianship", "salvage_craft", "resource_reuse", "earned_mastery", "quiet_mastery", "battlefield_control"],
    "role_tags": ["protector", "controller", "supporter", "scout", "striker"],
    "capability_families": ["defense", "ally_protection", "mobility", "reliability", "resource_reuse", "crafting", "damage", "burst", "area_control", "condition_application", "recovery", "action_economy", "durability"],
    "combat_functions": ["defense", "support", "mobility", "utility", "offense", "control", "recovery"],
    "resource_families": ["salvage"],
    "late_progression_tags": ["late_mastery"],
    "complexity_factors": ["conditional_timing"],
    "tradeoff_codes": ["setup_required", "lower_burst"],
})


def _d(label: str) -> str:
    return sha256_json({"fixture_label": label})


def _accept_final_validator(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "accepted": True,
        "validator": "sanitized-factory-final-validator-fixture",
        "validated_plan_sha256": sha256_json(payload),
    }


def _semantics(
    choice_id: str,
    choice_kind: str,
    *,
    role: str,
    capabilities: list[str],
    functions: list[str],
    themes: list[str] | None = None,
    consumes: list[str] | None = None,
    produces: list[str] | None = None,
    identity_cl: int = 1,
    signature_cl: int = 5,
    synergy_edges: list[dict[str, Any]] | None = None,
    tradeoffs: list[dict[str, Any]] | None = None,
    complexity: str = "moderate",
) -> ChoiceSemantics:
    fact = f"fixture.fact.{choice_id}"
    unsigned = {
        "schema": "TianxiaFoundry.ChoiceSemantics.v1",
        "semantics_version": 1,
        "choice_id": choice_id,
        "choice_kind": choice_kind,
        "vocabulary_authority_sha256": _VOCABULARY_AUTHORITY["authority_sha256"],
        "catalogue_binding": {
            "catalogue_sha256": _d("catalogue"),
            "choice_record_sha256": _d(f"record:{choice_id}"),
            "typed_authority_sha256": _d(f"typed:{choice_id}"),
        },
        "authority": {
            "status": "VERIFIED",
            "derivation": "EXPLICIT_CATALOGUE_METADATA",
            "adapter_version_sha256": None,
            "source_fact_ids": [fact],
            "source_projection_sha256": _d(f"projection:{choice_id}"),
        },
        "theme_tags": themes or ["quiet_craft"],
        "role_tags": [role],
        "capability_families": capabilities,
        "combat_functions": functions,
        "resource_loop": {
            "consumes": consumes or [],
            "produces": produces or [],
            "cadence": "per_scene",
            "setup": "moderate",
        },
        "progression": {
            "minimum_cl": 1,
            "identity_online_cl": identity_cl,
            "signature_cl": signature_cl,
            "late_progression_tags": ["late_mastery"],
        },
        "synergy_edges": synergy_edges or [],
        "redundancy_groups": [],
        "tradeoffs": tradeoffs or [],
        "complexity": {
            "band": complexity,
            "factors": ["conditional_timing"],
        },
    }
    return build_choice_semantics(unsigned)


def _fixture() -> dict[str, Any]:
    semantic_rows = {
        "path.bastion": _semantics(
            "path.bastion", "path", role="protector", capabilities=["defense", "ally_protection"], functions=["defense", "support"], themes=["quiet_craft", "guardianship"], synergy_edges=[{"target_choice_id": "talent.guard", "relation": "role_reinforcement", "source_fact_ids": ["fixture.fact.path.bastion.synergy"]}],
        ),
        "path.runner": _semantics(
            "path.runner", "path", role="scout", capabilities=["mobility", "reliability"], functions=["mobility", "utility"], themes=["quiet_mastery"], complexity="simple",
        ),
        "method.salvage": _semantics(
            "method.salvage", "method", role="supporter", capabilities=["resource_reuse", "crafting"], functions=["support", "utility"], themes=["salvage_craft", "resource_reuse"], consumes=["salvage"], produces=["salvage"], synergy_edges=[{"target_choice_id": "talent.scavenge", "relation": "shared_resource", "source_fact_ids": ["fixture.fact.method.salvage.synergy"]}], tradeoffs=[{"code": "setup_required", "severity": "moderate", "source_fact_ids": ["fixture.fact.method.salvage.tradeoff"]}],
        ),
        "method.charge": _semantics(
            "method.charge", "method", role="striker", capabilities=["damage", "burst"], functions=["offense"], themes=["earned_mastery"], tradeoffs=[{"code": "lower_burst", "severity": "light", "source_fact_ids": ["fixture.fact.method.charge.tradeoff"]}], complexity="simple",
        ),
        "talent.guard": _semantics(
            "talent.guard", "talent", role="protector", capabilities=["ally_protection", "defense"], functions=["defense", "support"], themes=["guardianship"], identity_cl=2, synergy_edges=[{"target_choice_id": "path.bastion", "relation": "role_reinforcement", "source_fact_ids": ["fixture.fact.talent.guard.synergy"]}],
        ),
        "talent.control": _semantics(
            "talent.control", "talent", role="controller", capabilities=["area_control", "condition_application"], functions=["control"], themes=["battlefield_control"], identity_cl=3, signature_cl=6, tradeoffs=[{"code": "setup_required", "severity": "light", "source_fact_ids": ["fixture.fact.talent.control.tradeoff"]}],
        ),
        "talent.scavenge": _semantics(
            "talent.scavenge", "talent", role="supporter", capabilities=["resource_reuse", "recovery"], functions=["support", "recovery"], themes=["salvage_craft"], consumes=["salvage"], produces=["salvage"], identity_cl=2,
        ),
        "talent.focus": _semantics(
            "talent.focus", "talent", role="controller", capabilities=["reliability", "action_economy"], functions=["utility", "control"], themes=["quiet_mastery"], complexity="simple",
        ),
        "talent.burst": _semantics(
            "talent.burst", "talent", role="striker", capabilities=["damage", "burst"], functions=["offense"], themes=["earned_mastery"], identity_cl=2, signature_cl=4,
        ),
        "talent.ward": _semantics(
            "talent.ward", "talent", role="protector", capabilities=["defense", "durability"], functions=["defense"], themes=["guardianship"], identity_cl=2,
        ),
    }
    schema_versions = {"methods": 1, "paths": 1, "talents": 1}
    catalogue_commitment = sha256_json({
        "catalogue_schema_versions": schema_versions,
        "active_record_commitments": [
            {
                "choice_id": choice_id,
                "choice_kind": semantic_rows[choice_id].value["choice_kind"],
                "choice_record_sha256": _d(f"record:{choice_id}:v1"),
                "typed_authority_sha256": _d(f"typed:{choice_id}:v1"),
                "source_rights_receipt_sha256": _d(f"rights:{choice_id}:v1"),
            }
            for choice_id in sorted(semantic_rows)
        ],
    })
    rebound_semantics: dict[str, ChoiceSemantics] = {}
    for choice_id, semantic in semantic_rows.items():
        unsigned = semantic.to_dict()
        unsigned.pop("semantics_sha256")
        unsigned["catalogue_binding"] = {
            "catalogue_sha256": catalogue_commitment,
            "choice_record_sha256": _d(f"record:{choice_id}:v1"),
            "typed_authority_sha256": _d(f"typed:{choice_id}:v1"),
        }
        rebound_semantics[choice_id] = build_choice_semantics(unsigned)
    semantic_rows = rebound_semantics
    edges = {
        "talent.guard": ["path.bastion"],
        "talent.control": ["path.bastion"],
        "talent.scavenge": ["method.salvage"],
        "talent.burst": ["method.charge"],
        "talent.ward": ["path.runner"],
    }
    records = tuple(
        ContentRecordCommitment(
            choice_id=choice_id,
            choice_kind=sem.value["choice_kind"],
            lifecycle="ACTIVE",
            eligible_for_new_builds=True,
            choice_record_sha256=_d(f"record:{choice_id}:v1"),
            typed_authority_sha256=_d(f"typed:{choice_id}:v1"),
            choice_semantics_sha256=sem.semantics_sha256,
            source_rights_receipt_sha256=_d(f"rights:{choice_id}:v1"),
        )
        for choice_id, sem in semantic_rows.items()
    )
    snapshot = build_content_snapshot(
        records,
        catalogue_schema_versions=schema_versions,
        rules_authority_sha256=_d("rules:v1"),
        required_compiler_profile_sha256=_d("compiler:v1"),
        dependency_edges=edges,
        vocabulary_authority_sha256=_VOCABULARY_AUTHORITY["authority_sha256"],
    )
    request_bytes = b"sanitized-kai-request-authority"
    request_sha256 = sha256_bytes(request_bytes)
    intent = build_creative_intent({
        "schema": "TianxiaFoundry.CreativeIntent.v1",
        "intent_revision": 1,
        "binding": {
            "project_id": "project.kai.shadow",
            "project_revision": 12,
            "request_sha256": request_sha256,
            "content_snapshot_sha256": snapshot.content_snapshot_sha256,
            "content_lock_hash": _d("content-lock"),
            "character_state_sha256": _d("character-state"),
        },
        "source": {
            "kind": "provider",
            "provider_id": "local",
            "provider_response_sha256": _d("sanitized-concept-source"),
        },
        "identity": {
            "suggested_name": "Kai",
            "suggested_title": "Quiet Forge",
            "one_sentence_concept": "A patient protector who turns salvage into controlled battlefield pressure.",
        },
        "creative": {
            "theme_terms": ["quiet_craft", "salvage_craft", "guardianship"],
            "narrative_cues": ["visible improvisation", "earned mastery"],
            "combat_fantasy": "Protect allies while converting found materials into decisive tools.",
            "desired_roles": ["protector", "controller"],
            "priority_order": ["defense", "control", "crafting"],
            "desired_synergies": ["resource_reuse", "ally_protection"],
            "acceptable_tradeoffs": ["lower_burst", "setup_required"],
            "avoidances": ["high_bookkeeping"],
            "complexity_preference": "moderate",
            "visual_cues": ["worn metal", "restrained motion"],
        },
        "controlled_preferences": {
            "must_include": [{"kind": "role_tag", "value": "protector"}],
            "must_exclude": [],
            "soft_prefer": [{"kind": "capability_family", "value": "resource_reuse"}],
            "soft_avoid": [],
        },
        "activation": {
            "mode": "AI_DIRECTOR",
            "status": "ACTIVE",
            "authorized_by": "frozen_run_policy",
            "active_fields": ["identity", "creative", "controlled_preferences"],
        },
    })
    predicate_menu = build_creative_predicate_menu(
        _VOCABULARY_AUTHORITY,
        hard_authorized_predicates=[{"kind": "role_tag", "value": "protector"}],
    )
    predicate_option = {
        (predicate["kind"], predicate["value"]): option_id
        for option_id, predicate in predicate_menu.option_to_predicate.items()
    }
    predicate_selection = {
        "schema": "TianxiaFoundry.CreativePredicateSelection.v1",
        "must_include": [predicate_option[("role_tag", "protector")]],
        "must_exclude": [],
        "soft_prefer": [predicate_option[("capability_family", "resource_reuse")]],
        "soft_avoid": [],
    }
    slots = (
        TypedChoiceSlot("route", (
            TypedChoiceOption("path.bastion", "path", 1),
            TypedChoiceOption("path.runner", "path", 1),
        ), choice_kind="path", acquisition_cl=1),
        TypedChoiceSlot("method", (
            TypedChoiceOption("method.salvage", "method", 1),
            TypedChoiceOption("method.charge", "method", 1, incompatibilities=("path.bastion",)),
        ), choice_kind="method", acquisition_cl=1),
        TypedChoiceSlot("talent", (
            TypedChoiceOption("talent.guard", "talent", 2, prerequisites=("path.bastion",)),
            TypedChoiceOption("talent.control", "talent", 3, prerequisites=("path.bastion",)),
            TypedChoiceOption("talent.scavenge", "talent", 2, prerequisites=("method.salvage",)),
            TypedChoiceOption("talent.focus", "talent", 2),
            TypedChoiceOption("talent.burst", "talent", 2, prerequisites=("method.charge",)),
            TypedChoiceOption("talent.ward", "talent", 2, prerequisites=("path.runner",)),
        ), choice_kind="talent", acquisition_cl=2),
    )
    from path_method_authority import CANONICAL_PATH_IDS
    from tests.test_rec1_p1ar2_target_cl_authority import _authority, _plan_for_target

    factory_project, _factory_envelope, factory_run = _authority(15)
    route_projection = {
        "path.bastion": CANONICAL_PATH_IDS[0],
        "path.runner": CANONICAL_PATH_IDS[1],
    }

    def project_controller_plan(payload: dict[str, Any]) -> dict[str, Any]:
        selected = {row["choice_id"] for row in payload["choices"]}
        selected_routes = sorted(route_projection[choice_id] for choice_id in selected if choice_id in route_projection)
        plan = _plan_for_target(15)
        plan["delegated_choice_selections"]["by_slot"] = {
            "path_choice": selected_routes,
            "method_choice": ["METHOD-ALL"],
        }
        return plan

    factory_validator = build_factory_final_validator(
        run=factory_run,
        project=factory_project,
        plan_projector=project_controller_plan,
        projector_version_sha256=_d("sanitized-kai-cl15-projector-v1"),
        response_sha256="SANITIZED-KAI-CL15-SHADOW",
        provider_required_planning_slot_ids=[],
        authority_binding=build_factory_validator_authority_binding(
            canonical_project_sha256=_d("canonical-project"),
            request_sha256=request_sha256,
            content_lock_hash=intent["binding"]["content_lock_hash"],
            typed_choice_snapshot_sha256=_d("typed-choice-snapshot"),
            delegated_choice_envelope_sha256=_d("delegated-envelope"),
            target_cl=15,
            projector_version_sha256=_d("sanitized-kai-cl15-projector-v1"),
            run=factory_run,
            project=factory_project,
            response_sha256="SANITIZED-KAI-CL15-SHADOW",
            provider_required_planning_slot_ids=[],
        ),
    )
    inputs = ShadowInputs(
        run_id="cg1.run.kai.shadow",
        project_id="project.kai.shadow",
        project_revision=12,
        request_sha256=request_sha256,
        request_resolver_id="dcc.request." + _d("request-resolver")[:24],
        request_resolver_binding_sha256=_d("request-resolver-binding"),
        content_lock_hash=intent["binding"]["content_lock_hash"],
        canonical_project_sha256=_d("canonical-project"),
        typed_choice_snapshot_sha256=_d("typed-choice-snapshot"),
        delegated_choice_envelope_sha256=_d("delegated-envelope"),
        character_state_sha256=intent["binding"]["character_state_sha256"],
        operator_contract_sha256=_d("operator-contract"),
        legal_compiler_version_sha256=_d("legal-compiler-v1"),
        content_snapshot=snapshot,
        intent=intent,
        slots=slots,
        semantics=semantic_rows,
        predicate_menu=predicate_menu,
        predicate_selection=predicate_selection,
        target_cl=15,
        controller_version_sha256=_d("controller-v1"),
        selected_ai_identity_sha256=_d("selected-ai-local"),
        final_validator=factory_validator,
        vocabulary_authority=_VOCABULARY_AUTHORITY,
    )
    return {"semantics": semantic_rows, "records": records, "snapshot": snapshot, "intent": intent, "slots": slots, "inputs": inputs, "request_bytes": request_bytes, "edges": edges, "predicate_menu": predicate_menu, "predicate_selection": predicate_selection}


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _fixture()


def _event_binding() -> dict[str, Any]:
    return {
        "project_revision": 12,
        "content_snapshot_sha256": _d("event-content"),
        "request_sha256": sha256_bytes(b"event-request"),
        "request_resolver_id": "dcc.request." + _d("event-resolver")[:24],
        "request_resolver_binding_sha256": _d("event-resolver-binding"),
        "content_lock_hash": _d("event-lock"),
        "selected_ai_identity_sha256": _d("event-ai"),
    }


def test_known_vector_ids_and_event_chaining(fixture: dict[str, Any]) -> None:
    payload = {"z": "é", "a": [3, 1]}

    def independent_h(domain: str, body: Any) -> str:
        raw = json.dumps({"domain": domain, "payload": body}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    expected_full = independent_h("known.vector.v1", payload)
    assert domain_digest("known.vector.v1", payload) == expected_full
    unsigned_intent = {"schema": "seed", "binding": {"x": 1}}
    seed = independent_h("dcc.intent.seed.v1", unsigned_intent)
    intent_id_full = independent_h("dcc.intent.id.v1", {"intent_seed_sha256": seed})
    assert derive_intent_id(unsigned_intent) == "dcc.intent." + intent_id_full[:24]
    request_hash = _d("known-request")
    controller = derive_controller_id("run.known", request_hash, _d("controller-version"), _d("known-ai"))
    controller_full = independent_h("dcc.controller.id.v1", {"run_id": "run.known", "request_sha256": request_hash, "controller_version_sha256": _d("controller-version"), "selected_ai_identity_sha256": _d("known-ai")})
    assert controller == "dcc.controller." + controller_full[:24]
    context = _d("manifest-context")
    assert derive_manifest_id(context, [_d("plan-a"), _d("plan-b")]) == "dcc.manifest." + independent_h("dcc.manifest.id.v1", {"manifest_context_sha256": context, "ordered_legal_plan_sha256s": [_d("plan-a"), _d("plan-b")]} )[:24]
    assert derive_option_id(context, _d("plan-a"), "WHOLE_BUILD", "complete_cl15_build").startswith("dcc.opt.")
    assert derive_continuation_id(context, 1, [_d("plan-a")], _d("ranked-view")).startswith("dcc.more.")

    binding = _event_binding()
    state_one, state_two = _d("state-one"), _d("state-two")
    subject_one, subject_two = _d("intent-subject"), _d("manifest-subject")
    first = build_event(controller_id=controller, ordinal=1, event_type="INTENT_ACTIVATED", run_id="run.known", project_id="project.known", previous_event_sha256=None, subject_sha256=subject_one, binding=binding, state_sha256_before=state_one, state_sha256_after=state_two)
    second = build_event(controller_id=controller, ordinal=2, event_type="MANIFEST_PUBLISHED", run_id="run.known", project_id="project.known", previous_event_sha256=first.event_sha256, subject_sha256=subject_two, binding=binding, state_sha256_before=state_two, state_sha256_after=_d("state-three"))
    event_id_full = independent_h("dcc.event.id.v1", {"controller_id": controller, "ordinal": 1, "previous_event_sha256": None, "event_type": "INTENT_ACTIVATED", "subject_sha256": subject_one})
    assert first.event_id == "dcc.event." + event_id_full[:24]
    chain = verify_event_chain((first, second))
    assert chain["event_count"] == 2 and chain["event_head_sha256"] == second.event_sha256
    replay = run_shadow_controller(fixture["inputs"])
    replay_binding = replay.artifact.manifest["binding"]
    receipt = build_replay_receipt(replay.events, content_snapshot_sha256=replay_binding["content_snapshot_sha256"], request_sha256=replay_binding["request_sha256"], request_resolver_id=replay_binding["request_resolver_id"], request_resolver_binding_sha256=replay_binding["request_resolver_binding_sha256"], selected_ai_identity_sha256=replay_binding["selected_ai_identity_sha256"], input_binding_sha256=sha256_json(replay_binding), expected_state_sha256=replay.events[-1].value["state_sha256_after"], expected_manifest_sha256=replay.artifact.manifest_sha256, request_bytes=fixture["request_bytes"], resolved_inputs=fixture["inputs"], expected_manifest_bytes=replay.manifest_json.encode("utf-8"))
    assert receipt.value["byte_identical"] is True
    assert all(not event_contains_complete_request_bytes(event.to_dict()) for event in (first, second))


def test_strict_schema_and_truncation_collision_fail_closed(fixture: dict[str, Any]) -> None:
    semantics = fixture["semantics"]["path.bastion"].to_dict()
    semantics["unknown_field"] = True
    with pytest.raises(CreativeControllerError) as error:
        validate_choice_semantics(semantics)
    assert error.value.code == "DCC_SCHEMA_UNKNOWN_FIELD"

    registry = IdentifierRegistry()
    short = "dcc.opt." + "a" * 24
    registry.register("dcc.opt.", "a" * 64, shortened_id=short)
    with pytest.raises(CreativeControllerError) as collision:
        registry.register("dcc.opt.", "b" * 64, shortened_id=short)
    assert collision.value.code == "DCC_ID_TRUNCATION_COLLISION"


def test_bounded_legal_plans_enforce_constraints_and_final_validator(fixture: dict[str, Any]) -> None:
    with pytest.raises(CreativeControllerError) as missing_validator:
        compile_legal_plans(fixture["slots"], target_cl=15)
    assert missing_validator.value.code == "DCC_FINAL_VALIDATOR_REQUIRED"

    result = compile_legal_plans(fixture["slots"], target_cl=15, final_validator=_accept_final_validator)
    assert len(result.plans) == 10
    for plan in result.plans:
        ids = plan.choice_ids
        assert len(ids) == len(set(ids))
        assert not ({"path.bastion", "method.charge"} <= set(ids))
        if "talent.guard" in ids or "talent.control" in ids:
            assert "path.bastion" in ids
        if "talent.burst" in ids:
            assert "method.charge" in ids
        assert all(row["acquisition_cl"] <= 3 for row in plan.choices)
        assert plan.proof["checks"]["final_factory_validator"] is True

    impossible_cardinality = (TypedChoiceSlot("two", (TypedChoiceOption("talent.a"), TypedChoiceOption("talent.b")), min_choices=2, max_choices=2, cardinality_group="talents", cardinality_limit=1),)
    assert compile_legal_plans(impossible_cardinality, target_cl=1, final_validator=_accept_final_validator).plans == ()

    rejected_calls: list[str] = []

    def reject_control(payload: dict[str, Any]) -> bool:
        rejected_calls.append(sha256_json(payload))
        return "talent.control" not in {row["choice_id"] for row in payload["choices"]}

    filtered = compile_legal_plans(fixture["slots"], target_cl=15, final_validator=reject_control)
    assert rejected_calls
    assert filtered.validator_rejections
    assert all("talent.control" not in plan.choice_ids for plan in filtered.plans)


def test_cl15_adapter_uses_existing_factory_final_validators() -> None:
    from path_method_authority import CANONICAL_PATH_IDS
    from tests.test_rec1_p1ar2_target_cl_authority import _authority, _plan_for_target

    project, _envelope, run = _authority(15)

    def projector(payload: dict[str, Any]) -> dict[str, Any]:
        by_slot: dict[str, list[str]] = {}
        for row in payload["choices"]:
            by_slot.setdefault(row["slot_id"], []).append(row["choice_id"])
        plan = _plan_for_target(15)
        plan["delegated_choice_selections"]["by_slot"] = by_slot
        return plan

    adapter = build_factory_final_validator(
        run=run,
        project=project,
        plan_projector=projector,
        projector_version_sha256=_d("cl15-controller-to-factory-projector-v1"),
        response_sha256="SANITIZED-DCC-CL15",
        provider_required_planning_slot_ids=[],
    )
    slots = (
        TypedChoiceSlot(
            "path_choice",
            tuple(TypedChoiceOption(path_id, "path", 1) for path_id in CANONICAL_PATH_IDS),
            choice_kind="path",
            min_choices=len(CANONICAL_PATH_IDS),
            max_choices=len(CANONICAL_PATH_IDS),
        ),
        TypedChoiceSlot("method_choice", (TypedChoiceOption("METHOD-ALL", "method", 1),), choice_kind="method"),
    )
    result = compile_legal_plans(slots, target_cl=15, final_validator=adapter, frontier_limit=1)
    assert len(result.plans) == 1
    assert result.validator_rejections == ()
    assert result.plans[0].proof["checks"]["final_factory_validator"] is True
    assert adapter(result.plans[0].plan_payload)["factory_target_cl"] == 15

    # The slots above admit exactly one assignment, so they prove the adapter
    # but exercise no search.  Give the compiler a real space, including a
    # choice the live Factory validator must reject, and confirm the gate is
    # doing the work rather than the fixture.
    searchable = (
        TypedChoiceSlot(
            "path_choice",
            tuple(TypedChoiceOption(path_id, "path", 1) for path_id in CANONICAL_PATH_IDS)
            + (TypedChoiceOption("tianxia.path.not_admitted", "path", 1),),
            choice_kind="path",
        ),
        TypedChoiceSlot("method_choice", (TypedChoiceOption("METHOD-ALL", "method", 1),), choice_kind="method"),
    )
    searched = compile_legal_plans(searchable, target_cl=15, final_validator=adapter, frontier_limit=12, search_strategy=SEARCH_EXHAUSTIVE)
    assert searched.explored_assignments == len(CANONICAL_PATH_IDS) + 1
    assert len(searched.validator_rejections) == 1
    published = sorted(choice for plan in searched.plans for choice in plan.choice_ids if choice.startswith("tianxia.path."))
    assert published == sorted(CANONICAL_PATH_IDS)
    for plan in searched.plans:
        assert plan.proof["final_validator_receipt"]["accepted"] is True


def test_baseline_locks_and_acquisition_history_are_compiler_authority() -> None:
    slots = (
        TypedChoiceSlot(
            "route",
            (
                TypedChoiceOption("path.locked", "path", 1),
                TypedChoiceOption("path.other", "path", 1),
            ),
            choice_kind="path",
        ),
        TypedChoiceSlot(
            "talent",
            (TypedChoiceOption("talent.followup", "talent", 5, prerequisites=("foundation.accepted",)),),
            choice_kind="talent",
            acquisition_cl=5,
        ),
    )
    result = compile_legal_plans(
        slots,
        target_cl=15,
        final_validator=_accept_final_validator,
        accepted_choices=("foundation.accepted",),
        acquisition_history={"foundation.accepted": 2},
        owner_locks={"route": ("path.locked",)},
    )
    assert len(result.plans) == 1
    assert result.plans[0].choice_ids == ("path.locked", "talent.followup")
    binding = result.plans[0].proof["compiler_binding"]
    assert binding["slot_authority_sha256"]
    with pytest.raises(CreativeControllerError) as invalid_history:
        compile_legal_plans(
            slots,
            target_cl=15,
            final_validator=_accept_final_validator,
            accepted_choices=("foundation.accepted",),
            acquisition_history={"unknown": 2},
        )
    assert invalid_history.value.code == "DCC_ACQUISITION_HISTORY_INVALID"


def test_frontier_budget_is_enforced_before_combinations_are_enqueued() -> None:
    slot = TypedChoiceSlot(
        "many",
        tuple(TypedChoiceOption(f"talent.{index}") for index in range(12)),
        min_choices=6,
        max_choices=6,
    )
    with pytest.raises(CreativeControllerError) as exhausted:
        compile_legal_plans(
            (slot,),
            target_cl=15,
            final_validator=_accept_final_validator,
            frontier_limit=1,
            search_state_limit=2,
            search_strategy=SEARCH_EXHAUSTIVE,
        )
    assert exhausted.value.code == "DCC_SEARCH_BUDGET_EXHAUSTED"

    # The same shape under AUTO is routed away from enumeration instead of
    # failing closed, because the estimated space does not fit the budget.
    routed = compile_legal_plans(
        (slot,),
        target_cl=15,
        final_validator=_accept_final_validator,
        frontier_limit=1,
        search_state_limit=2,
    )
    assert routed.search_strategy == SEARCH_SEEDED_ROLLOUT
    assert routed.space_complete is False
    assert len(routed.plans) == 1
    assert len(routed.plans[0].choice_ids) == 6

    # A space that does fit is still enumerated exactly, and says so.
    small = compile_legal_plans(
        (TypedChoiceSlot("few", tuple(TypedChoiceOption(f"talent.{index}") for index in range(3))),),
        target_cl=15,
        final_validator=_accept_final_validator,
    )
    assert small.search_strategy == SEARCH_EXHAUSTIVE
    assert small.space_complete is True
    assert len(small.plans) == 3
    for plan in small.plans:
        binding = plan.proof["compiler_binding"]
        assert binding["search_strategy"] == SEARCH_EXHAUSTIVE
        assert binding["skeleton_enumerated"] is True


def test_seeded_rollout_continues_after_predicate_rejection() -> None:
    slots = (
        TypedChoiceSlot(
            "candidate",
            (TypedChoiceOption("candidate.a_rejected"), TypedChoiceOption("candidate.b_accepted")),
            choice_kind="talent",
        ),
    )

    def predicate(payload: dict[str, Any]) -> bool:
        return payload["choices"][0]["choice_id"] == "candidate.b_accepted"

    result = compile_legal_plans(
        slots,
        target_cl=1,
        final_validator=_accept_final_validator,
        plan_predicate=predicate,
        controlled_preferences_sha256=sha256_json({}),
        frontier_limit=1,
        search_state_limit=2,
        search_strategy=SEARCH_SEEDED_ROLLOUT,
    )
    assert [plan.choice_ids for plan in result.plans] == [("candidate.b_accepted",)]
    assert len(result.predicate_rejections) == 1
    assert result.explored_states == 2


def test_seeded_rollout_continues_after_factory_validator_rejection() -> None:
    slots = (
        TypedChoiceSlot(
            "candidate",
            (TypedChoiceOption("candidate.a_rejected"), TypedChoiceOption("candidate.b_accepted")),
            choice_kind="talent",
        ),
    )

    def validator(payload: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": payload["choices"][0]["choice_id"] == "candidate.b_accepted"}

    result = compile_legal_plans(
        slots,
        target_cl=1,
        final_validator=validator,
        frontier_limit=1,
        search_state_limit=2,
        search_strategy=SEARCH_SEEDED_ROLLOUT,
    )
    assert [plan.choice_ids for plan in result.plans] == [("candidate.b_accepted",)]
    assert len(result.validator_rejections) == 1
    assert result.explored_states == 2


def test_auto_accounts_for_prefix_states_before_selecting_exhaustive() -> None:
    slots = tuple(
        TypedChoiceSlot(
            f"choice.{index}",
            (TypedChoiceOption(f"choice.{index}.0"), TypedChoiceOption(f"choice.{index}.1")),
            choice_kind="talent",
        )
        for index in range(8)
    )

    def accept_only_last_assignment(payload: dict[str, Any]) -> bool:
        return all(row["choice_id"].endswith(".1") for row in payload["choices"])

    with pytest.raises(CreativeControllerError) as exhausted:
        compile_legal_plans(
            slots,
            target_cl=1,
            final_validator=accept_only_last_assignment,
            frontier_limit=1,
            search_state_limit=300,
            search_strategy=SEARCH_EXHAUSTIVE,
        )
    assert exhausted.value.code == "DCC_SEARCH_BUDGET_EXHAUSTED"

    result = compile_legal_plans(
        slots,
        target_cl=1,
        final_validator=accept_only_last_assignment,
        frontier_limit=1,
        search_state_limit=300,
        search_strategy=SEARCH_AUTO,
        backtrack_limit=512,
    )
    assert result.search_strategy == SEARCH_SEEDED_ROLLOUT
    assert result.plans and all(row["choice_id"].endswith(".1") for row in result.plans[0].choices)
    assert result.explored_states <= 300


def test_exhaustive_preflights_raw_multi_select_combinations_before_pruning() -> None:
    slot = TypedChoiceSlot(
        "many",
        tuple(TypedChoiceOption(f"many.{index}") for index in range(40)),
        min_choices=6,
        max_choices=6,
    )

    with pytest.raises(CreativeControllerError) as exhausted:
        compile_legal_plans(
            (slot,),
            target_cl=1,
            final_validator=lambda _payload: False,
            frontier_limit=1,
            search_state_limit=1_000,
            search_strategy=SEARCH_EXHAUSTIVE,
        )
    assert exhausted.value.code == "DCC_SEARCH_BUDGET_EXHAUSTED"


def test_seeded_skeleton_bounds_raw_all_pruned_multi_select_combinations() -> None:
    choice_ids = tuple(f"route.{index}" for index in range(40))
    options = tuple(
        TypedChoiceOption(
            choice_id,
            choice_kind="path",
            incompatibilities=tuple(other for other in choice_ids if other != choice_id),
        )
        for choice_id in choice_ids
    )
    slot = TypedChoiceSlot("route", options, choice_kind="path", min_choices=6, max_choices=6)

    result = compile_legal_plans(
        (slot,),
        target_cl=1,
        final_validator=_accept_final_validator,
        frontier_limit=1,
        search_state_limit=100,
        search_strategy=SEARCH_SEEDED_ROLLOUT,
        skeleton_limit=4,
    )
    assert result.plans == ()
    assert result.skeleton_enumerated is False
    assert result.rollouts_attempted == 1
    assert result.rollouts_abandoned == 1


def test_diversity_seed_set_changes_compiler_authority() -> None:
    slots = (
        TypedChoiceSlot(
            "candidate",
            (TypedChoiceOption("candidate.a"), TypedChoiceOption("candidate.b")),
            choice_kind="talent",
        ),
    )

    def affinity(seed: dict[str, Any], option: dict[str, Any]) -> int:
        return 100 if option["choice_id"] == seed["choice_id"] else 0

    first_seeds = [{"choice_id": "candidate.a"}]
    second_seeds = [{"choice_id": "candidate.b"}]
    first = compile_legal_plans(
        slots,
        target_cl=1,
        final_validator=_accept_final_validator,
        frontier_limit=1,
        search_strategy=SEARCH_SEEDED_ROLLOUT,
        diversity_seeds=first_seeds,
        seed_affinity=affinity,
    )
    second = compile_legal_plans(
        slots,
        target_cl=1,
        final_validator=_accept_final_validator,
        frontier_limit=1,
        search_strategy=SEARCH_SEEDED_ROLLOUT,
        diversity_seeds=second_seeds,
        seed_affinity=affinity,
    )
    assert first.plans[0].choice_ids != second.plans[0].choice_ids
    first_binding = first.plans[0].proof["compiler_binding"]
    second_binding = second.plans[0].proof["compiler_binding"]
    assert first_binding["compiler_binding_sha256"] != second_binding["compiler_binding_sha256"]
    assert first_binding["diversity_seed_set_sha256"] == sha256_json(first_seeds)
    assert second_binding["diversity_seed_set_sha256"] == sha256_json(second_seeds)
    for binding in (first_binding, second_binding):
        assert binding["requested_search_strategy"] == SEARCH_SEEDED_ROLLOUT
        assert binding["resolved_search_strategy"] == SEARCH_SEEDED_ROLLOUT
        assert binding["search_strategy"] == SEARCH_SEEDED_ROLLOUT
        assert binding["frontier_limit"] == 1
        assert binding["search_state_limit"] == 100_000
        assert binding["skeleton_limit"] == 64
        assert binding["backtrack_limit"] == 64
        assert binding["affinity_policy_version"]
        assert binding["affinity_policy_sha256"]


def test_seeded_rollout_scales_past_the_enumeration_wall() -> None:
    """Catalogue-scale shapes must compile instead of exhausting the budget."""

    slots = tuple(
        TypedChoiceSlot(
            f"talent_{index}",
            tuple(TypedChoiceOption(f"talent.{index}.{option}", "talent", 1) for option in range(60)),
            choice_kind="talent",
        )
        for index in range(12)
    )
    started = time.monotonic()
    result = compile_legal_plans(slots, target_cl=15, final_validator=_accept_final_validator, frontier_limit=12)
    elapsed = time.monotonic() - started
    assert result.search_strategy == SEARCH_SEEDED_ROLLOUT
    assert result.plans
    assert elapsed < 5.0
    for plan in result.plans:
        assert len(plan.choice_ids) == 12
        assert plan.proof["checks"]["final_factory_validator"] is True

    # A single wide multi-select slot is combinatorially hopeless to enumerate
    # (C(40,6) is ~3.8M) but must still compile.
    wide = TypedChoiceSlot(
        "talents",
        tuple(TypedChoiceOption(f"talent.{index}", "talent", 1) for index in range(40)),
        choice_kind="talent",
        min_choices=6,
        max_choices=6,
    )
    wide_result = compile_legal_plans((wide,), target_cl=15, final_validator=_accept_final_validator, frontier_limit=4)
    assert wide_result.search_strategy == SEARCH_SEEDED_ROLLOUT
    assert wide_result.plans
    assert all(len(plan.choice_ids) == 6 for plan in wide_result.plans)


def test_seeded_rollout_pool_varies_across_many_slots() -> None:
    """The candidate pool must be diverse by construction, not by luck.

    Regression guard for enumeration order collapsing every candidate onto the
    lexicographically first option in all but the trailing slot.
    """

    def family(choice_id: str) -> int:
        return int(choice_id.rsplit(".", 1)[1]) % 6

    slots = tuple(
        TypedChoiceSlot(
            f"talent_{index}",
            tuple(TypedChoiceOption(f"talent.{index}.{option}", "talent", 1) for option in range(60)),
            choice_kind="talent",
        )
        for index in range(12)
    )
    seeds = [{"family": value} for value in range(6)]

    def seed_affinity(seed: dict[str, Any], option: dict[str, Any]) -> int:
        return 100 if family(option["choice_id"]) == seed["family"] else 0

    result = compile_legal_plans(
        slots,
        target_cl=15,
        final_validator=_accept_final_validator,
        frontier_limit=12,
        diversity_seeds=seeds,
        seed_affinity=seed_affinity,
    )
    assert len(result.plans) >= 4
    pool = [set(plan.choice_ids) for plan in result.plans]
    varying = 0
    for index in range(12):
        chosen = {next(choice for choice in plan if choice.startswith(f"talent.{index}.")) for plan in pool}
        if len(chosen) > 1:
            varying += 1
    assert varying == 12, "every decision slot must vary across the candidate pool"

    # Identical inputs must still produce an identical pool.
    repeat = compile_legal_plans(
        slots,
        target_cl=15,
        final_validator=_accept_final_validator,
        frontier_limit=12,
        diversity_seeds=seeds,
        seed_affinity=seed_affinity,
    )
    assert [plan.legal_plan_sha256 for plan in repeat.plans] == [plan.legal_plan_sha256 for plan in result.plans]


def test_diversity_seeds_are_derived_only_from_verified_semantics(fixture: dict[str, Any]) -> None:
    seeds = build_diversity_seeds(fixture["semantics"], count=8)
    assert seeds[0]["role_tags"] == [] and seeds[0]["capability_families"] == []
    assert len(seeds) == len(set(canonical_json(seed) for seed in seeds))
    assert build_diversity_seeds(fixture["semantics"], count=8) == seeds
    verified_roles = {tag for record in fixture["semantics"].values() for tag in record.value["role_tags"]}
    for seed in seeds[1:]:
        assert set(seed["role_tags"]) <= verified_roles


def test_duplicate_cards_refill_from_lower_ranked_plans(fixture: dict[str, Any]) -> None:
    """Incidental card collisions substitute; a total collapse still fails."""

    semantics = {
        "path.clone_a": _semantics("path.clone_a", "path", role="protector", capabilities=["defense"], functions=["defense"], themes=["guardianship"], complexity="simple"),
        "path.clone_b": _semantics("path.clone_b", "path", role="protector", capabilities=["defense"], functions=["defense"], themes=["guardianship"], complexity="simple"),
        # Same hard-gated role so it survives the intent's must_include, but a
        # different capability profile so its card is genuinely distinguishable.
        "path.distinct": _semantics("path.distinct", "path", role="protector", capabilities=["mobility"], functions=["utility"], themes=["earned_mastery"], complexity="complex"),
    }
    slots = (TypedChoiceSlot("route", tuple(TypedChoiceOption(choice_id, "path", 1) for choice_id in semantics), choice_kind="path"),)
    compiled = compile_legal_plans(slots, target_cl=15, final_validator=_accept_final_validator)
    ranked = rank_plans(compiled.plans, fixture["intent"], semantics)
    artifact = build_manifest(ranked.ranked_plans, binding=fixture["inputs"].binding)

    titles = [option["title"] for option in artifact.manifest["options"]]
    assert len(titles) == len(set(titles)) == 2, "the duplicate card is dropped, not published"
    substitutions = artifact.private_evidence["card_distinctness_substitutions"]
    assert len(substitutions) == 1
    skipped = substitutions[0]["skipped_legal_plan_sha256"]
    assert skipped not in [option["proof"]["legal_plan_sha256"] for option in artifact.manifest["options"]]
    assert skipped != substitutions[0]["duplicate_of_legal_plan_sha256"]


def test_shadow_rejects_unsealed_validator_callable(fixture: dict[str, Any]) -> None:
    with pytest.raises(CreativeControllerError) as error:
        replace(fixture["inputs"], final_validator=_accept_final_validator)
    assert error.value.code == "DCC_FACTORY_FINAL_VALIDATOR_REQUIRED"


def test_shadow_rejects_mismatched_factory_validator_authority_before_compilation(fixture: dict[str, Any]) -> None:
    with pytest.raises(CreativeControllerError) as error:
        replace(
            fixture["inputs"],
            delegated_choice_envelope_sha256=_d("tampered-delegated-envelope"),
        )
    assert error.value.code == "DCC_FACTORY_VALIDATOR_AUTHORITY_BINDING"


def test_verified_semantics_gate_and_whole_plan_aggregation(fixture: dict[str, Any]) -> None:
    semantics = fixture["semantics"]
    plan = {"choices": ["path.bastion", "method.salvage", "talent.scavenge"]}
    aggregate = aggregate_whole_plan_semantics(plan, semantics)
    assert aggregate["resource_loop"]["exact_producer_consumer_matches"] == ["salvage"]
    assert aggregate["synergy_edges"][0]["target_choice_id"] == "talent.scavenge"
    assert aggregate["choice_semantics_set_sha256"] == sha256_json([semantics[key].semantics_sha256 for key in sorted(plan["choices"])])
    path_record = next(row for row in fixture["records"] if row.choice_id == "path.bastion")
    verify_semantics_binding(semantics["path.bastion"], catalogue_sha256=fixture["snapshot"].catalogue_set_sha256, choice_record_sha256=path_record.choice_record_sha256, typed_authority_sha256=path_record.typed_authority_sha256)
    stale = semantics["path.bastion"].to_dict()
    stale["catalogue_binding"]["catalogue_sha256"] = _d("other-catalogue")
    stale["semantics_sha256"] = sha256_json({key: value for key, value in stale.items() if key != "semantics_sha256"})
    with pytest.raises(CreativeControllerError) as stale_error:
        verify_semantics_binding(stale, catalogue_sha256=fixture["snapshot"].catalogue_set_sha256, choice_record_sha256=path_record.choice_record_sha256, typed_authority_sha256=path_record.typed_authority_sha256)
    assert stale_error.value.code == "DCC_CHOICE_SEMANTICS_STALE"


def test_shadow_manifest_hides_private_scores_and_resolves_only_stored_options(fixture: dict[str, Any]) -> None:
    result = run_shadow_controller(fixture["inputs"])
    public = result.manifest
    public_text = result.manifest_json
    validate_manifest(public)
    assert len(public["options"]) == 4
    assert "scores" not in public_text
    assert "weighted_total" not in public_text
    assert "plan_payload" not in public_text
    assert "path.bastion" not in public_text
    assert "option_to_plan" not in public_text
    assert result.private_evidence["manifest_private_evidence"]["option_to_plan"]
    assert {
        option["proof"]["factory_validator_authority_sha256"]
        for option in public["options"]
    } == {fixture["inputs"].final_validator.authority_sha256}
    titles = [option["title"] for option in public["options"]]
    assert len(titles) == len(set(titles))
    assert all(option["why_it_fits"] != "Matches the accepted controlled priorities through verified Factory semantics." for option in public["options"])
    assert all(option["distinctness_cue"] != "distinct verified route in this set" for option in public["options"])
    assert {cluster["signature"]["primary_route"] for cluster in result.private_evidence["diversity"]["clusters"]} == {"path.bastion", "path.runner"}
    for payload in result.private_evidence["compiled_plan_payloads"].values():
        aggregate = aggregate_whole_plan_semantics(payload, fixture["semantics"])
        assert evaluate_controlled_preferences(aggregate, fixture["intent"])["hard_passed"] is True

    option_id = public["options"][0]["option_id"]
    plan = result.artifact.plan_for_option(option_id)
    before = result.artifact.to_json()
    accepted = accept_option(result.artifact, {"option_id": option_id, "rationale": "preserves the accepted priorities"}, expected_manifest_sha256=result.artifact.manifest_sha256)
    assert accepted.option_id == option_id
    assert accepted.legal_plan_sha256 == plan.legal_plan_sha256
    assert accepted.plan.plan_payload == plan.plan_payload
    with pytest.raises(CreativeControllerError) as malformed:
        accept_option(result.artifact, {"option_id": option_id, "plan_payload": plan.plan_payload})
    assert malformed.value.code == "DCC_SCHEMA_UNKNOWN_FIELD"
    with pytest.raises(CreativeControllerError) as unknown:
        accept_option(result.artifact, {"option_id": "dcc.opt." + "f" * 24})
    assert unknown.value.code == "DCC_OPTION_UNKNOWN"
    with pytest.raises(CreativeControllerError) as stale:
        accept_option(result.artifact, {"option_id": option_id}, expected_manifest_sha256=_d("stale-manifest"))
    assert stale.value.code == "DCC_MANIFEST_STALE"
    with pytest.raises(CreativeControllerError) as stale_revision:
        accept_option(result.artifact, {"option_id": option_id}, expected_project_revision=13, current_project_revision=13)
    assert stale_revision.value.code == "DCC_MANIFEST_STALE"
    assert result.artifact.to_json() == before


def test_one_hundred_cold_process_shadow_runs_are_byte_identical(fixture: dict[str, Any]) -> None:
    probe = (
        "import importlib.util,hashlib;"
        f"s=importlib.util.spec_from_file_location('dcc_probe',{str(Path(__file__).resolve())!r});"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "print(hashlib.sha256(m.run_shadow_controller(m._fixture()['inputs']).manifest_json.encode()).hexdigest())"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    outputs: list[str] = []
    for start in range(0, 100, 8):
        processes = [
            subprocess.Popen([sys.executable, "-c", probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
            for _ in range(min(8, 100 - start))
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            outputs.append(stdout.strip())
    assert len(outputs) == 100
    assert len(set(outputs)) == 1


def test_cold_process_shadow_runs_are_byte_identical_under_seeded_rollout() -> None:
    """The rollout path needs the same cross-process determinism guarantee.

    Hash randomization differs per subprocess, so this is the real evidence
    that seed derivation, affinity ordering, and backtracking introduced no
    dependence on set iteration order, a clock, or a random source.
    """

    probe = (
        "import importlib.util,hashlib,dataclasses;"
        f"s=importlib.util.spec_from_file_location('dcc_probe',{str(Path(__file__).resolve())!r});"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "i=dataclasses.replace(m._fixture()['inputs'],search_strategy='SEEDED_ROLLOUT');"
        "r=m.run_shadow_controller(i);"
        "assert r.private_evidence['compiler_search']['search_strategy']=='SEEDED_ROLLOUT';"
        "print(hashlib.sha256(r.manifest_json.encode()).hexdigest())"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    outputs: list[str] = []
    for start in range(0, 32, 8):
        processes = [
            subprocess.Popen([sys.executable, "-c", probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
            for _ in range(min(8, 32 - start))
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, stderr
            outputs.append(stdout.strip())
    assert len(outputs) == 32
    assert len(set(outputs)) == 1


def test_bounded_pre_intent_menu_resolves_only_factory_options(fixture: dict[str, Any]) -> None:
    resolved = resolve_creative_predicate_selection(fixture["predicate_menu"], fixture["predicate_selection"])
    assert resolved["controlled_preferences"] == fixture["intent"]["controlled_preferences"]
    assert resolved["receipt"]["controlled_preferences_sha256"] == sha256_json(fixture["intent"]["controlled_preferences"])
    unknown = deepcopy(fixture["predicate_selection"])
    unknown["soft_prefer"] = ["dcc.pred." + "f" * 24]
    with pytest.raises(CreativeControllerError) as error:
        resolve_creative_predicate_selection(fixture["predicate_menu"], unknown)
    assert error.value.code == "DCC_CREATIVE_PREDICATE_UNKNOWN"
    unauthorized = deepcopy(fixture["predicate_selection"])
    unauthorized["must_include"] = unauthorized["soft_prefer"]
    with pytest.raises(CreativeControllerError) as error:
        resolve_creative_predicate_selection(fixture["predicate_menu"], unauthorized)
    assert error.value.code == "DCC_CREATIVE_HARD_AUTHORITY"


def test_deterministic_clustering_and_tie_resolution(fixture: dict[str, Any]) -> None:
    compiled = compile_legal_plans(fixture["slots"], target_cl=15, final_validator=_accept_final_validator)
    ranked = rank_plans(compiled.plans, fixture["intent"], fixture["semantics"])
    first = select_diverse_plans(ranked.ranked_plans, count=4)
    second = select_diverse_plans(ranked.ranked_plans, count=4)
    assert [row.legal_plan_sha256 for row in first.selected] == [row.legal_plan_sha256 for row in second.selected]
    assert [cluster.medoid_plan_sha256 for cluster in first.clusters] == [cluster.medoid_plan_sha256 for cluster in second.clusters]
    signature = signature_for_plan(ranked.ranked_plans[0].plan, ranked.ranked_plans[0].semantics)
    assert categorical_distance(signature, signature) == 0
    assert len(first.clusters) == 4
    # Every medoid is the first ranked member of its own categorical cluster.
    for cluster in first.clusters:
        assert cluster.medoid_plan_sha256 in cluster.member_plan_sha256s
    tied = [row for row in ranked.ranked_plans if row.weighted_total == ranked.ranked_plans[0].weighted_total and row.scores.to_dict() == ranked.ranked_plans[0].scores.to_dict() and row.complexity_distance == ranked.ranked_plans[0].complexity_distance]
    assert len(tied) >= 2
    assert [row.legal_plan_sha256 for row in tied] == sorted(row.legal_plan_sha256 for row in tied)
    method_only = {"choices": [{"slot_id": "method", "choice_id": "method.salvage", "choice_kind": "method", "acquisition_cl": 1}]}
    method_semantics = aggregate_whole_plan_semantics(["method.salvage"], fixture["semantics"])
    with pytest.raises(CreativeControllerError) as missing_route:
        signature_for_plan(method_only, method_semantics)
    assert missing_route.value.code == "DCC_PRIMARY_ROUTE_REQUIRED"


def test_manifest_rejects_semantically_indistinguishable_cards(fixture: dict[str, Any]) -> None:
    semantics = {
        choice_id: _semantics(
            choice_id,
            "path",
            role="protector",
            capabilities=["defense"],
            functions=["defense"],
            themes=["guardianship"],
            complexity="simple",
        )
        for choice_id in ("path.clone_a", "path.clone_b")
    }
    slots = (TypedChoiceSlot("route", tuple(TypedChoiceOption(choice_id, "path", 1) for choice_id in semantics), choice_kind="path"),)
    compiled = compile_legal_plans(slots, target_cl=15, final_validator=_accept_final_validator)
    ranked = rank_plans(compiled.plans, fixture["intent"], semantics)
    with pytest.raises(CreativeControllerError) as duplicate:
        build_manifest(ranked.ranked_plans, binding=fixture["inputs"].binding)
    assert duplicate.value.code == "DCC_MANIFEST_CARD_NOT_DISTINCT"


def test_content_add_retire_restore_rebalance_and_incremental_closure(fixture: dict[str, Any]) -> None:
    root: FactoryContentSnapshot = fixture["snapshot"]
    original = root.to_dict()
    new_sem = _semantics("talent.spare", "talent", role="supporter", capabilities=["recovery"], functions=["recovery"])
    new_record = ContentRecordCommitment("talent.spare", "talent", "ACTIVE", True, _d("record:talent.spare"), _d("typed:talent.spare"), new_sem.semantics_sha256, _d("rights:talent.spare"))
    child_added = build_content_snapshot(tuple(root.records) + (new_record,), parent=root, catalogue_schema_versions=dict(root.catalogue_schema_versions), rules_authority_sha256=root.rules_authority_sha256, required_compiler_profile_sha256=root.required_compiler_profile_sha256, dependency_edges=fixture["edges"])
    added_changes = build_content_change_set(root, child_added)
    assert added_changes.value["added"] == [{"choice_id": "talent.spare", "choice_record_sha256": new_record.choice_record_sha256}]
    assert root.to_dict() == original

    retired_record = replace(next(row for row in root.records if row.choice_id == "talent.burst"), lifecycle="RETIRED", eligible_for_new_builds=False)
    retired = build_content_snapshot(tuple(retired_record if row.choice_id == "talent.burst" else row for row in root.records), parent=root, catalogue_schema_versions=dict(root.catalogue_schema_versions), rules_authority_sha256=root.rules_authority_sha256, required_compiler_profile_sha256=root.required_compiler_profile_sha256, dependency_edges=fixture["edges"])
    retired_changes = build_content_change_set(root, retired)
    assert retired_changes.value["retired"][0]["choice_id"] == "talent.burst"
    restored = build_content_snapshot(tuple(root.records), parent=retired, catalogue_schema_versions=dict(root.catalogue_schema_versions), rules_authority_sha256=root.rules_authority_sha256, required_compiler_profile_sha256=root.required_compiler_profile_sha256, dependency_edges=fixture["edges"])
    restored_changes = build_content_change_set(retired, restored)
    assert restored_changes.value["restored"][0]["choice_id"] == "talent.burst"

    old_row = next(row for row in root.records if row.choice_id == "path.bastion")
    rebalance_sem_unsigned = fixture["semantics"]["path.bastion"].to_dict()
    rebalance_sem_unsigned.pop("semantics_sha256")
    rebalance_sem_unsigned["theme_tags"] = ["quiet_craft", "guardianship", "quiet_mastery"]
    rebalance_sem = build_choice_semantics(rebalance_sem_unsigned)
    rebalance_row = replace(old_row, choice_record_sha256=_d("record:path.bastion:v2"), typed_authority_sha256=_d("typed:path.bastion:v2"), choice_semantics_sha256=rebalance_sem.semantics_sha256)
    rebalanced = build_content_snapshot(tuple(rebalance_row if row.choice_id == old_row.choice_id else row for row in root.records), parent=root, catalogue_schema_versions=dict(root.catalogue_schema_versions), rules_authority_sha256=root.rules_authority_sha256, required_compiler_profile_sha256=root.required_compiler_profile_sha256, dependency_edges=fixture["edges"])
    rebalance_changes = build_content_change_set(root, rebalanced)
    changed = next(row for row in rebalance_changes.value["changed"] if row["choice_id"] == "path.bastion")
    assert {"DISPLAY", "MECHANICS", "SEMANTICS"} <= set(changed["change_classes"])
    assert set(rebalance_changes.value["affected_choice_ids"]) >= {"path.bastion", "talent.guard", "talent.control"}
    assert affected_dependency_closure(["path.bastion"], fixture["edges"]) == ("path.bastion", "talent.control", "talent.guard")
    assert root.content_snapshot_sha256 != rebalanced.content_snapshot_sha256
    assert root.to_dict() == original

    downgraded = build_content_change_set(
        root,
        rebalanced,
        change_class_overrides={"path.bastion": ["DISPLAY"]},
    )
    downgraded_row = next(row for row in downgraded.value["changed"] if row["choice_id"] == "path.bastion")
    assert {"DISPLAY", "MECHANICS", "SEMANTICS"} <= set(downgraded_row["change_classes"])
    assert downgraded_row["migration_compatibility"] == "REVALIDATE"


def _rebound_child_snapshot(
    parent: FactoryContentSnapshot,
    records: tuple[ContentRecordCommitment, ...],
    semantics: dict[str, ChoiceSemantics],
    edges: dict[str, list[str]],
) -> tuple[FactoryContentSnapshot, dict[str, ChoiceSemantics]]:
    """Build child content and rebind active semantics to its catalogue hash."""

    provisional = build_content_snapshot(
        records,
        parent=parent,
        catalogue_schema_versions=dict(parent.catalogue_schema_versions),
        rules_authority_sha256=parent.rules_authority_sha256,
        required_compiler_profile_sha256=parent.required_compiler_profile_sha256,
        dependency_edges=edges,
        vocabulary_authority_sha256=parent.vocabulary_authority_sha256,
    )
    rebound: dict[str, ChoiceSemantics] = {}
    for choice_id, record in provisional.record_by_id().items():
        if record.lifecycle != "ACTIVE":
            continue
        unsigned = semantics[choice_id].to_dict()
        unsigned.pop("semantics_sha256")
        unsigned["catalogue_binding"] = {
            "catalogue_sha256": provisional.catalogue_set_sha256,
            "choice_record_sha256": record.choice_record_sha256,
            "typed_authority_sha256": record.typed_authority_sha256,
        }
        rebound[choice_id] = build_choice_semantics(unsigned)
    rebound_records = tuple(
        replace(row, choice_semantics_sha256=rebound[row.choice_id].semantics_sha256)
        if row.choice_id in rebound else row
        for row in records
    )
    child = build_content_snapshot(
        rebound_records,
        parent=parent,
        catalogue_schema_versions=dict(parent.catalogue_schema_versions),
        rules_authority_sha256=parent.rules_authority_sha256,
        required_compiler_profile_sha256=parent.required_compiler_profile_sha256,
        dependency_edges=edges,
        vocabulary_authority_sha256=parent.vocabulary_authority_sha256,
    )
    assert child.catalogue_set_sha256 == provisional.catalogue_set_sha256
    return child, rebound


def _child_shadow_inputs(
    base: ShadowInputs,
    child: FactoryContentSnapshot,
    semantics: dict[str, ChoiceSemantics],
) -> ShadowInputs:
    intent = base.intent.copy()
    intent.pop("intent_sha256")
    intent.pop("intent_id")
    intent["binding"] = {**intent["binding"], "content_snapshot_sha256": child.content_snapshot_sha256}
    active_ids = set(child.active_choice_ids)
    slots = tuple(
        replace(slot, options=tuple(option for option in slot.options if option.choice_id in active_ids))
        for slot in base.slots
    )
    return replace(
        base,
        content_snapshot=child,
        intent=build_creative_intent(intent),
        semantics=semantics,
        slots=slots,
    )


def test_pinned_shadow_manifest_survives_child_snapshots_and_rebound_runs(fixture: dict[str, Any]) -> None:
    """Child construction never mutates the pinned result and detached rebuilds agree."""

    root: FactoryContentSnapshot = fixture["snapshot"]
    base_result = run_shadow_controller(fixture["inputs"])
    pinned_manifest_bytes = base_result.manifest_json
    original_snapshot_bytes = root.to_dict()
    semantic_rows = fixture["semantics"]

    added_sem = _semantics("talent.spare.child", "talent", role="supporter", capabilities=["recovery"], functions=["recovery"])
    added_record = ContentRecordCommitment(
        "talent.spare.child",
        "talent",
        "ACTIVE",
        True,
        _d("record:talent.spare.child"),
        _d("typed:talent.spare.child"),
        added_sem.semantics_sha256,
        _d("rights:talent.spare.child"),
    )
    added_child, added_semantics = _rebound_child_snapshot(
        root,
        tuple(root.records) + (added_record,),
        {**semantic_rows, added_sem.choice_id: added_sem},
        fixture["edges"],
    )

    retired_record = replace(
        next(row for row in root.records if row.choice_id == "talent.burst"),
        lifecycle="RETIRED",
        eligible_for_new_builds=False,
    )
    retired_child, retired_semantics = _rebound_child_snapshot(
        root,
        tuple(retired_record if row.choice_id == retired_record.choice_id else row for row in root.records),
        semantic_rows,
        fixture["edges"],
    )

    rebalance_unsigned = semantic_rows["path.bastion"].to_dict()
    rebalance_unsigned.pop("semantics_sha256")
    rebalance_unsigned["theme_tags"] = ["quiet_craft", "guardianship", "quiet_mastery"]
    rebalance_sem = build_choice_semantics(rebalance_unsigned)
    rebalance_source = next(row for row in root.records if row.choice_id == "path.bastion")
    rebalance_record = replace(
        rebalance_source,
        choice_record_sha256=_d("record:path.bastion:child-v2"),
        typed_authority_sha256=_d("typed:path.bastion:child-v2"),
        choice_semantics_sha256=rebalance_sem.semantics_sha256,
    )
    rebalanced_child, rebalanced_semantics = _rebound_child_snapshot(
        root,
        tuple(rebalance_record if row.choice_id == rebalance_source.choice_id else row for row in root.records),
        {**semantic_rows, rebalance_sem.choice_id: rebalance_sem},
        fixture["edges"],
    )

    assert base_result.manifest_json == pinned_manifest_bytes
    assert root.to_dict() == original_snapshot_bytes
    for child, semantics in (
        (added_child, added_semantics),
        (retired_child, retired_semantics),
        (rebalanced_child, rebalanced_semantics),
    ):
        direct = run_shadow_controller(_child_shadow_inputs(fixture["inputs"], child, semantics))
        # Parsing a detached snapshot models the cold/incremental equality
        # available in Stage A without asserting production cache behavior.
        detached_child = FactoryContentSnapshot.from_mapping(child.to_dict())
        cold = run_shadow_controller(_child_shadow_inputs(fixture["inputs"], detached_child, semantics))
        assert direct.manifest_json == cold.manifest_json
        assert direct.manifest["binding"]["content_snapshot_sha256"] == child.content_snapshot_sha256
        assert direct.private_evidence["content_snapshot_sha256"] == child.content_snapshot_sha256
        assert direct.manifest_json != pinned_manifest_bytes
        assert base_result.manifest_json == pinned_manifest_bytes


def test_migration_receipt_preserves_historical_revision_and_blocks_or_creates_new_one(fixture: dict[str, Any]) -> None:
    root = fixture["snapshot"]
    old_row = next(row for row in root.records if row.choice_id == "path.bastion")
    changed_row = replace(old_row, choice_record_sha256=_d("migration-record-v2"), typed_authority_sha256=_d("migration-typed-v2"))
    child = build_content_snapshot(tuple(changed_row if row.choice_id == old_row.choice_id else row for row in root.records), parent=root, catalogue_schema_versions=dict(root.catalogue_schema_versions), rules_authority_sha256=root.rules_authority_sha256, required_compiler_profile_sha256=root.required_compiler_profile_sha256, dependency_edges=fixture["edges"])
    changes = build_content_change_set(root, child)
    source_revision = {"revision": 7, "content_snapshot_sha256": root.content_snapshot_sha256, "selected_choice_ids": ["path.bastion"]}
    source_before = deepcopy(source_revision)
    blocked_projection = migrate_character_revision(source_revision, target_snapshot_sha256=child.content_snapshot_sha256, result="BLOCKED")
    assert blocked_projection["target_revision"] is None
    assert source_revision == source_before
    blocked = build_migration_receipt(character_id="character.kai.shadow", from_character_revision_sha256=_d("character-revision-7"), from_snapshot=root, to_snapshot=child, change_set=changes, migration_policy_sha256=_d("migration-policy"), migration_intent_sha256=fixture["intent"]["intent_sha256"], selected_ai_identity_sha256=_d("selected-ai"), result="BLOCKED")
    assert blocked.value["to_character_revision_sha256"] is None
    source_revision_sha256 = sha256_json(source_revision)
    target_revision_unsigned = deepcopy(source_revision)
    target_revision_unsigned["content_snapshot_sha256"] = child.content_snapshot_sha256
    target_revision_unsigned["source_revision_sha256"] = source_revision_sha256
    target_revision_sha256 = sha256_json(target_revision_unsigned)
    with pytest.raises(CreativeControllerError) as missing_receipt:
        migrate_character_revision(source_revision, target_snapshot_sha256=child.content_snapshot_sha256, from_snapshot=root, to_snapshot=child, change_set=changes)
    assert missing_receipt.value.code == "DCC_MIGRATION_RECEIPT_REQUIRED"
    migrated = build_migration_receipt(character_id="character.kai.shadow", from_character_revision_sha256=source_revision_sha256, from_snapshot=root, to_snapshot=child, change_set=changes, migration_policy_sha256=_d("migration-policy"), migration_intent_sha256=fixture["intent"]["intent_sha256"], selected_ai_identity_sha256=_d("selected-ai"), closure_handled_choice_ids=changes.value["affected_choice_ids"], preserved_choice_ids=changes.value["affected_choice_ids"], regenerated_surfaces=["actions", "final_package"], validation_receipt_sha256s=[_d("validation")], to_character_revision_sha256=target_revision_sha256, result="MIGRATED")
    migrated_projection = migrate_character_revision(source_revision, target_snapshot_sha256=child.content_snapshot_sha256, from_snapshot=root, to_snapshot=child, change_set=changes, migration_receipt=migrated)
    assert migrated_projection["source_revision"] == source_before
    assert migrated_projection["target_revision"]["content_snapshot_sha256"] == child.content_snapshot_sha256
    assert migrated_projection["target_revision"]["character_revision_sha256"] == target_revision_sha256
    assert migrated.value["result"] == "MIGRATED"
    tampered_receipt = migrated.to_dict()
    tampered_receipt["to_content_snapshot_sha256"] = _d("unrelated-target-snapshot")
    tampered_receipt["migration_receipt_sha256"] = sha256_json({key: value for key, value in tampered_receipt.items() if key != "migration_receipt_sha256"})
    with pytest.raises(CreativeControllerError) as mismatched_receipt:
        migrate_character_revision(source_revision, target_snapshot_sha256=child.content_snapshot_sha256, from_snapshot=root, to_snapshot=child, change_set=changes, migration_receipt=tampered_receipt)
    assert mismatched_receipt.value.code == "DCC_MIGRATION_RECEIPT_BINDING"
    forged_receipt = migrated.to_dict()
    forged_receipt["content_change_set_sha256"] = _d("unrelated-change-set")
    forged_receipt["affected_dependency_closure_sha256"] = sha256_json(["path.bastion"])
    forged_receipt["closure_handled_choice_ids"] = ["path.bastion"]
    forged_receipt["preserved_choice_ids"] = ["path.bastion"]
    forged_receipt["migration_receipt_sha256"] = sha256_json({key: value for key, value in forged_receipt.items() if key != "migration_receipt_sha256"})
    with pytest.raises(CreativeControllerError) as forged:
        migrate_character_revision(source_revision, target_snapshot_sha256=child.content_snapshot_sha256, from_snapshot=root, to_snapshot=child, change_set=changes, migration_receipt=forged_receipt)
    assert forged.value.code == "DCC_MIGRATION_RECEIPT_BINDING"
    migrated.value["preserved_choice_ids"] = []
    migrated.value["replacement_choice_events"] = []
    migrated.value["regenerated_surfaces"] = []
    migrated.value["validation_receipt_sha256s"] = []
    migrated.value["migration_receipt_sha256"] = _d("mutated-receipt")
    with pytest.raises(CreativeControllerError) as mutated_instance:
        migrate_character_revision(source_revision, target_snapshot_sha256=child.content_snapshot_sha256, from_snapshot=root, to_snapshot=child, change_set=changes, migration_receipt=migrated)
    assert mutated_instance.value.code in {"DCC_MIGRATION_CLOSURE_INVALID", "DCC_MIGRATION_SURFACES_INVALID", "DCC_MIGRATION_VALIDATION_REQUIRED", "DCC_MIGRATION_RECEIPT_HASH_INVALID"}
    assert source_revision == source_before


def test_migration_receipt_fails_closed_without_target_closure_surfaces_or_validation(fixture: dict[str, Any]) -> None:
    root = fixture["snapshot"]
    old_row = next(row for row in root.records if row.choice_id == "path.bastion")
    changed_row = replace(old_row, choice_record_sha256=_d("migration-record-v3"), typed_authority_sha256=_d("migration-typed-v3"))
    child = build_content_snapshot(tuple(changed_row if row.choice_id == old_row.choice_id else row for row in root.records), parent=root, catalogue_schema_versions=dict(root.catalogue_schema_versions), rules_authority_sha256=root.rules_authority_sha256, required_compiler_profile_sha256=root.required_compiler_profile_sha256, dependency_edges=fixture["edges"])
    changes = build_content_change_set(root, child)
    common = {
        "character_id": "character.kai.shadow",
        "from_character_revision_sha256": _d("character-revision-9"),
        "from_snapshot": root,
        "to_snapshot": child,
        "change_set": changes,
        "migration_policy_sha256": _d("migration-policy-2"),
        "migration_intent_sha256": fixture["intent"]["intent_sha256"],
        "selected_ai_identity_sha256": _d("selected-ai-2"),
    }
    with pytest.raises(CreativeControllerError) as no_closure:
        build_migration_receipt(**common, result="MIGRATED")
    assert no_closure.value.code == "DCC_MIGRATION_CLOSURE_INVALID"

    valid_evidence = {
        "closure_handled_choice_ids": changes.value["affected_choice_ids"],
        "preserved_choice_ids": changes.value["affected_choice_ids"],
        "regenerated_surfaces": ["actions", "final_package"],
        "validation_receipt_sha256s": [_d("migration-validation")],
        "to_character_revision_sha256": _d("character-revision-10"),
        "result": "MIGRATED",
    }
    with pytest.raises(CreativeControllerError) as no_target:
        build_migration_receipt(**common, **{key: value for key, value in valid_evidence.items() if key != "to_character_revision_sha256"})
    assert no_target.value.code == "DCC_MIGRATION_SOURCE_MUTATION"
    with pytest.raises(CreativeControllerError) as no_surface:
        build_migration_receipt(**common, **{**valid_evidence, "regenerated_surfaces": ["actions"]})
    assert no_surface.value.code == "DCC_MIGRATION_SURFACES_INVALID"
    with pytest.raises(CreativeControllerError) as no_receipt:
        build_migration_receipt(**common, **{**valid_evidence, "validation_receipt_sha256s": []})
    assert no_receipt.value.code == "DCC_MIGRATION_VALIDATION_REQUIRED"

    blocked_evidence = {**valid_evidence, "to_character_revision_sha256": None, "result": "BLOCKED"}
    with pytest.raises(CreativeControllerError) as blocked:
        build_migration_receipt(**common, **blocked_evidence)
    assert blocked.value.code == "DCC_MIGRATION_EVIDENCE_ON_BLOCKED"


def test_replay_tampering_is_detected_and_request_bytes_are_never_in_events() -> None:
    binding = _event_binding()
    controller = derive_controller_id("run.replay", binding["request_sha256"], _d("replay-controller"), binding["selected_ai_identity_sha256"])
    first = build_event(controller_id=controller, ordinal=1, event_type="INTENT_ACTIVATED", run_id="run.replay", project_id="project.replay", previous_event_sha256=None, subject_sha256=_d("replay-intent"), binding=binding, state_sha256_before=_d("replay-before"), state_sha256_after=_d("replay-after"))
    second = build_event(controller_id=controller, ordinal=2, event_type="MANIFEST_PUBLISHED", run_id="run.replay", project_id="project.replay", previous_event_sha256=first.event_sha256, subject_sha256=_d("replay-manifest"), binding=binding, state_sha256_before=_d("replay-after"), state_sha256_after=_d("replay-final"))
    tampered = second.to_dict()
    tampered["subject_sha256"] = _d("changed-subject")
    with pytest.raises(CreativeControllerError) as error:
        verify_event_chain((first, tampered))
    assert error.value.code in {"DCC_EVENT_ID_INVALID", "DCC_EVENT_HASH_INVALID"}
    assert not event_contains_complete_request_bytes(first.to_dict())
    assert first.to_dict()["binding"]["request_sha256"] == binding["request_sha256"]
    assert "request_bytes" not in first.to_dict()


def test_selected_ai_identity_binds_controller_manifest_events_and_replay(fixture: dict[str, Any]) -> None:
    first = run_shadow_controller(fixture["inputs"])
    alternate = run_shadow_controller(replace(fixture["inputs"], selected_ai_identity_sha256=_d("different-ai")))
    assert first.private_evidence["controller_id"] != alternate.private_evidence["controller_id"]
    assert first.manifest_json != alternate.manifest_json
    assert first.events[0].value["binding"]["selected_ai_identity_sha256"] != alternate.events[0].value["binding"]["selected_ai_identity_sha256"]
    assert first.events[0].event_sha256 != alternate.events[0].event_sha256
    binding = first.artifact.manifest["binding"]
    with pytest.raises(CreativeControllerError) as error:
        build_replay_receipt(first.events, content_snapshot_sha256=binding["content_snapshot_sha256"], request_sha256=binding["request_sha256"], request_resolver_id=binding["request_resolver_id"], request_resolver_binding_sha256=binding["request_resolver_binding_sha256"], selected_ai_identity_sha256=_d("different-ai"), input_binding_sha256=sha256_json(binding), expected_state_sha256=first.events[-1].value["state_sha256_after"], expected_manifest_sha256=first.artifact.manifest_sha256, request_bytes=fixture["request_bytes"], resolved_inputs=fixture["inputs"], expected_manifest_bytes=first.manifest_json.encode())
    assert error.value.code == "DCC_REPLAY_BINDING_INVALID"


def test_legal_plan_proof_and_trust_boundary_fail_closed(fixture: dict[str, Any]) -> None:
    compiled = compile_legal_plans(fixture["slots"], target_cl=15, final_validator=_accept_final_validator)
    plan = compiled.plans[0]
    with pytest.raises(CreativeControllerError) as forged_instance:
        LegalPlan(deepcopy(plan.plan_payload), plan.legal_plan_sha256, deepcopy(plan.proof))
    assert forged_instance.value.code == "DCC_PLAN_TRUST_REQUIRED"
    with pytest.raises(CreativeControllerError) as bare_mapping:
        validate_legal_plan(plan.plan_payload)
    assert bare_mapping.value.code == "DCC_PLAN_TRUST_REQUIRED"
    plan.proof["checks"]["final_factory_validator"] = False
    with pytest.raises(CreativeControllerError) as forged_proof:
        validate_legal_plan(plan)
    assert forged_proof.value.code == "DCC_PLAN_PROOF_INVALID"


def test_snapshot_round_trip_preserves_dependency_graph_and_change_closure(fixture: dict[str, Any]) -> None:
    restored = FactoryContentSnapshot.from_mapping(fixture["snapshot"].to_dict())
    assert restored.dependency_edges == fixture["snapshot"].dependency_edges
    assert restored.dependency_graph_sha256 == fixture["snapshot"].dependency_graph_sha256
    assert affected_dependency_closure(["path.bastion"], restored.dependency_edges) == ("path.bastion", "talent.control", "talent.guard")
    child = build_content_snapshot(tuple(fixture["snapshot"].records), parent=restored, catalogue_schema_versions=dict(restored.catalogue_schema_versions), rules_authority_sha256=restored.rules_authority_sha256, required_compiler_profile_sha256=restored.required_compiler_profile_sha256, dependency_edges=restored.dependency_edges, vocabulary_authority_sha256=restored.vocabulary_authority_sha256)
    assert build_content_change_set(restored, child).value["affected_choice_ids"] == []


def test_supplied_vocabulary_authority_admits_new_valid_tag_without_controller_change(fixture: dict[str, Any]) -> None:
    values = deepcopy(_VOCABULARY_AUTHORITY["vocabularies"])
    values["theme_tags"].append("new_data_admitted_tag")
    authority = build_vocabulary_authority(values)
    unsigned = fixture["semantics"]["path.runner"].to_dict()
    unsigned.pop("semantics_sha256")
    unsigned["vocabulary_authority_sha256"] = authority["authority_sha256"]
    unsigned["theme_tags"] = ["new_data_admitted_tag"]
    admitted = build_choice_semantics(unsigned)
    validate_semantics_set({"path.runner": admitted}, required_choice_ids=["path.runner"], vocabulary_authority=authority)
    assert admitted.value["theme_tags"] == ["new_data_admitted_tag"]


@pytest.mark.parametrize(
    ("field", "fabricated_value"),
    [
        ("title", "Guaranteed time-stop route"),
        ("identity", "This route grants an invented mechanical identity."),
        ("why_it_fits", "Always wins every encounter without a tradeoff."),
        ("combat_role", "Unlisted absolute-damage role"),
        ("signature_capabilities", ["unverified_time_stop"]),
        ("important_synergies", ["guaranteed_unlisted_combo"]),
        ("meaningful_tradeoffs", ["no_downside"]),
        ("progression_consequences", ["immediate_unbounded_mastery"]),
        ("complexity", "simple"),
        ("visual_narrative_cues", ["the character rewrites the rules"]),
        ("distinctness_cue", "Invented mechanics distinguish this route."),
    ],
)
def test_nonempty_card_metadata_is_rejected_for_every_public_card_field(
    fixture: dict[str, Any], field: str, fabricated_value: Any
) -> None:
    plan = compile_legal_plans(fixture["slots"], target_cl=15, final_validator=_accept_final_validator).plans[0]
    inputs = replace(
        fixture["inputs"],
        card_metadata_by_plan={plan.legal_plan_sha256: {field: fabricated_value}},
    )
    with pytest.raises(CreativeControllerError) as error:
        run_shadow_controller(inputs)
    assert error.value.code == "DCC_CARD_METADATA_UNSUPPORTED"


def test_capped_frontier_has_reachable_nonoverlapping_bound_continuations(fixture: dict[str, Any]) -> None:
    result = run_shadow_controller(fixture["inputs"])
    pages = [result.artifact]
    while pages[-1].manifest["page"]["more_available"]:
        pages.append(continue_manifest(pages[-1], pages[-1].manifest["page"]["continuation_id"]))
    assert len(pages) == 2
    seen: list[str] = []
    for page in pages:
        ids = [option["option_id"] for option in page.manifest["options"]]
        assert not set(seen) & set(ids)
        seen.extend(ids)
    assert len(seen) == len(set(seen)) == 6
    with pytest.raises(CreativeControllerError) as error:
        continue_manifest(result.artifact, "dcc.more." + "0" * 24)
    assert error.value.code == "DCC_CONTINUATION_UNKNOWN"


def test_replay_recomputes_and_rejects_valid_but_wrong_event_subject(fixture: dict[str, Any]) -> None:
    result = run_shadow_controller(fixture["inputs"])
    first = result.events[0]
    binding = first.value["binding"]
    wrong_first = build_event(controller_id=result.private_evidence["controller_id"], ordinal=1, event_type="INTENT_ACTIVATED", run_id=fixture["inputs"].run_id, project_id=fixture["inputs"].project_id, previous_event_sha256=None, subject_sha256=_d("wrong-intent"), binding=binding, state_sha256_before=first.value["state_sha256_before"], state_sha256_after=first.value["state_sha256_after"])
    wrong_second = build_event(controller_id=result.private_evidence["controller_id"], ordinal=2, event_type="MANIFEST_PUBLISHED", run_id=fixture["inputs"].run_id, project_id=fixture["inputs"].project_id, previous_event_sha256=wrong_first.event_sha256, subject_sha256=result.artifact.manifest_sha256, binding=binding, state_sha256_before=first.value["state_sha256_after"], state_sha256_after=result.events[-1].value["state_sha256_after"])
    with pytest.raises(CreativeControllerError) as error:
        build_replay_receipt((wrong_first, wrong_second), content_snapshot_sha256=binding["content_snapshot_sha256"], request_sha256=binding["request_sha256"], request_resolver_id=binding["request_resolver_id"], request_resolver_binding_sha256=binding["request_resolver_binding_sha256"], selected_ai_identity_sha256=binding["selected_ai_identity_sha256"], input_binding_sha256=sha256_json(result.artifact.manifest["binding"]), expected_state_sha256=result.events[-1].value["state_sha256_after"], expected_manifest_sha256=result.artifact.manifest_sha256, request_bytes=fixture["request_bytes"], resolved_inputs=fixture["inputs"], expected_manifest_bytes=result.manifest_json.encode())
    assert error.value.code == "DCC_REPLAY_EVENT_SUBJECT_INVALID"
