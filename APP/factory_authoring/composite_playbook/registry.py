"""Action-data adapter: complete action surface -> typed, validated records.

The validator must never read the live sheet document directly. Every action-data
source becomes an :class:`ActionRegistry` through a ``from_*`` adapter, so a new
source (package export, sheet projection, test fixture) is a new adapter method
rather than a change to rule logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: Adapter-owned vocabulary normalisation. Unknown economies are kept verbatim
#: (lower-cased) so the validator can report them instead of the adapter hiding them.
ECONOMY_ALIASES: dict[str, str] = {
    "action": "action",
    "standard action": "action",
    "standard_action": "action",
    "bonus action": "bonus_action",
    "bonus_action": "bonus_action",
    "reaction": "reaction",
    "free": "free",
    "free action": "free",
    "free_action": "free",
    "movement": "movement",
    "movement action": "movement",
    "move": "movement",
    "passive": "passive",
    "procedure": "procedure",
    "ritual procedure": "procedure",
    "ritual_procedure": "procedure",
}


def normalize_economy(value: Any) -> str:
    """Normalise an economy label; unknown labels survive as their raw lowercase text."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value).strip().lower()
    return ECONOMY_ALIASES.get(" ".join(value.strip().lower().split()), " ".join(value.strip().lower().split()))


def _coerce_amount(value: Any) -> int | None:
    """Coerce a resource amount to int; ``None`` means 'unusable, skip the row'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _pairs(rows: Any, action_id: str, label: str, warnings: list[str]) -> tuple[tuple[str, int], ...]:
    if rows is None:
        return ()
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        warnings.append(f"{action_id}: {label} is not a list, ignored ({type(rows).__name__})")
        return ()
    out: list[tuple[str, int]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warnings.append(f"{action_id}: {label}[{index}] is not an object, skipped")
            continue
        resource_id = row.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            warnings.append(f"{action_id}: {label}[{index}] has no resource_id, skipped")
            continue
        key = "minimum" if label == "resource_requirements" else "amount"
        amount = _coerce_amount(row.get(key, row.get("amount")))
        if amount is None:
            warnings.append(
                f"{action_id}: {label}[{index}] {resource_id!r} has non-integer {key}="
                f"{row.get(key, row.get('amount'))!r}, row skipped")
            continue
        out.append((resource_id, amount))
    return tuple(out)


def _strings(rows: Any, action_id: str, label: str, warnings: list[str]) -> tuple[str, ...]:
    if rows is None:
        return ()
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        warnings.append(f"{action_id}: {label} is not a list, ignored ({type(rows).__name__})")
        return ()
    out: list[str] = []
    for index, item in enumerate(rows):
        if isinstance(item, str) and item:
            out.append(item)
        else:
            warnings.append(f"{action_id}: {label}[{index}] is not a non-empty string, skipped")
    return tuple(out)


@dataclass(frozen=True)
class ActionRecord:
    """One row of an action surface, reduced to the fields rules actually consume."""

    action_id: str
    display_name: str
    economy: str
    resource_costs: tuple[tuple[str, int], ...] = ()
    resource_requirements: tuple[tuple[str, int], ...] = ()
    creates_states: tuple[str, ...] = ()
    consumes_states: tuple[str, ...] = ()
    limit: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_surface_row(cls, row: Mapping[str, Any], warnings: list[str] | None = None) -> "ActionRecord":
        """Build a record from one complete-action-surface row."""
        sink: list[str] = warnings if warnings is not None else []
        action_id = row.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ValueError(f"action surface row has no usable action_id: {row.get('action_id')!r}")
        display_name = row.get("display_name") or row.get("name") or action_id
        if not isinstance(display_name, str):
            display_name = str(display_name)
        limit = row.get("limit")
        return cls(
            action_id=action_id,
            display_name=display_name,
            economy=normalize_economy(row.get("economy")),
            resource_costs=_pairs(row.get("resource_costs"), action_id, "resource_costs", sink),
            resource_requirements=_pairs(
                row.get("resource_requirements"), action_id, "resource_requirements", sink),
            creates_states=_strings(row.get("creates_states"), action_id, "creates_states", sink),
            consumes_states=_strings(row.get("consumes_states"), action_id, "consumes_states", sink),
            limit=limit if isinstance(limit, str) else (None if limit is None else str(limit)),
            raw=dict(row),
        )


class ActionRegistry:
    """Read-only action lookup built by an adapter; ``warnings`` records skipped rows."""

    def __init__(self, records: Iterable[ActionRecord] = (), warnings: Iterable[str] = ()) -> None:
        self._by_id: dict[str, ActionRecord] = {}
        self.warnings: list[str] = list(warnings)
        for record in records:
            if record.action_id in self._by_id:
                raise ValueError(f"duplicate action_id in action surface: {record.action_id!r}")
            self._by_id[record.action_id] = record

    @classmethod
    def from_complete_action_surface(cls, document_or_list: Any) -> "ActionRegistry":
        """Adapter for a ``Complete_Action_Surface.json`` document or a bare row list."""
        if isinstance(document_or_list, Mapping):
            if "actions" not in document_or_list:
                raise ValueError(
                    "complete action surface object has no 'actions' list "
                    f"(keys: {sorted(str(k) for k in document_or_list)})")
            rows = document_or_list["actions"]
        else:
            rows = document_or_list
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
            raise ValueError(f"action surface must be a list of rows, got {type(rows).__name__}")
        warnings: list[str] = []
        records: list[ActionRecord] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                warnings.append(f"actions[{index}] is not an object, skipped ({type(row).__name__})")
                continue
            action_id = row.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                warnings.append(f"actions[{index}] has no usable action_id, skipped")
                continue
            records.append(ActionRecord.from_surface_row(row, warnings))
        return cls(records, warnings)

    @classmethod
    def from_sheet_actions(cls, surface: Any) -> "ActionRegistry":
        """Adapter for the live sheet's ``surfaces.actions.data`` projection.

        The projected rows keep the Complete_Action_Surface field names, so the
        surface adapter applies directly.  An empty authored surface yields an
        empty registry; use ``sheet_adapter.registry_from_sheet`` for the sealed
        records instead.
        """
        rows = surface.get("actions") if isinstance(surface, Mapping) else surface
        return cls.from_complete_action_surface(rows or [])

    def get(self, action_id: str) -> ActionRecord | None:
        return self._by_id.get(action_id)

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def ids(self) -> list[str]:
        """Action ids in surface order."""
        return list(self._by_id)
