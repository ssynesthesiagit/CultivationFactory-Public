"""Finite Forge choices must survive the actual preferred response pipeline."""
from copy import deepcopy
import json

import pytest

from app.core import FoundryError
from character_creation.constructed_arts.explicit_forging import explicit_forging_contract, validate_explicit_concepts
from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
from character_creation.creative_controller.linear_walk import commit_option, _step_descriptors
from character_creation.creative_controller.linear_assembly import build_response
from character_creation.response_materialization import normalize_selection_intent
from character_creation.service import CharacterCreationExecutionService


def _case(cl=20):
    envelope = {"explicit_forging_contract": explicit_forging_contract(), "frozen_owner_target_cl": cl}
    request = {"request_sha256": "a" * 64, "target_cl": cl, "delegated_choice_envelope": envelope}
    state = CommittedState.empty().with_identity("Lin Qilin", "Dreamforger")
    state = state.with_ordinary(5, "TAL_AIR_DOWNBURST_SEAL").with_ordinary(15, "TAL_AIR_HEAVEN_SPLITTING_GALE")
    return request, envelope, state


def test_forge_menu_choices_roundtrip_into_canonical_intent():
    request, envelope, state = _case()
    for index, design in enumerate(("air.downburst.ignore_resistance", "air.gale.ignore_resistance"), 1):
        menu = build_step_menu(request, envelope, state, step_id=f"forged_design:{index}")
        option = next(row for row in menu.options if row.choice_ids == (design,))
        state = commit_option(menu, option.option_id, state)
    menu = build_step_menu(request, envelope, state, step_id="forged_design:3")
    assert len(menu.options) == 1 and menu.options[0].kind == "none"
    state = commit_option(menu, menu.options[0].option_id, state)
    raw = build_response(request, state)
    parsed, _ = CharacterCreationExecutionService._parse_plan(raw, expected_request_sha256=request["request_sha256"], explicit_forging_active=True)
    concepts = parsed["acquisition_intent"]["forged_technique_concepts"]
    assert len(concepts) == 2 and all(row["generator_version"] == 3 for row in concepts)
    intent = normalize_selection_intent(parsed, request_sha256=request["request_sha256"], delegated_envelope=envelope, project={}, target_cl=20).as_dict()
    assert intent["acquisition_intent"]["forged_technique_concepts"] == concepts
    assert not any(key.startswith("forged") for key in parsed["selection_intent"]["by_slot"])
    assert not any(key.startswith("forged") for key in parsed["bounded_choices"])
    with pytest.raises(FoundryError):
        CharacterCreationExecutionService._parse_plan(raw, expected_request_sha256=request["request_sha256"])


def test_forge_selection_cannot_be_silently_omitted_or_filled():
    request, envelope, state = _case()
    with pytest.raises(FoundryError) as error:
        build_response(request, state)
    assert error.value.code == "DCC_LINEAR_FORGED_DESIGN_INCOMPLETE"
    menu = build_step_menu(request, envelope, state, step_id="forged_design:1")
    stop = next(row for row in menu.options if row.kind == "none")
    state = commit_option(menu, stop.option_id, state)
    assert json.loads(build_response(request, state))["acquisition_intent"]["forged_technique_concepts"] == []
    service = object.__new__(CharacterCreationExecutionService)
    assert service._forged_technique_constructions({}, {}, {"acquisition_intent": {"forged_technique_concepts": []}}, [], {}, 20, intent_hash="a" * 64) == []
    assert build_step_menu(request, envelope, state, step_id="forged_design:1") is None
    assert not any(row[1] == "forged_design" for row in _step_descriptors(request, envelope, state))


@pytest.mark.parametrize("cl,known,expected", [(5, True, 0), (10, True, 1), (20, True, 2), (20, False, 0)])
def test_forge_menu_requires_actual_held_talent_and_realm(cl, known, expected):
    request, envelope, state = _case(cl)
    if not known:
        state = CommittedState.empty()
    menu = build_step_menu(request, envelope, state, step_id="forged_design:1")
    assert sum(row.kind != "none" for row in menu.options) == expected


def test_old_frozen_request_has_no_new_forge_step():
    request, envelope, state = _case()
    envelope.pop("explicit_forging_contract")
    assert build_step_menu(request, envelope, state, step_id="forged_design:1") is None
    assert "forged_technique_concepts" not in json.loads(build_response(request, state))["acquisition_intent"]


def test_forge_contract_and_concept_tampering_fail_closed():
    request, envelope, state = _case()
    concept = deepcopy(next(iter(envelope["explicit_forging_contract"]["designs"].values()))["concept"])
    with pytest.raises(FoundryError):
        validate_explicit_concepts([concept, concept])
    concept["augment_ids"].append("increased_damage")
    with pytest.raises(FoundryError):
        validate_explicit_concepts([concept])
    envelope["explicit_forging_contract"]["maximum_choices"] = 6
    with pytest.raises(FoundryError):
        build_step_menu(request, envelope, state, step_id="forged_design:1")


