"""Source-defined acquisition choices, shared by the builder and combat compilation.

A choice is owner input, never a grant. A sealed project snapshot transports it;
the consumer must independently verify that the character acquired the parent
feature. Void-Touched Cultivator's permanent Void Scar is the first entry: it is
chosen once when the Secret Law is acquired, and it can only be changed by the
major story procedure its printed text names.
"""
import json
from pathlib import Path

from app.core import FoundryError
from character_creation.choice_snapshot import valid_choice_snapshot

FIELD = "character.choices.acquisition"
DEFINITIONS = Path(__file__).resolve().parents[1] / "combat/rules/acquisition_choices.json"


def definitions() -> dict[str, dict]:
    return json.loads(DEFINITIONS.read_text(encoding="utf-8"))


def _valid_value(definition: dict, value: object) -> bool:
    if definition.get("value_type") == "text":
        return (isinstance(value, str) and value == value.strip()
                and 1 <= len(value) <= int(definition.get("maximum_length", 500))
                and all(ord(char) >= 32 for char in value))
    return isinstance(value, str) and value in (definition.get("options") or [])


def validate(selected_record_ids, selections, *, require_complete=True) -> dict[str, str]:
    """Validate exact options for the selected parents; never choose for an owner."""
    offered = {key: row for key, row in definitions().items()
               if row["parent_id"] in selected_record_ids}
    supplied = selections or {}
    if not isinstance(supplied, dict) or set(supplied) - set(offered):
        raise FoundryError("ACQUISITION_CHOICE_UNOWNED", "Choose only for a selected feature.")
    missing = [row for key, row in offered.items() if key not in supplied]
    if require_complete and missing:
        raise FoundryError("ACQUISITION_CHOICE_REQUIRED",
                           "Choose the feature's starting option before acquiring it.",
                           details={"choices": missing})
    for key, value in supplied.items():
        if not _valid_value(offered[key], value):
            raise FoundryError("ACQUISITION_CHOICE_INVALID",
                               "Choose one of the printed options.",
                               details={"choice": offered[key]})
    return dict(supplied)


def from_sheet(sheet: dict) -> dict[str, str]:
    """Read choices only from a valid sealed builder snapshot, not loose metadata."""
    snapshot = (sheet.get("advancement_history") or {}).get("typed_choice_snapshot") or {}
    if not valid_choice_snapshot(snapshot):
        return {}
    rows = [row.get("value") for row in snapshot.get("typed_locks", []) if row.get("field") == FIELD]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return {}
    return validate({row["parent_id"] for row in definitions().values()}, rows[0],
                    require_complete=False)


def recorded(sheet: dict, parent_id: str) -> dict[str, str]:
    """The choices recorded for one native acquisition on a compiled combat sheet.

    A native projection writes the persisted row onto ``path_and_subpath``; a
    builder-created character carries its sealed snapshot instead. Loose
    top-level metadata never counts as acquisition.
    """
    paths = sheet.get("path_and_subpath") or {}
    direct = (paths.get("acquisition_choices") or {}).get(parent_id)
    if isinstance(direct, dict):
        return validate([parent_id], direct, require_complete=False)
    for row in paths.get("paths") or []:
        if not isinstance(row, dict) or row.get("subpath_or_tradition_id") != parent_id:
            continue
        provenance = row.get("subpath_or_tradition_acquisition_provenance") or {}
        if provenance.get("recorded") is True and provenance.get("canonical_content_id") == parent_id:
            return validate([parent_id], row.get("acquisition_choices"), require_complete=False)
    return validate([parent_id], from_sheet(sheet), require_complete=False)


def for_acquisition(project: dict, parent_id: str) -> dict[str, str]:
    """Bind a native builder acquisition event to its already recorded owner choices.

    A parent proposed after blueprint creation without its choice blocks the
    grant and presents the exact choice instead of inventing a default. Other
    parents' choices are neither granted nor copied into this event.
    """
    wanted = {key for key, row in definitions().items() if row["parent_id"] == parent_id}
    if not wanted:
        return {}
    rows = [row.get("value") for row in project.get("user_locks", []) if row.get("field") == FIELD]
    values = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
    return validate([parent_id], {key: values[key] for key in wanted if key in values})
