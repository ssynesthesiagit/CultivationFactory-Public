"""Wording rules shared by the Factory rename and its authority readers.

This operates on prose. Structured callers must pass only the display values,
not identifiers, JSON keys, or syntax. Ambiguous bare legacy "Aspect" uses
require source context and are deliberately not guessed here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


TERMS = json.loads((Path(__file__).resolve().parents[1] / "authority/aspect_terms.json").read_text(encoding="utf-8"))

# A trailing sentence period is punctuation; a dot followed by more of the
# token is a filename or qualified name. Keep those and slash-joined paths.
_LEFT = r"(?<![\w./])"
_RIGHT = r"(?![\w/]|\.\w)"


def _alternatives(values) -> str:
    return "|".join(map(re.escape, sorted(values, key=len, reverse=True)))


def _replacements(mapping: dict[str, str], *, keep=()):
    folded = {old.casefold(): new for old, new in mapping.items()}
    pattern = re.compile(_LEFT + "(?:" + _alternatives([*mapping, *keep]) + ")" + _RIGHT, re.I)

    def replace(text: str) -> str:
        def substitute(match: re.Match[str]) -> str:
            old = match[0]
            new = folded.get(old.casefold(), old)
            return new.lower() if old.islower() else new
        return pattern.sub(substitute, text)

    return replace


_names = TERMS["names"]
_full_names = {name.casefold(): full for name, full in _names.items()}
_full_names.update({
    spelling.casefold(): _names[name]
    for spelling, name in TERMS["aliases_other_spellings_to_short_name"].items()
})
_NAME = "(?:" + _alternatives(_full_names) + ")"
_FULL = "(?:" + _alternatives(_names.values()) + ")"
_NAME_ONLY = re.compile(_LEFT + _NAME + _RIGHT, re.I)
_PREFIX = re.compile(_LEFT + r"(?P<term>Sphere) of[ \t]+(?P<name>" + _NAME + ")" + _RIGHT, re.I)
_SUFFIX = re.compile(
    _LEFT + rf"(?P<names>(?:{_FULL}|{_NAME})(?:(?:,[ \t]*(?:(?:or|and)[ \t]+)?"
    rf"|[ \t]+(?:or|and)[ \t]+)(?:{_FULL}|{_NAME}))*)[ \t]+(?P<term>spheres?)" + _RIGHT,
    re.I,
)
# Inline emphasis keeps the name inside the markup. A trailing term can be
# outside the emphasis ("**Fire** Sphere") or inside ("**Fire Sphere**").
_EMPHASIS = re.compile(r"(?P<mark>\*{1,2})(?P<name>" + _NAME + r")(?P=mark)[ \t]+spheres?" + _RIGHT, re.I)
_REQUIRED = re.compile(r"^(\s*(?:\*\*)?Required Sphere:(?:\*\*)?[ \t]*)(.*)$", re.I)
_LEGAL = re.compile(r"^\s*(?:\*\*)?Legal Sphere[s]?:(?:\*\*)?[ \t]*$", re.I)
_BULLET = re.compile(r"^(\s*[-*][ \t]+)(\*{0,2})(" + _NAME + r")(\2)([ \t]*[.]?[ \t]*)$", re.I)

_generic = TERMS["generic_term_map"]
_shape = TERMS["kept_shape_rule"]
_SPHERE = re.compile(_LEFT + _shape["regex_word"] + _RIGHT)
_MEASURE = re.compile(_shape["regex_measure_before_word"], re.I)
_SHAPE_WORD = re.compile(_shape["regex_shape_word_before"], re.I)
_SHAPE_LIST_BEFORE = re.compile(_shape["regex_shape_list_before"], re.I)
_SHAPE_LIST_AFTER = re.compile(_shape["regex_shape_list_after"], re.I)
_AREA_POINTER = re.compile(r"\b(?:within|inside|outside|into|through|from|in) (?:the|this|that)\s+$", re.I)
_SHAPE_AFTER = re.compile(r"^(?:-wide\b| of (?:supernatural darkness|darkness|light|water|force)\b)", re.I)

_legacy = _replacements(
    {**TERMS["feature_renames"], **TERMS["dao_divinity"], **TERMS["entry_names_that_changed"]},
    keep=TERMS["kept_aspect_phrases"],
)
_titles = _replacements({
    **TERMS["titles"],
    **{old: new for old, new in TERMS["heading_suffixes"].items() if new != "unchanged"},
})
_short_names = {old.casefold(): new for old, new in TERMS["short_lists"].items()}
_COMPACT_LIST = re.compile(
    r"^([ \t]*(?:[-*][ \t]+)?(?:\*{1,2})?(?:Common Aspect Synergies|"
    r"Background Aspect (?:&|and) Talent|Aspects|Aspect (?:Fit|Options)):(?:\*{1,2})?[ \t]*)(.*)$",
    re.I,
)
_CL_BRACKET = re.compile(r"\((" + _alternatives(_short_names) + r")(?=,[ \t]*CL[ \t]*\d)", re.I)


def _named_list(text: str) -> str:
    # Preserve any already-expanded names in a mixed list.
    return re.sub(_LEFT + rf"(?:{_FULL}|{_NAME})" + _RIGHT,
                  lambda m: _full_names.get(m[0].casefold(), m[0]), text, flags=re.I)


def _is_shape(text: str, start: int, end: int) -> bool:
    before, after = text[:start], text[end:]
    if _SHAPE_LIST_BEFORE.search(before) or _SHAPE_LIST_AFTER.match(after):
        return True
    if not text[start:end].islower():
        return False
    return bool(_MEASURE.search(before) or _SHAPE_WORD.search(before)
                or _AREA_POINTER.search(before) or _SHAPE_AFTER.match(after))


def _generic_term(match: re.Match[str]) -> str:
    word = match[0]
    if _is_shape(match.string, *match.span()):
        return word
    key = word + " (game sense)" if word.islower() else word
    return _generic[key]


def _article_pattern(old: str, new: str) -> tuple[re.Pattern[str], str]:
    article, following = old.removesuffix(" ...").split(" ", 1)
    return (
        re.compile(r"\b(" + article + r")([ \t]+\**" + re.escape(following) + r"\b)", re.I),
        new.split(" ", 1)[0],
    )


_ARTICLES = [_article_pattern(old, new) for old, new in TERMS["articles"].items()]


def _short_listing(match: re.Match[str]) -> str:
    def item(value: str) -> str:
        name = value.strip(" \t*.")
        new = _short_names.get(name.casefold())
        return value.replace(name, new, 1) if new else value
    return match[1] + ",".join(item(cell) for cell in match[2].split(","))


def aspect_terms(text: str) -> str:
    """Apply the Bible's context-independent term changes in source order."""
    folded = text.casefold()
    if "sphere" not in folded and "aspect" not in folded and "way of" not in folded and not _CL_BRACKET.search(text):
        return text

    lines = []
    legal = False
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        eol = raw[len(line):]
        line = _legacy(line)
        if _LEGAL.fullmatch(line):
            legal = True
        elif legal and (bullet := _BULLET.fullmatch(line)):
            line = bullet[1] + bullet[2] + _full_names[bullet[3].casefold()] + bullet[4] + bullet[5]
        elif line.strip():
            legal = False
        # Only the prerequisite list needs expansion, not the equivalent-access
        # prose that may follow it.
        required = _REQUIRED.fullmatch(line)
        if required:
            prefix, equivalent, tail = re.split(
                r"([,]?[ \t]+or[ \t]+an equivalent\b)", required[2], maxsplit=1, flags=re.I
            ) if re.search(r"[ \t]+or[ \t]+an equivalent\b", required[2], re.I) else (required[2], "", "")
            line = required[1] + _named_list(prefix) + equivalent + tail

        line = _PREFIX.sub(
            lambda m: m[0] if _is_shape(m.string, *m.span("term")) else _full_names[m["name"].casefold()],
            line,
        )
        line = _EMPHASIS.sub(lambda m: m["mark"] + _full_names[m["name"].casefold()] + m["mark"], line)
        line = _SUFFIX.sub(
            lambda m: m[0] if m["names"].islower() and _is_shape(m.string, *m.span("term"))
            else _named_list(m["names"]),
            line,
        )

        line = _SPHERE.sub(_generic_term, _titles(line))
        line = _COMPACT_LIST.sub(_short_listing, line)
        line = _CL_BRACKET.sub(lambda m: "(" + _short_names[m[1].casefold()], line)
        # The table only changes the article, preserving capitalization and
        # any bold/italic markup before the following game term.
        for pattern, article in _ARTICLES:
            line = pattern.sub(
                lambda m: (article.capitalize() if m[1][0].isupper() else article) + m[2], line,
            )
        lines.append(line + eol)
    return "".join(lines)
