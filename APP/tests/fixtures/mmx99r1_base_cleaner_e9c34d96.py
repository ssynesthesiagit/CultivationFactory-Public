# Frozen baseline cleaner: APP/combat/player_text.py as of commit e9c34d96
# (the default baseline tools/mmx99r1_text_delta.py compares today's cleaner
# against). Checked in so the comparison needs no repository history: the
# delta tool lists every printed text whose reading differs between this
# cleaner and the current one. Do not edit to match new behaviour; a
# different baseline is a new file naming its own source commit.
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

Each rule is deliberately general: nothing here is keyed on an ability id, a
character, or a sphere, so a new plug-in is cleaned without touching this file.
"""
from __future__ import annotations

import re
from typing import Any

# Internal build fields the typed factory writes into a printed record. They
# route the build; a player never decides anything with them. Kept as a named
# tuple so the newcomer builder and the in-fight builder stay in step.
FACTORY_FIELDS = (
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

# Parenthetical notes that describe the BUILD, not the rule: "no generic X on
# this table", "GM adjudicates", "not modelled", a source file, a build date.
_DEVELOPER_NOTE = (r"no generic|GM[- ]adjudicat|GM-only|GM line|not model|"
                   r"not implement|no (?:registered|compile|engine) (?:registry|row|mechanism)|"
                   rf"this (?:table|engine) (?:has|keeps)|{_WORKER_STAMP}")

# A Python literal in a player sentence. "None" is a cost, not a word.
_LITERAL = r"\b(?:None|True|False|null)\b"

# Internal names of engine hooks and typed rows ("hook speed", "row_allowed").
_CODE_NAME = (r"\bhook speed\b|\brow_allowed\b|\bcandidate_allowed\b|\bblock_save\b|"
              r"\bblock_movement\b|\bblock_condition\b|\bignores_difficult\b|"
              r"\bpinpoints\b|\bmasked_conditions\b|\bteleport_check\b")

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


def _drop_developer_note(text: str) -> str:
    """Remove parenthetical notes that talk about the build rather than the rule."""
    def keep(match: re.Match[str]) -> str:
        inner = match[1]
        return "" if re.search(_DEVELOPER_NOTE, inner, re.I) or _is_citation(inner) else match[0]
    # One line at a time: a printed record is full of brackets the author did not
    # pair, and a match that could cross a line break would swallow whole
    # paragraphs of the rule between them.
    return re.sub(r"\(([^()\n]*)\)", keep, text)


def _is_citation(text: str) -> bool:
    """True when a fragment is a source file, a build date or a code name."""
    return bool(re.search(r"\b(?:combat|APP|tools|authority|tests)/[\w/]+\.\w+", text)
                or re.search(r"\b\w+_[\w.]+\b", text)
                or re.search(_WORKER_STAMP, text, re.I))


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
        clauses = []
        for clause in re.split(r"(?<=[.;:])\s+", line):
            if re.search(r"\b(?:combat|APP|tools|authority|tests)/[\w/]+\.\w+", clause) \
                    or re.search(_WORKER_STAMP, clause, re.I) \
                    or re.search(_CODE_NAME, clause):
                continue
            # Dropping a clause takes its neighbour's ";" with it: what is left
            # has to end a sentence, not trail off into one. A ":" is kept,
            # because a label that introduces the rule is still doing its job.
            clauses.append(re.sub(r";$", ".", clause.rstrip()))
        if clauses:
            # Turning a ";" into a full stop starts a sentence, so the next
            # clause starts with a capital: "burning. It ends early".
            sentence = []
            for clause in clauses:
                if sentence and sentence[-1].endswith(".") and clause[:1].islower():
                    clause = clause[0].upper() + clause[1:]
                sentence.append(clause)
            kept.append(" ".join(sentence))
    return "\n".join(kept)


def _drop_factory_fields(text: str) -> str:
    """Remove internal build-routing fields, wherever they sit in a record."""
    names = "|".join(re.escape(name) for name in FACTORY_FIELDS)
    following = "|".join(re.escape(name) for name in _PRINTED_LABELS)
    pattern = re.compile(
        rf"(?:{names}):[^\n]*?(?=(?:{following})\s*:|\n|$|{_LABELLED_PROSE})", re.I)
    return pattern.sub("", text)


def _drop_scaling_lookup(text: str) -> str:
    """Remove a run of "CL 1-4: 1d8. CL 5-10: 2d8" band lookups.

    A printed rule may show a Cultivation Level table in its own card. In a
    fight log it is a lookup, not an outcome, and a player cannot roll it.
    Only a run of two or more bands is removed, so "CL 11 or higher" survives,
    and the label introducing the run goes with it, so no "Damage:" is left
    pointing at nothing.
    """
    band = r"(?:CL\s*)?\d+\s*[-\u2013]\s*\d+\s*:\s*[^\n.;]*"
    # "Damage:" introduces a band run in printed cards too, so it leaves with it.
    labels = "|".join(re.escape(name) for name in _PRINTED_LABELS + ("Damage",))
    return re.sub(rf"(?:(?:{labels})\s*:\s*)?(?:{band}\s*\.?\s*){{2,}}", "", text)


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
    out = str(text or "")
    out = re.sub(r"^#+\s*", "", out, flags=re.M)
    # Markdown first: a printed field can be bolded, as in "**Cost:** None",
    # and every rule below has to see the label and its value as the player does.
    out = re.sub(r"(\*\*|__|`)(.*?)\1", r"\2", out, flags=re.S)
    out = re.sub(r"<[^>]+>", "", out)
    out = re.sub(r"\(owner[^)]*\)", "", out)
    out = _drop_factory_fields(out)
    out = _drop_build_stamp(out)
    out = _drop_developer_note(out)
    out = _drop_citation_clauses(out)
    out = _drop_scaling_lookup(out)
    out = _fix_glued_labels(out)
    # A Python literal where a player needs a word.
    out = re.sub(rf"(Cost:\s*){_LITERAL}\b", r"\1no cost", out)
    out = re.sub(rf"(Duration:\s*){_LITERAL}\b", r"\1unlimited", out)
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
    return " ".join(clean(text).split())


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
