"""The one cleaner for every word the player reads.

Owner 2026-09-30: player text must read plainly for someone who knows nothing
but basic D&D. A fight audit (HUNT100) found the same build detail leaking to
the player through several builders that each had their own idea of "plain", so
this module is the single place that removes it and every builder routes here:

* ``status_text.plain``            -- button hovers, sheet entries, status cards
* ``condition_text.all_conditions`` -- the condition-pill hover catalogue
* ``tools/newcomer_text_data``     -- the resource-reference catalogue
* ``history_text.rider_text``      -- battle-log reminders
* ``history_feed``                 -- battle-log lines

It is read-only: it never changes a rule, a cost, a die or engine state, and it
never drops a mechanical sentence. It removes *build* detail (source files,
factory routing codes, developer notes) and turns Python literals and jargon
into plain wording, so a printed rule keeps its meaning and its exceptions.

Two surfaces, because one suppression belongs to only one of them:

* ``clean`` / ``plain`` / ``reading`` -- hovers, cards, reference catalogues. A
  Cultivation Level damage table stays here: it is the rule, and a card that
  says "deal the damage below" has to show what "below" is.
* ``log_text`` / ``log_plain`` -- the fight log, where the same table is a
  lookup the player cannot roll, so the run of bands goes.

Each rule is deliberately general: nothing here is keyed on an ability id, a
character, or a sphere, so a new plug-in is cleaned without touching this file.
"""
from __future__ import annotations

import re
import json
from pathlib import Path
from functools import lru_cache
from typing import Any

from factory_authoring.player_rules import display_prose, RAW_ID

SOURCE_RECORD_ID = re.compile(r"\btianxia\.[a-z_]+\.[\w.#-]*[\w#-]")


@lru_cache(maxsize=1)
def _display_evidence() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1] / "authority/typed_mechanics"
    path = root / "player_text.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = json.loads((root / "rules_text.json").read_text(encoding="utf-8"))
    return {**{raw: data["records"][key] for key, raw in sources.items() if key in data["records"]},
            **data.get("evidence", {})}


def reviewed_wording(text: str) -> str | None:
    """The owner's reviewed player wording for an exact raw evidence sentence, or None.

    Callers that pre-process raw evidence (``condition_text.plain_reading``) ask here first, so
    an owner edit always wins over the cleaner instead of being matched against text the cleaner
    already rewrote.
    """
    return _display_evidence().get(text)


def display_text(text: str) -> str:
    """Resolve builder-authored display wording without modifying saved evidence.

    Unrecognized legacy prose uses the same field projection. Runtime diagnostics
    stay in raw events and server logs; they are not rules or player decisions.
    """
    if re.search(r"combat\.ext\.[\w.]+.*\bfailed:\s*\w+(?:Error|Exception)", text):
        return ""
    out = _display_evidence().get(text)
    if out is None:
        out = display_prose(text)
    if RAW_ID.search(out) or SOURCE_RECORD_ID.search(out):
        from .history_text import history_name
        out = RAW_ID.sub(lambda m: history_name(m[0], {}), out)
        out = SOURCE_RECORD_ID.sub(lambda m: history_name(m[0], {}), out)
    return out

# Internal build fields the typed factory writes into a printed record. They
# route the build; a player never decides anything with them. Kept as a named
# tuple so the newcomer builder and the in-fight builder stay in step.
FACTORY_FIELDS = (
    "Factory Combat Bucket",
    "Canonical Action Type",
    "Split Candidate Buckets",
    "Split Review Decision",
    "Recommended Factory Realization",
    "Factory Routing",
    "Factory Metadata",
    "Source Record ID",
    "Typed Record ID",
)

# The real printed fields that end an internal field's value. An internal field
# runs to the next genuine label, the next heading, or the end of the text.
_PRINTED_LABELS = ("Action Type", "Timing Detail", "Range", "Target", "Area",
                   "Duration", "Cost", "Use Limit", "Tags", "Concentration")

