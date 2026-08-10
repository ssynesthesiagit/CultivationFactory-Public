"""Normalize delegated character responses at the Factory trust boundary.

The Manual Chat response is intentionally a semantic selector document.  It
may identify records and provide the few typed decisions which the installed
authority cannot derive, but it may not author Stage 1 bindings or Stage 2
events.  This module keeps that distinction explicit:

* preferred responses are parsed into semantic acquisition objects;
* historical v1/v2 responses are retained as exact compatibility evidence and
  projected into the same semantic acquisition objects; and
* legality, record ownership, event ordering, channels, and effective CLs are
  resolved by the authority/materialization services after this boundary.

No live catalog lookup or prose interpretation belongs here.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.core import FoundryError, sha256_json


SCHEMA = "TianxiaFoundry.DelegatedSelectionIntent.v1"
RESPONSE_SCHEMA = "TianxiaFoundry.DelegatedSelectionIntentResponse.v1"

PATH_SLOT = "path_choice"
METHOD_SLOT = "method_choice"
FOUNDATION_SLOT = "foundation_choice"
PLANNING_SLOTS = frozenset(
    {"sphere_priorities", "advancement_skeleton", "insight_priorities", "item_priorities"}
)

_SLOT_ALIASES = {
    "path_ids": PATH_SLOT,
    "path_choice_ids": PATH_SLOT,
    "selected_path_ids": PATH_SLOT,
    "method_id": METHOD_SLOT,
    "method_choice_id": METHOD_SLOT,
    "foundation_id": FOUNDATION_SLOT,
    "foundation_choice_id": FOUNDATION_SLOT,
    "subpath_id": "subpath_choice",
    "subpath_choice_id": "subpath_choice",
    "sphere_ids": "sphere_priorities",
    "sphere_choice_ids": "sphere_priorities",
    "sphere_priority_ids": "sphere_priorities",
    "insight_ids": "insight_priorities",
    "insight_choice_ids": "insight_priorities",
    "insight_priority_ids": "insight_priorities",
    "talent_ids": "advancement_skeleton",
    "talent_choice_ids": "advancement_skeleton",
    "offered_talent_priority_ids": "advancement_skeleton",
    "item_ids": "item_priorities",
    "item_choice_ids": "item_priorities",
    "item_priority_ids": "item_priorities",
}

_KNOWN_SLOTS = frozenset(
    {
        PATH_SLOT,
        METHOD_SLOT,
        FOUNDATION_SLOT,
        "subpath_choice",
        "background_choice",
        "background_sphere_choice",
        "background_talent_choice",
        "origin_insight_choice",
        *PLANNING_SLOTS,
    }
)

_HISTORICAL_SLOT_KINDS = {
    "path_acquisition": PATH_SLOT,
    "method_acquisition": METHOD_SLOT,
    "method_activation": METHOD_SLOT,
    "foundation_acquisition": FOUNDATION_SLOT,
    "foundation_expression": FOUNDATION_SLOT,
    "foundation_stage": FOUNDATION_SLOT,
    "background_acquisition": "background_choice",
    "background_sphere_acquisition": "background_sphere_choice",
    "background_talent_acquisition": "background_talent_choice",
    "origin_insight_acquisition": "origin_insight_choice",
    "origin_insight_selection": "origin_insight_choice",
    "subpath_acquisition": "subpath_choice",
    "tradition_acquisition": "subpath_choice",
    "item_acquisition": "item_priorities",
    "equipment_acquisition": "item_priorities",
    "sect_trial_sphere_acquisition": "sphere_priorities",
    "ai_bootstrap_sphere_acquisition": "sphere_priorities",
    "sphere_acquisition": "sphere_priorities",
    "sect_trial_talent_acquisition": "advancement_skeleton",
    "ai_bootstrap_talent_acquisition": "advancement_skeleton",
    "level_talent_acquisition": "advancement_skeleton",
    "new_sphere_bonus_talent_acquisition": "advancement_skeleton",
    "talent_acquisition": "advancement_skeleton",
    "cultivation_insight_acquisition": "insight_priorities",
    "insight_acquisition": "insight_priorities",
}

_SPHERE_KINDS = frozenset(
    {"sect_trial_sphere_acquisition", "ai_bootstrap_sphere_acquisition", "sphere_acquisition"}
)
_FREE_TALENT_KINDS = frozenset(
    {
        "sect_trial_talent_acquisition",
        "ai_bootstrap_talent_acquisition",
        "new_sphere_bonus_talent_acquisition",
    }
)
_ORDINARY_TALENT_KINDS = frozenset({"level_talent_acquisition", "talent_acquisition"})
_INSIGHT_KINDS = frozenset({"cultivation_insight_acquisition", "insight_acquisition"})


def empty_acquisition_intent() -> dict[str, Any]:
    """Return the only preferred acquisition shape."""

    return {
        "sphere_free_talent_pairs": [],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }


def _ordered_unique(values: list[str], *, field: str) -> list[str]:
    if len(values) != len(set(values)):
        raise FoundryError(
            "CG1_DELEGATED_DUPLICATE_CHOICE",
            "A delegated response repeats an ID; malformed IDs are not silently deduplicated.",
            details={"field": field, "values": values},
            status_code=409,
        )
    return values


def _strict_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FoundryError(
            "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
            f"{field} must be an array of non-empty stable IDs.",
            details={"field": field},
            status_code=422,
        )
    return _ordered_unique(list(value), field=field)


def _legacy_values(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _slot_for(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _SLOT_ALIASES.get(value, value if value in _KNOWN_SLOTS else None)


def _canonical_kind(value: Any) -> Any:
    return "cultivation_insight_acquisition" if value == "insight_acquisition" else value


def _descriptive_fields(plan: Mapping[str, Any]) -> dict[str, Any]:
    candidates: dict[str, list[str]] = {"name": [], "concept": []}
    surfaces: list[tuple[str, Mapping[str, Any]]] = []
    for key in ("owner_descriptive_fields", "descriptive_fields"):
        value = plan.get(key)
        if isinstance(value, Mapping):
            surfaces.append((key, value))
    # A short-lived producer put these at the top level.  It remains historical
    # input compatibility only and is never emitted by the preferred schema.
    if "name" in plan or "concept" in plan:
        surfaces.append(("top_level_descriptive_fields", plan))
    for _source, raw in surfaces:
        identity = raw.get("identity") if isinstance(raw.get("identity"), Mapping) else {}
        name = identity.get("name", raw.get("name"))
        concept = raw.get("concept", raw.get("character_concept"))
        if isinstance(name, str) and name.strip():
            candidates["name"].append(name.strip())
        if isinstance(concept, str) and concept.strip():
            candidates["concept"].append(concept.strip())
    for field, values in candidates.items():
        if len(set(values)) > 1:
            raise FoundryError(
                "CG1_DELEGATED_AUTHORITY_CONFLICT",
                f"The response supplied conflicting descriptive {field} values.",
                details={"field": field, "representations": values},
                status_code=409,
            )
    return {"name": candidates["name"][0] if candidates["name"] else None, "concept": candidates["concept"][0] if candidates["concept"] else None}


def _extract_legacy_slots(plan: Mapping[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """Collect legacy slot representations without changing multiplicity."""

    selected: dict[str, list[list[str]]] = {}
    priorities: dict[str, list[list[str]]] = {}
    stage1: dict[str, list[list[str]]] = {}

    def add(target: dict[str, list[list[str]]], slot_id: str | None, value: Any) -> None:
        if not slot_id:
            return
        target.setdefault(slot_id, []).append(_legacy_values(value))

    def add_mapping(target: dict[str, list[list[str]]], value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        for key, raw in value.items():
            add(target, _slot_for(key), raw)

    direct_intent = plan.get("selection_intent")
    if not isinstance(direct_intent, Mapping):
        direct_intent = plan.get("selection_intent_by_slot")
    if isinstance(direct_intent, Mapping):
        add_mapping(selected, direct_intent.get("by_slot") if isinstance(direct_intent.get("by_slot"), Mapping) else direct_intent)

    direct = plan.get("delegated_choice_selections")
    if isinstance(direct, Mapping):
        add_mapping(selected, direct.get("by_slot") or direct.get("slot_selections"))
        add_mapping(selected, direct)

    priority = plan.get("catalog_priority_order")
    if not isinstance(priority, Mapping):
        nested = plan.get("stage2_proposal")
        priority = nested.get("catalog_priority_order") if isinstance(nested, Mapping) else None
    add_mapping(priorities, priority)

    stage1_response = plan.get("stage1_response")
    payload = stage1_response.get("response_payload") if isinstance(stage1_response, Mapping) else None
    decisions = payload.get("decisions") if isinstance(payload, Mapping) else []
    if isinstance(decisions, list):
        for decision in decisions:
            if not isinstance(decision, Mapping) or decision.get("state") != "selected":
                continue
            add(stage1, _slot_for(decision.get("slot_id")), decision.get("choice_ids"))

    # Stage 2 rows are compatibility evidence and are intentionally collected
    # separately by the caller.  They must not silently turn a priority into an
    # acquisition in the preferred path.
    def merge(target: dict[str, list[list[str]]], *, name: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for slot_id, representations in target.items():
            nonempty = [values for values in representations if values]
            if len({tuple(values) for values in nonempty}) > 1:
                raise FoundryError(
                    "CG1_DELEGATED_AUTHORITY_CONFLICT",
                    "The historical response supplied conflicting IDs for one delegated slot.",
                    details={"slot_id": slot_id, "source": name, "representations": representations},
                    status_code=409,
                )
            result[slot_id] = list(nonempty[0] if nonempty else (representations[-1] if representations else []))
        return result

    return merge(selected, name="selection"), merge(priorities, name="planning"), merge(stage1, name="stage1")


def _historical_rows(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    proposal = plan.get("stage2_proposal")
    if not isinstance(proposal, Mapping) or not isinstance(proposal.get("choices"), list):
        return []
    return [deepcopy(row) for row in proposal["choices"] if isinstance(row, Mapping)]


def _historical_milestone_id(row: Mapping[str, Any], *, envelope: Mapping[str, Any]) -> str | None:
    """Map one historical resolution to exactly one frozen milestone."""
    parameters = row.get("parameters") if isinstance(row.get("parameters"), Mapping) else {}
    explicit = row.get("milestone_id") or parameters.get("milestone_id")
    advertised = {
        value.get("milestone_id"): value
        for value in envelope.get("advancement_choice_milestones") or []
        if isinstance(value, Mapping) and isinstance(value.get("milestone_id"), str)
    }
    if isinstance(explicit, str) and explicit in advertised:
        return explicit
    effective_cl = row.get("effective_cl")
    candidates = [
        milestone
        for milestone in advertised.values()
        if isinstance(effective_cl, int)
        and milestone.get("effective_cl", milestone.get("cl")) == effective_cl
    ]
    feature_record_id = (
        row.get("feature_record_id")
        or parameters.get("feature_record_id")
        # Established full-row producers used the advancement feature itself
        # as record_id for an ability-score/Insight milestone.  Treat that
        # exact frozen ID as feature identity, never as a fuzzy path label.
        or (row.get("record_id") if isinstance(row.get("record_id"), str) else None)
    )
    if isinstance(feature_record_id, str):
        feature_candidates = [
            milestone for milestone in candidates
            if milestone.get("feature_record_id") == feature_record_id
        ]
        if len(feature_candidates) == 1:
            return str(feature_candidates[0]["milestone_id"])
        if feature_candidates:
            candidates = feature_candidates
    if len(candidates) == 1:
        return str(candidates[0]["milestone_id"])
    if candidates:
        raise FoundryError(
            "CG1_HISTORICAL_MILESTONE_AMBIGUOUS",
            "A historical milestone resolution cannot be mapped unambiguously to frozen source authority.",
            details={
                "effective_cl": effective_cl,
                "record_id": row.get("record_id"),
                "milestone_ids": sorted(str(value["milestone_id"]) for value in candidates),
            },
            status_code=422,
        )
    return None


def _historical_semantics(rows: list[dict[str, Any]], *, envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Project established full rows into the preferred semantic buckets."""

    result = empty_acquisition_intent()
    pending_spheres: list[str] = []

    for index, row in enumerate(rows):
        kind = _canonical_kind(row.get("kind"))
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        parameters = row.get("parameters") if isinstance(row.get("parameters"), Mapping) else {}
        if kind == "__free_sphere_talent_pair__":
            sphere_id = row.get("sphere_id") or parameters.get("sphere_id")
            if not isinstance(sphere_id, str):
                sphere_id = pending_spheres.pop(0) if pending_spheres else None
            result["sphere_free_talent_pairs"].append(
                {"sphere_id": sphere_id, "talent_id": record_id}
            )
            continue
        if kind in _SPHERE_KINDS:
            pending_spheres.append(record_id)
            continue
        if kind in _FREE_TALENT_KINDS:
            sphere_id = row.get("sphere_id") or parameters.get("sphere_id")
            if not isinstance(sphere_id, str) and pending_spheres:
                sphere_id = pending_spheres.pop(0)
            elif isinstance(sphere_id, str) and sphere_id in pending_spheres:
                pending_spheres.remove(sphere_id)
            result["sphere_free_talent_pairs"].append(
                {"sphere_id": sphere_id, "talent_id": record_id}
            )
            continue
        if kind in _ORDINARY_TALENT_KINDS:
            result["ordinary_talent_ids"].append(record_id)
            continue
        if kind in _INSIGHT_KINDS:
            effective_cl = row.get("effective_cl")
            milestone_id = _historical_milestone_id(row, envelope=envelope)
            typed_parameters = {
                key: deepcopy(parameters[key])
                for key in ("ability", "amount", "repeat_index")
                if key in parameters
            }
            occurrence: dict[str, Any] = {
                "insight_id": record_id,
                "milestone_id": milestone_id,
            }
            if typed_parameters:
                occurrence["parameters"] = typed_parameters
            result["insight_occurrences"].append(occurrence)
            continue
        # Explicit historical acquisition rows for later features are not part
        # of the preferred acquisition surface.  They remain in raw evidence and
        # are compared by Stage 2 compatibility validation.
        _ = index
    return result


