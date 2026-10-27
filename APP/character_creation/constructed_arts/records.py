"""Project-locked records for Factory-constructed arts.

A constructed art becomes a ``TianxiaFoundry.RulesCatalogRecord.v1`` row in
``project_locked_records`` under its own pack, the way an owner-confirmed
custom training source does.  The row is authenticated by re-derivation: the
record embeds the typed art, the builder rebuilds the record from that art and
the bytes must match, and the art's figures must recompile from the sealed
authority.  The pack ID alone never authorizes anything.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core import (
    CATALOG_GM_COMPATIBILITY_VERSION,
    FACTORY_VERSION,
    FoundryError,
    canonical_json,
    sha256_bytes,
    sha256_json,
)
from contracts.canonical import canonical_record_hash

from .forged_technique import (
    FORGED_TECHNIQUE_SCHEMA,
    compile_forged_technique,
    construct_forged_technique,
    forged_technique_id,
    normalize_forged_technique_request,
)
from .forging_authority import load_forging_authority
from .immortal_art import (
    IMMORTAL_ART_KIND,
    IMMORTAL_ART_PACK_VERSION,
    IMMORTAL_ART_SCHEMA,
    compile_immortal_art,
    construct_immortal_art,
    immortal_art_progression_child_hash,
    load_immortal_art_authority,
)
from .manual import (
    MANUAL_CHANNEL,
    MANUAL_PACK_ID,
    MANUAL_PACK_VERSION,
    MANUAL_SCHEMA,
    MANUAL_TRAINING_CHANNEL,
    RECORDED_ART_CHANNEL,
    RECORDED_ART_PACK_ID,
    RECORDED_ART_SCHEMA,
    construct_lineage_manual,
    normalize_lineage_manual_request,
)

CONSTRUCTED_ART_SCHEMA = "TianxiaFoundry.ConstructedArt.v1"
FORGED_TECHNIQUE_PACK_ID = "tianxia.project.factory_constructed.forged_technique"
FORGED_TECHNIQUE_PACK_VERSION = "1"
FORGED_TECHNIQUE_CHANNEL = "factory-constructed-forging"
FORGED_TECHNIQUE_CONTENT_TYPE = "forged_technique_component"
FACTORY_CONSTRUCTED_SOURCE_PATH = "FACTORY_CONSTRUCTED_ART"
IMMORTAL_ART_RECORD_PACK_ID = "tianxia.project.factory_constructed.immortal_art"
IMMORTAL_ART_RECORD_PACK_VERSION = "1"
IMMORTAL_ART_RECORD_CHANNEL = "factory-constructed-immortal-art"
IMMORTAL_ART_RECORD_CONTENT_TYPE = "immortal_art"
STARTING_KIT_PACK_ID = "tianxia.project.factory_constructed.starting_kit"
STARTING_KIT_PACK_VERSION = "1"
STARTING_KIT_CHANNEL = "factory-constructed-starting-kit"
STARTING_KIT_CONTENT_TYPE = "item"
STARTING_KIT_KIND = "starting_kit"
STARTING_KIT_SCHEMA = "TianxiaFoundry.ConstructedStartingKit.v1"
CONSTRUCTED_ART_PACK_IDS = frozenset({
    FORGED_TECHNIQUE_PACK_ID,
    MANUAL_PACK_ID,
    RECORDED_ART_PACK_ID,
    IMMORTAL_ART_RECORD_PACK_ID,
    STARTING_KIT_PACK_ID,
})


def _pack_hash(technique_id: str) -> str:
    return sha256_json({
        "schema": CONSTRUCTED_ART_SCHEMA,
        "pack_id": FORGED_TECHNIQUE_PACK_ID,
        "pack_version": FORGED_TECHNIQUE_PACK_VERSION,
        "technique_id": technique_id,
    })


def forged_technique_record_text(technique: Mapping[str, Any]) -> str:
    """Render the GM Guide §2.8.1 record as readable lines."""
    cp = technique["cp_cost"]
    complexity = technique["complexity"]
    lines = [
        f"{technique['name']} (Forged Technique, {technique['realm']}, CL {technique['cl_created']})",
        f"Base Form: {technique['base_form']['display_name']} ({technique['base_form']['use']})",
        f"Primary Sphere Effect: {technique['primary_sphere_effect']['talent_name']} ({technique['primary_sphere_effect']['sphere_name']})",
    ]
    if technique.get("secondary_sphere_effects"):
        lines.append("Secondary Sphere Effects: " + "; ".join(f"{row['talent_name']} ({row['sphere_name']})" for row in technique["secondary_sphere_effects"]))
    lines.append("Augments: " + (", ".join(row["display_name"] for row in technique.get("augments") or []) or "none"))
    lines.append("Drawbacks: " + (", ".join(row["display_name"] for row in technique.get("drawbacks") or []) or "none"))
    lines.append(f"Activation: {technique['action_type']}; CP cost {cp['final']} (base {cp['base_form']} + augments {cp['augments']} - drawbacks {cp['drawback_reduction']})")
    lines.append(f"Complexity {complexity['final']} of {complexity['realm_maximum']}; Spheres used {technique['spheres_used']}; Technique-Forging DC {technique['technique_forging_dc']}")
    lines.append(f"Research {technique['research_days']} days; materials {technique['material_cost_gp']} gp")
    lines.append(f"Target/range/area: {technique['target_range_area']}")
    lines.append(f"Attack/save/check: {technique['attack_save_check']}")
    lines.append(f"Effect: {technique['effect']['summary']}")
    if technique["effect"].get("primary_effect_text"):
        lines.append("Primary effect as printed:")
        lines.append(technique["effect"]["primary_effect_text"])
    lines.append(f"Duration: {technique['duration']}")
    if technique.get("limits"):
        lines.append("Limits: " + "; ".join(technique["limits"]))
    if technique.get("backlash"):
        lines.append(f"Backlash: {technique['backlash']['trigger']} -> {technique['backlash']['consequence']}")
    lines.append(f"Evolution state: {technique['evolution_state']}")
    return "\n".join(lines)


def build_forged_technique_record(technique: Mapping[str, Any]) -> dict[str, Any]:
    """Build the locked catalog record for one constructed Forged Technique."""
    if technique.get("schema") != FORGED_TECHNIQUE_SCHEMA or not isinstance(technique.get("technique_id"), str):
        raise FoundryError("FORGED_TECHNIQUE_SCHEMA_INVALID", "Only a typed Forged Technique can become a locked record.")
    technique = deepcopy(dict(technique))
    technique_id = technique["technique_id"]
    pack_hash = _pack_hash(technique_id)
    rule_id = f"{technique_id}.forged-technique-creation.v1"
    effects = [technique["primary_sphere_effect"], *technique.get("secondary_sphere_effects", [])]
    text = forged_technique_record_text(technique)
    stage2_authority = {
        "authority_complete": True,
        "allowed_kinds": ["forged_technique_creation"],
        "allowed_channels": [FORGED_TECHNIQUE_CHANNEL],
        "rule_id": rule_id,
        "minimum_cl": technique["cl_created"],
        "forged_technique": {
            "technique_id": technique_id,
            "name": technique["name"],
            "realm": technique["realm"],
            "cl_created": technique["cl_created"],
            "complexity": technique["complexity"]["final"],
            "cp_cost": technique["cp_cost"]["final"],
            "spheres_used": technique["spheres_used"],
            "technique_forging_dc": technique["technique_forging_dc"],
            "required_talent_record_ids": sorted(row["talent_id"] for row in effects),
            "required_sphere_record_ids": list(technique.get("sphere_ids_used") or []),
            "counts_against_known_limit": True,
        },
    }
    record: dict[str, Any] = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": technique_id,
        "content_type": FORGED_TECHNIQUE_CONTENT_TYPE,
        "display_name": technique["name"],
        "aliases": [],
        "tags": ["factory-constructed", "forged-technique", "custom-design"],
        "publication": {
            "status": "published",
            "published_version": FORGED_TECHNIQUE_PACK_VERSION,
            "replaced_by": None,
        },
        "content_binding": {
            "pack_id": FORGED_TECHNIQUE_PACK_ID,
            "pack_version": FORGED_TECHNIQUE_PACK_VERSION,
            "pack_hash": pack_hash,
        },
        "source": {
            "source_id": f"source.factory_constructed.{technique_id.rsplit('.', 1)[-1]}",
            "path": FACTORY_CONSTRUCTED_SOURCE_PATH,
            "anchor": f"seed:{technique['construction']['seed']}",
            "source_hash": technique["construction"]["request_sha256"],
        },
        "summary": technique["effect"]["summary"],
        "legality": {
            "acquisition_channels": [FORGED_TECHNIQUE_CHANNEL],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": technique["cl_created"],
            "realm_rules": {"realm": technique["realm"], "maximum_complexity": technique["complexity"]["realm_maximum"]},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": [],
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": technique["effect"]["summary"][:500],
            "full_description": text,
            "surfaces": ["rules_catalog", "character_sheet"],
            "sort_key": technique["name"].casefold(),
        },
        "compatibility": {
            "factory": {
                "producer": FACTORY_VERSION,
                "authority_classification": "factory_constructed",
                "selected_authority": True,
                "display_only_not_execution_authority": False,
                "mechanical_authority": True,
                "unresolved_normalization_notes": [],
                "retained_prerequisites": [],
                "retained_grants": [],
                "custom_design": True,
                "constructed_art": {
                    "schema": CONSTRUCTED_ART_SCHEMA,
                    "kind": "forged_technique",
                    "pack_id": FORGED_TECHNIQUE_PACK_ID,
                    "pack_version": FORGED_TECHNIQUE_PACK_VERSION,
                    "pack_hash": pack_hash,
                    "rule_id": rule_id,
                    "technique": technique,
                },
                "stage2_authority": stage2_authority,
            },
            "gm_screen": {
                "consumer": CATALOG_GM_COMPATIBILITY_VERSION,
                "projection_status": "forged-technique-record",
            },
        },
        "revision_history": [
            {
                "version": FORGED_TECHNIQUE_PACK_VERSION,
                "summary": "Factory-constructed Forged Technique from the sealed Core §11 tables.",
                "previous_record_hash": None,
            }
        ],
        "regression_tests": [
            {
                "test_id": f"{technique_id}.figures",
                "kind": "forged-technique-figures",
                "input": {"seed": technique["construction"]["seed"]},
                "expected": {
                    "complexity": technique["complexity"]["final"],
                    "cp_cost": technique["cp_cost"]["final"],
                    "technique_forging_dc": technique["technique_forging_dc"],
                },
            }
        ],
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def immortal_art_record_text(art: Mapping[str, Any]) -> str:
    """Render the complete twelve-step Immortal Art for GM-facing records.

    The record remains machine-readable in ``art``.  This renderer deliberately
    uses labelled scalar/list fields instead of Python mapping reprs so the
    sealed source, factor chassis, action riders, and each construction step
    survive in a useful GM-facing audit text.
    """
    def render_value(value: Any, indent: int = 0) -> list[str]:
        pad = " " * indent
        if isinstance(value, Mapping):
            lines: list[str] = []
            # Records are persisted through canonical JSON, which sorts object
            # keys. Render the same order here so a freshly loaded lock produces
            # identical human-facing bytes to the in-memory producer.
            for key in sorted(value, key=lambda item: str(item)):
                child = value[key]
                label = str(key).replace("_", " ")
                if isinstance(child, (Mapping, list, tuple)):
                    lines.append(f"{pad}{label}:")
                    lines.extend(render_value(child, indent + 2))
                else:
                    lines.append(f"{pad}{label}: {child}")
            return lines or [f"{pad}(none)"]
        if isinstance(value, (list, tuple)):
            if not value:
                return [f"{pad}(none)"]
            lines = []
            for child in value:
                if isinstance(child, (Mapping, list, tuple)):
                    lines.append(f"{pad}-")
                    lines.extend(render_value(child, indent + 2))
                else:
                    lines.append(f"{pad}- {child}")
            return lines
        if value is None:
            return [f"{pad}none"]
        return [f"{pad}{value}"]

    source = art.get("source") if isinstance(art.get("source"), Mapping) else {}
    action = art.get("action_surface") if isinstance(art.get("action_surface"), Mapping) else {}
    aspect = art.get("dao_aspect") if isinstance(art.get("dao_aspect"), Mapping) else {}
    factors = art.get("factors") if isinstance(art.get("factors"), list) else []
    steps = art.get("steps") if isinstance(art.get("steps"), list) else []
    source_binding = source.get("source") if isinstance(source.get("source"), Mapping) else {}
    published_text = source.get("published_text")
    lines = [
        f"{art.get('display_name', art.get('art_id'))} (Immortal Art, {art.get('realm')}, CL {art.get('cl_created')})",
        "",
        "Record identity:",
        f"  art id: {art.get('art_id')}",
        f"  record source id: {art.get('source_record_id')}",
        f"  record source hash: {art.get('source_record_hash')}",
        f"  path: {art.get('path_name', art.get('path_id'))} [{art.get('path_id')}]",
        f"  key ability: {art.get('key_ability')}",
        "",
        "Source binding:",
    ]
    lines.extend(render_value(source_binding, 2))
    lines.extend(["", "Published source block (exact authenticated text):", "-----"])
    if isinstance(published_text, str) and published_text:
        lines.extend(published_text.splitlines())
    else:
        lines.append("(none)")
    lines.extend(["-----", "", "Dao Aspect:"])
    lines.extend(render_value(aspect, 2))
    lines.extend(["", "Mechanical chassis and factor application:", "Factors and sealed chassis:"])
    if factors:
        for factor in factors:
            lines.extend(render_value(factor, 2))
    else:
        lines.append("  none")
    lines.extend([
        "",
        "Mandate and refinement:",
        f"  mandate complexity: {art.get('mandate_complexity')}",
        f"  mandate threshold: {art.get('mandate_threshold')}",
        f"  heaven pressure: {art.get('heaven_pressure')}",
        f"  factor escalation: {art.get('factor_escalation')}",
        f"  refinement DC: {art.get('refinement_dc')}",
        f"  activation CP: {art.get('activation_cp')} {action.get('resource_name', '')}".rstrip(),
        f"  research days: {art.get('research_days')}",
        f"  material cost GP: {art.get('material_cost_gp')}",
        "",
        "complete action surface and resolution:",
    ])
    lines.extend(render_value(action, 2))
    lines.extend(["", "Construction steps (all twelve):"])
    if steps:
        for row in steps:
            if not isinstance(row, Mapping):
                lines.append(f"  - {row}")
                continue
            lines.append(f"  Step {row.get('step')}: {str(row.get('name', 'unnamed')).replace('_', ' ')}")
            payload = row.get("payload")
            lines.extend(render_value(payload, 4))
    else:
        lines.append("  none")
    return "\n".join(lines) + "\n"


def build_immortal_art_record(art: Mapping[str, Any]) -> dict[str, Any]:
    """Build one authenticated catalog record for a typed Immortal Art."""
    if not isinstance(art, Mapping) or art.get("schema") != IMMORTAL_ART_SCHEMA:
        raise FoundryError("IMMORTAL_ART_RECORD_INVALID", "Only a typed Immortal Art can become a locked record.")
    art = deepcopy(dict(art))
    record_id = art.get("art_id")
    if not isinstance(record_id, str) or not record_id:
        raise FoundryError("IMMORTAL_ART_RECORD_INVALID", "The Immortal Art has no stable identity.")
    source = art.get("source")
    source_binding = source.get("source") if isinstance(source, Mapping) else None
    if not isinstance(source_binding, Mapping):
        raise FoundryError("IMMORTAL_ART_RECORD_INVALID", "The Immortal Art has no authenticated source binding.")
    pack_hash = _constructed_pack_hash(
        IMMORTAL_ART_RECORD_PACK_ID,
        record_id,
        IMMORTAL_ART_RECORD_PACK_VERSION,
    )
    rule_id = f"{record_id}.immortal-art-creation.v1"
    authority = {
        "authority_complete": True,
        "allowed_kinds": ["immortal_art_creation"],
        "allowed_channels": [IMMORTAL_ART_RECORD_CHANNEL],
        "minimum_cl": int(art["cl_created"]),
        "rule_id": rule_id,
        "immortal_art": {
            "art_id": record_id,
            "name": art.get("name", art.get("display_name")),
            "display_name": art.get("display_name"),
            "cl_created": art.get("cl_created"),
            "pb_at_creation": art.get("pb_at_creation"),
            "path_id": art.get("path_id"),
            "path_kind": art.get("path_kind"),
            "key_ability": art.get("key_ability"),
            "source_record_id": art.get("source_record_id"),
            "source_record_hash": art.get("source_record_hash"),
            "source_binding": deepcopy(dict(source_binding)),
            "source_package_ids": list(art.get("source_packages_used") or []),
            "source_spheres_used": art.get("source_spheres_used"),
            "mandate_complexity": art.get("mandate_complexity"),
            "mandate_threshold": art.get("mandate_threshold"),
            "heaven_pressure": art.get("heaven_pressure"),
            "factor_ids": [row.get("factor_id") for row in art.get("factors") or []],
            "refinement_dc": art.get("refinement_dc"),
            "activation_cp": art.get("activation_cp"),
            "steps": deepcopy(art.get("steps") or []),
        },
    }
    text = immortal_art_record_text(art)
    contract = {
        "schema": CONSTRUCTED_ART_SCHEMA,
        "kind": IMMORTAL_ART_KIND,
        "pack_id": IMMORTAL_ART_RECORD_PACK_ID,
        "pack_version": IMMORTAL_ART_RECORD_PACK_VERSION,
        "pack_hash": pack_hash,
        "rule_id": rule_id,
        "art": art,
    }
    # Keep this short display summary factual and independent of mapping
    # insertion order.  The complete effect remains in full_description.
    action = art.get("action_surface") if isinstance(art.get("action_surface"), Mapping) else {}
    effect = action.get("effect") if isinstance(action.get("effect"), Mapping) else {}
    aspect = art.get("dao_aspect") if isinstance(art.get("dao_aspect"), Mapping) else {}
    effect_summary = effect.get("summary") if isinstance(effect.get("summary"), str) else None
    display_name = str(art.get("display_name") or record_id)
    activation = action.get("activation") or action.get("action_type") or "action"
    aspect_name = aspect.get("display_name") or aspect.get("aspect_id") or "sealed Dao Aspect"
    summary = f"{display_name}: {effect_summary or 'authenticated source effect'} ({activation}; {aspect_name})"
    record: dict[str, Any] = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": IMMORTAL_ART_RECORD_CONTENT_TYPE,
        "display_name": display_name,
        "aliases": [],
        "tags": ["factory-constructed", "immortal-art", "dao-aspect"],
        "publication": {"status": "published", "published_version": IMMORTAL_ART_RECORD_PACK_VERSION, "replaced_by": None},
        "content_binding": {"pack_id": IMMORTAL_ART_RECORD_PACK_ID, "pack_version": IMMORTAL_ART_RECORD_PACK_VERSION, "pack_hash": pack_hash},
        "source": deepcopy(dict(source_binding)),
        "summary": summary,
        "legality": {
            "acquisition_channels": [IMMORTAL_ART_RECORD_CHANNEL],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": int(art["cl_created"]),
            "realm_rules": {"realm": art.get("realm")},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": sorted({value for value in (art.get("path_id"), art.get("source_record_id")) if isinstance(value, str)}),
        "grants": [],
        "execution_templates": [],
        "display_projection": {"short_description": text[:500], "full_description": text, "surfaces": ["rules_catalog", "character_sheet"], "sort_key": str(art.get("display_name") or record_id).casefold()},
        "compatibility": {
            "factory": {
                "producer": FACTORY_VERSION,
                "authority_classification": "factory_constructed",
                "selected_authority": True,
                "display_only_not_execution_authority": False,
                "mechanical_authority": True,
                "unresolved_normalization_notes": [],
                "retained_prerequisites": [],
                "retained_grants": [],
                "custom_design": False,
                "constructed_art": contract,
                "stage2_authority": authority,
            },
            "gm_screen": {"consumer": CATALOG_GM_COMPATIBILITY_VERSION, "projection_status": "immortal-art-record"},
        },
        "revision_history": [{"version": IMMORTAL_ART_RECORD_PACK_VERSION, "summary": "Factory-constructed Immortal Art from the sealed Dao Aspect authority.", "previous_record_hash": None}],
        "regression_tests": [{"test_id": f"{record_id}.rederive", "kind": "immortal-art-rederivation", "expected": {"record_id": record_id, "content_type": IMMORTAL_ART_RECORD_CONTENT_TYPE}}],
    }
    record["record_hash"] = canonical_record_hash(record)
    return record



def _constructed_pack_hash(pack_id: str, record_id: str, pack_version: str = MANUAL_PACK_VERSION) -> str:
    return sha256_json({
        "schema": CONSTRUCTED_ART_SCHEMA,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "record_id": record_id,
    })


def _bundle_copy(manual: Mapping[str, Any], recorded_arts: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "manual": deepcopy(dict(manual)),
        "recorded_arts": [deepcopy(dict(art)) for art in recorded_arts],
    }


def _manual_record_source(manual: Mapping[str, Any]) -> dict[str, Any]:
    construction = manual.get("construction") or {}
    request_hash = construction.get("request_sha256")
    if not isinstance(request_hash, str):
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "The Manual construction has no request hash.")
    return {
        "source_id": f"source.factory_constructed.manual.{manual['manual_id'].rsplit('.', 1)[-1]}",
        "path": FACTORY_CONSTRUCTED_SOURCE_PATH,
        "anchor": f"seed:{construction.get('seed')}",
        "source_hash": request_hash,
    }


def _manual_authority(manual: Mapping[str, Any], art_ids: list[str]) -> dict[str, Any]:
    lineage = deepcopy(manual.get("lineage_source") or {})
    rule_id = f"{manual['manual_id']}.lineage-manual.v1"
    authority = {
        "authority_complete": True,
        "allowed_kinds": ["training_source_access"],
        "allowed_channels": [MANUAL_CHANNEL],
        "rule_id": rule_id,
        "minimum_cl": 1,
        "manual": {
            "technique_record_ids": list(art_ids),
            "access_modes": ["inherited_lineage_manual"],
            "lineage_source": lineage,
        },
        "training_source_access": {
            "mode": "requires_access_event",
            "access_modes": ["inherited_lineage_manual"],
            "training_types": ["recorded_art"],
            "target_record_ids": list(art_ids),
        },
    }
    collection = manual.get("collection")
    if isinstance(collection, Mapping):
        # Possession metadata is carried by the source record, while learned
        # Recorded Arts remain an explicit causal Stage 2 event.
        authority["manual"]["collection"] = deepcopy(dict(collection))
    return authority


def _recorded_art_authority(art: Mapping[str, Any], manual_id: str) -> dict[str, Any]:
    rule_id = f"{art['record_id']}.recorded-art-acquisition.v1"
    return {
        "authority_complete": True,
        "allowed_kinds": ["creation_recorded_art_acquisition", "manual_training_attempt"],
        "allowed_channels": [RECORDED_ART_CHANNEL, MANUAL_TRAINING_CHANNEL],
        "rule_id": rule_id,
        "minimum_cl": 1,
        "manual_id": manual_id,
        "recorded_art": deepcopy(dict(art)),
    }


def _record_shell(
    *,
    record_id: str,
    content_type: str,
    display_name: str,
    pack_id: str,
    source: dict[str, Any],
    summary: str,
    legality_channels: list[str],
    authority: dict[str, Any],
    contract: dict[str, Any],
    tags: list[str],
    minimum_cl: int = 1,
) -> dict[str, Any]:
    pack_hash = _constructed_pack_hash(pack_id, record_id)
    record: dict[str, Any] = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": content_type,
        "display_name": display_name,
        "aliases": [],
        "tags": tags,
        "publication": {
            "status": "published",
            "published_version": MANUAL_PACK_VERSION,
            "replaced_by": None,
        },
        "content_binding": {
            "pack_id": pack_id,
            "pack_version": MANUAL_PACK_VERSION,
            "pack_hash": pack_hash,
        },
        "source": deepcopy(source),
        "summary": summary,
        "legality": {
            "acquisition_channels": list(legality_channels),
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": minimum_cl,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": [],
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": summary[:500] or display_name,
            "full_description": summary,
            "surfaces": ["rules_catalog", "character_sheet"],
            "sort_key": display_name.casefold(),
        },
        "compatibility": {
            "factory": {
                "producer": FACTORY_VERSION,
                "authority_classification": "factory_constructed",
                "selected_authority": True,
                "display_only_not_execution_authority": False,
                "mechanical_authority": True,
                "unresolved_normalization_notes": [],
                "retained_prerequisites": [],
                "retained_grants": [],
                "custom_design": False,
                "constructed_art": contract,
                "stage2_authority": authority,
            },
            "gm_screen": {
                "consumer": CATALOG_GM_COMPATIBILITY_VERSION,
                "projection_status": "lineage-manual-record" if content_type == "manual" else "recorded-art-record",
            },
        },
        "revision_history": [{
            "version": MANUAL_PACK_VERSION,
            "summary": "Factory-constructed lineage Manual / Recorded Art from exact source-backed Talent authority.",
            "previous_record_hash": None,
        }],
        "regression_tests": [{
            "test_id": f"{record_id}.rederive",
            "kind": "lineage-manual-rederivation",
            "expected": {"record_id": record_id, "content_type": content_type},
        }],
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def build_lineage_manual_records(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Wrap one semantic Manual bundle as one parent and three child records."""
    manual = bundle.get("manual") if isinstance(bundle, Mapping) else None
    arts = bundle.get("recorded_arts") if isinstance(bundle, Mapping) else None
    if not isinstance(manual, Mapping) or not isinstance(arts, list) or len(arts) != 3:
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "A constructed lineage Manual must contain exactly three Recorded Arts.")
    manual_id = manual.get("manual_id")
    if not isinstance(manual_id, str) or manual.get("record_id") != manual_id:
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "The Manual identity is incomplete.")
    art_rows = [row for row in arts if isinstance(row, Mapping)]
    if len(art_rows) != 3 or manual.get("recorded_art_ids") != [row.get("record_id") for row in art_rows]:
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "Manual and Recorded Art identities are not an exact ordered bundle.")
    bundle_copy = _bundle_copy(manual, art_rows)
    manual_authority = _manual_authority(manual, list(manual["recorded_art_ids"]))
    manual_summary = (
        f"{manual['display_name']} teaches three exact published Recorded Arts "
        "through inherited lineage access; each child remains a fixed expression."
    )
    manual_contract = {
        "schema": CONSTRUCTED_ART_SCHEMA,
        "kind": "manual",
        "pack_id": MANUAL_PACK_ID,
        "pack_version": MANUAL_PACK_VERSION,
        "pack_hash": _constructed_pack_hash(MANUAL_PACK_ID, manual_id),
        "rule_id": manual_authority["rule_id"],
        "bundle": bundle_copy,
    }
    parent_record = _record_shell(
        record_id=manual_id,
        content_type="manual",
        display_name=str(manual["display_name"]),
        pack_id=MANUAL_PACK_ID,
        source=_manual_record_source(manual),
        summary=manual_summary,
        legality_channels=[MANUAL_CHANNEL],
        authority=manual_authority,
        contract=manual_contract,
        tags=["factory-constructed", "manual", "lineage-manual"],
        minimum_cl=1,
    )
    records = [parent_record]
    for art in art_rows:
        art_id = art.get("record_id")
        if not isinstance(art_id, str):
            raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "A Recorded Art lacks a stable identity.")
        art_authority = _recorded_art_authority(art, manual_id)
        art_contract = {
            "schema": CONSTRUCTED_ART_SCHEMA,
            "kind": "recorded_art",
            "pack_id": RECORDED_ART_PACK_ID,
            "pack_version": MANUAL_PACK_VERSION,
            "pack_hash": _constructed_pack_hash(RECORDED_ART_PACK_ID, art_id),
            "rule_id": art_authority["rule_id"],
            "bundle": bundle_copy,
        }
        source = art.get("source")
        if not isinstance(source, Mapping):
            raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "A Recorded Art lacks the source binding of its reproduced Talent.")
        art_summary = (
            f"{art['technique_name']} as an exact fixed expression from the published Talent block; "
            "learning grants no Sphere, Talent, or modification permission."
        )
        records.append(_record_shell(
            record_id=art_id,
            content_type="recorded_art",
            display_name=str(art["display_name"]),
            pack_id=RECORDED_ART_PACK_ID,
            source=dict(source),
            summary=art_summary,
            legality_channels=[RECORDED_ART_CHANNEL, MANUAL_TRAINING_CHANNEL],
            authority=art_authority,
            contract=art_contract,
            tags=["factory-constructed", "recorded-art", "manual-expression"],
            minimum_cl=int(art.get("minimum_cl", 1)),
        ))
    return records

