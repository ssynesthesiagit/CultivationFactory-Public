"""Sound's two paid melee-hit modifiers (owner's rules_text, riders lane 5).

Body Resonance Strike and Thunder-Meridian Strike trigger on melee weapon attacks
or Unarmed Strikes, not Resonant Note's ranged Cultivation Attack. The authority
names Unarmed Strike for the compiler's existing core modifier pass. This hook
offers the same optional variants on the character's actual melee weapons, with
one action per printed outcome and payment. Ranged/thrown deliveries are excluded.
No saved-fight engine file changes are needed.
"""

import copy
from typing import Any

from . import effect, hook

FEATURES = ("TAL_SOUND_BODY_RESONANCE_STRIKE", "TAL_SOUND_THUNDER_MERIDIAN_STRIKE")


@effect("sound_equipped_resonance")
def equipped_resonance(ctx: Any, eff: dict[str, Any]) -> None:
    """Body Resonance's equipment predicate, using the evented carry/disarm state.

    Only the new paid modifier row opts in. Worn body armor, carried shields, own
    held weapons and taken weapons count. Spare unworn armor and dropped/disarmed
    equipment do not. "Or is a construct": a creature labelled Construct (the
    shared classification, combat/ext/creature_kinds.py; rider lane C12) -- AC or
    immunity is no proxy, and an unlabelled creature is not one.
    """
    from .. import carry
    from ..typed_executor import block_mark

    identities = str((ctx.typed.get("modifier") or {}).get("id") or "").split("+")
    if FEATURES[0] not in identities and ctx.effect_source != FEATURES[0]:
        return
    target = ctx.target
    if target is None or not target.active:
        return
    items = (carry.carrying_of(ctx.engine, target.entity_id) or {}).get("items") or []
    equipped = any((item.get("worn") or item.get("weapon_action")
                    or item.get("item_id") == "tianxia.mortal.armor.shield")
                   and carry.holds(ctx.engine, target, item["key"]) for item in items)
    # Taken weapons stay in their original owner's evented Disarmed condition.
    equipped = equipped or any((c.data or {}).get("held_by") == target.entity_id
                              and (c.data or {}).get("disables_action")
                              for owner in ctx.engine.state.actors.values() for c in owner.conditions.values())
    if not equipped:
        from .creature_kinds import matches

        equipped = matches(target, ["construct"])
    if equipped:
        block_mark(ctx, {**eff, "type": "mark", "mark": "Resonance", "applies_to": "target",
                         "duration": {"kind": "until_start_of_your_next_turn"}})


@hook("effect_description")
def resonance_description(row: dict[str, Any]) -> str | None:
    """Explain Sound's named mark in both its ordinary and equipment-gated rows."""
    if row.get("type") == "sound_equipped_resonance" or (row.get("type") == "mark" and row.get("mark") == "Resonance"):
        return ("Resonance: a mark from you on the target. Your Sound talents can gain extra effects against a target "
                "bearing your mark; for example, Resonant Note can deafen it on a later hit. "
                "The mark lasts for the duration stated in the effect.")
    return None


@hook("compile_actions")
def melee_strikes(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS, _attach

    melee = {w["action_id"] for w in info.get("weapon_kinds") or [] if w.get("melee")}
    result = []
    for feature in FEATURES:
        if feature not in info["owned_ids"]:
            continue
        mechanic = info["mechanics"][feature]
        modifier = mechanic.get("modifier") or {}
        for action in info["actions"]:
            if action.source_definition_id not in melee:
                continue
            typed = (action.parameters or {}).get("typed") or {}
            for index, option in enumerate(modifier.get("options") or [{}]):
                effects = copy.deepcopy([{**row, "source_modifier": feature}
                                         for row in [*(modifier.get("effects") or []), *(option.get("effects") or [])]])
                payments = set()
                for way, payment in enumerate(modifier.get("cost") or [[]]):
                    # CP maps to the primary Path pool. Keep only held pools and
                    # one row when two printed ways resolve to the same payment.
                    resolved = [(info["primary"] if c["resource"] == "cp" else c["resource"], int(c["amount"]))
                                for c in payment]
                    if any(name not in info.get("pools", (info["primary"],)) for name, _amount in resolved):
                        continue
                    signature = tuple(sorted(resolved))
                    if signature in payments:
                        continue
                    payments.add(signature)
                    costs = list(action.costs)
                    label = ""
                    for cost in payment:
                        name = cost["resource"]
                        resource = RESOURCE_IDS[info["primary"]] if name == "cp" else RESOURCE_IDS[name]
                        costs.append((resource, int(cost["amount"])))
                        label = f" ({cost['amount']} {name.upper()})"
                    suffix = f": {option['label']}" if option.get("label") else ""
                    updated = {**typed, "numbers": {**(typed.get("numbers") or {}), "save_dc": info['numbers']['save_dc']},
                               "effects": _attach(typed.get("effects") or [], effects, "hit"),
                               "modifier": {"id": feature, "name": mechanic["name"]}}
                    result.append(action.model_copy(update={
                        "source_definition_id": f"{action.source_definition_id}#sound.{feature}.{index}.{way}",
                        "display_name": f"{action.display_name} + {mechanic['name']}{suffix}{label}",
                        "costs": tuple(costs), "parameters": {**action.parameters, "typed": updated}}))
    return result or None
