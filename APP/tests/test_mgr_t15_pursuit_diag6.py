"""TEMPORARY diagnostics #6: why the preview refuses the Flash Step teleport (not for commit)."""
import json

from combat import ext
from combat import gate4_engine
from combat.technique_interception import frame
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_preview_refusal(tmp_path):
    trace = []
    original_execute = gate4_engine.Gate4ControllerEngine.execute_intent

    def logged_execute(self, intent):
        before = len(self.events)
        actor = self.state.actors.get(intent.actor_id)
        snapshot = {'provider': getattr(self, '_gate4_reaction_provider', None) is not None,
                    'actor': getattr(intent, 'actor_id', None),
                    'destination': getattr(intent, 'destination', None),
                    'movement_remaining': getattr(actor, 'movement_remaining_ft', None),
                    'speed': getattr(actor, 'speed_ft', None),
                    'frame': {k: v for k, v in (frame(self, intent.actor_id,
                                                    getattr(intent, 'source_definition_id', '') or '') or {}).items()
                              if k in ('movement_cap_ft', 'movement_used_ft', 'forced_cap_ft', 'label')}}
        result = original_execute(self, intent)
        trace.append(('execute', id(self), snapshot,
                      [(e.event_type, e.source_definition_id, e.payload.get('rider'))
                       for e in self.events[before:]]))
        return result

    gate4_engine.Gate4ControllerEngine.execute_intent = logged_execute
    hooks = ext._HOOKS['committed_teleport_receipt']
    for index, fn in enumerate(list(hooks)):
        if getattr(fn, '__name__', '') == 'pursuit_teleport':
            def wrapper(engine, receipt, fn=fn):
                trace.append(('hook-receipt', id(engine), receipt.get('source_definition_id')))
                return fn(engine, receipt)
            hooks[index] = wrapper
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {'trace': [str(row) for row in trace],
              'chase': len(chase_events(engine)),
              'live_foe_movement': engine.state.actors[FOE].movement_remaining_ft}
    assert False, 'DIAG ' + json.dumps(report, default=str)
