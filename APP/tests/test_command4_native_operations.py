from copy import deepcopy
from pathlib import Path

import pytest

from app.core import FoundryError, sha256_bytes
from factory_authoring.native_path_operations import native_operation_bindings, validate_native_operation_binding
from factory_authoring.native_path_operations import validate_native_operation_candidate, validate_operation_acquisition
from factory_authoring.native_path_mechanics import native_path_binding
from factory_authoring.command4_actions import produce_action_documents
from factory_authoring.command4_provider import _candidate_action_type, Command4ProviderAuthoring

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "tianxia.path.spirit_awakening.feature."


@pytest.mark.parametrize("feature,kinds,costs", [
    ("spiritual_sense", ["passive", "action"], [None, None]),
    ("soul_vessel", ["procedure", "action", "reaction"], ["2 Resonance", "3 Resonance", "2 Resonance"]),
    ("spiritual_exorcism", ["action", "procedure"], ["4 Resonance", "6 Resonance, plus 2 for a remote Soul Vessel rite"]),
])
def test_actual_canonical_feature_keeps_each_operation_and_its_cost(feature, kinds, costs):
    rows = native_operation_bindings(ROOT, PREFIX + feature)
    assert [row["action_type"] for row in rows] == kinds
    assert [row["printed_cost"] for row in rows] == costs
    assert len({row["operation_id"] for row in rows}) == len(rows)
    for row in rows:
        assert not row["grants_acquisition"] and not row["execution_authority"]
        assert row["parent_record_id"] == PREFIX + feature
        parent_lines = row["parent_binding"]["full_description"].splitlines()
        assert row["operation_rules_text"] == "\n".join(parent_lines[row["source_line_start"] - 1:row["source_line_end"]]).strip()
        assert validate_native_operation_binding(ROOT, row) == row


def test_parent_context_keeps_remote_rite_and_shared_restrictions():
    rows = native_operation_bindings(ROOT, PREFIX + "soul_vessel")
    for row in rows:
        source = row["parent_binding"]["full_description"]
        assert "### Sympathetic Rite at CL13" in source
        assert "You can have only one Soul Vessel." in source
        assert "cannot combine with Soulward Response on the same saving throw" in source
    assert "### Vessel Ward" not in rows[1]["operation_rules_text"]


@pytest.mark.parametrize("field,value", [
    ("action_type", "bonus_action"), ("printed_cost", "0 Resonance"),
    ("parent_record_id", PREFIX + "mind_spike"), ("grants_acquisition", True),
    ("execution_authority", True), ("source_line_end", 999),
])
def test_changed_operation_metadata_is_not_authority(field, value):
    row = deepcopy(native_operation_bindings(ROOT, PREFIX + "soul_vessel")[0])
    row[field] = value
    with pytest.raises(FoundryError, match="independently rederived"):
        validate_native_operation_binding(ROOT, row)


def test_rehashed_source_edit_is_rejected():
    row = deepcopy(native_operation_bindings(ROOT, PREFIX + "spiritual_exorcism")[1])
    row["operation_rules_text"] = "Automatically destroy every soul for no cost."
    row["operation_rules_sha256"] = sha256_bytes(row["operation_rules_text"].encode())
    with pytest.raises(FoundryError):
        validate_native_operation_binding(ROOT, row)


def test_unknown_feature_does_not_gain_operations():
    assert native_operation_bindings(ROOT, PREFIX + "invented") == []


def operation_candidates():
    cards = []
    for feature in ("spiritual_sense", "soul_vessel", "spiritual_exorcism"):
        binding = native_path_binding(ROOT, PREFIX + feature)
        cards.append({
            "record_id": binding["record_id"], "record_hash": "parent-hash",
            "display_name": binding["name"], "source": binding["source"],
            "full_description": binding["full_description"],
            "source_packet_ids": ["packet.stage2.062.aaaaaaaaaaaaaaaa"],
        })
    return produce_action_documents(cards, native_authority_root=ROOT)["Action_Authoring_Candidates.json"]["candidates"]


def test_producer_preserves_all_seven_operations_without_execution_grants():
    rows = operation_candidates()
    assert len(rows) == 7
    assert len({row["action_id"] for row in rows}) == 7
    for row in rows:
        binding = validate_native_operation_candidate(ROOT, row)
        assert _candidate_action_type(row) == binding["action_type"]
        assert row["acquisition_parent_record_id"] == binding["parent_record_id"]
        assert row["acquisition_parent_record_hash"] == "parent-hash"
        assert "unambiguous_locked_mechanics_source" in row["missing_fields"]
        assert not row["execution_authority"]


def acquisition_fixture():
    row = next(row for row in operation_candidates() if row["record_id"].endswith(".vessel_ward"))
    parent = {"record_id": PREFIX + "soul_vessel", "record_hash": "parent-hash"}
    event = {
        "sequence": 62, "event_id": "original-event", "event_hash": "a" * 64,
        "subject": {"record_id": "tianxia.path.body_refining.feature.iron_voice"},
        "content_binding": {"record_hash": "representative-hash"},
        "advancement": {"kind": "level_advance", "target_cl": 9, "authority_bindings": [
            {"role": "path_automatic_feature_authority", **parent},
        ]},
    }
    packet = {
        "packet_id": "packet.stage2.062.aaaaaaaaaaaaaaaa", "sequence": 62,
        "event_id": event["event_id"], "event_hash": event["event_hash"],
        "record_id": event["subject"]["record_id"], "record_hash": "representative-hash",
        "target_cl": 9, "advancement_kind": "level_advance",
    }
    return row, packet, event, parent


def test_operation_retains_cross_path_representative_packet():
    row, packet, event, parent = acquisition_fixture()
    before = deepcopy((row, packet, event, parent))
    validate_operation_acquisition(row, packet, event, parent)
    assert (row, packet, event, parent) == before


@pytest.mark.parametrize("mutation", ["packet_event", "packet_subject", "parent_hash", "missing_parent_grant", "duplicate_parent_grant", "wrong_level"])
def test_operation_cannot_borrow_an_unrelated_event_or_parent(mutation):
    row, packet, event, parent = acquisition_fixture()
    if mutation == "packet_event":
        packet["event_id"] = "another-event"
    elif mutation == "packet_subject":
        packet["record_id"] = row["record_id"]
    elif mutation == "parent_hash":
        row["acquisition_parent_record_hash"] = "another-parent"
    elif mutation == "missing_parent_grant":
        event["advancement"]["authority_bindings"] = []
    elif mutation == "duplicate_parent_grant":
        event["advancement"]["authority_bindings"] *= 2
    else:
        packet["target_cl"] = 20
    with pytest.raises(FoundryError, match="actually acquired"):
        validate_operation_acquisition(row, packet, event, parent)


def test_provider_requires_verified_history_for_operation(tmp_path):
    row, packet, event, parent = acquisition_fixture()
    with pytest.raises(FoundryError) as error:
        Command4ProviderAuthoring()._resolve_locked_source_proof(tmp_path, row, {packet["packet_id"]: packet}, ())
    assert error.value.code == "COMMAND4_NATIVE_OPERATION_CONTEXT_MISSING"
    proof = Command4ProviderAuthoring()._resolve_locked_source_proof(
        tmp_path, row, {packet["packet_id"]: packet}, (),
        native_operation_context={"events": {event["event_id"]: event}, "parent_records": {parent["record_id"]: parent}, "event_head": event["event_hash"]},
    )
    assert proof["parent_record_id"] == parent["record_id"]
    assert proof["source_packet_ids"] == [packet["packet_id"]]
