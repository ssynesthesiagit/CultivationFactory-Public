"""TEMPORARY diagnostics #5: trace the Pursuit teleport dispatch (not for commit)."""
import json

from combat import ext
import combat.typed_reactions as tr
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events

PURSUIT = 'tianxia.subpath.body.sky_treading_tendon_school.feature.pursuit_without_horizon'


def _wrap(name, fn, trace):
    def inner(*args, **kwargs):
        result = fn(*args, **kwargs)
        row = next((a for a in args if isinstance(a, dict) and a.get('feature_id') == PURSUIT), None)
        if row is not None:
            trace.append((name, row.get('kind'), result))
        return result
    return inner


def test_diag_trace_flash_step(tmp_path):
    trace = []
    for name in ('_can_trigger', '_generic_affordable', '_generic_in_range', '_subject_ok', '_consent'):
        setattr(tr, name, _wrap(name, getattr(tr, name), trace))
    ordered = tr._ordered_generic_rows

    def logged_rows(engine, actor_id, kind, other=None):
        rows = ordered(engine, actor_id, kind, other)
        if kind == 'sky_pursuit_teleport':
            trace.append(('rows', kind, [(r.get('feature_id'), r.get('kind')) for r in rows]))
        return rows
    tr._ordered_generic_rows = logged_rows
    hooks = ext._HOOKS['committed_teleport_receipt']
    for index, fn in enumerate(list(hooks)):
        if getattr(fn, '__name__', '') == 'pursuit_teleport':
            def wrapper(engine, receipt, fn=fn):
                trace.append(('hook-receipt', receipt.get('source_definition_id'), receipt.get('willing')))
                result = fn(engine, receipt)
                trace.append(('hook-after', receipt.get('source_definition_id'), None))
                return result
            hooks[index] = wrapper
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {'trace': [str(row) for row in trace],
              'chase': len(chase_events(engine)),
              'prompts': [p['context']['reaction_source_id'] for p in prompts]}
    assert False, 'DIAG ' + json.dumps(report, default=str)
