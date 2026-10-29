"""Jester's outcome reactions, through documented event/miss/final-save hooks.

New reviewed packets own this dispatch. Generic copies are withheld to prevent
approximate legacy triggers from firing first. Costs, choices and limits still
use the standard reaction machinery. Every d20 receipt is bound to its roller.
"""
from . import hook
T='tianxia.talent.jester.'
COURT=T+'the_whole_court_laughs'
STEP=T+'dongfang_shuo_s_court_hermit_step'


def owned_row(engine, actor, feature):
    from .. import typed_reactions as tr
    for r in tr._rows(engine,actor.entity_id,'generic'):
        if r.get('feature_id')!=feature: continue
        effects=r.get('effects') or []
        stamped=(any(e.get('type')=='jester_passage_move' for e in effects) if feature==STEP else
            any(e.get('check_penalty') for save in effects for branch in ('on_fail','on_success') for e in save.get(branch) or []))
        if stamped:return r
    return None


@hook('row_allowed')
def owned_dispatch(engine, actor, row):
    if row.get('_jester_dispatch'):return None
    feature=row.get('feature_id')
    if feature in {COURT,STEP} and owned_row(engine,actor,feature):return False
    return None


def foil(engine, owner, other):
    from ..typed_executor import bears_mark
    from .jester import PROPOSITIONS, foil_mark
    return bears_mark(other,owner.entity_id,'Foil') or any(bears_mark(other,owner.entity_id,foil_mark(p)) for p in PROPOSITIONS)


def action_trigger(engine, actor_id, affected_id, source_id=None, action_name=None):
    """Describe the real action which produced this outcome receipt."""
    source=str(source_id or '')
    action=engine.action_catalog.get(source)
    return {'actor_id':actor_id,'action_actor_id':actor_id,'target_id':affected_id,'affected_id':affected_id,
            'source_id':source,'source_definition_id':source,
            'action_name':str(action_name or (action.display_name if action else ''))}


def offer(engine, actor, subject, feature, receipt, trigger=None):
    from .. import typed_reactions as tr
    row=owned_row(engine,actor,feature)
    if row is None or subject is None or not subject.active or not actor.active:return
    row={**row,'_jester_dispatch':True}
    if feature==COURT:
        from . import ai_controlled
        from ..target_knowledge import located
        if ai_controlled(engine,actor) and not located(engine,actor,subject):return
        if not foil(engine,actor,subject):return
        # Marks expire normally; ownership and perception are never guessed.
        row.pop('requires_mark',None)
    flag='jester_outcome_seen:'+feature+':'+str(receipt)
    if actor.turn_flags.get(flag):return
    if not tr._can_trigger(engine,actor,row) or not tr._generic_affordable(engine,actor,row):return
    if not tr._generic_in_range(engine,actor,subject,row) or not tr._subject_ok(engine,actor,subject,row):return
    intent=getattr(engine,'_active_intent',None)
    accepted=tr._consent(engine,row,actor,'JESTER_OUTCOME',trigger=trigger or {
        'actor_id':subject.entity_id,'target_id':actor.entity_id,'action_name':row.get('name')})
    actor.turn_flags[flag]=1
    if not accepted:return
    with tr._reaction_activation(engine,actor,subject,row) as permitted:
        if not permitted:return
        tr._open(engine,row,actor,(subject.entity_id,),'JESTER_OUTCOME')
        if not tr._spend_generic(engine,actor,row):return
        tr.spend_reaction(engine,actor,row)
        tr._run_generic_effects(engine,actor,subject,row,row['effects'],intent)
        engine._append_event('REACTION_RESOLVED',feature,actor_id=actor.entity_id,target_ids=(subject.entity_id,),
            payload={'checkpoint':'JESTER_OUTCOME'})


@hook('after_miss')
def missed(ctx, target):
    from ..attack_outcomes import attack_outcome
    # Native notices and typed results both settle here, after actual hit defenses.
    current=(ctx.attack_result or {}).get('roll_id') if ctx.attack_notice is None else ctx.attack_notice.roll_id
    receipt=current or 'miss:'+str(ctx.engine.state.event_sequence)
    trigger={'actor_id':ctx.actor.entity_id,'action_actor_id':ctx.actor.entity_id,'target_id':ctx.actor.entity_id,
             'affected_id':ctx.actor.entity_id,'source_id':ctx.source,'source_definition_id':ctx.source,
             'action_name':getattr(ctx.action,'display_name','')}
    offer(ctx.engine,target,ctx.actor,STEP,receipt,trigger)
    if not current:return  # concealment misses are attacks, but not d20 Tests
    found=None
    for i in range(len(ctx.engine.events)-1,-1,-1):
        ev=ctx.engine.events[i]
        if ev.event_type=='INTENT_ACCEPTED':break
        if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==ctx.actor.entity_id and target.entity_id in ev.target_ids and ev.source_definition_id==ctx.source and ev.payload.get('roll_id')==current:
            found=(i,ev);break
    receipt=current
    if found:
        i,ev=found;data=ev.payload
        outcome=attack_outcome(ctx.engine,ctx.actor.entity_id,i)
        ac=int((outcome or {}).get('armor_class',data.get('target_ac') or 0))
        total=int(data.get('modified_total',data.get('total') or 0))
        for correction in ctx.engine.events[found[0]+1:]:
            payload=correction.payload or {}
            if correction.event_type=='PASSIVE_TRIGGERED' and payload.get('attack_correction') and payload.get('roll_id')==current:
                total=int(payload.get('modified_total',total))
        if data.get('natural_result')==1 or ac-total>=5:
            for owner in list(ctx.engine.state.actors.values()):offer(ctx.engine,owner,ctx.actor,COURT,receipt,trigger)


