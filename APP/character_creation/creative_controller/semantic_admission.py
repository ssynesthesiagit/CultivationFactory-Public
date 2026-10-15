"""Data-owned semantic admission for deterministic creative-controller snapshots.

The adapter in this module accepts only typed, self-hashed facts.  It never
looks at display names, rules prose, descriptions, embeddings, or provider
output.  New game systems and content families are admitted through registry
and record data rather than content-specific controller branches.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core import sha256_json

from .choice_semantics import (
    ChoiceSemantics,
    build_choice_semantics,
    build_vocabulary_authority,
    choice_semantics_set_sha256,
    validate_semantics_set,
    validate_vocabulary_authority,
)
from .content_snapshots import (
    ContentRecordCommitment,
    FactoryContentSnapshot,
    build_content_snapshot,
    validate_content_snapshot,
)
from .contracts import (
    fail,
    require_digest,
    require_enum,
    require_exact_keys,
    require_identifier,
    require_list,
    require_string,
    require_type,
    validate_self_hash,
)
from .creative_menu import build_creative_predicate_menu


PROFILE_REGISTRY_SCHEMA = "TianxiaFoundry.SemanticProfileRegistry.v1"
TYPED_SEMANTIC_RECORD_SCHEMA = "TianxiaFoundry.TypedSemanticRecord.v1"
SEMANTIC_AUTHORITY_BUNDLE_SCHEMA = "TianxiaFoundry.SemanticAuthorityBundle.v1"
SEMANTIC_RECORD_AUTHORITY_SCHEMA = "TianxiaFoundry.SemanticRecordAuthority.v1"
FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA = "TianxiaFoundry.SemanticAuthorityTrustManifest.v1"
SEMANTIC_ADMISSION_RECEIPT_SCHEMA = "TianxiaFoundry.SemanticAdmissionReceipt.v1"
SEMANTIC_ADAPTER_SCHEMA = "TianxiaFoundry.TypedSemanticAdapter.v1"
_FACTORY_SEMANTIC_TRUST_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "authority" / "Tianxia_DCC_Semantic_Authority_Trust_v1.json"
)

_VOCABULARY_KEYS = (
    "theme_tags",
    "role_tags",
    "capability_families",
    "combat_functions",
    "resource_families",
    "late_progression_tags",
    "complexity_factors",
    "tradeoff_codes",
)
_PROFILE_KEYS = {
    "profile_id",
    "inherits",
    "source_fact_ids",
    "theme_tags",
    "role_tags",
    "capability_families",
    "combat_functions",
    "resource_loop",
    "progression",
    "synergy_edges",
    "redundancy_groups",
    "tradeoffs",
    "complexity",
}
_RESOURCE_KEYS = {"consumes", "produces", "cadence", "setup"}
_PROGRESSION_KEYS = {"minimum_cl", "identity_online_cl", "signature_cl", "late_progression_tags"}
_COMPLEXITY_KEYS = {"band", "factors"}
_EDGE_KEYS = {"target_choice_id", "relation", "source_fact_ids"}
_TRADEOFF_KEYS = {"code", "severity", "source_fact_ids"}
_RECORD_KEYS = {
    "schema",
    "choice_id",
    "choice_kind",
    "lifecycle",
    "eligible_for_new_builds",
    "catalogue_schema",
    "catalogue_schema_version",
    "choice_record_sha256",
    "typed_authority_sha256",
    "source_rights_receipt_sha256",
    "profile_ids",
    "source_fact_ids",
    "semantics",
    "dependency_ids",
    "record_projection_sha256",
}
_SOURCE_FACT_KEYS = {"source_fact_id", "status", "source_projection_sha256"}
_RECORD_AUTHORITY_KEYS = {
    "schema",
    "status",
    "choice_id",
    "choice_record_sha256",
    "typed_authority_sha256",
    "source_rights_receipt_sha256",
    "record_projection_sha256",
    "profile_ids",
    "source_fact_ids",
    "authority_sha256",
}
_CHOICE_KINDS = frozenset(
    {"path", "method", "foundation", "background", "origin", "sphere", "talent", "insight", "milestone", "item", "action"}
)
_LIFECYCLES = frozenset({"ACTIVE", "RETIRED", "QUARANTINED"})
_CADENCES = frozenset({"at_will", "per_turn", "per_scene", "per_rest", "limited", "not_applicable"})
_SETUPS = frozenset({"none", "light", "moderate", "heavy"})
_RELATIONS = frozenset({"prerequisite", "shared_resource", "action_chain", "role_reinforcement", "progression_bridge"})
_SEVERITIES = frozenset({"light", "moderate", "heavy"})
_COMPLEXITY_BANDS = frozenset({"simple", "moderate", "complex"})
_AUTHORITY_STATUSES = frozenset({"VERIFIED", "DRAFT", "REVOKED"})


def _unique_strings(value: Any, *, path: str, identifiers: bool = False, maximum: int = 256) -> list[str]:
    rows = require_list(value, path=path, max_length=maximum)
    result = [
        require_identifier(row, path=f"{path}[{index}]")
        if identifiers
        else require_string(row, path=f"{path}[{index}]")
        for index, row in enumerate(rows)
    ]
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must be duplicate-free.")
    return sorted(result)


def _nullable_enum(value: Any, allowed: Sequence[str] | frozenset[str], *, path: str) -> str | None:
    if value is None:
        return None
    return require_enum(value, allowed, path=path)


def _nullable_cl(value: Any, *, path: str) -> int | None:
    if value is None:
        return None
    result = require_type(value, int, path=path)
    if result < 1 or result > 100:
        fail("DCC_SCHEMA_VALUE", f"{path} is outside the supported CL range.")
    return result


def _normalize_edge(value: Any, *, path: str) -> dict[str, Any]:
    require_exact_keys(value, _EDGE_KEYS, path=path)
    return {
        "target_choice_id": require_identifier(value["target_choice_id"], path=f"{path}.target_choice_id"),
        "relation": require_enum(value["relation"], _RELATIONS, path=f"{path}.relation"),
        "source_fact_ids": _unique_strings(value["source_fact_ids"], path=f"{path}.source_fact_ids"),
    }


def _normalize_tradeoff(value: Any, *, path: str) -> dict[str, Any]:
    require_exact_keys(value, _TRADEOFF_KEYS, path=path)
    return {
        "code": require_identifier(value["code"], path=f"{path}.code"),
        "severity": require_enum(value["severity"], _SEVERITIES, path=f"{path}.severity"),
        "source_fact_ids": _unique_strings(value["source_fact_ids"], path=f"{path}.source_fact_ids"),
    }


def _normalize_semantic_fragment(value: Any, *, path: str) -> dict[str, Any]:
    require_exact_keys(
        value,
        {
            "theme_tags",
            "role_tags",
            "capability_families",
            "combat_functions",
            "resource_loop",
            "progression",
            "synergy_edges",
            "redundancy_groups",
            "tradeoffs",
            "complexity",
        },
        path=path,
    )
    resource = value["resource_loop"]
    require_exact_keys(resource, _RESOURCE_KEYS, path=f"{path}.resource_loop")
    progression = value["progression"]
    require_exact_keys(progression, _PROGRESSION_KEYS, path=f"{path}.progression")
    complexity = value["complexity"]
    require_exact_keys(complexity, _COMPLEXITY_KEYS, path=f"{path}.complexity")
    edges = [
        _normalize_edge(row, path=f"{path}.synergy_edges[{index}]")
        for index, row in enumerate(require_list(value["synergy_edges"], path=f"{path}.synergy_edges", max_length=256))
    ]
    edge_keys = [(row["target_choice_id"], row["relation"]) for row in edges]
    if len(edge_keys) != len(set(edge_keys)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path}.synergy_edges must be duplicate-free.")
    tradeoffs = [
        _normalize_tradeoff(row, path=f"{path}.tradeoffs[{index}]")
        for index, row in enumerate(require_list(value["tradeoffs"], path=f"{path}.tradeoffs", max_length=256))
    ]
    if len({row["code"] for row in tradeoffs}) != len(tradeoffs):
        fail("DCC_SCHEMA_DUPLICATE", f"{path}.tradeoffs must be duplicate-free.")
    return {
        "theme_tags": _unique_strings(value["theme_tags"], path=f"{path}.theme_tags", identifiers=True),
        "role_tags": _unique_strings(value["role_tags"], path=f"{path}.role_tags", identifiers=True),
        "capability_families": _unique_strings(value["capability_families"], path=f"{path}.capability_families", identifiers=True),
        "combat_functions": _unique_strings(value["combat_functions"], path=f"{path}.combat_functions", identifiers=True),
        "resource_loop": {
            "consumes": _unique_strings(resource["consumes"], path=f"{path}.resource_loop.consumes", identifiers=True),
            "produces": _unique_strings(resource["produces"], path=f"{path}.resource_loop.produces", identifiers=True),
            "cadence": _nullable_enum(resource["cadence"], _CADENCES, path=f"{path}.resource_loop.cadence"),
            "setup": _nullable_enum(resource["setup"], _SETUPS, path=f"{path}.resource_loop.setup"),
        },
        "progression": {
            "minimum_cl": _nullable_cl(progression["minimum_cl"], path=f"{path}.progression.minimum_cl"),
            "identity_online_cl": _nullable_cl(progression["identity_online_cl"], path=f"{path}.progression.identity_online_cl"),
            "signature_cl": _nullable_cl(progression["signature_cl"], path=f"{path}.progression.signature_cl"),
            "late_progression_tags": _unique_strings(progression["late_progression_tags"], path=f"{path}.progression.late_progression_tags", identifiers=True),
        },
        "synergy_edges": sorted(edges, key=lambda row: (row["target_choice_id"], row["relation"])),
        "redundancy_groups": _unique_strings(value["redundancy_groups"], path=f"{path}.redundancy_groups", identifiers=True),
        "tradeoffs": sorted(tradeoffs, key=lambda row: row["code"]),
        "complexity": {
            "band": _nullable_enum(complexity["band"], _COMPLEXITY_BANDS, path=f"{path}.complexity.band"),
            "factors": _unique_strings(complexity["factors"], path=f"{path}.complexity.factors", identifiers=True),
        },
    }


def _empty_fragment() -> dict[str, Any]:
    return {
        "theme_tags": [],
        "role_tags": [],
        "capability_families": [],
        "combat_functions": [],
        "resource_loop": {"consumes": [], "produces": [], "cadence": None, "setup": None},
        "progression": {"minimum_cl": None, "identity_online_cl": None, "signature_cl": None, "late_progression_tags": []},
        "synergy_edges": [],
        "redundancy_groups": [],
        "tradeoffs": [],
        "complexity": {"band": None, "factors": []},
    }


def _merge_fragments(fragments: Sequence[Mapping[str, Any]], *, path: str) -> dict[str, Any]:
    result = _empty_fragment()
    list_fields = ("theme_tags", "role_tags", "capability_families", "combat_functions", "redundancy_groups")
    for fragment in fragments:
        for key in list_fields:
            result[key] = sorted(set(result[key]) | set(fragment[key]))
        for section, list_keys in (("resource_loop", ("consumes", "produces")), ("progression", ("late_progression_tags",)), ("complexity", ("factors",))):
            for key in list_keys:
                result[section][key] = sorted(set(result[section][key]) | set(fragment[section][key]))
        for section, scalar_keys in (("resource_loop", ("cadence", "setup")), ("progression", ("minimum_cl", "identity_online_cl", "signature_cl")), ("complexity", ("band",))):
            for key in scalar_keys:
                incoming = fragment[section][key]
                current = result[section][key]
                if incoming is not None and current is not None and incoming != current:
                    fail("DCC_SEMANTIC_PROFILE_CONFLICT", f"{path} provides conflicting {section}.{key} values.")
                if incoming is not None:
                    result[section][key] = incoming
        edge_map = {(row["target_choice_id"], row["relation"]): row for row in result["synergy_edges"]}
        for row in fragment["synergy_edges"]:
            key = (row["target_choice_id"], row["relation"])
            if key in edge_map and edge_map[key] != row:
                fail("DCC_SEMANTIC_PROFILE_CONFLICT", f"{path} provides conflicting synergy evidence.")
            edge_map[key] = deepcopy(row)
        result["synergy_edges"] = [edge_map[key] for key in sorted(edge_map)]
        tradeoff_map = {row["code"]: row for row in result["tradeoffs"]}
        for row in fragment["tradeoffs"]:
            if row["code"] in tradeoff_map and tradeoff_map[row["code"]] != row:
                fail("DCC_SEMANTIC_PROFILE_CONFLICT", f"{path} provides conflicting tradeoff evidence.")
            tradeoff_map[row["code"]] = deepcopy(row)
        result["tradeoffs"] = [tradeoff_map[key] for key in sorted(tradeoff_map)]
    return result


def _validate_fragment_vocabulary(fragment: Mapping[str, Any], vocabulary: Mapping[str, Sequence[str]], *, path: str) -> None:
    checks = (
        ("theme_tags", fragment["theme_tags"]),
        ("role_tags", fragment["role_tags"]),
        ("capability_families", fragment["capability_families"]),
        ("combat_functions", fragment["combat_functions"]),
        ("resource_families", [*fragment["resource_loop"]["consumes"], *fragment["resource_loop"]["produces"]]),
        ("late_progression_tags", fragment["progression"]["late_progression_tags"]),
        ("complexity_factors", fragment["complexity"]["factors"]),
        ("tradeoff_codes", [row["code"] for row in fragment["tradeoffs"]]),
    )
    for vocabulary_key, values in checks:
        unknown = sorted(set(values) - set(vocabulary[vocabulary_key]))
        if unknown:
            fail("DCC_SEMANTIC_VOCABULARY_UNKNOWN", f"{path} uses values outside {vocabulary_key}.", details={"values": unknown})


def build_semantic_profile_registry(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and seal a data-owned semantic profile registry."""

    require_exact_keys(data, {"schema", "version", "adapter_version_sha256", "vocabularies", "profiles"}, path="semantic profile registry input")
    if data["schema"] != PROFILE_REGISTRY_SCHEMA or require_type(data["version"], int, path="semantic profile registry.version") < 1:
        fail("DCC_SCHEMA_VALUE", "Unsupported semantic profile registry version.")
    adapter_digest = require_digest(data["adapter_version_sha256"], path="semantic profile registry.adapter_version_sha256")
    vocabulary = build_vocabulary_authority(
        data["vocabularies"],
        version=data["version"],
        adapter_version_sha256=adapter_digest,
    )
    if sum(len(vocabulary["vocabularies"][key]) for key in ("theme_tags", "role_tags", "capability_families")) + 3 > 96:
        fail("DCC_CREATIVE_MENU_BOUND", "The admitted creative vocabulary exceeds the bounded menu ceiling.")
    normalized_profiles: list[dict[str, Any]] = []
    profile_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["profiles"], path="semantic profile registry.profiles", max_length=2048)):
        path = f"semantic profile registry.profiles[{index}]"
        require_exact_keys(raw, _PROFILE_KEYS, path=path)
        profile_id = require_identifier(raw["profile_id"], path=f"{path}.profile_id")
        if profile_id in profile_ids:
            fail("DCC_SEMANTIC_PROFILE_DUPLICATE", "Semantic profile IDs must be unique.")
        profile_ids.add(profile_id)
        fragment = _normalize_semantic_fragment({key: raw[key] for key in _PROFILE_KEYS - {"profile_id", "inherits", "source_fact_ids"}}, path=path)
        _validate_fragment_vocabulary(fragment, vocabulary["vocabularies"], path=path)
        normalized_profiles.append(
            {
                "profile_id": profile_id,
                "inherits": _unique_strings(raw["inherits"], path=f"{path}.inherits", identifiers=True, maximum=32),
                "source_fact_ids": _unique_strings(raw["source_fact_ids"], path=f"{path}.source_fact_ids"),
                **fragment,
            }
        )
    profiles = {row["profile_id"]: row for row in normalized_profiles}
    for row in normalized_profiles:
        unknown = sorted(set(row["inherits"]) - set(profiles))
        if unknown:
            fail("DCC_SEMANTIC_PROFILE_UNKNOWN", "A semantic profile inherits an unknown profile.", details={"profile_ids": unknown})
        if not row["source_fact_ids"]:
            fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "Every semantic profile requires typed source facts.")

    resolved: dict[str, dict[str, Any]] = {}
    visiting: set[str] = set()

    def resolve(profile_id: str, depth: int = 0) -> dict[str, Any]:
        if profile_id in resolved:
            return resolved[profile_id]
        if depth > 32:
            fail("DCC_SEMANTIC_PROFILE_DEPTH", "Semantic profile inheritance exceeds the supported depth.")
        if profile_id in visiting:
            fail("DCC_SEMANTIC_PROFILE_CYCLE", "Semantic profile inheritance contains a cycle.", details={"profile_id": profile_id})
        visiting.add(profile_id)
        row = profiles[profile_id]
        own = {key: deepcopy(row[key]) for key in _PROFILE_KEYS - {"profile_id", "inherits", "source_fact_ids"}}
        fragment = _merge_fragments([*(resolve(parent, depth + 1)["semantics"] for parent in row["inherits"]), own], path=f"semantic profile {profile_id}")
        facts = sorted(set(row["source_fact_ids"]) | {fact for parent in row["inherits"] for fact in resolve(parent, depth + 1)["source_fact_ids"]})
        result = {"semantics": fragment, "source_fact_ids": facts}
        visiting.remove(profile_id)
        resolved[profile_id] = result
        return result

    for profile_id in sorted(profiles):
        resolve(profile_id)
    canonical_profiles = [profiles[profile_id] for profile_id in sorted(profiles)]
    unsigned = {
        "schema": PROFILE_REGISTRY_SCHEMA,
        "version": data["version"],
        "adapter_version_sha256": adapter_digest,
        "vocabulary_authority": vocabulary,
        "profiles": canonical_profiles,
        "resolved_profiles_sha256": sha256_json({profile_id: resolved[profile_id] for profile_id in sorted(resolved)}),
    }
    return {**unsigned, "registry_sha256": sha256_json(unsigned)}


