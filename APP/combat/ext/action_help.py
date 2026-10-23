"""Read-only help for shared tabletop controls built by the compiler.

Uses compiled attack/save numbers and owner-editable combat rules. Ability-specific
context controls keep their help in their owning plug-in's button_description hook.
This module registers no effects and changes no fight state or action definitions.
"""
from typing import Any

from . import hook


@hook("button_description")
def control_help(row: dict[str, Any]) -> str | None:
    from ..tabletop import attack_to_hit, damage_text, saving_throw_text

    typed = (row.get("parameters") or {}).get("typed") or {}
    numbers = typed.get("numbers") or {}
    effects = typed.get("effects") or []
    kinds = {eff.get("type") for eff in effects}
    if "escape_grapple" in kinds:
        eff = next(eff for eff in effects if eff.get("type") == "escape_grapple")
        bonus = int(eff.get("bonus", numbers.get("escape_bonus")) or 0)
        check = f"{eff['check_skill']}" if eff.get("check_skill") else "Strength (Athletics) or Dexterity (Acrobatics), using your better bonus"
        from .escape_dc_text import DEFAULT_FORMULA
        # The button cannot see who is holding the reader, so it states the ordinary default
        # and the ways a hold may differ instead of promising a number (MMX115f1 review: the
        # owner's default is a default, and some holds set their own DC or repeat a save).
        return (f"Action: escape a grapple or pin affecting you. Check {check} "
                f"(1d20{bonus:+d}) against the escape Difficulty Class (DC) that hold was created with. "
                f"An ordinary grapple uses {DEFAULT_FORMULA}; an ability may set its own DC, or let you repeat a "
                "saving throw instead of making a check, and the hold's own rule wins. "
                "By default, a success ends every pin affecting you, or every grapple if you are not pinned; a failure leaves them in place. "
                "A Pinned creature breaks the pin first and must escape any grapple on a later turn. "
                "Your Grappled and Pinned statuses show each hold's DC; by default, use the highest DC among your pins, or among your grapples if you are not pinned. "
                "If an ability lets you choose an individual hold, use only the chosen hold's DC "
                "and check or saving throw; success ends only that hold. "
                "Independent bindings and burials stay in place: use Escape the binding or Dig free for those conditions.")
    if "release_grapple" in kinds:
        return "No action or cost: let go of a creature you are grappling. Its Grappled condition from your hold ends immediately."
    if "recover_weapon" in kinds:
        return "Bonus action: pick your dropped weapon back up. You can attack with it again once it is in your hands."
    if "take_weapon" in kinds:
        return "Bonus action: take a dropped weapon within 5 feet. You can use it while holding it; its previous owner cannot recover it from the ground."
    if "grab_improvised" in kinds:
        return "Use your free object interaction this turn to grab a loose object as an improvised weapon. It deals 1d4 Bludgeoning damage plus your Strength modifier; you keep it until you throw it."
    if any(eff.get("type") == "remove_condition" and eff.get("condition") == "burning" for eff in effects) and not typed.get("source"):
        return "Action: extinguish one Burn affecting you or a creature within 5 feet. No check or cultivation points are required; that Burn stops dealing damage."
    if "wall_breach" in kinds:
        opening = any(eff.get("result") == "opening" for eff in effects)
        bonus = int(numbers.get("check_bonus") or 0)
        if opening:
            return (f"Action while adjacent to a Puzzle Wall: make an Intelligence (Investigation) check (1d20{bonus:+d}) against its creator's Cultivation Save DC. "
                    "Success creates a 5-foot opening until the start of your next turn. Failure leaves it closed; the printed rule also lets its creator move you 5 feet, which the table does not run.")
        return (f"Action, while Large or larger and adjacent to a Dune Wall: make a Strength (Athletics) check (1d20{bonus:+d}) against its creator's Cultivation Save DC. "
                "Success collapses the wall's 5-foot section; failure leaves it standing.")
    if (typed.get("source") in {"improvised_weapon", "unarmed_strike"} or typed.get("unarmed_option")
            or typed.get("opportunity_of") or str(typed.get("source") or "").startswith("tianxia.mortal.weapon.")):
        attack = next((eff for eff in effects if eff.get("type") == "attack"), None)
        save = next((eff for eff in effects if eff.get("type") == "save"), None)
        option = typed.get("unarmed_option")
        if save and option:
            result = {"grapple": "grappled (its Speed becomes 0 until it escapes)",
                      "shove_push": "pushed 5 feet away", "shove_prone": "knocked Prone"}[option]
            maneuver = "Grapple" if option == "grapple" else "Shove"
            text = (f"Action: use {maneuver} in place of one unarmed attack. Target a creature within {row.get('range_ft') or 5} feet, "
                    f"at most one size larger than you. It makes a {saving_throw_text(save, numbers)}. "
                    f"On failure it is {result}; on success it is unaffected.")
            if option == "grapple":
                text += " You need a free hand to hold it."
            if attack:
                count = int(attack.get("count") or 1)
                # These are the *remaining attacks of the same Attack action*, not extra unarmed strikes: the
                # 2024 Attack action lets you mix a weapon attack, an Unarmed Strike, a Grapple and a Shove,
                # one per attack. So describe the delivery the character actually has -- the weapon in hand when
                # a melee weapon is held, otherwise the unarmed strike.
                armed = str(attack.get("attack_kind") or "") == "weapon"
                rest = (f"remaining attack{'s' if count != 1 else ''} with the weapon in your hand" if armed
                        else f"remaining unarmed attack{'s' if count != 1 else ''}")
                text += (f" Then make {count} {rest} as part of the same Attack action; "
                         f"roll 1d20{attack_to_hit(typed):+d} against the target's Armor Class. "
                         f"Each hit deals {damage_text(typed, int(numbers.get('cl') or 1)) or 'the listed damage'}.")
            return text
        if attack:
            count = int(attack.get("count") or 1)
            economy = {"REACTION": "Reaction when a visible hostile creature leaves your reach willingly without Disengaging",
                       "ACTION": "Action", "BONUS_ACTION": "Bonus action", "NONE": "No additional action"}.get(
                           row.get("economy"), "Using the listed action timing")
            text = (f"{economy}: make {count} attack{'s' if count != 1 else ''}; roll 1d20{attack_to_hit(typed):+d} "
                    f"against the target's Armor Class. Each hit deals {damage_text(typed, int(numbers.get('cl') or 1)) or 'the listed weapon damage'}.")
            parameters = row.get("parameters") or {}
            if parameters.get("following_strike"):
                text += (" Following Strike: after your off-hand Paired Strike, make this extra attack as part of the same Bonus action "
                         "or Attack action if Nick or Ambidexterity moved that strike there; once per turn. "
                         "Target a different creature from that strike, and your lead weapon must have attacked a third creature this turn.")
            # A turn flag is a general legality gate, not a paired-strike marker.
            elif typed.get("pair_role") == "answer" and row.get("economy") == "NONE" and parameters.get("requires_turn_flag"):
                if typed.get("mastery") == "Nick":
                    text += " Nick: after attacking with your other qualifying weapon, this off-hand attack is part of the Attack action instead of costing a Bonus action."
                else:
                    text += (" Ambidexterity: after attacking with your other qualifying weapon, expend Martial Focus "
                             "(your held combat focus; it is spent) to make this off-hand attack as part of the Attack action "
                             "instead of costing a Bonus action; once per turn.")
            elif typed.get("pair_role") == "answer" and row.get("economy") == "BONUS_ACTION" and parameters.get("requires_turn_flag"):
                text += " Make this off-hand attack after attacking with your other qualifying weapon as part of the Attack action."
            if typed.get("long_range_ft"):
                thrown = ("thrown" in str((typed.get("weapon") or {}).get("properties") or "").lower()
                          or typed.get("source") == "improvised_weapon")
                delivery = "Throw it" if thrown else "Fire it"
                retention = "you no longer hold it afterward" if thrown else "you keep the weapon afterward"
                if thrown and (typed.get("thrown_equipment") or {}).get("returning_inscription"):
                    retention = ("Returning Inscription brings it back to your free hand without an action, "
                                 "unless an area blocks teleportation or extradimensional movement")
                text += f" {delivery} up to {typed['range_ft']} feet normally, or {typed['long_range_ft']} feet with disadvantage; {retention}."
            else:
                text += f" Target a creature within {row.get('range_ft') or 5} feet."
            if typed.get("source") == "unarmed_strike" and not row.get("costs") and not typed.get("modifier"):
                text += " An Unarmed Strike is a punch, kick or similar blow: it needs no weapon and costs no Qi, Stamina or other resource."
            return text
        if save:
            result = "grappled (its Speed becomes 0 until it escapes)" if typed.get("unarmed_option") == "grapple" else "pushed 5 feet away or knocked Prone, as selected"
            return (f"Action: target a creature within {row.get('range_ft') or 5} feet, at most one size larger than you. "
                    f"It makes a {saving_throw_text(save, numbers)}. On failure it is {result}; on success it is unaffected.")
    return None
