"""Printed physiology shared by creature-record ingestion and physiology plug-ins.

Factory identity and summon records accept ``physiology: {trait: bool}``.
Explicit values are encoded as reserved string labels in the existing persisted
creature_types field, keeping saved-fight models and old bundles unchanged.
Ordinary creature-kind readers omit these labels. No names, immunity or lore
imply anatomy. Missing anatomy stays unknown; breathing alone has type defaults.
"""
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping

PREFIX = "physiology:"


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "rules/creature_physiology.json").read_text())


def printed_labels(record: Mapping[str, Any], encoded: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Validate reserved labels and explicit traits for Factory/summon ingestion.

    Encoded labels must use canonical names and 0/1 values. Matching declarations
    collapse to one label; conflicts, including with the explicit mapping, reject
    the record. Explicit declarations override type defaults, never each other.
    """
    traits = record.get("physiology", {})
    if not isinstance(traits, dict):
        raise ValueError("physiology must be a mapping of printed traits to booleans")
    values: dict[str, bool] = {}
    for label in encoded:
        parts = label.split(":")
        if (len(parts) != 3 or parts[0] != PREFIX[:-1]
                or parts[1] not in catalog()["traits"] or parts[2] not in {"0", "1"}):
            raise ValueError("invalid reserved physiology label")
        name, value = parts[1], parts[2] == "1"
        if name in values and values[name] != value:
            raise ValueError(f"conflicting physiology trait: {name}")
        values[name] = value
    for name, value in traits.items():
        if name not in catalog()["traits"] or type(value) is not bool:
            raise ValueError("physiology traits must be known names with boolean values")
        if name in values and values[name] != value:
            raise ValueError(f"conflicting physiology trait: {name}")
        values[name] = value
    return tuple(f"{PREFIX}{name}:{int(value)}" for name, value in values.items())


def trait(actor: Any, name: str) -> bool | None:
    """Read explicit physiology first, then type defaults; absent anatomy is None.

    Unlabelled legacy actors use the ordinary breathing default, but this query
    changes nothing unless an ability explicitly requests a physiology gate.
    """
    data = catalog()
    if name not in data["traits"]:
        raise ValueError(f"unknown physiology trait: {name}")
    labels = tuple(getattr(actor, "creature_types", ()) or ())
    values = {label.rsplit(":", 1)[-1] for label in labels if label.startswith(f"{PREFIX}{name}:")}
    if values:
        if len(values) != 1 or not values <= {"0", "1"}:
            raise ValueError(f"conflicting or invalid physiology trait: {name}")
        return values == {"1"}
    from .ext.creature_kinds import labels as creature_labels
    defaults = [data["creature_type_defaults"][kind][name] for kind in creature_labels(actor)
                if name in data["creature_type_defaults"].get(kind, {})]
    return all(defaults) if defaults else data["defaults"].get(name)
