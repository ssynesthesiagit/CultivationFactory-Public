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
    names = sorted({c.display_name for c in engine.legal_candidates()})
    shape_rows = sorted(k for k, row in engine.action_catalog.items() if "Shape" in row.display_name)
    owner = engine.state.actors[OWNER]
    resources = {k: v for k, v in (getattr(owner, "resources", {}) or {}).items()}
    raise AssertionError("DIAG names=%r shape_rows=%r resources=%r current=%r" % (
        [n for n in names if "Dark" in n or "Shape" in n], shape_rows[:20], resources,
        engine.state.current_actor_id))
