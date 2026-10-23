"""Special Attacks replace one attack of the Attack action (rider lane C13, 2026-09-30; owner: "i want everything we can automated,
keep going until its only the non-combat ones left").

Printed rule (Brute and Wrestling, "Special Attacks"): "When a talent says it is a Special Attack, replace one attack when you take the
Attack action unless the talent explicitly uses a different Action Type"; the abilities themselves say "Timing Detail: Special Attack" or
"Replace one attack when you take the Attack action" (Brutal Shove, Spear Thrust, Batter, Water Lash, ...). On this table such an ability
is its own Action button, so a character with Extra Attack lost the rest of its Attack action by using one.

Now, when an Action-economy ability whose printed text says so resolves, a character whose Attack action has N attacks (its compiled
``extra_attack`` row) may still choose its other attacks this turn: basic weapon attacks and qualifying Special Attacks gain continuation
buttons, offered only while enough attacks remain (an integer turn flag that ends with the turn). A Special Attack that already makes
every attack of the Attack action itself (a weapon-delivered one: factory_compiler._deliver_with_weapons) grants nothing more.

Which abilities are Special Attacks is typed data on the reviewed records (`"special_attack": true`, carried from
authority/typed_mechanics/reviewed_final.d/*.json into authority/Tianxia_Typed_Mechanics_Authority_R1.json), never from ids and
never from the printed prose, which the public copy of the rules scrambles (PRIVCONV2).
Hooks: compose_actions (buttons after other providers, only with Extra Attack), action_completed (start or decrement the count),
candidate_allowed (remaining-slot admission). Inert for every character without Extra Attack.

Shared replacement_actions(info) creates canonical weapon and Special Attack
continuations. sniper_precision reuses it for new sealed Snipe replacements.
parameters.replaces_attack=1 is the general explicit replacement marker read by
_special; 0 excludes an action from a multi-option source record, while an absent
marker retains the historical printed Special Attack query.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from . import hook, note

REST = "attack_action_rest"
FLAG = "special_attack_rest"   # a plain turn flag: it ends with the turn


@lru_cache(maxsize=1)
def special_ids() -> frozenset[str]:
    """The mechanics the reviewed typed records mark as Special Attacks (PRIVCONV2).

    Whether an ability is a Special Attack is typed data on its reviewed record -- ``"special_attack":
    true`` in ``authority/typed_mechanics/reviewed_final.d/*.json``, carried into
    ``authority/Tianxia_Typed_Mechanics_Authority_R1.json`` by tools/build_typed_mechanics_authority.py
    -- which is the same authority the rest of the fight reads. It used to be read off the printed text
    ("Timing Detail: Special Attack" / "Replace one attack ..."), which is prose: the public copy of the
    rules scrambles it, and then no ability was a Special Attack at all.
    """
    from ..typed_numbers import authority_mechanics

    return frozenset(key for key, row in (authority_mechanics() or {}).items()
                     if isinstance(row, dict) and row.get("special_attack") is True)


def _attacks(rows: Any) -> int:
    return max([1, *(int(row.get("attacks") or 1) for row in rows or [] if row.get("block") == "extra_attack")])


def attacks_of(engine: Any, actor: Any) -> int:
    return _attacks((getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("compose_actions")
def rest_of_the_attack_action(info: dict[str, Any]) -> list[Any] | None:
    if _attacks(info.get("passives")) <= 1 or not (special_ids() & set(info["owned_ids"])):
        return None
    existing = {a.source_definition_id for a in info.get("actions") or []}
    return [a for a in replacement_actions(info) or [] if a.source_definition_id not in existing]


def replacement_actions(info: dict[str, Any]) -> list[Any] | None:
    """Compile owned Attack-action choices, preserving each talent's full payload.

    Weapon entries gain an optional single-strike Action to begin a mixed sequence.
    Remaining weapons spend one slot; remaining Special Attacks retain their own
    attack count, costs, targeting and restrictions. Explicit other economies and
    already composed entries are excluded. Callers own character eligibility.
    """
    if _attacks(info.get("passives")) <= 1:
        return None
    import copy

    from ..gate2_runtime_models import EconomyKind
    from .weapon_actions import weapon_attacks

    out = []
    for action, typed, attack, _kind in weapon_attacks(info.get("actions") or [], info["actor_id"]):
        one = copy.deepcopy(typed)
        # The weapon-delivery contract (combat/ext/__init__.py): weapon_hits.available_weapons/weapon_identity treat this copy as that
        # weapon, and weapon_actions.weapon_attacks does not offer it again as a weapon of its own.
        one["weapon_source_id"] = action.source_definition_id
        one["variant_of"] = action.source_definition_id
        strike = {**copy.deepcopy(attack), "count": 1}
        strike.pop("count_by_cl", None)
        one["effects"] = [strike if effect is attack else copy.deepcopy(effect) for effect in typed.get("effects") or []]
        out.append(action.model_copy(update={
            "source_definition_id": f"{action.source_definition_id}.{REST}", "display_name": f"{action.display_name} (rest of the Attack action)",
            "economy": EconomyKind.NONE,
            "parameters": {**action.parameters, "typed": one, REST: True,
                           "expected_damage": int(int(action.parameters.get("expected_damage") or 0) / max(1, int(attack.get("count") or 1))),
                           "description": "One more attack of your Attack action, after a Special Attack replaced one of its attacks."}}))
        out.append(action.model_copy(update={
            "source_definition_id": f"{action.source_definition_id}.attack_action_begin",
            "display_name": f"{action.display_name} (one attack; choose the rest)",
            "parameters": {**out[-1].parameters, REST: False, "begins_attack_action": True,
                           "description": "Spend your Action to make one weapon attack, then choose the remaining attacks of the same Attack action."}}))
    compiled = {action.source_definition_id for action in out}
    for action in info.get("actions") or []:
        if (action.owner_id != info["actor_id"] or action.economy != EconomyKind.ACTION
                or action.parameters.get(REST) or action.parameters.get("begins_attack_action") or not _special(action)
                or f"{action.source_definition_id}.{REST}" in compiled):
            continue
        out.append(action.model_copy(update={
            "source_definition_id": f"{action.source_definition_id}.{REST}",
            "display_name": f"{action.display_name} (replace remaining attacks)",
            "economy": EconomyKind.NONE,
            "parameters": {**copy.deepcopy(action.parameters), REST: True,
                "description": str(action.parameters.get("description") or "") +
                    " Uses remaining attacks of the same Attack action; all of this ability's normal costs and requirements still apply."}}))
    return out or None


def _special(action: Any) -> bool:
    params = getattr(action, "parameters", None) or {}
    if "replaces_attack" in params:
        return params["replaces_attack"] == 1
    typed = params.get("typed") or {}
    return str(typed.get("option_of") or typed.get("source") or "") in special_ids()


def _slots(action: Any) -> int:
    """A talent keeps its printed attack count; a non-strike maneuver replaces one."""
    typed = (action.parameters or {}).get("typed") or {}
    cl = int((typed.get("numbers") or {}).get("cl") or 1)
    total = 0
    for effect in typed.get("effects") or []:
        if not isinstance(effect, dict) or effect.get("type") != "attack":
            continue
        count = int(effect.get("count") or 1)
        for low, high, scaled in effect.get("count_by_cl") or []:
            if int(low) <= cl <= int(high):
                count = int(scaled)
                break
        total += count
    return max(1, total)


@hook("action_completed")
def special_attack_made(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    action = engine.action_catalog.get(source_definition_id)
    if action is None:
        return
    if (action.parameters or {}).get(REST):
        actor.turn_flags[FLAG] = max(0, int(actor.turn_flags.get(FLAG) or 0) - _slots(action))
        return
    if (str(economy).upper() != "ACTION" or str(action.economy).upper() != "ACTION"
            or not (_special(action) or action.parameters.get("begins_attack_action"))):
        return
    attacks = attacks_of(engine, actor)
    own = _slots(action)
    left = attacks - own
    if left <= 0:
        return
    actor.turn_flags[FLAG] = left
    note(engine, source_definition_id, actor, f"{action.display_name} used {own} attack{'s' if own > 1 else ''} of {actor.display_name}'s Attack action: "
                                              f"{left} more attack{'s' if left > 1 else ''} this turn.")


@hook("candidate_allowed")
def rest_left(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get(REST):
        return None
    return not actor.action_available and int(actor.turn_flags.get(FLAG) or 0) >= _slots(action)


def _rest_reason(engine: Any, actor: Any, action: Any) -> str | None:
    """Plain text when a rest-of-the-Attack row has no attacks left to spend; None while it is usable."""
    if action is None or not (action.parameters or {}).get(REST):
        return None
    left = int(actor.turn_flags.get(FLAG) or 0)
    if not actor.action_available and left >= _slots(action):
        return None
    if actor.action_available:
        return "Use a Special Attack first: these are the attacks it leaves in your Attack action."
    total = attacks_of(engine, actor)
    if left <= 0:
        return ("Both attacks from your Attack action are used." if total == 2
                else f"All {total} attacks from your Attack action are used.")
    return f"This needs {_slots(action)} attacks left in your Attack action; you have {left}."


@hook("candidate_unavailability")
def rest_left_explained(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    """The reason beside a refused rest-of-the-Attack expansion (combat/ext/__init__.py availability hooks)."""
    return _rest_reason(engine, actor, action)


@hook("source_unavailable")
def rest_left_source_unavailable(engine: Any, actor: Any, action: Any) -> str | None:
    """The same plain reason for the lazy menu header, whose candidate vetoes run only on expansion."""
    return _rest_reason(engine, actor, action)
