"""TEMPORARY diagnostics #2 for the Pursuit teleport trigger (not for commit)."""
import json

from combat import ext
from combat.ext.sky_treading import PURSUIT
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, cold, action, move, chase_events


def test_diag_rows(tmp_path):
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {}
    report['subscribers'] = [(getattr(f, '__module__', '?'), getattr(f, '__name__', '?'))
                              for f in ext.subscribers('reaction_rows')]
    from combat.typed_reactions import _rows, _generic_rows, _ordered_generic_rows
    base = _rows(engine, OWNER, 'generic')
    report['base_kinds'] = [(r.get('kind'), r.get('feature_id')) for r in base]
    report['ordered_generic_rows'] = [(r.get('kind'), r.get('feature_id'))
                                      for r in _ordered_generic_rows(engine, OWNER, 'sky_pursuit_teleport')]
    from combat.ext.sky_treading import pursuit_teleport_row
    direct = pursuit_teleport_row(engine, OWNER, 'generic', base)
    report['direct_hook'] = None if direct is None else [(r.get('kind'), r.get('feature_id')) for r in direct]
    results = ext.run_strict('reaction_rows', engine, OWNER, 'generic', base)
    report['run_strict'] = [None if r is None else [(x.get('kind'), x.get('feature_id')) for x in r] for r in results]
    report['generic_moved'] = [(r.get('kind'), r.get('feature_id')) for r in _generic_rows(engine, OWNER, 'moved')]
    report['generic_teleport'] = [(r.get('kind'), r.get('feature_id'))
                                   for r in _generic_rows(engine, OWNER, 'sky_pursuit_teleport')]
    report['chase'] = len(chase_events(engine))
    assert False, 'DIAG ' + json.dumps(report, default=str)
