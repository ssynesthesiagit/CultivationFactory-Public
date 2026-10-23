from __future__ import annotations

from copy import deepcopy

import pytest

from app.core import FoundryError, sha256_json
from catalog_choice_authority import DELEGATED_FINAL_CATALOG_GRANT_FIELD
from character_creation.delegated_choice_authority import (
    build_delegated_choice_envelope,
    final_plan_sha256,
    _resolved_slot_values,
    _owner_user_locks,
    catalog_stage2_selections,
    validate_delegated_choice_plan,
)
from character_creation.response_materialization import normalize_selection_intent
from path_method_authority import CANONICAL_PATH_IDS


def _project(path_ids: list[str] | None = None) -> dict:
    locks = [{"field": "target_cl", "value": 1, "source": "rec1-p1ar2-test"}]
    if path_ids:
        locks.append({
            "field": "character_sheet.locked_choices",
            "value": {"path_choice": list(path_ids)},
            "source": "rec1-p1a-test",
        })
    return {
        "project_id": "REC1-P1A-PROJECT",
        "revision": 4,
        "user_locks": locks,
        "content_lock": {"catalog_build_id": "CATALOG-4", "lock_hash": "CONTENT-4"},
    }


def _choice(choice_id: str, **fields) -> dict:
    return {"choice_id": choice_id, "initial_creation_selectable": True, "availability": {"available": True}, **fields}


def _prompt() -> dict:
    body = CANONICAL_PATH_IDS[0]
    paths = list(CANONICAL_PATH_IDS)
    methods = {
        "METHOD-ALL": _choice("METHOD-ALL", related_choice_ids=paths, compatible_foundation_ids=["FOUNDATION-ALL"]),
        "METHOD-BODY": _choice("METHOD-BODY", related_choice_ids=[body], compatible_foundation_ids=["FOUNDATION-BODY"]),
    }
    foundations = {
        "FOUNDATION-ALL": _choice("FOUNDATION-ALL", compatible_method_ids=["METHOD-ALL"], compatible_path_ids=paths),
        "FOUNDATION-BODY": _choice("FOUNDATION-BODY", compatible_method_ids=["METHOD-BODY"], compatible_path_ids=[body]),
    }
    return {
        "prompt_id": "STAGE1-PROMPT-4",
        "prompt_sha256": "STAGE1-HASH-4",
        "envelope": {
            "decision_slots": [
                {"slot_id": "path_choice", "min_selections": 1, "max_selections": 3, "allow_none": False, "choices": [_choice(path_id) for path_id in paths]},
                {"slot_id": "method_choice", "min_selections": 0, "max_selections": 1, "allow_none": True, "choices": list(methods.values())},
                {"slot_id": "foundation_choice", "min_selections": 0, "max_selections": 1, "allow_none": True, "choices": list(foundations.values())},
                {"slot_id": "sphere_priorities", "min_selections": 0, "max_selections": 1, "allow_none": True, "choices": [_choice("SPHERE-FIRE"), _choice("SPHERE-LOCKED")],},
            ],
            "path_method_authority": {
                "all_path_ids": paths,
                "method_granted_path_ids": {"METHOD-ALL": paths, "METHOD-BODY": [body]},
            },
        },
    }


def _run(project: dict, envelope: dict) -> dict:
    return {
        "project_id": project["project_id"],
        "starting_revision": project["revision"],
        "execution_mode": "MANUAL_CHAT",
        "idempotency_key": "REC1-P1A-ONE-SHOT",
        "request": {"request_sha256": "REQUEST-4", "delegated_choice_envelope": envelope},
        "response": {"response_sha256": "RESPONSE-4"},
    }


