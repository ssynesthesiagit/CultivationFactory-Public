"""Source-bound inputs for initial Foundation mechanics.

This layer resolves installation state; it does not award advancement, grant
Path access, execute a feature, or infer a resource conversion. Numeric effects
must subsequently enter the causal calculator, not a second sheet calculator.
"""
from copy import deepcopy
from collections.abc import Mapping
import json
import re
from typing import Any

from app.core import FoundryError, canonical_json, sha256_json
from character_creation import foundation_corpus_release as release
from character_creation.path_attainment import CANONICAL_PATH_IDS


FOUNDATION_INITIAL_STATE_SCHEMA = "TianxiaFoundry.InitialFoundationState.v1"
FOUNDATION_INITIAL_MECHANICS_SCHEMA = "TianxiaFoundry.InitialFoundationMechanics.v1"
FOUNDATION_MECHANICS_PACK_VERSION = "0.4C-mechanics.1"
INITIAL_FOUNDATION_MECHANICS_POLICY = {
    "schema": "TianxiaFoundry.InitialFoundationMechanicsPolicy.v1",
    "record_version": FOUNDATION_MECHANICS_PACK_VERSION,
    "acquisition_cl": 5,
    "initial_stage": "published_default_or_explicit_published_choice",
    "active_expressions": "supported_selected_paths",
    "refill_current": False,
    "stage_advancement_inferred_from_cl": False,
}
_CANONICAL_PATHS = {
    "BODY_REFINING": "tianxia.path.body_refining",
    "QI_CULTIVATION": "tianxia.path.qi_cultivation",
    "SPIRIT_AWAKENING": "tianxia.path.spirit_awakening",
}