def _require(request, envelope, ids=None):
    from app.core import sha256_json
    required = sorted(ids if ids is not None else envelope["explicit_forging_contract"]["designs"])
    request["required_forged_design_ids"] = required
    envelope["required_forged_design_ids"] = required.copy()
    envelope.pop("envelope_sha256", None)
    envelope["envelope_sha256"] = sha256_json(envelope)


def test_required_designs_finish_only_after_both_and_reject_response_tampering():
    request, envelope, state = _case()
    _require(request, envelope)
    for index, design in enumerate(request["required_forged_design_ids"], 1):
        menu = build_step_menu(request, envelope, state, step_id=f"forged_design:{index}")
        assert all(row.kind != "none" for row in menu.options)
        state = commit_option(menu, next(row.option_id for row in menu.options if row.choice_ids == (design,)), state)
    menu = build_step_menu(request, envelope, state, step_id="forged_design:3")
    assert len(menu.options) == 1 and menu.options[0].kind == "none"
    state = commit_option(menu, menu.options[0].option_id, state)
    parsed = json.loads(build_response(request, state))
    intent = normalize_selection_intent(parsed, request_sha256=request["request_sha256"], delegated_envelope=envelope, project={}, target_cl=20)
    assert len(intent.as_dict()["acquisition_intent"]["forged_technique_concepts"]) == 2
    parsed["acquisition_intent"]["forged_technique_concepts"].pop()
    with pytest.raises(FoundryError, match="omits required"):
        normalize_selection_intent(parsed, request_sha256=request["request_sha256"], delegated_envelope=envelope, project={}, target_cl=20)


@pytest.mark.parametrize("value", [["unknown"], ["air.gale.ignore_resistance"] * 2, "air.gale.ignore_resistance", [1], [[], []]])
def test_required_design_ids_are_exact_unique_and_typed(value):
    from character_creation.constructed_arts.explicit_forging import normalize_required_design_ids
    with pytest.raises(FoundryError) as error:
        normalize_required_design_ids(value)
    assert error.value.code == "CG1_REQUIRED_FORGED_DESIGNS_INVALID"


def test_required_design_brief_conflicts_and_unsupported_route():
    from character_creation.constructed_arts.explicit_forging import normalize_required_design_ids
    ids = ["air.gale.ignore_resistance"]
    assert normalize_required_design_ids(None, {"brief": {"required_forged_design_ids": ids}}) == ids
    with pytest.raises(FoundryError):
        normalize_required_design_ids([], {"brief": {"required_forged_design_ids": ids}})
    service = object.__new__(CharacterCreationExecutionService)
    for method, kwargs in ((service._complete_request, {}), (service.start, {"execution_mode": "STANDARD_API", "idempotency_key": "required-forge"})):
        with pytest.raises(FoundryError) as error:
            method("unused", required_forged_design_ids=ids, **kwargs)
        assert error.value.code == "CG1_REQUIRED_FORGED_DESIGNS_ROUTE_UNSUPPORTED"


@pytest.mark.parametrize("cl,known", [(10, True), (20, False)])
def test_required_design_missing_prerequisites_never_grant(cl, known):
    request, envelope, state = _case(cl)
    _require(request, envelope)
    if not known:
        state = CommittedState.empty()
    before = state.to_dict()
    with pytest.raises(FoundryError) as error:
        build_step_menu(request, envelope, state, step_id="forged_design:1")
    assert error.value.code == "DCC_REQUIRED_FORGED_DESIGN_UNAVAILABLE"
    assert state.to_dict() == before


def test_required_design_frozen_tamper_and_fabricated_finish_fail_closed():
    from character_creation.creative_controller.linear_walk import replay_committed_state
    request, envelope, state = _case()
    _require(request, envelope)
    stopped = state.with_bounded("forged_design_done", True)
    for action in (lambda: build_response(request, stopped), lambda: _step_descriptors(request, envelope, stopped)):
        with pytest.raises(FoundryError):
            action()
    with pytest.raises(FoundryError):
        replay_committed_state([{"event_type": "STEP_COMMITTED", "payload": {"step_id": "forged_design:1", "choice_ids": []}}], state, request=request, envelope=envelope)
    envelope["required_forged_design_ids"].pop()
    with pytest.raises(FoundryError) as error:
        build_step_menu(request, envelope, state, step_id="forged_design:1")
    assert error.value.code == "CG1_DELEGATED_ENVELOPE_TAMPERED"