def validate_semantic_profile_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, {"schema", "version", "adapter_version_sha256", "vocabulary_authority", "profiles", "resolved_profiles_sha256", "registry_sha256"}, path="semantic profile registry")
    validate_self_hash(value, "registry_sha256", code="DCC_SEMANTIC_PROFILE_REGISTRY_HASH_INVALID")
    vocabulary = validate_vocabulary_authority(value["vocabulary_authority"])
    rebuilt = build_semantic_profile_registry(
        {
            "schema": value["schema"],
            "version": value["version"],
            "adapter_version_sha256": value["adapter_version_sha256"],
            "vocabularies": vocabulary["vocabularies"],
            "profiles": value["profiles"],
        }
    )
    if rebuilt != dict(value):
        fail("DCC_SEMANTIC_PROFILE_REGISTRY_HASH_INVALID", "Semantic profile registry does not rebuild identically.")
    return deepcopy(dict(value))


def _canonical_record_authority_unsigned(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _RECORD_AUTHORITY_KEYS - {"authority_sha256"}, path="semantic record authority input")
    if value["schema"] != SEMANTIC_RECORD_AUTHORITY_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported semantic record authority schema.")
    return {
        "schema": SEMANTIC_RECORD_AUTHORITY_SCHEMA,
        "status": require_enum(value["status"], _AUTHORITY_STATUSES, path="semantic record authority.status"),
        "choice_id": require_identifier(value["choice_id"], path="semantic record authority.choice_id"),
        "choice_record_sha256": require_digest(value["choice_record_sha256"], path="semantic record authority.choice_record_sha256"),
        "typed_authority_sha256": require_digest(value["typed_authority_sha256"], path="semantic record authority.typed_authority_sha256"),
        "source_rights_receipt_sha256": require_digest(value["source_rights_receipt_sha256"], path="semantic record authority.source_rights_receipt_sha256"),
        "record_projection_sha256": require_digest(value["record_projection_sha256"], path="semantic record authority.record_projection_sha256"),
        "profile_ids": _unique_strings(value["profile_ids"], path="semantic record authority.profile_ids", identifiers=True, maximum=64),
        "source_fact_ids": _unique_strings(value["source_fact_ids"], path="semantic record authority.source_fact_ids"),
    }


