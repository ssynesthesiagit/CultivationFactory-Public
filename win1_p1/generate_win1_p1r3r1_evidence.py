from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_REL = "APP/catalog_authority/cat3/generated/catalog_authority.v1.json"
OLD_MEMBER = "SOURCE/TIANXIA_CAT3_P1R_SOURCE_CHECKPOINT/catalog_authority/cat3/generated/catalog_authority.v1.json"


def read_prior(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read(OLD_MEMBER))


def git_json(revision: str, path: str) -> dict:
    raw = subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=ROOT)
    return json.loads(raw)


def record_index(rows: list[dict], key: str) -> dict[str, dict]:
    return {row[key]: row for row in rows}


def provenance(record: dict) -> dict:
    return {
        "record_commitment_sha256": record.get("record_commitment_sha256"),
        "source_provenance": record.get("source_provenance"),
        "exact_heading": record.get("exact_heading"),
        "raw_prerequisite_text": record.get("raw_prerequisite_text"),
        "typed_prerequisites": record.get("typed_prerequisites"),
        "unresolved_reason": record.get("unresolved_reason"),
        "creator_selectability_can_be_evaluated_safely": record.get("creator_selectability_can_be_evaluated_safely"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-cat3-zip", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--base", default="6ca4b6f388e7399be6598578a612c20abd5b23b5")
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    prior = read_prior(args.prior_cat3_zip)
    base = git_json(args.base, CATALOG_REL)
    current = json.loads((ROOT / CATALOG_REL).read_text(encoding="utf-8"))

    prior_talents = record_index(prior["talents"], "canonical_talent_id")
    current_talents = record_index(current["talents"], "canonical_talent_id")
    base_auto = record_index(base["automatic_base_abilities"], "runtime_component_id")
    current_auto = record_index(current["automatic_base_abilities"], "runtime_component_id")
    removed_ids = sorted(set(prior_talents) - set(current_talents))
    added_ids = sorted(set(current_talents) - set(prior_talents))
    readiness = sorted(
        talent_id for talent_id in set(prior_talents) & set(current_talents)
        if prior_talents[talent_id].get("creator_selectability_can_be_evaluated_safely") is False
        and current_talents[talent_id].get("creator_selectability_can_be_evaluated_safely") is True
    )
    prior_unresolved = {key for key, value in prior_talents.items() if value.get("creator_selectability_can_be_evaluated_safely") is False}
    current_unresolved = {key for key, value in current_talents.items() if value.get("creator_selectability_can_be_evaluated_safely") is False}
    parent_hits = {}
    for removed_id in removed_ids:
        hits = []
        removed_name = prior_talents[removed_id]["display_name"]
        for parent in current["talents"]:
            for child in parent.get("child_options") or []:
                if child.get("display_name") == removed_name or child.get("preserved_legacy_id") == removed_id:
                    hits.append({"parent_talent_id": parent["canonical_talent_id"], "parent_record": provenance(parent), "child_option": child})
        parent_hits[removed_id] = hits

    promoted_auto = sorted(set(current_auto) - set(base_auto))
    delta = {
        "schema": "Tianxia.WIN1P1R3R1.CatalogAuthorityDelta.v1",
        "status": "PASS",
        "lineage": {
            "accepted_cat3_p1r_checkpoint": prior["registry_commitment_sha256"],
            "exact_pr_base": base["registry_commitment_sha256"],
            "candidate": current["registry_commitment_sha256"],
            "base_git_commit": args.base,
            "prior_package_sha256": hashlib.sha256(args.prior_cat3_zip.read_bytes()).hexdigest(),
            "prior_package_member": OLD_MEMBER,
        },
        "reported_movements": {
            "automatic_base_ability_unique_components": [base["counts"]["automatic_base_ability_unique_components"], current["counts"]["automatic_base_ability_unique_components"]],
            "canonical_talents": [prior["counts"]["canonical_talents"], current["counts"]["canonical_talents"]],
            "unresolved_acquisition_talents": [prior["counts"]["unresolved_acquisition_talents"], current["counts"]["unresolved_acquisition_talents"]],
        },
        "promoted_automatic_components": [
            {"runtime_component_id": key, "before": None, "after": current_auto[key], "reason": current_auto[key].get("reason")}
            for key in promoted_auto
        ],
        "removed_talent_identities": [
            {"talent_id": key, "before": prior_talents[key], "after_talent": None, "current_child_option_bindings": parent_hits[key],
             "disposition": "Exact authored subchoice under its current parent talent; not a standalone canonical Talent."}
            for key in removed_ids
        ],
        "resolved_acquisition_dispositions": [
            {"talent_id": key, "before": provenance(prior_talents[key]), "after": provenance(current_talents[key]),
             "disposition": "Prior unresolved acquisition was resolved by current typed prerequisite/source-provenance authority; no name-only inference."}
            for key in readiness
        ],
        "remaining_unresolved": [
            {"talent_id": key, "before": provenance(prior_talents[key]), "after": provenance(current_talents[key])}
            for key in sorted(current_unresolved)
        ],
        "assertions": {
            "six_and_only_six_automatic_components_promoted": len(promoted_auto) == 6,
            "automatic_components_removed_from_exact_base": sorted(set(base_auto) - set(current_auto)),
            "four_and_only_four_prior_talent_identities_removed": len(removed_ids) == 4,
            "no_talent_identity_added": added_ids,
            "every_removed_identity_has_exact_child_option_binding": all(parent_hits.values()),
            "exactly_209_prior_unresolved_records_resolved": len(readiness) == 209,
            "current_unresolved_is_exact_subset_of_prior": current_unresolved < prior_unresolved,
            "no_new_unresolved_talents": sorted(current_unresolved - prior_unresolved),
            "remaining_unresolved_count": len(current_unresolved),
        },
    }
    expected_auto = {
        "TAL_DAEMONIC_CULTIVATION_DEMON_SEED", "TAL_KARMA_INVOKE_THE_LEDGER", "TAL_KARMA_LEDGER_EYE",
        "TAL_KARMA_RECORD_THE_DEED", "TAL_KARMA_SETTLE_MINOR_ACCOUNT", "TAL_SOUND_SOUND_INITIATION",
    }
    if (set(promoted_auto) != expected_auto or len(removed_ids) != 4 or added_ids or len(readiness) != 209 or len(current_unresolved) != 15):
        raise RuntimeError(json.dumps({"promoted_auto": promoted_auto, "removed_ids": removed_ids, "added_ids": added_ids, "readiness": len(readiness), "current_unresolved": len(current_unresolved)}, sort_keys=True))
    (args.output_root / "CATALOG_AUTHORITY_DELTA.json").write_text(json.dumps(delta, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    authority_path = ROOT / "APP/non_sphere_authority/authority/Background_Core_Authority_v1.json"
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    occurrences = []
    bindings: dict[str, list[str]] = defaultdict(list)
    for background in authority["backgrounds"]:
        for ordinal, name in enumerate(background["origin_insight"]["suggested_options"], 1):
            bindings[name].append(background["background_id"])
            occurrences.append({
                "background_id": background["background_id"], "background_name": background["display_name"],
                "origin_insight_name": name, "ordinal": ordinal,
                "raw_authority": background["origin_insight"]["raw_authority"],
                "source_path": background["source"]["path"], "source_anchor": background["source"]["anchor"],
            })
    background = {
        "schema": "Tianxia.WIN1P1R3R1.BackgroundOriginInsightInventory.v1", "status": "PASS",
        "authority_file": authority_path.relative_to(ROOT).as_posix(),
        "authority_file_sha256": hashlib.sha256(authority_path.read_bytes()).hexdigest(),
        "classification_rule": "Only records whose accepted content_type is origin_insight and whose normalized visible name occurs in this accepted Background authority are classified Background-Origin.",
        "selection_legality": "This inventory is preference-only. The selected origin_insight_choice is separately hard-validated against the selected Background's related_choice_ids.",
        "occurrences": occurrences,
        "unique_choices": [{"origin_insight_name": name, "background_ids": sorted(ids), "binding_count": len(ids)} for name, ids in sorted(bindings.items())],
        "summary": {"backgrounds": len(authority["backgrounds"]), "source_occurrences": len(occurrences), "unique_origin_insights": len(bindings),
                    "duplicate_name_count": sum(len(ids) > 1 for ids in bindings.values()), "maximum_binding_count": max(map(len, bindings.values()))},
    }
    if len(bindings) != 50 or not any(len(ids) > 1 for ids in bindings.values()):
        raise RuntimeError("Background-Origin inventory does not match accepted authority")
    (args.output_root / "BACKGROUND_ORIGIN_INSIGHT_INVENTORY.json").write_text(json.dumps(background, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
