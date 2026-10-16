"""Body as Center (Tianxia Gravity Insight).

Both printed combat clauses of this Insight, owned by this plug-in:

* "When you use Gravitic Pull, Gravity Well, Crushing Field, or Flight
  Suppression, you may center the effect on your body. If you do, reduce
  the Stamina actually paid by 1, minimum 1."  ``compile_actions``
  publishes one centered variant of each printed way to pay those four
  talents. The variant centers the effect on the fighter's own body:
  the three area talents place their zone on the fighter (their zone
  spec is compiled with ``centered_on_self``), and Gravitic Pull pulls
  toward the caster (its forced-movement rows are compiled with
  ``direction: toward``, the printed "toward a point you can see" with
  the point being the fighter's body). A variant that pays Stamina
  costs one less Stamina, never less than one; a variant that pays
  Cultivation Points keeps its printed CP cost, because the printed
  reduction is to the Stamina *actually paid*.

* "The area moves with you only until the start of your next turn
  unless the Gravity talent itself says the area moves. After that
  point it remains at its current location for the rest of its
  duration. Centering the effect does not make you immune to it unless
  the talent says so."  A centered area is compiled as an area that
  follows its owner, and the general ``zone_follows`` seam
  (combat/zones.py ``follows_now``, documented in combat/ext/__init__.py)
  ends the ride at the start of the owner's next turn: ``zone_created``
  records the turn the area was centered, and ``zone_follows`` answers
  False once the owner's turn count has moved past it, so the area then
  stays where it is for the rest of its duration. Talents that print
  their own moving area (a Domain aura, which the compiler records as
  following forever) carry no Body as Center marker, so this plug-in
  never answers for them. Centering changes only where the effect is
  placed and what it costs -- the talent's own saves and recipients are
  untouched, so a centered Crushing Field still saves against its
  owner's enemies and the owner is not immune to it unless the talent
  says so.

A character without the Insight owns none of its rows, so every hook
returns early and every other gravity user's placement, costs and area
behave exactly as before.
"""
from __future__ import annotations

from typing import Any

from . import hook
from .passive_rows import row_of

INSIGHT = "insight.body-as-center"
BLOCK = "body_as_center"
STAMINA = "resource:core.stamina"

# The four printed talents, by their typed-mechanics ids.
GRAVITIC_PULL = "tianxia.talent.gravity.gravitic_pull"
GRAVITY_WELL = "TAL_GRAVITY_GRAVITY_WELL"
CRUSHING_FIELD = "TAL_GRAVITY_CRUSHING_FIELD"
FLIGHT_SUPPRESSION = "TAL_GRAVITY_FLIGHT_SUPPRESSION"
CENTERED_TALENTS = frozenset({GRAVITIC_PULL, GRAVITY_WELL, CRUSHING_FIELD, FLIGHT_SUPPRESSION})
# The talents whose effect is a placed area rather than a single creature.
AREA_TALENTS = frozenset({GRAVITY_WELL, CRUSHING_FIELD, FLIGHT_SUPPRESSION})

# Short cost words for the variant's display name.
COST_WORDS = {"resource:core.cp": "CP", "resource:core.qi": "Qi",
              "resource:core.stamina": "Stamina", "resource:core.resonance": "Resonance",
              "resource:core.martial_focus": "Martial Focus"}


def owned(engine: Any, actor: Any) -> bool:
    return row_of(engine, actor.entity_id, BLOCK, BLOCK) is not None


@hook("compile_block")
def compile_body_as_center(block: str, spec: dict[str, Any], row: dict[str, Any],
                           numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "numbers": dict(numbers)}]


