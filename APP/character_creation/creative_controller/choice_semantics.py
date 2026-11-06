"""Verified, source-backed semantics for deterministic creative ranking.

Nothing in this module parses prose or performs similarity inference.  A
semantic claim is usable only when its exact vocabulary value and its
Factory source-fact commitments are present.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.core import sha256_json

from .contracts import (
    CreativeControllerError,
    fail,
    require_digest,
    require_enum,
    require_exact_keys,
    require_list,
    require_string,
    require_type,
    validate_self_hash,
    without_hash,
)


SEMANTICS_SCHEMA = "TianxiaFoundry.ChoiceSemantics.v1"
WHOLE_PLAN_SEMANTICS_SCHEMA = "TianxiaFoundry.WholePlanSemantics.v1"
VOCABULARY_AUTHORITY_SCHEMA = "TianxiaFoundry.CreativeVocabularyAuthority.v1"

CHOICE_KINDS = frozenset({"path", "method", "foundation", "background", "origin", "sphere", "talent", "insight", "milestone", "item", "action"})
SEMANTICS_STATUSES = frozenset({"VERIFIED", "DRAFT", "REVOKED"})
DERIVATIONS = frozenset({"EXPLICIT_CATALOGUE_METADATA", "DETERMINISTIC_TYPED_ADAPTER"})
RELATIONS = frozenset({"prerequisite", "shared_resource", "action_chain", "role_reinforcement", "progression_bridge"})
CADENCES = frozenset({"at_will", "per_turn", "per_scene", "per_rest", "limited", "not_applicable"})
SETUPS = frozenset({"none", "light", "moderate", "heavy"})
SEVERITIES = frozenset({"light", "moderate", "heavy"})
COMPLEXITY_BANDS = frozenset({"simple", "moderate", "complex"})

_ROOT_KEYS = {"schema", "semantics_version", "choice_id", "choice_kind", "catalogue_binding", "authority", "vocabulary_authority_sha256", "theme_tags", "role_tags", "capability_families", "combat_functions", "resource_loop", "progression", "synergy_edges", "redundancy_groups", "tradeoffs", "complexity", "semantics_sha256"}
_BINDING_KEYS = {"catalogue_sha256", "choice_record_sha256", "typed_authority_sha256"}
_AUTHORITY_KEYS = {"status", "derivation", "adapter_version_sha256", "source_fact_ids", "source_projection_sha256"}
_RESOURCE_KEYS = {"consumes", "produces", "cadence", "setup"}
_PROGRESSION_KEYS = {"minimum_cl", "identity_online_cl", "signature_cl", "late_progression_tags"}
_SYNERGY_KEYS = {"target_choice_id", "relation", "source_fact_ids"}
_TRADEOFF_KEYS = {"code", "severity", "source_fact_ids"}
_COMPLEXITY_KEYS = {"band", "factors"}
_VOCABULARY_KEYS = ("theme_tags", "role_tags", "capability_families", "combat_functions", "resource_families", "late_progression_tags", "complexity_factors", "tradeoff_codes")


def build_vocabulary_authority(
    vocabularies: Mapping[str, Sequence[str]],
    *,
    version: int = 1,
    adapter_version_sha256: str | None = None,
) -> dict[str, Any]:
    """Seal the data-owned token vocabulary used by a ranking run.

    Vocabulary values are intentionally supplied data.  The controller only
    knows the protocol field names; it does not own the game's tag list.
    """
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        fail("DCC_SCHEMA_VALUE", "Vocabulary authority version must be positive.")
    require_exact_keys(vocabularies, _VOCABULARY_KEYS, path="vocabulary authority.vocabularies")
    normalized: dict[str, list[str]] = {}
    for key in _VOCABULARY_KEYS:
        rows = require_list(vocabularies[key], path=f"vocabulary authority.vocabularies.{key}")
        values = sorted({require_string(row, path=f"vocabulary authority.vocabularies.{key}[]") for row in rows})
        if len(values) != len(rows):
            fail("DCC_SCHEMA_DUPLICATE", f"vocabulary authority.{key} must be duplicate-free.")
        normalized[key] = values
    if adapter_version_sha256 is not None:
        require_digest(adapter_version_sha256, path="vocabulary authority.adapter_version_sha256")
    unsigned = {
        "schema": VOCABULARY_AUTHORITY_SCHEMA,
        "version": version,
        "vocabularies": normalized,
        "adapter_version_sha256": adapter_version_sha256,
    }
    return {**unsigned, "authority_sha256": sha256_json(unsigned)}


def validate_vocabulary_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, {"schema", "version", "vocabularies", "adapter_version_sha256", "authority_sha256"}, path="vocabulary authority")
    if value["schema"] != VOCABULARY_AUTHORITY_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported vocabulary authority schema.")
    require_type(value["version"], int, path="vocabulary authority.version")
    require_digest(value["adapter_version_sha256"], path="vocabulary authority.adapter_version_sha256", allow_none=True)
    build = build_vocabulary_authority(value["vocabularies"], version=value["version"], adapter_version_sha256=value["adapter_version_sha256"])
    require_digest(value["authority_sha256"], path="vocabulary authority.authority_sha256")
    if value["authority_sha256"] != build["authority_sha256"]:
        fail("DCC_VOCABULARY_AUTHORITY_HASH_INVALID", "Vocabulary authority self-hash mismatch.")
    return deepcopy(dict(value))


def _source_facts(value: Any, *, path: str) -> tuple[str, ...]:
    rows = require_list(value, path=path)
    facts = [require_string(item, path=f"{path}[{index}]") for index, item in enumerate(rows)]
    if not facts:
        fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", f"{path} must contain a source fact.")
    if len(facts) != len(set(facts)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must not contain duplicate source facts.")
    return tuple(sorted(facts))


def _vocabulary_list(value: Any, vocabulary: Iterable[str] | None, *, path: str, allow_empty: bool = True) -> tuple[str, ...]:
    rows = require_list(value, path=path)
    values = [require_string(item, path=f"{path}[{index}]") if vocabulary is None else require_enum(item, vocabulary, path=f"{path}[{index}]") for index, item in enumerate(rows)]
    if not allow_empty and not values:
        fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", f"{path} must contain at least one verified value.")
    if len(values) != len(set(values)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must not contain duplicate vocabulary values.")
    return tuple(values)


@dataclass(frozen=True)
class ChoiceSemantics:
    value: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deepcopy(self.value))
        validate_choice_semantics(self.value)

    @property
    def choice_id(self) -> str:
        return self.value["choice_id"]

    @property
    def semantics_sha256(self) -> str:
        return self.value["semantics_sha256"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.value)


def _coerce_semantics(value: ChoiceSemantics | Mapping[str, Any]) -> ChoiceSemantics:
    return value if isinstance(value, ChoiceSemantics) else ChoiceSemantics(value)


def validate_choice_semantics(value: Mapping[str, Any], *, require_verified: bool = True, vocabulary_authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one exact ChoiceSemantics.v1 record."""

    require_exact_keys(value, _ROOT_KEYS, path="choice semantics")
    if value.get("schema") != SEMANTICS_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported ChoiceSemantics schema.")
    if require_type(value["semantics_version"], int, path="choice semantics.semantics_version") != 1:
        fail("DCC_SCHEMA_VALUE", "Only ChoiceSemantics version 1 is supported.")
    choice_id = require_string(value["choice_id"], path="choice semantics.choice_id")
    require_enum(value["choice_kind"], CHOICE_KINDS, path="choice semantics.choice_kind")
    require_digest(value["vocabulary_authority_sha256"], path="choice semantics.vocabulary_authority_sha256")
    if vocabulary_authority is not None and value["vocabulary_authority_sha256"] != validate_vocabulary_authority(vocabulary_authority)["authority_sha256"]:
        fail("DCC_CHOICE_SEMANTICS_STALE", "ChoiceSemantics references a different vocabulary authority.")

    binding = value["catalogue_binding"]
    require_exact_keys(binding, _BINDING_KEYS, path="choice semantics.catalogue_binding")
    for key in _BINDING_KEYS:
        require_digest(binding[key], path=f"choice semantics.catalogue_binding.{key}")

    authority = value["authority"]
    require_exact_keys(authority, _AUTHORITY_KEYS, path="choice semantics.authority")
    status = require_enum(authority["status"], SEMANTICS_STATUSES, path="choice semantics.authority.status")
    require_enum(authority["derivation"], DERIVATIONS, path="choice semantics.authority.derivation")
    require_digest(authority["adapter_version_sha256"], path="choice semantics.authority.adapter_version_sha256", allow_none=True)
    _source_facts(authority["source_fact_ids"], path="choice semantics.authority.source_fact_ids")
    require_digest(authority["source_projection_sha256"], path="choice semantics.authority.source_projection_sha256")
    if require_verified and status != "VERIFIED":
        fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "Only VERIFIED semantics can cross the publication gate.")

    authority = validate_vocabulary_authority(vocabulary_authority) if vocabulary_authority is not None else None
    vocab = authority["vocabularies"] if authority else {}
    _vocabulary_list(value["theme_tags"], vocab.get("theme_tags"), path="choice semantics.theme_tags")
    _vocabulary_list(value["role_tags"], vocab.get("role_tags"), path="choice semantics.role_tags", allow_empty=False)
    _vocabulary_list(value["capability_families"], vocab.get("capability_families"), path="choice semantics.capability_families", allow_empty=False)
    _vocabulary_list(value["combat_functions"], vocab.get("combat_functions"), path="choice semantics.combat_functions")

    resource = value["resource_loop"]
    require_exact_keys(resource, _RESOURCE_KEYS, path="choice semantics.resource_loop")
    _vocabulary_list(resource["consumes"], vocab.get("resource_families"), path="choice semantics.resource_loop.consumes")
    _vocabulary_list(resource["produces"], vocab.get("resource_families"), path="choice semantics.resource_loop.produces")
    require_enum(resource["cadence"], CADENCES, path="choice semantics.resource_loop.cadence")
    require_enum(resource["setup"], SETUPS, path="choice semantics.resource_loop.setup")

    progression = value["progression"]
    require_exact_keys(progression, _PROGRESSION_KEYS, path="choice semantics.progression")
    for key in ("minimum_cl", "identity_online_cl", "signature_cl"):
        number = require_type(progression[key], int, path=f"choice semantics.progression.{key}")
        if number < 1 or number > 100:
            fail("DCC_SCHEMA_VALUE", f"choice semantics.progression.{key} is outside the supported CL range.")
    if not (progression["minimum_cl"] <= progression["identity_online_cl"] <= progression["signature_cl"]):
        fail("DCC_SCHEMA_VALUE", "Progression CL fields must be monotonically ordered.")
    _vocabulary_list(progression["late_progression_tags"], vocab.get("late_progression_tags"), path="choice semantics.progression.late_progression_tags")

    edges = require_list(value["synergy_edges"], path="choice semantics.synergy_edges")
    seen_targets: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        require_exact_keys(edge, _SYNERGY_KEYS, path=f"choice semantics.synergy_edges[{index}]")
        target = require_string(edge["target_choice_id"], path=f"choice semantics.synergy_edges[{index}].target_choice_id")
        relation = require_enum(edge["relation"], RELATIONS, path=f"choice semantics.synergy_edges[{index}].relation")
        _source_facts(edge["source_fact_ids"], path=f"choice semantics.synergy_edges[{index}].source_fact_ids")
        marker = (target, relation)
        if marker in seen_targets:
            fail("DCC_SCHEMA_DUPLICATE", "choice semantics.synergy_edges must be unique.")
        seen_targets.add(marker)

    redundancy = require_list(value["redundancy_groups"], path="choice semantics.redundancy_groups")
    groups = [require_string(item, path=f"choice semantics.redundancy_groups[{index}]") for index, item in enumerate(redundancy)]
    if len(groups) != len(set(groups)):
        fail("DCC_SCHEMA_DUPLICATE", "redundancy_groups must be unique.")

    tradeoffs = require_list(value["tradeoffs"], path="choice semantics.tradeoffs")
    seen_tradeoffs: set[str] = set()
    for index, tradeoff in enumerate(tradeoffs):
        require_exact_keys(tradeoff, _TRADEOFF_KEYS, path=f"choice semantics.tradeoffs[{index}]")
        code = require_enum(tradeoff["code"], vocab.get("tradeoff_codes"), path=f"choice semantics.tradeoffs[{index}].code") if vocab else require_string(tradeoff["code"], path=f"choice semantics.tradeoffs[{index}].code")
        require_enum(tradeoff["severity"], SEVERITIES, path=f"choice semantics.tradeoffs[{index}].severity")
        _source_facts(tradeoff["source_fact_ids"], path=f"choice semantics.tradeoffs[{index}].source_fact_ids")
        if code in seen_tradeoffs:
            fail("DCC_SCHEMA_DUPLICATE", "tradeoffs must not repeat a code.")
        seen_tradeoffs.add(code)

    complexity = value["complexity"]
    require_exact_keys(complexity, _COMPLEXITY_KEYS, path="choice semantics.complexity")
    require_enum(complexity["band"], COMPLEXITY_BANDS, path="choice semantics.complexity.band")
    _vocabulary_list(complexity["factors"], vocab.get("complexity_factors"), path="choice semantics.complexity.factors")
    validate_self_hash(value, "semantics_sha256", code="DCC_CHOICE_SEMANTICS_HASH_INVALID")
    return deepcopy(dict(value))


