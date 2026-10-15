"""Printed alternate delivery for Thousand-Spark Volley, using compiled Lightning Lash.

The Cultivation Attack has Lash's ordinary Lightning attack damage, followed by
Volley's own hit/miss riders. Weapon delivery remains native and is capped at
120 feet. Arc's existing hostile/visible recipient filter handles both routes.
"""
from __future__ import annotations
import copy
from typing import Any
from . import hook

VOLLEY = "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY"
LASH = "TAL_LIGHTNING_LIGHTNING_LASH"


@hook("compile_actions")
def cultivation_volley(info: dict[str, Any]) -> list[Any] | None:
    if VOLLEY not in info["owned_ids"]:
        return None
    volley = next((a for a in info["actions"]
                   if (a.parameters.get("typed") or {}).get("source") == VOLLEY), None)
    lash = next((a for a in info["actions"]
                 if (a.parameters.get("typed") or {}).get("source") == LASH), None)
    if volley is None:
        return None
    typed = copy.deepcopy(volley.parameters["typed"])
    attack = next(row for row in typed["effects"] if row.get("type") == "attack")
    if lash is not None:
        lash_attack = next(row for row in lash.parameters["typed"]["effects"] if row.get("type") == "attack")
    else:
        # Volley grants this delivery itself; a separately listed Lash is unnecessary.
        options = info["mechanics"][LASH]["options"]
        lash_attack = next(row for option in options for row in option["effects"] if row.get("type") == "attack")
    # Normal damage only: Lash's optional Arc is not another Volley secondary.
    damage = [copy.deepcopy(row) for row in lash_attack.get("on_hit", []) if row.get("type") == "damage"]
    attack.update(attack_kind="cultivation_ranged", on_hit=[*damage, *attack.get("on_hit", [])])
    typed.update(source=VOLLEY + ".cultivation", range_ft=120, weapon=None, riders=[])
    return [volley.model_copy(update={
        "source_definition_id": volley.source_definition_id + ".cultivation",
        "display_name": "Thousand-Spark Volley: Cultivation Attack",
        "target_kind": "HOSTILE_ENTITY", "range_ft": 120,
        "parameters": {**volley.parameters, "typed": typed}})]


@hook("compile_action")
def volley_weapon_range(action: Any, info: dict[str, Any]) -> Any:
    typed = action.parameters.get("typed") or {}
    if typed.get("source") != VOLLEY or not typed.get("weapon"):
        return action
    normal = min(120, int(typed.get("range_ft") or action.range_ft or 120))
    return action.model_copy(update={"range_ft": min(120, int(action.range_ft or 120)),
        "parameters": {**action.parameters, "typed": {**typed, "range_ft": normal,
                                                        "long_range_ft": min(120, int(typed.get("long_range_ft") or normal))}}})


@hook("compile_action")
def needle_save_numbers(action: Any, info: dict[str, Any]) -> Any:
    """Seal the Lightning save DC in its hit-time rider, independent of weapon mastery DC."""
    if "TAL_LIGHTNING_CHARGED_NEEDLE" not in info["owned_ids"]:
        return action
    typed = copy.deepcopy(action.parameters.get("typed") or {})
    changed = False
    def visit(value: Any) -> None:
        nonlocal changed
        if isinstance(value, dict):
            if value.get("type") == "charged_needle_choice":
                value["numbers"] = dict(info["numbers"])
                changed = True
            for child in list(value.values()):
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(typed)
    return action.model_copy(update={"parameters": {**action.parameters, "typed": typed}}) if changed else action


@hook("effect_player_text")
def needle_choice_text(row: dict[str, Any]) -> str | None:
    if row.get("type") != "charged_needle_choice":
        return None
    return ("After the hit, you may place a Charge until your next turn starts. "
            "If the target already had a Charge, you may instead consume it and force a Constitution saving throw. "
            "On a failure it cannot regain Cultivation Points until your next turn starts; "
            "on a success it cannot regain them until the current turn ends. Points it already holds are unchanged.")
