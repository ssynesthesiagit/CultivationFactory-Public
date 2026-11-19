"""Strict public choice-manifest projection and option-only acceptance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.core import canonical_json, sha256_json

from .contracts import (
    HEX64,
    CreativeControllerError,
    IdentifierRegistry,
    derive_continuation_identifier,
    derive_manifest_identifier,
    derive_manifest_context_digest,
    derive_option_identifier,
    fail,
    require_digest,
    require_enum,
    require_exact_keys,
    require_identifier,
    require_list,
    require_string,
    require_type,
    validate_self_hash,
    without_hash,
)
from .legal_plan_compiler import LegalPlan, validate_legal_plan
from .ranking import RankedPlan, qualitative_fit_summary


MANIFEST_SCHEMA = "TianxiaFoundry.LegalChoiceManifest.v1"
ACCEPTED_OPTION_SCHEMA = "TianxiaFoundry.AcceptedManifestOption.v1"
MANIFEST_KINDS = {"WHOLE_BUILD", "MILESTONE", "CORRECTION"}
DECISION_SCOPES = {"complete_cl15_build", "milestone", "correction"}
PAGE_DEFAULTS = {"WHOLE_BUILD": (4, 12), "MILESTONE": (3, 9), "CORRECTION": (3, 6)}
DECISION_SCOPE_BY_KIND = {"WHOLE_BUILD": "complete_cl15_build", "MILESTONE": "milestone", "CORRECTION": "correction"}

BINDING_KEYS = {
    "content_snapshot_sha256", "catalogue_sha256", "catalogue_schema_version", "project_id", "project_revision",
    "canonical_project_sha256", "request_sha256", "request_resolver_id", "request_resolver_binding_sha256",
    "content_lock_hash", "typed_choice_snapshot_sha256", "delegated_choice_envelope_sha256", "character_state_sha256",
    "intent_sha256", "operator_contract_sha256", "controller_version_sha256", "legal_compiler_version_sha256",
    "ranking_profile_sha256", "choice_semantics_set_sha256", "selected_ai_identity_sha256", "vocabulary_authority_sha256",
    "creative_predicate_menu_sha256", "creative_predicate_selection_receipt_sha256", "accepted_baseline_sha256",
    "owner_locks_sha256", "acquisition_history_sha256",
}
OPTION_KEYS = {
    "option_id", "title", "identity", "why_it_fits", "combat_role", "signature_capabilities", "important_synergies",
    "meaningful_tradeoffs", "progression_consequences", "complexity", "visual_narrative_cues", "distinctness_cue", "fit_summary", "proof",
}
FIT_KEYS = {"overall", "strengths", "cautions", "ranking_receipt_sha256"}
PROOF_REQUIRED_KEYS = {"legal_plan_sha256", "validation_receipt_sha256", "double_compile_identity_sha256"}
PROOF_KEYS = PROOF_REQUIRED_KEYS | {"factory_validator_authority_sha256"}
MANIFEST_REQUIRED_KEYS = {"schema", "manifest_id", "manifest_kind", "decision_scope", "binding", "manifest_context_sha256", "page", "options", "response_schema", "manifest_sha256"}
MANIFEST_OPTIONAL_KEYS = {"factory_validator_authority_sha256"}


def _binding(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, BINDING_KEYS, path="manifest.binding")
    result = deepcopy(dict(value))
    for key in BINDING_KEYS - {"project_id", "catalogue_schema_version", "project_revision", "request_resolver_id"}:
        require_digest(result[key], path=f"manifest.binding.{key}")
    require_string(result["project_id"], path="manifest.binding.project_id")
    require_string(result["catalogue_schema_version"], path="manifest.binding.catalogue_schema_version")
    require_type(result["project_revision"], int, path="manifest.binding.project_revision")
    require_identifier(result["request_resolver_id"], path="manifest.binding.request_resolver_id", prefix="dcc.request.")
    return result


def _string_list(value: Any, *, path: str, max_length: int = 12) -> list[str]:
    rows = require_list(value, path=path, max_length=max_length)
    result = [require_string(row, path=f"{path}[{index}]", max_length=240) for index, row in enumerate(rows)]
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must not contain duplicate values.")
    return result


def _card_metadata(row: RankedPlan) -> dict[str, Any]:
    """Render every public card field from the verified ranked-plan facts."""

    semantics = row.semantics
    roles = list(dict.fromkeys(semantics.get("role_tags") or ["utility"]))
    capabilities = list(dict.fromkeys(semantics.get("capability_families") or []))
    themes = list(dict.fromkeys(semantics.get("theme_tags") or []))
    tradeoffs = list(dict.fromkeys(item["code"].replace("_", " ") for item in semantics.get("tradeoffs") or []))
    synergies = list(dict.fromkeys(item["relation"].replace("_", " ") for item in semantics.get("synergy_edges") or []))
    resource = semantics.get("resource_loop") or {}
    resources = list(dict.fromkeys((resource.get("produces") or []) + (resource.get("consumes") or [])))
    progression = semantics.get("progression") or {}
    identity_cl = progression.get("identity_online_cl", 1)
    progression_cue = "identity arrives early" if identity_cl <= 3 else "identity develops through progression"
    complexity = (semantics.get("complexity") or {}).get("bands") or ["moderate"]
    values = {"simple": 0, "moderate": 1, "complex": 2}
    complexity_value = max(complexity, key=lambda value: (values.get(value, 1), value))
    role_label = " / ".join(role.replace("_", " ") for role in roles[:3])
    capability_labels = [capability.replace("_", " ") for capability in capabilities[:4]]
    theme_labels = [theme.replace("_", " ") for theme in themes[:3]]
    title_detail = " & ".join(label.title() for label in capability_labels[:2]) or (theme_labels[0].title() if theme_labels else "Versatile Craft")
    identity_parts = [f"a {role_label} build", f"centered on {', '.join(capability_labels[:3])}"]
    if theme_labels:
        identity_parts.append(f"with a {', '.join(theme_labels[:2])} identity")
    fit_parts = [f"It expresses {', '.join(capability_labels[:3]) or role_label}"]
    if resources:
        fit_parts.append(f"uses a verified {' / '.join(resource.replace('_', ' ') for resource in resources[:2])} resource loop")
    if synergies:
        fit_parts.append(f"supports {', '.join(synergies[:2])}")
    distinct_parts = [capability_labels[0] if capability_labels else role_label]
    if len(roles) > 1:
        distinct_parts.append(f"as a {roles[1].replace('_', ' ')} secondary role")
    if resources:
        distinct_parts.append(f"through {resources[0].replace('_', ' ')}")
    if tradeoffs:
        distinct_parts.append(f"while accepting {tradeoffs[0]}")
    defaults: dict[str, Any] = {
        "title": f"{roles[0].replace('_', ' ').title()} — {title_detail}",
        "identity": "; ".join(identity_parts).capitalize() + ".",
        "why_it_fits": "; ".join(fit_parts) + ".",
        "combat_role": role_label,
        "signature_capabilities": capability_labels,
        "important_synergies": synergies[:4],
        "meaningful_tradeoffs": tradeoffs[:4],
        "progression_consequences": [progression_cue, f"signature expression is online by CL {progression.get('signature_cl', identity_cl)}"],
        "complexity": complexity_value,
        "visual_narrative_cues": theme_labels,
        "distinctness_cue": "; ".join(distinct_parts).capitalize() + ".",
    }
    defaults["title"] = require_string(defaults["title"], path="manifest.option.title", max_length=160)
    defaults["identity"] = require_string(defaults["identity"], path="manifest.option.identity", max_length=500)
    defaults["why_it_fits"] = require_string(defaults["why_it_fits"], path="manifest.option.why_it_fits", max_length=1000)
    defaults["combat_role"] = require_string(defaults["combat_role"], path="manifest.option.combat_role", max_length=240)
    for field in ("signature_capabilities", "important_synergies", "meaningful_tradeoffs", "progression_consequences", "visual_narrative_cues"):
        defaults[field] = _string_list(defaults[field], path=f"manifest.option.{field}", max_length=8)
    defaults["complexity"] = require_enum(defaults["complexity"], {"simple", "moderate", "complex"}, path="manifest.option.complexity")
    defaults["distinctness_cue"] = require_string(defaults["distinctness_cue"], path="manifest.option.distinctness_cue", max_length=240)
    return defaults


def _validate_option(option: Mapping[str, Any]) -> None:
    require_exact_keys(option, OPTION_KEYS, path="manifest.option")
    require_identifier(option["option_id"], path="manifest.option.option_id", prefix="dcc.opt.")
    for field in ("title", "identity", "why_it_fits", "combat_role", "distinctness_cue"):
        require_string(option[field], path=f"manifest.option.{field}")
    for field in ("signature_capabilities", "important_synergies", "meaningful_tradeoffs", "progression_consequences", "visual_narrative_cues"):
        _string_list(option[field], path=f"manifest.option.{field}", max_length=8)
    require_enum(option["complexity"], {"simple", "moderate", "complex"}, path="manifest.option.complexity")
    fit = option["fit_summary"]
    require_exact_keys(fit, FIT_KEYS, path="manifest.option.fit_summary")
    require_enum(fit["overall"], {"strong", "good", "mixed", "narrow"}, path="manifest.option.fit_summary.overall")
    _string_list(fit["strengths"], path="manifest.option.fit_summary.strengths", max_length=7)
    _string_list(fit["cautions"], path="manifest.option.fit_summary.cautions", max_length=7)
    require_digest(fit["ranking_receipt_sha256"], path="manifest.option.fit_summary.ranking_receipt_sha256")
    proof = option["proof"]
    require_exact_keys(proof, PROOF_REQUIRED_KEYS, {"factory_validator_authority_sha256"}, path="manifest.option.proof")
    for field in PROOF_REQUIRED_KEYS:
        require_digest(proof[field], path=f"manifest.option.proof.{field}")
    if "factory_validator_authority_sha256" in proof:
        require_digest(proof["factory_validator_authority_sha256"], path="manifest.option.proof.factory_validator_authority_sha256")


@dataclass(frozen=True)
class ManifestArtifact:
    """Public manifest plus server-private option mapping.

    ``to_dict`` and ``to_json`` serialize only the public projection.  The
    complete plan payloads remain in ``option_to_plan`` and are never merged
    into that projection.
    """

    manifest: dict[str, Any]
    option_to_plan: dict[str, LegalPlan]
    private_evidence: dict[str, Any]
    _ranked_frontier: tuple[RankedPlan, ...] = ()
    _page_size: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", deepcopy(self.manifest))
        object.__setattr__(self, "option_to_plan", dict(self.option_to_plan))
        object.__setattr__(self, "private_evidence", deepcopy(self.private_evidence))
        validate_manifest(self.manifest)
        public_ids = {row["option_id"] for row in self.manifest["options"]}
        if public_ids != set(self.option_to_plan):
            fail("DCC_MANIFEST_MAPPING_INVALID", "Every public option must resolve to exactly one private plan.")

    @property
    def manifest_sha256(self) -> str:
        return self.manifest["manifest_sha256"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.manifest)

    def to_json(self) -> str:
        return canonical_json(self.manifest)

    def plan_for_option(self, option_id: str) -> LegalPlan:
        plan = self.option_to_plan.get(option_id)
        if plan is None:
            fail("DCC_OPTION_UNKNOWN", "The option is not present in this manifest.", status_code=409)
        return plan.detached_copy()

    def next_page(self, continuation_id: str) -> "ManifestArtifact":
        """Resolve only the continuation committed by this artifact."""
        page = self.manifest["page"]
        if not page["more_available"] or continuation_id != page["continuation_id"]:
            fail("DCC_CONTINUATION_UNKNOWN", "The continuation is not bound to this active page.", status_code=409)
        if not self._ranked_frontier:
            fail("DCC_CONTINUATION_UNRESOLVABLE", "This artifact has no immutable ranked frontier.", status_code=409)
        prior = list(self.private_evidence.get("visible_plan_sha256s", ()))
        return build_manifest(
            self._ranked_frontier,
            binding=self.manifest["binding"],
            manifest_kind=self.manifest["manifest_kind"],
            decision_scope=self.manifest["decision_scope"],
            page_index=page["index"] + 1,
            page_size=page["size"],
            prior_visible_plan_sha256s=prior,
            maximum_visible_for_intent=page["maximum_visible_for_intent"],
            ranking_receipt_sha256=self.private_evidence["ranking_receipt_sha256"],
            factory_validator_authority_sha256=self.private_evidence.get("factory_validator_authority_sha256"),
        )


def validate_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, MANIFEST_REQUIRED_KEYS, MANIFEST_OPTIONAL_KEYS, path="manifest")
    if value["schema"] != MANIFEST_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported manifest schema.")
    require_identifier(value["manifest_id"], path="manifest.manifest_id", prefix="dcc.manifest.")
    require_enum(value["manifest_kind"], MANIFEST_KINDS, path="manifest.manifest_kind")
    require_enum(value["decision_scope"], DECISION_SCOPES, path="manifest.decision_scope")
    if value["decision_scope"] != DECISION_SCOPE_BY_KIND[value["manifest_kind"]]:
        fail("DCC_MANIFEST_SCOPE_INVALID", "manifest_kind and decision_scope must be paired exactly.")
    _binding(value["binding"])
    if "factory_validator_authority_sha256" in value:
        require_digest(value["factory_validator_authority_sha256"], path="manifest.factory_validator_authority_sha256")
    require_digest(value["manifest_context_sha256"], path="manifest.manifest_context_sha256")
    page = value["page"]
    require_exact_keys(page, {"index", "size", "returned", "more_available", "continuation_id", "maximum_visible_for_intent"}, path="manifest.page")
    for field in ("index", "size", "returned", "maximum_visible_for_intent"):
        number = require_type(page[field], int, path=f"manifest.page.{field}")
        if number < 0:
            fail("DCC_SCHEMA_VALUE", f"manifest.page.{field} cannot be negative.")
    default_size, default_maximum = PAGE_DEFAULTS[value["manifest_kind"]]
    if page["size"] < 1 or page["size"] > page["maximum_visible_for_intent"] or page["maximum_visible_for_intent"] > default_maximum:
        fail("DCC_MANIFEST_PAGE_LIMIT", "Manifest page values exceed the V1 bound.")
    require_type(page["more_available"], bool, path="manifest.page.more_available")
    if page["continuation_id"] is not None:
        require_identifier(page["continuation_id"], path="manifest.page.continuation_id", prefix="dcc.more.")
    options = require_list(value["options"], path="manifest.options")
    for option in options:
        _validate_option(option)
    validator_authorities = {
        option["proof"]["factory_validator_authority_sha256"]
        for option in options
        if "factory_validator_authority_sha256" in option["proof"]
    }
    if len(validator_authorities) > 1:
        fail("DCC_MANIFEST_PROOF_INVALID", "Manifest options are bound to mixed Factory validator authorities.")
    if "factory_validator_authority_sha256" in value:
        if validator_authorities != {value["factory_validator_authority_sha256"]}:
            fail("DCC_MANIFEST_PROOF_INVALID", "Manifest option proofs are not bound to the manifest Factory validator authority.")
    elif validator_authorities:
        fail("DCC_MANIFEST_PROOF_INVALID", "A manifest carrying a Factory validator proof must commit its authority digest.")
    option_ids = [option["option_id"] for option in options]
    if len(option_ids) != len(set(option_ids)):
        fail("DCC_MANIFEST_DUPLICATE_OPTION", "Manifest option IDs must be unique.")
    if page["returned"] != len(options) or page["returned"] > page["size"]:
        fail("DCC_MANIFEST_PAGE_INVALID", "Manifest page returned count does not match its option projection.")
    if page["more_available"] is True and page["continuation_id"] is None:
        fail("DCC_MANIFEST_PAGE_INVALID", "A page with more results requires a continuation ID.")
    if page["more_available"] is False and page["continuation_id"] is not None:
        fail("DCC_MANIFEST_PAGE_INVALID", "A terminal page cannot carry a continuation ID.")
    response = value["response_schema"]
    require_exact_keys(response, {"type", "additionalProperties", "required", "properties"}, path="manifest.response_schema")
    if response["type"] != "object" or response["additionalProperties"] is not False or response["required"] != ["option_id"]:
        fail("DCC_RESPONSE_SCHEMA_INVALID", "Manifest responses must be strict option-only objects.")
    properties = response["properties"]
    require_exact_keys(properties, {"option_id", "rationale"}, path="manifest.response_schema.properties")
    require_exact_keys(properties["option_id"], {"type", "enum"}, path="manifest.response_schema.properties.option_id")
    require_exact_keys(properties["rationale"], {"type", "maxLength"}, path="manifest.response_schema.properties.rationale")
    if properties["option_id"]["type"] != "string" or properties["option_id"]["enum"] != option_ids:
        fail("DCC_RESPONSE_SCHEMA_INVALID", "The option enum must exactly match the published options.")
    if properties["rationale"]["type"] != "string" or properties["rationale"]["maxLength"] != 1000:
        fail("DCC_RESPONSE_SCHEMA_INVALID", "The rationale bound is invalid.")
    validate_self_hash(value, "manifest_sha256", code="DCC_MANIFEST_HASH_INVALID")
    return deepcopy(dict(value))


def build_manifest(
    ranked_plans: Sequence[RankedPlan],
    *,
    binding: Mapping[str, Any],
    manifest_kind: str = "WHOLE_BUILD",
    decision_scope: str = "complete_cl15_build",
    page_index: int = 0,
    page_size: int | None = None,
    prior_visible_plan_sha256s: Sequence[str] = (),
    maximum_visible_for_intent: int | None = None,
    card_metadata_by_plan: Mapping[str, Mapping[str, Any]] | None = None,
    identifier_registry: IdentifierRegistry | None = None,
    double_compile_identity_by_plan: Mapping[str, str] | None = None,
    ranking_receipt_sha256: str | None = None,
    factory_validator_authority_sha256: str | None = None,
) -> ManifestArtifact:
    if card_metadata_by_plan is not None:
        if not isinstance(card_metadata_by_plan, Mapping):
            fail("DCC_SCHEMA_TYPE", "card_metadata_by_plan must be an object mapping.")
        if card_metadata_by_plan:
            fail(
                "DCC_CARD_METADATA_UNSUPPORTED",
                "Caller-supplied card metadata is not accepted; public cards are deterministic projections of verified facts.",
            )
    if not ranked_plans:
        fail("DCC_NO_LEGAL_PLANS", "A manifest requires at least one ranked plan.")
    require_enum(manifest_kind, MANIFEST_KINDS, path="manifest_kind")
    require_enum(decision_scope, DECISION_SCOPES, path="decision_scope")
    if decision_scope != DECISION_SCOPE_BY_KIND[manifest_kind]:
        fail("DCC_MANIFEST_SCOPE_INVALID", "manifest_kind and decision_scope must be paired exactly.")
    default_size, default_maximum = PAGE_DEFAULTS[manifest_kind]
    size = page_size if page_size is not None else default_size
    maximum = maximum_visible_for_intent if maximum_visible_for_intent is not None else default_maximum
    if not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 0:
        fail("DCC_SCHEMA_VALUE", "page_index must be a non-negative integer.")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1 or maximum > default_maximum:
        fail("DCC_MANIFEST_PAGE_LIMIT", "maximum_visible_for_intent exceeds the V1 bound.")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1 or size > maximum:
        fail("DCC_MANIFEST_PAGE_LIMIT", "page_size is outside its bounded manifest limit.")
    if maximum < size:
        fail("DCC_MANIFEST_PAGE_LIMIT", "maximum_visible_for_intent must bound page size.")
    bound = _binding(binding)
    if factory_validator_authority_sha256 is not None:
        require_digest(factory_validator_authority_sha256, path="factory_validator_authority_sha256")
    ordered_ranked = tuple(ranked_plans)
    compiler_bindings = {row.plan.proof["compiler_binding"]["compiler_binding_sha256"] for row in ordered_ranked}
    if len(compiler_bindings) != 1:
        fail("DCC_PLAN_COMPILER_BINDING", "All manifest options must come from one deterministic compiler binding.")
    input_plan_hashes = [row.legal_plan_sha256 for row in ordered_ranked]
    if len(input_plan_hashes) != len(set(input_plan_hashes)):
        fail("DCC_MANIFEST_DUPLICATE_PLAN", "A manifest cannot contain the same legal plan twice.")
    # Walk the whole ranked pool in order, keeping the first plan for each
    # distinct card projection and refilling from lower-ranked plans when a
    # later plan would publish an indistinguishable card.  Filtering happens
    # before paging so continuation prefixes stay exact.
    card_projection_by_plan: dict[str, dict[str, Any]] = {}
    card_projection_hashes: dict[str, str] = {}
    distinct_ranked: list[RankedPlan] = []
    substitutions: list[dict[str, str]] = []
    for row in ordered_ranked:
        if len(distinct_ranked) >= maximum:
            break
        projection = _card_metadata(row)
        projection_sha256 = sha256_json(projection)
        prior_plan = card_projection_hashes.get(projection_sha256)
        if prior_plan is not None:
            substitutions.append({"skipped_legal_plan_sha256": row.legal_plan_sha256, "duplicate_of_legal_plan_sha256": prior_plan})
            continue
        card_projection_hashes[projection_sha256] = row.legal_plan_sha256
        card_projection_by_plan[row.legal_plan_sha256] = projection
        distinct_ranked.append(row)
    if len(ordered_ranked) > 1 and len(distinct_ranked) == 1:
        # A single card from a multi-plan pool is a total collapse of semantic
        # distinctness, not a lawfully forced single result.  Incidental
        # duplicates refill; a whole pool that says one thing fails closed.
        fail(
            "DCC_MANIFEST_CARD_NOT_DISTINCT",
            "Every legal plan in the ranked pool publishes the same public card projection; semantic authority must distinguish them before publication.",
            details={"skipped_legal_plan_sha256s": sorted({row["skipped_legal_plan_sha256"] for row in substitutions})},
        )
    all_plan_hashes = [row.legal_plan_sha256 for row in distinct_ranked]
    visible_limit = min(maximum, len(distinct_ranked))
    visible_ranked = distinct_ranked[page_index * size: min((page_index + 1) * size, visible_limit)]
    if not visible_ranked:
        fail("DCC_MANIFEST_PAGE_EMPTY", "The requested page has no visible legal options.", status_code=409)
    if prior_visible_plan_sha256s:
        prior = list(prior_visible_plan_sha256s)
        expected_prior = all_plan_hashes[: page_index * size]
        if prior != expected_prior:
            fail("DCC_MANIFEST_CONTINUATION_STALE", "The continuation does not name the exact prior visible plans.", status_code=409)
    else:
        prior = all_plan_hashes[: page_index * size]
    page_request = {"index": page_index, "size": size, "prior_visible_plan_sha256s": prior}
    context_hash = derive_manifest_context_digest(bound, manifest_kind, decision_scope, page_request)
    registry = identifier_registry or IdentifierRegistry()
    manifest_id, _ = derive_manifest_identifier(context_hash, [row.legal_plan_sha256 for row in visible_ranked], registry=registry)
    if ranking_receipt_sha256 is None:
        ranking_receipt_sha256 = sha256_json([row.private_dict() for row in ordered_ranked])
    else:
        require_digest(ranking_receipt_sha256, path="ranking_receipt_sha256")
    options: list[dict[str, Any]] = []
    option_to_plan: dict[str, LegalPlan] = {}
    for row in visible_ranked:
        option_id, _ = derive_option_identifier(context_hash, row.legal_plan_sha256, manifest_kind, decision_scope, registry=registry)
        option_to_plan[option_id] = validate_legal_plan(row.plan)
        card = deepcopy(card_projection_by_plan[row.legal_plan_sha256])
        proof = {
            "legal_plan_sha256": row.legal_plan_sha256,
            "validation_receipt_sha256": row.plan.proof["final_validator_receipt"]["receipt_sha256"],
            "double_compile_identity_sha256": (double_compile_identity_by_plan or {}).get(row.legal_plan_sha256, sha256_json(row.plan.plan_payload)),
        }
        if factory_validator_authority_sha256 is not None:
            proof["factory_validator_authority_sha256"] = factory_validator_authority_sha256
        for field in PROOF_REQUIRED_KEYS:
            require_digest(proof[field], path=f"manifest.option.proof.{field}")
        if "factory_validator_authority_sha256" in proof:
            require_digest(proof["factory_validator_authority_sha256"], path="manifest.option.proof.factory_validator_authority_sha256")
        if proof["double_compile_identity_sha256"] != row.legal_plan_sha256:
            fail("DCC_MANIFEST_PROOF_INVALID", "The manifest double-compile identity is not bound to the compiled plan.")
        card["fit_summary"] = qualitative_fit_summary(row, ranking_receipt_sha256=ranking_receipt_sha256)
        card["proof"] = proof
        card["option_id"] = option_id
        options.append(card)
    # Preserve exact rank order in the public array.  Opaque IDs are derived
    # deterministically, but they do not replace ranking order as presentation
    # order.
    ordered_option_to_plan = {option["option_id"]: option_to_plan[option["option_id"]] for option in options}
    more_available = (page_index + 1) * size < visible_limit
    ranked_view_sha256 = sha256_json(all_plan_hashes)
    continuation_id = None
    if more_available:
        continuation_id, _ = derive_continuation_identifier(context_hash, page_index + 1, prior + [row.legal_plan_sha256 for row in visible_ranked], ranked_view_sha256, registry=registry)
    unsigned = {
        "schema": MANIFEST_SCHEMA,
        "manifest_id": manifest_id,
        "manifest_kind": manifest_kind,
        "decision_scope": decision_scope,
        "binding": bound,
        "manifest_context_sha256": context_hash,
        "page": {
            "index": page_index,
            "size": size,
            "returned": len(options),
            "more_available": more_available,
            "continuation_id": continuation_id,
            "maximum_visible_for_intent": maximum,
        },
        "options": options,
        "response_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["option_id"],
            "properties": {
                "option_id": {"type": "string", "enum": [option["option_id"] for option in options]},
                "rationale": {"type": "string", "maxLength": 1000},
            },
        },
    }
    if factory_validator_authority_sha256 is not None:
        unsigned["factory_validator_authority_sha256"] = factory_validator_authority_sha256
    public = {**unsigned, "manifest_sha256": sha256_json(unsigned)}
    evidence = {
        "schema": "TianxiaFoundry.PrivateManifestEvidence.v1",
        "visibility": "FACTORY_INTERNAL",
        "manifest_sha256": public["manifest_sha256"],
        "ranked_view_sha256": ranked_view_sha256,
        "ranking_receipt_sha256": ranking_receipt_sha256,
        "factory_validator_authority_sha256": factory_validator_authority_sha256,
        "option_to_plan": {option_id: plan.plan_payload for option_id, plan in ordered_option_to_plan.items()},
        # Retain the cumulative prefix so the next page can prove that no
        # continuation skipped or duplicated a previously exposed plan.
        "visible_plan_sha256s": prior + [row.legal_plan_sha256 for row in visible_ranked],
        # A collapse in card distinctness stays visible in evidence even
        # though the run continues with the refilled page.
        "card_distinctness_substitutions": substitutions,
    }
    return ManifestArtifact(public, ordered_option_to_plan, evidence, ordered_ranked, size)


@dataclass(frozen=True)
class AcceptedOption:
    manifest_sha256: str
    option_id: str
    legal_plan_sha256: str
    plan: LegalPlan
    rationale_sha256: str | None


def accept_option(
    artifact: ManifestArtifact,
    response: Mapping[str, Any],
    *,
    expected_manifest_sha256: str | None = None,
    current_manifest_sha256: str | None = None,
    consumed_option_ids: Iterable[str] = (),
    expected_project_revision: int | None = None,
    current_project_revision: int | None = None,
) -> AcceptedOption:
    """Resolve a strict option-only response without mutating server state."""

    if not isinstance(artifact, ManifestArtifact):
        fail("DCC_MANIFEST_ARTIFACT_REQUIRED", "Option acceptance requires the private server-side artifact.", status_code=409)
    if expected_manifest_sha256 is not None:
        require_digest(expected_manifest_sha256, path="expected_manifest_sha256")
    if current_manifest_sha256 is not None:
        require_digest(current_manifest_sha256, path="current_manifest_sha256")
    if expected_manifest_sha256 is not None and expected_manifest_sha256 != artifact.manifest_sha256:
        fail("DCC_MANIFEST_STALE", "The expected manifest is no longer active.", status_code=409)
    if current_manifest_sha256 is not None and current_manifest_sha256 != artifact.manifest_sha256:
        fail("DCC_MANIFEST_STALE", "The manifest is stale.", status_code=409)
    bound_revision = artifact.manifest["binding"]["project_revision"]
    if expected_project_revision is not None and expected_project_revision != bound_revision:
        fail("DCC_MANIFEST_STALE", "The expected project revision is not bound to this manifest.", status_code=409)
    if current_project_revision is not None and current_project_revision != bound_revision:
        fail("DCC_MANIFEST_STALE", "The manifest is bound to a stale project revision.", status_code=409)
    if expected_project_revision is not None and current_project_revision is not None and expected_project_revision != current_project_revision:
        fail("DCC_MANIFEST_STALE", "The project revision is stale.", status_code=409)
    if not isinstance(response, Mapping):
        fail("DCC_SELECTION_MALFORMED", "A selection response must be an object.", status_code=409)
    require_exact_keys(response, {"option_id"}, {"rationale"}, path="option response")
    option_id = require_identifier(response["option_id"], path="option response.option_id", prefix="dcc.opt.")
    if "rationale" in response:
        rationale = response["rationale"]
        require_string(rationale, path="option response.rationale", nonempty=False, max_length=1000)
    else:
        rationale = None
    consumed = {require_identifier(item, path="consumed_option_ids[]", prefix="dcc.opt.") for item in consumed_option_ids}
    if option_id in consumed:
        fail("DCC_OPTION_CONSUMED", "The option has already been consumed.", status_code=409)
    if option_id not in artifact.option_to_plan:
        fail("DCC_OPTION_UNKNOWN", "The option is not present in the active manifest.", status_code=409)
    plan = artifact.plan_for_option(option_id)
    return AcceptedOption(
        manifest_sha256=artifact.manifest_sha256,
        option_id=option_id,
        legal_plan_sha256=plan.legal_plan_sha256,
        plan=plan,
        rationale_sha256=sha256_json({"rationale": rationale}) if rationale is not None else None,
    )


def public_manifest_json(artifact: ManifestArtifact) -> str:
    return artifact.to_json()


def continue_manifest(artifact: ManifestArtifact, continuation_id: str) -> ManifestArtifact:
    if not isinstance(artifact, ManifestArtifact):
        fail("DCC_MANIFEST_ARTIFACT_REQUIRED", "Continuation requires the private server-side artifact.", status_code=409)
    require_identifier(continuation_id, path="continuation_id", prefix="dcc.more.")
    return artifact.next_page(continuation_id)


def option_only_response_schema(artifact: ManifestArtifact) -> dict[str, Any]:
    return deepcopy(artifact.manifest["response_schema"])
