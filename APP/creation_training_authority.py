"""Closed-world authority for constructed creation-training choices.

The ordinary training service records rolled attempts and owner-confirmed
training sources.  Direct character construction is a separate, deterministic
lane: it records a justified published route and a successful constructed
outcome without inventing a roll or an observed-play record.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping


CREATION_TRAINING_CONTRACT_SCHEMA = "TianxiaFoundry.CreationTrainingContract.v1"
CREATION_TRAINING_SOURCE_SCHEMA = "TianxiaFoundry.ConstructedTrainingSource.v1"
CREATION_TRAINING_OUTCOME_SCHEMA = "TianxiaFoundry.ConstructedTrainingOutcome.v1"
CREATION_TRAINING_CONTRACT_VERSION = 1
CREATION_TRAINING_MAX_PER_CL = 3
CREATION_TRAINING_SPHERE_KIND = "creation_training_sphere_acquisition"
CREATION_TRAINING_TALENT_KIND = "creation_training_talent_acquisition"
CREATION_TRAINING_BONUS_KIND = "new_sphere_bonus_talent_acquisition"
CREATION_TRAINING_SPHERE_CHANNEL = "creation-training-published-sphere"
CREATION_TRAINING_TALENT_CHANNEL = "creation-training-known-sphere-talent"
CREATION_TRAINING_BONUS_CHANNEL = "new-sphere-bonus"
CREATION_TRAINING_KINDS = frozenset({CREATION_TRAINING_SPHERE_KIND, CREATION_TRAINING_TALENT_KIND})
CREATION_TRAINING_CHANNEL_BY_KIND = {
    CREATION_TRAINING_SPHERE_KIND: CREATION_TRAINING_SPHERE_CHANNEL,
    CREATION_TRAINING_TALENT_KIND: CREATION_TRAINING_TALENT_CHANNEL,
    CREATION_TRAINING_BONUS_KIND: CREATION_TRAINING_BONUS_CHANNEL,
}
CREATION_TRAINING_CHOICE_TYPES = frozenset({"new_sphere", "known_sphere_talent"})
OPEN_ACCESS_CATEGORIES = frozenset({"open", "Open", "public", "Public"})
_CREATION_STATIC_CONTEXT_SLOTS = frozenset({
    "path_choice",
    "method_choice",
    "foundation_choice",
    "background_choice",
    "background_sphere_choice",
    "background_talent_choice",
    "origin_insight_choice",
})


def validate_mortal_level0_training(*, target_cl: int, training_choices: list[Any] | tuple[Any, ...]) -> dict[str, Any]:
    """Keep the pretrial mortal lane free of CL1 training acquisitions."""

    if type(target_cl) is not int or target_cl != 0:
        raise ValueError("MORTAL_LEVEL0_TARGET_REQUIRED")
    if not isinstance(training_choices, (list, tuple)) or training_choices:
        raise ValueError("MORTAL_LEVEL0_TRAINING_FORBIDDEN")
    return {"route": "completed_level0_mortal", "target_cl": 0, "training_choices": []}


class SealedBackgroundSphereResolutionError(ValueError):
    """A selected Background Sphere cannot be bound to one sealed Sphere ID."""

    def __init__(
        self,
        background_sphere_id: str,
        *,
        reason: str,
        display_name: str | None = None,
        candidate_ids: list[str] | None = None,
    ) -> None:
        self.background_sphere_id = background_sphere_id
        self.reason = reason
        self.display_name = display_name
        self.candidate_ids = list(candidate_ids or [])
        super().__init__(reason)


def canonical_background_sphere_ids(
    background_sphere_ids: list[str] | tuple[str, ...],
    choices_by_slot: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Resolve selected Background Sphere aliases through sealed Sphere rows.

    Background routes use their own stable IDs while creation-training talent
    routes point at canonical Sphere IDs.  The frozen envelope already carries
    both rows, so this mapping stays provider-free and cannot consult a live
    catalog or invent an ID from a prefix.  Every selected Background row must
    carry an explicit canonical relation that is also present in the sealed
    canonical Sphere choices.
    """

    slots = choices_by_slot if isinstance(choices_by_slot, Mapping) else {}
    background_choices = slots.get("background_sphere_choice")
    background_choices = background_choices if isinstance(background_choices, Mapping) else {}
    canonical_rows: list[Mapping[str, Any]] = []
    for slot_id in ("sphere_priorities", "sphere_choice"):
        rows = slots.get(slot_id)
        if isinstance(rows, Mapping):
            canonical_rows.extend(row for row in rows.values() if isinstance(row, Mapping))
        elif isinstance(rows, list):
            canonical_rows.extend(row for row in rows if isinstance(row, Mapping))

    canonical_ids: set[str] = set()
    for row in canonical_rows:
        sphere_id = next(
            (
                row.get(key)
                for key in ("canonical_sphere_id", "choice_id", "sphere_id")
                if isinstance(row.get(key), str) and row.get(key)
            ),
            None,
        )
        if not isinstance(sphere_id, str) or not sphere_id:
            continue
        canonical_ids.add(sphere_id)

    resolved: dict[str, str] = {}
    for raw_id in background_sphere_ids:
        if not isinstance(raw_id, str) or not raw_id:
            raise SealedBackgroundSphereResolutionError(
                str(raw_id), reason="background_sphere_id_invalid"
            )
        choice = background_choices.get(raw_id)
        if not isinstance(choice, Mapping):
            raise SealedBackgroundSphereResolutionError(
                raw_id, reason="background_choice_unresolved"
            )
        if "canonical_sphere_id" in choice:
            explicit_canonical_id = choice.get("canonical_sphere_id")
            if (
                not isinstance(explicit_canonical_id, str)
                or not explicit_canonical_id
                or explicit_canonical_id not in canonical_ids
            ):
                raise SealedBackgroundSphereResolutionError(
                    raw_id,
                    reason="background_canonical_relation_invalid",
                    candidate_ids=sorted(canonical_ids),
                )
            resolved[raw_id] = explicit_canonical_id
            continue
        raise SealedBackgroundSphereResolutionError(
            raw_id, reason="background_canonical_relation_missing"
        )
    return resolved


