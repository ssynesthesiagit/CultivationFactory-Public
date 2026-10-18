"""Editor durability and real map-store deletion/reload regressions."""
from itertools import product
from pathlib import Path

from combat.object_rules import editor_defaults, presets, rules, stats
from combat.tabletop import TabletopMapStore


def test_maps_api_exposes_table_resolved_editor_defaults(tmp_path):
    from app.api import create_app
    from app.core import Settings

    app = create_app(Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "data"))
    endpoint = next(route.endpoint for route in app.routes
                    if route.path == "/api/tabletop/maps" and "GET" in route.methods)
    response = endpoint()
    assert response["object_defaults"] == editor_defaults()
    assert response["object_defaults"]["presets"]["door"]["hp"] == 18
    assert response["object_defaults"]["presets"]["door"]["ac"] == 15


def test_editor_defaults_match_table_resolution():
    defaults = editor_defaults()
    for kind, material, size, resilient in product(presets(), rules()["materials"], rules()["sizes"], (False, True)):
        row = stats(dict(kind=kind, material=material, size=size, resilient=resilient))
        assert defaults["materials"][material] == row["ac"]
        assert defaults["sizes"][size][str(int(resilient))] == row["hp"]
    for kind in presets():
        row = stats({"kind": kind})
        assert defaults["presets"][kind]["hp"] == row["hp"]
        assert defaults["presets"][kind]["ac"] == row["ac"]


def test_deleted_object_stays_deleted_after_map_commit_reload(tmp_path):
    store = TabletopMapStore(tmp_path / "maps")
    saved = store.save({"display_name": "SOL69", "width_squares": 8, "height_squares": 8,
                        "objects": [{"id": 1, "kind": "door", "x": 3, "y": 3}]})
    assert len(store.get(saved["map_id"])["objects"]) == 1
    saved["objects"].clear()
    store.save(saved)
    assert TabletopMapStore(tmp_path / "maps").get(saved["map_id"])["objects"] == []
