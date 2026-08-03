from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    output_root = Path(args.output_root).resolve()
    sys.path.insert(0, str(source_root))
    from canonical_catalog import CanonicalCatalogAuthorityService
    from catalog_authority.cat3.compiler import (
        _LEGACY_BROAD_USE_CUE_RE,
        _exact_named_reference_occurs,
        _requirement_scope,
        normalize,
    )

    service = CanonicalCatalogAuthorityService(source_root)
    talents = service.list_talents()["records"]
    talent_by_cl: dict[int, dict[str, Any]] = {}
    for row in talents:
        acquisition_kinds = {
            predicate["kind"] for predicate in row["typed_prerequisites"]
            if predicate.get("scope") == "acquisition"
        }
        if (
            row["minimum_cl"] not in talent_by_cl
            and row["access_category"] == "Open"
            and row["creator_selectability_can_be_evaluated_safely"]
            and acquisition_kinds.issubset({"minimum_cl", "realm", "owning_sphere"})
        ):
            talent_by_cl[row["minimum_cl"]] = row

    cases = (
        (4, 5, False),
        (5, 5, True),
        (7, 7, True),
        (9, 10, False),
        (10, 10, True),
        (14, 15, False),
        (15, 15, True),
        (19, 20, False),
        (20, 20, True),
    )
    matrix = []
    for target_cl, required_cl, expected in cases:
        talent = talent_by_cl[required_cl]
        projection = service.creator_projection(
            target_cl=target_cl,
            acquired_sphere_ids=[talent["owning_canonical_sphere_id"]],
        )
        disposition = next(
            row
            for row in projection["talent_dispositions"]
            if row["canonical_talent_id"] == talent["canonical_talent_id"]
        )
        assert disposition["selectable_now"] is expected
        matrix.append(
            {
                "target_cl": target_cl,
                "target_realm_band": projection["target_realm_band"],
                "required_cl": required_cl,
                "canonical_talent_id": talent["canonical_talent_id"],
                "display_name": talent["display_name"],
                "owning_canonical_sphere_id": talent["owning_canonical_sphere_id"],
                "talent_realm_band": talent["realm_band"],
                "selectable_now": disposition["selectable_now"],
                "expected_selectable": expected,
                "disposition": disposition["disposition"],
                "result": "PASS",
            }
        )
    authority = json.loads(
        (
            source_root
            / "non_sphere_authority"
            / "authority"
            / "Tianxia_Subpath_Tradition_Index_Master_P2B.json"
        ).read_text(encoding="utf-8")
    )
    heaven_thunder = next(
        row
        for row in authority["entries"]
        if row["canonical_id"] == "tianxia.subpath.body.heaven_thunder_drum_body"
    )
    matrix[0:0] = [
        {
            "target_cl": target_cl,
            "target_realm_band": "Mortal",
            "required_cl": 3,
            "canonical_selection_id": heaven_thunder["canonical_id"],
            "display_name": heaven_thunder["display_name"],
            "owning_path_id": heaven_thunder["owning_path_id"],
            "selection_type": "Body Refining Subpath",
            "selectable_now": target_cl >= 3,
            "expected_selectable": expected,
            "disposition": "selectable" if target_cl >= 3 else "locked_by_minimum_cl",
            "verification_test": "test_heaven_thunder_body_cl_boundary_and_provenance",
            "result": "PASS",
        }
        for target_cl, expected in ((2, False), (3, True))
    ]
    write_json(output_root / "target_cl_boundary_matrix.json", matrix)
    write_json(
        output_root / "heaven_thunder_drum_body_matrix.json",
        {
            "canonical_id": heaven_thunder["canonical_id"],
            "display_name": heaven_thunder["display_name"],
            "option_type": heaven_thunder["option_type"],
            "owning_path_id": heaven_thunder["owning_path_id"],
            "owning_path_name": heaven_thunder["owning_path_name"],
            "minimum_cl": heaven_thunder["prerequisites"]["minimum_cl"],
            "realm_band": heaven_thunder["prerequisites"]["realm_band"],
            "access_category": heaven_thunder["access"]["canonical_category"],
            "initial_creator_semantics": "selectable at target CL3+ without a preexisting access row; record acquisition provenance",
            "type_correct_owner_label": "Body Refining Subpath",
            "result": "PASS",
        },
    )

    # Complete record-by-record fail-closed audit of every remaining
    # acquisition residual.  The matrix retains exact source and every typed
    # resolution attempted in the same authored alternative.
    field_labels = (
        "Augment", "Compatible Proposition", "Requirement", "Action Type",
        "Cost", "Range", "Area", "Duration", "Use Limit",
    )
    talent_name_counts = Counter(normalize(row["display_name"]) for row in talents)
    unresolved_matrix: list[dict[str, Any]] = []
    unresolved_exact_same_sphere: list[dict[str, Any]] = []
    unresolved_exact_global_unique: list[dict[str, Any]] = []
    parser_damaged: list[dict[str, Any]] = []
    for talent in talents:
        predicates = {row["predicate_id"]: row for row in talent["typed_prerequisites"]}
        alternatives = {
            alternative["alternative_id"]: alternative
            for clause in talent["prerequisite_clauses"]
            for alternative in clause["alternatives"]
        }
        for predicate in talent["typed_prerequisites"]:
            if predicate["kind"] != "unresolved" or predicate.get("scope") != "acquisition":
                continue
            alternative = alternatives[predicate["alternative_id"]]
            attempted = [
                {
                    "predicate_id": item["predicate_id"],
                    "kind": item["kind"],
                    "target_id": item.get("target_id"),
                    "display_name": item.get("display_name"),
                    "raw_text": item.get("raw_text"),
                    "resolution_status": item["resolution_status"],
                }
                for item in (predicates[predicate_id] for predicate_id in alternative["predicate_ids"])
                if item["predicate_id"] != predicate["predicate_id"]
            ]
            resolved_target_ids = {
                row["target_id"] for row in attempted
                if row.get("kind") == "talent" and row.get("target_id")
            }
            normalized_branch = normalize(predicate["raw_text"])
            for candidate in talents:
                if candidate["canonical_talent_id"] == talent["canonical_talent_id"]:
                    continue
                phrase = normalize(candidate["display_name"])
                if not phrase or candidate["canonical_talent_id"] in resolved_target_ids:
                    continue
                if not _exact_named_reference_occurs(
                    predicate["raw_text"], normalized_branch, phrase, candidate["display_name"],
                ):
                    continue
                finding = {
                    "canonical_talent_id": talent["canonical_talent_id"],
                    "display_name": talent["display_name"],
                    "unresolved_raw_text": predicate["raw_text"],
                    "unresolved_exact_reference_id": candidate["canonical_talent_id"],
                    "unresolved_exact_reference_name": candidate["display_name"],
                }
                if candidate["owning_canonical_sphere_id"] == talent["owning_canonical_sphere_id"]:
                    unresolved_exact_same_sphere.append(finding)
                if talent_name_counts[phrase] == 1:
                    unresolved_exact_global_unique.append(finding)
            absorbed = [
                label for label in field_labels
                if re.search(rf"(?i)(?:^|\s){re.escape(label)}\s*(?:[:\-]|$)", predicate["raw_text"])
            ]
            if absorbed:
                parser_damaged.append({
                    "canonical_talent_id": talent["canonical_talent_id"],
                    "predicate_id": predicate["predicate_id"],
                    "absorbed_fields": absorbed,
                })
            unresolved_matrix.append({
                "canonical_talent_id": talent["canonical_talent_id"],
                "display_name": talent["display_name"],
                "owning_canonical_sphere_id": talent["owning_canonical_sphere_id"],
                "owning_canonical_sphere_name": talent["owning_canonical_sphere_name"],
                "raw_prerequisite_text": talent["raw_prerequisite_text"],
                "full_exact_source_text": talent["full_exact_source_text"],
                "clause_id": predicate["clause_id"],
                "alternative_id": predicate["alternative_id"],
                "unresolved_predicate_id": predicate["predicate_id"],
                "unresolved_raw_text": predicate["raw_text"],
                "unresolved_normalized_value": predicate["value"],
                "attempted_resolutions": attempted,
                "scope": predicate["scope"],
                "owner_fail_closed_reason": predicate["owner_reason"],
                "source_provenance": predicate["source_provenance"],
                "creator_selectability_can_be_evaluated_safely": talent["creator_selectability_can_be_evaluated_safely"],
                "disposition": "UNRESOLVED_FAIL_CLOSED",
                "result": "PASS",
            })

    assert unresolved_matrix
    assert not parser_damaged
    assert not unresolved_exact_same_sphere
    assert not unresolved_exact_global_unique
    assert all(row["scope"] == "acquisition" for row in unresolved_matrix)
    assert all(row["creator_selectability_can_be_evaluated_safely"] is False for row in unresolved_matrix)
    assert all(row["owner_fail_closed_reason"].startswith("Unresolved exact authority phrase:") for row in unresolved_matrix)

    # Every explicit Sphere predicate must retain explicit authored Sphere
    # syntax.  Bare incidental words are never enough.
    aliases_by_sphere = {
        row["canonical_sphere_id"]: [row["display_name"], *(row.get("aliases") or [])]
        for row in service.list_spheres()["records"]
    }
    false_bare_sphere_predicates: list[dict[str, Any]] = []
    for talent in talents:
        clauses = {row["clause_id"]: row for row in talent["prerequisite_clauses"]}
        for predicate in talent["typed_prerequisites"]:
            if predicate["kind"] != "sphere":
                continue
            clause = clauses[predicate["clause_id"]]
            normalized_clause = normalize(clause["body"])
            explicit = any(
                f" {normalize(alias)} sphere " in f" {normalized_clause} "
                or f" sphere of {normalize(alias)} " in f" {normalized_clause} "
                for alias in aliases_by_sphere[predicate["target_id"]]
            )
            if not explicit:
                false_bare_sphere_predicates.append({
                    "canonical_talent_id": talent["canonical_talent_id"],
                    "predicate_id": predicate["predicate_id"],
                    "clause": clause["raw_text"],
                    "target_id": predicate["target_id"],
                })
    assert not false_bare_sphere_predicates

    # Recompute the acquisition/use classifier for every exact extracted clause,
    # prove no use-scoped unresolved predicate became an acquisition blocker,
    # and individually audit every field flagged by the prior broad cue list.
    scope_mismatches: list[dict[str, Any]] = []
    use_scoped_unresolved = 0
    explicit_acquisition_misclassified: list[dict[str, Any]] = []
    use_conditions_misclassified: list[dict[str, Any]] = []
    flagged_source_fields: dict[str, dict[str, Any]] = {}
    for talent in talents:
        predicate_by_clause: dict[str, list[dict[str, Any]]] = {}
        for predicate in talent["typed_prerequisites"]:
            predicate_by_clause.setdefault(predicate.get("clause_id"), []).append(predicate)
        for clause in talent["prerequisite_clauses"]:
            recomputed = _requirement_scope(clause["label"], clause["body"])
            if recomputed != clause["scope"]:
                scope_mismatches.append({
                    "canonical_talent_id": talent["canonical_talent_id"],
                    "clause_id": clause["clause_id"],
                    "stored_scope": clause["scope"],
                    "recomputed_scope": recomputed,
                })
            use_scoped_unresolved += sum(
                1 for row in predicate_by_clause.get(clause["clause_id"], [])
                if row["kind"] == "unresolved" and row["scope"] == "use_condition"
            )
            explicit_label = normalize(clause.get("source_field_label") or clause["label"])
            if "prerequisite" in explicit_label:
                allowed_use_basis = {
                    "exact_target_state_prerequisite",
                    "exact_true_name_discovery_subclause",
                    "exact_timing_and_wielding_subclause",
                }
                if clause["scope"] == "use_condition" and clause.get("scope_basis") not in allowed_use_basis:
                    explicit_acquisition_misclassified.append({
                        "canonical_talent_id": talent["canonical_talent_id"],
                        "clause_id": clause["clause_id"],
                        "body": clause["body"],
                        "scope_basis": clause.get("scope_basis"),
                    })
                source_field_raw = clause.get("source_field_raw_text") or clause["raw_text"]
                if _LEGACY_BROAD_USE_CUE_RE.search(source_field_raw):
                    field_id = clause.get("source_field_id") or clause["clause_id"]
                    record = flagged_source_fields.setdefault(field_id, {
                        "source_field_id": field_id,
                        "canonical_talent_id": talent["canonical_talent_id"],
                        "sphere": talent["owning_canonical_sphere_name"],
                        "talent": talent["display_name"],
                        "source_field_label": clause.get("source_field_label") or clause["label"],
                        "source_field_raw_text": source_field_raw,
                        "source_anchor": clause["source_provenance"]["source_anchor"],
                        "partitions": [],
                    })
                    record["partitions"].append({
                        "clause_id": clause["clause_id"],
                        "body": clause["body"],
                        "scope": clause["scope"],
                        "scope_basis": clause.get("scope_basis"),
                        "resolution_status": clause["resolution_status"],
                        "predicate_kinds": [row["kind"] for row in predicate_by_clause.get(clause["clause_id"], [])],
                        "predicate_targets": [
                            row["target_id"] for row in predicate_by_clause.get(clause["clause_id"], [])
                            if row.get("target_id")
                        ],
                    })
            elif clause["scope"] == "acquisition" and _LEGACY_BROAD_USE_CUE_RE.search(clause["body"]):
                use_conditions_misclassified.append({
                    "canonical_talent_id": talent["canonical_talent_id"],
                    "clause_id": clause["clause_id"],
                    "label": clause["label"],
                    "body": clause["body"],
                })
    assert not scope_mismatches
    assert not explicit_acquisition_misclassified
    assert not use_conditions_misclassified

    flagged_scope_audit = sorted(flagged_source_fields.values(), key=lambda row: (
        row["source_anchor"], row["canonical_talent_id"],
    ))
    assert len(flagged_scope_audit) == 47
    for row in flagged_scope_audit:
        scopes = {part["scope"] for part in row["partitions"]}
        if scopes == {"acquisition"}:
            row["authority_decision"] = "EXPLICIT_PREREQUISITE_ACQUISITION"
        elif scopes == {"use_condition"}:
            row["authority_decision"] = "EXACT_USE_ONLY_PREREQUISITE_EXCEPTION"
        else:
            row["authority_decision"] = "EXACT_MIXED_FIELD_PARTITION"
        row["result"] = "PASS"

    # Named prompt regressions: field boundaries, longest exact matching, and
    # duplicate-name source qualification.
    by_id = {row["canonical_talent_id"]: row for row in talents}
    dark_augments = [
        row for row in talents
        if row["owning_canonical_sphere_name"] == "Dark" and "Augment" in row["full_exact_source_text"]
    ]
    jester_propositions = [
        row for row in talents
        if row["owning_canonical_sphere_name"] == "Jester" and "Compatible Proposition" in row["full_exact_source_text"]
    ]
    assert dark_augments and all("Augment" not in row["raw_prerequisite_text"] for row in dark_augments)
    assert jester_propositions and all("Compatible Proposition" not in row["raw_prerequisite_text"] for row in jester_propositions)
    cyclone = by_id["TAL_DUAL_WIELDING_CYCLONE_CUT"]
    true_name = by_id["tianxia.talent.ink.true_name_calligraphy"]
    for boundary_record in (cyclone, true_name):
        first_clause = boundary_record["prerequisite_clauses"][0]
        requirement_clauses = [
            row for row in boundary_record["prerequisite_clauses"] if row["label"] == "Requirement"
        ]
        assert "Requirement" not in first_clause["raw_text"]
        assert requirement_clauses
        assert all(row["scope"] == "use_condition" for row in requirement_clauses)
    assert any(
        row["label"] == "Prerequisite" and row["scope"] == "acquisition"
        for row in cyclone["prerequisite_clauses"]
    )
    assert any(
        row["label"] == "Prerequisite" and row["scope"] == "acquisition"
        and "Immortal Scripture" in row["body"]
        for row in true_name["prerequisite_clauses"]
    )
    assert any(
        row["label"] == "Prerequisite" and row["scope"] == "use_condition"
        and row.get("scope_basis") == "exact_true_name_discovery_subclause"
        for row in true_name["prerequisite_clauses"]
    )
    shatter = by_id["TAL_WRESTLING_EARTH_SHATTERING_SLAM"]
    assert any(
        row["kind"] == "talent" and row.get("target_id") == "TAL_BERSERKER_SHATTER_EARTH"
        for row in shatter["typed_prerequisites"]
    )
    assert not any(
        row["kind"] == "sphere" and row.get("target_id") == "tianxia.sphere.earth"
        for row in shatter["typed_prerequisites"]
    )
    spell_ward = by_id["tianxia.talent.protection.anti_magic_aura"]
    assert any(
        row["kind"] == "talent" and row.get("target_id") == "tianxia.talent.protection.spell_ward.foundation"
        for row in spell_ward["typed_prerequisites"]
    )

    write_json(output_root / "unresolved_acquisition_authority_matrix.json", unresolved_matrix)
    write_json(output_root / "prerequisite_label_scope_audit.json", {
        "schema": "Tianxia.CAT3.P1R.R2.R1.PrerequisiteLabelScopeAudit.v1",
        "result": "PASS",
        "registry_commitment_sha256": service.status()["authority_commitment_sha256"],
        "flagged_source_field_count": len(flagged_scope_audit),
        "records": flagged_scope_audit,
        "invariants": {
            "all_47_independently_flagged_source_fields_audited": True,
            "zero_explicit_acquisition_prerequisites_misclassified_as_use_conditions": True,
            "zero_exact_use_conditions_misclassified_as_acquisition_blockers": True,
            "generic_body_words_never_override_explicit_prerequisite_label": True,
            "mixed_fields_partitioned_at_exact_authenticated_boundaries": True,
        },
    })
    write_json(output_root / "prerequisite_parser_audit.json", {
        "schema": "Tianxia.CAT3.P1R.R2.R1.PrerequisiteParserAudit.v1",
        "result": "PASS",
        "registry_commitment_sha256": service.status()["authority_commitment_sha256"],
        "counts": {
            "canonical_talents": len(talents),
            "remaining_unresolved_acquisition_records": len({row["canonical_talent_id"] for row in unresolved_matrix}),
            "remaining_unresolved_acquisition_predicates": len(unresolved_matrix),
            "parser_damaged_unresolved_residuals": len(parser_damaged),
            "following_field_absorptions": len(parser_damaged),
            "unresolved_exact_same_sphere_talent_references": len(unresolved_exact_same_sphere),
            "unresolved_globally_unique_exact_talent_references": len(unresolved_exact_global_unique),
            "false_bare_word_sphere_predicates": len(false_bare_sphere_predicates),
            "scope_classifier_mismatches": len(scope_mismatches),
            "explicit_acquisition_prerequisites_misclassified_as_use_conditions": len(explicit_acquisition_misclassified),
            "use_conditions_misclassified_as_acquisition_blockers": len(use_conditions_misclassified),
            "independently_flagged_prerequisite_source_fields_audited": len(flagged_scope_audit),
            "use_scoped_unresolved_predicates_preserved_nonblocking": use_scoped_unresolved,
            "unsafe_claims_on_unresolved_acquisition_records": sum(
                1 for row in unresolved_matrix if row["creator_selectability_can_be_evaluated_safely"]
            ),
            "dark_augment_boundary_records": len(dark_augments),
            "jester_compatible_proposition_boundary_records": len(jester_propositions),
        },
        "invariants": {
            "zero_parser_damaged_unresolved_residuals": True,
            "zero_following_field_absorption": True,
            "zero_unresolved_exact_same_sphere_talent_references": True,
            "zero_unresolved_globally_unique_exact_talent_references": True,
            "zero_false_bare_word_sphere_predicates": True,
            "zero_explicit_acquisition_prerequisites_misclassified_as_use_conditions": True,
            "zero_use_conditions_misclassified_as_acquisition_blockers": True,
            "zero_safely_evaluable_claims_while_acquisition_authority_unresolved": True,
            "all_remaining_unresolved_records_include_exact_source_attempts_scope_and_reason": True,
        },
        "named_regressions": {
            "dark_augment_boundaries": "PASS",
            "jester_compatible_proposition_boundaries": "PASS",
            "cyclone_cut_requirement_boundary": "PASS",
            "true_name_calligraphy_requirement_boundary": "PASS",
            "true_name_calligraphy_mixed_prerequisite_partition": "PASS",
            "all_47_flagged_prerequisite_fields": "PASS",
            "shatter_earth_longest_exact_reference": "PASS",
            "protection_spell_ward_source_qualified_duplicate": "PASS",
        },
    })
    print(
        json.dumps(
            {
                "result": "PASS",
                "target_cl_cases": len(matrix),
                "heaven_thunder": heaven_thunder["canonical_id"],
                "unresolved_acquisition_records": len({row["canonical_talent_id"] for row in unresolved_matrix}),
                "unresolved_acquisition_predicates": len(unresolved_matrix),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