def seal_semantic_record_authority(data: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = _canonical_record_authority_unsigned(data)
    return {**unsigned, "authority_sha256": sha256_json(unsigned)}


def validate_semantic_record_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _RECORD_AUTHORITY_KEYS, path="semantic record authority")
    validate_self_hash(value, "authority_sha256", code="DCC_SEMANTIC_RECORD_AUTHORITY_HASH_INVALID")
    canonical = _canonical_record_authority_unsigned({key: value[key] for key in _RECORD_AUTHORITY_KEYS - {"authority_sha256"}})
    rebuilt = {**canonical, "authority_sha256": sha256_json(canonical)}
    if dict(value) != rebuilt:
        fail("DCC_SEMANTIC_RECORD_AUTHORITY_NONCANONICAL", "Semantic record authority collections must use canonical ordering.")
    return deepcopy(rebuilt)


def build_semantic_authority_bundle(data: Mapping[str, Any]) -> dict[str, Any]:
    """Seal the offline authority against which semantic claims are verified.

    The returned digest is not itself a trust root.  Production callers must
    freeze it independently and pass that expected digest into admission.
    """

    require_exact_keys(
        data,
        {"schema", "version", "semantic_profile_registry_sha256", "source_facts", "record_authorities"},
        path="semantic authority bundle input",
    )
    if data["schema"] != SEMANTIC_AUTHORITY_BUNDLE_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported semantic authority bundle schema.")
    version = require_type(data["version"], int, path="semantic authority bundle.version")
    if version < 1:
        fail("DCC_SCHEMA_VALUE", "Semantic authority bundle version must be positive.")
    facts: list[dict[str, Any]] = []
    for index, raw in enumerate(require_list(data["source_facts"], path="semantic authority bundle.source_facts", max_length=8192)):
        path = f"semantic authority bundle.source_facts[{index}]"
        require_exact_keys(raw, _SOURCE_FACT_KEYS, path=path)
        facts.append(
            {
                "source_fact_id": require_string(raw["source_fact_id"], path=f"{path}.source_fact_id"),
                "status": require_enum(raw["status"], _AUTHORITY_STATUSES, path=f"{path}.status"),
                "source_projection_sha256": require_digest(raw["source_projection_sha256"], path=f"{path}.source_projection_sha256"),
            }
        )
    facts.sort(key=lambda row: row["source_fact_id"])
    if len({row["source_fact_id"] for row in facts}) != len(facts):
        fail("DCC_SEMANTIC_SOURCE_FACT_DUPLICATE", "Semantic authority source-fact IDs must be unique.")
    authorities: list[dict[str, Any]] = []
    for raw in require_list(data["record_authorities"], path="semantic authority bundle.record_authorities", max_length=8192):
        authorities.append(
            validate_semantic_record_authority(raw)
            if isinstance(raw, Mapping) and "authority_sha256" in raw
            else seal_semantic_record_authority(raw)
        )
    authorities.sort(key=lambda row: row["choice_id"])
    if len({row["choice_id"] for row in authorities}) != len(authorities):
        fail("DCC_SEMANTIC_RECORD_AUTHORITY_DUPLICATE", "Semantic record authorities must be unique by choice ID.")
    fact_ids = {row["source_fact_id"] for row in facts}
    unknown = sorted({fact for row in authorities for fact in row["source_fact_ids"]} - fact_ids)
    if unknown:
        fail("DCC_SEMANTIC_SOURCE_FACT_UNKNOWN", "A record authority references an unknown source fact.", details={"source_fact_ids": unknown})
    unsigned = {
        "schema": SEMANTIC_AUTHORITY_BUNDLE_SCHEMA,
        "version": version,
        "semantic_profile_registry_sha256": require_digest(
            data["semantic_profile_registry_sha256"],
            path="semantic authority bundle.semantic_profile_registry_sha256",
        ),
        "source_facts": facts,
        "record_authorities": authorities,
    }
    return {**unsigned, "authority_bundle_sha256": sha256_json(unsigned)}


