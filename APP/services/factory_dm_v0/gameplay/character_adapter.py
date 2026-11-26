"""Validated character-to-gameplay admission for the mortal level-0 route.

The adapter owns no campaign state.  The generic contract path consumes only a
clearly labeled provider-free fixture.  Portable producer bytes enter through
the trusted exact-byte audit boundary and fail closed when its pinned closure
or persisted evidence is unavailable.  It derives only the ordinary level-0
baseline and leaves the campaign to own all mutable values.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import base64
from hashlib import sha256
import json
from typing import Any, Mapping

from ..domain import (Ability, Character, CharacterKind, Resource, Trait, _primitive)
from .models import Actor, Condition, HitDice, Item, Reduction, identifier
from .profile import (
    EFFECTS,
    LEGACY_PROFILE_V9_IDENTITY,
    RULES,
    SOURCES,
    digest,
    identity,
)


EXPORT_SCHEMA = "tianxia.completed_character_export.v1"
ADMISSION_SCHEMA = "factory-gameplay-level0-admission-v2"
ADAPTER_ID = "factory-dm-gameplay.level0-character-adapter"
ADAPTER_VERSION = 2
PORTABLE_PACKAGE_SCHEMA = "TianxiaFoundry.PortableCharacterPackage.v1"
PORTABLE_AUDIT_ID = "PortableCharacterPackageService.audit"
PORTABLE_AUDIT_SOURCE_SHA256 = "e572cb39a5a5975a1c54365ed6e3607fee2833dedd3a04403d33f6bd5baa8865"
PORTABLE_EXPORTER_SOURCE_SHA256 = "fbda9748973bb858cdccd6c61836d46891c2b0df874c9600744153a461147827"
PORTABLE_EVIDENCE_SCHEMA = "factory-gameplay-portable-evidence-v1"

_ABILITY_NAMES = ("str", "dex", "con", "int", "wis", "cha")
_SHA_FIELDS = ("event_head_hash", "replay_state_hash", "content_lock_hash", "canonical_project_hash")
_CORE_KEYS = {
    "identity", "binding", "stage", "abilities", "ability_provenance", "speed", "hit_dice",
    "hp", "paths", "starting_items", "starting_effects", "background_origin", "initialization", "source",
}
_CONTRACT_KEYS = {"schema", "export_schema", "version", "adapter", "profile", *_CORE_KEYS}


class AdmissionError(ValueError):
    """Structured rejection from the source/contract boundary."""

    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        message = code if not details else f"{code}: {json.dumps(details, sort_keys=True, default=str)}"
        super().__init__(message)


def _fail(code: str, **details: Any) -> None:
    raise AdmissionError(code, **details)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("ADMISSION_FIELD_INVALID", field=field)
    return value


def _exact(value: Any, keys: set[str], field: str) -> Mapping[str, Any]:
    mapping = _mapping(value, field)
    if set(mapping) != keys:
        _fail("ADMISSION_FIELDS_MISMATCH", field=field,
              missing=sorted(keys - set(mapping)), unknown=sorted(set(mapping) - keys))
    return mapping


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        _fail("ADMISSION_FIELD_INVALID", field=field)
    return value


def _sha_field(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("ADMISSION_HASH_INVALID", field=field)
    return value


def _portable_evidence(value: Any) -> Mapping[str, Any]:
    evidence = _exact(value, {
        "schema", "package_b64", "package_sha256", "producer_root", "source_manifest",
        "source_manifest_sha256", "authority_pack_sha256", "audit_receipt",
    }, "portable_evidence")
    if evidence["schema"] != PORTABLE_EVIDENCE_SCHEMA:
        _fail("PORTABLE_EXPORT_EVIDENCE_SCHEMA_UNSUPPORTED")
    encoded = evidence["package_b64"]
    if not isinstance(encoded, str) or not encoded:
        _fail("PORTABLE_EXPORT_BYTES_REQUIRED")
    try:
        package_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise AdmissionError("PORTABLE_EXPORT_BYTES_INVALID") from exc
    if not package_bytes:
        _fail("PORTABLE_EXPORT_BYTES_REQUIRED")
    _sha_field(evidence["package_sha256"], "portable_evidence.package_sha256")
    if _sha256_bytes(package_bytes) != evidence["package_sha256"]:
        _fail("PORTABLE_EXPORT_EVIDENCE_HASH_MISMATCH")
    _text(evidence["producer_root"], "portable_evidence.producer_root")
    manifest = evidence["source_manifest"]
    if not isinstance(manifest, Mapping) or not manifest:
        _fail("PORTABLE_EXPORT_SOURCE_MANIFEST_REQUIRED")
    for path, source_hash in manifest.items():
        _text(path, "portable_evidence.source_manifest.path")
        _sha_field(source_hash, f"portable_evidence.source_manifest.{path}")
    _sha_field(evidence["source_manifest_sha256"], "portable_evidence.source_manifest_sha256")
    _sha_field(evidence["authority_pack_sha256"], "portable_evidence.authority_pack_sha256")
    receipt = _exact(evidence["audit_receipt"], {
        "valid", "sha256", "member_inventory_sha256", "checksum_manifest_sha256", "coverage_status",
    }, "portable_evidence.audit_receipt")
    if receipt["valid"] is not True or receipt["coverage_status"] != "EXACT":
        _fail("PORTABLE_EXPORT_AUDIT_RECEIPT_INVALID")
    for field in ("sha256", "member_inventory_sha256", "checksum_manifest_sha256"):
        _sha_field(receipt[field], f"portable_evidence.audit_receipt.{field}")
    if receipt["sha256"] != evidence["package_sha256"]:
        _fail("PORTABLE_EXPORT_AUDIT_RECEIPT_INVALID")
    return evidence


def _source_ref(value: Any, field: str) -> None:
    ref = _exact(value, {"source_id", "source_hash", "locator"}, field)
    _text(ref["source_id"], f"{field}.source_id")
    _sha_field(ref["source_hash"], f"{field}.source_hash")
    _text(ref["locator"], f"{field}.locator")


def _validate_identity(value: Any) -> Mapping[str, Any]:
    result = _exact(value, {
        "character_id", "campaign_actor_id", "display_name", "build_revision", "project_id", "project_revision",
        "event_head_hash", "replay_state_hash", "content_lock_hash", "canonical_project_hash",
    }, "identity")
    for field in ("character_id", "campaign_actor_id", "display_name", "build_revision", "project_id"):
        _text(result[field], f"identity.{field}")
    if not identifier(result["campaign_actor_id"]):
        _fail("ADMISSION_IDENTIFIER_INVALID", field="identity.campaign_actor_id")
    if type(result["project_revision"]) is not int or result["project_revision"] < 0:
        _fail("ADMISSION_FIELD_INVALID", field="identity.project_revision")
    for field in _SHA_FIELDS:
        _sha_field(result[field], f"identity.{field}")
    return result


def _validate_source(
    value: Any,
    identity_value: Mapping[str, Any],
    *,
    artifact_hash: str,
    trusted_portable: bool = False,
    package_sha256: str | None = None,
) -> Mapping[str, Any]:
    source = _exact(value, {"authority_kind", "package_schema", "validation_chain", "commitments"}, "source")
    authority_kind = source["authority_kind"]
    if authority_kind == "validated_portable_export" and not trusted_portable:
        _fail("PORTABLE_EXPORT_VALIDATION_REQUIRED",
              reason="portable authority requires the trusted producer boundary",
              dependency=PORTABLE_AUDIT_ID)
    if authority_kind not in {"validated_level0_fixture", "validated_portable_export"}:
        _fail("SOURCE_AUTHORITY_UNSUPPORTED", authority_kind=source["authority_kind"])
    expected_package_schema = PORTABLE_PACKAGE_SCHEMA if authority_kind == "validated_portable_export" else "factory-gameplay-fixture.v1"
    if source["package_schema"] != expected_package_schema:
        _fail("FIXTURE_SCHEMA_MISMATCH", package_schema=source["package_schema"])
    raw_chain = _mapping(source["validation_chain"], "source.validation_chain")
    if authority_kind == "validated_portable_export" and raw_chain.get("exporter_source_sha256") != PORTABLE_EXPORTER_SOURCE_SHA256:
        _fail("PORTABLE_EXPORT_VALIDATION_REQUIRED", dependency="TianxiaFoundry.MortalLevel0PackageService")
    chain_keys = {"id", "status", "source_sha256", "artifact_sha256", "bytes_verified"}
    if authority_kind == "validated_portable_export":
        chain_keys.add("exporter_source_sha256")
    chain = _exact(raw_chain, chain_keys, "source.validation_chain")
    _text(chain["id"], "source.validation_chain.id")
    if chain["status"] != "PASS" or chain["bytes_verified"] is not True:
        _fail("SOURCE_VALIDATION_REQUIRED", status=chain["status"], bytes_verified=chain["bytes_verified"])
    _sha_field(chain["source_sha256"], "source.validation_chain.source_sha256")
    if chain["artifact_sha256"] != artifact_hash:
        _fail("SOURCE_ARTIFACT_HASH_MISMATCH", expected=artifact_hash, actual=chain["artifact_sha256"])
    commitments = _exact(source["commitments"], {
        "package_sha256", "project_id", "project_revision", "event_head_hash", "replay_state_hash",
        "content_lock_hash", "canonical_project_hash",
    }, "source.commitments")
    for field in ("package_sha256", "event_head_hash", "replay_state_hash", "content_lock_hash", "canonical_project_hash"):
        _sha_field(commitments[field], f"source.commitments.{field}")
    if commitments["project_id"] != identity_value["project_id"] or commitments["project_revision"] != identity_value["project_revision"]:
        _fail("SOURCE_IDENTITY_MISMATCH", field="project_id/project_revision")
    for field in _SHA_FIELDS:
        if commitments[field] != identity_value[field]:
            _fail("SOURCE_IDENTITY_MISMATCH", field=field)
    if authority_kind == "validated_portable_export":
        if not trusted_portable:
            _fail("PORTABLE_EXPORT_VALIDATION_REQUIRED", dependency=PORTABLE_AUDIT_ID)
        if chain["id"] != PORTABLE_AUDIT_ID or chain["source_sha256"] != PORTABLE_AUDIT_SOURCE_SHA256:
            _fail("PORTABLE_EXPORT_AUDIT_BINDING_MISMATCH")
        if package_sha256 is None or commitments["package_sha256"] != package_sha256:
            _fail("PORTABLE_EXPORT_PACKAGE_HASH_MISMATCH")
    return source


def _validate_base(
    value: Any,
    *,
    artifact_bytes: bytes | None = None,
    trusted_portable: bool = False,
    package_sha256: str | None = None,
) -> Mapping[str, Any]:
    export = _exact(value, {"schema", *_CORE_KEYS}, "completed_export")
    if export["schema"] != EXPORT_SCHEMA:
        _fail("EXPORT_SCHEMA_UNSUPPORTED", schema=export["schema"])
    identity_value = _validate_identity(export["identity"])
    binding = _exact(export["binding"], {"faction_id", "location_id"}, "binding")
    for field in binding:
        if not identifier(binding[field]):
            _fail("ADMISSION_IDENTIFIER_INVALID", field=f"binding.{field}")
    stage = _exact(export["stage"], {"level", "route", "state"}, "stage")
    if stage["level"] != 0 or stage["route"] != "sect_trial_pending" or stage["state"] != "completed_level0":
        _fail("LEVEL0_STAGE_REQUIRED", stage=dict(stage))
    abilities = _exact(export["abilities"], set(_ABILITY_NAMES), "abilities")
    if any(type(score) is not int or not 1 <= score <= 30 for score in abilities.values()):
        _fail("ABILITY_AUTHORITY_INVALID")
    provenance = _exact(export["ability_provenance"], set(_ABILITY_NAMES), "ability_provenance")
    for name in _ABILITY_NAMES:
        ref = _exact(provenance[name], {"source_id", "source_hash", "locator", "modifier"}, f"ability_provenance.{name}")
        _source_ref({k: ref[k] for k in ("source_id", "source_hash", "locator")}, f"ability_provenance.{name}")
        if type(ref["modifier"]) is not int or ref["modifier"] != (abilities[name] - 10) // 2:
            _fail("ABILITY_MODIFIER_MISMATCH", ability=name)
    speed = _exact(export["speed"], {"walking_ft", "provenance"}, "speed")
    if speed["walking_ft"] != 30:
        _fail("LEVEL0_SPEED_UNSUPPORTED", walking_ft=speed["walking_ft"])
    _source_ref(speed["provenance"], "speed.provenance")
    dice = export["hit_dice"]
    if not isinstance(dice, list) or len(dice) != 1:
        _fail("LEVEL0_HIT_DICE_BASELINE_REQUIRED")
    die = _exact(dice[0], {"pool_id", "sides", "maximum", "remaining", "provenance"}, "hit_dice[0]")
    if die["pool_id"] != "primary" or die["sides"] != 6 or die["maximum"] != 1 or die["remaining"] != 1:
        _fail("LEVEL0_HIT_DICE_BASELINE_MISMATCH")
    _source_ref(die["provenance"], "hit_dice[0].provenance")
    hp = _exact(export["hp"], {"current", "maximum", "formula", "provenance"}, "hp")
    if hp["formula"] != "6 + CON modifier" or hp["current"] != hp["maximum"]:
        _fail("LEVEL0_HP_BASELINE_INVALID")
    if type(hp["current"]) is not int or hp["current"] != max(1, 6 + ((abilities["con"] - 10) // 2)):
        _fail("LEVEL0_HP_DERIVATION_MISMATCH", expected=max(1, 6 + ((abilities["con"] - 10) // 2)), actual=hp["current"])
    _source_ref(hp["provenance"], "hp.provenance")
    paths = _exact(export["paths"], {"attainment", "selected", "pools", "cultivation_permissions"}, "paths")
    attainment = _exact(paths["attainment"], {"body", "qi", "spirit"}, "paths.attainment")
    if any(value != 0 for value in attainment.values()) or paths["selected"] or paths["pools"] or paths["cultivation_permissions"]:
        _fail("LEVEL0_PATHS_FORBIDDEN")
    if not all(type(value) is int and value == 0 for value in attainment.values()):
        _fail("LEVEL0_PATH_ATTAINMENT_INVALID")
    if not all(isinstance(paths[key], list) for key in ("selected", "pools", "cultivation_permissions")):
        _fail("LEVEL0_PATHS_INVALID")
    items = export["starting_items"]
    if not isinstance(items, list):
        _fail("STARTING_ITEMS_INVALID")
    _validate_starting_items(items, identity_value["campaign_actor_id"], binding["location_id"])
    effects = export["starting_effects"]
    if not isinstance(effects, list):
        _fail("STARTING_EFFECTS_INVALID")
    _validate_starting_effects(effects)
    background = _exact(export["background_origin"], {"background_id", "origin_insight_ids", "exceptions", "provenance"}, "background_origin")
    if background["background_id"] is not None:
        _text(background["background_id"], "background_origin.background_id")
    if not isinstance(background["origin_insight_ids"], list) or not all(isinstance(v, str) for v in background["origin_insight_ids"]):
        _fail("BACKGROUND_ORIGIN_INVALID")
    if not isinstance(background["exceptions"], list) or not isinstance(background["provenance"], list):
        _fail("BACKGROUND_ORIGIN_INVALID")
    if background["exceptions"]:
        _fail("BACKGROUND_ORIGIN_EXCEPTIONS_UNSUPPORTED",
              reason="no source-backed exception effect adapter is implemented",
              count=len(background["exceptions"]))
    for ref in background["provenance"]:
        _source_ref(ref, "background_origin.provenance")
    initialization = _exact(export["initialization"], {"owner", "mode", "current_state", "recovery_provenance", "encounter_defaults_used"}, "initialization")
    if initialization["owner"] != "campaign" or initialization["mode"] != "level0_baseline" or initialization["current_state"] != "full_baseline" or initialization["encounter_defaults_used"] is not False:
        _fail("INITIALIZATION_PROVENANCE_INVALID")
    if not isinstance(initialization["recovery_provenance"], list) or not initialization["recovery_provenance"]:
        _fail("RECOVERY_PROVENANCE_REQUIRED")
    for ref in initialization["recovery_provenance"]:
        _source_ref(ref, "initialization.recovery_provenance")
    source_payload = {key: deepcopy(export[key]) for key in export if key != "source"}
    computed_artifact_hash = _sha(source_payload)
    if artifact_bytes is not None and not trusted_portable:
        computed_bytes_hash = _sha256_bytes(artifact_bytes)
        if computed_bytes_hash != computed_artifact_hash:
            _fail("SOURCE_ARTIFACT_BYTES_MISMATCH", expected=computed_artifact_hash, actual=computed_bytes_hash)
    _validate_source(
        export["source"],
        identity_value,
        artifact_hash=computed_artifact_hash,
        trusted_portable=trusted_portable,
        package_sha256=package_sha256 if package_sha256 is not None else (
            _sha256_bytes(artifact_bytes) if artifact_bytes is not None else None
        ),
    )
    return export


def _validate_starting_items(items: list[Any], actor_id: str, location_id: str) -> None:
    keys = {"record", "provenance"}
    for index, item in enumerate(items):
        row = _exact(item, keys, f"starting_items[{index}]")
        record = _exact(row["record"], {"instance_id", "label", "source_id", "kind", "quantity", "owner_id", "scene_id", "visible_to", "equipped", "attuned", "public_ownership"}, f"starting_items[{index}].record")
        try:
            parsed = Item(**dict(record))
        except (TypeError, ValueError) as exc:
            _fail("STARTING_ITEM_INVALID", item_id=record.get("instance_id"), error=str(exc))
        if parsed.owner_id not in {None, actor_id} or parsed.scene_id not in {None, location_id}:
            _fail("STARTING_ITEM_BINDING_INVALID", item_id=parsed.instance_id)
        _source_ref(row["provenance"], f"starting_items[{index}].provenance")


def _validate_starting_effects(effects: list[Any]) -> None:
    rule_sources = {rule["id"]: rule["citations"][0]["source_hash"] for rule in RULES}
    for index, effect in enumerate(effects):
        row = _exact(effect, {"kind", "record", "provenance"}, f"starting_effects[{index}]")
        record = row["record"]
        if row["kind"] == "condition":
            try:
                parsed = Condition(**dict(record))
            except (TypeError, ValueError) as exc:
                _fail("STARTING_EFFECT_INVALID", index=index, error=str(exc))
            if parsed.definition_id not in EFFECTS:
                _fail("STARTING_EFFECT_UNSUPPORTED", definition_id=parsed.definition_id)
            spec = EFFECTS[parsed.definition_id]
            if parsed.definition_version != 1 or parsed.source_hash != rule_sources[spec["rule_id"]] or parsed.kind != spec.get("kind"):
                _fail("STARTING_EFFECT_SOURCE_MISMATCH", index=index)
        elif row["kind"] == "reduction":
            try:
                parsed = Reduction(**dict(record))
            except (TypeError, ValueError) as exc:
                _fail("STARTING_EFFECT_INVALID", index=index, error=str(exc))
            if parsed.definition_id != "ordinary_reduction" or parsed.definition_version != 1 or parsed.source_hash != rule_sources["reduction"]:
                _fail("STARTING_EFFECT_SOURCE_MISMATCH", index=index)
        else:
            _fail("STARTING_EFFECT_KIND_UNSUPPORTED", kind=row["kind"])
        _source_ref(row["provenance"], f"starting_effects[{index}].provenance")


def _actor_and_character(contract: Mapping[str, Any]) -> tuple[Character, Actor]:
    ident = contract["identity"]
    binding = contract["binding"]
    abilities = contract["abilities"]
    hp = contract["hp"]
    die = contract["hit_dice"][0]
    conditions: dict[str, Condition] = {}
    reductions: dict[str, Reduction] = {}
    for effect in contract["starting_effects"]:
        record = dict(effect["record"])
        if effect["kind"] == "condition":
            parsed = Condition(**record)
            conditions[parsed.instance_id] = parsed
        else:
            parsed = Reduction(**record)
            reductions[parsed.instance_id] = parsed
    actor = Actor(
        ident["campaign_actor_id"], ident["display_name"], binding["location_id"], hp["current"], hp["maximum"],
        dict(abilities), {"primary": HitDice(die["sides"], die["maximum"], die["remaining"])},
        conditions=conditions, reductions=reductions, speed=contract["speed"]["walking_ft"],
    )
    character = Character(
        ident["campaign_actor_id"], ident["display_name"], CharacterKind.PLAYER, binding["faction_id"],
        binding["location_id"], (Trait("level0", 1),), (Ability("strike", 1, 1, 1),),
        (Resource("health", hp["current"], hp["maximum"]),), (), (), (),
    )
    return character, actor


def _contract_from_export(export: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": ADMISSION_SCHEMA,
        "export_schema": EXPORT_SCHEMA,
        "version": 2,
        "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION},
        "profile": deepcopy(identity()),
        **{key: deepcopy(export[key]) for key in _CORE_KEYS},
    }


def validate_level0_contract(
    value: Any,
    *,
    trusted_portable: bool = False,
    package_sha256: str | None = None,
) -> Mapping[str, Any]:
    contract = _exact(value, _CONTRACT_KEYS, "contract")
    if contract["schema"] != ADMISSION_SCHEMA or contract["export_schema"] != EXPORT_SCHEMA or contract["version"] != 2:
        _fail("ADMISSION_SCHEMA_UNSUPPORTED")
    adapter = _exact(contract["adapter"], {"id", "version"}, "contract.adapter")
    if adapter["id"] != ADAPTER_ID or adapter["version"] != ADAPTER_VERSION:
        _fail("ADAPTER_VERSION_UNSUPPORTED")
    if contract["profile"] != identity():
        _fail("INCOMPATIBLE_PROFILE")
    base = {key: deepcopy(contract[key]) for key in _CORE_KEYS}
    base["schema"] = EXPORT_SCHEMA
    _validate_base(base, trusted_portable=trusted_portable, package_sha256=package_sha256)
    return contract


def build_level0_admission(export: Mapping[str, Any], *, artifact_bytes: bytes | None = None) -> dict[str, Any]:
    """Translate one validated level-0 export into an atomic admission record."""

    base = deepcopy(dict(export))
    _validate_base(base, artifact_bytes=artifact_bytes)
    contract = _contract_from_export(base)
    validate_level0_contract(contract)
    character, actor = _actor_and_character(contract)
    value = {
        "schema": ADMISSION_SCHEMA,
        "authority_kind": base["source"]["authority_kind"],
        "authority_id": base["identity"]["project_id"],
        "character_id": base["identity"]["campaign_actor_id"],
        "character": _primitive(character),
        "character_digest": digest(_primitive(character)),
        "mechanics": asdict(actor),
        "resource_bindings": {"hp": "health", "paths": {}},
        "contract": contract,
    }
    return {**value, "digest": digest(value)}


def _portable_evidence_from_checked(checked: Mapping[str, Any]) -> dict[str, Any]:
    report = _mapping(checked.get("audit"), "portable.audit")
    receipt = {
        "valid": report.get("valid"),
        "sha256": report.get("sha256"),
        "member_inventory_sha256": report.get("member_inventory_sha256"),
        "checksum_manifest_sha256": report.get("checksum_manifest", {}).get("sha256"),
        "coverage_status": report.get("checksum_manifest", {}).get("coverage_status"),
    }
    evidence = {
        "schema": PORTABLE_EVIDENCE_SCHEMA,
        "package_b64": base64.b64encode(checked["package_bytes"]).decode("ascii"),
        "package_sha256": checked["package_sha256"],
        "producer_root": checked["producer_root"],
        "source_manifest": deepcopy(checked["source_manifest"]),
        "source_manifest_sha256": checked["source_manifest_sha256"],
        "authority_pack_sha256": checked["authority_pack_sha256"],
        "audit_receipt": receipt,
    }
    _portable_evidence(evidence)
    return evidence


def _build_trusted_portable_admission(
    export: Mapping[str, Any], *, artifact_bytes: bytes, checked: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an admission only after the trusted byte-audit bridge succeeds.

    This private boundary is deliberately separate from ``build_level0_admission``:
    caller-supplied portable audit mappings cannot opt into it.
    """

    if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
        _fail("PORTABLE_EXPORT_BYTES_REQUIRED")
    base = deepcopy(dict(export))
    _validate_base(base, artifact_bytes=artifact_bytes, trusted_portable=True)
    contract = _contract_from_export(base)
    validate_level0_contract(
        contract,
        trusted_portable=True,
        package_sha256=_sha256_bytes(artifact_bytes),
    )
    character, actor = _actor_and_character(contract)
    value = {
        "schema": ADMISSION_SCHEMA,
        "authority_kind": "validated_portable_export",
        "authority_id": base["identity"]["project_id"],
        "character_id": base["identity"]["campaign_actor_id"],
        "character": _primitive(character),
        "character_digest": digest(_primitive(character)),
        "mechanics": asdict(actor),
        "resource_bindings": {"hp": "health", "paths": {}},
        "contract": contract,
        "portable_evidence": _portable_evidence_from_checked(checked),
    }
    return {**value, "digest": digest(value)}


