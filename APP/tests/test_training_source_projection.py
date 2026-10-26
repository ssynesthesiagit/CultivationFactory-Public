from __future__ import annotations

import json
from contextlib import nullcontext
from copy import deepcopy

import pytest

from app.core import FoundryError, sha256_json
from character_creation.custom_training_source_authority import (
    build_custom_training_source_record,
    normalize_custom_training_source,
)
from projector.service import ProjectionService
from projector.v3_bridge import (
    _recorded_art_projection_rows,
    _training_source_projection_rows,
    _validate_binding,
    _validate_training_source_access_event,
)
from stage2.service import RulesCausalStage2Service, _state, _training_source_access_calculation_payload


def _source_record() -> dict:
    record = {
        "record_id": "source.manuals.alpha",
        "content_type": "source_document",
        "display_name": "The Alpha Archive",
        "record_hash": "a" * 64,
        "publication": {"status": "published"},
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "authority_complete": True,
                    "rule_id": "source.manuals.alpha.access.v1",
                    "allowed_kinds": ["training_source_access"],
                    "training_source_access": {
                        "mode": "requires_access_event",
                        "access_modes": ["owner-confirmed-study"],
                        "training_types": ["recorded_art"],
                        "target_record_ids": ["recorded-art.alpha"],
                    },
                }
            }
        },
    }
    return record


def _target_record() -> dict:
    return {
        "record_id": "recorded-art.alpha",
        "content_type": "recorded_art",
        "display_name": "Alpha Form",
        "record_hash": "b" * 64,
        "publication": {"status": "published"},
    }


def _source_event(*, access_mode: str = "owner-confirmed-study", event_id: str = "event.source.alpha", sequence: int = 2) -> dict:
    record = _source_record()
    payload = _training_source_access_calculation_payload(
        record=record,
        access_mode=access_mode,
        published_access_modes=["owner-confirmed-study"],
        training_types=["recorded_art"],
        target_record_ids=["recorded-art.alpha"],
    )
    return {
        "event_id": event_id,
        "sequence": sequence,
        "subject": {
            "record_id": record["record_id"],
            "content_type": record["content_type"],
            "display_name": record["display_name"],
        },
        "advancement": {
            "kind": "training_source_access",
            "target_cl": 1,
            "details": {},
            "calculation": {
                "rule_id": "source.manuals.alpha.access.v1",
                "formula": None,
                "inputs": deepcopy(payload),
                "outputs": deepcopy(payload),
                "trace": {},
            },
            "training_transaction": None,
            "none_state": None,
        },
        "created_records": [record["record_id"]],
        "updated_records": [],
        "retired_records": [],
    }


def _typed_none_event(event_id: str = "event.none.manuals", sequence: int = 1) -> dict:
    return {
        "event_id": event_id,
        "subject": {
            "record_id": "typed-none.manuals",
            "content_type": "source_document",
            "display_name": "No manuals",
        },
        "advancement": {
            "kind": "typed_none",
            "target_cl": 1,
            "details": {
                "target": "manuals",
                "reason_code": "not_selected",
                "reason": "No manuals was selected.",
            },
            "none_state": {
                "state": "none",
                "reason_code": "not_selected",
                "reason": "No manuals was selected.",
                "source_backed": True,
            },
            "calculation": {
                "rule_id": "typed-none.v1",
                "formula": None,
                "inputs": {},
                "outputs": {},
                "trace": {},
            },
            "training_transaction": None,
        },
        "created_records": [],
        "updated_records": [],
        "retired_records": [],
    }


