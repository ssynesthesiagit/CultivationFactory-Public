"""Folded Reach (Space; rider lane C11, 2026-09-30).

Source (owner text, authority/typed_mechanics/rules_text.json tianxia.talent.space.folded_reach):
  "Bonus Action. Duration: Until the end of your current turn. Cost: 1 CP. Your next melee weapon attack, Unarmed Strike, touch talent,
  or harmless touch effect made before the end of your turn may originate from a point you can see within 10 feet of you. At CL 10,
  this distance becomes 15 feet. At CL 15, it becomes 20 feet. The attack or effect still uses its normal range from the folded point.
  This talent does not allow you to attack through total cover, sealed barriers, or Dimensional Lock."

How it runs. The Folded Reach button (typed effect ``folded_reach``, reviewed_final.d/riders_c11.json) puts "Folded Reach" on its user
until the end of the turn, carrying the folded distance for the user's CL (10 / 15 / 20 ft). While it lasts, each of the user's melee
weapon attacks and touch techniques has a "(Folded Reach)" twin whose reach is its normal reach plus that distance ("its normal range
from the folded point"), offered only against a creature beyond the normal reach; the next qualifying use spends the fold even at normal reach,
and only the first attack of an Attack action reaches that far (the others keep the normal reach: ``later_reach_ft``). Line of sight
and cover are still measured from the user's own square -- the engine has no attack-origin point, so a creature the user cannot see
cannot be reached this way, which also keeps "does not allow you to attack through total cover" true.
Default-inert: no twin is compiled for a fighter without the talent, and no twin is offered without the state.
"""

from __future__ import annotations

import json
from typing import Any

from . import effect, hook
from .condition_ownership import remove_instance

TALENT = "tianxia.talent.space.folded_reach"
STATE = "condition:typed.folded_reach"
SUFFIX = ".folded_reach"
BANDS = ((1, 9, 10), (10, 14, 15), (15, 20, 20))  # "At CL 10, this distance becomes 15 feet. At CL 15, it becomes 20 feet."
_MECHANICS: dict[str, Any] = {}


def distance_ft(cl: int) -> int:
    return next((feet for low, high, feet in BANDS if low <= int(cl) <= high), 10)


def _mechanics() -> dict[str, Any]:
    if not _MECHANICS:
        from .. import factory_compiler

        _MECHANICS.update(json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"])
    return _MECHANICS


def _state(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == STATE), None)


@effect("folded_reach")
def fold(ctx: Any, row: dict[str, Any]) -> None:
    for key, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == STATE:
            remove_instance(ctx.engine, ctx.actor, key, ctx.source)
    feet = distance_ft(int(ctx.numbers.get("cl") or 1))
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"extra_ft": feet, "label": "Folded Reach",
                                      "reading": f"Your next melee weapon attack or touch technique this turn may reach {feet} feet farther "
                                                 "(it strikes from a folded point beside you)."})


def _mechanic_of(action_id: str) -> str:
    parts = str(action_id).split(".", 2)
    return parts[2].split("+")[0].split("#")[0] if len(parts) == 3 else ""


def _foldable(action: Any) -> bool:
    """A melee weapon attack (not thrown or shot, not a reaction) or a touch technique."""
    typed = (action.parameters or {}).get("typed") or {}
    if str(action.economy).split(".")[-1] not in ("ACTION", "BONUS_ACTION") or (action.parameters or {}).get("basic"):
        return False
    if action.target_kind not in ("HOSTILE_ENTITY", "ALLY_OR_SELF", "ALLY", "ANY_ENTITY", "HOSTILE_ENTITY_OR_SELF"):
        return False
    attacks = [e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"]
    if attacks:
        return (bool(typed.get("weapon")) and not typed.get("long_range_ft") and int(action.range_ft or 5) <= 10
                and all(e.get("attack_kind") in ("weapon", "melee", "unarmed", "cultivation_melee") for e in attacks))
    mechanic = _mechanics().get(_mechanic_of(action.source_definition_id)) or {}
    return (mechanic.get("range") or {}).get("kind") == "touch" and bool(mechanic.get("sphere_id"))


@hook("compile_actions")
def folded_twins(info: dict[str, Any]) -> list[Any] | None:
    if TALENT not in info["owned_ids"]:
        return None
    from ..action_variants import choice, extend_variant, with_variant

    feet = distance_ft(int((info.get("numbers") or {}).get("cl") or 1))
    made = []
    for action in info["actions"]:
        if not _foldable(action):
            continue
        parameters = json.loads(json.dumps(action.parameters))
        typed = parameters.get("typed") or {}
        normal = int(action.range_ft or 5)
        for row in typed.get("effects") or []:
            if isinstance(row, dict) and row.get("type") == "attack":
                row["later_reach_ft"] = normal  # only the next attack is folded
        if typed.get("range_ft"):
            typed["range_ft"] = int(typed["range_ft"]) + feet
        parameters["folded_reach"] = {"normal_ft": normal, "extra_ft": feet}
        folded = action.model_copy(update={"source_definition_id": action.source_definition_id + SUFFIX,
                                           "display_name": f"{action.display_name} (Folded Reach)",
                                           "range_ft": normal + feet, "parameters": parameters})
        reach = choice("reach", "folded", "Folded Reach")
        made.append(extend_variant(folded, reach) if action.variant is not None
                    else with_variant(folded, action.source_definition_id, action.display_name, [reach]))
    return made or None


@hook("candidate_allowed")
def only_while_folded(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    fold_row = (getattr(action, "parameters", None) or {}).get("folded_reach")
    if not fold_row:
        return None
    if _state(actor) is None:
        return False
    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", None) or ()]
    return all(target is not None and engine._distance_actor_to_actor(actor, target) > int(fold_row["normal_ft"]) for target in targets) \
        and bool(targets)


@hook("technique_used")
def spend_fold(ctx: Any) -> None:
    if _state(ctx.actor) is None or not ((ctx.action.parameters or {}).get("folded_reach") or _foldable(ctx.action)):
        return
    for key, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == STATE:
            remove_instance(ctx.engine, ctx.actor, key, ctx.source)
