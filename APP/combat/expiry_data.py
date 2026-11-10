"""Expiry derivation shared by the authority builder, rider converter and code-built effect producers.

Runtime readers require expiry_turn and never interpret prose. A null value
means the producer derived no turn answer; absence means an unconverted effect.
Non-null values carry edge/who plus the legacy overrides_counted and triggering
decisions. Duration expiry.scene and terrain_kind are also derived at build time.
expires_on, duration kinds, amounts and runtime anchoring retain their meanings.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_APOS = "(?:'|’)s"
_WHOSE = rf"(?P<who>your|its|their|his|her|the \w+{_APOS}|that \w+{_APOS})"
_LEAD = r"(?:until|before|expires at|ends at)"
_TURN_PHRASES = (
    ("end", re.compile(rf"\b{_LEAD} the end of {_WHOSE} (?:next|following) turn\b", re.I)),
    ("start", re.compile(rf"\b{_LEAD} (?:the start of )?{_WHOSE} (?:next|following) turn\b", re.I)),
    ("over", re.compile(r"\b(?:(?:until|before) the end of (?:the current|this|that|the|your|its|their)|(?:for )?the rest of (?:the|this|that)"
                        r"(?: current)?) turn\b", re.I)),
)


def _turn_phrases(effect: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Every turn lifetime the effect's own words name, as (where it starts, edge, whose), in the order they are written.
    Edge "start", "end" or "over" ("until the end of the turn"); whose "your" or another owner word ("its", "the target's")."""
    for field_name in ("evidence", "on"):
        text = re.sub(r"\s+", " ", str(effect.get(field_name) or ""))
        found = [(match.start(), edge, (match.groupdict().get("who") or "").lower())
                 for edge, pattern in _TURN_PHRASES for match in pattern.finditer(text)]
        if found:
            return sorted(found)
    return []


def _turn_phrase(effect: dict[str, Any]) -> tuple[str, str] | None:
    """(edge, whose) of the first "until the start / end of <whose> next turn" in the effect's own words: edge "start", "end" or
    "over" ("until the end of the turn"); whose "your" or another owner word ("its", "the target's"). None when it names none."""
    found = _turn_phrases(effect)
    return (found[0][1], found[0][2]) if found else None


# One effect's own words can describe more than one effect at once, so a turn phrase in them is not necessarily this effect's.
# These read that shape: _STATEMENT_SPLIT separates the sentences (or "; " clauses) of a quote, _A_CLAUSE_PAIR is the boundary
# between two clauses however it is punctuated (", and" or an " and " with no comma), _A_COUNTED_LIFETIME is a length stated in
# the same words, and _adds_a_second_effect says whether a later sentence, or a clause joined to this one, says that
# something else happens besides this effect.
_STATEMENT_SPLIT = re.compile(r"[.;]\s+")
_A_CLAUSE_PAIR = re.compile(r"(?:,\s*|\s+)(?:and|then|but|while)\s+", re.I)
_SPELLED_OUT_NUMBER = (r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty"
                       r"|a few|an?|another|several")
_A_COUNTED_LIFETIME = re.compile(rf"\b(?:{_SPELLED_OUT_NUMBER})\s+(?:full\s+|extra\s+)?(?:rounds?|minutes?|hours?|days?)\b"
                                 rf"|\bfor the next (?:round|minute|hour)\b", re.I)

# Words added after the lifetime are a *limit* on the effect already stated, not a further effect, when their predicate states
# a floor or a ceiling ("This cannot reduce Speed below 0.", "... but cannot be reduced below 0", "at least 0 feet"). A floor
# or a ceiling is a bound on a number, so it is the only thing a limit needs to be one: read in either order, a bound before
# the predicate ("below 0 feet") or after it ("cannot reduce Speed below 0"). A predicate that asserts a state before it
# limits something is a new statement about the creature ("It is also Poisoned.", "its Speed is reduced", "gains
# Disadvantage on saves"), and a name written with a capital in the middle of a sentence is one ("Poisoned", "Disadvantage on
# saves"). Nothing here knows an ability, an effect type or a stat -- only what a floor and a ceiling are made of, and that
# one penalty with a floor is still one penalty.
_A_BOUND = re.compile(r"\b(?:below|above|under|minimum|maximum|no\s+more\s+than|no\s+less\s+than|at\s+least|at\s+most"
                      r"|instead\s+of|rather\s+than|only\s+to|down\s+to|up\s+to)\b", re.I)
