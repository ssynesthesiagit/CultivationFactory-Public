"""Ingrain's minor toxin is one native source with separately consumable parts.

The failed save, not a fixture flag, creates it. Native next-save/check/healing
and holder-turn consumers retain that source's DC for Medicine/Alchemy/Life/
Poison/purification treatment. Long Rest ends every remaining component.
"""
from copy import deepcopy
from . import hook, effect
ID='POISON_BASE_INGRAIN_THE_TOXIN'
TOXIN='condition:typed.minor_ingrained_toxin'
DASH='condition:typed.minor_ingrained_heavy_pulse'
OPTIONS=['Bitter Breath','Numb Channels','Sour Blood','Clouded Senses','Heavy Pulse']

@hook('compile_action')
def seal_ingrain(action,info):
    params=deepcopy(action.parameters or {}); typed=params.get('typed') or {}
    if ID not in (typed.get('source'),typed.get('option_of')):
        return None
    preferred=next((s for s in OPTIONS if s in action.display_name),OPTIONS[0])
    typed['manual_inline_choice']=True
    sheet=info.get('owner_sheet') or {}; path=sheet.get('path_and_subpath') or {}; identity=sheet.get('identity') or {}
    paths=set(identity.get('path_ids') or ()) | set(path.get('path_record_ids') or ())
    if path.get('path_record_id'):paths.add(path['path_record_id'])
    # Payment selects a variant only after the build has actually acquired its
    # Path; Stamina by itself is never proof of Body Refining access.
    typed['ingrain_body_use']=int('tianxia.path.body_refining' in paths and
                                 any(pool=='resource:core.stamina' and cost>0 for pool,cost in action.costs))
    modifiers=[r for r in typed.get('effects') or [] if r.get('source_modifier')]
    typed['effects']=[{'type':'ingrain_delivery','effects':[{'type':'spend_mark','mark':'Dose Mark','count':2,'applies_to':'target'},
        {'type':'save','ability':'con','applies_to':'target','on_fail':[{'type':'ingrain_toxin_choice','preferred':preferred}],'on_success':[]}]}] + modifiers
    typed['riders']=[]
    return action.model_copy(update={'parameters':params})

@hook('candidate_allowed')
def body_ingrain(engine,actor,candidate,action):
    if action is None or ID not in ((action.parameters.get('typed') or {}).get('source'),(action.parameters.get('typed') or {}).get('option_of')):
        return None
    from ..clinical_sources import biological_target
    if not all(biological_target(engine,actor,engine.state.actors[who],spiritual=True,spiritual_feature='tianxia.talent.poison.soul_venom_method') for who in candidate.target_ids):return False
    if (action.parameters.get('typed') or {}).get('ingrain_body_use'):
        return all(engine.grid.distance_ft(actor.position,engine.state.actors[who].position)<=5 for who in candidate.target_ids)
    return None

@effect('ingrain_delivery')
def ingrain_delivery(ctx,row):
    from ..clinical_sources import biological_target
    from .creature_kinds import owns_modifier
    from .needle import ask,checkpoint_id,CHOICE
    from ..typed_executor import run_effects
    spiritual=False
    if owns_modifier(ctx.engine,ctx.actor,'tianxia.talent.poison.soul_venom_method'):
        modes=['ordinary','spiritual'] if biological_target(ctx.engine,ctx.actor,ctx.target) else ['spiritual']
        selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ingrain_delivery',ctx.target.entity_id),ctx.actor,
            CHOICE+'ingrain_delivery',modes,labels={'ordinary':'Ordinary poison: meaningful biology required','spiritual':'Soul Venom Method: spiritual poison; a soul or animating spirit/pattern is required'},
            preferred=modes[:1],prompt='Ingrain the Toxin: choose ordinary or spiritual delivery using your learned Soul Venom Method. This does not bypass immunity or stronger spiritual protection.')
        spiritual=(selected or modes[:1])[0]=='spiritual'
    if not biological_target(ctx.engine,ctx.actor,ctx.target,spiritual=spiritual,spiritual_feature='tianxia.talent.poison.soul_venom_method'):return
    run_effects(ctx,row['effects'])


