"""Deterministic Forged Technique construction and compilation.

The constructor takes the character's authenticated state (CL, PB, powering
Path, known Spheres and talents) and an optional concept, and walks the sealed
Core §11 tables under a seeded generator.  Everything numeric is recomputed by
``compile_forged_technique`` from the technique's typed choices, so a stored
technique whose numbers drift from the sealed tables fails closed.  Nothing is
invented: the effect text is the primary talent's published block, ranges and
areas are the Base Form's printed use, and every option names its table row.
"""
from __future__ import annotations

import hashlib
import random
import re
from copy import deepcopy
from functools import lru_cache
from typing import Any, Mapping, Sequence

from app.core import FoundryError, canonical_json, sha256_json

from .forging_authority import (
    augment as _augment_row,
    base_form as _base_form_row,
    drawback as _drawback_row,
    realm_at_least,
    realm_complexity_limit,
    realm_for_cl,
    recommended_maximum_spheres,
)

FORGED_TECHNIQUE_SCHEMA = "TianxiaFoundry.ForgedTechnique.v1"
FORGED_TECHNIQUE_REQUEST_SCHEMA = "TianxiaFoundry.ForgedTechniqueRequest.v1"
FORGED_TECHNIQUE_ACQUISITION_SCHEMA = "TianxiaFoundry.ForgedTechniqueAcquisition.v1"
FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_SCHEMA = "TianxiaFoundry.ForgedTechniqueAcquisitionAuthority.v1"
FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_VERSION = "server_owned_pre_provider.v2"
FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_ISSUER = "TianxiaFoundry.CharacterCreationExecutionService.v1"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
# Typed authority splits some Sphere effects into stable parent#variant IDs.
_EFFECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*(?:#[A-Za-z0-9][A-Za-z0-9._:-]*)?$")
_MAX_NAME = 120
_MAX_TEXT = 4000
# Published source blocks are not player-authored intent. Keep them intact:
# the catalog includes base-Sphere rules longer than the free-text limit.
_MAX_PUBLISHED_TEXT = 16_000

# Base Forms that already carry their activation in the printed use column.
_FORM_ACTION = {
    "counter": "reaction",
    "ritual": "ritual",
}
_TECHNIQUE_ID_PREFIX = "tianxia.constructed.forged_technique."
_REST_DRAWBACKS = frozenset({"once_per_short_rest", "once_per_long_rest"})
_ACTIVATION_AUGMENTS = frozenset({"bonus_action_activation", "reaction_activation"})


def _redundant_rest_drawbacks(rows: Sequence[Mapping[str, Any]]) -> bool:
    # Core §11.8 rejects restrictions that add no meaningful limitation.
    # A long-rest use limit already prevents a second use before a short rest.
    return _REST_DRAWBACKS.issubset(row["drawback_id"] for row in rows)


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("FORGED_TECHNIQUE_REQUEST_INVALID", message, details=details)


def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16))


def _clean_id(value: Any, field: str, *, sphere_effect: bool = False) -> str:
    pattern = _EFFECT_ID_RE if sphere_effect else _ID_RE
    if not isinstance(value, str) or not value or not pattern.fullmatch(value):
        raise _invalid("An identifier is missing or contains unsupported characters.", field=field, value=value)
    return value


def _clean_text(value: Any, field: str, *, maximum: int, allow_empty: bool = False) -> str:
    if value is None and allow_empty:
        return ""
    if not isinstance(value, str) or (not value.strip() and not allow_empty):
        raise _invalid("A text field must be a non-empty string.", field=field)
    text = value.strip()
    if len(text) > maximum or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        raise _invalid("A text field is too long or contains control characters.", field=field)
    return text


