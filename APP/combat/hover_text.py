"""One shared formatter for every player-facing hover and description.

Owner 2026-10-03 (MMX104, the round-24 Edict Seal screenshot): every hover -- an
ability, a condition, a mark, a Path, a Foundation, a sheet entry -- was a single
wall of text. The printed field labels were glued to the words before them
("Generate Edict Seal Type: No Action / Triggered Trigger: After a hostile
creature fails..."), and a generated line could contradict the printed rule
("Lasts until removed." next to "It expires at the end of your next turn") or
speak to the player in engine words ("the table's implemented abilities read it").

This module is the single place that lays a description out, so every surface
gets the same readable shape:

  1. a bold title
  2. a one-line plain summary, derived from the structured data -- never invented
  3. the printed fields, one labelled line each (Cost, Action, Trigger, Range,
     Target, Effect, Duration, Limit, Counterplay ...)
  4. the card's own prose, on its own Effect line: a line the printer wrapped
     continues the field above it, but a line that starts a new sentence is the
     rule, not that field's value (OC13, where a whole rules body printed as the Cost).
     A printed label the owner left empty ("Limits:" on a line of its own) keeps the
     lines printed under it, because those lines are that label's value, not prose
  5. a short footer: who applied it, and how long it lasts

It only reads. It never resolves an effect, never writes fight state, and never
paraphrases a printed rule away: the printed field values are kept verbatim, and
the summary is extra.

Surfaces use it through :func:`layout`, which returns the structured hover AND
its plain rendering. A ``title=`` tooltip shows the newlines; a card renderer
(MMX100's hover card) reads the same structure for bold labels, so the text
lives here once and the display layers only assemble it.
"""
from __future__ import annotations

import re
from typing import Any

# Printed field labels, in the order a printed card states them. "Type" is the
# owner's word for the economy line; it is shown as "Action" because that is what
# a player does. Labels are matched case-insensitively and with the owner's
# longer variants ("Counterplay and Boundaries" / "Counterplay").
FIELD_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Cost", ("cost", "action cost", "spend")),
    ("Action", ("type", "action type", "activation", "action")),
    ("Trigger", ("trigger", "timing detail", "timing", "when")),
    ("Range", ("range",)),
    ("Area", ("area",)),
    ("Target", ("target", "targets")),
    ("Saving Throw", ("saving throw",)),
    ("Attack or Save", ("attack or save", "attack", "save")),
    ("Effect", ("effect", "effects", "benefit", "procedure")),
    # Casting/ritual time is the time spent performing the ability, not the
    # effect's lifetime. Only Duration feeds printed_duration_of().
    ("Casting Time", ("time", "casting time")),
    ("Ritual Time", ("ritual time",)),
    ("Duration", ("duration",)),
    ("Limit", ("limit", "limits", "use limit", "prerequisite", "available at", "talent type")),
    ("Counterplay", ("counterplay and boundaries", "counterplay", "boundaries")),
)
_BY_KEY = {key: name for name, keys in FIELD_LABELS for key in keys}

