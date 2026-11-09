"""Anchored Soul: spatial save Advantage and one optional immediate return.

Only fresh compiled passive ownership enables these readers. Spatial consequences
are read from explicit effect rows, never from a creature's name or its Sphere.
The return consumes its Full Cultivation Session allowance only on a real hop.
"""
from dataclasses import replace
from . import hook, note
from .passive_rows import row_of

SOURCE = 'insight.anchored-soul'
BLOCK = 'space_anchored_soul'
USED = 'condition:typed.anchored_soul_used'


def _spatial_save(named):
    """Printed spatial hazards, supplied explicitly by this save's context."""
    hazards = {'unwilling_spatial_transport', 'unwilling_teleportation',
               'banishment', 'forced_pocket_space', 'spatial_possession',
               'forced_planar_travel'}
    return bool(set(named or ()) & (hazards | {'category:' + name for name in hazards}))


@hook('compile_passives')
def ownership(passives, info):
    if SOURCE not in info.get('owned_ids', []):
        return passives
    return [*passives, {'block': BLOCK, 'kind':'anchored', 'feature_id':SOURCE}]


@hook('save')
def save(ctx, subject, ability, named):
    if row_of(ctx.engine, subject.entity_id, BLOCK, 'anchored') and ctx.actor.entity_id != subject.entity_id and _spatial_save(named):
        return {'modes':['ADVANTAGE']}
    return None


@hook('save_mode')
def native_save(engine, target, ability, dc, source_id, roll_context):
    if not row_of(engine, target.entity_id, BLOCK, 'anchored'):
        return None
    if roll_context.get('source_actor_id') != target.entity_id and _spatial_save(roll_context.get('named')):
        return 'ADVANTAGE'
    return None


@hook('teleport_settled')
def return_after_unwilling_teleport(ctx, subject, previous, destination, unwilling):
    from ..typed_executor import teleport_subject, condition_rules
    from .needle import ask, checkpoint_id
    engine = ctx.engine
    if not unwilling:
        return None  # only the explicit accepted transport supplies unwillingness
    if not row_of(engine, subject.entity_id, BLOCK, 'anchored') or any(c.condition_id == USED for c in subject.conditions.values()):
        return None
    if not subject.active or subject.position != destination or engine.grid.distance_ft(previous, destination) > 60:
        return None
    if any(rule.get('no_teleport') for rule in condition_rules(subject)):
        return None
    if not engine.grid.placement_legal(previous, footprint=engine._footprint(subject), occupied_cells=engine._occupied_cells_except(subject.entity_id)):
        return None
    from .choice_prompt import action_context
    chosen=ask(engine,ctx.intent,checkpoint_id(engine,'anchored_soul',subject.entity_id),subject,
        'choice:needle.anchored_soul',['return'], labels={'return':'Return to your previous space'},
        preferred=['return'],allow_decline=True,name='Anchored Soul',
        prompt=f'Anchored Soul: {subject.display_name} was teleported unwillingly. Return to its previous open space within 60 feet? This spends its one return between Full Cultivation Sessions; no Reaction or resource is needed.',
        prompt_context=action_context(engine, ctx.actor, ctx.source, subject))
    if not chosen:
        return None
    # Mark before the return so its nested settled checkpoint is inert.
    engine._apply_condition(subject,USED,SOURCE,subject.entity_id,expires_on='UNTIL_REMOVED',
        data={'label':'Anchored Soul return spent until the next Full Cultivation Session.'})
    own=replace(ctx,actor=subject,targets=[subject],target=subject)
    teleport_subject(own,subject,previous,
        settlement_source_id=SOURCE,settlement_feature_id=SOURCE)
    if subject.position != previous:
        engine._remove_condition(subject,USED,SOURCE)
    else:
        note(engine,SOURCE,subject,f'Anchored Soul: {subject.display_name} returns to its previous space.')
