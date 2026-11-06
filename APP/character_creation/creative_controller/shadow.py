"""Provider-free, database-free Stage A orchestration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from app.core import canonical_json, sha256_json

from .choice_semantics import ChoiceSemantics, aggregate_whole_plan_semantics, choice_semantics_set_sha256, validate_semantics_set, verify_semantics_binding, validate_vocabulary_authority
from .clustering import DiversityResult, select_diverse_plans
from .creative_menu import CreativePredicateMenu, resolve_creative_predicate_selection, validate_intent_predicate_selection
from .contracts import (
    IdentifierRegistry,
    build_creative_intent,
    derive_controller_identifier,
    fail,
    require_digest,
    require_identifier,
    require_string,
    require_type,
    validate_creative_intent,
)
from .content_snapshots import FactoryContentSnapshot, validate_content_snapshot
from .factory_validator import FactoryFinalValidatorAdapter
from .legal_plan_compiler import (
    AFFINITY_POLICY_VERSION,
    DEFAULT_BACKTRACK_LIMIT,
    DEFAULT_SKELETON_CHOICE_KINDS,
    DEFAULT_SKELETON_LIMIT,
    SEARCH_AUTO,
    SEARCH_STRATEGIES,
    CompilationResult,
    LegalPlanCompiler,
)
from .manifest import ManifestArtifact, build_manifest
from .ranking import RANKING_PROFILE_SHA256, RankingResult, controlled_preferences_sha256, evaluate_controlled_preferences, rank_plans
from .replay import ControllerEvent, build_event, verify_event_chain


SHADOW_SCHEMA = "TianxiaFoundry.DeterministicCreativeControllerShadow.v1"


def _hash(value: Any, path: str) -> str:
    result = require_digest(value, path=path)
    assert result is not None
    return result


@dataclass(frozen=True)
class ShadowInputs:
    """All authority needed for one isolated shadow compilation.

    The complete request is represented only by its digest and resolver
    binding.  ``slots`` and ``semantics`` are typed, detached inputs supplied
    by the caller; this class never opens the live Factory run.
    """

    run_id: str
    project_id: str
    project_revision: int
    request_sha256: str
    request_resolver_id: str
    request_resolver_binding_sha256: str
    content_lock_hash: str
    canonical_project_sha256: str
    typed_choice_snapshot_sha256: str
    delegated_choice_envelope_sha256: str
    character_state_sha256: str
    operator_contract_sha256: str
    legal_compiler_version_sha256: str
    content_snapshot: FactoryContentSnapshot
    intent: Mapping[str, Any]
    slots: tuple[Any, ...]
    semantics: Mapping[str, ChoiceSemantics | Mapping[str, Any]]
    predicate_menu: CreativePredicateMenu
    predicate_selection: Mapping[str, Any]
    target_cl: int = 15
    controller_version_sha256: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    selected_ai_identity_sha256: str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    final_validator: FactoryFinalValidatorAdapter | None = None
    accepted_baseline: tuple[str, ...] = ()
    acquisition_history: Mapping[str, int] = field(default_factory=dict)
    owner_locks: Mapping[str, Sequence[str]] = field(default_factory=dict)
    cardinality_limits: Mapping[str, int] = field(default_factory=dict)
    frontier_limit: int = 12
    search_strategy: str = SEARCH_AUTO
    search_state_limit: int = 100_000
    skeleton_choice_kinds: tuple[str, ...] = tuple(sorted(DEFAULT_SKELETON_CHOICE_KINDS))
    skeleton_limit: int = DEFAULT_SKELETON_LIMIT
    backtrack_limit: int = DEFAULT_BACKTRACK_LIMIT
    affinity_policy_version: str = AFFINITY_POLICY_VERSION
    card_metadata_by_plan: Mapping[str, Mapping[str, Any]] | None = None
    vocabulary_authority: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        require_string(self.run_id, path="shadow.run_id")
        require_string(self.project_id, path="shadow.project_id")
        require_type(self.project_revision, int, path="shadow.project_revision")
        if self.project_revision < 0:
            fail("DCC_SCHEMA_VALUE", "shadow.project_revision cannot be negative.")
        require_identifier(self.request_resolver_id, path="shadow.request_resolver_id", prefix="dcc.request.")
        for field in ("request_sha256", "request_resolver_binding_sha256", "content_lock_hash", "canonical_project_sha256", "typed_choice_snapshot_sha256", "delegated_choice_envelope_sha256", "character_state_sha256", "operator_contract_sha256", "legal_compiler_version_sha256", "controller_version_sha256", "selected_ai_identity_sha256"):
            _hash(getattr(self, field), f"shadow.{field}")
        if not isinstance(self.content_snapshot, FactoryContentSnapshot):
            fail("DCC_SCHEMA_TYPE", "shadow.content_snapshot must be FactoryContentSnapshot.v1.")
        validate_content_snapshot(self.content_snapshot)
        if self.vocabulary_authority is None:
            authority = {"schema": "TianxiaFoundry.CreativeVocabularyAuthority.v1", "version": 1, "vocabularies": {key: [] for key in ("theme_tags", "role_tags", "capability_families", "combat_functions", "resource_families", "late_progression_tags", "complexity_factors", "tradeoff_codes")}, "adapter_version_sha256": None}
            authority["authority_sha256"] = sha256_json({key: value for key, value in authority.items() if key != "authority_sha256"})
            object.__setattr__(self, "vocabulary_authority", authority)
        authority = validate_vocabulary_authority(self.vocabulary_authority)
        object.__setattr__(self, "vocabulary_authority", authority)
        if authority["authority_sha256"] != self.content_snapshot.vocabulary_authority_sha256:
            fail("DCC_VOCABULARY_AUTHORITY_BINDING", "Shadow vocabulary authority is not committed by the content snapshot.")
        if not isinstance(self.predicate_menu, CreativePredicateMenu):
            fail("DCC_CREATIVE_MENU_REQUIRED", "Shadow execution requires a Factory-owned creative predicate menu.")
        if self.predicate_menu.public_menu["vocabulary_authority_sha256"] != authority["authority_sha256"]:
            fail("DCC_CREATIVE_MENU_AUTHORITY", "The creative predicate menu is not bound to the active vocabulary authority.")
        resolved_selection = resolve_creative_predicate_selection(self.predicate_menu, self.predicate_selection)
        object.__setattr__(self, "predicate_selection", deepcopy(dict(self.predicate_selection)))
        intent = validate_creative_intent(self.intent)
        object.__setattr__(self, "intent", intent)
        validate_intent_predicate_selection(intent, resolved_selection)
        intent_binding = intent["binding"]
        expected_intent_binding = {
            "project_id": self.project_id,
            "project_revision": self.project_revision,
            "request_sha256": self.request_sha256,
            "content_snapshot_sha256": self.content_snapshot.content_snapshot_sha256,
            "content_lock_hash": self.content_lock_hash,
            "character_state_sha256": self.character_state_sha256,
        }
        if intent_binding != expected_intent_binding:
            fail("DCC_INTENT_BINDING_INVALID", "The active intent is not bound to the exact shadow request, revision, and snapshot.")
        if not isinstance(self.slots, tuple):
            object.__setattr__(self, "slots", tuple(self.slots))
        if not isinstance(self.semantics, Mapping):
            fail("DCC_SCHEMA_TYPE", "shadow.semantics must be an object mapping choice IDs to records.")
        object.__setattr__(self, "semantics", deepcopy(dict(self.semantics)))
        if not isinstance(self.target_cl, int) or isinstance(self.target_cl, bool) or self.target_cl < 1:
            fail("DCC_SCHEMA_VALUE", "shadow.target_cl must be a positive integer.")
        if not isinstance(self.final_validator, FactoryFinalValidatorAdapter):
            fail("DCC_FACTORY_FINAL_VALIDATOR_REQUIRED", "Shadow execution requires a sealed FactoryFinalValidatorAdapter.")
        self.final_validator.validate_shadow_authority(
            canonical_project_sha256=self.canonical_project_sha256,
            request_sha256=self.request_sha256,
            content_lock_hash=self.content_lock_hash,
            typed_choice_snapshot_sha256=self.typed_choice_snapshot_sha256,
            delegated_choice_envelope_sha256=self.delegated_choice_envelope_sha256,
            target_cl=self.target_cl,
        )
        baseline = tuple(require_string(choice_id, path="shadow.accepted_baseline[]") for choice_id in self.accepted_baseline)
        if len(baseline) != len(set(baseline)):
            fail("DCC_SCHEMA_DUPLICATE", "shadow.accepted_baseline must be duplicate-free.")
        object.__setattr__(self, "accepted_baseline", baseline)
        history = dict(self.acquisition_history)
        if set(history) != set(baseline):
            fail("DCC_ACQUISITION_HISTORY_INVALID", "Acquisition history must exactly cover the accepted baseline.")
        object.__setattr__(self, "acquisition_history", history)
        object.__setattr__(self, "owner_locks", {key: tuple(value) for key, value in self.owner_locks.items()})
        object.__setattr__(self, "cardinality_limits", dict(self.cardinality_limits))
        if not isinstance(self.frontier_limit, int) or isinstance(self.frontier_limit, bool) or not 1 <= self.frontier_limit <= 12:
            fail("DCC_SCHEMA_VALUE", "shadow.frontier_limit must be an integer in [1,12].")
        if not isinstance(self.search_state_limit, int) or isinstance(self.search_state_limit, bool) or self.search_state_limit < self.frontier_limit:
            fail("DCC_SCHEMA_VALUE", "shadow.search_state_limit must be an integer at least as large as frontier_limit.")
        if self.search_strategy not in SEARCH_STRATEGIES:
            fail("DCC_SEARCH_STRATEGY_INVALID", "shadow.search_strategy must be AUTO, EXHAUSTIVE, or SEEDED_ROLLOUT.")
        kinds = tuple(sorted(require_string(kind, path="shadow.skeleton_choice_kinds[]") for kind in self.skeleton_choice_kinds))
        if len(kinds) != len(set(kinds)):
            fail("DCC_SCHEMA_DUPLICATE", "shadow.skeleton_choice_kinds must be duplicate-free.")
        for name, value in (("skeleton_limit", self.skeleton_limit), ("backtrack_limit", self.backtrack_limit)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                fail("DCC_SCHEMA_VALUE", f"shadow.{name} must be a positive integer.")
        object.__setattr__(self, "skeleton_choice_kinds", kinds)
        object.__setattr__(self, "affinity_policy_version", require_string(self.affinity_policy_version, path="shadow.affinity_policy_version"))
        if self.card_metadata_by_plan is not None:
            object.__setattr__(self, "card_metadata_by_plan", deepcopy(dict(self.card_metadata_by_plan)))

    @property
    def binding(self) -> dict[str, Any]:
        schema_versions = dict(self.content_snapshot.catalogue_schema_versions)
        version = ",".join(f"{name}:{schema_versions[name]}" for name in sorted(schema_versions))
        return {
            "content_snapshot_sha256": self.content_snapshot.content_snapshot_sha256,
            "catalogue_sha256": self.content_snapshot.catalogue_set_sha256,
            "catalogue_schema_version": version,
            "project_id": self.project_id,
            "project_revision": self.project_revision,
            "canonical_project_sha256": self.canonical_project_sha256,
            "request_sha256": self.request_sha256,
            "request_resolver_id": self.request_resolver_id,
            "request_resolver_binding_sha256": self.request_resolver_binding_sha256,
            "content_lock_hash": self.content_lock_hash,
            "typed_choice_snapshot_sha256": self.typed_choice_snapshot_sha256,
            "delegated_choice_envelope_sha256": self.delegated_choice_envelope_sha256,
            "character_state_sha256": self.character_state_sha256,
            "intent_sha256": self.intent["intent_sha256"],
            "operator_contract_sha256": self.operator_contract_sha256,
            "controller_version_sha256": self.controller_version_sha256,
            "legal_compiler_version_sha256": self.legal_compiler_version_sha256,
            "ranking_profile_sha256": RANKING_PROFILE_SHA256,
            "choice_semantics_set_sha256": self.content_snapshot.choice_semantics_set_sha256,
            "selected_ai_identity_sha256": self.selected_ai_identity_sha256,
            "vocabulary_authority_sha256": self.vocabulary_authority["authority_sha256"],
            "creative_predicate_menu_sha256": self.predicate_menu.menu_sha256,
            "creative_predicate_selection_receipt_sha256": resolve_creative_predicate_selection(self.predicate_menu, self.predicate_selection)["receipt"]["selection_receipt_sha256"],
            "accepted_baseline_sha256": sha256_json(list(self.accepted_baseline)),
            "owner_locks_sha256": sha256_json({key: sorted(value) for key, value in sorted(self.owner_locks.items())}),
            "acquisition_history_sha256": sha256_json(dict(sorted(self.acquisition_history.items()))),
        }


@dataclass(frozen=True)
class ShadowResult:
    manifest: dict[str, Any]
    private_evidence: dict[str, Any]
    artifact: ManifestArtifact
    events: tuple[ControllerEvent, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", deepcopy(self.manifest))
        object.__setattr__(self, "private_evidence", deepcopy(self.private_evidence))

    @property
    def manifest_json(self) -> str:
        return canonical_json(self.manifest)


SEED_SCHEMA = "TianxiaFoundry.CreativeDiversitySeed.v1"


def build_diversity_seeds(semantics: Mapping[str, ChoiceSemantics], *, count: int) -> tuple[dict[str, Any], ...]:
    """Derive deterministic diversity targets from verified semantics only.

    A seed is a reachable semantic profile that some admitted choice actually
    carries, so every seed names a direction the compiler can genuinely reach.
    The neutral seed comes first, which keeps the plain intent-best plan in the
    pool.  Nothing here consults a clock, a random source, or free prose.
    """

    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        fail("DCC_SCHEMA_VALUE", "Diversity seed count must be a positive integer.")
    profiles: set[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = set()
    for choice_id in sorted(semantics):
        value = semantics[choice_id].value
        resource = value.get("resource_loop") or {}
        profiles.add((
            tuple(sorted(value.get("role_tags") or ())),
            tuple(sorted(value.get("capability_families") or ())),
            tuple(sorted(set(resource.get("produces") or ()) | set(resource.get("consumes") or ()))),
        ))
    seeds: list[dict[str, Any]] = [{"schema": SEED_SCHEMA, "role_tags": [], "capability_families": [], "resource_families": []}]
    for roles, capabilities, resources in sorted(profiles):
        if len(seeds) >= count:
            break
        if not (roles or capabilities or resources):
            continue
        seeds.append({"schema": SEED_SCHEMA, "role_tags": list(roles), "capability_families": list(capabilities), "resource_families": list(resources)})
    return tuple(seeds)


def _compile_twice(inputs: ShadowInputs, semantics: Mapping[str, ChoiceSemantics]) -> tuple[CompilationResult, dict[str, str]]:
    controlled_hash = controlled_preferences_sha256(inputs.intent)

    def aggregate(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        choice_ids = list(inputs.accepted_baseline) + [row["choice_id"] for row in payload.get("choices", ())]
        if not choice_ids:
            return None
        return aggregate_whole_plan_semantics(choice_ids, semantics)

    def predicate(payload: Mapping[str, Any]) -> bool:
        whole = aggregate(payload)
        return whole is not None and evaluate_controlled_preferences(whole, inputs.intent)["hard_passed"] is True

    def branch_priority(payload: Mapping[str, Any]) -> int:
        whole = aggregate(payload)
        if whole is None:
            return 0
        evidence = evaluate_controlled_preferences(whole, inputs.intent)
        return (
            sum(400 for row in evidence["must_include"] if row["matched"])
            - sum(800 for row in evidence["must_exclude"] if row["matched"])
            + sum(100 for row in evidence["soft_prefer"] if row["matched"])
            - sum(150 for row in evidence["soft_avoid"] if row["matched"])
        )

    single_choice_cache: dict[str, dict[str, Any]] = {}

    def single_choice_aggregate(choice_id: str) -> dict[str, Any]:
        cached = single_choice_cache.get(choice_id)
        if cached is None:
            cached = aggregate_whole_plan_semantics([choice_id], semantics)
            single_choice_cache[choice_id] = cached
        return cached

    def seed_affinity(seed: Mapping[str, Any], option: Mapping[str, Any]) -> int:
        """Integer affinity of one option for one diversity target.

        Controlled-preference weights match the plan-level branch priority so
        rollout and frontier ordering stay continuous with each other.
        """

        whole = single_choice_aggregate(option["choice_id"])
        evidence = evaluate_controlled_preferences(whole, inputs.intent)
        score = (
            sum(400 for row in evidence["must_include"] if row["matched"])
            - sum(800 for row in evidence["must_exclude"] if row["matched"])
            + sum(100 for row in evidence["soft_prefer"] if row["matched"])
            - sum(150 for row in evidence["soft_avoid"] if row["matched"])
        )
        resource = whole.get("resource_loop") or {}
        families = set(resource.get("produces") or ()) | set(resource.get("consumes") or ())
        score += 100 * len(set(seed.get("role_tags") or ()) & set(whole.get("role_tags") or ()))
        score += 60 * len(set(seed.get("capability_families") or ()) & set(whole.get("capability_families") or ()))
        score += 40 * len(set(seed.get("resource_families") or ()) & families)
        return score

    compiler = LegalPlanCompiler(
        inputs.slots,
        target_cl=inputs.target_cl,
        final_validator=inputs.final_validator,
        accepted_choices=inputs.accepted_baseline,
        acquisition_history=inputs.acquisition_history,
        owner_locks=inputs.owner_locks,
        cardinality_limits=inputs.cardinality_limits,
        plan_predicate=predicate,
        controlled_preferences_sha256=controlled_hash,
        branch_priority=branch_priority,
        frontier_limit=inputs.frontier_limit,
        search_state_limit=inputs.search_state_limit,
        search_strategy=inputs.search_strategy,
        skeleton_choice_kinds=inputs.skeleton_choice_kinds,
        skeleton_limit=inputs.skeleton_limit,
        diversity_seeds=build_diversity_seeds(semantics, count=inputs.frontier_limit),
        seed_affinity=seed_affinity,
        affinity_policy_version=inputs.affinity_policy_version,
        backtrack_limit=inputs.backtrack_limit,
    )
    first = compiler.compile()
    second = compiler.compile()
    first_bytes = canonical_json({"plans": [plan.plan_payload for plan in first.plans], "proofs": [plan.proof for plan in first.plans]})
    second_bytes = canonical_json({"plans": [plan.plan_payload for plan in second.plans], "proofs": [plan.proof for plan in second.plans]})
    if first_bytes != second_bytes or [plan.legal_plan_sha256 for plan in first.plans] != [plan.legal_plan_sha256 for plan in second.plans]:
        fail("DCC_DOUBLE_COMPILE_MISMATCH", "Two isolated shadow compilations produced different legal plans.")
    identities = {plan.legal_plan_sha256: sha256_json(plan.plan_payload) for plan in first.plans}
    return first, identities


def run_shadow_controller(inputs: ShadowInputs) -> ShadowResult:
    """Compile and publish a bounded manifest in memory only."""

    if not isinstance(inputs, ShadowInputs):
        fail("DCC_SHADOW_INPUT_REQUIRED", "run_shadow_controller requires immutable ShadowInputs.")
    # ShadowInputs detaches its mappings, but nested mappings remain mutable to
    # ordinary Python callers.  Recheck the exact seal at the execution gate
    # so a post-construction authority edit cannot reach compilation.
    inputs.final_validator.validate_shadow_authority(
        canonical_project_sha256=inputs.canonical_project_sha256,
        request_sha256=inputs.request_sha256,
        content_lock_hash=inputs.content_lock_hash,
        typed_choice_snapshot_sha256=inputs.typed_choice_snapshot_sha256,
        delegated_choice_envelope_sha256=inputs.delegated_choice_envelope_sha256,
        target_cl=inputs.target_cl,
    )
    intent = validate_creative_intent(inputs.intent)
    controller_id, controller_derivation_sha256 = derive_controller_identifier(inputs.run_id, inputs.request_sha256, inputs.controller_version_sha256, inputs.selected_ai_identity_sha256, registry=IdentifierRegistry())
    semantics = validate_semantics_set(inputs.semantics, required_choice_ids=inputs.content_snapshot.active_choice_ids, vocabulary_authority=inputs.vocabulary_authority)
    active_records = inputs.content_snapshot.record_by_id()
    for choice_id, semantic in semantics.items():
        record = active_records.get(choice_id)
        if record is None or record.lifecycle != "ACTIVE":
            fail("DCC_CHOICE_SEMANTICS_INCOMPLETE", "A published plan references semantics outside the active snapshot.")
        verify_semantics_binding(
            semantic,
            catalogue_sha256=inputs.content_snapshot.catalogue_set_sha256,
            choice_record_sha256=record.choice_record_sha256,
            typed_authority_sha256=record.typed_authority_sha256,
        )
    if choice_semantics_set_sha256(semantics, required_choice_ids=inputs.content_snapshot.active_choice_ids, vocabulary_authority=inputs.vocabulary_authority) != inputs.content_snapshot.choice_semantics_set_sha256:
        fail("DCC_CHOICE_SEMANTICS_STALE", "The semantics set does not match the active snapshot commitment.")
    compiled, double_compile_identities = _compile_twice(inputs, semantics)
    if not compiled.plans:
        fail("DCC_NO_LEGAL_PLANS", "The shadow compiler found no complete legal plans satisfying the controlled predicates.")
    compiler_authority = {
        key: value
        for key, value in compiled.plans[0].proof["compiler_binding"].items()
        if key != "plan_payload_sha256"
    }
    compiler_authority_sha256 = compiler_authority["compiler_binding_sha256"]
    if any(plan.proof["compiler_binding"]["compiler_binding_sha256"] != compiler_authority_sha256 for plan in compiled.plans):
        fail("DCC_PLAN_COMPILER_BINDING", "The shadow compiler produced plans under mixed search authorities.")
    schedules = {
        plan.legal_plan_sha256: {
            **dict(inputs.acquisition_history),
            **{row["choice_id"]: row["acquisition_cl"] for row in plan.choices},
        }
        for plan in compiled.plans
    }
    ranked: RankingResult = rank_plans(compiled.plans, intent, semantics, acquisition_schedules=schedules, vocabulary_authority=inputs.vocabulary_authority, baseline_choice_ids=inputs.accepted_baseline)
    diversity: DiversityResult = select_diverse_plans(ranked.ranked_plans, count=4)
    selected_ids = {row.legal_plan_sha256 for row in diversity.selected}
    selected = tuple(diversity.selected) + tuple(row for row in ranked.ranked_plans if row.legal_plan_sha256 not in selected_ids)
    binding = inputs.binding
    # A single shadow manifest is whole-build-first; pages are bounded at the
    # proposal's V1 maximum and contain the diverse first four candidates.
    artifact = build_manifest(
        selected,
        binding=binding,
        manifest_kind="WHOLE_BUILD",
        decision_scope="complete_cl15_build",
        page_index=0,
        page_size=4,
        maximum_visible_for_intent=12,
        card_metadata_by_plan=inputs.card_metadata_by_plan,
        double_compile_identity_by_plan=double_compile_identities,
        ranking_receipt_sha256=ranked.private_receipt["ranking_receipt_sha256"],
        factory_validator_authority_sha256=inputs.final_validator.authority_sha256,
    )

    input_binding_sha256 = sha256_json(binding)
    state_before = sha256_json({"schema": "TianxiaFoundry.CreativeControllerState.v1", "controller_id": controller_id, "state": "CREATIVE_INTENT_PENDING", "binding": binding})
    state_after_intent = sha256_json({"schema": "TianxiaFoundry.CreativeControllerState.v1", "controller_id": controller_id, "state": "MANIFEST_COMPILING", "intent_sha256": intent["intent_sha256"], "binding": binding})
    state_after_manifest = sha256_json({"schema": "TianxiaFoundry.CreativeControllerState.v1", "controller_id": controller_id, "state": "AWAITING_CHOICE", "manifest_sha256": artifact.manifest_sha256, "binding": binding})
    activation = build_event(
        controller_id=controller_id,
        ordinal=1,
        event_type="INTENT_ACTIVATED",
        run_id=inputs.run_id,
        project_id=inputs.project_id,
        previous_event_sha256=None,
        subject_sha256=intent["intent_sha256"],
        binding={key: binding[key] for key in ("project_revision", "content_snapshot_sha256", "request_sha256", "request_resolver_id", "request_resolver_binding_sha256", "content_lock_hash", "selected_ai_identity_sha256")},
        state_sha256_before=state_before,
        state_sha256_after=state_after_intent,
        actor="factory",
    )
    publication = build_event(
        controller_id=controller_id,
        ordinal=2,
        event_type="MANIFEST_PUBLISHED",
        run_id=inputs.run_id,
        project_id=inputs.project_id,
        previous_event_sha256=activation.event_sha256,
        subject_sha256=artifact.manifest_sha256,
        binding=activation.value["binding"],
        state_sha256_before=state_after_intent,
        state_sha256_after=state_after_manifest,
        actor="factory",
    )
    events = (activation, publication)
    verify_event_chain(events)
    private_evidence = {
        "schema": SHADOW_SCHEMA,
        "visibility": "FACTORY_INTERNAL",
        "controller_id": controller_id,
        "controller_derivation_sha256": controller_derivation_sha256,
        "input_binding_sha256": input_binding_sha256,
        "content_snapshot_sha256": inputs.content_snapshot.content_snapshot_sha256,
        "legal_plan_set_sha256": compiled.legal_plan_set_sha256,
        "compiled_plan_payloads": {plan.legal_plan_sha256: plan.plan_payload for plan in compiled.plans},
        "compiled_plan_proofs": {plan.legal_plan_sha256: plan.proof for plan in compiled.plans},
        "compiler_search": {
            "requested_search_strategy": compiler_authority["requested_search_strategy"],
            "frontier_limit": compiled.frontier_limit,
            "search_strategy": compiled.search_strategy,
            "resolved_search_strategy": compiler_authority["resolved_search_strategy"],
            "search_state_limit": compiler_authority["search_state_limit"],
            "skeleton_choice_kinds": compiler_authority["skeleton_choice_kinds"],
            "skeleton_limit": compiler_authority["skeleton_limit"],
            "space_complete": compiled.space_complete,
            "skeleton_enumerated": compiled.skeleton_enumerated,
            "backtrack_limit": compiler_authority["backtrack_limit"],
            "diversity_seed_set_sha256": compiler_authority["diversity_seed_set_sha256"],
            "affinity_policy_version": compiler_authority["affinity_policy_version"],
            "affinity_policy_sha256": compiler_authority["affinity_policy_sha256"],
            "compiler_search_authority_sha256": compiler_authority_sha256,
            "rollouts_attempted": compiled.rollouts_attempted,
            "rollouts_abandoned": compiled.rollouts_abandoned,
            "explored_states": compiled.explored_states,
            "pruned_states": compiled.pruned_states,
            "validator_rejections": list(compiled.validator_rejections),
            "predicate_rejections": list(compiled.predicate_rejections),
        },
        "compiler_search_authority": compiler_authority,
        "creative_predicate_selection_receipt": resolve_creative_predicate_selection(inputs.predicate_menu, inputs.predicate_selection)["receipt"],
        "ranking_receipt": ranked.private_receipt,
        "diversity": {
            "selected_plan_sha256s": [row.legal_plan_sha256 for row in diversity.selected],
            "clusters": [
                {"medoid_plan_sha256": cluster.medoid_plan_sha256, "member_plan_sha256s": list(cluster.member_plan_sha256s), "signature": cluster.signature.to_dict()}
                for cluster in diversity.clusters
            ],
        },
        "manifest_private_evidence": artifact.private_evidence,
        "events": [event.to_dict() for event in events],
    }
    return ShadowResult(artifact.to_dict(), private_evidence, artifact, events)


def run_shadow(inputs: ShadowInputs) -> ShadowResult:
    return run_shadow_controller(inputs)


def build_shadow_inputs(**kwargs: Any) -> ShadowInputs:
    """Convenience constructor retaining the typed-input boundary."""

    return ShadowInputs(**kwargs)