def normalize_forged_technique_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the constructor input and return a canonical copy."""
    if not isinstance(request, Mapping):
        raise _invalid("The forging request must be an object.")
    if request.get("schema") not in (None, FORGED_TECHNIQUE_REQUEST_SCHEMA):
        raise _invalid("The forging request declares an unsupported schema.", schema=request.get("schema"))
    seed = _clean_text(request.get("seed"), "seed", maximum=200)
    project_id = _clean_text(request.get("project_id"), "project_id", maximum=200)
    cl = request.get("cl")
    pb = request.get("pb")
    if type(cl) is not int or not 1 <= cl <= 20:
        raise _invalid("CL must be an integer from 1 to 20.", field="cl", value=cl)
    if type(pb) is not int or not 2 <= pb <= 6:
        raise _invalid("Proficiency Bonus must be an integer from 2 to 6.", field="pb", value=pb)
    path_id = _clean_id(request.get("path_id"), "path_id")
    key_ability = request.get("key_ability")
    if key_ability not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
        raise _invalid("The powering Path key ability must be a six-ability code.", field="key_ability", value=key_ability)
    spheres_in = request.get("known_spheres")
    talents_in = request.get("known_talents")
    if not isinstance(spheres_in, list) or not isinstance(talents_in, list):
        raise _invalid("Known Spheres and known Sphere effects must be lists.")
    known_spheres: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(spheres_in):
        if not isinstance(row, Mapping):
            raise _invalid("A known Sphere row must be an object.", field=f"known_spheres[{index}]")
        sphere_id = _clean_id(row.get("sphere_id"), f"known_spheres[{index}].sphere_id")
        known_spheres[sphere_id] = {
            "sphere_id": sphere_id,
            "display_name": _clean_text(row.get("display_name"), f"known_spheres[{index}].display_name", maximum=_MAX_NAME),
        }
    known_talents: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(talents_in):
        if not isinstance(row, Mapping):
            raise _invalid("A known talent row must be an object.", field=f"known_talents[{index}]")
        talent_id = _clean_id(row.get("talent_id"), f"known_talents[{index}].talent_id", sphere_effect=True)
        sphere_id = _clean_id(row.get("sphere_id"), f"known_talents[{index}].sphere_id")
        if sphere_id not in known_spheres:
            raise _invalid("A known talent names a Sphere the character does not know.", field=f"known_talents[{index}].sphere_id", value=sphere_id)
        source = row.get("source")
        if not isinstance(source, Mapping) or not isinstance(source.get("source_hash"), str) or not isinstance(source.get("path"), str):
            raise _invalid("A known talent must carry its published source binding.", field=f"known_talents[{index}].source")
        known_talents[talent_id] = {
            "talent_id": talent_id,
            "sphere_id": sphere_id,
            "display_name": _clean_text(row.get("display_name"), f"known_talents[{index}].display_name", maximum=_MAX_NAME),
            "record_hash": _clean_text(row.get("record_hash"), f"known_talents[{index}].record_hash", maximum=64),
            "source": {
                "source_id": source.get("source_id"),
                "path": source["path"],
                "anchor": source.get("anchor"),
                "source_hash": source["source_hash"],
            },
            "published_text": _clean_text(row.get("published_text"), f"known_talents[{index}].published_text", maximum=_MAX_PUBLISHED_TEXT, allow_empty=True),
        }
    if not known_talents:
        raise _invalid("Forging needs at least one known Sphere base ability or talent to supply the Primary Sphere Effect.", field="known_talents")
    concept_in = request.get("concept") or {}
    if not isinstance(concept_in, Mapping):
        raise _invalid("The concept must be an object.", field="concept")
    concept = {
        "name": _clean_text(concept_in.get("name"), "concept.name", maximum=_MAX_NAME, allow_empty=True) or None,
        "intent": _clean_text(concept_in.get("intent"), "concept.intent", maximum=_MAX_TEXT, allow_empty=True) or None,
        "base_form": concept_in.get("base_form"),
        "primary_talent_id": concept_in.get("primary_talent_id"),
        "secondary_talent_ids": list(concept_in.get("secondary_talent_ids") or []),
        "augment_ids": list(concept_in.get("augment_ids") or []),
        "drawback_ids": list(concept_in.get("drawback_ids") or []),
    }
    for field in ("base_form", "primary_talent_id"):
        if concept[field] is not None:
            concept[field] = _clean_id(concept[field], f"concept.{field}", sphere_effect=field == "primary_talent_id")
    for field in ("secondary_talent_ids", "augment_ids", "drawback_ids"):
        concept[field] = [_clean_id(value, f"concept.{field}", sphere_effect=field == "secondary_talent_ids") for value in concept[field]]
    if concept["primary_talent_id"] and concept["primary_talent_id"] not in known_talents:
        raise _invalid("The concept's primary talent is not known to the character.", field="concept.primary_talent_id", value=concept["primary_talent_id"])
    for talent_id in concept["secondary_talent_ids"]:
        if talent_id not in known_talents:
            raise _invalid("A concept secondary talent is not known to the character.", field="concept.secondary_talent_ids", value=talent_id)
    known_count = request.get("known_forged_technique_count", 0)
    if type(known_count) is not int or known_count < 0:
        raise _invalid("The known Forged Technique count must be a non-negative integer.", field="known_forged_technique_count")
    return {
        "schema": FORGED_TECHNIQUE_REQUEST_SCHEMA,
        "seed": seed,
        "project_id": project_id,
        "cl": cl,
        "pb": pb,
        "path_id": path_id,
        "key_ability": key_ability,
        "known_spheres": [known_spheres[key] for key in sorted(known_spheres)],
        "known_talents": [known_talents[key] for key in sorted(known_talents)],
        "known_forged_technique_count": known_count,
        "concept": concept,
    }


def _effect_row(talent: Mapping[str, Any], sphere: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sphere_id": sphere["sphere_id"],
        "sphere_name": sphere["display_name"],
        "talent_id": talent["talent_id"],
        "talent_name": talent["display_name"],
        "talent_record_hash": talent["record_hash"],
        "source": deepcopy(talent["source"]),
        "published_text": talent.get("published_text") or "",
    }


def forged_technique_id(technique: Mapping[str, Any]) -> str:
    """Return the deterministic identity for a fully typed technique."""
    return _TECHNIQUE_ID_PREFIX + sha256_json(
        {key: value for key, value in technique.items() if key != "technique_id"}
    )[:40]


def _action_type(form_id: str, augment_ids: set[str]) -> str:
    """Resolve activation from the sealed Base Form and Augment choices."""
    if _ACTIVATION_AUGMENTS.issubset(augment_ids):
        raise FoundryError(
            "FORGING_ACTIVATION_AMBIGUOUS",
            "This technique format supports one activation mode; choose either Bonus-Action Activation or Reaction Activation.",
        )
    if "bonus_action_activation" in augment_ids:
        return "bonus action"
    if "reaction_activation" in augment_ids or _FORM_ACTION.get(form_id) == "reaction":
        return "reaction"
    if _FORM_ACTION.get(form_id):
        return _FORM_ACTION[form_id]
    return "action"


def construct_forged_technique(authority: Mapping[str, Any], request: Mapping[str, Any], *, generator_version: int = 2, design_policy: str | None = "single_resolution_v1") -> dict[str, Any]:
    """Walk the sealed tables under a seeded generator and return a technique.

    Concept fields are honoured when legal; anything the concept leaves open
    is chosen by the generator.  The result is fully typed and carries the
    seed, so the same request always yields the same technique.
    """
    if type(generator_version) is not int or generator_version not in {1, 2, 3}:
        raise FoundryError("FORGING_GENERATOR_VERSION_UNSUPPORTED", "The Forged Technique generator version is unsupported.")
    normalized = normalize_forged_technique_request(request)
    cl = normalized["cl"]
    pb = normalized["pb"]
    realm = realm_for_cl(cl)
    access_cl = int(authority["access"]["minimum_cl"])
    if cl < access_cl:
        raise FoundryError("FORGING_NOT_AVAILABLE", "Technique Forging becomes available at Foundation, CL 5; Mortal-Realm forging needs GM permission.", details={"cl": cl, "minimum_cl": access_cl})
    if normalized["known_forged_technique_count"] >= pb:
        raise FoundryError("FORGING_KNOWN_LIMIT_REACHED", "Maximum known Forged Techniques equals Proficiency Bonus.", details={"known": normalized["known_forged_technique_count"], "pb": pb})
    limit = realm_complexity_limit(authority, realm)
    max_complexity = int(limit["maximum_complexity"])
    max_spheres = recommended_maximum_spheres(authority, realm)
    rng = _rng(normalized["seed"])
    spheres = {row["sphere_id"]: row for row in normalized["known_spheres"]}
    talents = {row["talent_id"]: row for row in normalized["known_talents"]}
    concept = normalized["concept"]
    if generator_version == 3 and (not concept["primary_talent_id"] or not concept["base_form"]):
        raise FoundryError("FORGING_EXPLICIT_CONCEPT_REQUIRED", "An explicit Forge design must name its primary source and Base Form.")

    # Primary Sphere Effect: one effect from a known Sphere base ability or talent.
    primary_id = concept["primary_talent_id"] or rng.choice(sorted(talents))
    primary = talents[primary_id]
    primary_effect = _effect_row(primary, spheres[primary["sphere_id"]])

    # Base Form.  The concept may name one; otherwise pick a form whose
    # Complexity leaves room under the Realm cap.
    # Ritual's CP "varies" by ruling, so the generator never draws it; a
    # concept may still name it and is refused below with the published reason.
    forms = [row for row in authority["base_forms"] if int(row["complexity"]) <= max_complexity and row.get("starting_cp") is not None]
    if concept["base_form"]:
        form = _base_form_row(authority, concept["base_form"])
        if int(form["complexity"]) > max_complexity:
            raise FoundryError("FORGING_COMPLEXITY_EXCEEDED", "The Base Form alone exceeds the Realm's Complexity limit.", details={"base_form": form["form_id"], "realm": realm})
    else:
        form = dict(rng.choice(forms))
    complexity = int(form["complexity"])
    spheres_used = [primary["sphere_id"]]

    # Secondary Sphere Effects: each additional Sphere is +1 Complexity.
    secondary_effects: list[dict[str, Any]] = []
    candidates = [tid for tid in sorted(talents) if talents[tid]["sphere_id"] not in spheres_used]
    if concept["secondary_talent_ids"] or generator_version == 3:
        chosen = [talents[tid] for tid in concept["secondary_talent_ids"]]
    else:
        # Most techniques express one or two Spheres; leave Complexity for Augments.
        target_spheres = min(max_spheres, 1 + rng.choice([0, 0, 1, 1, 2])) if candidates else 1
        chosen = []
        while candidates and len(spheres_used) + len(chosen) < target_spheres:
            pick = talents[rng.choice(candidates)]
            chosen.append(pick)
            candidates = [tid for tid in candidates if talents[tid]["sphere_id"] != pick["sphere_id"]]
    for talent in chosen:
        if talent["sphere_id"] in spheres_used:
            raise FoundryError("FORGING_SECONDARY_SPHERE_DUPLICATE", "A Secondary Sphere Effect repeats a Sphere already used.", details={"talent_id": talent["talent_id"]})
        if len(spheres_used) >= max_spheres:
            raise FoundryError("FORGING_SPHERE_LIMIT_EXCEEDED", "The technique uses more Spheres than the Realm's recommended maximum.", details={"realm": realm, "maximum_spheres": max_spheres})
        if complexity + int(authority["secondary_sphere_effect"]["complexity_per_additional_sphere"]) > max_complexity:
            if concept["secondary_talent_ids"]:
                raise FoundryError("FORGING_COMPLEXITY_EXCEEDED", "A Secondary Sphere Effect exceeds the Realm's Complexity limit.", details={"realm": realm, "maximum_complexity": max_complexity})
            break
        complexity += int(authority["secondary_sphere_effect"]["complexity_per_additional_sphere"])
        spheres_used.append(talent["sphere_id"])
        secondary_effects.append(_effect_row(talent, spheres[talent["sphere_id"]]))

    # Augments: fill remaining Complexity, honouring minimum Realm.
    augments: list[dict[str, Any]] = []
    legal = [row for row in authority["augments"] if realm_at_least(realm, row["minimum_realm"])]
    if concept["augment_ids"] or generator_version == 3:
        wanted = [_augment_row(authority, aid) for aid in concept["augment_ids"]]
        for row in wanted:
            if not realm_at_least(realm, row["minimum_realm"]):
                raise FoundryError("FORGING_AUGMENT_REALM_TOO_LOW", "An Augment needs a higher Realm than the character has.", details={"augment_id": row["augment_id"], "minimum_realm": row["minimum_realm"], "realm": realm})
            if complexity + int(row["complexity"]) > max_complexity:
                raise FoundryError("FORGING_COMPLEXITY_EXCEEDED", "An Augment exceeds the Realm's Complexity limit.", details={"augment_id": row["augment_id"], "realm": realm, "maximum_complexity": max_complexity})
            complexity += int(row["complexity"])
            augments.append(row)
    else:
        remaining = [row for row in legal]
        if design_policy is not None:
            # Spend the random design's Complexity on something its delivery
            # can use. Explicit concepts retain every legal table choice and
            # receive a concrete validation error when incompatible.
            area_forms = {"burst", "cone", "line", "aura", "zone"}
            unusable = set()
            if form["form_id"] not in area_forms:
                unusable.add("expanded_area")
            if form["form_id"] not in {"burst", "cone", "line"}:
                unusable.add("persistent_zone")
            if form["form_id"] in {"strike", "movement", "aura", "cone", "line"}:
                unusable.add("extended_range")
            from combat.forged import payload
            from .forge_design import walk
            source_mechanics = design_mechanics()
            source_ids = [primary_id, *[row["talent_id"] for row in secondary_effects]]
            if all(tid in source_mechanics for tid in source_ids):
                if not any(effect.get("type") in {"damage", "extra_damage"}
                           for tid in source_ids
                           for effect in walk(payload(source_mechanics[tid])["effects"])):
                    unusable.update({"increased_damage", "ignore_resistance"})
            remaining = [row for row in remaining if row["augment_id"] not in unusable]
        # Aim for a signature technique near the cap, leaving room only when
        # the generator says so.
        target = rng.randint(max(complexity, max_complexity - 2), max_complexity)
        while complexity < target and remaining:
            fits = [row for row in remaining if complexity + int(row["complexity"]) <= target]
            if not fits:
                break
            row = dict(rng.choice(fits))
            complexity += int(row["complexity"])
            augments.append(row)
            remaining = [r for r in remaining if r["augment_id"] != row["augment_id"]]
            if generator_version >= 2 and row["augment_id"] in _ACTIVATION_AUGMENTS:
                remaining = [r for r in remaining if r["augment_id"] not in _ACTIVATION_AUGMENTS]
    if len({row["augment_id"] for row in augments}) != len(augments):
        raise FoundryError("FORGING_AUGMENT_DUPLICATE", "An Augment is listed twice.", details={"augment_ids": [row["augment_id"] for row in augments]})

    # CP: Base Form starting CP plus Augment CP; Ritual has no fixed CP.
    starting_cp = form.get("starting_cp")
    if starting_cp is None:
        raise FoundryError("FORGING_BASE_FORM_CP_UNPUBLISHED", "The Ritual Base Form's CP varies by ruling; the Factory does not construct it.", details={"base_form": form["form_id"]})
    augment_cp = sum(int(row["cp"]) for row in augments)
    gross_cp = int(starting_cp) + augment_cp

    # Drawbacks: reduce CP, never below 1, by at most PB in total.
    drawbacks: list[dict[str, Any]] = []
    reduction = 0
    if concept["drawback_ids"] or generator_version == 3:
        for did in concept["drawback_ids"]:
            row = _drawback_row(authority, did)
            if reduction + int(row["cp_reduction"]) > pb or gross_cp - reduction - int(row["cp_reduction"]) < int(authority["drawback_rules"]["minimum_final_cp"]):
                raise FoundryError("FORGING_DRAWBACK_LIMIT_EXCEEDED", "Drawbacks cannot reduce CP below 1 or by more than Proficiency Bonus.", details={"drawback_id": did, "pb": pb})
            reduction += int(row["cp_reduction"])
            drawbacks.append(row)
    else:
        pool = list(authority["drawbacks"])
        count = rng.randint(0, 2)
        while count and pool:
            row = dict(rng.choice(pool))
            pool = [r for r in pool if r["drawback_id"] != row["drawback_id"]]
            if generator_version >= 2 and _redundant_rest_drawbacks([*drawbacks, row]):
                continue
            if reduction + int(row["cp_reduction"]) > pb or gross_cp - reduction - int(row["cp_reduction"]) < int(authority["drawback_rules"]["minimum_final_cp"]):
                continue
            reduction += int(row["cp_reduction"])
            drawbacks.append(row)
            count -= 1
    if len({row["drawback_id"] for row in drawbacks}) != len(drawbacks):
        raise FoundryError("FORGING_DRAWBACK_DUPLICATE", "A Drawback is listed twice.", details={"drawback_ids": [row["drawback_id"] for row in drawbacks]})
    if _redundant_rest_drawbacks(drawbacks):
        raise FoundryError("FORGING_DRAWBACK_REDUNDANT", "Once per Long Rest already includes the Once per Short Rest restriction.")
    backlash = None
    if any(row["drawback_id"] == "backlash" for row in drawbacks):
        backlash = {
            "trigger": rng.choice(list(authority["backlash"]["default_triggers"])),
            "consequence": rng.choice(list(authority["backlash"]["default_effects"])),
            "rule": "Backlash is not automatically Exhaustion.",
        }
    exhausting = any(row["drawback_id"] == "exhausting" for row in drawbacks)

    # Activation: the Base Form's printed use, or a paid action-economy Augment.
    augment_ids = {row["augment_id"] for row in augments}
    action_type = _action_type(form["form_id"], augment_ids)
    hostile_condition = any(row["augment_id"] in {"major_condition", "minor_hindrance", "severe_hindrance", "forced_movement"} for row in augments)

    name = concept["name"] or _default_name(rng, form, primary_effect, secondary_effects)
    technique = {
        "schema": FORGED_TECHNIQUE_SCHEMA,
        "name": name,
        "owner_project_id": normalized["project_id"],
        "cl_created": cl,
        "pb_at_creation": pb,
        "realm": realm,
        "powering_path_id": normalized["path_id"],
        "key_ability": normalized["key_ability"],
        "base_form": {"form_id": form["form_id"], "display_name": form["display_name"], "starting_cp": int(starting_cp), "complexity": int(form["complexity"]), "use": form["use"]},
        "primary_sphere_effect": primary_effect,
        "secondary_sphere_effects": secondary_effects,
        "augments": [{"augment_id": row["augment_id"], "display_name": row["display_name"], "tier": row["tier"], "complexity": int(row["complexity"]), "cp": int(row["cp"]), "minimum_realm": row["minimum_realm"]} for row in augments],
        "drawbacks": [{"drawback_id": row["drawback_id"], "display_name": row["display_name"], "cp_reduction": int(row["cp_reduction"]), "restriction": row["restriction"]} for row in drawbacks],
        "backlash": backlash,
        "exhausting": exhausting,
        "action_type": action_type,
        "cp_cost": {"base_form": int(starting_cp), "augments": augment_cp, "drawback_reduction": reduction, "final": gross_cp - reduction},
        "complexity": {"base_form": int(form["complexity"]), "secondary_spheres": len(secondary_effects), "augments": sum(int(row["complexity"]) for row in augments), "final": complexity, "realm_maximum": max_complexity},
        "spheres_used": len(spheres_used),
        "sphere_ids_used": list(spheres_used),
        "target_range_area": f"{form['display_name']}: {form['use']}; the Primary Sphere Effect's printed range and targets apply unless an Augment extends them.",
        "attack_save_check": (
            "Hostile conditions require a saving throw against the Cultivation Save DC; attacks and checks resolve as the Primary Sphere Effect prints."
            if hostile_condition else "As the Primary Sphere Effect prints."
        ),
        "effect": {
            "summary": _effect_summary(form, primary_effect, secondary_effects, augments),
            "primary_effect_text": primary_effect["published_text"],
            "augment_names": [row["display_name"] for row in augments],
        },
        "duration": "As the Primary Sphere Effect prints; Aura and Zone forms persist as their Base Form states; Lingering Effect or Persistent Zone extends the effect when chosen.",
        "limits": [row["restriction"] for row in drawbacks] + ([f"Backlash: {backlash['trigger']} -> {backlash['consequence']}"] if backlash else []),
        "technique_forging_dc": _forging_dc(authority, complexity, len(spheres_used)),
        "research_days": max(int(authority["forging_check"]["research_days"]["minimum"]), int(authority["forging_check"]["research_days"]["per_complexity"]) * complexity),
        "material_cost_gp": int(authority["forging_check"]["material_cost_gp"]["per_complexity_squared"]) * complexity * complexity,
        "evolution_state": "base",
        "hard_limits": list(authority["hard_limits"]),
        "source_notes": [
            {"kind": "forging_rules", **authority["sources"]["core_rules"]},
            {"kind": "forging_rules", **authority["sources"]["phb_chapter_18"]},
            {"kind": "primary_effect", **primary_effect["source"], "talent_id": primary_effect["talent_id"]},
            *[{"kind": "secondary_effect", **row["source"], "talent_id": row["talent_id"]} for row in secondary_effects],
        ],
        "construction": {
            "seed": normalized["seed"],
            "concept": deepcopy(concept),
            "request": deepcopy(normalized),
            "request_sha256": sha256_json(normalized),
            "authority_seal_sha256": authority.get("seal_sha256"),
            "rule_ids": [authority["access"]["rule_id"], authority["forging_check"]["rule_id"], authority["known_limit"]["rule_id"]],
        },
    }
    if generator_version >= 2:
        # Version the seeded selection policy. Legacy records omit this field
        # and replay the original draw sequence, still under strict compilation.
        technique["construction"]["generator_version"] = generator_version
    from .forge_design import POLICY
    if design_policy is not None:
        if design_policy != POLICY:
            raise FoundryError("FORGING_DESIGN_POLICY_UNKNOWN", "The Forged Technique design policy is unsupported.")
        technique["design_policy"] = POLICY
        try:
            design = validate_forged_design(technique)
        except FoundryError as exc:
            # An automatic random draft is not an owner choice. Deterministically
            # try simple source-known designs instead of aborting character
            # creation because its random draft was unusable. Explicit concepts
            # stay explicit and receive the design error for review.
            explicit = any(concept.get(key) for key in ("primary_talent_id", "base_form", "secondary_talent_ids", "augment_ids", "drawback_ids"))
            if exc.code != "FORGING_DESIGN_REJECTED" or explicit:
                raise
            for talent_id in sorted(talents):
                for fallback_form in ("projection", "burst", "ward", "movement"):
                    for fallback_augments in ([], ["major_condition"]):
                        fallback = deepcopy(normalized)
                        fallback["concept"] = {"name": concept["name"], "intent": concept["intent"],
                                               "primary_talent_id": talent_id, "base_form": fallback_form,
                                               "secondary_talent_ids": [], "augment_ids": fallback_augments,
                                               "drawback_ids": []}
                        try:
                            return construct_forged_technique(authority, fallback, generator_version=3, design_policy=design_policy)
                        except FoundryError as rejected:
                            if rejected.code not in {"FORGING_DESIGN_REJECTED", "FORGING_COMPLEXITY_EXCEEDED"}:
                                raise
            raise
        if design and any(row.get("type") == "save" for row in design.get("effects", [])):
            technique["attack_save_check"] = "One saving throw against your Cultivation Save DC resolves the technique and its riders together. On a failure, apply the full effect; on a success, take half damage if any."
    technique["technique_id"] = forged_technique_id(technique)
    compile_forged_technique(authority, technique, cl=cl, pb=pb, known_talent_ids=set(talents), known_forged_technique_count=normalized["known_forged_technique_count"])
    return technique


def validate_forged_design(technique):
    """Reject unsafe delivery combinations before a new record is admitted.

    Synthetic/source-only records without installed typed mechanics continue
    through the existing sealed-table validator; they cannot claim a clean
    executable-design audit.
    """
    from .forge_design import design_issues
    from combat.forged import as_reaction, mechanic_for
    mechanics = design_mechanics()
    primary = technique["primary_sphere_effect"]["talent_id"]
    if primary not in mechanics:
        return
    mechanic = mechanic_for(technique, mechanics)
    if mechanic and technique.get("action_type") == "reaction":
        mechanic = as_reaction(technique, mechanic, mechanics)
    issues = design_issues(mechanic) if mechanic else ["unportable_primary_effect"]
    if issues:
        raise FoundryError("FORGING_DESIGN_REJECTED", "Choose a different form, source effect or Augment: this design cannot deliver a meaningful payoff with one roll.", details={"issues": issues})
    return mechanic


@lru_cache(maxsize=1)
def design_mechanics():
    # The authority is immutable for a process, just like the combat compiler's
    # installed authority. Cache the large file across seeded design attempts.
    import json
    from pathlib import Path
    return json.loads((Path(__file__).resolve().parents[2] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]


def _default_name(rng: random.Random, form: Mapping[str, Any], primary: Mapping[str, Any], secondary: Sequence[Mapping[str, Any]]) -> str:
    lead = primary["sphere_name"]
    tail = secondary[0]["sphere_name"] if secondary else primary["talent_name"]
    patterns = [
        f"{lead} {form['display_name']}",
        f"{tail} {form['display_name']} of {lead}",
        f"{lead}-{tail} {form['display_name']}",
    ]
    return rng.choice(patterns)[:_MAX_NAME]


def _effect_summary(form: Mapping[str, Any], primary: Mapping[str, Any], secondary: Sequence[Mapping[str, Any]], augments: Sequence[Mapping[str, Any]]) -> str:
    parts = [f"A {form['display_name']} ({form['use']}) expressing {primary['talent_name']} ({primary['sphere_name']})"]
    if secondary:
        parts.append("with " + ", ".join(f"{row['talent_name']} ({row['sphere_name']})" for row in secondary))
    if augments:
        parts.append("augmented by " + ", ".join(row["display_name"] for row in augments))
    return " ".join(parts) + "."


def _forging_dc(authority: Mapping[str, Any], complexity: int, spheres: int) -> int:
    dc = authority["forging_check"]["dc"]
    return int(dc["base"]) + int(dc["per_complexity"]) * complexity + int(dc["per_sphere"]) * spheres


def forged_technique_acquisition_authority() -> dict[str, str]:
    """Return the durable issuer/version marker for new creator proofs."""
    return {
        "schema": FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_SCHEMA,
        "version": FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_VERSION,
        "issuer": FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_ISSUER,
    }


def validate_forged_technique_acquisition(
    acquisition: Mapping[str, Any],
    *,
    event_id: str,
    record_id: str,
    record_hash: str,
    cl: int,
    path_id: str,
    key_ability: str,
    ability_modifier: int,
    pb: int,
    dc: int,
    research_days: int,
    material_cost_gp: int,
    require_derived_fields: bool = False,
    require_authority_binding: bool = False,
) -> dict[str, Any]:
    """Validate the bounded acquisition proof for one forged technique.

    The construction record supplies the published DC, research and material
    requirements.  This helper accepts only the bounded d20 and provenance
    fields as input, then derives every result field and the retry history.
    It is shared by Stage 2 and the projector so a forged success cannot be
    created by copying an authored total or result into an event.
    """

    def reject(message: str, **details: Any) -> FoundryError:
        return FoundryError(
            "FORGED_TECHNIQUE_ACQUISITION_INVALID",
            message,
            details={"record_id": record_id, **details},
        )

    if not isinstance(acquisition, Mapping):
        raise reject("A Forged Technique needs a typed acquisition proof.")
    if acquisition.get("schema") != FORGED_TECHNIQUE_ACQUISITION_SCHEMA:
        raise reject("The Forged Technique acquisition proof declares an unsupported schema.")
    authority = acquisition.get("authority")
    expected_authority = forged_technique_acquisition_authority()
    if require_authority_binding and authority != expected_authority:
        raise reject("A new creator Forged Technique proof must carry its server-owned authority binding.")
    if authority is not None and authority != expected_authority:
        raise reject("The Forged Technique proof carries an unsupported server-owned authority binding.")
    if acquisition.get("mode") != "creator_generated_history" or acquisition.get("scope") != "initial_creation":
        raise reject("Forged Technique historical provenance must be scoped to initial creation.")
    if acquisition.get("observed_play") is not False or acquisition.get("live_currency_debit") is not False:
        raise reject("Creator-generated forging history cannot claim observed play or a live currency debit.")
    if acquisition.get("target_cl") != cl or acquisition.get("record_id") != record_id or acquisition.get("record_hash") != record_hash:
        raise reject("The forging acquisition proof is bound to a different target or record snapshot.")
    if acquisition.get("powering_path_id") != path_id or acquisition.get("key_ability") != key_ability:
        raise reject("The forging acquisition proof is bound to a different Powering Path or ability.")
    if acquisition.get("pb") not in (None, pb) or acquisition.get("ability_modifier") not in (None, ability_modifier) or acquisition.get("dc") not in (None, dc):
        raise reject("The forging acquisition proof contains authored or stale check inputs.")
    if require_derived_fields and (
        acquisition.get("pb") != pb
        or acquisition.get("ability_modifier") != ability_modifier
        or acquisition.get("dc") != dc
    ):
        raise reject("The persisted forging acquisition proof is missing a server-derived check input.")

    research = acquisition.get("research")
    if not isinstance(research, Mapping):
        raise reject("Forging research completion is required.")
    required_hours = research_days * 8
    if (
        research.get("required_days") != research_days
        or research.get("meaningful_training_hours") != required_hours
        or research.get("completed") is not True
    ):
        raise reject("Forging research must cover the exact published duration.", expected_days=research_days, expected_hours=required_hours)

    materials = acquisition.get("materials")
    if not isinstance(materials, Mapping):
        raise reject("Forging material completion is required.")
    if (
        materials.get("required_gp") != material_cost_gp
        or materials.get("paid_gp") != material_cost_gp
        or materials.get("payment_complete") is not True
    ):
        raise reject("Forging materials must record the exact published cost.", expected_gp=material_cost_gp)

    location = acquisition.get("training_location")
    if not isinstance(location, Mapping) or location.get("mode") != "creator_generated_history" or location.get("scope") != "initial_creation" or location.get("suitable") is not True:
        raise reject("Forging requires a suitable creator-history training location.")

    completion = acquisition.get("completion")
    if not isinstance(completion, Mapping) or completion.get("mode") != "creator_generated_history" or completion.get("scope") != "initial_creation" or completion.get("record_id") != record_id or completion.get("record_hash") != record_hash or completion.get("research_complete") is not True or completion.get("payment_complete") is not True:
        raise reject("Forging completion and payment provenance are incomplete.")
    if completion.get("event_id") not in (None, event_id):
        raise reject("Forging completion provenance is bound to a different event.")

    attempts = acquisition.get("attempts")
    if not isinstance(attempts, list) or not attempts or len(attempts) > 8:
        raise reject("Forging requires one to eight ordered attempts.")
    full_materials = material_cost_gp
    half_materials = material_cost_gp // 2
    full_hours = required_hours
    half_hours = full_hours // 2
    normalized_attempts: list[dict[str, Any]] = []
    seen_attempt_ids: set[str] = set()
    previous_attempt_id: str | None = None
    successful_attempt_index: int | None = None
    for index, raw_attempt in enumerate(attempts):
        if not isinstance(raw_attempt, Mapping):
            raise reject("Every forging attempt must be an object.", attempt_index=index)
        attempt_id = raw_attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id.strip() or attempt_id in seen_attempt_ids:
            raise reject("Every forging attempt needs a unique identity.", attempt_index=index)
        retry_of = raw_attempt.get("retry_of_attempt_id")
        if retry_of != previous_attempt_id:
            raise reject("Forging retries must form one ordered chain.", attempt_index=index, expected_retry_of=previous_attempt_id, actual_retry_of=retry_of)
        check_die = raw_attempt.get("check_die_result")
        if type(check_die) is not int or not 1 <= check_die <= 20:
            raise reject("Forging accepts only a bounded d20 result.", attempt_index=index)
        supplied_keys = set(raw_attempt)
        allowed_input_keys = {"attempt_id", "retry_of_attempt_id", "check_die_result", "research_time_hours", "materials_paid_gp"}
        derived_keys = {
            "target_record_id", "target_record_hash", "character_cl", "check_ability", "pb", "ability_modifier", "dc", "computed_dc", "computed_check_total", "result", "research_complete", "payment_complete"
        }
        authored_keys = supplied_keys - allowed_input_keys - derived_keys
        if authored_keys:
            raise reject("A forging attempt contains unsupported authored fields.", attempt_index=index, fields=sorted(authored_keys))
        if not require_derived_fields and supplied_keys & derived_keys:
            raise reject("A forging attempt may supply only its bounded die and retry/payment inputs.", attempt_index=index, fields=sorted(supplied_keys & derived_keys))
        total = check_die + pb + ability_modifier
        result = "success" if total >= dc else "failure"
        expected_hours = full_hours if result == "success" else half_hours
        expected_materials = full_materials if result == "success" else half_materials
        if raw_attempt.get("research_time_hours") != expected_hours or raw_attempt.get("materials_paid_gp") != expected_materials:
            raise reject(
                "Forging research and material payment must match the derived attempt result.",
                attempt_index=index,
                result=result,
                expected_research_time_hours=expected_hours,
                expected_materials_paid_gp=expected_materials,
            )
        if result == "success" and index != len(attempts) - 1:
            raise reject("A successful forging attempt must end the retry history.", attempt_index=index)
        if result == "success":
            successful_attempt_index = index
        normalized = {
            "attempt_id": attempt_id,
            "retry_of_attempt_id": retry_of,
            "target_record_id": record_id,
            "target_record_hash": record_hash,
            "character_cl": cl,
            "check_die_result": check_die,
            "check_ability": key_ability,
            "pb": pb,
            "ability_modifier": ability_modifier,
            "computed_dc": dc,
            "computed_check_total": total,
            "result": result,
            "research_time_hours": expected_hours,
            "materials_paid_gp": expected_materials,
            "research_complete": result == "success",
            "payment_complete": result == "success",
        }
        if require_derived_fields:
            for field, expected in normalized.items():
                if field in {"attempt_id", "retry_of_attempt_id", "target_record_id", "target_record_hash", "character_cl", "check_die_result", "research_time_hours", "materials_paid_gp"}:
                    continue
                if raw_attempt.get(field) != expected:
                    raise reject("The persisted forging attempt contains authored or stale derived data.", attempt_index=index, field=field)
        normalized_attempts.append(normalized)
        seen_attempt_ids.add(attempt_id)
        previous_attempt_id = attempt_id
    if successful_attempt_index is None:
        raise reject("The forging check failed; the technique cannot become known.", result="failure")

    normalized_acquisition = deepcopy(dict(acquisition))
    normalized_acquisition["pb"] = pb
    normalized_acquisition["ability_modifier"] = ability_modifier
    normalized_acquisition["dc"] = dc
    normalized_acquisition["attempts"] = normalized_attempts
    normalized_acquisition["completion"] = deepcopy(dict(completion))
    normalized_acquisition["completion"]["event_id"] = event_id
    normalized_acquisition["research"] = deepcopy(dict(research))
    normalized_acquisition["materials"] = deepcopy(dict(materials))
    normalized_acquisition["training_location"] = deepcopy(dict(location))
    return normalized_acquisition


def compile_forged_technique(
    authority: Mapping[str, Any],
    technique: Mapping[str, Any],
    *,
    cl: int,
    pb: int,
    known_talent_ids: set[str],
    known_forged_technique_count: int,
) -> dict[str, Any]:
    """Recompute every number from the sealed tables and fail closed on drift.

    Returns the compiled figures so a Stage 2 calculation can carry them.
    """
    def block(code: str, message: str, **details: Any) -> FoundryError:
        return FoundryError(code, message, details={"technique_id": technique.get("technique_id"), **details})

    if technique.get("schema") != FORGED_TECHNIQUE_SCHEMA:
        raise block("FORGED_TECHNIQUE_SCHEMA_INVALID", "The Forged Technique declares an unsupported schema.")
    construction = technique.get("construction")
    if not isinstance(construction, Mapping) or not isinstance(construction.get("request"), Mapping):
        raise block("FORGED_TECHNIQUE_CONSTRUCTION_INVALID", "The Forged Technique has no normalized construction request.")
    generator_version = construction.get("generator_version", 1)
    if type(generator_version) is not int or generator_version not in {1, 2, 3}:
        raise block("FORGING_GENERATOR_VERSION_UNSUPPORTED", "The Forged Technique generator version is unsupported.")
    realm = realm_for_cl(cl)
    if cl < int(authority["access"]["minimum_cl"]):
        raise block("FORGING_NOT_AVAILABLE", "Technique Forging becomes available at Foundation, CL 5.", cl=cl)
    if technique.get("cl_created") != cl or technique.get("realm") != realm:
        raise block("FORGED_TECHNIQUE_REALM_MISMATCH", "The technique's creation CL and Realm do not match the compile point.", cl=cl, realm=realm)
    if technique.get("pb_at_creation") != pb:
        raise block("FORGED_TECHNIQUE_PB_MISMATCH", "The technique's creation Proficiency Bonus does not match the compile point.", pb=pb)
    if known_forged_technique_count >= pb:
        raise block("FORGING_KNOWN_LIMIT_REACHED", "Maximum known Forged Techniques equals Proficiency Bonus.", known=known_forged_technique_count, pb=pb)
    form = _base_form_row(authority, technique["base_form"]["form_id"])
    if form.get("starting_cp") is None:
        raise block("FORGING_BASE_FORM_CP_UNPUBLISHED", "The Ritual Base Form's CP is not published.")
    primary = technique["primary_sphere_effect"]
    effects = [primary, *technique.get("secondary_sphere_effects", [])]
    for row in effects:
        if row["talent_id"] not in known_talent_ids:
            raise block("FORGING_TALENT_NOT_KNOWN", "A Forged Technique cannot replace talents the character does not know.", talent_id=row["talent_id"])
    sphere_ids = [row["sphere_id"] for row in effects]
    if len(set(sphere_ids)) != len(sphere_ids):
        raise block("FORGING_SECONDARY_SPHERE_DUPLICATE", "Each Sphere may supply one effect.")
    if len(sphere_ids) > recommended_maximum_spheres(authority, realm):
        raise block("FORGING_SPHERE_LIMIT_EXCEEDED", "The technique uses more Spheres than the Realm's recommended maximum.", realm=realm)
    augments = [_augment_row(authority, row["augment_id"]) for row in technique.get("augments", [])]
    if len({row["augment_id"] for row in augments}) != len(augments):
        raise block("FORGING_AUGMENT_DUPLICATE", "An Augment is listed twice.")
    for row in augments:
        if not realm_at_least(realm, row["minimum_realm"]):
            raise block("FORGING_AUGMENT_REALM_TOO_LOW", "An Augment needs a higher Realm.", augment_id=row["augment_id"], minimum_realm=row["minimum_realm"])
    complexity = int(form["complexity"]) + (len(effects) - 1) * int(authority["secondary_sphere_effect"]["complexity_per_additional_sphere"]) + sum(int(row["complexity"]) for row in augments)
    max_complexity = int(realm_complexity_limit(authority, realm)["maximum_complexity"])
    if complexity > max_complexity:
        raise block("FORGING_COMPLEXITY_EXCEEDED", "Final Complexity exceeds the Realm's limit.", complexity=complexity, maximum=max_complexity)
    drawbacks = [_drawback_row(authority, row["drawback_id"]) for row in technique.get("drawbacks", [])]
    if len({row["drawback_id"] for row in drawbacks}) != len(drawbacks):
        raise block("FORGING_DRAWBACK_DUPLICATE", "A Drawback is listed twice.")
    if _redundant_rest_drawbacks(drawbacks):
        raise block("FORGING_DRAWBACK_REDUNDANT", "Once per Long Rest already includes the Once per Short Rest restriction.")
    reduction = sum(int(row["cp_reduction"]) for row in drawbacks)
    gross_cp = int(form["starting_cp"]) + sum(int(row["cp"]) for row in augments)
    final_cp = gross_cp - reduction
    if reduction > pb or final_cp < int(authority["drawback_rules"]["minimum_final_cp"]):
        raise block("FORGING_DRAWBACK_LIMIT_EXCEEDED", "Drawbacks cannot reduce CP below 1 or by more than Proficiency Bonus.", reduction=reduction, pb=pb)
    if any(row["drawback_id"] == "backlash" for row in drawbacks) and not isinstance(technique.get("backlash"), dict):
        raise block("FORGING_BACKLASH_UNDEFINED", "A Backlash Drawback must define its trigger and consequence when the technique is created.")
    if not any(row["drawback_id"] == "backlash" for row in drawbacks) and technique.get("backlash") is not None:
        raise block("FORGING_BACKLASH_UNEXPECTED", "A Forged Technique without the Backlash Drawback cannot carry a Backlash definition.")
    action_type = _action_type(form["form_id"], {row["augment_id"] for row in augments})
    expected_base_form = {
        "form_id": form["form_id"],
        "display_name": form["display_name"],
        "starting_cp": int(form["starting_cp"]),
        "complexity": int(form["complexity"]),
        "use": form["use"],
    }
    expected_augments = [
        {
            "augment_id": row["augment_id"],
            "display_name": row["display_name"],
            "tier": row["tier"],
            "complexity": int(row["complexity"]),
            "cp": int(row["cp"]),
            "minimum_realm": row["minimum_realm"],
        }
        for row in augments
    ]
    expected_drawbacks = [
        {
            "drawback_id": row["drawback_id"],
            "display_name": row["display_name"],
            "cp_reduction": int(row["cp_reduction"]),
            "restriction": row["restriction"],
        }
        for row in drawbacks
    ]
    expected_cp_cost = {
        "base_form": int(form["starting_cp"]),
        "augments": sum(int(row["cp"]) for row in augments),
        "drawback_reduction": reduction,
        "final": final_cp,
    }
    expected_complexity = {
        "base_form": int(form["complexity"]),
        "secondary_spheres": len(effects) - 1,
        "augments": sum(int(row["complexity"]) for row in augments),
        "final": complexity,
        "realm_maximum": max_complexity,
    }
    expected = {
        "complexity": complexity,
        "cp_cost": final_cp,
        "spheres_used": len(sphere_ids),
        "technique_forging_dc": _forging_dc(authority, complexity, len(sphere_ids)),
        "research_days": max(int(authority["forging_check"]["research_days"]["minimum"]), int(authority["forging_check"]["research_days"]["per_complexity"]) * complexity),
        "material_cost_gp": int(authority["forging_check"]["material_cost_gp"]["per_complexity_squared"]) * complexity * complexity,
    }
    actual = {
        "complexity": (technique.get("complexity") or {}).get("final"),
        "cp_cost": (technique.get("cp_cost") or {}).get("final"),
        "spheres_used": technique.get("spheres_used"),
        "technique_forging_dc": technique.get("technique_forging_dc"),
        "research_days": technique.get("research_days"),
        "material_cost_gp": technique.get("material_cost_gp"),
    }
    drift = {key: {"expected": expected[key], "actual": actual[key]} for key in expected if expected[key] != actual[key]}
    sealed_fields = {
        "base_form": expected_base_form,
        "augments": expected_augments,
        "drawbacks": expected_drawbacks,
        "cp_cost_breakdown": expected_cp_cost,
        "complexity_breakdown": expected_complexity,
        "action_type": action_type,
        "sphere_ids_used": list(sphere_ids),
        "exhausting": any(row["drawback_id"] == "exhausting" for row in drawbacks),
    }
    actual_sealed_fields = {
        "base_form": technique.get("base_form"),
        "augments": technique.get("augments"),
        "drawbacks": technique.get("drawbacks"),
        "cp_cost_breakdown": technique.get("cp_cost"),
        "complexity_breakdown": technique.get("complexity"),
        "action_type": technique.get("action_type"),
        "sphere_ids_used": technique.get("sphere_ids_used"),
        "exhausting": technique.get("exhausting"),
    }
    for key, expected_value in sealed_fields.items():
        actual_value = actual_sealed_fields[key]
        if type(actual_value) is not type(expected_value) or canonical_json(actual_value) != canonical_json(expected_value):
            drift[key] = {"expected": expected_value, "actual": actual_value}
    if drift:
        raise block("FORGED_TECHNIQUE_FIGURES_DRIFTED", "The technique's stored figures do not match the sealed forging tables.", drift=drift)
    return {**expected, "realm": realm, "realm_maximum_complexity": max_complexity, "known_after": known_forged_technique_count + 1, "known_limit": pb}


__all__ = [
    "FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_ISSUER",
    "FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_SCHEMA",
    "FORGED_TECHNIQUE_ACQUISITION_AUTHORITY_VERSION",
    "FORGED_TECHNIQUE_ACQUISITION_SCHEMA",
    "FORGED_TECHNIQUE_REQUEST_SCHEMA",
    "FORGED_TECHNIQUE_SCHEMA",
    "compile_forged_technique",
    "construct_forged_technique",
    "forged_technique_id",
    "forged_technique_acquisition_authority",
    "normalize_forged_technique_request",
    "validate_forged_technique_acquisition",
]
