"""Pure, frozen authority for mandatory starting proficiencies.

This module deliberately has no database, provider, or catalog access.
Callers pass the already-authenticated authority projections and the exact
source section that they want to bind.  The result is a compact contract that
can be sealed by the request owner without allowing response prose to become
mechanical authority.

The only file it reads is its own sealed Tool Proficiency Registry (a JSON
constant next to the module, loaded once at import like ``_SKILLS``).  The
registry lists every tool, kit, supplies, utensils and vehicle proficiency
name printed in the bundled Backgrounds book, Origin Insights book and
ItemBook, each bound to its printed source location.  Origin options that
name one of those tools (or the printed category "one artisan's tool")
become typed tool choices; contracts carry the registry hash so a validator
with a different registry fails closed.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata


CONTRACT_SCHEMA = "TianxiaFoundry.StartingProficiencyChoiceContract.v1"
VALIDATED_SCHEMA = "TianxiaFoundry.ValidatedStartingProficiencyChoices.v1"

_CHOICE_FIELDS = (
    "path_skill_choices_by_path_id",
    "origin_skill_choices_by_origin_id",
    "background_language_choices_by_background_id",
)
_FIELD_TO_SLOT = {
    "path_skill_choices_by_path_id": "path_choice",
    "origin_skill_choices_by_origin_id": "origin_insight_choice",
    "background_language_choices_by_background_id": "background_choice",
}
_SELECTED_SLOTS = tuple(_FIELD_TO_SLOT.values())
_FIXED_GRANT_KEYS = frozenset({
    "fixed_skill_names",
    "fixed_skills",
    "fixed_tool_proficiencies",
    "fixed_tools",
    "background_fixed_skills",
    "background_fixed_tools",
})

_SKILLS = frozenset({
    "Acrobatics",
    "Animal Handling",
    "Arcana",
    "Athletics",
    "Deception",
    "History",
    "Insight",
    "Investigation",
    "Medicine",
    "Nature",
    "Perception",
    "Performance",
    "Persuasion",
    "Religion",
    "Sleight of Hand",
    "Stealth",
    "Survival",
    "Intimidation",
})

TOOL_REGISTRY_SCHEMA = "Tianxia.ToolProficiencyRegistry.v1"
TOOL_REGISTRY_PATH = Path(__file__).resolve().parent / "authority" / "Tool_Proficiency_Registry_v1.json"
_TOOL_KINDS = frozenset({"tool", "kit", "supplies", "utensils", "vehicle"})
_OPTION_KINDS = frozenset({"skill", "tool", "trade", "language"})
_TOOL_ID_PREFIX = "tianxia.tool_proficiency."
_TRADE_ID_PREFIX = "tianxia.trade_proficiency."


def _rule_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"[^a-z0-9]+", "_", folded.casefold()).strip("_")
# Printed category phrases that expand to every artisan tool in the registry.
_ARTISAN_CATEGORY_KEYS = frozenset({
    "one artisan's tool",
    "one artisan's tool of your choice",
})
_ORIGIN_OPTIONAL_ENTRY_KEYS = frozenset({"option_kinds", "tool_authority", "category_expansions"})


def _tool_key(value: str) -> str:
    """Compare printed tool names without weakening their stored spelling."""
    folded = unicodedata.normalize("NFKD", value).replace("\u2019", "'").replace("\u2018", "'")
    folded = " ".join(folded.casefold().split())
    return folded[4:] if folded.startswith("the ") else folded


def _load_tool_registry() -> dict[str, Any] | None:
    """Load and shape-check the sealed registry; ``None`` leaves tools untyped."""
    try:
        raw = TOOL_REGISTRY_PATH.read_bytes()
        document = json.loads(raw)
    except (OSError, ValueError):
        return None
    if (
        not isinstance(document, dict)
        or document.get("schema") != TOOL_REGISTRY_SCHEMA
        or not isinstance(document.get("registry_id"), str)
        or not document["registry_id"].strip()
        or not isinstance(document.get("scope"), str)
        or document.get("offered_set_complete") is not False
        or not isinstance(document.get("tools"), list)
        or not document["tools"]
    ):
        return None
    by_key: dict[str, dict[str, Any]] = {}
    tool_ids: set[str] = set()
    for row in document["tools"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("tool_id"), str)
            or not row["tool_id"].strip()
            or not isinstance(row.get("display_name"), str)
            or row["display_name"] != row["display_name"].strip()
            or not row["display_name"]
            or row.get("kind") not in _TOOL_KINDS
            or type(row.get("artisan")) is not bool
            or not isinstance(row.get("printed_in"), list)
            or not row["printed_in"]
            or any(
                not isinstance(evidence, dict)
                or not _nonempty_string(evidence.get("source_path"))
                or not _hex_hash(evidence.get("source_hash"))
                or not _nonempty_string(evidence.get("source_anchor"))
                for evidence in row["printed_in"]
            )
        ):
            return None
        key = _tool_key(row["display_name"])
        if (
            key in by_key
            or row["tool_id"] in tool_ids
            or key in _SKILLS
            or row["display_name"] in _SKILLS
            or row["tool_id"] != f"{_TOOL_ID_PREFIX}{_rule_slug(row['display_name'])}"
        ):
            return None
        by_key[key] = row
        tool_ids.add(row["tool_id"])
    # Printed trade categories ("one service trade proficiency") and
    # campaign-language categories ("one court or formal campaign language")
    # are typed by their printed phrase: a trade becomes a single trade
    # proficiency named by the phrase; a language category offers the
    # matching names from the campaign-language display set.
    by_phrase: dict[str, dict[str, Any]] = {}
    trades = document.get("trades", [])
    categories = document.get("language_categories", {})
    if not isinstance(trades, list) or not isinstance(categories, dict):
        return None
    for row in trades:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("trade_id"), str)
            or not isinstance(row.get("display_name"), str)
            or row["display_name"] != row["display_name"].strip()
            or not row["display_name"]
            or row["trade_id"] != f"{_TRADE_ID_PREFIX}{_rule_slug(row['display_name'])}"
            or not _nonempty_string(row.get("printed_phrase"))
            or not isinstance(row.get("printed_in"), list)
            or not row["printed_in"]
            or _tool_key(row["display_name"]) in by_key
            or _tool_key(row["printed_phrase"]) in by_phrase
        ):
            return None
        by_phrase[_tool_key(row["printed_phrase"])] = {"kind": "trade", "row": row}
    for phrase, spec in categories.items():
        if (
            not _nonempty_string(phrase)
            or _tool_key(phrase) in by_phrase
            or not isinstance(spec, dict)
            or not isinstance(spec.get("offered_display_names"), list)
            or not spec["offered_display_names"]
            or any(not _nonempty_string(name) or name not in _LANGUAGE_DISPLAYS for name in spec["offered_display_names"])
            or len(set(spec["offered_display_names"])) != len(spec["offered_display_names"])
            or not isinstance(spec.get("printed_in"), list)
            or not spec["printed_in"]
        ):
            return None
        by_phrase[_tool_key(phrase)] = {"kind": "language", "phrase": phrase, "row": spec}
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "registry_id": document["registry_id"],
        "scope": document["scope"],
        "by_key": by_key,
        "by_phrase": by_phrase,
        "artisan": sorted(
            (row["display_name"] for row in document["tools"] if row["artisan"] is True),
            key=str.casefold,
        ),
        "tools": [deepcopy(row) for row in document["tools"]],
        "trades": [deepcopy(row) for row in trades],
        "language_categories": deepcopy(categories),
    }


def tool_proficiency_registry() -> dict[str, Any] | None:
    """Return the sealed registry (tools, artisan set, hash) or ``None``."""
    if _TOOL_REGISTRY is None:
        return None
    return {
        "schema": TOOL_REGISTRY_SCHEMA,
        "registry_id": _TOOL_REGISTRY["registry_id"],
        "registry_sha256": _TOOL_REGISTRY["sha256"],
        "scope": _TOOL_REGISTRY["scope"],
        "offered_set_complete": False,
        "artisan_display_names": list(_TOOL_REGISTRY["artisan"]),
        "tools": deepcopy(_TOOL_REGISTRY["tools"]),
        "trades": deepcopy(_TOOL_REGISTRY["trades"]),
        "language_categories": deepcopy(_TOOL_REGISTRY["language_categories"]),
    }


def _registry_tool(value: str) -> dict[str, Any] | None:
    if _TOOL_REGISTRY is None or not isinstance(value, str):
        return None
    return _TOOL_REGISTRY["by_key"].get(_tool_key(value))


def _split_origin_options(options_text: str) -> list[str]:
    """Split a printed option list, keeping registry phrases whole.

    Printed category phrases such as "meditation, breath, or discipline
    practice as a trade proficiency" or "one language tied to your family,
    clan, or region" contain the very separators that divide options, so the
    registry's phrases are lifted out before the remainder is split.
    """
    phrases = sorted(_TOOL_REGISTRY["by_phrase"], key=len, reverse=True) if _TOOL_REGISTRY else []
    lifted: list[str] = []
    working = options_text
    for phrase_key in phrases:
        pattern = re.compile(
            r"\s+".join(
                re.escape(token).replace("'", "['\u2019\u2018]")
                for token in phrase_key.split()
            ),
            re.IGNORECASE,
        )
        match = pattern.search(working)
        if match is None:
            continue
        lifted.append(match.group(0))
        working = working[: match.start()] + f" \x00{len(lifted) - 1}\x00 " + working[match.end():]
    values: list[str] = []
    for item in re.split(r",|\s+or\s+", working):
        item = item.strip()
        if not item:
            continue
        marker = re.fullmatch(r"\x00(\d+)\x00", item)
        values.append(lifted[int(marker.group(1))] if marker else item)
    return values


def _resolve_origin_options(values: list[str]) -> tuple[list[str], dict[str, str], dict[str, list[str]]] | None:
    """Type every printed Origin option as a skill, tool, trade or language.

    ``None`` when any option is none of those (an unprinted tool or an
    unregistered category).  Category phrases expand: "one artisan's tool"
    to the registry's artisan tools, a printed trade phrase to its single
    trade proficiency, a campaign-language category to its offered names.
    An expansion that repeats an explicitly named option folds into the
    single canonical option.
    """
    allowed: list[str] = []
    kinds: dict[str, str] = {}
    expansions: dict[str, list[str]] = {}

    def add(display: str, kind: str) -> None:
        if display not in kinds:
            allowed.append(display)
            kinds[display] = kind

    for item in values:
        if item in _SKILLS:
            add(item, "skill")
            continue
        tool = _registry_tool(item)
        if tool is not None:
            add(tool["display_name"], "tool")
            continue
        if _TOOL_REGISTRY is None:
            return None
        key = _tool_key(item)
        if key in _ARTISAN_CATEGORY_KEYS and _TOOL_REGISTRY["artisan"]:
            expansions[item] = list(_TOOL_REGISTRY["artisan"])
            for display in _TOOL_REGISTRY["artisan"]:
                add(display, "tool")
            continue
        category = _TOOL_REGISTRY["by_phrase"].get(key)
        if category is None:
            return None
        if category["kind"] == "trade":
            display = category["row"]["display_name"]
            expansions[item] = [display]
            add(display, "trade")
            continue
        names = list(category["row"]["offered_display_names"])
        expansions[item] = names
        for display in names:
            add(display, "language")
    return allowed, kinds, expansions


def _registry_trade(value: str) -> dict[str, Any] | None:
    if _TOOL_REGISTRY is None or not isinstance(value, str):
        return None
    key = _tool_key(value)
    for row in _TOOL_REGISTRY["trades"]:
        if _tool_key(row["display_name"]) == key:
            return row
    return None


def _fixed_tool_keys(fixed_tools: list[str]) -> set[str]:
    """Keys of the tools a Background grants outright (not a pending "or" choice)."""
    keys: set[str] = set()
    for value in fixed_tools:
        if not isinstance(value, str) or re.search(r"\bor\b", value):
            continue
        for part in re.split(r",|\s+and\s+", value):
            key = _tool_key(part)
            if key:
                keys.add(key)
    return keys


_LANGUAGE_HEADING = "## Campaign Languages and Cants"
_LANGUAGE_BODY = (
    "Backgrounds may grant campaign languages, cants, signs, or liturgical "
    "languages such as Classical, Trade Pidgin, gang cant, military signs, "
    "ancestral liturgical language, or regional ritual language."
)
_LANGUAGE_QUALIFIER = (
    "These count as languages unless the Background says they are a trade proficiency."
)
_LANGUAGE_DISPLAYS = [
    "Classical",
    "Trade Pidgin",
    "gang cant",
    "military signs",
    "ancestral liturgical language",
    "regional ritual language",
]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hex_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


# Loaded once the string helpers above exist; a missing or malformed registry
# leaves every tool option untyped rather than raising at import.
_TOOL_REGISTRY = _load_tool_registry()


def _frozen_row(
    choices_by_slot: dict[str, Any],
    allowed_choice_ids_by_slot: dict[str, Any],
    slot_id: str,
    choice_id: str,
) -> dict[str, Any] | None:
    """Return an exact presented row, rejecting key/record identity drift."""
    allowed = allowed_choice_ids_by_slot.get(slot_id)
    rows = choices_by_slot.get(slot_id)
    if not isinstance(allowed, list) or choice_id not in allowed:
        return None
    if not isinstance(rows, dict):
        return None
    row = rows.get(choice_id)
    if not isinstance(row, dict):
        return None
    identities = [
        row.get(key)
        for key in ("choice_id", "record_id", "canonical_id", "id")
        if row.get(key) is not None
    ]
    if identities and any(value != choice_id for value in identities):
        return None
    return row


def _path_entry(path_id: str, profile: Any) -> dict[str, Any] | None:
    if not isinstance(profile, dict) or profile.get("canonical_id") != path_id:
        return None
    path_profile = profile.get("path_profile")
    if not isinstance(path_profile, dict):
        return None
    raw = path_profile.get("skills")
    if not isinstance(raw, str):
        return None
    match = re.fullmatch(
        r"\s*Choose\s+([1-9][0-9]*|one|two|three|four|five|six)\s*:\s*(.+?)\s*",
        raw,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        count_token = match.group(1).casefold()
        count = int(count_token) if count_token.isdigit() else {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
        }[count_token]
    except (KeyError, ValueError):
        return None
    allowed_values = [item.strip() for item in match.group(2).split(",")]
    if (
        count < 1
        or count > len(allowed_values)
        or any(item not in _SKILLS for item in allowed_values)
        or len(set(allowed_values)) != len(allowed_values)
    ):
        return None
    source = profile.get("source")
    if not isinstance(source, dict):
        return None
    source_hash = source.get("sha256") or source.get("source_hash")
    factory_path = source.get("factory_path") or source.get("path")
    if not _nonempty_string(factory_path) or not _hex_hash(source_hash):
        return None
    return {
        "choice_kind": "path_skill",
        "choice_id": path_id,
        "required_count": count,
        "allowed_values": allowed_values,
        "source": {
            "factory_path": factory_path,
            **(
                {"corpus_path": source["corpus_path"]}
                if _nonempty_string(source.get("corpus_path"))
                else {}
            ),
            "source_hash": source_hash,
            "anchor": "path_profile.skills",
        },
    }


def background_starting_proficiency_unresolved_reason(
    background_id: str,
    background: Any,
) -> str | None:
    """Return why a Background lacks complete frozen starting-proficiency authority.

    ``None`` means the Background can be presented: the sealed request will be
    able to build its starting-proficiency contract entry (given a resolved
    campaign language authority when the Background grants a language choice).
    Stage 1 uses this predicate to keep such Backgrounds out of the presented
    set, so the contract check in request assembly never fires on a choice the
    model was offered. ``_background_entry`` applies exactly these checks first,
    so the two cannot drift.
    """
    if not isinstance(background, dict) or background.get("background_id") != background_id:
        return "authority_missing"
    skills = background.get("skills")
    tools = background.get("tools_languages_trades")
    if not isinstance(skills, dict) or skills.get("resolved") is not True:
        return "skills_unresolved"
    if not isinstance(tools, dict) or tools.get("resolved") is not True:
        return "tools_languages_trades_unresolved"
    fixed_skills = skills.get("fixed_skill_names")
    fixed_tools = tools.get("fixed_proficiencies")
    language_count = tools.get("free_choice_count_detected")
    if (
        not isinstance(fixed_skills, list)
        or any(not _nonempty_string(item) or item not in _SKILLS for item in fixed_skills)
        or len(set(fixed_skills)) != len(fixed_skills)
    ):
        return "fixed_skills_invalid"
    if (
        not isinstance(fixed_tools, list)
        or any(not _nonempty_string(item) for item in fixed_tools)
        or len(set(fixed_tools)) != len(fixed_tools)
    ):
        return "fixed_tools_invalid"
    if type(language_count) is not int or language_count < 0 or language_count > 1:
        return "language_choice_count_unsupported"
    source = background.get("source")
    if not isinstance(source, dict) or not _nonempty_string(source.get("path")):
        return "source_missing"
    return None


def _background_entry(
    background_id: str,
    background: Any,
    language_authority: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if background_starting_proficiency_unresolved_reason(background_id, background) is not None:
        return None
    skills = background["skills"]
    tools = background["tools_languages_trades"]
    fixed_skills = skills.get("fixed_skill_names")
    fixed_tools = tools.get("fixed_proficiencies")
    language_count = tools.get("free_choice_count_detected")
    source = background.get("source")
    entry: dict[str, Any] = {
        "choice_kind": "background_language",
        "choice_id": background_id,
        "fixed_skill_names": list(fixed_skills),
        "fixed_tool_proficiencies": list(fixed_tools),
        "language_choice_count": language_count,
        "resolved": True,
        "source": deepcopy(source),
        "allowed_values": [],
    }
    if language_count:
        if not isinstance(language_authority, dict):
            return None
        values = language_authority.get("offered_display_names")
        if not isinstance(values, list) or not values or any(not _nonempty_string(item) for item in values):
            return None
        entry["allowed_values"] = list(values)
        entry["language_authority"] = deepcopy(language_authority)
    return entry


def _origin_texts(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    mappings = [row]
    stage2 = row.get("stage2_authority")
    if isinstance(stage2, dict):
        mappings.append(stage2)
    compatibility = row.get("compatibility")
    if isinstance(compatibility, dict):
        factory = compatibility.get("factory")
        if isinstance(factory, dict) and isinstance(factory.get("stage2_authority"), dict):
            mappings.append(factory["stage2_authority"])
    for mapping in mappings:
        for key in (
            "full_description",
            "summary",
            "raw_benefit",
            "benefit",
            "raw_authority",
            "source_summary",
            "description",
        ):
            value = mapping.get(key)
            if _nonempty_string(value):
                normalized = " ".join(value.split())
                if normalized not in values:
                    values.append(normalized)
    return values


def _origin_evidence(row: dict[str, Any]) -> list[dict[str, str]]:
    evidence_rows: list[Any] = []
    for mapping in (row, row.get("stage2_authority")):
        if not isinstance(mapping, dict):
            continue
        evidence = mapping.get("source_evidence")
        if isinstance(evidence, list):
            evidence_rows.extend(evidence)
        elif isinstance(evidence, dict):
            evidence_rows.append(evidence)
        source = mapping.get("source")
        if isinstance(source, dict):
            evidence_rows.append(source)
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for evidence in evidence_rows:
        if not isinstance(evidence, dict):
            continue
        path = evidence.get("source_path") or evidence.get("path")
        source_hash = evidence.get("source_hash") or evidence.get("sha256")
        anchor = evidence.get("source_anchor") or evidence.get("anchor")
        if not all(_nonempty_string(value) for value in (path, source_hash, anchor)) or not _hex_hash(source_hash):
            continue
        key = (path, source_hash, anchor)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "source_path": path,
            "source_hash": source_hash,
            "source_anchor": anchor,
        })
    return result


def _origin_entry(origin_id: str, row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    identities = [
        row.get(key)
        for key in ("choice_id", "record_id", "canonical_id", "id")
        if row.get(key) is not None
    ]
    if identities and any(value != origin_id for value in identities):
        return None
    # Printed Origin grammar: "You gain proficiency in A, B, or C. If you
    # already have proficiency in the chosen skill, gain expertise in it."
    # Variants in the source: an Oxford comma before "or" (which leaves an
    # empty item after splitting), "the chosen option" instead of "the chosen
    # skill", and a single fixed skill that names itself in the second
    # sentence ("... proficiency in Intimidation, gain expertise in it").
    # Every option must be a skill or a registry tool ("the chosen tool" is
    # the printed wording of tool-only Origins); language and trade options
    # are left unresolved until the campaign publishes those lists.
    grammar = re.compile(
        r"^You gain proficiency in (.+?)\. "
        r"If you already have proficiency in (the chosen skill|the chosen option|the chosen tool|.+?), gain expertise in it\.$"
    )
    matches: list[tuple[str, list[str], dict[str, str], dict[str, list[str]]]] = []
    for text in _origin_texts(row):
        match = grammar.fullmatch(text)
        if match is None:
            continue
        values = _split_origin_options(match.group(1))
        repeated = match.group(2)
        if repeated not in ("the chosen skill", "the chosen option", "the chosen tool") and (len(values) != 1 or repeated != values[0]):
            continue
        if not values or len(set(values)) != len(values):
            continue
        resolved = _resolve_origin_options(values)
        if resolved is None:
            continue
        matches.append((text, *resolved))
    if not matches or len({(text, tuple(values)) for text, values, _kinds, _expansions in matches}) != 1:
        return None
    source_evidence = _origin_evidence(row)
    if len(source_evidence) != 1:
        return None
    text, values, kinds, expansions = matches[0]
    entry: dict[str, Any] = {
        "choice_kind": "origin_skill",
        "choice_id": origin_id,
        "required_count": 1,
        "allowed_values": values,
        "duplicate_result": "expertise",
        "source_text": text,
        "source_evidence": source_evidence,
    }
    if any(kind != "skill" for kind in kinds.values()):
        # Skill-only Origins keep their v1 entry shape exactly; Origins with
        # tool, trade or language options add the option typing and the
        # registry binding.
        entry["option_kinds"] = {value: kinds[value] for value in values}
        authority: dict[str, Any] = {
            "authority": "authenticated_tool_proficiency_registry",
            "registry_id": _TOOL_REGISTRY["registry_id"],
            "registry_sha256": _TOOL_REGISTRY["sha256"],
            "scope": _TOOL_REGISTRY["scope"],
            "offered_set_complete": False,
            "tool_ids": {
                value: _registry_tool(value)["tool_id"]
                for value in values
                if kinds[value] == "tool"
            },
        }
        if any(kind == "trade" for kind in kinds.values()):
            authority["trade_ids"] = {
                value: _registry_trade(value)["trade_id"]
                for value in values
                if kinds[value] == "trade"
            }
        if any(kind == "language" for kind in kinds.values()):
            authority["language_categories"] = {
                phrase: list(names)
                for phrase, names in expansions.items()
                if any(kinds.get(name) == "language" for name in names)
            }
        entry["tool_authority"] = authority
        if expansions:
            entry["category_expansions"] = expansions
    return entry


def origin_starting_proficiency_unresolved(origin_id: str, row: Any) -> bool:
    """True when an Origin would be rejected by the validator if selected.

    Mirrors ``unresolved_origin_proficiency_ids``: the frozen text states
    proficiency mechanics but the Origin grammar cannot resolve them into a
    typed skill choice. Stage 1 uses this to keep such Origins out of the
    presented set instead of letting a lock or a pick fail at validation.
    """
    return _origin_entry(origin_id, row) is None and _origin_proficiency_mechanics_present(row)


def _origin_proficiency_mechanics_present(row: Any) -> bool:
    """Detect only explicit proficiency mechanics in frozen Origin text.

    This marker is intentionally narrower than the full Origin grammar.  It
    lets the validator distinguish an ordinary unresolved Origin (which may
    legitimately have no skill subchoice) from a malformed mandatory skill
    rule that must not silently pass.
    """
    if not isinstance(row, dict):
        return False
    try:
        pattern = re.compile(r"\b(?:proficiency|proficient|expertise)\b", re.IGNORECASE)
        return any(pattern.search(text) is not None for text in _origin_texts(row))
    except (TypeError, ValueError):
        return False


def _origin_unresolved_row(
    choice_id: Any,
    reason: str,
    row: Any = None,
) -> dict[str, Any]:
    return {
        "field": "origin_skill_choices_by_origin_id",
        "choice_id": choice_id,
        "reason": reason,
        "proficiency_mechanics_present": _origin_proficiency_mechanics_present(row),
    }


def _campaign_language_contract(
    source_text: str,
    source: Any,
) -> dict[str, Any] | None:
    if not isinstance(source_text, str) or not isinstance(source, dict):
        return None
    source_path = source.get("path") or source.get("source_path")
    source_hash = source.get("source_hash") or source.get("sha256")
    if not _nonempty_string(source_path) or not _hex_hash(source_hash):
        return None
    # The caller binds the exact source bytes it supplied.  CRLF/CR is
    # normalized only for locating and comparing the bounded Markdown section;
    # it never changes the source commitment itself.
    if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != source_hash:
        return None
    normalized = source_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    try:
        start = lines.index(_LANGUAGE_HEADING)
    except ValueError:
        return None
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end]).rstrip("\n")
    expected = f"{_LANGUAGE_HEADING}\n\n{_LANGUAGE_BODY}\n\n{_LANGUAGE_QUALIFIER}"
    if section != expected:
        return None
    return {
        "authority": "authenticated_background_source_section",
        "scope": "source-backed offered display set; not a complete language registry",
        "offered_set_complete": False,
        "offered_display_names": list(_LANGUAGE_DISPLAYS),
        "source": {
            **deepcopy(source),
            "anchor": "heading:campaign-languages-and-cants",
            "section_sha256": hashlib.sha256(section.encode("utf-8")).hexdigest(),
        },
    }


def build_starting_proficiency_choice_contract(
    *,
    path_profiles: dict,
    backgrounds: dict,
    choices_by_slot: dict,
    allowed_choice_ids_by_slot: dict,
    campaign_language_source_text: str,
    campaign_language_source: dict,
) -> dict:
    """Build a deterministic, source-bound starting-proficiency contract.

    Every allowed ID is checked against both the frozen presented row and the
    supplied server authority.  Unresolved IDs are retained only as bounded
    diagnostics and never receive a selectable enum.
    """
    fields: dict[str, dict[str, Any]] = {
        "path_skill_choices_by_path_id": {},
        "origin_skill_choices_by_origin_id": {},
        "background_language_choices_by_background_id": {},
    }
    unresolved: list[dict[str, Any]] = []
    path_profiles = path_profiles if isinstance(path_profiles, dict) else {}
    backgrounds = backgrounds if isinstance(backgrounds, dict) else {}
    choices_by_slot = choices_by_slot if isinstance(choices_by_slot, dict) else {}
    allowed_choice_ids_by_slot = (
        allowed_choice_ids_by_slot if isinstance(allowed_choice_ids_by_slot, dict) else {}
    )

    for path_id in allowed_choice_ids_by_slot.get("path_choice") or []:
        if not isinstance(path_id, str) or not path_id.strip():
            unresolved.append({"field": "path_skill_choices_by_path_id", "choice_id": path_id, "reason": "invalid_id"})
            continue
        if _frozen_row(choices_by_slot, allowed_choice_ids_by_slot, "path_choice", path_id) is None:
            unresolved.append({"field": "path_skill_choices_by_path_id", "choice_id": path_id, "reason": "frozen_row_mismatch"})
            continue
        entry = _path_entry(path_id, path_profiles.get(path_id))
        if entry is None:
            unresolved.append({"field": "path_skill_choices_by_path_id", "choice_id": path_id, "reason": "authority_unresolved"})
            continue
        fields["path_skill_choices_by_path_id"][path_id] = entry

    language_contract = _campaign_language_contract(
        campaign_language_source_text,
        campaign_language_source,
    )
    for background_id in allowed_choice_ids_by_slot.get("background_choice") or []:
        if not isinstance(background_id, str) or not background_id.strip():
            unresolved.append({"field": "background_language_choices_by_background_id", "choice_id": background_id, "reason": "invalid_id"})
            continue
        if _frozen_row(choices_by_slot, allowed_choice_ids_by_slot, "background_choice", background_id) is None:
            unresolved.append({"field": "background_language_choices_by_background_id", "choice_id": background_id, "reason": "frozen_row_mismatch"})
            continue
        entry = _background_entry(background_id, backgrounds.get(background_id), language_contract)
        if entry is None:
            unresolved.append({"field": "background_language_choices_by_background_id", "choice_id": background_id, "reason": "authority_unresolved"})
            continue
        fields["background_language_choices_by_background_id"][background_id] = entry

    origin_rows = choices_by_slot.get("origin_insight_choice")
    for origin_id in allowed_choice_ids_by_slot.get("origin_insight_choice") or []:
        if not isinstance(origin_id, str) or not origin_id.strip():
            unresolved.append(_origin_unresolved_row(origin_id, "invalid_id"))
            continue
        if _frozen_row(choices_by_slot, allowed_choice_ids_by_slot, "origin_insight_choice", origin_id) is None:
            unresolved.append(_origin_unresolved_row(origin_id, "frozen_row_mismatch"))
            continue
        row = origin_rows.get(origin_id) if isinstance(origin_rows, dict) else None
        entry = _origin_entry(origin_id, row)
        if entry is None:
            unresolved.append(_origin_unresolved_row(origin_id, "source_grammar_unresolved", row))
            continue
        fields["origin_skill_choices_by_origin_id"][origin_id] = entry

    unsigned = {
        "schema": CONTRACT_SCHEMA,
        "fields": fields,
        "unresolved": unresolved,
        "policy": {
            "fixed_background_grants_server_owned": True,
            "planner_prose_is_authority": False,
            "language_registry_complete": False,
            "origin_duplicate_proficiency_result": "expertise",
        },
    }
    result = deepcopy(unsigned)
    result["contract_sha256"] = _sha256(unsigned)
    return result


def _typed_blocker(code: str, **details: Any) -> dict[str, Any]:
    """Create a bounded, JSON-safe validation diagnostic.

    The response is model-controlled, so diagnostics deliberately carry only
    field names, IDs, counts, and other small scalar facts.  In particular,
    they never echo a submitted value or source prose.
    """
    result: dict[str, Any] = {"code": code}
    for key, value in details.items():
        if isinstance(value, (str, int, bool)) or value is None:
            result[key] = value
        elif isinstance(value, list) and all(
            isinstance(item, (str, int, bool)) or item is None for item in value
        ):
            result[key] = list(value)
    return result


def _sort_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        blockers,
        key=lambda row: (
            row.get("code", "") if isinstance(row.get("code"), str) else "",
            _canonical_bytes(row),
        ),
    )


def _safe_identifier(value: Any) -> bool:
    return _nonempty_string(value) and value == value.strip()


def _safe_string_list(value: Any, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_safe_identifier(item) for item in value)
        and len(set(value)) == len(value)
    )


def _validate_contract_entry(
    field: str,
    choice_id: Any,
    entry: Any,
    blockers: list[dict[str, Any]],
) -> bool:
    """Validate the builder's v1 entry shape, including its authority kind."""
    if not _safe_identifier(choice_id) or not isinstance(entry, dict):
        blockers.append(_typed_blocker("CONTRACT_ENTRY_INVALID", field=field))
        return False
    expected_keys_by_field = {
        "path_skill_choices_by_path_id": {
            "choice_kind", "choice_id", "required_count", "allowed_values", "source",
        },
        "origin_skill_choices_by_origin_id": {
            "choice_kind", "choice_id", "required_count", "allowed_values",
            "duplicate_result", "source_text", "source_evidence",
            *_ORIGIN_OPTIONAL_ENTRY_KEYS,
        },
        "background_language_choices_by_background_id": {
            "choice_kind", "choice_id", "fixed_skill_names",
            "fixed_tool_proficiencies", "language_choice_count", "resolved",
            "source", "allowed_values", "language_authority",
        },
    }
    if not set(entry).issubset(expected_keys_by_field[field]):
        blockers.append(_typed_blocker("CONTRACT_ENTRY_SCHEMA_INVALID", field=field))
        return False
    kind = entry.get("choice_kind")
    expected_kind = {
        "path_skill_choices_by_path_id": "path_skill",
        "background_language_choices_by_background_id": "background_language",
        "origin_skill_choices_by_origin_id": "origin_skill",
    }[field]
    if entry.get("choice_id") != choice_id or kind != expected_kind:
        blockers.append(_typed_blocker(
            "CONTRACT_ENTRY_ID_OR_KIND_INVALID",
            field=field,
            choice_id=choice_id,
        ))
        return False

    # Background entries describe a fixed-grant row plus an optional language
    # selection; unlike path/origin entries they intentionally have no
    # ``required_count`` member (their count is ``language_choice_count``).
    if field == "background_language_choices_by_background_id":
        fixed_skills = entry.get("fixed_skill_names")
        fixed_tools = entry.get("fixed_tool_proficiencies")
        language_count = entry.get("language_choice_count")
        if (
            entry.get("resolved") is not True
            or not _safe_string_list(fixed_skills)
            or any(item not in _SKILLS for item in fixed_skills)
            or not _safe_string_list(fixed_tools)
            or type(language_count) is not int
            or language_count < 0
            or language_count > 1
            or not isinstance(entry.get("source"), dict)
            or not _nonempty_string(entry["source"].get("path"))
        ):
            blockers.append(_typed_blocker(
                "CONTRACT_ENTRY_BACKGROUND_GRANTS_INVALID",
                field=field,
                choice_id=choice_id,
            ))
            return False
        allowed = entry.get("allowed_values")
        if language_count == 0:
            if allowed != [] or "language_authority" in entry:
                blockers.append(_typed_blocker(
                    "CONTRACT_ENTRY_LANGUAGE_AUTHORITY_INVALID",
                    field=field,
                    choice_id=choice_id,
                ))
                return False
        else:
            authority = entry.get("language_authority")
            if (
                not _safe_string_list(allowed, allow_empty=False)
                or not isinstance(authority, dict)
                or authority.get("offered_set_complete") is not False
                or authority.get("offered_display_names") != allowed
                or not _nonempty_string(authority.get("scope"))
                or not isinstance(authority.get("source"), dict)
                or not _hex_hash(authority["source"].get("source_hash"))
            ):
                blockers.append(_typed_blocker(
                    "CONTRACT_ENTRY_LANGUAGE_AUTHORITY_INVALID",
                    field=field,
                    choice_id=choice_id,
                ))
                return False
        return True

    required = entry.get("required_count")
    if type(required) is not int or required < 1:
        blockers.append(_typed_blocker(
            "CONTRACT_ENTRY_COUNT_INVALID",
            field=field,
            choice_id=choice_id,
        ))
        return False
    allowed = entry.get("allowed_values")
    if not _safe_string_list(allowed, allow_empty=False):
        blockers.append(_typed_blocker(
            "CONTRACT_ENTRY_ALLOWED_VALUES_INVALID",
            field=field,
            choice_id=choice_id,
        ))
        return False
    if required > len(allowed):
        blockers.append(_typed_blocker(
            "CONTRACT_ENTRY_COUNT_EXCEEDS_ENUM",
            field=field,
            choice_id=choice_id,
        ))
        return False

    if field == "path_skill_choices_by_path_id":
        if any(item not in _SKILLS for item in allowed):
            blockers.append(_typed_blocker(
                "CONTRACT_ENTRY_SKILL_ENUM_INVALID",
                field=field,
                choice_id=choice_id,
            ))
            return False
        source = entry.get("source")
        if (
            not isinstance(source, dict)
            or not _nonempty_string(source.get("factory_path"))
            or not _hex_hash(source.get("source_hash"))
        ):
            blockers.append(_typed_blocker(
                "CONTRACT_ENTRY_SOURCE_INVALID",
                field=field,
                choice_id=choice_id,
            ))
            return False
        return True

    if field == "origin_skill_choices_by_origin_id":
        if (
            required != 1
            or entry.get("duplicate_result") != "expertise"
            or not _nonempty_string(entry.get("source_text"))
        ):
            blockers.append(_typed_blocker(
                "CONTRACT_ENTRY_ORIGIN_RULE_INVALID",
                field=field,
                choice_id=choice_id,
            ))
            return False
        if "option_kinds" not in entry:
            # v1 skill-only entry: no tool keys, every option a skill.
            if (
                any(key in entry for key in _ORIGIN_OPTIONAL_ENTRY_KEYS)
                or any(item not in _SKILLS for item in allowed)
            ):
                blockers.append(_typed_blocker(
                    "CONTRACT_ENTRY_ORIGIN_RULE_INVALID",
                    field=field,
                    choice_id=choice_id,
                ))
                return False
        elif not _valid_origin_tool_typing(entry, allowed):
            blockers.append(_typed_blocker(
                "CONTRACT_ENTRY_TOOL_AUTHORITY_INVALID",
                field=field,
                choice_id=choice_id,
            ))
            return False
        evidence = entry.get("source_evidence")
        if (
            not isinstance(evidence, list)
            or len(evidence) != 1
            or not isinstance(evidence[0], dict)
            or not _nonempty_string(evidence[0].get("source_path"))
            or not _hex_hash(evidence[0].get("source_hash"))
            or not _nonempty_string(evidence[0].get("source_anchor"))
        ):
            blockers.append(_typed_blocker(
                "CONTRACT_ENTRY_SOURCE_INVALID",
                field=field,
                choice_id=choice_id,
            ))
            return False
        return True

    return False


