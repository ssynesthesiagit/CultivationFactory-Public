from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.core import canonical_json, sha256_json
from factory_authoring.native_path_mechanics import native_path_binding
from factory_authoring.native_path_operations import expand_native_operation_cards


ACTION_CANDIDATES_SCHEMA = "TianxiaFoundry.Command4ActionAuthoringCandidates.v1"
ACTION_SURFACE_SCHEMA = "TianxiaFoundry.Command4CompleteActionSurface.v1"
ACTION_AUDIT_SCHEMA = "TianxiaFoundry.Command4ExecutableActionAudit.v1"
TALENT_COVERAGE_SCHEMA = "TianxiaFoundry.Command4TalentExecutionCoverage.v1"
ACTION_ALGORITHM_VERSION = "explicit-label-action-projection.v3"

ACTION_BUCKETS = {
    "Action": "action",
    "Bonus Action": "bonus_action",
    "Reaction": "reaction",
    "Passive": "passive",
    "Ritual Procedure": "procedure",
}

_NONE_COST_VALUES = {
    "none",
    "no action",
    "no cost",
    "no qi",
    "no resource",
    "no resources",
    "no resource cost",
    "no additional resource cost",
    "0",
    "zero",
}
_REQUIRED_FIELDS = (
    "action_id",
    "name",
    "bucket",
    "action_type",
    "timing",
    "cost",
    "range",
    "target",
    "roll_save_check",
    "effect",
    "failure",
    "duration",
    "limit",
    "counterplay",
    "source_packet_ids",
    "resource_costs",
    "resource_gains",
    "resource_requirements",
)

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "action_type": ("Action Type",),
    "canonical_action_type": ("Canonical Action Type",),
    "bucket": ("Factory Combat Bucket",),
    "factory_routing": ("Factory Routing",),
    "timing": ("Timing", "Trigger"),
    "cost": ("Cost",),
    "range": ("Range",),
    "target": ("Target",),
    "area": ("Area",),
    "roll_save_check": ("Roll/Save/Check", "Roll", "Save", "Check"),
    "effect": ("Effect/Success", "Effect", "Success", "Failed Save"),
    "failure": ("Failure", "Successful Save"),
    "duration": ("Duration",),
    "limit": ("Limit", "Limits", "Use Limit"),
    "counterplay": ("Counterplay",),
}
_LABEL_TO_FIELD = {
    label.casefold(): field
    for field, labels in _FIELD_LABELS.items()
    for label in labels
}
_LABEL_PATTERN = "|".join(
    re.escape(label)
    for label in sorted(_LABEL_TO_FIELD, key=len, reverse=True)
)
_LABEL_RE = re.compile(
    rf"^\s*(?:#{{1,6}}\s*)?(?:[-*>]\s*)?(?:\*\*)?(?P<label>{_LABEL_PATTERN})(?:\*\*)?\s*(?:(?::|-)(?:\*\*)?\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)

_SINGLE_LINE_FIELDS = {
    "action_type",
    "bucket",
    "factory_routing",
    "timing",
    "cost",
    "range",
    "target",
    "area",
    "roll_save_check",
    "duration",
    "limit",
    "counterplay",
}

_RESOURCE_ID_ALIASES = {
    "banked heat": "RES_HEAT",
    "martial focus": "RES_MARTIAL_FOCUS",
    "qi": "RES_QI",
    "resolve": "RES_RESOLVE",
}

_RESOURCE_COST_TIMING = "When the action is declared and confirmed legal."
_RESOURCE_COST_CONDITION = "Always for a legal use of this action."
_RESOURCE_REQUIREMENT_CONDITION = "The resource must be available before the action resolves."
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RESOURCE_CLAUSE_RE = re.compile(
    r"^(?P<amount>[0-9]+|one|a|an|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?P<resource>[A-Za-z][A-Za-z0-9_.:/-]*(?:\s+[A-Za-z][A-Za-z0-9_.:/-]*){0,3})$",
    re.IGNORECASE,
)
_SPEND_VERB_RE = re.compile(r"^(?:spend|pay)\s+", re.IGNORECASE)
_EXPEND_RESOURCE_RE = re.compile(
    r"^expend\s+(?P<resource>[A-Za-z][A-Za-z0-9_.:/-]*(?:\s+[A-Za-z][A-Za-z0-9_.:/-]*){0,2})$",
    re.IGNORECASE,
)
# A Cost line that offers a choice of resources ("2 CP or 2 Stamina",
# "Expend Martial Focus if you have it, or spend 5 CP if you do not").
_ALTERNATIVE_COST_RE = re.compile(r"\bor\b", re.IGNORECASE)
_VARIABLE_AMOUNT_RE = re.compile(r"\b[0-9]+\s+or\s+more\b", re.IGNORECASE)
_CHOICE_SEPARATOR_RE = re.compile(r"\s*(?<![0-9]),(?![0-9])\s*(?:or\s+)?|\s+or\s+", re.IGNORECASE)
_CHOICE_CONDITION_RE = re.compile(r"^(?P<base>.*?)\s+(?P<condition>(?:if|when|unless|while)\b.*)$", re.IGNORECASE)
_CHOICE_VERB_RE = re.compile(r"^(?:spend|pay)\s+", re.IGNORECASE)
_CHOICE_SLASH_RE = re.compile(
    r"^(?P<amount>[0-9]+|one|a|an)\s+(?P<left>[A-Za-z][A-Za-z ]*?)\s*/\s*(?P<right>[A-Za-z][A-Za-z ]*?)$",
    re.IGNORECASE,
)
_CHOICE_ELIDED_RE = re.compile(r"^[A-Za-z][A-Za-z ]*$")
# Resources a Cost choice may name.  Anything else keeps the row display-only
# instead of manufacturing a RES_* identity for an ingredient or a price.
_CHOICE_KNOWN_RESOURCES = frozenset({
    "RES_CP", "RES_STAMINA", "RES_QI", "RES_RESONANCE", "RES_MARTIAL_FOCUS", "RES_HEAT", "RES_RESOLVE",
    # Daemonic Cultivation's pool; its single Cost lines already project to
    # this identity through the generic clause grammar.
    "RES_DEVOURED_ESSENCE",
})
_CHOICE_POOL_RESOURCES = frozenset({"RES_CP", "RES_STAMINA", "RES_QI", "RES_RESONANCE"})
_CHOICE_MAX_OPTIONS = 6
_COST_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)?(?:\*\*)?Cost(?:\*\*)?\s*(?::|-)\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_CONTEXT_COST_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)?(?:\*\*)?(?P<context>Ingredient|Refinement)(?:\*\*)?\s*/\s*"
    r"(?:\*\*)?Cost(?:\*\*)?\s*(?::|-)\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_COST_CONTEXT_LABEL_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)?(?:\*\*)?(Ingredient|Refinement)(?:\*\*)?\s*$", re.IGNORECASE)
