"""Public source-owned, finite active feature overrides.

Producers declare ``feature_state`` effects in typed data; consumers (currently
Poison Touch) query override_for. Ownership never implies active state. The
ordinary condition journal and expiry clock persist activation independently
of the source action's later availability. No classes or functions are patched.

Shared helper: Poison Touch (mgr_t14_poison_touch) imports override_for to read
the active state its Decaying Presence override writes; any other plug-in that
declares a feature_state effect uses the same public reader.
"""
from . import effect

STATE = 'condition:typed.active_feature_state'


@effect('feature_state')
def activate(ctx, row):
    from ..typed_executor import effect_expiry
    from .condition_ownership import remove_instance
    # Explicit keys and integer values only: no executable objects in saves.
    overrides = row.get('overrides') or {}
    if any(not isinstance(k, str) or not isinstance(v, dict)
           or any(not isinstance(n, str) or type(value) is not int or value < 0 for n, value in v.items())
           for k, v in overrides.items()):
        raise ValueError('feature_state requires feature ids and nonnegative integer overrides')
    expires = effect_expiry(ctx, row, ctx.actor, condition=True)
    if not expires:
        raise ValueError('feature_state requires an explicit duration')
    for old in list(ctx.actor.conditions.values()):
        if old.condition_id == STATE and old.source_definition_id == ctx.source and old.source_actor_id == ctx.actor.entity_id:
            remove_instance(ctx.engine, ctx.actor, old.instance_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
        expires_on=expires, data={'overrides': overrides,
            'feature_id': str(ctx.typed.get('option_of') or ctx.typed.get('source') or ''),
            'label': str(row.get('label') or ctx.action.display_name)})


def overrides_for(actor, *, source_feature=None):
    """The whole override map of one actually activated source-owned state.

    Shared reader: ``override_for`` below returns one feature's slice, while a
    consumer that owns several dependent features reads them from one active
    state (Poison Touch and Lord of Decay's Decaying Presence overrides). Only
    the activated state's own owner reads it, never another creature's benefit.
    """
    return next((dict(c.data['overrides']) for c in actor.conditions.values()
                 if c.condition_id == STATE and c.source_actor_id == actor.entity_id
                 and not c.data.get('suppressed')
                 and (source_feature is None or c.data.get('feature_id') == source_feature)), {})


def override_for(actor, feature, *, source_feature=None):
    """Read one feature's overrides from an actually activated owned state."""
    return dict(overrides_for(actor, source_feature=source_feature).get(feature) or {})
