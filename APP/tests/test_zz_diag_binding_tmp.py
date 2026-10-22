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
    bc = [c for c in engine.legal_candidates() if (engine.action_catalog.get(c.source_definition_id) is not None and engine.action_catalog[c.source_definition_id].display_name == 'Character of Binding')]
    from combat.ext.qi_subpaths_four import rewrite_available
    from combat.ext import subpath_acquisition as _sa
    act = [a for a in engine.action_catalog.values() if a.display_name == 'Character of Binding' and (a.parameters.get('typed') or {}).get('source','').endswith('character_of_binding')]
    a = act[0] if act else None
    fo = engine.state.actors[FOE]
    ow = engine.state.actors[OWNER]
    info = {'foe_dist': engine.grid.distance_ft(fo.position, ow.position), 'foe_cells': len(legal_anchor_cells(engine, fo.position, 5)), 'owner_cells': len(legal_anchor_cells(engine, ow.position, 5)), 'foe_alive': not getattr(fo,'dead',None), 'foe_conds': [c.condition_id for c in fo.conditions.values()], 'foe_hp': getattr(fo,'current_hp',None), 'foe_pos_cells': sorted((p.x,p.y,p.z) for p in legal_anchor_cells(engine, fo.position, 5))}
    from types import SimpleNamespace
    if a is not None:
        cand = SimpleNamespace(target_ids=(FOE,))
        info['allowed_foe'] = rewrite_available(engine, ow, cand, a)
    raise AssertionError('DIAG3 ' + repr(info) + ' bonus=' + repr(ow.bonus_action_available) + ' qi=' + repr(ow.resources.get('resource:core.qi')))