def _valid_origin_tool_typing(entry: dict[str, Any], allowed: list[str]) -> bool:
    """Check a typed Origin entry (tools, trades, languages) for coherence.

    The contract is server-built and sealed, so the validator checks the
    entry against itself and against invariants that do not depend on the
    registry bytes: option typing covers exactly the allowed values, every
    tool or trade id is the canonical id of its display name, every language
    is an offered campaign-language name, and every category expansion lists
    typed options.  When this process holds the same registry the entry was
    sealed against, membership is enforced as well; a later registry edit
    therefore never invalidates an already sealed request.
    """
    kinds = entry.get("option_kinds")
    authority = entry.get("tool_authority")
    if (
        not isinstance(kinds, dict)
        # Sealed requests are stored as canonical (key-sorted) JSON, so the
        # typing map's key order is not significant; its key set is.
        or set(kinds) != set(allowed)
        or len(kinds) != len(allowed)
        or any(kind not in _OPTION_KINDS for kind in kinds.values())
        or all(kind == "skill" for kind in kinds.values())
        or not isinstance(authority, dict)
    ):
        return False
    base_keys = {"authority", "registry_id", "registry_sha256", "scope", "offered_set_complete", "tool_ids"}
    if (
        not base_keys <= set(authority)
        or not set(authority) <= base_keys | {"trade_ids", "language_categories"}
        or not _nonempty_string(authority.get("authority"))
        or not _nonempty_string(authority.get("registry_id"))
        or not _hex_hash(authority.get("registry_sha256"))
        or not _nonempty_string(authority.get("scope"))
        or authority.get("offered_set_complete") is not False
    ):
        return False
    same_registry = _TOOL_REGISTRY is not None and authority["registry_sha256"] == _TOOL_REGISTRY["sha256"]
    tool_values = [value for value, kind in kinds.items() if kind == "tool"]
    trade_values = [value for value, kind in kinds.items() if kind == "trade"]
    language_values = [value for value, kind in kinds.items() if kind == "language"]
    tool_ids = authority.get("tool_ids")
    if not isinstance(tool_ids, dict) or set(tool_ids) != set(tool_values):
        return False
    for value in tool_values:
        if tool_ids[value] != f"{_TOOL_ID_PREFIX}{_rule_slug(value)}":
            return False
        if same_registry:
            tool = _registry_tool(value)
            if tool is None or tool["display_name"] != value:
                return False
    trade_ids = authority.get("trade_ids", {})
    if bool(trade_values) != ("trade_ids" in authority) or not isinstance(trade_ids, dict) or set(trade_ids) != set(trade_values):
        return False
    for value in trade_values:
        if trade_ids[value] != f"{_TRADE_ID_PREFIX}{_rule_slug(value)}":
            return False
        if same_registry:
            trade = _registry_trade(value)
            if trade is None or trade["display_name"] != value:
                return False
    categories = authority.get("language_categories", {})
    if bool(language_values) != ("language_categories" in authority) or not isinstance(categories, dict):
        return False
    covered_languages: set[str] = set()
    for phrase, names in categories.items():
        if (
            not _nonempty_string(phrase)
            or not _safe_string_list(names, allow_empty=False)
            or any(name not in _LANGUAGE_DISPLAYS or kinds.get(name) != "language" for name in names)
        ):
            return False
        if same_registry:
            category = _TOOL_REGISTRY["by_phrase"].get(_tool_key(phrase))
            if category is None or category["kind"] != "language" or list(category["row"]["offered_display_names"]) != list(names):
                return False
        covered_languages.update(names)
    if set(language_values) != covered_languages:
        return False
    for value, kind in kinds.items():
        if kind == "skill" and value not in _SKILLS:
            return False
    expansions = entry.get("category_expansions", {})
    if not isinstance(expansions, dict):
        return False
    for phrase, displays in expansions.items():
        if (
            not _nonempty_string(phrase)
            or not _safe_string_list(displays, allow_empty=False)
            or any(kinds.get(display) in (None, "skill") for display in displays)
        ):
            return False
        if same_registry:
            key = _tool_key(phrase)
            if key not in _ARTISAN_CATEGORY_KEYS and key not in _TOOL_REGISTRY["by_phrase"]:
                return False
    return True


