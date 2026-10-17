"""Cloud Immortal and Liquid Body's creature-space clauses.

This marker is deliberately separate from other C6 features: only passage and
the printed Opportunity Attack protection live here. Walls/openings and lasting
shared occupancy remain separate rules. The timed marker is applied by typed data.
"""
from . import effect, hook

MARK = 'condition:typed.creature_passage'


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