def build_choice_semantics(unsigned: Mapping[str, Any]) -> ChoiceSemantics:
    base = deepcopy(dict(unsigned))
    if "semantics_sha256" in base:
        fail("DCC_SEMANTICS_BUILD_INPUT", "ChoiceSemantics construction accepts an unsigned object only.")
    if "vocabulary_authority_sha256" not in base:
        base["vocabulary_authority_sha256"] = sha256_json({"schema": VOCABULARY_AUTHORITY_SCHEMA, "version": 1, "vocabularies": {}, "adapter_version_sha256": None})
    base["semantics_sha256"] = sha256_json(base)
    return ChoiceSemantics(base)


def verify_semantics_binding(value: ChoiceSemantics | Mapping[str, Any], *, catalogue_sha256: str, choice_record_sha256: str, typed_authority_sha256: str) -> None:
    semantics = _coerce_semantics(value).value
    expected = {
        "catalogue_sha256": catalogue_sha256,
        "choice_record_sha256": choice_record_sha256,
        "typed_authority_sha256": typed_authority_sha256,
    }
    if semantics["catalogue_binding"] != expected:
        fail("DCC_CHOICE_SEMANTICS_STALE", "ChoiceSemantics is bound to a different catalogue commitment.")


def minimum_coverage_gate(value: ChoiceSemantics | Mapping[str, Any]) -> None:
    semantics = _coerce_semantics(value).value
    validate_choice_semantics(semantics, require_verified=True)
    authority = semantics["authority"]
    missing: list[str] = []
    if not semantics["role_tags"]:
        missing.append("role_tags")
    if not semantics["capability_families"]:
        missing.append("capability_families")
    if not semantics["complexity"]["band"]:
        missing.append("complexity.band")
    if not all(key in semantics["progression"] for key in ("minimum_cl", "identity_online_cl", "signature_cl")):
        missing.append("progression.timing")
    if not authority["source_fact_ids"]:
        missing.append("authority.source_fact_ids")
    for index, edge in enumerate(semantics["synergy_edges"]):
        if not edge["source_fact_ids"]:
            missing.append(f"synergy_edges[{index}].source_fact_ids")
    for index, tradeoff in enumerate(semantics["tradeoffs"]):
        if not tradeoff["source_fact_ids"]:
            missing.append(f"tradeoffs[{index}].source_fact_ids")
    if missing:
        fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "ChoiceSemantics does not meet minimum verified coverage.", details={"missing": missing})


