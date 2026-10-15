"""Height labels for legal movement/teleport menus, without changing authority.

Gate4Engine uses this general presentation seam after candidate vetoes. Only
destinations of the same action at one square with multiple legal heights change;
candidate identity, order, routes and metadata remain untouched.
"""


def distinguish_heights(candidates):
    heights = {}
    for row in candidates:
        if row.destination is not None and (row.kind == "MOVE" or row.metadata.get("teleport")):
            key = (row.source_definition_id, row.destination.x, row.destination.y)
            heights.setdefault(key, set()).add(row.destination.z)
    out = []
    for row in candidates:
        pos = row.destination
        key = (row.source_definition_id, pos.x, pos.y) if pos is not None else None
        if key in heights and len(heights[key]) > 1:
            label = row.display_name
            if row.kind == "MOVE":
                mode = row.metadata.get("movement_mode", "walk")
                verb = "Move" if mode == "walk" else mode.replace("_", " ").title()
                label = f"{verb} to {pos.x},{pos.y}"
            height = "ground" if pos.z == 0 else f"{pos.z * 5} ft up"
            row = row.model_copy(update={"display_name": f"{label} ({height})"})
        out.append(row)
    return tuple(out)