# A build stamp inside a note: "subpaths worker 2026-09-28",
# "worker w2-support 2026-09-28". The name between "worker" and the date
# varies, so the whole phrase is matched, not one spelling of it.
_WORKER_STAMP = r"\b(?:subpaths\s+)?worker\s+[\w-]*\s*\d{4}-\d{2}-\d{2}\b"

# Parenthetical notes that describe the BUILD rather than the rule, anywhere
# they appear: "GM adjudicates", "not modelled", "riders lane 4", a source file,
# a build date. A note is judged part by part, so a rule printed inside the same
# bracket survives.
_DEVELOPER_NOTE = (r"no generic|blocked\s*:|GM[- ]adjudicat|GM[- ]?(?:reminder|note)|GM-only|GM line|"
                   r"not model|not implement|no (?:registered|compile|engine) (?:registry|row|mechanism)|"
                   rf"this (?:table|engine)\b|{_WORKER_STAMP}")

# Build talk that makes ONE part of a note unusable while its neighbours stand.
_BUILD_TALK = (r"riders? lane|which also carries|nothing clears it on rest|"
               r"not in the rules file|see the source")

# A Python literal in a player sentence. "None" is a cost, not a word.
_LITERAL = r"\b(?:None|True|False|null)\b"

# Internal names of engine hooks and typed rows ("hook speed", "row_allowed").
# Ordinary English that merely sounds like one is not listed: "Tremorsense
# pinpoints eligible creatures" is the owner's own printed rule, and dropping
# that clause took a targeting restriction away from the player.
_CODE_NAME = (r"\bhook speed\b|\brow_allowed\b|\bcandidate_allowed\b|\bblock_save\b|"
              r"\bblock_movement\b|\bblock_condition\b|\bignores_difficult\b|"
              r"\bmasked_conditions\b|\bteleport_check\b")

# A source file, the way a build record spells one.
_SOURCE_FILE = r"(?:combat|APP|tools|authority|tests|static|catalog_authority)/[\w/]+\.\w+"

# A Python identifier ("_rule", "block_movement", "riders_lane2").
_INTERNAL_NAME = r"\b\w+_[\w.]+\b"

# A build date, with or without the worker or lane stamp in front of it.
_BUILD_DATE = r"\b20\d\d-\d\d-\d\d\b"

# Internal shorthand a player cannot read. The owner's own rules use the long
# form; only the abbreviated evidence sentences are rewritten here. CP is not
# listed: explain_cp() owns that wording.
_SHORTHAND = ((r"\bPB\b", "Proficiency Bonus"), (r"Source key modifier", "Source key ability modifier"))

# CP is undefined on a hover. One plain wording, explained once, everywhere.
CP_WORDING = "cultivation points (your Path resource)"
CP_UNKNOWN = "cultivation points (paying Path resource not recorded)"

# A capitalised word pair that cannot be a field label, so it ends an internal
# factory field without swallowing the prose that follows it.
_LABELLED_PROSE = r"(?=[A-Z][a-z]+\s+[a-z]+[,.;])"


def _drop_build_stamp(text: str) -> str:
    """Remove a build stamp in place, keeping whatever else the note said.

    "(Space, worker w2-support 2026-09-28)" is a sphere name plus build noise,
    so only the stamp goes; a note left with nothing but punctuation goes whole.
    """
    text = re.sub(rf",?\s*{_WORKER_STAMP}", "", text, flags=re.I)
    return re.sub(r"\(\s*[,;:]?\s*\)", "", text)


def _is_citation(text: str) -> bool:
    """True when a fragment is a source file, a build date or a code name."""
    return bool(re.search(_SOURCE_FILE, text) or re.search(_INTERNAL_NAME, text)
                or re.search(_WORKER_STAMP, text, re.I))


