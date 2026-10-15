"""Source-bound combat expressions of Cultivation Insights in the fourth group."""
from . import effect, hook
from .passive_rows import row_of

BLOCK = 'insights_four'
BOIL = 'insight.legacy-blood-boil'
STATE = 'condition:typed.insights_blood_boil'
EMPOWER = 'insight.legacy-empowered-technique'
DISTANT = 'insight.legacy-distant-technique'

@hook('compile_block')
def compile_insights(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': row['feature_id'], 'key_mod': int(numbers['key_mod']),
             'pb': int(numbers['pb']), 'choice_owner': True,
             'player_outcome': spec['outcome']}]

@effect('insights_blood_boil')
def blood_boil(ctx, effect):
    from ..typed_executor import effect_expiry
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, effect, ctx.actor, condition=True),
        data={'label': 'Blood Boil: Advantage on melee attacks; attacks against you have Advantage; take 1d4 damage at the end of each turn',
              'rule': {'melee_attacks_have': 'ADVANTAGE', 'attacked_with': 'ADVANTAGE'}})

@hook('turn_end')
def boil_damage(engine, actor):
    from ..gate2_runtime_models import DiceSpec
    state = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    if state is None or not actor.active:
        return
    roll = engine.roller.roll(DiceSpec(count=1,sides=4,modifier=0),actor_id=actor.entity_id,reason='DAMAGE:'+BOIL)
    engine._record_roll(roll)
    engine._append_event('DAMAGE_ROLLED', state.source_definition_id, actor_id=actor.entity_id,
        target_ids=(actor.entity_id,), payload=roll.model_dump(mode='json'))
    previous = getattr(engine, '_damage_unreduced', None)
    engine._damage_unreduced = actor.entity_id
    try:
        engine._commit_damage(actor, roll.total, 'UNTYPED', state.source_definition_id,
                              actor.entity_id, engine._active_intent, reaction_depth=2)
    finally:
        engine._damage_unreduced = previous

@hook('compile_actions')
def distant_variants(info):
    import copy
    if DISTANT not in info['owned_ids']:
        return None
    from ..factory_compiler import RESOURCE_IDS
    made=[]
    for action in info['actions']:
        typed = action.parameters.get('typed') or {}
        record = info['mechanics'].get(typed.get('source')) or {}
        if not record.get('sphere_id') or record.get('kind') not in ('talent','base_ability') or not action.range_ft or action.range_ft < 10:
            continue
        if action.target_kind in ('SELF','CELL') and (record.get('range') or {}).get('kind') == 'self':
            continue
        for pool in info['pools']:
            t=copy.deepcopy(typed)
            t['range_ft']=int(action.range_ft)*2
            if t.get('long_range_ft'): t['long_range_ft']=int(t['long_range_ft'])*2
            t['insights_distant']=DISTANT
            made.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'+distant_'+pool,
                'display_name': action.display_name+' + Distant Technique ('+pool.title()+')',
                'range_ft': int(action.range_ft)*2,
                'costs': (*action.costs,(RESOURCE_IDS[pool],1)),
                'parameters':{**action.parameters,'typed':t}}))
    return made or None

@hook('damage_dice_reroll')
def empowered(ctx, effect, kinds, dice_count):
    from .needle import ask, checkpoint_id
    from .choice_costs import payable
    row=row_of(ctx.engine,ctx.actor.entity_id,BLOCK,EMPOWER)
    key_mod=int(ctx.numbers.get('key_mod',row['key_mod']) or 0) if row else 0
    if not row or not ctx.typed.get('sphere') or dice_count<=0 or key_mod<=0 or ctx.damage_cache.get('insights_empowered_used'):
        return None
    pools=[p for p in ('resource:core.qi','resource:core.stamina','resource:core.resonance') if ctx.actor.resources.get(p,0)>=1]
    if not pools:return None
    count=min(dice_count,key_mod)
    options={p:(p,count) for p in pools}
    options.update({p+'|'+str(n):(p,n) for p in pools for n in range(1,count)})
    from .choice_prompt import action_context
    affected = list(getattr(ctx, 'targets', ()) or ())
    affected_names = ', '.join(t.display_name for t in affected) or 'the affected creature'
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'Empowered Technique',ctx.source),ctx.actor,
        'choice:needle.insights_empowered',list(options),allow_decline=True,default='first',name='Empowered Technique',feature_id=EMPOWER,
        labels={key:'Spend 1 '+p.rsplit('.',1)[-1].title()+' to reroll '+str(n)+' damage dice; use the new rolls' for key,(p,n) in options.items()},
        target_id=affected[0].entity_id if affected else ctx.actor.entity_id,
        prompt=f"Empowered Technique after {ctx.action.display_name} against {affected_names}: spend 1 additional cultivation point to reroll damage dice?",
        prompt_context=action_context(ctx.engine,ctx.actor,ctx.source,affected[0] if affected else ctx.actor,action=ctx.action))
    if not picked or picked[0] not in options:return None
    pool,count=options[picked[0]]
    payable(ctx.actor,pool,1).pay(ctx.engine,ctx.actor,EMPOWER)
    ctx.damage_cache['insights_empowered_used']=1
    return count

