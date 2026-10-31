"""Shared plain-wording helpers for the text a hold prints about escaping, and the ability names
a check is written with. Used by action_help (the sheet's own escape text) and d20_floor (the name
of the check a d20 floor is about to raise); no other plug-in should re-state the ability table.
Every helper here returns player text and changes no state.

What it takes to get out of a hold, in the hold's own numbers (MMX115, round 24, HUNT113 #1;
MMX115f1 review fixes: the advice must match the roll the table actually makes).

The printed rules for every escape a creature can attempt name a Difficulty Class -- a number
its roll has to reach -- but the table never showed that number, so a player could not tell
whether escaping was realistic. The number was always stored on the hold: ``escape_dc`` is
written into the condition's data when the hold lands
(``combat/typed_executor.py`` stores the grappler's printed escape DC, a Talent's own
escape DC, or a Save DC) and is what the escape actually rolls against.

By default one escape roll covers a whole *set* of holds: ``block_escape_grapple`` breaks
every Pin first when the creature has any, otherwise every grapple, rolls against the
**highest** DC in that set, and escapes the whole set with a saving throw when any hold in the
set asks for one. So the number stored on one hold is not always the number the creature has
to reach, and a hold that asks for a check can be resolved as a save. This module therefore
names *this hold's* stored number, and says what one roll really covers when the creature is
held more than once. Ability-specific selection may narrow that set, so all aggregate advice
is qualified as the default. Rendering never invokes the choice-producing escape hook.
It never derives, recomputes or changes a Difficulty Class, and it applies no rule.

Inert for any row whose stored data has no ``escape_dc``, so a fight with no escape in it is
unaffected, and for a holder that is not held more than once, which sees only its own number.

Users: the table's status pill and sheet, through the ``status_description`` hook
(``combat/status_text.py``). The menu-time Escape button cannot know which creature holds you
or how many hold you, so ``combat/ext/action_help.py`` states the printed default formula and
the exceptions instead; that is the same owner text
(``WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC``: "8 + Strength modifier + Proficiency
Bonus") read once here for both places.
"""

from __future__ import annotations

from typing import Any

from . import hook

# Owner 2026-10-04, authority/typed_mechanics/rules_text.json
# WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC: "Your default Wrestling Save DC and
# grapple escape DC are: 8 + Strength modifier + Proficiency Bonus", and the same row allows
# "a Path synergy, Insight, or other feature may explicitly replace Strength for Wrestling
# talents or grapples". So this is the ordinary default, not every hold's number: a Talent may
# set its own DC, and some holds repeat a saving throw instead of asking for a check. Shown
# where no live hold exists to read a number from.
DEFAULT_FORMULA = "8 + their Strength modifier + their proficiency bonus"

ESCAPE_CHECK = "Strength (Athletics) or Dexterity (Acrobatics)"

PINNED = "condition:typed.pinned"
GRAPPLED = "condition:typed.grappled"

ABILITY_NAMES = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence",
                 "WIS": "Wisdom", "CHA": "Charisma"}


def ability_name(ability: str) -> str:
    """The plain ability name for a stored three-letter ability code, or the code's own title."""
    code = str(ability or "").upper()
    return ABILITY_NAMES.get(code, code.title())


def escape_sentence(data: dict[str, Any], *, subject: str = "it") -> str:
    """One plain sentence naming *this hold's* escape, its check or save, and the DC stored on it.

    ``data`` is a hold's stored data. Returns "" when the hold states no escape Difficulty
    Class, so a caller can drop the sentence instead of printing "DC 0".
    """
    try:
        dc = int(data["escape_dc"])
    except (KeyError, TypeError, ValueError):
        return ""
    ability = str(data.get("escape_save") or "").upper()
    what = f"repeat the {ability_name(ability)} saving throw" if ability else f"make a {ESCAPE_CHECK} check"
    return (f"To get free, {subject} uses its Action to {what} against DC {dc}, "
            f"the number this hold sets.")


def _holds_of(holder: Any, condition_id: str) -> list[Any]:
    conditions = getattr(holder, "conditions", None) or {}
    return [condition for condition in conditions.values()
            if getattr(condition, "condition_id", "") == condition_id]


def held_conditions(holder: Any) -> tuple[list[Any], list[Any]]:
    """The Pin and grapple instances a held creature currently carries, read-only.

    A holder that is None (a map area, or a pill rendered without an actor) has neither.
    """
    return _holds_of(holder, PINNED), _holds_of(holder, GRAPPLED)


def escape_set_advice(holder: Any, data: dict[str, Any], *, subject: str = "it") -> str:
    """Default set advice and the individual-selection exception for grapple/Pin pills.

    Describes the default in ``typed_executor.block_escape_grapple``: the set is every Pin when the creature
    has any, otherwise every grapple; one roll is compared against the highest DC in that set
    and a success removes the whole set; a set holding any save-style hold is escaped with
    that saving throw. An ability may narrow that set; no choice hook is called here.
    Returns "" whenever none of that applies, so a single ordinary grapple reads as one
    plain sentence. Callers must limit this advice to the grapple/Pin resolver's conditions.
    """
    pins, grapples = held_conditions(holder)
    escapes = [condition.data for condition in (pins or grapples) if isinstance(getattr(condition, "data", None), dict)]
    notes: list[str] = []
    if len(escapes) > 1:
        notes.append(f"Several creatures are holding {subject}: by default, one roll must reach the highest of those DCs, "
                     f"and a success frees {subject} from all of them at once")
    if pins and grapples:
        notes.append("a Pin is broken first, so this roll ends the Pin and the grapple still needs its own escape")
    if not data.get("escape_save"):
        other = next((str(row.get("escape_save") or "").upper() for row in escapes if row.get("escape_save")), "")
        if other:
            notes.append(f"one of those holds asks {subject} to repeat the {ability_name(other)} saving throw instead, "
                         f"so by default the roll is that saving throw rather than a check")
    if len(escapes) > 1:
        notes.append("if an ability lets you choose an individual hold, use only the chosen hold's DC and "
                     "check or saving throw; success ends only that hold")
    if not notes:
        return ""
    return "Note: " + "; ".join(notes) + "."


@hook("status_description")
def escape_dc_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """State the stored escape DC for any hold that records one (Grapple, pin, Burial, bindings)."""
    data = data or {}
    sentence = escape_sentence(data)
    if not sentence:
        return None
    advice = escape_set_advice(holder, data) if row.get("condition_id") in {PINNED, GRAPPLED} else ""
    return {"text": f"{sentence} {advice}".strip() if advice else sentence}
