"""View-time owner text overlay shared by Factory and combat sheets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


RULES_TEXT_SECTIONS = ("talents", "background_talent", "sphere_automatic_components", "spheres", "background_origin", "insights")
RULES_TEXT_MIN_CHARS = 200


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
