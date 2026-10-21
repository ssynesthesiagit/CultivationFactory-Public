"""A Forged/Constructed ability's button prints ITS OWN rule, not the source talent's card.

A Forged Technique is a Base Form carrying a Primary Sphere Effect (combat/forged.py
``mechanic_for``): its shape, cost, range, duration, Augments and Drawbacks are the technique's
own, and they differ from the talent it was built from. The shared description helper
(combat/action_text.describe_action) listed ``typed.forged_from`` as a printed-text source,
so every forged button fell back to the SOURCE TALENT's whole printed card -- a different
ability's shape, cost, damage and prerequisites, and the shape is what the player needs in
order to place the area.

This module owns the text for those buttons. It is inert for anything that is not a forged
technique: it returns None unless the compiled typed block says so, so every printed talent,
Meld, option and older saved fight keeps the text it had.

Everything the player is told about the technique's OWN behaviour is read from its compiled
row, never from the source talent's card, because that card is a different ability:

  * what the technique reaches -- its compiled area, or the delivery combat/forged.py builds as
    the first row of ``typed.effects`` (an attack, an area save, a Ward, a movement);
  * the compiled effects themselves -- the damage dice at this character's Cultivation Level
    (an Augment's extra die is already inside them), added conditions, Resistance bypass, the
    Drawbacks the technique costs its user (self-damage, Exhaustion);
  * its own range, duration and Concentration, which the Base Form and the augments set
    (a Zone lasts 1 minute on Concentration; Extended Range doubles the reach);
  * printed component clauses for details not safely paraphrased, such as carried movement
    restrictions and recurring area timing. These are quoted separately from creation-time
    delivery; the source talent's complete casting card and uncarried options stay absent.
"""
from __future__ import annotations

import re
from typing import Any

from . import hook

_ECONOMY = {"ACTION": "Action", "BONUS_ACTION": "Bonus Action", "REACTION": "Reaction",
            "NONE": "No action needed"}
_SHAPES = {"sphere": "radius", "burst": "radius", "cone": "cone", "line": "line",
           "square": "square", "cube": "cube", "wall": "wall", "ring": "ring"}
# The engine's expiry names, in the words the printed rules use for them.
_WHEN = {"until_start_of_next_turn": "until the start of your next turn",
         "until_start_of_your_next_turn": "until the start of your next turn",
         "until_end_of_your_next_turn": "until the end of your next turn",
         "until_end_of_turn": "until the end of the current turn",
         "end_of_turn": "until the end of the current turn",
         "start_of_source_next_turn": "until the start of your next turn",
         "until_start_of_source_next_turn": "until the start of your next turn",
         "instant": "immediately"}


def _ability(word: Any) -> str:
    """Use the public save formatter for single abilities and supported alternatives."""
    from ..tabletop import saving_throw_text

    name = str(word or "").strip().lower()
    if not name or name == "none":
        return ""
    return (saving_throw_text({"ability": name}, {}) or "").removesuffix(" save")


# Mirror typed_executor's evidence/on turn grammar without reading private engine state.
_WHOSE = r"(?P<who>your|its|their|his|her|the \w+(?:'|’)s|that \w+(?:'|’)s)"
_LEAD = r"(?:until|before|expires at|ends at)"
_TURN_PHRASES = (
    ("end", re.compile(rf"\b{_LEAD} the end of {_WHOSE} (?:next|following) turn\b", re.I)),
    ("start", re.compile(rf"\b{_LEAD} (?:the start of )?{_WHOSE} (?:next|following) turn\b", re.I)),
    ("over", re.compile(r"\b(?:(?:until|before) the end of (?:the current|this|that|the|your|its|their)|(?:for )?the rest of (?:the|this|that)"
                        r"(?: current)?) turn\b", re.I)),
)


def _stated_turn(effect: dict[str, Any], holder: str) -> str:
    """First executor-recognized turn phrase, evidence before on; 'your' is the source."""
    for field in ("evidence", "on"):
        text = re.sub(r"\s+", " ", str(effect.get(field) or ""))
        found = [(match.start(), edge, (match.groupdict().get("who") or "").lower())
                 for edge, pattern in _TURN_PHRASES for match in pattern.finditer(text)]
        if found:
            _, edge, whose = min(found)
            if edge == "over":
                return "until the end of the current turn"
            owner = "your" if whose == "your" else holder
            return f"until the {edge} of {owner} next turn"
    return ""