def _plan(*, paths: list[str] | None = None, method: str | None = "METHOD-ALL", foundation: str | None = None, sphere: list[str] | None = None) -> dict:
    by_slot = {}
    if paths is not None:
        by_slot["path_choice"] = list(paths)
    if method is not None:
        by_slot["method_choice"] = [method]
    if foundation is not None:
        by_slot["foundation_choice"] = [foundation]
    if sphere is not None:
        by_slot["sphere_priorities"] = list(sphere)
    return {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "target_cl": 1,
        "delegated_choice_selections": {"by_slot": by_slot},
        "stage2_proposal": {"target_cl": 1, "choices": [], "planner_rationale": "Prose cannot grant a choice."},
        # Delegated-name responses are now positive delegation: use a valid
        # fixture name by default and test the missing-name rejection explicitly
        # below.
        "owner_descriptive_fields": {"identity": {"name": "Delegated Fixture Name"}, "concept": ""},
    }


def _authority(path_ids: list[str] | None = None):
    project = _project(path_ids)
    envelope = build_delegated_choice_envelope(
        project,
        _prompt(),
        execution_mode="MANUAL_CHAT",
        idempotency_key="REC1-P1A-ONE-SHOT",
    )
    assert envelope is not None
    return project, envelope, _run(project, envelope)


def _raises(code: str, plan: dict, project: dict | None = None, envelope: dict | None = None):
    project, fresh_envelope, run = _authority() if project is None else (project, envelope, _run(project, envelope))
    with pytest.raises(FoundryError) as exc:
        validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert exc.value.code == code


def test_zero_owner_locks_offer_all_paths_and_ai_method_grants_are_authoritative():
    project, envelope, run = _authority()
    assert envelope["frozen_owner_target_cl"]["value"] == 1
    assert envelope["frozen_owner_target_cl"]["delegated"] is False
    assert envelope["owner_locks"]["by_slot"]["path_choice"] == []
    assert envelope["owner_locks"]["zero_owner_path_locks_are_legal"] is True
    assert envelope["offered_choice_ids_by_slot"]["path_choice"] == list(CANONICAL_PATH_IDS)
    assert envelope["allowed_choice_ids_by_slot"]["path_choice"] == list(CANONICAL_PATH_IDS)
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-FIRE"])
    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert final is not None
    assert final["target_cl"] == 1
    assert final["target_cl_authority"]["value"] == 1
    resolution = final["resolution"]
    assert resolution["actual_advancing_path_ids"] == list(CANONICAL_PATH_IDS)
    assert resolution["actual_advancing_path_ids"] == resolution["method_granted_path_ids"]
    assert resolution["selected_choices_by_slot"]["sphere_priorities"] == ["SPHERE-FIRE"]
    assert all(row["provenance"] == "AI" for row in resolution["provenance"] if row["slot_id"] == "path_choice")
    assert resolution["descriptive_fields"] == {"name": "Delegated Fixture Name", "concept": None}
    assert final_plan_sha256(final) == final["final_plan_sha256"]


def test_server_derived_final_grant_lock_is_excluded_from_owner_lock_binding():
    project = _project()
    project["user_locks"].append({
        "field": DELEGATED_FINAL_CATALOG_GRANT_FIELD,
        "value": {"schema": "TianxiaFactory.CanonicalGrantPlan.v1", "records": []},
        "source": "server-derived",
    })
    prompt = _prompt()
    envelope = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="REC1-P1A-ONE-SHOT",
    )
    assert envelope is not None
    repeat = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="REC1-P1A-ONE-SHOT",
    )
    assert repeat == envelope
    assert envelope["owner_locks"]["lock_sha256"] == sha256_json(_owner_user_locks(project))
    assert envelope["owner_locks"]["lock_sha256"] != sha256_json(project["user_locks"])

    run = _run(project, envelope)
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-FIRE"])
    validated = validate_delegated_choice_plan(
        run,
        project,
        plan,
        response_sha256="RESPONSE-4",
    )
    assert validated["target_cl"] == 1


