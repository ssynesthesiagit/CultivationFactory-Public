"""Frozen integer ranking and private evidence receipts.

Only verified whole-plan semantics reach this module.  Numeric scores are
returned in a private receipt and are never required by the public manifest.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core import sha256_json

from .choice_semantics import aggregate_whole_plan_semantics, validate_semantics_set
from .contracts import CreativeControllerError, fail, normalized_text, require_digest, require_type
from .legal_plan_compiler import LegalPlan, validate_legal_plan


RANKING_PROFILE_VERSION = 2
RANKING_WEIGHTS: dict[str, int] = {
    "theme_fit": 20,
    "mechanical_synergy": 20,
    "combat_usability": 20,
    "progression_continuity": 15,
    "redundancy_avoidance": 10,
    "tradeoff_fit": 10,
    "complexity_fit": 5,
}
DIMENSIONS = tuple(RANKING_WEIGHTS)
COMPLEXITY_VALUES = {"simple": 0, "moderate": 1, "complex": 2}
SEVERITY_VALUES = {"light": 1, "moderate": 2, "heavy": 3}


def _ranking_profile_payload() -> dict[str, Any]:
    return {
        "version": RANKING_PROFILE_VERSION,
        "weights": dict(RANKING_WEIGHTS),
        "complexity_values": dict(COMPLEXITY_VALUES),
        "severity_values": dict(SEVERITY_VALUES),
        "aggregation": "dcc.choice-semantics.v1-exact-token-aggregation",
    }


RANKING_PROFILE_SHA256 = sha256_json(_ranking_profile_payload())


@dataclass(frozen=True)
class ScoreVector:
    theme_fit: int
    mechanical_synergy: int
    combat_usability: int
    progression_continuity: int
    redundancy_avoidance: int
    tradeoff_fit: int
    complexity_fit: int

    def __post_init__(self) -> None:
        for dimension in DIMENSIONS:
            value = getattr(self, dimension)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
                fail("DCC_RANKING_SCORE_INVALID", f"{dimension} must be an integer in [0,1000].")

    def to_dict(self) -> dict[str, int]:
        return {dimension: getattr(self, dimension) for dimension in DIMENSIONS}

    @property
    def weighted_total(self) -> int:
        return sum(RANKING_WEIGHTS[dimension] * getattr(self, dimension) for dimension in DIMENSIONS)


@dataclass(frozen=True)
class RankedPlan:
    plan: LegalPlan
    semantics: dict[str, Any]
    scores: ScoreVector
    source_fact_ids: tuple[str, ...]
    complexity_distance: int
    rank: int = 0
    option_id: str | None = None

    @property
    def legal_plan_sha256(self) -> str:
        return self.plan.legal_plan_sha256

    @property
    def weighted_total(self) -> int:
        return self.scores.weighted_total

    def private_dict(self) -> dict[str, Any]:
        return {
            "legal_plan_sha256": self.legal_plan_sha256,
            "scores": self.scores.to_dict(),
            "weighted_total": self.weighted_total,
            "source_fact_ids": list(self.source_fact_ids),
            "complexity_distance": self.complexity_distance,
            "rank": self.rank,
            "option_id": self.option_id,
        }


@dataclass(frozen=True)
class RankingResult:
    ranked_plans: tuple[RankedPlan, ...]
    private_receipt: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "private_receipt", deepcopy(self.private_receipt))

    @property
    def legal_plan_set_sha256(self) -> str:
        return self.private_receipt["binding"]["legal_plan_set_sha256"]

    @property
    def choice_semantics_set_sha256(self) -> str:
        return self.private_receipt["binding"]["choice_semantics_set_sha256"]


def _creative(intent: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(intent, Mapping):
        fail("DCC_SCHEMA_TYPE", "Ranking intent must be an object.")
    creative = intent.get("creative", intent)
    if not isinstance(creative, Mapping):
        fail("DCC_SCHEMA_TYPE", "Ranking intent creative projection must be an object.")
    return creative


def _tokens(creative: Mapping[str, Any], field: str) -> set[str]:
    value = creative.get(field, ())
    if not isinstance(value, (list, tuple)):
        fail("DCC_SCHEMA_TYPE", f"creative.{field} must be an array.")
    return {normalized_text(item) for item in value if isinstance(item, str)}


def _semantic_tokens(semantics: Mapping[str, Any]) -> set[str]:
    return {
        normalized_text(item)
        for field in ("theme_tags", "role_tags", "capability_families", "combat_functions")
        for item in semantics[field]
    }


def controlled_preferences_sha256(intent: Mapping[str, Any]) -> str:
    controlled = intent.get("controlled_preferences", {}) if isinstance(intent, Mapping) else {}
    if not isinstance(controlled, Mapping):
        fail("DCC_SCHEMA_TYPE", "intent.controlled_preferences must be an object.")
    return sha256_json(controlled)


def _predicate_matches(aggregate: Mapping[str, Any], predicate: Mapping[str, Any]) -> bool:
    kind = predicate.get("kind")
    value = normalized_text(predicate.get("value")) if isinstance(predicate.get("value"), str) else None
    if value is None:
        fail("DCC_SCHEMA_TYPE", "A controlled preference value must be a string.")
    if kind == "role_tag":
        candidates = aggregate.get("role_tags", ())
    elif kind == "theme_tag":
        candidates = aggregate.get("theme_tags", ())
    elif kind == "capability_family":
        candidates = aggregate.get("capability_families", ())
    elif kind == "tradeoff_code":
        candidates = [row.get("code") for row in aggregate.get("tradeoffs", ()) if isinstance(row, Mapping)]
    elif kind == "complexity_band":
        candidates = (aggregate.get("complexity") or {}).get("bands", ())
    else:
        fail("DCC_CONTROLLED_PREDICATE_KIND", "Unsupported controlled preference predicate kind.")
    return value in {normalized_text(item) for item in candidates if isinstance(item, str)}


def evaluate_controlled_preferences(aggregate: Mapping[str, Any], intent: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate typed hard and soft predicates against verified semantics."""

    controlled = intent.get("controlled_preferences", {})
    if not isinstance(controlled, Mapping):
        fail("DCC_SCHEMA_TYPE", "intent.controlled_preferences must be an object.")
    fields = ("must_include", "must_exclude", "soft_prefer", "soft_avoid")
    evaluated: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        rows = controlled.get(field, ())
        if not isinstance(rows, (list, tuple)):
            fail("DCC_SCHEMA_TYPE", f"intent.controlled_preferences.{field} must be an array.")
        evaluated[field] = [
            {"kind": row.get("kind"), "value": row.get("value"), "matched": _predicate_matches(aggregate, row)}
            for row in rows
            if isinstance(row, Mapping)
        ]
        if len(evaluated[field]) != len(rows):
            fail("DCC_SCHEMA_TYPE", f"intent.controlled_preferences.{field} must contain predicate objects.")
    hard_passed = all(row["matched"] for row in evaluated["must_include"]) and not any(row["matched"] for row in evaluated["must_exclude"])
    return {
        "hard_passed": hard_passed,
        "must_include": evaluated["must_include"],
        "must_exclude": evaluated["must_exclude"],
        "soft_prefer": evaluated["soft_prefer"],
        "soft_avoid": evaluated["soft_avoid"],
    }


