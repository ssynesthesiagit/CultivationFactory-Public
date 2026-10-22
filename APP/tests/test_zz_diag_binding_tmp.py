"""TEMP diagnostic (delete before commit)."""
from copy import deepcopy
from combat.factory_compiler import compile_character
from combat.ext.qi_subpaths_four import legal_anchor_cells
from tests.test_mgr_t14_calligraphy_cultivator_floor58 import acquired, seal_alcove, OWNER, ALLY, FOE, QI, SUBPATH
from tests.worker2_support import fixture, reload

def test_diag(tmp_path, acquired):
    owner = compile_character(deepcopy(acquired), actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=owner, seed='MGR-T14-CALLIGRAPHY',
        battlefield_transform=seal_alcove,
        positions={OWNER: {'x': 1, 'y': 0}, ALLY: {'x': 10, 'y': 10}, FOE: {'x': 0, 'y': 1}})
    engine = reload(tmp_path, mid)
    tgt = engine.state.actors[FOE].position
    cells = legal_anchor_cells(engine, tgt, 5)
    names = sorted({engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog and engine.action_catalog[c.source_definition_id].owner_id == OWNER})
    binding = [a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Character of Binding']
    raise AssertionError(f"DIAG tgt={tgt} cells={[(p.x,p.y,p.z) for p in cells]} blocked={sorted(engine.grid.blocked)[:20]} owner_names={names} binding_ids={binding} actor_pos={engine.state.actors[OWNER].position} bonus={engine.state.actors[OWNER].bonus_action_available} res={engine.state.actors[OWNER].resources}")