# ------------------------------------------------------------------ the centered variants
@hook("compile_actions")
def centered_variants(info: dict[str, Any]) -> list[Any] | None:
    """One centered-on-you variant of each printed way to pay the four talents."""
    if INSIGHT not in info.get("owned_ids", ()):
        return None
    from ..gate2_runtime_models import ActionDefinition

    out = []
    for action in info.get("actions") or ():
        typed = (action.parameters or {}).get("typed") or {}
        if typed.get("source") not in CENTERED_TALENTS:
            continue
        costs = tuple((rid, max(1, amount - 1) if rid == STAMINA else amount)
                      for rid, amount in action.costs)
        parameters = {**action.parameters}
        typed = dict(typed)
        target_kind, range_ft = action.target_kind, action.range_ft
        if typed["source"] in AREA_TALENTS:
            # The area is placed on the fighter's own body and follows them
            # until the start of their next turn (the zone_follows seam).
            zone_spec = dict(typed.get("zone_spec") or {})
            zone_spec["centered_on_self"] = True
            zone_spec["follows_owner"] = True
            zone_spec["profile"] = {"body_center": 1}
            typed["zone_spec"] = zone_spec
            target_kind, range_ft = "SELF", None
        else:
            # Gravitic Pull: the point you can see is your own body, so the
            # pull travels toward the caster.
            typed["effects"] = _toward_caster(typed.get("effects") or [])
        parameters["typed"] = typed
        name = _base_name(action.display_name)
        # The talent's own way is its Cultivation Points way
        # (its Path pool), which centering leaves at its printed
        # cost; an alternative way (the compiler's ``#pay`` row)
        # is the printed alternative -- Stamina for these four
        # talents -- which centering reduces by one.
        words = _way_words(costs, "#pay" in action.source_definition_id)
        out.append(ActionDefinition(
            source_definition_id=f"{action.source_definition_id}#body_center",
            display_name=f"{name}, centered on you ({words}) (Body as Center)",
            owner_id=action.owner_id,
            economy=action.economy,
            resolution_kind=action.resolution_kind,
            target_kind=target_kind,
            range_ft=range_ft,
            costs=costs,
            concentration=action.concentration,
            parameters=parameters))
    return out or None


def _base_name(display_name: str) -> str:
    """The talent's own name, without a trailing printed cost group."""
    import re

    return re.sub(r"\s*\(\d[^)]*\)\s*$", "", display_name).strip()


def _way_words(costs: tuple[tuple[str, int], ...], alternative: bool) -> str:
    """The printed cost words for one way to pay a centered talent.

    The talent's own way is its Cultivation Points way -- the
    Path pool the ability's printed CP cost compiles to -- which
    centering leaves at its printed cost, so it reads as CP. An
    alternative way (the compiler's ``#pay`` row) is the printed
    alternative, Stamina for these four talents, named by the
    resource it actually pays; centering has already reduced it
    by one, never below one."""
    if alternative:
        return ", ".join(
            f"{amount} {'Stamina' if str(rid) == STAMINA else COST_WORDS.get(str(rid), str(rid))}"
            for rid, amount in costs)
    return ", ".join(f"{amount} CP" for _rid, amount in costs)


def _toward_caster(effects: list[Any]) -> list[Any]:
    """Every forced-movement row of the pull travels toward the caster."""
    out = []
    for effect in effects:
        if isinstance(effect, dict):
            effect = dict(effect)
            if effect.get("type") == "forced_movement":
                effect["direction"] = "toward"
            for key in ("on_fail", "on_success"):
                if isinstance(effect.get(key), list):
                    effect[key] = _toward_caster(effect[key])
        out.append(effect)
    return out


# ------------------------------------------------------------------ the ride with the area
@hook("zone_created")
def record_center_turn(ctx: Any, zone: Any) -> None:
    """Record the turn this area was centered, so it stops riding next turn."""
    profile = zone.trigger_profile
    if not (profile.get("profile") or {}).get("body_center"):
        return
    zone.trigger_profile = {**profile, "body_center_turn": int(ctx.actor.turns_started)}


@hook("zone_follows")
def ride_until_next_turn(engine: Any, zone: Any) -> bool | None:
    """A centered area rides its owner only until the start of the owner's next turn."""
    profile = zone.trigger_profile
    if not (profile.get("profile") or {}).get("body_center"):
        return None
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None:
        return None
    return int(owner.turns_started) <= int(profile.get("body_center_turn") or 0)