def validate_semantic_authority_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(
        value,
        {
            "schema",
            "version",
            "semantic_profile_registry_sha256",
            "source_facts",
            "record_authorities",
            "authority_bundle_sha256",
        },
        path="semantic authority bundle",
    )
    validate_self_hash(value, "authority_bundle_sha256", code="DCC_SEMANTIC_AUTHORITY_BUNDLE_HASH_INVALID")
    rebuilt = build_semantic_authority_bundle(
        {
            "schema": value["schema"],
            "version": value["version"],
            "semantic_profile_registry_sha256": value["semantic_profile_registry_sha256"],
            "source_facts": value["source_facts"],
            "record_authorities": value["record_authorities"],
        }
    )
    if rebuilt != dict(value):
        fail("DCC_SEMANTIC_AUTHORITY_BUNDLE_NONCANONICAL", "Semantic authority bundle must use canonical ordering.")
    return deepcopy(rebuilt)


def _canonical_typed_record_unsigned(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _RECORD_KEYS - {"record_projection_sha256"}, path="typed semantic record input")
    if value["schema"] != TYPED_SEMANTIC_RECORD_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported typed semantic record schema.")
    choice_id = require_identifier(value["choice_id"], path="typed semantic record.choice_id")
    choice_kind = require_enum(value["choice_kind"], _CHOICE_KINDS, path="typed semantic record.choice_kind")
    lifecycle = require_enum(value["lifecycle"], _LIFECYCLES, path="typed semantic record.lifecycle")
    if not isinstance(value["eligible_for_new_builds"], bool) or value["eligible_for_new_builds"] is not (lifecycle == "ACTIVE"):
        fail("DCC_CONTENT_LIFECYCLE_INVALID", "Typed record eligibility must exactly match lifecycle.")
    catalogue_schema = require_identifier(value["catalogue_schema"], path="typed semantic record.catalogue_schema")
    version = require_type(value["catalogue_schema_version"], int, path="typed semantic record.catalogue_schema_version")
    if version < 1:
        fail("DCC_SCHEMA_VALUE", "Catalogue schema version must be positive.")
    digests: dict[str, str] = {}
    for key in ("choice_record_sha256", "typed_authority_sha256", "source_rights_receipt_sha256"):
        require_digest(value[key], path=f"typed semantic record.{key}")
        digests[key] = value[key]
    profile_ids = _unique_strings(value["profile_ids"], path="typed semantic record.profile_ids", identifiers=True, maximum=64)
    facts = _unique_strings(value["source_fact_ids"], path="typed semantic record.source_fact_ids")
    if not facts:
        fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "A typed semantic record requires source facts.")
    semantics = _normalize_semantic_fragment(value["semantics"], path="typed semantic record.semantics")
    dependencies = _unique_strings(value["dependency_ids"], path="typed semantic record.dependency_ids", identifiers=True)
    if choice_id in dependencies:
        fail("DCC_DEPENDENCY_CYCLE", "A typed semantic record cannot depend on itself.")
    return {
        "schema": TYPED_SEMANTIC_RECORD_SCHEMA,
        "choice_id": choice_id,
        "choice_kind": choice_kind,
        "lifecycle": lifecycle,
        "eligible_for_new_builds": value["eligible_for_new_builds"],
        "catalogue_schema": catalogue_schema,
        "catalogue_schema_version": version,
        **digests,
        "profile_ids": profile_ids,
        "source_fact_ids": facts,
        "semantics": semantics,
        "dependency_ids": dependencies,
    }


