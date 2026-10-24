"""A printed resource cost belongs to the ability that prints it, not to a summoned creature's own action.

Owner text first. ``combat/rules/summons.json`` note, read when a fight's characters are compiled:
"``sources`` says which ability brings which creature: arrives ``start`` (already with the summoner
when the fight begins: rituals that last until destroyed, a manifested spirit, tamed beasts) or
``action`` (the ability itself calls it mid-fight)."  Grave Formation prints the same shape
(``authority/typed_mechanics/rules_text.json``, ``TAL_DEATH_GRAVE_FORMATION``): "Action Type: Ritual
Procedure / Timing Detail: Ritual / Time: 1 hour / Duration: 24 hours, or until the formation is
destroyed or dismissed / Cost: 8 CP", and its own rider: "A single command causes it to take one
action from its stat block."  The printed Grave Assault entry inside that stat block
(``TAL_DEATH_GRAVE_FORMATION_STAT_BLOCK``) prints no cost of its own, and neither does any other
printed action a summoned creature takes, nor the printed Commanding Death Servants bonus action.

So the printed N CP is paid once -- before the fight for a summon that arrives with its summoner, and
by the summoner at the moment they use the ability for a summon the ability calls mid-fight -- while
an action the creature takes is an entry of that creature's own stat block, and commanding a creature
you already have out is a separate bonus action.  Neither is a new activation of the ability that
called it out.  Summon buttons used to be built from that ability's whole printed rules text, so
"Cost: 8 CP" sat on the Grave Formation's own attack, "Cost: 15 CP" on the Legion's and "Cost: 4 CP"
on "Command Death servants", while the engine charged nothing and refused nothing: 39 of the 43
summon-creature actions in ``combat/rules/summons.json`` (HUNT 114 finding 3, twenty fights played at
the table).  A player reads a cost, presses the button and nothing is spent, which is
indistinguishable from a dead button.

``button_description`` answers only for a button about a summon that charges nothing while the ability
behind it prints a resource cost, and then says what happens, to whom, and that it costs no
cultivation points.  It is a pure read of the compiled action row and the owner's data: no state,
event, roll, choice, expiry or saved field is written, so a fight saved before this change replays
byte-identically and only its button wording differs.  Every other button returns ``None`` and is left
exactly as it was: an ordinary fighter's paid ability, a summoner's own paid summon, a summon whose
ability prints no cost, and any button that already charges what it shows.
"""
from __future__ import annotations

import functools
import re
from typing import Any

from . import hook

# A summoned creature's entity id is "<summoner>.summon.<group>.<n>" (combat/summons.py), so its group
# is the second-to-last dotted segment.  An ordinary fighter's id carries no such segment.
SUMMON_ENTITY = ".summon."
PRINTS_COST = re.compile(r"\bCost:\s*\S")


@functools.lru_cache(maxsize=1)
def _printed_text(record: str) -> str:
    from ..status_text import plain, printed_rules

    return plain(printed_rules().get(record, ""))


@functools.lru_cache(maxsize=1)
def _owner_data() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """The owner's own rows for the two things a summon button can be about.

    ``callers``: creature group -> the ability that calls that group out, its printed name and whether
    it arrives with its summoner or is called mid-fight.  ``commanders``: command group -> the
    Bonus Action that commands a group already out.  Both come from ``combat/rules/summons.json``
    rather than from names written here, so a new summon joins this rule by adding owner data only.
    """
    from ..summons import rules

    table = rules()
    creatures = table.get("creatures") or {}
    callers: dict[str, dict[str, str]] = {}
    commanders: dict[str, dict[str, str]] = {}
    for source_id, source in (table.get("sources") or {}).items():
        if source_id in ("tamer", "rider"):
            continue  # a Tamer's trained beast and a Rider Package mount are not printed-cost summons
        ability = str(source.get("ability") or source_id)
        if not PRINTS_COST.search(_printed_text(ability)):
            continue  # an ability that prints no cost has no cost for a creature's action to inherit
        # A "group" reuses a creature's statistics under its own name (combat/summons.py, the Legion's formations).
        creature = creatures.get(str(source.get("creature") or "")) or {}
        name = str(source.get("name") or creature.get("name") or "").strip()
        if name:
            callers.setdefault(str(source.get("group") or source.get("creature") or ""), {
                "source": ability, "creature": name, "arrives": str(source.get("arrives") or "start")})
        group = str(source.get("command_group") or source.get("family") or source.get("group")
                    or source.get("creature") or "")
        if group and str(source.get("command") or "bonus_action") == "bonus_action":
            commanders.setdefault(group, {
                "name": str(source.get("command_group_name") or source.get("family_name") or name).strip(),
                "range": str(source.get("command_range_ft") or "")})
    return {group: row for group, row in callers.items() if group}, commanders