MERIDIANS='insight.legacy-enhanced-meridians'

@hook('compile_resource_definitions')
def enhanced_resources(resources, info):
    """Only recorded occurrences size existing pools; never create a Path."""
    if MERIDIANS not in info['owned_ids']:
        return resources
    from ..factory_compiler import RESOURCE_IDS
    occurrences=(info['owner_sheet'].get('spheres_and_talents') or {}).get('cultivation_insight_occurrences') or []
    selected=[o for o in occurrences if o.get('insight_id')==MERIDIANS][:2]
    active=[r for r in resources if r.resource_id in {RESOURCE_IDS[p] for p in ('stamina','qi','resonance')}]
    if not selected and len(active)==1:
        selected=[{'parameters':{'resource_pool':active[0].resource_id.rsplit('.',1)[-1]}}]
    bonuses={}
    for o in selected:
        params=o.get('parameters') or {}
        pool=str(params.get('resource_pool') or params.get('pool') or '').lower()
        rid=RESOURCE_IDS.get(pool)
        if rid and any(r.resource_id==rid for r in resources):
            bonuses[rid]=bonuses.get(rid,0)+2*int(info['pb'])
    return [r.model_copy(update={'initial':r.initial+bonuses[r.resource_id],
                                'maximum':r.maximum+bonuses[r.resource_id]})
            if r.resource_id in bonuses else r for r in resources]

ADAMANTINE='insight.legacy-adamantine-breath'
CUSTODIAN='insight.hollow-script-custodian'

@hook('soak_total')
def adamantine_breath(engine, actor, row, roll):
    from .needle import ask,checkpoint_id
    from .choice_prompt import action_context
    if row.get('feature_id')!='tianxia.path.body_refining.feature.stamina_guard' or not row_of(engine,actor.entity_id,BLOCK,ADAMANTINE):
        return None
    if actor.turn_flags.get('once_per_round:insights_adamantine')==int(engine.state.round_number) or 'd10' not in roll.expression or not roll.dice:
        return None
    trigger=getattr(engine,'_reaction_trigger',None) or {}
    subject=engine.state.actors.get(trigger.get('target_id') or actor.entity_id)
    intent=engine._active_intent
    event=next((e for e in reversed(engine.events)
        if e.actor_id==getattr(intent,'actor_id',None) and e.source_definition_id in engine.action_catalog
        and e.event_type in ('INTENT_ACCEPTED','ACTION_DECLARED','ATTACK_DECLARED','SAVE_ROLLED')),None)
    source_id=trigger.get('source_definition_id') or (event.source_definition_id if event else None)
    source_action=engine.action_catalog.get(source_id)
    trigger_name=str(trigger.get('action_name') or getattr(source_action,'display_name','incoming attack'))
    picked=ask(engine,engine._active_intent,checkpoint_id(engine,'Adamantine Breath',roll.roll_id),actor,
        'choice:needle.insights_adamantine',['maximize'],allow_decline=True,default='first',name='Adamantine Breath',feature_id=ADAMANTINE,
        labels={'maximize':'Treat one Stamina Guard d10 as a 10; once per round, no extra cost'},
        target_id=subject.entity_id if subject else actor.entity_id,
        prompt='After '+trigger_name+' against '+(subject.display_name if subject else actor.display_name)+
            ', treat one Stamina Guard d10 as a 10? Once per round; no extra cost.',
        prompt_context={'source_definition_id':str(source_id or trigger_name),
            'action_name':trigger_name,'action_actor_id':str(trigger.get('actor_id') or (event.actor_id if event else getattr(intent,'actor_id',''))),
            'affected_id':str(subject.entity_id if subject else actor.entity_id)})
    if not picked:return None
    actor.turn_flags['once_per_round:insights_adamantine']=int(engine.state.round_number)
    return int(roll.total)+10-min(roll.dice)