def test_genuine_owner_lock_change_still_invalidates_frozen_envelope():
    project, envelope, run = _authority()
    project["user_locks"].append({
        "field": "owner.review_note",
        "value": "changed after request freeze",
        "source": "owner",
    })
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-FIRE"])
    with pytest.raises(FoundryError) as exc:
        validate_delegated_choice_plan(
            run,
            project,
            plan,
            response_sha256="RESPONSE-4",
        )
    assert exc.value.code == "CG1_DELEGATED_OWNER_LOCKS_CHANGED"


def test_provider_required_planning_slots_control_only_planning_owner_provenance():
    project, envelope, _run_unused = _authority()
    assert "sphere_priorities" in envelope["unresolved_owner_decisions"]
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=None)

    def unresolved_sphere(required_slots_marker):
        case_envelope = deepcopy(envelope)
        final = validate_delegated_choice_plan(
            _run(project, case_envelope),
            project,
            deepcopy(plan),
            response_sha256="RESPONSE-4",
            provider_required_planning_slot_ids=required_slots_marker,
        )
        return [
            row for row in final["resolution"]["provenance"]
            if row.get("slot_id") == "sphere_priorities" and row.get("status") == "unresolved"
        ]

    assert unresolved_sphere(None)  # Absent marker preserves legacy behavior.
    assert unresolved_sphere(["sphere_priorities"])
    assert unresolved_sphere([]) == []


def test_blank_delegated_name_and_concept_can_be_ai_proposed_for_owner_review():
    project, envelope, run = _authority()
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    plan["owner_descriptive_fields"] = {
        "identity": {"name": "玄火·云舟"},
        "concept": "A wandering cultivator who turns disciplined fire into patient protection.",
    }
    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert final["resolution"]["descriptive_fields"] == {
        "name": "玄火·云舟",
        "concept": "A wandering cultivator who turns disciplined fire into patient protection.",
    }
    assert any(
        row["slot_id"] == "identity.name" and row["provenance"] == "needs_owner"
        for row in final["resolution"]["provenance"]
    ) is False


def test_delegated_name_is_positive_required_and_missing_name_fails_closed():
    project, envelope, run = _authority()
    contract = envelope["delegated_name_contract"]
    assert contract["state"] == "delegated"
    assert contract["required"] is True
    assert contract["nonblank"] is True
    assert contract["positive_delegation"] is True
    missing = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    missing["owner_descriptive_fields"] = {"identity": {"name": "   "}, "concept": "A valid concept"}
    with pytest.raises(FoundryError) as exc:
        validate_delegated_choice_plan(run, project, missing, response_sha256="RESPONSE-4")
    assert exc.value.code == "CG1_DELEGATED_NAME_REQUIRED"


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_all_owner_path_lock_counts_are_explicit_and_final_no_path_is_rejected(count: int):
    locked = list(CANONICAL_PATH_IDS[:count])
    project, envelope, run = _authority(locked)
    assert len(envelope["owner_locks"]["by_slot"]["path_choice"]) == count
    if count == 0:
        assert envelope["owner_locks"]["by_slot"]["path_choice"] == []
        with pytest.raises(FoundryError) as exc:
            validate_delegated_choice_plan(run, project, _plan(paths=None, method=None), response_sha256="RESPONSE-4")
        assert exc.value.code == "CG1_DELEGATED_PATH_REQUIRED"
        return
    final = validate_delegated_choice_plan(run, project, _plan(paths=locked, method="METHOD-ALL"), response_sha256="RESPONSE-4")
    assert final["resolution"]["selected_path_ids"] == locked
    assert set(locked).issubset(set(final["resolution"]["actual_advancing_path_ids"]))
    assert all(row["provenance"] == "owner" for row in final["resolution"]["provenance"] if row["slot_id"] == "path_choice" and row["choice_id"] in locked)