def constructed_art_contract(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the embedded constructed-art contract when the record carries one."""
    binding = record.get("content_binding") if isinstance(record, Mapping) else None
    if not isinstance(binding, Mapping) or binding.get("pack_id") not in CONSTRUCTED_ART_PACK_IDS:
        return None
    factory = ((record.get("compatibility") or {}).get("factory") or {}) if isinstance(record, Mapping) else {}
    contract = factory.get("constructed_art")
    return contract if isinstance(contract, Mapping) else None


def validate_forged_technique_record(record: Mapping[str, Any], *, root_dir: Path) -> dict[str, Any]:
    """Re-derive a locked Forged Technique record and recompile its figures.

    Returns the embedded technique.  Raises ``CONSTRUCTED_ART_RECORD_INVALID``
    when the bytes are not the builder's own or the figures drift from the
    sealed forging tables.
    """
    def invalid(message: str, **details: Any) -> FoundryError:
        return FoundryError("CONSTRUCTED_ART_RECORD_INVALID", message, details={"record_id": record.get("record_id") if isinstance(record, Mapping) else None, **details})

    contract = constructed_art_contract(record)
    if contract is None or contract.get("kind") != "forged_technique" or contract.get("schema") != CONSTRUCTED_ART_SCHEMA:
        raise invalid("The record does not carry a constructed Forged Technique contract.")
    technique = contract.get("technique")
    if not isinstance(technique, Mapping):
        raise invalid("The constructed Forged Technique contract has no typed technique.")
    construction = technique.get("construction")
    if not isinstance(construction, Mapping):
        raise invalid("The constructed Forged Technique has no construction provenance.")
    request = construction.get("request")
    if not isinstance(request, Mapping):
        raise invalid("The constructed Forged Technique has no normalized construction request.")
    try:
        normalized_request = normalize_forged_technique_request(request)
    except FoundryError as exc:
        raise invalid("The embedded construction request is not valid.", cause=exc.code) from exc
    request_hash = sha256_json(normalized_request)
    if construction.get("request_sha256") != request_hash:
        raise invalid(
            "The construction request hash does not match its normalized request.",
            expected_request_sha256=request_hash,
            actual_request_sha256=construction.get("request_sha256"),
        )
    if construction.get("seed") != normalized_request["seed"]:
        raise invalid("The construction seed does not match its normalized request.")
    expected_id = forged_technique_id(technique)
    if technique.get("technique_id") != expected_id:
        raise invalid(
            "The technique identity does not match its typed construction.",
            expected_technique_id=expected_id,
            actual_technique_id=technique.get("technique_id"),
        )
    authority = load_forging_authority(root_dir)
    if construction.get("authority_seal_sha256") != authority.get("seal_sha256"):
        raise invalid("The technique was constructed under a different forging authority seal.")
    try:
        rederived_technique = construct_forged_technique(
            authority, normalized_request, generator_version=construction.get("generator_version", 1),
            design_policy=technique.get("design_policy"),
        )
    except FoundryError as exc:
        raise invalid("The construction request cannot rederive under the sealed forging authority.", cause=exc.code) from exc
    if canonical_json(rederived_technique) != canonical_json(technique):
        raise invalid("The technique does not match deterministic re-derivation from its construction request.")
    try:
        expected = build_forged_technique_record(technique)
    except FoundryError as exc:
        raise invalid("The embedded technique cannot rebuild its record.", cause=exc.code) from exc
    if canonical_json(expected) != canonical_json(record):
        raise invalid("The locked record is not byte-identical to its own re-derivation.")
    if canonical_record_hash(record) != record.get("record_hash"):
        raise invalid("The locked record does not match its canonical hash.")
    effects = [technique["primary_sphere_effect"], *technique.get("secondary_sphere_effects", [])]
    try:
        compile_forged_technique(
            authority,
            technique,
            cl=int(technique["cl_created"]),
            pb=int(technique["pb_at_creation"]),
            known_talent_ids={row["talent_id"] for row in effects},
            known_forged_technique_count=0,
        )
    except FoundryError as exc:
        raise invalid("The technique's figures do not recompile from the sealed forging tables.", cause=exc.code, cause_details=exc.details) from exc
    return deepcopy(dict(technique))


def validate_lineage_manual_record(
    record: Mapping[str, Any],
    *,
    root_dir: Path,
    factory_root: Path | None = None,
) -> dict[str, Any]:
    """Re-derive a Manual or Recorded Art and compare the complete bundle."""
    del root_dir  # Forging authority is separate; lineage source files use factory_root.
    def invalid(message: str, **details: Any) -> FoundryError:
        return FoundryError(
            "CONSTRUCTED_ART_RECORD_INVALID",
            message,
            details={"record_id": record.get("record_id") if isinstance(record, Mapping) else None, **details},
        )
    if factory_root is None:
        raise invalid(
            "Lineage Manual validation requires an explicit installed Factory source root."
        )
    try:
        factory_root = Path(factory_root).resolve()
    except (TypeError, ValueError) as exc:
        raise invalid("The installed Factory source root is invalid.") from exc
    contract = constructed_art_contract(record)
    if contract is None or contract.get("schema") != CONSTRUCTED_ART_SCHEMA or contract.get("kind") not in {"manual", "recorded_art"}:
        raise invalid("The record does not carry a constructed Manual or Recorded Art contract.")
    bundle = contract.get("bundle")
    if not isinstance(bundle, Mapping) or not isinstance(bundle.get("manual"), Mapping) or not isinstance(bundle.get("recorded_arts"), list):
        raise invalid("The constructed Manual contract has no complete parent/child bundle.")
    manual = bundle["manual"]
    construction = manual.get("construction")
    request = construction.get("request") if isinstance(construction, Mapping) else None
    if not isinstance(request, Mapping):
        raise invalid("The Manual has no normalized construction request.")
    try:
        normalized = normalize_lineage_manual_request(request)
        request_hash = sha256_json(normalized)
        rebuilt_bundle = construct_lineage_manual(normalized)
        if not isinstance(construction, Mapping) or construction.get("request_sha256") != request_hash:
            raise invalid("The Manual construction request hash does not match its normalized request.", expected_request_sha256=request_hash)
        if construction.get("manual_id") != manual.get("manual_id"):
            raise invalid("The Manual identity is not bound to its normalized construction request.")
        if construction.get("seed") != normalized.get("seed"):
            raise invalid("The Manual construction seed does not match its normalized request.")
        from .sources import published_block

        for rebuilt_art in rebuilt_bundle.get("recorded_arts") or []:
            derivation = rebuilt_art.get("execution_derivation") if isinstance(rebuilt_art, Mapping) else None
            source = rebuilt_art.get("source") if isinstance(rebuilt_art, Mapping) else None
            quoted = derivation.get("source_block") if isinstance(derivation, Mapping) else None
            verified = published_block(factory_root, source)
            if (
                not isinstance(quoted, str)
                or not verified
                or quoted != verified
                or derivation.get("source_block_sha256") != sha256_bytes(verified.encode("utf-8"))
            ):
                raise invalid(
                    "Every Recorded Art quote must equal the hash-verified installed published source block.",
                    child_record_id=rebuilt_art.get("record_id") if isinstance(rebuilt_art, Mapping) else None,
                    source_record_id=derivation.get("source_record_id") if isinstance(derivation, Mapping) else None,
                )
        expected_records = build_lineage_manual_records(rebuilt_bundle)
    except FoundryError as exc:
        if exc.code == "CONSTRUCTED_ART_RECORD_INVALID":
            raise
        raise invalid("The embedded Manual construction request is not valid.", cause=exc.code) from exc
    expected = next((row for row in expected_records if row.get("record_id") == record.get("record_id")), None)
    if expected is None:
        raise invalid("The record ID is not one of the rederived Manual bundle records.")
    if canonical_json(expected) != canonical_json(record):
        raise invalid("The locked Manual/Recorded Art is not byte-identical to its deterministic bundle re-derivation.")
    if canonical_record_hash(record) != record.get("record_hash"):
        raise invalid("The locked Manual/Recorded Art does not match its canonical hash.")
    if contract.get("kind") == "recorded_art":
        art = next((row for row in rebuilt_bundle["recorded_arts"] if row.get("record_id") == record.get("record_id")), None)
        if not isinstance(art, Mapping):
            raise invalid("The Recorded Art child is absent from its rederived bundle.")
        derivation = art.get("execution_derivation") or {}
        block = derivation.get("source_block")
        if derivation.get("mode") != "quote_published_source_block" or not isinstance(block, str) or sha256_bytes(block.encode("utf-8")) != derivation.get("source_block_sha256"):
            raise invalid("The Recorded Art quote is not hash-bound to its published source block.")
        return deepcopy(dict(art))
    return deepcopy(dict(rebuilt_bundle["manual"]))


def validate_immortal_art_record(
    record: Mapping[str, Any],
    *,
    root_dir: Path,
    factory_root: Path | None = None,
) -> dict[str, Any]:
    """Re-derive a locked Immortal Art and verify its installed source block."""
    def invalid(message: str, **details: Any) -> FoundryError:
        return FoundryError(
            "CONSTRUCTED_ART_RECORD_INVALID",
            message,
            details={"record_id": record.get("record_id") if isinstance(record, Mapping) else None, **details},
        )

    contract = constructed_art_contract(record)
    if contract is None or contract.get("schema") != CONSTRUCTED_ART_SCHEMA or contract.get("kind") != IMMORTAL_ART_KIND:
        raise invalid("The record does not carry a constructed Immortal Art contract.")
    art = contract.get("art")
    if not isinstance(art, Mapping):
        raise invalid("The constructed Immortal Art contract has no typed Art payload.")
    source = art.get("source") if isinstance(art.get("source"), Mapping) else {}
    progression = source.get("progression") if isinstance(source.get("progression"), Mapping) else {}
    feature_snapshot = progression.get("feature_snapshot")
    from .native_immortal_sources import NATIVE_COMMITMENT_KIND, native_feature_hash, validate_native_source
    native_source = source.get("feature_record_hash_kind") == NATIVE_COMMITMENT_KIND
    commitment_kind = NATIVE_COMMITMENT_KIND if native_source else "subpath_progression_commitment"
    if feature_snapshot is not None:
        try:
            expected_feature_hash = (native_feature_hash if native_source else immortal_art_progression_child_hash)(
                progression.get("parent_record_id"),
                progression.get("parent_record_hash"),
                feature_snapshot,
            )
        except FoundryError as exc:
            raise invalid("The Immortal Art progression-child provenance is malformed.", cause=exc.code) from exc
        if (
            source.get("feature_record_hash_kind") != commitment_kind
            or source.get("record_hash") != expected_feature_hash
            or progression.get("feature_record_hash_kind") != commitment_kind
            or progression.get("feature_record_id") != art.get("source_record_id")
        ):
            raise invalid("The Immortal Art source hash is not the parent-bound progression commitment.")
    try:
        if native_source:
            path_cl = ((art.get("construction") or {}).get("request") or {}).get("owning_path_cl")
            validate_native_source(root_dir, factory_root, source, path_cl)
        authority = load_immortal_art_authority(root_dir)
        known_sources = [art["source"]] if isinstance(art.get("source"), Mapping) else None
        compile_immortal_art(
            authority,
            art,
            cl=int(art["cl_created"]),
            pb=int(art["pb_at_creation"]),
            known_source_ids={str(art["source_record_id"])},
            known_sources=known_sources,
        )
    except (FoundryError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FoundryError) and exc.code == "CONSTRUCTED_ART_RECORD_INVALID":
            raise
        raise invalid("The Immortal Art does not recompile under the sealed authority.", cause=getattr(exc, "code", type(exc).__name__)) from exc
    if factory_root is not None:
        try:
            from .sources import published_section

            source = art.get("source") or {}
            progression = source.get("progression") if isinstance(source, Mapping) else None
            exact_source = progression.get("source") if isinstance(progression, Mapping) else None
            published = published_section(factory_root, exact_source)
            expected_text = source.get("published_text") if isinstance(source, Mapping) else None
            if not isinstance(exact_source, Mapping) or not isinstance(expected_text, str) or not published or published != expected_text:
                raise invalid("The Immortal Art source block is not the exact hash-verified installed published section.")
        except FoundryError:
            raise
        except Exception as exc:  # pragma: no cover - defensive source I/O boundary
            raise invalid("The Immortal Art installed source block could not be verified.", cause=type(exc).__name__) from exc
    try:
        expected = build_immortal_art_record(art)
    except FoundryError as exc:
        raise invalid("The Immortal Art cannot rebuild its locked record.", cause=exc.code) from exc
    if canonical_json(expected) != canonical_json(record):
        raise invalid("The locked Immortal Art is not byte-identical to its deterministic re-derivation.")
    if canonical_record_hash(record) != record.get("record_hash"):
        raise invalid("The locked Immortal Art does not match its canonical hash.")
    return deepcopy(dict(art))


def construct_starting_kit(
    *,
    background_id: str,
    path_id: str,
    path_option: str,
    picks: Mapping[str, int],
    seed: str,
    purchases: Sequence[str] | None = None,
    treasure_weapon: Mapping[str, Any] | None = None,
    treasure_armor: Mapping[str, Any] | None = None,
    treasure_purchases: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the controller's kit decision into one typed, deterministic kit.

    ``treasure_weapon`` ({chassis_id, material_id, enchantment_ids, target_cl})
    adds the character's signature treasure weapon (Item Book Chapter 2);
    ``treasure_armor`` ({chassis_id, material_id, enhancement_ids, target_cl})
    its treasure armour (Chapter 3); ``treasure_purchases`` ({wondrous_ids,
    consumable_ids, target_cl}) Wondrous Treasures and consumables (Chapters 4-5).
    """
    from factory_authoring.starting_kits import KIT_AUTHORITY_SHA256, resolve_starting_kit

    inputs = {
        "background_id": background_id,
        "path_id": path_id,
        "path_option": path_option,
        "picks": dict(sorted(dict(picks).items())),
        "seed": seed,
        "authority_sha256": KIT_AUTHORITY_SHA256,
    }
    # Owner-preferred gear bought with Option B coin; absent (not empty) when
    # there is none, so earlier kits keep their identity.
    if purchases:
        inputs["purchases"] = list(purchases)
    if treasure_weapon:
        from factory_authoring.treasure_weapons import AUTHORITY_SHA256 as TREASURE_AUTHORITY_SHA256

        inputs["treasure_weapon"] = {
            "chassis_id": treasure_weapon["chassis_id"],
            "material_id": treasure_weapon["material_id"],
            "enchantment_ids": list(treasure_weapon["enchantment_ids"]),
            "target_cl": int(treasure_weapon["target_cl"]),
            "authority_sha256": TREASURE_AUTHORITY_SHA256,
            # Absent on the first kits (capacity rules 1); see treasure_weapons.
            **({"capacity_rules": int(treasure_weapon["capacity_rules"])} if "capacity_rules" in treasure_weapon else {}),
        }
    if treasure_armor:
        from factory_authoring.treasure_armor import AUTHORITY_SHA256 as ARMOR_AUTHORITY_SHA256

        inputs["treasure_armor"] = {
            "chassis_id": treasure_armor["chassis_id"],
            "material_id": treasure_armor["material_id"],
            "enhancement_ids": list(treasure_armor["enhancement_ids"]),
            "target_cl": int(treasure_armor["target_cl"]),
            "authority_sha256": ARMOR_AUTHORITY_SHA256,
            **({"capacity_rules": int(treasure_armor["capacity_rules"])} if "capacity_rules" in treasure_armor else {}),
        }
    if treasure_purchases:
        from factory_authoring.treasure_catalog import AUTHORITY_SHA256 as CATALOG_AUTHORITY_SHA256

        inputs["treasure_purchases"] = {
            "wondrous_ids": list(treasure_purchases.get("wondrous_ids") or []),
            "consumable_ids": list(treasure_purchases.get("consumable_ids") or []),
            "target_cl": int(treasure_purchases["target_cl"]),
            "authority_sha256": CATALOG_AUTHORITY_SHA256,
        }
    try:
        resolved = resolve_starting_kit(background_id, path_id, path_option=path_option, picks=inputs["picks"], seed=seed, purchases=inputs.get("purchases"))
        if "treasure_weapon" in inputs:
            from factory_authoring.treasure_weapons import resolve_treasure_weapon

            weapon = inputs["treasure_weapon"]
            resolved["treasure_weapon"] = resolve_treasure_weapon(
                target_cl=weapon["target_cl"],
                background_id=background_id,
                chassis_id=weapon["chassis_id"],
                material_id=weapon["material_id"],
                enchantment_ids=weapon["enchantment_ids"],
                capacity_rules=weapon.get("capacity_rules", 1),
            )
        if "treasure_armor" in inputs:
            from factory_authoring.treasure_armor import resolve_treasure_armor

            armor = inputs["treasure_armor"]
            resolved["treasure_armor"] = resolve_treasure_armor(
                target_cl=armor["target_cl"],
                background_id=background_id,
                path_id=path_id,
                chassis_id=armor["chassis_id"],
                material_id=armor["material_id"],
                enhancement_ids=armor["enhancement_ids"],
                capacity_rules=armor.get("capacity_rules", 1),
            )
        if "treasure_purchases" in inputs:
            from factory_authoring.treasure_catalog import resolve_treasure_catalog

            bought = inputs["treasure_purchases"]
            resolved["treasure_purchases"] = resolve_treasure_catalog(
                target_cl=bought["target_cl"],
                background_id=background_id,
                path_id=path_id,
                wondrous_ids=bought["wondrous_ids"],
                consumable_ids=bought["consumable_ids"],
            )
    except (FoundryError, KeyError, TypeError, ValueError) as exc:
        raise FoundryError("STARTING_KIT_RECORD_INVALID", "The starting kit cannot be resolved.", details={"cause": getattr(exc, "code", type(exc).__name__)}) from exc
    return {
        "schema": STARTING_KIT_SCHEMA,
        "kit_id": f"tianxia.constructed.starting_kit.{sha256_json(inputs)[:32]}",
        **inputs,
        "resolved": resolved,
    }


def starting_kit_record_text(kit: Mapping[str, Any]) -> str:
    resolved = kit["resolved"]
    lines = [f"Starting kit ({kit['path_option'].replace('_', ' ')})."]
    for item in resolved["items"]:
        printed = f" — printed: {item['printed']}" if item.get("printed") else ""
        lines.append(f"- {item['quantity']} × {item['name']} ({item['source']}){printed}")
    for trinket in resolved["trinkets"]:
        lines.append(f"- {trinket['text']} ({trinket['source']}; keepsake, no market value)")
    lines.append(f"Coin: {resolved['coin_cc']} Copper Cash.")
    weapon = resolved.get("treasure_weapon")
    if weapon:
        enchantments = ", ".join(f"{row['name']} (+{row['equivalent_bonus']})" for row in weapon["enchantments"]) or "none"
        lines.append(
            f"Treasure weapon: {weapon['name']} ({weapon['grade_label']}; {weapon['material']['name']}: "
            f"{weapon['material']['property_name']}; enchantments: {enchantments}; value {weapon['value_gt']} GT)."
        )
    armor = resolved.get("treasure_armor")
    if armor:
        enhancements = ", ".join(f"{row['name']} (+{row['equivalent_bonus']})" for row in armor["enhancements"]) or "none"
        lines.append(
            f"Treasure armour: {armor['name']} ({armor['grade_label']}; AC {armor['chassis']['armor_class']} +{armor['refinement_bonus']}; "
            f"{armor['material']['name']}: {armor['material']['property_name']}; enhancements: {enhancements}; value {armor['value_gt']} GT)."
        )
    bought = resolved.get("treasure_purchases")
    if bought:
        for row in bought["wondrous"]:
            lines.append(f"Wondrous Treasure: {row['name']} ({row['grade']} {row['item_type']}; value {row['value_gt']} GT).")
        for row in bought["consumables"]:
            lines.append(f"Consumables: {row['batch_quantity']} {row['batch_unit']} of {row['name']} ({row['grade']}; {row['batch_price_gt']} GT).")
    return "\n".join(lines)


def build_starting_kit_record(kit: Mapping[str, Any]) -> dict[str, Any]:
    """Build the project-locked item record carrying one resolved starting kit."""
    if not isinstance(kit, Mapping) or kit.get("schema") != STARTING_KIT_SCHEMA:
        raise FoundryError("STARTING_KIT_RECORD_INVALID", "Only a typed starting kit can become a locked record.")
    kit = deepcopy(dict(kit))
    record_id = kit["kit_id"]
    pack_hash = _constructed_pack_hash(STARTING_KIT_PACK_ID, record_id, STARTING_KIT_PACK_VERSION)
    rule_id = f"{record_id}.starting-kit.v1"
    contract = {
        "schema": CONSTRUCTED_ART_SCHEMA,
        "kind": STARTING_KIT_KIND,
        "pack_id": STARTING_KIT_PACK_ID,
        "pack_version": STARTING_KIT_PACK_VERSION,
        "pack_hash": pack_hash,
        "rule_id": rule_id,
        "kit": kit,
    }
    text = starting_kit_record_text(kit)
    record: dict[str, Any] = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": STARTING_KIT_CONTENT_TYPE,
        "display_name": "Starting kit",
        "aliases": [],
        "tags": ["factory-constructed", "starting-kit", "mortal-equipment"],
        "publication": {"status": "published", "published_version": STARTING_KIT_PACK_VERSION, "replaced_by": None},
        "content_binding": {"pack_id": STARTING_KIT_PACK_ID, "pack_version": STARTING_KIT_PACK_VERSION, "pack_hash": pack_hash},
        "source": {
            "source_id": f"source.factory_constructed.starting_kit.{record_id.rsplit('.', 1)[-1]}",
            "path": FACTORY_CONSTRUCTED_SOURCE_PATH,
            "anchor": f"background:{kit['background_id']}",
            "source_hash": kit["authority_sha256"],
        },
        "summary": f"Printed Background kit and Path kit {kit['path_option'].replace('_', ' ')}: "
                   f"{len(kit['resolved']['items'])} items, {kit['resolved']['coin_cc']} CC.",
        "legality": {
            "acquisition_channels": [STARTING_KIT_CHANNEL],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": 1,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": sorted({kit["background_id"], kit["path_id"]}),
        "grants": [],
        "execution_templates": [],
        "display_projection": {"short_description": text[:500], "full_description": text, "surfaces": ["rules_catalog", "character_sheet"], "sort_key": "starting kit"},
        "compatibility": {
            "factory": {
                "producer": FACTORY_VERSION,
                "authority_classification": "factory_constructed",
                "selected_authority": True,
                "display_only_not_execution_authority": False,
                "mechanical_authority": True,
                "unresolved_normalization_notes": [],
                "retained_prerequisites": [],
                "retained_grants": [],
                "custom_design": False,
                "constructed_art": contract,
                "stage2_authority": {
                    "authority_complete": True,
                    "allowed_kinds": ["equipment_acquisition"],
                    "allowed_channels": [STARTING_KIT_CHANNEL],
                    "minimum_cl": 1,
                    "rule_id": rule_id,
                },
            },
            "gm_screen": {"consumer": CATALOG_GM_COMPATIBILITY_VERSION, "projection_status": "starting-kit-record"},
        },
        "revision_history": [{"version": STARTING_KIT_PACK_VERSION, "summary": "Factory-constructed starting kit from the printed Background and Path kits.", "previous_record_hash": None}],
        "regression_tests": [{"test_id": f"{record_id}.rederive", "kind": "starting-kit-rederivation", "expected": {"record_id": record_id, "content_type": STARTING_KIT_CONTENT_TYPE}}],
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def validate_starting_kit_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Re-resolve a locked starting kit from the pinned kit authority and rebuild its record."""
    def invalid(message: str, **details: Any) -> FoundryError:
        return FoundryError(
            "CONSTRUCTED_ART_RECORD_INVALID",
            message,
            details={"record_id": record.get("record_id") if isinstance(record, Mapping) else None, **details},
        )

    contract = constructed_art_contract(record)
    if contract is None or contract.get("schema") != CONSTRUCTED_ART_SCHEMA or contract.get("kind") != STARTING_KIT_KIND:
        raise invalid("The record does not carry a constructed starting-kit contract.")
    kit = contract.get("kit")
    if not isinstance(kit, Mapping):
        raise invalid("The constructed starting-kit contract has no typed kit payload.")
    try:
        expected_kit = construct_starting_kit(
            background_id=kit["background_id"],
            path_id=kit["path_id"],
            path_option=kit["path_option"],
            picks=kit["picks"],
            seed=kit["seed"],
            purchases=kit.get("purchases"),
            treasure_weapon=kit.get("treasure_weapon"),
            treasure_armor=kit.get("treasure_armor"),
            treasure_purchases=kit.get("treasure_purchases"),
        )
    except (FoundryError, KeyError, TypeError) as exc:
        raise invalid("The starting kit does not re-resolve under the pinned kit authority.", cause=getattr(exc, "code", type(exc).__name__)) from exc
    if canonical_json(expected_kit) != canonical_json(kit):
        raise invalid("The locked starting kit differs from its deterministic re-resolution.")
    if canonical_json(build_starting_kit_record(expected_kit)) != canonical_json(record):
        raise invalid("The locked starting-kit record is not byte-identical to its re-derivation.")
    if canonical_record_hash(record) != record.get("record_hash"):
        raise invalid("The locked starting-kit record does not match its canonical hash.")
    return deepcopy(dict(kit))


def validate_constructed_art_record(
    record: Mapping[str, Any],
    *,
    root_dir: Path,
    factory_root: Path | None = None,
) -> dict[str, Any]:
    """Dispatch constructed-record authentication by its typed artifact kind."""
    contract = constructed_art_contract(record)
    if contract is None:
        raise FoundryError(
            "CONSTRUCTED_ART_RECORD_INVALID",
            "The record does not carry a recognized constructed-art contract.",
            details={"record_id": record.get("record_id") if isinstance(record, Mapping) else None},
        )
    if contract.get("kind") == "forged_technique":
        return validate_forged_technique_record(record, root_dir=root_dir)
    if contract.get("kind") in {"manual", "recorded_art"}:
        return validate_lineage_manual_record(record, root_dir=root_dir, factory_root=factory_root)
    if contract.get("kind") == IMMORTAL_ART_KIND:
        return validate_immortal_art_record(record, root_dir=root_dir, factory_root=factory_root)
    if contract.get("kind") == STARTING_KIT_KIND:
        return validate_starting_kit_record(record)
    raise FoundryError(
        "CONSTRUCTED_ART_RECORD_INVALID",
        "The constructed-art kind is unsupported.",
        details={"record_id": record.get("record_id"), "kind": contract.get("kind")},
    )


__all__ = [
    "CONSTRUCTED_ART_PACK_IDS",
    "CONSTRUCTED_ART_SCHEMA",
    "FORGED_TECHNIQUE_CHANNEL",
    "FORGED_TECHNIQUE_CONTENT_TYPE",
    "FORGED_TECHNIQUE_PACK_ID",
    "FORGED_TECHNIQUE_PACK_VERSION",
    "IMMORTAL_ART_RECORD_CHANNEL",
    "IMMORTAL_ART_RECORD_CONTENT_TYPE",
    "IMMORTAL_ART_RECORD_PACK_ID",
    "IMMORTAL_ART_RECORD_PACK_VERSION",
    "MANUAL_PACK_ID",
    "MANUAL_CHANNEL",
    "RECORDED_ART_PACK_ID",
    "RECORDED_ART_CHANNEL",
    "build_forged_technique_record",
    "build_lineage_manual_records",
    "constructed_art_contract",
    "forged_technique_record_text",
    "immortal_art_record_text",
    "immortal_art_progression_child_hash",
    "build_immortal_art_record",
    "validate_forged_technique_record",
    "validate_lineage_manual_record",
    "validate_immortal_art_record",
    "validate_constructed_art_record",
    "STARTING_KIT_CHANNEL",
    "STARTING_KIT_KIND",
    "STARTING_KIT_PACK_ID",
    "build_starting_kit_record",
    "construct_starting_kit",
    "validate_starting_kit_record",
]