def seal_typed_semantic_record(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and seal one exact typed semantic record projection."""

    unsigned = _canonical_typed_record_unsigned(data)
    sealed = {**unsigned, "record_projection_sha256": sha256_json(unsigned)}
    return validate_typed_semantic_record(sealed)


def validate_typed_semantic_record(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _RECORD_KEYS, path="typed semantic record")
    require_digest(value["record_projection_sha256"], path="typed semantic record.record_projection_sha256")
    validate_self_hash(value, "record_projection_sha256", code="DCC_TYPED_SEMANTIC_RECORD_HASH_INVALID")
    canonical = _canonical_typed_record_unsigned({key: value[key] for key in _RECORD_KEYS - {"record_projection_sha256"}})
    rebuilt = {**canonical, "record_projection_sha256": sha256_json(canonical)}
    if dict(value) != rebuilt:
        fail("DCC_TYPED_SEMANTIC_RECORD_NONCANONICAL", "Typed semantic record collections must use canonical ordering.")
    return deepcopy(rebuilt)


def _resolved_profiles(registry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    # Re-resolution is deterministic and verified by the registry rebuild.
    rebuilt = build_semantic_profile_registry(
        {
            "schema": registry["schema"],
            "version": registry["version"],
            "adapter_version_sha256": registry["adapter_version_sha256"],
            "vocabularies": registry["vocabulary_authority"]["vocabularies"],
            "profiles": registry["profiles"],
        }
    )
    profiles = {row["profile_id"]: row for row in rebuilt["profiles"]}
    memo: dict[str, dict[str, Any]] = {}

    def resolve(profile_id: str) -> dict[str, Any]:
        if profile_id in memo:
            return memo[profile_id]
        row = profiles[profile_id]
        own = {key: deepcopy(row[key]) for key in _PROFILE_KEYS - {"profile_id", "inherits", "source_fact_ids"}}
        semantics = _merge_fragments([*(resolve(parent)["semantics"] for parent in row["inherits"]), own], path=f"semantic profile {profile_id}")
        facts = sorted(set(row["source_fact_ids"]) | {fact for parent in row["inherits"] for fact in resolve(parent)["source_fact_ids"]})
        memo[profile_id] = {"semantics": semantics, "source_fact_ids": facts}
        return memo[profile_id]

    for profile_id in sorted(profiles):
        resolve(profile_id)
    return memo


@dataclass(frozen=True)
class SemanticAdmissionResult:
    registry: dict[str, Any]
    vocabulary_authority: dict[str, Any]
    semantics: dict[str, ChoiceSemantics]
    snapshot: FactoryContentSnapshot
    receipt: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry", deepcopy(self.registry))
        object.__setattr__(self, "vocabulary_authority", deepcopy(self.vocabulary_authority))
        object.__setattr__(self, "semantics", {key: ChoiceSemantics(value.to_dict()) for key, value in self.semantics.items()})
        object.__setattr__(self, "snapshot", FactoryContentSnapshot.from_mapping(self.snapshot.to_dict()))
        object.__setattr__(self, "receipt", deepcopy(self.receipt))

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry": deepcopy(self.registry),
            "vocabulary_authority": deepcopy(self.vocabulary_authority),
            "semantics": {key: value.to_dict() for key, value in sorted(self.semantics.items())},
            "snapshot": self.snapshot.to_dict(),
            "receipt": deepcopy(self.receipt),
        }


def load_factory_semantic_authority_bundle_sha256() -> str:
    """Load the one owner-published semantic trust root from Factory assets.

    The path is deliberately not caller-selectable.  Publishing or revoking a
    semantic authority is a content-authority operation, not a run request or
    provider capability.  The checked-in manifest starts inactive; activation
    requires an explicit owner-reviewed authority publication.
    """

    try:
        value = json.loads(_FACTORY_SEMANTIC_TRUST_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(
            "DCC_SEMANTIC_AUTHORITY_TRUST_UNAVAILABLE",
            "Factory semantic authority trust manifest is unavailable or malformed.",
            details={"error_type": type(exc).__name__},
        )
    require_exact_keys(
        value,
        {
            "schema",
            "version",
            "status",
            "active_authority_bundle_sha256",
            "revoked_authority_bundle_sha256s",
            "manifest_sha256",
        },
        path="Factory semantic authority trust manifest",
    )
    validate_self_hash(value, "manifest_sha256", code="DCC_SEMANTIC_AUTHORITY_TRUST_HASH_INVALID")
    if value["schema"] != FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported Factory semantic authority trust manifest schema.")
    version = require_type(value["version"], int, path="Factory semantic authority trust manifest.version")
    if version < 1:
        fail("DCC_SCHEMA_VALUE", "Factory semantic authority trust manifest version must be positive.")
    status = require_enum(value["status"], {"ACTIVE", "INACTIVE"}, path="Factory semantic authority trust manifest.status")
    revoked = _unique_strings(
        value["revoked_authority_bundle_sha256s"],
        path="Factory semantic authority trust manifest.revoked_authority_bundle_sha256s",
        maximum=8192,
    )
    for index, digest in enumerate(revoked):
        require_digest(digest, path=f"Factory semantic authority trust manifest.revoked_authority_bundle_sha256s[{index}]")
    active = value["active_authority_bundle_sha256"]
    if status == "INACTIVE":
        if active is not None:
            fail("DCC_SEMANTIC_AUTHORITY_TRUST_INVALID", "An inactive Factory semantic trust manifest cannot publish an active authority.")
        fail("DCC_SEMANTIC_AUTHORITY_UNPUBLISHED", "Factory has not published an active semantic authority bundle.")
    active_digest = require_digest(active, path="Factory semantic authority trust manifest.active_authority_bundle_sha256")
    if active_digest in revoked:
        fail("DCC_SEMANTIC_AUTHORITY_REVOKED", "The active Factory semantic authority bundle has been revoked.")
    canonical = {
        "schema": FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA,
        "version": version,
        "status": status,
        "active_authority_bundle_sha256": active_digest,
        "revoked_authority_bundle_sha256s": revoked,
    }
    if value != {**canonical, "manifest_sha256": sha256_json(canonical)}:
        fail("DCC_SEMANTIC_AUTHORITY_TRUST_NONCANONICAL", "Factory semantic authority trust manifest must be canonical.")
    return active_digest


def _admit_typed_semantics(
    records: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    authority_bundle: Mapping[str, Any],
    *,
    catalogue_schema_versions: Mapping[str, int],
    rules_authority_sha256: str,
    required_compiler_profile_sha256: str,
    parent: FactoryContentSnapshot | Mapping[str, Any] | None = None,
    expected_authority_bundle_sha256: str | None = None,
) -> SemanticAdmissionResult:
    """Admit typed records into verified semantics and an immutable snapshot."""

    admitted_registry = validate_semantic_profile_registry(registry)
    vocabulary = validate_vocabulary_authority(admitted_registry["vocabulary_authority"])
    admitted_authority = validate_semantic_authority_bundle(authority_bundle)
    expected_authority = (
        load_factory_semantic_authority_bundle_sha256()
        if expected_authority_bundle_sha256 is None
        else require_digest(expected_authority_bundle_sha256, path="semantic admission.expected_authority_bundle_sha256")
    )
    if admitted_authority["authority_bundle_sha256"] != expected_authority:
        fail("DCC_SEMANTIC_AUTHORITY_TRUST_MISMATCH", "Semantic authority bundle does not match the frozen Factory trust anchor.")
    if admitted_authority["semantic_profile_registry_sha256"] != admitted_registry["registry_sha256"]:
        fail("DCC_SEMANTIC_PROFILE_AUTHORITY_STALE", "Frozen semantic authority does not bind the admitted profile registry.")
    facts_by_id = {row["source_fact_id"]: row for row in admitted_authority["source_facts"]}

    def require_verified_facts(source_fact_ids: Sequence[str], *, context: str) -> None:
        unknown = sorted(set(source_fact_ids) - set(facts_by_id))
        if unknown:
            fail("DCC_SEMANTIC_SOURCE_FACT_UNKNOWN", "Semantic admission references unknown source facts.", details={"context": context, "source_fact_ids": unknown})
        unverified = sorted(fact_id for fact_id in set(source_fact_ids) if facts_by_id[fact_id]["status"] != "VERIFIED")
        if unverified:
            fail("DCC_SEMANTIC_SOURCE_FACT_UNVERIFIED", "Semantic admission references draft or revoked source facts.", details={"context": context, "source_fact_ids": unverified})

    for profile in admitted_registry["profiles"]:
        profile_facts = [
            *profile["source_fact_ids"],
            *(fact for edge in profile["synergy_edges"] for fact in edge["source_fact_ids"]),
            *(fact for tradeoff in profile["tradeoffs"] for fact in tradeoff["source_fact_ids"]),
        ]
        require_verified_facts(profile_facts, context=f"profile:{profile['profile_id']}")
    require_digest(rules_authority_sha256, path="semantic admission.rules_authority_sha256")
    require_digest(required_compiler_profile_sha256, path="semantic admission.required_compiler_profile_sha256")
    normalized_input = require_list(records, path="semantic admission.records", max_length=8192)
    if not normalized_input:
        fail("DCC_CONTENT_EMPTY", "Semantic admission requires at least one typed record.")
    normalized = [validate_typed_semantic_record(row) for row in normalized_input]
    normalized.sort(key=lambda row: row["choice_id"])
    if len({row["choice_id"] for row in normalized}) != len(normalized):
        fail("DCC_CONTENT_DUPLICATE_CHOICE_ID", "Semantic admission cannot contain duplicate choice IDs.")
    record_authorities = {row["choice_id"]: row for row in admitted_authority["record_authorities"]}
    for row in normalized:
        record_authority = record_authorities.get(row["choice_id"])
        if record_authority is None:
            fail("DCC_SEMANTIC_RECORD_AUTHORITY_MISSING", "A typed semantic record has no frozen authority.", details={"choice_id": row["choice_id"]})
        expected_binding = {
            "schema": SEMANTIC_RECORD_AUTHORITY_SCHEMA,
            "status": "VERIFIED",
            "choice_id": row["choice_id"],
            "choice_record_sha256": row["choice_record_sha256"],
            "typed_authority_sha256": row["typed_authority_sha256"],
            "source_rights_receipt_sha256": row["source_rights_receipt_sha256"],
            "record_projection_sha256": row["record_projection_sha256"],
            "profile_ids": row["profile_ids"],
            "source_fact_ids": row["source_fact_ids"],
        }
        expected_binding["authority_sha256"] = sha256_json(expected_binding)
        if record_authority != expected_binding:
            fail("DCC_SEMANTIC_RECORD_AUTHORITY_STALE", "Frozen record authority does not exactly bind the typed semantic record.", details={"choice_id": row["choice_id"]})
        record_facts = [
            *row["source_fact_ids"],
            *(fact for edge in row["semantics"]["synergy_edges"] for fact in edge["source_fact_ids"]),
            *(fact for tradeoff in row["semantics"]["tradeoffs"] for fact in tradeoff["source_fact_ids"]),
        ]
        require_verified_facts(record_facts, context=f"record:{row['choice_id']}")
    if not isinstance(catalogue_schema_versions, Mapping):
        fail("DCC_SCHEMA_TYPE", "semantic admission.catalogue_schema_versions must be an object.")
    if len(catalogue_schema_versions) > 256:
        fail("DCC_SCHEMA_LIMIT", "semantic admission.catalogue_schema_versions exceeds its item limit.", details={"maximum": 256})
    versions = dict(catalogue_schema_versions)
    if not versions:
        fail("DCC_CONTENT_SCHEMA_VERSIONS_EMPTY", "Semantic admission requires catalogue schema versions.")
    for name, version in versions.items():
        require_identifier(name, path="semantic admission.catalogue_schema_versions.name")
        if require_type(version, int, path=f"semantic admission.catalogue_schema_versions.{name}") < 1:
            fail("DCC_SCHEMA_VALUE", "Catalogue schema versions must be positive.")
    for row in normalized:
        if versions.get(row["catalogue_schema"]) != row["catalogue_schema_version"]:
            fail("DCC_SEMANTIC_CATALOGUE_SCHEMA_STALE", "Typed record catalogue schema/version is not in the admitted version map.", details={"choice_id": row["choice_id"]})

    active_commitments = [
        {
            "choice_id": row["choice_id"],
            "choice_kind": row["choice_kind"],
            "choice_record_sha256": row["choice_record_sha256"],
            "typed_authority_sha256": row["typed_authority_sha256"],
            "source_rights_receipt_sha256": row["source_rights_receipt_sha256"],
        }
        for row in normalized
        if row["lifecycle"] == "ACTIVE"
    ]
    catalogue_set_sha256 = sha256_json(
        {
            "catalogue_schema_versions": dict(sorted(versions.items())),
            "active_record_commitments": active_commitments,
        }
    )
    profiles = _resolved_profiles(admitted_registry)
    semantic_rows: dict[str, ChoiceSemantics] = {}
    commitments: list[ContentRecordCommitment] = []
    for row in normalized:
        unknown_profiles = sorted(set(row["profile_ids"]) - set(profiles))
        if unknown_profiles:
            fail("DCC_SEMANTIC_PROFILE_UNKNOWN", "A typed record references an unknown semantic profile.", details={"choice_id": row["choice_id"], "profile_ids": unknown_profiles})
        record_fragment = _normalize_semantic_fragment(row["semantics"], path=f"typed semantic record {row['choice_id']}.semantics")
        merged = _merge_fragments(
            [*(profiles[profile_id]["semantics"] for profile_id in sorted(row["profile_ids"])), record_fragment],
            path=f"typed semantic record {row['choice_id']}",
        )
        _validate_fragment_vocabulary(merged, vocabulary["vocabularies"], path=f"typed semantic record {row['choice_id']}")
        scalar_values = (
            merged["resource_loop"]["cadence"],
            merged["resource_loop"]["setup"],
            merged["progression"]["minimum_cl"],
            merged["progression"]["identity_online_cl"],
            merged["progression"]["signature_cl"],
            merged["complexity"]["band"],
        )
        if any(value is None for value in scalar_values) or not merged["role_tags"] or not merged["capability_families"]:
            fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "Typed profiles do not provide minimum complete semantics.", details={"choice_id": row["choice_id"]})
        facts = sorted(
            set(row["source_fact_ids"])
            | {fact for profile_id in row["profile_ids"] for fact in profiles[profile_id]["source_fact_ids"]}
            | {fact for edge in merged["synergy_edges"] for fact in edge["source_fact_ids"]}
            | {fact for tradeoff in merged["tradeoffs"] for fact in tradeoff["source_fact_ids"]}
        )
        require_verified_facts(facts, context=f"resolved:{row['choice_id']}")
        if not facts:
            fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "Typed semantic projection has no source facts.")
        projection = {
            "schema": SEMANTIC_ADAPTER_SCHEMA,
            "registry_sha256": admitted_registry["registry_sha256"],
            "authority_bundle_sha256": admitted_authority["authority_bundle_sha256"],
            "record_projection_sha256": row["record_projection_sha256"],
            "resolved_semantics": merged,
            "source_fact_ids": facts,
        }
        semantic = build_choice_semantics(
            {
                "schema": "TianxiaFoundry.ChoiceSemantics.v1",
                "semantics_version": 1,
                "choice_id": row["choice_id"],
                "choice_kind": row["choice_kind"],
                "catalogue_binding": {
                    "catalogue_sha256": catalogue_set_sha256,
                    "choice_record_sha256": row["choice_record_sha256"],
                    "typed_authority_sha256": row["typed_authority_sha256"],
                },
                "authority": {
                    "status": "VERIFIED",
                    "derivation": "DETERMINISTIC_TYPED_ADAPTER",
                    "adapter_version_sha256": admitted_registry["adapter_version_sha256"],
                    "source_fact_ids": facts,
                    "source_projection_sha256": sha256_json(projection),
                },
                "vocabulary_authority_sha256": vocabulary["authority_sha256"],
                **merged,
            }
        )
        semantic_rows[row["choice_id"]] = semantic
        commitments.append(
            ContentRecordCommitment(
                choice_id=row["choice_id"],
                choice_kind=row["choice_kind"],
                lifecycle=row["lifecycle"],
                eligible_for_new_builds=row["eligible_for_new_builds"],
                choice_record_sha256=row["choice_record_sha256"],
                typed_authority_sha256=row["typed_authority_sha256"],
                choice_semantics_sha256=semantic.semantics_sha256,
                source_rights_receipt_sha256=row["source_rights_receipt_sha256"],
                dependency_ids=tuple(row["dependency_ids"]),
            )
        )
    validate_semantics_set(semantic_rows, required_choice_ids=[row["choice_id"] for row in normalized if row["lifecycle"] == "ACTIVE"], vocabulary_authority=vocabulary)
    snapshot = build_content_snapshot(
        commitments,
        catalogue_schema_versions=versions,
        rules_authority_sha256=rules_authority_sha256,
        required_compiler_profile_sha256=required_compiler_profile_sha256,
        parent=parent,
        dependency_edges={row["choice_id"]: row["dependency_ids"] for row in normalized},
        vocabulary_authority_sha256=vocabulary["authority_sha256"],
    )
    validate_content_snapshot(snapshot)
    if snapshot.catalogue_set_sha256 != catalogue_set_sha256:
        fail("DCC_SEMANTIC_CATALOGUE_BINDING_INVALID", "Semantic admission and snapshot catalogue commitments disagree.")
    active_semantics = {row["choice_id"]: semantic_rows[row["choice_id"]] for row in normalized if row["lifecycle"] == "ACTIVE"}
    expected_semantics_hash = choice_semantics_set_sha256(active_semantics, required_choice_ids=active_semantics, vocabulary_authority=vocabulary)
    if snapshot.choice_semantics_set_sha256 != expected_semantics_hash:
        fail("DCC_SEMANTIC_SET_BINDING_INVALID", "Semantic admission and snapshot semantics commitments disagree.")
    # Constructing this menu is also the admission-time upper-bound check.
    predicate_menu = build_creative_predicate_menu(vocabulary, maximum_options=96)
    unsigned_receipt = {
        "schema": SEMANTIC_ADMISSION_RECEIPT_SCHEMA,
        "registry_sha256": admitted_registry["registry_sha256"],
        "authority_bundle_sha256": admitted_authority["authority_bundle_sha256"],
        "vocabulary_authority_sha256": vocabulary["authority_sha256"],
        "content_snapshot_sha256": snapshot.content_snapshot_sha256,
        "catalogue_set_sha256": snapshot.catalogue_set_sha256,
        "choice_semantics_set_sha256": snapshot.choice_semantics_set_sha256,
        "predicate_menu_sha256": predicate_menu.menu_sha256,
        "active_choice_ids": sorted(active_semantics),
        "record_count": len(normalized),
    }
    receipt = {**unsigned_receipt, "receipt_sha256": sha256_json(unsigned_receipt)}
    return SemanticAdmissionResult(admitted_registry, vocabulary, semantic_rows, snapshot, receipt)


def admit_typed_semantics(
    records: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    authority_bundle: Mapping[str, Any],
    *,
    catalogue_schema_versions: Mapping[str, int],
    rules_authority_sha256: str,
    required_compiler_profile_sha256: str,
    parent: FactoryContentSnapshot | Mapping[str, Any] | None = None,
) -> SemanticAdmissionResult:
    """Admit against the fixed production semantic trust root.

    The publication workflow calls the private helper with an in-memory
    proposed trust digest during preflight.  Runtime callers retain this
    fixed-trust entry point and cannot select a trust root.
    """

    return _admit_typed_semantics(
        records,
        registry,
        authority_bundle,
        catalogue_schema_versions=catalogue_schema_versions,
        rules_authority_sha256=rules_authority_sha256,
        required_compiler_profile_sha256=required_compiler_profile_sha256,
        parent=parent,
    )


__all__ = [
    "PROFILE_REGISTRY_SCHEMA",
    "TYPED_SEMANTIC_RECORD_SCHEMA",
    "SEMANTIC_AUTHORITY_BUNDLE_SCHEMA",
    "SEMANTIC_RECORD_AUTHORITY_SCHEMA",
    "FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA",
    "SEMANTIC_ADMISSION_RECEIPT_SCHEMA",
    "SemanticAdmissionResult",
    "build_semantic_profile_registry",
    "validate_semantic_profile_registry",
    "seal_semantic_record_authority",
    "validate_semantic_record_authority",
    "build_semantic_authority_bundle",
    "validate_semantic_authority_bundle",
    "load_factory_semantic_authority_bundle_sha256",
    "seal_typed_semantic_record",
    "validate_typed_semantic_record",
    "admit_typed_semantics",
]
