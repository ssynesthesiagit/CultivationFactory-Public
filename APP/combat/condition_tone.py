"""Which colour a condition pill gets on the table, the character panel and the sheet
(owner 2026-09-30: "debuffs shouldnt be green. green is for buffs not debuffs").

A pill is coloured by what the condition does TO THE CREATURE THAT CARRIES IT, not by which ability
happened to put it there, so a player can read the table at a glance: red works against the bearer,
green helps it, grey is a note for play. The answer is worked out from data that already exists, never
from a list of condition names handed around in code:

  1. bookkeeping   the engine's own notes (Concentration, a Shaping choice, a bond) - a tracker rather
                   than a change to the creature, so grey;
  2. typed kind    what the creature's own rule says it does (combat/rules/typed_conditions.json, an
                   owner-editable file the engine re-reads on change). A rule that takes something away
                   is red; a rule that hands something over is green. ``effect_kind: "harmful"`` is how
                   an ability says "this costs my bearer something" when it has no engine-wide mechanic
                   to declare (combat/ext/end_effect.py reads the same vocabulary);
                   ``pill_tone: "beneficial"`` / ``"harmful"`` preserves presentation-only effects whose mechanics
                   live elsewhere. It does not change removal eligibility or add combat mechanics;
  3. who applied it  a condition an enemy put on a creature works against that creature (red); one the
                   creature or an ally put on it helps it (green). A Mark follows its maker's side.

Used by combat/presentation.py, which works the tone out once and ships it to every surface, so the
map token's hover card, the character panel and the pop-out sheet can never disagree.
"""

from __future__ import annotations

from typing import Any

from .typed_executor import rules


HARMFUL = "harmful"        # red: this works against the creature carrying it
BENEFICIAL = "beneficial"  # green: this helps the creature carrying it
NEUTRAL = "neutral"        # grey: a note for play, not a change to the creature

# The three kinds of rule field, because "Advantage" means opposite things depending on who rolls.
# Being set is itself the loss: no actions, Speed 0, no Reactions, halved healing and so on.
# combat/ext/end_effect.py keeps its own list of the same names.
_SELF_LOSS = ("speed_zero", "no_actions", "no_reactions", "no_dash", "no_teleport", "no_cp_regain",
              "no_cp_reactions", "cant_hear", "no_save_advantage", "no_disengage", "healing_halved")
# Modes on the bearer's own rolls: Disadvantage (or an automatic failure) costs it, Advantage helps it.
_SELF_MODE = ("attacks_have", "attacks_others_have", "save_mode", "check_mode", "save_against",
              "check_against", "concentration_mode", "death_save_mode")
# Modes on rolls made AGAINST the bearer, which read the other way round: attacks against it having
# Advantage costs it, attacks against it having Disadvantage helps it (Hidden, Invisible).
_AGAINST_MODE = ("attacked_with", "attacked_within_5ft", "attacked_beyond_5ft")

# A rule field that, when set, hands the creature something.
GRANTS = ("ignore_difficult", "damage_resistance", "damage_immunity", "damage_reduction", "ac_bonus",
          "cover", "stance", "condition_immunities", "speed_ft", "armor_class")

_HURTS_MODE = frozenset(("DISADVANTAGE", "AUTO_FAIL"))
_HELPS_MODE = frozenset(("ADVANTAGE",))
_ALL_MODES = _HURTS_MODE | _HELPS_MODE

# The engine's own bookkeeping: something is happening, not something changed in the creature.
_BOOKKEEPING = ("concentration", "concentration_held", "shaping", "augments", "improvised")

_MARK_PREFIX = "condition:typed.mark."


def condition_name(condition_id: str) -> str:
    """The bare name a condition id ends in ("condition:typed.creeping_lethargy" -> "creeping_lethargy")."""
    return str(condition_id or "").split(".").pop()


def mark_maker(condition_id: str) -> str | None:
    """Whose Mark this is, or None when this is not a Mark.

    A Mark is stored as ``condition:typed.mark.<name>.<owner id>`` and an owner id contains dots
    ("actor:factory.tabik"), so the maker is everything after the FIRST dot following the name.
    """
    text = str(condition_id or "")
    if not text.startswith(_MARK_PREFIX):
        return None
    rest = text[len(_MARK_PREFIX):]
    _name, _dot, owner = rest.partition(".")
    return owner or None


def declared_rule(name: str) -> dict[str, Any]:
    """What the owner-editable rules say this condition does, or an empty rule."""
    declared = rules().get("conditions", {}).get(name) or {}
    return declared if isinstance(declared, dict) else {}