def plan_satisfies_controlled_preferences(plan: LegalPlan | Mapping[str, Any], intent: Mapping[str, Any], semantics_by_choice: Mapping[str, Any]) -> bool:
    aggregate = _plan_semantics(plan, semantics_by_choice, None)
    return evaluate_controlled_preferences(aggregate, intent)["hard_passed"] is True


def _bounded(value: int) -> int:
    return max(0, min(1000, value))


def _ratio(numerator: int, denominator: int, *, neutral: int = 500) -> int:
    if denominator <= 0:
        return neutral
    return _bounded((numerator * 1000) // denominator)


def _plan_semantics(
    plan: LegalPlan | Mapping[str, Any],
    semantics_by_choice: Mapping[str, Any],
    acquisition_schedule: Mapping[str, int] | Sequence[Mapping[str, Any]] | None,
    baseline_choice_ids: Sequence[str] = (),
) -> dict[str, Any]:
    valid = validate_legal_plan(plan)
    choice_ids = list(baseline_choice_ids) + list(valid.choice_ids)
    if len(choice_ids) != len(set(choice_ids)):
        fail("DCC_ACCEPTED_BASELINE_CONFLICT", "A compiled choice duplicates an accepted baseline choice.")
    return aggregate_whole_plan_semantics(choice_ids, semantics_by_choice, acquisition_schedule=acquisition_schedule)


def score_plan(
    plan: LegalPlan | Mapping[str, Any],
    intent: Mapping[str, Any],
    semantics_by_choice: Mapping[str, Any],
    *,
    acquisition_schedule: Mapping[str, int] | Sequence[Mapping[str, Any]] | None = None,
    baseline_choice_ids: Sequence[str] = (),
) -> tuple[ScoreVector, dict[str, Any], tuple[str, ...], int]:
    """Score one plan from exact semantic tokens and return private evidence."""

    aggregate = _plan_semantics(plan, semantics_by_choice, acquisition_schedule, baseline_choice_ids)
    creative = _creative(intent)
    controlled_evidence = evaluate_controlled_preferences(aggregate, intent)
    if controlled_evidence["hard_passed"] is not True:
        fail("DCC_CONTROLLED_PREFERENCES_UNSATISFIED", "A ranked plan violates an active hard controlled preference.")
    semantic_tokens = _semantic_tokens(aggregate)
    requested_tokens = set()
    for field in ("theme_terms", "desired_roles", "desired_synergies", "priority_order"):
        requested_tokens.update(_tokens(creative, field))
    theme_hits = len(requested_tokens & semantic_tokens)
    theme_fit = _ratio(theme_hits, len(requested_tokens), neutral=500)
    preferred_matches = sum(1 for row in controlled_evidence["soft_prefer"] if row["matched"])
    avoided_matches = sum(1 for row in controlled_evidence["soft_avoid"] if row["matched"])
    theme_fit = _bounded(theme_fit + preferred_matches * 100 - avoided_matches * 150)

    explicit_synergies = aggregate["synergy_edges"]
    resource_matches = aggregate["resource_loop"]["exact_producer_consumer_matches"]
    mechanical_synergy = _bounded(min(1000, len(explicit_synergies) * 250 + len(resource_matches) * 150 + len(aggregate["capability_families"]) * 70))
    if not explicit_synergies and not resource_matches:
        mechanical_synergy = _bounded(len(aggregate["capability_families"]) * 100)

    functions = set(aggregate["combat_functions"])
    capabilities = set(aggregate["capability_families"])
    combat_usability = _bounded(len(functions) * 180 + len(functions & {"defense", "control", "offense", "support"}) * 100 + len(capabilities & {"action_economy", "range_diversity", "reliability", "durability"}) * 80)

    progression = aggregate["progression"]
    schedule = progression["acquisition_schedule"]
    identity_cl = progression["identity_online_cl"]
    signature_cl = progression["signature_cl"]
    early = any(row["cl"] <= 3 for row in schedule)
    mid = any(4 <= row["cl"] <= 8 for row in schedule)
    late = any(row["cl"] >= 9 for row in schedule)
    progression_continuity = (250 if early else 0) + (250 if mid else 0) + (200 if late else 0)
    progression_continuity += 150 if identity_cl <= 3 else 50 if identity_cl <= 5 else 0
    progression_continuity += 150 if signature_cl <= 8 else 50 if signature_cl <= 12 else 0
    progression_continuity = _bounded(progression_continuity)

    redundancy_counts = aggregate["redundancy_counts"]
    repeated = sum(max(0, count - 1) for count in redundancy_counts.values())
    qualifying_synergy = len(explicit_synergies)
    redundancy_avoidance = _bounded(1000 - repeated * 180 + qualifying_synergy * 70)

    wanted_tradeoffs = set()
    for field in ("acceptable_tradeoffs", "avoidances"):
        wanted_tradeoffs.update(_tokens(creative, field))
    actual_tradeoffs = {normalized_text(row["code"]): row for row in aggregate["tradeoffs"]}
    tradeoff_hits = len(wanted_tradeoffs & set(actual_tradeoffs))
    tradeoff_fit = _ratio(tradeoff_hits, len(wanted_tradeoffs), neutral=650)
    if _tokens(creative, "avoidances") & set(actual_tradeoffs):
        tradeoff_fit = _bounded(tradeoff_fit - 250)

    preference = creative.get("complexity_preference", "moderate")
    if not isinstance(preference, str):
        fail("DCC_SCHEMA_TYPE", "creative.complexity_preference must be a string.")
    preference_key = normalized_text(preference)
    if preference_key not in COMPLEXITY_VALUES:
        preference_key = "moderate"
    complexity_distance = min(abs(COMPLEXITY_VALUES[preference_key] - COMPLEXITY_VALUES[band]) for band in aggregate["complexity"]["bands"])
    complexity_fit = _bounded(1000 - complexity_distance * 450 - max(0, aggregate["complexity"]["factor_count"] - 2) * 50)

    vector = ScoreVector(theme_fit, mechanical_synergy, combat_usability, progression_continuity, redundancy_avoidance, tradeoff_fit, complexity_fit)
    source_facts = tuple(sorted(set(aggregate["source_fact_ids"])))
    return vector, aggregate, source_facts, complexity_distance


def _tie_key(row: RankedPlan) -> tuple[Any, ...]:
    return (
        -row.weighted_total,
        tuple(-getattr(row.scores, dimension) for dimension in DIMENSIONS),
        row.complexity_distance,
        row.legal_plan_sha256,
        row.option_id or "",
    )


def qualitative_fit_summary(row: RankedPlan, *, ranking_receipt_sha256: str) -> dict[str, Any]:
    scores = row.scores
    strengths = [
        dimension
        for dimension in DIMENSIONS
        if getattr(scores, dimension) >= 700
    ]
    cautions = [
        dimension
        for dimension in DIMENSIONS
        if getattr(scores, dimension) < 450
    ]
    if row.weighted_total >= 80000:
        overall = "strong"
    elif row.weighted_total >= 60000:
        overall = "good"
    elif row.weighted_total >= 40000:
        overall = "mixed"
    else:
        overall = "narrow"
    return {
        "overall": overall,
        "strengths": strengths,
        "cautions": cautions,
        "ranking_receipt_sha256": ranking_receipt_sha256,
    }


def rank_plans(
    plans: Sequence[LegalPlan | Mapping[str, Any]],
    intent: Mapping[str, Any],
    semantics_by_choice: Mapping[str, Any],
    *,
    acquisition_schedules: Mapping[str, Mapping[str, int] | Sequence[Mapping[str, Any]]] | None = None,
    option_ids_by_plan: Mapping[str, str] | None = None,
    vocabulary_authority: Mapping[str, Any] | None = None,
    baseline_choice_ids: Sequence[str] = (),
) -> RankingResult:
    if not plans:
        fail("DCC_NO_LEGAL_PLANS", "Ranking requires at least one legal plan.")
    valid_plans = tuple(validate_legal_plan(plan) for plan in plans)
    compiler_bindings = {plan.proof["compiler_binding"]["compiler_binding_sha256"] for plan in valid_plans}
    if len(compiler_bindings) != 1:
        fail("DCC_PLAN_COMPILER_BINDING", "All ranked plans must come from one deterministic compiler binding.")
    semantics = validate_semantics_set(semantics_by_choice, vocabulary_authority=vocabulary_authority)
    plan_hashes = [plan.legal_plan_sha256 for plan in valid_plans]
    legal_plan_set_sha256 = sha256_json(sorted(plan_hashes))
    semantic_ids = sorted(semantics)
    choice_semantics_set_sha256 = sha256_json([semantics[choice_id].value["semantics_sha256"] for choice_id in semantic_ids])
    vocabulary_hashes = {row.value["vocabulary_authority_sha256"] for row in semantics.values()}
    if len(vocabulary_hashes) != 1:
        fail("DCC_VOCABULARY_AUTHORITY_BINDING", "All semantics in a ranking run must use one vocabulary authority.")
    eligible_plans: list[LegalPlan] = []
    hard_rejections: list[str] = []
    for plan in valid_plans:
        aggregate = _plan_semantics(plan, semantics, (acquisition_schedules or {}).get(plan.legal_plan_sha256), baseline_choice_ids)
        if evaluate_controlled_preferences(aggregate, intent)["hard_passed"] is True:
            eligible_plans.append(plan)
        else:
            hard_rejections.append(plan.legal_plan_sha256)
    if not eligible_plans:
        fail("DCC_NO_LEGAL_PLANS", "No Factory-validated plan satisfies the active hard controlled preferences.")
    ranked: list[RankedPlan] = []
    for plan in eligible_plans:
        schedule = (acquisition_schedules or {}).get(plan.legal_plan_sha256)
        scores, aggregate, source_facts, complexity_distance = score_plan(plan, intent, semantics, acquisition_schedule=schedule, baseline_choice_ids=baseline_choice_ids)
        option_id = (option_ids_by_plan or {}).get(plan.legal_plan_sha256)
        ranked.append(RankedPlan(plan, aggregate, scores, source_facts, complexity_distance, option_id=option_id))
    ranked.sort(key=_tie_key)
    ranked = [RankedPlan(row.plan, row.semantics, row.scores, row.source_fact_ids, row.complexity_distance, index + 1, row.option_id) for index, row in enumerate(ranked)]
    receipt_unsigned = {
        "schema": "TianxiaFoundry.PrivateRankingReceipt.v1",
        "visibility": "FACTORY_INTERNAL",
        "ranking_profile": {"version": RANKING_PROFILE_VERSION, "weights": dict(RANKING_WEIGHTS), "ranking_profile_sha256": RANKING_PROFILE_SHA256},
        "binding": {"legal_plan_set_sha256": legal_plan_set_sha256, "intent_sha256": intent.get("intent_sha256") if isinstance(intent, Mapping) else None, "choice_semantics_set_sha256": choice_semantics_set_sha256, "vocabulary_authority_sha256": next(iter(vocabulary_hashes))},
        "semantic_gate": {"passed": True, "verified_choice_count": len(semantic_ids), "semantics_receipt_sha256": sha256_json(sorted(semantic_ids))},
        "controlled_preference_gate": {"passed": True, "controlled_preferences_sha256": controlled_preferences_sha256(intent), "rejected_plan_sha256s": sorted(hard_rejections)},
        "candidate_scores": [row.private_dict() for row in ranked],
    }
    receipt = {**receipt_unsigned, "ranking_receipt_sha256": sha256_json(receipt_unsigned)}
    return RankingResult(tuple(ranked), receipt)


def verify_private_ranking_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("visibility") != "FACTORY_INTERNAL":
        fail("DCC_RANKING_VISIBILITY", "Ranking receipts are private evidence only.")
    actual = receipt.get("ranking_receipt_sha256")
    if actual != sha256_json({key: value for key, value in receipt.items() if key != "ranking_receipt_sha256"}):
        fail("DCC_RANKING_RECEIPT_HASH_INVALID", "Ranking receipt self-hash mismatch.")