@effect('ingrain_toxin_choice')
def ingrain(ctx,row):
    from .needle import ask,checkpoint_id,CHOICE
    from .effect_durations import token
    target=ctx.target
    if target is None or ID not in (ctx.typed.get('source'),ctx.typed.get('option_of')):
        return
    labels={
        'Bitter Breath':'Bitter Breath: Disadvantage on the next Constitution save before Long Rest or treatment',
        'Numb Channels':'Numb Channels: Speed reduced by 5 feet until Long Rest or treatment',
        'Sour Blood':f"Sour Blood: next healing reduced by {int(ctx.numbers.get('pb') or 2)} before Long Rest or treatment",
        'Clouded Senses':'Clouded Senses: Disadvantage on the next Wisdom (Perception) check before Long Rest or treatment',
        'Heavy Pulse':'Heavy Pulse: no Dash benefit on its next turn; Disadvantage on its next Dexterity save before Long Rest or treatment'}
    from ..clinical_sources import metadata
    previous={}
    for c in target.conditions.values():
        facts=metadata(ctx.engine,target,c,retained=True) or {}
        if facts.get('rule')==ID and facts.get('owner')==ctx.actor.entity_id:previous[facts['source_instance']]=facts
    if previous:
        replacement=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ingrain_replacement',target.entity_id),ctx.actor,
            CHOICE+'ingrain_replacement',['replace','fail'],labels={'replace':'End your previous Ingrained Toxin and create the new toxin','fail':'Keep your previous toxin; this attempt fails, with CP and marks already spent'},
            preferred=['replace'],prompt=f'{target.display_name} already bears your Ingrained Toxin. Only one from you may remain. Choose whether the old toxin ends or this new attempt fails.')
        if (replacement or ['fail'])[0]=='fail':return
        from ..clinical_sources import end
        for old in previous.values():end(ctx.engine,target,old,ctx.source)
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ingrain',ctx.source,target.entity_id),ctx.actor,
        CHOICE+'ingrain_toxin',OPTIONS,labels=labels,preferred=[row.get('preferred',OPTIONS[0])],
        prompt=f'Ingrain the Toxin: {target.display_name} failed the Constitution save. Your Action, 2 CP and two Dose Marks are spent. Choose one minor toxin.')
    choice=(selected or [row.get('preferred',OPTIONS[0])])[0]
    rule={}
    if choice=='Bitter Breath':rule={'save_mode':{'CON':'DISADVANTAGE'}}
    if choice=='Clouded Senses':rule={'check_mode':{'Perception':'DISADVANTAGE','perception':'DISADVANTAGE'}}
    if choice=='Heavy Pulse':rule={'save_mode':{'DEX':'DISADVANTAGE'}}
    source_instance=f'{ctx.source}:{ctx.actor.entity_id}:{ctx.intent.intent_id if ctx.intent else ctx.engine.state.event_sequence}'
    dc=ctx.numbers.get('save_dc')
    if type(dc) is not int or dc<1:
        raise ValueError('Ingrain requires the actual sealed Cultivation Save DC')
    clinical={'source_instance':source_instance,'source':ctx.source,'owner':ctx.actor.entity_id,
        'rule':ID,'category':'poison','ongoing':0,'excluded':[],'readers':[ctx.actor.entity_id],'private':1, 'label':choice,
        'dc':dc}
    ctx.engine._apply_condition(target,TOXIN,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'choice':choice,'pb':int(ctx.numbers.get('pb') or 2),'rule':rule,'clinical':clinical,'label':labels[choice]})
    if choice=='Heavy Pulse':
        ctx.engine._apply_condition(target,DASH,ctx.source,ctx.actor.entity_id,
            expires_on=token('END',target.entity_id,target.turns_started+1),
            data={'clinical':clinical,'next_turn':target.turns_started+1,'rule':{},'label':'Heavy Pulse: Dash gives no extra movement on the next turn'})

@hook('dash_benefit_allowed')
def heavy_dash_benefit(engine,actor,source):
    if any(c.condition_id==DASH and actor.turns_started==c.data['next_turn']
           and not c.data.get('suppressed') for c in actor.conditions.values()):
        return False
    return None

@hook('speed')
def toxin_speed(engine,actor):
    return -5*sum(c.condition_id==TOXIN and c.data.get('choice')=='Numb Channels' and not c.data.get('suppressed') for c in actor.conditions.values())

@hook('d20_finalized')
def toxin_roll(engine,roll,intent):
    actor=engine.state.actors.get(roll.actor_id)
    if actor is None or roll.natural_result is None:return
    frame=engine.d20_context(roll) or {}; reason=str(roll.reason)
    ability=str(frame.get('ability') or '').upper()
    skill=str(frame.get('skill') or '').lower()
    for c in list(actor.conditions.values()):
        if c.condition_id!=TOXIN:continue
        choice=c.data.get('choice')
        save=frame.get('kind')=='save' or reason.startswith('SAVE:')
        con=ability=='CON' or reason.startswith('SAVE:CON')
        dex=ability=='DEX' or reason.startswith('SAVE:DEX')
        perception=(frame.get('kind')=='check' or reason.startswith('CHECK:')) and (skill=='perception' or 'perception' in reason.lower())
        if (choice=='Bitter Breath' and save and con) or (choice=='Heavy Pulse' and save and dex) or (choice=='Clouded Senses' and perception):
            engine._remove_condition_instance(actor,c.instance_id,c.source_definition_id,expected=c)

@hook('healing_received')
def toxin_healing(engine,subject,amount):
    if amount<=0:return None
    result=amount
    for c in list(subject.conditions.values()):
        if c.condition_id==TOXIN and c.data.get('choice')=='Sour Blood' and not c.data.get('suppressed'):
            result=max(0,result-int(c.data['pb']))
            engine._remove_condition_instance(subject,c.instance_id,c.source_definition_id,expected=c)
    return result if result!=amount else None

@hook('journey_rest')
def rest_cures(session,actor_id):
    import json
    snapshot=session.state['actors'][actor_id].get('encounter_snapshot')
    if snapshot:
        for key,encoded in list(snapshot['conditions'].items()):
            c=json.loads(encoded);data=c.get('data',{});kept=data.get('model') or {}
            if c['condition_id'] in (TOXIN,DASH) or kept.get('condition_id') in (TOXIN,DASH):
                snapshot['conditions'].pop(key)
                session.emit('CLINICAL_SOURCE_ENDED',actor_id,instance_id=key,reason='long_rest')
