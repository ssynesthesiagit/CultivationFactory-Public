"""Weight-Seeking Clod: native object targets and legal Body origins.

Creature attacks, damage dice, hit rules and Burden Marks retain their existing
single provider. The object attack uses the public typed object contract; a hit
adds an owner-qualified mark to that real object. Body origins are selected
from actual body/equipment/contact, with optional explicit GM connection policy.
"""
from copy import deepcopy
from . import hook, effect
from . import needle
SOURCE = 'EARTH_BASE_WEIGHT_SEEKING_CLOD'


@hook('compile_action')
def clod(action, info):
    parameters = action.parameters or {}; typed = parameters.get('typed') or {}
    if typed.get('source') != SOURCE or SOURCE not in info['owned_ids']:
        return None
    typed = deepcopy(typed)
    for row in typed.get('effects', ()):
        if row.get('type') == 'attack':
            row.update(object_target='any', object_on_hit_effects=['earth_object_mark'])
            row['on_hit'].append({'type': 'earth_object_mark'})
    paths = (info['owner_sheet'].get('path_and_subpath') or {}).get('path_record_ids') or []
    typed['earth_body_contact'] = int('tianxia.path.body_refining' in paths)
    if typed['earth_body_contact']:
        typed['effects'].insert(0, {'type': 'earth_body_origin'})
        # Object resolution runs the same preparation before its native roll.
        for row in typed['effects']:
            if row.get('type') == 'attack': row['object_before_effects'] = ['earth_body_origin']
    return action.model_copy(update={'parameters': {**parameters, 'typed': typed}})


def connected_target(engine, actor, target):
    from .surface_contact import connected_contact
    return connected_contact(engine, actor, target)


@hook('candidate_allowed')
def contact_gate(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if typed.get('source') != SOURCE or not typed.get('earth_body_contact'):
        return None
    from .physical_source_facts import facts, projected
    if projected(engine, actor.entity_id, SOURCE):
        return None
    if not facts(engine, actor.entity_id).get('earth_connection_required'):
        return None
    for tid in candidate.target_ids:
        target = engine.state.actors.get(tid)
        if target is None and tid in engine.state.objects:
            target = actor.model_copy(update={'entity_id': 'probe:clod_object', 'position': engine.state.objects[tid].position, 'size_category': 'Medium', 'conditions': {}})
        if target is None or not connected_target(engine, actor, target): return False
    return None


@effect('earth_body_origin', harmful=False)
def origin(ctx, row):
    from .glass_surfaces import choices
    options = choices(ctx.engine, ctx.actor)
    selected = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'earth_origin', ctx.source),
        ctx.actor, 'choice:needle.earth_origin', list(options), preferred=['body'],
        labels={k: v['label'] for k,v in options.items()}, name='Weight-Seeking Clod',
        prompt='Weight-Seeking Clod: choose your body, worn or held equipment, or a solid surface you touch as the attack’s origin. An Action, no Cultivation Point cost. The GM’s recorded connected-surface requirement still applies.')
    if selected:
        ctx.rider('Weight-Seeking Clod originates from ' + options[selected[0]]['label'] + '.')


@effect('earth_object_mark')
def mark(ctx, row):
    obj = ctx.damage_cache.get('_object')
    if obj is None:
        return  # ordinary creature on-hit mark already owns its one mark
    from .object_marks import add
    from ..typed_executor import mark_capacity
    add(ctx, ctx.engine.state.objects[obj.object_id], 'Burden Mark', mark_capacity(ctx, 'Burden Mark'))
