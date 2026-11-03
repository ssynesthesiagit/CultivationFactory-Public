"""Source-agnostic, always-on traits carried by the existing passive bundle.

Shared helper is_grapple(hold) recognizes native or complete rule-copy Grappled
holds for Insights8 failure receipts and this module's escape-mode readers.

An owned, reviewed feature-block spec may carry ``passive_traits`` alongside
its ordinary block. The strict compile transform validates and copies those
traits into ``typed_passives``; runtime queries read only the retained bundle.
Missing traits do not change existing rows, actions, events or saved state.

These traits have no conditional activation, replacement tiers or resource
costs. Such rules need a different, source-qualified implementation. Escape
modes apply only to a supplied, live Grappled hold on the creature rolling,
and only when that hold's source actor owns the compiled trait.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Iterator

from . import hook


BLOCK = "passive_trait"
_FIELDS = {
    "forced_movement_reduction": frozenset({"kind", "distance_ft"}),
    "standing_cost": frozenset({"kind", "cost_ft"}),
    "effective_size": frozenset({"kind", "steps", "roles", "purposes"}),
    "grapple_escape_mode": frozenset({"kind", "mode", "checks", "saves"}),
}
_ROLES = frozenset({"act", "resist"})
_PURPOSES = frozenset({"forced", "shove", "grapple", "prone", "comparison", "brutal_shove", "overrun", "carrying", "wrestling"})
_MODES = frozenset({"ADVANTAGE", "DISADVANTAGE"})
_GRAPPLED = frozenset({"condition:typed.grappled", "condition:core.grappled"})


def _validated_trait(value: Any, feature_id: str) -> dict[str, Any]:
    """Reject unexpressed constraints instead of silently granting a broad trait."""
    prefix = f"Invalid passive trait for {feature_id}"
    if not isinstance(value, dict):
        raise ValueError(f"{prefix}: each trait must be an object")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in _FIELDS:
        raise ValueError(f"{prefix}: unsupported kind")
    if set(value) != _FIELDS[kind]:
        raise ValueError(f"{prefix}: fields must be {', '.join(sorted(_FIELDS[kind]))}")
    if kind in {"forced_movement_reduction", "standing_cost", "effective_size"}:
        field = {"forced_movement_reduction": "distance_ft", "standing_cost": "cost_ft", "effective_size": "steps"}[kind]
        minimum = 1 if field == "steps" else 0
        if type(value[field]) is not int or value[field] < minimum:
            raise ValueError(f"{prefix}: {field} must be an integer of at least {minimum}")
    if kind == "effective_size":
        for field, allowed in (("roles", _ROLES), ("purposes", _PURPOSES)):
            choices = value[field]
            if (not isinstance(choices, list) or not choices
                    or any(not isinstance(choice, str) or choice not in allowed for choice in choices)
                    or len(set(choices)) != len(choices)):
                raise ValueError(f"{prefix}: {field} must be a nonempty list of distinct supported values")
    if kind == "grapple_escape_mode":
        if not isinstance(value["mode"], str) or value["mode"] not in _MODES:
            raise ValueError(f"{prefix}: mode must be ADVANTAGE or DISADVANTAGE")
        if type(value["checks"]) is not bool or type(value["saves"]) is not bool:
            raise ValueError(f"{prefix}: checks and saves must be booleans")
        if not value["checks"] and not value["saves"]:
            raise ValueError(f"{prefix}: at least one escape roll kind is required")
    return value


@hook("compile_passives")
def compile_passives(passives: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    """Append copied traits for reviewed owned IDs without mutating either input.

    The compiler supplies source/hash-gated ``owned_ids``. ``numbers`` is part
    of the shared context, but these four traits accept literal typed numbers
    only. A malformed owned spec raises through the strict transform.
    """
    if not isinstance(passives, list):
        raise ValueError("compile_passives requires a passive-row list")
    owned_ids = info.get("owned_ids", [])
    if (not isinstance(owned_ids, (list, tuple))
            or any(not isinstance(feature_id, str) or not feature_id for feature_id in owned_ids)):
        raise ValueError("compile_passives requires a list of owned feature IDs")
    result = list(passives)
    if not owned_ids:
        return result
    from ..typed_reactions import rules

    features = rules().get("features") or {}
    for feature_id in dict.fromkeys(owned_ids):
        spec = features.get(feature_id)
        if not isinstance(spec, dict) or "passive_traits" not in spec:
            continue
        traits = spec["passive_traits"]
        if not isinstance(traits, list):
            raise ValueError(f"Invalid passive traits for {feature_id}: expected a list")
        seen: set[str] = set()
        for value in traits:
            trait = _validated_trait(value, feature_id)
            if trait["kind"] in seen:
                raise ValueError(f"Invalid passive traits for {feature_id}: repeated kind {trait['kind']}")
            seen.add(trait["kind"])
            result.append({"feature_id": feature_id, "block": BLOCK, **deepcopy(trait)})
    return result


def _traits(engine: Any, actor: Any, kind: str) -> Iterator[dict[str, Any]]:
    """Read retained passive rows, never the current source or feature-block map."""
    actor_id = getattr(actor, "entity_id", None)
    if not actor_id:
        return
    for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, ()):
        if not isinstance(row, dict) or row.get("block") != BLOCK or row.get("kind") != kind:
            continue
        feature_id = row.get("feature_id")
        if not isinstance(feature_id, str) or not feature_id:
            continue
        # Bundle compilers may add display metadata such as name. Only the
        # documented trait config can affect a query; malformed rows are inert.
        config = {key: row[key] for key in _FIELDS[kind] if key in row}
        try:
            yield _validated_trait(config, feature_id)
        except ValueError:
            continue


@hook("forced_distance")
def forced_distance(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    """One standing reduction at every existing on_forced_movement checkpoint."""
    reduction = sum(row["distance_ft"] for row in _traits(engine, mover, "forced_movement_reduction"))
    return reduction or None


@hook("stand_cost")
def stand_cost(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """Quote movement only; posture owns eligibility, payment and condition removal."""
    costs = [row["cost_ft"] for row in _traits(engine, actor, "standing_cost")]
    return min(costs) if costs else None


@hook("size_steps")
def size_steps(engine: Any, actor: Any, role: str, purposes: Any) -> int | None:
    """Both role and an explicitly requested comparison purpose must match."""
    requested = set(purposes or ())
    steps = sum(row["steps"] for row in _traits(engine, actor, "effective_size")
                if role in row["roles"] and requested.intersection(row["purposes"]))
    return steps or None


def is_grapple(hold: Any) -> bool:
    """Shared physical Grappled predicate; mere restraint is not a Grapple."""
    if getattr(hold, "condition_id", None) in _GRAPPLED:
        return True
    rule = (getattr(hold, "data", None) or {}).get("rule")
    if not isinstance(rule, dict):
        return False
    # Custom holds can carry the complete base Grappled rule, as the shared
    # escape-options reader already recognizes. Mere restraint is insufficient.
    from ..typed_executor import rules

    base = rules()["conditions"]["grappled"]
    return bool(base) and all(rule.get(key) == value for key, value in base.items())


def _escape_mode(engine: Any, escaper: Any, grips: Any, roll_kind: str, mode: str) -> str | None:
    """A holder's trait affects only that holder's actual, selected Grappled hold."""
    actor_id = getattr(escaper, "entity_id", None)
    conditions = getattr(escaper, "conditions", {}) or {}
    actors = getattr(getattr(engine, "state", None), "actors", {}) or {}
    supplied = grips.values() if isinstance(grips, Mapping) else (grips or ())
    for grip in supplied:
        hold = conditions.get(getattr(grip, "instance_id", None))
        if (hold is None or getattr(hold, "target_id", None) != actor_id
                or getattr(hold, "source_actor_id", None) != getattr(grip, "source_actor_id", None)
                or getattr(hold, "condition_id", None) != getattr(grip, "condition_id", None)
                or not is_grapple(hold)):
            continue
        holder = actors.get(hold.source_actor_id)
        if any(row[roll_kind] and row["mode"] == mode
               for row in _traits(engine, holder, "grapple_escape_mode")):
            return mode
    return None


# Keep the two modes as separate replies so an Advantage from this module and
# a Disadvantage from any other provider still combine by the shared rules.
@hook("escape_mode")
def escape_check_advantage(engine: Any, escaper: Any, grips: Any) -> str | None:
    return _escape_mode(engine, escaper, grips, "checks", "ADVANTAGE")


@hook("escape_mode")
def escape_check_disadvantage(engine: Any, escaper: Any, grips: Any) -> str | None:
    return _escape_mode(engine, escaper, grips, "checks", "DISADVANTAGE")


@hook("escape_save_mode")
def escape_save_advantage(engine: Any, escaper: Any, grips: Any) -> str | None:
    return _escape_mode(engine, escaper, grips, "saves", "ADVANTAGE")


@hook("escape_save_mode")
def escape_save_disadvantage(engine: Any, escaper: Any, grips: Any) -> str | None:
    return _escape_mode(engine, escaper, grips, "saves", "DISADVANTAGE")
