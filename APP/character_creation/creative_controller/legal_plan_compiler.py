"""Bounded, typed legal-plan compilation for the Stage A shadow layer.

The compiler explores a deterministic best-first frontier, prunes impossible
partial assignments, and retains only a bounded number of Factory-validated
plans.  It never reads free prose and it never calls a provider or a solver.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import heapq
from itertools import combinations
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.core import sha256_json

from .contracts import CreativeControllerError, fail, require_digest, require_exact_keys, require_list, require_string, require_type, validate_self_hash


SEARCH_AUTO = "AUTO"
SEARCH_EXHAUSTIVE = "EXHAUSTIVE"
SEARCH_SEEDED_ROLLOUT = "SEEDED_ROLLOUT"
SEARCH_STRATEGIES = (SEARCH_AUTO, SEARCH_EXHAUSTIVE, SEARCH_SEEDED_ROLLOUT)
DEFAULT_SKELETON_CHOICE_KINDS = frozenset({"path", "route", "method", "foundation"})
DEFAULT_SKELETON_LIMIT = 64
DEFAULT_BACKTRACK_LIMIT = 64
AFFINITY_POLICY_VERSION = "greedy-positive-affinity-v1"
AFFINITY_POLICY_SCHEMA = "TianxiaFoundry.DeterministicSeedAffinityPolicy.v1"

PLAN_SCHEMA = "TianxiaFoundry.LegalPlan.v1"
PROOF_SCHEMA = "TianxiaFoundry.LegalPlanProof.v1"
VALIDATOR_RECEIPT_SCHEMA = "TianxiaFoundry.FinalFactoryValidatorReceipt.v1"
COMPILER_BINDING_SCHEMA = "TianxiaFoundry.LegalPlanCompilerBinding.v1"
_COMPILER_ATTESTATION = object()
_PROOF_CHECKS = {"prerequisites", "incompatibilities", "cardinality", "acquisition_order_and_cl", "uniqueness", "controlled_preferences", "final_factory_validator"}


def _strings(value: Any, *, path: str) -> tuple[str, ...]:
    rows = require_list(value, path=path)
    result = tuple(require_string(item, path=f"{path}[{index}]") for index, item in enumerate(rows))
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must be duplicate-free.")
    return tuple(sorted(result))


@dataclass(frozen=True)
class TypedChoiceOption:
    choice_id: str
    choice_kind: str = "action"
    acquisition_cl: int = 1
    prerequisites: tuple[str, ...] = ()
    incompatibilities: tuple[str, ...] = ()
    grants: tuple[str, ...] = ()
    cardinality_group: str | None = None
    unique_key: str | None = None

    def __post_init__(self) -> None:
        require_string(self.choice_id, path="choice option.choice_id")
        require_string(self.choice_kind, path="choice option.choice_kind")
        if not isinstance(self.acquisition_cl, int) or isinstance(self.acquisition_cl, bool) or self.acquisition_cl < 1:
            fail("DCC_SCHEMA_VALUE", "choice option.acquisition_cl must be a positive integer.")
        for field in ("prerequisites", "incompatibilities", "grants"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                fail("DCC_SCHEMA_DUPLICATE", f"choice option.{field} must be duplicate-free.")
            if any(not isinstance(item, str) or not item for item in values):
                fail("DCC_SCHEMA_TYPE", f"choice option.{field} must contain non-empty strings.")
            object.__setattr__(self, field, tuple(sorted(values)))
        if self.cardinality_group is not None:
            require_string(self.cardinality_group, path="choice option.cardinality_group")
        if self.unique_key is not None:
            require_string(self.unique_key, path="choice option.unique_key")
        else:
            object.__setattr__(self, "unique_key", self.choice_id)

    @property
    def option_id(self) -> str:
        return self.choice_id

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, default_choice_kind: str = "action", default_acquisition_cl: int = 1) -> "TypedChoiceOption":
        require_exact_keys(value, {"choice_id"}, {"choice_kind", "acquisition_cl", "prerequisites", "incompatibilities", "grants", "cardinality_group", "unique_key", "option_id"}, path="choice option")
        if "choice_id" in value and "option_id" in value and value["choice_id"] != value["option_id"]:
            fail("DCC_SCHEMA_VALUE", "choice_id and option_id cannot disagree.")
        choice_id = value.get("choice_id", value.get("option_id"))
        if choice_id is None:
            fail("DCC_SCHEMA_MISSING_FIELD", "choice option requires choice_id.")
        return cls(
            choice_id=choice_id,
            choice_kind=value.get("choice_kind", default_choice_kind),
            acquisition_cl=value.get("acquisition_cl", default_acquisition_cl),
            prerequisites=_strings(value.get("prerequisites", []), path="choice option.prerequisites"),
            incompatibilities=_strings(value.get("incompatibilities", []), path="choice option.incompatibilities"),
            grants=_strings(value.get("grants", []), path="choice option.grants"),
            cardinality_group=value.get("cardinality_group"),
            unique_key=value.get("unique_key"),
        )

    def to_dict(self, *, slot_id: str) -> dict[str, Any]:
        return {
            "slot_id": slot_id,
            "choice_id": self.choice_id,
            "choice_kind": self.choice_kind,
            "acquisition_cl": self.acquisition_cl,
        }


@dataclass(frozen=True)
class TypedChoiceSlot:
    slot_id: str
    options: tuple[TypedChoiceOption, ...]
    choice_kind: str = "action"
    acquisition_cl: int = 1
    min_choices: int = 1
    max_choices: int = 1
    cardinality_group: str | None = None
    cardinality_limit: int | None = None

    def __post_init__(self) -> None:
        require_string(self.slot_id, path="choice slot.slot_id")
        require_string(self.choice_kind, path="choice slot.choice_kind")
        for field in ("acquisition_cl", "min_choices", "max_choices"):
            number = getattr(self, field)
            if not isinstance(number, int) or isinstance(number, bool):
                fail("DCC_SCHEMA_TYPE", f"choice slot.{field} must be an integer.")
        if self.acquisition_cl < 1 or self.min_choices < 0 or self.max_choices < self.min_choices:
            fail("DCC_SCHEMA_VALUE", "choice slot cardinality or acquisition CL is invalid.")
        if self.cardinality_group is not None:
            require_string(self.cardinality_group, path="choice slot.cardinality_group")
        if self.cardinality_limit is not None:
            if not isinstance(self.cardinality_limit, int) or isinstance(self.cardinality_limit, bool) or self.cardinality_limit < 1:
                fail("DCC_SCHEMA_VALUE", "choice slot.cardinality_limit must be a positive integer.")
        option_ids = [option.choice_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            fail("DCC_SCHEMA_DUPLICATE_CHOICE_ID", "A slot cannot publish the same choice twice.")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TypedChoiceSlot":
        require_exact_keys(value, {"slot_id", "options"}, {"choice_kind", "acquisition_cl", "min_choices", "max_choices", "cardinality_group", "cardinality_limit"}, path="choice slot")
        slot_id = require_string(value["slot_id"], path="choice slot.slot_id")
        choice_kind = value.get("choice_kind", "action")
        acquisition_cl = value.get("acquisition_cl", 1)
        raw_options = require_list(value["options"], path=f"choice slot[{slot_id}].options")
        options = tuple(TypedChoiceOption.from_mapping(row, default_choice_kind=choice_kind, default_acquisition_cl=acquisition_cl) for row in raw_options)
        return cls(
            slot_id=slot_id,
            options=options,
            choice_kind=choice_kind,
            acquisition_cl=acquisition_cl,
            min_choices=value.get("min_choices", 1),
            max_choices=value.get("max_choices", 1),
            cardinality_group=value.get("cardinality_group"),
            cardinality_limit=value.get("cardinality_limit"),
        )


def _coerce_slot(value: TypedChoiceSlot | Mapping[str, Any]) -> TypedChoiceSlot:
    return value if isinstance(value, TypedChoiceSlot) else TypedChoiceSlot.from_mapping(value)


def _slot_authority_sha256(slots: Sequence[TypedChoiceSlot], target_cl: int, accepted_choices: Mapping[str, int], owner_locks: Mapping[str, Sequence[str]], cardinality_limits: Mapping[str, int]) -> str:
    payload = {
        "target_cl": target_cl,
        "slots": [{
            "slot_id": slot.slot_id,
            "choice_kind": slot.choice_kind,
            "acquisition_cl": slot.acquisition_cl,
            "min_choices": slot.min_choices,
            "max_choices": slot.max_choices,
            "cardinality_group": slot.cardinality_group,
            "cardinality_limit": slot.cardinality_limit,
            "options": [{
                "choice_id": option.choice_id,
                "choice_kind": option.choice_kind,
                "acquisition_cl": option.acquisition_cl,
                "prerequisites": list(option.prerequisites),
                "incompatibilities": list(option.incompatibilities),
                "grants": list(option.grants),
                "cardinality_group": option.cardinality_group,
                "unique_key": option.unique_key,
            } for option in slot.options],
        } for slot in slots],
        "accepted_choices": [
            {"choice_id": choice_id, "acquisition_cl": accepted_choices[choice_id]}
            for choice_id in sorted(accepted_choices)
        ],
        "owner_locks": {key: sorted(value) for key, value in sorted(owner_locks.items())},
        "cardinality_limits": dict(sorted(cardinality_limits.items())),
    }
    return sha256_json(payload)


def _affinity_policy_sha256(version: str) -> str:
    """Commit the rollout ordering policy without attempting to hash code."""

    return sha256_json({
        "schema": AFFINITY_POLICY_SCHEMA,
        "version": version,
        "ordering": "descending_affinity_then_choice_id",
        "selection": "greedy_positive_affinity",
    })


@dataclass(frozen=True)
class LegalPlan:
    plan_payload: dict[str, Any]
    legal_plan_sha256: str
    proof: dict[str, Any]
    _attestation: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_payload", deepcopy(self.plan_payload))
        object.__setattr__(self, "proof", deepcopy(self.proof))
        if self._attestation is not _COMPILER_ATTESTATION:
            fail("DCC_PLAN_TRUST_REQUIRED", "LegalPlan instances must be issued by the deterministic compiler.")
        _validate_plan_payload(self.plan_payload)
        expected = sha256_json(self.plan_payload)
        if expected != self.legal_plan_sha256:
            fail("DCC_PLAN_HASH_INVALID", "LegalPlan hash does not match its canonical payload.")
        _validate_plan_proof(self.proof, self.legal_plan_sha256)

    @property
    def choice_ids(self) -> tuple[str, ...]:
        return tuple(row["choice_id"] for row in self.plan_payload["choices"])

    @property
    def choices(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(row) for row in self.plan_payload["choices"])

    def detached_copy(self) -> "LegalPlan":
        return LegalPlan(deepcopy(self.plan_payload), self.legal_plan_sha256, deepcopy(self.proof), _COMPILER_ATTESTATION)


@dataclass(frozen=True)
class CompilationResult:
    plans: tuple[LegalPlan, ...]
    validator_rejections: tuple[str, ...] = ()
    predicate_rejections: tuple[str, ...] = ()
    explored_assignments: int = 0
    explored_states: int = 0
    pruned_states: int = 0
    search_strategy: str = SEARCH_EXHAUSTIVE
    skeleton_enumerated: bool = True
    rollouts_attempted: int = 0
    rollouts_abandoned: int = 0
    space_complete: bool = True
    frontier_limit: int = 12

    @property
    def legal_plan_set_sha256(self) -> str:
        return sha256_json([plan.legal_plan_sha256 for plan in self.plans])


FinalValidator = Callable[[Mapping[str, Any]], Any]
PlanPredicate = Callable[[Mapping[str, Any]], bool]
BranchPriority = Callable[[Mapping[str, Any]], int]
SeedAffinity = Callable[[Mapping[str, Any], Mapping[str, Any]], int]


def _validator_outcome(result: Any, plan_hash: str) -> tuple[bool, dict[str, Any]]:
    if isinstance(result, bool):
        accepted = result
        receipt = {"accepted": accepted, "legal_plan_sha256": plan_hash}
    elif isinstance(result, tuple) and len(result) == 2:
        accepted = result[0] is True
        receipt = result[1]
    elif isinstance(result, Mapping):
        accepted = result.get("accepted") is True or result.get("valid") is True
        receipt = result
    else:
        fail("DCC_FINAL_VALIDATOR_RESULT", "The final validator must return bool, (bool, receipt), or an outcome object.")
    if not isinstance(accepted, bool):
        fail("DCC_FINAL_VALIDATOR_RESULT", "The final validator outcome must be boolean.")
    if isinstance(receipt, str):
        fail("DCC_FINAL_VALIDATOR_RESULT", "A final validator must return a receipt object, not an identity-only digest.")
    receipt_unsigned = {
        "schema": VALIDATOR_RECEIPT_SCHEMA,
        "legal_plan_sha256": plan_hash,
        "accepted": accepted,
        "validator_output_sha256": sha256_json(result),
    }
    return accepted, {**receipt_unsigned, "receipt_sha256": sha256_json(receipt_unsigned)}


def _validate_plan_proof(proof: Mapping[str, Any], plan_hash: str) -> None:
    require_exact_keys(proof, {"schema", "legal_plan_sha256", "checks", "final_validator_receipt", "compiler_binding", "proof_sha256"}, path="legal plan proof")
    if proof["schema"] != PROOF_SCHEMA or proof["legal_plan_sha256"] != plan_hash:
        fail("DCC_PLAN_PROOF_INVALID", "LegalPlan proof is not bound to the plan.")
    checks = proof["checks"]
    require_exact_keys(checks, _PROOF_CHECKS, path="legal plan proof.checks")
    if any(value is not True for value in checks.values()):
        fail("DCC_PLAN_PROOF_INVALID", "Every deterministic legal-plan check must pass.")
    receipt = proof["final_validator_receipt"]
    require_exact_keys(receipt, {"schema", "legal_plan_sha256", "accepted", "validator_output_sha256", "receipt_sha256"}, path="legal plan proof.final_validator_receipt")
    if receipt["schema"] != VALIDATOR_RECEIPT_SCHEMA or receipt["legal_plan_sha256"] != plan_hash or receipt["accepted"] is not True:
        fail("DCC_PLAN_PROOF_INVALID", "The final-validator receipt is not a trusted accepted receipt.")
    require_digest(receipt["validator_output_sha256"], path="legal plan proof.final_validator_receipt.validator_output_sha256")
    require_digest(receipt["receipt_sha256"], path="legal plan proof.final_validator_receipt.receipt_sha256")
    validate_self_hash(receipt, "receipt_sha256", code="DCC_PLAN_PROOF_INVALID")
    compiler = proof["compiler_binding"]
    require_exact_keys(
        compiler,
        {
            "schema", "plan_payload_sha256", "target_cl", "slot_authority_sha256",
            "controlled_preferences_sha256", "requested_search_strategy", "search_strategy",
            "resolved_search_strategy", "frontier_limit", "search_state_limit",
            "skeleton_choice_kinds", "skeleton_limit", "skeleton_enumerated",
            "backtrack_limit", "diversity_seed_set_sha256", "affinity_policy_version",
            "affinity_policy_sha256", "compiler_binding_sha256",
        },
        path="legal plan proof.compiler_binding",
    )
    if compiler["requested_search_strategy"] not in SEARCH_STRATEGIES:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding must name a requested search strategy.")
    if compiler["resolved_search_strategy"] not in {SEARCH_EXHAUSTIVE, SEARCH_SEEDED_ROLLOUT}:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding must name a resolved search strategy.")
    if compiler["search_strategy"] != compiler["resolved_search_strategy"]:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding search strategy must equal its resolved strategy.")
    if compiler["skeleton_enumerated"] not in {True, False}:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding skeleton flag must be boolean.")
    if compiler["schema"] != COMPILER_BINDING_SCHEMA or compiler["plan_payload_sha256"] != plan_hash:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding is not bound to the legal plan.")
    require_type(compiler["target_cl"], int, path="legal plan proof.compiler_binding.target_cl")
    if compiler["target_cl"] < 1:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding target CL must be positive.")
    require_digest(compiler["slot_authority_sha256"], path="legal plan proof.compiler_binding.slot_authority_sha256")
    require_digest(compiler["controlled_preferences_sha256"], path="legal plan proof.compiler_binding.controlled_preferences_sha256")
    for field in ("frontier_limit", "search_state_limit", "skeleton_limit", "backtrack_limit"):
        require_type(compiler[field], int, path=f"legal plan proof.compiler_binding.{field}")
        if compiler[field] < 1:
            fail("DCC_PLAN_PROOF_INVALID", f"The compiler binding {field} must be positive.")
    if compiler["search_state_limit"] < compiler["frontier_limit"]:
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding search_state_limit must cover frontier_limit.")
    skeleton_kinds = compiler["skeleton_choice_kinds"]
    require_list(skeleton_kinds, path="legal plan proof.compiler_binding.skeleton_choice_kinds")
    if any(not isinstance(kind, str) or not kind for kind in skeleton_kinds) or len(skeleton_kinds) != len(set(skeleton_kinds)):
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding skeleton choice kinds must be unique strings.")
    if skeleton_kinds != sorted(skeleton_kinds):
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding skeleton choice kinds must be canonicalized.")
    require_digest(compiler["diversity_seed_set_sha256"], path="legal plan proof.compiler_binding.diversity_seed_set_sha256")
    require_string(compiler["affinity_policy_version"], path="legal plan proof.compiler_binding.affinity_policy_version")
    require_digest(compiler["affinity_policy_sha256"], path="legal plan proof.compiler_binding.affinity_policy_sha256")
    require_digest(compiler["compiler_binding_sha256"], path="legal plan proof.compiler_binding.compiler_binding_sha256")
    authority_unsigned = {key: value for key, value in compiler.items() if key not in {"plan_payload_sha256", "compiler_binding_sha256"}}
    if compiler["compiler_binding_sha256"] != sha256_json(authority_unsigned):
        fail("DCC_PLAN_PROOF_INVALID", "The compiler binding self-hash is invalid.")
    validate_self_hash(proof, "proof_sha256", code="DCC_PLAN_PROOF_INVALID")


def _validate_plan_payload(payload: Mapping[str, Any]) -> None:
    require_exact_keys(payload, {"schema", "target_cl", "choices"}, path="legal plan")
    if payload["schema"] != PLAN_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported legal plan schema.")
    target_cl = require_type(payload["target_cl"], int, path="legal plan.target_cl")
    if target_cl < 1:
        fail("DCC_SCHEMA_VALUE", "legal plan.target_cl must be positive.")
    choices = require_list(payload["choices"], path="legal plan.choices")
    seen: set[str] = set()
    for index, choice in enumerate(choices):
        require_exact_keys(choice, {"slot_id", "choice_id", "choice_kind", "acquisition_cl"}, path=f"legal plan.choices[{index}]")
        choice_id = require_string(choice["choice_id"], path=f"legal plan.choices[{index}].choice_id")
        if choice_id in seen:
            fail("DCC_PLAN_DUPLICATE_CHOICE", "A legal plan cannot contain duplicate choice IDs.")
        seen.add(choice_id)
        require_string(choice["slot_id"], path=f"legal plan.choices[{index}].slot_id")
        require_string(choice["choice_kind"], path=f"legal plan.choices[{index}].choice_kind")
        acquisition_cl = require_type(choice["acquisition_cl"], int, path=f"legal plan.choices[{index}].acquisition_cl")
        if acquisition_cl < 1 or acquisition_cl > target_cl:
            fail("DCC_PLAN_PROOF_INVALID", "A plan choice is outside the target CL.")


class LegalPlanCompiler:
    """Compile a bounded deterministic frontier in canonical authority order."""

    def __init__(
        self,
        slots: Sequence[TypedChoiceSlot | Mapping[str, Any]],
        *,
        target_cl: int,
        final_validator: FinalValidator | None = None,
        accepted_choices: Iterable[str] = (),
        acquisition_history: Mapping[str, int] | None = None,
        owner_locks: Mapping[str, Sequence[str]] | None = None,
        cardinality_limits: Mapping[str, int] | None = None,
        plan_predicate: PlanPredicate | None = None,
        controlled_preferences_sha256: str | None = None,
        branch_priority: BranchPriority | None = None,
        frontier_limit: int = 12,
        search_state_limit: int = 100_000,
        search_strategy: str = SEARCH_AUTO,
        skeleton_choice_kinds: Iterable[str] = DEFAULT_SKELETON_CHOICE_KINDS,
        skeleton_limit: int = DEFAULT_SKELETON_LIMIT,
        diversity_seeds: Sequence[Mapping[str, Any]] = (),
        seed_affinity: SeedAffinity | None = None,
        affinity_policy_version: str = AFFINITY_POLICY_VERSION,
        backtrack_limit: int = DEFAULT_BACKTRACK_LIMIT,
    ) -> None:
        if not isinstance(target_cl, int) or isinstance(target_cl, bool) or target_cl < 1:
            fail("DCC_SCHEMA_VALUE", "target_cl must be a positive integer.")
        normalized = tuple(_coerce_slot(slot) for slot in slots)
        if len({slot.slot_id for slot in normalized}) != len(normalized):
            fail("DCC_SCHEMA_DUPLICATE", "Typed slots must have unique slot IDs.")
        self.slots = tuple(sorted(normalized, key=lambda slot: (slot.acquisition_cl, slot.slot_id)))
        self.target_cl = target_cl
        if final_validator is None or not callable(final_validator):
            fail("DCC_FINAL_VALIDATOR_REQUIRED", "A real Factory final validator is required; compilation fails closed when it is absent.")
        self.final_validator = final_validator
        accepted_ids = tuple(require_string(choice, path="accepted_choices[]") for choice in accepted_choices)
        if len(accepted_ids) != len(set(accepted_ids)):
            fail("DCC_SCHEMA_DUPLICATE", "accepted_choices must be duplicate-free.")
        history = dict(acquisition_history or {})
        if set(history) - set(accepted_ids):
            fail("DCC_ACQUISITION_HISTORY_INVALID", "Acquisition history may only describe accepted baseline choices.")
        self.accepted_choices: dict[str, int] = {}
        for choice_id in accepted_ids:
            acquisition_cl = history.get(choice_id, 1)
            if not isinstance(acquisition_cl, int) or isinstance(acquisition_cl, bool) or acquisition_cl < 1 or acquisition_cl > target_cl:
                fail("DCC_ACQUISITION_HISTORY_INVALID", "Accepted-choice acquisition CL must be within the target progression.")
            self.accepted_choices[choice_id] = acquisition_cl
        self.owner_locks = {require_string(slot_id, path="owner_locks.slot_id"): frozenset(require_string(choice, path=f"owner_locks.{slot_id}[]") for choice in choices) for slot_id, choices in (owner_locks or {}).items()}
        self.cardinality_limits = {require_string(group, path="cardinality_limits.group"): limit for group, limit in (cardinality_limits or {}).items()}
        for group, limit in self.cardinality_limits.items():
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                fail("DCC_SCHEMA_VALUE", f"cardinality_limits.{group} must be a positive integer.")
        if not isinstance(frontier_limit, int) or isinstance(frontier_limit, bool) or frontier_limit < 1:
            fail("DCC_SCHEMA_VALUE", "frontier_limit must be a positive integer.")
        if not isinstance(search_state_limit, int) or isinstance(search_state_limit, bool) or search_state_limit < frontier_limit:
            fail("DCC_SCHEMA_VALUE", "search_state_limit must be an integer at least as large as frontier_limit.")
        if plan_predicate is not None and not callable(plan_predicate):
            fail("DCC_SCHEMA_TYPE", "plan_predicate must be callable.")
        if branch_priority is not None and not callable(branch_priority):
            fail("DCC_SCHEMA_TYPE", "branch_priority must be callable.")
        empty_preferences_sha256 = sha256_json({})
        if plan_predicate is not None and controlled_preferences_sha256 is None:
            fail("DCC_CONTROLLED_PREFERENCES_BINDING", "A plan predicate requires an exact controlled-preferences commitment.")
        if plan_predicate is None and controlled_preferences_sha256 not in {None, empty_preferences_sha256}:
            fail("DCC_CONTROLLED_PREFERENCES_BINDING", "A controlled-preferences commitment requires an enforcing plan predicate.")
        self.plan_predicate = plan_predicate
        self.controlled_preferences_sha256 = controlled_preferences_sha256 or empty_preferences_sha256
        require_digest(self.controlled_preferences_sha256, path="controlled_preferences_sha256")
        self.branch_priority = branch_priority
        self.frontier_limit = frontier_limit
        self.search_state_limit = search_state_limit
        if search_strategy not in SEARCH_STRATEGIES:
            fail("DCC_SEARCH_STRATEGY_INVALID", "search_strategy must be AUTO, EXHAUSTIVE, or SEEDED_ROLLOUT.")
        self.search_strategy = search_strategy
        self.skeleton_choice_kinds = frozenset(require_string(kind, path="skeleton_choice_kinds[]") for kind in skeleton_choice_kinds)
        for name, value in (("skeleton_limit", skeleton_limit), ("backtrack_limit", backtrack_limit)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                fail("DCC_SCHEMA_VALUE", f"{name} must be a positive integer.")
        self.skeleton_limit = skeleton_limit
        self.backtrack_limit = backtrack_limit
        if seed_affinity is not None and not callable(seed_affinity):
            fail("DCC_SCHEMA_TYPE", "seed_affinity must be callable.")
        self.seed_affinity = seed_affinity
        seeds = tuple(deepcopy(dict(seed)) for seed in diversity_seeds)
        for seed in seeds:
            if not isinstance(seed, Mapping):
                fail("DCC_SCHEMA_TYPE", "Every diversity seed must be an object.")
        if seeds and seed_affinity is None:
            fail("DCC_DIVERSITY_SEED_BINDING", "Diversity seeds require a seed_affinity function.")
        self.diversity_seeds = seeds
        # The neutral seed is an actual rollout input when callers omit a
        # diversity set, so commit the effective ordered seed sequence.
        self._effective_diversity_seeds = seeds or ({},)
        self.diversity_seed_set_sha256 = sha256_json(list(self._effective_diversity_seeds))
        self.affinity_policy_version = require_string(affinity_policy_version, path="affinity_policy_version")
        self.affinity_policy_sha256 = _affinity_policy_sha256(self.affinity_policy_version)
        self.requested_search_strategy = search_strategy
        self._resolved_strategy = SEARCH_EXHAUSTIVE if search_strategy == SEARCH_AUTO else search_strategy
        self._skeleton_enumerated = True
        self._affinity_cache: dict[tuple[int, str, str], int] = {}
        self.slot_authority_sha256 = _slot_authority_sha256(self.slots, self.target_cl, self.accepted_choices, self.owner_locks, self.cardinality_limits)

    def _compiler_authority_unsigned(self) -> dict[str, Any]:
        """Return the complete deterministic authority for one compilation.

        The supplied callbacks are deliberately absent: their behavior is
        represented by the explicit affinity-policy version commitment rather
        than an unstable callable/object hash.
        """

        return {
            "schema": COMPILER_BINDING_SCHEMA,
            "target_cl": self.target_cl,
            "slot_authority_sha256": self.slot_authority_sha256,
            "controlled_preferences_sha256": self.controlled_preferences_sha256,
            "requested_search_strategy": self.requested_search_strategy,
            # Keep the original field as the resolved-strategy compatibility
            # name used by existing proof consumers.
            "search_strategy": self._resolved_strategy,
            "resolved_search_strategy": self._resolved_strategy,
            "frontier_limit": self.frontier_limit,
            "search_state_limit": self.search_state_limit,
            "skeleton_choice_kinds": sorted(self.skeleton_choice_kinds),
            "skeleton_limit": self.skeleton_limit,
            "skeleton_enumerated": self._skeleton_enumerated,
            "backtrack_limit": self.backtrack_limit,
            "diversity_seed_set_sha256": self.diversity_seed_set_sha256,
            "affinity_policy_version": self.affinity_policy_version,
            "affinity_policy_sha256": self.affinity_policy_sha256,
        }

    @property
    def compiler_search_authority(self) -> dict[str, Any]:
        """Expose the resolved authority without any callable identity."""

        return deepcopy(self._compiler_authority_unsigned())

    @property
    def compiler_search_authority_sha256(self) -> str:
        return sha256_json(self._compiler_authority_unsigned())

    def _candidate_options(self, slot: TypedChoiceSlot) -> tuple[TypedChoiceOption, ...]:
        locked = self.owner_locks.get(slot.slot_id)
        rows = [option for option in slot.options if option.acquisition_cl <= self.target_cl and (locked is None or option.choice_id in locked)]
        return tuple(sorted(rows, key=lambda option: (option.acquisition_cl, option.choice_id, option.unique_key or "")))

    @staticmethod
    def _selected_by_id(selected: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]]) -> dict[str, tuple[TypedChoiceSlot, TypedChoiceOption]]:
        return {option.choice_id: (slot, option) for slot, option in selected}

    def _conditions_hold(self, selected: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]]) -> bool:
        by_id = self._selected_by_id(selected)
        if len(by_id) != len(selected):
            return False
        for slot, option in selected:
            for prerequisite in option.prerequisites:
                if prerequisite not in by_id:
                    return False
                prerequisite_cl = by_id[prerequisite][1].acquisition_cl
                if prerequisite_cl > option.acquisition_cl:
                    return False
            if set(option.incompatibilities) & set(by_id):
                return False
            if any(option.choice_id in other.incompatibilities for _, other in selected if other is not option):
                return False
        counts: dict[str, int] = {}
        for slot, option in selected:
            group = option.cardinality_group or slot.cardinality_group
            if group is not None:
                counts[group] = counts.get(group, 0) + 1
            if option.unique_key is not None:
                # A unique key is global even when its display choice ID is
                # represented by more than one typed slot.
                for _, other in selected:
                    if other is not option and other.unique_key == option.unique_key:
                        return False
        for slot in self.slots:
            count = sum(1 for selected_slot, _ in selected if selected_slot.slot_id == slot.slot_id)
            if count < slot.min_choices or count > slot.max_choices:
                return False
        for slot in self.slots:
            group = slot.cardinality_group
            if group is not None and slot.cardinality_limit is not None:
                if counts.get(group, 0) > slot.cardinality_limit:
                    return False
        for group, limit in self.cardinality_limits.items():
            if counts.get(group, 0) > limit:
                return False
        return True

    def _partial_conditions_hold(self, selected: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]], remaining_choice_ids: set[str] | None = None) -> bool:
        by_id = self._selected_by_id(selected)
        if len(by_id) != len(selected):
            return False
        for _, option in selected:
            for prerequisite in option.prerequisites:
                if prerequisite not in by_id and remaining_choice_ids is not None and prerequisite not in remaining_choice_ids:
                    return False
            if set(option.incompatibilities) & set(by_id):
                return False
            if any(option.choice_id in other.incompatibilities for _, other in selected if other is not option):
                return False
        counts: dict[str, int] = {}
        for slot, option in selected:
            group = option.cardinality_group or slot.cardinality_group
            if group is not None:
                counts[group] = counts.get(group, 0) + 1
            if option.unique_key is not None and sum(1 for _, other in selected if other.unique_key == option.unique_key) > 1:
                return False
        for group, limit in self.cardinality_limits.items():
            if counts.get(group, 0) > limit:
                return False
        return True

    def _plan_from_selection(self, selected: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]]) -> LegalPlan:
        choices = [option.to_dict(slot_id=slot.slot_id) for slot, option in sorted(selected, key=lambda row: (row[0].acquisition_cl, row[0].slot_id, row[1].acquisition_cl, row[1].choice_id))]
        payload = {"schema": PLAN_SCHEMA, "target_cl": self.target_cl, "choices": choices}
        plan_hash = sha256_json(payload)
        if self.plan_predicate is not None and self.plan_predicate(deepcopy(payload)) is not True:
            raise _RejectedPredicate(plan_hash)
        validator_result: Any = self.final_validator(deepcopy(payload))
        accepted, validator_receipt = _validator_outcome(validator_result, plan_hash)
        if not accepted:
            raise _RejectedPlan(plan_hash)
        compiler_authority_unsigned = self._compiler_authority_unsigned()
        compiler_binding = {**compiler_authority_unsigned, "plan_payload_sha256": plan_hash, "compiler_binding_sha256": sha256_json(compiler_authority_unsigned)}
        proof_unsigned = {
            "schema": PROOF_SCHEMA,
            "legal_plan_sha256": plan_hash,
            "checks": {
                "prerequisites": True,
                "incompatibilities": True,
                "cardinality": True,
                "acquisition_order_and_cl": True,
                "uniqueness": True,
                "controlled_preferences": True,
                "final_factory_validator": True,
            },
            "final_validator_receipt": validator_receipt,
            "compiler_binding": compiler_binding,
        }
        proof = {**proof_unsigned, "proof_sha256": sha256_json(proof_unsigned)}
        return LegalPlan(payload, plan_hash, proof, _COMPILER_ATTESTATION)

    # ---- shared search setup -------------------------------------------------

    def _baseline_selection(self) -> list[tuple[TypedChoiceSlot, TypedChoiceOption]]:
        """Accepted choices are already authoritative.

        They participate in prerequisite, incompatibility, and uniqueness
        checks but are never re-emitted as a slot selection.
        """

        return [
            (TypedChoiceSlot(f"__accepted__.{choice_id}", (), min_choices=0, max_choices=0), TypedChoiceOption(choice_id, acquisition_cl=self.accepted_choices[choice_id]))
            for choice_id in sorted(self.accepted_choices)
        ]

    @staticmethod
    def _saturating_combination_count(n: int, k: int, *, cap: int) -> int:
        """Return ``C(n,k)`` capped at ``cap + 1`` without huge integers."""

        if k < 0 or k > n:
            return 0
        k = min(k, n - k)
        result = 1
        for index in range(1, k + 1):
            result = (result * (n - k + index)) // index
            if result > cap:
                return cap + 1
        return result

    def _estimate_space(self, candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]], *, cap: int) -> int:
        """Saturating count of exhaustive prefix states; never builds a huge int.

        Exhaustive search charges the root and every enqueued prefix, not just
        complete leaves.  AUTO must account for that same work or it can pick
        EXHAUSTIVE for a leaf-sized space whose prefixes exceed the budget.
        """

        prefix_product = 1
        total = 1  # the root state
        for slot, options in zip(self.slots, candidates_by_slot):
            lower = slot.min_choices
            upper = min(slot.max_choices, len(options))
            if upper < lower:
                return 0
            width = 0
            for count in range(lower, upper + 1):
                width += self._saturating_combination_count(len(options), count, cap=cap)
                if width > cap:
                    width = cap + 1
                    break
            if width > cap or prefix_product > cap // max(width, 1):
                prefix_product = cap + 1
            else:
                prefix_product *= max(width, 1)
            total += prefix_product
            if total > cap:
                return cap + 1
        return total

    @staticmethod
    def _remaining_ids(indexes: Sequence[int], candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]]) -> set[str]:
        remaining: set[str] = set()
        for index in indexes:
            remaining |= {option.choice_id for option in candidates_by_slot[index]}
        return remaining

    def compile(self) -> CompilationResult:
        candidates_by_slot = tuple(self._candidate_options(slot) for slot in self.slots)
        strategy = self.search_strategy
        if strategy == SEARCH_AUTO:
            estimate = self._estimate_space(candidates_by_slot, cap=self.search_state_limit)
            strategy = SEARCH_EXHAUSTIVE if estimate <= self.search_state_limit else SEARCH_SEEDED_ROLLOUT
        self._resolved_strategy = strategy
        self._skeleton_enumerated = True
        if strategy == SEARCH_EXHAUSTIVE:
            return self._compile_exhaustive(candidates_by_slot)
        return self._compile_seeded_rollout(candidates_by_slot)

    # ---- exhaustive strategy -------------------------------------------------

    def _compile_exhaustive(self, candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]]) -> CompilationResult:
        # Preflight the raw prefix space before any prerequisite or
        # incompatibility pruning.  Otherwise a validator/pruning function
        # that rejects every combination could make EXHAUSTIVE scan an
        # unbounded combinatorial wall while the queue budget stays empty.
        estimate = self._estimate_space(candidates_by_slot, cap=self.search_state_limit)
        if estimate > self.search_state_limit:
            fail("DCC_SEARCH_BUDGET_EXHAUSTED", "The deterministic legal-plan search exceeded its raw prefix budget.")
        selected = self._baseline_selection()
        plans: list[LegalPlan] = []
        rejected: list[str] = []
        predicate_rejected: list[str] = []
        explored = 0
        explored_states = 0
        pruned_states = 0
        suffix_choices: list[set[str]] = [set() for _ in range(len(self.slots) + 1)]
        for index in range(len(self.slots) - 1, -1, -1):
            suffix_choices[index] = suffix_choices[index + 1] | {option.choice_id for option in candidates_by_slot[index]}

        def state_priority(index: int, current: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]]) -> tuple[Any, ...]:
            actual = [option.to_dict(slot_id=slot.slot_id) for slot, option in current if not slot.slot_id.startswith("__accepted__.")]
            payload = {"schema": PLAN_SCHEMA, "target_cl": self.target_cl, "choices": actual}
            score = self.branch_priority(deepcopy(payload)) if self.branch_priority is not None else 0
            if not isinstance(score, int) or isinstance(score, bool):
                fail("DCC_BRANCH_PRIORITY_INVALID", "branch_priority must return an integer.")
            # Deeper states win ties so the frontier drives toward complete
            # plans instead of expanding every shallow prefix first.
            return (-score, -index, tuple(row["choice_id"] for row in actual))

        frontier: list[tuple[tuple[Any, ...], int, tuple[tuple[TypedChoiceSlot, TypedChoiceOption], ...]]] = []
        heapq.heappush(frontier, (state_priority(0, selected), 0, tuple(selected)))
        while frontier and len(plans) < self.frontier_limit:
            if explored_states >= self.search_state_limit:
                fail("DCC_SEARCH_BUDGET_EXHAUSTED", "The deterministic legal-plan search exceeded its state budget.")
            _, index, current = heapq.heappop(frontier)
            explored_states += 1
            if index >= len(self.slots):
                actual = [row for row in current if not row[0].slot_id.startswith("__accepted__.")]
                if not self._conditions_hold(current):
                    pruned_states += 1
                    continue
                explored += 1
                try:
                    plans.append(self._plan_from_selection(actual))
                except _RejectedPredicate as rejected_predicate:
                    predicate_rejected.append(rejected_predicate.plan_hash)
                except _RejectedPlan as rejected_plan:
                    rejected.append(rejected_plan.plan_hash)
                continue
            slot = self.slots[index]
            options = candidates_by_slot[index]
            lower = slot.min_choices
            upper = min(slot.max_choices, len(options))
            if upper < lower:
                pruned_states += 1
                continue
            for count in range(lower, upper + 1):
                for chosen in combinations(options, count):
                    next_current = current + tuple((slot, option) for option in chosen)
                    if self._partial_conditions_hold(next_current, suffix_choices[index + 1]):
                        if explored_states + len(frontier) >= self.search_state_limit:
                            fail("DCC_SEARCH_BUDGET_EXHAUSTED", "The deterministic legal-plan frontier exceeded its state budget before enqueue.")
                        heapq.heappush(frontier, (state_priority(index + 1, next_current), index + 1, next_current))
                    else:
                        pruned_states += 1
        return self._result(
            plans,
            rejected,
            predicate_rejected,
            explored_assignments=explored,
            explored_states=explored_states,
            pruned_states=pruned_states,
            space_complete=not frontier,
        )

    # ---- seeded rollout strategy ---------------------------------------------

    def _affinity(self, seed_index: int, seed: Mapping[str, Any], slot: TypedChoiceSlot, option: TypedChoiceOption) -> int:
        if self.seed_affinity is None:
            return 0
        key = (seed_index, slot.slot_id, option.choice_id)
        cached = self._affinity_cache.get(key)
        if cached is not None:
            return cached
        value = self.seed_affinity(seed, option.to_dict(slot_id=slot.slot_id))
        if not isinstance(value, int) or isinstance(value, bool):
            fail("DCC_SEED_AFFINITY_INVALID", "seed_affinity must return an integer.")
        self._affinity_cache[key] = value
        return value

    def _slot_candidate_groups(
        self,
        slot: TypedChoiceSlot,
        options: Sequence[TypedChoiceOption],
        selected: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]],
        seed_index: int,
        seed: Mapping[str, Any],
        remaining: set[str],
        *,
        limit: int,
    ) -> list[tuple[TypedChoiceOption, ...]]:
        """Bounded, deterministic alternatives for one slot.

        Groups are built greedily from the highest-affinity option down, so
        the cost is linear in the option count rather than combinatorial.
        """

        lower = slot.min_choices
        upper = min(slot.max_choices, len(options))
        groups: list[tuple[TypedChoiceOption, ...]] = []
        if upper < lower:
            return groups
        ranked = sorted(options, key=lambda option: (-self._affinity(seed_index, seed, slot, option), option.choice_id))
        for start in ranked[:limit]:
            chosen: list[TypedChoiceOption] = []
            if upper >= 1:
                if not self._partial_conditions_hold(tuple(selected) + ((slot, start),), remaining):
                    continue
                chosen.append(start)
            for option in ranked:
                if len(chosen) >= upper:
                    break
                if option in chosen:
                    continue
                if len(chosen) >= lower and self._affinity(seed_index, seed, slot, option) <= 0:
                    break
                trial = tuple(selected) + tuple((slot, row) for row in chosen + [option])
                if self._partial_conditions_hold(trial, remaining):
                    chosen.append(option)
            if len(chosen) < lower:
                continue
            group = tuple(chosen)
            if group not in groups:
                groups.append(group)
        if lower == 0 and () not in groups:
            groups.append(())
        return groups

    def _rollout_candidates(
        self,
        fill_indexes: Sequence[int],
        fill_suffix: Sequence[set[str]],
        candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]],
        baseline: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]],
        skeleton: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]],
        seed_index: int,
        seed: Mapping[str, Any],
        *,
        alternatives: int,
    ) -> Iterable[tuple[list[tuple[TypedChoiceSlot, TypedChoiceOption]], int]]:
        """Yield bounded complete rollout candidates in deterministic order.

        A rollout is a bounded depth-first walk over the per-slot alternative
        groups.  Keeping the walk resumable lets a caller run the next
        candidate after a predicate or Factory validator rejects the current
        one, without restarting at the same false frontier head.
        """

        selected: list[tuple[TypedChoiceSlot, TypedChoiceOption]] = list(baseline) + list(skeleton)
        stack: list[list[Any]] = []
        marks: list[int] = []
        position = 0
        backtracks = 0
        while True:
            while position < len(fill_indexes):
                index = fill_indexes[position]
                slot = self.slots[index]
                if len(stack) == position:
                    groups = self._slot_candidate_groups(
                        slot,
                        candidates_by_slot[index],
                        selected,
                        seed_index,
                        seed,
                        fill_suffix[position + 1],
                        limit=alternatives,
                    )
                    stack.append([groups, 0])
                    marks.append(len(selected))
                groups, cursor = stack[position]
                if cursor >= len(groups):
                    stack.pop()
                    marks.pop()
                    position -= 1
                    if position < 0:
                        return
                    del selected[marks[position]:]
                    stack[position][1] += 1
                    backtracks += 1
                    if backtracks > self.backtrack_limit:
                        return
                    continue
                del selected[marks[position]:]
                selected.extend((slot, option) for option in groups[cursor])
                position += 1
            yield list(selected), backtracks
            # Resume from the final slot after the caller has inspected this
            # candidate.  The normal loop below then advances parents as
            # their groups are exhausted.
            position -= 1
            if position < 0:
                return
            del selected[marks[position]:]
            stack[position][1] += 1
            backtracks += 1
            if backtracks > self.backtrack_limit:
                return

    def _rollout(
        self,
        fill_indexes: Sequence[int],
        fill_suffix: Sequence[set[str]],
        candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]],
        baseline: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]],
        skeleton: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]],
        seed_index: int,
        seed: Mapping[str, Any],
        *,
        alternatives: int,
    ) -> tuple[list[tuple[TypedChoiceSlot, TypedChoiceOption]] | None, int]:
        """Compatibility wrapper returning the first bounded rollout."""

        candidates = self._rollout_candidates(
            fill_indexes,
            fill_suffix,
            candidates_by_slot,
            baseline,
            skeleton,
            seed_index,
            seed,
            alternatives=alternatives,
        )
        return next(iter(candidates), (None, 0))

    def _enumerate_skeletons(
        self,
        skeleton_indexes: Sequence[int],
        candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]],
        baseline: Sequence[tuple[TypedChoiceSlot, TypedChoiceOption]],
        fill_indexes: Sequence[int],
    ) -> list[tuple[tuple[TypedChoiceSlot, TypedChoiceOption], ...]] | None:
        """Exact cross product of the skeleton slots, or None when too wide."""

        partials: list[tuple[tuple[TypedChoiceSlot, TypedChoiceOption], ...]] = [()]
        raw_attempts = 0
        for order, index in enumerate(skeleton_indexes):
            slot = self.slots[index]
            options = candidates_by_slot[index]
            lower = slot.min_choices
            upper = min(slot.max_choices, len(options))
            if upper < lower:
                return []
            remaining = self._remaining_ids(list(skeleton_indexes[order + 1:]) + list(fill_indexes), candidates_by_slot)
            grown: list[tuple[tuple[TypedChoiceSlot, TypedChoiceOption], ...]] = []
            for partial in partials:
                for count in range(lower, upper + 1):
                    for chosen in combinations(options, count):
                        # Charge each raw combination before semantic pruning;
                        # all-pruned spaces must not bypass skeleton_limit.
                        raw_attempts += 1
                        if raw_attempts > self.skeleton_limit:
                            return None
                        candidate = partial + tuple((slot, option) for option in chosen)
                        if self._partial_conditions_hold(tuple(baseline) + candidate, remaining):
                            grown.append(candidate)
                            if len(grown) > self.skeleton_limit:
                                return None
            partials = grown
            if not partials:
                return []
        return partials

    def _compile_seeded_rollout(self, candidates_by_slot: Sequence[tuple[TypedChoiceOption, ...]]) -> CompilationResult:
        self._affinity_cache: dict[tuple[int, str, str], int] = {}
        baseline = self._baseline_selection()
        skeleton_positions = [index for index, slot in enumerate(self.slots) if slot.choice_kind in self.skeleton_choice_kinds]
        fill_indexes = [index for index in range(len(self.slots)) if index not in set(skeleton_positions)]
        skeletons = self._enumerate_skeletons(skeleton_positions, candidates_by_slot, baseline, fill_indexes) if skeleton_positions else [()]
        if skeletons is None:
            # The skeleton is itself too wide to enumerate exactly; roll it out
            # with everything else and say so in the proof.
            self._skeleton_enumerated = False
            skeletons = [()]
            fill_indexes = list(range(len(self.slots)))

        fill_suffix: list[set[str]] = [set() for _ in range(len(fill_indexes) + 1)]
        for position in range(len(fill_indexes) - 1, -1, -1):
            fill_suffix[position] = fill_suffix[position + 1] | {option.choice_id for option in candidates_by_slot[fill_indexes[position]]}

        seeds = list(self._effective_diversity_seeds)
        plans: dict[str, LegalPlan] = {}
        rejected: list[str] = []
        predicate_rejected: list[str] = []
        explored = 0
        explored_states = 0
        rollouts_attempted = 0
        abandoned = 0
        # Keep several deterministic branches available for rejection
        # recovery even when the requested frontier is one plan.  The hard
        # cap keeps wide catalogues linear per slot; search_state_limit and
        # backtrack_limit remain the global/per-rollout bounds.
        alternatives = min(8, max(2, self.frontier_limit, self.backtrack_limit))
        for seed_index, seed in enumerate(seeds):
            for skeleton in skeletons:
                if len(plans) >= self.frontier_limit:
                    break
                if rollouts_attempted >= self.search_state_limit:
                    fail("DCC_SEARCH_BUDGET_EXHAUSTED", "The deterministic legal-plan rollout exceeded its attempt budget.")
                rollouts_attempted += 1
                rollout_produced = False
                for selection, _ in self._rollout_candidates(
                    fill_indexes,
                    fill_suffix,
                    candidates_by_slot,
                    baseline,
                    skeleton,
                    seed_index,
                    seed,
                    alternatives=alternatives,
                ):
                    # A complete candidate is the bounded search unit for a
                    # seeded rollout.  Pulling a further candidate after the
                    # limit is reached fails closed instead of silently
                    # returning a false empty/short frontier.
                    if explored_states >= self.search_state_limit:
                        fail("DCC_SEARCH_BUDGET_EXHAUSTED", "The deterministic legal-plan rollout exceeded its state budget.")
                    explored_states += 1
                    if not self._conditions_hold(selection):
                        continue
                    rollout_produced = True
                    actual = [row for row in selection if not row[0].slot_id.startswith("__accepted__.")]
                    explored += 1
                    try:
                        plan = self._plan_from_selection(actual)
                    except _RejectedPredicate as rejected_predicate:
                        predicate_rejected.append(rejected_predicate.plan_hash)
                        continue
                    except _RejectedPlan as rejected_plan:
                        rejected.append(rejected_plan.plan_hash)
                        continue
                    plans[plan.legal_plan_sha256] = plan
                    # One accepted candidate is enough for this seed/skeleton
                    # direction.  Extra candidates from the same direction
                    # are only consumed when earlier candidates were rejected;
                    # this preserves diversity across independent seeds while
                    # still repairing the false-empty rejection path.
                    break
                if not rollout_produced:
                    abandoned += 1
            if len(plans) >= self.frontier_limit:
                break
        return self._result(
            list(plans.values()),
            rejected,
            predicate_rejected,
            explored_assignments=explored,
            explored_states=explored_states,
            pruned_states=abandoned,
            rollouts_attempted=rollouts_attempted,
            rollouts_abandoned=abandoned,
            space_complete=False,
        )

    def _result(
        self,
        plans: Sequence[LegalPlan],
        rejected: Sequence[str],
        predicate_rejected: Sequence[str],
        *,
        explored_assignments: int,
        explored_states: int,
        pruned_states: int,
        space_complete: bool,
        rollouts_attempted: int = 0,
        rollouts_abandoned: int = 0,
    ) -> CompilationResult:
        unique: dict[str, LegalPlan] = {plan.legal_plan_sha256: plan for plan in plans}
        return CompilationResult(
            plans=tuple(unique[key] for key in sorted(unique)),
            validator_rejections=tuple(sorted(set(rejected))),
            predicate_rejections=tuple(sorted(set(predicate_rejected))),
            explored_assignments=explored_assignments,
            explored_states=explored_states,
            pruned_states=pruned_states,
            search_strategy=self._resolved_strategy,
            skeleton_enumerated=self._skeleton_enumerated,
            rollouts_attempted=rollouts_attempted,
            rollouts_abandoned=rollouts_abandoned,
            space_complete=space_complete,
            frontier_limit=self.frontier_limit,
        )


class _RejectedPlan(Exception):
    def __init__(self, plan_hash: str) -> None:
        self.plan_hash = plan_hash


class _RejectedPredicate(Exception):
    def __init__(self, plan_hash: str) -> None:
        self.plan_hash = plan_hash


def compile_legal_plans(
    slots: Sequence[TypedChoiceSlot | Mapping[str, Any]],
    *,
    target_cl: int,
    final_validator: FinalValidator | None = None,
    accepted_choices: Iterable[str] = (),
    acquisition_history: Mapping[str, int] | None = None,
    owner_locks: Mapping[str, Sequence[str]] | None = None,
    cardinality_limits: Mapping[str, int] | None = None,
    plan_predicate: PlanPredicate | None = None,
    controlled_preferences_sha256: str | None = None,
    branch_priority: BranchPriority | None = None,
    frontier_limit: int = 12,
    search_state_limit: int = 100_000,
    search_strategy: str = SEARCH_AUTO,
    skeleton_choice_kinds: Iterable[str] = DEFAULT_SKELETON_CHOICE_KINDS,
    skeleton_limit: int = DEFAULT_SKELETON_LIMIT,
    diversity_seeds: Sequence[Mapping[str, Any]] = (),
    seed_affinity: SeedAffinity | None = None,
    affinity_policy_version: str = AFFINITY_POLICY_VERSION,
    backtrack_limit: int = DEFAULT_BACKTRACK_LIMIT,
) -> CompilationResult:
    return LegalPlanCompiler(
        slots,
        target_cl=target_cl,
        final_validator=final_validator,
        accepted_choices=accepted_choices,
        acquisition_history=acquisition_history,
        owner_locks=owner_locks,
        cardinality_limits=cardinality_limits,
        plan_predicate=plan_predicate,
        controlled_preferences_sha256=controlled_preferences_sha256,
        branch_priority=branch_priority,
        frontier_limit=frontier_limit,
        search_state_limit=search_state_limit,
        search_strategy=search_strategy,
        skeleton_choice_kinds=skeleton_choice_kinds,
        skeleton_limit=skeleton_limit,
        diversity_seeds=diversity_seeds,
        seed_affinity=seed_affinity,
        affinity_policy_version=affinity_policy_version,
        backtrack_limit=backtrack_limit,
    ).compile()


def validate_legal_plan(plan: LegalPlan | Mapping[str, Any]) -> LegalPlan:
    if isinstance(plan, LegalPlan):
        _validate_plan_proof(plan.proof, plan.legal_plan_sha256)
        return plan
    fail("DCC_PLAN_TRUST_REQUIRED", "Bare legal-plan mappings cannot cross a trust boundary.")


def legal_plan_set_sha256(result: CompilationResult | Sequence[LegalPlan]) -> str:
    plans = result.plans if isinstance(result, CompilationResult) else tuple(result)
    return sha256_json([plan.legal_plan_sha256 for plan in plans])