def _rule_whose_subject_was_a_file(segment: str) -> str:
    """Rescue a rule whose written subject was the file that implements it.

    Evidence often reads "combat/ext/stone_womb.py ends it early on healing, a
    dismissal, or damage equal to 10 + the Source key modifier + PB". The file
    is the build's way of naming the subject; the rest is the rule the player
    needs, so the file goes and the predicate is left as a sentence of its own.
    Only a citation in *subject* position is rescued, a citation anywhere else
    is build talk, and a bare fragment ("hook speed") is not a rule.
    """
    match = re.match(rf"^(?:{_SOURCE_FILE}|{_INTERNAL_NAME}|{_WORKER_STAMP})[,:;]?\s+", segment, re.I)
    if not match:
        return ""
    rest = segment[match.end():].strip(" ,;:")
    words = rest.split()
    # Fewer than four words is a name, not a rule, and a tail that stops on a
    # preposition or a conjunction is a half-sentence the file was hiding.
    if len(words) < 4 or re.search(r"\b(?:in|on|at|of|to|for|with|by|from|and|or|that|which|the)$", words[-1], re.I):
        return ""
    # What is left still has to be player prose: "ignores_difficult reads the
    # rule" is the build talking about itself, not a rule with a file for a
    # subject, so nothing is rescued and the clause goes.
    if re.search(rf"{_SOURCE_FILE}|{_INTERNAL_NAME}|{_CODE_NAME}|{_BUILD_TALK}|{_BUILD_DATE}", rest):
        return ""
    # The rescued subject is "It", so a predicate that already carries its own
    # object must not read "It ends it early".
    rest = re.sub(r"^(\w+)\s+(?:it|them|its|their)\b", r"\1", rest, flags=re.I)
    return f"It {rest}"


def _owner_words(inner: str) -> list[str]:
    """The player's own words inside one parenthetical, judged a part at a time.

    A note is kept only when every part of it is about the fight. When the owner's rule and the
    build note share one bracket the parts are judged separately, so "Rest Hold,
    combat/ext/hold_still.py" keeps the ability name and loses the file, and the Stone Womb ending
    rule survives beside the file that implements it. Returns the parts, in order, for the caller to
    put back however it needs them.
    """
    kept = []
    for part in re.split(r"\s*;\s*", inner):
        part = part.strip()
        if not part:
            continue
        # A citation in subject position is the build's way of naming the
        # subject, so the whole remainder of that part is the rule and is kept
        # as one sentence: "ends it early on healing, a dismissal, or ...".
        rescued = _rule_whose_subject_was_a_file(part)
        if rescued:
            kept.append(rescued)
            continue
        # Otherwise the parts are judged one at a time, so "Rest Hold,
        # combat/ext/hold_still.py" keeps the ability name and loses the file.
        for segment in re.split(r"\s*,\s*", part):
            segment = segment.strip()
            if not segment or re.search(rf"{_DEVELOPER_NOTE}|{_BUILD_TALK}|{_BUILD_DATE}|{_CODE_NAME}", segment, re.I) \
                    or _is_citation(segment):
                continue
            kept.append(segment)
    return kept


def _keep_paren(match: re.Match[str]) -> str:
    """Keep the rule inside a parenthetical, drop only the build talk in it."""
    kept = _owner_words(match[1])
    if not kept:
        return ""
    return f" ({', '.join(kept)})"


def _drop_developer_note(text: str) -> str:
    """Remove parenthetical notes that talk about the build rather than the rule."""
    # One line at a time: a printed record is full of brackets the author did not
    # pair, and a match that could cross a line break would swallow whole
    # paragraphs of the rule between them.
    return re.sub(r"\s?\(([^()\n]*)\)", _keep_paren, text)


# A whole parenthetical, so a caller holding one note can hand it over unchanged.
_ONE_NOTE = re.compile(r"\s?\(([^()\n]*)\)")