def test_training_source_projection_rows_are_deterministic_and_recorded_art_targets_only():
    event = _source_event()
    records = {
        "source.manuals.alpha": _source_record(),
        "recorded-art.alpha": _target_record(),
    }
    first = _training_source_projection_rows(
        [event],
        event_records={event["event_id"]: records["source.manuals.alpha"]},
        locked_records=records,
        packet_by_event={event["event_id"]: "packet.stage2.002.deadbeefdeadbeef"},
    )
    second = _training_source_projection_rows(
        [deepcopy(event)],
        event_records={event["event_id"]: deepcopy(records["source.manuals.alpha"])},
        locked_records=deepcopy(records),
        packet_by_event={event["event_id"]: "packet.stage2.002.deadbeefdeadbeef"},
    )
    assert first == second
    rows, indexes = first
    assert indexes == {event["event_id"]: 0}
    assert rows == [{
        "source_id": "source.manuals.alpha",
        "allocation_id": "training_source_access:event.source.alpha",
        "name": "The Alpha Archive",
        "type": "other",
        "gained_at_cl": 1,
        "contents": {
            "recorded_arts": ["recorded-art.alpha"],
            # 80fee3e0 adds each Recorded Art's readable details for the sheet;
            # the source carries no manual collection.
            "recorded_art_details": [{
                "record_id": "recorded-art.alpha",
                "display_name": "Alpha Form",
                "record_text": None,
                "source_record_id": None,
                "minimum_cl": None,
                "state": "locked",
                "parent_manual_record_id": None,
            }],
            "manual_collection": None,
            "methods": [],
            "warnings": [],
            "recipes": [],
            "theory": [],
            "false_routes": [],
        },
        "restrictions": [],
        "risks": [],
        "mechanics_granted": [],
        "source_packet_ids": ["packet.stage2.002.deadbeefdeadbeef"],
        "record_hash": "a" * 64,
    }]


def test_training_source_access_calculation_is_replay_bound_and_tamper_evident():
    service = object.__new__(RulesCausalStage2Service)
    state = _state("project.training-source")
    event = _source_event()
    after = service._apply_event(state, event)
    assert after["training_sources"] == ["source.manuals.alpha"]
    assert after["typed_none_states"] == {}
    tampered = deepcopy(event)
    tampered["advancement"]["calculation"]["inputs"]["access_mode"] = "invented"
    with pytest.raises(FoundryError) as exc:
        service._apply_event(state, tampered)
    assert exc.value.code == "TRAINING_SOURCE_ACCESS_CALCULATION_INVALID"


def test_bridge_requires_root_created_records_and_exact_rule_trace():
    event = _source_event()
    record = _source_record()
    locked_records = {record["record_id"]: record, "recorded-art.alpha": _target_record()}

    # The canonical v3 event places record mutations at the event root.
    _validate_training_source_access_event(event, record, locked_records)

    for malformed in ("missing", "advancement"):
        candidate = deepcopy(event)
        if malformed == "missing":
            del candidate["created_records"]
        else:
            candidate["advancement"]["created_records"] = [record["record_id"]]
            del candidate["created_records"]
        with pytest.raises(FoundryError) as exc:
            _validate_training_source_access_event(candidate, record, locked_records)
        assert exc.value.code == "PROJECTION_TRAINING_SOURCE_ACCESS_CALCULATION_INVALID"

    for field in ("updated_records", "retired_records"):
        candidate = deepcopy(event)
        candidate[field] = ["unexpected.record"]
        with pytest.raises(FoundryError) as exc:
            _validate_training_source_access_event(candidate, record, locked_records)
        assert exc.value.code == "PROJECTION_TRAINING_SOURCE_ACCESS_CALCULATION_INVALID"

    for field, value in (("rule_id", "source.manuals.alpha.other.v1"), ("trace", {"authenticated": True})):
        candidate = deepcopy(event)
        candidate["advancement"]["calculation"][field] = value
        with pytest.raises(FoundryError) as exc:
            _validate_training_source_access_event(candidate, record, locked_records)
        assert exc.value.code == "PROJECTION_TRAINING_SOURCE_ACCESS_CALCULATION_INVALID"


def test_later_source_access_resolves_manuals_none_but_prior_source_cannot_be_overridden():
    service = object.__new__(RulesCausalStage2Service)
    state = service._apply_event(_state("project.training-source"), _typed_none_event())
    after = service._apply_event(state, _source_event())
    assert after["training_sources"] == ["source.manuals.alpha"]
    assert "manuals" not in after["typed_none_states"]
    with pytest.raises(FoundryError) as exc:
        service._apply_event(after, _typed_none_event(event_id="event.none.later", sequence=3))
    assert exc.value.code == "TYPED_NONE_CONTRADICTS_TRAINING_SOURCE_ACCESS"


