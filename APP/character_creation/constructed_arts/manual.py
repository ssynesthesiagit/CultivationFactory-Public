"""Deterministic lineage Manual and Recorded Art construction.

The Factory's lineage lane is deliberately narrower than an authored manual:
a Manual is a source-access record and every child Recorded Art is an exact
quoted published Talent expression.  The constructor carries the normalized
request in both parent and child provenance so a lock can rederive the entire
bundle without trusting display text or a parent/child hash cycle.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any, Mapping

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json

MANUAL_SCHEMA = "TianxiaFoundry.LineageManual.v1"
MANUAL_REQUEST_SCHEMA = "TianxiaFoundry.LineageManualRequest.v1"
RECORDED_ART_SCHEMA = "TianxiaFoundry.RecordedArt.v1"
from recorded_art_authority import (
    MANUAL_ACCESS_MODE,
    MANUAL_CHANNEL,
    MANUAL_OUTCOME,
    MANUAL_OUTCOME_SCHEMA,
    MANUAL_PACK_ID,
    MANUAL_PACK_VERSION,
    MANUAL_TRAINING_CHANNEL,
    RECORDED_ART_CHANNEL,
    RECORDED_ART_CONSTRUCTION_KIND,
    RECORDED_ART_PACK_ID,
    manual_outcome,
)

MANUAL_POLICY_ID = "TIANXIA.FACTORY.LINEAGE_MANUAL.THREE_EXACT_TALENTS.v1"
MANUAL_DC_RULE_ID = "TIANXIA.RECORDED_ART.DC.10_PLUS_DIFFICULTY_PLUS_2_PER_ART_THIS_CL.v1"
MANUAL_TIME_RULE_ID = "TIANXIA.RECORDED_ART.STUDY_TIME.FACTORY_PRINTED_DAYS.v1"
MANUAL_COLLECTION_POLICY_ID = "TIANXIA.FACTORY.MARTIAL_MANUAL_COLLECTION.D6_BANDS.v1"
MANUAL_COLLECTION_SCHEMA = "TianxiaFoundry.LineageManualCollection.v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ABILITY_CODES = frozenset({"STR", "DEX", "CON", "INT", "WIS", "CHA"})
_ACCESS_TO_DIFFICULTY = {
    "open": 1,
    "public": 1,
    "restricted": 2,
    "rare": 2,
    "forbidden": 3,
    "secret": 3,
}
_SCHOOL_PATTERNS = (
    "{sphere} Returning School",
    "{sphere} Thread Lineage",
    "{sphere} Gate School",
    "{sphere} Quiet Hall",
)


def manual_collection_band(cl: int) -> dict[str, Any]:
    """Return the owner-authored count band without clamping its result."""
    if type(cl) is not int or not 1 <= cl <= 20:
        raise _invalid("Manual collection count requires CL 1 through 20.", field="cl", value=cl)
    if cl <= 5:
        dice_count, band = 1, "CL1_5_1D6"
    elif cl <= 10:
        dice_count, band = 2, "CL6_10_2D6"
    elif cl <= 15:
        dice_count, band = 3, "CL11_15_3D6"
    else:
        dice_count, band = 4, "CL16_20_4D6"
    return {
        "policy_id": MANUAL_COLLECTION_POLICY_ID,
        "schema": MANUAL_COLLECTION_SCHEMA,
        "band": band,
        "cl": cl,
        "dice_count": dice_count,
        "die_sides": 6,
    }


def validate_manual_collection_roll(roll: Mapping[str, Any], *, cl: int) -> dict[str, Any]:
    """Validate the persisted die faces and total used for one collection."""
    expected = manual_collection_band(cl)
    if not isinstance(roll, Mapping):
        raise _invalid("The persisted Manual collection roll must be an object.", field="manual_collection")
    for key, value in expected.items():
        if roll.get(key) != value:
            raise _invalid("The persisted Manual collection roll does not match its versioned policy.", field=f"manual_collection.{key}", expected=value, actual=roll.get(key))
    faces = roll.get("faces")
    if not isinstance(faces, list) or len(faces) != expected["dice_count"] or any(type(face) is not int or not 1 <= face <= 6 for face in faces):
        raise _invalid("Manual collection dice must contain exactly the policy number of d6 faces.", field="manual_collection.faces")
    total = roll.get("total")
    if type(total) is not int or total != sum(faces) or not expected["dice_count"] <= total <= expected["dice_count"] * 6:
        raise _invalid("Manual collection total does not match its persisted die faces.", field="manual_collection.total")
    return {**expected, "faces": list(faces), "total": total}


def roll_manual_collection_count(
    cl: int,
    *,
    seed: str,
    dice_faces: list[int] | None = None,
) -> dict[str, Any]:
    """Roll one deterministic, replayable collection count for a new intent."""
    expected = manual_collection_band(cl)
    if not isinstance(seed, str) or not seed.strip():
        raise _invalid("A Manual collection roll requires a non-empty intent seed.", field="seed")
    if dice_faces is None:
        # A byte modulo six is biased because 256 is not divisible by six.
        # Rejection sampling keeps every d6 face equally likely while the
        # policy/seed/counter makes the accepted faces replay-stable.
        faces: list[int] = []
        counter = 0
        while len(faces) < expected["dice_count"]:
            digest = hashlib.sha256(
                f"{seed}:{MANUAL_COLLECTION_POLICY_ID}:{counter}".encode("utf-8")
            ).digest()
            counter += 1
            for byte in digest:
                if byte >= 252:
                    continue
                faces.append((byte % 6) + 1)
                if len(faces) == expected["dice_count"]:
                    break
    else:
        faces = list(dice_faces)
    return validate_manual_collection_roll({**expected, "faces": faces, "total": sum(faces)}, cl=cl)


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("LINEAGE_MANUAL_REQUEST_INVALID", message, details=details)


def _clean_text(value: Any, field: str, *, maximum: int, allow_empty: bool = False) -> str:
    if value is None and allow_empty:
        return ""
    if not isinstance(value, str):
        raise _invalid("A text field must be a string.", field=field)
    text = value.strip()
    if not text and not allow_empty:
        raise _invalid("A text field must be non-empty.", field=field)
    if len(text) > maximum or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        raise _invalid("A text field is too long or contains control characters.", field=field)
    return text


def _clean_id(value: Any, field: str) -> str:
    value = _clean_text(value, field, maximum=240)
    if not _ID_RE.fullmatch(value):
        raise _invalid("An identifier contains unsupported characters.", field=field, value=value)
    return value


def _clean_hash(value: Any, field: str) -> str:
    value = _clean_text(value, field, maximum=64)
    if not _HASH_RE.fullmatch(value):
        raise _invalid("A source or record hash must be a lowercase SHA-256 commitment.", field=field)
    return value


def _source(row: Mapping[str, Any], field: str) -> dict[str, Any]:
    source = row.get("source")
    if not isinstance(source, Mapping):
        raise _invalid("Every Talent must carry an exact source binding.", field=f"{field}.source")
    source_id = _clean_id(source.get("source_id"), f"{field}.source.source_id")
    path = _clean_text(source.get("path"), f"{field}.source.path", maximum=1000)
    anchor = _clean_text(source.get("anchor"), f"{field}.source.anchor", maximum=500)
    source_hash = _clean_hash(source.get("source_hash"), f"{field}.source.source_hash")
    return {"source_id": source_id, "path": path, "anchor": anchor, "source_hash": source_hash}


def _access_category(row: Mapping[str, Any], field: str) -> str:
    authority = row.get("stage2_authority")
    if not isinstance(authority, Mapping):
        authority = {}
    raw = row.get("access_category")
    if raw is None:
        raw = authority.get("access_category")
    if not isinstance(raw, str):
        raise _invalid(
            "A Talent's source-assigned access category is required for Recorded Art Difficulty.",
            field=f"{field}.access_category",
            value=raw,
        )
    category = raw.strip().casefold()
    if category not in _ACCESS_TO_DIFFICULTY:
        if category.startswith("open") or category.startswith("public"):
            category = "open"
        elif "restricted" in category or category.startswith("rare"):
            category = "restricted" if "restricted" in category else "rare"
        elif "forbidden" in category or category.startswith("secret"):
            category = "forbidden" if "forbidden" in category else "secret"
    if category not in _ACCESS_TO_DIFFICULTY:
        raise _invalid(
            "A Talent's source-assigned access category is required for Recorded Art Difficulty.",
            field=f"{field}.access_category",
            value=raw,
        )
    return category


def _normalize_talent_row(
    row: Mapping[str, Any],
    *,
    field: str,
    spheres: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Normalize one source-backed Talent without treating it as learned."""
    if not isinstance(row, Mapping):
        raise _invalid("A Talent row must be an object.", field=field)
    talent_id = _clean_id(row.get("talent_id"), f"{field}.talent_id")
    sphere_id = _clean_id(row.get("sphere_id"), f"{field}.sphere_id")
    if sphere_id not in spheres:
        raise _invalid("A Talent must belong to an authenticated Sphere row.", field=f"{field}.sphere_id", value=sphere_id)
    record_hash = _clean_hash(row.get("record_hash"), f"{field}.record_hash")
    published_text = _clean_text(row.get("published_text"), f"{field}.published_text", maximum=4000)
    if not published_text:
        raise _invalid("A Talent must carry a non-empty quoted published block.", field=f"{field}.published_text")
    result = {
        "talent_id": talent_id,
        "sphere_id": sphere_id,
        "display_name": _clean_text(row.get("display_name"), f"{field}.display_name", maximum=300),
        "record_hash": record_hash,
        "source": _source(row, field),
        "published_text": published_text,
        "access_category": _access_category(row, field),
    }
    if "available_at_cl" in row:
        value = row["available_at_cl"]
        if type(value) is not int or not 1 <= value <= 20:
            raise _invalid("A Talent availability CL must be an integer from 1 through 20.", field=f"{field}.available_at_cl", value=value)
        result["available_at_cl"] = value
    if "minimum_cl" in row:
        value = row["minimum_cl"]
        if type(value) is not int or not 1 <= value <= 20:
            raise _invalid("A Talent minimum CL must be an integer from 1 through 20.", field=f"{field}.minimum_cl", value=value)
        result["minimum_cl"] = value
    return result