@hook('save_final')
def final_save(ctx, subject, ability, named, failed):
    roll=ctx.save_result
    receipt=roll.roll_id if roll is not None else 'automatic_save:'+str(ctx.engine.state.event_sequence)
    trigger=action_trigger(ctx.engine,ctx.actor.entity_id,subject.entity_id,ctx.source,
                           getattr(ctx.action,'display_name',''))
    if not failed:
        from ..effect_harm import classify_effect
        packet=ctx.save_effect
        effects=([*(packet.get('on_fail') or []),*(packet.get('on_success') or [])] if packet else ctx.typed.get('effects') or [])
        if any(classify_effect(e) is True for e in effects):offer(ctx.engine,subject,ctx.actor,STEP,receipt,trigger)
    if roll is None:return  # Whole Court needs a genuine d20 Test
    if roll.natural_result==1 or (failed and str(ctx.typed.get('source') or ctx.source).startswith(T) and ctx.save_dc is not None and
            ctx.save_dc-int(roll.total)>=5):
        for owner in list(ctx.engine.state.actors.values()):
            if roll.natural_result==1 or owner.entity_id==ctx.actor.entity_id:offer(ctx.engine,owner,subject,COURT,receipt,trigger)


@hook('event',nested=True)
def tests_and_punchlines(engine, event_type, kwargs):
    from ..typed_executor import active_save_pending
    from .roll_context import check_receipts
    if event_type=='CHECK_ROLLED':
        receipts=check_receipts(kwargs)
        payload=kwargs.get('payload') or {}
        # Death saves and opposed save sides use the check transport, while
        # retaining their real SAVE reason. They are also printed d20 Tests.
        for data in (payload.get('actor') or payload.get('roll') or payload,payload.get('target')):
            if isinstance(data,dict) and str(data.get('reason') or '').startswith('SAVE:') and data.get('actor_id') and type(data.get('natural_result')) is int:
                receipts.append((data['actor_id'],data))
        for aid,data in receipts:
            if data.get('natural_result')==1:
                for owner in list(engine.state.actors.values()):
                    offer(engine,owner,engine.state.actors.get(aid),COURT,data.get('roll_id'),
                          action_trigger(engine,aid,aid,kwargs.get('source_definition_id'),data.get('action_name')))
    elif event_type=='SAVE_ROLLED' and not active_save_pending(engine,kwargs.get('source_definition_id'),kwargs.get('actor_id')):
        subject=engine.state.actors.get(kwargs.get('actor_id'));data=kwargs.get('payload') or {}
        if data.get('natural_result')==1:
            frame=engine.d20_context() or {}
            action_actor=frame.get('source_actor_id') or kwargs.get('actor_id')
            for owner in list(engine.state.actors.values()):offer(engine,owner,subject,COURT,data.get('roll_id'),
                action_trigger(engine,action_actor,kwargs.get('actor_id'),kwargs.get('source_definition_id')))
        if data.get('success'):
            frame=engine.d20_context() or {}
            action=engine.action_catalog.get(kwargs.get('source_definition_id'))
            from ..effect_harm import classify_effect
            harmful=action is not None and (action.target_kind=='HOSTILE_ENTITY' or any(
                classify_effect(e) is True for e in ((action.parameters or {}).get('typed') or {}).get('effects') or []))
            harmful=harmful or bool(set(frame.get('named') or []) & {'damaging_save','prone','charmed','frightened','grappled','restrained'})
            if harmful:
                source_actor=engine.state.actors.get(frame.get('source_actor_id')) or subject
                source_id=kwargs.get('source_definition_id')
                offer(engine,subject,source_actor,STEP,data.get('roll_id'),
                      action_trigger(engine,source_actor.entity_id,subject.entity_id,source_id))
    elif event_type=='REACTION_RESOLVED':
        source=kwargs.get('source_definition_id') or '';event=next(e for e in reversed(engine.events) if e.event_type==event_type and e.source_definition_id==source and e.actor_id==kwargs.get('actor_id'))
        if source==STEP or not source.startswith(T):return
        actor=engine.state.actors.get(kwargs.get('actor_id'))
        from .. import typed_reactions as tr
        punchline=source in {T+'fine_display',T+'a_fine_display',T+'banquet_escape'} or any(
            r.get('feature_id')==source and str(r.get('requires_mark') or '').startswith('Foil:') for r in tr._rows(engine,actor.entity_id,'generic')) if actor else False
        if punchline:
            subject=next((engine.state.actors.get(a) for a in kwargs.get('target_ids') or () if a in engine.state.actors),actor)
            source_id=event.source_definition_id
            offer(engine,actor,subject,STEP,'punchline:'+str(event.sequence),
                  action_trigger(engine,actor.entity_id,subject.entity_id,source_id))
