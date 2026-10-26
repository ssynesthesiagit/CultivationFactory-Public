"""Real table harness for the FD-19 lighting regressions (docs/specs/LIGHTING_SPEC.md §8).

A map is saved through the map store and handed to the worker-2 fixture as its battlefield, so every test below fights on
a real map document through the same TabletopMapStore -> to_battlefield -> TabletopService path the table uses. Nothing
here reaches into the fight state: the tests ask the engine and the table, and a cold reload asks again.
"""
from typing import Any

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.worker2_support import ALLY, FOE, OWNER, fixture

__all__ = ["ALLY", "FOE", "OWNER", "ambient_light", "fight", "light", "map_arena", "map_document", "torch"]


def map_document(width=20, height=12, *, ambient=None, lights=None, regions=None, walls=None, roofs=None,
                 materials=None, starts=None):
    """The document a map is saved from: a flat plate unless the test gives it walls, and light only when it names it."""
    document: dict[str, Any] = {"display_name": "Lighting S1", "width_squares": width, "height_squares": height,
                                "walls": list(walls or []), "terrain": [],
                                "starts": starts or {"team1": [[2, 2]], "team2": [[2, 4]]}}
    if ambient is not None:
        document["ambient"] = dict(ambient)
    if lights is not None:
        document["lights"] = [dict(row) for row in lights]
    if regions is not None:
        document["ambient_regions"] = [dict(row) for row in regions]
    if roofs is not None:
        document["roofs"] = dict(roofs)
    if materials is not None:
        document["materials"] = [dict(row) for row in materials]
    return document


def ambient_light(time_of_day="night", indoor_level=None):
    """The map's ambient block: the setting the fight happens under (spec §2.9, §3.2)."""
    row = {"time_of_day": time_of_day}
    if indoor_level is not None:
        row["indoor_level"] = indoor_level
    return row


def light(x, y, *, bright_ft=20, dim_ft=40, name="Torch", magical=False, light_id=None):
    """One placed light on one square (spec §3.2)."""
    return {"id": light_id or f"light-{x}-{y}", "name": name, "x": x, "y": y,
            "bright_ft": bright_ft, "dim_ft": dim_ft, "magical": magical}


torch = light


def map_arena(tmp_path, document):
    """Save the map the way the editor does and take the arena the table would start a fight on."""
    service = CombatService(ROOT, tmp_path)
    saved = service.tabletop_maps.save(document)
    return service.factory_arenas()["battlefield:map." + saved["map_id"]]


def fight(tmp_path, document=None, *, talents=(), ally_talents=(), senses=None, ally_senses=None, positions=None,
          seed="LIGHTING-S1", modes=None, battlefield_transform=None, extra_allies=0):
    """Start a real fight on the saved map: (combat, table, match_id), already at the owner's turn.

    senses is a list of {"sense": "darkvision", "range_ft": 60} written into the compiled bundle's senses rows exactly
    where combat/factory_compiler.py writes a granted sense, which is the only thing combat/senses.py reads; passing an empty
    list takes every sense away (the fixture sheets are born with the species' Darkvision, and a lighting test that asks what a
    creature without it sees has to say so).
    """
    def transform(bundles):
        for index, rows in ((0, senses), (1, ally_senses)):
            if rows is not None:
                bundles[index]["senses"] = {"rows": [
                    {"feature_id": f"test:lighting.{row['sense']}", "sense": row["sense"],
                     "range_ft": int(row["range_ft"]), "when": "always"} for row in rows]}
    return fixture(tmp_path, list(talents), ally_talents=list(ally_talents), bundle_transform=transform,
                   battlefield=map_arena(tmp_path, document or map_document()), positions=positions, seed=seed,
                   modes=modes, battlefield_transform=battlefield_transform, extra_allies=extra_allies)


def payload(table, match_id, viewer_id):
    """The table's own light answer for one viewer, as the browser receives it (spec §7.1)."""
    return table.state(match_id, fog=True)["light"][viewer_id]
