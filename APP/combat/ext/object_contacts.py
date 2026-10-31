"""Source-requested native contact with actual unattended physical objects.

The source supplies eligible identities, never a receipt. Native geometry,
visibility and the shared free-interaction/Utilize budget validate the touch.
Glass Faultline Marks consumes the committed contact. No provider is inert.
"""
from . import hook, run_strict

PREFIX = 'system:combat.touch_object.'


def eligible(engine, actor):
    from ..asset_anchor_runtime import touches_object
    from ..object_rules import solid_surface
    from ..senses import perceives_object
    from .needle import incapacitated
    if not actor.active or incapacitated(actor):
        return []
    identities = set()
    for answer in run_strict('touchable_objects', engine, actor):
        if not isinstance(answer, (tuple, list)) or any(type(value) is not str for value in answer):
            raise ValueError('touchable_objects returns a list of actual object identities.')
        identities.update(answer)
    return [obj for identity in sorted(identities)
        if (obj := engine.state.objects.get(identity)) is not None
        and obj.unattended and not obj.destroyed and solid_surface(obj) is True
        and perceives_object(engine, actor, obj) and touches_object(engine, actor, obj)]


@hook('match_start')
def install(engine):
    replies = run_strict('object_contact_tracking', engine)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('object_contact_tracking returns bool or None.')
    if not any(replies):
        return
    from ..gate2_runtime_models import ActionDefinition
    for payment in ('free', 'utilize'):
        source = PREFIX + payment
        cost = 'free object interaction' if payment == 'free' else 'Utilize Action'
        engine.action_catalog[source] = ActionDefinition(source_definition_id=source,
            display_name=f'Touch an unattended surface ({cost})', owner_id='*',
            economy='NONE' if payment == 'free' else 'ACTION', resolution_kind='TYPED',
            target_kind='OBJECT', range_ft=5,
            parameters={'free_primary': payment == 'free', 'object_contact_payment': payment,
                'description': f'Touch one visible unattended solid surface within 5 feet using your {cost}. '
                    'This does not damage, move, activate or use the object.',
                'typed': {'effects': [], 'numbers': {}, 'riders': []}})


@hook('additional_actions')
def actions(engine, actor):
    from ..object_interaction import used
    source = PREFIX + ('utilize' if used(actor) else 'free')
    return [source] if source in engine.action_catalog and eligible(engine, actor) else []


@hook('object_targets')
def targets(engine, actor, action):
    if action.source_definition_id.startswith(PREFIX):
        return [obj.object_id for obj in eligible(engine, actor)]


@hook('candidate_allowed')
def allowed(engine, actor, candidate, action):
    if action is None or not action.source_definition_id.startswith(PREFIX):
        return None
    from ..object_interaction import used
    return ((action.parameters['object_contact_payment'] == 'utilize') == used(actor)
        and candidate.target_ids in [(obj.object_id,) for obj in eligible(engine, actor)])


@hook('object_action')
def touch(engine, actor, action, obj, candidate, intent):
    if not action.source_definition_id.startswith(PREFIX):
        return None
    from ..object_interaction import claim
    from ..object_rules import label
    if obj not in eligible(engine, actor):
        raise ValueError('Choose a visible, reachable unattended solid surface.')
    if action.parameters['object_contact_payment'] == 'free':
        claim(engine, actor, action.source_definition_id)
    engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id,
        actor_id=actor.entity_id, target_ids=(obj.object_id,), payload={
            'checkpoint': 'OBJECT_CONTACT_COMMITTED', 'object_id': obj.object_id,
            'position': actor.position.model_dump(mode='json'),
            'log': f'{actor.display_name} touches {label(obj)}.'})
    run_strict('object_contact_committed', engine, actor, obj, action.source_definition_id, intent)
    return True
