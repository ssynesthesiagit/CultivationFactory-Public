from __future__ import annotations

import inspect
import json
import os
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import FoundryError
from app.models import CanonicalCatalogChoiceLockRequest, CanonicalCreatorProjectionRequest
from canonical_catalog import CanonicalCatalogAuthorityService
from character_builder import CharacterBuilderService
from non_sphere_authority import NonSphereAuthorityService


ROOT = Path(__file__).resolve().parents[1]
BLOOD = "tianxia.sphere.blood"
FREE_BLOOD = "tianxia.talent.blood.blood_armament"
GATED = "tianxia.talent.blood.blood_puppet"


def _predicate(talent: dict, kind: str) -> dict:
    return next(row for row in talent["typed_prerequisites"] if row["kind"] == kind)


def _targets(
    talent: dict, predicate: dict, project_id: str, *, route: str = "post_creation_acquisition",
) -> dict:
    return {
        "canonical_content_id": talent["canonical_talent_id"],
        "binding_type": "predicate",
        "binding_id": predicate["predicate_id"],
        "catalog_record_commitment_sha256": talent["record_commitment_sha256"],
        "character_id": project_id,
        "issuance_route": route,
    }


def _projection(catalog: CanonicalCatalogAuthorityService, project_id: str, **overrides):
    values = {
        "target_cl": 7,
        "acquired_sphere_ids": [BLOOD],
        "free_talent_grants": {BLOOD: FREE_BLOOD},
        "ordinary_talent_ids": [GATED],
        "project_id": project_id,
        "character_id": project_id,
    }
    values.update(overrides)
    return catalog.creator_projection(**values)


def _disposition(projection: dict) -> dict:
    return next(row for row in projection["talent_dispositions"] if row["canonical_talent_id"] == GATED)


def _error_code(call) -> str:
    with pytest.raises(FoundryError) as exc:
        call()
    return exc.value.code