def _caller_for(row: dict[str, Any]) -> dict[str, str] | None:
    """The ability that called the creature behind this button out, or None when there is none."""
    _, marker, tail = str(row.get("owner_id") or "").partition(SUMMON_ENTITY)
    if not marker:
        return None  # an ordinary fighter's button, or a button their summoner owns
    caller = _owner_data()[0].get(tail.rsplit(".", 1)[0])
    if caller is None or caller["source"] != str((row.get("parameters") or {}).get("typed", {}).get("source") or ""):
        return None
    return caller


def _condition_words(condition_id: str) -> str:
    """A condition's player-facing name ("condition:typed.prone" -> "Prone")."""
    return str(condition_id or "").rsplit(".", 1)[-1].replace("_", " ").strip().title() or "it"


def _rider_text(on_hit: list[dict[str, Any]]) -> str:
    """What a hit adds beyond its damage, read off the row's own on-hit effects.

    A form's rider (combat/ext/painting_forms.py: the Tiger's Pouncing Stroke, the Serpent's Coiling
    Stroke) and a save for a condition are part of what the attack does, so the help says so rather
    than leaving the player to discover it on the table.
    """
    from . import painting_forms

    out: list[str] = []
    for effect in on_hit:
        if not isinstance(effect, dict):
            continue
        kind = str(effect.get("type") or "")
        if kind == "form_rider":
            said = painting_forms.rider_text(str(effect.get("form") or ""))
            if said and said not in out:
                out.append(said)
        elif kind == "save":
            ability = str(effect.get("ability") or "").title() or "a saving throw"
            names = [_condition_words(str((row or {}).get("condition") or ""))
                     for row in effect.get("on_fail") or [] if isinstance(row, dict) and row.get("type") == "condition"]
            if names:
                out.append(f"The target then makes {ability} saving throw; on a failure it is {names[0]}.")
    return (" " + " ".join(out)) if out else ""


def _damage_choices(typed: dict[str, Any]) -> str:
    """A stat block that offers a choice of damage types ("Slashing or Force") is worth saying."""
    kinds = [str(kind).lower() for kind in ((typed.get("weapon") or {}).get("damage_types") or []) if kind]
    if len(kinds) < 2:
        return ""
    listed = ", ".join(kinds[:-1]) + f" or {kinds[-1]}"
    if typed.get("creation_damage_choice"):
        return f" It deals the {listed} damage type its creator chose when creating it; that choice lasts until this painting ends."
    return f" It may deal any one of {listed} damage; whichever of them lands hardest is what it deals."


def _own_action_text(row: dict[str, Any]) -> str:
    """What the creature's own action does, read from the numbers the engine resolves."""
    from ..tabletop import damage_text

    typed = (row.get("parameters") or {}).get("typed") or {}
    numbers = typed.get("numbers") or {}
    attack = next((effect for effect in typed.get("effects") or [] if effect.get("type") == "attack"), None)
    if attack is None or not numbers.get("attack_bonus"):
        return "It takes this action from its own stat block."
    reach = row.get("range_ft") or row.get("reach_ft")
    distance = f", reach {reach} feet" if reach else ""
    count = int(attack.get("count") or 1)
    times = f" {count} times" if count > 1 else ""
    damage = damage_text(typed, int(numbers.get("cl") or 1))
    return (f"It attacks{times}{distance}: roll 1d20{int(numbers['attack_bonus']):+d} against the target's "
            f"Armor Class. On a hit, deal {damage or 'the damage on its stat block'}.{_damage_choices(typed)}"
            f"{_rider_text(attack.get('on_hit') or [])}")


@hook("button_description")
def summon_action_cost(row: dict[str, Any]) -> str | None:
    """Correct a summon button that shows a cost its action never charges; otherwise stay silent."""
    if row.get("costs") or (row.get("parameters") or {}).get("requires_resource"):
        return None  # the action already charges what it shows
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(isinstance(effect, dict) and effect.get("type") == "command_summons" for effect in effects):
        # summon_command owns the order's economy, per-creature range and Dodge
        # explanation, including its explicit zero resource cost. Do not shadow
        # that reading with a second implementation or a group-wide range.
        return None
    caller = _caller_for(row)
    if caller is None:
        return None  # not a summon this rule knows: another character's button, left alone
    name = str(row.get("display_name") or "This action")
    paid = ("was already paid before the fight."
            if caller["arrives"] == "start"
            else "is paid once, by the creature that summoned it, at the moment the ability calls it out.")
    return (f"{caller['creature']} takes its own action, {name}. {_own_action_text(row)} "
            f"This costs no cultivation points: it is the creature's own action from its stat block, "
            f"not a new use of the ability that calls it out. That ability's printed cost {paid}")
