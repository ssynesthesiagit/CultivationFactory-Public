"""TEMPORARY diagnostics #8: why the preview has no legal teleport landing (not for commit)."""
import json

from combat import ext
from combat.ext import teleport_steps
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_preview_destinations(tmp_path):
    trace = []
    original_destinations = teleport_steps.destinations
    original_allowed = teleport_steps.destination_allowed

    def logged_destinations(engine, actor, feet, **kw):
        cells = original_destinations(engine, actor, feet, **kw)
        trace.append(('destinations', id(engine), actor.entity_id, feet, len(cells),
                      [(c.x, c.y) for c in cells[:6]],
                      dict(getattr(actor, 'resources', {}) or {})))
        return cells

    def logged_allowed(engine, actor, cell, feet, *, where=None, action=None, occupied_cells=None, viewer=None):
        result = original_allowed(engine, actor, cell, feet, where=where, action=action,
                                  occupied_cells=occupied_cells, viewer=viewer)
        if not result and len(trace) < 40:
            from combat.gate2_runtime_models import CandidateKind
            veto = None
            if action is not None and action.target_kind == 'SELF':
                candidate = engine._candidate(CandidateKind.ACTION, actor, action.source_definition_id,
                                              action.display_name, target_ids=(actor.entity_id,),
                                              destination=cell, metadata={'teleport': True, 'expected_damage': 0})
                veto = ext.any_false('candidate_allowed', engine, actor, candidate, action)
            trace.append(('reject', id(engine), cell.x, cell.y, feet,
                          engine.grid.distance_ft(actor.position, cell),
                          engine._line_of_sight_actor_to_cell(actor, cell),
                          bool(engine.grid.placement_legal(cell, footprint=engine._footprint(actor),
                                                           occupied_cells=engine._occupied_cells_except(actor.entity_id))),
                          veto))
        return result

    teleport_steps.destinations = logged_destinations
    teleport_steps.destination_allowed = logged_allowed
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {'trace': [str(row) for row in trace],
              'chase': len(chase_events(engine)),
              'prompts': len(prompts)}
    assert False, 'DIAG ' + json.dumps(report, default=str)