def _lineage_hints(request: Mapping[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key in ("lineage_source", "lineage_hints"):
        value = request.get(key)
        if isinstance(value, Mapping):
            raw.update(value)
    for key in (
        "sect_trial_sphere_id",
        "background_id",
        "background_name",
    ):
        if request.get(key) is not None:
            raw[key] = request.get(key)
    result: dict[str, Any] = {}
    if raw.get("sect_trial_sphere_id") is not None:
        result["sect_trial_sphere_id"] = _clean_id(raw["sect_trial_sphere_id"], "lineage_source.sect_trial_sphere_id")
    if raw.get("background_id") is not None:
        result["background_id"] = _clean_id(raw["background_id"], "lineage_source.background_id")
    if raw.get("background_name") is not None:
        result["background_name"] = _clean_text(raw["background_name"], "lineage_source.background_name", maximum=300)
    return result


def normalize_lineage_manual_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize the pure constructor input."""
    if not isinstance(request, Mapping):
        raise _invalid("The Manual request must be an object.")
    schema = request.get("schema")
    if schema not in (None, MANUAL_REQUEST_SCHEMA):
        raise _invalid("The Manual request declares an unsupported schema.", schema=schema)
    seed = _clean_text(request.get("seed"), "seed", maximum=240)
    project_id = _clean_text(request.get("project_id"), "project_id", maximum=240)
    cl = request.get("cl")
    pb = request.get("pb")
    if type(cl) is not int or not 1 <= cl <= 20:
        raise _invalid("CL must be an integer from 1 through 20.", field="cl")
    if type(pb) is not int or not 2 <= pb <= 6:
        raise _invalid("Proficiency Bonus must be an integer from 2 through 6.", field="pb")
    path_id = _clean_id(request.get("path_id"), "path_id")
    key_ability = request.get("key_ability")
    if key_ability not in _ABILITY_CODES:
        raise _invalid("The powering Path key ability is invalid.", field="key_ability")

    spheres_in = request.get("known_spheres")
    talents_in = request.get("known_talents")
    if not isinstance(spheres_in, list) or not isinstance(talents_in, list):
        raise _invalid("Known Spheres and Talents must be lists.")
    spheres: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(spheres_in):
        if not isinstance(row, Mapping):
            raise _invalid("A known Sphere row must be an object.", field=f"known_spheres[{index}]")
        sphere_id = _clean_id(row.get("sphere_id"), f"known_spheres[{index}].sphere_id")
        if sphere_id in spheres:
            raise _invalid("Known Spheres must be unique.", field=f"known_spheres[{index}].sphere_id")
        spheres[sphere_id] = {
            "sphere_id": sphere_id,
            "display_name": _clean_text(row.get("display_name"), f"known_spheres[{index}].display_name", maximum=300),
        }
    if not spheres:
        raise _invalid("A lineage Manual requires at least one known Sphere.", field="known_spheres")
    talents: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(talents_in):
        field = f"known_talents[{index}]"
        talent = _normalize_talent_row(row, field=field, spheres=spheres)
        if talent["talent_id"] in talents:
            raise _invalid("Known Talents must be unique.", field=f"{field}.talent_id")
        talents[talent["talent_id"]] = talent
    collection_in = request.get("manual_collection")
    collection: dict[str, Any] | None = None
    if collection_in is not None:
        if not isinstance(collection_in, Mapping):
            raise _invalid("Manual collection authority must be an object.", field="manual_collection")
        roll = validate_manual_collection_roll(collection_in.get("roll"), cl=cl)
        collection_count = collection_in.get("count")
        collection_index = collection_in.get("index")
        if type(collection_count) is not int or collection_count != roll["total"] or collection_count < 1:
            raise _invalid("Manual collection count must equal the persisted dice total.", field="manual_collection.count")
        if type(collection_index) is not int or not 0 <= collection_index < collection_count:
            raise _invalid("Manual collection index is outside the persisted collection count.", field="manual_collection.index")
        collection_id = collection_in.get("collection_id")
        if collection_id is not None:
            collection_id = _clean_id(collection_id, "manual_collection.collection_id")
        content_talents_in = collection_in.get("content_talents")
        content_talents: list[dict[str, Any]] = []
        if content_talents_in is not None:
            if not isinstance(content_talents_in, list) or len(content_talents_in) != 3:
                raise _invalid("Each Manual must bind exactly three distinct printed Talent contents.", field="manual_collection.content_talents")
            seen_content: set[str] = set()
            for content_index, row in enumerate(content_talents_in):
                talent = _normalize_talent_row(
                    row,
                    field=f"manual_collection.content_talents[{content_index}]",
                    spheres=spheres,
                )
                if talent["talent_id"] in seen_content:
                    raise _invalid("A Manual's printed Talent contents must be distinct.", field="manual_collection.content_talents")
                seen_content.add(talent["talent_id"])
                content_talents.append(talent)
        source_talent_id = collection_in.get("source_talent_id")
        if source_talent_id is not None:
            source_talent_id = _clean_id(source_talent_id, "manual_collection.source_talent_id")
            if source_talent_id not in talents:
                raise _invalid("A legacy Manual collection entry must bind to an authenticated source Talent.", field="manual_collection.source_talent_id")
        if not content_talents and source_talent_id is None:
            raise _invalid("A new Manual collection entry must bind printed contents or a legacy source Talent.", field="manual_collection")
        if not talents and not content_talents:
            raise _invalid("A lineage Manual requires a known Talent or authenticated printed contents.", field="known_talents")
        collection = {
            "schema": MANUAL_COLLECTION_SCHEMA,
            "policy_id": MANUAL_COLLECTION_POLICY_ID,
            "roll": roll,
            "count": collection_count,
            "index": collection_index,
            **({"collection_id": collection_id} if collection_id is not None else {}),
            **({"source_talent_id": source_talent_id} if source_talent_id is not None else {}),
            **({"content_talents": content_talents} if content_talents else {}),
        }
    elif not talents:
        raise _invalid("A lineage Manual requires at least one known Talent.", field="known_talents")
    return {
        "schema": MANUAL_REQUEST_SCHEMA,
        "seed": seed,
        "project_id": project_id,
        "cl": cl,
        "pb": pb,
        "path_id": path_id,
        "key_ability": key_ability,
        "known_spheres": [spheres[key] for key in sorted(spheres)],
        "known_talents": [talents[key] for key in sorted(talents)],
        "lineage_source": _lineage_hints(request),
        **({"manual_collection": collection} if collection is not None else {}),
    }


def _manual_id(request: Mapping[str, Any]) -> str:
    return "tianxia.constructed.manual." + sha256_json(request)[:40]


def recorded_art_id(manual_id: str, ordinal: int) -> str:
    return f"tianxia.constructed.recorded_art.{manual_id.rsplit('.', 1)[-1]}.{ordinal + 1:02d}"


def _school_name(sphere_name: str, seed: str) -> str:
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return _SCHOOL_PATTERNS[value % len(_SCHOOL_PATTERNS)].format(sphere=sphere_name)


def _pack_hash(pack_id: str, record_id: str) -> str:
    return sha256_json({"schema": MANUAL_SCHEMA, "pack_id": pack_id, "pack_version": MANUAL_PACK_VERSION, "record_id": record_id})


def construct_lineage_manual(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a Manual plus its complete, deterministic three-art bundle.

    The return value contains ``manual`` and ``recorded_arts`` semantic rows.
    Record wrappers are intentionally built by ``records.py`` so the exact
    bundle can be re-created without a circular parent/child hash.
    """
    normalized = normalize_lineage_manual_request(request)
    request_hash = sha256_json(normalized)
    manual_id = _manual_id(normalized)
    spheres = {row["sphere_id"]: row for row in normalized["known_spheres"]}
    talents = list(normalized["known_talents"])
    collection = normalized.get("manual_collection")
    if isinstance(collection, Mapping):
        content_talents = collection.get("content_talents")
        if isinstance(content_talents, list) and content_talents:
            talents = deepcopy(content_talents)
        else:
            source_talent_id = collection["source_talent_id"]
            source_talent = next(row for row in talents if row["talent_id"] == source_talent_id)
            talents = [source_talent, *[row for row in talents if row["talent_id"] != source_talent_id]]
    sect_sphere_id = normalized["lineage_source"].get("sect_trial_sphere_id")
    if sect_sphere_id not in spheres:
        sect_sphere_id = talents[0]["sphere_id"]
    school_name = _school_name(spheres[sect_sphere_id]["display_name"], normalized["seed"])
    if isinstance(collection, Mapping):
        # Each book in a collection is its own title: a seeded school for its
        # Sphere, named after the first Talent it teaches.
        book_sphere_id = talents[0]["sphere_id"] if talents[0]["sphere_id"] in spheres else sect_sphere_id
        book_school = _school_name(spheres[book_sphere_id]["display_name"], f"{normalized['seed']}:{int(collection['index'])}")
        school_name = f"{book_school} — {talents[0].get('display_name') or talents[0]['talent_id']}"
    art_ids = [recorded_art_id(manual_id, ordinal) for ordinal in range(3)]
    lineage = {
        **deepcopy(normalized["lineage_source"]),
        "sect_trial_sphere_id": sect_sphere_id,
        "school_name": school_name,
        "source_kind": "factory-constructed-lineage-manual",
    }
    manual = {
        "schema": MANUAL_SCHEMA,
        "manual_id": manual_id,
        "record_id": manual_id,
        "display_name": school_name,
        "name": school_name,
        "cl_created": normalized["cl"],
        "pb_at_creation": normalized["pb"],
        "path_id": normalized["path_id"],
        "lineage_source": lineage,
        "recorded_art_ids": art_ids,
        "technique_record_ids": art_ids,
        "construction": {
            "schema": MANUAL_REQUEST_SCHEMA,
            "seed": normalized["seed"],
            "request": deepcopy(normalized),
            "request_sha256": request_hash,
            "manual_id": manual_id,
            "policy_id": MANUAL_POLICY_ID,
            "policy_sha256": sha256_json({"policy_id": MANUAL_POLICY_ID, "art_count": 3, "difficulty_map": _ACCESS_TO_DIFFICULTY}),
            **({"manual_collection": deepcopy(collection)} if isinstance(collection, Mapping) else {}),
        },
    }
    if isinstance(collection, Mapping):
        bindings = [
            {
                "record_id": talent["talent_id"],
                "record_hash": talent["record_hash"],
                "source": deepcopy(talent["source"]),
            }
            for talent in talents
        ]
        manual["collection"] = {
            "schema": MANUAL_COLLECTION_SCHEMA,
            "policy_id": MANUAL_COLLECTION_POLICY_ID,
            "roll": deepcopy(collection["roll"]),
            "count": collection["count"],
            "index": collection["index"],
            **({"collection_id": collection["collection_id"]} if collection.get("collection_id") else {}),
            "content_record_ids": [talent["talent_id"] for talent in talents],
            "content_record_bindings": bindings,
            "possession_status": "owned",
            "learned_record_ids": [],
        }
    arts: list[dict[str, Any]] = []
    for ordinal, talent in enumerate(talents[i % len(talents)] for i in range(3)):
        art_id = art_ids[ordinal]
        difficulty = _ACCESS_TO_DIFFICULTY[talent["access_category"]]
        art_seed = normalized["seed"]
        if art_seed.endswith(":manual"):
            art_seed = art_seed[: -len(":manual")]
        art_seed = f"{art_seed}:recorded_art:{ordinal}"
        block = talent["published_text"].strip()
        art = {
            "schema": RECORDED_ART_SCHEMA,
            "record_id": art_id,
            "display_name": f"{talent['display_name']} (from {school_name})",
            "parent_manual_record_id": manual_id,
            "technique_name": talent["display_name"],
            "associated_sphere_record_ids": [talent["sphere_id"]],
            "expression_kind": "exact_named_talent",
            "reproduced_component_record_ids": [talent["talent_id"]],
            "execution_derivation": {
                "mode": "quote_published_source_block",
                "source_record_id": talent["talent_id"],
                "source_block": block,
                "source_block_sha256": sha256_bytes(block.encode("utf-8")),
            },
            "learning_dc": {
                "mode": "difficulty_formula",
                "difficulty": difficulty,
                "rule_id": MANUAL_DC_RULE_ID,
                "access_category": talent["access_category"],
            },
            "study_time": {
                "mode": "printed_days",
                "value": 2,
                "rule_id": MANUAL_TIME_RULE_ID,
            },
            "allowed_study_abilities": ["INT", "WIS"],
            "requirements": [],
            "fixed_expression_only": True,
            "grants_sphere": False,
            "grants_talent": False,
            "grants_modification_permission": False,
            "source_record_id": talent["talent_id"],
            "source": deepcopy(talent["source"]),
            "source_record_hash": talent["record_hash"],
            "minimum_cl": int(talent.get("minimum_cl", 1)),
            "entry_ordinal": ordinal,
            "repeated_component": len(talents) < 3,
            "construction": {
                "schema": MANUAL_REQUEST_SCHEMA,
                "seed": art_seed,
                "request": deepcopy(normalized),
                "request_sha256": request_hash,
                "parent_manual_record_id": manual_id,
                "ordinal": ordinal,
                "manual_id": manual_id,
            },
        }
        arts.append(art)
    return {"manual": manual, "recorded_arts": arts}


def construct_lineage_manual_collection(
    request: Mapping[str, Any],
    *,
    roll: Mapping[str, Any],
    source_talent_ids: list[str] | None = None,
    manual_contents: list[list[Mapping[str, Any]]] | None = None,
    collection_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Construct one distinct Manual bundle per authenticated collection entry.

    ``manual_contents`` is the new possession path: its rows are already
    authenticated by the caller against the locked catalog and are copied as
    printed contents.  ``source_talent_ids`` remains only for old direct
    constructor callers and does not define the new authority contract.
    """
    if not isinstance(request, Mapping):
        raise _invalid("The Manual collection request must be an object.")
    normalized = normalize_lineage_manual_request({key: value for key, value in request.items() if key != "manual_collection"})
    checked_roll = validate_manual_collection_roll(roll, cl=normalized["cl"])
    count = checked_roll["total"]
    if manual_contents is not None:
        if len(manual_contents) != count:
            raise _invalid("Manual collection contents must contain one entry per persisted collection count.", field="manual_contents")
        if collection_ids is not None and len(collection_ids) != count:
            raise _invalid("Manual collection IDs must contain one entry per persisted collection count.", field="collection_ids")
    else:
        talents = [row["talent_id"] for row in normalized["known_talents"]]
        chosen = list(source_talent_ids) if source_talent_ids is not None else talents[:count]
        if len(chosen) != count or len(set(chosen)) != count or any(source_id not in talents for source_id in chosen):
            raise _invalid("Legacy Manual collection source identities must be distinct authenticated Talents.", field="source_talent_ids")
    bundles: list[dict[str, Any]] = []
    for index in range(count):
        entry_request = dict(request)
        entry_collection: dict[str, Any] = {
            "roll": deepcopy(dict(roll)),
            "count": count,
            "index": index,
        }
        if collection_ids is not None:
            entry_collection["collection_id"] = collection_ids[index]
        if manual_contents is not None:
            entry_collection["content_talents"] = [deepcopy(dict(row)) for row in manual_contents[index]]
        else:
            entry_collection["source_talent_id"] = chosen[index]
        entry_request["manual_collection"] = entry_collection
        bundles.append(construct_lineage_manual(entry_request))
    return bundles


def reconstruct_lineage_manual_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the semantic bundle from any Manual/Recorded Art record."""
    contract = ((record.get("compatibility") or {}).get("factory") or {}).get("constructed_art") if isinstance(record, Mapping) else None
    if not isinstance(contract, Mapping):
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "The record has no constructed Manual contract.")
    bundle = contract.get("bundle")
    if not isinstance(bundle, Mapping):
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "The constructed Manual contract has no complete bundle.")
    manual = bundle.get("manual")
    arts = bundle.get("recorded_arts")
    if not isinstance(manual, Mapping) or not isinstance(arts, list):
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "The constructed Manual bundle is incomplete.")
    construction = manual.get("construction")
    if not isinstance(construction, Mapping) or not isinstance(construction.get("request"), Mapping):
        raise FoundryError("LINEAGE_MANUAL_RECORD_INVALID", "The Manual bundle has no normalized request.")
    rebuilt = construct_lineage_manual(construction["request"])
    return rebuilt


__all__ = [
    "MANUAL_ACCESS_MODE",
    "MANUAL_CHANNEL",
    "MANUAL_DC_RULE_ID",
    "MANUAL_COLLECTION_POLICY_ID",
    "MANUAL_COLLECTION_SCHEMA",
    "MANUAL_OUTCOME_SCHEMA",
    "MANUAL_PACK_ID",
    "MANUAL_PACK_VERSION",
    "MANUAL_POLICY_ID",
    "MANUAL_REQUEST_SCHEMA",
    "MANUAL_SCHEMA",
    "MANUAL_TIME_RULE_ID",
    "MANUAL_TRAINING_CHANNEL",
    "RECORDED_ART_CHANNEL",
    "RECORDED_ART_CONSTRUCTION_KIND",
    "RECORDED_ART_PACK_ID",
    "RECORDED_ART_SCHEMA",
    "construct_lineage_manual",
    "construct_lineage_manual_collection",
    "manual_outcome",
    "manual_collection_band",
    "roll_manual_collection_count",
    "validate_manual_collection_roll",
    "normalize_lineage_manual_request",
    "recorded_art_id",
    "reconstruct_lineage_manual_from_record",
]
