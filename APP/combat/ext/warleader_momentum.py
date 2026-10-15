"""Momentum acquisition and lifecycle; Warleader remains its sole gain provider."""
from . import hook, effect

SOURCE = 'WARLEADER_BASE_MOMENTUM_MARKS'
POOL = 'resource:named.momentum_mark'


@hook('compile_resources')
def acquire(info):
    if SOURCE not in info.get('owned_ids', ()) and 'tianxia.sphere.warleader' not in info.get('spheres', ()):
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=POOL, initial=0, maximum=int(info['pb']))]


@hook('state_event')
def end_combat(engine, event):
    if event.event_type != 'MATCH_ENDED':
        return
    for actor in engine.state.actors.values():
        remaining = int(actor.resources.get(POOL, 0))
        if remaining and owns_contract(engine, actor):
            engine._spend_resource(actor, POOL, remaining, SOURCE)


def clear_journey(session, actor_id, why):
    actor = session.state['actors'][actor_id]
    if not any(r.get('block') == 'momentum_contract' and r.get('feature_id') == SOURCE
               for r in actor['bundle'].get('typed_passives', ())):
        return
    amount = int(actor.get('resources', {}).get(POOL, 0))
    if amount:
        actor['resources'][POOL] = 0
        session.emit('RESOURCE_SPENT', actor_id, source=SOURCE, resource_id=POOL, amount=amount,
                     text=f"{actor['name']} loses all Momentum Marks {why}.")


@hook('journey_rest')
def long_rest(session, actor_id):
    clear_journey(session, actor_id, 'after a Long Rest')


@hook('journey_rest_completed')
def short_rest(session, actor_id, kind):
    clear_journey(session, actor_id, 'after a Short Rest' if kind == 'short' else 'after a Long Rest')


@hook('journey_state_changed')
def incapacitated(session, actor_id):
    if session.state['actors'][actor_id]['incapacitated']:
        clear_journey(session, actor_id, 'on becoming Incapacitated')


@hook('help_actions_enabled')
def help_menu(engine):
    return any(owns_contract(engine, actor) for actor in engine.state.actors.values())


@hook('help_delivered')
def help_gain(engine, helper, recipient, source, kind):
    from .warleader import leaders, commanded, gain_momentum
    if helper is recipient:
        return
    for leader, data in leaders(engine):
        if owns_contract(engine, leader) and commanded(engine, leader, data, helper) and commanded(engine, leader, data, recipient):
            gain_momentum(engine, leader, helper, 'helped another Commanded ally')


@hook('compile_passives')
def seal_contract(rows, info):
    if SOURCE in info.get('owned_ids', ()) or 'tianxia.sphere.warleader' in info.get('spheres', ()):
        return [*rows, {'block': 'momentum_contract', 'feature_id': SOURCE}]
    return rows


def owns_contract(engine, actor):
    return any(r.get('block') == 'momentum_contract' and r.get('feature_id') == SOURCE
               for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))


@hook('compile_actions')
def identify_action(info):
    if not any(r.get('block') == 'momentum_contract' for r in info.get('passives', ())):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id='action:typed.' + info['short'] + '.warleader_objective',
        display_name='Identify an objective', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='ANY_CREATURE', parameters={'expected_damage': 0,
            'description': 'Identify one creature as your objective by voice or a visible signal. No Action or resource cost. A Commanded ally hitting it can build Momentum.',
            'typed': {'effects': [{'type': 'warleader_identify_objective'}], 'numbers': {}, 'riders': [], 'duration': {'kind': 'instant'}}})]


@effect('warleader_identify_objective')
def identify(ctx, effect):
    from .needle import ask, checkpoint_id, CHOICE
    from ..speech import silenced
    from ..senses import perceives
    from ..fact_consent_admission import admit_choice, digest
    if not owns_contract(ctx.engine, ctx.actor) or ctx.target is None:
        return
    # A declaration identifies an actually perceived creature. Choosing a mode
    # is controller-owned input; voice/visual eligibility is mechanical.
    if not perceives(ctx.engine, ctx.actor, ctx.target):
        return
    modes = ['visible'] + ([] if silenced(ctx.actor) else ['verbal'])
    receipt = admit_choice(ctx, ctx.actor, SOURCE, 'objective', digest({
        'intent': ctx.intent.intent_id, 'target': ctx.target.entity_id}), modes,
        labels={'visible': 'Identify ' + ctx.target.display_name + ' with a visible signal',
                'verbal': 'Name ' + ctx.target.display_name + ' aloud as the objective'},
        prompt='How do you identify your objective? No Action or resource cost.',
        expires_on='UNTIL_REMOVED', readers=list(ctx.engine.state.actors), automatic_options=modes[:1])
    if receipt is None:
        return
    ctx.engine._remove_condition(ctx.actor, 'condition:typed.warleader_objective', SOURCE)
    ctx.engine._apply_condition(ctx.actor, 'condition:typed.warleader_objective', SOURCE, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'target': ctx.target.entity_id, 'mode': receipt['value'],
            'receipt_id': receipt['receipt_id'], 'label': 'Objective: ' + ctx.target.display_name})


@hook('after_hit')
def identified_hit(ctx, target, kind):
    from .warleader import leaders, commanded, gain_momentum
    for leader, data in leaders(ctx.engine):
        if not owns_contract(ctx.engine, leader) or not commanded(ctx.engine, leader, data, ctx.actor):
            continue
        if any(c.condition_id == 'condition:typed.warleader_objective' and c.source_definition_id == SOURCE
               and c.data.get('target') == target.entity_id for c in leader.conditions.values()):
            gain_momentum(ctx.engine, leader, ctx.actor, 'hit the identified objective, ' + target.display_name)