_PREPARED_SENTENCE_PREFIX = "Throw or launch one prepared "
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?=\s+|$)")
_RECIPE_ACTION_LABEL_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)?(?:\*\*)?(?P<label>Action Type|Factory Combat Bucket|Factory Routing)"
    r"(?:\*\*)?\s*(?::|-)(?:\*\*)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)

# Constructed Immortal Art source authority is issued only after the
# project-record and acquisition-packet proof has been rederived by the
# server.  Keep the transport value opaque to this stateless producer: a
# copied binding dictionary on a card is not sufficient to clear the source
# blocker.
_AUTHENTICATED_IMMORTAL_SOURCE_TOKEN = object()
_CONSTRUCTED_IMMORTAL_RECORD_PREFIX = "tianxia.constructed.immortal_art."


class _AuthenticatedConstructedImmortalSource:
    __slots__ = ("_proof", "_token")

    def __init__(self, proof: Mapping[str, Any], token: object) -> None:
        self._proof = deepcopy(dict(proof))
        self._token = token

    @property
    def proof(self) -> dict[str, Any]:
        return deepcopy(self._proof)


def _issue_authenticated_constructed_immortal_source(
    proof: Mapping[str, Any],
) -> _AuthenticatedConstructedImmortalSource:
    """Issue the producer's private server-controlled proof transport."""

    if not isinstance(proof, Mapping):
        raise TypeError("constructed Immortal Art proof must be a mapping")
    return _AuthenticatedConstructedImmortalSource(
        proof,
        _AUTHENTICATED_IMMORTAL_SOURCE_TOKEN,
    )


def _authenticated_constructed_immortal_binding(
    card: Mapping[str, Any],
    authority: Any,
    *,
    expected_project_id: str | None,
) -> dict[str, Any] | None:
    """Return a proof binding only for an internally issued authority value."""

    if not isinstance(authority, _AuthenticatedConstructedImmortalSource):
        return None
    if authority._token is not _AUTHENTICATED_IMMORTAL_SOURCE_TOKEN:
        return None
    if not isinstance(expected_project_id, str) or not expected_project_id.strip():
        return None
    proof = authority.proof
    binding = proof.get("constructed_immortal_source_binding")
    record_id = card.get("record_id")
    packet_ids = card.get("source_packet_ids")
    if (
        not isinstance(binding, Mapping)
        or not isinstance(record_id, str)
        or binding.get("record_id") != record_id
        or binding.get("project_id") != expected_project_id
        or proof.get("project_id") != expected_project_id
        or binding.get("record_hash") != card.get("record_hash")
        or binding.get("source") != card.get("source")
        or binding.get("name") != card.get("display_name")
        or binding.get("full_description") != card.get("full_description")
        or any(
            proof.get(key) != binding.get("source", {}).get(field)
            for key, field in (("path", "path"), ("anchor", "anchor"), ("sha256", "sha256"))
        )
        or proof.get("source_packet_ids") != packet_ids
        or not isinstance(packet_ids, list)
        or not packet_ids
        or len(packet_ids) != len(set(packet_ids))
    ):
        return None
    return deepcopy(dict(binding))


def _identity_slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _resource_transaction(resource_id: str, amount: int) -> dict[str, Any]:
    return {
        "resource_id": resource_id,
        "amount": amount,
        "timing": _RESOURCE_COST_TIMING,
        "condition": _RESOURCE_COST_CONDITION,
    }


def _resource_requirement(transaction: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "resource_id": transaction["resource_id"],
        "minimum": transaction["amount"],
        "condition": _RESOURCE_REQUIREMENT_CONDITION,
    }


def _source_cost_values(description: Any) -> tuple[list[str], list[dict[str, str]]]:
    """Split action Cost lines from the exact recipe/refinement contexts."""

    if not isinstance(description, str):
        return [], []
    action_values: list[str] = []
    contextual: list[dict[str, str]] = []
    context: str | None = None
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        inline = _CONTEXT_COST_LINE_RE.fullmatch(line)
        if inline is not None:
            value = inline.group("value").strip()
            if value:
                contextual.append({"context": inline.group("context").casefold(), "value": value})
            else:
                contextual.append({"context": inline.group("context").casefold(), "value": ""})
            context = None
            continue
        context_match = _COST_CONTEXT_LABEL_RE.fullmatch(line)
        if context_match is not None:
            context = context_match.group(1).casefold()
            continue
        cost_match = _COST_LINE_RE.fullmatch(line)
        if cost_match is not None:
            value = cost_match.group("value").strip()
            if context is None:
                action_values.append(value)
            else:
                contextual.append({"context": context, "value": value})
            context = None
            continue
        # A recipe/refinement context only scopes its immediately following
        # Cost line (apart from blank separators).  Never let unrelated prose
        # inherit that context.
        context = None
    return action_values, contextual


def _source_sentences(description: Any) -> list[tuple[int, str]]:
    if not isinstance(description, str):
        return []
    result: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(description.splitlines()):
        for sentence in _SENTENCE_SPLIT_RE.split(raw_line.strip()):
            normalized = " ".join(sentence.strip().split())
            if normalized:
                result.append((line_number, normalized))
    return result


def _prepared_action_sentences(description: Any) -> list[tuple[int, str]]:
    """Return canonical prepared-item sentence candidates by source line.

    Source whitespace is normalized by collapsing runs and trimming the
    sentence.  Only a sentence beginning with the exact canonical verb is a
    candidate; its candidate-name text, case, and terminal period are checked
    by ``_prepared_item_clause``.
    """

    prefix = _PREPARED_SENTENCE_PREFIX.casefold()
    return [
        (line_number, sentence)
        for line_number, sentence in _source_sentences(description)
        if sentence.casefold().startswith(prefix)
    ]


