"""Source records, real creation rows and causal events agree on activation.

These are deterministic development checks; they do not claim model acceptance.
"""
from copy import copy, deepcopy

import pytest

from character_creation.response_materialization import CanonicalSelectionIntent
from contracts.canonical import ZERO_HASH
from non_sphere_authority.method_mechanics import has_acquired_method
from non_sphere_authority.service import NonSphereAuthorityService
from projector.method_mechanics import project_initial_method_mechanics
from projector.v3_bridge import _validate_binding
from stage2.service import RulesCausalStage2Service, _state
from tests.test_creation_training_r4 import _real_creation_intent
from tests.test_rec1_p1cr5_owner_authority import _private_scope


@pytest.fixture(scope="module")
def method_pipeline(catalog_environment):
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment)
    method = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record("METHOD-083", mechanical=True)
    return creator, project, run, intent, method


@pytest.mark.parametrize("path_ids", [
    ["tianxia.path.body_refining"],
    ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"],
])
def test_new_method_runs_through_real_producer_causal_engine_and_projection(method_pipeline, path_ids):
    creator, project, run, intent, method = method_pipeline
    document = intent.as_dict()
    document["selected_by_slot"]["method_choice"] = [method["record_id"]]
    document["selected_by_slot"]["path_choice"] = path_ids
    document["bounded_choices"]["path_progression_by_cl"] = {"1": path_ids[0]}
    intent = CanonicalSelectionIntent.from_document(document)
    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, intent)
    kinds = [row["kind"] for row in rows]
    assert kinds.index("method_acquisition") + 1 == kinds.index("method_activation")
    assert kinds.index("method_activation") < kinds.index("level_advance")
    rows = rows[:kinds.index("level_advance") + 1]
    stage2 = RulesCausalStage2Service(creator.db)
    proposal = {
        "project_id": project["project_id"], "proposal_id": "method-mechanics-pipeline",
        "expected_project_revision": project["revision"],
        "idempotency_key": "method-mechanics-pipeline", "created_at": "2026-09-07T00:00:00+00:00",
    }
    state = _state(project["project_id"])
    events = []
    with _private_scope(stage2, run["request"], run["run_id"], set(path_ids)), creator.db.connection() as conn:
        for index, choice in enumerate(rows):
            event, state, blockers = stage2._choice_event(
                conn=conn, row=proposal, project=project, state=state, choice=choice,
                index=index, sequence=index + 1,
                previous_hash=events[-1]["event_hash"] if events else ZERO_HASH,
                generic_prefix=events,
            )
            assert blockers == [], (choice["kind"], blockers)
            assert event is not None
            events.append(event)
    activation = next(e for e in events if e["advancement"]["kind"] == "method_activation")
    assert activation["advancement"]["details"] == {}
    assert activation["advancement"]["calculation"]["outputs"] == {}
    assert state["method"]["state"] == "active"
    resource = state["resources"]["tianxia.resource.stamina"]
    assert resource["method_delta"] == -2
    assert resource["maximum"] == max(0, resource["base_value"] - 2)
    assert resource["current"] <= resource["maximum"]
    if "tianxia.path.spirit_awakening" in path_ids:
        resonance = state["resources"]["tianxia.resource.resonance"]
        assert resonance["method_delta"] == 2
        assert resonance["maximum"] == resonance["base_value"] + 2
        assert resonance["current"] <= resonance["maximum"]
    _validate_binding(activation, method, project, locked_records={method["record_id"]: method})
    packets = {event["event_id"]: f"packet-{index}" for index, event in enumerate(events)}
    projected = project_initial_method_mechanics(creator.db.settings.root_dir, method, events, packets)
    assert projected["activation_event_id"] == activation["event_id"]
    assert projected["mechanical_projection"] is True
    assert has_acquired_method({"record_id": method["record_id"], **projected})
    assert any(
        binding["role"] == "method_delta" and binding["causal_event_id"] == activation["event_id"]
        for binding in events[-1]["advancement"]["authority_bindings"]
    )


@pytest.mark.parametrize("state,owned", [("acquired", True), ("active", True), ("none", False), ("selected", False)])
def test_method_ownership_survives_activation_without_promoting_selection(state, owned):
    assert has_acquired_method({"state": state, "record_id": "METHOD-083"}) is owned
    assert has_acquired_method({"state": state}) is False


def test_legacy_request_does_not_silently_gain_method_activation(method_pipeline):
    creator, project, run, intent, _ = method_pipeline
    service = copy(creator)
    # This checks row derivation for the historical input shape, without
    # changing any persisted request or claiming a new request hash is valid.
    # Exact historical record/import proofs are covered by the authority suite.
    run = deepcopy(run)
    run["request"]["server_owned_authority"].pop("initial_method_mechanics_policy")
    record = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record("METHOD-083")
    records = creator._locked_records_for_project(project["project_id"])
    records[record["record_id"]] = record
    service._locked_records_for_project = lambda _, **kwargs: deepcopy(records)
    document = intent.as_dict()
    document["selected_by_slot"]["method_choice"] = [record["record_id"]]
    rows = service._derive_stage2_rows_from_frozen_authority(run, project, CanonicalSelectionIntent.from_document(document))
    assert len([row for row in rows if row["kind"] == "method_acquisition"]) == 1
    assert not any(row["kind"] == "method_activation" for row in rows)


@pytest.mark.parametrize("state", ["acquired", "active"])
def test_sheet_and_gm_preserve_owned_method_instead_of_requiring_typed_absence(state):
    from character_sheet.service import CharacterSheetService
    from factory_authoring.command5_profile import CharacterGMCommand5Profile

    method = {"record_id": "METHOD-083", "state": state}
    snapshot = {
        "method": method,
        "identity": {"cultivation_level": 1},
        "explicit_none_systems": {
            name: {"state": "none", "source_backed": True}
            for name in ("foundation", "manuals", "equipment", "forged_techniques")
        },
        "later_stage_status": {name: {"status": "NOT_ATTEMPTED"} for name in ("gm_screen", "combat")},
    }
    CharacterSheetService._validate_snapshot(snapshot, set(), {})
    assert CharacterGMCommand5Profile._typed_none(snapshot, "method") == method