def validate_semantics_set(values: Mapping[str, ChoiceSemantics | Mapping[str, Any]] | Sequence[ChoiceSemantics | Mapping[str, Any]], *, required_choice_ids: Iterable[str] = (), vocabulary_authority: Mapping[str, Any] | None = None) -> dict[str, ChoiceSemantics]:
    if isinstance(values, Mapping):
        rows = list(values.items())
    else:
        rows = [(None, row) for row in values]
    result: dict[str, ChoiceSemantics] = {}
    for supplied_id, row in rows:
        semantics = _coerce_semantics(row)
        validate_choice_semantics(semantics.value, vocabulary_authority=vocabulary_authority)
        minimum_coverage_gate(semantics)
        if supplied_id is not None and supplied_id != semantics.choice_id:
            fail("DCC_SEMANTICS_BINDING", "A semantics mapping key must equal the record choice_id.")
        if semantics.choice_id in result:
            fail("DCC_SEMANTICS_DUPLICATE", "A semantics set cannot contain duplicate choice IDs.")
        result[semantics.choice_id] = semantics
    required = set(required_choice_ids)
    missing = sorted(required - set(result))
    if missing:
        fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "The semantics set is missing a required choice.", details={"choice_ids": missing})
    return dict(sorted(result.items()))


def choice_semantics_set_sha256(values: Mapping[str, ChoiceSemantics | Mapping[str, Any]] | Sequence[ChoiceSemantics | Mapping[str, Any]], *, required_choice_ids: Iterable[str] = (), vocabulary_authority: Mapping[str, Any] | None = None) -> str:
    records = validate_semantics_set(values, required_choice_ids=required_choice_ids, vocabulary_authority=vocabulary_authority)
    return sha256_json([records[choice_id].semantics_sha256 for choice_id in sorted(records)])