def canonical_background_package_ids(
    selected_by_slot: Mapping[str, Any],
    typed_choice_authority_by_slot: Mapping[str, Any] | None,
) -> tuple[set[str], set[str]]:
    """Return canonical IDs from one selected, sealed Background package.

    Background slots retain source-specific aliases for provenance.  The
    authenticated package linkage is the only relation allowed to add its
    canonical Sphere or Talent record to causal holdings; names and ID
    prefixes are intentionally ignored.
    """

    if not isinstance(selected_by_slot, Mapping):
        return set(), set()
    selected_backgrounds = {
        value
        for value in selected_by_slot.get("background_choice") or []
        if isinstance(value, str) and value
    }
    selected_spheres = {
        value
        for value in selected_by_slot.get("background_sphere_choice") or []
        if isinstance(value, str) and value
    }
    selected_talents = {
        value
        for value in selected_by_slot.get("background_talent_choice") or []
        if isinstance(value, str) and value
    }
    if not selected_backgrounds:
        return set(), set()
    typed = typed_choice_authority_by_slot if isinstance(typed_choice_authority_by_slot, Mapping) else {}
    background = typed.get("background_choice")
    background = background if isinstance(background, Mapping) else {}
    linkage = background.get("background_package_linkage")
    if not isinstance(linkage, Mapping):
        contract = background.get("authority_contract")
        contract = contract if isinstance(contract, Mapping) else {}
        linkage = contract.get("background_package_linkage")
    if not isinstance(linkage, Mapping):
        return set(), set()

    canonical_spheres: set[str] = set()
    canonical_talents: set[str] = set()
    for background_id, raw_packages in linkage.items():
        if not isinstance(background_id, str):
            continue
        if selected_backgrounds and background_id not in selected_backgrounds:
            continue
        packages = raw_packages if isinstance(raw_packages, list) else [raw_packages]
        for package in packages:
            if not isinstance(package, Mapping):
                continue
            sphere_choice_id = package.get("background_sphere_choice_id")
            talent_choice_id = package.get("background_talent_choice_id")
            sphere_selected = isinstance(sphere_choice_id, str) and sphere_choice_id in selected_spheres
            talent_selected = isinstance(talent_choice_id, str) and talent_choice_id in selected_talents
            if sphere_selected:
                for key in ("canonical_sphere_id", "sphere_record_id"):
                    value = package.get(key)
                    if isinstance(value, str) and value:
                        canonical_spheres.add(value)
                        break
            # A package grants its Talent only as part of the same selected
            # Sphere/Talent pair.  A Talent alias from another package must
            # not become canonical merely because it appears in the selected
            # Background Talent slot.
            if sphere_selected and talent_selected:
                value = package.get("canonical_talent_id") or package.get("talent_record_id")
                if isinstance(value, str) and value:
                    canonical_talents.add(value)
    return canonical_spheres, canonical_talents


