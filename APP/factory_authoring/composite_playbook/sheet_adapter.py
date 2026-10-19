"""Adapter: sealed owner character sheet -> ActionRegistry + resource pools.

The authored action surface can be empty (``ACTION_SURFACE_PARTIAL``), so the
grounded repertoire is the sealed sheet's own records whose printed rules carry
an ``Action Type:`` block -- the same rule the owner tab's repertoire uses
(``ownerActionRepertoire`` in APP/static/app.js) -- plus the 5.5e baseline
actions the combat bootstrap delegates to (``rules/base_actions.v1.json``).

Only labelled lines are read (Action Type, Factory Combat Bucket, Cost,
Trigger, Prerequisite); nothing else is inferred from prose.  ``N CP`` (or
``N <primary resource name>``, e.g. ``4 Qi``) charges the sheet's primary
resource.  A cost that does not parse is kept on the record
(``raw["cost_parsed"] is False``) so a proposer can exclude it.

Learned Forged Techniques are read from the sheet's ``forged_techniques``
container (same aliases Command 5 uses); their structured fields lead
(``action_type``, ``cp_cost.final``, ``limits``) and the printed text supplies
labelled lines when a field is absent.  They are the character's own records
(``raw["forged"] is True``), never baseline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .registry import ActionRecord, ActionRegistry, normalize_economy
from .rules import RULES_DIR

DEFAULT_BASE_ACTIONS_PATH = RULES_DIR / "base_actions.v1.json"
#: Sections of ``selected_record_sections`` that can grant a usable action.
#: ``spheres`` is excluded: a Sphere row restates its component talents' text.
DEFAULT_SECTIONS = ("talents", "sphere_automatic_components", "path_features",
                    "advancement_features", "background_talent")


def _line(label: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*(?:\*\*)?{label}(?:\*\*)?\s*:\s*(.+?)\s*$", re.I | re.M)


_ACTION_TYPE = _line("Action Type")
_BUCKET = _line("Factory Combat Bucket")
_COST = _line("Cost")
_TRIGGER = _line("Trigger")
_PREREQUISITE = _line("Prerequisite")
_UNIT_COST = re.compile(r"^\s*(\d+)\s*([A-Za-z][A-Za-z ]*?)\s*\.?\s*$")
_NO_COST = frozenset({"", "none", "no cost", "0", "0 cp", "free"})


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).replace("**", "").strip().rstrip(".")
    return value or None


def parse_printed_cost(text: str | None, resource_id: str,
                       resource_names: tuple[str, ...] = ("cp",)) -> tuple[tuple[tuple[str, int], ...], bool]:
    """Return (resource_costs, parsed).  ``N CP`` or ``N <resource name>`` charges ``resource_id``; None/empty is free."""
    if text is None or text.strip().lower() in _NO_COST:
        return (), True
    match = _UNIT_COST.match(text)
    if match and match.group(2).strip().casefold() in {name.casefold() for name in resource_names}:
        return ((resource_id, int(match.group(1))),), True
    return (), False


def sheet_record_to_action(record: Mapping[str, Any], *, section: str, resource_id: str,
                           resource_names: tuple[str, ...] = ("cp",)) -> ActionRecord | None:
    """One sealed record -> ActionRecord, or None when it prints no Action Type."""
    text = record.get("full_description") or record.get("player_rules_text") or ""
    if not isinstance(text, str):
        return None
    action_type = _first(_ACTION_TYPE, text)
    if not action_type:
        return None
    record_id = record.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        return None
    bucket = _first(_BUCKET, text)
    cost_text = _first(_COST, text)
    costs, cost_parsed = parse_printed_cost(cost_text, resource_id, resource_names)
    preconditions = tuple(
        f"{label}: {value}"
        for label, pattern in (("Trigger", _TRIGGER), ("Prerequisite", _PREREQUISITE))
        if (value := _first(pattern, text))
    )
    display_name = record.get("display_name") or record_id
    return ActionRecord(
        action_id=record_id,
        display_name=str(display_name),
        economy=normalize_economy(bucket or action_type),
        resource_costs=costs,
        raw={
            "record_id": record_id,
            "source_section": section,
            "action_type": action_type,
            "cost_text": cost_text,
            "cost_parsed": cost_parsed,
            "external_preconditions": preconditions,
            "rules_text": text,
            "base": False,
        },
    )


def forged_technique_rows(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The sheet's learned Forged Techniques wherever the sealed sheet keeps them (mirrors Command 5's aliases)."""
    containers: list[Mapping[str, Any]] = [snapshot]
    for key in ("advanced_systems", "advanced_arts", "source_containers", "source_records"):
        value = snapshot.get(key)
        if isinstance(value, Mapping):
            containers.append(value)
    for container in containers:
        for alias in ("forged_techniques", "forged"):
            raw = container.get(alias)
            if isinstance(raw, list):
                if raw:
                    return [row for row in raw if isinstance(row, Mapping)]
                continue
            if isinstance(raw, Mapping):
                for entry_key in ("entries", "records", "items", "arts", "techniques"):
                    entries = raw.get(entry_key)
                    if isinstance(entries, list) and entries:
                        return [row for row in entries if isinstance(row, Mapping)]
    return []


