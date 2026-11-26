"""The readable name of a condition, for every surface that prints one.

A condition id is a storage key, not a sentence: it carries a namespace
(``condition:typed.``), sometimes a scope (``state.``, ``wenxue.``) and often an
instance or option tail (``...:prepared:3``, ``....actor:factory.4f3a-...``,
``....action_typed_dec5e0a6_weapon_bi``). The fight log used to print the key
itself, which reached players as ``No Temp Hp`` or, once the tail was a number,
as ``Unnamed effect`` -- an internal id dressed up as rules text.

One shared formatter keeps the *name* segment of an id and resolves it through
the owner's own wording:

* :data:`NAMES` first, for the handful of conditions whose slug is not readable
  English;
* then ``condition_text``'s canonical condition table, so an alias such as
  ``suppressed.no_temp_hp`` resolves to the condition it stands for, and the
  compiled authority vocabulary, which is where legacy talents, named pools and
  marks get their printed names;
* otherwise the name segment itself, title-cased with small words left lowercase
  ("court_of_charged_paths" -> "Court of Charged Paths").

Used by ``combat/history_feed.py`` for both the applied and the removed branch of
the fight log, so one condition can never be named two ways. Read-only: it
executes no rules and reads no fight state.

This module resolves the *name* only. What a condition does is
``condition_text``'s business (``zone_readings()``), which the condition pills
and the area reader already share.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

__all__ = ["condition_key", "condition_label"]

# The namespaces a condition id may carry, longest first so "condition:typed." is
# stripped before the shorter "condition:" fallback.
_NAMESPACES = ("condition:typed.", "condition:core.", "condition:")

# Words that stay lowercase inside a printed name, so a name reads as English
# ("Court of Charged Paths", not "Court Of Charged Paths").
_SMALL_WORDS = frozenset(
    "a an and as at but by for from in into is it its nor of on or the to with".split())

# A segment that is bookkeeping rather than a name: a generated option id
# ("action_typed_dec5e0a651_weapon_bi_shou"), a hash, or a copy index.
_NOT_A_NAME = re.compile(
    r"^(?:\d+|action_typed_[0-9a-f]{6,}[a-z_]*|[0-9a-f]{8}(?:-[0-9a-f]{4,})*)$", re.I)

# The owner segment a stamped condition carries: which creature or copy it belongs
# to ("...actor:factory.4f3a-...", "...:prepared:3", "...:2").
_OWNER_SEGMENT = re.compile(
    r"^(?:actor|owner|holder|source|summon|mount|minion|companion|beast\w*|prepared|"
    r"instance|staged|rank|level|index|copy)$", re.I)

# The owner's own wording, for the conditions whose slug is not readable English.
# Each value is a short noun phrase, not a sentence: the log reads
# "<who> applied <this> to <target>", and ``condition_text.READING`` already says
# what the condition does. Keys are the name segment of a condition id (see
# condition_key()).
NAMES = {
    # Void (combat/ext hollowed riders). condition_text.READING: "It can't gain
    # Temporary Hit Points." / "It can't turn Invisible from an ordinary
    # temporary supernatural effect."
    "no_temp_hp": "No Temporary Hit Points",
    "no_invisible": "Cannot Become Invisible",
    # "It can't regain CP (Qi, Stamina, Resonance)." / "It can't benefit from the
    # Dash action." -- the log must not print the bare abbreviation.
    "no_cp_regain": "Cannot Regain Cultivation Points",
    "no_dash": "Cannot Dash",
    # "Something has taken its Reaction until it recovers."
    "reaction_denied": "Reactions Taken Away",
}


def _title(slug: str) -> str:
    """Title-case a slug, leaving small words lowercase unless they lead or end."""
    words = [word for word in re.split(r"[_\-]+", slug) if word]
    if not words:
        return ""
    out = [words[0].capitalize()]
    for word in words[1:]:
        out.append(word.lower() if word.lower() in _SMALL_WORDS else word.capitalize())
    if len(out) > 1 and out[-1].lower() in _SMALL_WORDS:
        out[-1] = out[-1].capitalize()
    return " ".join(out)


def condition_key(condition_id: Any) -> str:
    """The readable segments of a condition id: namespace, owner and option tail removed.

    "condition:typed.qi_storage_talisman:prepared:3"  -> "qi_storage_talisman"
    "condition:typed.state.court_of_charged_paths"    -> "state.court_of_charged_paths"
    "condition:core.dodge"                            -> "dodge"

    A scope prefix ("state.", "wenxue.") is kept here because which segments are a
    scope is the table's business, not this function's: condition_label() narrows the
    segments to the one the tables know, so a scope prefix never reaches a player.

    Returns "" when nothing readable is left (a bare hash or index), which the
    caller reads as "this id names nothing".
    """
    rest = str(condition_id or "").strip()
    for namespace in _NAMESPACES:
        if rest.startswith(namespace):
            rest = rest[len(namespace):]
            break
    else:
        if ":" in rest:  # an id in a namespace this module does not know
            return ""
    rest = rest.split(":", 1)[0]  # "...:prepared:3", "...actor:factory.4f3a-..."
    segments = [segment for segment in rest.split(".") if segment]
    while segments and (_OWNER_SEGMENT.match(segments[-1]) or _NOT_A_NAME.match(segments[-1])):
        segments.pop()
    return ".".join(segments)


def _candidates(key: str) -> list[str]:
    """The key and each of its trailing segments, longest first.

    A scoped id such as "wenxue.hard_draw_ready" or "state.court_of_charged_paths"
    keeps the last segment that the table knows, so the scope prefix never reaches
    a player.
    """
    parts = key.split(".")
    return [key] + [".".join(parts[index:]) for index in range(1, len(parts))]


@lru_cache(maxsize=1)
def _canonical_names() -> dict[str, str]:
    """{condition key: its printed name} for the engine's canonical conditions.

    Built once: it reads the compiled typed-condition rules, which is far too
    expensive to redo for every log line. An alias resolves to the condition it
    stands for, so "suppressed.no_temp_hp" is named like "no_temp_hp".
    """
    from .condition_text import READING
    from .typed_executor import rules

    table = rules().get("conditions") or {}
    aliases = rules().get("condition_aliases") or {}
    names: dict[str, str] = {}
    for key in set(table) | set(aliases) | set(READING):
        canonical = str(aliases.get(key, key))
        titled = _title(canonical)
        if titled:
            names[canonical] = titled
            names.setdefault(key, titled)
    return names


@lru_cache(maxsize=1)
def _authority_names() -> dict[str, str]:
    """{slug: printed name} from the compiled authority vocabulary.

    Legacy talents, named pools and marks carry their printed name only here.
    Imported defensively: a missing vocabulary must not blank the fight log.
    """
    try:
        from .history_text import _vocabulary

        return dict(_vocabulary())
    except Exception:  # pragma: no cover - a broken authority must not break the log
        return {}


def condition_label(condition_id: Any) -> str:
    """The condition's readable name, or "Unnamed effect" when the id names nothing."""
    key = condition_key(condition_id)
    candidates = _candidates(key) if key else []
    for candidate in candidates:
        if candidate in NAMES:
            return NAMES[candidate]
        canonical = _canonical_names().get(candidate)
        if canonical:
            return canonical
        authority = _authority_names().get(candidate)
        if authority and authority != candidate:
            return authority
    # Nothing in the tables knows this name: use the shortest segment that reads
    # as a name, so a scope prefix ("state.", "mark.") is never printed.
    for candidate in reversed(candidates):
        if not _NOT_A_NAME.match(candidate):
            titled = _title(candidate)
            if titled:
                return titled
    return "Unnamed effect"