def keep_owner_words_in_note(note: str) -> str:
    """One whole parenthetical, rebuilt from the player's own words, or "" when it held none.

    ``plain()`` judges every bracket it meets through ``_keep_paren``, so it never loses the rule
    printed next to a citation. ``combat.condition_text.plain_reading()`` reads the same evidence
    first, to lift out the duties the note hands the Game Master, and it needs the same judgement for
    the rest of the note rather than a second copy of the rules that would drift. Both callers see
    the same note, so the ability name and the rule it explains survive the file in either one.

    The note comes back with its brackets, because the caller puts it back where it was.
    """
    match = _ONE_NOTE.fullmatch(note.strip())
    if match is None:
        return ""
    kept = _owner_words(match[1])
    return f" ({', '.join(kept)})" if kept else ""


def rule_after_a_citation(clause: str) -> str:
    """The rule that followed a citation the build wrote as the clause's subject, or "".

    ``_drop_citation_clauses`` rescues it where the clause stood; ``combat.condition_text`` cuts a
    sentence at the same citation and would drop the rule with the clause, so it asks here rather
    than keeping a second copy of what counts as a rule with a file for a subject.
    """
    return _rule_whose_subject_was_a_file((clause or "").strip())


def _drop_citation_clauses(text: str) -> str:
    """Drop the clause that is about the build, not about the creature.

    Clause by clause, and line by line: a printed record is a list of fields, so
    filtering the whole text as one run of sentences would also collapse its line
    structure, and dropping a whole line would throw away the rule printed next
    to the note. A clause that names a source file or an internal row name is
    build talk and goes; the rest of the line stays exactly where it was.
    """
    kept = []
    for line in text.splitlines():
        # Split on the author's own punctuation, keeping the separator, so a
        # line that loses nothing is rejoined exactly as it was written.
        parts = re.split(r"([.;:])\s+", line)
        clauses, dropped = [], False
        for index in range(0, len(parts), 2):
            clause = parts[index]
            if re.search(_SOURCE_FILE, clause) or re.search(_WORKER_STAMP, clause, re.I) \
                    or re.search(_CODE_NAME, clause):
                # A clause that lost its file may still be a rule whose subject
                # was that file, so the rule is rescued where it stood before
                # the clause goes.
                rescued = _rule_whose_subject_was_a_file(clause.rstrip(";,"))
                clause = rescued if rescued else ""
            elif re.search(rf"{_BUILD_TALK}|{_BUILD_DATE}|GM-only\b", clause, re.I):
                # "riders lane 4, 2026-09-29" is build bookkeeping, not a rule.
                clause = ""
            if not clause.strip():
                dropped = True
                continue
            clauses.append((clause.rstrip(), parts[index + 1] if index + 1 < len(parts) else ""))
        if clauses:
            # Dropping a clause takes its neighbour's ";" with it: what is left
            # has to end a sentence, not trail off into one. A line that loses
            # nothing is rejoined exactly as the owner wrote it, so a ";" the
            # author chose still reads as the author wrote it. A ":" is kept
            # either way, because a label that introduces the rule is doing its
            # job, and only a ";" this code replaced capitalises what follows.
            words, capitalise = [], False
            for clause, separator in clauses:
                if dropped and separator == ";":
                    words.append(clause + ".")
                    capitalise = True
                    continue
                if capitalise and clause[:1].islower():
                    clause = clause[0].upper() + clause[1:]
                capitalise = False
                # The separator stays glued to the clause it ended, so a label
                # like "Cost:" is still one word for the readers that come
                # after this one.
                words.append(clause + separator)
            kept.append(" ".join(words).rstrip())
    return "\n".join(kept)


def _drop_factory_fields(text: str) -> str:
    """Remove internal build-routing fields, wherever they sit in a record."""
    # Constructed records carry a labelled, indented identity block before
    # their rules. Preserve that block in source evidence, never in player text.
    text = re.sub(r"(?im)^Record identity:[ \t]*\n(?:[ \t]+[^\n]*(?:\n|$))+", "", text)
    # The generic field-to-sentence projection may already have transformed
    # the Action Type portion of this internal duplicate header.
    text = re.sub(r"(?im)^Canonical Use this as[^\n]*(?:\n|$)", "", text)
    names = "|".join(re.escape(name) for name in FACTORY_FIELDS)
    following = "|".join(re.escape(name) for name in _PRINTED_LABELS)
    pattern = re.compile(
        rf"(?:{names}):[^\n]*?(?=(?:{following})\s*:|\n|$|{_LABELLED_PROSE})", re.I)
    return pattern.sub("", text)