def has_acquired_foundation(foundation: Any) -> bool:
    """Recognize a Foundation after its authenticated projection lifecycle.

    The v3 bridge authenticates the locked source and causal event before it
    reaches consumers. Legacy projections use ``acquired`` directly; modern
    initial-mechanics projections use ``active`` and carry the sealed
    mechanics, event, packet and source commitments that identify that path.
    This predicate recognizes those consumer states without granting or
    authenticating a Foundation on caller-supplied fields.
    """
    if not isinstance(foundation, Mapping):
        return False
    record_id = foundation.get("record_id")
    if not isinstance(record_id, str) or not record_id.strip():
        return False
    if foundation.get("state") == "acquired":
        return True
    if foundation.get("state") != "active":
        return False
    mechanics = foundation.get("mechanics")
    packet_ids = foundation.get("source_packet_ids")
    acquisition_event_id = foundation.get("acquisition_event_id")
    source_record_sha256 = foundation.get("source_record_sha256")
    return (
        foundation.get("mechanical_projection") is True
        and foundation.get("mechanics_schema") == FOUNDATION_INITIAL_MECHANICS_SCHEMA
        and isinstance(mechanics, Mapping)
        and mechanics.get("schema") == FOUNDATION_INITIAL_MECHANICS_SCHEMA
        and mechanics.get("foundation_id") == record_id
        and mechanics.get("source_record_sha256") == source_record_sha256
        and isinstance(acquisition_event_id, str)
        and bool(acquisition_event_id.strip())
        and foundation.get("event_id") == acquisition_event_id
        and isinstance(packet_ids, list)
        and bool(packet_ids)
        and all(isinstance(packet_id, str) and bool(packet_id.strip()) for packet_id in packet_ids)
        and isinstance(source_record_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", source_record_sha256) is not None
    )


def _invalid(reason: str, **details: Any) -> FoundryError:
    return FoundryError(
        "NS1R_INITIAL_FOUNDATION_AUTHORITY_INVALID",
        "Initial Foundation state requires its exact published source and explicit choices.",
        details={"reason": reason, **details}, status_code=409,
    )


def initial_foundation_record_version(request: dict[str, Any]) -> str | None:
    """Historical absence retains P2A; only this exact policy opts in."""
    authority = request.get("server_owned_authority") or {}
    if not isinstance(authority, dict):
        raise _invalid("server_authority_shape")
    if "initial_foundation_mechanics_policy" not in authority:
        return None
    if canonical_json(authority["initial_foundation_mechanics_policy"]) != canonical_json(INITIAL_FOUNDATION_MECHANICS_POLICY):
        raise _invalid("unsupported_frozen_policy")
    return FOUNDATION_MECHANICS_PACK_VERSION


def foundation_initial_stage_contract() -> dict[str, Any]:
    """Freeze all published alternatives before asking for a selection."""
    return {
        "type": "published_foundation_initial_stage",
        "options_by_foundation_id": {
            identity: record["stage"].split(" or ")
            for identity, record in sorted(verified_foundation_records().items())
        },
        "registry_sha256": release.REGISTRY_SHA256,
        "default_only_when_unique": True,
    }


def validate_foundation_initial_stage(request: dict[str, Any], by_slot: dict[str, Any], bounded: dict[str, Any]) -> None:
    if initial_foundation_record_version(request) is None:
        return
    contract = ((request.get("bounded_choice_contract") or {}).get("fields") or {}).get("foundation_initial_stage")
    if canonical_json(contract) != canonical_json(foundation_initial_stage_contract()):
        raise _invalid("frozen_stage_contract_mismatch")
    selected = by_slot.get("foundation_choice") or []
    selected = [selected] if isinstance(selected, str) else selected
    stage = bounded.get("foundation_initial_stage")
    if not selected:
        if stage is not None:
            raise _invalid("stage_without_foundation")
        return
    if not isinstance(selected, list) or len(selected) != 1 or not isinstance(selected[0], str):
        raise _invalid("selected_foundation_shape")
    options = contract["options_by_foundation_id"].get(selected[0], [])
    if stage is None and len(options) != 1:
        raise FoundryError("CG1_FOUNDATION_INITIAL_STAGE_REQUIRED", "Choose an exact published initial Foundation stage.", details={"foundation_id": selected[0], "stage_options": options}, status_code=409)
    if stage is not None and (not isinstance(stage, str) or stage not in options):
        raise _invalid("unpublished_initial_stage", stage=stage, stage_options=options)


def verified_foundation_records() -> dict[str, dict[str, Any]]:
    """Verify the complete release before returning any playable source row."""
    sections = release.verified_sections()
    registry = json.loads(release.parent._read_pinned(release.REGISTRY_PATH, release.REGISTRY_SHA256))
    records = {row["foundation_id"]: row for row in registry["orthodox"]}
    if len(records) != 30 or {
        release.MEMBER_PREFIX + identity + ".md" for identity in records
    } != set(sections):
        raise _invalid("source_inventory")
    return records


def _verified_record(foundation: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(foundation, dict):
        raise _invalid("source_shape")
    expected = verified_foundation_records().get(foundation.get("foundation_id"))
    if expected is None or canonical_json(expected) != canonical_json(foundation):
        raise _invalid("source_record_mismatch", foundation_id=foundation.get("foundation_id"))
    return expected


def initial_foundation_options(
    foundation: dict[str, Any], selected_path_ids: list[str],
) -> dict[str, Any]:
    """Expose recorded defaults and all supported active Path expressions."""
    foundation = _verified_record(foundation)
    if (
        not isinstance(selected_path_ids, list) or not selected_path_ids
        or any(not isinstance(path_id, str) or path_id not in CANONICAL_PATH_IDS for path_id in selected_path_ids)
        or len(selected_path_ids) != len(set(selected_path_ids))
    ):
        raise _invalid("selected_paths")
    stages = foundation["stage"].split(" or ")
    if any(not stage or stage.strip() != stage for stage in stages) or len(stages) != len(set(stages)):
        raise _invalid("recorded_stage_options")
    supported = {_CANONICAL_PATHS[path] for path in foundation["compatible_path_ids"]}
    active = sorted(supported & set(selected_path_ids))
    if not active:
        raise _invalid("no_supported_active_expression", foundation_id=foundation["foundation_id"])
    return {
        "foundation_id": foundation["foundation_id"],
        "stage_options": stages,
        "default_stage": stages[0] if len(stages) == 1 else None,
        "active_expression_path_ids": active,
        "unsupported_active_path_ids": sorted(set(selected_path_ids) - supported),
        "dormant_expression_path_ids": sorted(supported - set(selected_path_ids)),
        "source": deepcopy(foundation["source"]),
        "source_record_sha256": sha256_json(foundation),
    }


def resolve_initial_foundation_state(
    foundation: dict[str, Any], selected_path_ids: list[str], *, stage: str | None = None,
) -> dict[str, Any]:
    """Resolve only an explicitly recorded initial stage, never a CL upgrade."""
    options = initial_foundation_options(foundation, selected_path_ids)
    chosen_stage = options["default_stage"] if stage is None else stage
    if chosen_stage is None:
        raise FoundryError(
            "CG1_FOUNDATION_INITIAL_STAGE_REQUIRED",
            "Choose one of this Foundation's published initial stages.",
            details={"foundation_id": options["foundation_id"], "stage_options": options["stage_options"]},
            status_code=409,
        )
    if not isinstance(chosen_stage, str) or chosen_stage not in options["stage_options"]:
        raise _invalid("unpublished_initial_stage", stage=chosen_stage, stage_options=options["stage_options"])
    resource_text = foundation["semantic_surfaces"]["resource"]
    pairs = re.findall(r"^\| \*\*([^*]+)\*\* \| (.*?) \|$", resource_text, re.MULTILINE)
    if len({key for key, _ in pairs}) != len(pairs):
        raise _invalid("duplicate_resource_rule")
    rules = dict(pairs)
    # The pinned playable release explicitly supplies these values for all30;
    # absence or a changed representation is not a default-zero permission.
    if rules.get("Maximum") != "1" or rules.get("Starting Amount") != "0":
        raise _invalid("initial_resource_authority")
    heading = re.search(r"^### ([^\n]+)$", resource_text, re.MULTILINE)
    if heading is None or foundation["foundation_resource"] != heading[1] + " 0/1":
        raise _invalid("resource_identity")
    return {
        "schema": FOUNDATION_INITIAL_STATE_SCHEMA,
        "foundation_id": options["foundation_id"],
        "stage": chosen_stage,
        "stage_origin": "published_initial_stage",
        "active_expression_path_ids": options["active_expression_path_ids"],
        "unsupported_active_path_ids": options["unsupported_active_path_ids"],
        "dormant_expression_path_ids": options["dormant_expression_path_ids"],
        "resource": {
            "resource_id": "foundation.resource." + options["foundation_id"],
            "name": heading[1], "initial_current": 0, "maximum": 1,
            "rules": rules,
            "source_surface_sha256": sha256_json(resource_text),
            "execution_authority": False,
        },
        "source": options["source"],
        "source_record_sha256": options["source_record_sha256"],
        "registry_sha256": release.REGISTRY_SHA256,
        "refill_current": False,
        "grants_path_attainment": False,
        "awards_stage_advancement": False,
    }


def foundation_passive_definitions(foundation: dict[str, Any]) -> dict[str, Any]:
    """Normalize printed passive inputs, retaining every condition verbatim.

    These are definitions, not evaluated character values. In particular a
    conditional speed benefit cannot become unconditional movement, a Path
    resource modifier cannot be copied into every pool, and a later stage's
    replacement must not be added once per character level.
    """
    foundation = _verified_record(foundation)
    features = foundation["semantic_surfaces"]["features"]
    blocks = re.split(r"^#### ", features, flags=re.MULTILINE)[1:]
    rows = []
    for block in blocks:
        name, _, body = block.partition("\n")
        # The next category heading is not part of this feature's body.
        body = re.split(r"^### ", body, maxsplit=1, flags=re.MULTILINE)[0]
        fields = dict(re.findall(r"^\*\*([^*]+):\*\* (.+)$", body, re.MULTILINE))
        trigger = fields.get("Trigger", "")
        explicitly_passive = (
            fields.get("Type") == "Passive"
            or trigger.casefold().startswith("always active")
            or fields.get("Limit", "").casefold().startswith("always active")
        )
        if not explicitly_passive:
            continue
        effect = fields.get("Effect")
        if not effect:
            raise _invalid("passive_effect_missing", feature=name)
        numeric = []
        normalized = effect.casefold()
        patterns = (
            ("hp_maximum", r"^(?:base: )?(?:your )?(?:maximum (?:hit points|hp)|hit point maximum) increases? by (twice )?(?:your )?(?:proficiency bonus|pb)"),
            ("path_resource_maximum", r"^(?:base: )?(?:your )?maximum (?:path resource|cp) increases? by (twice )?(?:your )?(?:proficiency bonus|pb)"),
        )
        for statistic, pattern in patterns:
            match = re.match(pattern, normalized)
            if match:
                units = 2 if match[1] else 1
                numeric.append({
                    "statistic": statistic,
                    "formula": {
                        "schema_version": "TianxiaFoundry.SafeFormula.v1",
                        "formula_id": f"foundation.{foundation['foundation_id']}.{statistic}.base.v1",
                        "root": {"op": "multiply", "terms": [{"op": "constant", "value": units}, {"op": "pb"}]},
                    },
                    "scope": "one_character_maximum" if statistic == "hp_maximum" else "supported_path_resource",
                })
        # Movement remains a conditional definition. The entire source trigger,
        # availability, effect and limit travel with it for causal evaluation.
        if re.search(r"\b(?:walking speed|your speed) increases by 5 (?:ft|feet)", normalized):
            numeric.append({
                "statistic": "speed_ft",
                "formula": {
                    "schema_version": "TianxiaFoundry.SafeFormula.v1",
                    "formula_id": f"foundation.{foundation['foundation_id']}.speed_ft.base.v1",
                    "root": {"op": "constant", "value": 5},
                },
                "scope": "source_condition_required",
            })
        rows.append({
            "name": name, "source_fields": fields, "numeric_base_definitions": numeric,
            "source_feature_sha256": sha256_json({"name": name, "fields": fields}),
            "execution_authority": False,
        })
    return {
        "schema": "TianxiaFoundry.FoundationPassiveDefinitions.v1",
        "foundation_id": foundation["foundation_id"],
        "source": deepcopy(foundation["source"]),
        "source_record_sha256": sha256_json(foundation),
        "passives": rows,
        "numeric_definitions_are_not_evaluated_values": True,
        "stage_advancement_inferred_from_cl": False,
    }


def resolve_initial_foundation_mechanics(
    foundation: dict[str, Any], selected_path_ids: list[str], *, stage: str | None = None,
) -> dict[str, Any]:
    """Compile source formulas eligible at an explicitly published initial stage.

    This does not apply bonuses to a character. Stage2 must bind the selected
    version, acquisition, stage and supported Paths before using these formulas
    in its existing calculators. Conditional effects keep their complete source
    fields instead of becoming unconditional numeric bonuses.
    """
    initial = resolve_initial_foundation_state(foundation, selected_path_ids, stage=stage)
    definitions = foundation_passive_definitions(foundation)
    chosen = initial["stage"]
    result = {
        "schema": FOUNDATION_INITIAL_MECHANICS_SCHEMA,
        "foundation_id": initial["foundation_id"],
        "initial_state": initial,
        "source_record_sha256": initial["source_record_sha256"],
        "resource_modifiers": [], "hp_maximum_modifiers": [], "statistic_modifiers": [],
        "conditional_modifiers": [],
        "source_passives": deepcopy(definitions["passives"]),
    }
    path_resources = {
        "tianxia.path.body_refining": "tianxia.resource.stamina",
        "tianxia.path.qi_cultivation": "tianxia.resource.qi",
        "tianxia.path.spirit_awakening": "tianxia.resource.resonance",
    }

    def availability(fields: dict[str, str], statistic: str) -> str:
        requirement = fields.get("Available At", "").split(";", 1)[0].strip()
        stable_required = "while foundation is stable" in fields.get("Limit", "").casefold()
        if stable_required and chosen == "Unstable":
            return "unavailable"
        # Latent is not the source's Common Expression or Awakened grant.
        # An Unstable status likewise cannot establish a ranked stage when
        # a feature explicitly requires one.
        if chosen == "Latent" and requirement != "Latent":
            return "unavailable"
        if requirement:
            allowed = {
                "Latent": {"Latent"},
                "Common Expression": {"Common Expression", "Awakened", "Integrated"},
                "Common Expression or higher": {"Common Expression", "Awakened", "Integrated"},
                "Awakened": {"Awakened", "Integrated"},
                "Awakened or higher": {"Awakened", "Integrated"},
                "Integrated": {"Integrated"},
                "Integrated or higher": {"Integrated"},
            }.get(requirement)
            if allowed is None or chosen == "Unstable":
                return "condition_required"
            if chosen not in allowed:
                return "unavailable"
        if statistic == "speed_ft" and re.search(
            r"while .*?(?:armor|restraints|footwork)", fields.get("Effect", ""), re.IGNORECASE,
        ):
            return "condition_required"
        return "available"

    for passive in definitions["passives"]:
        fields = passive["source_fields"]
        for definition in passive["numeric_base_definitions"]:
            statistic = definition["statistic"]
            modifier = {
                **deepcopy(definition),
                "source_feature_sha256": passive["source_feature_sha256"],
                "source_fields": deepcopy(fields),
                "feature_name": passive["name"],
                "availability": availability(fields, statistic),
            }
            formula = modifier["formula"]
            formula["formula_id"] = (
                f"foundation.{initial['foundation_id']}.{statistic}.initial."
                f"{chosen.lower().replace(' ', '-')}.v1"
            )
            # Only the selected published initial stage can enable an explicit
            # additive Integrated rider. Target CL never supplies that stage.
            effect = fields.get("Effect", "")
            if chosen == "Integrated" and statistic in {"hp_maximum", "path_resource_maximum"} and re.search(
                r"(?:Integrated:.*?another PB|reaches Integrated,.*?additional proficiency bonus)", effect,
                re.IGNORECASE,
            ):
                formula["root"]["terms"][0]["value"] += 1
            if modifier["availability"] != "available":
                result["conditional_modifiers"].append(modifier)
            elif statistic == "hp_maximum":
                # One character maximum contribution, independent of how many
                # compatible Path expressions are currently selected.
                result["hp_maximum_modifiers"].append(modifier)
            elif statistic == "path_resource_maximum":
                for path_id in initial["active_expression_path_ids"]:
                    result["resource_modifiers"].append({
                        **deepcopy(modifier), "path_id": path_id, "resource_id": path_resources[path_id],
                    })
            else:
                result["statistic_modifiers"].append(modifier)
    return result


def verified_initial_foundation_record_source(record):
    """Verify the installed payload after the caller proves its locked source."""
    from contracts.canonical import canonical_record_hash

    factory = (record.get("compatibility") or {}).get("factory") or {}
    authority = factory.get("stage2_authority") or {}
    mechanics = authority.get("initial_foundation_mechanics")
    if mechanics is None:
        if (record.get("content_binding") or {}).get("pack_version") == FOUNDATION_MECHANICS_PACK_VERSION:
            raise _invalid("missing_installed_mechanics")
        return None
    if not isinstance(mechanics, dict):
        raise _invalid("installed_mechanics_shape")
    source = record.get("non_sphere_foundation") or (factory.get("raw_projection") or {}).get("non_sphere_foundation")
    source = _verified_record(source)
    if (
        record.get("record_id") != source["foundation_id"]
        or record.get("content_type") != "foundation"
        or (record.get("content_binding") or {}).get("pack_id") != "tianxia.non_sphere.authority"
        or (record.get("content_binding") or {}).get("pack_version") != FOUNDATION_MECHANICS_PACK_VERSION
        or record.get("record_hash") != canonical_record_hash(record)
        or (record.get("publication") or {}).get("status") != "published"
        or not (record.get("selected_authority") is True or (factory.get("raw_projection") or {}).get("selected_authority") is True)
        or authority.get("authority_complete") is not True
        or authority.get("allowed_kinds") != ["foundation_acquisition"]
        or authority.get("allowed_channels") != ["foundation-selection"]
        or authority.get("foundation_id") != source["foundation_id"]
        or authority.get("rule_id") != f"ns1r.{source['foundation_id']}.initial-foundation-mechanics.v1"
        or mechanics.get("schema") != FOUNDATION_INITIAL_MECHANICS_SCHEMA
        or mechanics.get("registry_sha256") != release.REGISTRY_SHA256
        or mechanics.get("source_record_sha256") != sha256_json(source)
        or mechanics.get("initial_stage_options") != source["stage"].split(" or ")
        or canonical_json(mechanics.get("passive_definitions")) != canonical_json(foundation_passive_definitions(source))
        or mechanics.get("refill_current") is not False
        or mechanics.get("stage_advancement_inferred_from_cl") is not False
        or authority.get("minimum_cl") != 5
    ):
        raise _invalid("installed_record_mechanics_mismatch")
    return source


def initial_foundation_mechanics_for_record(record, selected_path_ids, *, stage=None):
    """Consume only a source-proved record of the supported installed version."""
    source = verified_initial_foundation_record_source(record)
    if source is None:
        return None
    return resolve_initial_foundation_mechanics(source, selected_path_ids, stage=stage)


def installed_foundation_state(mechanics, record_id, event_id):
    initial = deepcopy(mechanics["initial_state"])
    initial["resource"]["current"] = initial["resource"]["initial_current"]
    initial["resource"]["rule_descriptions"] = [
        {"name": name, "description": description}
        for name, description in sorted(initial["resource"]["rules"].items())
    ]
    return {
        **initial, "record_id": record_id, "event_id": event_id,
        "state": "active", "status": "dormant" if initial["stage"] == "Latent" else "unstable" if initial["stage"] == "Unstable" else "active",
        "expression_record_id": None, "path_id": None,
        "mechanics_schema": mechanics["schema"],
    }
