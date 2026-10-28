"""TEMPORARY diagnostics #7: why the preview has no legal teleport landing (not for commit)."""
import json

from combat import ext
from combat import gate4_engine
from combat.ext import teleport_steps
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_preview_destinations(tmp_path):
    trace = []
    original_execute = gate4_engine.Gate4ControllerEngine.execute_intent

    def logged_execute(self, intent):
        actor = self.state.actors.get(intent.actor_id)
        before = len(self.events)
        result = original_execute(self, intent)
        if getattr(intent, 'source_definition_id', '') == 'action:typed.bab13d9948.flash_step':
            reach = self._effective_speed(actor)
            rows = []
            for y in range(max(0, actor.position.y - 6), min(self.grid.height, actor.position.y + 7)):
                for x in range(max(0, actor.position.x - 6), min(self.grid.width, actor.position.x + 7)):
                    cell = type(actor.position)(x=x, y=y)
                    rows.append((x, y,
                                 self.grid.distance_ft(actor.position, cell),
                                 self._line_of_sight_actor_to_cell(actor, cell),
                                 bool(self.grid.placement_legal(cell, footprint=self._footprint(actor),
                                                                occupied_cells=self._occupied_cells_except(actor.entity_id)))))
            trace.append(('flash-step', id(self), getattr(self, '_gate4_reaction_provider', None) is not None,
                          actor.position.model_dump(), reach,
                          [(e.event_type, e.source_definition_id) for e in self.events[before:]],
                          rows[:40]))
        return result

    gate4_engine.Gate4ControllerEngine.execute_intent = logged_execute
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {'trace': [str(row) for row in trace],
              'chase': len(chase_events(engine)),
              'prompts': len(prompts),
              'modes': dict(getattr(engine, 'typed_control_modes', {}) or {})}
    assert False, 'DIAG ' + json.dumps(report, default=str)
