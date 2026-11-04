from __future__ import annotations

import copy
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import CORE_PACK_ID, CORE_PACK_VERSION, Database, canonical_json, sha256_bytes, sha256_json
from content_packs.identity import compute_payload_identity

from .handoff import CATALOG_PATHS, FoundationHandoff, FoundationHandoffError
from .semantic import (
    PATH_TO_RECORD_ID,
    normalized_stage_progression,
    validate_foundation_handoff,
)


FOUNDATION_PACK_ID = "tianxia.extension.foundation46.rc2"
FOUNDATION_PACK_VERSION = "1.0.0-foundation46.rc2"
FAMILY_RECORD_PREFIX = "tianxia.foundation.family."
EXPRESSION_RECORD_PREFIX = "tianxia.foundation.expression."
PACK_SOURCE_PATHS = {
    logical_name: f"sources/foundation46/{Path(handoff_path).name}"
    for logical_name, handoff_path in CATALOG_PATHS.items()
}


@dataclass(frozen=True)
class FoundationPackPlan:
    pack_id: str
    version: str
    handoff: FoundationHandoff
    semantic_report: dict[str, Any]
    record_blueprints: tuple[dict[str, Any], ...]
    source_payload: dict[str, bytes]
    generated_payload: dict[str, bytes]
    replacement_map: dict[str, Any] | None

    @property
    def selectable(self) -> bool:
        return bool(self.semantic_report["summary"]["selectable_after_validation"])


def family_record_id(family_id: str) -> str:
    return FAMILY_RECORD_PREFIX + family_id


def expression_record_id(expression_id: str) -> str:
    return EXPRESSION_RECORD_PREFIX + expression_id


def load_pinned_core_foundation_authorities(
    db: Database,
    *,
    pack_id: str = CORE_PACK_ID,
    pack_version: str = CORE_PACK_VERSION,
) -> tuple[dict[str, Any], ...]:
    """Load exact immutable core Foundation authority rows from the catalog.

    Nothing is matched by an unverified display string alone: each returned row
    carries the exact record, record hash, pack ID/version, and pack hash that a
    project must lock for replacement authority to apply.
    """

    with db.connection() as conn:
        pack = conn.execute(
            "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
            (pack_id, pack_version),
        ).fetchone()
        rows = conn.execute(
            """SELECT record_id,record_hash,pack_id,pack_version,data_json
               FROM catalog_records
               WHERE content_type='foundation' AND pack_id=? AND pack_version=? AND selected_authority=1
               ORDER BY record_id""",
            (pack_id, pack_version),
        ).fetchall()
    if pack is None:
        raise FoundationHandoffError(
            "FOUNDATION_CORE_PACK_NOT_INSTALLED",
            "Pinned core pack must be installed before exact Foundation replacements can be generated.",
            pack_id=pack_id,
            pack_version=pack_version,
        )
    if len(rows) != 30:
        raise FoundationHandoffError(
            "FOUNDATION_CORE_AUTHORITY_COUNT_MISMATCH",
            "Pinned core catalog must expose exactly 30 selected flat Foundation authority rows.",
            expected=30,
            actual=len(rows),
            pack_id=pack_id,
            pack_version=pack_version,
        )
    authorities: list[dict[str, Any]] = []
    for row in rows:
        record = json.loads(row["data_json"])
        binding = record.get("content_binding") or {}
        if (
            record.get("record_id") != row["record_id"]
            or record.get("record_hash") != row["record_hash"]
            or binding.get("pack_id") != row["pack_id"]
            or binding.get("pack_version") != row["pack_version"]
            or binding.get("pack_hash") != pack["pack_hash"]
            or sha256_json({key: value for key, value in record.items() if key != "record_hash"}) != row["record_hash"]
        ):
            raise FoundationHandoffError(
                "FOUNDATION_CORE_AUTHORITY_IDENTITY_INVALID",
                "A pinned core Foundation row failed exact identity reconciliation.",
                record_id=row["record_id"],
            )
        authorities.append({
            "record_id": row["record_id"],
            "record_hash": row["record_hash"],
            "pack_id": row["pack_id"],
            "pack_version": row["pack_version"],
            "pack_hash": pack["pack_hash"],
            "record": record,
        })
    return tuple(authorities)


