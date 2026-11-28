"""View-time owner text overlay shared by Factory and combat sheets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


RULES_TEXT_SECTIONS = ("talents", "background_talent", "sphere_automatic_components", "spheres", "background_origin", "insights")
RULES_TEXT_MIN_CHARS = 200


def overlay_constructed_art_display(
    snapshot: dict[str, Any], *, locked_displays: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update display copies, never the projection or installed sheet bytes."""
    from character_creation.constructed_arts.forged_technique import FORGED_TECHNIQUE_SCHEMA
    from character_creation.constructed_arts.records import render_constructed_art_display

    displays = dict(locked_displays or {})
    result = snapshot
    for section, kind in (("forged_techniques", "forged_technique"), ("immortal_arts", "immortal_art")):
        rows = snapshot.get(section)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            record_id = row.get("record_id") or row.get("technique_id") or row.get("art_id")
            if not isinstance(record_id, str) or not record_id.startswith("tianxia.constructed."):
                continue
            display = displays.get(record_id)
            if display is None:
                # A creation projection omits the design policy. Without its
                # locked record, don't redraw it as if it were a legacy design.
                if kind == "forged_technique" and row.get("schema") != FORGED_TECHNIQUE_SCHEMA:
                    continue
                display = render_constructed_art_display(row, projected_kind=kind)["display_projection"]
                displays[record_id] = display
            if result is snapshot:
                result = deepcopy(snapshot)
            result[section][index]["record_text"] = display["full_description"]
    if displays:
        for section, rows in (snapshot.get("selected_record_sections") or {}).items():
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                display = displays.get(row.get("record_id")) if isinstance(row, dict) else None
                if display is None:
                    continue
                if result is snapshot:
                    result = deepcopy(snapshot)
                result["selected_record_sections"][section][index].update(
                    one_line_description=display["short_description"],
                    full_description=display["full_description"],
                )
    return result


def overlay_owner_current_rules(
    snapshot: Any,
    *,
    edits: dict[str, Any],
    apply_owner_edit: Callable[[str, Any], tuple[Any, str, Any]],
    authenticated_rules_block: Callable[[dict[str, Any], Any], tuple[str, str]],
    factory_root: Callable[[], Any],
) -> Any:
    """Copy display rows, authenticate missing printed prose, and apply current owner edits."""
    if not isinstance(snapshot, dict):
        return snapshot
    sections = snapshot.get("selected_record_sections")
    if not isinstance(sections, dict):
        return snapshot
    from character_sheet.build_provenance import effective_component_rules, present_build_provenance

    changed = False
    result = snapshot
    # Fill genuinely incomplete acquisition cards before applying owner edits,
    # so receipt fallback cannot introduce superseded prose after the overlay.
    components = {row.get("component_id"): row for row in
                  (snapshot.get("spheres_and_talents") or {}).get("automatic_sphere_components") or []}
    for index, row in enumerate(sections.get("sphere_automatic_components") or []):
        display = effective_component_rules(row, components.get(row.get("record_id")) or {})
        if display is not row:
            if not changed:
                result = deepcopy(snapshot)
                changed = True
            result["selected_record_sections"]["sphere_automatic_components"][index] = display
    sections = result["selected_record_sections"]
    for kind, rows in sections.items():
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            edit = edits.get(row.get("record_id"))
            if kind not in RULES_TEXT_SECTIONS and not edit:
                continue
            current = row.get("full_description")
            current_text = current.strip() if isinstance(current, str) else ""
            if len(current_text) >= RULES_TEXT_MIN_CHARS and not edit:
                continue
            block, identity = current_text, row.get("rules_text_source_locator")
            source_label = row.get("full_description_source")
            # A short authenticated/owner-edited rule is complete current text,
            # not evidence that a longer historical source should replace it.
            if len(current_text) < RULES_TEXT_MIN_CHARS and not source_label and not identity:
                authenticated, locator = authenticated_rules_block(row.get("source"), factory_root())
                if len(authenticated) > len(current_text):
                    block, identity = authenticated, locator
                    source_label = "locked_catalog_record_rules_text"
            pending_edit = edit
            already_edited = False
            if edit:
                pairs = edit.get("replace") or []
                pending_pairs = [pair for pair in pairs if not pair.get("new") or pair["new"] not in block]
                already_edited = len(pending_pairs) != len(pairs)
                pending_edit = {**edit, "replace": pending_pairs}
            _removed, edited, _problems = apply_owner_edit(block, pending_edit)
            if edited != block or already_edited:
                block = edited
                source_label = "Owner-edited current rules"
            if block == current_text and source_label == row.get("full_description_source"):
                continue
            if not changed:
                result = deepcopy(snapshot)
                changed = True
            target = result["selected_record_sections"][kind][index]
            target["full_description"] = block
            target["full_description_source"] = source_label
            target["rules_text_source_locator"] = identity or None
    return present_build_provenance(result)