def forged_technique_to_action(record: Mapping[str, Any], *, resource_id: str,
                               resource_names: tuple[str, ...] = ("cp",)) -> ActionRecord | None:
    """One learned Forged Technique -> ActionRecord, or None when it names no action type."""
    record_id = record.get("record_id") or record.get("technique_id")
    if not isinstance(record_id, str) or not record_id:
        return None
    projection = record.get("display_projection") if isinstance(record.get("display_projection"), Mapping) else {}
    text = next((value for value in (record.get("full_description"), record.get("record_text"),
                                     projection.get("full_description")) if isinstance(value, str) and value), "")
    action_type = record.get("action_type") if isinstance(record.get("action_type"), str) and record.get("action_type") else None
    action_type = action_type or _first(_ACTION_TYPE, text)
    if not action_type:
        return None
    bucket = _first(_BUCKET, text)
    cp = record.get("cp_cost")
    final = cp.get("final") if isinstance(cp, Mapping) else cp
    if isinstance(final, int) and not isinstance(final, bool) and final >= 0:
        cost_text = f"{final} CP"
        costs: tuple[tuple[str, int], ...] = ((resource_id, final),) if final else ()
        cost_parsed = True
    else:
        cost_text = _first(_COST, text)
        costs, cost_parsed = parse_printed_cost(cost_text, resource_id, resource_names)
    preconditions = [f"{label}: {value}" for label, pattern in (("Trigger", _TRIGGER), ("Prerequisite", _PREREQUISITE))
                     if (value := _first(pattern, text))]
    preconditions.extend(f"Limit: {item}" for item in (record.get("limits") or []) if isinstance(item, str) and item)
    display_name = record.get("display_name") or record.get("name") or record_id
    return ActionRecord(
        action_id=record_id,
        display_name=str(display_name),
        economy=normalize_economy(bucket or action_type),
        resource_costs=costs,
        raw={"record_id": record_id, "source_section": "forged_techniques", "action_type": action_type,
             "cost_text": cost_text, "cost_parsed": cost_parsed, "external_preconditions": tuple(preconditions),
             "rules_text": text, "base": False, "forged": True},
    )


def load_base_actions(path: Path | None = None) -> list[ActionRecord]:
    """The 5.5e baseline actions the bootstrap delegates to (data file, names only)."""
    source = Path(path) if path is not None else DEFAULT_BASE_ACTIONS_PATH
    document = json.loads(source.read_text(encoding="utf-8"))
    records: list[ActionRecord] = []
    for row in document.get("actions") or []:
        records.append(ActionRecord(
            action_id=str(row["action_id"]),
            display_name=str(row["name"]),
            economy=normalize_economy(row.get("economy")),
            raw={"base": True, "source_label": document.get("source_label", ""),
                 "cost_parsed": True, "external_preconditions": (), "cost_text": None},
        ))
    return records


def primary_resource_pool(snapshot: Mapping[str, Any]) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """(primary resource_id, pools) from ``ability_scores_and_statistics.primary_resource``."""
    stats = snapshot.get("ability_scores_and_statistics") if isinstance(snapshot, Mapping) else None
    primary = stats.get("primary_resource") if isinstance(stats, Mapping) else None
    pools: dict[str, dict[str, Any]] = {}
    primary_id: str | None = None
    if isinstance(primary, Mapping):
        for definition in primary.get("definitions") or []:
            if not isinstance(definition, Mapping):
                continue
            resource_id = definition.get("resource_id")
            if not isinstance(resource_id, str) or not resource_id:
                continue
            pool: dict[str, Any] = {"name": definition.get("name") or resource_id}
            for key, target in (("current", "current"), ("max", "maximum"), ("maximum", "maximum")):
                value = definition.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    pool[target] = value
            pools[resource_id] = pool
            primary_id = primary_id or resource_id
    return primary_id, pools


def registry_from_sheet(
    snapshot: Mapping[str, Any],
    *,
    sections: tuple[str, ...] = DEFAULT_SECTIONS,
    include_base_actions: bool = True,
    base_actions_path: Path | None = None,
    include_forged: bool = True,
) -> tuple[ActionRegistry, dict[str, dict[str, Any]], str | None]:
    """Return (registry, resource_pools, primary_resource_id) for a sealed owner sheet."""
    primary_id, pools = primary_resource_pool(snapshot)
    resource_id = primary_id or "primary_resource"
    pool_name = pools.get(primary_id, {}).get("name") if primary_id else None
    names: tuple[str, ...] = ("cp",) + ((str(pool_name),) if pool_name else ())
    warnings: list[str] = []
    records: list[ActionRecord] = []
    seen: set[str] = set()
    section_map = snapshot.get("selected_record_sections") if isinstance(snapshot, Mapping) else None
    for section in sections:
        rows = section_map.get(section) if isinstance(section_map, Mapping) else None
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            action = sheet_record_to_action(row, section=section, resource_id=resource_id, resource_names=names)
            if action is None or action.action_id in seen:
                continue
            seen.add(action.action_id)
            if not action.raw.get("cost_parsed"):
                warnings.append(f"{action.action_id}: cost {action.raw.get('cost_text')!r} not parsed; excluded from proposals")
            records.append(action)
    if include_forged:
        for row in forged_technique_rows(snapshot) if isinstance(snapshot, Mapping) else []:
            action = forged_technique_to_action(row, resource_id=resource_id, resource_names=names)
            if action is None or action.action_id in seen:
                continue
            seen.add(action.action_id)
            if not action.raw.get("cost_parsed"):
                warnings.append(f"{action.action_id}: cost {action.raw.get('cost_text')!r} not parsed; excluded from proposals")
            records.append(action)
    if include_base_actions:
        for base in load_base_actions(base_actions_path):
            if base.action_id not in seen:
                seen.add(base.action_id)
                records.append(base)
    if primary_id is None:
        warnings.append("no primary_resource definition on the sheet; CP costs cannot be checked against a pool")
    return ActionRegistry(records, warnings), pools, primary_id