def test_bridge_rejects_missing_target_and_unsupported_training_type():
    event = _source_event()
    record = _source_record()
    with pytest.raises(FoundryError) as exc:
        _validate_training_source_access_event(event, record, {record["record_id"]: record})
    assert exc.value.code == "PROJECTION_TRAINING_SOURCE_TARGET_MISSING"

    bad_record = deepcopy(record)
    bad_record["compatibility"]["factory"]["stage2_authority"]["training_source_access"]["training_types"] = ["unsupported"]
    bad_event = _source_event()
    with pytest.raises(FoundryError) as exc:
        _validate_training_source_access_event(bad_event, bad_record, {"recorded-art.alpha": _target_record()})
    assert exc.value.code == "PROJECTION_TRAINING_SOURCE_TRAINING_TYPE_UNSUPPORTED"


def test_custom_training_source_access_projects_only_authenticated_locked_record():
    target = _target_record()
    normalized = normalize_custom_training_source({
        "route_id": "owner_supplied_custom_training_source",
        "owner_confirmation_id": "owner-confirmation.synthetic",
        "display_name": "Owner Confirmed Archive",
        "summary": "A bounded owner-confirmed training source.",
        "source_text": "The owner supplied this source text.",
        "source_anchor": "synthetic.custom-training-source",
        "access_mode": "owner-confirmed-study",
        "training_types": ["recorded_art"],
        "target_record_ids": [target["record_id"]],
    })
    record = build_custom_training_source_record(normalized)
    payload = _training_source_access_calculation_payload(
        record=record,
        access_mode="owner-confirmed-study",
        published_access_modes=["owner-confirmed-study"],
        training_types=["recorded_art"],
        target_record_ids=[target["record_id"]],
    )
    event = {
        "event_id": "event.custom-source.alpha",
        "sequence": 1,
        "subject": {
            "record_id": record["record_id"],
            "content_type": record["content_type"],
            "display_name": record["display_name"],
        },
        "advancement": {
            "kind": "training_source_access",
            "target_cl": 1,
            "details": {},
            "calculation": {
                "rule_id": record["compatibility"]["factory"]["stage2_authority"]["rule_id"],
                "formula": None,
                "inputs": deepcopy(payload),
                "outputs": deepcopy(payload),
                "trace": {},
            },
            "training_transaction": None,
            "none_state": None,
        },
        "content_binding": {
            **deepcopy(record["content_binding"]),
            "record_hash": record["record_hash"],
        },
        "created_records": [record["record_id"]],
        "updated_records": [],
        "retired_records": [],
    }
    locked_records = {record["record_id"]: record, target["record_id"]: target}
    project = {"content_lock": {"packs": []}}
    _validate_binding(event, record, project, locked_records=locked_records)
    _validate_training_source_access_event(event, record, locked_records)
    rows, indexes = _training_source_projection_rows(
        [event],
        event_records={event["event_id"]: record},
        locked_records=locked_records,
        packet_by_event={event["event_id"]: "packet.custom-source.alpha"},
    )
    assert indexes == {event["event_id"]: 0}
    assert rows[0]["source_id"] == record["record_id"]
    assert rows[0]["source_packet_ids"] == ["packet.custom-source.alpha"]
    assert rows[0]["contents"]["recorded_arts"] == [target["record_id"]]

    forged = deepcopy(record)
    forged["source"]["source_text"] = "A forged source payload."
    with pytest.raises(FoundryError) as exc:
        _validate_binding(event, forged, project, locked_records=locked_records)
    assert exc.value.code == "PROJECTION_CUSTOM_TRAINING_SOURCE_INVALID"


