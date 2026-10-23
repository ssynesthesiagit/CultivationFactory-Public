"""Scratch diagnostic for the Pure Darkness candidate; deleted before commit."""
import json, os
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]


def test_diag_e11_candidates(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(24, 14, ambient=NIGHT), senses=DARKVISION,
                               ally_senses=[{"sense": "blindsight", "range_ft": 30}],
                               talents=["DARK_BASE_DARKNESS", "TAL_DARK_PURE_DARKNESS"],
                               positions={OWNER: {"x": 12, "y": 6}, ALLY: {"x": 14, "y": 6}, FOE: {"x": 2, "y": 2}})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    shapes = []
    for row in engine.action_catalog.values():
        p = row.parameters or {}
        if p.get("zone_shape"):
            shapes.append({"name": row.display_name, "owner": row.owner_id, "costs": p.get("shape_costs"),
                           "talents": p.get("shape_talents")})
    names = sorted({c.display_name for c in engine.legal_candidates()})
    info = {"current": engine.state.current_actor_id, "owner_resources": {str(k): v for k, v in owner.resources.items()},
            "shapes": shapes, "legal_names": names}
    os.makedirs("/var/tmp/lights1f4-evidence", exist_ok=True)
    with open("/var/tmp/lights1f4-evidence/diag.json", "w") as handle:
        json.dump(info, handle, indent=1, default=str)
    assert False, "DIAG " + json.dumps(info, default=str)[:2400]