# The negations a clause can state: "cannot", "is not", "no longer". A negation is not a limit by itself -- one that stops
# the creature doing something instead is a further effect, quoted beside this one: "Speed is reduced by 10 feet for the
# rest of the turn and it cannot take Reactions." carries two effects, so the row's own counted clock must stand
# (PRO15r4 review, finding 1). What it limits is decided by _names_the_effect_this_speaks_of.
_A_KEEPS = re.compile(r"\b(?:cannot|can\s+not|can't|may\s+not|is\s+not|are\s+not|does\s+not|do\s+not|has\s+not|have\s+not"
                      r"|will\s+not|does\s+never|never|no\s+longer|not)\b", re.I)
# What opens a fresh statement about the creature: a subject of its own ("It", "its Speed", "the target"), a predicate with
# the subject it follows ("and gains Disadvantage on saves"), or a capitalised name in the middle of a sentence. A
# coordination inside one noun phrase opens none of them ("Its walking and flying Speed are reduced by 10 feet"), so it is
# still one effect.
_OPENS_A_STATEMENT = re.compile(r"^(?:this|that|it|they|them|these|those|he|she|you|its|their|his|her|your|the|a|an)\b"
                                r"|^(?:is|are|am|become|becomes|gain|gains|lose|loses|has|have)\b", re.I)
_OPENS_WITH_A_NAME = re.compile(r"^[A-Z][a-z]")
# A predicate can be led by the effect's own name, written with a capital or not ("This reduction cannot reduce Speed below
# 0", "This Speed reduction cannot ..."), so up to two words between a subject and its predicate are read past. A word that
# joins two clauses, or that states something in its own right, stops the scan: that is a further effect, not a limit
# ("It is also Poisoned and cannot be cured").
_STOPS_A_PREDICATE = re.compile(r"^(?:and|or|but|then|while|because|so|which|also|gains?|loses?|becomes?|has|have|does|do"
                                r"|will|can|could|may|might)\b", re.I)
_ORDINARY_WORD = re.compile(r"^[A-Za-z]+$")
_EDGE_OF_A_WORD = str.maketrans("", "", ".,;:!?\"'()")
# A passive verb carries the subject it was built on, so a negated one speaks about the thing that was already said ("cannot
# be reduced"); a plain verb and its object is the creature losing something else.
_A_PASSIVE = re.compile(r"\bbe\s+(?:not\s+)?\w+(?:ed|en)\b", re.I)
# An adverb says how much, how often or how well, never what is done, so the verb behind it is still the verb of the clause.
# Printed rules set one in front of the verb ("cannot be further reduced", "cannot further reduce Speed below 0"); taking
# it for the verb would name the clause after it, and so refuse the floor it states. This is one closed class of English
# adverbs, not a list of ability names, and it is only ever read past -- never treated as the verb itself.
_AN_ADVERB_BEFORE_A_VERB = re.compile(
    r"^(?:further|furthermore|more|less|again|also|even|only|still|ever|already|hereafter|thereafter|instead|otherwise"
    r"|likewise|anymore|thus|hence|well)$", re.I)
# A word short enough to be shared by half the printed rules ("the", "its", "not", "10") names nothing on its own, so it can
# never be what says two passages are about the same thing.
_TOO_SHORT_TO_NAME_SOMETHING = 4
# "-ing" as a present participle drops a silent e and doubles a final consonant, so "reduce"/"reducing", "move"/"moving",
# "take"/"taking" and "dispel"/"dispelling" are one word whose stem is spelled three different ways.
_THE_PRESENT_PARTICIPLE = "ing"


def _the_same_word(one: str, other: str) -> bool:
    """Whether two words are one word written two ways -- a base and its inflection, "reduce"/"reduced", "reduce"/"reducing",
    "move"/"moving", "dispel"/"dispelling": the shorter leads the longer, or the longer is the shorter's present participle,
    and the shorter is long enough to be a word of its own."""
    shorter, longer = sorted((one, other), key=len)
    if len(shorter) < _TOO_SHORT_TO_NAME_SOMETHING:
        return False
    return longer.startswith(shorter) or _is_that_word_a_participle(shorter, longer)


