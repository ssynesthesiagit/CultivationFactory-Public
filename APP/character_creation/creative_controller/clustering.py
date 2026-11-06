"""Deterministic categorical diversity selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .contracts import fail, require_string
from .legal_plan_compiler import LegalPlan
from .ranking import RankedPlan


SIGNATURE_FIELDS = ("primary_route", "combat_role", "signature_capabilities", "resource_loop", "progression_cadence", "key_synergy_pair", "major_tradeoff", "complexity_band")
SIGNATURE_WEIGHTS = {
    "primary_route": 5,
    "combat_role": 4,
    "signature_capabilities": 3,
    "resource_loop": 3,
    "progression_cadence": 2,
    "key_synergy_pair": 2,
    "major_tradeoff": 2,
    "complexity_band": 1,
}


def _as_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item) for item in value}
    return {str(value)}


@dataclass(frozen=True)
class CategoricalSignature:
    primary_route: str
    combat_role: tuple[str, ...]
    signature_capabilities: tuple[str, ...]
    resource_loop: tuple[str, ...]
    progression_cadence: tuple[str, ...]
    key_synergy_pair: tuple[str, ...]
    major_tradeoff: tuple[str, ...]
    complexity_band: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_route": self.primary_route,
            "combat_role": list(self.combat_role),
            "signature_capabilities": list(self.signature_capabilities),
            "resource_loop": list(self.resource_loop),
            "progression_cadence": list(self.progression_cadence),
            "key_synergy_pair": list(self.key_synergy_pair),
            "major_tradeoff": list(self.major_tradeoff),
            "complexity_band": self.complexity_band,
        }


@dataclass(frozen=True)
class DiversityCluster:
    medoid_plan_sha256: str
    member_plan_sha256s: tuple[str, ...]
    signature: CategoricalSignature


@dataclass(frozen=True)
class DiversityResult:
    selected: tuple[RankedPlan, ...]
    clusters: tuple[DiversityCluster, ...]


def signature_for_plan(plan: LegalPlan | Mapping[str, Any], whole_plan_semantics: Mapping[str, Any]) -> CategoricalSignature:
    if hasattr(plan, "plan_payload"):
        payload = plan.plan_payload  # type: ignore[union-attr]
    else:
        payload = plan
    choices = payload.get("choices") if isinstance(payload, Mapping) else None
    if not isinstance(choices, (list, tuple)):
        fail("DCC_SCHEMA_TYPE", "A plan signature requires typed choices.")
    ordered = sorted(choices, key=lambda row: (row.get("acquisition_cl", 0), row.get("slot_id", ""), row.get("choice_id", "")))
    routes = [
        row
        for row in ordered
        if row.get("choice_kind") in {"path", "route"}
        or str(row.get("slot_id", "")).lower() in {"path", "route", "primary_route"}
    ]
    if len(routes) != 1:
        fail("DCC_PRIMARY_ROUTE_REQUIRED", "A diversity signature requires exactly one explicit primary Path/route selection.")
    primary_route = require_string(routes[0].get("choice_id"), path="plan.primary_route.choice_id")
    roles = tuple(sorted(whole_plan_semantics.get("role_tags") or ()))
    capabilities = tuple(sorted(whole_plan_semantics.get("capability_families") or ()))
    resource = whole_plan_semantics.get("resource_loop") or {}
    resource_loop = tuple(sorted(set(resource.get("consumes") or ()) | set(resource.get("produces") or ()) | set(resource.get("cadences") or ()) | set(resource.get("setups") or ())))
    schedule = whole_plan_semantics.get("progression", {}).get("acquisition_schedule") or []
    cadence = []
    for row in schedule:
        cl = row.get("cl")
        if isinstance(cl, int):
            cadence.append("early" if cl <= 3 else "mid" if cl <= 8 else "late")
    progression_cadence = tuple(sorted(set(cadence)))
    pairs = [f"{edge['source_choice_id']}->{edge['target_choice_id']}:{edge['relation']}" for edge in whole_plan_semantics.get("synergy_edges") or []]
    tradeoffs = tuple(sorted(row["code"] for row in whole_plan_semantics.get("tradeoffs") or []))
    bands = whole_plan_semantics.get("complexity", {}).get("bands") or ["moderate"]
    complexity_band = sorted(bands, key=lambda band: {"simple": 0, "moderate": 1, "complex": 2}.get(band, 99))[-1]
    return CategoricalSignature(primary_route, roles, capabilities, resource_loop, progression_cadence, tuple(sorted(pairs)), tradeoffs, complexity_band)


def _signature_mapping(value: CategoricalSignature | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, CategoricalSignature):
        return value.to_dict()
    if not isinstance(value, Mapping):
        fail("DCC_SCHEMA_TYPE", "A categorical signature must be an object.")
    missing = sorted(set(SIGNATURE_FIELDS) - set(value))
    unknown = sorted(set(value) - set(SIGNATURE_FIELDS))
    if missing or unknown:
        fail("DCC_SCHEMA_UNKNOWN_FIELD", "A categorical signature must have exact fields.", details={"missing": missing, "unknown": unknown})
    return {field: value[field] for field in SIGNATURE_FIELDS}


def categorical_distance(left: CategoricalSignature | Mapping[str, Any], right: CategoricalSignature | Mapping[str, Any]) -> int:
    a, b = _signature_mapping(left), _signature_mapping(right)
    distance = 0
    for field in SIGNATURE_FIELDS:
        av, bv = _as_set(a[field]), _as_set(b[field])
        union = av | bv
        if not union:
            continue
        # Integer Jaccard distance in [0, 1000], avoiding floating point.
        distance += SIGNATURE_WEIGHTS[field] * ((len(av ^ bv) * 1000) // len(union))
    return distance


def _rank_key(row: RankedPlan, index: int) -> tuple[Any, ...]:
    return (row.rank or index + 1, row.legal_plan_sha256)


def select_diverse_plans(ranked_plans: Sequence[RankedPlan], *, count: int = 4) -> DiversityResult:
    if not ranked_plans:
        fail("DCC_NO_LEGAL_PLANS", "Diversity selection requires ranked plans.")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        fail("DCC_SCHEMA_VALUE", "Diversity count must be a positive integer.")
    original_index = {id(row): index for index, row in enumerate(ranked_plans)}
    ordered = tuple(sorted(ranked_plans, key=lambda row: _rank_key(row, original_index[id(row)])))
    signatures = {row.legal_plan_sha256: signature_for_plan(row.plan, row.semantics) for row in ordered}
    medoids: list[RankedPlan] = [ordered[0]]
    while len(medoids) < min(count, len(ordered)):
        candidates = [row for row in ordered if row not in medoids]
        chosen = max(
            candidates,
            key=lambda row: (
                min(categorical_distance(signatures[row.legal_plan_sha256], signatures[medoid.legal_plan_sha256]) for medoid in medoids),
                -(_rank_key(row, ordered.index(row))[0]),
                row.legal_plan_sha256,
            ),
        )
        medoids.append(chosen)

    member_lists: list[list[RankedPlan]] = [[] for _ in medoids]
    for row in ordered:
        distances = [categorical_distance(signatures[row.legal_plan_sha256], signatures[medoid.legal_plan_sha256]) for medoid in medoids]
        nearest = min(range(len(medoids)), key=lambda index: (distances[index], index, medoids[index].legal_plan_sha256))
        member_lists[nearest].append(row)
    clusters = tuple(
        DiversityCluster(
            medoid_plan_sha256=medoids[index].legal_plan_sha256,
            member_plan_sha256s=tuple(row.legal_plan_sha256 for row in sorted(members, key=lambda row: _rank_key(row, ordered.index(row)))),
            signature=signatures[medoids[index].legal_plan_sha256],
        )
        for index, members in enumerate(member_lists)
    )

    selected: list[RankedPlan] = []
    depth = 0
    while len(selected) < min(count, len(ordered)):
        progressed = False
        for members in member_lists:
            members_sorted = sorted(members, key=lambda row: _rank_key(row, ordered.index(row)))
            if depth < len(members_sorted):
                row = members_sorted[depth]
                if row not in selected:
                    selected.append(row)
                    progressed = True
                    if len(selected) >= min(count, len(ordered)):
                        break
        if not progressed:
            break
        depth += 1
    return DiversityResult(tuple(selected), clusters)


def deterministic_categorical_distance(left: CategoricalSignature | Mapping[str, Any], right: CategoricalSignature | Mapping[str, Any]) -> int:
    return categorical_distance(left, right)