def _plan_choice_ids(plan: Any) -> tuple[str, ...]:
    if isinstance(plan, Mapping):
        raw = plan.get("choices")
        if raw is None:
            raw = plan.get("choice_ids")
        if not isinstance(raw, (list, tuple)):
            fail("DCC_SCHEMA_TYPE", "A plan must expose ordered choices or choice_ids.")
        ids: list[str] = []
        for index, row in enumerate(raw):
            if isinstance(row, Mapping):
                value = row.get("choice_id")
                if value is None:
                    value = row.get("option_id")
            else:
                value = row
            ids.append(require_string(value, path=f"plan.choices[{index}].choice_id"))
    elif isinstance(plan, (list, tuple)):
        ids = [require_string(row, path=f"plan.choice_ids[{index}]") for index, row in enumerate(plan)]
    else:
        fail("DCC_SCHEMA_TYPE", "A plan must be an object or an ordered choice-ID array.")
    if not ids:
        fail("DCC_SCHEMA_VALUE", "A whole-plan semantics projection requires at least one choice.")
    if len(ids) != len(set(ids)):
        fail("DCC_PLAN_DUPLICATE_CHOICE", "A legal plan cannot contain the same choice twice.")
    return tuple(ids)


def _sorted_union(records: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    return sorted({item for record in records for item in record[key]})


def aggregate_whole_plan_semantics(
    plan: Any,
    semantics_by_choice: Mapping[str, ChoiceSemantics | Mapping[str, Any]],
    *,
    acquisition_schedule: Mapping[str, int] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate only explicit verified semantics in choice-ID order."""

    choice_ids = _plan_choice_ids(plan)
    semantics = validate_semantics_set(semantics_by_choice, required_choice_ids=choice_ids)
    rows = [semantics[choice_id].value for choice_id in sorted(choice_ids)]
    semantic_hashes = [semantics[choice_id].semantics_sha256 for choice_id in sorted(choice_ids)]

    synergy_edges: list[dict[str, Any]] = []
    included = set(choice_ids)
    for source_id in sorted(choice_ids):
        for edge in semantics[source_id].value["synergy_edges"]:
            if edge["target_choice_id"] in included:
                synergy_edges.append({
                    "source_choice_id": source_id,
                    "target_choice_id": edge["target_choice_id"],
                    "relation": edge["relation"],
                    "source_fact_ids": sorted(edge["source_fact_ids"]),
                })
    synergy_edges.sort(key=lambda edge: (edge["source_choice_id"], edge["target_choice_id"], edge["relation"], edge["source_fact_ids"]))

    redundancy_counts: dict[str, int] = {}
    for row in rows:
        for group in row["redundancy_groups"]:
            redundancy_counts[group] = redundancy_counts.get(group, 0) + 1

    severity_order = {"light": 1, "moderate": 2, "heavy": 3}
    tradeoff_severity: dict[str, str] = {}
    tradeoff_facts: dict[str, set[str]] = {}
    for row in rows:
        for tradeoff in row["tradeoffs"]:
            code = tradeoff["code"]
            previous = tradeoff_severity.get(code)
            if previous is None or severity_order[tradeoff["severity"]] > severity_order[previous]:
                tradeoff_severity[code] = tradeoff["severity"]
            tradeoff_facts.setdefault(code, set()).update(tradeoff["source_fact_ids"])

    complexity_values = {"simple": 1, "moderate": 2, "complex": 3}
    complexity_bands = sorted({row["complexity"]["band"] for row in rows})
    complexity_factors = sorted({factor for row in rows for factor in row["complexity"]["factors"]})
    complexity_score = sum(complexity_values[row["complexity"]["band"]] for row in rows) + len(complexity_factors)

    schedule: list[dict[str, Any]] = []
    if acquisition_schedule is not None:
        if isinstance(acquisition_schedule, Mapping):
            schedule = [{"choice_id": choice_id, "cl": require_type(acquisition_schedule[choice_id], int, path=f"acquisition_schedule.{choice_id}")} for choice_id in sorted(choice_ids) if choice_id in acquisition_schedule]
        elif isinstance(acquisition_schedule, (list, tuple)):
            for index, item in enumerate(acquisition_schedule):
                require_exact_keys(item, {"choice_id", "cl"}, path=f"acquisition_schedule[{index}]")
                schedule.append({"choice_id": require_string(item["choice_id"], path=f"acquisition_schedule[{index}].choice_id"), "cl": require_type(item["cl"], int, path=f"acquisition_schedule[{index}].cl")})
            schedule = sorted(schedule, key=lambda item: (item["cl"], item["choice_id"]))
    if not schedule:
        schedule = [{"choice_id": choice_id, "cl": semantics[choice_id].value["progression"]["minimum_cl"]} for choice_id in sorted(choice_ids)]
    if any(item["choice_id"] not in included for item in schedule):
        fail("DCC_SCHEMA_VALUE", "An acquisition schedule cannot contain an excluded choice.")

    source_facts = set()
    for row in rows:
        source_facts.update(row["authority"]["source_fact_ids"])
    for edge in synergy_edges:
        source_facts.update(edge["source_fact_ids"])
    for facts in tradeoff_facts.values():
        source_facts.update(facts)
    progression = {
        "minimum_cl": min(row["progression"]["minimum_cl"] for row in rows),
        "identity_online_cl": min(row["progression"]["identity_online_cl"] for row in rows),
        "signature_cl": max(row["progression"]["signature_cl"] for row in rows),
        "late_progression_tags": sorted({tag for row in rows for tag in row["progression"]["late_progression_tags"]}),
        "acquisition_schedule": schedule,
    }
    unsigned = {
        "schema": WHOLE_PLAN_SEMANTICS_SCHEMA,
        "choice_ids": list(sorted(choice_ids)),
        "choice_semantics_set_sha256": sha256_json(semantic_hashes),
        "theme_tags": _sorted_union(rows, "theme_tags"),
        "role_tags": _sorted_union(rows, "role_tags"),
        "capability_families": _sorted_union(rows, "capability_families"),
        "combat_functions": _sorted_union(rows, "combat_functions"),
        "resource_loop": {
            "consumes": _sorted_union([row["resource_loop"] for row in rows], "consumes"),
            "produces": _sorted_union([row["resource_loop"] for row in rows], "produces"),
            "exact_producer_consumer_matches": sorted(set(_sorted_union([row["resource_loop"] for row in rows], "consumes")) & set(_sorted_union([row["resource_loop"] for row in rows], "produces"))),
            "cadences": sorted({row["resource_loop"]["cadence"] for row in rows}),
            "setups": sorted({row["resource_loop"]["setup"] for row in rows}),
        },
        "synergy_edges": synergy_edges,
        "redundancy_counts": dict(sorted(redundancy_counts.items())),
        "tradeoffs": [
            {"code": code, "maximum_severity": tradeoff_severity[code], "source_fact_ids": sorted(tradeoff_facts[code])}
            for code in sorted(tradeoff_severity)
        ],
        "complexity": {
            "bands": complexity_bands,
            "factors": complexity_factors,
            "band_value_sum": sum(complexity_values[row["complexity"]["band"]] for row in rows),
            "factor_count": len(complexity_factors),
            "complexity_score": complexity_score,
        },
        "progression": progression,
        "source_fact_ids": sorted(source_facts),
    }
    return {**unsigned, "whole_plan_semantics_sha256": sha256_json(unsigned)}


def aggregate_plan_semantics(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return aggregate_whole_plan_semantics(*args, **kwargs)


def valid_choice_semantics(value: ChoiceSemantics | Mapping[str, Any]) -> bool:
    try:
        validate_choice_semantics(value.value if isinstance(value, ChoiceSemantics) else value)
    except CreativeControllerError:
        return False
    return True
