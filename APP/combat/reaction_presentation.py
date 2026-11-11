"""Pure usefulness hints for the player's complete reaction card.

TabletopService supplies already eligible contexts in engine transport order.
Only the reactor's compiled rows and known trigger data are read; no dice,
hooks, model calls or hidden future outcomes are consulted. Unknown effects
remain relevant. A provably unhelpful response moves to Other reactions, never
out of the payload. The UI sorts hints while preserving original answer keys.
These are base estimates: printed riders and qualifications remain alongside.
"""
import re

from .typed_amounts import amount_bounds
from .decision_text import resource_name


def _average_twice(effect, row):
    low, high = amount_bounds(effect, row.get("numbers"),
                              ability_mods=row.get("ability_mods"), weapon=row.get("weapon"))
    return None if low is None or high is None else max(0, low + high)


def _half(value):
    return str(value // 2) + (".5" if value % 2 else "")


def annotate_reactions(prompts, contexts, engine):
    """Return all prompts, in transport order, with integer ranking hints.

    Damage discovered by declining a hit defense belongs to that same attack
    (ReactionMenuProbe enforces this boundary). It can describe the hit's flat
    reduction without rolling or predicting a second attack. Never borrow an
    unrelated target's damage amount.
    """
    result = []
    for prompt, context in zip(prompts, contexts, strict=True):
        trigger = context.get("choice_trigger") or {}
        moment = context["checkpoint"].split("@", 1)[0].removeprefix("TYPED:")
        target = trigger.get("target_id") or context.get("damaged_target_id") or context.get("protected_target_id")
        pending = trigger.get("damage_amount", context.get("pending_damage"))
        damage_type = trigger.get("damage_type")
        if target and moment == "ATTACK_HIT_BEFORE_DAMAGE" and (pending is None or not damage_type):
            for other in contexts:
                info = other.get("choice_trigger") or {}
                if (other["checkpoint"].split("@", 1)[0].removeprefix("TYPED:") == "DAMAGE_APPLICATION"
                        and (info.get("target_id") or other.get("damaged_target_id") or other.get("protected_target_id")) == target):
                    if pending is None:
                        pending = info.get("damage_amount", other.get("pending_damage"))
                    damage_type = damage_type or info.get("damage_type")
                    if pending is not None and damage_type:
                        break
        source = context["reaction_source_id"].removeprefix("reaction:typed.")
        mode = re.search(r":mode:(\d+)$", source)
        source = re.sub(r":mode:\d+$", "", source)
        row = next((row for row in getattr(engine, "typed_reaction_rows", {}).get(context["reactor_id"], ())
                    if row.get("feature_id") == source), {})
        if mode:
            selected = next((item for item in row.get("reaction_modes") or [] if item["index"] == int(mode[1])), {})
            row = {**row, **selected}
        effect = " ".join(str(prompt.get("summary") or prompt.get("trigger") or "Choose this response.").split())
        useful, score = True, 1
        block = row.get("block")
        amount = None
        quantified = []
        if block == "damage_soak" and int(row.get("die") or 0) > 1:
            die = int(row["die"])
            options = (prompt.get("choice") or {}).get("options") or []
            spends = [int(option["id"]) for option in options if str(option["id"]).isdigit()]
            spend = max(spends, default=1)
            amount = spend * (die + 1)
            resource = resource_name(str(row.get("resource_id") or "resource point"))
            effect = f"Reduce {str(pending) + ' ' if pending is not None else ''}damage by 1d{die} per {resource} (base avg {_half(die + 1)} each)."
        elif block == "damage_reduction":
            dice = row.get("dice") or {}
            if isinstance(dice, str):
                match = re.fullmatch(r"(\d+)d(\d+)", dice)
                dice = {"count": int(match[1]), "sides": int(match[2])} if match else {}
            amount = _average_twice({"dice": dice, "flat": row.get("bonus", 0)}, row)
        elif block == "generic" and moment in {"ATTACK_HIT_BEFORE_DAMAGE", "DAMAGE_APPLICATION", "ATTACK_MISSED"}:
            reductions = [e for e in row.get("effects") or [] if e.get("type") == "damage_modifier"
                          and not e.get("only_if_zero") and not e.get("protected_if")
                          and not e.get("half") and not e.get("damage_types")
                          and (not e.get("only_damage_types") or damage_type)
                          and (moment == "DAMAGE_APPLICATION" or e.get("applies_to", "self") == "self"
                               or row.get("includes_self") and e.get("applies_to") == "ally")]
            # Execution uses only_damage_types, not damage_types. Unknown
            # types leave that contribution unquantified with its printed
            # qualification; known mismatches contribute zero, as in combat.
            values = [0 if e.get("only_damage_types") and str(damage_type).upper() not in
                      {str(kind).upper() for kind in e["only_damage_types"]}
                      else _average_twice(e, row) for e in reductions]
            if values and all(value is not None for value in values):
                amount = sum(values)
                quantified = reductions
        elif block == "hit_ac":
            # This compiled block is offered only if its AC bonus stops the hit.
            effect, score = f"Add {row['ac']} AC to turn this hit into a miss.", 1_000_000
        if amount is not None:
            extra_effects = [e for e in row.get("effects") or []
                             if e not in quantified and not e.get("only_if_zero")]
            no_damage = moment == "ATTACK_MISSED" or pending == 0
            useful = (not no_damage and amount > 0) or bool(extra_effects)
            score = max(1, min(amount, 2 * pending) if isinstance(pending, int) else amount) if useful else 0
            if no_damage:
                effect = "No damage to reduce for this trigger." + (" Other printed effects may still apply." if extra_effects else "")
            elif block != "damage_soak":
                effect = f"Reduce {str(pending) + ' ' if pending is not None else 'this hit’s '}damage by {_half(amount)} (base average)."
        result.append({**prompt, "expected_effect": effect, "useful_now": useful, "menu_priority": score})
    return result