def _revalidate_portable_evidence(evidence_value: Any) -> tuple[Mapping[str, Any], dict[str, Any]]:
    evidence = _portable_evidence(evidence_value)
    try:
        package_bytes = base64.b64decode(evidence["package_b64"].encode("ascii"), validate=True)
        from .trusted_producer import audit_exact_package_bytes, source_manifest_is_compatible
        checked = audit_exact_package_bytes(package_bytes, producer_root=evidence["producer_root"])
    except Exception as exc:
        _fail("PORTABLE_EXPORT_TRUST_FAILED", reason=str(exc), dependency=PORTABLE_AUDIT_ID)
    if checked["package_sha256"] != evidence["package_sha256"]:
        _fail("PORTABLE_EXPORT_EVIDENCE_HASH_MISMATCH")
    if not source_manifest_is_compatible(
        checked["source_manifest"],
        checked["source_manifest_sha256"],
        dict(evidence["source_manifest"]),
        evidence["source_manifest_sha256"],
    ):
        _fail("PORTABLE_EXPORT_SOURCE_MANIFEST_MISMATCH")
    if checked["authority_pack_sha256"] != evidence["authority_pack_sha256"]:
        _fail("PORTABLE_EXPORT_AUTHORITY_PACK_MISMATCH")
    receipt = evidence["audit_receipt"]
    report = checked["audit"]
    expected_receipt = {
        "valid": report.get("valid"), "sha256": report.get("sha256"),
        "member_inventory_sha256": report.get("member_inventory_sha256"),
        "checksum_manifest_sha256": report.get("checksum_manifest", {}).get("sha256"),
        "coverage_status": report.get("checksum_manifest", {}).get("coverage_status"),
    }
    if dict(receipt) != expected_receipt:
        _fail("PORTABLE_EXPORT_AUDIT_RECEIPT_MISMATCH")
    return checked, _portable_authority_to_export(checked)


