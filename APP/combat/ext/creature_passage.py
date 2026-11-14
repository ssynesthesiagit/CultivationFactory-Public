"""Cloud Immortal and Liquid Body's creature-space clauses.

This marker is deliberately separate from other C6 features: only passage and
the printed Opportunity Attack protection live here. Walls/openings and lasting
shared occupancy remain separate rules. The timed marker is applied by typed data.
"""
from . import effect, hook

MARK = 'condition:typed.creature_passage'
NAMED = 'condition:typed.named_creature_passage'


def grant_named(ctx, target):
    """Grant one difficult-terrain crossing of this creature this turn."""
    from .rider_support import remove_instance
    for c in list(ctx.actor.conditions.values()):
        if c.condition_id == NAMED and c.data.get('target_id') == target.entity_id:
            remove_instance(ctx.engine, ctx.actor, c.instance_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, NAMED, ctx.source, ctx.actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'target_id': target.entity_id, 'entered': 0,
            'label': f'Cross {target.display_name} once this turn; its space costs double movement. Stop in a free space.'})


def named_permission(engine, mover, occupant):
    c = next((c for c in mover.conditions.values() if c.condition_id == NAMED
              and c.data.get('target_id') == occupant.entity_id), None)
    if c is not None and (not c.data.get('entered') or
            set(engine._actor_volume(mover)) & set(engine._actor_volume(occupant))):
        return c
    return None


@hook('pass_through')
def named_through(engine, mover, occupant):
    return 'difficult' if named_permission(engine, mover, occupant) is not None else None


@hook('pass_through_entered')
def named_entered(engine, mover, occupant, intent):
    c = named_permission(engine, mover, occupant)
    if c is None or c.data.get('entered'):
        return
    c.data['entered'] = 1
    engine._append_event('CONDITION_APPLIED', c.source_definition_id, actor_id=mover.entity_id,
        target_ids=(mover.entity_id,), payload={'condition_id': NAMED, 'instance_id': c.instance_id,
            'source_actor_id': c.source_actor_id, 'expires_on': c.expires_on, 'data': dict(c.data)})


@effect('creature_passage')
def start(ctx, row):
    from ..typed_executor import effect_expiry
    ctx.engine._apply_condition(ctx.actor, MARK, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.actor, condition=True),
        data={'label': 'Pass through creatures and stop in a free square. Passing through a creature costs twice the movement unless you ignore difficult terrain.',
              'mode': 'difficult', 'no_oa': row.get('no_oa', 'crossed')})


@hook('pass_through')
def through(engine, mover, occupant):
    return next((c.data['mode'] for c in mover.conditions.values() if c.condition_id == MARK), None)


@hook('opportunity_allowed')
def protection(engine, reactor, mover):
    for condition in mover.conditions.values():
        if condition.condition_id != MARK:
            continue
        if condition.data['no_oa'] == 'all' or reactor.entity_id in condition.data.get('crossed', []):
            return False
    return None


@hook('pass_through_entered')
def remember_crossing(engine, mover, occupant, intent):
    for instance_id, condition in mover.conditions.items():
        if condition.condition_id != MARK or condition.data['no_oa'] != 'crossed':
            continue
        crossed = sorted(set(condition.data.get('crossed', [])) | {occupant.entity_id})
        condition.data['crossed'] = crossed
        engine._append_event('CONDITION_APPLIED', condition.source_definition_id, actor_id=mover.entity_id,
            target_ids=(mover.entity_id,), payload={'condition_id': MARK, 'instance_id': instance_id,
                'expires_on': condition.expires_on, 'crossed': crossed,
                'log': f'{mover.display_name} passes through {occupant.display_name}; that creature cannot make an Opportunity Attack against this Liquid Body.'})