def _is_that_word_a_participle(base: str, word: str) -> bool:
    """Whether ``word`` is ``base`` written as a present participle: "reduce"/"reducing", "move"/"moving", "take"/"taking",
    "dispel"/"dispelling". Adding "-ing" drops a silent e ("reduc" + "ing", "mov" + "ing") or doubles a final consonant
    ("dispell" + "ing"), so the stem is compared against the base with either of those done to it. Nothing here names an
    ability, an effect type or a stat -- only how English spells a participle."""
    if not word.endswith(_THE_PRESENT_PARTICIPLE) or len(word) < _TOO_SHORT_TO_NAME_SOMETHING:
        return False
    stem = word[: -len(_THE_PRESENT_PARTICIPLE)]
    return stem == base[:-1] or stem.startswith(base) or stem == base + base[-1]


def _the_verb_of(predicate: str) -> str:
    """The verb of ``predicate`` -- the words a denial governs -- as the one word that says what it is done to: the word
    after "be" when the predicate is passive ("be reduced"), otherwise the first word ("reduce Speed below 0"), reading
    past an adverb that stands in front of it ("be further reduced", "further reduce"). One word, because the verb is what
    says what a clause is about and the rest of the clause does not."""
    words = _words_of(predicate)
    if len(words) > 1 and words[0] == "be":
        words = words[1:]
    return next((word for word in words if not _AN_ADVERB_BEFORE_A_VERB.match(word)), "")


def _speaks_of_this_effect(predicate: str, said: str) -> bool:
    """Whether the verb of ``predicate`` is a word ``said`` -- the sentence that states the effect -- already uses, written
    as a base or as an inflection of it ("reduce"/"reduced", "reduce"/"reducing", "move"/"moved", "move"/"moving"). A limit
    has to be about the very thing that was stated, and a verb is what says what a clause is about: so a floor on this
    effect ("cannot reduce Speed below 0", "cannot be further reduced below 0") speaks of it, and a restriction on something
    else ("cannot be healed", "cannot be moved above 10 feet from the ground") does not, however much else the two
    passages share.

    The verb is read through the words that do not name what is done to anything -- the adverb in front of it ("cannot be
    further reduced", "cannot further reduce Speed below 0") -- and matched against the participles a sentence may print
    instead of its verb ("This is reducing Speed by 10 feet ... cannot reduce Speed below 0"), because a floor is still the
    same floor whichever of the two ways it is written, and the effect it bounds is still that same Speed.

    The numbers and nouns a restriction quotes are deliberately not evidence. "The target cannot be moved above 10 feet from
    the ground" beside "Speed is reduced by 10 feet" shares every number and every noun it has and is still about the
    target's height rather than this effect. Where the predicate does not name the effect, whether it is a limit on it or a
    second effect beside it is not stated by the words, and the row's own counted kind is kept (PRO15r5 review, finding 1).
    Nothing here names an ability, an effect type or a stat -- only whether two sentences use the same word."""
    verb = _the_verb_of(predicate)
    return bool(verb) and any(_the_same_word(verb, word) for word in _words_of(said))


def _names_the_effect_this_speaks_of(words: list[str], said: str) -> bool:
    """Whether ``words`` -- what is left of a clause once its negation is read -- is about the effect already stated, rather
    than about something else the creature is forbidden to do. It is about that effect when its own verb says so
    (``_speaks_of_this_effect``) *and* its predicate states a bound on it: a bound is a bound on a number ("cannot reduce
    Speed below 0"), and a passive is that same verb carrying the bound ("cannot be reduced below 0"). A plain verb and its
    object is the creature losing something else, which is a further effect."""
    if not words:
        return True  # a bare negation bounds nothing, but names no other effect either
    predicate = " ".join(words)
    if not _speaks_of_this_effect(predicate, said):
        return False  # its verb is not this effect's verb, so how far it limits that effect is not stated
    return _A_BOUND.search(predicate) is not None or _A_PASSIVE.match(predicate) is not None