def _validated_contract_parts(
    contract: Any,
    blockers: list[dict[str, Any]],
) -> tuple[
    str | None,
    dict[str, dict[str, Any]],
    dict[str, set[str]],
    set[str],
]:
    """Validate a sealed v1 contract and return its usable field maps."""
    if not isinstance(contract, dict):
        blockers.append(_typed_blocker("CONTRACT_SHAPE_INVALID"))
        return None, {}, {field: set() for field in _CHOICE_FIELDS}, set()
    expected_keys = {"schema", "fields", "unresolved", "policy", "contract_sha256"}
    if set(contract) != expected_keys:
        blockers.append(_typed_blocker("CONTRACT_SCHEMA_INVALID"))
    if contract.get("schema") != CONTRACT_SCHEMA:
        blockers.append(_typed_blocker("CONTRACT_SCHEMA_INVALID"))
    fields = contract.get("fields")
    if not isinstance(fields, dict) or set(fields) != set(_CHOICE_FIELDS):
        blockers.append(_typed_blocker("CONTRACT_FIELDS_INVALID"))
        fields = fields if isinstance(fields, dict) else {}
    unresolved = contract.get("unresolved")
    if not isinstance(unresolved, list):
        blockers.append(_typed_blocker("CONTRACT_UNRESOLVED_INVALID"))
        unresolved = []
    else:
        for row in unresolved:
            if (
                not isinstance(row, dict)
                or row.get("field") not in _CHOICE_FIELDS
                or not _safe_identifier(row.get("choice_id"))
                or not _safe_identifier(row.get("reason"))
            ):
                blockers.append(_typed_blocker("CONTRACT_UNRESOLVED_INVALID"))
                break
            marker = row.get("proficiency_mechanics_present")
            if row["field"] == "origin_skill_choices_by_origin_id":
                if type(marker) is not bool:
                    blockers.append(_typed_blocker(
                        "CONTRACT_ORIGIN_PROFICIENCY_MARKER_INVALID",
                    ))
                    break
            elif "proficiency_mechanics_present" in row:
                blockers.append(_typed_blocker("CONTRACT_UNRESOLVED_INVALID"))
                break
    expected_policy = {
        "fixed_background_grants_server_owned": True,
        "planner_prose_is_authority": False,
        "language_registry_complete": False,
        "origin_duplicate_proficiency_result": "expertise",
    }
    if contract.get("policy") != expected_policy:
        blockers.append(_typed_blocker("CONTRACT_POLICY_INVALID"))

    contract_hash = contract.get("contract_sha256")
    if not _hex_hash(contract_hash):
        blockers.append(_typed_blocker("CONTRACT_HASH_INVALID"))
        contract_hash = None
    else:
        unsigned = {key: contract[key] for key in expected_keys if key != "contract_sha256"}
        try:
            computed = _sha256(unsigned)
        except (TypeError, ValueError):
            computed = None
        if computed != contract_hash:
            blockers.append(_typed_blocker("CONTRACT_HASH_MISMATCH"))

    valid_fields: dict[str, dict[str, Any]] = {
        field: {} for field in _CHOICE_FIELDS
    }
    for field in _CHOICE_FIELDS:
        field_rows = fields.get(field)
        if not isinstance(field_rows, dict):
            blockers.append(_typed_blocker("CONTRACT_FIELD_MAP_INVALID", field=field))
            continue
        for choice_id, entry in field_rows.items():
            if _validate_contract_entry(field, choice_id, entry, blockers):
                valid_fields[field][choice_id] = entry

    unresolved_ids = {field: set() for field in _CHOICE_FIELDS}
    unresolved_origin_proficiency_ids: set[str] = set()
    for row in unresolved:
        if isinstance(row, dict) and row.get("field") in unresolved_ids:
            choice_id = row.get("choice_id")
            if _safe_identifier(choice_id):
                unresolved_ids[row["field"]].add(choice_id)
                if (
                    row["field"] == "origin_skill_choices_by_origin_id"
                    and row.get("proficiency_mechanics_present") is True
                ):
                    unresolved_origin_proficiency_ids.add(choice_id)
    return (
        contract_hash,
        valid_fields,
        unresolved_ids,
        unresolved_origin_proficiency_ids,
    )


