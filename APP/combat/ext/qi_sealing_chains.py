"""Chains of Qi's exact source-owned hold, authority cadence and escape action.

New qi5_chain rows opt in through condition_state. Native Restrained owns the
condition's combat rules and Concentration/finite clock. Repeat saves and
escape checks release the exact instance, preserving other casters' holds.
"""
from . import hook, effect
from .condition_ownership import remove_instance
from .passive_rows import known_level

SOURCE = 'tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi'


def holds(actor):
    return [c for c in actor.conditions.values() if c.data.get('qi5_chain')]


@hook('condition_state')
def chain_state(ctx, subject, row):
    if not row.get('qi5_chain'):
        return None
    cl=int(ctx.numbers['cl']); level=known_level(ctx.engine,subject)
    gap=cl-level if level is not None else 0
    every=0 if gap>=6 else 2 if gap>=3 else 1
    return {'data':{'qi5_chain':1,'source_cl':cl,'save_dc':int(ctx.numbers['save_dc']),
        'repeat_every':every,'first_turn':subject.turns_started-int(ctx.engine.state.current_actor_id==subject.entity_id),
        'prepared_for_sealing':True,'rule':{'no_teleport':True},'label':'Chains of Qi: Restrained; teleportation, phasing and possession blocked'}}


@hook('turn_end')
def repeated_escape(engine,actor):
    for c in holds(actor):
        cadence=int(c.data['repeat_every'])
        if not cadence or (actor.turns_started-int(c.data['first_turn']))%cadence:
            continue
        rolled=engine._roll_save(actor,'DEX',int(c.data['save_dc']),c.source_definition_id)
        if rolled and rolled.total>=int(c.data['save_dc']):
            remove_instance(engine,actor,c.instance_id,c.source_definition_id)


@hook('compile_actions')
def break_action(info):
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    # Anyone may try to escape a hold placed later in this fight.
    return [ActionDefinition(source_definition_id='action:typed.'+info['short']+'.qi5_break_chains',
        owner_id=info['actor_id'],display_name='Break Chains of Qi',economy=EconomyKind.ACTION,
        resolution_kind='TYPED',target_kind='SELF',parameters={'qi5_escape':1,'expected_damage':0,
        'typed':{'source':'system:qi5.break_chains','numbers':info['numbers'],
        'effects':[{'type':'qi5_escape_chains'}],'riders':[]}})]


@hook('candidate_allowed')
def chain_candidates(engine,actor,candidate,action):
    if action is not None and (action.parameters or {}).get('qi5_escape'):
        return bool(holds(actor))
    if not holds(actor):
        return None
    # Gate4 marks these destination candidates only for self-teleports. Keep
    # the held creature from choosing one; ally teleportation and conditional
    # teleport branches are governed by teleport_gate when the subject moves.
    if candidate.metadata.get('teleport'):
        return False
    return None


def _nothing_to_break(actor, action):
    """The refusal's player-facing words, for both an expansion and a compact-menu header.

    The hold is a native Restrained instance tagged qi5_chain, so no id or
    plain name can express "while held by Chains of Qi"; the action declares
    the requirement through the two explanation hooks instead of requires_condition.
    """
    if not (action is not None and (action.parameters or {}).get('qi5_escape')):
        return None
    return None if holds(actor) else 'You are not held by Chains of Qi; there is nothing to break.'


@hook('candidate_unavailability')
def chains_refused_reason(engine, actor, candidate, action):
    return _nothing_to_break(actor, action)


@hook('source_unavailable')
def chains_header_reason(engine, actor, action):
    """A compact-menu header for Break Chains of Qi while this creature holds no chains."""
    return _nothing_to_break(actor, action)


@hook('teleport_gate')
def chains_teleport(ctx,start,destination):
    # All explicit teleport routes still pass the shared no_teleport rule.
    return False if holds(ctx.actor) else None


@effect('qi5_escape_chains')
def escape(ctx,row):
    from .needle import ask,checkpoint_id
    held=holds(ctx.actor)
    if not held:
        return
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'QI5_ESCAPE'),ctx.actor,
        'choice:needle.qi5_escape',[c.instance_id for c in held],preferred=[held[0].instance_id],
        labels={c.instance_id:'Break the chains from '+ctx.engine.state.actors[c.source_actor_id].display_name for c in held},
        name='Break Chains of Qi',prompt='Choose one set of chains to break. Use a Strength check or Cultivation Check against its creator’s save DC; this costs your Action.')
    c=next((c for c in held if chosen and c.instance_id==chosen[0]),held[0])
    picks=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'QI5_ESCAPE_KIND'),ctx.actor,
        'choice:needle.qi5_escape_kind',['strength','cultivation'],preferred=['cultivation'],
        labels={'strength':'Strength check','cultivation':'Cultivation Check'},name='Break Chains of Qi',
        prompt=f'Choose your check against DC {c.data["save_dc"]}. Success ends these Chains of Qi.')
    from ..typed_executor import resolve_opposed_check
    owner=ctx.engine.state.actors[c.source_actor_id]
    check={'kind':'check','ability':'STR','label':'Strength check'} if picks and picks[0]=='strength' else {'kind':'cultivation'}
    result=resolve_opposed_check(ctx,owner,check,{'kind':'dc','dc':int(c.data['save_dc'])})
    if result.success:
        remove_instance(ctx.engine,ctx.actor,c.instance_id,ctx.source)


@hook('condition_attempt')
def chain_phase(ctx,subject,row):
    if holds(subject) and row.get('condition') in {'incorporeal','possessing'}:
        return False
    return None


@effect('qi5_chain_lock',harmful=True)
def short_lock(ctx,row):
    from ..typed_executor import effect_expiry
    if ctx.target:
        ctx.engine._apply_condition(ctx.target,'condition:typed.qi5_chain_lock',ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,ctx.target,condition=True),
            data={'rule':{'no_teleport':True},'label':'Chains of Qi: voluntary teleportation blocked'})
