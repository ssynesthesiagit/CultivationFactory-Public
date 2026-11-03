"""Resonant Note's object rider, from the owner's printed Sound rules.

Objects carry caster-owned Resonance until that caster next starts a turn. The
optional object rider requires existing Resonance and exposes the object to its
next damage instance, ignoring Thunder Resistance only. Any damage actually
taken consumes it; misses and fully prevented damage do not. Immunity and other
Resistances remain effective.
All component changes use OBJECT_UPDATED snapshots, including expiry/consumption.
Shared helper consume_exposure is used by combat.ext.objects to resolve the
next object damage instance. objects._direct dispatches the explicit on-hit effect after resolving damage;
objects.deal calls consume_exposure before the next instance is calculated.

The same printed sentence's construct half is carried by the damage row's
bonus_if_kind through combat.ext.creature_kinds. This object plug-in must not
add a second creature bonus; creature and object delivery have separate owners.
"""

from . import effect, hook

KEY = "sound_resonance"
EXPOSURE = "sound_thunder_exposure"


@hook("candidate_allowed")
def exposed_object_only(engine, actor, candidate, action):
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if not any(eff.get("type") == "sound_object_resonance" and eff.get("expose")
               for attack in typed.get("effects") or [] for eff in attack.get("on_hit") or []):
        return None
    return bool(candidate.target_ids) and all(
        target in engine.state.objects and actor.entity_id in
        ((engine.state.objects[target].component or {}).get(KEY) or {})
        for target in candidate.target_ids)


@effect("sound_object_resonance")
def resonate(ctx, eff):
    obj = ctx.damage_cache.get("_object")
    if obj is None:
        return  # creature versions retain their ordinary Resonance condition
    obj = ctx.engine.state.objects[obj.object_id]
    component = dict(obj.component or {})
    marks = dict(component.get(KEY) or {})
    if eff.get("expose") and ctx.actor.entity_id in marks:
        component[EXPOSURE] = {**(component.get(EXPOSURE) or {}), ctx.actor.entity_id: True}
    marks[ctx.actor.entity_id] = True
    component[KEY] = marks
    ctx.engine._update_object(obj.model_copy(update={"component": component}), ctx.source, ctx.actor.entity_id)


def consume_exposure(engine, obj, packets):
    """Return a snapshot with the one-instance rider consumed and bypassed kinds."""
    component = dict(obj.component or {})
    if not component.get(EXPOSURE) or not any(amount > 0 for amount, _ in packets):
        return obj, ()
    component.pop(EXPOSURE)
    return obj.model_copy(update={"component": component}), ("THUNDER",)


@hook("turn_start")
def expire(engine, actor):
    for obj in list(engine.state.objects.values()):
        component = dict(obj.component or {})
        marks = dict(component.get(KEY) or {})
        changed = marks.pop(actor.entity_id, None) is not None
        if changed:
            component[KEY] = marks
        exposure = dict(component.get(EXPOSURE) or {})
        if exposure.pop(actor.entity_id, None) is not None:
            if exposure:
                component[EXPOSURE] = exposure
            else:
                component.pop(EXPOSURE)
            changed = True
        if changed:
            engine._update_object(obj.model_copy(update={"component": component}), "sound:resonance_expired", actor.entity_id)
