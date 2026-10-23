"""Public source-owned, finite active feature overrides.

Producers declare ``feature_state`` effects in typed data; consumers (currently
Poison Touch) query override_for. Ownership never implies active state. The
ordinary condition journal and expiry clock persist activation independently
of the source action's later availability. No classes or functions are patched.
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


def active(actor, source_feature):
    """Every override an actually activated owned state publishes, or {}.

    ``source_feature`` names the record whose activation published the state
    (the action's typed source), so a consumer can tell an active state from a
    merely owned one and never reads another creature's benefit.
    """
    return next((dict(c.data.get('overrides') or {}) for c in actor.conditions.values()
                 if c.condition_id == STATE and c.source_actor_id == actor.entity_id
                 and not c.data.get('suppressed') and c.data.get('feature_id') == source_feature), {})


def override_for(actor, feature, *, source_feature=None):
    """Read an actually activated owned state, never another creature's benefit."""
    if source_feature is not None:
        return dict(active(actor, source_feature).get(feature) or {})
    return next((dict(c.data['overrides'][feature]) for c in actor.conditions.values()
                 if c.condition_id == STATE and c.source_actor_id == actor.entity_id
                 and not c.data.get('suppressed')
                 and feature in c.data.get('overrides', {})), {})
