"""Owner phrase filtering shared by named gear and advisory concept matching."""

import re


_CLAUSE_BREAK = re.compile(r"([,;.!?\n+]|\b(?:and|or|nor|but|with)\b)", re.IGNORECASE)
_NEGATOR = re.compile(
    r"\b(?:without|do not|does not|not|no|never|neither|except|excluding|excludes?|"
    r"avoids?|avoiding|rather than|instead of|don't|doesn't|cannot|can't|won't)\b(?!\s+only\b)",
    re.IGNORECASE,
)
_GEAR_VERB = r"(?:using|uses?|used|wield(?:s|ing|ed)?|carrying|carr(?:y|ies|ied)|wear(?:s|ing)?)\b"
_VERB_START = re.compile(r"\s*" + _GEAR_VERB, re.IGNORECASE)
_POSITIVE_START = re.compile(r"\s*(?:(he|she|they|I|we)\s+)?" + _GEAR_VERB, re.IGNORECASE)


def without_owner_exclusions(text: str) -> str:
    """Filter coordinated clauses for named gear and advisory concept matching.

    Nouns and verbs share their governing exclusion across and/or/comma lists.
    A negated verb ("without using", "doesn't wear") governs coordinated verbs
    too; a nominal exclusion ("without armor") permits a new positive gear verb.
    With, but, sentence boundaries, or an explicit new subject reset polarity.
    Preserve affirmative "not only" and positive wording for catalog matching;
    semicolons prevent removed clauses from creating spurious adjacent choices.
    """
    excluded = governed_verb = False
    kept: list[str] = []
    for index, part in enumerate(_CLAUSE_BREAK.split(text.replace("’", "'"))):
        if index % 2:
            if part.casefold() in {"but", "with"} or part in ";.!?\n+":
                excluded = governed_verb = False
            kept.append(part)
            continue
        positive = _POSITIVE_START.match(part)
        if excluded and positive and (not governed_verb or positive.group(1)):
            excluded = governed_verb = False
        negator = _NEGATOR.search(part)
        if negator:
            if not excluded:
                kept.append(part[:negator.start()])
            governed_verb = governed_verb or bool(_VERB_START.match(part[negator.end():]))
            excluded = True
            kept.append(";")
        elif excluded:
            kept.append(";")
        else:
            kept.append(part)
    return "".join(kept)