def test_catalog_evidence_negative_and_post_creation_positive_matrix(catalog_environment):
    db = catalog_environment["db"]
    project_id = str(uuid.uuid4())
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="CAT3 R2 evidence matrix",
        concept="Server evidence boundary proof.",
        target_cl=7,
        power_band="standard",
        source_reference="CAT3-P1R-R2 evidence acceptance",
        creation_mode="detailed",
        ability_scores={},
        selections={},
        sphere_priority_ids=[BLOOD],
        talent_priority_ids=[GATED],
        canonical_sphere_ids=[BLOOD],
        sphere_free_talent_grants={BLOOD: FREE_BLOOD},
        ordinary_talent_ids=[GATED],
        project_id_override=project_id,
    )
    pending = next(
        row for row in created["character_sheet"]["canonical_grant_plan"]["grant_accounting"]["acquisition_provenance"]
        if row["canonical_content_id"] == GATED
    )
    assert pending["source"] == "pending-trusted-initial-finalization"
    assert pending["recorded"] is False

    # A public exact-choice commit may freeze owner choices, but cannot carry
    # authority-shaped input and cannot issue an evidence row.  It is one-shot.
    with db.connection() as conn:
        evidence_before_choice_commit = conn.execute(
            "SELECT COUNT(*) FROM non_sphere_authority_evidence WHERE project_id=?", (project_id,),
        ).fetchone()[0]
    committed = builder.commit_catalog_choices(
        project_id,
        acquired_sphere_ids=[BLOOD],
        free_talent_grants={BLOOD: FREE_BLOOD},
        ordinary_talent_ids=[GATED],
    )
    with db.connection() as conn:
        evidence_after_choice_commit = conn.execute(
            "SELECT COUNT(*) FROM non_sphere_authority_evidence WHERE project_id=?", (project_id,),
        ).fetchone()[0]
    assert committed["evidence_issued"] is False
    assert evidence_after_choice_commit == evidence_before_choice_commit
    assert _error_code(lambda: builder.commit_catalog_choices(
        project_id,
        acquired_sphere_ids=[BLOOD],
        free_talent_grants={BLOOD: FREE_BLOOD},
        ordinary_talent_ids=[GATED],
    )) == "USER_LOCK_FIELD_IMMUTABLE"
    for authority_shaped_choice_payload in (
        {
            "acquired_sphere_ids": [BLOOD], "free_talent_grants": {BLOOD: FREE_BLOOD},
            "ordinary_talent_ids": [GATED], "allow_initial_provenance_recording": True,
        },
        {
            "acquired_sphere_ids": [BLOOD], "free_talent_grants": {BLOOD: FREE_BLOOD},
            "ordinary_talent_ids": [GATED], "issuance_route": "initial_character_finalization",
        },
        {
            "acquired_sphere_ids": [BLOOD], "free_talent_grants": {BLOOD: FREE_BLOOD},
            "ordinary_talent_ids": [GATED], "evidence": {"source_hash": "0" * 64},
        },
    ):
        with pytest.raises(ValidationError):
            CanonicalCatalogChoiceLockRequest.model_validate(authority_shaped_choice_payload)

    authority = NonSphereAuthorityService(db)
    catalog = CanonicalCatalogAuthorityService(ROOT, evidence_resolver=authority.resolve_evidence)
    talent = catalog.get_talent(GATED)
    access_predicate = _predicate(talent, "acquisition_provenance")
    minimum_predicate = _predicate(talent, "minimum_cl")
    exact_targets = _targets(talent, access_predicate, project_id)

    # No public request field, boolean, route label, or client object can turn
    # the pending initial plan into issued authority.
    assert "allow_initial_provenance_recording" not in inspect.signature(catalog.creator_projection).parameters
    assert "allow_initial_provenance_recording" not in CanonicalCreatorProjectionRequest.model_fields
    assert "issuance_route" not in CanonicalCreatorProjectionRequest.model_fields
    for payload in (
        {"allow_initial_provenance_recording": True},
        {"issuance_route": "initial_character_finalization"},
        {"acquisition_evidence": [{"source_hash": "0" * 64}]},
        {"acquisition_evidence_ids": [{"evidence_id": "nse_client", "source_hash": "0" * 64}]},
        {"acquisition_evidence_ids": [{"evidence_id": "nse_client", "source_hash": uuid.uuid4().hex * 2}]},
    ):
        with pytest.raises(ValidationError):
            CanonicalCreatorProjectionRequest.model_validate({"target_cl": 7, **payload})

    initial_label_only = _error_code(lambda: authority.commit_authority_event(
        project_id,
        "talent_acquisition_provenance",
        _targets(talent, access_predicate, project_id, route="initial_character_finalization"),
        idempotency_key="r2.public-route-label-cannot-issue",
    ))
    assert initial_label_only == "NS1R_INITIAL_CATALOG_EVIDENCE_ISSUANCE_FORBIDDEN"

    baseline = _projection(catalog, project_id)
    assert baseline["ready"] is False
    assert _disposition(baseline)["acquisition_provenance_required"] is True

    negative: dict[str, str] = {}
    negative["all_zero_source_hash"] = "REQUEST_SCHEMA_REJECTED_CLIENT_EVIDENCE_OBJECT"
    negative["random_source_hash"] = "REQUEST_SCHEMA_REJECTED_CLIENT_EVIDENCE_OBJECT"
    negative["client_initial_provenance_attempt"] = initial_label_only
    negative["self_supplied_talent_id"] = _error_code(lambda: _projection(
        catalog, project_id, acquisition_evidence_ids=[GATED],
    ))
    negative["unknown_evidence_id"] = _error_code(lambda: _projection(
        catalog, project_id, acquisition_evidence_ids=["nse_unknown_record"],
    ))

    wrong_type = authority.commit_authority_event(
        project_id, "equipment_authority", exact_targets,
        idempotency_key="r2.wrong-authority-type",
    )
    negative["wrong_authority_type"] = _error_code(lambda: _projection(
        catalog, project_id, acquisition_evidence_ids=[wrong_type["evidence_id"]],
    ))

    other_talent = next(
        row for row in catalog.list_talents()["records"]
        if row["canonical_talent_id"] != GATED
        and any(p["kind"] == "acquisition_provenance" and p["scope"] == "acquisition" for p in row["typed_prerequisites"])
    )
    other_predicate = _predicate(other_talent, "acquisition_provenance")
    wrong_content = authority.commit_authority_event(
        project_id, "talent_acquisition_provenance",
        _targets(other_talent, other_predicate, project_id),
        idempotency_key="r2.wrong-content",
    )
    wrong_content_projection = _projection(
        catalog, project_id, acquisition_evidence_ids=[wrong_content["evidence_id"]],
    )
    assert wrong_content_projection["ready"] is False
    negative["wrong_content_id"] = _disposition(wrong_content_projection)["disposition"]

    wrong_predicate = authority.commit_authority_event(
        project_id, "talent_acquisition_provenance",
        _targets(talent, minimum_predicate, project_id),
        idempotency_key="r2.wrong-predicate",
    )
    wrong_predicate_projection = _projection(
        catalog, project_id, acquisition_evidence_ids=[wrong_predicate["evidence_id"]],
    )
    assert wrong_predicate_projection["ready"] is False
    negative["wrong_predicate_or_clause"] = _disposition(wrong_predicate_projection)["disposition"]

    positive = authority.commit_authority_event(
        project_id, "talent_acquisition_provenance", exact_targets,
        idempotency_key="r2.authenticated-post-creation-positive",
    )
    accepted = _projection(catalog, project_id, acquisition_evidence_ids=[positive["evidence_id"]])
    assert accepted["ready"] is True
    assert _disposition(accepted)["selectable_now"] is True
    assert positive["creation_authority"] == "AUTHENTICATED_PROJECT_AUTHORITY_SERVICE"
    assert positive["targets"] == exact_targets

    negative["wrong_project"] = _error_code(lambda: catalog.creator_projection(
        target_cl=7,
        acquired_sphere_ids=[BLOOD],
        free_talent_grants={BLOOD: FREE_BLOOD},
        ordinary_talent_ids=[GATED],
        project_id=str(uuid.uuid4()),
        character_id=project_id,
        acquisition_evidence_ids=[positive["evidence_id"]],
    ))
    wrong_character = _projection(
        catalog, project_id, character_id=str(uuid.uuid4()),
        acquisition_evidence_ids=[positive["evidence_id"]],
    )
    assert wrong_character["ready"] is False
    negative["wrong_character"] = _disposition(wrong_character)["disposition"]

    revoked = authority.commit_authority_event(
        project_id, "talent_acquisition_provenance", exact_targets,
        idempotency_key="r2.revoked-evidence",
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE non_sphere_authority_evidence SET valid=0,revoked_at='CAT3-R2-TEST-REVOCATION' WHERE evidence_id=?",
            (revoked["evidence_id"],),
        )
    negative["revoked_evidence"] = _error_code(lambda: _projection(
        catalog, project_id, acquisition_evidence_ids=[revoked["evidence_id"]],
    ))

    stale = authority.commit_authority_event(
        project_id, "talent_acquisition_provenance", exact_targets,
        idempotency_key="r2.stale-source-evidence",
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE events SET event_hash=? WHERE project_id=? AND event_id=?",
            ("0" * 64, project_id, stale["source_identity"]),
        )
    negative["stale_source_evidence"] = _error_code(lambda: _projection(
        catalog, project_id, acquisition_evidence_ids=[stale["evidence_id"]],
    ))

    assert set(negative) == {
        "self_supplied_talent_id", "all_zero_source_hash", "random_source_hash",
        "unknown_evidence_id", "wrong_authority_type", "client_initial_provenance_attempt",
        "wrong_content_id", "wrong_predicate_or_clause", "wrong_project",
        "wrong_character", "revoked_evidence", "stale_source_evidence",
    }
    assert all(negative.values())

    report = {
        "schema": "TianxiaFactory.CAT3P1RR2EvidenceAuthorityMatrix.v1",
        "status": "PASS",
        "project_id": project_id,
        "public_initial_creation_bypass_rejected": True,
        "negative_matrix": negative,
        "positive_post_creation": {
            "evidence_id": positive["evidence_id"],
            "authority_type": positive["authority_type"],
            "targets": positive["targets"],
            "creation_authority": positive["creation_authority"],
            "accepted_by_creator_projection": True,
        },
        "positive_initial_creation": {
            "acceptance_source": "CAT3_P1R_R2_REAL_WINDOWS_CHROMIUM_ACCEPTANCE.json",
            "required_route": "initial_character_finalization",
            "status": "COVERED_BY_REAL_FINALIZATION_CHAIN",
        },
    }
    output = os.environ.get("CAT3_R2_EVIDENCE_MATRIX_OUTPUT")
    if output:
        path = Path(output).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
