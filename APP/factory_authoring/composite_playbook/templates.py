"""Playbook templates: the data-driven shapes the proposer fills.

A template is an ordered list of slots; each slot names an economy bucket, a
round offset and a preference.  Templates live in
``rules/playbook_templates.v1.json`` so a new playbook shape is a data edit,
not a code change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .hooks import SHIFT_KINDS
from .rules import RULES_DIR

DEFAULT_TEMPLATES_PATH = RULES_DIR / "playbook_templates.v1.json"
TEMPLATES_SCHEMA_VERSION = "TianxiaFoundry.CompositePlaybookTemplates.v1"
PREFERENCES = ("highest_cost", "zero_cost", "any")
_SLOT_FLAGS = {"optional": False, "distinct": True, "own_only": False, "base_only": False, "forged_only": False}


@dataclass(frozen=True)
class Slot:
    round_offset: int
    economy: str
    prefer: str = "any"
    optional: bool = False
    distinct: bool = True
    own_only: bool = False
    base_only: bool = False
    forged_only: bool = False
    action_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, mapping: Any, where: str) -> "Slot":
        if not isinstance(mapping, Mapping):
            raise ValueError(f"{where}: slot must be an object")
        offset = mapping.get("round_offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError(f"{where}: round_offset must be a non-negative integer")
        economy = mapping.get("economy")
        if not isinstance(economy, str) or not economy:
            raise ValueError(f"{where}: economy must be a non-empty string")
        prefer = mapping.get("prefer", "any")
        if prefer not in PREFERENCES:
            raise ValueError(f"{where}: prefer must be one of {PREFERENCES}, got {prefer!r}")
        ids = mapping.get("action_ids") or ()
        if isinstance(ids, str) or not all(isinstance(item, str) and item for item in ids):
            raise ValueError(f"{where}: action_ids must be a list of non-empty strings")
        flags: dict[str, bool] = {}
        for name, default in _SLOT_FLAGS.items():
            value = mapping.get(name, default)
            if not isinstance(value, bool):
                raise ValueError(f"{where}: {name} must be a boolean")
            flags[name] = value
        if flags["own_only"] and flags["base_only"]:
            raise ValueError(f"{where}: own_only and base_only are mutually exclusive")
        if flags["forged_only"] and flags["base_only"]:
            raise ValueError(f"{where}: forged_only and base_only are mutually exclusive")
        return cls(round_offset=offset, economy=economy, prefer=prefer, action_ids=tuple(ids), **flags)


@dataclass(frozen=True)
class Template:
    template_id: str
    category: str
    execution_role: str
    slots: tuple[Slot, ...]
    tendency: str | None = None
    shift_to: str | None = None
    shift_when: str = "resource_low"

    @classmethod
    def from_mapping(cls, mapping: Any, index: int) -> "Template":
        where = f"templates[{index}]"
        if not isinstance(mapping, Mapping):
            raise ValueError(f"{where}: template must be an object")
        for key in ("template_id", "category", "execution_role"):
            if not isinstance(mapping.get(key), str) or not mapping[key]:
                raise ValueError(f"{where}: {key} must be a non-empty string")
        slots = mapping.get("slots")
        if not isinstance(slots, list) or len(slots) < 2:
            raise ValueError(f"{where}: slots must be a list of at least two slots")
        change = mapping.get("i_ching") or {}
        if not isinstance(change, Mapping):
            raise ValueError(f"{where}: i_ching must be an object")
        tendency, shift_to = change.get("tendency"), change.get("shift_to")
        shift_when = change.get("shift_when", "resource_low")
        if tendency is not None and (not isinstance(tendency, str) or not tendency.strip()):
            raise ValueError(f"{where}: i_ching.tendency must be a non-empty string")
        if shift_to is not None and (not isinstance(shift_to, str) or not shift_to):
            raise ValueError(f"{where}: i_ching.shift_to must be a template_id")
        if shift_when not in SHIFT_KINDS:
            raise ValueError(f"{where}: i_ching.shift_when must be one of {SHIFT_KINDS}, got {shift_when!r}")
        return cls(
            template_id=mapping["template_id"],
            category=mapping["category"],
            execution_role=mapping["execution_role"],
            slots=tuple(Slot.from_mapping(slot, f"{where}.slots[{i}]") for i, slot in enumerate(slots)),
            tendency=tendency.strip() if isinstance(tendency, str) else None,
            shift_to=shift_to,
            shift_when=shift_when,
        )


@dataclass(frozen=True)
class TemplateSet:
    schema_version: str
    budget_fraction: float
    fallback_economy: str
    hooks: Mapping[str, str]
    templates: tuple[Template, ...]
    min_own_steps: int = 0

    @classmethod
    def from_mapping(cls, mapping: Any) -> "TemplateSet":
        if not isinstance(mapping, Mapping) or mapping.get("schema_version") != TEMPLATES_SCHEMA_VERSION:
            raise ValueError(f"templates document must declare schema_version {TEMPLATES_SCHEMA_VERSION!r}")
        fraction = mapping.get("budget_fraction", 1.0)
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 < fraction <= 1:
            raise ValueError("budget_fraction must be a number in (0, 1]")
        fallback_economy = mapping.get("fallback_economy", "action")
        if not isinstance(fallback_economy, str) or not fallback_economy:
            raise ValueError("fallback_economy must be a non-empty string")
        hooks = mapping.get("hooks") or {}
        if not isinstance(hooks, Mapping) or not all(isinstance(v, str) and v for v in hooks.values()):
            raise ValueError("hooks must map names to non-empty strings")
        rows = mapping.get("templates")
        if not isinstance(rows, list) or not rows:
            raise ValueError("templates must be a non-empty list")
        min_own = mapping.get("min_own_steps", 0)
        if isinstance(min_own, bool) or not isinstance(min_own, int) or min_own < 0:
            raise ValueError("min_own_steps must be a non-negative integer")
        templates = tuple(Template.from_mapping(row, i) for i, row in enumerate(rows))
        ids = [template.template_id for template in templates]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate template_id: {duplicates}")
        for template in templates:
            if template.shift_to is not None and template.shift_to not in ids:
                raise ValueError(f"template {template.template_id}: i_ching.shift_to {template.shift_to!r} is not a template_id")
        return cls(
            schema_version=mapping["schema_version"],
            budget_fraction=float(fraction),
            fallback_economy=fallback_economy,
            hooks=dict(hooks),
            templates=templates,
            min_own_steps=min_own,
        )

    def with_templates(self, templates: tuple[Template, ...] | list[Template]) -> "TemplateSet":
        """Same settings, different template list (tests and callers narrowing the set)."""
        return TemplateSet(self.schema_version, self.budget_fraction, self.fallback_economy, dict(self.hooks),
                           tuple(templates), min_own_steps=self.min_own_steps)


def load_templates(path: Path | None = None) -> TemplateSet:
    """Load and validate a templates JSON document; defaults to ``DEFAULT_TEMPLATES_PATH``."""
    source = Path(path) if path is not None else DEFAULT_TEMPLATES_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"templates file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"templates file {source} is not valid JSON: {exc}") from exc
    return TemplateSet.from_mapping(raw)
