"""Disambiguate same-square teleport destinations after legality filtering.

Gate4 uses this presentation-only helper for every self-teleport. Candidate
identity, order, metadata and legal destinations are unchanged; single-height
squares and ordinary movement keep their existing labels.
"""


def distinguish_teleport_heights(candidates, *, square_size_ft):
    heights = {}
    for row in candidates:
        if row.destination is not None and row.metadata.get("teleport"):
            pos = row.destination
            key = (row.source_definition_id, pos.x, pos.y)
            heights.setdefault(key, set()).add(pos.z)
    out = []
    for row in candidates:
        pos = row.destination
        if pos is not None and row.metadata.get("teleport"):
            key = (row.source_definition_id, pos.x, pos.y)
            if len(heights[key]) > 1:
                height = "ground" if pos.z == 0 else f"{pos.z * square_size_ft} ft up"
                row = row.model_copy(update={"display_name": f"{row.display_name} ({height})"})
        out.append(row)
    return tuple(out)