def canonical_selected_background_sphere_ids(
    selected_by_slot: Mapping[str, Any],
    choices_by_slot: Mapping[str, Any] | None,
    typed_choice_authority_by_slot: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Resolve a selected Background Sphere only in its selected package.

    The sealed Sphere row supplies the canonical relation, while the selected
    Background package linkage proves that the relation belongs to this
    Background.  A Sphere choice without a selected Background or without
    that package relation is never causal ownership proof.
    """

    if not isinstance(selected_by_slot, Mapping):
        return {}
    background_ids = {
        value
        for value in selected_by_slot.get("background_choice") or []
        if isinstance(value, str) and value
    }
    sphere_ids = [
        value
        for value in selected_by_slot.get("background_sphere_choice") or []
        if isinstance(value, str) and value
    ]
    # A Background may be selected while its dependent Sphere slot is still
    # dormant.  There are no Background holdings to expose until that slot has
    # a selected choice; the existing slot validator owns the required-choice
    # error.
    if not sphere_ids:
        return {}
    if not background_ids:
        raise SealedBackgroundSphereResolutionError(
            sphere_ids[0], reason="background_package_selection_missing"
        )

    resolved = canonical_background_sphere_ids(sphere_ids, choices_by_slot)
    typed = typed_choice_authority_by_slot if isinstance(typed_choice_authority_by_slot, Mapping) else {}
    background = typed.get("background_choice")
    background = background if isinstance(background, Mapping) else {}
    linkage = background.get("background_package_linkage")
    if not isinstance(linkage, Mapping):
        contract = background.get("authority_contract")
        contract = contract if isinstance(contract, Mapping) else {}
        linkage = contract.get("background_package_linkage")
    if not isinstance(linkage, Mapping) or not linkage:
        raise SealedBackgroundSphereResolutionError(
            sphere_ids[0], reason="background_package_relation_missing"
        )
    package_spheres, _package_talents = canonical_background_package_ids(
        selected_by_slot,
        typed,
    )
    if not package_spheres or set(resolved.values()) != package_spheres:
        raise SealedBackgroundSphereResolutionError(
            sphere_ids[0],
            reason="background_package_relation_mismatch",
            candidate_ids=sorted(package_spheres),
        )
    return resolved


def creation_context_ids(
    selected_by_slot: Mapping[str, Any],
    choices_by_slot: Mapping[str, Any] | None,
    typed_choice_authority_by_slot: Mapping[str, Any] | None,
    *,
    current_cl: int,
) -> set[str]:
    """Return selected records available before a causal creation choice.

    Paths, the initial Method/Foundation, and starting package choices are
    present at creation.  A selected Subpath is added only when its sealed
    attainment/minimum CL is at or before ``current_cl``.  Other unknown
    non-planning slots are deliberately ignored so a future feature or Insight
    cannot become prerequisite proof merely because it was selected.
    """

    if not isinstance(selected_by_slot, Mapping) or type(current_cl) is not int:
        return set()
    choices = choices_by_slot if isinstance(choices_by_slot, Mapping) else {}
    typed = typed_choice_authority_by_slot if isinstance(typed_choice_authority_by_slot, Mapping) else {}
    result: set[str] = set()
    # Background aliases are source provenance, not canonical ownership.  Add
    # canonical Background holdings only after the selected package relation
    # has been authenticated by the shared resolver.  This also prevents a
    # selected Sphere or Talent from becoming ownership proof when the
    # Background package is absent, mismatched, or still awaiting its Sphere.
    try:
        canonical_background_ids = canonical_selected_background_sphere_ids(
            selected_by_slot,
            choices,
            typed,
        )
    except SealedBackgroundSphereResolutionError:
        canonical_background_ids = {}
    if canonical_background_ids:
        result.update(canonical_background_ids.values())
        _package_spheres, package_talents = canonical_background_package_ids(selected_by_slot, typed)
        result.update(package_talents)
    for slot_id, raw_values in selected_by_slot.items():
        if not isinstance(slot_id, str) or not isinstance(raw_values, (list, tuple)):
            continue
        values = [value for value in raw_values if isinstance(value, str) and value]
        if slot_id in {"background_sphere_choice", "background_talent_choice"}:
            continue
        if slot_id in _CREATION_STATIC_CONTEXT_SLOTS:
            result.update(values)
            continue
        if slot_id != "subpath_choice":
            continue
        slot_rows = choices.get(slot_id)
        slot_rows = slot_rows if isinstance(slot_rows, Mapping) else {}
        authority = typed.get(slot_id)
        authority = authority if isinstance(authority, Mapping) else {}
        minimum_by_choice = authority.get("minimum_attainment_by_choice")
        minimum_by_choice = minimum_by_choice if isinstance(minimum_by_choice, Mapping) else {}
        for choice_id in values:
            row = slot_rows.get(choice_id)
            row = row if isinstance(row, Mapping) else {}
            minimum = minimum_by_choice.get(choice_id)
            if minimum is None:
                availability = row.get("availability")
                availability = availability if isinstance(availability, Mapping) else {}
                legality = row.get("legality")
                legality = legality if isinstance(legality, Mapping) else {}
                minimum = (
                    row.get("effective_cl")
                    if row.get("effective_cl") is not None
                    else row.get("acquisition_cl")
                )
                if minimum is None:
                    minimum = row.get("minimum_cl")
                if minimum is None:
                    minimum = availability.get("minimum_cl")
                if minimum is None:
                    minimum = legality.get("minimum_cl")
            if type(minimum) is int and minimum >= 0 and minimum <= current_cl:
                result.add(choice_id)
    return result


def _raw(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("raw_record")
    if isinstance(value, Mapping):
        return value
    factory = ((record.get("compatibility") or {}).get("factory") or {})
    projection = factory.get("raw_projection") if isinstance(factory, Mapping) else None
    nested = projection.get("raw_record") if isinstance(projection, Mapping) else None
    if isinstance(nested, Mapping):
        return nested
    return projection if isinstance(projection, Mapping) else {}


def _authority(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = ((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority")
    return value if isinstance(value, Mapping) else {}


def _authority_allows_kind_channel(
    authority: Mapping[str, Any],
    *,
    kind: str,
    channel: str,
) -> bool:
    """Require the exact typed Stage 2 kind and channel for a route."""

    allowed_kinds = {
        value for value in authority.get("allowed_kinds") or []
        if isinstance(value, str) and value.strip()
    }
    allowed_channels = {
        value for value in authority.get("allowed_channels") or []
        if isinstance(value, str) and value.strip()
    }
    return kind in allowed_kinds and channel in allowed_channels


def record_source_provenance(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact source commitment already present on a locked record."""

    source = record.get("source") if isinstance(record.get("source"), Mapping) else {}
    raw_source = _raw(record).get("source_provenance")
    raw_source = raw_source if isinstance(raw_source, Mapping) else {}
    source_id = source.get("source_id") or raw_source.get("source_authority_sha256")
    source_hash = source.get("source_hash") or raw_source.get("source_file_sha256")
    anchor = source.get("anchor") or raw_source.get("source_anchor")
    path = source.get("path") or raw_source.get("source_path")
    if not all(isinstance(value, str) and value.strip() for value in (source_id, source_hash, anchor, path)):
        return {}
    return {
        "record_id": record.get("record_id"),
        "record_hash": record.get("record_hash"),
        "source_id": source_id,
        "source_hash": source_hash,
        "source_anchor": anchor,
        "source_path": path,
    }


def _open_route(record: Mapping[str, Any], *, content_type: str) -> bool:
    """Whether a locked catalog row exposes a legal constructed route."""

    raw = _raw(record)
    authority = _authority(record)
    category = raw.get("access_category")
    if isinstance(category, str) and category not in OPEN_ACCESS_CATEGORIES:
        return False
    if content_type == "sphere":
        # A CAT3 Sphere is itself the published teaching/access authority.  A
        # future restricted Sphere must opt in explicitly as Open; an unknown
        # category is retained for the current published Sphere corpus.
        return (
            authority.get("authority_complete") is True
            and _authority_allows_kind_channel(
                authority,
                kind=CREATION_TRAINING_SPHERE_KIND,
                channel=CREATION_TRAINING_SPHERE_CHANNEL,
            )
            and bool(record_source_provenance(record))
        )
    if content_type == "talent":
        return (
            authority.get("authority_complete") is True
            and _authority_allows_kind_channel(
                authority,
                kind=CREATION_TRAINING_TALENT_KIND,
                channel=CREATION_TRAINING_TALENT_CHANNEL,
            )
            and raw.get("creator_selectability_can_be_evaluated_safely") is not False
            and isinstance(authority.get("sphere_id") or raw.get("owning_canonical_sphere_id"), str)
            and bool(record_source_provenance(record))
        )
    return False


def _legality_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the typed record legality needed for causal menu validation.

    Creation training is selected before a Stage 2 event exists, so the walk
    must carry the same minimum CL and typed relation inputs that Stage 2 will
    later evaluate.  Keep this projection deliberately small; source and
    record identity remain bound by the route itself.
    """

    raw = _raw(record)
    legality = record.get("legality") if isinstance(record.get("legality"), Mapping) else {}
    minimum_cl = legality.get("minimum_cl")
    if type(minimum_cl) is not int:
        minimum_cl = record.get("minimum_cl")
    if type(minimum_cl) is not int:
        minimum_cl = raw.get("minimum_cl")
    prerequisites = legality.get("prerequisites")
    if not isinstance(prerequisites, list):
        prerequisites = record.get("prerequisites")
    if not isinstance(prerequisites, list):
        prerequisites = []
    incompatibilities = legality.get("incompatibilities")
    if not isinstance(incompatibilities, list):
        incompatibilities = record.get("incompatibilities")
    if not isinstance(incompatibilities, list):
        incompatibilities = []
    realm_rules = legality.get("realm_rules")
    if not isinstance(realm_rules, Mapping):
        realm_rules = {}
    return {
        "minimum_cl": minimum_cl if type(minimum_cl) is int else None,
        "realm_rules": deepcopy(dict(realm_rules)),
        "prerequisites": deepcopy(prerequisites),
        "incompatibilities": deepcopy(incompatibilities),
        "access_category": raw.get("access_category") if isinstance(raw.get("access_category"), str) else None,
    }


def _record_route(record: Mapping[str, Any]) -> dict[str, Any] | None:
    content_type = record.get("content_type")
    if content_type == "sphere" and _open_route(record, content_type="sphere"):
        route = {
            "record_id": record.get("record_id"),
            "content_type": "sphere",
            "choice_type": "new_sphere",
            "source_route": "published_legal_teaching_route",
            "source_record_id": record.get("record_id"),
            "source_provenance": record_source_provenance(record),
            "owning_sphere_id": None,
            "bonus_talent_eligible": True,
        }
        route.update(_legality_projection(record))
        return route
    if content_type == "talent" and _open_route(record, content_type="talent"):
        authority = _authority(record)
        sphere_id = authority.get("sphere_id") or _raw(record).get("owning_canonical_sphere_id")
        route = {
            "record_id": record.get("record_id"),
            "content_type": "talent",
            "choice_type": "known_sphere_talent",
            "source_route": "recorded_self_training",
            "source_record_id": sphere_id,
            "source_provenance": record_source_provenance(record),
            "owning_sphere_id": sphere_id,
            "bonus_talent_eligible": (
                bool(_raw(record).get("free_sphere_talent_eligible"))
                and _authority_allows_kind_channel(
                    authority,
                    kind=CREATION_TRAINING_BONUS_KIND,
                    channel=CREATION_TRAINING_BONUS_CHANNEL,
                )
            ),
        }
        route.update(_legality_projection(record))
        return route
    return None


def build_creation_training_contract(
    records: Mapping[str, Mapping[str, Any]] | list[Mapping[str, Any]],
    *,
    target_cl: int | None,
    power_band: str | None,
    canonical_talent_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Build the sealed, source-bound construction authority projection.

    ``canonical_talent_resolver`` is the CAT3 canonical registry's exact
    talent resolver.  The final validator accepts a constructed Talent only
    when that registry resolves it, and the registry classifies a few
    catalog rows typed as talents (the "<Talent> Stat Block" creature and
    formation blocks) as non-talent components of a parent Talent.  Such a
    row is never a legal constructed-training route, so it is excluded here
    at the source rather than offered by a menu and rejected at the end.
    """

    iterable = records.values() if isinstance(records, Mapping) else records
    routes: dict[str, dict[str, Any]] = {}
    for record in iterable:
        if not isinstance(record, Mapping) or not isinstance(record.get("record_id"), str):
            continue
        route = _record_route(record)
        if route is None:
            continue
        if (
            route["content_type"] == "talent"
            and canonical_talent_resolver is not None
            and not canonical_talent_resolver(record["record_id"])
        ):
            continue
        routes[record["record_id"]] = route
    required = 3 if power_band == "rival/boss" else None
    return {
        "schema": CREATION_TRAINING_CONTRACT_SCHEMA,
        "version": CREATION_TRAINING_CONTRACT_VERSION,
        "target_cl": target_cl,
        "power_band": power_band,
        "max_choices_per_cl": CREATION_TRAINING_MAX_PER_CL,
        "required_choices_per_cl": required,
        "bonus_rule": "new_sphere_one_same_sphere_talent_without_slot_cost",
        "construction_mode": "published_route_success_without_rolls",
        "records": {key: routes[key] for key in sorted(routes)},
        "rule_ids": ["Q06", "RAW-079", "RAW-081"],
    }


def validate_creation_training_contract(contract: Any) -> list[str]:
    if not isinstance(contract, Mapping) or contract.get("schema") != CREATION_TRAINING_CONTRACT_SCHEMA:
        return ["contract_schema"]
    errors: list[str] = []
    if contract.get("version") != CREATION_TRAINING_CONTRACT_VERSION:
        errors.append("contract_version")
    target_cl = contract.get("target_cl")
    if type(target_cl) is not int or not 1 <= target_cl <= 20:
        errors.append("target_cl")
    if contract.get("max_choices_per_cl") != CREATION_TRAINING_MAX_PER_CL:
        errors.append("max_choices_per_cl")
    if contract.get("construction_mode") != "published_route_success_without_rolls":
        errors.append("construction_mode")
    if contract.get("bonus_rule") != "new_sphere_one_same_sphere_talent_without_slot_cost":
        errors.append("bonus_rule")
    if contract.get("rule_ids") != ["Q06", "RAW-079", "RAW-081"]:
        errors.append("rule_ids")
    if contract.get("required_choices_per_cl") not in {None, 3}:
        errors.append("required_choices_per_cl")
    records = contract.get("records")
    if not isinstance(records, Mapping):
        errors.append("records")
    else:
        for record_id, route in records.items():
            if not isinstance(record_id, str) or not isinstance(route, Mapping):
                errors.append("record_route")
                continue
            if route.get("record_id") != record_id:
                errors.append(f"record_route:{record_id}:record_id")
            content_type = route.get("content_type")
            choice_type = route.get("choice_type")
            if (content_type, choice_type) not in {("sphere", "new_sphere"), ("talent", "known_sphere_talent")}:
                errors.append(f"record_route:{record_id}:type")
            if not isinstance(route.get("source_route"), str) or not isinstance(route.get("source_record_id"), str):
                errors.append(f"record_route:{record_id}:source")
            if not isinstance(route.get("source_provenance"), Mapping) or not route.get("source_provenance"):
                errors.append(f"record_route:{record_id}:source_provenance")
            if content_type == "talent" and not isinstance(route.get("owning_sphere_id"), str):
                errors.append(f"record_route:{record_id}:owning_sphere")
            if not isinstance(route.get("prerequisites"), list) or not isinstance(route.get("incompatibilities"), list):
                errors.append(f"record_route:{record_id}:legality")
            access_category = route.get("access_category")
            if access_category is not None and access_category not in OPEN_ACCESS_CATEGORIES:
                errors.append(f"record_route:{record_id}:access_category")
            minimum_cl = route.get("minimum_cl")
            if minimum_cl is not None and (type(minimum_cl) is not int or not 1 <= minimum_cl <= 20):
                errors.append(f"record_route:{record_id}:minimum_cl")
            realm_rules = route.get("realm_rules")
            if realm_rules is not None and not isinstance(realm_rules, Mapping):
                errors.append(f"record_route:{record_id}:realm_rules")
    return errors


def constructed_source(route: Mapping[str, Any], *, choice_type: str) -> dict[str, Any]:
    """Create the explicit construction provenance carried by one ledger row."""

    rule_ids = ["Q06", "RAW-079"]
    if choice_type == "new_sphere":
        rule_ids.append("RAW-081")
    return {
        "schema": CREATION_TRAINING_SOURCE_SCHEMA,
        "mode": "constructed",
        "route": route.get("source_route"),
        "choice_type": choice_type,
        "source_record_id": route.get("source_record_id"),
        "source_provenance": deepcopy(route.get("source_provenance") or {}),
        "rule_ids": rule_ids,
        "observed_play": False,
    }


def constructed_outcome() -> dict[str, Any]:
    return {
        "schema": CREATION_TRAINING_OUTCOME_SCHEMA,
        "result": "learned",
        "mode": "automatic_construction",
        "dice_simulated": False,
        "counts_against_limit": True,
        "slot_cost": 1,
    }


def _relation_targets(relation: Any) -> list[str]:
    if isinstance(relation, str):
        return [relation]
    if not isinstance(relation, Mapping):
        return []
    targets = relation.get("target_ids") or relation.get("targets")
    if isinstance(targets, str):
        return [targets]
    if isinstance(targets, (list, tuple)):
        return [target for target in targets if isinstance(target, str) and target]
    target = relation.get("target_id") or relation.get("record_id") or relation.get("canonical_id") or relation.get("id")
    return [target] if isinstance(target, str) and target else []


def _route_constraint(route: Mapping[str, Any], key: str) -> Any:
    value = route.get(key)
    if value is not None:
        return value
    legality = route.get("legality")
    return legality.get(key) if isinstance(legality, Mapping) else None


def creation_route_temporal_legality_errors(
    route: Mapping[str, Any],
    *,
    cl: int,
    present_ids: set[str],
    candidate_ids: tuple[str, ...] = (),
    prior_choice_ids: tuple[str, ...] = (),
) -> list[str]:
    """Evaluate non-access route constraints before one causal choice.

    This is shared by menu projection and response validation.  ``candidate``
    IDs are considered for incompatibilities, while only ``prior_choice_ids``
    can satisfy prerequisites; this preserves the causal ordering of a new
    Sphere followed by its bundled Talent.
    """

    if not isinstance(route, Mapping):
        return ["route"]
    errors: list[str] = []
    minimum_cl = _route_constraint(route, "minimum_cl")
    if minimum_cl is not None and (type(minimum_cl) is not int or minimum_cl < 1 or cl < minimum_cl):
        errors.append("minimum_cl")
    allowed_cls = _route_constraint(route, "allowed_cls")
    if allowed_cls is not None:
        if not isinstance(allowed_cls, (list, tuple)) or any(type(value) is not int for value in allowed_cls):
            errors.append("allowed_cls")
        elif cl not in allowed_cls:
            errors.append("allowed_cls")
    realm_rules = _route_constraint(route, "realm_rules")
    if realm_rules is not None:
        if not isinstance(realm_rules, Mapping):
            errors.append("realm_rules")
        else:
            realm_minimum = realm_rules.get("minimum_cl")
            if realm_minimum is not None and (type(realm_minimum) is not int or realm_minimum < 1 or cl < realm_minimum):
                errors.append("realm_rules.minimum_cl")
            realm_allowed = realm_rules.get("allowed_cls")
            if realm_allowed is not None:
                if not isinstance(realm_allowed, (list, tuple)) or any(type(value) is not int for value in realm_allowed):
                    errors.append("realm_rules.allowed_cls")
                elif cl not in realm_allowed:
                    errors.append("realm_rules.allowed_cls")

    prior = set(present_ids) | set(prior_choice_ids)
    prerequisites = _route_constraint(route, "prerequisites")
    if prerequisites is None:
        prerequisites = []
    if not isinstance(prerequisites, (list, tuple)):
        errors.append("prerequisites")
    else:
        for index, relation in enumerate(prerequisites):
            targets = _relation_targets(relation)
            if not isinstance(relation, Mapping) or not targets:
                errors.append(f"prerequisites:{index}:shape")
                continue
            operator = relation.get("operator", "requires")
            if operator in {"requires", "all_of"}:
                satisfied = all(target in prior for target in targets)
            elif operator == "one_of":
                satisfied = any(target in prior for target in targets)
            elif operator == "not":
                satisfied = not any(target in prior for target in targets)
            else:
                errors.append(f"prerequisites:{index}:operator")
                continue
            if not satisfied:
                errors.append(f"prerequisites:{index}:unmet")

    incompatibilities = _route_constraint(route, "incompatibilities")
    if incompatibilities is None:
        incompatibilities = []
    if not isinstance(incompatibilities, (list, tuple)):
        errors.append("incompatibilities")
    else:
        incompatibility_state = set(present_ids) | set(candidate_ids)
        own_id = route.get("record_id")
        if isinstance(own_id, str):
            incompatibility_state.discard(own_id)
        for index, relation in enumerate(incompatibilities):
            targets = _relation_targets(relation)
            if not targets:
                errors.append(f"incompatibilities:{index}:shape")
            elif any(target in incompatibility_state for target in targets):
                errors.append(f"incompatibilities:{index}:present")
    return sorted(set(errors))


def creation_route_legality_errors(
    route: Mapping[str, Any],
    *,
    cl: int,
    present_ids: set[str],
    candidate_ids: tuple[str, ...] = (),
    prior_choice_ids: tuple[str, ...] = (),
) -> list[str]:
    """Evaluate a route, including its source access category.

    Access is intentionally kept at this wrapper boundary.  Callers that
    already validate a route's source/access channel can use the pure causal
    helper above without constructing a route that silently bypasses access
    validation for other callers.
    """

    if not isinstance(route, Mapping):
        return ["route"]
    errors = creation_route_temporal_legality_errors(
        route,
        cl=cl,
        present_ids=present_ids,
        candidate_ids=candidate_ids,
        prior_choice_ids=prior_choice_ids,
    )
    access_category = _route_constraint(route, "access_category")
    if access_category is not None and access_category not in OPEN_ACCESS_CATEGORIES:
        errors.append("access_category")
    return sorted(set(errors))


def canonical_trained_choice(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only the stable semantic fields accepted by the response contract."""

    result = {
        "cl": row.get("cl"),
        "slot": row.get("slot"),
        "choice_type": row.get("choice_type"),
        "record_id": row.get("record_id"),
        "source": deepcopy(row.get("source")),
        "outcome": row.get("outcome"),
    }
    if row.get("choice_type") == "new_sphere":
        result["bonus_talent_id"] = row.get("bonus_talent_id")
    return result


def validate_trained_choice_shape(row: Any) -> list[str]:
    if not isinstance(row, Mapping):
        return ["row"]
    required = {"cl", "slot", "choice_type", "record_id", "source", "outcome"}
    errors = sorted(required - set(row))
    if set(row) - required - {"bonus_talent_id"}:
        errors.append("extra_fields")
    if type(row.get("cl")) is not int or row["cl"] < 1 or row["cl"] > 20:
        errors.append("cl")
    if type(row.get("slot")) is not int or row["slot"] < 1 or row["slot"] > CREATION_TRAINING_MAX_PER_CL:
        errors.append("slot")
    if row.get("choice_type") not in CREATION_TRAINING_CHOICE_TYPES:
        errors.append("choice_type")
    if not isinstance(row.get("record_id"), str) or not row["record_id"]:
        errors.append("record_id")
    source = row.get("source")
    if not isinstance(source, Mapping) or source.get("schema") != CREATION_TRAINING_SOURCE_SCHEMA or source.get("mode") != "constructed" or source.get("observed_play") is not False:
        errors.append("source")
    outcome = row.get("outcome")
    if not isinstance(outcome, Mapping) or outcome.get("schema") != CREATION_TRAINING_OUTCOME_SCHEMA or outcome.get("result") != "learned" or outcome.get("dice_simulated") is not False or outcome.get("counts_against_limit") is not True or outcome.get("slot_cost") != 1:
        errors.append("outcome")
    if row.get("choice_type") == "new_sphere":
        if not isinstance(row.get("bonus_talent_id"), str) or not row["bonus_talent_id"]:
            errors.append("bonus_talent_id")
    elif "bonus_talent_id" in row:
        errors.append("bonus_talent_id")
    return sorted(set(errors))


__all__ = [
    "CREATION_TRAINING_CONTRACT_SCHEMA",
    "CREATION_TRAINING_SOURCE_SCHEMA",
    "CREATION_TRAINING_OUTCOME_SCHEMA",
    "CREATION_TRAINING_MAX_PER_CL",
    "CREATION_TRAINING_SPHERE_KIND",
    "CREATION_TRAINING_TALENT_KIND",
    "CREATION_TRAINING_BONUS_KIND",
    "CREATION_TRAINING_SPHERE_CHANNEL",
    "CREATION_TRAINING_TALENT_CHANNEL",
    "CREATION_TRAINING_BONUS_CHANNEL",
    "CREATION_TRAINING_CHANNEL_BY_KIND",
    "CREATION_TRAINING_KINDS",
    "build_creation_training_contract",
    "validate_creation_training_contract",
    "constructed_source",
    "constructed_outcome",
    "canonical_selected_background_sphere_ids",
    "canonical_background_package_ids",
    "creation_context_ids",
    "creation_route_temporal_legality_errors",
    "creation_route_legality_errors",
    "canonical_trained_choice",
    "validate_trained_choice_shape",
    "record_source_provenance",
]