def test_ordinary_recorded_art_template_acquisition_projects_without_quote_fallback():
    template = {
        "template_id": "action.alpha",
        "template_type": "action",
        "payload": {
            "action_id": "action.alpha",
            "name": "Alpha Form",
            "timing": "On your turn",
            "cost": "1 Qi",
            "range": "Self",
            "target": "One creature",
            "roll_save_check": "Make a Body check",
            "effect": "The target is marked until the end of your next turn.",
            "failure": "On a failure, the mark is not applied.",
            "duration": "1 round",
            "limit": "Once per round",
            "counterplay": "The target may break line of sight.",
        },
    }
    parent = {
        "record_id": "manual.ordinary",
        "content_type": "manual",
        "display_name": "The Alpha Manual",
        "record_hash": "a" * 64,
        "publication": {"status": "published"},
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "authority_complete": True,
                    "allowed_kinds": ["training_source_access"],
                    "manual": {
                        "lineage_source": "published-alpha-manual",
                        "technique_record_ids": ["recorded-art.alpha"],
                    },
                }
            }
        },
    }
    sphere = {
        "record_id": "sphere.alpha",
        "content_type": "sphere",
        "display_name": "Alpha Sphere",
        "record_hash": "b" * 64,
        "publication": {"status": "published"},
    }
    talent = {
        "record_id": "talent.alpha",
        "content_type": "talent",
        "display_name": "Alpha Talent",
        "record_hash": "c" * 64,
        "publication": {"status": "published"},
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "authority_complete": True,
                    "sphere_id": sphere["record_id"],
                }
            }
        },
        "execution_templates": [template],
        "display_projection": {
            "short_description": "Alpha Talent",
            "full_description": "Alpha Talent published execution.",
        },
    }
    art_authority = {
        "parent_manual_record_id": parent["record_id"],
        "technique_name": "Alpha Form",
        "associated_sphere_record_ids": [sphere["record_id"]],
        "expression_kind": "exact_named_talent",
        "reproduced_component_record_ids": [talent["record_id"]],
        "execution_derivation": {
            "mode": "copy_exact_published_template",
            "source_record_id": talent["record_id"],
            "template_id": template["template_id"],
        },
        "learning_dc": {"mode": "difficulty_formula", "difficulty": 1},
        "study_time": {"mode": "training_scene", "value": "one scene"},
        "allowed_study_abilities": ["INT", "WIS"],
        "requirements": [],
        "fixed_expression_only": True,
        "grants_sphere": False,
        "grants_talent": False,
        "grants_modification_permission": False,
    }
    record = {
        "record_id": "recorded-art.alpha",
        "content_type": "recorded_art",
        "display_name": "Alpha Form",
        "record_hash": "d" * 64,
        "publication": {"status": "published"},
        "source": {
            "source_id": "source.recorded-art.alpha",
            "path": "Compendium.md",
            "anchor": "line:1:column:1",
            "source_hash": "e" * 64,
        },
        "content_binding": {
            "pack_id": "ordinary.manual.pack",
            "pack_version": "1",
            "pack_hash": "f" * 64,
        },
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "authority_complete": True,
                    "rule_id": "recorded-art.alpha.stage2",
                    "allowed_kinds": ["manual_training_attempt"],
                    "recorded_art": art_authority,
                }
            }
        },
    }
    locked_records = {
        parent["record_id"]: parent,
        sphere["record_id"]: sphere,
        talent["record_id"]: talent,
        record["record_id"]: record,
    }
    source_access_event_id = "event.manual.alpha"
    event_id = "event.recorded-art.alpha"
    event_records = {
        source_access_event_id: parent,
        event_id: record,
    }
    output_art = {
        "record_id": record["record_id"],
        "display_name": record["display_name"],
        "parent_manual_record_id": parent["record_id"],
        "parent_manual_name": parent["display_name"],
        "lineage_source": "published-alpha-manual",
        "technique_name": "Alpha Form",
        "dm_facing_line": "Sphere of Alpha Sphere — Alpha Form — Alpha Talent — Difficulty 1",
        "associated_sphere_record_ids": [sphere["record_id"]],
        "associated_sphere_names": [sphere["display_name"]],
        "reproduced_component_record_ids": [talent["record_id"]],
        "reproduced_component_names": [talent["display_name"]],
        "expression_kind": "exact_named_talent",
        "learning_dc": deepcopy(art_authority["learning_dc"]),
        "study_time": deepcopy(art_authority["study_time"]),
        "allowed_study_abilities": ["INT", "WIS"],
        "requirements": [],
        "execution": deepcopy(template["payload"]),
        "execution_derivation": {
            "derivation_kind": "published_expression",
            "source_execution_record_id": talent["record_id"],
            "component_record_ids": [talent["record_id"]],
            "source_template_hash": sha256_json(template),
            "compiled_payload_hash": sha256_json(template["payload"]),
        },
        "linked_action_id": template["payload"]["action_id"],
        "fixed_expression_warning": "Learning this Recorded Art grants no source Sphere, source talent, flexible package, or modification permission.",
        "learned_at_cl": 1,
        "acquisition_event_id": event_id,
        "record_hash": record["record_hash"],
    }
    event = {
        "event_id": event_id,
        "sequence": 2,
        "subject": {
            "record_id": record["record_id"],
            "content_type": record["content_type"],
            "display_name": record["display_name"],
        },
        "advancement": {
            "kind": "manual_training_attempt",
            "target_cl": 1,
            "calculation": {"outputs": {"recorded_art": output_art}},
            "training_transaction": {
                "training_type": "recorded_art",
                "target_record_id": record["record_id"],
                "target_record_hash": record["record_hash"],
                "training_source_record_id": parent["record_id"],
                "training_source_record_hash": parent["record_hash"],
                "training_source_access_event_id": source_access_event_id,
                "result": "success",
                "computed_dc": 11,
                "recorded_arts_learned_this_cl_before": 0,
            },
        },
    }
    packet_by_event = {
        source_access_event_id: "packet.stage2.001.manual",
        event_id: "packet.stage2.002.art",
    }

    rows, indexes = _recorded_art_projection_rows(
        [event],
        event_records=event_records,
        locked_records=locked_records,
        packet_by_event=packet_by_event,
    )
    assert indexes == {event_id: 0}
    assert rows[0]["execution"] == template["payload"]
    assert rows[0]["execution_derivation"]["source_template_hash"] == sha256_json(template)
    assert rows[0]["record_text"] == talent["display_projection"]["full_description"]
    assert rows[0]["source_block_sha256"] is None
    assert rows[0]["source_packet_ids"] == [packet_by_event[event_id], packet_by_event[source_access_event_id]]

    tampered = deepcopy(event)
    tampered["advancement"]["calculation"]["outputs"]["recorded_art"]["execution"]["effect"] = "client-authored effect"
    with pytest.raises(FoundryError) as exc:
        _recorded_art_projection_rows(
            [tampered],
            event_records=event_records,
            locked_records=locked_records,
            packet_by_event=packet_by_event,
        )
    assert exc.value.code == "PROJECTION_RECORDED_ART_INVALID"

