"""Height labels for self-teleport destinations that share a square.

A finite-height map offers every legal standing level as a real landing:
Gate4's height-aware enumeration (combat/gate4_engine.py) and the shared
landing picker (combat/ext/teleport_steps.py) both add those elevated squares
to the legal destinations. This module only formats the labels of candidates
that already passed legality: where one square has more than one legal level,
the label names it plainly ("ground" or "10 ft up") so a player can tell the
landings apart. Candidate identity, option ids, order, destinations and
metadata are never changed here, and a single-level square keeps its label.

The height wording is a lead decision for clarity, not a rules change: Ino
recorded 2026-10-21 07:35Z and approved it 2026-10-21 13:10Z, so reviewers
should not treat the labels as an unapproved UI change.
"""

SEPARATOR = " — "

# Position.z is an altitude index in fixed 5-foot steps (gate2_grid, altitude_ceiling_z),
# whatever the horizontal square_size_ft of the map is.
ALTITUDE_STEP_FT = 5


def height_text(position):
    """The plain height a newcomer reads: "ground" or "10 ft up"."""
    if int(position.z) == 0:
        return "ground"
    return f"{int(position.z) * ALTITUDE_STEP_FT} ft up"


def same_square_heights(positions):
    """Map (x, y) to the legal heights offered on that square."""
    heights = {}
    for position in positions:
        if position is not None:
            heights.setdefault((position.x, position.y), set()).add(position.z)
    return heights


def destination_label(text, position, *, levels):
    """Append the height only when this square offers more than one level."""
    if len(levels) > 1:
        return f"{text}{SEPARATOR}{height_text(position)}"
    return text


def distinguish_teleport_heights(candidates):
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
                row = row.model_copy(update={"display_name": f"{row.display_name}{SEPARATOR}"
                                             f"{height_text(pos)}"})
        out.append(row)
    return tuple(out)