def _adds_a_second_effect(clause: str, said: str) -> bool:
    """Whether ``clause`` -- a sentence or an "and" / "then" / "but" / "while" clause following this effect's lifetime --
    says something else happens, rather than limiting the effect already stated in ``said``. One general lexical test, shared
    by every counted row: a later sentence or clause is a further effect when it opens a statement of its own and its
    predicate is not a limit ("It is also Poisoned.", "The court ends.", "it cannot take Reactions."), and part of the same
    effect when it limits that effect ("This cannot reduce Speed below 0.", "This reduction cannot reduce Speed below 0.") or
    joins words inside one phrase ("walking and flying Speed"). A clause with no subject of its own only adds an effect when
    it denies the creature something, which it can only mean besides this one ("... and cannot take Reactions")."""
    opening = _OPENS_A_STATEMENT.match(clause) or _OPENS_WITH_A_NAME.match(clause)
    head = clause if opening is None else clause[opening.end():]
    if _is_a_limit(head, said):
        return False
    if opening is not None:
        return True
    # No subject of its own: a noun phrase or a verb joining words inside this effect's own sentence ("Its walking and
    # flying Speed are reduced by 10 feet") is part of it, and a denial that named this effect was read as a limit above.
    # What is left denies the creature something of its own, and so is a further effect.
    words = _words_of(head)
    denial = _A_KEEPS.match(" ".join(words))
    return denial is not None and not _names_the_effect_this_speaks_of(words[len(denial.group(0).split()):], said)


def _is_a_limit(head: str, said: str) -> bool:
    """Whether the words after a subject state a bound on this effect -- a floor, a ceiling, or a negation that keeps to
    this effect ("cannot reduce Speed below 0", "cannot be reduced below 0"). The effect may be named between the subject
    and its predicate ("This reduction cannot reduce Speed below 0"), so up to two words are read past first; a word that
    joins clauses or states something of its own stops the scan and is not a limit. What it bounds decides the rest: a
    predicate whose verb is not this effect's own bounds nothing here that the words state."""
    text = head.strip()
    words = _words_of(text)
    for index in range(min(3, len(words))):
        denial = _A_KEEPS.match(" ".join(words[index:]))
        if denial is not None:
            return _names_the_effect_this_speaks_of(words[index + len(denial.group(0).split()):], said)
        if _STOPS_A_PREDICATE.match(words[index]) or not _ORDINARY_WORD.match(words[index]):
            return False
    return False


def _words_of(text: str) -> list[str]:
    """The words of ``text``, stripped of the punctuation that ends them, so a participle is read as a participle whether it
    ends the clause ("reduced.") or comes before another word ("reduced by 10 feet")."""
    return [word.translate(_EDGE_OF_A_WORD).lower() for word in text.split() if word.translate(_EDGE_OF_A_WORD)]


