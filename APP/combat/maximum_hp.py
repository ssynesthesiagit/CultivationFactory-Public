"""Evented, independently removable Hit Point maximum adjustments.

Keys identify condition instances (or another caller-owned lifetime). Recompute
from the unmodified maximum, so overlapping reductions at the floor do not lose
their magnitude. Current HP changes are explicit; removing a penalty never heals.
This is not damage or healing and does not fire either kind of rider.

One further printed defence is read here: a creature's Immunity to Hit Point
maximum reduction (Essence Rot, CL14: "Immunity to maximum-HP reduction applies").
It is typed as an ordinary ``immunity`` effect's ``reductions`` list, so a source
that protects a creature names the channel instead of the attacker hard-coding a
creature. :func:`immune` is the one shared check; :func:`change` consults it for
every negative adjustment, so no reducer needs its own copy.
"""
from .gate2_runtime_models import MaximumHPAdjustment

REDUCTION_IMMUNITY = "max_hp_reduction_immunity"
MAX_HP_REDUCTION = "max_hp_reduction"


def immune(engine, target, channel: str = MAX_HP_REDUCTION) -> bool:
    """Whether ``target`` is immune to this kind of Hit Point maximum reduction.

    An active immunity effect protects through its ``max_hp_reduction_immunity``
    modifier (combat/typed_executor.py block_resistance); an always-on one is a
    ``maximum_hp_immunity`` passive row carrying ``reductions`` (the same shape
    combat/ext/mgr_t14_lord_of_decay.py builds for its standing clauses). A
    plug-in asks this function rather than testing either store itself.
    """
    if target is None:
        return False
    channel = str(channel).lower()
    if any(modifier.target_field == REDUCTION_IMMUNITY and str(modifier.value).lower() == channel
           for modifier in target.modifiers.values()):
        return True
    from . import typed_reactions

    return any(channel in {str(value).lower() for value in row.get("reductions") or ()}
               for row in typed_reactions._rows(engine, target.entity_id, "maximum_hp_immunity"))


def change(engine, target, key, amount, source_id, source_actor_id, *, label,
           current_delta=0, expiry_current_delta=0, current_floor=0):
    """Set a named signed adjustment; zero removes it. Returns the max-HP delta.

    Expiry policy belongs to the effect, not the engine. A current-HP floor only
    protects an already living target; expiry cannot revive a creature at zero.
    Callers reducing current HP to zero must resolve the resulting life state.
    """
    for value in (amount, current_delta, expiry_current_delta, current_floor):
        if type(value) is not int:
            raise ValueError('Hit Point adjustments require integers, not booleans')
    if not key or not source_id or not label or current_floor not in (0, 1):
        raise ValueError('Hit Point adjustment needs a key, source, label and floor of zero or one')
    previous = target.maximum_hp_adjustments.get(key)
    if amount < 0 and immune(engine, target):
        # "Immunity to maximum-HP reduction applies": the whole keyed reduction is refused, so this key's
        # recorded amount and the creature's current Hit Points are both unchanged.
        return 0
    if not amount and previous is None:
        return 0
    proposed = dict(target.maximum_hp_adjustments)
    if amount:
        entry = MaximumHPAdjustment(amount=amount, source_id=source_id, source_actor_id=source_actor_id,
                                    expiry_current_delta=expiry_current_delta,
                                    current_floor=current_floor, label=label)
        if previous == entry:
            return 0  # Reapplying the same receipt cannot heal again.
        proposed[key] = entry
    else:
        del proposed[key]
    base = target.maximum_hp_base if target.maximum_hp_base is not None else target.maximum_hp
    before, hp_before = target.maximum_hp, target.current_hp
    after = max(1, base + sum(row.amount for row in proposed.values()))
    hp_after = min(after, max(current_floor if hp_before > 0 else 0, hp_before + current_delta))
    # Assignment validation must also hold between the two writes.
    target.current_hp = min(target.current_hp, after)
    target.maximum_hp = after
    target.current_hp = hp_after
    target.maximum_hp_base = base if proposed else None
    target.maximum_hp_adjustments = proposed
    engine._append_event('MAXIMUM_HP_CHANGED', source_id, actor_id=source_actor_id,
        target_ids=(target.entity_id,), payload={
            'key': key, 'maximum_before': before, 'maximum_after': after,
            'current_before': hp_before, 'current_after': hp_after,
            'base_after': target.maximum_hp_base,
            'adjustments_after': {k: v.model_dump(mode='json') for k, v in proposed.items()},
            'log': f'{label}: {target.display_name} now has {hp_after}/{after} Hit Points.'})
    return after - before


def expire(engine, target, key):
    row = target.maximum_hp_adjustments.get(key)
    if row is not None:
        change(engine, target, key, 0, row.source_id, row.source_actor_id,
               label=f'{row.label} ends', current_delta=row.expiry_current_delta,
               current_floor=row.current_floor)


def on_event(engine, event):
    if event.event_type == 'CONDITION_REMOVED':
        for aid in event.target_ids:
            expire(engine, engine.state.actors[aid], event.payload.get('instance_id'))


def bind(engine, target, condition, amount, *, label, current_delta=0, expiry_current_delta=0, current_floor=0):
    """Attach an adjustment to an already-recorded condition's exact lifetime.

    Returns the same signed maximum-HP delta :func:`change` returns, so a caller that has to log what the condition did
    (combat/ext/maximum_hp_riders.max_hp_loss) does not have to measure the actor itself.
    """
    return change(engine, target, condition.instance_id, amount, condition.source_definition_id,
                  condition.source_actor_id, label=label, current_delta=current_delta,
                  expiry_current_delta=expiry_current_delta, current_floor=current_floor)