def _alias_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def build_foundation_replacement_map(
    handoff: FoundationHandoff,
    core_foundation_authorities: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    alias_rows = handoff.legacy_alias_map["aliases"]
    aliases_by_family = {row["family_id"]: row for row in alias_rows}
    token_to_families: dict[str, set[str]] = {}
    for family_id, row in aliases_by_family.items():
        values = [family_id, row["family_name"], *(row.get("aliases") or [])]
        for value in values:
            token_to_families.setdefault(_alias_token(value), set()).add(family_id)

    replacements: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    matched_families: set[str] = set()
    seen_sources: set[tuple[str, str, str, str]] = set()
    for authority in sorted(core_foundation_authorities, key=lambda row: row["record_id"]):
        record = authority.get("record") or {}
        if record.get("content_type") != "foundation":
            raise FoundationHandoffError("FOUNDATION_REPLACEMENT_SOURCE_TYPE_INVALID", "Replacement source must be a core foundation record.", record_id=authority.get("record_id"))
        if record.get("record_id") != authority.get("record_id") or record.get("record_hash") != authority.get("record_hash"):
            raise FoundationHandoffError("FOUNDATION_REPLACEMENT_SOURCE_IDENTITY_INVALID", "Replacement source record identity is inconsistent.", record_id=authority.get("record_id"))
        binding = record.get("content_binding") or {}
        expected_binding = (authority.get("pack_id"), authority.get("pack_version"), authority.get("pack_hash"))
        if (binding.get("pack_id"), binding.get("pack_version"), binding.get("pack_hash")) != expected_binding:
            raise FoundationHandoffError("FOUNDATION_REPLACEMENT_SOURCE_PACK_BINDING_INVALID", "Replacement source pack identity is inconsistent.", record_id=authority.get("record_id"))
        source_key = (authority["record_id"], authority["record_hash"], authority["pack_id"], authority["pack_version"])
        if source_key in seen_sources:
            raise FoundationHandoffError("FOUNDATION_REPLACEMENT_SOURCE_DUPLICATE", "Core Foundation authority row was supplied more than once.", record_id=authority["record_id"])
        seen_sources.add(source_key)

        source_values = [authority["record_id"], str(record.get("display_name") or ""), *(record.get("aliases") or [])]
        candidates: set[str] = set()
        matched_tokens: list[str] = []
        for value in source_values:
            token = _alias_token(value)
            families = token_to_families.get(token, set())
            if families:
                candidates.update(families)
                matched_tokens.append(token)
        if len(candidates) != 1:
            raise FoundationHandoffError(
                "FOUNDATION_REPLACEMENT_ALIAS_MATCH_INVALID",
                "Each pinned core Foundation must match exactly one legacy alias family.",
                record_id=authority["record_id"],
                candidates=sorted(candidates),
                source_values=source_values,
            )
        family_id = next(iter(candidates))
        if family_id in matched_families:
            raise FoundationHandoffError("FOUNDATION_REPLACEMENT_FAMILY_DUPLICATE", "Two core Foundations matched the same legacy family.", family_id=family_id)
        matched_families.add(family_id)
        alias = aliases_by_family[family_id]
        target_expression_id = alias["default_expression_id"]
        target_record_id = expression_record_id(target_expression_id)
        replacement_id = f"tianxia.foundation.replacement.{family_id}"
        source_identity = {
            "record_id": authority["record_id"],
            "record_hash": authority["record_hash"],
            "pack_id": authority["pack_id"],
            "pack_version": authority["pack_version"],
            "pack_hash": authority["pack_hash"],
        }
        replacements.append({
            "replacement_id": replacement_id,
            "source": source_identity,
            "target_record_id": target_record_id,
            "mode": "replace_in_selection",
            "reason": "Replace the exact pinned flat core Foundation with its legacy-alias default Path-specific Foundation expression for projects locking this extension.",
        })
        audit_rows.append({
            "replacement_id": replacement_id,
            "source": source_identity,
            "matched_family_id": family_id,
            "matched_alias_tokens": sorted(set(matched_tokens)),
            "default_expression_id": target_expression_id,
            "target_record_id": target_record_id,
        })

    if len(replacements) != 30 or len(matched_families) != 30:
        raise FoundationHandoffError(
            "FOUNDATION_REPLACEMENT_COVERAGE_MISMATCH",
            "Replacement map must cover all 30 pinned core Foundations exactly once.",
            replacement_count=len(replacements),
            matched_family_count=len(matched_families),
        )
    replacement_map = {
        "schema_version": "TianxiaFoundry.FoundationReplacementMap.v1",
        "replacement_pack_id": FOUNDATION_PACK_ID,
        "replacement_pack_version": FOUNDATION_PACK_VERSION,
        "replacements": replacements,
    }
    audit = {
        "schema_version": "TianxiaFoundry.FoundationReplacementAudit.v1",
        "source_pack": {
            "pack_id": core_foundation_authorities[0]["pack_id"],
            "pack_version": core_foundation_authorities[0]["pack_version"],
            "pack_hash": core_foundation_authorities[0]["pack_hash"],
        },
        "source_foundation_count": len(core_foundation_authorities),
        "replacement_count": len(replacements),
        "matched_family_count": len(matched_families),
        "rows": audit_rows,
    }
    return replacement_map, audit


def _aliases(values: list[Any]) -> list[str]:
    return sorted({str(value) for value in values if isinstance(value, str) and value})


def _source_catalog_hashes(handoff: FoundationHandoff) -> dict[str, str]:
    return {name: blob.sha256 for name, blob in sorted(handoff.source_blobs.items())}


def _base_record(
    *,
    record_id: str,
    content_type: str,
    display_name: str,
    aliases: list[str],
    tags: list[str],
    source_id: str,
    source_path: str,
    source_hash: str,
    source_anchor: str,
    summary: str,
    legality: dict[str, Any],
    dependencies: list[str],
    grants: list[dict[str, Any]],
    execution_templates: list[dict[str, Any]],
    display_projection: dict[str, Any],
    compatibility: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": content_type,
        "display_name": display_name,
        "aliases": aliases,
        "tags": tags,
        "publication": {
            "status": "published",
            "published_version": FOUNDATION_PACK_VERSION,
            "replaced_by": None,
        },
        # The non-circular payload identity normalizes these two derived fields.
        "content_binding": {
            "pack_id": FOUNDATION_PACK_ID,
            "pack_version": FOUNDATION_PACK_VERSION,
            "pack_hash": "0" * 64,
        },
        "source": {
            "source_id": source_id,
            "path": source_path,
            "anchor": source_anchor,
            "source_hash": source_hash,
        },
        "summary": summary,
        "legality": legality,
        "dependencies": dependencies,
        "grants": grants,
        "execution_templates": execution_templates,
        "display_projection": display_projection,
        "compatibility": compatibility,
        "revision_history": [{
            "version": FOUNDATION_PACK_VERSION,
            "summary": "Deterministic native adapter projection of Foundation 46 RC2 without mechanic flattening.",
            "previous_record_hash": None,
        }],
        "regression_tests": [{
            "test_id": f"{record_id}.source-payload",
            "kind": "source-payload-hash",
            "input": {"source_anchor": source_anchor},
            "expected": {"preserved": True},
        }],
        "record_hash": "0" * 64,
    }


def _family_blueprint(
    handoff: FoundationHandoff,
    family: dict[str, Any],
    selection: dict[str, Any],
    alias: dict[str, Any],
) -> dict[str, Any]:
    family_id = family["family_id"]
    record_id = family_record_id(family_id)
    expression_ids = [row["expression_id"] for row in selection.get("expressions", [])]
    summary = str(family["one_sentence_fantasy"])
    full_description = "\n\n".join((
        summary,
        str(family["family_principle"]),
        f"Inheritance: {family['inheritance_type']}",
        "This is a family reference. Select a Path-specific Foundation expression, not the family row.",
    ))
    source_hashes = _source_catalog_hashes(handoff)
    compatibility = {
        "factory": {
            "producer": "HF05ZVK-R1H",
            "authority_classification": "published-extension",
            "selected_authority": True,
            "phase2_compilable": False,
            "reference_only": True,
            "unresolved_normalization_notes": [],
            "retained_prerequisites": [],
            "source_payload_hash": sha256_json(family),
            "source_catalog_hashes": source_hashes,
            "family_contract": {
                "family_id": family_id,
                "expression_record_ids": [expression_record_id(value) for value in expression_ids],
                "selection_rule": handoff.families_catalog["policies"]["expression_selection"],
            },
            "raw_projection": {
                "source_family": copy.deepcopy(family),
                "selection_index_entry": copy.deepcopy(selection),
                "legacy_alias_entry": copy.deepcopy(alias),
            },
        },
        "gm_screen": {
            "consumer": "HF05ZUI-R2K.3-HF2",
            "importable": False,
            "projection_role": "foundation-family-reference",
        },
    }
    return _base_record(
        record_id=record_id,
        content_type="foundation_family",
        display_name=family["name"],
        aliases=_aliases(list(alias.get("aliases") or []) + list(family.get("legacy_ids") or [])),
        tags=["foundation", "foundation-family", str(family["grade"]["label"]), family["catalog_code"]],
        source_id="tianxia.source.foundation46.families.rc2",
        source_path=PACK_SOURCE_PATHS["families"],
        source_hash=handoff.source_blobs["families"].sha256,
        source_anchor=f"/families/{family['catalog_number'] - 1}",
        summary=summary,
        legality={
            "acquisition_channels": ["reference-only"],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": None,
            "realm_rules": {"select_expression_instead": True},
            "source_cl": {"basis": "family-reference-only"},
            "suppression": {},
        },
        dependencies=[],
        grants=[],
        execution_templates=[],
        display_projection={
            "short_description": summary,
            "full_description": full_description,
            "surfaces": ["foundry-foundation-family-browser"],
            "sort_key": f"{family['catalog_number']:03d}:{family['name']}",
        },
        compatibility=compatibility,
    )


def _mechanic_target(kind: str, stable_id: str) -> str:
    return f"tianxia.foundation.{kind}.{stable_id}"


def _expression_templates(expression: dict[str, Any], normalized_stages: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    templates: list[dict[str, Any]] = []
    grants: list[dict[str, Any]] = []

    def add(template_id: str, template_type: str, payload: dict[str, Any], grant_type: str) -> None:
        if len(template_id) > 200:
            raise FoundationHandoffError("FOUNDATION_TEMPLATE_ID_TOO_LONG", "Generated template ID exceeds the native record limit.", template_id=template_id)
        templates.append({"template_id": template_id, "template_type": template_type, "payload": payload})
        grants.append({"grant_type": grant_type, "target_id": template_id, "operation": "create", "value": {"template_id": template_id}})

    resource = expression["resource"]
    resource_template_id = _mechanic_target("resource", resource["resource_id"])
    add(
        resource_template_id,
        "resource",
        {
            "resource_id": resource["resource_id"],
            "name": resource["name"],
            "maximum_by_stage": copy.deepcopy(resource["maximum_by_stage"]),
            "starting": resource["starting"],
            "generation": copy.deepcopy(resource["generation"]),
            "frequency": resource["frequency"],
            "retention": resource["retention"],
            "same_event_rule": resource["same_event_rule"],
            "anti_farming": copy.deepcopy(resource["anti_farming"]),
            "spend_feature_ids": copy.deepcopy(resource["spend_feature_ids"]),
            "source_resource": copy.deepcopy(resource),
        },
        "resource",
    )

    for passive in expression["passives"]:
        template_id = _mechanic_target("passive", passive["passive_id"])
        add(
            template_id,
            "passive_statistic",
            {
                "passive_id": passive["passive_id"],
                "name": passive["name"],
                "available_at": passive["available_at"],
                "effect": passive["effect"],
                "limits": passive["limits"],
                "source_passive": copy.deepcopy(passive),
            },
            "passive_statistic",
        )

    for feature in expression["features"]:
        template_id = _mechanic_target("feature", feature["feature_id"])
        add(
            template_id,
            "action",
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "available_at": feature["available_at"],
                "timing": feature["timing"],
                "action_type": feature["action_type"],
                "cost": feature["cost"],
                "trigger": feature["trigger"],
                "range": feature["range"],
                "target": feature["target"],
                "resolution": feature["attack_or_save"],
                "effect": feature["effect"],
                "failure": {
                    "classification": "source-does-not-print-a-separate-failure-field",
                    "resolution_source_field": "attack_or_save",
                    "source_value": feature["attack_or_save"],
                    "rule": "Apply no unprinted failure rider.",
                },
                "duration": feature["duration"],
                "limits": feature["limits"],
                "counterplay": feature["counterplay"],
                "source_feature": copy.deepcopy(feature),
            },
            "action",
        )

    state_collections = (
        ("burden", [expression["burden"]]),
        ("injury", expression["injuries"]),
        ("strain", expression["strains"]),
        ("deviation", expression["deviations"]),
    )
    for state_kind, rows in state_collections:
        for index, state in enumerate(rows):
            stable_id = state.get("id") or f"{expression['expression_id']}_{state_kind}_{index}"
            template_id = _mechanic_target(state_kind, stable_id)
            add(
                template_id,
                "state",
                {"state_kind": state_kind, "source_state": copy.deepcopy(state), **copy.deepcopy(state)},
                "state",
            )

    procedure_collections = (
        ("repair", expression["repair_procedures"]),
        ("advancement", expression["advancement_challenges"]),
    )
    for procedure_kind, rows in procedure_collections:
        for index, procedure in enumerate(rows):
            stable_id = procedure.get("procedure_id") or f"{expression['expression_id']}_{procedure_kind}_{index}"
            template_id = _mechanic_target("procedure", stable_id)
            add(
                template_id,
                "procedure",
                {"procedure_kind": procedure_kind, "source_procedure": copy.deepcopy(procedure), **copy.deepcopy(procedure)},
                "procedure",
            )

    expression_id = expression["expression_id"]
    add(
        f"tianxia.foundation.stage-progression.{expression_id}",
        "procedure",
        {
            "procedure_kind": "foundation-stage-progression",
            "controlling_rule": "cumulative from passives[].available_at and features[].available_at",
            "normalized_stage_progression": copy.deepcopy(normalized_stages),
            "source_stage_progression": copy.deepcopy(expression["stage_progression"]),
        },
        "procedure",
    )
    add(
        f"tianxia.foundation.affinity.{expression_id}",
        "permission",
        {
            "permission_kind": "foundation-sphere-affinity",
            "grants_sphere": False,
            "source_affinity": copy.deepcopy(expression["affinity"]),
        },
        "permission",
    )
    add(
        f"tianxia.foundation.suppression.{expression_id}",
        "modifier",
        {
            "modifier_kind": "foundation-realm-suppression",
            "source_realm_suppression": copy.deepcopy(expression["realm_suppression"]),
        },
        "modifier",
    )
    if expression["aura_progression"] is not None:
        add(
            f"tianxia.foundation.aura.{expression_id}",
            "modifier",
            {"modifier_kind": "foundation-aura-progression", "source_aura_progression": copy.deepcopy(expression["aura_progression"])},
            "modifier",
        )
    if expression["domain_seed"] is not None:
        add(
            f"tianxia.foundation.domain-seed.{expression_id}",
            "permission",
            {"permission_kind": "domain-seed-not-domain-grant", "grants_domain": False, "source_domain_seed": copy.deepcopy(expression["domain_seed"])},
            "permission",
        )
    return templates, grants


def _expression_blueprint(
    handoff: FoundationHandoff,
    expression: dict[str, Any],
    *,
    expression_index: int,
    family: dict[str, Any],
    family_decision: dict[str, Any],
    selection_expression: dict[str, Any],
    readable: dict[str, Any],
    alias: dict[str, Any],
    repair_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    expression_id = expression["expression_id"]
    record_id = expression_record_id(expression_id)
    path = expression["path"]
    path_record_id = PATH_TO_RECORD_ID[path]
    normalized_stages = normalized_stage_progression(expression)
    templates, grants = _expression_templates(expression, normalized_stages)
    identity = expression["identity"]
    summary = str(identity["one_sentence_fantasy"])
    player_summary = "\n".join(f"- {row}" for row in identity["player_summary"])
    full_description = f"{identity['what_it_is']}\n\n{player_summary}"
    source_hashes = _source_catalog_hashes(handoff)
    raw_projection = {
        "source_expression": copy.deepcopy(expression),
        "source_family": copy.deepcopy(family),
        "family_expression_decision": copy.deepcopy(family_decision),
        "selection_index_expression": copy.deepcopy(selection_expression),
        "readable_projection": copy.deepcopy(readable),
        "legacy_alias_entry": copy.deepcopy(alias),
    }
    compatibility = {
        "factory": {
            "producer": "HF05ZVK-R1H",
            "authority_classification": "published-extension",
            "selected_authority": True,
            "phase2_compilable": False,
            "native_content_type": "foundation_expression",
            "unresolved_normalization_notes": [],
            "retained_prerequisites": [],
            "source_payload_hash": sha256_json(expression),
            "source_catalog_hashes": source_hashes,
            "foundation_contract": {
                "family_id": expression["family_id"],
                "family_record_id": family_record_id(expression["family_id"]),
                "expression_id": expression_id,
                "expression_type": expression["expression_type"],
                "path": path,
                "path_record_id": path_record_id,
                "source_cl": expression["source_cl"],
                "normalized_stage_progression": normalized_stages,
                "normalization_receipts": [repair_receipt] if repair_receipt else [],
                "no_mechanic_flattening": True,
            },
            "raw_projection": raw_projection,
        },
        "gm_screen": {
            "consumer": "HF05ZUI-R2K.3-HF2",
            "importable": False,
            "projection_role": "foundation-expression-source",
            "required_surfaces": ["Foundation", "Actions", "Resources", "States", "Procedures"],
        },
    }
    return _base_record(
        record_id=record_id,
        content_type="foundation_expression",
        display_name=expression["display_name"],
        aliases=_aliases([expression_id, expression["catalog_code"], expression["display_name"]]),
        tags=["foundation", "foundation-expression", expression["expression_type"], path, expression["grade"], expression["catalog_code"]],
        source_id="tianxia.source.foundation46.expressions.rc2",
        source_path=PACK_SOURCE_PATHS["expressions"],
        source_hash=handoff.source_blobs["expressions"].sha256,
        source_anchor=f"/expressions/{expression_index}",
        summary=summary,
        legality={
            "acquisition_channels": ["foundation-expression-establishment"],
            "prerequisites": [{"kind": "path", "target_id": path_record_id, "operator": "requires"}],
            "incompatibilities": [],
            "minimum_cl": expression["source_cl"],
            "realm_rules": {
                "expression_selection": handoff.expressions_catalog["policies"]["expression_selection"],
                "method_gated_integration": handoff.expressions_catalog["policies"]["method_gated_integration"],
            },
            "source_cl": {"basis": "printed-expression-source-cl", "value": expression["source_cl"]},
            "suppression": copy.deepcopy(expression["realm_suppression"]),
        },
        dependencies=[family_record_id(expression["family_id"]), path_record_id],
        grants=grants,
        execution_templates=templates,
        display_projection={
            "short_description": summary,
            "full_description": full_description,
            "surfaces": ["foundry-foundation-expression-browser", "stage1-foundation-choice"],
            "sort_key": f"{expression['catalog_number']:03d}:{expression['catalog_code']}:{expression['display_name']}",
        },
        compatibility=compatibility,
    )


def build_foundation_pack_plan(
    handoff: FoundationHandoff,
    *,
    authorize_stage_repairs: bool = False,
    core_foundation_authorities: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> FoundationPackPlan:
    report = validate_foundation_handoff(handoff, authorize_stage_repairs=authorize_stage_repairs)
    if report["summary"]["blocker_count"]:
        raise FoundationHandoffError(
            "FOUNDATION_SEMANTIC_VALIDATION_FAILED",
            "Foundation handoff cannot become a selectable native pack until semantic blockers are resolved.",
            issues=report["issues"],
        )

    families = {row["family_id"]: row for row in handoff.families_catalog["families"]}
    selections = {row["family_id"]: row for row in handoff.selection_index["families"]}
    readables = {row["foundation_id"]: row for row in handoff.readable_projection["foundations"]}
    aliases = {row["family_id"]: row for row in handoff.legacy_alias_map["aliases"]}
    receipts = {row["expression_id"]: row for row in report["repair_receipts"]}
    selection_expressions = {
        row["expression_id"]: row
        for family in handoff.selection_index["families"]
        for row in family["expressions"]
    }

    blueprints: list[dict[str, Any]] = []
    for family in handoff.families_catalog["families"]:
        blueprints.append(_family_blueprint(handoff, family, selections[family["family_id"]], aliases[family["family_id"]]))
    for expression_index, expression in enumerate(handoff.expressions_catalog["expressions"]):
        family = families[expression["family_id"]]
        decision = family["expression_decisions"][expression["expression_type"]]
        blueprints.append(_expression_blueprint(
            handoff,
            expression,
            expression_index=expression_index,
            family=family,
            family_decision=decision,
            selection_expression=selection_expressions[expression["expression_id"]],
            readable=readables[expression["expression_id"]],
            alias=aliases[expression["family_id"]],
            repair_receipt=receipts.get(expression["expression_id"]),
        ))

    source_payload = {
        PACK_SOURCE_PATHS[name]: blob.data
        for name, blob in handoff.source_blobs.items()
    }
    replacement_map = None
    replacement_audit = None
    if core_foundation_authorities is not None:
        replacement_map, replacement_audit = build_foundation_replacement_map(handoff, core_foundation_authorities)

    generated_payload = {
        "provenance/foundation_handoff_identity.json": canonical_json({
            "schema_version": "TianxiaFoundry.FoundationHandoffIdentity.v1",
            "archive_name": handoff.archive_path.name,
            "archive_sha256": handoff.archive_sha256,
            "handoff_manifest_sha256": handoff.manifest_sha256,
            "checksum_manifest_sha256": handoff.checksum_manifest_sha256,
            "source_hashes": _source_catalog_hashes(handoff),
        }).encode("utf-8"),
        "tests/foundation_semantic_report.json": canonical_json(report).encode("utf-8"),
        "tests/foundation_normalization_receipts.json": canonical_json({
            "schema_version": "TianxiaFoundry.FoundationNormalizationReceiptSet.v1",
            "count": len(report["repair_receipts"]),
            "receipts": report["repair_receipts"],
        }).encode("utf-8"),
        "tests/foundation_pack_assertions.json": canonical_json({
            "schema_version": "TianxiaFoundry.FoundationPackAssertions.v1",
            "expected": {
                "family_records": 46,
                "expression_records": 113,
                "resources": 113,
                "passives": 339,
                "features": 340,
                "normalization_repairs": 9,
                "semantic_status": "PASS",
                "raw_source_payload_preserved": True,
                "core_foundation_replacements": 30,
            },
        }).encode("utf-8"),
    }
    if replacement_audit is not None:
        generated_payload["tests/foundation_replacement_audit.json"] = canonical_json(replacement_audit).encode("utf-8")
    return FoundationPackPlan(
        pack_id=FOUNDATION_PACK_ID,
        version=FOUNDATION_PACK_VERSION,
        handoff=handoff,
        semantic_report=report,
        record_blueprints=tuple(blueprints),
        source_payload=source_payload,
        generated_payload=generated_payload,
        replacement_map=replacement_map,
    )


def bind_native_records(plan: FoundationPackPlan, pack_hash: str) -> tuple[dict[str, Any], ...]:
    if len(pack_hash) != 64 or any(char not in "0123456789abcdef" for char in pack_hash):
        raise ValueError("pack_hash must be a lowercase SHA-256 digest")
    records: list[dict[str, Any]] = []
    for blueprint in plan.record_blueprints:
        record = copy.deepcopy(blueprint)
        record["content_binding"] = {
            "pack_id": plan.pack_id,
            "pack_version": plan.version,
            "pack_hash": pack_hash,
        }
        record["record_hash"] = sha256_json({key: value for key, value in record.items() if key != "record_hash"})
        records.append(record)
    return tuple(records)


def _record_payload(records: tuple[dict[str, Any], ...]) -> tuple[dict[str, bytes], set[str]]:
    payload: dict[str, bytes] = {}
    paths: set[str] = set()
    for record in records:
        path = f"records/{record['record_id']}.json"
        payload[path] = canonical_json(record).encode("utf-8")
        paths.add(path)
    return payload, paths


def validate_native_record_projection(plan: FoundationPackPlan, records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    family_sources = {row["family_id"]: row for row in plan.handoff.families_catalog["families"]}
    expression_sources = {row["expression_id"]: row for row in plan.handoff.expressions_catalog["expressions"]}
    family_records = {row["record_id"]: row for row in records if row.get("content_type") == "foundation_family"}
    expression_records = {row["record_id"]: row for row in records if row.get("content_type") == "foundation_expression"}
    if len(family_records) != 46 or len(expression_records) != 113:
        issues.append({"code": "FOUNDATION_NATIVE_RECORD_COUNT_MISMATCH"})

    for family_id, source in family_sources.items():
        record = family_records.get(family_record_id(family_id))
        if record is None:
            issues.append({"code": "FOUNDATION_NATIVE_FAMILY_MISSING", "family_id": family_id})
            continue
        raw = record["compatibility"]["factory"]["raw_projection"].get("source_family")
        if raw != source or record["compatibility"]["factory"].get("source_payload_hash") != sha256_json(source):
            issues.append({"code": "FOUNDATION_NATIVE_FAMILY_SOURCE_LOSS", "family_id": family_id})

    for expression_id, source in expression_sources.items():
        record = expression_records.get(expression_record_id(expression_id))
        if record is None:
            issues.append({"code": "FOUNDATION_NATIVE_EXPRESSION_MISSING", "expression_id": expression_id})
            continue
        factory = record["compatibility"]["factory"]
        if factory["raw_projection"].get("source_expression") != source or factory.get("source_payload_hash") != sha256_json(source):
            issues.append({"code": "FOUNDATION_NATIVE_EXPRESSION_SOURCE_LOSS", "expression_id": expression_id})
        contract = factory["foundation_contract"]
        if contract.get("path") != source["path"] or contract.get("expression_type") != source["expression_type"]:
            issues.append({"code": "FOUNDATION_NATIVE_PATH_TYPE_LOSS", "expression_id": expression_id})
        if contract.get("normalized_stage_progression") != normalized_stage_progression(source):
            issues.append({"code": "FOUNDATION_NATIVE_STAGE_NORMALIZATION_MISMATCH", "expression_id": expression_id})
        templates = record.get("execution_templates") or []
        resources = [row for row in templates if row.get("template_type") == "resource"]
        passives = [row for row in templates if row.get("template_type") == "passive_statistic"]
        actions = [row for row in templates if row.get("template_type") == "action"]
        if len(resources) != 1 or resources[0]["payload"].get("source_resource") != source["resource"]:
            issues.append({"code": "FOUNDATION_NATIVE_RESOURCE_LOSS", "expression_id": expression_id})
        if [row["payload"].get("source_passive") for row in passives] != source["passives"]:
            issues.append({"code": "FOUNDATION_NATIVE_PASSIVE_LOSS", "expression_id": expression_id})
        if [row["payload"].get("source_feature") for row in actions] != source["features"]:
            issues.append({"code": "FOUNDATION_NATIVE_FEATURE_LOSS", "expression_id": expression_id})
        expected_dependencies = {family_record_id(source["family_id"]), PATH_TO_RECORD_ID[source["path"]]}
        if set(record.get("dependencies") or []) != expected_dependencies:
            issues.append({"code": "FOUNDATION_NATIVE_DEPENDENCY_LOSS", "expression_id": expression_id})

    return {
        "schema_version": "TianxiaFoundry.FoundationNativeProjectionReport.v1",
        "summary": {"status": "PASS" if not issues else "FAIL", "issue_count": len(issues)},
        "counts": {"families": len(family_records), "expressions": len(expression_records)},
        "issues": issues,
    }


def build_native_pack_bytes(plan: FoundationPackPlan) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Build the final payload and manifest under ContentPackPayloadIdentity.v3."""

    if plan.replacement_map is None or len(plan.replacement_map.get("replacements") or []) != 30:
        raise FoundationHandoffError(
            "FOUNDATION_REPLACEMENT_MAP_REQUIRED",
            "A final native Foundation pack requires exact replacement authority for all 30 pinned core Foundations.",
        )
    replacement_path = "replacements/foundations.json"
    replacement_bytes = canonical_json(plan.replacement_map).encode("utf-8")
    source_ids = {
        "families": "tianxia.source.foundation46.families.rc2",
        "expressions": "tianxia.source.foundation46.expressions.rc2",
        "selection_index": "tianxia.source.foundation46.selection-index.rc2",
        "readable_projection": "tianxia.source.foundation46.readable-projection.rc2",
        "legacy_alias_map": "tianxia.source.foundation46.legacy-alias-map.rc2",
    }
    source_rows = [
        {
            "source_id": source_ids[name],
            "path": PACK_SOURCE_PATHS[name],
            "sha256": plan.handoff.source_blobs[name].sha256,
            "license_note": "User-supplied Tianxia Foundation 46 RC2 authority handoff; exact bytes preserved.",
        }
        for name in sorted(source_ids)
    ]

    def manifest_contract_seed(
        records: tuple[dict[str, Any], ...],
        current_payload: dict[str, bytes],
        identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_payload, _ = _record_payload(records)
        return {
            "schema_version": "TianxiaFoundry.ContentPackManifest.v1",
            "pack_id": plan.pack_id,
            "name": "Tianxia Foundation 46 RC2 - Native Expression Catalog",
            "version": plan.version,
            "state": "published",
            "publisher": {"name": "Local Tianxia Content Authority", "contact": "local exact-digest trust required"},
            "released_at": None,
            "compatibility": {
                "foundry": ">=0.3.1B-HF1",
                "project_schema": "TianxiaFoundry.CharacterProject.v1",
                "catalog_schema": "TianxiaFoundry.RulesCatalogRecord.v1",
                "factory_producers": [],
                "gm_screen_consumers": [],
            },
            "dependencies": [{
                "pack_id": "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2",
                "version_range": "==2.9.3",
                "optional": False,
            }],
            "conflicts": [],
            "records": [
                {
                    "record_id": record["record_id"],
                    "content_type": record["content_type"],
                    "path": f"records/{record['record_id']}.json",
                    "sha256": sha256_bytes(record_payload[f"records/{record['record_id']}.json"]),
                }
                for record in records
            ],
            "sources": source_rows,
            "tests": {
                "inventory": [
                    {"test_id": "foundation46.semantic", "path": "tests/foundation_semantic_report.json"},
                    {"test_id": "foundation46.normalization", "path": "tests/foundation_normalization_receipts.json"},
                    {"test_id": "foundation46.assertions", "path": "tests/foundation_pack_assertions.json"},
                    {"test_id": "foundation46.native-projection", "path": "tests/foundation_native_projection_report.json"},
                ],
                "verdict": "PASS",
                "report_path": "tests/foundation_native_projection_report.json",
            },
            "migrations": [],
            "replacement_maps": [{"path": replacement_path, "sha256": sha256_bytes(replacement_bytes)}],
            "files": [
                {"path": path, "bytes": len(data), "sha256": sha256_bytes(data)}
                for path, data in sorted(current_payload.items())
            ],
            "manifest_contract_hash": identity["manifest_contract_hash"] if identity else "0" * 64,
            "content_hash": identity["content_hash"] if identity else "0" * 64,
            "revision_history": [{
                "version": plan.version,
                "summary": "First deterministic native 46-family/113-expression adapter release with nine explicit stage-progression repairs.",
            }],
        }

    initial_records = bind_native_records(plan, "0" * 64)
    initial_record_payload, record_paths = _record_payload(initial_records)
    payload = {**plan.source_payload, **plan.generated_payload, replacement_path: replacement_bytes, **initial_record_payload}
    initial_identity = compute_payload_identity(
        pack_id=plan.pack_id,
        version=plan.version,
        payload=payload,
        record_paths=record_paths,
        manifest=manifest_contract_seed(initial_records, payload),
    )
    final_records = bind_native_records(plan, initial_identity["content_hash"])
    projection_report = validate_native_record_projection(plan, final_records)
    if projection_report["summary"]["status"] != "PASS":
        raise FoundationHandoffError("FOUNDATION_NATIVE_PROJECTION_FAILED", "Native Foundation record projection lost source mechanics.", issues=projection_report["issues"])
    final_record_payload, final_record_paths = _record_payload(final_records)
    payload = {
        **plan.source_payload,
        **plan.generated_payload,
        replacement_path: replacement_bytes,
        "tests/foundation_native_projection_report.json": canonical_json(projection_report).encode("utf-8"),
        **final_record_payload,
    }
    # The projection report is opaque payload and must participate in identity,
    # so compute once more from the complete payload, then bind that hash.
    complete_identity = compute_payload_identity(
        pack_id=plan.pack_id,
        version=plan.version,
        payload=payload,
        record_paths=final_record_paths,
        manifest=manifest_contract_seed(final_records, payload),
    )
    final_records = bind_native_records(plan, complete_identity["content_hash"])
    final_record_payload, final_record_paths = _record_payload(final_records)
    payload.update(final_record_payload)
    verified_identity = compute_payload_identity(
        pack_id=plan.pack_id,
        version=plan.version,
        payload=payload,
        record_paths=final_record_paths,
        manifest=manifest_contract_seed(final_records, payload, complete_identity),
    )
    if verified_identity != complete_identity:
        raise FoundationHandoffError("FOUNDATION_PACK_IDENTITY_NONDETERMINISTIC", "Binding derived record hashes changed normalized pack identity.")

    file_rows = [
        {"path": path, "bytes": len(data), "sha256": sha256_bytes(data)}
        for path, data in sorted(payload.items())
    ]
    record_rows = [
        {
            "record_id": record["record_id"],
            "content_type": record["content_type"],
            "path": f"records/{record['record_id']}.json",
            "sha256": sha256_bytes(final_record_payload[f"records/{record['record_id']}.json"]),
        }
        for record in final_records
    ]
    source_ids = {
        "families": "tianxia.source.foundation46.families.rc2",
        "expressions": "tianxia.source.foundation46.expressions.rc2",
        "selection_index": "tianxia.source.foundation46.selection-index.rc2",
        "readable_projection": "tianxia.source.foundation46.readable-projection.rc2",
        "legacy_alias_map": "tianxia.source.foundation46.legacy-alias-map.rc2",
    }
    source_rows = [
        {
            "source_id": source_ids[name],
            "path": PACK_SOURCE_PATHS[name],
            "sha256": plan.handoff.source_blobs[name].sha256,
            "license_note": "User-supplied Tianxia Foundation 46 RC2 authority handoff; exact bytes preserved.",
        }
        for name in sorted(source_ids)
    ]
    manifest = {
        "schema_version": "TianxiaFoundry.ContentPackManifest.v1",
        "pack_id": plan.pack_id,
        "name": "Tianxia Foundation 46 RC2 - Native Expression Catalog",
        "version": plan.version,
        "state": "published",
        "publisher": {"name": "Local Tianxia Content Authority", "contact": "local exact-digest trust required"},
        "released_at": None,
        "compatibility": {
            "foundry": ">=0.3.1B-HF1",
            "project_schema": "TianxiaFoundry.CharacterProject.v1",
            "catalog_schema": "TianxiaFoundry.RulesCatalogRecord.v1",
            # HF2 supplies Foundry catalog and Stage 1 planning authority only.
            # Foundation execution is not yet projected into Factory candidates
            # or GM Screen models, so those compatibility claims stay empty
            # until Stage 2 and the consumer regression gate are implemented.
            "factory_producers": [],
            "gm_screen_consumers": [],
        },
        "dependencies": [{
            "pack_id": "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2",
            "version_range": "==2.9.3",
            "optional": False,
        }],
        "conflicts": [],
        "records": record_rows,
        "sources": source_rows,
        "tests": {
            "inventory": [
                {"test_id": "foundation46.semantic", "path": "tests/foundation_semantic_report.json"},
                {"test_id": "foundation46.normalization", "path": "tests/foundation_normalization_receipts.json"},
                {"test_id": "foundation46.assertions", "path": "tests/foundation_pack_assertions.json"},
                {"test_id": "foundation46.native-projection", "path": "tests/foundation_native_projection_report.json"},
            ],
            "verdict": "PASS",
            "report_path": "tests/foundation_native_projection_report.json",
        },
        "migrations": [],
        "replacement_maps": [{"path": replacement_path, "sha256": sha256_bytes(replacement_bytes)}],
        "files": file_rows,
        "manifest_contract_hash": verified_identity["manifest_contract_hash"],
        "content_hash": verified_identity["content_hash"],
        "revision_history": [{
            "version": plan.version,
            "summary": "First deterministic native 46-family/113-expression adapter release with nine explicit stage-progression repairs.",
        }],
    }
    return {**payload, "pack.json": canonical_json(manifest).encode("utf-8")}, manifest


def write_deterministic_foundation_pack(plan: FoundationPackPlan, destination: Path) -> dict[str, Any]:
    files, manifest = build_native_pack_bytes(plan)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return {
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "archive_sha256": sha256_bytes(destination.read_bytes()),
        "pack_id": manifest["pack_id"],
        "version": manifest["version"],
        "content_hash": manifest["content_hash"],
        "record_count": len(manifest["records"]),
        "file_count": len(manifest["files"]),
        "trust_requirement": f"TRUST_LOCAL_CONTENT_PACK:{sha256_bytes(destination.read_bytes())}",
    }