def _validate_selected_ids(
    selected_by_slot: Any,
    valid_fields: dict[str, dict[str, Any]],
    unresolved_ids: dict[str, set[str]],
    unresolved_origin_proficiency_ids: set[str],
    blockers: list[dict[str, Any]],
) -> dict[str, list[str]]:
    if not isinstance(selected_by_slot, dict):
        blockers.append(_typed_blocker("SELECTED_BY_SLOT_SHAPE_INVALID"))
        return {slot: [] for slot in _SELECTED_SLOTS}
    expected_slots = set(_SELECTED_SLOTS)
    for slot in sorted(set(selected_by_slot) - expected_slots):
        blockers.append(_typed_blocker("SELECTED_BY_SLOT_KEY_UNKNOWN", slot=slot if isinstance(slot, str) else None))
    for slot in _SELECTED_SLOTS:
        if slot not in selected_by_slot:
            blockers.append(_typed_blocker("SELECTED_BY_SLOT_KEY_MISSING", slot=slot))
    selected: dict[str, list[str]] = {}
    for field, slot in _FIELD_TO_SLOT.items():
        raw = selected_by_slot.get(slot)
        if not isinstance(raw, list):
            blockers.append(_typed_blocker("SELECTED_ID_LIST_SHAPE_INVALID", slot=slot))
            selected[slot] = []
            continue
        values = list(raw)
        if any(not _safe_identifier(value) for value in values):
            blockers.append(_typed_blocker("SELECTED_ID_INVALID", slot=slot))
        if len(set(value for value in values if _safe_identifier(value))) != len(
            [value for value in values if _safe_identifier(value)]
        ):
            blockers.append(_typed_blocker("SELECTED_ID_DUPLICATE", slot=slot))
        selected[slot] = values
        known = set(valid_fields[field]) | unresolved_ids[field]
        for value in values:
            if not _safe_identifier(value):
                continue
            if value not in known:
                blockers.append(_typed_blocker("SELECTED_ID_UNKNOWN", slot=slot))
            elif value in unresolved_ids[field]:
                if (
                    field == "origin_skill_choices_by_origin_id"
                    and value in unresolved_origin_proficiency_ids
                ):
                    blockers.append(_typed_blocker(
                        "SELECTED_ORIGIN_PROFICIENCY_AUTHORITY_UNRESOLVED",
                        slot=slot,
                    ))
                elif field != "origin_skill_choices_by_origin_id":
                    blockers.append(_typed_blocker("SELECTED_AUTHORITY_UNRESOLVED", slot=slot))

    path_entries = valid_fields["path_skill_choices_by_path_id"]
    if path_entries and not selected["path_choice"]:
        blockers.append(_typed_blocker("PATH_SELECTION_REQUIRED"))
    background_entries = valid_fields["background_language_choices_by_background_id"]
    if background_entries and len(selected["background_choice"]) != 1:
        blockers.append(_typed_blocker(
            "BACKGROUND_SELECTION_CARDINALITY",
            expected=1,
        ))
    origin_entries = valid_fields["origin_skill_choices_by_origin_id"]
    if origin_entries and not selected["origin_insight_choice"]:
        blockers.append(_typed_blocker("ORIGIN_SELECTION_REQUIRED"))
    if len(selected["origin_insight_choice"]) > 1:
        blockers.append(_typed_blocker("ORIGIN_SELECTION_CARDINALITY", expected=1))
    return selected