def _legacy_acquisition_rows(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = plan.get("acquisition_intent")
    if raw is None:
        raw = plan.get("acquisition_plan")
    if raw is None and isinstance(plan.get("selection_intent"), Mapping):
        selection = plan["selection_intent"]
        raw = selection.get("acquisition_intent") or selection.get("acquisitions")
    if isinstance(raw, list):
        return [deepcopy(row) for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping):
        rows = raw.get("stage2_rows") or raw.get("rows")
        if isinstance(rows, list):
            return [deepcopy(row) for row in rows if isinstance(row, Mapping)]
    return []


def _semantic_from_legacy_acquisition_rows(rows: list[dict[str, Any]], *, envelope: Mapping[str, Any]) -> dict[str, Any]:
    # Some old producers used a list of typed rows in acquisition_intent.  It is
    # accepted only as historical input and projected immediately into the same
    # semantic object used by the preferred response.
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        kind = _canonical_kind(row.get("kind"))
        if kind not in _HISTORICAL_SLOT_KINDS and kind != "__free_sphere_talent_pair__":
            raise FoundryError(
                "CG1_HISTORICAL_RESPONSE_UNSUPPORTED",
                "The historical acquisition row kind is not a supported compatibility form.",
                details={"kind": kind},
                status_code=422,
            )
        normalized_rows.append(row)
    return _historical_semantics(normalized_rows, envelope=envelope)


def _acquisition_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return canonical_semantic_acquisition(left) == canonical_semantic_acquisition(right)


def canonical_semantic_acquisition(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy only the supported semantic acquisition fields in stable order."""

    value = value if isinstance(value, Mapping) else {}
    pairs: list[dict[str, Any]] = []
    for pair in value.get("sphere_free_talent_pairs") or []:
        if not isinstance(pair, Mapping):
            continue
        pairs.append(
            {
                "sphere_id": pair.get("sphere_id"),
                "talent_id": pair.get("talent_id"),
            }
        )
    ordinary = list(value.get("ordinary_talent_ids") or [])
    insights: list[dict[str, Any]] = []
    for occurrence in value.get("insight_occurrences") or []:
        if not isinstance(occurrence, Mapping):
            continue
        item: dict[str, Any] = {
            "insight_id": occurrence.get("insight_id"),
            "milestone_id": occurrence.get("milestone_id"),
        }
        if "parameters" in occurrence:
            item["parameters"] = deepcopy(occurrence.get("parameters") or {})
        insights.append(item)
    return {
        "sphere_free_talent_pairs": pairs,
        "ordinary_talent_ids": ordinary,
        "insight_occurrences": insights,
    }


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class CanonicalSelectionIntent:
    """Immutable server-bound semantic selection intent."""

    document: Mapping[str, Any]

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "CanonicalSelectionIntent":
        return cls(_freeze(deepcopy(dict(document))))

    @property
    def intent_hash(self) -> str:
        return str(self.document.get("intent_sha256") or "")

    def as_dict(self) -> dict[str, Any]:
        def thaw(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {key: thaw(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [thaw(item) for item in value]
            return value

        return thaw(self.document)


def _preferred_acquisition(plan: Mapping[str, Any]) -> dict[str, Any]:
    raw = plan.get("acquisition_intent")
    if not isinstance(raw, Mapping):
        raise FoundryError(
            "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
            "Preferred acquisition_intent must be one semantic object, not a list of backend rows.",
            status_code=422,
        )
    expected = {"sphere_free_talent_pairs", "ordinary_talent_ids", "insight_occurrences"}
    unexpected = sorted(set(raw) - expected)
    missing = sorted(expected - set(raw))
    if unexpected or missing:
        raise FoundryError(
            "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
            "Preferred acquisition_intent must contain exactly the three supported semantic arrays.",
            details={"unexpected": unexpected, "missing": missing},
            status_code=422,
        )
    pairs: list[dict[str, Any]] = []
    if not isinstance(raw["sphere_free_talent_pairs"], list):
        raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "sphere_free_talent_pairs must be an array.", status_code=422)
    seen_spheres: set[str] = set()
    seen_talents: set[str] = set()
    for index, pair in enumerate(raw["sphere_free_talent_pairs"]):
        if not isinstance(pair, Mapping) or set(pair) != {"sphere_id", "talent_id"}:
            raise FoundryError(
                "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
                "Each Sphere free-Talent acquisition must be exactly {sphere_id, talent_id}; planner event metadata is forbidden.",
                details={"index": index},
                status_code=422,
            )
        sphere_id = pair.get("sphere_id")
        talent_id = pair.get("talent_id")
        if not isinstance(sphere_id, str) or not sphere_id or not isinstance(talent_id, str) or not talent_id:
            raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Sphere/free-Talent IDs must be non-empty strings.", details={"index": index}, status_code=422)
        if sphere_id in seen_spheres or talent_id in seen_talents:
            raise FoundryError("CG1_DELEGATED_DUPLICATE_CHOICE", "Sphere/free-Talent acquisitions must be unique.", details={"index": index, "sphere_id": sphere_id, "talent_id": talent_id}, status_code=409)
        seen_spheres.add(sphere_id)
        seen_talents.add(talent_id)
        pairs.append({"sphere_id": sphere_id, "talent_id": talent_id})

    ordinary = _strict_string_list(raw["ordinary_talent_ids"], field="acquisition_intent.ordinary_talent_ids")
    if not isinstance(raw["insight_occurrences"], list):
        raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "insight_occurrences must be an array.", status_code=422)
    insights: list[dict[str, Any]] = []
    seen_occurrences: set[tuple[Any, Any]] = set()
    for index, occurrence in enumerate(raw["insight_occurrences"]):
        if not isinstance(occurrence, Mapping):
            raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Each Insight occurrence must be an object.", details={"index": index}, status_code=422)
        unexpected_occurrence = sorted(set(occurrence) - {"insight_id", "milestone_id", "parameters"})
        if unexpected_occurrence or set(occurrence) - {"insight_id", "milestone_id", "parameters"}:
            raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight occurrences may contain only insight_id, milestone_id, and typed parameters.", details={"index": index, "unexpected": unexpected_occurrence}, status_code=422)
        insight_id = occurrence.get("insight_id")
        milestone_id = occurrence.get("milestone_id")
        if not isinstance(insight_id, str) or not insight_id or not isinstance(milestone_id, str) or not milestone_id:
            raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight occurrences require non-empty insight_id and milestone_id.", details={"index": index}, status_code=422)
        key = (insight_id, milestone_id)
        if key in seen_occurrences:
            raise FoundryError("CG1_DELEGATED_DUPLICATE_CHOICE", "An Insight occurrence is repeated for one milestone.", details={"index": index, "insight_id": insight_id, "milestone_id": milestone_id}, status_code=409)
        seen_occurrences.add(key)
        item = {"insight_id": insight_id, "milestone_id": milestone_id}
        if "parameters" in occurrence:
            if not isinstance(occurrence["parameters"], Mapping):
                raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight parameters must be a typed object.", details={"index": index}, status_code=422)
            unsupported_parameters = sorted(set(occurrence["parameters"]) - {"ability"})
            if unsupported_parameters:
                raise FoundryError(
                    "CG1_INSIGHT_PARAMETER_OUT_OF_AUTHORITY",
                    "Preferred Insight parameters may contain only a source-advertised typed ability choice.",
                    details={"index": index, "unsupported_parameters": unsupported_parameters},
                    status_code=422,
                )
            item["parameters"] = deepcopy(dict(occurrence["parameters"]))
        insights.append(item)
    return {
        "sphere_free_talent_pairs": pairs,
        "ordinary_talent_ids": ordinary,
        "insight_occurrences": insights,
    }


def normalize_selection_intent(
    plan: Mapping[str, Any],
    *,
    request_sha256: str,
    delegated_envelope: Mapping[str, Any],
    project: Mapping[str, Any],
    target_cl: int,
) -> CanonicalSelectionIntent:
    """Normalize preferred or historical response semantics.

    The ``target_cl`` argument is a server binding used in the immutable intent
    document; it is never read from preferred response authority.  Historical
    rows are copied under ``historical_stage2_rows`` solely as compatibility
    evidence and are never returned as the materialized proposal.
    """

    if not isinstance(plan, Mapping):
        raise FoundryError("CG1_PLAN_SCHEMA_INVALID", "The delegated response must be one JSON object.", status_code=422)
    preferred = plan.get("schema") == RESPONSE_SCHEMA
    if preferred:
        selection = plan.get("selection_intent")
        if not isinstance(selection, Mapping) or set(selection) != {"by_slot"} or not isinstance(selection.get("by_slot"), Mapping):
            raise FoundryError("CG1_PREFERRED_RESPONSE_SHAPE_INVALID", "selection_intent.by_slot is required and no other selection fields are supported.", status_code=422)
        selected: dict[str, list[str]] = {}
        planning: dict[str, list[str]] = {}
        for slot_id, raw in selection["by_slot"].items():
            if not isinstance(slot_id, str) or slot_id not in _KNOWN_SLOTS:
                raise FoundryError("CG1_PREFERRED_RESPONSE_SELECTION_INVALID", "The response named an unknown delegated slot.", details={"slot_id": slot_id}, status_code=422)
            values = _strict_string_list(raw, field=f"selection_intent.by_slot.{slot_id}")
            (planning if slot_id in PLANNING_SLOTS else selected)[slot_id] = values
        acquisition = _preferred_acquisition(plan)
        historical_rows: list[dict[str, Any]] = []
        response_form = "preferred"
        bounded = deepcopy(plan.get("bounded_choices") or {})
    else:
        selected, planning, stage1_selected = _extract_legacy_slots(plan)
        historical_rows = _historical_rows(plan)
        historical_acquisition = _historical_semantics(historical_rows, envelope=delegated_envelope)
        explicit_rows = _legacy_acquisition_rows(plan)
        if explicit_rows:
            explicit_acquisition = _semantic_from_legacy_acquisition_rows(explicit_rows, envelope=delegated_envelope)
            if historical_rows and not _acquisition_equal(historical_acquisition, explicit_acquisition):
                raise FoundryError(
                    "CG1_DELEGATED_AUTHORITY_CONFLICT",
                    "Historical acquisition representations do not describe the same semantic intent.",
                    details={"historical": historical_acquisition, "explicit": explicit_acquisition},
                    status_code=409,
                )
            acquisition = explicit_acquisition
        else:
            acquisition = historical_acquisition
        # Stage 1 declarations are owner/delegated bindings.  They may confirm
        # a historical final row set, but can never be used to erase a value.
        for slot_id, values in stage1_selected.items():
            if not values:
                continue
            if slot_id in selected and selected[slot_id] != values:
                if not set(values).issubset(selected[slot_id]):
                    raise FoundryError("CG1_DELEGATED_AUTHORITY_CONFLICT", "A historical Stage 1 selection conflicts with the accepted selection.", details={"slot_id": slot_id, "stage1": values, "selected": selected[slot_id]}, status_code=409)
            else:
                selected[slot_id] = values
        # Historical Stage 2 rows are a mechanical representation.  Record the
        # IDs in planning buckets only when no explicit priority representation
        # exists; the materializer still uses ``acquisition`` as its authority.
        for row in historical_rows:
            slot_id = _HISTORICAL_SLOT_KINDS.get(_canonical_kind(row.get("kind")))
            record_id = row.get("record_id")
            if not slot_id or not isinstance(record_id, str):
                continue
            target = planning if slot_id in PLANNING_SLOTS else selected
            if slot_id not in target:
                target[slot_id] = []
            if record_id not in target[slot_id]:
                target[slot_id].append(record_id)
        bounded = {}
        for key in ("bounded_choices", "bounded_choice", "choice_parameters"):
            value = plan.get(key)
            if isinstance(value, Mapping):
                if bounded and bounded != value:
                    raise FoundryError("CG1_DELEGATED_AUTHORITY_CONFLICT", "Historical bounded-choice representations conflict.", details={"field": key}, status_code=409)
                bounded = deepcopy(dict(value))
        # Convert every genuinely non-derivable historical value into the same
        # canonical bounded/semantic surfaces used by preferred responses.  The
        # raw rows remain evidence only and are never consulted by Stage 2
        # derivation.
        historical_by_kind = {
            kind: [row for row in historical_rows if row.get("kind") == kind]
            for kind in {
                "starting_state",
                "background_acquisition",
                "ability_score_change",
                "level_advance",
                "item_acquisition",
                "equipment_acquisition",
            }
        }
        starting_rows = historical_by_kind["starting_state"]
        if "ability_scores" not in bounded and starting_rows:
            scores = (starting_rows[0].get("parameters") or {}).get("ability_scores")
            if isinstance(scores, Mapping):
                bounded["ability_scores"] = deepcopy(dict(scores))
        background_rows = historical_by_kind["background_acquisition"]
        if background_rows:
            background_parameters = background_rows[0].get("parameters") or {}
            if "background_ability" not in bounded and isinstance(background_parameters.get("ability"), str):
                bounded["background_ability"] = background_parameters["ability"]
            if "background_ability_amount" not in bounded and type(background_parameters.get("amount")) is int:
                bounded["background_ability_amount"] = background_parameters["amount"]

        milestone_changes = dict(bounded.get("ability_score_changes_by_milestone_id") or {})
        progression_by_cl = dict(bounded.get("path_progression_by_cl") or {})
        advertised_progressions = {
            int(row["cl"]): list(row.get("path_ids") or [])
            for row in delegated_envelope.get("path_progression_choices") or []
            if isinstance(row, Mapping) and isinstance(row.get("cl"), int)
        }
        for row in historical_by_kind["ability_score_change"]:
            milestone_id = _historical_milestone_id(row, envelope=delegated_envelope)
            deltas = (row.get("parameters") or {}).get("deltas")
            if not milestone_id or not isinstance(deltas, Mapping):
                raise FoundryError(
                    "CG1_HISTORICAL_MILESTONE_UNRESOLVED",
                    "A historical ability-score resolution lacks a stable source milestone or typed deltas.",
                    details={"row": deepcopy(row)},
                    status_code=422,
                )
            milestone_changes[milestone_id] = {"deltas": deepcopy(dict(deltas))}
        for row in historical_by_kind["level_advance"]:
            effective_cl = row.get("effective_cl")
            record_id = row.get("record_id")
            if not isinstance(effective_cl, int) or not isinstance(record_id, str):
                continue
            available = advertised_progressions.get(effective_cl) or []
            historical_path = record_id.split(".feature.", 1)[0] if ".feature." in record_id else ""
            if historical_path in available:
                progression_by_cl[str(effective_cl)] = historical_path
            elif len(available) == 1:
                progression_by_cl[str(effective_cl)] = available[0]
            elif len(available) > 1:
                raise FoundryError(
                    "CG1_HISTORICAL_PATH_PROGRESSION_AMBIGUOUS",
                    "A historical Path progression row cannot be mapped to one frozen Path at its CL.",
                    details={"effective_cl": effective_cl, "record_id": record_id, "available_path_ids": available},
                    status_code=422,
                )
        if milestone_changes:
            bounded["ability_score_changes_by_milestone_id"] = milestone_changes
        if progression_by_cl:
            bounded["path_progression_by_cl"] = progression_by_cl
        compatibility_items = []
        for kind in ("item_acquisition", "equipment_acquisition"):
            for row in historical_by_kind[kind]:
                if isinstance(row.get("record_id"), str):
                    compatibility_items.append({
                        "record_id": row["record_id"],
                        "parameters": deepcopy(row.get("parameters") or {}),
                    })
        response_form = "historical"

    descriptive = _descriptive_fields(plan)
    binding = {
        "request_sha256": request_sha256,
        "delegated_envelope_sha256": delegated_envelope.get("envelope_sha256"),
        "project_id": project.get("project_id"),
        "project_revision": project.get("revision"),
        "content_lock_hash": (project.get("content_lock") or {}).get("lock_hash"),
        "target_cl": target_cl,
    }
    unsigned = {
        "schema": SCHEMA,
        "binding": binding,
        "frozen_bindings": deepcopy(binding),
        "request_sha256": request_sha256,
        "delegated_envelope_sha256": delegated_envelope.get("envelope_sha256"),
        "project_id": project.get("project_id"),
        "project_revision": project.get("revision"),
        "content_lock_hash": (project.get("content_lock") or {}).get("lock_hash"),
        "target_cl": target_cl,
        "selected_by_slot": selected,
        "planning_preferences_by_slot": planning,
        "acquisition_intent": canonical_semantic_acquisition(acquisition),
        "bounded_choices": bounded,
        "owner_descriptive_fields": {
            "identity": {"name": descriptive.get("name")},
            "concept": descriptive.get("concept"),
        },
        "historical_stage2_rows": historical_rows,
        "compatibility_item_occurrences": compatibility_items if not preferred else [],
        "response_form": response_form,
        "policy": {
            "planner_prose_is_mechanical_authority": False,
            "planning_preferences_are_non_acquisitive": True,
            "acquisitions_are_semantic_and_explicit": True,
            "target_cl_server_owned": True,
        },
    }
    return CanonicalSelectionIntent.from_document({**unsigned, "intent_sha256": sha256_json(unsigned)})


def inject_canonical_intent(
    plan: Mapping[str, Any], intent: CanonicalSelectionIntent, *, target_cl: int
) -> dict[str, Any]:
    """Return an internal compatibility plan carrying the server intent."""

    result = deepcopy(dict(plan))
    document = intent.as_dict()
    result["canonical_selection_intent"] = document
    result["canonical_intent_hash"] = document["intent_sha256"]
    # These are internal server-owned values, not fields accepted by the
    # preferred transport parser.
    result["target_cl"] = target_cl
    result["owner_descriptive_fields"] = deepcopy(document["owner_descriptive_fields"])
    return result


__all__ = [
    "SCHEMA",
    "RESPONSE_SCHEMA",
    "CanonicalSelectionIntent",
    "canonical_semantic_acquisition",
    "empty_acquisition_intent",
    "inject_canonical_intent",
    "normalize_selection_intent",
]
