"""Buffs cast before a fight (owner 2026-09-29: "it takes 10 minutes to cast meld which is pretty annoying. We should allow
at the beginning of the fights 2 persistent buffs for each entry"). Rulings the same day: a buff qualifies when it lasts
10 minutes or longer (Melds included because they last up to an hour); its CP is paid from the
fighter's starting pool; at most one of the two uses Concentration (as many as the fighter may hold at once, by its
Cultivation Level, since several Concentrations were allowed the same day: combat/concentration.py); the AI picks its best
two for every fighter, and the player may change them when setting up the fight.

- options(): the buffs a compiled character may start with, stored in its bundle ("prefight": {"options", "picks",
  "chosen"}) by combat/factory_compiler.py. A qualifying buff helps its user or an ally (no attack, save, damage, forced
  movement, summon or area to place) and lasts 10 minutes or longer. A Meld is cast by its ritual before a fight: no
  Melds take one Action; Persistent Meld's 2 CP take it off Concentration.
- choose() / validate(): the AI's two picks, and a player's picks checked against the rules above (no more CP than the
  fighter starts with; Melds stack since the owner struck the one-Meld sentence on 2026-09-29).
- cast_all(): as the match is made (Gate2Engine.__init__, after the first turn starts), every fighter's picks are paid
  and take effect through the engine's evented methods; they are part of the match's genesis, so a saved fight keeps them.
"""

from __future__ import annotations

import copy
from typing import Any

MAX_PICKS = 2
SOURCE = "system:prefight"
_HARMFUL = {"attack", "save", "damage", "extra_damage", "forced_movement", "zone", "summon", "teleport", "movement"}
_LONG_KINDS = {"hours", "days", "until_long_rest", "until_short_rest", "until_dispelled", "permanent"}


def _long(duration: dict[str, Any] | None) -> bool:
    duration = duration or {}
    kind, amount = str(duration.get("kind") or ""), duration.get("amount")
    if kind in _LONG_KINDS:
        return True
    return kind == "minutes" and isinstance(amount, (int, float)) and amount >= 10


def _walk(effects: Any):
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(effect.get(key))


def _duration_text(duration: dict[str, Any] | None, concentration: bool) -> str:
    duration = duration or {}
    amount, kind = duration.get("amount"), str(duration.get("kind") or "").replace("_", " ")
    text = f"{amount} {kind[:-1] if amount == 1 and kind.endswith('s') else kind}" if amount else kind
    return f"{'Concentration, ' if concentration else ''}{text}".strip(", ")


def options(actions: list[Any], actor_id: str) -> list[dict[str, Any]]:
    """The buffs this fighter may start a fight with, in the order its actions compiled."""
    from . import ext

    out = []
    for action in actions:
        parameters = action.parameters or {}
        typed = parameters.get("typed")
        if action.owner_id != actor_id or action.resolution_kind != "TYPED" or not isinstance(typed, dict):
            continue
        if ext.any_false('prefight_allowed', action):
            continue
        if str(action.economy.value if hasattr(action.economy, "value") else action.economy) not in ("ACTION", "BONUS_ACTION", "NONE"):
            continue
        costs = [[resource, int(amount)] for resource, amount in action.costs]
        if parameters.get("meld_talent"):
            # Ordinary Meld costs no CP; Persistent Meld's separate 2 CP cost remains.
            concentration = any(effect.get("concentration") for effect in typed.get("effects") or [] if isinstance(effect, dict))
            out.append({"action_id": action.source_definition_id, "name": action.display_name, "meld": parameters["meld_talent"],
                        "concentration": concentration, "costs": costs,
                        "description": _description(action, typed, parameters),
                        "duration": "Concentration, up to 1 hour" if concentration else "up to 1 hour"})
            continue
        if parameters.get("player_only") or parameters.get("inert"):
            continue  # a free choice toggle, or an ability combat runs nothing for
        if action.target_kind not in ("SELF", "ALLY", "ALLY_OR_SELF") or typed.get("area") or typed.get("zone_spec"):
            continue
        if not _long(typed.get("duration")) or any(effect.get("type") in _HARMFUL for effect in _walk(typed.get("effects"))):
            continue
        concentration = bool((typed.get("duration") or {}).get("concentration"))
        out.append({"action_id": action.source_definition_id, "name": action.display_name, "meld": None, "concentration": concentration,
                    "costs": costs, "duration": _duration_text(typed.get("duration"), concentration),
                    "description": _description(action, typed, parameters)})
        # Keep legal player choices; equipment changes and combat-disabling
        # forms require a deliberate choice rather than an automatic buff.
        if any(e.get('type') in {'drop_item', 'take_weapon', 'pickup_item', 'recover_weapon', 'equipment_grip'}
               or (e.get('type') == 'condition' and str(e.get('condition', '')).split('.')[-1]
                   in {'disarmed', 'unconscious', 'incapacitated'})
               for e in _walk(typed.get('effects'))) or ext.any_false('prefight_ai_allowed', action):
            out[-1]['ai_eligible'] = False
    return out


def _description(action: Any, typed: dict[str, Any], parameters: dict[str, Any]) -> str:
    """The public shared action text for the compiled choice and selected talent."""
    from .action_text import describe_action

    row = {"source_definition_id": action.source_definition_id, "display_name": action.display_name,
           "parameters": {**parameters, "typed": typed}}
    ability = describe_action(row)
    if parameters.get("meld_talent") and ability:
        return f"This affects this fighter. {ability}"
    return ability


def _affordable(picked: list[dict[str, Any]], pools: dict[str, int]) -> bool:
    spent: dict[str, int] = {}
    for option in picked:
        for resource, amount in option["costs"]:
            spent[resource] = spent.get(resource, 0) + int(amount)
    return all(spent[resource] <= int(pools.get(resource, 0)) for resource in spent)


