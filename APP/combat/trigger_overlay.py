"""Normalized-trigger overlay lookup (owner 2026-09-26): a reversible layer over
combat/reaction_triggers.py's free-text classifier.

Built by tools/normalize_triggers.py (or, while Command Code usage was exhausted, hand-normalized
by the agent -- see each row's "model" field) from
authority/typed_mechanics/trigger_normalization.jsonl. Each row rewrites one mechanic's trigger into
the shared canonical grammar (docs/rules/TRIGGER_NORMALIZATION_REVIEW.md) and records the
DeepSeek/agent-assigned canonical event id, grounded in that mechanic's own trigger text (no invented
numbers, marks, or events -- see tools/normalize_triggers.py's validator).

combat/reaction_triggers.py's classify_mechanic prefers an approved row here, keyed by
(mechanic_id, sha256 of the mechanic's *current* printed trigger) so an edited trigger silently falls
back to the old free-text path until it is renormalized. Rows with confidence "low" or
intent_changed=True are kept in the file (for the owner's review doc) but never used automatically:
"approved" is only true for confidence high/medium with intent_changed False.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

OVERLAY_PATH = Path(__file__).resolve().parents[1] / "authority" / "typed_mechanics" / "trigger_normalization.jsonl"
# DeepSeek V4.1 Flash rewrite (owner 2026-09-26, "let er rip"): takes precedence over the rule-based rows.
DEEPSEEK_PATH = OVERLAY_PATH.with_name("trigger_normalization_deepseek.jsonl")
_CACHE: dict[str, Any] = {}


def from_model(row: dict[str, Any]) -> bool:
    return "deepseek" in str(row.get("model") or "")


import re

# The reactor's own action ("When you hit ...", "After you miss ..."): not an attack on the reactor
# (owner 2026-09-26 check: the rewrite mapped 15 of these to "an attack hits you").
_OWN_ACTION = re.compile(r"^\s*(?:when|after|whenever)\s+you\s+(?:hit|miss|deal|score|make an? (?:attack|weapon))", re.I)
# Clauses combat treats as met: sight/hearing, the reaction's own once-per-round, being conscious.
_BENIGN = re.compile(r"^\s*(?:(?:that |which |if )?you can (?:see|perceive|hear)(?: it)?|once per (?:round|turn)|(?:and )?(?:you )?remain(?:s)? conscious"
                     r"|(?:after|before) (?:damage is rolled|rolling|it is applied|the outcome is known)[^;]*|hostile|from a creature(?: you can (?:see|perceive))?)\s*$", re.I)


# A limit written into the normalized trigger itself that combat still can't check: your own zone /
# reach, a qualifying or bonded creature, a special weapon, a save ability combat has no hook
# for (concentration, death) -- unlike strength/.../charisma below, owner 2026-09-26. Marks ("bearing
# your X"/"marked") are carved out below, the same way save_abilities/damage_types/requires_resource
# were: a checkable limit now, not a blanket disqualifier.
_QUALIFIER = re.compile(
    r"\b(?:concentration|death)\s+sav"
    r"|\b(?:qualifying|eligible|inside your|of your|connected|bound to|willing)\b"
    r"|\bwithin your (?!reach\b|weapon'?s reach\b)[a-z-]+"
    r"|\bfixed\b.*\bscope\b"
    r"|\bwhen an? (?!hostile\b|creature\b|enemy\b)[a-z-]+ creature\b"
    r"|\bwith an? (?!attack\b|melee\b|ranged\b|weapon attack\b)[a-z-]+ (?:weapon|projectile|talent|technique)\b",
    re.I)
# Owner 2026-09-26 ("mark tracking"): a "bearing your <Mark>"/"a marked creature" subject -- combat can
# now check this (combat/typed_executor.py's block_mark, combat/typed_reactions.py's bears_mark) for the
# four kinds whose triggering creature is a single fixed other actor.
_MARK_RE = re.compile(r"\bbearing your\b|\ba marked\b|\bwith a mark\b", re.I)
_MARK_KINDS = frozenset({"attacked", "hit", "missed", "technique_used"})

# Limits combat can now check (owner 2026-09-26, "make sure the mechanics aren't damaged":
# combat/reaction_triggers.py parses these into save_abilities/damage_types/requires_resource, and
# combat/typed_reactions.py's hooks enforce them) -- no longer a blanket disqualifier by themselves.
_SAVE_ABILITY_RE = re.compile(r"\b(?:strength|dexterity|constitution|intelligence|wisdom|charisma)\s+sav", re.I)
_DAMAGE_TYPE_RE = re.compile(r"\b(?:acid|cold|fire|force|lightning|necrotic|poison|psychic|radiant|thunder|bludgeoning|piercing|slashing)\b", re.I)
# Only the on_damage family (combat/typed_reactions.py) is ever handed the incoming damage type; a
# damage type named on any other kind's trigger still can't be checked, so it must still disqualify.
_DAMAGE_TYPE_KINDS = frozenset({"damaged", "ally_damaged", "drop_to_zero", "bloodied"})
_WHILE_RE = re.compile(r"\bwhile\b", re.I)
# "while you have X" / "already have X" / "while holding (pre-existing) X" / "X is active" /
# "have X available" -- the same shape as combat/reaction_triggers.py's _requires_resource, duplicated
# (rather than imported) because that module already imports from this one. _PHRASE (unanchored)
# finds the phrase anywhere inside the full normalized_trigger sentence; _CLAUSE (anchored) matches a
# structured condition/extra_conditions field, which holds nothing but the clause itself.
_RESOURCE_NAME = r"[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*"
_RESOURCE_PHRASE = (
    rf"(?i:while\s+)?(?i:you\s+)?(?i:already\s+)?(?i:have)\s+{_RESOURCE_NAME}"
    rf"|(?i:while\s+)?(?i:holding)(?i:\s+pre-existing)?\s+{_RESOURCE_NAME}"
    rf"|(?i:while\s+)?{_RESOURCE_NAME}\s+(?i:is\s+active)"
    rf"|(?i:have)\s+{_RESOURCE_NAME}\s+(?i:available)\b.*")
_RESOURCE_PHRASE_RE = re.compile(_RESOURCE_PHRASE)
_RESOURCE_CLAUSE_RE = re.compile(rf"^(?:{_RESOURCE_PHRASE})\s*$")


def own_action(row: dict[str, Any]) -> bool:
    return bool(_OWN_ACTION.match(str(row.get("normalized_trigger") or "")))


def _benign_clause(clause: str) -> bool:
    """A clause the row's structured condition/extra_conditions fields carry that combat treats as met
    or now checks (owner 2026-09-26): sight/conscious/etc, or a held-resource phrase."""
    return bool(_BENIGN.match(clause) or _RESOURCE_CLAUSE_RE.match(clause))


def enforceable(row: dict[str, Any]) -> bool:
    """True when combat can honour the whole normalized trigger (owner 2026-09-26: "make sure the
    mechanics aren't damaged").  A dropped qualifier ("while Bloodied", "bearing your Mark") would make
    the reaction fire more often than its rule allows, so such a row is not used; extra alternatives
    ("; or ...") only narrow it and are fine."""
    normalized = str(row.get("normalized_trigger") or "")
    if _OWN_ACTION.match(normalized) or _QUALIFIER.search(normalized):
        return False
    kind = kind_for_event(str(row.get("event") or ""), row.get("subject"))
    if _SAVE_ABILITY_RE.search(normalized) and kind != "save":
        return False
    if _DAMAGE_TYPE_RE.search(normalized) and kind not in _DAMAGE_TYPE_KINDS:
        return False
    if _MARK_RE.search(normalized) and kind not in _MARK_KINDS:
        return False
    if _WHILE_RE.search(normalized) and not _RESOURCE_PHRASE_RE.search(normalized):
        return False
    condition = str(row.get("condition") or "").strip()
    if condition and not _benign_clause(re.sub(r"^while\s+", "", condition, flags=re.I)):
        return False
    for clause in re.split(r";", str(row.get("extra_conditions") or "")):
        clause = clause.strip().rstrip(".")
        if not clause or clause.lower().startswith("or ") or _benign_clause(clause):
            continue
        return False
    return True


def usable(row: dict[str, Any]) -> bool:
    """A rule-based row needs its own approval; a DeepSeek row is used at high or medium confidence even
    when it says it simplified the wording (the owner asked for normalized wording that keeps the
    intent; the review doc lists those first)."""
    if row.get("event") in (None, "", "other"):
        return False  # the grammar's catch-all: nothing for combat to key off
    if not enforceable(row):
        return False
    if from_model(row):
        return str(row.get("confidence") or "") in ("high", "medium")
    return bool(row.get("approved", False))

# Canonical event id -> reaction_triggers.py "kind". attacked/hit/missed/damaged/save are the kinds
# runnable today (RUNNABLE_KINDS); the rest keep their own name rather than folding into an existing
# kind, so the owner's distribution report shows real counts once an engine hook exists for them
# (owner 2026-09-26: "so the other agent's new kinds can be wired"). "other" -- the grammar's explicit
# catch-all for wording it cannot express -- maps to "unsupported", matching the old classifier's
# default for anything it does not recognize.
EVENT_TO_KIND = {
    "attacked": "attacked",
    "hit": "hit",
    "missed": "missed",
    "damaged": "damaged",
    # save_made and save_failed both land on the classifier's one existing "save" kind (its regexes
    # already treat "you fail a saving throw" and "you make a saving throw" the same way); a
    # bare "succeeds" is new behavior with no engine hook yet, so it keeps its own name.
    "save_made": "save",
    "save_failed": "save",
    "save_succeeded": "save_succeeded",
    "drop_to_zero": "drop_to_zero",
    "bloodied": "bloodied",
    "condition_gained": "condition_gained",
    "technique_targets": "technique_targets",
    "technique_used": "technique_used",
    "critical_hit": "critical_hit",
    "natural_1": "natural_1",
    "moved": "moved",
    "own_action": "own_action",
    "other": "unsupported",
}


def trigger_hash(trigger: str | None) -> str:
    return hashlib.sha256((trigger or "").strip().encode("utf-8")).hexdigest()


def _load() -> dict[tuple[str, str], dict[str, Any]]:
    mtime = tuple(path.stat().st_mtime_ns if path.is_file() else None for path in (OVERLAY_PATH, DEEPSEEK_PATH))
    if _CACHE.get("mtime") != mtime:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for path in (OVERLAY_PATH, DEEPSEEK_PATH):  # later file wins: DeepSeek over rule-based
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        row = json.loads(line)
                        rows[(row["mechanic_id"], row["text_sha256"])] = row
        _CACHE.update(mtime=mtime, rows=rows)
    return _CACHE["rows"]


def lookup(mechanic_id: str | None, trigger: str | None) -> dict[str, Any] | None:
    """The approved normalization row for this mechanic's *current* trigger text, or None.

    None if there is no row, the row is not approved, or the stored hash no longer matches
    ``trigger`` (the owner edited the printed trigger since it was normalized).
    """
    if not mechanic_id:
        return None
    row = _load().get((mechanic_id, trigger_hash(trigger)))
    if row is None or not usable(row):
        return None
    return row


_ALLY_KINDS = {"attacked": "ally_attacked", "hit": "ally_hit", "missed": "ally_missed", "damaged": "ally_damaged"}
_GENERIC_CREATURES = {"a creature", "a hostile creature", "one creature", "an enemy", "another creature", "a creature you can see",
                      "a creature you can perceive", "a hostile creature you can see", "any creature"}


def model_row(mechanic_id: str | None, trigger: str | None) -> dict[str, Any] | None:
    """The DeepSeek row for this mechanic's current trigger, used or not (it also tells the phrase
    classifier when a trigger has a limit combat can't check)."""
    row = _load().get((mechanic_id or "", trigger_hash(trigger)))
    return row if row is not None and from_model(row) else None


def kind_for_event(event: str, subject: str | None = "you") -> str:
    """The runnable kind for a normalized trigger.  The subject matters (owner 2026-09-26 merge review):
    "an ally takes damage" is the ally hook, not the reactor taking damage; triggers about other,
    unidentified creatures stay unsupported. A creature "bearing your Mark" or "marked" is tracked now
    (combat/typed_executor.py's block_mark) for the four kinds whose triggering creature is a single
    fixed other actor -- combat/typed_reactions.py's bears_mark enforces it at runtime."""
    who = str(subject or "you").strip().lower()
    if who in ("", "you"):
        return EVENT_TO_KIND.get(event, "unsupported")
    if who.startswith("an ally") or who.startswith("you or an ally"):
        return _ALLY_KINDS.get(event, "unsupported")
    if event in ("attacked", "hit", "missed") and _MARK_RE.search(who):
        return EVENT_TO_KIND[event]
    # Step 8 (owner 2026-09-26): any creature in range -- typed_reactions offers a harmful reaction only against a
    # hostile creature and a helpful one only for you or an ally.
    creature = who in _GENERIC_CREATURES or who.startswith("a creature within") or who.startswith("one creature within")
    if creature and event in _ALLY_KINDS:
        return _ALLY_KINDS[event]
    if creature and event == "moved":
        return "moved"
    if (creature or _MARK_RE.search(who)) and event == "drop_to_zero":
        return "any_drop_to_zero"
    if (creature or _MARK_RE.search(who)) and event in ("save_failed", "save_succeeded"):
        return "creature_" + event
    # "a creature / a hostile creature uses a technique" only: marked, willing or specific creatures need
    # state combat doesn't track, and the hook answers hostile techniques.
    if event == "technique_used" and (who in ("a creature", "a hostile creature", "one creature", "an enemy") or _MARK_RE.search(who)):
        return EVENT_TO_KIND[event]
    return "unsupported"
