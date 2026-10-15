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
    return [*rows, {'block': BLOCK, 'feature_id': SOURCE, 'cl': cl}]


@hook('reaction_rows')
def replace_unphased(engine, actor_id, block, rows):
    # This phase provider is the only consumer. Preserve every other row.
    return [r for r in rows if r.get('feature_id') != SOURCE]


def row(engine, actor):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == BLOCK and r.get('feature_id') == SOURCE), None)


@hook('choice_reactors')
def choosers(engine):
    # A willing recipient owns its consent and landing even off turn.
    return list(engine.state.actors) if any(row(engine, a) for a in engine.state.actors.values()) else []


@hook('attack_roll_visible')
def protect(engine, attacker, target, spec, roll, intent):
    from ..typed_executor import condition_rules
    from ..relations import relation, ALLY
    from .choice_costs import payable
    from .needle import ask, CHOICE, checkpoint_id
    from .recipient_consent import willing
    from .rider_choices import step
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        owned = row(engine, owner)
        if (owned is None or not owner.active or not owner.reaction_available
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
                   f'total {roll.total}. Before the result, spend your Reaction and 2 Qi for +3 AC '
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
        step(engine, target, 'predictive_step_landing', 'Predictive Step', attacker, 5,
             SOURCE, intent, ignored_oa=list(engine.state.actors),
             trigger=f'{attacker.display_name} has rolled an attack against {target.display_name}',
             prompt_context={'cost': 'Included in Predictive Step; no additional cost'})
        engine._append_event('REACTION_RESOLVED', SOURCE, actor_id=owner.entity_id,
            target_ids=(target.entity_id,), payload={'ac_bonus': 3, 'attack_roll_id': roll.roll_id,
                'attacker_id': attacker.entity_id, 'round': engine.state.round_number})
        return {'ac_bonus': 3, 'revalidate_target': True}