# A field line in its printed form, "**Range:** Self", then the plain form a
# sheet or a log line uses, "Range: Self". Bold is matched first and exactly, so
# the closing "**" can never leak into the value; the plain form is only tried for
# a label we know, so an ordinary sentence ("Path key ability modifier: ...")
# is never split in half.
_FIELD_BOLD = re.compile(r"^\s*\*\*(?P<label>[^*]{1,40}?)\s*:\*\*\s*(?P<value>.*)$")
_FIELD_PLAIN = re.compile(r"^\s*(?P<label>[A-Z][A-Za-z ]{1,28}?)\s*:\s*(?P<value>.*)$")
# An unlabelled line only continues the field above it when it reads as a sentence the
# printer wrapped: it starts in lower case or with punctuation. Anything else after the
# printed labels is the card's own prose (OC13: 2,235 of the printed records printed their whole
# rule body as the value of Cost, Limit or Duration, because every unlabelled line was appended
# to whatever field came last). Prose opens the body's own "Effect" line, and the rest of the prose
# follows it until the next printed label.
# An EMPTY printed label is the exception: the owner wrote the heading on a line of its own and
# then the value under it ("Limits:" alone, then the restrictions), so what follows is that label's
# value rather than the card's body (both shipped Space talents, and Ten-Thousand Demon Sutra,
# print it this way; without this the restriction lines landed in a second Effect under no Limit
# at all, so a player looking for the targeting limits found none).
_CONTINUES = re.compile(r"^[a-z,;:)”\"']")
BODY_FIELD = "Effect"
# An expiry the printed text states about itself, used to settle a contradiction
# with a generated "until removed" line.
_STATED_EXPIRY = re.compile(
    r"\b(?:it\s+)?(?:expires?|ends?|lasts?|persists?|remains?|fades?)\b[^.;]{0,80}?"
    r"\b(?:end|start|turn|round|minute|hour|second)\b[^.;]{0,60}\.", re.I)
_UNTIL_REMOVED = re.compile(r"\buntil removed\b", re.I)
# A *timed amount* in a printed clock: a number with a time unit. A printed
# "Until the end of your next turn" states a moment rather than a length, so it
# is deliberately not matched here (see :func:`printed_clock_note`).
_TIMED_AMOUNT = re.compile(r"\b\d+(?:\s*[-–]\s*\d+)?\s*(?:rounds?|turns?|minutes?|hours?|seconds?)\b", re.I)


def _label(raw: str) -> str:
    return _BY_KEY.get(" ".join(raw.split()).casefold().rstrip("*_ ").casefold(), "")


def has_structural_blocks(text: str) -> bool:
    """Whether a description needs its original Markdown block structure.

    Multiple headings, lists and tables cannot be represented by a single
    card's field list. Retain them verbatim rather than attaching their rules
    to whichever field happened to precede them.
    """
    lines = str(text or "").splitlines()
    return (sum(bool(re.match(r"^\s*#{1,6}\s+", line)) for line in lines) > 1
            or any(re.match(r"^\s*(?:\||[-*•]\s+|\d+[.)]\s+)", line) for line in lines))


