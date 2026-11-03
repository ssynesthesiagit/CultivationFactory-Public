"""Talisman Affinity's crafting choices and stored combat bonuses.

Uses the same declared-crafting model as Elemental Talisman: each learning
records a distinct family, then an activation asks which benefit that talisman
was crafted with. This is not crafting, and spends no new crafting payment.
Only newly compiled owned formulas carry the wrapper; saved catalogs are inert.
"""
from copy import deepcopy
from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .talismans import TALENT, SPHERE, formula_of

OWNER = TALENT + "talisman_affinity"
FAMILY = "condition:typed.talisman_affinity"
FAMILIES = {
    "ember_talisman": ("Attack",), "binding_talisman": ("Binding",),
    "healing_talisman": ("Restoration",), "purifying_talisman": ("Purification",),
    "warding_talisman": ("Shielding",), "shield_talisman": ("Shielding",),
    "featherfall_talisman": ("Movement",), "revealing_talisman": ("Detection",),
    "message_talisman": ("Communication",), "qi_storage_talisman": ("Sealing", "Restoration"),
    "ghost_warding_talisman": ("Purification", "Sealing"),
    "demon_subduing_tag": ("Binding", "Purification", "Sealing"),
}
BENEFITS = {
    "none": "No stored combat bonus (or crafted for cheaper materials or less crafting time)",
    "save": "Crafted with +1 to its stored saving throw DC",
    "attack": "Crafted with +1 to its stored attack modifier",
    "healing": "Crafted to add your Proficiency Bonus to one healing roll",
}


def families(actor: Any) -> set[str]:
    """Distinct families previously selected for this owner's learnings."""
    return {str((row.data or {}).get("family")) for row in actor.conditions.values()
            if row.condition_id.startswith(FAMILY + ".") and (row.data or {}).get("family")}


@hook("compile_actions")
def setting(info: dict) -> list | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    count = sum(key == OWNER for key in info.get("owned_ids") or [])
    if not count:
        return None
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.talisman.affinity", owner_id=info["actor_id"],
        display_name="Talisman Affinity: choose a formula family", economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF", parameters={
            "player_only": True, "affinity_learnings": count,
            "description": "Choose a different formula family for each learning of Talisman Affinity. "
                           "When you use a talisman from that family, record its crafting benefit: "
                           "+1 saving throw DC, +1 attack modifier, or your Proficiency Bonus on one healing roll. "
                           "This choice costs no action or cultivation points and lasts for this fight.",
            "typed": {"source": OWNER, "sphere": SPHERE, "numbers": dict(info["numbers"]),
                      "effects": [{"type": "talisman_affinity_family"}], "riders": [],
                      "duration": {"kind": "instant"}, "coverage": "FULL"}})]


@effect("talisman_affinity_family")
def choose_family(ctx: Any, row: dict) -> None:
    known = families(ctx.actor)
    if len(known) >= int(ctx.action.parameters.get("affinity_learnings") or 1):
        return
    offered = sorted({family for value in FAMILIES.values() for family in value} - known)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "talisman_affinity_family", ctx.actor.entity_id),
                 ctx.actor, CHOICE + "talisman_affinity_family", offered,
                 labels={key: key + " formula family" for key in offered}, preferred=offered[:1],
                 prompt="Talisman Affinity: which different formula family did you learn to improve? "
                        "This choice costs no action or cultivation points.", name="Talisman Affinity", feature_id=OWNER)
    if picked:
        family = picked[0]
        ctx.engine._apply_condition(ctx.actor, FAMILY + "." + family.lower(), OWNER, ctx.actor.entity_id,
                                    expires_on="UNTIL_REMOVED", data={"family": family,
                                    "label": f"Talisman Affinity: {family} formulae can carry a chosen crafting bonus"})


@hook("candidate_allowed")
def setting_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.parameters.get("affinity_learnings"):
        return False if len(families(actor)) >= int(action.parameters["affinity_learnings"]) else None
    return None


@hook("compile_action")
def wrap_formula(action: Any, info: dict) -> Any | None:
    formula = formula_of(action)
    if OWNER not in (info.get("owned_ids") or []) or formula not in FAMILIES:
        return None
    typed = deepcopy(action.parameters.get("typed") or {})
    rows = typed.get("effects") or []
    if not rows or rows[0].get("type") == "talisman_affinity_formula":
        return None
    typed["effects"] = [{"type": "talisman_affinity_formula", "formula": formula}, *rows]
    return action.model_copy(update={"parameters": {**action.parameters, "typed": typed}})


@effect("talisman_affinity_formula")
def activate(ctx: Any, row: dict) -> None:
    if not families(ctx.actor).intersection(FAMILIES.get(row.get("formula"), ())):
        return
    affected = ctx.target_display()
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "talisman_affinity_benefit", ctx.actor.entity_id),
                 ctx.actor, CHOICE + "talisman_affinity_benefit", list(BENEFITS), labels=BENEFITS,
                 preferred=["none"], prompt=f"Talisman Affinity: which benefit was {ctx.action.display_name}, "
                 f"affecting {affected}, crafted with? This records its crafting benefit for this activation "
                 "and costs no additional cultivation points.", name="Talisman Affinity", feature_id=OWNER,
                 target_id=ctx.target.entity_id if ctx.target is not None else ctx.actor.entity_id)
    benefit = picked[0] if picked else "none"
    numbers = dict(ctx.numbers)
    if benefit in ("save", "attack"):
        key = "save_dc" if benefit == "save" else "attack_bonus"
        numbers[key] = int(numbers.get(key) or 0) + 1
    if benefit == "healing":
        ctx.damage_cache["talismans:affinity_healing_ready"] = True
    # This Context belongs to this activation. Never mutate the sealed action.
    ctx.typed = {**ctx.typed, "numbers": numbers}
    if benefit != "none":
        note(ctx.engine, ctx.source, ctx.actor, f"Talisman Affinity: {ctx.action.display_name}: {BENEFITS[benefit]}.")


@hook("healing_roll_bonus")
def heal(ctx: Any, row: dict) -> int | None:
    key = "talismans:affinity_healing"
    if ctx.damage_cache.get("talismans:affinity_healing_ready") and not ctx.damage_cache.get(key):
        ctx.damage_cache[key] = True
        return int(ctx.numbers.get("pb") or 2)
    return None
