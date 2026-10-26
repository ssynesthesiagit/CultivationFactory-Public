"""Classify a reaction's printed trigger text into a canonical kind (owner 2026-09-25).

Reactions in the typed mechanics authority (``mechanics[id].activation.trigger``)
are free text: 427 of them, only a fraction phrased simply enough to run without
a human reading the card (marks, terrain, stance, and equipment preconditions
cannot be checked generically).  This module recognizes the small set of clean,
common phrasings -- data in ``combat/rules/reaction_trigger_phrases.json``,
owner-editable -- and classifies everything else as ``unsupported`` rather than
guess.  A record whose printed sentence is not safe to parse (or whose export copy
rewrites printed prose) may declare the same event in ``activation.trigger_reading``
(reviewed_final.d; one event, or a list when the trigger names several, as in
``trigger_readings.jsonl``'s ``events``), which :func:`readings_for` uses before any prose is read.
Filters that ARE checked at runtime: melee/ranged, "you can see" style
awareness (recorded but not enforced -- the engine does not track visibility),
and a "within N feet" range.  Anything else the trigger mentions is not
verified, matching how every other building block in this combat engine keeps
its policy simple (combat/typed_reactions.py's module docstring).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .trigger_overlay import from_model as _overlay_from_model, kind_for_event, own_action as _overlay_own_action
from .trigger_overlay import lookup as _overlay_lookup, model_row as _overlay_model_row

RULES_PATH = Path(__file__).resolve().parent / "rules" / "reaction_trigger_phrases.json"
_CACHE: dict[str, Any] = {}

# Kinds an engine hook actually runs (combat/typed_reactions.py). ally_hit/ally_attacked/
# ally_missed/ally_damaged are offered to other active Factory fighters on the target's own
# team (combat/typed_reactions.py's on_attacked/on_attack_hit/on_attack_missed/on_damage);
# drop_to_zero/bloodied fire from the damage hook, condition_gained from block_condition,
# technique_targets/technique_used from resolve_typed, and critical_hit/natural_1 from the
# attack-hit/miss hooks (owner 2026-09-26). "moved" has no hook and stays non-runnable.
RUNNABLE_KINDS = frozenset({
    "attacked", "hit", "missed", "damaged", "save",
    "ally_hit", "ally_attacked", "ally_missed", "ally_damaged",
    "drop_to_zero", "bloodied", "condition_gained", "critical_hit", "natural_1",
    "technique_targets", "technique_used",
    # The character's own acts (owner 2026-09-26): typed_reactions.on_own_event, mostly resource generation.
    "own_hit", "own_kill", "own_save_failed",
    # R2 (owner 2026-09-26: pushes and throws): being pushed or pulled -- yourself or an ally -- and an ally gaining a condition.
    "forced_moved", "ally_forced_moved", "ally_condition_gained",
    # R3-R5 (owner 2026-09-26): actions, reactions and rolls of creatures in range; turn starts, initiative, moving into or
    # out of range and reach; grapples; an ally about to drop to 0; one effect damaging several creatures; own follow-ups.
    "creature_acted", "reaction_used", "own_ability", "creature_d20", "creature_nat", "own_d20_fail", "own_save_succeeded",
    "creature_attack_missed", "creature_turn_start", "ally_turn_start", "own_turn_start", "enters_range", "leaves_reach",
    "initiative", "grapple_failed", "ally_grapple_succeeded", "multi_damage", "ally_drop_to_zero", "own_action",
    # Step 8 (owner 2026-09-26): another creature moves, drops to 0 HP, saves, or regains HP (typed_reactions.on_creature_event).
    "moved", "any_drop_to_zero", "creature_save_failed", "creature_save_succeeded", "healed",
    # Riders lane 2 (2026-09-29): a creature gains the Hidden or Invisible condition (combat/ext/exposed.py fires it).
    "became_hidden",
    "temp_hp_gained", "cp_restored",
})

_SIGHT_RE = re.compile(r"\b(?:that )?you can (?:see|perceive|hear)\b|\byou are aware of\b|\bthat can (?:see|hear)\b")
_RANGE_RE = re.compile(r"within (\d+) feet(?: of (?:you|yourself|one of your \w+))?")
_LEADING_WHEN = re.compile(r"^when\s+", re.I)

# Owner 2026-09-26 ("make sure the mechanics aren't damaged"): checkable limits parsed from the
# ORIGINAL printed trigger, alongside its kind -- combat/rules/reaction_trigger_phrases.json's "limits".
_SAVE_ABILITY_CLAUSE_RE = re.compile(
    r"((?:strength|dexterity|constitution|intelligence|wisdom|charisma)"
    r"(?:(?:,\s*|\s+)(?:or\s+|and\s+)?(?:strength|dexterity|constitution|intelligence|wisdom|charisma))*)"
    r"\s+saving throw", re.I)

# The reactor's own resource/state phrases: "while you have X", "already have X", "while holding
# (pre-existing) X", "X is active", "have X available". Matched against the trigger with a leading
# When/While/After/Before dropped first (so a sentence-initial capitalized connector is never mistaken
# for part of the capitalized resource name, e.g. "When Orbiting Guard is active").
_LEADING_CONNECTOR_RE = re.compile(r"^(?:when|while|after|before)\s+", re.I)
_RESOURCE_NAME = r"[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*"
_RESOURCE_PREFIX_RE = re.compile(
    rf"(?i:while\s+(?:you\s+)?already\s+have|already\s+have|while\s+holding(?:\s+pre-existing)?|while\s+you\s+have)"
    rf"\s+({_RESOURCE_NAME})")
_RESOURCE_AVAILABLE_RE = re.compile(rf"(?i:have)\s+({_RESOURCE_NAME})\s+(?i:available)\b")
_RESOURCE_ACTIVE_RE = re.compile(rf"({_RESOURCE_NAME})\s+(?i:is\s+active)\b")


def _save_abilities(core: str) -> frozenset[str]:
    """Ability names immediately before "saving throw" (empty when none is named: a bare "saving
    throw" or "the selected saving throw" -- picked elsewhere -- fires on any save)."""
    match = _SAVE_ABILITY_CLAUSE_RE.search(core)
    if not match:
        return frozenset()
    abbreviations = rules()["limits"]["save_abilities"]
    return frozenset(abbr for name, abbr in abbreviations.items() if re.search(rf"\b{name}\b", match.group(1)))


def _damage_types(core: str) -> frozenset[str]:
    """Named damage types anywhere in the trigger (owner 2026-09-26): enforced only for
    damaged/ally_damaged/drop_to_zero/bloodied, where the incoming type is actually known."""
    return frozenset(word.upper() for word in rules()["limits"]["damage_types"] if re.search(rf"\b{word}\b", core))


def _conditions(core: str) -> frozenset[str]:
    """Named conditions anywhere in the trigger, for a condition_gained row."""
    return frozenset(word for word in rules()["limits"]["conditions"] if re.search(rf"\b{word}\b", core))


def _requires_resource(trigger: str) -> str | None:
    """The printed name of a resource/state the reactor must hold (owner 2026-09-26), or None. Just the
    name as printed -- combat/factory_compiler.py resolves it to a real resource id per character."""
    stripped = _LEADING_CONNECTOR_RE.sub("", trigger.strip())
    for pattern in (_RESOURCE_PREFIX_RE, _RESOURCE_AVAILABLE_RE, _RESOURCE_ACTIVE_RE):
        match = pattern.search(stripped)
        if match:
            return match.group(1)
    return None


# A "bearing your <Mark>"/"a marked creature" subject (owner 2026-09-26): the triggering creature must
# carry a mark this reactor placed (combat/typed_executor.py's block_mark). Parsed from the ORIGINAL
# printed trigger, same layer as the limits above -- combat/factory_compiler.py hands the name straight
# to combat/typed_reactions.py's bears_mark, no per-character resolution needed.
_MARK_NAME_RE = re.compile(r"bearing (?:one of )?your ((?:[A-Z][\w'-]*\s*){1,4})"
                           r"(?=\s+(?:hits?|misses?|targets?|makes?|uses?|moves?|deals?|forces?|within|succeeds?|fails?|regains?"
                           r"|dies|drops?|attacks?|casts?|would|ends?|starts?|begins?|enters?|leaves?|takes?)\b|[.,;]|$)")
_MARKED_CREATURE_RE = re.compile(r"\ba marked creature\b|\bwith (?:a|one of your) marks?\b", re.I)
# Step 8 (owner 2026-09-26): "a creature with a Fracture Mark", "with your Tension Mark", "a Resonance Marked creature".
_WITH_MARK_RE = re.compile(r"\bwith (?:a|an|your|one of your) ((?:[A-Z][\w'-]*\s+){1,3}(?:Mark|Trace))s?\b")
_ZONE_LOS_RE = re.compile(r"line of sight passes through your ((?:[A-Z][\w'-]*\s*){1,4})(?=[.,;]|$)")
_NAMED_MARKED_RE = re.compile(r"\b((?:(?!(?:A|An|The)\s)[A-Z][\w'-]*\s+){1,3})Marked (?:creature|target)\b")
# Step 15 (owner 2026-09-26): "Your Marked Star hits you" -- the creature bearing your Star Mark.
_YOUR_MARKED_RE = re.compile(r"\b[Yy]our Marked ([A-Z][\w'-]*)\b(?! (?:creature|target)\b)")


def _requires_mark(trigger: str) -> str | None:
    """The printed mark name a "bearing your X" subject names, "*" for a bare "a marked creature", or
    None when the trigger does not gate on a mark at all."""
    match = _MARK_NAME_RE.search(trigger or "")
    if match:
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        return name[:-1] if len(name) > 1 and name[-1] == "s" and name[-2] != "s" else name
    match = _WITH_MARK_RE.search(trigger or "")
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    match = _NAMED_MARKED_RE.search(trigger or "")
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip() + " Mark"
    match = _YOUR_MARKED_RE.search(trigger or "")
    if match:
        return match.group(1) + " Mark"
    if _MARKED_CREATURE_RE.search(trigger or ""):
        return "*"
    return None


def rules() -> dict[str, Any]:
    mtime = RULES_PATH.stat().st_mtime_ns
    if _CACHE.get("mtime") != mtime:
        _CACHE.update(mtime=mtime, data=json.loads(RULES_PATH.read_text(encoding="utf-8")))
    return _CACHE["data"]


@dataclass(frozen=True)
class TriggerMatch:
    kind: str
    melee_only: bool = False
    ranged_only: bool = False
    requires_sight: bool = False
    range_ft: int | None = None
    # Owner 2026-09-26 ("make sure the mechanics aren't damaged"): limits parsed from the printed
    # trigger that combat can actually check. save_abilities/damage_types/conditions empty means the
    # trigger named none, so the row is unrestricted on that axis (unchanged behavior).
    # requires_resource is the printed NAME only; combat/factory_compiler.py resolves it per character.
    save_abilities: frozenset[str] = frozenset()
    damage_types: frozenset[str] = frozenset()
    conditions: frozenset[str] = frozenset()
    requires_resource: str | None = None
    # Owner 2026-09-26: a specific printed mark name, "*" for any of the reactor's own marks (a bare
    # "marked creature"), or None -- combat/typed_reactions.py's attacked/hit/missed/technique_used
    # hooks enforce it (only kinds where the triggering creature is a fixed, single other actor).
    requires_mark: str | None = None
    requires_zone_los: str | None = None  # named, reactor-owned zone intersecting source-to-subject sight line
    # A reading of the trigger (owner 2026-09-26: "i want all the reactions usable ... we can update the phrasing";
    # authority/typed_mechanics/trigger_readings.jsonl): the limits combat checks for it, beyond the ones above.
    includes_self: bool | None = None       # "you or an ally"; None: the compiler reads the printed phrase
    any_subject: bool = False               # an ally_* kind that answers any creature ("damages a creature other than you")
    allies_only: bool = False               # only allies of the reactor (a willing creature, an ally's technique)
    self_only: bool = False                 # only the reactor (enters YOUR reach)
    mark_on: str = "source"                 # requires_mark is checked on the triggering creature or on the "subject"
    opportunity_only: bool = False          # an attacked row only for an opportunity attack
    teleport_only: bool = False
    min_move_ft: int = 0
    source_within_reach: bool = False       # the damaging creature is within the reactor's reach
    requires_hearing_technique: bool = False  # a spoken technique (one whose targets must hear)
    rolls: frozenset[str] = frozenset()     # creature_d20: attack / save / check
    outcome: str | None = None
    toward: bool = False
    needs: str | None = None                # an effect combat does not have yet; the row is not compiled
    economies: frozenset[str] = frozenset()  # creature_acted: ACTION / BONUS_ACTION / REACTION
    natural: frozenset[int] = frozenset()    # creature_nat: 1 and/or 20
    action: str | None = None               # own_action: dodge / opportunity_attack / paired_strike
    source_name: str | None = None          # own_ability: after the reactor's own named ability fires
    min_cost: int = 0                       # technique_used: the technique costs at least this much
    grappling: bool = False                 # own_turn_start: only while grappling a creature
    reading: str | None = None

    @property
    def runnable(self) -> bool:
        return self.kind in RUNNABLE_KINDS and not self.needs


def _clean(trigger: str) -> str:
    text = _LEADING_WHEN.sub("", trigger.strip()).lower().replace("’", "'")
    text = re.sub(r"\.$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_filters(text: str) -> tuple[str, bool, int | None]:
    sight = bool(_SIGHT_RE.search(text))
    text = _SIGHT_RE.sub("", text)
    match = _RANGE_RE.search(text)
    range_ft = int(match.group(1)) if match else None
    text = _RANGE_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip(), sight, range_ft


_SOURCE_IN_REACH = re.compile(r"^(?:a|an|one|the|any)?\s*(?:hostile |enemy )?(?:creature|enemy|attacker|foe)s?\b[^,.;]{0,40}?\bwithin (?:your )?reach\b")


def classify_trigger(trigger: str | None) -> TriggerMatch:
    """The trigger's canonical kind, plus the filters recorded for it (unsupported if empty/None)."""
    if not trigger or trigger == "None":
        return TriggerMatch(kind="unsupported")
    core, sight, range_ft = _strip_filters(_clean(trigger))
    filters = {"requires_sight": sight, "range_ft": range_ft, "melee_only": "melee" in core, "ranged_only": "ranged" in core,
               "save_abilities": _save_abilities(core), "damage_types": _damage_types(core), "conditions": _conditions(core),
               "requires_resource": _requires_resource(trigger), "requires_mark": _requires_mark(trigger),
               "requires_zone_los": (re.sub(r"\s+", " ", zone.group(1)).strip() if (zone := _ZONE_LOS_RE.search(trigger)) else None),
               # "A creature within your reach misses you" (Hammer Rebuke, Counter Palm; owner playtest 2026-09-29: they
               # answered attacks from across the map): the triggering creature must be within the reactor's reach.
               "source_within_reach": bool(_SOURCE_IN_REACH.match(core))}
    data = rules()
    for kind in data["kind_order"]:
        if any(re.search(pattern, core) for pattern in data["kinds"].get(kind, [])):
            return TriggerMatch(kind=kind, **filters)
    return TriggerMatch(kind="unsupported", **filters)


_SELF_OBJECT = re.compile(r"\b(?:hits|misses|attacks|targets|damages|strikes)\s+you\b", re.I)
_OTHERS_TOO = re.compile(r"\byou or\b|\ballies\b|\ban ally\b|\bwilling creature\b|\bnear to you\b", re.I)
_YOU_OR_ALLY = re.compile(r"\byou or (?:an? |another |one )?(?:ally|allies)\b", re.I)


def _both(match: TriggerMatch, trigger: str | None) -> TriggerMatch:
    """"You or an ally ..." is the ally kind, whose row also answers the reactor's own event
    (includes_self, combat/factory_compiler.py) -- so it covers both (owner 2026-09-26 review)."""
    if match.kind in ("attacked", "hit", "missed", "damaged") and _YOU_OR_ALLY.search(trigger or ""):
        return replace(match, kind=f"ally_{match.kind}")
    return match


_CREATURE_KIND_TEXT = {
    "creature_save_failed": (re.compile(r"\bfails? (?:a|its|the|their) saving throw", re.I), re.compile(r"\byou(?: to)? fail\b", re.I)),
    "creature_save_succeeded": (re.compile(r"\bsucceeds? on (?:a|its|the|their) saving throw", re.I), None),
    # A plain move; a trigger bound to terrain or state combat does not track ("enters your Molten Terrain", "Buried
    # by your Sand talent", "flies") stays unsupported.
    "moved": (re.compile(r"\bmoves\b", re.I),
              re.compile(r"\byour (?:[A-Z][\w'-]* )*(?:Terrain|Spaces?|Line|Mantle|Field|Domain|Zone|Web|Array)\b|\bBuried\b|\bfl(?:y|ies)\b"
                         r"|\bburrows?\b|\bYour (?:[A-Z][\w'-]* )*Target\b")),
    "any_drop_to_zero": (re.compile(r"\b(?:drops? to 0|reduced to 0|dies)\b", re.I), re.compile(r"\bwould (?:drop|be reduced)\b", re.I)),
    "healed": (re.compile(r"\bregains?\b|\btemporary (?:hit points|hp)\b", re.I), None),
}


_UNCHECKED_STATE = re.compile(r"\b(?:that|who) (?:is|are|you (?:damaged|hit|struck))\b|\binvolved in\b", re.I)


READINGS_PATH = Path(__file__).resolve().parents[1] / "authority" / "typed_mechanics" / "trigger_readings.jsonl"
_READINGS: dict[str, Any] = {}
_READING_FIELDS = {"range_ft", "melee_only", "ranged_only", "includes_self", "any_subject", "self_only", "mark_on", "opportunity_only",
                   "teleport_only", "min_move_ft", "source_within_reach", "requires_hearing_technique", "requires_sight", "outcome",
                   "toward", "needs", "requires_mark", "action", "source_name", "min_cost", "grappling"}


def _reading_rows() -> dict[tuple[str, str], dict[str, Any]]:
    mtime = READINGS_PATH.stat().st_mtime_ns if READINGS_PATH.exists() else None
    if _READINGS.get("mtime") != mtime:
        rows = {}
        if mtime is not None:
            for line in READINGS_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    rows[(row["mechanic_id"], row["text_sha256"])] = row
        _READINGS.update(mtime=mtime, rows=rows)
    return _READINGS["rows"]


def _match_from_event(event: dict[str, Any], reading: str) -> TriggerMatch:
    fields = {key: event[key] for key in _READING_FIELDS if key in event}
    return TriggerMatch(kind=str(event["kind"]), reading=reading, allies_only=bool(event.get("allies")),
                        save_abilities=frozenset(event.get("save_abilities") or ()), damage_types=frozenset(str(kind).upper() for kind in event.get("damage_types") or ()),
                        conditions=frozenset(event.get("conditions") or ()), rolls=frozenset(event.get("rolls") or ()),
                        economies=frozenset(event.get("economies") or ()), natural=frozenset(event.get("natural") or ()), **fields)


def declared_reading(mechanic: dict[str, Any]) -> list[TriggerMatch] | None:
    """The record's own reviewed declaration of what its printed trigger means, one TriggerMatch per event,
    or None.

    A typed record may carry ``activation.trigger_reading`` (authority/typed_mechanics/reviewed_final.d):
    the same event shape as a trigger_readings row (``kind`` plus limits such as ``range_ft``,
    ``includes_self`` or ``requires_sight``, and optionally the ``reading`` sentence). A trigger that names
    two events ("targets you with an attack or harmful effect") declares a list, as a trigger_readings row
    does in its ``events`` -- the engine has a separate hook for each. The compiler then knows the engine
    events without reading the printed prose, which matters for the public test copy: its export rewrites
    printed prose into pseudo-words, so a sentence-only trigger classified there would drop the whole
    reaction (and the ability's tests). It is a declaration, not a guess: the owner's sentence stays in
    ``activation.trigger`` for display, and the reviewed reading stays here.
    """
    activation = mechanic.get("activation") or {}
    row = activation.get("trigger_reading")
    rows = row if isinstance(row, list) else [row]
    matches = [_match_from_event(event, str(event.get("reading") or ""))
               for event in rows if isinstance(event, dict) and event.get("kind")]
    return matches or None


def readings_for(mechanic: dict[str, Any]) -> list[TriggerMatch] | None:
    """The reviewed reading of this mechanic's *current* printed trigger (authority/typed_mechanics/trigger_readings.jsonl,
    owner 2026-09-26), one TriggerMatch per event it names; [] for a trigger combat can't observe (manual / zone);
    None when the trigger has no reading (the phrase classifier decides, as before). An edited trigger falls back.

    A declaration in the record itself (``activation.trigger_reading``, :func:`declared_reading`) wins:
    it names the event(s) in typed data, so they survive an export that rewrites the printed sentence."""
    declared = declared_reading(mechanic)
    if declared is not None:
        return declared
    trigger = (mechanic.get("activation") or {}).get("trigger") or ""
    row = _reading_rows().get((str(mechanic.get("mechanic_id")), hashlib.sha256(str(trigger).encode("utf-8")).hexdigest()))
    if row is None:
        return None
    return [_match_from_event(event, row.get("reading") or "") for event in row.get("events") or []]


def classify_mechanic_all(mechanic: dict[str, Any]) -> list[TriggerMatch]:
    """Every trigger kind the reaction answers: its reading's events, else the single classified kind."""
    readings = readings_for(mechanic)
    if readings is None:
        return [classify_mechanic(mechanic)]
    return readings or [TriggerMatch(kind="unsupported")]


def classify_mechanic(mechanic: dict[str, Any]) -> TriggerMatch:
    readings = readings_for(mechanic)
    if readings is not None:
        # A reading (owner 2026-09-26) is deliberate: its first runnable event stands for the reaction.
        return next((match for match in readings if match.runnable), readings[0] if readings else TriggerMatch(kind="unsupported"))
    trigger = (mechanic.get("activation") or {}).get("trigger")
    result = _both(_classify_mechanic(mechanic, trigger), trigger)
    sanity = _CREATURE_KIND_TEXT.get(result.kind)
    if sanity is not None and (not sanity[0].search(trigger or "") or (sanity[1] is not None and sanity[1].search(trigger or ""))
                               or _UNCHECKED_STATE.search(trigger or "")):
        # Step 8 (owner 2026-09-26): the printed trigger must say it ("forces you to fail a saving throw" is not another
        # creature's failed save) and name no state combat cannot check ("a creature that is Off-Rhythm from you").
        return replace(result, kind="unsupported")
    return result


def _classify_mechanic(mechanic: dict[str, Any], trigger: str | None) -> TriggerMatch:
    base = classify_trigger(trigger)
    # Owner 2026-09-26 ("make sure the mechanics aren't damaged"): the reactor's own hit or miss
    # ("After you hit ...") is never an attack on the reactor, whatever the phrase classifier matched.
    reading = _overlay_model_row(mechanic.get("mechanic_id"), trigger)
    if reading is not None and _overlay_own_action(reading) and not base.kind.startswith("own_"):
        return replace(base, kind="unsupported")
    # Owner 2026-09-26: the normalized-trigger overlay (tools/normalize_triggers.py), matched to this
    # mechanic's *current* trigger text.
    row = _overlay_lookup(mechanic.get("mechanic_id"), trigger)
    if row is None:
        return base
    kind = kind_for_event(row["event"], row.get("subject"))
    # A DeepSeek-normalized trigger can correct the phrase classifier (it read the whole trigger); the
    # rule-based rows only fill gaps, and neither turns a working kind into "unsupported".
    if kind == "unsupported" or (base.kind != "unsupported" and not _overlay_from_model(row)):
        return base
    # "A creature within reach misses you" is the reactor's own event: the model reading must not widen it to any ally
    # (owner playtest 2026-09-29: Counter Palm answered a miss on a teammate; Iron Forearm Guard had the same reading).
    if base.kind in ("attacked", "hit", "missed", "damaged") and kind == f"ally_{base.kind}" and _SELF_OBJECT.search(trigger or "") \
            and not _OTHERS_TOO.search(trigger or ""):
        return base
    return replace(base, kind=kind)


def distribution(mechanics: dict[str, Any]) -> dict[str, int]:
    """How many reactions in the authority fall into each trigger kind (owner report)."""
    data = rules()
    counts = {kind: 0 for kind in [*data["kind_order"], "unsupported"]}
    for mechanic in mechanics.values():
        if (mechanic.get("activation") or {}).get("economy") != "reaction":
            continue
        # Owner 2026-09-26: the overlay above can return a kind outside this module's fixed kind_order
        # (a canonical event with no engine hook yet, e.g. "drop_to_zero"); count it too rather than
        # raise, so this report stays the owner's source for which new kinds are worth wiring next.
        match = classify_mechanic(mechanic)
        # A reading whose moment exists but needs an effect combat lacks (Intercepting Strike's attack-off) is not run.
        kind = match.kind if match.runnable or match.kind not in RUNNABLE_KINDS else "unsupported"
        counts[kind] = counts.get(kind, 0) + 1
    return counts
