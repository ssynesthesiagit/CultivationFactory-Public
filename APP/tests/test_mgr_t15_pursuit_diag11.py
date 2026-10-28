"""TEMPORARY diagnostics #11: the exception inside the Blink Guard landing (not for commit)."""
import json

from combat import ext
from combat import typed_executor
from tests.cw2_service_support import add_action
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_blink_guard_error(tmp_path):
    trace = []
    original_subject = typed_executor.teleport_subject
    original_committed = None
    from combat import movement_receipts
    original_committed = movement_receipts.teleport_committed

    def logged_committed(ctx, subject, previous, destination, movement_event, **kw):
        trace.append(('teleport_committed', id(ctx.engine), str(getattr(ctx, 'source', None)),
                      getattr(ctx, 'intent', None) is not None))
        try:
            return original_committed(ctx, subject, previous, destination, movement_event, **kw)
        except Exception as exc:
            trace.append(('teleport_committed-error', type(exc).__name__, str(exc)))
            raise

    def logged_subject(ctx, actor, destination, **kw):
        trace.append(('teleport_subject', id(ctx.engine), str(getattr(ctx, 'source', None)),
                      getattr(ctx, 'intent', None) is not None))
        try:
            return original_subject(ctx, actor, destination, **kw)
        except Exception as exc:
            trace.append(('teleport_subject-error', type(exc).__name__, str(exc)))
            raise

    typed_executor.teleport_subject = logged_subject
    movement_receipts.teleport_committed = logged_committed

    def prepare(bundles):
        add_action(bundles[0], 'Trigger attack', [{'type': 'attack', 'attack_kind': 'ranged_cultivation',
                   'count': 1, 'on_hit': []}], typed={'numbers': {'cl': 14, 'pb': 5, 'attack_bonus': 100, 'save_dc': 16}})
    combat, table, mid = fight(tmp_path, prepare=prepare,
                               foe_talents=['tianxia.talent.space.blink_guard'])
    engine, prompts = action(tmp_path, mid, 'Trigger attack', target=FOE)
    riders = [(e.source_definition_id, e.payload.get('rider')) for e in engine.events if e.event_type == 'GM_RIDER']
    report = {'trace': [str(row) for row in trace],
              'riders': riders,
              'chase': len(chase_events(engine)),
              'prompts': [p['context'].get('reaction_source_id') for p in prompts],
              'foe': engine.state.actors[FOE].position.model_dump()}
    assert False, 'DIAG ' + json.dumps(report, default=str)
