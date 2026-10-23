"""Read-only decision text shared by the tabletop's reaction, choice and Ready surfaces.

Printed rules supply effects, targets, duration and limits. Compiled rows supply
the paying pool and current costs. Plugins may explain their own choices through
``ext.decision_text``; this module never interprets an ability id as a rule.
"""
from __future__ import annotations

import re
from typing import Any

from .resource_costs import parts as cost_parts
from .player_text import explain_cp


def plain(text: Any) -> str:
    """Keep complete owner wording, removing headings and implementation metadata."""
    lines = []
    source_lines = str(text or "").splitlines()
    headers = None
    for index, line in enumerate(source_lines):
        if line.startswith("#") or re.match(r"\s*(Factory |Record ID:|Source ID:|Prerequisite:|Tags:|Talent Type:)", line):
            continue
        if line.strip().startswith("|"):
            cells = [re.sub(r"[*`]", "", c).strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            following = source_lines[index + 1].strip() if index + 1 < len(source_lines) else ""
            if following.startswith("|") and all(re.fullmatch(r":?-{3,}:?", c.strip())
                    for c in following.strip("|").split("|")):
                headers = cells
                continue
            lines.append("; ".join(f"{headers[i]}: {cell}" if headers and i < len(headers) else cell
                                   for i, cell in enumerate(cells)))
            continue
        headers = None
        lines.append(re.sub(r"[*`]", "", line).strip())
    return re.sub(r"\bCL\b", "cultivation level", "\n".join(lines).strip())


def resource_name(resource: str) -> str:
    if resource.startswith("resource:uses.") or resource.startswith("resource:typed."):
        return "use"
    return resource.rsplit(".", 1)[-1].removeprefix("resource:").replace("_", " ").title()


def is_second_person(name: Any) -> bool:
    """Whether a creature is addressed as "You": the table's control-mode label for the player's own fighter
    (hunt 74), which through a fixed-verb sentence reads "You is about to take 5 damage"."""
    return str(name or "").strip().casefold() == "you"


def agrees(name: Any, singular: str, plural: str) -> str:
    """The verb that reads right for a creature by name: "You are", "Brute is". Changes nothing for a named
    creature, so no other wording moves."""
    return plural if is_second_person(name) else singular


def costs_text(costs: Any) -> str:
    out = []
    for cost in costs or []:
        resource, amount = cost_parts(cost)
        if amount:
            out.append(f"{amount} {resource_name(str(resource))}")
    return " + ".join(out)


#: Words that mean a printed cost says MORE than the one figure beside them: the player picks between
#: branches, the charge depends on a condition, or another cost is added to it. Matched against what
#: immediately follows the printed figure and ONLY on the figure's own line -- a record's next
#: paragraph very often opens "When the target rolls..." or "While mounted...", and that is the
#: ability's effect, not more cost -- so prose that merely contains one of these words is never
#: mistaken for part of the cost: "2 CP or 2 Stamina", "up to 5 Stamina", "0 CP if drawing from an
#: existing Sand Source", "1 CP plus the Modulation's cost", "2 CP (or 1 Stamina)".
_COST_CONTINUES = re.compile(
    r"^[ \t,;/(+]*(?:or|and|plus|if|unless|when|whenever|while|provided|per|for\s+each|up\s+to"
    r"|at\s+most|instead|no\s+more\s+than)\b", re.I)
#: A second cost figure inside a printed cost's own clause. A digit beside a word, so a rate limit
#: ("once per long rest") and run-together metadata ("Control: 1") are not read as a second cost.
_COST_SECOND_FIGURE = re.compile(r"\d[\d,.]*\s*[A-Za-z]")
#: Where a printed cost's own clause ends: the end of its sentence or of the record. A semicolon does
#: NOT end it, because the owner's conditional costs are written as branches on one line
#: ("0 CP if drawing from an existing Sand Source; 1 CP if creating sand where no Sand Source exists").
_COST_CLAUSE_END = re.compile(r"(?<!\d)[.]|\n")
#: The words the owner's printed records use for a cost that is genuinely nothing. They are a fixed
#: phrase, so they are replaced as a whole phrase and never as the prose that happens to follow.
_FREE_COST_WORDS = ("no resource cost", "None")
#: A generic name for the Path resource, which the printed rules use for whatever pool the character
#: actually carries. The fight log always names the pool, so a button that says only "CP" meets a
#: newcomer with two names for one pool; the charged pool's own name replaces it.
_GENERIC_COST_WORDS = ("cultivation points", "CP point", "CP points", "CP")


def _one_charge(costs: Any) -> tuple[int, str] | None:
    """The single (amount, pool) a fight really charges, or None when there is not exactly one.

    A limited-use charge (``resource:uses.*``) is counted and printed by the use limit itself, and a
    charge spread over two pools has no single figure to state, so neither becomes a printed total.
    """
    charged = [(amount, resource_name(str(resource)))
               for resource, amount in (cost_parts(cost) for cost in costs or [])
               if amount and not str(resource).startswith("resource:uses.")]
    return charged[0] if len(charged) == 1 else None


def reviewed_printed_cost(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The printed cost the reviewed typed record behind this button states, when it states one (PRIVCONV2).

    Some abilities print their cost in words the fight does not charge in: ``tianxia.talent.ink.painted_beast``
    prints "Cost: 4 cultivation points" and is charged 4 Qi. The figure and the pool it is printed in are typed
    data on the reviewed record (``"printed_cost": {"amount": 4, "pool": "cultivation points"}`` in
    authority/typed_mechanics/reviewed_final.d/*.json, carried into
    authority/Tianxia_Typed_Mechanics_Authority_R1.json), so :func:`cost_as_charged` restates the charge from the
    record instead of re-reading the printed line -- which the public copy of the rules scrambles. A record that
    states no printed cost returns None and keeps the existing printed-wording handling.
    """
    row = row or {}
    typed = (row.get("parameters") or {}).get("typed") or {}
    from .typed_numbers import authority_mechanics

    table = authority_mechanics()
    candidates = [str(value) for value in (typed.get("forged_from"), typed.get("source"), typed.get("option_of"))
                  if value]
    # "action:typed.<mechanic id>[.<more>]": the id is the longest dotted prefix the authority knows.
    source_id = str(row.get("source_definition_id") or "")
    suffix = source_id.partition("action:typed.")[2] or source_id
    while "." in suffix:
        suffix = suffix.rsplit(".", 1)[0]
        candidates.append(suffix)
    for key in candidates:
        record = table.get(key)
        if isinstance(record, dict) and isinstance(record.get("printed_cost"), dict):
            return record["printed_cost"]
    return None


def _cost_continues(tail: str) -> bool:
    """Whether the printed cost says more than the single figure a fight really charges.

    A cost that hands the player a choice ("2 CP or 2 Stamina"), that depends on a condition ("0 CP if
    drawing from an existing Sand Source; 1 CP if creating sand where no Sand Source exists"), that
    adds another cost to it ("1 CP plus the Modulation's cost") or that names a second figure anywhere
    in its own clause cannot be restated as one compiled total: doing so would price a free branch, or
    fold an added cost into a figure which is only part of it. The connective test reads only what
    immediately follows the figure, so an effect that says "if" later in the same record is still
    restated; the second-figure test reads the cost's own clause, so a rate limit ("once per long
    rest") and run-together metadata ("Control: 1") are not mistaken for a second cost.

    Returns True (leave the owner's wording exactly as printed) rather than guessing at a figure.
    """
    if _COST_CONTINUES.match(tail):
        return True
    clause = _COST_CLAUSE_END.search(tail)
    return bool(_COST_SECOND_FIGURE.search(tail, 0, clause.start() if clause else len(tail)))


def _typed_cost(body: str, amount: int, pool: str, printed_amount: int) -> str:
    """Restate the charge over a cost line the reviewed typed record states.

    The record says the printed cost is exactly this one figure, so the figure after the cost header is the cost:
    no choice between pools, no conditional branch and no second figure to protect, and nothing about the words
    has to be decided. When the printed text states no cost line at all -- the public copy's scrambled prose --
    the charge is stated in the button's own words, so a player is never shown a button that hides its cost.
    """
    header = r"(?P<key>\bCost[*_`\s]*:)(?P<gap>[*_`\s]*)"
    figure = re.compile(r"%s%s(?P<pool>(?:[\s]+[A-Za-z]+){0,3})(?=[.,;:\n]|$)" % (header, printed_amount))
    match = figure.search(body)
    if match is not None:
        return f"{body[:match.start()]}{match['key']}{match['gap']}{amount} {pool}{body[match.end():]}"
    if re.search(r"\bCost\s*:", body):
        return body  # the text prints a cost line the reviewed record does not state; the owner's wording stands
    stated = f"Cost: {amount} {pool}."
    return f"{body} {stated}" if body.strip() else stated


def cost_as_charged(text: str, costs: Any, printed: Any = None) -> str:
    """State a printed cost as the cost the fight really charges, in the pool's own name.

    Both halves of hunt 90's cost finding sit on one button. A composed augment -- the base ability
    with any number of augments on one use (owner 2026-09-27: "Yes, any number") -- is charged its
    augments on top of the base ability, but its button showed the BASE ability's printed rules, so
    "Ye Yi spent 2 Resonance for Lightning-God Body + True Lightning-God Mantle" sat under a button
    reading "Cost: 1 CP", and a Darkness that really costs nothing to use read "Cost: no resource
    cost" under a button that charged 1 Qi. Where the amount was right the pool still had two names
    on one screen: the rules print a Path resource as "CP" while the fight log names the pool it is
    taken from ("Cost: 8 CP" beside "Zou Chenzhen spent 8 Stamina"). Amount and pool are therefore
    corrected together, from the compiled costs the engine charges, so one implementation serves every
    ability and no ability id is involved.

    Only a cost printed as one plain figure is touched. A cost that hands the player a choice, that
    depends on a condition, that adds another cost, or that names a second figure is the player's own
    decision and a compiled total would take that away or price a free branch, so the owner's wording
    stays. Text with no printed cost header is returned as it stands rather than having one invented
    for it.

    Display only. Nothing here prices a cost, gates a candidate or changes a state hash, so saved
    fights, candidate ids and AI replays are untouched.
    """
    body = str(text or "")
    charge = _one_charge(costs)
    if charge is None:
        return body
    amount, pool = charge
    # PRIVCONV2: a reviewed record that states its own printed cost is restated from that data (see
    # reviewed_printed_cost). Everything below reads the printed wording, which the public copy scrambles, so
    # it stays only for records that state no typed printed cost.
    reviewed = printed if isinstance(printed, dict) else {}
    if isinstance(reviewed.get("amount"), int) and not isinstance(reviewed.get("amount"), bool):
        return _typed_cost(body, amount, pool, int(reviewed["amount"]))
    if not body.strip() or len(re.findall(r"\bCost\s*:", body)) != 1:
        return body

    # A printed "no resource cost" / "None" is a fixed phrase, so the prose that may follow it
    # ("no resource cost Create a sphere of Darkness") is left alone and only a printed cost that
    # says more than the charged figure stops the correction.  The header is matched through the
    # owner's markdown bold ("**Cost:** 2 CP") and is written back with that markup as it was.
    header = r"(?P<key>\bCost[*_`\s]*:)(?P<gap>[*_`\s]*)"
    free = re.compile(r"%s(?:%s)(?=[\s,.])" % (header, "|".join(re.escape(w) for w in _FREE_COST_WORDS)), re.I)
    match = free.search(body)
    if match is not None:
        rest = body[match.end():]
        if _cost_continues(rest):
            return body
        return f"{body[:match.start()]}{match['key']}{match['gap']}{amount} {pool}{rest}"

    # A printed figure keeps its own wording for everything but the cost itself, and is restated as the
    # amount and the pool the fight log names.
    names = sorted({pool, *_GENERIC_COST_WORDS}, key=len, reverse=True)
    figure = re.compile(r"%s\d+(?:[\s]+(?P<pool>%s))?" % (header, "|".join(re.escape(n) for n in names)))
    match = figure.search(body)
    if match is None:
        return body
    tail = body[match.end():]
    if _cost_continues(tail):
        return body  # the printed cost says more than one figure; the owner's wording stands
    if match.group("pool") is None and re.match(r"[ \t]+[A-Za-z]", tail):
        return body  # a pool named in the owner's own words, not one this fight charges from
    return f"{body[:match.start()]}{match['key']}{match['gap']}{amount} {pool}{tail}"


# A printed selection is build-time only with explicit advancement evidence about the
# same selected trait -- "At CL15, learn a second Defensive Discipline." -- that the table has
# already resolved and that a Use/Pass prompt cannot offer as buttons.  Never let it open a
# choice-less decision's summary.  Owner wording is never edited: build_decision_text still
# publishes the complete printed text under "rules"; only the at-a-glance summary drops the
# unanswerable selection, exactly as it already drops a "Choose one of the following:" line.
_CHOOSE_HEADING = re.compile(r"^\s*choose\s+(?:one|two|three|four|five|\d+)\b", re.I)
_MARKDOWN_HEADING = re.compile(r"^(#{2,6})\s+\S")
_BOLD_LABEL = re.compile(r"^\*\*[^*]+\*\*")


def _build_time_selection(text: Any) -> str:
    """The printed text with a leading "Choose one <X>." selection block (its instruction and the
    sibling option sub-headings that follow) removed, so a choice-less prompt's summary opens on the
    operative procedure instead.  Pure, structure-only, never keyed on an ability id.

    Require an explicit level-based gain/learn of a second instance of the same trait.
    Headings and missing buttons alone cannot distinguish targets or activation modes
    from advancement selections. Ambiguous inputs keep the complete description.

    An option is a sibling heading of that depth plus the words printed directly under it, and the
    block ends at the first thing that is not an option: a heading of a different depth (the
    "Response Procedure" section), a bold label, a second "Choose" instruction, or -- because some
    texts print the procedure straight after their last option with no heading of its own -- the
    first new paragraph after the option run.  When that boundary cannot be established the owner's
    wording is kept rather than risk deleting what the ability actually does.  Text with no such
    sibling-heading block is returned unchanged.
    """
    lines = str(text or "").splitlines()
    start = next((index for index, line in enumerate(lines) if _CHOOSE_HEADING.match(line)), None)
    if start is None:
        return str(text or "")
    selection = re.fullmatch(r"\s*choose\s+one\s+([^.!?]+)[.!]?\s*", lines[start], re.I)
    if selection is None:
        return str(text or "")
    trait = re.escape(selection.group(1).strip())
    advancement = re.compile(r"\b(?:gain|learn)\s+(?:a\s+)?second\s+" + trait + r"\b", re.I)
    if not any(advancement.search(line) and re.search(r"\bCL\s*\d+\b", line, re.I)
               for line in lines):
        return str(text or "")
    # The options are the first run of sibling sub-headings after the instruction.
    level = None
    for line in lines[start + 1:]:
        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            break
        if line.strip() and not _BOLD_LABEL.match(line):
            break  # prose, not an option list: nothing to lift
    if level is None:
        return str(text or "")  # not the sibling-heading form; leave the owner's wording intact
    end = start + 1
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if _BOLD_LABEL.match(line) or _CHOOSE_HEADING.match(line):
            break
        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            if len(heading.group(1)) != level:
                break  # a sub-section of another depth (the procedure) begins the real decision
            index += 1
            end = index
            while index < len(lines) and not lines[index].strip():
                index += 1  # an option's own words sit under its heading, past the blank line
            while index < len(lines) and lines[index].strip():
                inner = _MARKDOWN_HEADING.match(lines[index])
                if inner or _BOLD_LABEL.match(lines[index]) or _CHOOSE_HEADING.match(lines[index]):
                    break
                index += 1
                end = index
            continue
        if not line.strip():
            offset = next((n for n, other in enumerate(lines[index:]) if other.strip()), None)
            following = lines[index + offset] if offset is not None else ""
            heading = _MARKDOWN_HEADING.match(following)
            if heading and len(heading.group(1)) == level:
                index += offset  # another sibling option follows
                continue
            break  # a blank line and then a new paragraph: the option run is finished
        break  # prose before any option heading
    # Introductory prose is not a replacement for option-only effects. Even with
    # advancement evidence, retain the options unless a separate procedure follows.
    if not any(line.strip() and not _MARKDOWN_HEADING.match(line)
               and not advancement.search(line) for line in lines[end:]):
        return str(text or "")
    return "\n".join([*lines[:start], *lines[end:]])


def _source_row(engine: Any, reactor: str, feature: str, name: str) -> tuple[str, dict, Any]:
    if engine is None:
        return feature, {}, None
    catalog = getattr(engine, "action_catalog", {})
    for store in ("typed_reaction_rows", "typed_passive_rows"):
        for row in getattr(engine, store, {}).get(reactor, []):
            if row.get("feature_id") == feature or (name and row.get("name", "").casefold() == name.casefold()):
                return str(row.get("feature_id") or feature), row, None
    for action in catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == reactor and (action.source_definition_id == feature or typed.get("source") == feature
                                          or (name and action.display_name.casefold() == name.casefold())):
            return str(typed.get("source") or feature), typed, action
    return feature, {}, None


_ABILITIES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
              "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
_ROLL_EVENTS = {"save": "SAVE_ROLLED", "attack": "ATTACK_ROLLED", "check": "CHECK_ROLLED"}
# A save against maintaining Concentration is a Constitution save in basic D&D, and the record
# carries no ability for it, so the prompt names it in words. Owner 2026-10-02 (hunt DS12 #1).
_SYSTEM_SAVE = {"system:combat.concentration": ("Constitution", " to keep concentrating")}


def _ability_name(code: Any) -> str:
    return _ABILITIES.get(str(code or "").lower()[:3], "")


def _rolled_event(recent: list[dict], kind: str, roller_id: Any, source_id: Any = None) -> dict:
    """A recorded roll of this kind, for a scope that carries no roll of its own.

    The newest one made by the creature that rolled it, and -- when the prompt names a source --
    only from that source, so an unrelated earlier roll is never presented as this prompt's.
    """
    wanted = _ROLL_EVENTS.get(str(kind or ""))
    if not wanted:
        return {}
    mine = [e for e in recent if e.get("event_type") == wanted
            and (not roller_id or e.get("actor_id") == roller_id)]
    if not mine:
        return {}
    if source_id:
        return next((e for e in mine if e.get("source_definition_id") == source_id), {})
    return mine[0]


def _roll_of_prompt(trigger: dict, recent: list[dict], kind: str, roller_id: Any) -> dict:
    """What is known about the roll this reroll/retry prompt is about.

    The consent transport carries the active roll (combat/ext/d20_rewrite.roll_scope) and that is
    the only record that can be right: the current roll is written to the journal after the prompt
    opens, so a search of the history can return a previous roll instead. The history is read only
    when the scope carries no roll at all, and then only for the roller's own roll from this source.
    MMX71r review, owner 2026-10-02.
    """
    if trigger.get("roll_record_id"):
        return {"ability": trigger.get("roll_ability"), "dc": trigger.get("roll_dc"),
                "outcome": str(trigger.get("roll_outcome") or "unknown"),
                "guarantee": str(trigger.get("roll_guarantee") or "unknown"),
                "victim_id": trigger.get("roll_victim_id"),
                "source_id": str(trigger.get("source_definition_id") or "")}
    record = _rolled_event(recent, kind, roller_id, trigger.get("source_definition_id"))
    data = record.get("payload") or {}
    told = data.get("provisional_hit") if str(kind) == "attack" else data.get("success")
    return {"ability": data.get("ability"), "dc": data.get("dc"),
            "outcome": {True: "success", False: "failure"}.get(told, "unknown"),
            "guarantee": "unknown",     # no rule travels with a scope that carries no roll
            "victim_id": next(iter(record.get("target_ids") or []), None),
            "source_id": str(trigger.get("source_definition_id") or record.get("source_definition_id") or "")}


def _dc_text(roll: dict) -> str:
    dc = roll.get("dc")
    return f" (DC {dc})" if isinstance(dc, int) else ""

# The trigger kinds the engine raises itself (combat/reaction_triggers.py RUNNABLE_KINDS), in the
# words a player who knows only basic D&D would use. The checkpoint word is the trigger kind
# uppercased (combat/typed_reactions.py's kind.upper()), and it names a change to a creature --
# so one table reads correctly for every ability that triggers on that kind, self or not.
#
# Each entry is (subject, predicate[, plain_words]). "subject" is "who" when the creature named in
# the sentence is the one the change happened to, "actor" when it is the creature that did it, and
# "ally" when the change happened to one of the reactor's allies. That choice decides whether a
# "from ..." clause may be added at all: an ally_* kind is fired *by* the ally's own event, so the
# ally is the subject and naming a separate source would be wrong.
#
# A predicate may use these slots, each replaced only when the event actually carries that detail,
# so a missing name never leaves a gap in the sentence:
#   {action}  the ability or attack that was used, or the entry's own plain_words
#   {from}    what caused the change, read as "from <creature>'s <action>" ("from <creature>",
#             "from <action>"); dropped when the only name available is the creature itself
#   {by}      the same detail read as the doer of something ("by <creature>'s <action>");
#             omit a self-doer because a recent save names the defender, not the source
#   {other}   the second creature the event names (the one an ally grabbed, for one); plain_words
#             when that one is not known
_MOMENTS: dict[str, tuple] = {
    # something a creature gained
    "HEALED": ("who", "regained hit points"),
    "TEMP_HP_GAINED": ("who", "gained Temporary hit points"),
    "CP_RESTORED": ("who", "regained cultivation points (its Path resource)"),
    "BECAME_HIDDEN": ("who", "became Hidden"),
    # something a creature lost
    "DAMAGED": ("who", "took damage"),
    "BLOODIED": ("who", "fell to half its hit points"),
    "DROP_TO_ZERO": ("who", "fell to 0 hit points"),
    "MULTI_DAMAGE": ("actor", "damaged two or more creatures with {action}", "one effect"),
    "CONDITION_GAINED": ("who", "gained a condition"),
    # an attack landing or missing
    "CRITICAL_HIT": ("who", "was hit by a critical hit"),
    "NATURAL_1": ("who", "was missed by a natural 1"),
    "ATTACKED": ("who", "was targeted by an attack"),
    "HIT": ("who", "was hit"),
    "MISSED": ("who", "missed with an attack"),
    # a saving throw
    "SAVE": ("who", "failed a saving throw"),
    "SAVE_RESULT_BEFORE_DECLARED": ("who", "failed a saving throw"),
    # a grapple. The one who failed to be grabbed is the creature the grapple happened to, and the
    # one who tried is named as the doer: nothing says a grapple was already on it beforehand.
    "GRAPPLE_FAILED": ("who", "was not grabbed{by}"),
    # the reactor's own turn and actions
    "OWN_ACTION": ("who", "used an ability"),
    "OWN_ABILITY": ("who", "used an ability"),
    "OWN_TURN_START": ("who", "started its turn"),
    "OWN_HIT": ("who", "hit a creature with an attack"),
    "OWN_KILL": ("who", "defeated a creature with an attack"),
    "OWN_SAVE_FAILED": ("who", "failed a saving throw"),
    "OWN_SAVE_SUCCEEDED": ("who", "passed a saving throw"),
    "OWN_D20_FAIL": ("who", "failed a d20 roll"),
    # another creature acting. The acting creature is the subject, so name the ability it used.
    "CREATURE_ACTED": ("actor", "used {action}", "an ability"),
    "CREATURE_ATTACK_MISSED": ("actor", "missed with {action}", "an attack"),
    "CREATURE_TURN_START": ("actor", "started its turn"),
    "CREATURE_D20": ("actor", "rolled a d20"),
    "CREATURE_NAT": ("actor", "rolled a d20"),
    "CREATURE_SAVE_FAILED": ("actor", "failed a saving throw"),
    "CREATURE_SAVE_SUCCEEDED": ("actor", "passed a saving throw"),
    "INITIATIVE": ("actor", "rolled for initiative"),
    # something that happened to one of the reactor's allies (the ally did the thing). The ally is
    # the subject, so it is named when the event says who it was; the creature it acted on, when the
    # event names one, comes after it.
    "ALLY_ATTACKED": ("ally", "was targeted by an attack"),
    "ALLY_HIT": ("ally", "was hit"),
    "ALLY_MISSED": ("ally", "missed with an attack"),
    "ALLY_DAMAGED": ("ally", "took damage"),
    "ALLY_DROP_TO_ZERO": ("ally", "fell to 0 hit points"),
    "ALLY_CONDITION_GAINED": ("ally", "gained a condition"),
    "ALLY_FORCED_MOVED": ("ally", "was pushed or pulled"),
    "ALLY_TURN_START": ("ally", "started its turn"),
    "ALLY_GRAPPLE_SUCCEEDED": ("ally", "grabbed {other}", "a creature"),
    # movement
    "LEAVES_REACH": ("who", "moved out of reach"),
    "FORCED_MOVED": ("who", "was pushed or pulled"),
    # a technique aimed at the reactor
    "TECHNIQUE_USED": ("who", "was targeted by a technique"),
    "TECHNIQUE_TARGETS": ("who", "was targeted by a technique"),
    # an attack that has finished
    "ATTACK_RESOLVED": ("who", "finished an attack"),
}


def _source_clause(target: str, actor: str, action: str, preposition: str = "from") -> str:
    """Name what did it, but never as the creature it happened to.

    A heal is caused by a *different* creature, so naming the healed creature as its own source
    ("Corpse Servant 2 healed from Corpse Servant 2") states something untrue. The clause is
    dropped when the only name available is the creature the sentence is already about, and when
    nothing at all is known.
    """
    if action and actor and actor != target:
        return f" {preposition} {actor}'s {action}"
    if action and actor and actor == target:
        return f" {preposition} {'your' if is_second_person(target) else 'their'} own effect: {action}"
    if action:
        return f" {preposition} {action}"
    return f" {preposition} {actor}" if actor and actor != target else ""


def _named_clause(target: str, actor: str, action: str, preposition: str) -> str:
    """``_source_clause`` for a sentence that has already said who the change happened to.

    Naming the same creature as its own source ("Corpse Servant 2 healed from Corpse Servant 2")
    states something untrue, so ``_source_clause`` drops that case. The sentences that use this one
    keep the two creatures apart through explicit movement metadata -- a shove names the creature
    that is moving -- so the creature is always worth naming.
    """
    if action and actor:
        return f" {preposition} {actor}'s {action}"
    if action:
        return f" {preposition} {action}"
    return f" {preposition} {actor}" if actor else ""


def _moment_sentence(moment: str, target: str, actor: str, action: str) -> str | None:
    """Read a trigger kind as the change it describes, or None when this is not a known kind.

    Any trigger kind in ``_MOMENTS`` reads the same for every ability that uses it, because the
    moment is about the creature rather than the feature. A kind whose subject is the acting
    creature needs that creature actually named; an ally_* kind names the ally itself, so it
    never takes a separate source.
    """
    entry = _MOMENTS.get(moment)
    if not entry:
        return None
    subject, predicate = entry[0], entry[1]
    # The plain words this entry uses when the event does not name that detail.
    generic = entry[2] if len(entry) > 2 else ""
    if subject == "actor":
        # Nothing is known about who acted: say what is true rather than name the reactor wrongly.
        if not actor:
            return None
        who = actor
        # The acting creature is the subject, so the other one is whatever the event acted on.
        other = target if target and target != actor else ""
    elif subject == "ally":
        # The ally is the creature the event came from, so name it when the engine says who.
        who = actor or "An ally"
        other = target if target and target != actor else ""
    else:
        who = target or actor
        # The change happened to this creature, so the other one is whoever caused it.
        other = actor
    # Each slot is replaced with what the event actually carries, or with this entry's own plain
    # words, so a missing detail never leaves a gap in the sentence.
    says = (predicate.replace("{action}", action or generic)
            .replace("{other}", other or generic or "a creature")
            .replace("{by}", _source_clause(who, actor, action, "by")))
    if "{from}" in predicate:
        says = says.replace("{from}", _source_clause(who, actor, action))
    elif subject == "who" and "{by}" not in predicate:
        # A change to a creature usually has a cause worth naming, unless the entry already said who.
        says += _source_clause(who, actor, action)
    return f"{who} {says}."


def trigger_text(context: dict, prompt: dict, actors: dict, definitions: dict) -> str:
    """Describe the actual checkpoint, with explicit nested metadata taking priority."""
    trigger = context.get("choice_trigger") or {}
    recent = list(reversed(context.get("recent_events") or []))
    moment = str(context.get("checkpoint") or "").removeprefix("TYPED:").split("@")[0]
    reactor = prompt["reactor"]
    source_id = trigger.get("source_definition_id")
    # Optional trigger fields are serialized as null by older/native producers.
    # Only concrete provenance overrides the matching recent action; a null
    # source is not evidence that the triggering action has no name.
    has_explicit_trigger = bool(source_id or trigger.get("source_id") or trigger.get("roll_kind")
                                or trigger.get("action_name"))
    has_contextual_action = bool(prompt.get("action")) and bool(prompt.get("affected"))
    explicit = has_explicit_trigger or has_contextual_action
    source_id = source_id or trigger.get("source_id")
    actor_id = (trigger.get("action_actor_id", trigger.get("actor_id")) if has_explicit_trigger else
                trigger.get("action_actor_id") or trigger.get("actor_id") or context.get("attacking_actor_id"))
    target_id = (trigger.get("affected_id") or trigger.get("target_id") or context.get("damaged_target_id")
                 or context.get("protected_target_id") or (prompt.get("affected") if has_contextual_action else None))
    # Only action events identify an action; a recent resource spend/zone tick is not one.
    event = next((e for e in recent if e.get("event_type") in ("INTENT_ACCEPTED", "ATTACK_DECLARED", "ACTION_DECLARED", "ATTACK_ROLLED", "SAVE_ROLLED")
                  and (not actor_id or e.get("actor_id") == actor_id)), {})
    if not explicit:
        source_id = source_id or event.get("source_definition_id")
        actor_id = actor_id or event.get("actor_id")
    target_id = target_id or next(iter(event.get("target_ids") or []), None)
    action = trigger.get("action_name") or definitions.get(source_id, "") or prompt.get("action", "")
    if moment == "GRAPPLE_FAILED" and trigger.get("trigger_kind") == "grapple_failed":
        # on_own_event names the reactor first and the attempted grappler second.
        # Present the failed attempt with the defender as subject and grappler as cause.
        actor_id, target_id = target_id, actor_id
    actor = actors.get(actor_id, "") or ("" if explicit else prompt.get("trigger_actor") or prompt.get("by", ""))
    # A prompt must never show a raw actor id to a player; resolve the reactor's name too.
    target = actors.get(target_id, "") or prompt.get("affected") or actors.get(reactor, "") or reactor
    cause = f"{actor}'s {action}" if actor and action else action or actor
    from .placement_menu import CHOICE as PLACEMENT_CHOICE
    if (context.get("extension_choice") and actor_id == context.get("reactor_id")
            and context.get("reaction_source_id") == PLACEMENT_CHOICE and not trigger.get("roll_kind")
            and trigger.get("prompt")):
        # A placement square the reactor chooses for its own action is a choice, not a reaction to oneself.
        return str(prompt.get("moment", ""))
    if has_contextual_action and not trigger.get("roll_kind"):
        # "by" names the chooser/reactor in the table envelope. The triggering
        # action belongs to its structured actor, which can be another creature.
        # An unknown source stays unknown rather than borrowing the reactor.
        source = actor or ("" if has_explicit_trigger else prompt.get("trigger_actor"))
        if source and action and target:
            return f"{source}'s {action} triggered a reaction affecting {target}."
    if context.get("extension_choice") and not trigger.get("prepared") and not has_explicit_trigger:
        # Without a scoped receipt or structured action/affected pair, the
        # extension's own moment text is the only reliable description.
        return str(prompt.get("moment", ""))
    roll_kind = trigger.get("roll_kind")
    if roll_kind:
        roll = {"attack": "attack roll", "save": "saving throw", "check": "ability check"}.get(roll_kind, "d20 roll")
        ability = _ability_name(trigger.get("save_ability"))
        if moment.startswith(("D20_REROLL", "D20_REWRITE")):
            # A reroll/retry prompt is only legal once the d20 is already rolled, so it must say which roll it is
            # about, what came of it, and what caused it. Owner 2026-10-02 (hunt DS12 #1, review MMX71r): saying
            # "failed" of every such prompt called a successful roll a failure, and reading the history could
            # show a previous roll's ability and DC instead of this one's.
            this_roll = _roll_of_prompt(trigger, recent, roll_kind, target_id if roll_kind == "save" else actor_id)
            outcome = this_roll["outcome"] if this_roll["outcome"] != "unknown" else this_roll["guarantee"]
            system_save = _SYSTEM_SAVE.get(this_roll["source_id"], ("", ""))
            ability = ability or _ability_name(this_roll["ability"]) or system_save[0]
            purpose = system_save[1]
            against = cause or actor
            who = actors.get(trigger.get("roll_roller_id") or "") or target
            if roll_kind == "attack":
                # The roller is the creature making the attack; the creature it was rolled against is named apart.
                victim = actors.get(this_roll["victim_id"], "")
                aimed = f" against {victim}" if victim else ""
                named = f" for {action}" if action else ""
                attack = f"{who}'s{f' {ability}' if ability else ''} attack roll{named}{aimed}"
                landed = {"success": "hit", "failure": "missed"}.get(outcome)
                if landed:
                    return f"{attack} {landed}."
                return f"{attack} was just rolled; this prompt is about that roll."
            noun = "ability check" if roll_kind == "check" else "saving throw"
            article = "a" if ability or roll_kind == "save" else "an"
            what = f"{article} {f'{ability} ' if ability else ''}{noun}{purpose}{_dc_text(this_roll)}"
            # A creature's own roll is not caused by that creature: say "from" only for another creature.
            because = f" from {against}" if against and against != who else ""
            if outcome == "failure":
                return f"{who} failed {what}{because}."
            if outcome == "success":
                return f"{who} succeeded at {what}{because}."
            # The table cannot read this roll's result: say the roll, never guess how it went.
            return f"{who} made {what}{because}; this prompt is about that roll."
        if roll_kind == "save" and ability:
            roll = f"{ability} {roll}"
        timing = ("are about to make" if is_second_person(target) else "is about to make") if moment == "D20_PENDING" \
            else ("have made" if is_second_person(target) else "has made")
        article = "an" if roll.startswith(("attack", "ability")) else "a"
        return f"{target} {timing} {article} {roll}{_source_clause(target, actor, action, 'for')}."
    if moment == "ANY_DROP_TO_ZERO":
        dropped = next((e for e in recent if e.get("event_type") in ("ACTOR_DEFEATED", "LIFE_STATE_CHANGED")
                        or (e.get("event_type") == "DAMAGE_APPLIED" and (e.get("payload") or {}).get("hp_after") == 0)), {})
        fallen = actors.get(trigger.get("target_id"), "") or actors.get(next(iter(dropped.get("target_ids") or []), dropped.get("actor_id")), "")
        return f"{fallen or target} dropped to 0 HP."
    if moment == "REACTION_USED":
        used = next((e for e in recent if e.get("event_type") == "REACTION_WINDOW_OPENED"), {})
        who = actors.get(trigger.get("actor_id") or used.get("actor_id"), "") or actor
        name = trigger.get("reaction_name") or definitions.get(used.get("source_definition_id"), "")
        return f"{who} used {name or 'a Reaction'}{f' affecting {target}' if target != who else ''}."
    if moment == "DAMAGE_APPLICATION":
        amount = trigger.get("damage_amount", context.get("pending_damage"))
        window = next((e for e in recent if e.get("event_type") == "REACTION_WINDOW_OPENED"
                       and (e.get("payload") or {}).get("checkpoint") == "DAMAGE_APPLICATION"
                       and (not target_id or target_id in (e.get("target_ids") or []))), {})
        if amount is None:
            amount = (window.get("payload") or {}).get("pending_damage")
        if not target_id:
            target = actors.get(next(iter(window.get("target_ids") or []), None), "") or target
        return f"{target} {agrees(target, 'is', 'are')} about to take {str(amount) + ' ' if amount is not None else ''}damage{_source_clause(target, actor, action)}."
    if moment == "CONDITION_ABOUT_TO_APPLY":
        condition = str(trigger.get("condition_name") or "a condition").replace("_", " ")
        return f"{target} would become {condition}{_source_clause(target, actor, action)}."
    if moment == "ENTERS_RANGE":
        return f"{actor or target} moved into {reactor}'s reach."
    if moment.startswith("READY:") and trigger.get("prepared"):
        prepared = trigger["prepared"]
        event_type = trigger.get("event_type")
        moved = event_type in ("ACTOR_MOVED", "MOVEMENT_COMMITTED") or (event.get("payload") or {}).get("kind") == "MOVE"
        activity = "moves" if moved else f"uses {action or 'an action'}"
        return f"{actor or target} {activity}{f' on {target}' if target != actor and not moved else ''}; this matches {prepared['label']}."
    if moment == "D20_ROLL_BONUS":
        kind = {"save": "saving throw", "attack": "attack roll", "check": "ability check"}.get(trigger.get("roll_kind"), "roll")
        return f"{target} rolled a {kind}; you may add a bonus to the result."
    phrases = {
        "OWN_KILL": f"{actor}'s {action or 'damage'} reduced {target} to 0 HP",
        "OWN_HIT": f"{actor}'s {action or 'attack'} hit {target}",
        "D20_REROLL_SAVE": f"{target} failed a saving throw",
        "D20_REROLL_CHECK": f"{target} failed an ability check",
        "D20_REROLL_ATTACK": f"{target} was hit by an attack",
        "ATTACK_DECLARED": f"{actor} attacks {target} with {action or 'an attack'}",
        "ATTACK_HIT_BEFORE_DAMAGE": f"{actor}'s {action or 'attack'} hit {target}; damage has not been applied",
        "ATTACK_MISSED": f"{actor}'s {action or 'attack'} missed {target}",
        "TECHNIQUE_DECLARED": f"{actor} uses {action or 'an ability'} on {target}",
        "LEAVE_REACH": f"{actor or target} leaves {reactor}'s reach",
        # "is being moved" needs the preposition attached to the source name, so the source is
        # joined with "by" rather than with the "from ..." clause ("moved by from Right's Shove").
        "FORCED_MOVEMENT": f"{target} is being moved{_named_clause(target, actor, action, 'by') or ' by an effect'}",
        "MOVED": f"{actor or target} moved willingly",
    }
    if moment in phrases:
        if moment not in {"OWN_HIT", "OWN_KILL"} or actor:
            return phrases[moment] + "."
    read = _moment_sentence(moment, target, actor, action)
    if read is not None:
        return read
    # Anything left is either owner wording that already reads as a sentence, or a checkpoint the
    # table has no plain words for. A bare checkpoint word is never spliced into a sentence
    # ("Corpse Servant 2 healed" is not English and asserts nothing); say what is true instead.
    said = str(prompt.get("moment", "") or "").strip()
    if said and said.casefold() != moment.replace("_", " ").lower():
        return f"{target} {said}{_source_clause(target, actor, action)}."
    if actor and actor != target:
        return f"{actor} just did something {target} can react to."
    return f"Something just happened that {target} can react to."


def _choice_summary(prompt: dict, cost: str) -> str:
    """The plain-language rule for a choice prompt whose printed feature text did not resolve.

    A shared choice transport (``combat/ext/needle.py``'s ``ask``) carries sub-decisions of a printed
    ability under their own name -- "Tempering Forms", "Reed Quench" -- which are not printed headings, so
    no rules_text entry matches and the prompt would show "No printed rule summary is available". The
    decision still knows what it is: the ability, when it is being asked, what each option does, and what
    it costs. This states those in plain words for a player who knows only basic D&D, and is inert whenever
    a printed rule summary resolved.
    """
    choice = prompt.get("choice") or {}
    options = choice.get("options") or []
    if not options:
        return ""
    name = str(prompt.get("reaction") or "").strip()
    when = str(prompt.get("moment") or "").strip()
    if name and when.lower().startswith(name.lower()):
        # Drop only the name the first line already states. The rest of the moment is the part that carries
        # the timing, the number of picks and the duration ("choose one Form until your next turn"), so it
        # must survive: deleting the whole moment is what made the summary unexplained.
        when = when[len(name):].lstrip(" :-\u2014").strip()
    if when and not when.endswith((".", "?", "!")):
        when += "."
    if when:
        when = when[:1].upper() + when[1:]
    lines = [f"{name} asks you to choose what it does." if name else "This decision asks you to choose what happens."]
    if when:
        lines.append(when)
    lines.append("Your options:")
    for option in options:
        label = str(option.get("label") or "").strip()
        lines.append(f"- {label}" if label else "- (an unnamed option)")
    pay = re.sub(r"^none$", "no cost", (str(cost or "none").strip().rstrip(".") or "none"))
    lines.append(f"Cost: {pay}.")
    if choice.get("allow_decline"):
        lines.append("You may also decline and skip this.")
    return "\n".join(lines)


def build_decision_text(engine: Any, context: dict, prompt: dict, actors: dict, definitions: dict, rules: dict) -> dict:
    """Enrich an existing response without changing its answer contract or mechanics."""
    from . import ext

    metadata = {}
    if engine is not None:
        for result in ext.run("decision_text", engine, context, rules):
            if isinstance(result, dict):
                metadata.update(result)
    trigger = context.get("choice_trigger") or {}
    metadata = {**{key: trigger[key] for key in (
        "cost", "paying_pool", "display_name", "display_trigger", "display_summary",
        "display_cost", "display_uses_reaction", "display_rules") if key in trigger}, **metadata}
    feature = str(metadata.get("feature_id") or trigger.get("feature_id") or context.get("reaction_source_id", "").removeprefix("reaction:typed."))
    feature, row, action = _source_row(engine, context.get("reactor_id"), feature, prompt["reaction"])
    text = metadata.get("display_rules") or metadata.get("rules") or rules.get(feature, "")
    if not text:
        # Older plugins carry a display name rather than a record id. Match the printed heading, never an invented rule.
        text = next((value for value in rules.values() if value.splitlines() and
                     re.sub(r"^#+\s*", "", value.splitlines()[0]).split(" - ")[0].casefold() == prompt["reaction"].casefold()), "")
    if not text:
        # Constructed techniques may only carry their owner-approved evidence in the compiled effects.
        evidence = []
        def collect(value):
            if isinstance(value, dict):
                if value.get("evidence") and value["evidence"] not in evidence:
                    evidence.append(str(value["evidence"]))
                for key, child in value.items():
                    if key != "evidence":
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(row.get("effects") or [])
        text = "\n".join(evidence)
    costs = costs_text(action.costs if action else row.get("costs"))
    if row.get("resource_id"):
        if row.get("block") == "damage_soak":
            spend = trigger.get("automatic_spend")
            costs = f"{spend} {resource_name(row['resource_id'])} selected by the table; up to {row['max_spend']} allowed" if spend else f"up to {row['max_spend']} {resource_name(row['resource_id'])}"
        else:
            costs = costs_text([(row["resource_id"], row.get("cost", 0))])
    opportunity = row.get("block") == "opportunity" or context.get("reaction_source_id") == "system:combat.opportunity_attack"
    if opportunity and not metadata.get("display_name"):
        text = ("When a hostile creature leaves your reach, you may spend your Reaction to make one melee attack against it before it leaves. "
                "Disengaging or movement that does not provoke an opportunity attack does not trigger this attack.")
        costs = "Reaction; no additional resource cost"
    cost = metadata.get("display_cost") or metadata.get("cost") or costs
    if not cost:
        cost = next((re.sub(r"^Cost:\s*", "", line) for line in plain(text).splitlines() if line.startswith("Cost:")), "none")
    # Explain CP at this decision in the pool actually paying it, including in the owner wording.
    pool = next((resource_name(str(resource)) for resource, _amount in (cost_parts(c) for c in row.get("costs") or []) if resource and resource_name(str(resource)) not in ("use", "Martial Focus")), "")
    if action:
        pool = next((resource_name(r) for r, _ in action.costs if resource_name(r) not in ("use", "Martial Focus")), pool)
    if metadata.get("paying_pool"):
        pool = resource_name(metadata["paying_pool"])
    unresolved_cost = bool(re.search(r"\bCP\b", str(cost)) and not pool)
    cost = explain_cp(cost, pool)
    # CP is explained in the pool actually paying it, in the summary and in the owner wording alike.
    def with_pool(body: str) -> str:
        return explain_cp(body, pool)
    printed = with_pool(plain(text))
    limits = "\n".join(line for line in printed.splitlines() if re.search(r"Use Limit:|once|only one|cannot|no more than|per round|per turn", line, re.I))
    riders = row.get("riders") or []
    effects = row.get("effects") or []
    notes = []
    if str(context.get("checkpoint", "")).startswith("TYPED:D20_PENDING"):
        notes.append("This table asks before the d20 is rolled. It applies the bonus to an ally's roll or the penalty to an enemy's roll automatically.")
    if unresolved_cost:
        notes.append("The printed resource cost is not compiled for this prompt; the table does not charge that cost automatically.")
    if riders or any(e.get("type") in ("rider", "recorded_modifier") for e in effects):
        notes.append("Some printed effects are recorded for the GM; the table does not apply those effects automatically.")
    if row.get("option_labels") and not prompt.get("choice") and not metadata.get("selected_mode"):
        selected = int(row.get("option") or 0)
        labels = row["option_labels"]
        if 0 <= selected < len(labels):
            selected_label = re.sub(r"\bCP\b", pool or "cultivation points", labels[selected])
            notes.append(f"Use runs the saved option: {selected_label}. This prompt does not choose a different outcome.")
    note = metadata.get("table_note") or " ".join(notes)
    if metadata.get("selected_mode") and metadata.get("table_note"):
        note = " ".join([*notes, metadata["table_note"]])
    # A printed Reaction and a compiled free trigger are different; display the current decision's economy.
    if not metadata.get("cost") and str(context.get("reaction_source_id", "")).startswith("reaction:typed."):
        reaction = bool(row and not row.get("free") and row.get("reaction", True))
        if reaction and "Reaction" not in str(cost):
            cost = "Reaction; " + ("no resource cost" if str(cost).lower() == "none" else str(cost))
    # A prompt that offers no selectable options must not open its summary with a printed
    # "Choose one ..." selection the player cannot pick from (a build-time discipline, a resolved
    # default).  Such prompts are Use/Pass: the summary describes the operative procedure instead.
    # Prompts that DO carry options (real buttons) keep the printed selection, and the complete
    # owner wording is still published under "rules" either way.
    choice = prompt.get("choice") or {}
    offers_options = bool(choice.get("options"))
    # The stripped text is normalized the same way as "rules", so a summary never re-introduces a
    # bare "CP" the paying-pool wording just explained, and a text with no selection block is
    # published unchanged.
    def effect_text(body: str) -> list:
        return [line for line in body.splitlines() if line and not re.match(
            r"^(?:(?:Action Type|Timing Detail|Trigger|Cost|Range|Target|Area|Duration|Use Limit|Limit|Prerequisite):|"
            r"(?:Reaction|Action|Bonus Action|No Action)$|Choose one of the following:)", line, re.I)]
    effect_lines = effect_text(printed if offers_options else with_pool(plain(_build_time_selection(text))))
    if not effect_lines and not offers_options:
        # The options ran to the end of the text, so there is no procedure to fall back to and
        # lifting the selection would leave the player a summary of nothing.  The owner's wording is
        # the better of the two, so keep it.
        effect_lines = effect_text(printed)
    summary = "\n".join(effect_lines[:4]) or _choice_summary(prompt, str(cost))
    trigger_data = context.get("choice_trigger") or {}
    has_trigger_provenance = (bool(trigger_data.get("source_definition_id") or trigger_data.get("source_id")
                                  or trigger_data.get("roll_kind") or trigger_data.get("action_name"))
                              or (bool(prompt.get("action")) and bool(prompt.get("affected"))))
    actual_trigger = trigger_text(context, prompt, actors, definitions)
    supplied_trigger = (metadata.get("trigger") or metadata.get("display_trigger")
                        or (prompt.get("moment") if context.get("extension_choice") else None))
    if has_trigger_provenance:
        # Provenance identifies the action/creature; provider text can carry
        # printed consequences or limits that must survive that identification.
        described_trigger = actual_trigger
        if supplied_trigger and supplied_trigger not in actual_trigger:
            described_trigger += " " + supplied_trigger
    else:
        described_trigger = supplied_trigger or actual_trigger
    result = {**prompt, "reaction": metadata.get("name") or metadata.get("display_name") or prompt["reaction"],
              "trigger": with_pool(described_trigger),
              "summary": metadata.get("summary") or metadata.get("display_summary") or summary or "No printed rule summary is available for this decision.",
              "cost": str(cost), "limits": metadata.get("limits") or limits,
              "rules": printed, "table_note": note}
    # Plug-in choices keep their original moment rather than replacing it with
    # the trigger. Apply the same resource vocabulary on both public surfaces.
    if "moment" in result:
        result["moment"] = with_pool(result["moment"])
    # Reaction transport also carries free triggers and choices within an action.
    # The compiled economy (or Ready's explicit current cost) identifies a real Reaction.
    uses_reaction = bool(row and not row.get("free") and row.get("reaction", True)
                         and str(context.get("reaction_source_id", "")).startswith("reaction:typed."))
    uses_reaction = uses_reaction or bool(action and not context.get("extension_choice") and action.economy == "REACTION")
    uses_reaction = uses_reaction or bool(re.match(r"^(?:\d+\s+)?Reaction\b", str(cost)))
    if metadata.get("display_uses_reaction") is not None:
        uses_reaction = bool(metadata["display_uses_reaction"])
    result["title"] = "Reaction" if uses_reaction else metadata.get("display_name") or prompt["reaction"]
    if prompt.get("choice"):
        descriptions = metadata.get("option_descriptions") or {}
        options = []
        for option in prompt["choice"]["options"]:
            # Display copies use the same resource wording as the moment and
            # rules; the engine's option ids and stored labels stay untouched.
            label = with_pool(option["label"])
            description = descriptions.get(option["id"]) or next((line for line in printed.splitlines()
                if re.match(r"^" + re.escape(label.split(" (")[0]) + r"\s*:", line, re.I)), "")
            description = with_pool(description)
            options.append({**option, "label": label,
                            "description": description if description != label else ""})
        result["choice"] = {**prompt["choice"], "options": options}
    return result