def _modes(rule: dict[str, Any], key: str) -> frozenset[str]:
    """Every roll mode one rule field names.

    Two shapes, both real in the fight state:

    - a **scoped** field -- ``save_against`` / ``check_against`` carry their mode under a ``mode``
      member, next to the ``against`` / ``abilities`` lists of what it applies to and a ``next`` flag
      (combat/typed_executor.py builds these; combat/ext/save_against.py reads the mode back). Only
      the ``mode`` member is a roll mode, so the lists beside it are ignored;
    - a **mode map** -- ``check_mode: {"CON": "DISADVANTAGE", "DCX": "ADVANTAGE"}`` names one mode
      per ability, so a map whose entries disagree still says both. Every mode it names is returned:
      ``hurts()`` counts a loss anywhere in the field and ``helps()`` counts a gain, and ``tone()``
      settles a field that carries both as a cost.
    """
    value = rule.get(key)
    if isinstance(value, str):
        return frozenset((value,)) if value else frozenset()
    if not isinstance(value, dict):
        return frozenset()
    scoped = value.get("mode")
    if isinstance(scoped, str):
        return frozenset((scoped,))
    return frozenset(mode for mode in map(str, value.values()) if mode in _ALL_MODES)


def hurts(rule: dict[str, Any]) -> bool:
    """Does this rule take something away from the creature carrying it?

    A field that names a loss costs its bearer something even when the same field also names a gain,
    so a mixed map reads as a drawback (a rule that helps on one ability and hurts on another is a
    trade the player needs to see, not a free buff).
    """
    if rule.get("pill_tone") == HARMFUL or str(rule.get("effect_kind") or "") == HARMFUL:
        return True
    if any(rule.get(key) for key in _SELF_LOSS):
        return True
    if any(not _HURTS_MODE.isdisjoint(_modes(rule, key)) for key in _SELF_MODE):
        return True
    return any(not _HELPS_MODE.isdisjoint(_modes(rule, key)) for key in _AGAINST_MODE)


def helps(rule: dict[str, Any]) -> bool:
    """Does this rule hand the creature something?"""
    if rule.get("pill_tone") == BENEFICIAL:
        return True  # presentation metadata only; tone() still gives mechanical losses priority
    if str(rule.get("effect_kind") or "") in ("benefit", "defense"):
        return True
    if any(rule.get(key) for key in GRANTS):
        return True
    if any(not _HELPS_MODE.isdisjoint(_modes(rule, key)) for key in _SELF_MODE):
        return True
    return any(not _HURTS_MODE.isdisjoint(_modes(rule, key)) for key in _AGAINST_MODE)


def rule_for(name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """The condition's rule: what the owner-editable file says, plus anything the ability carried with it."""
    declared = declared_rule(name)
    own = (data or {}).get("rule")
    combined = {**declared, **(own if isinstance(own, dict) else {})}
    if str(declared.get("effect_kind") or "") == "structural":
        combined["effect_kind"] = "structural"  # a rider's extra benefit cannot turn a bond into a buff
    return combined


def _companions_hurt(name: str, rule: dict[str, Any], seen: frozenset[str]) -> bool:
    """A condition that drags others along is only as kind as the worst of them."""
    for companion in rule.get("companions") or ():
        other = str(companion)
        if other in seen:
            continue
        other_rule = declared_rule(other)
        if hurts(other_rule) or _companions_hurt(other, other_rule, seen | {other}):
            return True
    return False


def tone(condition_id: str, *, data: dict[str, Any] | None = None, source_is_ally: bool | None = None,
         mark_maker_is_ally: bool | None = None) -> str:
    """The pill colour for one condition: HARMFUL, BENEFICIAL or NEUTRAL.

    ``source_is_ally``: True when the creature itself or an ally applied this, False when an enemy
    did, None when that is not known. ``mark_maker_is_ally`` answers the same question for a Mark.
    """
    if mark_maker_is_ally is not None:
        return BENEFICIAL if mark_maker_is_ally else HARMFUL
    if mark_maker(condition_id) is not None:
        return HARMFUL  # a Mark whose maker's side is unknown is read as an enemy's

    name = condition_name(condition_id)
    if name in _BOOKKEEPING:
        return NEUTRAL

    rule = rule_for(name, data)
    if str(rule.get("effect_kind") or "") == "structural":
        return NEUTRAL

    # What it does decides first: a cost stays a cost whoever applied it, so an ally's gift and the
    # creature's own drawback still read as drawbacks.
    if hurts(rule) or _companions_hurt(name, rule, frozenset({name})):
        return HARMFUL
    if helps(rule):
        return BENEFICIAL

    # Nothing in the rules says, so go by who applied it.
    return BENEFICIAL if source_is_ally else HARMFUL
