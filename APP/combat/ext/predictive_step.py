"""Divination's Predictive Step, using the public attack and movement engines.

Compilation preserves exact acquired ownership. The sealed passive holds CL;
there are no live authority reads and no sibling feature grants.
"""
from . import hook

SOURCE = 'tianxia.subpath.qi.divination_cultivator.feature.predictive_step'
BLOCK = 'predictive_step'
QI = 'resource:core.qi'
LIMIT = '_round_predictive_step'


@hook('compile_passives')
def acquired(rows, info):
    cl = int(info['numbers'].get('cl') or 1)
    if SOURCE not in info.get('owned_ids', ()) or cl < 6:
        return rows
    return [*rows, {'block': BLOCK, 'feature_id': SOURCE, 'cl': cl, 'recipient_consent_choices': 1}]


@hook('reaction_rows')
def replace_unphased(engine, actor_id, block, rows):
    # Newly sealed access selects this phase provider. Historical catalogs
    # retain their prior reaction consumer and replay unchanged.
    actor = engine.state.actors.get(actor_id)
    if actor is None or row(engine, actor) is None:
        return rows
    return [r for r in rows if r.get('feature_id') != SOURCE]


def row(engine, actor):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == BLOCK and r.get('feature_id') == SOURCE), None)


@hook('attack_roll_visible')
def protect(engine, attacker, target, spec, roll, intent):
    from ..typed_executor import condition_rules
    from ..relations import relation, ALLY
    from .choice_costs import payable
    from .needle import ask, CHOICE, checkpoint_id
    from .recipient_consent import willing
    from .granted_movement import choose
    protected = False
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not target.active:
            break
        owned = row(engine, owner)
        if (owned is None or not owner.active or owner.life_state not in (None, 'CONSCIOUS') or not owner.reaction_available
                or owner.turn_flags.get(LIMIT) == engine.state.round_number
                or any(r.get('no_reactions') for r in condition_rules(owner))):
            continue
        if target is not owner and (owned['cl'] < 11 or relation(engine, owner, target) != ALLY
                                    or engine._distance_actor_to_actor(owner, target) > 30):
            continue
        payment = payable(owner, QI, 2)
        if payment is None:
            continue
        use = ask(engine, intent, checkpoint_id(engine, BLOCK, roll.roll_id, owner.entity_id),
            owner, CHOICE + BLOCK, ['protect'], labels={'protect': 'Protect ' + target.display_name},
            name='Predictive Step', feature_id=SOURCE, payment=payment,
            target_id=target.entity_id, allow_decline=True,
            prompt=f'{attacker.display_name} attacks {target.display_name}: visible roll {roll.natural_result}, '
                   f'total {spec.get("attack_modified_total", roll.total)}. Before the result, spend your Reaction and 2 Qi for +3 AC '
                   'against this attack and up to 5 feet of movement without Opportunity Attacks?')
        if not use:
            continue
        if not willing(engine, target, owner, SOURCE, 'Predictive Step',
                       '+3 AC against this attack and up to 5 feet of ordinary movement', intent=intent):
            continue
        payment.pay(engine, owner, SOURCE)
        owner.reaction_available = False
        owner.turn_flags[LIMIT] = engine.state.round_number
        # Every destination is a native path, with terrain/collision/hazard
        # checks. A recipient may stay put; the AC bonus still applies.
        choose(engine, target, 5, SOURCE, key='predictive_step_landing', name='Predictive Step',
               threat=attacker, intent=intent, ignored=list(engine.state.actors))
        engine._append_event('REACTION_RESOLVED', SOURCE, actor_id=owner.entity_id,
            target_ids=(target.entity_id,), payload={'ac_bonus': 3, 'attack_roll_id': roll.roll_id,
                'attacker_id': attacker.entity_id, 'round': engine.state.round_number})
        protected = True
    # The same named AC benefit applies once. Each eligible
    # owner still keeps their own legal reaction and movement choice.
    return {'ac_bonus': 3, 'revalidate_target': True} if protected else None
