"""TEMPORARY diagnostics #10: is the Blink Guard landing a published teleport receipt? (not for commit)"""
import json

from combat import ext
from combat import typed_executor
from combat.ext import teleport_steps
from tests.cw2_service_support import add_action
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_blink_guard_receipt(tmp_path):
    trace = []
    names = [getattr(fn, '__name__', '?') for fn in ext._HOOKS.get('committed_teleport_receipt', ())]
    trace.append(('hook_names', names))

    original_subject = typed_executor.teleport_subject
    original_reaction = teleport_steps.reaction_teleport

    def logged_subject(ctx, actor, destination, **kw):
        trace.append(('teleport_subject', id(ctx.engine), getattr(ctx, 'source', None), str(destination)))
        return original_subject(ctx, actor, destination, **kw)

    def logged_reaction(ctx, row):
        trace.append(('reaction_teleport', id(ctx.engine), dict(row)))
        return original_reaction(ctx, row)

    typed_executor.teleport_subject = logged_subject
    teleport_steps.reaction_teleport = logged_reaction

    hooks = ext._HOOKS['committed_teleport_receipt']
    for index, fn in enumerate(list(hooks)):
        if getattr(fn, '__name__', '') == 'pursuit_teleport':
            def wrapper(engine, receipt, fn=fn):
                trace.append(('receipt', id(engine), dict(receipt)))
                return fn(engine, receipt)
            hooks[index] = wrapper

    def prepare(bundles):
        add_action(bundles[0], 'Trigger attack', [{'type': 'attack', 'attack_kind': 'ranged_cultivation',
                   'count': 1, 'on_hit': []}], typed={'numbers': {'cl': 14, 'pb': 5, 'attack_bonus': 100, 'save_dc': 16}})
    combat, table, mid = fight(tmp_path, prepare=prepare,
                               foe_talents=['tianxia.talent.space.blink_guard'])
    engine, prompts = action(tmp_path, mid, 'Trigger attack', target=FOE)
    report = {'trace': [str(row) for row in trace],
              'chase': len(chase_events(engine)),
              'prompts': [p['context'].get('reaction_source_id') for p in prompts],
              'foe': engine.state.actors[FOE].position.model_dump()}
    assert False, 'DIAG ' + json.dumps(report, default=str)
