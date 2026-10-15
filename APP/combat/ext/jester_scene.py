"""Base Foil admission and source-scoped committed Proposition receipts.

The existing Jester provider retains mark replacement, expiry and Punchline
consumption. These observers record base fulfillment at the rule's declaration
or entered-space checkpoint; a talent's expressly later trigger stays later.
"""
from . import hook
from contextvars import ContextVar
_DISPATCH=ContextVar('jester_source_dispatch',default=None)
from .ability_source import mechanic_of
SOURCE='JESTER_BASE_SET_THE_SCENE'


def perceives(engine,target,owner):
    from ..target_knowledge import can_see
    from ..speech import can_hear_from
    return can_see(engine,target,owner) or can_hear_from(engine,owner,target)


@hook('compile_action')
def admission(action,info):
    if SOURCE in info['owned_ids'] and mechanic_of(action)==SOURCE:
        return action.model_copy(update={'target_kind':'ANY_CREATURE'})
    return None


@hook('recipient_allowed')
def legal_recipient(ctx,target):
    if mechanic_of(ctx.action)==SOURCE:return perceives(ctx.engine,target,ctx.actor)
    return None


@hook('candidate_allowed')
def legal_candidate(engine,actor,candidate,action):
    if action is None or mechanic_of(action)!=SOURCE:return None
    return None if candidate.target_ids and all(t in engine.state.actors and perceives(engine,engine.state.actors[t],actor) for t in candidate.target_ids) else False


def fulfill(engine,foil,proposition,source,*,targets=(),owner_id=None):
    from .jester import foil_mark
    from ..typed_executor import mark_condition_id
    for owner in engine.state.actors.values():
        if owner_id is not None and owner.entity_id!=owner_id:continue
        cid=mark_condition_id(foil_mark(proposition),owner.entity_id)
        for c in list(foil.conditions.values()):
            if c.condition_id!=cid :continue
            intent=getattr(engine,'_active_intent',None)
            identity=str(getattr(intent,'intent_id',''))+':'+proposition
            if c.data.get('trigger_intent')==identity:continue
            engine._update_condition_data(foil,c,{**c.data,'proposition_fulfilled':1,'trigger_source':source,
                'trigger_sequence':engine.state.event_sequence,'trigger_intent':identity,'trigger_targets':list(targets)},SOURCE)
            engine._append_event('PASSIVE_TRIGGERED',SOURCE,actor_id=owner.entity_id,target_ids=(foil.entity_id,),
                payload={'log':f'{foil.display_name} fulfills {proposition}. One compatible Punchline may answer this action.',
                    'proposition':proposition,'trigger_source':source})
            from ..typed_reactions import source_reaction_rows,resolve_source_reaction
            kinds={'Come Closer':{'enters_range'},'Ignore the Fool':{'ally_attacked'},'Show Your Hand':{'technique_used'},'Strike the Fool':{'attacked'}}[proposition]
            token=_DISPATCH.set((engine,owner.entity_id,proposition))
            try:
                for row in source_reaction_rows(engine,owner):
                    if row.get('requires_mark')!=foil_mark(proposition) or row.get('kind') not in kinds:continue
                    if not any(mark.condition_id==cid for mark in foil.conditions.values()):break
                    protected=engine.state.actors.get(next(iter(targets),'')) if proposition=='Ignore the Fool' else None
                    if resolve_source_reaction(engine,owner,foil,row,'PROPOSITION_FULFILLED',
                            trigger={'actor_id':foil.entity_id,'target_id':protected.entity_id if protected else owner.entity_id,'source_id':source,'trigger_kind':proposition},protects=protected):
                        # A Punchline ends this source's scene even if an old row
                        # omitted the explicit cleanup effect.
                        from .jester import drop_foils
                        from ..typed_reactions import generic_reaction_context
                        drop_foils(generic_reaction_context(engine,owner,foil,row,intent))
                        break
            finally:_DISPATCH.reset(token)


@hook('before_attack')
def attack(engine,actor,target,intent,spec):
    from ..typed_executor import bears_mark
    from .jester import foil_mark
    fulfill(engine,actor,'Strike the Fool',str(spec.get('source_definition_id') or getattr(engine,'_active_action_source_id','')),targets=(target.entity_id,),owner_id=target.entity_id) if bears_mark(actor,target.entity_id,foil_mark('Strike the Fool')) else None
    for owner in engine.state.actors.values():
        if owner.entity_id!=target.entity_id and perceives(engine,actor,owner) and bears_mark(actor,owner.entity_id,foil_mark('Ignore the Fool')):
            fulfill(engine,actor,'Ignore the Fool',str(spec.get('source_definition_id') or getattr(engine,'_active_action_source_id','')),targets=(target.entity_id,),owner_id=owner.entity_id)


@hook('technique_declared')
def technique(engine,actor,targets,typed,intent,action):
    from .action_source_facts import profile
    from ..effect_harm import classify_effect
    from ..typed_executor import bears_mark
    from .jester import foil_mark
    fact=profile(engine,actor,action)
    source=action.source_definition_id if action else ''
    if fact.get('action_kind')=='magic' or fact.get('supernatural')==1:fulfill(engine,actor,'Show Your Hand',source,targets=tuple(t.entity_id for t in targets))
    if any(classify_effect(row) is True for row in typed.get('effects',[])):
        for owner in engine.state.actors.values():
            if any(t.entity_id!=owner.entity_id for t in targets) and perceives(engine,actor,owner) and bears_mark(actor,owner.entity_id,foil_mark('Ignore the Fool')):
                fulfill(engine,actor,'Ignore the Fool',source,targets=tuple(t.entity_id for t in targets),owner_id=owner.entity_id)


@hook('movement_landed')
def closer(engine,mover,previous,destination,intent,forced):
    if forced:return
    from ..typed_executor import bears_mark
    from .jester import foil_mark
    for owner in engine.state.actors.values():
        if not bears_mark(mover,owner.entity_id,foil_mark('Come Closer')):continue
        before=engine.grid.distance_ft(previous,owner.position);after=engine.grid.distance_ft(destination,owner.position)
        reach=engine.opportunity_reach_ft(owner) if hasattr(engine,'opportunity_reach_ft') else 5
        if before-after>=5 or before>reach>=after:fulfill(engine,mover,'Come Closer',getattr(intent,'source_definition_id','movement'),owner_id=owner.entity_id)


@hook('state_event')
def invitation(engine,event):
    if event.event_type!='CONDITION_APPLIED' or not str(event.payload.get('condition_id','')).startswith('condition:typed.mark.foil_'):return
    from ..observer_information import publish
    owner=engine.state.actors.get(event.actor_id);foil=engine.state.actors.get(next(iter(event.target_ids),''))
    if owner and foil:publish(engine,foil,SOURCE,owner,'declaration',{'invitation':'You are invited to respond. The intended Punchline is not disclosed.'},'START_OF_SOURCE_NEXT_TURN')


@hook('reaction_consent_allowed')
def exact_proposition_phase(engine,reactor,row,checkpoint):
    mark=row.get('requires_mark')
    if not str(mark or '').startswith('Foil: ') or row.get('kind') not in ('enters_range','ally_attacked','technique_used','attacked'):return None
    current=_DISPATCH.get()
    return bool(current and current[0] is engine and current[1]==reactor.entity_id and mark=='Foil: '+current[2])
