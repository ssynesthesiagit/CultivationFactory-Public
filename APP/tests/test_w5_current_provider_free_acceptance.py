from __future__ import annotations

from rec1_p1cr4_real_acceptance import METHOD_ID, PATH_IDS, SUBPATH_IDS, run_acceptance


def test_current_delegated_response_completes_provider_free_pipeline(tmp_path):
    """Prove the current model-facing contract through a loadable sheet.

    ``run_acceptance`` starts the real Manual Chat workflow, validates a
    deterministic preferred response against the sealed schema, uploads it
    through the production response-file boundary, finalizes two isolated
    builds, and verifies export/import/re-import without calling a provider.
    """

    report = run_acceptance(
        data_dir=tmp_path / "OwnerTestData",
        report_path=tmp_path / "current-provider-free-acceptance.json",
    )

    assert report["status"] == "PASS"
    assert report["response_schema"] == "TianxiaFoundry.DelegatedSelectionIntentResponse.v1"
    assert report["response_evidence"]["kind"] == "publication_safe_deterministic_equivalent"
    assert report["response_evidence"]["owner_private_response_bytes_embedded"] is False

    preview = report["preview"]
    assert preview["status"] == "READY_FOR_REVIEW"
    assert preview["project_unchanged"] is True
    assert preview["owner_projection_checks"]["method_identity_and_owner_provenance_visible"] is True
    assert preview["owner_projection_checks"]["both_path_owned_subpaths_visible"] is True
    assert preview["owner_projection_checks"]["insights_visible"] is True

    finalized = report["finalization"]
    assert finalized["status"] == "CLEAN_AND_FINALIZED"
    assert finalized["method_id"] == METHOD_ID
    assert finalized["paths"] == PATH_IDS
    assert finalized["subpaths"] == SUBPATH_IDS
    assert finalized["dry_run"]["deterministic"] is True
    assert finalized["dry_run"]["independent_compilations"] == 2
    assert finalized["package_members"]["checks"]["accepted_insights_survive_export"] is True
    assert finalized["import_reimport"]["first_status"] in {
        "IMPORTED",
        "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
    }
    assert finalized["import_reimport"]["second_status"] in {
        "ALREADY_INSTALLED_IDENTICAL",
        "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
    }
    assert finalized["import_reimport"]["character_sheet_semantic_equal"] is True
    assert finalized["import_reimport"]["gm_model_semantic_equal"] is True
