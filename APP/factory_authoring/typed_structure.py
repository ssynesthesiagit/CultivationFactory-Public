"""How an ability is delivered, and which abilities a talent modifies (owner 2026-09-25).

The typed mechanics authority started as flat effect lists.  Two things were wrong with that:

- an ability that says "Make a ranged Cultivation Attack" hit without an attack roll, and a saving
  throw typed beside its damage did not gate the damage (107 and 175 abilities respectively);
- a talent that changes another ability ("When your Water Lash hits, you may spend 1 CP...") was a
  passive the fight skipped, because nothing recorded what it changes or when.

This module gives every mechanic a delivery structure (attack -> on_hit / on_miss, save -> on_fail /
on_success) and a ``modifier`` record.  The structured model pass (tools/type_mechanics_v2.py) is used
when it has read the exact printed text; otherwise a deterministic reading of the text and the v1
model's ``modifies`` / ``trigger`` fields fills in.  Both are recorded with their source.
"""

from __future__ import annotations

import copy
import re
from typing import Any, NamedTuple

MODIFIER_SCHEMA = "TianxiaFoundry.TypedModifier.v1"
_ATTACK_TEXT = re.compile(
    r"\bmake\s+(?:(one|a|an|two|three)\s+)?(?:(melee|ranged|thrown)\s+)?(?:[\w’'-]+\s+){0,3}?attack(?:s| rolls?)?\b"
    r"|\b(?:melee|ranged)\s+cultivation\s+attack\b|\bcultivation\s+attack\b", re.I)
_COUNT = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3}
_TARGET_HARM = {"damage", "extra_damage", "condition", "forced_movement", "reaction_denied", "save", "half_damage"}
_HALF_TEXT = re.compile(r"\bhalf (?:as much )?(?:the )?damage\b|\bhalf damage\b", re.I)
_OPTIONAL_TEXT = re.compile(r"\byou (?:may|can|can choose to)\b|\bchoose to\b", re.I)
_EXTRA_CP = re.compile(r"\b(?:spend|pay|costs?)\s+(?:an additional\s+|an extra\s+|additional\s+|extra\s+)?(\d+)\s*(?:more\s+)?(?:CP|cultivation points?)\b", re.I)
# "you may spend 1 CP, 1 Stamina, or expend Martial Focus" / "Cost: 3 CP or expend Martial Focus" / "... or expend Martial Focus and 1 CP/Stamina":
# a choice of how to pay, not a price of all of them (see modifier_cost_alternatives).  "Spear Resource" is what the Spear talents print for
# the CP their Path pool pays: the reviewed authority types "Cost: 3 Spear Resource" as ``cp 3`` (Dragon-Spear Charge, Spear Guard).
_PAY_UNIT = r"(?:CP|Stamina|Qi|Resonance|Spear Resource)"
_PAY_RESOURCE = {"cp": "cp", "spear resource": "cp", "stamina": "stamina", "qi": "qi", "resonance": "resonance"}
_PAY_ALTERNATIVES = re.compile(
    rf"\b(?:spend|pay|cost:)\s+((?:\d+\s*{_PAY_UNIT}\s*(?:,\s*or\s+|,\s*|\s+or\s+))+)expend\s+(?:your\s+)?martial focus"
    rf"(?:\s+and\s+(\d+)\s*({_PAY_UNIT}(?:/{_PAY_UNIT})*))?", re.I)
# "you may spend 1 Stamina or 1 CP" / "Cost: 2 CP or 2 Stamina" / "Cost: +1 Stamina or +1 CP when ..." / "spend 5 CP or Stamina": the same choice
# with no Martial Focus in it (a later "or" naming a pool this reads no further is left to the flags: _PAY_MORE).
_PAY_CHOICE = re.compile(
    rf"\b(?:spend|pay|cost:)\s+\+?(\d+)\s*({_PAY_UNIT})((?:\s*(?:,\s*or\s+|,\s*|\s+or\s+)\+?(?:\d+\s*)?{_PAY_UNIT})+)", re.I)
_PAY_MORE = re.compile(r"\s*(?:,\s*or\s+|,\s*|or\s+)\+?\d+\s*[A-Za-z]", re.I)
_ONCE_TURN = re.compile(r"\bonce (?:per|each) turn\b", re.I)
_ONCE_ROUND = re.compile(r"\bonce (?:per|each) round\b", re.I)


def _harms_target(effect: dict[str, Any]) -> bool:
    return isinstance(effect, dict) and effect.get("type") in _TARGET_HARM and effect.get("applies_to") not in ("self", "ally")


def nest_saves(effects: list[dict[str, Any]], text: str = "") -> list[dict[str, Any]]:
    """A flat save gates the harmful effects typed after it; half damage goes to the success branch."""
    out: list[dict[str, Any]] = []
    open_save: dict[str, Any] | None = None
    for effect in effects:
        if not isinstance(effect, dict):
            out.append(effect)
            continue
        effect = dict(effect)
        for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
            if isinstance(effect.get(branch), list):
                effect[branch] = nest_saves(effect[branch], text)
        kind = effect.get("type")
        if kind == "save" and not (effect.get("on_fail") or effect.get("on_success")):
            effect = {**effect, "on_fail": [], "on_success": []}
            out.append(effect)
            open_save = effect
            continue
        if kind in ("save", "attack"):
            open_save = None
            out.append(effect)
            continue
        if open_save is not None and kind == "half_damage":
            open_save["on_success"].append(effect)
            continue
        if open_save is not None and _harms_target(effect):
            open_save["on_fail"].append(effect)
            continue
        out.append(effect)
    for effect in out:
        if isinstance(effect, dict) and effect.get("type") == "save" and effect.get("on_fail") and not effect.get("on_success") and _HALF_TEXT.search(text or ""):
            if any(row.get("type") in ("damage", "extra_damage") for row in effect["on_fail"]):
                effect["on_success"] = [{"type": "half_damage", "evidence": _HALF_TEXT.search(text).group(0), "origin": "structure"}]
    return out