def _validate_prepared_recipe_shape(
    description: Any,
    *,
    expected_action_type: Any = None,
) -> str | None:
    """Validate the sole multi-cost prepared-item source grammar.

    The producer and provider must make the same decision about whether a
    pair of recipe costs is executable.  This predicate therefore owns the
    complete shape: exactly ``Ingredient`` then ``Refinement`` costs, the
    canonical action labels after them, and one exact prepared-item sentence
    after those labels.  A standalone Cost line remains valid for ordinary
    actions because a source without recipe context and without a prepared
    sentence returns ``None``.
    """

    if not isinstance(description, str):
        return None
    cost_rows: list[tuple[int, str | None, str]] = []
    context: str | None = None
    action_labels: dict[str, tuple[int, str]] = {}
    for index, raw_line in enumerate(description.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if _CONTEXT_COST_LINE_RE.fullmatch(line):
            return "recipe_cost_context_invalid"
        context_match = _COST_CONTEXT_LABEL_RE.fullmatch(line)
        if context_match is not None:
            context = context_match.group(1).casefold()
            continue
        cost_match = _COST_LINE_RE.fullmatch(line)
        if cost_match is not None:
            cost_rows.append((index, context, cost_match.group("value").strip()))
            context = None
            continue
        action_match = _RECIPE_ACTION_LABEL_RE.fullmatch(line)
        if action_match is not None:
            label = action_match.group("label").casefold()
            key = (
                "action_type" if label == "action type"
                else "bucket" if label == "factory combat bucket"
                else "routing"
            )
            if key in action_labels:
                return "recipe_action_labels_ambiguous"
            action_labels[key] = (index, action_match.group("value").strip())
        # A recipe/refinement heading scopes only its immediately following
        # Cost line (apart from blank separators).  Any intervening prose is
        # unrelated and cannot be promoted to a transaction.
        context = None

    prepared_lines = [index for index, _sentence in _prepared_action_sentences(description)]
    contextual = [row for row in cost_rows if row[1] is not None]
    if not contextual:
        return "recipe_cost_context_invalid" if prepared_lines else None
    if len(cost_rows) != 2 or [row[1] for row in cost_rows] != ["ingredient", "refinement"]:
        return "recipe_cost_context_invalid"
    if any(not row[2] for row in cost_rows):
        return "recipe_cost_context_invalid"
    if set(action_labels) != {"action_type", "bucket", "routing"}:
        return "recipe_action_labels_missing_or_out_of_order"
    last_cost_line = cost_rows[-1][0]
    if any(action_labels[key][0] <= last_cost_line for key in action_labels):
        return "recipe_action_labels_missing_or_out_of_order"
    if len(prepared_lines) != 1:
        return "prepared_item_clause_missing_or_out_of_order"
    last_action_line = max(action_labels[key][0] for key in action_labels)
    if prepared_lines[0] <= last_action_line:
        return "prepared_item_clause_missing_or_out_of_order"

    action_type = _canonical_action_type(action_labels["action_type"][1])
    bucket = _canonical_action_type(action_labels["bucket"][1])
    if action_type is None:
        return "recipe_action_type_mismatch"
    if bucket is None or bucket != action_type:
        return "recipe_bucket_mismatch"
    expected = _canonical_action_type(expected_action_type) if expected_action_type is not None else None
    if expected is not None and action_type != expected:
        return "recipe_action_type_mismatch"
    if not action_labels["routing"][1]:
        return "recipe_routing_missing"
    return None


def _prepared_item_clause(
    description: Any,
    *,
    record_id: Any,
    display_name: Any,
) -> tuple[str | None, str | None]:
    if not isinstance(description, str):
        return None, None
    matches = _prepared_action_sentences(description)
    if not matches:
        return None, None
    related = [
        sentence
        for _line_number, sentence in _source_sentences(description)
        if re.search(r"\b(?:one|a|an|[0-9]+)\s+prepared\b", sentence, re.IGNORECASE)
    ]
    if len(matches) != 1 or len(related) != 1:
        return None, "prepared_item_clause_ambiguous"
    if not isinstance(display_name, str) or not display_name.strip() or not isinstance(record_id, str) or not record_id.strip():
        return None, "prepared_item_identity_missing"
    expected_name = _identity_slug(display_name)
    expected_sentence = " ".join(
        f"{_PREPARED_SENTENCE_PREFIX}{display_name.strip()}.".split()
    )
    if matches[0][1] != expected_sentence:
        # A canonical prepared-item sentence with the wrong name, verb case,
        # punctuation, or suffix is an attempted but unproven transaction.
        return None, "prepared_item_identity_mismatch"
    if not expected_name or expected_name not in _identity_slug(record_id):
        return None, "prepared_item_identity_mismatch"
    return matches[0][1], None


def _parse_explicit_fields(description: Any) -> dict[str, str]:
    """Parse only the small, explicitly labelled action vocabulary."""

    if not isinstance(description, str) or not description.strip():
        return {}
    values: dict[str, list[str]] = {}
    current: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        nonlocal chunks
        if current is not None:
            value = "\n".join(chunks).strip()
            if value:
                values.setdefault(current, []).append(value)
        chunks = []

    for line in description.splitlines():
        match = _LABEL_RE.match(line)
        if match:
            flush()
            current = _LABEL_TO_FIELD[match.group("label").casefold()]
            value = match.group("value")
            if value and value.strip():
                chunks.append(value.strip())
            continue
        if current in _SINGLE_LINE_FIELDS and not line.strip():
            # Canonical source text separates scalar labels such as Cost and
            # Range from the following rules paragraph with a blank line.  Do
            # not let that prose become part of the scalar value.
            flush()
            current = None
            continue
        if current is not None:
            chunks.append(line.rstrip())
    flush()
    return {field: "\n\n".join(parts).strip() for field, parts in values.items() if parts}


def _canonical_action_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    folded = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
    for display, bucket in ACTION_BUCKETS.items():
        if folded in {
            " ".join(display.casefold().split()),
            " ".join(bucket.casefold().replace("_", " ").split()),
        }:
            return bucket
    return None


def _canonical_bucket(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    folded = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
    for display, bucket in ACTION_BUCKETS.items():
        if folded in {
            " ".join(display.casefold().split()),
            " ".join(bucket.casefold().replace("_", " ").split()),
        }:
            return bucket
    return None


def _canonical_resource_id(value: str) -> str:
    normalized = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
    alias = _RESOURCE_ID_ALIASES.get(normalized)
    if alias:
        return alias
    slug = re.sub(r"[^A-Z0-9]+", "_", normalized.upper()).strip("_")
    return f"RES_{slug}"


def _resource_cost(
    value: str | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    costs, kind, _options = _resource_cost_with_options(value)
    return costs, kind


def _resource_cost_with_options(
    value: str | None,
) -> tuple[list[dict[str, Any]] | None, str | None, list[dict[str, Any]]]:
    """Type one Cost line; a choice ("2 CP or 2 Stamina") also returns its options."""

    if not isinstance(value, str) or not value.strip():
        return None, None, []
    normalized = value.strip().casefold().rstrip(".")
    if normalized in _NONE_COST_VALUES:
        return [], "explicit_none", []
    if _ALTERNATIVE_COST_RE.search(normalized):
        return _resource_cost_choice(value)
    costs, kind = _resource_cost_single(value)
    return costs, kind, []


def _expand_choice_option(text: str) -> list[str]:
    """Expand ``1 CP/Stamina`` inside one option into its concrete variants."""

    parts = [part.strip() for part in re.split(r"\s+and\s+", text, flags=re.IGNORECASE)]
    variants: list[list[str]] = [[]]
    for part in parts:
        slash = _CHOICE_SLASH_RE.fullmatch(part)
        choices = (
            [f"{slash.group('amount')} {slash.group('left').strip()}", f"{slash.group('amount')} {slash.group('right').strip()}"]
            if slash is not None
            else [part]
        )
        variants = [existing + [choice] for existing in variants for choice in choices]
    return [" and ".join(variant) for variant in variants]


def _resource_cost_choice(
    value: str,
) -> tuple[list[dict[str, Any]] | None, str | None, list[dict[str, Any]]]:
    """Project a source Cost line that offers a choice of payments.

    Every option is typed with the single-cost grammar.  The default payment
    is the first option payable from the generic pool (``RES_CP``), then the
    first option payable from any Path pool, then the first option listed; the
    other options travel with the action as ``resource_cost_options`` so the
    table can honour the source's choice.  A variable amount ("1 or more"),
    an unknown resource, or an unparseable option keeps the row display-only.
    """

    text = value.strip().rstrip(".").strip()
    if _VARIABLE_AMOUNT_RE.search(text):
        return None, "explicit_resource_cost_variable", []
    text = re.sub(r"^either\s+", "", text, flags=re.IGNORECASE)
    raw_options = [part.strip() for part in _CHOICE_SEPARATOR_RE.split(text) if part and part.strip()]
    if len(raw_options) < 2:
        return None, "explicit_resource_cost_alternative_unparsed", []
    options: list[dict[str, Any]] = []
    previous_amount: int | None = None
    for raw in raw_options:
        condition: str | None = None
        base = raw.rstrip(".").strip()
        condition_match = _CHOICE_CONDITION_RE.fullmatch(base)
        if condition_match is not None:
            base = condition_match.group("base").strip()
            condition = condition_match.group("condition").strip()
        base = _CHOICE_VERB_RE.sub("", base).strip()
        if _CHOICE_ELIDED_RE.fullmatch(base) and not base.casefold().startswith("expend "):
            # "1 CP or Stamina": the second option inherits the amount.
            if previous_amount is None:
                return None, "explicit_resource_cost_alternative_unparsed", []
            base = f"{previous_amount} {base}"
        for variant in _expand_choice_option(base):
            costs, kind = _resource_cost_single(variant)
            if kind != "explicit_resource_cost_complete" or not costs:
                return None, "explicit_resource_cost_alternative_unparsed", []
            if any(row["resource_id"] not in _CHOICE_KNOWN_RESOURCES for row in costs):
                return None, "explicit_resource_cost_alternative_unparsed", []
            label = variant if variant != base else raw.rstrip(".").strip()
            options.append({
                "label": label,
                "condition": condition,
                "resource_costs": costs,
                "resource_requirements": [_resource_requirement(row) for row in costs],
                "default": False,
            })
        if len(options) > _CHOICE_MAX_OPTIONS:
            return None, "explicit_resource_cost_alternative_unparsed", []
        previous_amount = costs[0]["amount"] if len(costs) == 1 else None

    def rank(option: Mapping[str, Any]) -> int:
        ids = {row["resource_id"] for row in option["resource_costs"]}
        if ids == {"RES_CP"}:
            return 0
        if ids <= _CHOICE_POOL_RESOURCES:
            return 1
        return 2

    default_index = min(range(len(options)), key=lambda index: (rank(options[index]), index))
    options[default_index]["default"] = True
    alternatives = "; ".join(option["label"] for index, option in enumerate(options) if index != default_index)
    default_costs = deepcopy(options[default_index]["resource_costs"])
    for row in default_costs:
        row["condition"] = f"Default payment for this action; the source allows instead: {alternatives}."
    return default_costs, "explicit_resource_cost_choice_complete", options


def _resource_cost_single(
    value: str | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    normalized = _SPEND_VERB_RE.sub("", value.strip().casefold().rstrip(".")).strip()
    if normalized in _NONE_COST_VALUES:
        return [], "explicit_none"
    expend_match = _EXPEND_RESOURCE_RE.fullmatch(normalized)
    if expend_match is not None:
        resource = " ".join(expend_match.group("resource").split())
        resource_id = _RESOURCE_ID_ALIASES.get(resource)
        if resource_id is None:
            # An expenditure is typed only when it names one of the existing
            # authenticated resource aliases.  Do not manufacture a RES_*
            # identity for an unfamiliar source term.
            return None, "explicit_unknown_resource"
        return [_resource_transaction(resource_id, 1)], "explicit_resource_cost_complete"
    clauses = [part.strip() for part in re.split(r"\s+and\s+", normalized, flags=re.IGNORECASE)]
    if len(clauses) > 2:
        return None, "explicit_resource_cost_ambiguous"
    parsed_clauses: list[tuple[int, str]] = []
    if clauses:
        for clause in clauses:
            expend_clause = _EXPEND_RESOURCE_RE.fullmatch(clause.rstrip("."))
            if expend_clause is not None:
                # "expend Martial Focus and 1 CP": an expenditure inside a
                # compound is typed only through the authenticated aliases.
                resource = " ".join(expend_clause.group("resource").split())
                if _RESOURCE_ID_ALIASES.get(resource) is None:
                    parsed_clauses = []
                    break
                parsed_clauses.append((1, resource))
                continue
            clause_match = _RESOURCE_CLAUSE_RE.fullmatch(clause.rstrip("."))
            if clause_match is None:
                parsed_clauses = []
                break
            amount_text = clause_match.group("amount").casefold()
            amount = int(amount_text) if amount_text.isdigit() else _NUMBER_WORDS.get(amount_text, 1)
            if amount <= 0:
                # "0 CP" states an explicit zero cost, the same as "None".
                if len(clauses) == 1:
                    return [], "explicit_none"
                parsed_clauses = []
                break
            resource = clause_match.group("resource").strip()
            if not resource:
                parsed_clauses = []
                break
            parsed_clauses.append((amount, resource))
    if parsed_clauses and len({
        _canonical_resource_id(resource)
        for _, resource in parsed_clauses
    }) == len(parsed_clauses):
        costs = [
            _resource_transaction(_canonical_resource_id(resource), amount)
            for amount, resource in parsed_clauses
        ]
        return costs, "explicit_resource_cost_complete"
    # A conjunction is a claimed compound grammar.  Do not fall back to the
    # legacy preview regex, which would silently turn the entire expression
    # into a bogus resource name.
    if len(clauses) > 1:
        return None, "explicit_resource_cost_ambiguous"
    matches = list(
        re.finditer(
            r"\b(?P<amount>[0-9]+)\s+(?P<resource>[A-Za-z][A-Za-z0-9_.:-]*(?:\s+[A-Za-z][A-Za-z0-9_.:-]*){0,2})",
            value,
        )
    )
    if not matches:
        return None, "explicit_unparsed"
    # The source proves the resource name and amount, but it does not prove a
    # condition.  Keep the archive field shape in the diagnostic preview and
    # leave the candidate non-executable until a future explicitly labelled
    # condition can be supplied.
    costs = [
        {
            "resource_id": _canonical_resource_id(match.group("resource")),
            "amount": int(match.group("amount")),
            "timing": None,
            "condition": None,
        }
        for match in matches
    ]
    return costs, "explicit_resource_cost_incomplete"


def _resource_projection_from_description(
    description: Any,
    *,
    record_id: Any = None,
    display_name: Any = None,
    expected_action_type: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Derive executable resource transactions from sealed source syntax.

    ``Ingredient`` and ``Refinement`` Cost lines are recipe metadata, not a
    combat declaration cost.  A prepared item is executable only when the
    source contains exactly one ``one prepared <name>`` clause and the sealed
    candidate identity and name agree with it.
    """

    shape_error = _validate_prepared_recipe_shape(
        description,
        expected_action_type=expected_action_type,
    )
    if shape_error is not None:
        return None, shape_error
    action_values, contextual_costs = _source_cost_values(description)
    prepared_clause, prepared_error = _prepared_item_clause(
        description,
        record_id=record_id,
        display_name=display_name,
    )
    if prepared_error is not None:
        return None, prepared_error
    if len(action_values) > 1:
        return None, "missing_or_ambiguous_standalone_cost"

    action_costs: list[dict[str, Any]] = []
    projection_kind: str | None = None
    action_cost_text: str | None = None
    cost_options: list[dict[str, Any]] = []
    if action_values:
        action_cost_text = action_values[0]
        action_costs, projection_kind, cost_options = _resource_cost_with_options(action_cost_text)
        if projection_kind not in {
            "explicit_none",
            "explicit_resource_cost_complete",
            "explicit_resource_cost_choice_complete",
        } or action_costs is None:
            return None, projection_kind or "unparseable_standalone_cost"
    elif prepared_clause is None:
        return None, "missing_or_ambiguous_standalone_cost"

    costs = list(action_costs)
    if prepared_clause is not None:
        # ``_prepared_item_clause`` already compared this phrase to the
        # candidate name.  The deterministic resource ID keeps the prepared
        # state distinct from an unprepared item with the same display name.
        prepared_resource_id = _canonical_resource_id(f"prepared {display_name}")
        costs.append(_resource_transaction(prepared_resource_id, 1))
        projection_kind = "explicit_prepared_item_complete"
        prepared_cost_text = prepared_clause[len("Throw or launch "):].rstrip(".").strip()
        action_cost_text = prepared_cost_text if action_cost_text is None else f"{action_cost_text}; {prepared_cost_text}"

    return {
        "resource_costs": costs,
        "resource_gains": [],
        "resource_requirements": [_resource_requirement(row) for row in costs],
        "resource_cost_options": cost_options,
        "non_action_costs": contextual_costs,
        "action_cost_text": action_cost_text,
        "projection_kind": projection_kind,
    }, None


def _stable_action_id(record_id: str) -> str:
    return f"action.{sha256_json({'record_id': record_id})[:24]}"


def _sorted_cards(cards: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = [deepcopy(dict(card)) for card in cards if isinstance(card, Mapping)]
    result.sort(
        key=lambda row: (
            row.get("acquisition_cl") if type(row.get("acquisition_cl")) is int else 0,
            str(row.get("record_id") or ""),
        )
    )
    return result


def _candidate(
    card: Mapping[str, Any],
    *,
    expected_project_id: str | None = None,
    authenticated_constructed_immortal_source: Any = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    record_id = card.get("record_id")
    description = card.get("full_description")
    fields = _parse_explicit_fields(description)
    if not any(key in fields for key in ("action_type", "canonical_action_type", "bucket", "factory_routing")):
        return None, None

    action_label = fields.get("action_type")
    canonical_action_label = fields.get("canonical_action_type")
    action_label_type = _canonical_action_type(action_label)
    canonical_action_label_type = _canonical_action_type(canonical_action_label)
    action_type_invalid = (
        (action_label is not None and action_label_type is None)
        or (canonical_action_label is not None and canonical_action_label_type is None)
    )
    action_type_conflict = (
        action_label_type is not None
        and canonical_action_label_type is not None
        and action_label_type != canonical_action_label_type
    )
    action_type = None if action_type_invalid or action_type_conflict else (action_label_type or canonical_action_label_type)
    expected_bucket = action_type
    explicit_bucket = _canonical_bucket(fields.get("bucket"))
    bucket = explicit_bucket or expected_bucket
    missing: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    semantic_sources: dict[str, str] = {}
    source_error = card.get("_source_authority_error")
    authenticated_binding: dict[str, Any] | None = None

    if not isinstance(record_id, str) or not record_id.strip():
        missing.append("record_id")
        record_id = ""
    else:
        record_id = record_id.strip()
    if record_id.startswith(_CONSTRUCTED_IMMORTAL_RECORD_PREFIX):
        authenticated_binding = _authenticated_constructed_immortal_binding(
            card,
            authenticated_constructed_immortal_source,
            expected_project_id=expected_project_id,
        )
        if authenticated_binding is None:
            source_error = {
                "code": "COMMAND4_IMMORTAL_SOURCE_AUTHORITY_MISSING",
                "message": "The Immortal Art source requires server-rederived project and acquisition proof.",
            }
        else:
            source_error = None
    if isinstance(source_error, Mapping):
        missing.append("unambiguous_locked_mechanics_source")
        diagnostics.append(deepcopy(dict(source_error)))
    if not isinstance(card.get("display_name"), str) or not card.get("display_name", "").strip():
        missing.append("name")
    if action_type_invalid:
        missing.append("action_type")
        diagnostics.append({
            "code": "ACTION_TYPE_NOT_CANONICAL",
            "value": action_label if action_label_type is None else canonical_action_label,
        })
    elif action_type_conflict:
        missing.append("action_type")
        diagnostics.append({
            "code": "ACTION_TYPE_LABEL_CONFLICT",
            "action_type": action_label,
            "canonical_action_type": canonical_action_label,
        })
    elif not action_type:
        missing.append("action_type")
    else:
        semantic_sources["action_type"] = (
            "explicit:Action Type" if action_label_type is not None else "explicit:Canonical Action Type"
        )
    if not bucket:
        missing.append("bucket")
    elif explicit_bucket and expected_bucket and explicit_bucket != expected_bucket:
        missing.append("bucket")
        diagnostics.append({"code": "FACTORY_BUCKET_MISMATCH", "expected": expected_bucket, "actual": explicit_bucket})
    else:
        semantic_sources["bucket"] = "explicit:Factory Combat Bucket" if explicit_bucket else "system_default:Action Type"

    timing = fields.get("timing")
    if timing:
        semantic_sources["timing"] = "explicit:Timing"
    elif action_type:
        timing = action_type
        semantic_sources["timing"] = "system_default:Action Type"
    else:
        missing.append("timing")

    cost = fields.get("cost")
    source_projection, source_projection_error = _resource_projection_from_description(
        description,
        record_id=record_id,
        display_name=card.get("display_name"),
        expected_action_type=action_type,
    )
    source_action_cost_values, contextual_costs = _source_cost_values(description)
    if source_projection is not None:
        resource_costs = deepcopy(source_projection["resource_costs"])
        cost_kind = source_projection.get("projection_kind")
        derived_cost = source_projection.get("action_cost_text")
        if isinstance(derived_cost, str) and derived_cost.strip():
            cost = derived_cost
    elif source_projection_error and (
        source_projection_error.startswith("prepared_item")
        or contextual_costs
        or len(source_action_cost_values) > 1
    ):
        # Once a source explicitly presents recipe context or a malformed
        # prepared-item clause, never fall back to the legacy scalar parser.
        # That parser cannot know whether a Cost belongs to the action.
        resource_costs, cost_kind = None, source_projection_error
    else:
        resource_costs, cost_kind = _resource_cost(cost)
    if cost_kind == "explicit_prepared_item_complete":
        semantic_sources["cost"] = "source:prepared_item_consumption"
    elif cost:
        semantic_sources["cost"] = "explicit:Cost"
    else:
        missing.append("cost")
    parsed_resource_costs = deepcopy(resource_costs) if cost_kind in {
        "explicit_resource_cost_complete",
        "explicit_resource_cost_choice_complete",
        "explicit_resource_cost_incomplete",
        "explicit_prepared_item_complete",
    } else []
    if cost_kind == "explicit_none":
        resource_gains: list[dict[str, Any]] | None = []
        resource_requirements: list[dict[str, Any]] | None = []
        semantic_sources.update({
            "resource_costs": "explicit:Cost=None",
            "resource_gains": "explicit:Cost=None",
            "resource_requirements": "explicit:Cost=None",
        })
    elif cost_kind in {
        "explicit_resource_cost_complete",
        "explicit_resource_cost_choice_complete",
        "explicit_prepared_item_complete",
    }:
        resource_gains = []
        resource_requirements = [_resource_requirement(row) for row in resource_costs or []]
        semantic_sources.update({
            "resource_costs": (
                "source:prepared_item_consumption+system_transaction_policy"
                if cost_kind == "explicit_prepared_item_complete"
                else "explicit:Cost+system_transaction_policy"
            ),
            "resource_gains": "system_default:no_immediate_activation_gain_modeled",
            "resource_requirements": (
                "source:prepared_item_consumption+system_transaction_policy"
                if cost_kind == "explicit_prepared_item_complete"
                else "explicit:Cost+system_transaction_policy"
            ),
        })
    else:
        resource_gains = None
        resource_requirements = None
        # A numeric Cost line is useful evidence, but it cannot satisfy the
        # typed transaction contract until timing and condition are explicit.
        # Keep the evidence-bearing item shape in the candidate document even
        # though the missing condition leaves it non-executable.  The typed
        # compiler never receives this row because ``executable`` is false.
        resource_costs = deepcopy(parsed_resource_costs)
        missing.append("resource_costs")
        missing.extend(["resource_gains", "resource_requirements"])

    values: dict[str, Any] = {
        "action_id": _stable_action_id(record_id) if record_id else None,
        "record_id": record_id or None,
        "name": card.get("display_name"),
        "bucket": bucket,
        "action_type": bucket,
        "action_type_label": action_type,
        "timing": timing,
        "cost": cost,
        "range": fields.get("range"),
        "target": fields.get("target") or fields.get("area"),
        "area": fields.get("area"),
        "roll_save_check": fields.get("roll_save_check"),
        "effect": fields.get("effect"),
        "failure": fields.get("failure"),
        "duration": fields.get("duration"),
        "limit": fields.get("limit"),
        "counterplay": fields.get("counterplay"),
        "source_packet_ids": sorted({
            str(value) for value in (card.get("source_packet_ids") or [])
            if isinstance(value, str) and value
        }),
        "resource_costs": resource_costs,
        "resource_gains": resource_gains,
        "resource_requirements": resource_requirements,
        "parsed_resource_costs": parsed_resource_costs,
        "resource_cost_options": deepcopy(source_projection.get("resource_cost_options") or []) if source_projection is not None else [],
        "non_action_costs": deepcopy(
            source_projection.get("non_action_costs", contextual_costs)
            if source_projection is not None
            else contextual_costs
        ),
    }
    for field in ("range", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay"):
        if values[field]:
            semantic_sources[field] = f"explicit:{field}"
        else:
            missing.append(field)
    if not values["source_packet_ids"]:
        missing.append("source_packet_ids")
    if card.get("source") is None:
        missing.append("source")
    missing = list(dict.fromkeys(missing))

    values.update({
        "factory_routing": fields.get("factory_routing"),
        "full_description": deepcopy(description),
        "one_line_description": deepcopy(card.get("one_line_description")),
        "source": deepcopy(card.get("source")),
        "source_packet_ids": deepcopy(values["source_packet_ids"]),
        "record_hash": deepcopy(card.get("record_hash")),
        "acquisition": {
            "acquisition_cl": deepcopy(card.get("acquisition_cl")),
            "acquisition_route": deepcopy(card.get("acquisition_route")),
        },
        "semantic_sources": semantic_sources,
        "missing_fields": missing,
        "executable": not missing,
        "execution_authority": not missing,
        "display_only_not_execution_authority": bool(missing),
        "algorithm": ACTION_ALGORITHM_VERSION,
        "mechanics_source": deepcopy(card.get("mechanics_source")),
        **({"native_source_binding": deepcopy(card["native_source_binding"])} if "native_source_binding" in card else {}),
        **({key: deepcopy(card.get(key)) for key in ("native_operation_source_binding", "acquisition_parent_record_id", "acquisition_parent_record_hash")} if "native_operation_source_binding" in card else {}),
        **({"constructed_immortal_source_binding": authenticated_binding} if authenticated_binding is not None else {}),
        **({"constructed_forged_source_binding": deepcopy(card["constructed_forged_source_binding"])} if "constructed_forged_source_binding" in card else {}),
    })
    unresolved = None
    if missing:
        unresolved = {
            "record_id": record_id or None,
            "action_id": values.get("action_id"),
            "missing_fields": missing,
            "diagnostics": diagnostics,
            "status": "NON_EXECUTABLE_INCOMPLETE_EXPLICIT_ACTION",
        }
    return values, unresolved


_OWNER_KEYS = (
    "owning_canonical_sphere_id",
    "owning_sphere_id",
    "sphere_id",
)


def _resolved_sphere_owner(value: Mapping[str, Any] | None) -> str | None:
    """Return one unambiguous owner from the sealed row's recognized aliases."""

    if not isinstance(value, Mapping):
        return None
    owners = {
        str(value[key]).strip()
        for key in _OWNER_KEYS
        if isinstance(value.get(key), str) and value.get(key, "").strip()
    }
    return next(iter(owners)) if len(owners) == 1 else None


def _locked_record_id(value: Mapping[str, Any]) -> str | None:
    return next(
        (
            value.get(key)
            for key in ("canonical_talent_id", "canonical_record_id", "record_id", "choice_id")
            if isinstance(value.get(key), str) and value.get(key, "").strip()
        ),
        None,
    )


def _without_private_source_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): deepcopy(item)
        for key, item in value.items()
        if not str(key).startswith("_")
    }


def _locked_mechanics_index(projection_provenance: Mapping[str, Any] | None) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Index exact, owner-bound rich records from the sealed typed snapshot.

    The display card is intentionally not treated as a mechanics source.  Only
    rows retained under a typed lock (normally ``talent_dispositions``) may
    enrich it.  Every recognized owner alias is checked together so a stale or
    conflicting source row cannot silently authorize a different sphere.
    """

    if not isinstance(projection_provenance, Mapping):
        return {}, set()
    snapshot = projection_provenance.get("typed_choice_snapshot")
    if not isinstance(snapshot, Mapping):
        return {}, set()
    snapshot_sha = (
        projection_provenance.get("typed_choice_snapshot_sha256")
        or snapshot.get("snapshot_sha256")
    )
    found: dict[str, list[dict[str, Any]]] = {}

    def add_row(row: Any, lock: Mapping[str, Any] | None = None) -> None:
        if not isinstance(row, Mapping):
            return
        record_id = _locked_record_id(row)
        full = row.get("full_description")
        if not isinstance(record_id, str) or not isinstance(full, str) or not full.strip():
            return
        source = deepcopy(dict(row))
        source["_typed_lock_field"] = lock.get("field") if isinstance(lock, Mapping) else None
        source["_typed_lock_id"] = lock.get("lock_id") if isinstance(lock, Mapping) else None
        source["_typed_choice_snapshot_sha256"] = snapshot_sha
        source["_typed_record_commitment_sha256"] = next(
            (
                row.get(key)
                for key in ("record_commitment_sha256", "source_record_commitment_sha256", "record_hash")
                if isinstance(row.get(key), str) and row.get(key, "").strip()
            ),
            None,
        )
        found.setdefault(record_id, []).append(source)

    locks = snapshot.get("typed_locks")
    if isinstance(locks, list):
        for lock in locks:
            if not isinstance(lock, Mapping):
                continue
            value = lock.get("value")
            if not isinstance(value, Mapping):
                continue
            # ``talent_dispositions`` is the documented rich-mechanics source
            # in the sealed typed-lock contract.  Do not recursively inspect
            # compatibility/provenance payloads: a same-ID copy elsewhere is
            # not authenticated mechanics and must never promote a card.
            rows = value.get("talent_dispositions")
            if isinstance(rows, list):
                for row in rows:
                    add_row(row, lock)

    index: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for record_id, rows in found.items():
        # De-duplicate a row repeated at more than one sealed lock while still
        # treating different owner/content rows as an ambiguity.
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            raw = _without_private_source_metadata(row)
            unique.setdefault(canonical_json(raw), row)
        candidates = list(unique.values())
        if len(candidates) != 1 or _resolved_sphere_owner(candidates[0]) is None:
            ambiguous.add(record_id)
            continue
        index[record_id] = candidates[0]
    return index, ambiguous


def _enrich_cards(
    cards: list[dict[str, Any]],
    projection_provenance: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    index, ambiguous = _locked_mechanics_index(projection_provenance)
    snapshot_sha = (
        (projection_provenance or {}).get("typed_choice_snapshot_sha256")
        or ((projection_provenance or {}).get("typed_choice_snapshot") or {}).get("snapshot_sha256")
    ) if isinstance(projection_provenance, Mapping) else None
    issues: list[dict[str, Any]] = []
    enriched: list[dict[str, Any]] = []
    for original in cards:
        card = deepcopy(original)
        record_id = card.get("record_id")
        if isinstance(record_id, str) and record_id in ambiguous:
            source_error = {"code": "LOCKED_MECHANICS_SOURCE_AMBIGUOUS_OR_OWNER_INVALID"}
            card["_source_authority_error"] = source_error
            issues.append({
                "record_id": record_id,
                "missing_fields": ["unambiguous_locked_mechanics_source"],
                "diagnostics": [source_error],
                "status": "NON_EXECUTABLE_AMBIGUOUS_SOURCE",
            })
        locked = index.get(str(record_id))
        if locked is not None:
            locked_owner = _resolved_sphere_owner(locked)
            card_owner = _resolved_sphere_owner(card)
            if locked_owner is None or (card_owner is not None and card_owner != locked_owner):
                source_error = {
                    "code": "LOCKED_MECHANICS_OWNER_MISMATCH"
                    if locked_owner is not None and card_owner is not None
                    else "LOCKED_MECHANICS_OWNER_INVALID"
                }
                card["_source_authority_error"] = source_error
                issues.append({
                    "record_id": record_id,
                    "missing_fields": ["unambiguous_locked_mechanics_source"],
                    "diagnostics": [source_error],
                    "status": "NON_EXECUTABLE_AMBIGUOUS_SOURCE",
                })
            else:
                raw_locked = _without_private_source_metadata(locked)
                card["full_description"] = locked["full_description"].strip()
                if isinstance(locked.get("short_description"), str) and locked.get("short_description", "").strip():
                    card["one_line_description"] = locked["short_description"].strip()
                card["mechanics_source"] = {
                    "authority": "locked_typed_choice_snapshot",
                    "typed_choice_snapshot_sha256": snapshot_sha,
                    "typed_lock_field": locked.get("_typed_lock_field"),
                    "typed_lock_id": locked.get("_typed_lock_id"),
                    "owner_sphere_id": locked_owner,
                    "locked_record_sha256": sha256_json(raw_locked),
                    "record_commitment_sha256": locked.get("_typed_record_commitment_sha256"),
                    "source_reference": deepcopy(locked.get("source_reference")),
                }
        elif not (isinstance(record_id, str) and record_id in ambiguous):
            # A selected/display card is not itself mechanical authority.  It
            # may remain a useful candidate, but only an exact owner-bound row
            # from the sealed typed-choice lock can authorize execution.
            card["_source_authority_error"] = {
                "code": "LOCKED_MECHANICS_SOURCE_NOT_FOUND"
            }
        enriched.append(card)
    return enriched, issues


def produce_action_documents(
    selected_record_cards: Iterable[Mapping[str, Any]],
    *,
    project_id: str | None = None,
    project_revision: int | None = None,
    projection_provenance: Mapping[str, Any] | None = None,
    native_authority_root: Path | None = None,
    _authenticated_constructed_immortal_sources: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Project explicitly labelled selected cards into a bounded action archive."""

    materialized = _sorted_cards(selected_record_cards)
    materialized, source_issues = _enrich_cards(materialized, projection_provenance)
    if native_authority_root is not None:
        for card in materialized:
            record_id = card.get("record_id")
            binding = native_path_binding(native_authority_root, record_id) if isinstance(record_id, str) else None
            if binding is not None:
                # Retain the source-required blocker until Command4 independently
                # validates this binding. Do not promote display text to authority.
                card["native_source_binding"] = binding
        materialized = [
            operation
            for card in materialized
            for operation in expand_native_operation_cards(native_authority_root, card)
        ]
    candidates: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = list(source_issues)
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    authenticated_sources = (
        _authenticated_constructed_immortal_sources
        if isinstance(_authenticated_constructed_immortal_sources, Mapping)
        else {}
    )
    for card in materialized:
        record_id = card.get("record_id")
        if isinstance(record_id, str) and record_id in seen_ids:
            duplicate_ids.append(record_id)
        if isinstance(record_id, str):
            seen_ids.add(record_id)
        candidate, issue = _candidate(
            card,
            expected_project_id=project_id,
            authenticated_constructed_immortal_source=(
                authenticated_sources.get(record_id)
                if isinstance(record_id, str)
                else None
            ),
        )
        if candidate is None:
            continue
        candidates.append(candidate)
        if issue is not None:
            unresolved.append(issue)
    if duplicate_ids:
        unresolved.append({
            "record_id": None,
            "missing_fields": ["unique_record_id"],
            "diagnostics": [{"code": "ACTION_RECORD_DUPLICATE", "record_ids": sorted(set(duplicate_ids))}],
            "status": "NON_EXECUTABLE_DUPLICATE_RECORD",
        })
        for candidate in candidates:
            if candidate.get("record_id") in duplicate_ids:
                candidate["missing_fields"] = list(dict.fromkeys([*candidate.get("missing_fields", []), "unique_record_id"]))
                candidate["executable"] = False
                candidate["execution_authority"] = False
                candidate["display_only_not_execution_authority"] = True

    executable = [deepcopy(row) for row in candidates if row.get("executable") is True]
    eligible_count = len(candidates)
    action_authority = bool(eligible_count and len(unresolved) == 0 and len(executable) == eligible_count)
    if not eligible_count:
        status = "NO_EXPLICIT_ACTION_RECORDS"
    elif action_authority:
        status = "ACTION_SURFACE_READY"
    else:
        status = "ACTION_SURFACE_PARTIAL"
    identity = {}
    if isinstance(project_id, str):
        identity["project_id"] = project_id
    if type(project_revision) is int:
        identity["project_revision"] = project_revision
    provenance = {
        "algorithm": ACTION_ALGORITHM_VERSION,
        "selected_record_count": len(materialized),
        "eligible_record_count": eligible_count,
        "project_identity": identity,
        "workspace_authority": "C2B2_INPUT_ONLY",
    }
    candidate_document = {
        "schema_version": ACTION_CANDIDATES_SCHEMA,
        "status": status,
        "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
        "mechanical_authority": True,
        "execution_authority": action_authority,
        "global_combat_readiness": False,
        **identity,
        "candidates": deepcopy(candidates),
        "unresolved": deepcopy(unresolved),
        "provenance": provenance,
    }
    surface = {
        "schema_version": ACTION_SURFACE_SCHEMA,
        "status": status,
        "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
        "mechanical_authority": True,
        "execution_authority": action_authority,
        "global_combat_readiness": False,
        "workspace_authority": "C2B2_INPUT_ONLY",
        **identity,
        "actions": deepcopy(executable),
        "unresolved": deepcopy(unresolved),
        "provenance": provenance,
    }
    audit = {
        "schema_version": ACTION_AUDIT_SCHEMA,
        "status": status,
        "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
        "mechanical_authority": True,
        "execution_authority": action_authority,
        "global_combat_readiness": False,
        "executable_actions_created": len(executable),
        "display_records_promoted": len(executable),
        "eligible_explicit_action_records": eligible_count,
        "unresolved_records": deepcopy(unresolved),
        "legacy_pinned_command4_validation": "NOT_RUN",
        "blocking_for_c2b2": False,
        **identity,
    }
    coverage = {
        "schema_version": TALENT_COVERAGE_SCHEMA,
        "status": status,
        "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
        "mechanical_authority": True,
        "execution_authority": action_authority,
        "global_combat_readiness": False,
        "records": [
            {
                "record_id": row.get("record_id"),
                "action_id": row.get("action_id"),
                "eligible": True,
                "executable": row.get("executable") is True,
                "missing_fields": deepcopy(row.get("missing_fields") or []),
            }
            for row in candidates
        ],
        "combat_execution_complete": action_authority,
        "legacy_pinned_command4_validation": "NOT_RUN",
        **identity,
    }
    return {
        "Action_Authoring_Candidates.json": candidate_document,
        "Complete_Action_Surface.json": surface,
        "Executable_Action_Audit.json": audit,
        "Talent_Execution_Coverage_Audit.json": coverage,
    }


class Command4ActionProducer:
    """Small stateless adapter for the post-workspace action projection."""

    @staticmethod
    def produce(
        selected_record_cards: Iterable[Mapping[str, Any]],
        *,
        project_id: str | None = None,
        project_revision: int | None = None,
        projection_provenance: Mapping[str, Any] | None = None,
        native_authority_root: Path | None = None,
        _authenticated_constructed_immortal_sources: Mapping[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        return produce_action_documents(
            selected_record_cards,
            project_id=project_id,
            project_revision=project_revision,
            projection_provenance=projection_provenance,
            native_authority_root=native_authority_root,
            _authenticated_constructed_immortal_sources=_authenticated_constructed_immortal_sources,
        )


__all__ = [
    "ACTION_AUDIT_SCHEMA",
    "ACTION_CANDIDATES_SCHEMA",
    "ACTION_SURFACE_SCHEMA",
    "ACTION_ALGORITHM_VERSION",
    "Command4ActionProducer",
    "produce_action_documents",
]
