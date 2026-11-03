"""Factory-owned bounded predicate menus for pre-intent AI selection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core import sha256_json

from .choice_semantics import validate_vocabulary_authority
from .contracts import fail, require_digest, require_exact_keys, require_list, require_string


MENU_SCHEMA = "TianxiaFoundry.CreativePredicateMenu.v1"
SELECTION_SCHEMA = "TianxiaFoundry.CreativePredicateSelection.v1"
PREDICATE_FIELDS = ("must_include", "must_exclude", "soft_prefer", "soft_avoid")
KIND_TO_VOCABULARY = {
    "role_tag": "role_tags",
    "theme_tag": "theme_tags",
    "capability_family": "capability_families",
    "tradeoff_code": "tradeoff_codes",
}


def _option_id(authority_sha256: str, kind: str, value: str) -> str:
    return "dcc.pred." + sha256_json({
        "domain": "dcc.creative-predicate-option.v1",
        "vocabulary_authority_sha256": authority_sha256,
        "kind": kind,
        "value": value,
    })[:24]


def _predicate_key(value: Mapping[str, Any]) -> tuple[str, str]:
    require_exact_keys(value, {"kind", "value"}, path="creative predicate")
    return (
        require_string(value["kind"], path="creative predicate.kind"),
        require_string(value["value"], path="creative predicate.value"),
    )


@dataclass(frozen=True)
class CreativePredicateMenu:
    public_menu: dict[str, Any]
    option_to_predicate: dict[str, dict[str, str]]
    hard_authorized_option_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_menu", deepcopy(self.public_menu))
        object.__setattr__(self, "option_to_predicate", deepcopy(self.option_to_predicate))
        object.__setattr__(self, "hard_authorized_option_ids", tuple(sorted(self.hard_authorized_option_ids)))
        validate_creative_predicate_menu(self)

    @property
    def menu_sha256(self) -> str:
        return self.public_menu["menu_sha256"]


def build_creative_predicate_menu(
    vocabulary_authority: Mapping[str, Any],
    *,
    hard_authorized_predicates: Sequence[Mapping[str, Any]] = (),
    maximum_options: int = 96,
) -> CreativePredicateMenu:
    """Build the bounded menu presented to the selected AI before intent."""

    authority = validate_vocabulary_authority(vocabulary_authority)
    if not isinstance(maximum_options, int) or isinstance(maximum_options, bool) or maximum_options < 1:
        fail("DCC_SCHEMA_VALUE", "maximum_options must be a positive integer.")
    predicates: list[tuple[str, str]] = []
    for kind, vocabulary_key in KIND_TO_VOCABULARY.items():
        predicates.extend((kind, value) for value in authority["vocabularies"][vocabulary_key])
    predicates.extend(("complexity_band", value) for value in ("simple", "moderate", "complex"))
    predicates = sorted(set(predicates))
    if len(predicates) > maximum_options:
        fail("DCC_CREATIVE_MENU_BOUND", "The Factory creative predicate menu exceeds its configured bound.")
    private_mapping = {
        _option_id(authority["authority_sha256"], kind, value): {"kind": kind, "value": value}
        for kind, value in predicates
    }
    authorized_keys = {_predicate_key(row) for row in hard_authorized_predicates}
    unknown = authorized_keys - set(predicates)
    if unknown:
        fail("DCC_CREATIVE_MENU_AUTHORITY", "A hard-authorized predicate is absent from the active Factory vocabulary.")
    authorized_ids = tuple(sorted(
        option_id
        for option_id, predicate in private_mapping.items()
        if (predicate["kind"], predicate["value"]) in authorized_keys
    ))
    unsigned = {
        "schema": MENU_SCHEMA,
        "vocabulary_authority_sha256": authority["authority_sha256"],
        "maximum_selections_per_field": 16,
        "options": [
            {
                "option_id": option_id,
                "kind": private_mapping[option_id]["kind"],
                "label": private_mapping[option_id]["value"].replace("_", " "),
                "hard_authorized": option_id in authorized_ids,
            }
            for option_id in sorted(private_mapping)
        ],
    }
    public_menu = {**unsigned, "menu_sha256": sha256_json(unsigned)}
    return CreativePredicateMenu(public_menu, private_mapping, authorized_ids)


def validate_creative_predicate_menu(menu: CreativePredicateMenu) -> None:
    public = menu.public_menu
    require_exact_keys(public, {"schema", "vocabulary_authority_sha256", "maximum_selections_per_field", "options", "menu_sha256"}, path="creative predicate menu")
    if public["schema"] != MENU_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported creative predicate menu schema.")
    require_digest(public["vocabulary_authority_sha256"], path="creative predicate menu.vocabulary_authority_sha256")
    require_digest(public["menu_sha256"], path="creative predicate menu.menu_sha256")
    if public["menu_sha256"] != sha256_json({key: value for key, value in public.items() if key != "menu_sha256"}):
        fail("DCC_CREATIVE_MENU_HASH_INVALID", "Creative predicate menu self-hash mismatch.")
    rows = require_list(public["options"], path="creative predicate menu.options", max_length=96)
    public_ids: set[str] = set()
    for index, row in enumerate(rows):
        require_exact_keys(row, {"option_id", "kind", "label", "hard_authorized"}, path=f"creative predicate menu.options[{index}]")
        option_id = require_string(row["option_id"], path=f"creative predicate menu.options[{index}].option_id")
        if option_id in public_ids:
            fail("DCC_SCHEMA_DUPLICATE", "Creative predicate option IDs must be unique.")
        public_ids.add(option_id)
    if public_ids != set(menu.option_to_predicate):
        fail("DCC_CREATIVE_MENU_MAPPING", "Every public predicate option must have one private Factory mapping.")
    if not set(menu.hard_authorized_option_ids) <= public_ids:
        fail("DCC_CREATIVE_MENU_AUTHORITY", "Hard-authorized option IDs must be in the active menu.")


def resolve_creative_predicate_selection(menu: CreativePredicateMenu, response: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve an option-ID-only AI response to controlled Factory predicates."""

    require_exact_keys(response, {"schema", *PREDICATE_FIELDS}, path="creative predicate selection")
    if response["schema"] != SELECTION_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported creative predicate selection schema.")
    resolved: dict[str, list[dict[str, str]]] = {}
    selected_ids: dict[str, tuple[str, ...]] = {}
    for field in PREDICATE_FIELDS:
        rows = require_list(response[field], path=f"creative predicate selection.{field}", max_length=16)
        option_ids = tuple(require_string(row, path=f"creative predicate selection.{field}[]") for row in rows)
        if len(option_ids) != len(set(option_ids)):
            fail("DCC_SCHEMA_DUPLICATE", f"creative predicate selection.{field} must be duplicate-free.")
        unknown = set(option_ids) - set(menu.option_to_predicate)
        if unknown:
            fail("DCC_CREATIVE_PREDICATE_UNKNOWN", "The selected AI returned a predicate option outside the Factory menu.")
        if field in {"must_include", "must_exclude"} and not set(option_ids) <= set(menu.hard_authorized_option_ids):
            fail("DCC_CREATIVE_HARD_AUTHORITY", "The selected AI cannot originate an unauthorized hard predicate.")
        selected_ids[field] = option_ids
        resolved[field] = [deepcopy(menu.option_to_predicate[option_id]) for option_id in option_ids]
    include_keys = {_predicate_key(row) for row in resolved["must_include"]}
    exclude_keys = {_predicate_key(row) for row in resolved["must_exclude"]}
    if include_keys & exclude_keys:
        fail("DCC_CREATIVE_PREDICATE_CONFLICT", "A predicate cannot be both required and excluded.")
    receipt_unsigned = {
        "schema": "TianxiaFoundry.CreativePredicateSelectionReceipt.v1",
        "menu_sha256": menu.menu_sha256,
        "selected_option_ids": {field: list(selected_ids[field]) for field in PREDICATE_FIELDS},
        "controlled_preferences_sha256": sha256_json(resolved),
    }
    return {
        "controlled_preferences": resolved,
        "receipt": {**receipt_unsigned, "selection_receipt_sha256": sha256_json(receipt_unsigned)},
    }


def validate_intent_predicate_selection(intent: Mapping[str, Any], resolved_selection: Mapping[str, Any]) -> None:
    controlled = intent.get("controlled_preferences")
    expected = resolved_selection.get("controlled_preferences")
    if controlled != expected:
        fail("DCC_INTENT_PREDICATE_BINDING", "CreativeIntent controlled preferences must exactly match the Factory-resolved pre-intent selection.")
