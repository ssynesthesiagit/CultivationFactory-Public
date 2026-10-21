"""Documented forwarding seam for plug-ins that need the in-flight resolution
state or one root-side write (roll, root event, condition/object update, damage
packet, resource gain/spend, native save or actor distance).

Every function forwards to a public, documented accessor on Gate2Engine
(combat/gate2_engine.py, "Public engine seam" block); this module reads no
engine privates and uses no getattr fallback, so a missing context raises
instead of silently skipping a choice. Plug-ins reach the engine only through
these functions; tests/test_seam_engine_access.py forbids private engine access
in the subscriber files. Behaviour is identical to the engine accessors; nothing
is cached or copied.

Users: combat/ext/iron_oath.py, combat/ext/foundation_iron_oath_2.py,
combat/ext/fate_reader.py, combat/ext/protected_subjects.py (duty-timing check)
and combat/project_checks.py.

Contract per function (names mirror the engine accessors):
- active_intent(engine): the ActionIntent being resolved, or None between turns
  / outside an action.
- active_candidate(engine): the legal candidate of that intent. Only read after
  active_intent is not None; gate2 sets both together (and clears both together)
  around each accepted intent.
- active_intent_id(engine): the journal intent id bound to the in-flight
  resolution, or None.
- record_roll(engine, roll): append a RollRecord to the engine's roll history.
- append_event(engine, event_type, *a, **k): append one root event with the
  engine's normal signature (SOURCE and actor/target ids are keyword arguments).
- spend_resource(engine, actor, resource_id, amount, source_id) and
  gain_resource(engine, actor, resource_id, amount, source_id): native resource
  movement, including the reduction/allowance seams and the cap.
- roll_save(engine, target, ability, dc, source_id, extra_mode=None): native save.
- apply_condition(engine, target, condition_id, source_id, source_actor_id, *,
  expires_on, data=None): native condition pipeline.
- update_object(engine, obj, source_id, actor_id=None): evented object upsert.
- commit_damage(engine, target, amount, damage_type, source_definition_id,
  source_actor_id, intent, **kw): native damage packet commit.
- distance(engine, source, target): actual actor-to-actor table distance, feet.
- note(engine, key, default=None) / set_note(engine, key, value) /
  pop_note(engine, key, default=None): public plug-in re-entrancy/de-duplication
  note tote backed by Gate2Engine.note/set_note/pop_note.
"""


def active_intent(engine):
    return engine.active_intent()


def active_candidate(engine):
    return engine.active_candidate()


def active_intent_id(engine):
    return engine.active_intent_id()


def record_roll(engine, roll):
    engine.record_roll(roll)


def append_event(engine, event_type, *args, **kwargs):
    return engine.append_event(event_type, *args, **kwargs)


def spend_resource(engine, actor, resource_id, amount, source_id):
    engine.spend_resource(actor, resource_id, amount, source_id)


def gain_resource(engine, actor, resource_id, amount, source_id, **kwargs):
    return engine.gain_resource(actor, resource_id, amount, source_id, **kwargs)


def roll_save(engine, target, ability, dc, source_id, extra_mode=None, **kwargs):
    return engine.roll_save(target, ability, dc, source_id, extra_mode=extra_mode, **kwargs)


def apply_condition(engine, target, condition_id, source_id, source_actor_id, *,
                    expires_on=None, data=None, unavoidable=False):
    return engine.apply_condition(target, condition_id, source_id, source_actor_id,
                                  expires_on=expires_on, data=data, unavoidable=unavoidable)


def update_object(engine, obj, source_id, actor_id=None):
    return engine.update_object(obj, source_id, actor_id)


def commit_damage(engine, target, amount, damage_type, source_definition_id, source_actor_id, intent, **kwargs):
    return engine.commit_damage(target, amount, damage_type, source_definition_id, source_actor_id, intent,
                                **kwargs)


def distance(engine, source, target):
    return engine.distance_actor_to_actor(source, target)


def note(engine, key, default=None):
    return engine.note(key, default)


def set_note(engine, key, value):
    engine.set_note(key, value)


def pop_note(engine, key, default=None):
    return engine.pop_note(key, default)
