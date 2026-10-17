"""Data-driven rule set for the standalone Composite Playbook validator.

All tunables live in ``rules/*.json``; this module only loads, normalises and
sanity-checks them. Editing a rule's data (buckets, capacities, limits) is a JSON
edit; adding a *new* rule code is a validator change (see ``README.md``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = PACKAGE_DIR / "schemas"
RULES_DIR = PACKAGE_DIR / "rules"
DEFAULT_RULES_PATH = RULES_DIR / "combat_economy.v1.json"

RULES_SCHEMA_VERSION = "TianxiaFoundry.CompositePlaybookRules.v1"

_TEXT_FIELDS = ("source_citations", "executable_buckets",
                "non_executable_kinds", "enabled_rules", "notes")


def _text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"rules field {field_name!r} must be a list of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"rules field {field_name!r} must contain non-empty strings, got {item!r}")
        out.append(item)
    return tuple(out)


def _int_field(value: Any, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"rules field {field_name!r} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"rules field {field_name!r} must be >= {minimum}, got {value}")
    return value


def _capacity_map(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("rules field 'round_economy_capacity' must be an object")
    out: dict[str, int] = {}
    for bucket, capacity in value.items():
        if not isinstance(bucket, str) or not bucket:
            raise ValueError(f"round_economy_capacity keys must be non-empty strings, got {bucket!r}")
        out[bucket] = _int_field(capacity, f"round_economy_capacity[{bucket!r}]")
    return out


def _sequence_length(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("rules field 'sequence_length' must be an object with 'min' and 'max'")
    missing = [key for key in ("min", "max") if key not in value]
    if missing:
        raise ValueError(f"rules field 'sequence_length' is missing {missing}")
    low = _int_field(value["min"], "sequence_length.min")
    high = _int_field(value["max"], "sequence_length.max")
    if low < 2:
        raise ValueError(f"sequence_length.min must be >= 2, got {low}")
    if high < low:
        raise ValueError(f"sequence_length.max ({high}) must be >= sequence_length.min ({low})")
    return {"min": low, "max": high}


@dataclass(frozen=True)
class RuleSet:
    """Normalised, validated view of one rules JSON document."""

    schema_version: str
    source_citations: tuple[str, ...]
    executable_buckets: tuple[str, ...]
    non_executable_kinds: tuple[str, ...]
    round_economy_capacity: dict[str, int]
    max_round_offset: int
    sequence_length: dict[str, int]
    fallback_must_be_zero_cost: bool
    enabled_rules: tuple[str, ...]
    notes: tuple[str, ...]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "RuleSet":
        """Build a validated RuleSet from a raw rules mapping (tests pass overrides here)."""
        if not isinstance(mapping, Mapping):
            raise ValueError(f"rules document must be an object, got {type(mapping).__name__}")
        missing = [name for name in (f.name for f in fields(cls)) if name not in mapping]
        if missing:
            raise ValueError(f"rules document is missing required fields: {missing}")

        text = {name: _text_tuple(mapping[name], name) for name in _TEXT_FIELDS}

        version = mapping["schema_version"]
        if not isinstance(version, str) or version != RULES_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported rules schema_version {version!r}; "
                f"expected {RULES_SCHEMA_VERSION!r}")

        if not text["executable_buckets"]:
            raise ValueError("rules field 'executable_buckets' must not be empty")
        if not text["enabled_rules"]:
            raise ValueError("rules field 'enabled_rules' must be a non-empty list of rule codes")
        if len(set(text["enabled_rules"])) != len(text["enabled_rules"]):
            raise ValueError("rules field 'enabled_rules' must not contain duplicates")

        # A bucket with no round_economy_capacity entry is unlimited per round
        # (the bootstrap states no per-round count for e.g. ``passive``).
        capacity = _capacity_map(mapping["round_economy_capacity"])

        fallback = mapping["fallback_must_be_zero_cost"]
        if not isinstance(fallback, bool):
            raise ValueError(
                f"rules field 'fallback_must_be_zero_cost' must be a boolean, got {fallback!r}")

        return cls(
            schema_version=version,
            source_citations=text["source_citations"],
            executable_buckets=text["executable_buckets"],
            non_executable_kinds=text["non_executable_kinds"],
            round_economy_capacity=capacity,
            max_round_offset=_int_field(mapping["max_round_offset"], "max_round_offset"),
            sequence_length=_sequence_length(mapping["sequence_length"]),
            fallback_must_be_zero_cost=fallback,
            enabled_rules=text["enabled_rules"],
            notes=text["notes"],
        )

    def to_mapping(self) -> dict[str, Any]:
        """Round-trippable plain-data view (lists, not tuples) of this rule set."""
        return {
            "schema_version": self.schema_version,
            "source_citations": list(self.source_citations),
            "executable_buckets": list(self.executable_buckets),
            "non_executable_kinds": list(self.non_executable_kinds),
            "round_economy_capacity": dict(self.round_economy_capacity),
            "max_round_offset": self.max_round_offset,
            "sequence_length": dict(self.sequence_length),
            "fallback_must_be_zero_cost": self.fallback_must_be_zero_cost,
            "enabled_rules": list(self.enabled_rules),
            "notes": list(self.notes),
        }

    def with_overrides(self, **changes: Any) -> "RuleSet":
        """Return a new validated RuleSet with the given fields replaced (test/experiment hook)."""
        unknown = sorted(set(changes) - {f.name for f in fields(self)})
        if unknown:
            raise ValueError(f"unknown RuleSet field(s) in with_overrides: {unknown}")
        data = self.to_mapping()
        data.update(changes)
        return RuleSet.from_mapping(data)

    def is_executable(self, kind: str) -> bool:
        return kind in self.executable_buckets

    def capacity_for(self, bucket: str) -> int | None:
        return self.round_economy_capacity.get(bucket)


def load_rules(path: Path | None = None) -> RuleSet:
    """Load and validate a rules JSON document; defaults to ``DEFAULT_RULES_PATH``."""
    source = Path(path) if path is not None else DEFAULT_RULES_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"rules file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"rules file {source} is not valid JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError(f"rules file {source} must contain a JSON object")
    return RuleSet.from_mapping(raw)