def _own_words_state_one_lifetime(effect: dict[str, Any]) -> bool:
    """Whether the effect's own words name a turn lifetime *for this effect and nothing else*, so the words, not a coarser
    counted ``duration`` kind, decide how long it lasts (P20261005-15).

    A counted kind is the row's own reviewed lifetime, and one printed sentence routinely describes several effects: Heaven's
    Roar's Deafened reads "Deafened for 1 minute, and Disadvantage on Concentration saving throws until the end of your next
    turn", so the turn phrase there is a sibling effect's and the minute must stand. That is why this is a test about the
    *shape* of the words, not about whose turn they name: a quote that describes one effect and one lifetime only -- no second
    clause, no second lifetime, no length named beside the turn -- is read as this effect's own words, whether the phrase is
    ownerless ("for the rest of the turn") or owned ("until the start of its next turn"). A printed "for the rest of the turn"
    must not last ten rounds because the typed kind said ``one_minute``.

    Every way the words can carry more than one effect or one lifetime is refused, however it is punctuated (review
    2026-10-05, finding 1): two turn lifetimes in one quote ("Disadvantage until the start of its next turn and Speed reduced
    for the rest of the turn") are two effects', a length spelled out rather than written in digits beside the turn ("Poisoned
    for two minutes and its Speed is reduced until the start of its next turn") is a second lifetime, and the lifetime
    itself sitting in a later sentence than the effect it belongs to is the rider's.

    A sentence or a joined clause after the lifetime is part of that one description when it limits this effect, and a
    further effect when it says something else happens (review findings 1 and 2, PRO15r3): "This cannot reduce Speed below
    0.", "... but cannot be reduced below 0." and "Its walking and flying Speed are reduced by 10 feet" are one penalty --
    with a floor, or one Speed -- and keep the lifetime in the words, while "It is also Poisoned." is a second effect and the
    counted kind is kept. A row whose printed wording really is short is corrected in the typed data (its own ``duration``),
    not guessed from wording here. Every counted row whose words name a turn is such a sibling quote (P20261005-15 census,
    re-read after this change), so the exception changes no shipped ability.

    A limit must also *refer back* to that one effect (PRO15r4 review, findings 1 and 2), which is what its own words have to
    show, not merely that a negation is there, and it must show it with its own verb (PRO15r5 review, finding 1): the verb of
    the words a denial governs has to be a word this effect's own sentence already uses, written as a base or as an
    inflection of it. So the lifetime stays in the words for "This cannot reduce Speed below 0" and for "Its Speed cannot be
    reduced below 0", however the effect is named before its predicate ("This reduction cannot reduce Speed below 0") and
    whichever subject is put in front of it. A passive carries the subject it was built on and a bound bounds only the number
    it is written beside, so a restriction on the creature beside this effect is a further effect and its counted kind is
    kept -- "The target cannot be healed.", "and its wounds cannot be healed", "It cannot take Reactions.", and even
    "The target cannot be moved above 10 feet from the ground", whose numbers and nouns are this effect's own. Where the
    words do not say whether a clause limits this effect or states another beside it, the row's reviewed counted kind is what
    ends it, which is the conservative reading in both directions.

    Reading that verb means reading through the words in front of it that do not name what is done to anything, and matching
    the participles a sentence may print in place of its verb (PRO15r6 review, finding 1). "Its Speed cannot be further
    reduced below 0" puts an adverb in front of the passive, "This cannot further reduce Speed below 0" in front of the plain
    verb, and "This is reducing Speed by 10 feet for the rest of the turn. This cannot reduce Speed below 0." writes the
    effect itself as a participle. All three state one Speed penalty with a floor on it, so all three keep the lifetime in
    the words; taking the adverb or the participle for the verb named the clause after the wrong word and read the floor as a
    second effect, which lasted the row's counted ten rounds -- or a whole Concentration -- instead of the stated turn. The
    floor side is unchanged by reading them through: a restriction on the creature beside the effect still names another
    verb and still keeps its counted kind.
    """
    for field_name in ("evidence", "on"):
        text = re.sub(r"\s+", " ", str(effect.get(field_name) or "")).strip()
        phrases = _turn_phrases({field_name: text})
        if not phrases:
            continue
        if len(phrases) > 1 or _A_COUNTED_LIFETIME.search(text):
            return False  # more than one lifetime: the counted kind is the row's reviewed lifetime
        statements = [part.strip() for part in _STATEMENT_SPLIT.split(text) if part.strip()]
        if phrases[0][0] >= len(statements[0]):
            return False  # the lifetime is in a later sentence, so it is the rider's and not this effect's
        said = statements[0]  # the sentence that states the effect; every added clause is read against it
        parts = [part.strip() for part in _A_CLAUSE_PAIR.split(said) if part.strip()]
        # A clause that was joined to this sentence is read against the sentence with itself taken out, so that "its wounds
        # cannot be healed" cannot be the echo of its own "healed" rather than of the Speed penalty's "reduced".
        added = [(part, said) for part in statements[1:]] + [(part, said.replace(part, " ", 1)) for part in parts[1:]]
        return not any(_adds_a_second_effect(part, beside) for part, beside in added)
    return False

_SCENE_TEXT = re.compile(r"\bscene\b", re.I)
_TRIGGERING = re.compile(r"\btriggering\b", re.I)


@lru_cache(maxsize=8192)
def _derive_expiry(evidence: str, on: str, duration_text: str) -> tuple:
    """Lexical decisions used only by the producer derivation APIs below."""
    effect = {"evidence": evidence, "on": on}
    phrase = _turn_phrase(effect)
    turn = (phrase[0], "source" if phrase[1] == "your" else "holder") if phrase else None
    # The compiler synthesizes changed-ground effects from a sentence. Its
    # historical vocabulary is deliberately narrower than ordinary effect turns.
    if re.search(r"until the end of your next turn", evidence, re.I):
        terrain_kind = "until_end_of_next_turn"
    elif re.search(r"until the end of (?:the current|this|your) turn", evidence, re.I):
        terrain_kind = "turn"
    elif re.search(r"until the start of your next turn", evidence, re.I):
        terrain_kind = "until_start_of_next_turn"
    else:
        terrain_kind = "scene"
    return (turn, _own_words_state_one_lifetime(effect),
            bool(_TRIGGERING.search(f"{on} {evidence}")),
            bool(_SCENE_TEXT.search(duration_text)), terrain_kind)


