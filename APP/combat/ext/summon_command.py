"""Plain rules text for the "Command <creatures>" buttons a summoner is offered (hunt89 finding 1).

Every commanded group is one button on the summoner's turn, and the rule that describes
it is in the owner-editable ``combat/rules/summons.json`` note:

    command 'bonus_action': one Bonus Action of the summoner commands every one of that
    group within command_range_ft to follow an order on its next turn;
    uncommanded, it acts on its own instincts (owner 2026-10-17).

The button used to describe itself with the *summoning* ability's rules instead, so a
Bonus Action button read "Ritual Time: 1 hour ... Duration: 24 hours ... Cost: 8 CP".
``combat/summons.py`` records the summoning talent as the command row's typed ``source``
(so the engine can trace who brought the creatures), and ``combat/action_text.py`` reads
that field as a printed-text candidate, which returned the talent's text. Which talent
answered therefore depended on which creature record came first in the group.

This hook answers for every ``command_summons`` row, so any group's command button
states its own cost, timing and duration. Read-only presentation: it registers no
effect, changes no action definition and touches no fight state. Rows with no
``command_summons`` effect -- every other button on the table -- are left to the general
description builders, and a character who summons nothing has no such row to describe.

The wording also says *which* of the group the order reaches. A command is a bonus
action, not a wave over the whole battlefield: ``combat/summons.commandable`` keeps only
the creatures whose own retained ``command_range_ft`` reaches back to the summoner, so
one command of a spread-out group reaches the near ones and leaves the rest to their instincts.
Promising that every member acts would misdescribe the button. The range lives on each
creature's own fight record (60 ft for a Death servant, 1000 for a Bone Guard) and never
on the action row, so the text qualifies the recipients in plain words rather than
printing a number that would be wrong for some members of the same group, and an old
saved fight reads the same after a reload.
"""

from __future__ import annotations

from typing import Any

from . import hook

# What the row's own economy charges, in the words the table already uses for it
# (APP/static/tabletop/tabletop.js costTag), so the text and the button's cost tag agree.
# Each clause says what the order spends, which is the point of the fix: a command is an
# action, never a resource cost, so no Cultivation points, Qi, Stamina or Resonance.
COST_WORD = {"BONUS_ACTION": "Bonus action", "ACTION": "Action",
             "REACTION": "Reaction", "NONE": "Free"}
COST_CLAUSE = {"BONUS_ACTION": "It uses your Bonus action, costs no Qi, Stamina or other resource, and lasts only for each creature's next turn.",
               "ACTION": "It uses your Action and lasts only for each creature's next turn.",
               "REACTION": "It uses your Reaction and lasts only for each creature's next turn.",
               "NONE": "It needs no action, costs no resource, and lasts only for each creature's next turn."}


def _group_words(row: dict[str, Any]) -> str:
    """The creatures this command reaches, named the way the button names them.

    combat/summons.py builds the label as "Command " + the group's own printed name
    ("Command Death servants", "Command Bonded Spirit"), so the name is read from the
    label rather than from the internal group key, which a player must never see.
    """
    label = " ".join(str(row.get("display_name") or "").split())
    if label[:8].lower() == "command ":
        return label[8:].strip() or "summoned creatures"
    return "summoned creatures"


@hook("button_description")
def command_help(row: dict[str, Any]) -> str | None:
    """Describe what a command button does, instead of the talent that summoned its group."""
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if not any(isinstance(effect, dict) and effect.get("type") == "command_summons" for effect in effects):
        return None
    economy = str(row.get("economy") or "")
    group = _group_words(row)
    # EconomyKind has exactly these four members, so the fallbacks are only a guard
    # against a malformed row: an unlabelled one is described without claiming a cost.
    prefix = f"{COST_WORD[economy]}: " if economy in COST_WORD else ""
    clause = COST_CLAUSE.get(economy, "It lasts only for each creature's next turn.")
    # Each creature has its own command range; an order never reaches the whole group by fiat.
    return (f"{prefix}Give an order to your {group}. "
            "Each one in range of the order follows your chosen order on its next turn, "
            "using only its own stat-block actions and movement; "
            f"any that is out of range, or that you do not order, acts on its own instincts instead. {clause}")