def validate_persisted_portable_admission(contract: Mapping[str, Any], evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    """Re-audit the immutable portable evidence carried by a campaign binding."""

    checked, trusted_export = _revalidate_portable_evidence(evidence)
    current_contract = _contract_from_export(trusted_export)
    if not _persisted_contract_is_compatible(contract, current_contract):
        _fail("PORTABLE_EXPORT_ADMISSION_MISMATCH")
    # Validate the freshly derived current contract.  A retained v9 contract
    # is accepted only after the exact source/profile transition below has
    # matched every other field byte-for-byte.
    validate_level0_contract(current_contract, trusted_portable=True, package_sha256=checked["package_sha256"])
    return checked


def _persisted_contract_is_compatible(
    persisted: Mapping[str, Any], current: Mapping[str, Any],
) -> bool:
    if persisted == current:
        return True
    from .trusted_producer import LEGACY_PORTABLE_AUDIT_SOURCE_SHA256

    candidate = deepcopy(dict(persisted))
    source = candidate.get("source")
    chain = source.get("validation_chain") if isinstance(source, dict) else None
    if candidate.get("profile") != LEGACY_PROFILE_V9_IDENTITY or not isinstance(chain, dict):
        return False
    if chain.get("source_sha256") != LEGACY_PORTABLE_AUDIT_SOURCE_SHA256:
        return False
    current_chain = current.get("source", {}).get("validation_chain", {})
    if not isinstance(current_chain, dict) or not current_chain.get("source_sha256"):
        return False
    candidate["profile"] = deepcopy(current["profile"])
    chain["source_sha256"] = current_chain["source_sha256"]
    return candidate == current


def validate_level0_admission(value: Any) -> tuple[Character, Actor, Mapping[str, Any], Mapping[str, Any]]:
    raw_admission = _mapping(value, "admission")
    admission_keys = {"schema", "authority_kind", "authority_id", "character_id", "character", "character_digest", "mechanics", "resource_bindings", "contract", "digest"}
    if raw_admission.get("authority_kind") == "validated_portable_export":
        if "portable_evidence" not in raw_admission:
            _fail("PORTABLE_EXPORT_VALIDATION_REQUIRED", dependency=PORTABLE_AUDIT_ID)
        admission_keys.add("portable_evidence")
    admission = _exact(raw_admission, admission_keys, "admission")
    if admission["schema"] != ADMISSION_SCHEMA:
        _fail("ADMISSION_SCHEMA_UNSUPPORTED")
    trusted_portable = admission["authority_kind"] == "validated_portable_export"
    if admission["authority_kind"] != "validated_level0_fixture" and not trusted_portable:
        _fail("SOURCE_AUTHORITY_UNSUPPORTED", authority_kind=admission["authority_kind"])
    if digest({key: admission[key] for key in admission if key != "digest"}) != admission["digest"]:
        _fail("CHARACTER_AUTHORITY_HASH_MISMATCH")
    if trusted_portable:
        checked, trusted_export = _revalidate_portable_evidence(admission["portable_evidence"])
        expected_contract = _contract_from_export(trusted_export)
        if not _persisted_contract_is_compatible(admission["contract"], expected_contract):
            _fail("PORTABLE_EXPORT_ADMISSION_MISMATCH")
        validate_level0_contract(
            expected_contract, trusted_portable=True,
            package_sha256=checked["package_sha256"],
        )
        # Keep the retained contract bytes in the replayed state.  The
        # current contract above proves the re-audited package; replacing the
        # old profile here would change the saved event/state digest.
        contract = admission["contract"]
    else:
        contract = validate_level0_contract(admission["contract"])
    if admission["authority_kind"] != contract["source"]["authority_kind"] or admission["authority_id"] != contract["identity"]["project_id"]:
        _fail("SOURCE_IDENTITY_MISMATCH")
    character, actor = _actor_and_character(contract)
    if admission["character_id"] != actor.actor_id or admission["character"] != _primitive(character):
        _fail("CHARACTER_AUTHORITY_STALE")
    if admission["character_digest"] != digest(_primitive(character)) or admission["mechanics"] != asdict(actor):
        _fail("CHARACTER_MECHANICS_AUTHORITY_MISMATCH")
    resources = _exact(admission["resource_bindings"], {"hp", "paths"}, "resource_bindings")
    if resources["hp"] != "health" or resources["paths"]:
        _fail("LEVEL0_RESOURCE_BINDING_MISMATCH")
    return character, actor, resources, contract


def level0_fixture_export(*, character_id: str = "mortal-lin", name: str = "Mortal Lin") -> dict[str, Any]:
    """Return a provider-free, explicitly fixture-labeled level-0 export."""

    abilities = {"str": 10, "dex": 12, "con": 14, "int": 10, "wis": 14, "cha": 10}
    source_hash = SOURCES["PHB"]["sha256"]
    ref = lambda locator: {"source_id": "PHB", "source_hash": source_hash, "locator": locator}
    base: dict[str, Any] = {
        "schema": EXPORT_SCHEMA,
        "identity": {
            "character_id": character_id, "campaign_actor_id": character_id, "display_name": name,
            "build_revision": "fixture-r1", "project_id": character_id, "project_revision": 1,
            "event_head_hash": _sha("fixture:event:" + character_id),
            "replay_state_hash": _sha("fixture:state:" + character_id),
            "content_lock_hash": _sha("fixture:content:" + character_id),
            "canonical_project_hash": _sha("fixture:project:" + character_id),
        },
        "binding": {"faction_id": "party", "location_id": "courtyard"},
        "stage": {"level": 0, "route": "sect_trial_pending", "state": "completed_level0"},
        "abilities": abilities,
        "ability_provenance": {name: {**ref("PHB lines 324-345"), "modifier": (score - 10) // 2} for name, score in abilities.items()},
        "speed": {"walking_ft": 30, "provenance": ref("PHB lines 324-345")},
        "hit_dice": [{"pool_id": "primary", "sides": 6, "maximum": 1, "remaining": 1, "provenance": ref("PHB lines 324-345")}],
        "hp": {"current": 8, "maximum": 8, "formula": "6 + CON modifier", "provenance": ref("PHB lines 324-345")},
        "paths": {"attainment": {"body": 0, "qi": 0, "spirit": 0}, "selected": [], "pools": [], "cultivation_permissions": []},
        "starting_items": [], "starting_effects": [],
        "background_origin": {"background_id": "background-orphan", "origin_insight_ids": ["origin-street"], "exceptions": [], "provenance": [ref("PHB lines 498-531")]},
        "initialization": {"owner": "campaign", "mode": "level0_baseline", "current_state": "full_baseline", "recovery_provenance": [ref("PHB lines 324-345")], "encounter_defaults_used": False},
    }
    artifact_hash = _sha(base)
    base["source"] = {
        "authority_kind": "validated_level0_fixture", "package_schema": "factory-gameplay-fixture.v1",
        "validation_chain": {"id": "factory-gameplay.level0-fixture-validator", "status": "PASS", "source_sha256": _sha("fixture-validator-v1"), "artifact_sha256": artifact_hash, "bytes_verified": True},
        "commitments": {"package_sha256": artifact_hash, "project_id": character_id, "project_revision": 1,
                         "event_head_hash": base["identity"]["event_head_hash"], "replay_state_hash": base["identity"]["replay_state_hash"],
                         "content_lock_hash": base["identity"]["content_lock_hash"], "canonical_project_hash": base["identity"]["canonical_project_hash"]},
    }
    return base


def validate_portable_export(package_bytes: bytes, producer_audit: Mapping[str, Any]) -> dict[str, Any]:
    """Reject caller-supplied audit mappings until a trusted producer boundary exists.

    A package hash, ZIP checksum manifest and public audit-shaped mapping prove
    only self-consistency.  They do not prove that the creator's complete
    validation service accepted the package, so this gameplay workspace does
    not treat them as portable authority.
    """

    if not isinstance(package_bytes, bytes):
        _fail("PORTABLE_EXPORT_BYTES_REQUIRED")
    _fail("PORTABLE_EXPORT_VALIDATION_REQUIRED",
          reason="trusted producer validation dependency unavailable",
          dependency=PORTABLE_AUDIT_ID)


def admission_from_portable_export(package_bytes: bytes, producer_audit: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a real package, then reject unsupported current level-0 authority explicitly."""

    checked = validate_portable_export(package_bytes, producer_audit)
    owner = checked["owner"]
    identity_value = owner.get("identity") if isinstance(owner.get("identity"), dict) else {}
    if "cultivation_level" not in identity_value:
        _fail("LEVEL0_AUTHORITY_MISSING", field="owner.identity.cultivation_level")
    if identity_value["cultivation_level"] != 0:
        _fail("LEVEL0_ROUTE_UNSUPPORTED", actual_level=identity_value["cultivation_level"], path=identity_value.get("path_id"), reason="current producer enforces CL1-20")
    _fail("LEVEL0_AUTHORITY_MISSING", field="explicit_no_path_no_resource_authority")


def admission_from_trusted_portable_package(package_path: str, *, producer_root: str) -> dict[str, Any]:
    """Audit exact producer bytes and map the resulting source authority.

    The public legacy portable helper above intentionally remains fail-closed
    for caller mappings.  This route accepts only a package path and a source
    snapshot whose audit/exporter hashes are pinned by ``trusted_producer``.
    """

    from .trusted_producer import audit_exact_package

    try:
        checked = audit_exact_package(package_path, producer_root=producer_root)
    except Exception as exc:
        _fail("PORTABLE_EXPORT_TRUST_FAILED", reason=str(exc), dependency=PORTABLE_AUDIT_ID)
    export = _portable_authority_to_export(checked)
    return _build_trusted_portable_admission(
        export,
        artifact_bytes=checked["package_bytes"],
        checked=checked,
    )


def _portable_authority_to_export(checked: Mapping[str, Any]) -> dict[str, Any]:
    """Map the trusted producer's semantic authority to the canonical contract."""

    authority = _mapping(checked.get("authority"), "portable.authority")
    manifest = _mapping(checked.get("manifest"), "portable.manifest")
    ident = _mapping(authority.get("identity"), "portable.authority.identity")
    stage = _mapping(authority.get("stage"), "portable.authority.stage")
    abilities = _mapping(authority.get("abilities"), "portable.authority.abilities")
    hp = _mapping(authority.get("hp"), "portable.authority.hp")
    die = _mapping(authority.get("hit_dice"), "portable.authority.hit_dice")
    speed = _mapping(authority.get("speed"), "portable.authority.speed")
    paths = _mapping(authority.get("paths"), "portable.authority.paths")
    background = _mapping(authority.get("background_record"), "portable.authority.background_record")
    origin = _mapping(authority.get("origin_record"), "portable.authority.origin_record")
    source = _mapping(authority.get("source"), "portable.authority.source")
    package_hash = checked["package_sha256"]

    def ref(source_id: Any, source_hash: Any, locator: Any) -> dict[str, Any]:
        return {"source_id": source_id, "source_hash": source_hash, "locator": locator}

    source_ref = ref(source["source_id"], source["source_hash"], source["locator"])
    background_source = _mapping(background.get("source"), "portable.background.source")
    origin_source = _mapping(origin.get("source"), "portable.origin.source")
    export = {
        "schema": EXPORT_SCHEMA,
        "identity": {
            "character_id": str(ident["character_id"]),
            "campaign_actor_id": str(ident["character_id"]),
            "display_name": str(ident["display_name"]),
            "build_revision": f"{manifest['project_id']}:r{manifest['project_revision']}",
            "project_id": manifest["project_id"],
            "project_revision": manifest["project_revision"],
            "event_head_hash": manifest["event_head_hash"],
            "replay_state_hash": manifest["replay_state_hash"],
            "content_lock_hash": manifest["content_lock_hash"],
            "canonical_project_hash": manifest["canonical_project_hash"],
        },
        "binding": deepcopy(authority["binding"]),
        "stage": deepcopy(stage),
        "abilities": {name.lower(): abilities[name.upper()] for name in _ABILITY_NAMES},
        "ability_provenance": {
            name.lower(): {
                **source_ref,
                "locator": f"{source['locator']}:{name.upper()}",
                "modifier": (abilities[name.upper()] - 10) // 2,
            }
            for name in _ABILITY_NAMES
        },
        "speed": {"walking_ft": speed["walking_ft"], "provenance": source_ref},
        "hit_dice": [{
            "pool_id": "primary", "sides": die["sides"], "maximum": die["maximum"],
            "remaining": die["remaining"], "provenance": source_ref,
        }],
        "hp": {**deepcopy(hp), "provenance": source_ref},
        "paths": {
            "attainment": {"body": paths["attainment"]["tianxia.path.body_refining"],
                           "qi": paths["attainment"]["tianxia.path.qi_cultivation"],
                           "spirit": paths["attainment"]["tianxia.path.spirit_awakening"]},
            "selected": deepcopy(paths["selected"]),
            "pools": deepcopy(paths["pools"]),
            "cultivation_permissions": deepcopy(paths["cultivation_permissions"]),
        },
        "starting_items": [],
        "starting_effects": [],
        "background_origin": {
            "background_id": background["canonical_record_id"],
            "origin_insight_ids": [origin["canonical_record_id"]],
            "exceptions": [],
            "provenance": [
                ref(background["canonical_record_id"], background_source["source_hash"], background_source["anchor"]),
                ref(origin["canonical_record_id"], origin_source["source_hash"], origin_source["anchor"]),
            ],
        },
        "initialization": {
            "owner": "campaign", "mode": "level0_baseline", "current_state": "full_baseline",
            "recovery_provenance": [source_ref], "encounter_defaults_used": False,
        },
        "source": {
            "authority_kind": "validated_portable_export",
            "package_schema": PORTABLE_PACKAGE_SCHEMA,
            "validation_chain": {
                "id": PORTABLE_AUDIT_ID, "status": "PASS",
                "source_sha256": PORTABLE_AUDIT_SOURCE_SHA256,
                "exporter_source_sha256": PORTABLE_EXPORTER_SOURCE_SHA256,
                "artifact_sha256": "",
                "bytes_verified": True,
            },
            "commitments": {
                "package_sha256": package_hash,
                "project_id": manifest["project_id"], "project_revision": manifest["project_revision"],
                "event_head_hash": manifest["event_head_hash"], "replay_state_hash": manifest["replay_state_hash"],
                "content_lock_hash": manifest["content_lock_hash"], "canonical_project_hash": manifest["canonical_project_hash"],
            },
        },
    }
    export["source"]["validation_chain"]["artifact_sha256"] = _sha(
        {key: deepcopy(export[key]) for key in export if key != "source"}
    )
    return export
