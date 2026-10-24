"""Forged effects remain bound to the locked talent and its real source bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from character_creation.constructed_arts.forged_technique import (
    construct_forged_technique,
    forged_technique_acquisition_authority,
    validate_forged_technique_acquisition,
)
from character_creation.constructed_arts.forging_authority import load_forging_authority
from character_creation.constructed_arts.records import build_forged_technique_record
from character_creation.constructed_arts.sources import published_block
from character_creation.service import CharacterCreationExecutionService
from projector.v3_bridge import _forged_technique_projection_rows
from stage2.service import RulesCausalStage2Service
from test_constructed_forged_techniques import _request

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def authority():
    return load_forging_authority(ROOT)


def _case(tmp_path):
    request = _request(concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"})
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "factory_adapter.json").write_text(json.dumps({"factory_root": str(tmp_path)}))
    records = {}
    for index, talent in enumerate(request["known_talents"]):
        path = tmp_path / f"talent-{index}.md"
        path.write_text(talent["published_text"] + "\n")
        talent["source"] = {"source_id": f"test.source.{index}", "path": path.name, "anchor": "line:1:column:1", "source_hash": hashlib.sha256(path.read_bytes()).hexdigest()}
        records[talent["talent_id"]] = {
            "record_id": talent["talent_id"], "record_hash": talent["record_hash"],
            "display_name": talent["display_name"], "source": deepcopy(talent["source"]),
            "content_binding": {"pack_id": "test.pack", "pack_version": "1", "pack_hash": "c" * 64},
            "compatibility": {"factory": {"stage2_authority": {"sphere_id": talent["sphere_id"]}}},
        }
    for sphere in request["known_spheres"]:
        records[sphere["sphere_id"]] = {
            "record_id": sphere["sphere_id"], "record_hash": "d" * 64,
            "display_name": sphere["display_name"], "source": deepcopy(request["known_talents"][0]["source"]),
            "content_binding": {"pack_id": "test.pack", "pack_version": "1", "pack_hash": "c" * 64},
        }
    service = object.__new__(RulesCausalStage2Service)
    service.db = SimpleNamespace(settings=SimpleNamespace(root_dir=ROOT, vendor_dir=vendor))
    service._record = lambda conn, project_id, record_id, pointer, **kwargs: (records[record_id], [])
    state = {"current_cl": 10, "forged_techniques": [], "known_talents": {t["talent_id"] for t in request["known_talents"]}, "known_spheres": {s["sphere_id"] for s in request["known_spheres"]}, "record_event_ids": {}}
    return request, service, state


@pytest.mark.parametrize("mutation", [None, "sphere", "source", "text", "name", "source_bytes"])
def test_stage2_forged_effect_checks_locked_source(tmp_path, mutation):
    request, service, state = _case(tmp_path)
    talent = request["known_talents"][0]
    if mutation == "sphere":
        talent["sphere_id"] = request["known_spheres"][1]["sphere_id"]
    elif mutation == "source":
        talent["source"]["source_id"] = "test.fabricated.source"
    elif mutation == "text":
        talent["published_text"] = "Invented mechanics."
    elif mutation == "name":
        talent["display_name"] = "Invented Talent"
    elif mutation == "source_bytes":
        # Prime the reader, then change the bytes without changing the locked hash.
        assert published_block(tmp_path, talent["source"])
        (tmp_path / talent["source"]["path"]).write_text("Changed source bytes.\n")
    art = construct_forged_technique(load_forging_authority(ROOT), request)
    record = build_forged_technique_record(art)
    blockers, outputs, bindings = service._forged_technique_compile(None, "project-1", record, state, "/test", 10)
    if mutation is None:
        assert not blockers
        assert outputs["forged_technique"]["technique_id"] == art["technique_id"]
        assert bindings
    else:
        assert "FORGING_EFFECT_SOURCE_MISMATCH" in {b["code"] for b in blockers}
        assert outputs == {} and bindings == []


def test_source_reader_rechecks_expected_hash_after_prior_success(tmp_path):
    request, _, _ = _case(tmp_path)
    source = request["known_talents"][0]["source"]
    assert published_block(tmp_path, source)
    assert published_block(tmp_path, {**source, "source_hash": "0" * 64}) == ""


def _forging_acquisition(technique, *, attempts, event_id="event-1", ability_modifier=1, include_authority=False):
    research_days = technique["research_days"]
    material_cost_gp = technique["material_cost_gp"]
    acquisition = {
        "schema": "TianxiaFoundry.ForgedTechniqueAcquisition.v1",
        "mode": "creator_generated_history",
        "scope": "initial_creation",
        "observed_play": False,
        "live_currency_debit": False,
        "target_cl": technique["cl_created"],
        "record_id": technique["technique_id"],
        "record_hash": "record-hash",
        "powering_path_id": technique["powering_path_id"],
        "key_ability": technique["key_ability"],
        "pb": 4,
        "ability_modifier": ability_modifier,
        "dc": technique["technique_forging_dc"],
        "research": {"required_days": research_days, "meaningful_training_hours": research_days * 8, "completed": True},
        "materials": {"required_gp": material_cost_gp, "paid_gp": material_cost_gp, "payment_complete": True},
        "training_location": {"mode": "creator_generated_history", "scope": "initial_creation", "suitable": True},
        "completion": {
            "mode": "creator_generated_history",
            "scope": "initial_creation",
            "record_id": technique["technique_id"],
            "record_hash": "record-hash",
            "research_complete": True,
            "payment_complete": True,
            "event_id": event_id,
        },
        "attempts": attempts,
    }
    if include_authority:
        acquisition["authority"] = forged_technique_acquisition_authority()
    return acquisition


def _projector_forged_event(technique, record, acquisition, *, include_proof=True):
    marker = forged_technique_acquisition_authority()
    compiled = {
        "technique_id": technique["technique_id"],
        "record_id": record["record_id"],
        "forging_acquisition_authority": marker,
    }
    outputs = {"forged_technique": compiled}
    inputs = {"forging_acquisition_authority": marker}
    if include_proof:
        outputs["forging_acquisition"] = deepcopy(acquisition)
        inputs["forging_acquisition"] = deepcopy(acquisition)
    return {
        "event_id": "event-1",
        "advancement": {
            "target_cl": 10,
            "calculation": {"inputs": inputs, "outputs": outputs},
        },
    }


def test_projector_accepts_new_persistent_forging_authority(authority):
    technique = construct_forged_technique(
        authority,
        _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"}),
    )
    record = build_forged_technique_record(technique)
    acquisition = _forging_acquisition(
        technique,
        attempts=[{
            "attempt_id": "attempt-1",
            "retry_of_attempt_id": None,
            "check_die_result": 20,
            "research_time_hours": technique["research_days"] * 8,
            "materials_paid_gp": technique["material_cost_gp"],
        }],
        include_authority=True,
    )
    acquisition["record_id"] = record["record_id"]
    acquisition["record_hash"] = record["record_hash"]
    acquisition["completion"]["record_id"] = record["record_id"]
    acquisition["completion"]["record_hash"] = record["record_hash"]
    acquisition = validate_forged_technique_acquisition(
        acquisition,
        event_id="event-1",
        record_id=record["record_id"],
        record_hash=record["record_hash"],
        cl=10,
        path_id=technique["powering_path_id"],
        key_ability=technique["key_ability"],
        ability_modifier=1,
        pb=4,
        dc=technique["technique_forging_dc"],
        research_days=technique["research_days"],
        material_cost_gp=technique["material_cost_gp"],
        require_authority_binding=True,
    )
    event = _projector_forged_event(technique, record, acquisition)
    rows, indexes = _forged_technique_projection_rows(
        [event],
        event_records={"event-1": record},
        locked_records={record["record_id"]: record},
        packet_by_event={"event-1": "packet-1"},
        event_context_by_id={
            "event-1": {
                "path_event": {"subject": {"record_id": technique["powering_path_id"]}},
                "path_record": {"compatibility": {"factory": {"stage2_authority": {"key_ability": technique["key_ability"]}}}},
                "ability_event": {"advancement": {"calculation": {"outputs": {"ability_modifiers": {technique["key_ability"]: 1}}}}},
                "level_event": {"advancement": {"calculation": {"outputs": {"pb": 4}}}},
            },
        },
        factory_root=ROOT,
    )
    assert indexes == {"event-1": 0}
    assert rows[0]["state"] == "known"


def test_projector_new_forging_authority_cannot_fall_back_to_legacy(authority):
    technique = construct_forged_technique(
        authority,
        _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"}),
    )
    record = build_forged_technique_record(technique)
    event = _projector_forged_event(technique, record, {}, include_proof=False)
    with pytest.raises(FoundryError) as failure:
        _forged_technique_projection_rows(
            [event],
            event_records={"event-1": record},
            locked_records={record["record_id"]: record},
            packet_by_event={"event-1": "packet-1"},
            factory_root=ROOT,
        )
    assert failure.value.code == "PROJECTION_FORGED_ACQUISITION_REQUIRED"


def test_forged_acquisition_derives_check_and_retains_failed_retry_history(authority):
    request = _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"})
    technique = construct_forged_technique(authority, request)
    failed = {
        "attempt_id": "attempt-1",
        "retry_of_attempt_id": None,
        "check_die_result": 1,
        "research_time_hours": technique["research_days"] * 4,
        "materials_paid_gp": technique["material_cost_gp"] // 2,
    }
    successful = {
        "attempt_id": "attempt-2",
        "retry_of_attempt_id": "attempt-1",
        "check_die_result": 20,
        "research_time_hours": technique["research_days"] * 8,
        "materials_paid_gp": technique["material_cost_gp"],
    }
    result = validate_forged_technique_acquisition(
        _forging_acquisition(technique, attempts=[failed, successful]),
        event_id="event-1",
        record_id=technique["technique_id"],
        record_hash="record-hash",
        cl=10,
        path_id=technique["powering_path_id"],
        key_ability=technique["key_ability"],
        ability_modifier=1,
        pb=4,
        dc=technique["technique_forging_dc"],
        research_days=technique["research_days"],
        material_cost_gp=technique["material_cost_gp"],
    )
    assert [attempt["result"] for attempt in result["attempts"]] == ["failure", "success"]
    assert result["attempts"][0]["computed_check_total"] == 6
    assert result["completion"]["event_id"] == "event-1"


def test_forged_acquisition_rejects_authored_result_and_missing_evidence(authority):
    request = _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"})
    technique = construct_forged_technique(authority, request)
    attempt = {
        "attempt_id": "attempt-1",
        "retry_of_attempt_id": None,
        "check_die_result": 20,
        "research_time_hours": technique["research_days"] * 8,
        "materials_paid_gp": technique["material_cost_gp"],
        "result": "failure",
    }
    acquisition = _forging_acquisition(technique, attempts=[attempt])
    with pytest.raises(FoundryError) as authored:
        validate_forged_technique_acquisition(
            acquisition,
            event_id="event-1",
            record_id=technique["technique_id"],
            record_hash="record-hash",
            cl=10,
            path_id=technique["powering_path_id"],
            key_ability=technique["key_ability"],
            ability_modifier=1,
            pb=4,
            dc=technique["technique_forging_dc"],
            research_days=technique["research_days"],
            material_cost_gp=technique["material_cost_gp"],
        )
    assert authored.value.code == "FORGED_TECHNIQUE_ACQUISITION_INVALID"
    acquisition.pop("materials")
    with pytest.raises(FoundryError) as missing:
        validate_forged_technique_acquisition(
            acquisition,
            event_id="event-1",
            record_id=technique["technique_id"],
            record_hash="record-hash",
            cl=10,
            path_id=technique["powering_path_id"],
            key_ability=technique["key_ability"],
            ability_modifier=1,
            pb=4,
            dc=technique["technique_forging_dc"],
            research_days=technique["research_days"],
            material_cost_gp=technique["material_cost_gp"],
        )
    assert missing.value.code == "FORGED_TECHNIQUE_ACQUISITION_INVALID"


def test_new_creator_proof_rejects_missing_or_tampered_authority(authority):
    technique = construct_forged_technique(
        authority,
        _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"}),
    )
    base_attempt = {
        "attempt_id": "attempt-1",
        "retry_of_attempt_id": None,
        "check_die_result": 20,
        "research_time_hours": technique["research_days"] * 8,
        "materials_paid_gp": technique["material_cost_gp"],
    }
    acquisition = _forging_acquisition(
        technique,
        attempts=[base_attempt],
        include_authority=True,
    )
    with pytest.raises(FoundryError) as missing:
        validate_forged_technique_acquisition(
            {key: value for key, value in acquisition.items() if key != "authority"},
            event_id="event-1",
            record_id=technique["technique_id"],
            record_hash="record-hash",
            cl=10,
            path_id=technique["powering_path_id"],
            key_ability=technique["key_ability"],
            ability_modifier=1,
            pb=4,
            dc=technique["technique_forging_dc"],
            research_days=technique["research_days"],
            material_cost_gp=technique["material_cost_gp"],
            require_authority_binding=True,
        )
    assert "server-owned authority binding" in missing.value.message
    tampered = deepcopy(acquisition)
    tampered["authority"]["issuer"] = "untrusted"
    with pytest.raises(FoundryError) as forged:
        validate_forged_technique_acquisition(
            tampered,
            event_id="event-1",
            record_id=technique["technique_id"],
            record_hash="record-hash",
            cl=10,
            path_id=technique["powering_path_id"],
            key_ability=technique["key_ability"],
            ability_modifier=1,
            pb=4,
            dc=technique["technique_forging_dc"],
            research_days=technique["research_days"],
            material_cost_gp=technique["material_cost_gp"],
            require_authority_binding=True,
        )
    assert "server-owned authority binding" in forged.value.message


def test_creator_forging_history_is_replay_stable_under_persisted_nonce(authority):
    request = _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"})
    technique = construct_forged_technique(authority, request)
    record = build_forged_technique_record(technique)
    run = {
        "project_id": "project-1",
        "request": {
            "server_owned_authority": {
                "manual_collection": {
                    "authority_version": "server_owned_pre_provider.v2",
                    "nonce": "n" * 48,
                },
            },
        },
    }
    first = CharacterCreationExecutionService._forged_technique_creation_parameters(
        run, technique, record, index=0, intent_hash="intent-hash", ability_modifier=1,
    )
    replay = CharacterCreationExecutionService._forged_technique_creation_parameters(
        deepcopy(run), deepcopy(technique), deepcopy(record), index=0, intent_hash="intent-hash", ability_modifier=1,
    )
    assert first == replay
    assert first["mode"] == "creator_generated_history"
    assert first["scope"] == "initial_creation"
    assert first["observed_play"] is False
    assert first["live_currency_debit"] is False
    assert first["authority"]["version"] == "server_owned_pre_provider.v2"
    assert len(first["attempts"]) >= 1
    assert 1 <= first["attempts"][0]["check_die_result"] <= 20
    assert "result" not in first["attempts"][0]


def test_creator_forging_history_retries_with_raw_half_costs(monkeypatch, authority):
    request = _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"})
    technique = construct_forged_technique(authority, request)
    record = build_forged_technique_record(technique)
    run = {
        "project_id": "project-1",
        "request": {
            "server_owned_authority": {
                "manual_collection": {
                    "authority_version": "server_owned_pre_provider.v2",
                    "nonce": "n" * 48,
                },
            },
        },
    }

    class SequenceRng:
        def __init__(self, seed):
            self.seed = seed
            self.values = iter((1, 20))

        def randint(self, lower, upper):
            assert (lower, upper) == (1, 20)
            return next(self.values)

    monkeypatch.setattr("character_creation.service.random.Random", SequenceRng)
    acquisition = CharacterCreationExecutionService._forged_technique_creation_parameters(
        run,
        technique,
        record,
        index=0,
        intent_hash="intent-hash",
        ability_modifier=1,
    )
    assert [attempt["check_die_result"] for attempt in acquisition["attempts"]] == [1, 20]
    assert acquisition["attempts"][1]["retry_of_attempt_id"] == acquisition["attempts"][0]["attempt_id"]
    assert acquisition["attempts"][0]["research_time_hours"] == technique["research_days"] * 4
    assert acquisition["attempts"][0]["materials_paid_gp"] == technique["material_cost_gp"] // 2
    assert acquisition["attempts"][1]["research_time_hours"] == technique["research_days"] * 8
    assert acquisition["attempts"][1]["materials_paid_gp"] == technique["material_cost_gp"]


def test_creator_forging_history_exhaustion_retains_failed_attempts(monkeypatch, authority):
    request = _request(cl=10, pb=4, concept={"primary_talent_id": "tianxia.talent.blood.crimson_mark", "base_form": "strike"})
    technique = construct_forged_technique(authority, request)
    record = build_forged_technique_record(technique)
    run = {
        "project_id": "project-1",
        "request": {
            "server_owned_authority": {
                "manual_collection": {
                    "authority_version": "server_owned_pre_provider.v2",
                    "nonce": "n" * 48,
                },
            },
        },
    }

    class FailingRng:
        def __init__(self, seed):
            self.seed = seed

        def randint(self, lower, upper):
            return 1

    monkeypatch.setattr("character_creation.service.random.Random", FailingRng)
    with pytest.raises(FoundryError) as failure:
        CharacterCreationExecutionService._forged_technique_creation_parameters(
            run,
            technique,
            record,
            index=0,
            intent_hash="intent-hash",
            ability_modifier=1,
        )
    assert failure.value.code == "CG1_FORGING_ACQUISITION_EXHAUSTED"
    attempts = failure.value.details["attempts"]
    assert len(attempts) == 8
    assert all(attempt["materials_paid_gp"] == technique["material_cost_gp"] // 2 for attempt in attempts)


def test_stage2_rejects_supplied_creator_forging_history_without_trusted_scope(tmp_path, authority):
    request, service, state = _case(tmp_path)
    technique = construct_forged_technique(authority, request)
    record = build_forged_technique_record(technique)
    acquisition = _forging_acquisition(technique, attempts=[{
        "attempt_id": "attempt-1",
        "retry_of_attempt_id": None,
        "check_die_result": 20,
        "research_time_hours": technique["research_days"] * 8,
        "materials_paid_gp": technique["material_cost_gp"],
    }])
    blockers, outputs, bindings = service._forged_technique_compile(
        None,
        "project-1",
        record,
        state,
        "/test",
        10,
        parameters={"forging_acquisition": acquisition},
        event_id="event-1",
    )
    assert "FORGING_CREATOR_SCOPE_REQUIRED" in {blocker["code"] for blocker in blockers}
    assert outputs == {} and bindings == []


def test_generated_forging_row_has_a_closed_stage2_schema_and_proof_boundary(authority):
    from contracts.registry import ContractValidationError, SchemaRegistry

    technique = construct_forged_technique(
        authority,
        _request(
            cl=10,
            pb=4,
            concept={
                "primary_talent_id": "tianxia.talent.blood.crimson_mark",
                "base_form": "strike",
            },
        ),
    )
    record = build_forged_technique_record(technique)
    run = {
        "project_id": "project-1",
        "request": {
            "server_owned_authority": {
                "manual_collection": {
                    "authority_version": "server_owned_pre_provider.v2",
                    "nonce": "n" * 48,
                },
            },
        },
    }
    acquisition = CharacterCreationExecutionService._forged_technique_creation_parameters(
        run,
        technique,
        record,
        index=0,
        intent_hash="intent-hash",
        ability_modifier=1,
    )
    proposal = {
        "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
        "project_id": "project-1",
        "expected_project_revision": 1,
        "expected_content_lock_hash": "a" * 64,
        "target_cl": 10,
        "idempotency_key": "forging-schema-test",
        "choices": [
            {
                "kind": "forged_technique_creation",
                "effective_cl": 10,
                "record_id": record["record_id"],
                "acquisition_channel": "forged-technique-creation",
                "parameters": {
                    "prewritten_record_id": record["record_id"],
                    "forging_acquisition": acquisition,
                },
            }
        ],
    }
    registry = SchemaRegistry(ROOT)
    assert registry.validate(proposal, proposal["schema_version"]) == proposal

    malformed = deepcopy(proposal)
    malformed["choices"][0]["parameters"]["forging_acquisition"]["attempts"][0]["untrusted"] = True
    with pytest.raises(ContractValidationError) as schema_error:
        registry.validate(malformed, malformed["schema_version"])
    assert any(
        diagnostic.pointer.endswith("/attempts/0")
        and diagnostic.validator == "additionalProperties"
        for diagnostic in schema_error.value.diagnostics
    )

    malformed_proof = deepcopy(acquisition)
    malformed_proof["attempts"][0]["untrusted"] = True
    with pytest.raises(FoundryError):
        validate_forged_technique_acquisition(
            malformed_proof,
            event_id="event-1",
            record_id=record["record_id"],
            record_hash=record["record_hash"],
            cl=10,
            path_id=technique["powering_path_id"],
            key_ability=technique["key_ability"],
            ability_modifier=1,
            pb=4,
            dc=technique["technique_forging_dc"],
            research_days=technique["research_days"],
            material_cost_gp=technique["material_cost_gp"],
            require_authority_binding=True,
        )