def validate(picks: list[str], offered: list[dict[str, Any]], pools: dict[str, int], max_concentration: int = 1) -> list[str]:
    """A player's picks, checked; raises ValueError with the reason."""
    by_id = {option["action_id"]: option for option in offered}
    unknown = [pick for pick in picks if pick not in by_id]
    if unknown:
        raise ValueError("That choice is not available for this fighter before the fight.")
    picked = [by_id[pick] for pick in dict.fromkeys(picks)]
    if len(picked) > MAX_PICKS:
        raise ValueError(f"At most {MAX_PICKS} buffs before a fight.")
    if sum(1 for option in picked if option["concentration"]) > max_concentration:
        raise ValueError("At most one of them may use Concentration." if max_concentration == 1
                         else f"At most {max_concentration} of them may use Concentration.")
    if len({option["meld"] for option in picked if option["meld"]}) < sum(1 for option in picked if option["meld"]):
        raise ValueError("You can choose each Meld only once.")
    if not _affordable(picked, pools):
        raise ValueError("Not enough CP to have cast them before the fight.")
    return [option["action_id"] for option in picked]


def choose(offered: list[dict[str, Any]], pools: dict[str, int], meld_order: list[str] | None = None, max_concentration: int = 1) -> list[str]:
    """The AI's two: its best Meld first (Persistent when affordable, keeping Concentration free; the first known in the
    Dark sphere's list, so Clearsight when known), then other buffs without Concentration, then with it -- costlier first
    -- and only then a second Meld."""
    offered = [option for option in offered if option.get('ai_eligible', True)]
    order = {talent: index for index, talent in enumerate(meld_order or [])}
    melds = sorted((option for option in offered if option["meld"]),
                   key=lambda option: (order.get(option["meld"], 99), option["concentration"]))
    others = sorted((option for option in offered if not option["meld"]),
                    key=lambda option: (option["concentration"], -sum(amount for _resource, amount in option["costs"]), option["name"]))
    picked: list[dict[str, Any]] = []
    for option in [*melds[:2], *others, *melds[2:]]:
        trial = [*picked, option]
        same_meld = len({row["meld"] for row in trial if row["meld"]}) < sum(1 for row in trial if row["meld"])
        if len(trial) > MAX_PICKS or sum(1 for row in trial if row["concentration"]) > max_concentration or same_meld:
            continue
        if _affordable(trial, pools):
            picked = trial
    return [option["action_id"] for option in picked]


def starting_pools(bundle: dict[str, Any]) -> dict[str, int]:
    return {row["resource_id"]: int(row.get("initial") or 0) for row in (bundle.get("actor_template") or {}).get("resources") or []}


def cast_all(engine: Any) -> None:
    """Every fighter's picks, once, as the match is made. Plug-ins' event hooks do not see them (they are the fight's
    starting state, the same whether the engine is made by the combat service or directly); a pick that fails to cast is
    left to the GM rather than stopping the fight."""
    held = engine.__dict__.get("_ext_in_event", False)
    engine._ext_in_event = True
    try:
        for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
            actor = engine.state.actors.get(bundle.get("actor_id"))
            if actor is None or not (bundle.get("prefight") or {}).get("picks"):
                continue
            try:
                cast(engine, actor, bundle)
            except Exception as exc:  # noqa: BLE001 -- a buff that fails is the GM's, not the end of the fight
                engine._append_event("GM_RIDER", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"rider": "A buff cast before the fight did not take effect; the GM applies it.",
                                              "error_type": type(exc).__name__})
    finally:
        engine._ext_in_event = held


def cast(engine: Any, actor: Any, bundle: dict[str, Any]) -> None:
    """Pay for and cast this fighter's picks. Its Meld replaces the one it would otherwise have started with; a
    Concentration buff starts its Concentration."""
    from . import typed_executor

    prefight = bundle.get("prefight") or {}
    by_id = {option["action_id"]: option for option in prefight.get("options") or []}
    picks = [pick for pick in prefight.get("picks") or [] if pick in by_id and pick in engine.action_catalog]
    if not picks or not actor.active:
        return
    engine._append_event("PASSIVE_TRIGGERED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"trigger": f"Cast before the fight: {', '.join(by_id[pick]['name'] for pick in picks)}"})
    for pick in picks:
        option, action = by_id[pick], engine.action_catalog[pick]
        from . import ext
        # Unlike a foreground activation, setup has no candidate/intent and
        # cannot ask a new question. Its explicit sealed pick owns every mode.
        action = ext.transform('prefight_prepare', action, engine, actor, option)
        for resource, amount in option["costs"]:
            engine._spend_resource(actor, resource, int(amount), SOURCE)
        from . import ext
        ext.run_strict('technique_accepted', engine, actor, action)

        # A pre-fight cast is still a technique activation: let plug-ins handle
        # general activation costs such as consumed formulae before its effects.
        if any(ext.run("technique_start", engine, actor, action)):
            continue
        typed = dict(action.parameters.get("typed") or {})
        typed["numbers"] = dict(typed.get("numbers") or {})
        typed['activation_phase'] = 'prefight'
        effects = copy.deepcopy(typed.get("effects") or [])
        # Cast on itself before the fight (an ally buff too: its allies' picks are their own).
        ctx = typed_executor.Context(engine, actor, action, None, typed, [actor], actor)
        if option["concentration"]:
            engine._start_concentration(actor, action.source_definition_id)
        first_event = len(engine.events)
        typed_executor.run_effects(ctx, effects)
        from .activation_settlement import settle
        settle(ctx, first_event)