def _drop_scaling_lookup(text: str) -> str:
    """Remove a run of "CL 1-4: 1d8. CL 5-10: 2d8" band lookups.

    Fight log only -- see ``log_text``. On a printed card the same table is the
    rule the ability deals, not a lookup, and a card that says "deal the damage
    below" has to show what "below" is.
    Only a run of two or more bands is removed, so "CL 11 or higher" survives,
    and the label introducing the run goes with it, so no "Damage:" is left
    pointing at nothing.
    """
    band = r"(?:CL\s*)?\d+\s*[-\u2013]\s*\d+\s*:\s*[^\n.;]*"
    # "Damage:" introduces a band run in printed cards too, so it leaves with it.
    labels = "|".join(re.escape(name) for name in _PRINTED_LABELS + ("Damage",))
    out, removed = re.subn(rf"(?:(?:{labels})\s*:\s*)?(?:{band}\s*\.?\s*){{2,}}", "", text)
    if not removed:
        return out
    # A pointer to the run just removed ("the damage below", "listed below")
    # now points at nothing, so the pointer goes and the noun stays: "deal the
    # damage below" reads as "deal the damage".
    out = re.sub(r"\s*(?:shown|listed|given|set out|printed|provided)?\s*"
                 r"(?:in|on)\s+(?:the\s+)?(?:table\s+|list\s+|row\s+)?below\b", "", out, flags=re.I)
    return re.sub(r"\s+below\b", "", out, flags=re.I)


def _fix_glued_labels(text: str) -> str:
    """Separate a field label glued to the word before it.

    Typed data has produced "Cost: NoneConcentration: Not required" and
    "Duration: 1 minuteConcentration: Required"; a player reads one run-on word.
    """
    labels = "|".join(re.escape(name) for name in _PRINTED_LABELS)
    return re.sub(rf"(?<=[a-z0-9])(?=(?:{labels})\s*:)", ". ", text)


def collapse_doubled(text: str) -> str:
    """Remove an immediately repeated word ("damage damage", "the the").

    Two guards keep this off real rule text. A compound name is not a doubled
    word: in "Five-Venom Venom Effects" the first Venom belongs to the name, so
    only a word that starts a phrase can be doubled. And "had had" is correct
    English, so it is left alone.
    """
    return re.sub(r"(?<![\w/-])(?!had\b)([A-Za-z]{2,})(?:\s+\1\b)+", r"\1", text, flags=re.I)


def clean(text: Any) -> str:
    """Remove build detail and jargon, keeping the rule and its line structure.

    One implementation for every player-facing builder; see the module docstring
    for the callers. Markdown emphasis is dropped, so callers can keep their own
    sentence assembly.
    """
    return _clean_string(str(text or ""))


@lru_cache(maxsize=4096)
def _clean_string(out: str) -> str:
    """Pure cleanup keyed by the entire input string, never an actor or rule ID.

    Normalize at the public boundary so mutable/unhashable inputs keep working
    and changes to their rendered text cannot reuse an old answer. Only immutable
    strings are retained; changed printed rules naturally have different keys.
    """
    return _clean_body(display_text(out))


@lru_cache(maxsize=4096)
def _source_string(out: str) -> str:
    """The same cleanup without a reviewed whole-record display replacement.

    A condition chip's catalogue entry must quote the owner's printed rule. The
    reviewed ``player_text`` cards reorder and relabel that rule for a button, so
    resolving the whole record through them here would make the hover drift from
    the text it says it quotes. Owner evidence replacements are still resolved by
    their own callers; this path only removes build detail from the printed text.
    """
    return _clean_body(out)


