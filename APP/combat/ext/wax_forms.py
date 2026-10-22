"""Living Wax Form's paid changes, sealed only into newly compiled actions.

The lifecycle marker prevents simultaneous forms. A change costs 1 CP and keeps
the original one-minute deadline; it never refreshes that deadline. Existing
form effects remain the single implementation for each form's benefits.
"""
import copy
from dataclasses import replace
from typing import Any

from . import effect, hook
from .end_effect import remove_instance
from .states import active
from ..typed_executor import run_effects

FEATURE = "TAL_WAX_LIVING_WAX_FORM"
NAMES = tuple("living_wax_form_" + name for name in ("soft_body", "set_body", "wick_body"))


def current(engine: Any, actor: Any) -> Any:
    return active(engine, actor, *NAMES)


def enabled(info: dict[str, Any]) -> bool:
    record = (info.get("mechanics") or {}).get(FEATURE) or {}
    return FEATURE in set(info.get("owned_ids") or ()) and any(
        row.get("type") == "wax_form_lifecycle" for row in record.get("effects") or [])


@hook("compile_action")
def initial_form(action: Any, info: dict[str, Any]) -> Any:
    typed = action.parameters.get("typed") or {}
    if not enabled(info) or typed.get("source") != FEATURE or action.source_definition_id.endswith(".change"):
        return None
    parameters = copy.deepcopy(action.parameters)
    parameters["typed"]["effects"] = [{"type": "wax_form_lifecycle"}, *(typed.get("effects") or [])]
    return action.model_copy(update={"parameters": parameters})


@hook("button_description")
def description(action: dict[str, Any]) -> str | None:
    from .choice_costs import quote
    if not str(action.get("source_definition_id") or "").endswith(".change"):
        return None
    rows = ((action.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if not any(row.get("type") == "wax_form_change" for row in rows):
        return None
    numbers = ((action.get("parameters") or {}).get("typed") or {}).get("numbers") or {}
    name = next((effect.get("name") for row in rows for effect in row.get("effects") or []
                 if effect.get("type") == "state" and effect.get("name") in NAMES), None)
    benefits = {
        NAMES[0]: ("Your body softens. You have Advantage on checks and saves to escape Grappled or Restrained, "
                   "and Disadvantage on saves against pushes, pulls or being knocked Prone. "
                   "You can fit through a 1-inch gap if your rigid equipment can pass too; the GM checks such gaps and equipment."),
        NAMES[1]: (f"You gain {2 * int(numbers.get('cl') or 0)} Temporary Hit Points. While these points remain, "
                   "reduce forced movement by 10 feet and gain Advantage on saves against being knocked Prone."),
        NAMES[2]: (f"The first time each round a melee attack hits you, you may spend your Reaction to deal "
                   f"{int(numbers.get('pb') or 0)} fire damage to the attacker and shine bright candlelight "
                   "in a 10-foot radius until your next turn starts."),
    }
    return ("Bonus Action. Cost: " + (quote(action.get("costs") or []) or "none")
            + ". You change your active Living Wax Form. " + benefits.get(name, "")
            + " The form lasts only for the time left on the original one-minute use.")


@hook("compile_actions")
def changes(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS

    if not enabled(info):
        return None
    result = []
    for action in info.get("actions") or []:
        typed = action.parameters.get("typed") or {}
        rows = typed.get("effects") or []
        if typed.get("source") != FEATURE:
            continue
        parameters = copy.deepcopy(action.parameters)
        parameters["typed"]["effects"] = [{"type": "wax_form_change", "effects": copy.deepcopy(rows)}]
        primary = RESOURCE_IDS[str(info.get("primary") or "qi")]
        discounted = False
        costs = []
        for pool, amount in action.costs:
            if pool == primary and not discounted:
                amount = max(0, amount - 1)  # 2-CP activation -> 1-CP change; preserve every added fee.
                discounted = True
            if amount:
                costs.append((pool, amount))
        result.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + ".change",
            "display_name": action.display_name.replace("Living Wax Form:", "Change Living Wax Form:"),
            "costs": tuple(costs),
            "parameters": parameters,
        }))
    return result or None


@hook("candidate_allowed")
def change_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    rows = (action.parameters.get("typed") or {}).get("effects") or []
    if not any(row.get("type") == "wax_form_change" for row in rows):
        return None
    previous = current(engine, actor)
    requested = next((effect.get("name") for row in rows if row.get("type") == "wax_form_change"
                      for effect in row.get("effects") or [] if effect.get("type") == "state"), None)
    return previous is not None and requested is not None and previous.data.get("name") != requested


@effect("wax_form_lifecycle")
def end_previous(ctx: Any, row: dict[str, Any]) -> None:
    """End only this user's previous form benefits; granted temporary HP remain.

    Temporary HP are a grant, rather than a timed modifier. Removing the old
    Set Body state ends its defenses without erasing an already-granted pool.
    """
    from .wax_footing import SET_BODY_HP, SET_BODY

    same_pool = any(effect.get("type") == "state" and effect.get("name") == SET_BODY
                    for effect in (ctx.action.parameters.get("typed") or {}).get("effects") or [])
    for kind, instances in (("condition", ctx.actor.conditions), ("modifier", ctx.actor.modifiers)):
        for key, item in tuple(instances.items()):
            if kind == "condition" and item.condition_id == SET_BODY_HP and same_pool:
                # This is provenance for an accepted HP grant, not a form bonus.
                # Keep it on a Set Body recast; wax_footing restamps its deadline.
                continue
            if instances.get(key) is item and FEATURE in item.source_definition_id and item.source_actor_id == ctx.actor.entity_id:
                remove_instance(ctx, ctx.actor, kind, key, item)


@effect("wax_form_change")
def change(ctx: Any, row: dict[str, Any]) -> None:
    previous = current(ctx.engine, ctx.actor)
    if previous is None:
        return
    deadline = previous.expires_on
    # Reuse the original form action's provenance, so its existing state,
    # temporary-HP and hit-reaction readers see the same owning talent.
    original = ctx.engine.action_catalog.get(ctx.action.source_definition_id.removesuffix(".change"))
    if original is None:
        return
    inner = replace(ctx, action=original)
    end_previous(inner, {})
    effects = [{**copy.deepcopy(effect), "expires_on": deadline} for effect in row.get("effects") or []]
    run_effects(inner, effects)