def split_fields(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a printed record into its lead line and its labelled fields.

    Intended for single cards: a line the printer wrapped from the field above it
    (it starts in lower case, or with punctuation) continues that field, a printed
    label the owner left EMPTY owns the lines printed under it, and the prose a card
    prints after its own labels opens the body's ``Effect`` field rather than becoming
    the last label's value. Nothing is dropped either way -- every printed line ends up
    in exactly one field, in the order it was printed. ``layout`` retains the original
    Markdown instead for records with structural blocks.
    """
    lead: list[str] = []
    fields: list[list[str]] = []
    body: str | None = None
    # The label of a printed field that is still waiting for its value.
    pending = ""
    for raw in str(text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line).strip()
            if not fields:
                lead.append(heading)
            continue
        match = _FIELD_BOLD.match(line) or _FIELD_PLAIN.match(line)
        name = _label(match["label"]) if match else ""
        if name:
            fields.append([name, match["value"].strip()])
            body = None
            pending = "" if match["value"].strip() else name
        elif fields:
            if pending:
                # The owner printed this label with nothing after it; the lines beneath it
                # are its value, and stay its value until the next printed label.
                body, pending = fields[-1][0], ""
                fields[-1][1] = line
            elif _CONTINUES.match(line) or body is not None:
                fields[-1][1] = f"{fields[-1][1]} {line}".strip()
            else:
                fields.append([BODY_FIELD, line])
                body = BODY_FIELD
        else:
            lead.append(re.sub(r"(?:\*\*|__|`)", "", line).strip())
    return " ".join(part for part in lead if part), [(name, value) for name, value in fields if value]


def first_sentence(text: str) -> str:
    """The first complete sentence of a printed value, for a derived summary."""
    for match in re.finditer(r"[^.;:]+[.;:]", str(text or "")):
        sentence = " ".join(match[0].split()).strip(" .;:")
        if len(sentence) > 12:
            return sentence
    return ""


def summary_for(subject: str, fields: list[tuple[str, str]], *, kind: str = "ability",
                mark_note: str = "") -> str:
    """One plain line saying what this does for you, or ``""`` when it cannot be derived.

    Only the structured fields are used. Nothing is invented: an ability summarises
    from its own printed Effect, a mark from its own reading, and anything else
    gets no summary line rather than a made-up one.
    """
    if kind == "mark":
        # A mark's printed text belongs to the ability that placed it, so the
        # Effect of that ability is not a summary of the mark. The mark's own
        # reading is what the player is shown.
        return mark_note
    # The card's opening Effect, which is the first one: a card that prints one
    # labelled Effect and then its prose has the labelled one.
    effect = next((value for name, value in fields if name == BODY_FIELD), "")
    lead = first_sentence(effect)
    if not lead:
        return ""
    return f"{subject}: {lead}" if subject and not lead.casefold().startswith(subject.casefold()) else lead


def stated_expiry(text: str) -> str:
    """The expiry a printed record states about itself, or ``""``."""
    match = _STATED_EXPIRY.search(str(text or ""))
    return " ".join(match[0].split()) if match else ""


def printed_clock_note(lifetime: str, printed_duration: str, source: str = "") -> str:
    """Name a printed clock that differs from the lifetime actually enforced.

    The two are different claims. ``lifetime`` is what the engine will do to this
    row; a printed ``Duration`` belongs to the ability that was printed and may
    describe a different thing entirely -- a persistent setting whose printed
    text also describes a short-lived rider of a triggered attack. Substituting
    the printed clock would promise an expiry nothing enforces, so the printed
    clock is shown *beside* the real one, marked as the printed rule.

    Only a timed amount counts as a difference. A printed "Until the end of your
    next turn" names the same moment the engine already says, in the player's
    words, and repeating it would only add noise.
    """
    printed = _TIMED_AMOUNT.findall(str(printed_duration or ""))
    if not printed or printed == _TIMED_AMOUNT.findall(str(lifetime or "")):
        return ""
    who = f"the printed rules for {source} also say" if source else "the printed rules also say"
    return f"{who}: {_TIMED_AMOUNT.sub(lambda m: m[0], str(printed_duration)).strip().rstrip('.')}"


def settle_duration(generated: str, fields: list[tuple[str, str]] | None = None, *, source: str = "") -> str:
    """The lifetime the engine actually enforces, with a differing printed clock named.

    ``generated`` is the row's own supported lifetime (a plug-in's duration
    override, or the translated storage token) and is ALWAYS the footer's
    authority: the returned string starts with it, so the footer and the
    top-level ``duration`` can no longer disagree. Only when a printed ``Duration``
    states a timed amount the enforced lifetime does not is the printed rule
    appended, clearly marked as printed.

    The printed record is deliberately not scanned for an expiry sentence here.
    Any "it expires at the end of your next turn" anywhere in the body may
    describe a *different* status the same ability creates, and letting it
    override the real lifetime is how a footer ends up promising an expiry that
    nothing enforces.
    """
    generated = str(generated or "").strip()
    if not generated:
        return generated
    note = printed_clock_note(generated, printed_duration_of(fields or []), source)
    return f"{generated.rstrip('.')}; {note}." if note else generated


def printed_duration_of(fields: list[tuple[str, str]]) -> str:
    """The printed ``Duration`` field as a phrase for the footer, or ``""``.

    A duration the owner printed ("1 minute", "While concentrating, up to 1
    hour") is already in the player's words; repeating it in the footer as
    "until removed (printed duration: 1 minute)" only adds noise.
    """
    value = dict(fields).get("Duration", "").strip()
    if not value or value.casefold() in {"instant", "immediate", "-", "none"}:
        return ""
    value = re.sub(r"^(?:for|up to|lasting)\s+", "", value, flags=re.I).strip().rstrip(".")
    return value


def layout(*, subject: str = "", kind: str = "ability", markup: str = "",
           extra: list[str] | tuple[str, ...] = (), summary: str = "",
           applied_by: str = "", source_ability: str = "", duration: str = "") -> dict[str, Any]:
    """Lay a description out once, for every surface.

    ``markup`` is the printed record with its ``**Label:**`` fields still marked
    up, so the labels survive splitting and the display layer can bold them.
    ``extra`` are the engine's own sentences (the stored reading, the mechanical
    summary, which abilities use a mark, how the table handles it) -- they are
    the caller's, so no rule text is dropped when a printed card is split up.
    ``summary`` is passed in when the caller derived one from its own structured
    data.
    The additive ``body`` list preserves unlabelled sentences for structured
    clients; ``text`` remains the complete plain presentation for all clients.
    For multi-section rules, lists or tables, ``body`` and ``text`` retain the
    original Markdown instead of flattening it into unrelated labelled fields.
    """
    structural = has_structural_blocks(markup)
    if structural:
        heading = re.search(r"^\s*#{1,6}\s+(.+)$", markup, re.M)
        lead, fields = (heading[1].strip() if heading else ""), []
    else:
        lead, fields = split_fields(markup)
    # The printed card's own heading is the ability's name, so it is the title;
    # the caller's subject is only used when the record has no heading of its own
    # (a condition or a mark, whose printed text belongs to the ability that
    # placed it -- naming the mark there would read as a second ability).
    title = lead or subject or "Effect"
    if structural and kind != "mark":
        # No derived single-field summary can describe all independent options.
        # A mark's own reading is independent of the source card's options.
        summary = ""
    summary = " ".join(str(summary or "").split())
    printed_all = " ".join(value for _, value in fields)
    # A summary that only restates the printed Effect, which is already a labelled
    # line of its own below, would print the same words twice in a row. Drop it and
    # let the printed field speak; the summary is extra, never a required line.
    core = summary
    if subject and core.casefold().startswith(f"{subject.casefold()}:"):
        core = core[len(subject) + 1:].strip()
    if core and printed_all and core.casefold() in printed_all.casefold():
        summary = ""
    lines: list[str] = []
    if structural:
        lines.append(markup)
    elif title:
        lines.append(title)
    if summary:
        lines.append(summary)
    lines.extend(f"{name}: {value}" for name, value in fields)
    seen = {printed_all.casefold()} if printed_all else set()
    body: list[str] = [markup] if structural else []
    if structural:
        seen.add(" ".join(markup.split()).casefold())
    for sentence in extra:
        sentence = " ".join(str(sentence or "").split())
        # The flattened printed card is already shown as labelled fields.
        if sentence and sentence.casefold() not in seen:
            seen.add(sentence.casefold())
            body.append(sentence)
            lines.append(sentence)
    footer_bits = []
    if applied_by and source_ability:
        footer_bits.append(f"Applied by {applied_by}, from {source_ability}.")
    elif applied_by:
        footer_bits.append(f"Applied by {applied_by}.")
    # The real lifetime is the footer's authority; a differing printed clock is
    # named beside it (settle_duration), never substituted for it.
    duration = settle_duration(duration, fields, source=source_ability)
    if duration:
        footer_bits.append(f"Lasts {duration.rstrip('.')}.")
    footer = " ".join(footer_bits)
    if footer:
        lines.append(footer)
    return {"title": title, "summary": summary,
            "fields": [{"label": name, "value": value} for name, value in fields],
            "body": body, "footer": footer, "duration": duration, "text": "\n".join(lines)}
