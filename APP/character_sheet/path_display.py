"""Read-only Path/Subpath projection shared by character sheets and fighter cards.

Uses finalized ownership bindings; never infers attainment or edits a sheet.
"""
from typing import Any


def path_display(sheet: dict[str, Any]) -> dict[str, Any]:
    block = sheet.get("path_and_subpath") or {}
    paths = block.get("paths") or (sheet.get("identity") or {}).get("paths") or []
    subpaths = block.get("subpaths") or []
    if not subpaths and isinstance(block.get("subpath"), dict):
        subpaths = [block["subpath"]]
    entries = []
    for row in paths:
        if not isinstance(row, dict):
            continue
        name = row.get("display_name") or row.get("name")
        if not name:
            continue
        path_id = row.get("path_id") or row.get("record_id")
        bound_ids = {binding.get("subpath_id") for binding in block.get("bindings") or []
                     if isinstance(binding, dict) and path_id and binding.get("path_id") == path_id
                     and binding.get("subpath_id")}
        names = []
        for sub in subpaths:
            if not isinstance(sub, dict):
                continue
            owner = sub.get("owning_path_id")
            if not path_id or not (owner == path_id or (not owner and sub.get("subpath_id") in bound_ids)):
                continue
            label = sub.get("display_name") or sub.get("name")
            if label and label not in names:
                names.append(label)
        entries.append({"path": name, "subpaths": names})
    return {"path_entries": entries, "path_summary": " + ".join(
        row["path"] + (f" ({', '.join(row['subpaths'])})" if row["subpaths"] else "")
        for row in entries) if len(entries) > 1 else None}