def _validate_choice_map(
    *,
    field: str,
    actual: Any,
    selected: list[str],
    entries: dict[str, dict[str, Any]],
    unresolved_ids: set[str],
    blockers: list[dict[str, Any]],
) -> dict[str, list[str]]:
    expected = {
        choice_id
        for choice_id in selected
        if choice_id in entries
        and (
            entries[choice_id].get("language_choice_count", 0)
            if field == "background_language_choices_by_background_id"
            else entries[choice_id].get("required_count", 0)
        ) > 0
    }
    if actual is None:
        actual = {}
    if not isinstance(actual, dict):
        blockers.append(_typed_blocker("BOUNDED_CHOICE_MAP_SHAPE_INVALID", field=field))
        return {}
    actual_keys = set(actual)
    for choice_id in sorted(expected - actual_keys):
        blockers.append(_typed_blocker("BOUNDED_CHOICE_MAP_KEY_MISSING", field=field))
    for choice_id in sorted(actual_keys - expected, key=lambda value: str(value)):
        blockers.append(_typed_blocker("BOUNDED_CHOICE_MAP_KEY_EXTRA", field=field))
    normalized: dict[str, list[str]] = {}
    for choice_id in sorted(expected):
        value = actual.get(choice_id)
        if not isinstance(value, list):
            blockers.append(_typed_blocker("BOUNDED_CHOICE_VALUE_SHAPE_INVALID", field=field))
            continue
        entry = entries[choice_id]
        count = (
            entry["language_choice_count"]
            if field == "background_language_choices_by_background_id"
            else entry["required_count"]
        )
        allowed = entry["allowed_values"]
        if len(value) != count:
            blockers.append(_typed_blocker("BOUNDED_CHOICE_VALUE_COUNT_INVALID", field=field))
        if any(not isinstance(item, str) for item in value):
            blockers.append(_typed_blocker("BOUNDED_CHOICE_VALUE_TYPE_INVALID", field=field))
            continue
        if len(set(value)) != len(value):
            blockers.append(_typed_blocker("BOUNDED_CHOICE_VALUE_DUPLICATE", field=field))
        if any(item not in allowed for item in value):
            blockers.append(_typed_blocker("BOUNDED_CHOICE_VALUE_ILLEGAL", field=field))
        normalized[choice_id] = list(value)
    # An unresolved origin is intentionally not selectable, but a map value
    # for it (or any other unresolved ID) is still an extra model assertion.
    for choice_id in unresolved_ids & actual_keys:
        blockers.append(_typed_blocker("BOUNDED_CHOICE_UNRESOLVED_ID", field=field))
    return normalized