def test_projection_inputs_load_all_source_access_targets_without_acquisition_events():
    project_id = "project.training-source-inputs"
    source = _source_record()
    source["compatibility"]["factory"]["stage2_authority"]["training_source_access"]["target_record_ids"] = [
        "recorded-art.alpha",
        "recorded-art.beta",
    ]
    first_target = _target_record()
    second_target = deepcopy(first_target)
    second_target["record_id"] = "recorded-art.beta"
    second_target["record_hash"] = "c" * 64
    unrelated = deepcopy(first_target)
    unrelated["record_id"] = "unrelated.record"
    unrelated["record_hash"] = "d" * 64
    event = _source_event()
    payload = _training_source_access_calculation_payload(
        record=source,
        access_mode="owner-confirmed-study",
        published_access_modes=["owner-confirmed-study"],
        training_types=["recorded_art"],
        target_record_ids=[first_target["record_id"], second_target["record_id"]],
    )
    event["advancement"]["calculation"]["inputs"] = deepcopy(payload)
    event["advancement"]["calculation"]["outputs"] = deepcopy(payload)
    locked_rows = [
        {
            "record_id": record["record_id"],
            "pack_id": "synthetic.pack",
            "pack_version": "1",
            "record_hash": record["record_hash"],
            "record_json": json.dumps(record),
        }
        for record in (source, first_target, second_target, unrelated)
    ]

    class Connection:
        def execute(self, sql, _params=()):
            if "record_id IN" in sql:
                requested = set(_params[1:])
                return [row for row in locked_rows if row["record_id"] in requested]
            if "ORDER BY record_id" in sql:
                return locked_rows
            raise AssertionError(f"unexpected projection SQL: {sql}")

    class DatabaseStub:
        def connection(self):
            return nullcontext(Connection())

    class ProjectsStub:
        def get_project(self, requested_project_id):
            assert requested_project_id == project_id
            project = {"project_id": project_id, "revision": 0, "content_lock": {"packs": []}}
            return {"project": project, "project_id": project_id, "revision": 0, "working_name": "source target projection"}

        def timeline(self, requested_project_id):
            assert requested_project_id == project_id
            return [event]

    projector = object.__new__(ProjectionService)
    projector.db = DatabaseStub()
    projector.projects = ProjectsStub()
    _project, _events, records, _input_hash = projector._inputs(project_id)

    assert records[first_target["record_id"]] == first_target
    assert records[second_target["record_id"]] == second_target
    assert unrelated["record_id"] not in records
