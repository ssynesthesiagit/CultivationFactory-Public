"""Documented engine seam for plug-ins that need the in-flight action or write a root event/roll.

Users: combat/ext/iron_oath.py, combat/ext/foundation_iron_oath_2.py, combat/ext/fate_reader.py and
combat/project_checks.py. Plug-ins call these functions instead of reading engine privates or using
getattr fallbacks, so a missing context fails loudly instead of silently skipping a choice.

- active_intent(engine): the ActionIntent being resolved, or None between turns / outside an action.
- active_candidate(engine): the legal candidate of that intent. Only read after active_intent is not None;
  gate2 sets both together (and clears both together) around each accepted intent.
- record_roll(engine, roll): records a RollRecord on the engine's roll history.
- append_event(engine, event_type, *args, **kwargs): appends one root event with the engine's normal signature.

Behaviour is identical to the engine calls these wrap; nothing is cached or copied.
"""


def active_intent(engine):
    return engine._active_intent


def active_candidate(engine):
    return engine._active_candidate


def record_roll(engine, roll):
    engine._record_roll(roll)


def append_event(engine, event_type, *args, **kwargs):
    return engine._append_event(event_type, *args, **kwargs)
