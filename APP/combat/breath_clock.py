"""Explicit breath-holding clocks used by Athletics and environmental providers.

No clock is inferred from flavour text or a save. A caller supplies the normal
duration, Constitution modifier and source; pure breath_duration providers may
modify that duration. Persisted seconds are integers. One completed own turn
costs six seconds. Expiry removes only this clock and reports running out of
breath; it does not invent suffocation damage or immunity to inhaled effects.
"""
from . import ext

CLOCK = 'condition:typed.breath_clock'


def duration(engine, actor, normal_seconds, constitution_modifier):
    if type(normal_seconds) is not int or normal_seconds <= 0 or type(constitution_modifier) is not int:
        raise ValueError('Breath duration requires positive integer seconds and an integer Constitution modifier')
    seconds = normal_seconds
    for value in ext.run_strict('breath_duration', engine, actor, normal_seconds, constitution_modifier):
        if type(value) is not int or value <= 0:
            raise ValueError('breath_duration must return positive integer seconds or None')
        seconds = max(seconds, value)
    return seconds


def start(engine, actor, source, normal_seconds, constitution_modifier):
    seconds = duration(engine, actor, normal_seconds, constitution_modifier)
    engine._apply_condition(actor, CLOCK, source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'remaining_seconds': seconds, 'label': label(actor, seconds)})


def label(actor, seconds):
    return f'{actor.display_name} holds breath: {seconds} seconds left; ends when breathing again or time runs out.'


def stop(engine, actor, source):
    engine._remove_condition(actor, CLOCK, source)


@ext.hook('turn_end')
def elapsed_turn(engine, actor):
    for condition in list(actor.conditions.values()):
        if condition.condition_id != CLOCK:
            continue
        remaining = max(0, int(condition.data['remaining_seconds']) - 6)
        if remaining:
            engine._update_condition_data(actor, condition, {**condition.data, 'remaining_seconds': remaining,
                                                            'label': label(actor, remaining)},
                                          condition.source_definition_id)
        else:
            source = condition.source_definition_id
            stop(engine, actor, source)
            engine._append_event('PASSIVE_TRIGGERED', source, actor_id=actor.entity_id,
                payload={'log': f'{actor.display_name} runs out of held breath.', 'breath_expired': 1})
