from copy import deepcopy
from pathlib import Path
import json

import pytest

from app.core import FoundryError
from factory_authoring.command4_actions import produce_action_documents
from factory_authoring.command4_provider import Command4ProviderAuthoring
from factory_authoring.native_path_mechanics import native_path_binding, validate_native_path_candidate

ROOT = Path(__file__).resolve().parents[1]
FEATURE = "tianxia.path.spirit_awakening.feature.mind_spike"


def candidate():
    binding = native_path_binding(ROOT, FEATURE)
    return {
        "record_id": FEATURE,
        "name": binding["name"],
        "display_name": binding["name"],
        "source": deepcopy(binding["source"]),
        "full_description": binding["full_description"],
        "native_source_binding": binding,
        "source_packet_ids": ["acquisition.level.1"],
        "missing_fields": ["unambiguous_locked_mechanics_source"],
    }


def test_native_producer_binding_requires_independent_resolution(tmp_path):
    card = candidate()
    card.pop("native_source_binding")
    documents = produce_action_documents([card], native_authority_root=ROOT)
    rows = documents["Action_Authoring_Candidates.json"]["candidates"]
    assert len(rows) == 1
    row = rows[0]
    assert row["native_source_binding"] == native_path_binding(ROOT, FEATURE)
    assert "unambiguous_locked_mechanics_source" in row["missing_fields"]
    assert not row["execution_authority"]
    # Equal-Path advancement can retain a Body representative acquisition
    # packet while granting Spirit features. Never relabel that packet as a
    # Sphere source or replace it with the feature's mechanical text.
    packets = {"acquisition.level.1": {"record_id": "tianxia.path.body_refining.feature.tempered_response", "advancement_kind": "level_advance", "target_cl": 1}}
    before = deepcopy(packets)
    proof = Command4ProviderAuthoring()._resolve_locked_source_proof(tmp_path, row, packets, ())
    assert proof["native_source_binding"]["owner_path_id"] == "tianxia.path.spirit_awakening"
    assert proof["native_source_binding"]["grants_acquisition"] is False
    assert proof["source_packet_ids"] == card["source_packet_ids"]
    assert packets == before


@pytest.mark.parametrize("field", ["name", "full_description", "source", "native_source_binding", "record_id"])
def test_native_candidate_cannot_change_identity_or_text(field):
    row = candidate()
    row[field] = "invented"
    with pytest.raises(FoundryError) as error:
        validate_native_path_candidate(ROOT, row)
    assert error.value.code == "COMMAND4_NATIVE_SOURCE_INVALID"


def test_display_card_without_explicit_native_binding_is_not_authority():
    row = candidate()
    row.pop("native_source_binding")
    assert validate_native_path_candidate(ROOT, row) is None


def test_native_binding_rederives_feature_even_when_candidate_copy_agrees():
    row = candidate()
    row["native_source_binding"]["full_description"] = "Mind Spike automatically wins."
    row["full_description"] = row["native_source_binding"]["full_description"]
    with pytest.raises(FoundryError):
        validate_native_path_candidate(ROOT, row)


def test_native_source_requires_original_acquisition_packet(tmp_path):
    with pytest.raises(FoundryError) as error:
        Command4ProviderAuthoring()._resolve_locked_source_proof(tmp_path, candidate(), {}, ())
    assert error.value.code == "COMMAND4_LOCKED_SOURCE_PACKET_MISSING"


def test_changed_native_index_fails_its_existing_authority_identity(tmp_path):
    source = ROOT / "non_sphere_authority/authority"
    target = tmp_path / "non_sphere_authority/authority"
    target.mkdir(parents=True)
    name = "spirit_awakening.path_index.p2a.json"
    (target / "NS1R_AUTHORITY_IDENTITIES.json").write_bytes((source / "NS1R_AUTHORITY_IDENTITIES.json").read_bytes())
    document = json.loads((source / name).read_text())
    document["features"][0]["display_name"] = "Changed"
    (target / name).write_text(json.dumps(document))
    with pytest.raises(FoundryError) as error:
        native_path_binding(tmp_path, FEATURE)
    assert error.value.code == "COMMAND4_NATIVE_SOURCE_INVALID"
