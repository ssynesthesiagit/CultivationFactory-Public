"""Scratch diagnostic for the Pure Darkness candidate; deleted before commit."""
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
    cat = [(r.display_name, r.owner_id, bool((r.parameters or {}).get("zone_shape")), bool((r.parameters or {}).get("setting_only")))
           for r in engine.action_catalog.values() if "Darkness" in r.display_name]
    raise AssertionError("CAT " + repr(cat)[:1500] + " OWNER=" + OWNER + " CUR=" + str(engine.state.current_actor_id))