def test_method_granted_extras_are_disclosed_and_ai_can_select_unspecified_legal_choices():
    project, envelope, run = _authority([CANONICAL_PATH_IDS[0]])
    final = validate_delegated_choice_plan(run, project, _plan(paths=[CANONICAL_PATH_IDS[0]], method="METHOD-ALL", sphere=["SPHERE-FIRE"]), response_sha256="RESPONSE-4")
    assert final["resolution"]["extra_method_granted_path_ids"] == list(CANONICAL_PATH_IDS[1:])
    assert {row["choice_id"] for row in final["resolution"]["provenance"] if row["provenance"] == "automatic"} == set(CANONICAL_PATH_IDS[1:])
    assert any(row["choice_id"] == "SPHERE-FIRE" and row["provenance"] == "AI" for row in final["resolution"]["provenance"])
    assert final["resolution"]["planner_prose_authority"] is False


def test_out_of_envelope_duplicate_count_conflict_and_method_incompatibility_fail_closed():
    project, envelope, run = _authority()
    _raises("CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE", _plan(paths=["PATH-NOT-OFFERED"], method="METHOD-ALL"), project, envelope)
    out_of_envelope_stage2 = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    out_of_envelope_stage2["stage2_proposal"]["choices"] = [{
        "kind": "ai_bootstrap_sphere_acquisition",
        "record_id": "SPHERE-NOT-OFFERED",
    }]
    _raises("CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE", out_of_envelope_stage2, project, envelope)
    _raises("CG1_DELEGATED_DUPLICATE_CHOICE", _plan(paths=[CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[0]], method="METHOD-ALL"), project, envelope)
    _raises("CG1_DELEGATED_CHOICE_COUNT_INVALID", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-FIRE", "SPHERE-LOCKED"]), project, envelope)
    too_many_methods = _plan(paths=list(CANONICAL_PATH_IDS), method=None)
    too_many_methods["delegated_choice_selections"]["by_slot"]["method_choice"] = ["METHOD-ALL", "METHOD-BODY"]
    _raises("CG1_DELEGATED_CHOICE_COUNT_INVALID", too_many_methods, project, envelope)
    _raises("CG1_METHOD_PATH_INCOMPATIBLE", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-BODY"), project, envelope)


def test_method_foundation_prerequisite_and_conflicting_authority_fail_closed():
    project, envelope, run = _authority()
    _raises("CG1_METHOD_FOUNDATION_INCOMPATIBLE", _plan(paths=[CANONICAL_PATH_IDS[0]], method="METHOD-ALL", foundation="FOUNDATION-BODY"), project, envelope)
    prereq_envelope = deepcopy(envelope)
    prereq_envelope["choices_by_slot"]["sphere_priorities"]["SPHERE-LOCKED"]["prerequisites"] = [{"operator": "requires", "target_id": "SPHERE-MISSING"}]
    prereq_envelope["envelope_sha256"] = __import__("app.core", fromlist=["sha256_json"]).sha256_json({k: v for k, v in prereq_envelope.items() if k != "envelope_sha256"})
    prereq_run = _run(project, prereq_envelope)
    _raises("CG1_DELEGATED_PREREQUISITE_UNMET", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-LOCKED"]), project, prereq_envelope)
    conflict = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    conflict["stage2_proposal"]["catalog_priority_order"] = {"path_ids": [CANONICAL_PATH_IDS[0]]}
    _raises("CG1_DELEGATED_AUTHORITY_CONFLICT", conflict, project, envelope)


def test_set_shaped_subpath_materialization_accepts_reordering_but_not_membership_changes():
    body_path, qi_path, spirit_path = CANONICAL_PATH_IDS
    body_subpath = "SUBPATH-BODY"
    qi_subpath = "SUBPATH-QI"
    spirit_subpath = "SUBPATH-SPIRIT"
    prompt = deepcopy(_prompt())
    prompt["envelope"]["decision_slots"].append({
        "slot_id": "subpath_choice",
        "min_selections": 0,
        "max_selections": 3,
        "allow_none": True,
        "choices": [
            _choice(body_subpath, owning_path_id=body_path, owning_path_choice_ids=[body_path]),
            _choice(qi_subpath, owning_path_id=qi_path, owning_path_choice_ids=[qi_path]),
            _choice(spirit_subpath, owning_path_id=spirit_path, owning_path_choice_ids=[spirit_path]),
        ],
    })
    project = _project()
    envelope = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="REC1-P1A-ONE-SHOT",
    )
    assert envelope is not None
    run = _run(project, envelope)
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    plan["delegated_choice_selections"]["by_slot"]["subpath_choice"] = [body_subpath, qi_subpath]
    plan["stage2_proposal"]["choices"] = [
        {"kind": "subpath_acquisition", "record_id": qi_subpath},
        {"kind": "subpath_acquisition", "record_id": body_subpath},
    ]

    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert final["resolution"]["selected_choices_by_slot"]["subpath_choice"] == [body_subpath, qi_subpath]

    changed = deepcopy(plan)
    changed["stage2_proposal"]["choices"][1]["record_id"] = spirit_subpath
    _raises("CG1_DELEGATED_AUTHORITY_CONFLICT", changed, project, envelope)


def _reconciliation_envelope(*slot_values: dict[str, list[str]]) -> dict:
    allowed = {slot_id: list(choice_ids) for values in slot_values for slot_id, choice_ids in values.items()}
    return {
        "allowed_choice_ids_by_slot": allowed,
        "selection_limits_by_slot": {
            slot_id: {"final_min": 1, "final_max": 1}
            for slot_id in allowed
        },
        "choices_by_slot": {
            slot_id: {
                choice_id: {
                    "choice_id": choice_id,
                    "availability": {"available": True},
                }
                for choice_id in choice_ids
            }
            for slot_id, choice_ids in allowed.items()
        },
    }


def test_background_route_consequence_is_not_reconciled_as_delegated_conflict():
    background_id = "tianxia.background.abandoned_orphan"
    background_sphere_id = "tianxia.background_sphere.scoundrel"
    route_sphere_id = "tianxia.sphere.scoundrel"
    envelope = _reconciliation_envelope(
        {"background_choice": [background_id]},
        {"background_sphere_choice": [background_sphere_id]},
    )
    plan = {
        "canonical_selection_intent": {
            "selected_by_slot": {
                "background_choice": [background_id],
                "background_sphere_choice": [background_sphere_id],
            },
            "sources_by_slot": {},
            "planning_preferences_by_slot": {},
        },
        "stage2_proposal": {
            "choices": [
                {"kind": "background_acquisition", "record_id": background_id},
                {"kind": "background_sphere_acquisition", "record_id": background_sphere_id},
                # This is a server-derived route consequence, not a second
                # delegated Background Sphere choice.
                {"kind": "background_sphere_acquisition", "record_id": route_sphere_id},
            ],
        },
    }

    resolved, _ = _resolved_slot_values(envelope, plan)

    assert resolved["background_sphere_choice"] == [background_sphere_id]
    ledger = catalog_stage2_selections(plan)
    assert ledger["background_sphere_ids"] == [background_sphere_id, route_sphere_id]


@pytest.mark.parametrize("slot,acquisition,lifecycle,bucket", [
    ("method_choice", "method_acquisition", ["method_activation"], "method_ids"),
    ("foundation_choice", "foundation_acquisition", ["foundation_expression", "foundation_stage"], "foundation_ids"),
])
def test_lifecycle_operations_do_not_count_as_additional_acquisitions(slot, acquisition, lifecycle, bucket):
    identity = "METHOD-083" if slot == "method_choice" else "FOUNDATION-ALL"
    envelope = _reconciliation_envelope({slot: [identity]})
    plan = {
        "canonical_selection_intent": {"selected_by_slot": {slot: [identity]}},
        "stage2_proposal": {"choices": [
            {"kind": acquisition, "record_id": identity},
            *[{"kind": kind, "record_id": identity} for kind in lifecycle],
        ]},
    }
    resolved, _ = _resolved_slot_values(envelope, plan)
    assert resolved[slot] == [identity]
    assert catalog_stage2_selections(plan)[bucket] == [identity]
    # Lifecycle operations do not acquire anything by themselves. Their
    # ownership and order are independently checked by the causal engine.
    plan["stage2_proposal"]["choices"] = plan["stage2_proposal"]["choices"][1:]
    assert catalog_stage2_selections(plan)[bucket] == []


@pytest.mark.parametrize("slot,acquisition", [
    ("method_choice", "method_acquisition"),
    ("foundation_choice", "foundation_acquisition"),
])
def test_duplicate_acquisitions_remain_semantic_authority_conflicts(slot, acquisition):
    identity = "METHOD-083" if slot == "method_choice" else "FOUNDATION-ALL"
    envelope = _reconciliation_envelope({slot: [identity]})
    plan = {
        "canonical_selection_intent": {"selected_by_slot": {slot: [identity]}},
        "stage2_proposal": {"choices": [{"kind": acquisition, "record_id": identity}] * 2},
    }
    with pytest.raises(FoundryError) as exc:
        _resolved_slot_values(envelope, plan)
    assert exc.value.code == "CG1_DELEGATED_AUTHORITY_CONFLICT"
    assert exc.value.details["stage2_choice_ids"] == [identity, identity]


def test_non_route_stage2_mismatch_still_fails_closed():
    selected_path = "tianxia.path.qi_cultivation"
    other_path = "tianxia.path.body_refining"
    envelope = _reconciliation_envelope(
        {"path_choice": [selected_path, other_path]},
    )
    plan = {
        "canonical_selection_intent": {
            "selected_by_slot": {"path_choice": [selected_path]},
            "sources_by_slot": {},
            "planning_preferences_by_slot": {},
        },
        "stage2_proposal": {
            "choices": [
                {"kind": "path_acquisition", "record_id": other_path},
            ],
        },
    }

    with pytest.raises(FoundryError) as exc:
        _resolved_slot_values(envelope, plan)
    assert exc.value.code == "CG1_DELEGATED_AUTHORITY_CONFLICT"
    assert exc.value.details["slot_id"] == "path_choice"


def test_historical_selection_intent_normalizes_explicit_acquisition_list():
    project, envelope, run = _authority([CANONICAL_PATH_IDS[0]])
    pair = {
        "kind": "__free_sphere_talent_pair__",
        "sphere_id": "SPHERE-FIRE",
        "record_id": "TALENT-FLAME",
    }
    plan = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "path_choice": [CANONICAL_PATH_IDS[0]],
                "method_choice": ["METHOD-ALL"],
            },
        },
        "acquisition_intent": [pair],
        "owner_descriptive_fields": {"identity": {"name": "Intent Test"}, "concept": "Bounded"},
        "bounded_choices": {"ability_scores": {"STR": 8, "DEX": 15, "CON": 12, "INT": 10, "WIS": 10, "CHA": 10}},
    }
    intent = normalize_selection_intent(
        plan,
        request_sha256=run["request"]["request_sha256"],
        delegated_envelope=envelope,
        project=project,
        target_cl=1,
    )
    document = intent.as_dict()
    assert document["acquisition_intent"] == {
        "sphere_free_talent_pairs": [{
            "sphere_id": "SPHERE-FIRE",
            "talent_id": "TALENT-FLAME",
        }],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert "sphere_priorities" not in document["selected_by_slot"]


def test_stale_or_tampered_envelope_and_owner_lock_changes_are_rejected():
    project, envelope, run = _authority()
    tampered = deepcopy(envelope)
    tampered["allowed_choice_ids_by_slot"]["path_choice"] = list(CANONICAL_PATH_IDS[:1])
    _raises("CG1_DELEGATED_ENVELOPE_TAMPERED", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL"), project, tampered)
    stale_project = deepcopy(project)
    stale_project["revision"] = 5
    with pytest.raises(FoundryError) as exc:
        validate_delegated_choice_plan(_run(stale_project, envelope), stale_project, _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL"), response_sha256="RESPONSE-4")
    assert exc.value.code == "CG1_DELEGATED_ENVELOPE_STALE"


def test_foundation_below_realm_entry_cl_is_typed_none_not_an_owner_decision():
    # CL 1: no Foundation exists before the Foundation Realm, so the absent
    # choice is a legal typed none and finalization must not wait on it.
    project, envelope, run = _authority()
    assert "foundation_choice" in envelope["unresolved_owner_decisions"]
    final = validate_delegated_choice_plan(run, project, _plan(paths=[CANONICAL_PATH_IDS[0]]), response_sha256="RESPONSE-4")
    foundation_rows = [row for row in final["resolution"]["provenance"] if row["slot_id"] == "foundation_choice" and row["choice_id"] is None]
    assert foundation_rows == [{
        "slot_id": "foundation_choice", "choice_id": None, "provenance": "typed_none",
        "status": "deferred_or_typed_none", "reason": "foundation_not_available_below_realm_entry_cl",
    }]
    assert not [row for row in final["unresolved"] if row["slot_id"] == "foundation_choice"]

    # CL 5: the same unselected slot is a real owner decision.
    project = _project()
    project["user_locks"][0]["value"] = 5
    envelope = build_delegated_choice_envelope(project, _prompt(), execution_mode="MANUAL_CHAT", idempotency_key="REC1-P1A-ONE-SHOT")
    run = _run(project, envelope)
    plan = _plan(paths=[CANONICAL_PATH_IDS[0]])
    plan["target_cl"] = 5
    plan["stage2_proposal"]["target_cl"] = 5
    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert [row for row in final["unresolved"] if row["slot_id"] == "foundation_choice"] == [
        {"slot_id": "foundation_choice", "choice_id": None, "provenance": "needs_owner", "status": "unresolved"}
    ]


def _prompt_with_method_access(*, restricted_has_route: bool) -> dict:
    prompt = _prompt()
    body = CANONICAL_PATH_IDS[0]
    slots = {slot["slot_id"]: slot for slot in prompt["envelope"]["decision_slots"]}
    slots["method_choice"]["choices"] = [
        # Production Stage 1 rows carry no selectability flag; the access map does.
        _choice("METHOD-RESTRICTED", related_choice_ids=[body], compatible_foundation_ids=["FOUNDATION-BODY"]),
    ]
    prompt["envelope"]["path_method_authority"] = {
        "all_path_ids": list(CANONICAL_PATH_IDS),
        "compatible_method_ids": ["METHOD-RESTRICTED"],
        "method_granted_path_ids": {"METHOD-RESTRICTED": [body]},
        "method_access_by_id": {
            "METHOD-RESTRICTED": {
                "initial_creation_selectable": False,
                "access_tier": "SECT_TEACHER_LINEAGE_OR_SCRIPTURE",
                "access_required": True,
                "owner_route_options": (
                    [
                        {"choice_id": "route-personal-teacher", "label": "Personal teacher", "typed_route": "PERSONAL_TEACHER", "source_route_sha256": "c" * 64, "requires_explanation": False},
                        {"choice_id": "route-custom", "label": "Custom", "typed_route": "CUSTOM_DOCUMENTED_ROUTE", "source_route_sha256": "d" * 64, "requires_explanation": True},
                    ]
                    if restricted_has_route
                    else [{"choice_id": "route-custom", "label": "Custom", "typed_route": "CUSTOM_DOCUMENTED_ROUTE", "source_route_sha256": "d" * 64, "requires_explanation": True}]
                ),
            }
        },
    }
    return prompt


def _method_access_snapshot():
    from character_creation import compiler_selection_authority as compiler_authority

    def records(ids):
        return {"records": {choice_id: {"choice_id": choice_id, "canonical_name": choice_id, "selectable": True} for choice_id in ids}}

    return compiler_authority.CompilerSelectionAuthoritySnapshot(
        {
            "authority_sha256": "a" * 64,
            "content": {"content_lock_hash": "CONTENT-4"},
            "path_choice": {},
            "method_choice": records(["METHOD-RESTRICTED"]),
            "foundation_choice": records(["FOUNDATION-ALL", "FOUNDATION-BODY"]),
        },
        _token=compiler_authority._SERVER_SNAPSHOT_TOKEN,
    )


def _build_with_snapshot(monkeypatch, project, prompt):
    from character_creation import delegated_choice_authority as delegated_authority

    monkeypatch.setattr(delegated_authority, "verify_compiler_selection_authority", lambda authority, *, expected_content_lock: authority)
    return build_delegated_choice_envelope(project, prompt, execution_mode="MANUAL_CHAT", idempotency_key="REC1-P1A-ONE-SHOT", compiler_selection_authority=_method_access_snapshot())


def test_attained_character_cannot_defer_method_even_with_owner_locked_paths():
    # Rulebook line 11: Path 0 -> 1 is a Method initiation.  The fixture's
    # target CL is 1 with owner-locked Paths; deferring used to be accepted.
    project, envelope, run = _authority([CANONICAL_PATH_IDS[0]])
    with pytest.raises(FoundryError) as excinfo:
        validate_delegated_choice_plan(run, project, _plan(paths=[CANONICAL_PATH_IDS[0]], method=None), response_sha256="RESPONSE-4")
    assert excinfo.value.code == "CG1_DELEGATED_METHOD_REQUIRED"
    assert excinfo.value.details["target_cl"] == 1


def test_restricted_method_with_published_route_is_selectable_through_a_constructed_route(monkeypatch):
    project = _project([CANONICAL_PATH_IDS[0]])
    envelope = _build_with_snapshot(monkeypatch, project, _prompt_with_method_access(restricted_has_route=True))
    assert envelope["allowed_choice_ids_by_slot"]["method_choice"] == ["METHOD-RESTRICTED"]
    route = envelope["path_method_authority"]["method_access_by_id"]["METHOD-RESTRICTED"]["constructed_access_route"]
    # The first non-custom published route, in registry order, source-bound.
    assert route == {"choice_id": "route-personal-teacher", "typed_route": "PERSONAL_TEACHER", "label": "Personal teacher", "source_route_sha256": "c" * 64, "origin": "factory_constructed"}
    run = _run(project, envelope)
    binding = envelope["binding"]
    # A compiler-gated run must be bound to its persisted Stage 1 prompt and request.
    run["request"].update({
        "stage1_prompt": {"prompt_id": binding["stage1_prompt_id"], "prompt_sha256": binding["stage1_prompt_sha256"]},
        "project_id": binding["project_id"],
        "project_revision": binding["project_revision"],
        "content_lock_hash": binding["content_lock_hash"],
    })
    plan = _plan(paths=[CANONICAL_PATH_IDS[0]], method="METHOD-RESTRICTED")
    plan["owner_descriptive_fields"]["identity"]["title"] = "Furnace Disciple"
    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert final["resolution"]["method_id"] == "METHOD-RESTRICTED"
    assert final["resolution"]["deferred_method"] is False


def test_request_fails_closed_when_no_method_can_be_selected_for_attained_paths(monkeypatch):
    project = _project([CANONICAL_PATH_IDS[0]])
    with pytest.raises(FoundryError) as excinfo:
        _build_with_snapshot(monkeypatch, project, _prompt_with_method_access(restricted_has_route=False))
    assert excinfo.value.code == "CG1_METHOD_REQUIRED_NONE_SELECTABLE"
    assert excinfo.value.details["reasons_by_method_id"] == {"METHOD-RESTRICTED": ["no_published_learning_route"]}
    assert excinfo.value.details["locked_path_ids"] == [CANONICAL_PATH_IDS[0]]
