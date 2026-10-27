"""One-time prose-to-data migration for duration anchors (PRIVCONV3).

The lexer below is frozen from the pre-migration executor. It is authoring-only,
never imported by combat. Run on the normal authority, then rebuild authority.
Re-running is deterministic; --check verifies the committed supplement.
For new/reshaped durations, first run build_typed_mechanics_authority.py with
--unanchored-durations, generate this supplement, then rebuild without that flag.
"""
from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[1]
# The supplement is not a reviewed record: it annotates durations, so it lives
# beside reviewed_final.json, not inside the reviewed_final.d record folder (whose
# files are whole reviewed records with a "mechanics" document).
OUTPUT = APP / "authority/typed_mechanics/duration_anchors.json"

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


def _bounded_to_this_turn(effect: dict[str, Any]) -> bool:
    """Whether the effect's own words bound it to the turn it happens in ("for the rest of the turn", "until the end of the
    current turn"): a shorter statement than any counted or Concentrating lifetime, so it is read even under one."""
    phrase = _turn_phrase(effect)
    return phrase is not None and phrase[0] == "over"


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



def anchor_duration(effect: dict, *, ability: bool = False) -> dict:
    """Snapshot the former runtime decision; never infer a new interpretation."""
    raw = effect.get("duration")
    duration = dict(raw) if isinstance(raw, dict) else {"kind": raw or "instant"}
    # The legacy lexer below fixes the current wording-derived decision.
    duration.pop("edge", None)
    duration.pop("overrides_clock", None)
    kind = str(duration.get("kind") or "").strip().lower()
    turns = {
        "until_start_of_next_turn": ("start", "source"),
        "until_start_of_your_next_turn": ("start", "source"),
        "until_end_of_your_next_turn": ("end", "source"),
        "until_end_of_next_turn": ("end", "holder"),
    }
    phrase = _turn_phrase(effect) if not ability else None
    if phrase:
        edge, who = phrase
        anchor = "current" if edge == "over" else "source" if who == "your" else "holder"
        edge = "end" if edge == "over" else edge
    elif not ability and kind == "special" and re.search(
            r"\btriggering\b", f"{effect.get('on') or ''} {effect.get('evidence') or ''}", re.I):
        edge, anchor = "end", "current"
    else:
        edge, anchor = "", "kind"
    duration["anchor"] = anchor
    if edge and (anchor == "current" or kind not in turns or edge != turns[kind][0]):
        duration["edge"] = edge
    # The old counted-duration exception is an authoring decision, not runtime NLP.
    if not ability and kind in ("rounds", "minutes", "one_minute", "hours", "one_hour", "days") and _own_words_state_one_lifetime(effect):
        duration["overrides_clock"] = True
    return duration


def duration_rows(node, path=()):
    """All durations, including CL-scaled variants, plus previously prose-only effects."""
    if isinstance(node, dict):
        if "duration" in node or (path and "type" in node and _turn_phrase(node)):
            yield path + ("duration",), node, not path
        for key, value in node.items():
            if key == "duration":
                continue
            if key == "duration_by_cl":
                for index, (_low, _high, duration) in enumerate(value):
                    yield path + (key, index, 2), {**node, "duration": duration}, False
            else:
                yield from duration_rows(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from duration_rows(value, path + (index,))


def generate(mechanics):
    records = {}
    counts = Counter()
    ambiguous = []
    for key, mechanic in sorted(mechanics.items()):
        rows = []
        for path, effect, ability in duration_rows(mechanic):
            duration = anchor_duration(effect, ability=ability)
            annotation = {field: duration[field] for field in ("anchor", "edge", "overrides_clock") if field in duration}
            raw = effect.get("duration")
            kind = raw.get("kind") if isinstance(raw, dict) else raw
            rows.append({"path": list(path), "kind": kind or "instant", **annotation})
            counts[annotation["anchor"]] += 1
            phrases = _turn_phrases(effect) if not ability else []
            reasons = []
            if len(phrases) > 1:
                reasons.append("multiple turn phrases; preserved first")
            if phrases and phrases[0][2] not in ("", "your", "its", "their", "his", "her", "the target's", "the target’s",
                                                 "that creature's", "that creature’s", "the creature's", "the creature’s"):
                reasons.append("nonstandard owner word; preserved holder interpretation")
            if reasons:
                ambiguous.append({"record": key, "path": list(path), "reason": "; ".join(reasons)})
        if rows:
            records[key] = rows
    return {"duration_anchors": records}, dict(sorted(counts.items())), ambiguous


def apply_anchors(result: dict, records: dict) -> None:
    """Apply and validate the supplement; shared by the builder and public synthetic tests."""
    for key, rows in records.items():
        for row in rows:
            node = result["mechanics"][key]
            for part in row["path"][:-1]:
                node = node[part]
            field = row["path"][-1]
            raw = node.get(field) if isinstance(node, dict) else node[field]
            duration = dict(raw) if isinstance(raw, dict) else {"kind": raw or "instant"}
            kind = raw.get("kind") if isinstance(raw, dict) else raw
            if (kind or "instant") != row["kind"]:
                raise ValueError(f"Stale duration anchor: {key} {row['path']}")
            duration.update({name: row[name] for name in ("anchor", "edge", "overrides_clock") if name in row})
            node[field] = duration

    def validate(node, location):
        if isinstance(node, dict):
            if "duration" in node:
                duration = node["duration"]
                if not isinstance(duration, dict) or duration.get("anchor") not in {"source", "holder", "current", "kind"}:
                    raise ValueError(f"Missing typed duration anchor: {location}")
            for name, value in node.items():
                if name == "duration_by_cl":
                    for low, high, duration in value:
                        validate({"duration": duration}, f"{location}.duration_by_cl[{low}:{high}]")
                else:
                    validate(value, f"{location}.{name}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                validate(value, f"{location}[{index}]")

    validate(result["mechanics"], "mechanics")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    mechanics = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    data, counts, ambiguous = generate(mechanics)
    # One duration per line keeps this generated supplement reviewable.
    payload = '{\n  "duration_anchors": {\n' + ',\n'.join(
        f'    {json.dumps(key)}: [\n' + ',\n'.join(
            "      " + json.dumps(row, ensure_ascii=False) for row in rows) + '\n    ]'
        for key, rows in data["duration_anchors"].items()) + '\n  }\n}\n'
    if args.check:
        if OUTPUT.read_text() != payload:
            raise SystemExit("Duration anchors are stale; regenerate on the normal copy")
    else:
        OUTPUT.write_text(payload)
    evidence = {"rows": sum(counts.values()), "by_anchor": counts, "ambiguous": ambiguous}
    if args.evidence:
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"rows": sum(counts.values()), "by_anchor": counts, "ambiguous": len(ambiguous)}))


if __name__ == "__main__":
    main()
