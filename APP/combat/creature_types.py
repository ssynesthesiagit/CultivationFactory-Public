"""Printed creature labels shared by Factory, portable rosters, summons and plug-ins.

Only explicit creature_type/creature_types fields supply labels. No race, name,
condition, immunity or ability implies a type. Multiple labels use a list;
punctuation inside a printed label is preserved rather than interpreted.
Explicit physiology mappings also travel in this existing persisted field as
reserved string labels (combat.physiology); types_for exposes only creature kinds.
"""
from collections.abc import Mapping
from typing import Any


def from_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Read printed kinds plus validated physiology labels for persisted storage."""
    labels: list[str] = []
    encoded: list[str] = []
    seen: set[str] = set()
    for key in ('creature_type', 'creature_types'):
        value = record.get(key)
        if value is None:
            continue
        values = (value,) if isinstance(value, str) else value
        if not isinstance(values, (list, tuple)):
            raise ValueError('creature types must be text labels or a list of text labels')
        for label in values:
            if not isinstance(label, str):
                raise ValueError('creature type labels must be text')
            label = ' '.join(label.split())
            if label.casefold().startswith('physiology:'):
                encoded.append(label)
                continue
            if label and label.casefold() not in seen:
                labels.append(label)
                seen.add(label.casefold())
    from .physiology import printed_labels
    return tuple(labels) + printed_labels(record, tuple(encoded))


def types_for(actor: Any) -> tuple[str, ...]:
    """Return printed creature kinds, omitting reserved physiology storage labels."""
    return tuple(label for label in actor.creature_types if not label.casefold().startswith('physiology:'))


def has_type(actor: Any, label: str) -> bool:
    """Case-insensitive exact printed-label query; no inferred classifications."""
    wanted = ' '.join(label.split()).casefold()
    return any(value.casefold() == wanted for value in types_for(actor))