def derive_expiry_turn(row: dict[str, Any]) -> dict[str, Any] | None:
    """Derive a producer's own evidence/on, never an executor fallback."""
    turn, own, triggering, _scene, _terrain = _derive_expiry(
        str(row.get("evidence") or ""), str(row.get("on") or ""), "")
    result: dict[str, Any] = {}
    if turn:
        result.update(edge=turn[0], who=turn[1])
    if own:
        result["overrides_counted"] = True
    if triggering:
        result["triggering"] = True
    return result or None


def require_expiry_turn(row: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    """Require producer metadata; shared by executor and saved-bundle validation."""
    if "expiry_turn" not in row:
        raise ValueError(f"effect {row.get('type', '(unspecified)')} from {source_id}: missing expiry_turn")
    return row["expiry_turn"]


def require_duration_expiry(duration: dict[str, Any], source_id: str) -> dict[str, Any]:
    """Require special-duration metadata at executor and saved-bundle boundaries."""
    if str(duration.get("kind") or "").strip().lower() != "special":
        return {}
    if "expiry" not in duration:
        raise ValueError(f"duration special from {source_id}: missing expiry")
    return duration["expiry"]


def derive_expiry(row: dict[str, Any], *, duration: bool = False, terrain: bool = False) -> dict[str, Any]:
    """Build one effect/duration record without mutating the input; explicit data wins."""
    if duration:
        if "expiry" in row:
            return row
        scene = _derive_expiry("", "", str(row.get("text") or ""))[3]
        return {**row, "expiry": {"scene": True} if scene else {}}
    result = row if "expiry_turn" in row else {**row, "expiry_turn": derive_expiry_turn(row)}
    if terrain:
        result = {**result, "expiry": {"terrain_kind": _derive_expiry(
            str(row.get("evidence") or ""), str(row.get("on") or ""), "")[4]}}
    return result


def seal_expiry_data(node: Any, *, duration: bool = False, refresh: bool = False) -> None:
    """Seal authority and shipped rules effects/durations in place, including nested rows.

    Shared by the authority build, rules-file producer pass and fixture authors,
    never runtime resolution: walking all
    containers covers zone triggers, modifiers, options and nested save/attack
    outcomes without an ability-specific list. Shipped rules use refresh=True:
    their seals are generated output, unlike explicit authority overrides.
    """
    if isinstance(node, list):
        for child in node:
            seal_expiry_data(child, refresh=refresh)
    elif isinstance(node, dict):
        for key, child in list(node.items()):
            if key == "expiry":
                continue
            if key == "duration_by_cl":
                for _low, _high, length in child or []:
                    seal_expiry_data(length, duration=True, refresh=refresh)
            else:
                seal_expiry_data(child, duration=key == "duration", refresh=refresh)
        if "type" in node:
            if refresh:
                node.pop("expiry_turn", None)
            node.update(derive_expiry(node))
        if duration:
            if refresh:
                node.pop("expiry", None)
            node.update(derive_expiry(node, duration=True))
        if "mechanic_id" in node:
            seal_terrain_expiry(node)


def seal_terrain_expiry(mechanic: dict[str, Any]) -> None:
    """Seal compiler-synthesized terrain lifetimes at the builder/converter seam.

    The compiler's existing area/choice text selection is shared, so an option's
    duration is derived from exactly its own ground sentence, not a sibling's.
    Runtime terrain discovery reads only this sentence-to-kind table.
    """
    from .factory_compiler import _left_terrain, _printed_choices, _texts

    menu = _printed_choices(mechanic)
    readings = [_texts(mechanic)]
    labels = {str(option.get("label") or "").strip().lower()
              for option in mechanic.get("options") or [] if isinstance(option, dict)}
    readings += [_texts(mechanic, shared_zone=True, own_choice=choice, choices=menu)
                 for choice in [None, *sorted(menu | labels)]]
    durations = {}
    for text in readings:
        ground = _left_terrain(text)
        if ground:
            sentence = ground["sentence"]
            durations[sentence] = derive_expiry({"evidence": sentence}, terrain=True)["expiry"]["terrain_kind"]
    if durations:
        mechanic.setdefault("duration", {})["terrain_expiry"] = durations
    elif isinstance(mechanic.get("duration"), dict):
        mechanic["duration"].pop("terrain_expiry", None)