def _stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _build_normalized_mechanics(
    selected: dict[str, list[str]],
    path_values: dict[str, list[str]],
    background_values: dict[str, list[str]],
    origin_values: dict[str, list[str]],
    valid_fields: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path_skills = [
        skill
        for path_id in sorted(path_values)
        for skill in path_values[path_id]
    ]
    background_id = selected["background_choice"][0] if selected["background_choice"] else None
    background_entry = (
        valid_fields["background_language_choices_by_background_id"].get(background_id)
        if background_id is not None
        else None
    )
    fixed_skills = list(background_entry.get("fixed_skill_names", [])) if background_entry else []
    fixed_tools = list(background_entry.get("fixed_tool_proficiencies", [])) if background_entry else []
    selected_languages = list(background_values.get(background_id, [])) if background_id else []

    origin_id = selected["origin_insight_choice"][0] if selected["origin_insight_choice"] else None
    origin_entry = (
        valid_fields["origin_skill_choices_by_origin_id"].get(origin_id)
        if origin_id is not None
        else None
    )
    origin_value = origin_values.get(origin_id, [None])[0] if origin_id else None
    origin_kind = (
        (origin_entry.get("option_kinds") or {}).get(origin_value, "skill")
        if origin_entry is not None
        else "skill"
    )
    origin_skill: str | None = None
    origin_tool: str | None = None
    origin_trade: str | None = None
    origin_language: str | None = None
    normalized_origin: dict[str, Any] | None = None
    tool_duplicate = False
    trade_duplicate = False
    language_duplicate = False
    if origin_entry is not None and isinstance(origin_value, str):
        if origin_kind == "tool":
            # A tool the Background already grants outright becomes expertise,
            # exactly as a repeated skill does (Origin Insights, Design Rules).
            origin_tool = origin_value
            tool_duplicate = _tool_key(origin_tool) in _fixed_tool_keys(fixed_tools)
            origin_result = origin_entry["duplicate_result"] if tool_duplicate else "proficiency"
            normalized_origin = {
                "origin_id": origin_id,
                "selected_skill": None,
                "selected_tool": origin_tool,
                "selected_tool_id": origin_entry["tool_authority"]["tool_ids"].get(origin_tool),
                "result": origin_result,
            }
        elif origin_kind == "trade":
            origin_trade = origin_value
            trade_duplicate = _tool_key(origin_trade) in _fixed_tool_keys(fixed_tools)
            origin_result = origin_entry["duplicate_result"] if trade_duplicate else "proficiency"
            normalized_origin = {
                "origin_id": origin_id,
                "selected_skill": None,
                "selected_trade": origin_trade,
                "selected_trade_id": (origin_entry["tool_authority"].get("trade_ids") or {}).get(origin_trade),
                "result": origin_result,
            }
        elif origin_kind == "language":
            origin_language = origin_value
            language_duplicate = origin_language in selected_languages
            origin_result = origin_entry["duplicate_result"] if language_duplicate else "proficiency"
            normalized_origin = {
                "origin_id": origin_id,
                "selected_skill": None,
                "selected_language": origin_language,
                "result": origin_result,
            }
        else:
            origin_skill = origin_value
            duplicate = origin_skill in fixed_skills or origin_skill in path_skills
            origin_result = origin_entry["duplicate_result"] if duplicate else "proficiency"
            normalized_origin = {
                "origin_id": origin_id,
                "selected_skill": origin_skill,
                "result": origin_result,
            }
    all_skills = _stable_unique(path_skills + fixed_skills + ([origin_skill] if isinstance(origin_skill, str) else []))
    expertise = [origin_skill] if isinstance(origin_skill, str) and normalized_origin and normalized_origin["result"] == "expertise" else []
    all_tools = _stable_unique(fixed_tools + ([origin_tool] if isinstance(origin_tool, str) and not tool_duplicate else []))
    proficiencies: dict[str, Any] = {
        "skills": all_skills,
        "tools": all_tools,
        "languages": selected_languages,
        "expertise": expertise,
    }
    if isinstance(origin_tool, str):
        proficiencies["tool_expertise"] = [origin_tool] if normalized_origin and normalized_origin["result"] == "expertise" else []
    if isinstance(origin_trade, str):
        proficiencies["trades"] = [origin_trade]
        proficiencies["trade_expertise"] = [origin_trade] if normalized_origin and normalized_origin["result"] == "expertise" else []
    if isinstance(origin_language, str):
        proficiencies["languages"] = _stable_unique(selected_languages + [origin_language])
        proficiencies["language_expertise"] = [origin_language] if normalized_origin and normalized_origin["result"] == "expertise" else []
    return {
        "selected_by_slot": deepcopy(selected),
        "path_skill_choices_by_path_id": deepcopy(path_values),
        "background": {
            "background_id": background_id,
            "fixed_skill_names": fixed_skills,
            "fixed_tool_proficiencies": fixed_tools,
            "selected_languages": selected_languages,
        },
        "origin": normalized_origin,
        "proficiencies": proficiencies,
    }


def validate_starting_proficiency_choices(
    *,
    contract: dict,
    selected_by_slot: dict,
    bounded_choices: dict,
) -> dict:
    """Validate and normalize response-authored starting proficiency choices.

    This is deliberately a result-returning validator: malformed model data
    produces a stable, typed blocker list instead of an exception.  The
    contract hash is checked before any response value can become mechanics.
    """
    blockers: list[dict[str, Any]] = []
    contract_hash: str | None = None
    normalized: dict[str, Any] = {}
    try:
        (
            contract_hash,
            valid_fields,
            unresolved_ids,
            unresolved_origin_proficiency_ids,
        ) = _validated_contract_parts(contract, blockers)
        selected = _validate_selected_ids(
            selected_by_slot,
            valid_fields,
            unresolved_ids,
            unresolved_origin_proficiency_ids,
            blockers,
        )
        if not isinstance(bounded_choices, dict):
            blockers.append(_typed_blocker("BOUNDED_CHOICES_SHAPE_INVALID"))
            bounded_choices = {}
        for key in sorted(_FIXED_GRANT_KEYS & set(bounded_choices)):
            blockers.append(_typed_blocker("FIXED_BACKGROUND_GRANT_FORBIDDEN", field=key))

        path_values = _validate_choice_map(
            field="path_skill_choices_by_path_id",
            actual=bounded_choices.get("path_skill_choices_by_path_id"),
            selected=selected["path_choice"],
            entries=valid_fields["path_skill_choices_by_path_id"],
            unresolved_ids=unresolved_ids["path_skill_choices_by_path_id"],
            blockers=blockers,
        )
        background_values = _validate_choice_map(
            field="background_language_choices_by_background_id",
            actual=bounded_choices.get("background_language_choices_by_background_id"),
            selected=selected["background_choice"],
            entries=valid_fields["background_language_choices_by_background_id"],
            unresolved_ids=unresolved_ids["background_language_choices_by_background_id"],
            blockers=blockers,
        )
        origin_values = _validate_choice_map(
            field="origin_skill_choices_by_origin_id",
            actual=bounded_choices.get("origin_skill_choices_by_origin_id"),
            selected=selected["origin_insight_choice"],
            entries=valid_fields["origin_skill_choices_by_origin_id"],
            unresolved_ids=unresolved_ids["origin_skill_choices_by_origin_id"],
            blockers=blockers,
        )
        if not blockers:
            normalized = _build_normalized_mechanics(
                selected,
                path_values,
                background_values,
                origin_values,
                valid_fields,
            )
    except Exception:
        # The public guarantee is fail-closed for arbitrary model-shaped
        # values, including values that are not JSON-serializable.
        blockers.append(_typed_blocker("VALIDATION_INTERNAL_SHAPE_INVALID"))
        normalized = {}

    blockers = _sort_blockers(blockers)
    unsigned = {
        "schema": VALIDATED_SCHEMA,
        "valid": not blockers,
        "blockers": blockers,
        "normalized_mechanics": normalized,
        "contract_sha256": contract_hash,
    }
    try:
        validation_hash = _sha256(unsigned)
    except (TypeError, ValueError):
        # All output values are intentionally bounded JSON primitives.  This
        # fallback protects the no-raise contract if that invariant changes.
        unsigned["normalized_mechanics"] = {}
        validation_hash = _sha256(unsigned)
    return {**unsigned, "validation_sha256": validation_hash}


__all__ = [
    "CONTRACT_SCHEMA",
    "TOOL_REGISTRY_PATH",
    "TOOL_REGISTRY_SCHEMA",
    "VALIDATED_SCHEMA",
    "build_starting_proficiency_choice_contract",
    "tool_proficiency_registry",
    "validate_starting_proficiency_choices",
]
