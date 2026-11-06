"""The v3 bridge validates Method access events against the locked row they bound.

The non-Sphere authority service binds the exact ``project_locked_records``
row for the Method, while the projector serves ``METHOD-*`` ids through the
proof-bound registry projection for ``method_acquisition`` events.  Before
this regression the bridge compared the access event's binding against the
projection, so every Method access event failed at final projection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import FoundryError, sha256_json  # noqa: E402
from contracts.canonical import canonical_record_hash  # noqa: E402
from projector.v3_bridge import _validate_non_sphere_method_access_event  # noqa: E402

PROJECT_ID = "project-1"
PROOF_HASH = "e" * 64
IDEMPOTENCY_KEY = "cg1.method-access:run-1:METHOD-002"


def _locked_record(*, pack_id: str = "tianxia.core.factory.test", pack_version: str = "2.9.5", pack_hash: str = "f" * 64) -> dict:
    record = {
        "record_id": "METHOD-002",
        "content_type": "cultivation_method",
        "display_name": "Test Method",
        "publication": {"status": "published", "published_version": pack_version, "replaced_by": None},
        "content_binding": {"pack_id": pack_id, "pack_version": pack_version, "pack_hash": pack_hash},
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def _row(record: dict) -> dict:
    binding = record["content_binding"]
    return {
        "record_id": record["record_id"],
        "pack_id": binding["pack_id"],
        "pack_version": binding["pack_version"],
        "record_hash": record["record_hash"],
    }


def _access_event(record: dict) -> dict:
    binding = record["content_binding"]
    target = {
        "role": "method",
        "record_id": record["record_id"],
        "record_hash": record["record_hash"],
        "relationship_id": f"method:{record['record_id']}",
        "relationship_hash": sha256_json({"method_id": record["record_id"], "authority": {"method_id": record["record_id"]}}),
        "pack_id": binding["pack_id"],
        "pack_version": binding["pack_version"],
        "pack_hash": binding["pack_hash"],
        "source_id": record["record_id"],
        "source_hash": record["record_hash"],
        "source_anchor": "project_locked_records",
        "source_path": f"project_locked_records/{record['record_id']}",
        "causal_event_id": None,
    }
    proof = {
        "role": "project_lock_proof",
        "relationship_id": "project_lock_proof",
        "relationship_hash": PROOF_HASH,
        "record_id": "project_lock_proof",
        "record_hash": PROOF_HASH,
        "pack_id": "project.lock",
        "pack_version": "HF2",
        "pack_hash": PROOF_HASH,
        "source_id": "project_lock_proof",
        "source_hash": PROOF_HASH,
        "source_anchor": "immutable_hf2_project_lock",
        "source_path": "project_store/project_lock_proof",
        "causal_event_id": None,
    }
    targets = {
        "method_id": record["record_id"],
        "access_tier": "COMMON_OR_WANDERING_ACCESS",
        "route_type": "INHERITANCE",
        "route_label": "Inheritance",
        "owner_annotation": "Factory-constructed learning route: Inheritance",
        "source_reference": {"registry_schema": "test", "registry_version": "0.6", "method_record_sha256": "a" * 64, "source_evidence": []},
        "source_route_sha256": "b" * 64,
        "route_commitment_sha256": "c" * 64,
        "method_registry_commitment_sha256": "d" * 64,
    }
    operation_hash = sha256_json({
        "project_id": PROJECT_ID,
        "kind": "non_sphere_method_access",
        "details": targets,
        "amount_awarded": None,
        "idempotency_key": IDEMPOTENCY_KEY,
    })
    details = {
        **targets,
        "authority_type": "method_access",
        "amount_awarded": None,
        "creation_authority": "AUTHENTICATED_PROJECT_AUTHORITY_SERVICE",
        "operation_hash": operation_hash,
    }
    canonical_targets = [{
        key: target[key]
        for key in ("role", "record_id", "record_hash", "relationship_id", "relationship_hash", "pack_id", "pack_version", "pack_hash")
    }]
    return {
        "event_id": "nsae_" + operation_hash[:32],
        "legal_channel": "authenticated_project_authority_service",
        "subject": {"record_id": record["record_id"], "content_type": "non_sphere_authority", "display_name": "method_access"},
        "content_binding": {
            "pack_id": "project.locked.target-set",
            "pack_version": "1",
            "pack_hash": PROOF_HASH,
            "record_hash": sha256_json({"schema": "Tianxia.CompleteLockedTargetBinding.v1", "targets": canonical_targets}),
            "catalog_build_id": "catalog.unbuilt",
        },
        "idempotency_key": IDEMPOTENCY_KEY,
        "advancement": {
            "kind": "non_sphere_method_access",
            "details": details,
            "authority_bindings": [target, proof],
            "calculation": {"rule_id": "non_sphere_authority_commit", "trace": {"authenticated": True}},
        },
    }


def test_access_event_validates_against_the_locked_row_it_bound():
    record = _locked_record()
    _validate_non_sphere_method_access_event(_access_event(record), record, {"project_id": PROJECT_ID}, locked_row=_row(record))


def test_registry_projection_of_the_same_method_is_not_the_bound_target():
    """The defect: the projector served the registry projection for the id."""
    bound = _locked_record()
    projection = _locked_record(pack_id="tianxia.non_sphere.authority", pack_version="0.6", pack_hash="8" * 64)
    assert projection["record_hash"] != bound["record_hash"]
    with pytest.raises(FoundryError) as excinfo:
        _validate_non_sphere_method_access_event(_access_event(bound), projection, {"project_id": PROJECT_ID}, locked_row=_row(projection))
    assert excinfo.value.code == "PROJECTION_NON_SPHERE_AUTHORITY_INVALID"


def test_locked_row_drift_is_rejected_before_binding_comparison():
    record = _locked_record()
    drifted = dict(_row(record), record_hash="0" * 64)
    with pytest.raises(FoundryError) as excinfo:
        _validate_non_sphere_method_access_event(_access_event(record), record, {"project_id": PROJECT_ID}, locked_row=drifted)
    assert excinfo.value.code == "PROJECTION_NON_SPHERE_AUTHORITY_INVALID"
    assert "immutable project-locked row" in excinfo.value.message
