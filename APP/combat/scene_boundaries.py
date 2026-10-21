"""Explicit scene boundaries for native match completion and table-authored scenes.

The serial is persisted as an evented condition. A match ends its current scene once;
campaign/table scripts can use the same producer without restarting a service.
"""
from . import ext

CLOCK = 'condition:typed.recorded_scene_clock'


def serial(engine):
    return max((int(c.data['serial']) for actor in engine.state.actors.values() for c in actor.conditions.values()
                if c.condition_id == CLOCK), default=0)


def end_scene(engine):
    current = serial(engine)
    interested = ext.run_strict('scene_ended', engine, current)
    if any(interested) or current:
        # Use the ordinary condition producer/reducer; mutating fight.rules
        # without an event would fail cold mechanical replay.
        owner = next(iter(engine.state.actors.values()))
        for actor in engine.state.actors.values():
            if any(c.condition_id == CLOCK for c in actor.conditions.values()):
                owner = actor
                engine._remove_condition(actor, CLOCK, 'system:scene_boundary')
        engine._apply_condition(owner, CLOCK, 'system:scene_boundary', owner.entity_id, expires_on='UNTIL_REMOVED',
            data={'serial': current + 1, 'label': f'Recorded scene {current + 2}'})