def wrap_attack(effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """An ability whose text makes an attack rolls to hit: its harmful effects move to on_hit."""
    if any(isinstance(effect, dict) and effect.get("type") == "attack" for effect in effects):
        return effects
    match = _ATTACK_TEXT.search(text or "")
    harmful = [effect for effect in effects if _harms_target(effect)]
    if not match or not harmful:
        return effects
    count = _COUNT.get((match.group(1) or "a").lower(), 1)
    kind = (match.group(2) or ("ranged" if re.search(r"\branged\b", text, re.I) else "melee")).lower()
    attack = {"type": "attack", "attack_kind": f"cultivation_{kind}", "count": count, "on_hit": harmful, "on_miss": [],
              "evidence": match.group(0), "origin": "structure"}
    rest = [effect for effect in effects if not _harms_target(effect)]
    return [attack, *rest]


def normalize_dice(effects: list[Any]) -> list[Any]:
    """Dice written as text ("1d8", "PBd6") become the parser's dice objects everywhere in the tree."""
    for effect in effects or []:
        if isinstance(effect, dict):
            if isinstance(effect.get("dice"), str):
                effect["dice"] = _dice_dict(effect["dice"])
                if effect["dice"] in ("", None):
                    effect.pop("dice", None)
            for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
                normalize_dice(effect.get(branch) or [])
            if effect.get("type") == "save":
                _restore_failed_save_damage(effect)
    return effects


def _restore_failed_save_damage(save: dict[str, Any]) -> None:
    """A save whose "half damage" success row carries the dice while its failure deals no damage (the model's
    shorthand for "6d6 fire damage, half on a success"): the failure deals the full roll (owner 2026-09-26
    merge review: Explosive Pill's Flame Pill dealt nothing on a failed save)."""
    fail = save.get("on_fail") or []
    if any(isinstance(row, dict) and row.get("type") in ("damage", "extra_damage") for row in fail):
        return
    carrier = next((row for row in save.get("on_success") or [] if isinstance(row, dict) and row.get("type") == "half_damage"
                    and (isinstance(row.get("dice"), dict) or str(row.get("formula") or "none") != "none")), None)
    if carrier is not None:
        save["on_fail"] = [{**carrier, "type": "damage"}, *fail]


def structure(effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Deterministic delivery structure for effects typed flat."""
    return dedupe(normalize_dice(nest_saves(wrap_attack(copy.deepcopy(effects), text), text)))


def _dice_dict(value: Any) -> Any:
    """"2d6" -> {"count": 2, "sides": 6}; "PBd6" -> count from the Proficiency Bonus (as the parser writes it)."""
    if not isinstance(value, str) or not value:
        return value
    match = re.fullmatch(r"\s*(\d+|PB)d(\d+)\s*", value, re.I)
    if not match:
        return value
    if match.group(1).upper() == "PB":
        return {"count": None, "count_formula": "pb", "sides": int(match.group(2)), "bonus": None, "bonus_formula": None}
    return {"count": int(match.group(1)), "count_formula": None, "sides": int(match.group(2)), "bonus": None, "bonus_formula": None}


def _normalize(effects: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    out = []
    for effect in effects or []:
        row = {key: value for key, value in effect.items() if key != "rejected"}
        row["dice"] = _dice_dict(row.get("dice"))
        if row.get("dice") in ("", None):
            row.pop("dice", None)
        row["origin"] = origin
        out.append(row)
    return out


def _damage_rows(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for effect in effects or []:
        if not isinstance(effect, dict):
            continue
        if effect.get("type") in ("damage", "extra_damage") and (effect.get("dice") or effect.get("weapon_damage") or effect.get("flat") or effect.get("formula") not in (None, "none")):
            rows.append(effect)
        for branch in ("on_hit", "on_fail"):
            rows += _damage_rows(effect.get(branch) or [])
    return rows


def _all(effects: list[Any]):
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
                yield from _all(effect.get(branch) or [])


def _signature(effect: dict[str, Any]) -> tuple:
    return (effect.get("type"), str(effect.get("condition") or "").lower())


def from_v2(result: dict[str, Any], prior_effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """The effect tree the structured pass read, plus what the deterministic parser found that the model
    missed (placed by delivery), and damage the model could not ground (CL and Realm tables)."""
    tree = _from_v2(result, prior_effects, text)
    if not any(True for _ in _all(tree)) and any(True for _ in _all(prior_effects)):
        # The structured pass grounded nothing here: keep the earlier typing, structured.
        return structure(prior_effects, text)
    seen = {_signature(effect) for effect in _all(tree)}
    has_damage = any(effect.get("type") in ("damage", "extra_damage") for effect in _all(tree))
    missing = [dict(effect) for effect in _all(prior_effects)
               if effect.get("origin") in ("parser", "model", "reviewed", "model_v2") and effect.get("type") not in ("attack", "save", "half_damage")
               and not (effect.get("type") in ("damage", "extra_damage") and has_damage)
               and _signature(effect) not in seen]
    if not missing:
        return tree
    for effect in missing:
        effect = {key: value for key, value in effect.items() if key not in ("on_hit", "on_miss", "on_fail", "on_success")}
        if _signature(effect) in seen:
            continue  # the earlier typing often states one effect several times (Wind Lash: five pushes)
        seen.add(_signature(effect))
        head = tree[0] if tree and isinstance(tree[0], dict) else None
        if head and head.get("type") == "attack" and _harms_target(effect):
            head.setdefault("on_hit", []).append(effect)
        elif head and head.get("type") == "save" and _harms_target(effect):
            head.setdefault("on_fail", []).append(effect)
        else:
            tree.append(effect)
    return dedupe(normalize_dice(tree))


# Buffs the parser types without "applies_to" land on the user (combat/typed_executor.py _default_subject).
_SELF_BY_DEFAULT = {"ac_bonus", "temp_hp", "healing", "resistance", "immunity", "speed", "advantage"}


def _key(effect: dict[str, Any]) -> tuple:
    dice = effect.get("dice") if isinstance(effect.get("dice"), dict) else {}
    kind = "reaction_denied" if effect.get("type") == "reaction_denied" or effect.get("condition") == "reaction_denied" else effect.get("type")
    # distance_ft is usually a number, but block_movement's "speed" sentinel (combat/typed_executor.py:
    # "Dash grants movement equal to your current Speed") is a string; pre-existing bug fixed in passing
    # (owner 2026-09-26, found rebuilding the authority): int() must not crash the whole build over it.
    distance = effect.get("distance_ft")
    distance_key = int(distance) if isinstance(distance, (int, float)) else str(distance or 0)
    return (kind, str(effect.get("condition") or "").lower() if kind != "reaction_denied" else "", str(effect.get("ability") or "").lower(),
            effect.get("applies_to") or ("self" if kind in _SELF_BY_DEFAULT else "target"), distance_key, dice.get("count"), dice.get("sides"),
            # the parser writes a fixed number as "amount", the models as "flat" (Domain Armament's +2 AC twice)
            str(effect.get("formula") or "none"), str(effect.get("flat") or effect.get("amount") or 0), tuple(effect.get("damage_types") or ()),
            str(effect.get("mark") or "").lower())


def dedupe(effects: list[Any]) -> list[Any]:
    """One effect stated twice (by the parser and a model, or twice by a model) runs once (owner 2026-09-26
    tournament check: Wind Lash pushed its target five times).  Branches are de-duplicated separately."""
    out, seen = [], set()
    for effect in effects or []:
        if not isinstance(effect, dict):
            out.append(effect)
            continue
        effect = dict(effect)
        for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
            if isinstance(effect.get(branch), list):
                effect[branch] = dedupe(effect[branch])
        if effect.get("type") in ("attack", "save"):
            out.append(effect)
            continue
        key = _key(effect)
        if key in seen:
            continue
        seen.add(key)
        out.append(effect)
    return [effect for effect in out if not _restated(effect, out)]


def _evidence(effect: dict[str, Any]) -> str:
    return " ".join(str(effect.get("evidence") or "").replace("`", "").lower().split())


def _restated(effect: Any, effects: list[Any]) -> bool:
    """A parser effect whose printed phrase a model effect of the same type and number quotes in full, with
    its qualifiers (owner 2026-09-26 tournament: Domain Armament's "+2 AC" ran as an always-on self bonus
    beside the model's "+2 AC against ranged attack rolls" for a protected creature)."""
    if not isinstance(effect, dict) or effect.get("origin") != "parser" or effect.get("type") in ("attack", "save"):
        return False
    phrase, number = _evidence(effect), str(effect.get("flat") or effect.get("amount") or 0)
    return bool(phrase) and any(
        isinstance(other, dict) and other.get("origin") in ("model", "model_v2", "reviewed") and other.get("type") == effect.get("type")
        and str(other.get("flat") or other.get("amount") or 0) == number and phrase in _evidence(other) and phrase != _evidence(other)
        for other in effects)


# ------------------------------------------------------------------ parser rows a typed row already states
# The parser (typed_mechanics.py) reads what it can of a line and states no subject and no duration; the models then type the same
# line with both.  ``from_v2`` re-adds a parser row whenever the model has not typed that (type, condition) -- but a model row says
# condition "none" where the parser says nothing, so the two never matched -- and ``dedupe`` compares whole keys ("flat" against
# "amount", a subject the parser never states).  The parser's copy outlived the model's row, and it has no duration: Furnace Step's
# +10 Speed ran on every cast and never ended, Joint Seal's -10 Speed stayed on its target for the fight (fight audit 2026-09-29,
# "parser duplicate rows").  ``drop_restated_parser_rows`` runs once at the end of the build, over whatever the earlier passes left.
_TYPED_ORIGINS = ("model", "model_v2", "model_options", "reviewed")
_BRANCHES = ("on_hit", "on_miss", "on_fail", "on_success")
# "You and allies of your choice gain ...": the caster is one of the recipients, so a parser row that lands on the caster may be the
# caster's share rather than a copy of the model's ally row.
_CASTER_TOO = re.compile(r"\byou (?:and|or) (?!(?:may|can|must|learn|choose|gain|take|use|spend)\b)"
                         r"|\b(?:and|or) you\b(?! (?:may|can|must|learn|choose|spend|take|use)\b)|\b(?:and|or|including|even) yourself\b"
                         r"|\bincluding you\b")
_SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)]*$")


class _Text(NamedTuple):
    lines: list[str]  # every line, bullet and ";"-separated clause of the rules text, normalised
    contexts: list[str]  # every line together with the lead-in above it ("you and allies gain the following:"), normalised


def _read(text: str) -> _Text:
    """The rules text as lines, and as lines each read with the lead-in that names its recipients.  A benefit listed on a line of its
    own ("Resistance to Necrotic damage;") is a bullet of the lead-in above it, the nearest line that ends with a colon and belongs
    to the same sentence (a sentence runs to the next line that ends with a full stop)."""
    lines, contexts, lead = [], [], ""
    for part in re.split(r"[\n\u2022]|(?<=[.!?])\s+(?=[A-Z`*])", text or ""):
        words = _words(part)
        if words:
            contexts.append(f"{lead} {words}".strip())
            lines += [line for line in (_words(clause) for clause in part.split(";")) if line]
        if part.strip().endswith(":"):
            lead = words
        elif _SENTENCE_END.search(part.strip()):
            lead = ""
    return _Text(lines, contexts)


# What ``_same_value`` (or the subject and condition checks) already compares; any other attribute of the parser row (repeat_save,
# within_range, dice_by_cl, type_choice ...) must be on the typed row too, or the parser row says something the typed row does not.
_COMPARED = frozenset({"type", "origin", "evidence", "applies_to", "condition", "amount", "flat", "on", "dice", "damage_types", "distance_ft",
                       "direction", "halved", "formula", "ability", "dc", "mode", "duration", "expires_on", *_BRANCHES})
# A movement the text says provokes nothing: the parser reads "without provoking" itself, so the flag moves to the typed movement row.
_HANDED_ON = ("no_opportunity_attacks",)


def _words(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _number(effect: dict[str, Any]) -> Any:
    for key in ("flat", "amount"):  # the models write a fixed number as "flat", the parser as "amount"
        value = effect.get(key)
        if value not in (None, "", 0, "0"):
            try:
                return int(value)
            except (TypeError, ValueError):
                return str(value)
    return 0


def _kind(effect: dict[str, Any]) -> tuple:
    """What an effect does: its type, the condition it imposes, and reaction_denied however it is written."""
    if effect.get("type") == "reaction_denied" or effect.get("condition") == "reaction_denied":
        return ("reaction_denied",)
    if effect.get("type") == "condition":
        return ("condition", str(effect.get("condition") or "").lower())
    return (effect.get("type"),)


def _when(effect: dict[str, Any]) -> str:
    condition = str(effect.get("condition") or "").lower()
    return "" if condition == "none" else condition


def _subject(effect: dict[str, Any]) -> str:
    """Whom an effect lands on, as combat/typed_executor.py's ``_default_subject`` reads it."""
    applies = effect.get("applies_to")
    if applies:
        return "target" if applies in ("target", "enemies_in_area", "creatures_in_area", "attacker") else str(applies)
    number = _number(effect)
    if effect.get("type") == "speed" and ((isinstance(number, int) and number < 0) or effect.get("halved")):
        return "target"  # a Speed penalty is harmful: it lands on the enemy
    return "self" if effect.get("type") in _SELF_BY_DEFAULT or effect.get("type") == "movement" else "target"


def _same_value(row: dict[str, Any], other: dict[str, Any]) -> bool:
    """The same effect by its numbers, whatever else the two rows say.  Only the types whose values are understood compare equal."""
    kind = row.get("type")
    if kind == "save":
        return bool(row.get("ability")) and str(row.get("ability")).lower() == str(other.get("ability") or "").lower()
    if kind == "speed":
        return _number(row) == _number(other) and bool(row.get("halved")) == bool(other.get("halved"))
    if kind == "ac_bonus":
        return _number(row) == _number(other)
    if kind in ("resistance", "immunity"):
        mine, theirs = set(row.get("damage_types") or ()), set(other.get("damage_types") or ())
        return mine <= theirs and bool(mine) == bool(theirs)
    if kind in ("advantage", "disadvantage"):
        mine, theirs = _words(row.get("on")), _words(other.get("on"))
        return mine == theirs or bool(mine and theirs and (mine in theirs or theirs in mine))
    if kind == "condition" or _kind(row) == ("reaction_denied",):
        return True
    if kind == "movement":
        return row.get("distance_ft") == other.get("distance_ft") and (row.get("mode") or "move") == (other.get("mode") or "move")
    if kind == "forced_movement":  # a push is "away" unless the row says "toward" (typed_executor.block_forced_movement)
        return row.get("distance_ft") == other.get("distance_ft") and (row.get("direction") or "away") == (other.get("direction") or "away")
    if kind in ("damage", "extra_damage", "healing", "temp_hp"):
        # Temporary HP "equal to PB + your key ability modifier" is one parser row (a text formula) but two model rows (pb, then
        # key_ability_modifier), and a Temporary HP grant takes the larger, not the sum: those stay.
        return (row.get("dice") == other.get("dice") and set(row.get("damage_types") or ()) == set(other.get("damage_types") or ())
                and str(row.get("formula") or "none") == str(other.get("formula") or "none") and _number(row) == _number(other))
    return False


class _Node(NamedTuple):
    row: dict[str, Any]
    context: tuple  # ((branch, what it is nested in), ...): a row in a Dexterity save's on_fail is (("on_fail", "dex"),)
    origin: Any  # the row's own origin, else its parent's (the parser stamps only the rows it puts at the top)
    inside: bool  # somewhere inside a parser save, which stands or falls with everything it holds
    parents: tuple  # id() of every row it is nested in


def _nodes(effects: list[Any], context: tuple = (), origin: Any = None, inside: bool = False, parents: tuple = ()):
    """Every row of an effect tree, a parent before its children."""
    for effect in effects or []:
        if isinstance(effect, dict):
            own = effect.get("origin") or origin
            yield _Node(effect, context, own, inside, parents)
            what = str(effect.get("ability") or "").lower() if effect.get("type") == "save" else str(effect.get("type") or "")
            for branch in _BRANCHES:
                yield from _nodes(effect.get(branch), (*context, (branch, what)), own, inside or (effect.get("type") == "save" and own == "parser"),
                                  (*parents, id(effect)))


def _carries_more(row: dict[str, Any], other: dict[str, Any]) -> bool:
    """Whether the parser row says something the typed row does not: an attribute ``_same_value`` and the subject and condition checks
    do not compare (repeat_save, within_range, dice_by_cl, type_choice ...) that the typed row lacks."""
    return any(key not in _COMPARED and value not in (None, False, 0, "", [], {}, "none") and other.get(key) != value
               and not (key in _HANDED_ON and other.get("type") == "movement") for key, value in row.items())


def _hand_on(row: dict[str, Any], cover: dict[str, Any]) -> None:
    for flag in _HANDED_ON:
        if row.get(flag) and cover.get("type") == "movement" and not cover.get(flag):
            cover[flag] = row[flag]


def _covering_row(row: dict[str, Any], context: tuple, typed: list[tuple[dict[str, Any], tuple]], words: _Text) -> dict[str, Any] | None:
    """The typed row (model or reviewed) that already states this parser row, or None: the same effect by type and numbers, on the same
    printed line (its quote contains or is contained in the other's, or both sit in one sentence or bullet), for the same recipient,
    in the same branch (a parser row that sits outside every branch may be covered by a row inside one), and carrying nothing the
    typed row lacks."""
    kind, phrase = _kind(row), _words(row.get("evidence"))
    if not phrase:
        return None
    for other, where in typed:
        if _kind(other) != kind or (context and where != context):
            continue
        theirs = _words(other.get("evidence"))
        if not theirs or not (phrase in theirs or theirs in phrase or any(phrase in line and theirs in line for line in words.lines)):
            continue
        if row.get("type") != "condition" and _when(row) != _when(other):
            continue
        if not _same_value(row, other):
            continue
        if _subject(row) != _subject(other) and _CASTER_TOO.search(
                " ".join(context for context in words.contexts if phrase in context or theirs in context) or f"{phrase} {theirs}"):
            continue
        if not _carries_more(row, other):
            return other
    return None


def _restated_save(node: _Node, nodes: list[_Node], typed: list[tuple[dict[str, Any], tuple]], words: _Text) -> dict[int, dict[str, Any]]:
    """{id(row): covering row} for a parser save and everything in it when a typed save of the same ability, in the same place, holds
    all of it -- a save rolls again for each copy, so a parser save beside the model's runs its damage and conditions twice.  {} when
    the parser save holds something the typed one does not (that stays, whole: its save is the only thing that gates it) or when no
    typed save states it (a bare parser save is dropped only where a typed save of that ability exists)."""
    save, ability = node.row, str(node.row.get("ability") or "").lower()
    below = [inner for inner in nodes if id(save) in inner.parents]
    for other, where in typed:
        if other.get("type") != "save" or where != node.context or str(other.get("ability") or "").lower() != ability or _carries_more(save, other):
            continue
        held = [(inner.row, inner.context) for inner in nodes if id(other) in inner.parents and inner.origin in _TYPED_ORIGINS]
        found: dict[int, dict[str, Any]] = {id(save): other}
        for inner in below:
            # "takes half damage" is the save's own flag: a typed save that halves in the same branch states it
            cover = next((row for row, place in held if row.get("type") == "half_damage" and place == inner.context), None) \
                if inner.row.get("type") == "half_damage" else _covering_row(inner.row, inner.context, held, words)
            if cover is None:
                break
            found[id(inner.row)] = cover
        else:
            for inner in below:
                _hand_on(inner.row, found[id(inner.row)])
            return found
    return {}


def _restated_rows(effects: list[Any], words: _Text) -> dict[int, dict[str, Any]]:
    """{id(parser row): the typed row that states it} for one effect tree (one delivery surface of a mechanic)."""
    nodes = list(_nodes(effects))
    typed = [(node.row, node.context) for node in nodes if node.origin in _TYPED_ORIGINS and not node.inside]
    found: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if node.row.get("type") == "save" and node.origin == "parser" and not node.inside:
            found.update(_restated_save(node, nodes, typed, words))
    for node in nodes:
        row = node.row
        if node.inside or node.origin != "parser" or row.get("type") in ("attack", "half_damage", "save"):
            continue  # the attack, and a save with its half-damage line, are the delivery's scaffolding, never a copy of an effect
        cover = _covering_row(row, node.context, typed, words)
        if cover is not None:
            _hand_on(row, cover)
            found[id(row)] = cover
    return found


def _without(effects: list[Any], gone: dict[int, Any]) -> list[Any]:
    out = []
    for effect in effects:
        if isinstance(effect, dict) and id(effect) in gone:
            continue
        if isinstance(effect, dict):
            effect = {**effect, **{branch: _without(effect[branch], gone) for branch in _BRANCHES if isinstance(effect.get(branch), list)}}
        out.append(effect)
    return out


def drop_restated_parser_rows(mechanic: dict[str, Any], text: str = "") -> list[dict[str, Any]]:
    """Removes the parser rows of a mechanic that a model or reviewed row of the same delivery surface (effects, one option, the
    modifier, one modifier option) already states, and returns them.  A parser row that is the only typing of its line stays, as
    does one whose type, numbers, recipient or branch the typed row does not share; a reviewed_final mechanic is what its reviewer
    wrote and is never touched."""
    if mechanic.get("typing_status") == "reviewed_final":
        return []
    words = _read(text)
    modifier = mechanic.get("modifier") if isinstance(mechanic.get("modifier"), dict) else {}
    surfaces = [mechanic, *(o for o in mechanic.get("options") or [] if isinstance(o, dict)), modifier,
                *(o for o in modifier.get("options") or [] if isinstance(o, dict))]
    dropped: list[dict[str, Any]] = []
    for surface in surfaces:
        effects = surface.get("effects")
        found = _restated_rows(effects, words) if isinstance(effects, list) else {}
        if found:
            dropped += [node.row for node in _nodes(effects) if id(node.row) in found]
            surface["effects"] = _without(effects, found)
    return dropped


# ------------------------------------------------------------------ which way a push or pull moves its target
# A forced_movement row's ``direction`` is "away" or "toward" the caster, "away_center" or "toward_center" the centre of the area the
# effect fills, or "choice"; combat/typed_executor.block_forced_movement moves a row that has none away from the caster.  The models'
# row schema has no direction, so 567 of the authority's 573 forced_movement rows had none and every "pull" ran as a push away from the
# caster (hunt 3, bug 1: Chain Counter, Chain Lash, Wind Lash, Cyclone Prison, Collapsing Gap, Gate of the Inner Sea).  The printed
# words say which way: the row's own quote when it names a direction, else the "toward" / "away from" phrase that follows the same push
# or pull verb in the ability's text.  Words that do not settle it -- a row that reduces or ignores forced movement, "push or pull",
# "toward the damaged creature", "perpendicular to the line" -- leave the row as it was; the build lists those rows.
_FM_ADJUSTS = re.compile(r"\b(?:increase[sd]?|reduc(?:e[sd]?|tion)|ignor(?:e[sd]?|ing)|redirect|add \d+ feet to|cannot move|additional movement)\b")
_FM_STARTS = re.compile(r"^(?:you may )?(?:push|pull)\w*\b")  # "pull it 10 feet ... reduce": the row is the move itself, not a change to one
_FM_PUSH = re.compile(r"\bpush(?:es|ed)?\b")
_FM_PULL = re.compile(r"\bpull(?:s|ed)?\b")
_FM_MOVE = re.compile(r"\b(?:push(?:es|ed)?|pull(?:s|ed)?|move[sd]?|moving|drag(?:s|ged)?|throw|launch)\b")
_FM_CENTRE = r"(?:(?:the|that|this) )?(?:[a-z0-9]+ ){0,4}?(?:center|centre|origin)\b"  # "the center", "the blast's point of origin"
_FM_TOWARD_CENTRE, _FM_AWAY_CENTRE = re.compile(rf"towards? {_FM_CENTRE}"), re.compile(rf"away from {_FM_CENTRE}")
_FM_TOWARD_YOU, _FM_AWAY_YOU = re.compile(r"towards? (?:you|yourself)\b"), re.compile(r"away from (?:you|yourself)\b")
_FM_PHRASE = re.compile(r"\btowards?\b|\baway from\b")
# A way that is neither toward nor away from anything: the executor has no such move, so the row stays as it was.
_FM_OTHER_WAY = re.compile(r"\b(?:direction|perpendicular|side|sideways|along|upward|downward|vertical\w*|around|through|opposite|back)\b")
_FM_DIRECTION = {("toward", "centre"): "toward_center", ("toward", "you"): "toward", ("away", "centre"): "away_center", ("away", "you"): "away"}


def _fm_phrases(words: str) -> list[tuple[str, str]]:
    """Every "toward ..." and "away from ..." in ``words`` as (kind, anchor): "you" (the caster), "centre" (the centre or origin of
    the area) or "other" (a creature, a wall, a point the phrase only names)."""
    found = []
    for match in _FM_PHRASE.finditer(words):
        rest = words[match.start():]
        toward = rest.startswith("toward")
        centre, you = (_FM_TOWARD_CENTRE, _FM_TOWARD_YOU) if toward else (_FM_AWAY_CENTRE, _FM_AWAY_YOU)
        found.append(("toward" if toward else "away", "centre" if centre.match(rest) else "you" if you.match(rest) else "other"))
    return found


def _fm_attached(verb: re.Pattern, lines: list[str]) -> list[tuple[str, str]]:
    """The toward / away-from phrases that follow a push (or pull) verb in the lines, up to the next movement verb: a phrase after
    another verb of the same sentence ("... and move yourself 20 feet toward it") is that verb's, not this one's."""
    found = []
    for line in lines:
        for match in verb.finditer(line):
            tail = line[match.end():]
            stop = _FM_MOVE.search(tail)
            found += _fm_phrases(tail[:stop.start()] if stop else tail)
    return found


def _fm_decide(found: list[tuple[str, str]]) -> str | None:
    kinds = set(found)
    return _FM_DIRECTION.get(next(iter(kinds))) if len(kinds) == 1 else None


def forced_movement_direction(evidence: str, lines: list[str]) -> tuple[str | None, str]:
    """The direction the printed words give a forced_movement row -- "toward" or "away" (the caster), "toward_center" or
    "away_center" (the area's centre) -- with where they said it: "evidence" (the row's own quote), "line" (after its own push or pull
    verb in the printed line that holds the quote), "whole" (after that verb in another line of the ability), "bare" (a push or a pull
    that names no direction anywhere: away from, or toward, the caster).  None, and why, when the words leave it open.  ``lines`` are
    the ability's normalised lines (``_read(text).lines``)."""
    words = _words(evidence)
    if _FM_ADJUSTS.search(words) and not _FM_STARTS.match(words):
        return None, "modifier"  # "reduce forced movement by 10 feet", "increase the push by 5 feet": a change to a move, not a move
    push, pull = bool(_FM_PUSH.search(words)), bool(_FM_PULL.search(words))
    if push and pull:
        return None, "push-or-pull"
    found = _fm_phrases(words)
    if found:
        direction = _fm_decide(found)
        return direction, "evidence" if direction else "other-anchor"
    if not (push or pull):
        return None, "reposition"  # "move the target 5 feet", "drag", "throw": no push or pull to read a direction from
    if _FM_OTHER_WAY.search(words):
        return None, "other-way"
    verb = _FM_PUSH if push else _FM_PULL
    found, scope = _fm_attached(verb, [line for line in lines if words in line]), "line"
    if not found:
        found, scope = _fm_attached(verb, lines), "whole"
    if found:
        direction = _fm_decide(found)
        return direction, scope if direction else f"mixed-anchors({scope})"
    return ("away" if push else "toward"), "bare"


def _forced_movement_rows(node: Any):
    """Every forced_movement row anywhere in a mechanic: its effects, options and modifier, the branches of a save, a zone's triggers."""
    if isinstance(node, dict):
        if node.get("type") == "forced_movement":
            yield node
        for value in node.values():
            yield from _forced_movement_rows(value)
    elif isinstance(node, list):
        for value in node:
            yield from _forced_movement_rows(value)


def derive_forced_movement_directions(mechanic: dict[str, Any], text: str = "") -> list[tuple[dict[str, Any], str | None, str]]:
    """Gives every undirected forced_movement row of a mechanic the direction its printed words settle (``forced_movement_direction``)
    and returns (row, direction or None, where the words said it or why they did not) for each row it looked at.  A row that already
    has a direction keeps it.  A reviewed_final mechanic is read like any other: its rows have no direction unless the reviewer wrote
    one, and the executor moves an undirected row away from the caster whoever typed it (Chain Counter is reviewed_final)."""
    lines = _read(text).lines
    looked = []
    for row in _forced_movement_rows(mechanic):
        if row.get("direction"):
            continue
        direction, why = forced_movement_direction(str(row.get("evidence") or ""), lines)
        if direction:
            row["direction"] = direction
        looked.append((row, direction, why))
    return looked


# ------------------------------------------------------------------ "reduce forced movement affecting you by 10 feet"
# The model typed it as ``movement`` -- a free move for the character, which the executor grants as movement left this turn (hunt 3,
# bug 7: Chain Armor, Deep Root Stance ...).  The engine reduces a push or pull in one place, the forced_moved / ally_forced_moved
# reaction (combat/typed_reactions.on_forced_movement reads the reaction's forced_movement row); a standing reduction on a stance or
# a passive has no place to run, so it stays what the printed text calls it, a GM line -- unless the same ability already types the
# reduction as that forced_movement row (Gravity Anchor Stance's reaction), when the wrong row is simply dropped.
_REDUCES_FORCED_MOVEMENT = re.compile(r"\b(?:reduc\w+|ignor\w+)\b[^.;:]*\bforced movement\b", re.I)


def _reduces_forced_movement(row: Any, kind: str) -> bool:
    return isinstance(row, dict) and row.get("type") == kind and bool(_REDUCES_FORCED_MOVEMENT.search(str(row.get("evidence") or "")))


def movement_that_reduces_forced_movement(mechanic: dict[str, Any]) -> list[dict[str, Any]]:
    """Takes the ``movement`` rows that only reduce forced movement out of a mechanic's delivery surfaces (effects, one option, the
    modifier, one modifier option), adds each one's printed words to its riders unless the same surface already types the reduction
    as a forced_movement row or the riders already say it, and returns the rows taken out."""
    modifier = mechanic.get("modifier") if isinstance(mechanic.get("modifier"), dict) else {}
    surfaces = [mechanic, *(o for o in mechanic.get("options") or [] if isinstance(o, dict)), modifier,
                *(o for o in modifier.get("options") or [] if isinstance(o, dict))]
    taken: list[dict[str, Any]] = []
    for surface in surfaces:
        effects = surface.get("effects")
        if not isinstance(effects, list):
            continue
        nodes = list(_nodes(effects))
        wrong = {id(node.row): node.row for node in nodes if _reduces_forced_movement(node.row, "movement")}
        if not wrong:
            continue
        typed = any(_reduces_forced_movement(node.row, "forced_movement") for node in nodes)
        surface["effects"] = _without(effects, wrong)
        for row in wrong.values():
            taken.append(row)
            line = " ".join(str(row.get("evidence") or "").split())
            riders = mechanic.setdefault("riders", [])
            if not typed and line and not any(_words(line) in _words(rider) for rider in riders):
                riders.append(line)
    return taken


def _from_v2(result: dict[str, Any], prior_effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    always = _normalize(result.get("effects"), "model_v2")
    delivery = result.get("delivery")
    carried = [copy.deepcopy(row) for row in _damage_rows(prior_effects)]
    if delivery == "attack":
        on_hit = _normalize(result.get("on_hit"), "model_v2")
        if not any(row.get("type") in ("damage", "extra_damage") for row in on_hit) and carried:
            on_hit = [carried[0], *on_hit]
        # A save that only an attack's hit allows sits inside on_hit.
        on_hit = nest_saves(on_hit + _normalize(result.get("on_fail"), "model_v2") if any(
            row.get("type") == "save" for row in on_hit) else on_hit, text)
        attack = {"type": "attack", "attack_kind": f"cultivation_{result.get('attack_kind') or 'ranged'}",
                  "count": int(result.get("attack_count") or 1), "on_hit": on_hit,
                  "on_miss": _normalize(result.get("on_miss"), "model_v2"), "origin": "model_v2"}
        return normalize_dice([attack, *nest_saves(always, text)])
    if delivery == "save":
        on_fail = _normalize(result.get("on_fail"), "model_v2")
        if not any(row.get("type") in ("damage", "extra_damage") for row in on_fail) and carried:
            on_fail = [carried[0], *on_fail]
        on_success = _normalize(result.get("on_success"), "model_v2")
        if result.get("half_on_success") and not any(row.get("type") == "half_damage" for row in on_success):
            on_success.append({"type": "half_damage", "origin": "model_v2"})
        save = {"type": "save", "ability": result.get("save_ability"), "dc": "technique_save_dc",
                "on_fail": nest_saves(on_fail, text), "on_success": on_success, "origin": "model_v2"}
        return normalize_dice([save, *nest_saves([row for row in always if row.get("type") != "save"], text)])
    effects = always + _normalize(result.get("on_hit"), "model_v2") + _normalize(result.get("on_fail"), "model_v2")
    if not any(row.get("type") in ("damage", "extra_damage") for row in _damage_rows(effects)) and carried and delivery == "automatic":
        effects = [carried[0], *effects]
    return structure(effects, text)


# ------------------------------------------------------------------ modifiers
def _when_from_trigger(trigger: str) -> str:
    lowered = (trigger or "").lower()
    if re.search(r"\bmiss(?:es)?\b", lowered):
        return "miss"
    if re.search(r"\bhits?\b|\bdeals? damage\b|\bdamages?\b", lowered):
        return "hit"
    if re.search(r"\bfails?\b[^.]{0,30}\bsav", lowered) or "failed save" in lowered:
        return "failed_save"
    if re.search(r"\bsucceeds?\b", lowered):
        return "success"
    return "use"


def modifier_from_v2(modifier: dict[str, Any], text: str) -> dict[str, Any]:
    out = {"schema": MODIFIER_SCHEMA, "source": "model_v2", **{key: value for key, value in modifier.items() if key != "effects"}}
    out["effects"] = normalize_dice(nest_saves(_normalize(modifier.get("effects"), "model_v2"), text))
    return out


def modifier_options(common_effects: list[dict[str, Any]], option_rows: list[dict[str, Any]], text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A modifier's printed menu (Daemonic Augment: add PB to one damage roll, or Disadvantage on one
    Concentration save, or 5 more feet of movement), from tools/type_options.py --modifiers: (what it adds
    whichever option is chosen, [{"label", "effects"}] per option) -- normalized like ``modifier_from_v2``.
    Fewer than two grounded options gives no options (owner 2026-09-26)."""
    options = [{"label": str(row.get("label") or "").strip(),
                "effects": normalize_dice(nest_saves(_normalize([dict(effect) for effect in row.get("effects") or [] if isinstance(effect, dict)],
                                                                "model_options"), text))}
               for row in option_rows or [] if isinstance(row, dict)]
    options = [option for option in options if option["label"] and option["effects"]]
    common = normalize_dice(nest_saves(_normalize([dict(effect) for effect in common_effects or [] if isinstance(effect, dict)], "model_options"), text))
    return (common, options) if len(options) >= 2 else (common, [])


def modifier_from_text(name: str, text: str, modifies: str | None, trigger: str | None,
                       effects: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A modifier record read deterministically from the v1 typing's ``modifies``/``trigger`` and the text."""
    targets = [part.strip() for part in re.split(r",| or | and |/", modifies or "") if part.strip()]
    targets = [target for target in targets if target.lower() != name.lower() and target.lower() in (text or "").lower()]
    if not targets:
        return None
    cp = _EXTRA_CP.search(text or "")
    out: dict[str, Any] = {
        "schema": MODIFIER_SCHEMA, "source": "text_v1", "targets": targets, "scope": "named",
        "when": _when_from_trigger(trigger or text[:200]), "optional": bool(_OPTIONAL_TEXT.search(text or "")),
        "limit": "once_per_turn" if _ONCE_TURN.search(text or "") else "once_per_round" if _ONCE_ROUND.search(text or "") else "none",
        "group": "", "precondition": "",
        "effects": normalize_dice(nest_saves([{**row, "origin": row.get("origin") or "model"} for row in copy.deepcopy(effects)], text)),
    }
    if cp:
        out["extra_cp"] = int(cp.group(1))
    if re.search(r"\bexpend (?:your )?martial focus\b", text or "", re.I):
        out["martial_focus"] = True
    alternatives = modifier_cost_alternatives(text, out)
    if alternatives:
        out["cost"] = alternatives
    return out


def modifier_cost_alternatives(text: str, modifier: dict[str, Any] | None) -> list[list[dict[str, Any]]] | None:
    """How a modifier printed "you may spend 1 CP, 1 Stamina, or expend Martial Focus" is paid, in the shape of a mechanic's
    ``cost``: a list of alternatives, each a list of parts (the user pays ONE of them; sw-athletics report 2026-09-28,
    "Modifier cost alternatives").  The modifier record only keeps two independent flags for this, ``extra_cp`` and
    ``martial_focus``, and the compiler used to charge both -- Hook the Giant's Knee ("spend 2 CP, 2 Stamina, or expend
    Martial Focus and 1 CP/Stamina") cost Stamina 2 *and* Martial Focus.  A printed "and" (Phasic Shot: "expend Martial Focus
    and spend 2 CP") really is both, and returns None, as does a text whose first CP amount disagrees with ``extra_cp`` (left
    as the flags say).  Three shapes are read:

    * both flags: "spend 1 CP, 1 Stamina, or expend Martial Focus" (the alternatives, then Martial Focus);
    * ``martial_focus`` alone: "Cost: 2 Spear Resource or expend Martial Focus" (Army-Breaking Thrust, Pinning Strike), whose CP
      way the flags had dropped -- "Spear Resource" is CP, as the reviewed authority already types it;
    * ``extra_cp`` alone: "spend 1 Stamina or 1 CP" / "Cost: 2 CP or 2 Stamina" / "spend 5 CP or Stamina" (Body Resonance
      Strike, Nullifying Strike; fight-audit 2026-09-29, action cost alternatives), whose Stamina way the one flag cannot say."""
    if not modifier or not (modifier.get("extra_cp") or modifier.get("martial_focus")):
        return None
    text = text or ""

    def part(unit: str, amount: int) -> dict[str, Any]:
        return {"resource": _PAY_RESOURCE[unit.lower()], "amount": amount, "amount_formula": None}

    if modifier.get("martial_focus"):
        match = _PAY_ALTERNATIVES.search(text)
        if not match:
            return None
        alternatives = [[part(unit, int(amount))] for amount, unit in re.findall(rf"(\d+)\s*({_PAY_UNIT})", match.group(1), re.I)]
        focus = {"resource": "martial_focus", "amount": 1}
        if match.group(2):  # "expend Martial Focus and 1 CP/Stamina": Martial Focus plus one of those
            alternatives += [[dict(focus), part(unit, int(match.group(2)))] for unit in match.group(3).split("/")]
        else:
            alternatives.append([focus])
    else:
        match = _PAY_CHOICE.search(text)
        if not match or _PAY_MORE.match(text, match.end()):
            return None
        amount = int(match.group(1))
        alternatives = [[part(match.group(2), amount)]]
        for given, unit in re.findall(rf"\+?(?:(\d+)\s*)?({_PAY_UNIT})", match.group(3), re.I):
            alternatives.append([part(unit, int(given) if given else amount)])
    cp = next((alternative[0]["amount"] for alternative in alternatives if len(alternative) == 1 and alternative[0]["resource"] == "cp"), None)
    if not modifier.get("extra_cp"):
        return alternatives if cp is not None else None  # a Martial-Focus-only modifier printing a CP way it was typed without
    return alternatives if cp == modifier["extra_cp"] else None


def modifier_adds_something(modifier: dict[str, Any] | None) -> bool:
    if not modifier:
        return False
    return bool(modifier.get("effects") or modifier.get("damage_type") or modifier.get("add_range_ft") or modifier.get("range_ft_by_cl")
                or modifier.get("area_size_ft") or modifier.get("add_area_ft") or modifier.get("damage_die_steps")
                or modifier.get("extra_attacks"))


# ------------------------------------------------------------------ choose-one menu detection (owner 2026-09-26)
# "Choose one" is also this ruleset's ordinary idiom for picking a TARGET ("Choose one creature...",
# "choose one visible creature or object...") -- not the printed menu of alternative effects tonight's
# tournament found running all at once. A menu nested inside one save outcome ("Failed Save: Choose
# one: push the target 10 feet; knock it Prone; ...") is real, but this pass's flat common/options split
# cannot represent it (the options would run whichever way the save went); left for a later pass.
_CHOOSE_ONE_TARGET_RE = re.compile(
    r"^\s*(?:willing\s+|unwilling\s+|hostile\s+|visible\s+|mortal\s+|legal\s+|valid\s+|qualifying\s+|"
    r"known\s+|existing\s+|other\s+|ordinary\s+|living\s+|dead\s+)*"
    r"(?:creatures?|allies|ally|enem(?:y|ies)|targets?|objects?|points?|weapons?|structures?|cultivators?)\b", re.I)
_CHOOSE_ONE_BRANCH_RE = re.compile(r"\b(?:failure|failed save|success|successful save|on a (?:hit|miss|failure|success))\b\s*:\s*\Z", re.I)


def has_choose_one_menu(text: str) -> bool:
    """True when the printed text has at least one "Choose one:" / "choose one of the following" /
    "one of the following" that introduces the ability's own top-level menu of alternative effects --
    not a target pick, and not a menu inside one save outcome only."""
    if not text:
        return False
    for match in re.finditer(r"\bchoose one\b|\bone of the following\b", text, re.I):
        if match.group(0).lower() == "choose one" and _CHOOSE_ONE_TARGET_RE.match(text[match.end():match.end() + 40]):
            continue
        if _CHOOSE_ONE_BRANCH_RE.search(text[max(0, match.start() - 40):match.start()]):
            continue
        return True
    return False


# ------------------------------------------------------------------ a menu inside one save outcome (fight audit 2026-09-28)
# "Failed Save: Choose one: ..." (Court of the Ninth Grave, Dream Mirror, Fortress-Breaker's Denial, ...) is the ability's own
# menu, but ``has_choose_one_menu`` leaves it out (above), so no split ever ran on it: the typing put every bullet in the
# save's on_fail and a failed save applied all of them together (H1-11: Speed -10 and "cannot take Reactions" at once).
# ``branch_menu`` finds that one menu and where it sits; ``split_branch_menu`` turns it into one whole tree per option, each
# holding only its own bullet where the menu was and everything else the ability does unchanged.
_BRANCH_HEAD_RE = re.compile(r"\b(failure|failed save|success|successful save|on a (?:hit|miss|failure|success))\b\s*:\s*\Z", re.I)
_BRANCH_OF = {"failure": "on_fail", "failed save": "on_fail", "on a failure": "on_fail", "success": "on_success",
              "successful save": "on_success", "on a success": "on_success", "on a hit": "on_hit", "on a miss": "on_miss",
              "hit": "on_hit", "miss": "on_miss"}
_NEXT_BRANCH_RE = re.compile(r"(?:^|\n)[ \t]*(failed save|failure|successful save|success|on a (?:hit|miss)|hit|miss)[ \t]*:", re.I)
_MORE_THAN_ONE_RE = re.compile(r"\bchoose (?:two|three|four|five|a number|up to|any number|\w+ different)\b", re.I)


def branch_menu(text: str) -> dict[str, Any] | None:
    """The ability's one "Choose one" menu when it is printed inside a save or attack outcome, as
    ``{"branch": "on_fail" | "on_success" | "on_hit" | "on_miss", "start", "end", "text"}`` -- ``text`` running from the branch
    label ("Failed Save:") to the next branch label or the end of the printed text -- else None. Left alone: a text with any other
    "choose one" that is not a target pick (two menus), or with "choose two/three ..." (a menu of combinations), and every
    top-level menu (``has_choose_one_menu`` and ``build_options`` own those)."""
    if not text or _MORE_THAN_ONE_RE.search(text):
        return None
    menus = [match for match in re.finditer(r"\bchoose one\b|\bone of the following\b", text, re.I)
             if not (match.group(0).lower() == "choose one" and _CHOOSE_ONE_TARGET_RE.match(text[match.end():match.end() + 40]))]
    if len(menus) != 1:
        return None
    match = menus[0]
    lead = text[max(0, match.start() - 40):match.start()]
    head = _BRANCH_HEAD_RE.search(lead)
    if head is None:
        return None
    start = match.start() - len(lead) + head.start()
    following = _NEXT_BRANCH_RE.search(text, match.end())
    end = following.start() if following else len(text)
    after = None
    if following:  # the outcome printed next, with the words it is printed in
        later = _NEXT_BRANCH_RE.search(text, following.end())
        after = {"branch": _BRANCH_OF[" ".join(following.group(1).lower().split())], "text": text[following.start():later.start() if later else len(text)]}
    return {"branch": _BRANCH_OF[" ".join(head.group(1).lower().split())], "head": " ".join(head.group(1).split()),
            "start": start, "end": end, "text": text[start:end], "after": after}


def _plain(text: Any) -> str:
    """Printed words compared without case, quote style, dashes, markup or spacing."""
    text = str(text or "")
    for old, new in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("`", ""), ("*", "")):
        text = text.replace(old, new)
    return " ".join(text.lower().split()).strip(" .;:,-")


_LABELLED = re.compile(r"^\s*[A-Za-z' ]{1,24}:\s*")
_BRANCH_LISTS = ("on_hit", "on_miss", "on_fail", "on_success")


def overlaps(a: str, b: str) -> bool:
    """One of two plain printed phrases sits inside the other."""
    return bool(a) and bool(b) and (a in b or b in a)


def _denies_bonus_actions(effect: dict[str, Any]) -> bool:
    """A reaction_denied whose printed words are about Bonus Actions, not Reactions."""
    evidence = str(effect.get("evidence") or "").lower()
    return (effect.get("type") == "reaction_denied" or effect.get("condition") == "reaction_denied") \
        and "bonus action" in evidence and "reaction" not in evidence


def split_branch_menu(prior: list[Any], row: dict[str, Any], text: str, menu: dict[str, Any],
                      riders: list[Any] | None = None) -> dict[str, Any] | None:
    """The one-effect-per-option split of a menu printed inside a save or attack outcome (``branch_menu``), or None when the
    earlier typing gives it no delivery to hang the choice on. ``prior`` is the ability's earlier-typed tree, in which the
    parser and the model put every bullet of the menu into the one outcome and so applied them together; ``row`` is the
    options proposal (tools/type_options.py). Returns ``{"effects": the tree with the menu's slot empty, "options": [{"label",
    "effects", "riders"}], "riders": what is left shared}``, each option the whole tree the ability runs when it is picked --
    the delivery, the other outcome, and everything the ability does whichever is chosen, with only that option's own
    effects in the slot -- so a Successful Save's healing reduction or a top-level resistance stays on every option and the
    bullets are never run together.

    An effect of the earlier tree belongs to the menu when its quoted words sit inside the menu's printed bullets (and
    nowhere else in the text); those come out, and each option puts its own back. A bullet the options proposal could not type
    stays a choice: rescued from the earlier typing or as a healing reduction when that is what it says, else an option that
    runs the shared tree and carries the printed bullet as its one GM line -- never dropped from the menu."""
    branch = menu["branch"]
    kind = "attack" if branch in ("on_hit", "on_miss") else "save"
    heading = menu.get("head") or "Failed Save"
    accepted, missing, pieces = [], {}, []
    for option in row.get("options") or []:
        label = str(option.get("label") or "").strip()
        own = [dict(effect) for effect in option.get("effects") or [] if isinstance(effect, dict)]
        if label and own:
            pieces += [_plain(effect.get("evidence")) for effect in own]
            # "cannot take Bonus Actions" typed as denying Reactions (Ten-Thousand Masks Procession) would deny the wrong thing:
            # that option is its printed line for the GM
            kept = [effect for effect in own if not _denies_bonus_actions(effect)]
            accepted.append({"label": label, "own": _normalize(kept, "model_options") if kept else [],
                             "lines": [] if kept else [f"{heading}: {str(own[0].get('evidence') or label).strip().rstrip('.;')}."]})
    labels = {option["label"].lower() for option in accepted}
    for entry in row.get("rejected") or []:
        label = str(entry.get("option") or "").strip()
        if label:
            missing.setdefault(label, []).append(entry)
    pieces += [_plain(entry.get("evidence")) for entries in missing.values() for entry in entries]
    lines = menu["text"].split("\n")
    prefixes = [_plain("\n".join(lines[:index + 1])) for index in range(len(lines))]
    # the menu's bullets, without a generic line printed after them (a passive's trailing "This Domain ..." sentence): the
    # menu's lines up to the first one by which every quoted piece of its options has ended
    found = [piece for piece in pieces if piece and piece in prefixes[-1]]
    last = next((index for index, prefix in enumerate(prefixes) if all(piece in prefix for piece in found)), -1) if found else -1
    if last < 0:
        return None
    region, whole = prefixes[last], _plain(text)

    def belongs(effect: Any, in_slot: bool = False) -> bool:
        # In the menu's own outcome the words only have to be printed in the menu ("Apply your Shadow Mark" is also the
        # Successful Save line); elsewhere they must be printed nowhere else.
        piece = _plain(effect.get("evidence")) if isinstance(effect, dict) else ""
        return len(piece) >= 8 and piece in region and (in_slot or whole.count(piece) == region.count(piece))

    tree = copy.deepcopy(prior)
    deliveries = [effect for effect in _all(tree) if effect.get("type") == kind]
    anchor = next((effect for effect in deliveries
                   if any(belongs(effect_row, True) for effect_row in effect.get(branch) or [])), None)
    if anchor is None and len(deliveries) == 1:
        anchor = deliveries[0]
    if anchor is None:
        return None
    taken: list[dict[str, Any]] = []

    def strip(rows: list[Any], in_slot: bool = False) -> list[Any]:
        out = []
        for effect in rows or []:
            if isinstance(effect, dict):
                if effect is not anchor and belongs(effect, in_slot):
                    taken.append(effect)
                    continue
                for key in _BRANCH_LISTS:
                    if isinstance(effect.get(key), list):
                        effect[key] = strip(effect[key], effect is anchor and key == branch)
            out.append(effect)
        return out

    base = strip(tree)
    # An effect the earlier typing put in the menu's outcome from the words printed under the OTHER outcome (Half-Waking Moon's
    # "Successful Save: Cannot take Reactions" ran on a failed save, beside the chosen bullet) goes back to its own outcome.
    after = menu.get("after")
    if after and after["branch"] != branch:
        later = _plain(after["text"])
        moved = [effect for effect in anchor.get(branch) or [] if isinstance(effect, dict) and len(_plain(effect.get("evidence"))) >= 8
                 and _plain(effect.get("evidence")) in later and _plain(effect.get("evidence")) not in region
                 and whole.count(_plain(effect.get("evidence"))) == later.count(_plain(effect.get("evidence")))]
        anchor[branch] = [effect for effect in anchor.get(branch) or [] if not any(effect is other for other in moved)]
        there = [effect for effect in anchor.get(after["branch"]) or [] if isinstance(effect, dict)]
        # the same words typed there already (the model's fuller "Cannot take Reactions until the start of its next turn") stay one
        anchor[after["branch"]] = [*(anchor.get(after["branch"]) or []),
                                   *[effect for effect in moved if not any(_key(effect)[0] == _key(other)[0] and overlaps(_plain(effect.get("evidence")), _plain(other.get("evidence")))
                                                                           for other in there)]]
    # ...and one the earlier typing put there from a line printed outside the menu that another effect of the tree already types
    # (Thousand-Monkey Uprising's aura-wide "enemies cannot take Reactions" also ran on the failed save, beside the chosen bullet)
    elsewhere = [effect for effect in _all(base) if isinstance(effect, dict) and not any(effect is slot for slot in anchor.get(branch) or [])]

    def twinned(effect: Any) -> bool:
        piece = _plain(effect.get("evidence")) if isinstance(effect, dict) else ""
        return len(piece) >= 8 and piece not in region and effect.get("type") not in ("attack", "save") \
            and any(_key(other)[0] == _key(effect)[0] and overlaps(piece, _plain(other.get("evidence"))) for other in elsewhere)

    anchor[branch] = [effect for effect in anchor.get(branch) or [] if not twinned(effect)]
    for label, entries in missing.items():
        if label.lower() in labels:
            continue
        evidence = [str(entry.get("evidence") or "").strip() for entry in entries if str(entry.get("evidence") or "").strip()]
        plain = [_plain(piece) for piece in evidence]
        own = [copy.deepcopy(effect) for effect in taken if any(overlaps(_plain(effect.get("evidence")), piece) for piece in plain)]
        if not own:  # "the enemy cannot regain HP": a healing typed with no amount is a healing reduction
            fixed = fix_misread_effects(_normalize([{key: value for key, value in entry.items() if key != "option"}
                                                    for entry in entries if entry.get("type") in ("healing", "temp_hp") and entry.get("evidence")],
                                                   "model_options"), adds_to_technique=False)
            own = [effect for effect in fixed if effect.get("type") == "healing_reduction" and healing_reduction_amount(str(effect.get("evidence") or ""))]
        if own or evidence:
            accepted.append({"label": label, "own": own, "lines": [] if own else [f"{heading}: {evidence[0].rstrip('.;')}."]})
            labels.add(label.lower())
    if len(accepted) < 2:
        return None
    # A part of a typed option the proposals rejected stays a line for the GM on that option (Shadow Mark's second sentence).
    for option in accepted:
        seen = [_plain(effect.get("evidence")) for effect in option["own"]]
        for entry in missing.get(option["label"], []):
            piece = str(entry.get("evidence") or "").strip()
            if piece and option["own"] and not any(overlaps(_plain(piece), other) for other in seen):
                option["lines"].append(f"{heading}: {piece.rstrip('.;')}.")

    def place(option: dict[str, Any]) -> int:
        spots = [region.find(_plain(effect.get("evidence"))) for effect in option["own"]]
        spots += [region.find(_plain(line.split(":", 1)[-1])) for line in option["lines"]]
        return min((spot for spot in spots if spot >= 0), default=len(region))

    accepted.sort(key=place)  # the printed order: the menu, and the default pick on a tie
    options = []
    for option in accepted:
        copied, spot = copy.deepcopy((base, anchor))
        spot[branch] = [*(spot.get(branch) or []), *nest_saves(copy.deepcopy(option["own"]), text)]
        options.append({"label": option["label"], "effects": dedupe(normalize_dice(copied)), "lines": option["lines"]})
    # The record's lines about the menu's own bullets (and its "Choose one" header) are not shared by every option: each
    # bullet is now its option's effects, or its own line above.
    def restates(rider: Any) -> bool:
        body = _plain(_LABELLED.sub("", str(rider)))
        return _plain(rider) in region or (len(body) >= 8 and body in region)

    shared = [rider for rider in riders or [] if _plain(rider) and not restates(rider)]
    return {"effects": dedupe(normalize_dice(copy.deepcopy(base))), "riders": shared,
            "options": [{"label": option["label"], "effects": option["effects"], "riders": [*shared, *option["lines"]]} for option in options]}


# ------------------------------------------------------------------ choose-one options (owner 2026-09-26)
# 751 usable abilities print a menu ("Choose one:", "choose one of the following", "one of the following")
# but were typed as one flat/structured effect list holding every option, so combat applied all of them at
# once (tools/type_options.py finds and types them).  ``build_options`` turns the model's grounded
# {"common_effects": [...], "options": [{"label", "effects": [...]}]} into one structured tree per option,
# so the compiler can build one action per option instead of the all-options action.
def build_options(common_effects: list[dict[str, Any]], option_rows: list[dict[str, Any]], text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the ability's common effects, structured; its options, each a full structured tree) -- or
    (structured common_effects, []) when fewer than two options are grounded."""
    common_effects = [dict(effect) for effect in common_effects or [] if isinstance(effect, dict)]
    cleaned: list[dict[str, Any]] = []
    for option in option_rows or []:
        label = str(option.get("label") or "").strip()
        own = [dict(effect) for effect in option.get("effects") or [] if isinstance(effect, dict)]
        if label and own:
            cleaned.append({"label": label, "own": own})
    if len(cleaned) < 2:
        return structure(common_effects, text), []
    # The delivery (attack / save) the printed text uses to reach a target: learned from every effect on
    # the whole menu, since an option-only damage or condition line can be the only harmful effect that
    # reveals "make an attack" wraps every option, not only whatever landed in common_effects.
    # Options that bring their own save or attack keep it, so only the others teach the shared delivery
    # (Explosive Pill: Frost Pill is a Constitution save, not inside Flame Pill's Dexterity one; owner
    # 2026-09-26 merge review).
    bare = [option for option in cleaned if not any(row.get("type") in ("attack", "save") for row in option["own"])]
    sample = copy.deepcopy(common_effects) + [effect for option in bare for effect in copy.deepcopy(option["own"])]
    learned = structure(sample, text)
    head = learned[0] if learned and isinstance(learned[0], dict) and learned[0].get("type") in ("attack", "save") else None
    common = structure(copy.deepcopy(common_effects), text)
    shell = None
    if head is not None and not (common and isinstance(common[0], dict) and common[0].get("type") == head.get("type")):
        shell = {key: value for key, value in head.items() if key not in ("on_hit", "on_miss", "on_fail", "on_success")}
        for branch in (("on_hit", "on_miss") if head["type"] == "attack" else ("on_fail", "on_success")):
            shell[branch] = []
    options = []
    for option in cleaned:
        own = _normalize(option["own"], "model_options")
        # The shared delivery wraps an option with none of its own that harms a target (not Smoke Pill's cloud).
        wrap = shell is not None and option in bare and any(_harms_target(row) for row in option["own"])
        tree = copy.deepcopy([shell, *common] if wrap else common)
        head = tree[0] if tree and isinstance(tree[0], dict) and tree[0].get("type") in ("attack", "save") else None
        restated = next((row for row in own if head is not None and row.get("type") == head["type"] and (
            head["type"] == "attack" or str(row.get("ability") or "").lower() in ("", str(head.get("ability") or "").lower()))), None)
        if restated is not None:
            # The option restates the ability's own delivery (every Explosive Pill: "Each creature in the area
            # makes a Dexterity saving throw"): one roll with the branches joined, not a save inside a save
            # (owner 2026-09-26 merge review).
            for key in (("on_hit", "on_miss") if head["type"] == "attack" else ("on_fail", "on_success")):
                head[key] = [*(head.get(key) or []), *(restated.get(key) or [])]
            own = [row for row in own if row is not restated]
        _mark_delivery_branch(tree).extend(own)
        options.append({"label": option["label"], "effects": dedupe(normalize_dice(nest_saves(tree, text)))})
    return ([shell, *common] if shell is not None else common), options


# ------------------------------------------------------------------ area from text (owner 2026-09-26)
# 305 usable abilities name their area only in the printed rules text -- no typed "Area:" header
# the parser could read (factory_authoring.typed_mechanics._area), or one it could not parse (e.g.
# a cylinder's "10-foot-radius, 30-foot-high" pair).  Without area.size_ft, combat/factory_compiler
# ._target_kind makes them single-target and combat/typed_executor._area_targets never runs.
_SHAPE_ALIASES = {"radius": "sphere", "aura": "emanation"}
_SHAPE_WORDS = "sphere|cube|square|cylinder|emanation|aura|radius"
_AREA_LINE_RE = re.compile(
    r"(\d+)-foot\s+line\b(?:\s*,?\s*(?:that is\s+)?(\d+)(?:\s+feet|-foot)\s+wide)?"
    r"|\bline\s+(\d+)\s+feet\s+long(?:\s+and\s+(\d+)\s+feet\s+wide)?", re.I)
_AREA_CONE_RE = re.compile(r"(\d+)-foot\s+cone\b", re.I)
_AREA_SHAPE_RE = re.compile(rf"(\d+)-foot(?:-radius)?(?:,\s*\d+-foot-high)?\s+({_SHAPE_WORDS})\b", re.I)
_AREA_POINT_RE = re.compile(r"creatures?\s+(?:other than you\s+)?within\s+(\d+)\s+feet\s+of\s+(?:the|that|a)\s+point\b", re.I)
# A quantified clause ("each"/"all"/"every creature ... in/within the ...") is the one text shape
# that is safe to trust anywhere in the ability, even for an attack delivery (e.g. Cone of Death:
# "Make one ranged weapon attack against every creature of your choice within a 30-foot cone") --
# a splash line under a hit or a later/conditional effect's object size never uses this quantifier.
_AREA_EACH_SHAPE_RE = re.compile(
    rf"\b(?:each|all|every)\s+creatures?\b[^.]{{0,60}}?\b(?:in|within|inside)\s+(?:the|that|this|an?)\s+"
    rf"(?:(\d+)-foot\s+({_SHAPE_WORDS}|cone|line)|area)\b", re.I)
_AREA_ANCHOR_RE = re.compile(r"\bcreatures?\b[^.]{0,40}?\b(?:in|within|inside)\s+(?:the|that|this)\s+area\b", re.I)
_AREA_CL_HEADER_RE = re.compile(r"\|[^|\n]*\bradius\b[^|\n]*\|", re.I)
_AREA_CL_ROW_RE = re.compile(r"\|\s*(\d+)\s*[–-]\s*(\d+)\s*\|\s*(\d+)\s*feet\s*\|", re.I)
_AREA_CONTAINER_RE = re.compile(
    r"(?:no larger than|no more than|fits?\s+within|fit\s+inside|smaller than|occupies)\s*(?:an?\s+|one\s+)?$", re.I)
_AREA_INTRO_SPLIT_RE = re.compile(
    r"\b(?:if |when |failed save|successful save|failed check|successful check|on a hit|on a miss|on a failure|on a success)\b", re.I)


def _area_delivery(effects: list[dict[str, Any]]) -> str:
    head = effects[0] if effects and isinstance(effects[0], dict) else None
    kind = head.get("type") if head else None
    return kind if kind in ("attack", "save") else "automatic"


def _container_guarded(text: str, start: int) -> bool:
    """"no larger than a 10-foot cube" sizes an object the ability creates, not its area."""
    return bool(_AREA_CONTAINER_RE.search(text[max(0, start - 30):start]))


def _line_from(text: str) -> dict[str, Any] | None:
    match = _AREA_LINE_RE.search(text)
    if not match or _container_guarded(text, match.start()):
        return None
    size, width = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    area = {"shape": "line", "size_ft": int(size), "evidence": match.group(0)}
    if width:
        area["width_ft"] = int(width)
    return area


def _cone_from(text: str) -> dict[str, Any] | None:
    match = _AREA_CONE_RE.search(text)
    if not match or _container_guarded(text, match.start()):
        return None
    return {"shape": "cone", "size_ft": int(match.group(1)), "evidence": match.group(0)}


def _radial_from(text: str) -> dict[str, Any] | None:
    match = _AREA_SHAPE_RE.search(text)
    if not match or _container_guarded(text, match.start()):
        return None
    shape = _SHAPE_ALIASES.get(match.group(2).lower(), match.group(2).lower())
    return {"shape": shape, "size_ft": int(match.group(1)), "evidence": match.group(0)}


def _point_from(text: str) -> dict[str, Any] | None:
    match = _AREA_POINT_RE.search(text)
    if not match:
        return None
    return {"shape": "sphere", "size_ft": int(match.group(1)), "evidence": match.group(0)}


def _each_shape_from(text: str) -> tuple[dict[str, Any] | None, bool]:
    """(area, matched): matched is True whenever the quantified clause is present at all, even
    without its own shape+size, so a bare "every creature in the area" still marks eligibility."""
    match = _AREA_EACH_SHAPE_RE.search(text)
    if not match:
        return None, False
    if match.group(1) and match.group(2):
        shape = _SHAPE_ALIASES.get(match.group(2).lower(), match.group(2).lower())
        return {"shape": shape, "size_ft": int(match.group(1)), "evidence": match.group(0)}, True
    return None, True


def _cl_table_from(text: str) -> dict[str, Any] | None:
    """A CL-scaled radius with no header value at all (e.g. Earthquake Stomp's "| Cultivation
    Level | Radius |" table): the CL-1 (lowest printed) row is the base size_ft; every row is kept
    as size_by_cl."""
    header = _AREA_CL_HEADER_RE.search(text)
    if not header or not _AREA_ANCHOR_RE.search(text):
        return None
    rows = sorted({(int(a), int(b), int(c)) for a, b, c in _AREA_CL_ROW_RE.findall(text[header.end():header.end() + 400])})
    if not rows:
        return None
    return {"shape": "sphere", "size_ft": rows[0][2], "size_by_cl": [list(row) for row in rows], "evidence": "CL radius table"}


def infer_area_from_text(mechanic: dict[str, Any], source_text: str) -> dict[str, Any] | None:
    """The mechanic's area read from its printed text when no typed "Area:" header gave one.
    Conservative (owner 2026-09-26): only for save- or automatic-delivery abilities, or text that
    explicitly says each/all/every creature is affected -- never a splash line under an attack's
    hit, nor an object or terrain size that belongs to a later or conditional effect."""
    area = mechanic.get("area")
    if area and area.get("size_ft") is not None:
        return area
    text = source_text or ""
    delivery = _area_delivery(mechanic.get("effects") or [])
    each_area, each_matched = _each_shape_from(text)
    if delivery == "attack" and not each_matched:
        return area
    if each_area:
        return {**each_area, "source": "text"}
    header_specials = []
    if area and area.get("shape") == "special" and area.get("text"):
        header_specials.append(area["text"])
    rng = mechanic.get("range")
    if rng and rng.get("kind") == "special" and rng.get("text"):
        header_specials.append(rng["text"])
    for candidate in header_specials:
        for finder in (_line_from, _cone_from, _radial_from):
            found = finder(candidate)
            if found:
                return {**found, "source": "text"}
    found = _point_from(text)
    if found:
        return {**found, "source": "text"}
    if delivery != "attack":
        intro = _AREA_INTRO_SPLIT_RE.split(text, maxsplit=1)[0]
        for finder in (_line_from, _cone_from, _radial_from):
            found = finder(intro)
            if found:
                return {**found, "source": "text"}
        found = _cl_table_from(text)
        if found:
            return {**found, "source": "text"}
    return area


# ------------------------------------------------------------------ marks (owner 2026-09-26)
# Many Sphere talents place a named mark on a creature ("place a Faultline Mark on it", "the target
# also gains a Faultline Mark", "plant a Dream Seed") and other talents key off "a creature bearing
# your <Mark>" or "spend/consume the <Mark>". combat/typed_executor.py's block_mark/block_spend_mark/
# block_if_marked are the runtime side; this module only recognizes the printed text, grounded by the
# matched span (never invented).
_MARK_SUFFIXES = ("Mark", "Seal", "Seed", "Trace", "Point", "Imprint", "String", "Star", "Brand",
                  "Rune", "Sigil", "Thread", "Scar", "Token", "Glyph")
# Horizontal whitespace only ([^\S\n]): the source text's list/table layout puts an unrelated heading
# and its body on separate lines, and re's default \s spans newlines -- without this a verb ending one
# line could otherwise capture a Title-Case phrase that starts the next (owner 2026-09-26, found
# rebuilding the authority: "Marks\nSpend Forge Marks" read as one bogus match).
_WS = r"[^\S\n]"
_MARK_NAME = rf"(?:[A-Z][\w'-]*{_WS}+){{0,3}}(?:{'|'.join(_MARK_SUFFIXES)})s?"
_MARK_PLACE_RE = re.compile(
    rf"(?i:places?|plants?|planted|applies|apply|applied|marks?|marked|leaves?|left|gains?|now{_WS}+bears?)"
    rf"{_WS}+(?:a|an|your|\d+)?{_WS}*({_MARK_NAME})\b")
# "you may place a Faultline Mark when one of the following happens" introduces a menu of different
# trigger clauses for a whole Foundation/base-ability passive, not one ability's own placement: never a
# clean single on_hit/on_fail/top-level branch, so it is excluded rather than guessed.
_MARK_MENU_RE = re.compile(r"\bwhen one of the following\b|\bwhenever one of the following\b", re.I)
_MARK_NEXT_TURN_RE = re.compile(r"\buntil (?:the )?end of your next turn\b", re.I)
_MARK_SPEND_RE = re.compile(rf"(?i:spends?|consumes?|expends?){_WS}+(?:a|an|your|the|one{_WS}of{_WS}your)?{_WS}*({_MARK_NAME})\b")
# A suffix word alone is common English, not a mark name (owner 2026-09-26: "gains Hit Points" is not a
# mark); excluded by the whole matched phrase, lowercased.
_MARK_NAME_EXCLUDE = {"hit point", "hit points", "action point", "action points",
                      "cultivation point", "cultivation points", "experience point", "experience points"}
# "gains Temporary Hit Points", "gain PB Temporary Hit Points": a pool of Hit Points, never a mark (hunt 3, bug 3: 89 mechanics carried a
# "Temporary Hit Point" mark placed on the target, and a mark on the target made every self buff that grants some an ability aimed at a foe).
_HIT_POINT_NAME = re.compile(r"\bhit points?$", re.I)


def _is_no_mark(name: str) -> bool:
    return name.lower() in _MARK_NAME_EXCLUDE or bool(_HIT_POINT_NAME.search(name))


def _singular_mark(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name[:-1] if len(name) > 1 and name[-1] == "s" and name[-2] != "s" else name


def _find_marks(text: str) -> list[dict[str, Any]]:
    """Named marks this mechanic's printed text places on a target (owner 2026-09-26), each grounded
    by its matched span. Deduplicated by name: flavour text often repeats the same mark's name."""
    text = text or ""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for match in _MARK_PLACE_RE.finditer(text):
        if _MARK_MENU_RE.search(text[match.end():match.end() + 60]):
            continue
        name = _singular_mark(match.group(1))
        if name.lower() in seen or _is_no_mark(name):
            continue
        seen.add(name.lower())
        window = text[max(0, match.start() - 80):match.end() + 80]
        duration = {"kind": "target_next_turn"} if _MARK_NEXT_TURN_RE.search(window) else {"kind": "until_removed"}
        out.append({"mark": name, "evidence": match.group(0).strip(), "duration": duration})
    return out


def _mark_delivery_branch(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where a newly found mark effect lands (owner 2026-09-26): on_hit for an attack delivery,
    on_fail for a save, else top-level -- the same reading as ``_area_delivery``."""
    head = effects[0] if effects and isinstance(effects[0], dict) else None
    if head and head.get("type") == "attack":
        return head.setdefault("on_hit", [])
    if head and head.get("type") == "save":
        return head.setdefault("on_fail", [])
    return effects


def add_marks_from_text(effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Append a ``mark`` effect for each named mark the printed text places (owner 2026-09-26),
    grounded by evidence text; a mark already present anywhere in the tree is not added twice."""
    marks = _find_marks(text)
    if not marks:
        return effects
    existing = {str(row.get("mark") or "").lower() for row in _all(effects) if row.get("type") == "mark"}
    branch = _mark_delivery_branch(effects)
    for mark in marks:
        if mark["mark"].lower() in existing:
            continue
        existing.add(mark["mark"].lower())
        branch.append({"type": "mark", "mark": mark["mark"], "applies_to": "target", "duration": mark["duration"],
                       "evidence": mark["evidence"], "origin": "structure"})
    return effects


# "against a/the creature bearing your <Mark>" or "against a marked creature" (owner 2026-09-26): only
# gates a pre-existing bonus "extra_damage" effect (never the ability's own base attack/save/damage),
# and only when the text is this explicit -- a narrower automation than mark placement above.
_MARK_GATE_RE = re.compile(rf"\bagainst (?:a|the|one) (?:creature )?(?:bearing (?:one of )?your ({_MARK_NAME})|marked creature)\b", re.I)


_OPENED_SENTENCE = re.compile(r"[^.\n]*\b(?:already Opened|an? Opened creature|the Opened creature|(?:is|was) Opened)\b[^.\n]*[.\n]", re.I)


def gate_on_opened(modifier: dict[str, Any], text: str) -> dict[str, Any]:
    """Iron Fist's Openings (owner 2026-09-28): what a talent does "if the target was already Opened" runs only against a
    creature bearing the actor's Opened mark (combat/typed_executor.py open_guard places it). A talent whose trigger itself
    names an Opened creature ("When you hit an Opened creature ...") is gated whole; otherwise only the effects printed in
    an Opened sentence are. The modifier-wide precondition text about it is then dropped: the gate carries it."""
    sentences = [match.group(0).lower() for match in _OPENED_SENTENCE.finditer(text or "")]
    if not sentences or not isinstance(modifier, dict):
        return modifier
    body = re.sub(r"^\s*#+[^\n]*\n", "", text or "")
    body = re.sub(r"^\s*Prerequisite:[^\n]*\n", "", body.strip())
    first = (re.split(r"(?<=[.!?])\s+|\n", body.strip(), maxsplit=1) or [""])[0].lower()
    whole = bool(_OPENED_SENTENCE.search(first + "."))

    def in_opened(row: dict[str, Any]) -> bool:
        evidence = str(row.get("evidence") or "").lower().strip()
        return bool(evidence) and any(evidence in sentence or evidence[:40] in sentence for sentence in sentences)

    def wrap(rows: list[Any]) -> list[Any]:
        out = []
        for row in rows:
            if not isinstance(row, dict) or row.get("type") == "if_marked":
                out.append(row)
                continue
            for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
                if isinstance(row.get(branch), list):
                    row[branch] = wrap(row[branch])
            if whole or in_opened(row):
                out.append({"type": "if_marked", "mark": "Opened", "effects": [row], "evidence": str(row.get("evidence") or ""), "origin": "structure"})
            else:
                out.append(row)
        return out

    out = {**modifier, "effects": wrap(copy.deepcopy(modifier.get("effects") or []))}
    if re.search(r"\bopened\b", str(out.get("precondition") or ""), re.I):
        out["precondition"] = ""
    return out


def gate_extra_damage_on_mark(effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Wrap ``extra_damage`` effects in ``if_marked`` when the printed text ties them to a creature
    bearing the actor's mark (owner 2026-09-26), e.g. "deal an extra 2d6 damage against a creature
    bearing your Stellar Mark." Leaves everything else untouched -- only where the text is clear."""
    match = _MARK_GATE_RE.search(text or "")
    if not match:
        return effects
    mark = _singular_mark(match.group(1)) if match.group(1) else None

    def _wrap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            if not isinstance(row, dict):
                out.append(row)
                continue
            for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
                if isinstance(row.get(branch), list):
                    row[branch] = _wrap(row[branch])
            if row.get("type") == "extra_damage" and mark:
                out.append({"type": "if_marked", "mark": mark, "effects": [row], "evidence": match.group(0), "origin": "structure"})
            else:
                out.append(row)
        return out

    return _wrap(effects)


def add_spend_mark_from_text(effects: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Append a ``spend_mark`` effect when the printed text spends/consumes a named mark as part of
    using this ability (owner 2026-09-26), e.g. "you may spend a Faultline Mark on the target to ...".
    Never added twice, and never for a mark this same text is also placing (a placement and a spend of
    the identical name in one ability reads as the mark's own limit text, not a use of it)."""
    match = _MARK_SPEND_RE.search(text or "")
    if not match:
        return effects
    name = _singular_mark(match.group(1))
    if _is_no_mark(name):
        return effects
    placed = {str(row.get("mark") or "").lower() for row in _all(effects) if row.get("type") == "mark"}
    if name.lower() in placed or any(row.get("type") == "spend_mark" and str(row.get("mark") or "").lower() == name.lower()
                                     for row in _all(effects)):
        return effects
    branch = _mark_delivery_branch(effects)
    branch.append({"type": "spend_mark", "mark": name, "applies_to": "target", "evidence": match.group(0).strip(), "origin": "structure"})
    return effects


_COST_LINE_RE = re.compile(r"^\W*cost\s*:", re.I)


def drop_cost_restatement(effects: list[Any], cost: Any) -> list[Any]:
    """A typed ``spend_resource`` that quotes the header's "Cost:" line is the activation cost the compiler
    already charges (owner 2026-09-26 tournament: Talisman Recall paid its 1 CP twice).  Kept when the
    header cost was not read, since it is then the only charge."""
    if not cost:
        return effects
    out = []
    for effect in effects or []:
        if isinstance(effect, dict):
            if effect.get("type") == "spend_resource" and _COST_LINE_RE.match(str(effect.get("evidence") or "")):
                continue
            effect = {**effect, **{branch: drop_cost_restatement(effect[branch], cost)
                                   for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects") if isinstance(effect.get(branch), list)}}
        out.append(effect)
    return out


_DEFERRED_RE = re.compile(r"^\W*(?:once (?:per|each) (?:turn|round),?\s*)?(?:when|whenever|the (?:first|next) time|each time)\b", re.I)


def mark_deferred(effects: list[Any]) -> list[Any]:
    """An action's effect printed as a later trigger ("once per turn when you hit...", "when it drops to 0
    HP, gain 1 Devoured Essence") is not an effect of using the action: tagged ``deferred`` so the
    executor does not run it on use (owner 2026-09-26 tournament: Demon Mark gained its Devoured Essence
    on every cast).  combat/typed_executor.py turns the "when you hit" extra damage into a bonus on later
    hits; the rest stays in the printed description."""
    for effect in _all(effects):
        if effect.get("type") != "attack" and _DEFERRED_RE.match(str(effect.get("evidence") or "")):
            effect["deferred"] = True
    return effects


_IGNORES_RESISTANCE = re.compile(r"\b(?:ignor|bypass)\w*\b[^.;]*\b(?:resistance|immunity)\b", re.I)
_LOSES_RESISTANCE = re.compile(r"\b(?:lose|loses|suppress\w*)\b[^.;]*\bresistance\b"
                               r"|\bhave resistances?\b[^.;]*\b(?:ignored|suppressed|negated)\b", re.I)  # Living Flame's "have Resistance to Fire ignored"
_ADDS_DAMAGE = re.compile(r"\b(?:add|increase|additional|extra)\b[^.;]*\bdamage\b|\+\d+\s+(?:to\s+)?damage", re.I)
# Not an addition: "increase Impact damage to 6d10", "the die from d6 to d8", "becomes twice your PB", "instead".
_REDUCES_HEALING = re.compile(r"\b(?:reduc\w*|halv\w*|less(?:en\w*)?|cannot regain|can't regain|no longer regain)\b[^.;]*\b(?:heal\w*|hit points?|regain\w*|hp)\b"
                              r"|\b(?:heal\w*|regain\w*)\b[^.;]*\b(?:is |are )?(?:reduced|halved)\b", re.I)
_LESSENS = re.compile(r"\b(?:reduc|less|halv|lower|becomes?|change|instead)|\bto\s+`?\d+d\d+|\bfrom\s+`?d\d+", re.I)


def fix_misread_effects(effects: list[Any], *, adds_to_technique: bool) -> list[Any]:
    """Two readings the model typing gets backwards (owner 2026-09-26 overnight bug hunt):
    - "ignore Resistance to Slashing" typed as a resistance effect would grant the target that resistance
      (Armor-Splitting Cut, Targeted Assault): it becomes ``ignore_resistance``, read when the damage lands;
      "the target loses Resistance to ..." (To the Hilt) becomes ``suppress_resistance`` on the target;
    - in one option of a talent's menu (Daemonic Augment's "add Proficiency Bonus to one damage roll"), a
      damage_modifier (which only reactions read, as a reduction) adds that damage to the technique's target."""
    out = []
    for effect in effects or []:
        if isinstance(effect, dict):
            evidence = str(effect.get("evidence") or "")
            if effect.get("type") in ("resistance", "immunity") and _IGNORES_RESISTANCE.search(evidence):
                if "resistance" not in evidence.lower():
                    continue  # ignoring an immunity is not supported
                effect = {**effect, "type": "ignore_resistance"}
            elif effect.get("type") in ("resistance", "immunity") and _LOSES_RESISTANCE.search(evidence):
                effect = {**effect, "type": "suppress_resistance", "applies_to": "target"}
            if adds_to_technique and effect.get("type") == "damage_modifier" and _ADDS_DAMAGE.search(evidence) and not _LESSENS.search(evidence):
                effect = {**effect, "type": "extra_damage", "applies_to": "target"}
            if effect.get("type") in ("healing", "temp_hp") and _REDUCES_HEALING.search(evidence):
                # "Reduce the healing it receives" typed as healing healed the enemy (Astra's audit, 2026-09-26, Cinder
                # Brand); combat has no healing reduction yet, so it is kept as rules text (a rider), never applied.
                effect = {**effect, "type": "healing_reduction", "was": effect["type"]}
            effect = {**effect, **{branch: fix_misread_effects(effect[branch], adds_to_technique=adds_to_technique)
                                   for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects") if isinstance(effect.get(branch), list)}}
        out.append(effect)
    return out


_ON_ANOTHER = re.compile(r"\b(?:target|creature|it|them|enemy|foe|ally|object|place[sd]?|appl(?:y|ies|ied)|bears?|leaves?)\b", re.I)


def _named_phrase(evidence: str, name: str) -> bool:
    """The whole capitalised phrase at the match is exactly ``name`` -- "Charge" is not "Thunder Charge"
    or "Charge Momentum" (owner 2026-09-26 review of the first conversion)."""
    for match in re.finditer(rf"((?:[A-Z][\w'-]*[ \t]+)*){re.escape(name)}s?((?:[ \t]+[A-Z][\w'-]*)*)", evidence):
        if not match.group(1).strip() and not match.group(2).strip():
            return True
    return False


def resources_as_marks(effects: list[Any], marks: list[str], pools: list[str] = ()) -> list[Any]:
    """A mark typed as a resource ("The target gains 1 Dose Mark", "Place 1 Forge Mark on it", "remove one Dose
    Mark from the target") is placed on or spent from the creature (owner 2026-09-26: "we need the different
    resources to be generated and placed on characters"); ``marks``/``pools`` are the names tools/type_resources.py
    found. Only when the whole name is a mark's and the sentence puts it on another creature; "you gain 1 Thunder
    Charge" is the character's own pool. combat/typed_executor.py's mark blocks track the marks."""
    names = sorted([(name, "mark") for name in marks] + [(name, "pool") for name in pools], key=lambda row: -len(row[0]))
    out = []
    for effect in effects or []:
        if isinstance(effect, dict):
            effect = {**effect, **{branch: resources_as_marks(effect[branch], marks, pools)
                                   for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects") if isinstance(effect.get(branch), list)}}
            if effect.get("type") in ("gain_resource", "spend_resource"):
                evidence = str(effect.get("evidence") or "").replace("’", "'")
                found = next(((name, kind) for name, kind in names if _named_phrase(evidence, name)), None)
                if found and found[1] == "mark" and _ON_ANOTHER.search(evidence):
                    applies = effect.get("applies_to") if effect.get("applies_to") in ("target", "ally", "enemies_in_area", "creatures_in_area") else "target"
                    effect = {"type": "mark" if effect["type"] == "gain_resource" else "spend_mark", "mark": found[0], "applies_to": applies,
                              "evidence": effect.get("evidence"), "origin": effect.get("origin"), "was": effect["type"],
                              **({"deferred": True} if effect.get("deferred") else {})}
        out.append(effect)
    return out


_REMOVAL_LABEL = re.compile(r"^\s*(?:remove|end|cure|cleanse|suppress|purge|negate)\b", re.I)


def removals_as_removals(effects: list[Any], label: str = "") -> list[Any]:
    """"End the Poisoned condition" or a menu option "Remove Blinded" typed as a ``condition`` effect would apply the
    condition it removes (Astra's audit, 2026-09-26: Purify the Pulse's "Remove Poisoned" poisoned its target): it
    becomes ``remove_condition`` (combat/typed_executor.py block_remove_condition)."""
    by_label = bool(_REMOVAL_LABEL.match(label or ""))
    out = []
    for effect in effects or []:
        if isinstance(effect, dict):
            effect = {**effect, **{branch: removals_as_removals(effect[branch], label)
                                   for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects") if isinstance(effect.get(branch), list)}}
            name = str(effect.get("condition") or "").lower()
            evidence = str(effect.get("evidence") or "")
            named_by_label = by_label and re.search(rf"\b{re.escape(name[:6])}", label or "", re.I)  # "End Poison" names Poisoned
            if effect.get("type") == "condition" and name and name != "none" and (named_by_label or re.search(
                    rf"\b(?:remov\w*|end|ends|cures?|cleanses?|suppress(?:es)?)\s+(?:the |one |a |an |any |its |their )?{re.escape(name)}\b"
                    rf"|\b(?:remov\w*|end|ends|cures?)\b[^.;]*\b{re.escape(name)} condition\b", evidence, re.I)):
                effect = {**effect, "type": "remove_condition", "was": "condition"}
        out.append(effect)
    return out


def mandatory_core(prior: list[Any], options: list[dict[str, Any]]) -> list[Any]:
    """The delivery and damage an ability deals whichever option is chosen, when the options leave it out (Astra's
    audit, 2026-09-26: Ignite's split kept an empty attack and lost its Fire damage): the earlier typing's attack
    or save with only its damage. Nothing else is carried -- the earlier typing ran every option at once, so any
    other effect in it may belong to one option -- and nothing at all when an option has damage of its own."""
    head = prior[0] if prior and isinstance(prior[0], dict) and prior[0].get("type") in ("attack", "save") else None
    if head is None or any(row.get("type") in ("damage", "extra_damage") for option in options for row in _all(option.get("effects") or [])):
        return []
    branch, other = ("on_hit", "on_miss") if head["type"] == "attack" else ("on_fail", "on_success")
    damage = [copy.deepcopy(row) for row in head.get(branch) or [] if isinstance(row, dict) and row.get("type") == "damage"]
    if not damage:
        return []
    kept_other = [copy.deepcopy(row) for row in head.get(other) or [] if isinstance(row, dict) and row.get("type") == "half_damage"]
    return [{**{key: value for key, value in head.items() if key not in ("on_hit", "on_miss", "on_fail", "on_success")},
             branch: damage, other: kept_other}]


def _substantive(effects: list[Any]) -> bool:
    return any(row.get("type") not in ("attack", "save", "half_damage") for row in _all(effects))


def graft_options(core: list[Any], options: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Each option on top of the mandatory core (Astra's audit, 2026-09-26): inside the core's delivery branch
    (on a hit, on a failed save), an option's own restatement of that delivery merged into it rather than nested."""
    head_of = lambda tree: tree[0] if tree and isinstance(tree[0], dict) and tree[0].get("type") in ("attack", "save") else None
    grafted = []
    for option in options:
        tree = copy.deepcopy(core)
        own = copy.deepcopy(option.get("effects") or [])
        head, own_head = head_of(tree), head_of(own)
        if head is not None and own_head is not None and own_head.get("type") == head.get("type"):
            for key in (("on_hit", "on_miss") if head["type"] == "attack" else ("on_fail", "on_success")):
                head[key] = [*(head.get(key) or []), *(own_head.get(key) or [])]
            own = own[1:]
        (_mark_delivery_branch(tree) if head is not None else tree).extend(own)
        grafted.append({**option, "effects": dedupe(normalize_dice(nest_saves(tree, text)))})
    return grafted


def option_area(option: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any] | None:
    """An option's own area from its own printed words (Astra's audit, 2026-09-26: Field Formula's Numbing Smoke
    fills "a 5-foot-radius Sphere centered" on a point; the menu itself names no area)."""
    words = " ".join(str(row.get("evidence") or "") for row in _all(option.get("effects") or []))
    area = infer_area_from_text({**parent, "area": None, "effects": option.get("effects") or []}, words)
    return area if area and area.get("size_ft") else None


_REPEAT_SAVE = re.compile(r"repeats? the (?:saving throw|save)[^.]*?(?:at the (start|end) of each (?:of (?:its|their) )?turns?)?", re.I)


def mark_repeat_saves(effects: list[Any], text: str | None) -> list[Any]:
    """"The target repeats the saving throw at the end of each of its turns, ending the effect on a success" (owner
    2026-09-26, 143 abilities): a condition a failed save gives carries ``repeat_save`` with that save's ability;
    combat/gate2_engine.py rolls it at the end (or start) of the affected creature's turn."""
    match = _REPEAT_SAVE.search(text or "")
    if not match:
        return effects
    when = (match.group(1) or "end").lower()

    def walk(rows: list[Any], ability: str | None) -> list[Any]:
        out = []
        for effect in rows or []:
            if isinstance(effect, dict):
                if effect.get("type") == "save":
                    effect = {**effect, "on_fail": walk(effect.get("on_fail") or [], str(effect.get("ability") or "con").upper())}
                elif effect.get("type") == "condition" and ability:
                    effect = {**effect, "repeat_save": {"ability": ability, "when": when}}
                else:
                    effect = {**effect, **{branch: walk(effect[branch], ability) for branch in ("on_hit", "on_miss", "on_success", "effects")
                                           if isinstance(effect.get(branch), list)}}
            out.append(effect)
        return out

    return walk(effects, None)


_HEAL_BY_PB = re.compile(r"\b(?:reduc\w*)\b[^.]*\b(?:heal\w*|regain\w*)\b[^.]*\bproficiency bonus|\bheal\w*\b[^.]*\breduc\w*\b[^.]*\bproficiency bonus", re.I)
_HEAL_HALF = re.compile(r"\bheal\w*\b[^.]*\bhalved\b|\bregains? only half\b|\bhalv(?:e|es|ing)\b[^.;]*\bheal\w*", re.I)
# "cannot regain HP" too (Black Trace's Fray, roster playtest 2026-09-29: it was left a GM line).
_HEAL_NONE = re.compile(r"\b(?:can't|can’t|cannot) regain (?:hit points|HP)\b", re.I)


def healing_reduction_amount(evidence: str) -> str | None:
    """What a healing_reduction effect does when healing lands: "pb", "half" or "none" (owner 2026-09-26); None for a
    misread ("reduced to 0 HP") that stays rules text."""
    if _HEAL_NONE.search(evidence):
        return "none"
    if _HEAL_HALF.search(evidence):
        return "half"
    if _HEAL_BY_PB.search(evidence):
        return "pb"
    return None



# ------------------------------------------------------------------ weapon delivery (owner 2026-09-27)
# "Make a melee weapon attack with an axe weapon. On a hit, the attack deals its normal weapon damage" (Hewing
# Strike) is an attack with the character's own weapon -- its attack bonus, damage and reach -- not a damageless
# Cultivation Attack (the playtest: "that attack did nothing"). The phrase must be the user's own attack: a
# sentence that begins "Make ...", or "you (may) make ..."; a command listed for another creature ("- make one
# weapon attack at Disadvantage against a legal target you choose", Dance of Borrowed Limbs) is not.
_WEAPON_ATTACK = re.compile(
    r"(?P<verb>[Mm]ake) (?:a|an|one) (?P<kind>melee |ranged |thrown )?"
    r"(?:weapon attack|attack with (?:a|an|your|the) (?:(?P<fam>[a-z-]+?)(?:-family)? )?weapon)"
    r"(?: with (?:a|an|the|your) (?P<fam2>[a-z-]+?)(?= weapon\b|[ .,;]))?")
_SENTENCE_START = re.compile(r"(?:^|[.:*\n])\s*$")
_USER_SUBJECT = re.compile(r"\b(?:you|and)\s+(?:may |can |then |instead )?$")


def weapon_delivery(text: str) -> dict[str, Any] | None:
    """{"kind": melee | ranged | thrown | any, "family": "axe" | "greatbow" | None, "special_attack": bool} when the
    ability's own delivery is a weapon attack; "special_attack" is the Attack action's "Parent Action: Attack" form
    (it replaces one attack of the Attack action, so Extra Attack keeps the others)."""
    for match in _WEAPON_ATTACK.finditer(text or ""):
        before = text[:match.start("verb")]
        if match.group("verb") == "Make" and _SENTENCE_START.search(before) or _USER_SUBJECT.search(before):
            family = (match.group("fam") or match.group("fam2") or "").strip().lower()
            return {"kind": (match.group("kind") or "").strip() or "any",
                    "family": family if family and family not in ("same", "chosen", "wielded", "held") else None,
                    "special_attack": bool(re.search(r"Parent Action:\s*Attack", text))}
    return None


_ON_HIT_MENU = re.compile(r"\bmake (?:a|an|one) [^.]{0,60}attack[^.]{0,80}\.\s*(?:[^.]{0,160}\.\s*)?"
                          r"(?:then )?(?:on (?:a )?hit,? )?choose one\b", re.I)


def options_ride_the_hit(effects: list[Any], options: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """"Make an attack. On a hit ... Then choose one rider" (Hewing Strike, Cast Axe, Black Trace): every option is
    part of that hit. An option typed without the attack (Hewing Strike's Hamper, only "reduce its Speed") gets it,
    with its own effects on the hit -- otherwise it compiled as a buff for the user (owner 2026-09-27 playtest)."""
    if not _ON_HIT_MENU.search(text or ""):
        return options
    head = next((row for row in effects or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    if head is None:
        head = next((row for option in options for row in option.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    if head is None:
        return options
    shell = {key: value for key, value in head.items() if key not in ("on_hit", "on_miss")}
    out = []
    for option in options:
        own = option.get("effects") or []
        if any(isinstance(row, dict) and row.get("type") == "attack" for row in own):
            out.append(option)
            continue
        out.append({**option, "effects": [{**copy.deepcopy(shell), "on_hit": [*copy.deepcopy(head.get("on_hit") or []), *copy.deepcopy(own)],
                                            "on_miss": copy.deepcopy(head.get("on_miss") or [])}]})
    return out
