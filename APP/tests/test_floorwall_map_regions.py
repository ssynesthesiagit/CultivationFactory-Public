"""FLOORWALL: authored indoor floor regions, through the map store and table projection."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from combat.roof_coverage import roof_regions
from combat.tabletop import TabletopMapStore, normalize_map, to_battlefield, wall_cells
from tools.map_floor_regions import confine_floor_to_rooms


ROOT = Path(__file__).resolve().parents[1]
MAP_ID = "builtin-willow-village-compound"


def cells(document, style):
    return {tuple(cell) for row in document["materials"] if row["material"] == "floor:" + style
            for cell in row["cells"]}


def test_willow_exterior_floor_and_room_authoring_survive_map_save_reload(tmp_path):
    store = TabletopMapStore(tmp_path, ROOT / "combat/maps")
    shipped = store.get(MAP_ID)
    rooms = roof_regions(shipped, wall_cells)
    inside = set().union(*(room["cells"] for room in rooms))
    assert len(rooms) == 5
    assert len(cells(shipped, "sutra_hall_wood")) == 188
    assert cells(shipped, "sutra_hall_wood") <= inside

    # The screenshot's upper lane strip and wide lower band were painted brick
    # outside the ancestral hall; these are map cells, not screen coordinates.
    assert not cells(shipped, "herringbone_brick")
    assert {(13, 2), (13, 8), (20, 2), (26, 8), (20, 13)} <= cells(shipped, "packed_dirt")
    assert len(cells(shipped, "packed_dirt")) == 520

    # Recreate a generator's over-broad rectangle: one legitimate interior
    # square plus the whole outside ring (including the wall footprint). The rule keeps the
    # former, replaces the latter, and never fills a building's bounding box.
    outside = {(x, y) for x in range(13, 27) for y in range(2, 12)
               if not (15 <= x <= 24 and 4 <= y <= 9)}
    outside |= {(x, y) for x in range(14, 26) for y in range(12, 15)}
    assert len(outside) == 116
    authored = deepcopy(shipped)
    authored["materials"].append({"material": "floor:herringbone_brick",
                                  "cells": [list(cell) for cell in sorted(outside | {(20, 6)})]})
    untouched = deepcopy(authored)
    corrected = confine_floor_to_rooms(authored, "herringbone_brick", "packed_dirt")
    assert authored == untouched
    assert cells(corrected, "herringbone_brick") == {(20, 6)}
    assert outside <= cells(corrected, "packed_dirt")
    assert cells(corrected, "sutra_hall_wood") == cells(shipped, "sutra_hall_wood") - {(20, 6)}
    assert confine_floor_to_rooms(corrected, "herringbone_brick", "packed_dirt") == corrected

    saved = store.save({**corrected, "map_id": "floorwall-copy"})
    reloaded = TabletopMapStore(tmp_path, ROOT / "combat/maps").get("floorwall-copy")
    assert reloaded == saved
    sealed = to_battlefield(reloaded)
    assert {tuple(cell) for row in sealed["tabletop"]["floors"] if row["style"] == "herringbone_brick"
            for cell in row["cells"]} == {(20, 6)}
    # Authoring alters only visual floor rows. Structural rules and roof
    # surfaces stay exactly the same through the table's sealed projection.
    before = to_battlefield(shipped)
    del before["tabletop"]["floors"]
    del sealed["tabletop"]["floors"]
    for document in (before, sealed):
        document["stable_id"] = "map-copy"
        document["tabletop"]["map_id"] = "map-copy"
    assert before == sealed


@pytest.mark.parametrize("style,outside", [("grass_meadow", "packed_dirt"),
                                           ("herringbone_brick", "unknown"),
                                           ("wood", "wood")])
def test_room_floor_authoring_rejects_invalid_styles(style, outside):
    document = json.loads((ROOT / "combat/maps" / (MAP_ID + ".json")).read_text())
    with pytest.raises(ValueError):
        confine_floor_to_rooms(document, style, outside)
    assert normalize_map(document)["materials"] == document["materials"]