def _own_header(record: str) -> str:
    """The source talent's printed NAME (its first heading), never a row id."""
    from ..status_text import printed_rules

    for line in (printed_rules().get(record) or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip()
            return name.split(" - ", 1)[0].strip() or record
    return ""


def _when(effect: dict[str, Any], *, who: str = "it") -> str:
    """Explicit expiry, then evidence/on turn wording, then generic duration."""
    holder = "your" if who == "you" else "its"
    turn_names = {
        "start_of_target_next_turn": f"until the start of {holder} next turn",
        "start_of_holder_next_turn": f"until the start of {holder} next turn",
        "end_of_holder_next_turn": f"until the end of {holder} next turn",
        "target_next_turn": f"until the end of {holder} next turn",
        "until_end_of_next_turn": f"until the end of {holder} next turn",
        "end_of_current_turn": "until the end of the current turn",
        "concentration_end": "while you maintain Concentration on this technique",
        "until_removed": "until removed",
    }
    for key in ("expires_on", "duration"):
        if key == "duration":
            stated = _stated_turn(effect, holder)
            if stated:
                return stated
        value = effect.get(key)
        name = str(value.get("kind") if isinstance(value, dict) else value or "").strip().lower()
        if name and name != "instant":
            if isinstance(value, dict) and name in ("rounds", "minutes"):
                amount = int(value.get("amount") or 1)
                return f"for {amount} {name.rstrip('s')}{'s' if amount != 1 else ''}"
            if isinstance(value, dict) and value.get("text"):
                return str(value["text"]).strip().rstrip(".")
            return turn_names.get(name) or _WHEN.get(name, f"for {_words(name)}")
    return ""


def _words(text: Any) -> str:
    return str(text or "").replace("_", " ").strip()


def _condition_name(key: Any) -> str:
    """A condition's own catalog name when the owner gave it one ("Prone"), else readable words."""
    from ..condition_text import all_conditions

    name = str(key or "").strip()
    if not name:
        return ""
    entry = all_conditions().get(name) or {}
    return str(entry.get("name") or _words(name)).replace("_", " ").strip()


def _amount(effect: dict[str, Any], typed: dict[str, Any]) -> str:
    """Format carried amounts without losing weapon context or changing compiled rows.

    The shared formatter reads damage rows; healing uses the same dice/formula arithmetic
    with no damage type. Formula-only amounts use the shared static display lookup.
    """
    from ..tabletop import damage_text
    from ..display_values import display_formula_value

    numbers = typed.get("numbers") or {}
    display = {**effect, "type": "damage"}
    if effect.get("type") in ("healing", "heal"):
        display["damage_types"] = []
    amount = damage_text({**typed, "effects": [display]}, int(numbers.get("cl") or 1))
    if (effect.get("type") in ("healing", "heal", "temp_hp")
            and not effect.get("dice") and not effect.get("dice_by_cl")
            and effect.get("formula") not in (None, "", "none")):
        formula = str(effect["formula"])
        try:
            value = int(effect.get("flat") or 0) + display_formula_value(formula, numbers)
        except ValueError:
            return f"equal to {_FORMULAS.get(formula, _words(formula))}"
        types = " ".join(_words(part) for part in display.get("damage_types") or [])
        return f"{value} {types}".strip()
    return amount


# A formula-only row (a Self-Damage Drawback: "damage equal to your Proficiency Bonus") carries
# no dice and no flat number, so the shared damage reader has nothing to print for it.
_FORMULAS = {"pb": "your Proficiency Bonus",
             "key_ability_modifier": "your Path key ability modifier",
             "level": "your Cultivation Level"}
# "you gains" is not a word: the second person takes the plain verb.
_SECOND_PERSON = (("gains ", "gain "), ("takes ", "take "), ("becomes ", "become "),
                  ("regains ", "regain "), ("moves ", "move "), ("is pushed ", "are pushed "),
                  ("'s ", "r "))


def _outcome(effect: dict[str, Any], typed: dict[str, Any], *, who: str = "it") -> str:
    """One compiled effect row, in the words a player needs: what happens, to whom, for how long.

    Only rows the compiled technique actually carries are described; an Augment's extra die is
    already inside the dice, so nothing here restates it.
    """
    kind = str(effect.get("type") or "")
    when = _when(effect, who=who)

    if kind == "save":
        return _save_outcome(effect, typed, who=who)
    if kind in ("if_marked", "if_not_marked"):
        raw = effect.get("mark")
        names = raw if isinstance(raw, list) else [raw]
        names = [_words(name) for name in names if name]
        subject = "you" if effect.get("applies_to") == "self" else who
        children = _outcomes(effect.get("effects"), typed, who=subject)
        if not names or not children:
            return ""
        verb = "bear" if subject == "you" else "bears"
        if kind == "if_not_marked":
            verb = "do not already bear" if subject == "you" else "does not already bear"
        marks = " or ".join(f"your {name} mark" for name in names)
        return f"if {subject} {verb} {marks}, " + _join(children)
    if kind == "mark":
        name = _words(effect.get("mark"))
        if not name:
            return ""
        from ..status_text import plain
        from ..tabletop_service import TabletopService

        # The shared catalog's first sentence explains what a mark means. Later
        # sentences can give its BASE ability's clock; this row owns its deadline.
        key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        reading = plain(TabletopService.MARK_READINGS.get(key, "")).split(". ", 1)[0].rstrip(".")
        reading = re.sub(r"\s*\([^)]*\)", "", reading)
        sentence = f"{who} gains your {name} mark{_tail(when)}"
        return sentence + (f" ({reading})" if reading else "")
    if kind in ("damage", "extra_damage"):
        amount = _amount(effect, typed)
        formula = str(effect.get("formula") or "")
        types = " ".join(_words(part) for part in effect.get("damage_types") or [])
        if amount:
            return f"{who} takes {amount} damage{_tail(when)}"
        if formula and formula != "none":
            base = f"{who} takes damage equal to {_FORMULAS.get(formula, _words(formula))}"
            return f"{base} ({types} damage){_tail(when)}" if types else f"{base}{_tail(when)}"
        flat = int(effect.get("flat") or 0)
        return f"{who} takes {flat} {types} damage{_tail(when)}".replace("  ", " ") if flat or types else ""
    if kind in ("healing", "heal"):
        amount = _amount(effect, typed)
        return f"{who} regains {amount} hit points{_tail(when)}" if amount else ""
    if kind == "condition":
        condition = _condition_name(effect.get("condition"))
        if not condition:
            return ""
        # Match the executor's target-owned condition expiry, including its default.
        if str(effect.get("condition") or "").lower() == "prone":
            when = "until it stands up (standing up costs half its Speed)"
        elif effect.get("until_escape"):
            when = "until it escapes"
        elif not when:
            duration = typed.get("duration") or {}
            if duration.get("concentration"):
                when = "while you maintain Concentration on this technique"
            elif duration.get("kind") in ("rounds", "minutes"):
                amount = int(duration.get("amount") or 1)
                unit = str(duration["kind"]).rstrip("s")
                when = f"for {amount} {unit}{'s' if amount != 1 else ''}"
            else:
                when = "until the end of its next turn"
        sentence = f"{who} becomes {condition}{_tail(when)}"
        repeat = effect.get("repeat_save") or {}
        if repeat:
            ability = _ability(repeat.get("ability"))
            checkpoint = "start" if repeat.get("when") == "start" else "end"
            sentence += (f"; {who} repeats the {ability + ' ' if ability else ''}saving throw "
                         f"against your Cultivation Save DC at the {checkpoint} of each of its turns, "
                         f"ending {condition} on a success")
        return sentence
    if kind == "speed":
        possessive = "your" if who == "you" else "its" if who == "it" else f"{who}'s"
        if effect.get("halved"):
            return f"{possessive} Speed is halved{_tail(when)}"
        if effect.get("becomes") is not None:
            return f"{possessive} Speed becomes {int(effect['becomes'])} feet{_tail(when)}"
        amount = effect.get("amount") if effect.get("amount") is not None else effect.get("flat")
        amount = int(amount or 0)
        if not amount:
            return ""
        change = "increases" if amount > 0 else "drops"
        return f"{possessive} Speed {change} by {abs(amount)} feet{_tail(when)}"
    if kind == "exhaustion":
        levels = int(effect.get("amount") or 1)
        return f"{who} gains {levels} level{'s' if levels != 1 else ''} of Exhaustion"
    if kind == "temp_hp":
        formula = str(effect.get("formula") or "")
        amount = ("equal to your Proficiency Bonus" if formula == "pb" and not effect.get("flat")
                  else _amount(effect, typed))
        if not amount:
            return ""
        return f"{who} gains Temporary Hit Points {amount}{_tail(when)}"
    if kind == "resistance":
        types = " and ".join(_words(part) for part in effect.get("damage_types") or []) or "this damage type"
        return f"{who} gains Resistance to {types} damage{_tail(when)}"
    if kind == "ignore_resistance":
        types = " and ".join(_words(part) for part in effect.get("damage_types") or []) or "its damage"
        return f"{who}'s Resistance is ignored by {types} damage from this technique"
    if kind == "forced_movement":
        # Keep the carried printed clause verbatim, including its reference point and
        # restrictions. Do not turn a pull (or a perpendicular push) into a generic push.
        if effect.get("evidence"):
            return f"Printed movement rule: {effect['evidence']}"
        distance = int(effect.get("distance_ft") or effect.get("flat") or 0)
        direction = effect.get("direction")
        reference = {None: "away from you", "": "away from you", "away": "away from you",
                     "toward": "toward you", "toward_center": "toward the area's center",
                     "away_center": "away from the area's center"}.get(direction)
        if reference is None:
            return ""  # Unknown direction has no faithful generated description.
        verb = "pulled" if direction in ("toward", "toward_center") else "pushed"
        return f"{who} is {verb} {distance} feet {reference}{_tail(when)}" if distance else ""
    if kind == "movement":
        distance = int(effect.get("distance_ft") or 0)
        if not distance:
            return ""
        quiet = " without provoking Opportunity Attacks" if effect.get("no_opportunity_attacks") else ""
        return f"{who} moves up to {distance} feet{quiet}"
    if kind == "half_damage":
        return f"{who} takes half that damage"
    # An effect kind this plug-in does not name: fall back to the owner's own evidence line for
    # the row rather than dropping a real effect or inventing one.
    return f"Printed component rule: {effect['evidence']}" if effect.get("evidence") else ""


def _tail(when: str) -> str:
    return f" {when}" if when else ""


def _save_outcome(effect: dict[str, Any], typed: dict[str, Any], *, who: str) -> str:
    """Render a compiled save and both branches, recursively, wherever it is carried."""
    ability = _ability(effect.get("ability"))
    sentence = f"{who} makes a {ability + ' ' if ability else ''}saving throw against your Cultivation Save DC"
    for key, result in (("on_fail", "failure"), ("on_success", "success")):
        outcomes = _outcomes(effect.get(key), typed, who="it" if who.startswith("Each ") else who)
        if outcomes:
            sentence += f". On a {result}, " + _join(outcomes)
    return sentence


def _second_person(sentence: str) -> str:
    """A row that costs its user is addressed to the reader as "you", not as "it"."""
    if not sentence.startswith("you "):
        return sentence
    rest = sentence[len("you "):]
    for wrong, right in _SECOND_PERSON:
        if rest.startswith(wrong):
            return "you " + right + rest[len(wrong):]
    return sentence


def _outcomes(effects: Any, typed: dict[str, Any], *, who: str = "it") -> list[str]:
    rows = [_outcome(effect, typed, who=who) for effect in effects or [] if isinstance(effect, dict)]
    rows = [row for row in rows if row]
    return [_second_person(row) for row in rows] if who == "you" else rows


def _delivery(row: dict[str, Any], typed: dict[str, Any]) -> list[str]:
    """What the technique does, read only from its compiled rows.

    combat/forged.py builds the delivery as the FIRST row of ``typed.effects`` (an attack, an
    area save, a Ward's temporary hit points, a movement); the Augments' own saves follow it.
    """
    effects = [effect for effect in typed.get("effects") or [] if isinstance(effect, dict)]
    numbers = typed.get("numbers") or {}
    cl = int(numbers.get("cl") or 1)
    area = typed.get("area") or {}
    size, shape = area.get("size_ft"), str(area.get("shape") or "").lower()
    where = "centred on you" if area.get("centered_on_self") else "where you choose"
    lines: list[str] = []
    first = effects[0] if effects else {}

    if first.get("type") == "save":
        reach = f"Each creature in a {size}-foot {_SHAPES.get(shape, shape)} {where}" if size and shape else "Each target"
        creation = "When you create the area: " if typed.get("zone_spec") else ""
        lines.append(creation + _save_outcome(first, typed, who=reach) + ".")
    elif first.get("type") == "attack":
        kind = str(first.get("attack_kind") or "")
        count = int(first.get("count") or 1)
        verb = "Make a ranged Cultivation Attack" if "ranged" in kind else "Make a weapon attack"
        hits = _outcomes(first.get("on_hit"), typed)
        sentence = f"{verb}{f' {count} times' if count > 1 else ''}."
        if hits:
            sentence += " On a hit, " + _join(hits) + "."
        lines.append(sentence)
    elif first.get("type") == "temp_hp":
        feet = row.get("range_ft")
        near = f"within {int(feet)} feet" if feet else "within range"
        benefits = [effect for effect in effects if effect.get("applies_to") == "target"
                    and effect.get("type") != "save"]
        for index, effect in enumerate(benefits):
            who = f"You or an ally {near}" if index == 0 else "The protected creature"
            benefit = _outcome(effect, typed, who=who)
            if benefit:
                lines.append(benefit + ".")
    elif first.get("type") == "movement":
        lines.append(_outcome(first, typed, who="you").capitalize() + ".")

    # An Augment's own saves: each is a separate roll against a separate target.
    for effect in effects[1:]:
        if effect.get("type") == "save":
            lines.append(_save_outcome(effect, typed, who="Each creature affected") + ".")
    return lines


def _persistent_area_text(typed: dict[str, Any]) -> str:
    """Quote the owner's component timing, separately from the compiled creation save.

    The form's first sentence contains template size/duration, which augments can change;
    compiled helpers own those numbers. Only its remaining clauses are quoted. An area
    made persistent by an augment instead uses that augment's printed rule verbatim.
    No zone state or trigger effects are added by this presentation helper.
    """
    from ..forged import rules

    spec = typed.get("zone_spec") or {}
    if not spec.get("triggers"):
        return ""
    table = rules()
    form = table["forms"].get(str(typed.get("base_form") or "")) or {}
    if form.get("delivery") == "zone":
        text = str(form.get("text") or "").partition(". ")[2]
    else:
        text = str(table["augments"]["persistent_zone"]["text"])
    return f"Persistent area — printed component rule: {text}" if text else ""


def _self_costs(typed: dict[str, Any]) -> list[str]:
    """What the technique costs ITS USER: the Drawbacks and Augments that apply to you."""
    effects = [effect for effect in typed.get("effects") or [] if isinstance(effect, dict)]
    rows = _outcomes([effect for effect in effects[1:] if effect.get("applies_to") == "self"], typed, who="you")
    if effects and effects[0].get("applies_to") == "self" and effects[0].get("type") == "movement":
        rows = _outcomes([effects[0]], typed, who="you") + rows
    return rows


def _reach_line(row: dict[str, Any], typed: dict[str, Any]) -> str:
    """The technique's OWN reach. A cone or line states its length as its area, and a form that
    centres on you has no range to place, so neither prints a range it would contradict."""
    area = typed.get("area") or {}
    feet = row.get("range_ft")
    if not feet or area.get("centered_on_self"):
        return ""
    if str(area.get("shape") or "").lower() in ("cone", "line") and int(feet) == int(area.get("size_ft") or -1):
        return ""
    return f"Range: {int(feet)} feet."


def _duration_line(row: dict[str, Any], typed: dict[str, Any]) -> str:
    """The technique's OWN duration and Concentration (a Zone's minute, a Drawback's
    Concentration, a Persistent Zone's longer span), never the source talent's."""
    duration = typed.get("duration") or {}
    kind = str(duration.get("kind") or "instant").lower()
    amount = duration.get("amount")
    concentration = bool(duration.get("concentration") or row.get("concentration"))
    if kind in ("instant", "", "round") and not concentration:
        return ""
    if kind in ("instant", "", "round"):
        text = "It resolves immediately."
    elif kind in ("rounds",):
        text = f"Duration: {int(amount or 1)} round{'s' if int(amount or 1) != 1 else ''}."
    elif kind in ("minutes",):
        text = f"Duration: {int(amount or 1)} minute{'s' if int(amount or 1) != 1 else ''}."
    else:
        stated = str(duration.get("text") or "").strip().rstrip(".")
        deadline = stated or (f"{amount} {_words(kind)}" if amount is not None
                              else _when({"duration": duration}))
        text = f"Duration: {deadline}." if deadline else ""
    if concentration:
        text += " You must concentrate on it for as long as it lasts; it ends if you stop concentrating."
    return text


def _join(rows: list[str]) -> str:
    """Read a list of clauses as one sentence without repeating the subject."""
    if not rows:
        return ""
    if len(rows) == 1:
        return rows[0]
    head, rest = rows[0], [_lower_first(row) for row in rows[1:]]
    return head + ", and " + ", ".join(rest)


def _lower_first(sentence: str) -> str:
    if sentence.startswith("Printed "):
        return sentence  # Keep quoted component clauses visibly separate and verbatim.
    return sentence[:1].lower() + sentence[1:] if sentence else sentence


def _cost_line(row: dict[str, Any]) -> str:
    from ..resource_labels import resource_name

    parts = []
    for entry in row.get("costs") or []:
        try:
            resource, amount = entry[0], entry[1]
        except (TypeError, IndexError):
            continue
        amount = int(amount or 0)
        if amount:
            parts.append(f"{amount} {resource_name(str(resource))}")
    return f"Cost: {', '.join(parts)}." if parts else "Cost: none."


def technique_text(row: dict[str, Any]) -> str:
    """The printed rule of one forged/constructed ability, or '' when it owns none."""
    typed = (row.get("parameters") or {}).get("typed") or {}
    name = str(row.get("display_name") or "").strip()
    primary = str(typed.get("forged_from") or "").strip()
    form = str(typed.get("base_form") or "").strip()
    if not name or not primary:
        return ""

    action = _ECONOMY.get(str(row.get("economy") or "").upper(), "")
    lines = [f"{name} — a technique you forged{form and f' (Base Form: {form})' or ''}."]
    lead = " ".join(part for part in (
        f"Action type: {action}." if action else "",
        _cost_line(row),
        _reach_line(row, typed),
    ) if part)
    if lead:
        lines.append(lead)
    for line in _delivery(row, typed):
        lines.append(line)
    duration = _duration_line(row, typed)
    if duration:
        lines.append(duration)
    persistent = _persistent_area_text(typed)
    if persistent:
        lines.append(persistent)

    costs = _self_costs(typed)
    if costs:
        lines.append("It also costs you: " + _join(costs) + ".")

    # Attribution only: the source's complete card advertises uncarried options and delivery.
    label = _own_header(primary) or "its Primary Sphere Effect"
    lines.append(f"Primary Sphere Effect — carried from {label}.")

    extras = [str(rider).strip() for rider in (typed.get("riders") or [])
              if str(rider).strip() and "'" not in str(rider)[:40]]   # drop record dict dumps
    if extras:
        lines.append("This technique also: " + "; ".join(extras) + ".")
    return " ".join(lines)


@hook("button_description")
def forged_ability_text(row: dict[str, Any]) -> str | None:
    """The forged ability's own rule. Inert for every non-forged button."""
    typed = (row.get("parameters") or {}).get("typed") or {}
    if str(typed.get("typing_status") or "") != "forged" or not typed.get("forged_from"):
        return None
    return technique_text(row) or None