@hook('save_final')
def hollow_custodian(ctx,subject,ability,named,failed):
    from .needle import ask,checkpoint_id
    from ..typed_executor import block_condition
    if not failed or ctx.typed.get('sphere')!='tianxia.sphere.void' or not row_of(ctx.engine,ctx.actor.entity_id,BLOCK,CUSTODIAN) or any(c.condition_id=='condition:typed.insights_custodian_used' for c in ctx.actor.conditions.values()):
        return
    existing=any(c.condition_id=='condition:typed.hollowed' for c in subject.conditions.values())
    if not existing and 'hollowed' not in named:return
    from .choice_prompt import action_context
    trigger = getattr(ctx, 'action', None)
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'Hollow Script Custodian',subject.entity_id),ctx.actor,
        'choice:needle.insights_custodian',['extend'],allow_decline=True,default='first',name='Hollow Script Custodian',feature_id=CUSTODIAN,
        labels={'extend':'Extend Hollowed until the end of your next turn; once between Full Cultivation Sessions'},
        target_id=subject.entity_id,
        prompt='After '+(trigger.display_name if trigger else 'your Void technique')+', extend Hollowed on '+subject.display_name+' until the end of your next turn? No extra cost.',
        prompt_context=action_context(ctx.engine,ctx.actor,ctx.source,subject,action=trigger))
    if not picked:return
    ctx.engine._apply_condition(ctx.actor,'condition:typed.insights_custodian_used',CUSTODIAN,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Hollow Script Custodian: used until your next Full Cultivation Session'})
    ctx.damage_cache.setdefault('insights_hollow_extended',set()).add(subject.entity_id)
    if existing and 'hollowed' not in named:
        block_condition(ctx.on_hit_context(subject),{'type':'condition','condition':'hollowed','applies_to':'target',
            'duration':'until_end_of_your_next_turn','evidence':'Extend Hollowed until the end of your next turn.'})

@hook('condition_state')
def hollow_extension(ctx,subject,effect):
    if effect.get('condition')=='hollowed' and subject.entity_id in ctx.damage_cache.get('insights_hollow_extended',()):
        return {'expires_on':f'END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started)+1}'}
    return None

HOOK_MASTER='insight.hook-master'
HOOK='tianxia.talent.chains.restraining_hook'
FREE_HOOK='resource:uses.insight.hook-master'

@hook('compile_resources')
def hook_counter(info):
    from ..gate2_runtime_models import ResourceDefinition
    if HOOK_MASTER in info['owned_ids']:
        return [ResourceDefinition(resource_id=FREE_HOOK,initial=1,maximum=1)]
    return None

IRON_BLOOD='insight.iron-blood-circulation'
@hook('save_effects')
def circulation_save(ctx,subject,ability,fail_effects,success_effects,categories):
    from ..typed_executor import _walk_rows
    if not row_of(ctx.engine,subject.entity_id,BLOCK,IRON_BLOOD):return None
    relevant='disease' in categories or 'physical_injury_exhaustion' in categories or any(
        e.get('type')=='condition' and e.get('condition') in ('disease','diseased') for e in _walk_rows(fail_effects))
    return {'modes':['ADVANTAGE']} if relevant else None

@hook('compile_passives')
def circulation_marker(passives,info):
    if IRON_BLOOD in info['owned_ids']:
        return [*passives,{'feature_id':IRON_BLOOD,'block':BLOCK,'kind':IRON_BLOOD,
            'player_outcome':'Advantage on saves against Bleeding, Poison, Disease, and Exhaustion caused by physical injury'}]
    return passives


@hook('generic_reaction_costs')
def hook_free_costs(engine,reactor,other,row,costs):
    if row.get('feature_id')!=HOOK or not row_of(engine,reactor.entity_id,BLOCK,HOOK_MASTER) or reactor.resources.get(FREE_HOOK,0)<1:
        return None
    # Keep normal CP as the affordability quote when available; payment choice
    # is made only after the player accepts the reaction.
    cp={'resource:core.qi','resource:core.stamina','resource:core.resonance'}
    if any(c['resource_id'] in cp and reactor.resources.get(c['resource_id'],0)>=c['amount'] for c in costs):
        return None
    return [*(c for c in costs if c['resource_id'] not in cp),{'resource_id':FREE_HOOK,'amount':1}]

@hook('generic_reaction_payment')
def hook_payment_choice(engine,reactor,row,costs):
    if row.get('feature_id')!=HOOK or not row_of(engine,reactor.entity_id,BLOCK,HOOK_MASTER):
        return None
    cp=[c for c in costs if c['resource_id'] in {'resource:core.qi','resource:core.stamina','resource:core.resonance'}]
    free=reactor.resources.get(FREE_HOOK,0)>=1
    paid=next((c for c in cp if reactor.resources.get(c['resource_id'],0)>=c['amount']),None)
    if not (free and paid):
        return None
    from .needle import ask,checkpoint_id
    intent=getattr(engine,'_active_intent',None)
    trigger=getattr(engine,'_reaction_trigger',None) or {}
    subject=engine.state.actors.get(trigger.get('target_id') or trigger.get('actor_id') or getattr(intent,'actor_id',None)) or reactor
    trigger_name=str(trigger.get('action_name') or 'movement')
    picked=ask(engine,intent,checkpoint_id(engine,'Hook Master payment',row.get('feature_id')),
        reactor,'choice:needle.hook_master_payment',['paid','free'],allow_decline=False,
        default='first',name='Hook Master',feature_id=HOOK_MASTER,
        labels={'paid':'Pay '+str(paid['amount'])+' cultivation point(s) and save the free use for later',
                'free':'Use the once-per-scene free use; save your cultivation points'},
        prompt='After '+trigger_name+' by '+subject.display_name+', choose how to pay for Restraining Hook against '+subject.display_name+'.',
        target_id=subject.entity_id,
        prompt_context={'source_definition_id':str(trigger.get('source_definition_id') or row.get('feature_id')),
            'action_name':trigger_name,
            'action_actor_id':str(trigger.get('actor_id') or getattr(intent,'actor_id','')),
            'affected_id':str(subject.entity_id)},
        automatic_options=['free'])
    if picked and picked[0]=='free':
        return [*(c for c in costs if c['resource_id'] not in {'resource:core.qi','resource:core.stamina','resource:core.resonance'}),
                {'resource_id':FREE_HOOK,'amount':1}]
    return costs

@hook('compile_passives')
def hook_master_marker(passives,info):
    if HOOK_MASTER in info['owned_ids']:
        return [*passives,{'feature_id':HOOK_MASTER,'block':BLOCK,'kind':HOOK_MASTER,'choice_owner':True,
            'player_outcome':'Restraining Hook gains 30 feet of range and can be used without CP once per scene'}]
    return passives

@hook('confirmed_damage_roll_adjustment')
def empowered_attack_damage(engine,actor,target,spec,intent,source,roll):
    from .attack_scope import current
    from ..gate2_runtime_models import DiceSpec
    frame=current(engine)
    if not frame or frame['actor_id']!=actor.entity_id or frame['source']!=source or spec.get('fixed_damage') is not None:
        return None
    ctx=frame['context']
    dice=spec.get('damage')
    if not isinstance(dice,DiceSpec) or not roll.dice:return None
    count=empowered(ctx,frame.get('effect'),[str(spec.get('damage_type') or '')],len(roll.dice))
    if not count:return None
    replacement=engine.roller.roll(DiceSpec(count=count,sides=dice.sides,modifier=0),actor_id=actor.entity_id,
        reason='DAMAGE_REROLL:'+source)
    engine._record_roll(replacement)
    engine._append_event('DAMAGE_ROLLED',source,actor_id=actor.entity_id,target_ids=(target.entity_id,),
        payload={**replacement.model_dump(mode='json'),'rerolled_dice':count,'reroll_bonus':0})
    return replacement.total-sum(sorted(roll.dice)[:count])