def test_required_design_runtime_provider_projection_is_not_persisted_authority():
    request, envelope, state = _case()
    _require(request, envelope)
    augmented = {**deepcopy(envelope), "linear_provider_payload": {"schema": "runtime-projection"}}
    menu = build_step_menu(request, augmented, state, step_id="forged_design:1")
    assert len(menu.options) == 2 and all(row.kind != "none" for row in menu.options)
    assert "linear_provider_payload" not in request["delegated_choice_envelope"]
    augmented["required_forged_design_ids"].pop()
    with pytest.raises(FoundryError) as error:
        build_step_menu(request, augmented, state, step_id="forged_design:1")
    assert error.value.code == "CG1_DELEGATED_ENVELOPE_TAMPERED"


def test_actual_complete_request_freezes_requirement_before_provider(monkeypatch):
    import character_creation.service as service_module
    from app.core import sha256_json
    from tests.test_combat_output_profile_authority import _request_service
    from character_creation.constructed_arts.explicit_forging import required_design_ids
    service = _request_service(monkeypatch)
    original_builder = service_module.build_delegated_choice_envelope
    def envelope_builder(*args, **kwargs):
        envelope = original_builder(*args, **kwargs)
        envelope["explicit_forging_contract"] = explicit_forging_contract()
        return envelope
    monkeypatch.setattr(service_module, "build_delegated_choice_envelope", envelope_builder)
    monkeypatch.setattr(service_module, "build_active_controller_route_binding", lambda **kwargs: {})
    ids = list(explicit_forging_contract()["designs"])
    kwargs = {"controller_route": "DETERMINISTIC_CREATIVE_CONTROLLER", "manual_collection_nonce": "x" * 40}
    request = service._complete_request("project.combat-target", required_forged_design_ids=ids, **kwargs)
    envelope = request["delegated_choice_envelope"]
    assert required_design_ids(envelope, request) == sorted(ids)
    assert request["request_sha256"] == service.request_payload_sha256(request)
    assert envelope["envelope_sha256"] == sha256_json({k: v for k, v in envelope.items() if k != "envelope_sha256"})
    old = service._complete_request("project.combat-target", **kwargs)
    assert "required_forged_design_ids" not in old and "required_forged_design_ids" not in old["delegated_choice_envelope"]
    assert old["request_sha256"] != request["request_sha256"]


@pytest.mark.parametrize("chosen_count,required", [(0, False), (1, False), (2, False), (2, True)])
def test_forge_decisions_replay_through_persisted_snapshot(fresh_db, chosen_count, required):
    from character_creation.creative_controller.linear_persistence import LinearWalkPersistence
    from tests.test_dcc_linear_s4 import _insert_project, _request, _seed_run

    _insert_project(fresh_db)
    envelope = {"explicit_forging_contract": explicit_forging_contract(), "frozen_owner_target_cl": 20}
    request = _request(envelope)
    if required:
        _require(request, envelope)
    run = f"cg1.run.forge-replay-{chosen_count}"
    _seed_run(fresh_db, request, run)
    persistence = LinearWalkPersistence(fresh_db)
    projection = persistence.projection(run)
    state = CommittedState.empty()
    persistence.append_event(run, event_type="WALK_STARTED", subject_sha256=request["request_sha256"], state_sha256_before=projection["state_sha256"], state_sha256_after=state.committed_sha256, payload={})
    step_count = 0
    for cl, talent in ((5, "TAL_AIR_DOWNBURST_SEAL"), (15, "TAL_AIR_HEAVEN_SPLITTING_GALE")):
        after = state.with_ordinary(cl, talent)
        event = persistence.append_event(run, event_type="STEP_COMMITTED", subject_sha256=request["request_sha256"], state_sha256_before=state.committed_sha256, state_sha256_after=after.committed_sha256, payload={"step_id": f"ordinary_talent:{cl}", "choice_ids": [talent]})
        state = after
        step_count += 1
    choices = list(envelope["explicit_forging_contract"]["designs"])[:chosen_count] + [None]
    for index, design in enumerate(choices, 1):
        menu = build_step_menu(request, envelope, state, step_id=f"forged_design:{index}")
        option = next(row for row in menu.options if row.choice_ids == ((design,) if design else ()))
        after = commit_option(menu, option.option_id, state)
        event = persistence.append_event(run, event_type="STEP_COMMITTED", subject_sha256=menu.menu_sha256, state_sha256_before=state.committed_sha256, state_sha256_after=after.committed_sha256, payload={"step_id": menu.step_id, "choice_ids": list(option.choice_ids)})
        state = after
        step_count += 1
        persistence.save_snapshot(run, step_count, state, event["event_sha256"])
        assert LinearWalkPersistence(fresh_db).verified_replay(request, envelope, run)["state"].to_dict() == state.to_dict()
    forged_snapshot = state.with_bounded("forged_design_done", False)
    persistence.save_snapshot(run, step_count, forged_snapshot, event["event_sha256"])
    with pytest.raises(FoundryError) as error:
        LinearWalkPersistence(fresh_db).verified_replay(request, envelope, run)
    assert error.value.code == "DCC_LINEAR_SNAPSHOT_MISMATCH"