def _clean_body(out: str) -> str:
    """Clean one already-resolved string; shared by ``_clean_string``/``_source_string``."""
    out = re.sub(r"^#+\s*", "", out, flags=re.M)
    # Markdown first: a printed field can be bolded, as in "**Cost:** None",
    # and every rule below has to see the label and its value as the player does.
    out = re.sub(r"(\*\*|__|`)(.*?)\1", r"\2", out, flags=re.S)
    out = re.sub(r"<[^>]+>", "", out)
    out = re.sub(r"\(owner[^)]*\)", "", out)
    # A source file the build wrote in parentheses or after a comma is build talk.
    out = re.sub(rf"\s*\(\s*{_SOURCE_FILE}\s*\)", "", out)
    out = re.sub(rf"[,;]?\s*{_SOURCE_FILE}\b", "", out)
    out = _drop_factory_fields(out)
    out = _drop_build_stamp(out)
    out = _drop_developer_note(out)
    out = _drop_citation_clauses(out)
    out = _fix_glued_labels(out)
    # A Python literal where a player needs a word.
    out = re.sub(rf"(Cost:\s*){_LITERAL}\b", r"\1no cost", out)
    out = re.sub(rf"(Duration:\s*){_LITERAL}\b", r"\1unlimited", out)
    # Abbreviations the owner does not use, so the rule beside them is readable.
    for shorthand, wording in _SHORTHAND:
        out = re.sub(shorthand, wording, out)
    out = collapse_doubled(out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    # The owner's own line structure is kept verbatim, indentation and blank
    # lines included: an indented line in a printed rule is content, not
    # formatting, and plain() joins everything for the single-paragraph
    # surfaces that do not care.
    return out.strip()


def plain(text: Any) -> str:
    """clean() with the record's line structure joined into one paragraph.

    Hovers and log lines are single paragraphs; use clean() where a caller
    builds its own list of lines and wants them kept apart.
    """
    return _plain_string(str(text or ""))


@lru_cache(maxsize=4096)
def _plain_string(text: str) -> str:
    return " ".join(_clean_string(text).split())


def source_plain(text: Any) -> str:
    """``plain`` for a printer's quote: the owner's printed words, not a player card.

    Used where a surface promises to quote the printed source (a condition chip's
    catalogue entry), so a reviewed card projection cannot silently reorder or
    relabel the rule. The same build-detail cleanup applies; only the whole-record
    ``player_text`` replacement is skipped.
    """
    return _source_plain_string(str(text or ""))


@lru_cache(maxsize=4096)
def _source_plain_string(text: str) -> str:
    return " ".join(_source_string(text).split())


def log_text(text: Any) -> str:
    """clean() plus the one suppression that belongs to the fight log alone.

    A run of Cultivation Level damage bands is a lookup on a card and a rule in
    a log the player cannot roll, so ``history_text.rider_text`` and the battle
    log use this and every hover, card and reference catalogue uses ``clean``.
    """
    return _drop_scaling_lookup(clean(text))


def log_plain(text: Any) -> str:
    """log_text() as the single paragraph a log line is."""
    return " ".join(log_text(text).split())


def explain_cp(text: Any, pool: str = "") -> str:
    """Say what CP is, in the pool that is paying, in one plain wording.

    Callers that know the pool pass its player-facing name; callers that do not
    still get the same plain explanation rather than a bare "CP".
    """
    return re.sub(r"\bCP\b", pool.strip() or CP_WORDING, str(text or ""))


def reading(text: Any) -> str:
    """A condition-pill hover: clean, plain, and never addressed to the GM.

    ``all_conditions`` falls back to the engine's raw evidence sentence for
    keys with no hand-written reading. That sentence cites the file that typed
    the condition and sometimes an internal row name, so it is cleaned here
    before it can reach the table.
    """
    return plain(explain_cp(text))


def source_reading(text: Any) -> str:
    """``reading`` for a printer's quote: cleaned evidence, without a card reflow."""
    return source_plain(explain_cp(text))
