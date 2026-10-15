"""Source-specific appraisal consumers on the public encounter/observer seams.

All choices use the native owner-bound transport. Unknown facts stay unknown;
only question-sized answers reach the observer projection. Object targeting uses
the existing object hooks; it never inserts objects into the creature roster.
"""
from copy import deepcopy
from . import hook, effect
from .needle import ask, checkpoint_id, CHOICE
from ..encounter_sources import facts

QI='HUNGER_BASE_TASTE_THE_QI'
TRACE='INK_BASE_READ_THE_TRACE'
VESSEL='IMBUEMENT_BASE_READ_THE_VESSEL'
VENOM='POISON_BASE_APPRAISE_THE_VENOM'
METAL='METAL_BASE_METAL_APPRAISAL'
SKY='WEATHER_BASE_READ_THE_SKY'
QUESTIONS={
 QI: ['qi.nature','qi.bloodied','qi.expression','qi.impurity','qi.suitable','qi.ward'],
 TRACE:['trace.nature','trace.contents','trace.age','trace.hand','trace.alteration'],
 VESSEL:['vessel.mandate','vessel.safe','vessel.resists','vessel.nature','vessel.bonus','vessel.enhancement','vessel.backlash'],
 VENOM:['poison.kind','poison.poisoned','poison.dose','poison.burden','poison.ingrained','poison.timing','poison.antidote','poison.safe','poison.sphere'],
 METAL:['metal.material','metal.nature','metal.structure','metal.suitable','metal.properties'],
}
LABELS={
 'qi.fallback':'Spiritually nourishing or dangerous?', 'poison.present':'Is poison present?',
 'qi.nature':'Spiritual nature or nourishment', 'qi.bloodied':'Is this creature Bloodied?',
 'qi.expression':'Strongest obvious qi expression', 'qi.impurity':'Does this meal or ingredient contain Impurity?',
 'qi.suitable':'Suitable for a Hunger talent I know?', 'qi.ward':'Obvious anti-consumption protection',
 'trace.nature':'Ordinary, magical, spiritual, forged or sphere-created?',
 'trace.contents':'Active Ink Mark, seal, curse, ward or hidden script?', 'trace.age':'Written recently or long ago?',
 'trace.hand':'Living hand, spirit, construct, item, formation or sphere effect?',
 'trace.alteration':'Altered, forged, erased or overwritten?',
 'vessel.mandate':'Currently affected by a Mandate?', 'vessel.safe':'One property it can receive safely',
 'vessel.resists':'One property it resists', 'vessel.nature':'Mundane, magical, awakened, construct-like, soul-bound or artifact-grade?',
 'vessel.bonus':'Suppressed or active magical bonus?', 'vessel.enhancement':'Active creature enhancement',
 'vessel.backlash':'Backlash from careless imbuement?',
 'poison.kind':'Poison family', 'poison.poisoned':'Is the target Poisoned?', 'poison.dose':'Does it carry any of my Dose Marks?',
 'poison.burden':'Toxin Burden?', 'poison.ingrained':'Ingrained Toxin?', 'poison.timing':'Immediate, delayed or long-term danger?',
 'poison.antidote':'Might an ordinary antidote help?', 'poison.safe':'Safe to handle in this scene?', 'poison.sphere':'Associated sphere',
 'metal.material':'Obvious metal, alloy, ore or mineral quality', 'metal.nature':'Mundane, spiritual, cursed, oath-bound, corpse-touched, crafted or artifact-like?',
 'metal.structure':'Damaged, brittle, reinforced, warded or poorly balanced?', 'metal.suitable':'Suitable for a Metal talent I know?',
 'metal.properties':'Conductive, magnetic, brittle, hardened, hollow or resonant?',
}
KINDS={
 QI:{'creature','corpse','meal','ingredient','beast_core','spiritual_dish','residue','container'},
 TRACE:{'text','mark','seal','rune','painting','inscription','talisman','formation_mark','ink_mark'},
 VESSEL:{'creature','object','weapon','armor','tool','construct','vessel','construct_part','formation_node'},
 VENOM:{'creature','corpse','object','wound','food','drink','weapon','sample','terrain','contamination','meal','ingredient'},
 METAL:{'object','weapon','armor','restraint','gate','lock','bell','ore','mineral','construct_part','formation_node','metal_creature'},
}

def questions_for(source, kind):
    result=list(QUESTIONS[source])
    if source==QI:
        if kind not in {'creature','metal_creature','construct'}:
            result.remove('qi.bloodied')
        if kind not in {'meal','ingredient','spiritual_dish'}:
            result.remove('qi.impurity')
        if kind not in {'creature','metal_creature','construct','ingredient'}:
            result.remove('qi.suitable')
    return result


def higher_realm(source_cl,reader_cl):
    if source_cl is None or reader_cl is None:
        return False
    from ..table_advance import realm_of
    return source_cl>reader_cl and realm_of(source_cl)!=realm_of(reader_cl)


def source_of(action):
    return ((getattr(action,'parameters',None) or {}).get('typed') or {}).get('source')


def choice(ctx, key, options, *, labels=None, count=1, optional=False, target_id=None, prompt=None):
    if not options:
        return []
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'READ_'+key, ctx.actor.entity_id), ctx.actor,
        CHOICE+'reading_'+key, options, labels=labels or {k:LABELS.get(k,k) for k in options},
        minimum=count, maximum=count, allow_decline=optional, default='decline' if optional else 'first',
        target_id=target_id, name=ctx.action.display_name, feature_id=ctx.action.display_name,
        prompt=prompt or f'{ctx.action.display_name}: choose {count} question(s). Answers are private to you.')


@hook('compile_action')
def compile_reading(action, info):
    source=source_of(action)
    option=(action.parameters.get('typed') or {}).get('option_label','')
    if source not in QUESTIONS or source not in info['owned_ids'] or ((action.parameters.get('typed') or {}).get('option_of') and (source!=QI or not option.startswith('Read an openly'))):
        return None
    typed=deepcopy(action.parameters['typed'])
    typed.pop('option_of',None);typed.pop('option_label',None)
    typed['numbers']={**typed.get('numbers',{}),'ability_mods':dict(info['mods'])}
    background=info['owner_sheet'].get('background_origin',{})
    proficient=list((background.get('background') or {}).get('tool_proficiencies',[]))
    proficient+=list((info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('tool_proficiencies',[]))
    origin=background.get('origin_insight') or {}
    if origin.get('selected_tool'):
        proficient.append(origin['selected_tool'])
    normalize=lambda name:str(name).replace('’',"'").casefold()
    ranks={normalize(name):1 for name in proficient}
    ranks.update({normalize(name):2 for name in origin.get('tool_expertise',[])})
    typed['reading_tool_proficiencies']=ranks
    from ..factory_compiler import primary_resource
    typed['reading_cp_pool']=primary_resource(info['owner_sheet'])[0]

    typed.update(effects=[{'type':'knowledge_reading'}], riders=[])
    if source==QI:typed['manual_inline_choice']=True
    range_ft=5 if source==TRACE else 30
    if typed.get('reading_internal'):
        range_ft=5
    typed['range']={'kind':'touch' if range_ft==5 else 'feet','distance_ft':range_ft}
    return action.model_copy(update={'display_name':'Taste the Qi' if source==QI and not typed.get('reading_object') else action.display_name,'target_kind':'OBJECT' if typed.get('reading_object') else 'ANY_CREATURE',
        'range_ft':range_ft,'parameters':{**action.parameters,'scene_check_source':True,'typed':typed}})


@hook('compile_actions')
def reading_variants(info):
    additions=[]
    for base in info['actions']:
        source=source_of(base)
        option=base.parameters['typed'].get('option_label','')
        if source not in QUESTIONS or source not in info['owned_ids'] or (base.parameters['typed'].get('option_of') and (source!=QI or not option.startswith('Read an openly'))):
            continue
        copies=[base]
        if source==VESSEL:
            copies.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'#internal',
                'display_name':base.display_name+' (internal properties, touch)',
                'parameters':{**base.parameters,'typed':{**base.parameters['typed'],'reading_internal':1}}}))
        if source==VENOM:
            copies.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'#three',
                'display_name':base.display_name+' (three facts, 1 CP)',
                'costs':((base.costs[0][0] if base.costs else 'resource:core.'+info['primary'],1),),
                'parameters':{**base.parameters,'typed':{**base.parameters['typed'],'reading_count':3}}}))
        if source==METAL:
            copies.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'#search',
                'display_name':base.display_name+' (Search)'}))
        additions.extend(copies[1:])
        for cast in copies:
            additions.append(cast.model_copy(update={'source_definition_id':cast.source_definition_id+'#object',
                'display_name':cast.display_name+' (object)',
                'parameters':{**cast.parameters,'typed':{**cast.parameters['typed'],'reading_object':1}}}))
    return additions or None


def subject_kind(engine, subject):
    supplied=facts(engine,subject).get('subject.kind',{}).get('value')
    if supplied:
        return supplied
    target=engine.state.actors.get(subject)
    if target:
        from ..typed_executor import mark_condition_id
        if any(c.condition_id==mark_condition_id('Ink Mark',c.source_actor_id) for c in target.conditions.values()):
            return 'ink_mark'
    return 'creature' if subject in engine.state.actors else 'object'


def eligible(engine, actor, action, subject):
    from ..senses import perceives, perceives_object
    source=source_of(action)
    if action.owner_id!=actor.entity_id or action.source_definition_id not in actor.action_ids:
        return False
    target=engine.state.actors.get(subject) or engine.state.objects.get(subject)
    if target is None or getattr(target,'destroyed',False):
        return False
    kind=subject_kind(engine,subject)
    if source==METAL and subject in engine.state.actors:
        if facts(engine,subject).get('metal.bearing',{}).get('value') is not True:
            return False
    elif kind not in KINDS[source]:
        return False
    if source==METAL and subject in engine.state.objects:
        bearing=facts(engine,subject).get('metal.bearing',{}).get('value')
        material=(target.component or {}).get('material')
        if bearing is not True and material not in {'iron','steel','iron or steel','copper','bronze','brass','gold','silver','mithral','adamantine'} and kind not in {'ore','mineral'}:
            return False
    if subject in engine.state.actors:
        distance=engine._distance_actor_to_actor(actor,target)
        visible=perceives(engine,actor,target,locate_concealed=True)
    else:
        from ..object_geometry import target_cells
        distance=min(engine.grid.distance_ft(p,q) for p in engine._actor_cells(actor) for q in target_cells(engine,target))
        visible=perceives_object(engine,actor,target)
    if distance > (action.range_ft or 0):
        return False
    # Touch is itself sufficient for the printed nonvisual examinations. Qi
    # requires perception even in reach; metal requires a visible structure.
    return visible or distance<=5 and source in {TRACE,VESSEL,VENOM}


@hook('object_targets')
def reading_objects(engine, actor, action):
    if source_of(action) not in QUESTIONS or not action.parameters['typed'].get('reading_object'):
        return []
    return [oid for oid in engine.state.objects if eligible(engine,actor,action,oid)]


@hook('candidate_allowed')
def reading_allowed(engine, actor, candidate, action):
    if source_of(action) not in QUESTIONS:
        return None
    if source_of(action)==QI and action.parameters.get('typed',{}).get('option_label','').startswith('Unwilling, concealed'):
        return False
    if candidate.target_ids:
        return len(candidate.target_ids)==1 and eligible(engine,actor,action,candidate.target_ids[0])
    return None


@hook('object_action')
def read_object(engine, actor, action, obj, candidate, intent):
    if source_of(action) not in QUESTIONS or not action.parameters['typed'].get('reading_object'):
        return None
    if not eligible(engine,actor,action,obj.object_id):
        raise ValueError('This examination is no longer available.')
    from ..typed_executor import Context
    ctx=Context(engine,actor,action,intent,action.parameters['typed'],[],damage_cache={'_object':obj})
    resolve(ctx,obj.object_id)
    return True


@effect('knowledge_reading')
def reading_effect(ctx, spec):
    if ctx.target is not None:
        resolve(ctx,ctx.target.entity_id)


def native_fact(ctx, subject, key):
    """Actual committed state precedes external input for mechanically tracked facts."""
    target=ctx.engine.state.actors.get(subject)
    if target is None:
        obj=ctx.engine.state.objects.get(subject)
        if key=='metal.material' and obj and (obj.component or {}).get('material'):
            return obj.component['material']
        return None
    if key=='poison.present':
        from .stacking_marks import count
        if any(c.condition_id in ('poisoned','condition:typed.poisoned') for c in target.conditions.values()) or any(count(ctx.engine,owner,target,name)>0 for owner in ctx.engine.state.actors.values() for name in ('Dose Mark','Toxin Burden','Ingrained Toxin')):
            return True
    if key in {'trace.nature','trace.contents','trace.hand'}:
        from ..typed_executor import mark_condition_id
        marks=[c for c in target.conditions.values() if c.condition_id==mark_condition_id('Ink Mark',c.source_actor_id)]
        if marks:
            if key=='trace.contents':
                return 'An active Ink Mark; other contents are unknown.'
            return 'Sphere-created' if key=='trace.nature' else 'A sphere effect'
    if key=='qi.bloodied':
        return target.current_hp*2 <= target.maximum_hp
    if key=='poison.poisoned':
        from ..typed_executor import condition_rules
        return any(c.condition_id in ('poisoned','condition:typed.poisoned') for c in target.conditions.values()) or any(
            r.get('poisoned') for r in condition_rules(target))
    if key in {'poison.dose','poison.burden','poison.ingrained'}:
        from .stacking_marks import count as mark_count
        name={'poison.dose':'Dose Mark','poison.burden':'Toxin Burden','poison.ingrained':'Ingrained Toxin'}[key]
        return (True if any(mark_count(ctx.engine,owner,target,name)>0 for owner in ctx.engine.state.actors.values()) else None) if key!='poison.dose' else mark_count(ctx.engine,ctx.actor,target,name)>0
    if key=='trace.contents':
        from .stacking_marks import count as mark_count
        if mark_count(ctx.engine,ctx.actor,target,'Ink Mark'):
            return 'An active Ink Mark from you; other contents are unknown.'
    return None


def check_spec(ctx, source):
    if source==QI:
        pool=ctx.typed['reading_cp_pool']
        maximum=min(ctx.actor.proficiency_bonus,ctx.actor.resources.get(pool,0))
        from ..resource_labels import resource_name
        labels={str(n):f'Spend {n} {resource_name(pool)} for +{n} to this Hunger Check' if n else 'Spend no CP' for n in range(maximum+1)}
        picked=choice(ctx,'hunger_steady',list(labels),labels=labels,
            prompt='Taste the Qi: before the Hunger Check, you may spend up to your Proficiency Bonus in CP. Each point adds +1 to this check.')
        amount=int(picked[0]) if picked else 0
        if amount:
            ctx.engine._spend_resource(ctx.actor,pool,amount,ctx.source)
        ctx.damage_cache['hunger_steady']=amount
        return {'kind':'cultivation','label':'Hunger Check'}
    if source==TRACE:
        choices={'INT:Arcana':'Intelligence (Arcana)','INT:Investigation':'Intelligence (Investigation)',
            'WIS:Insight':'Wisdom (Insight)','cultivation':'Cultivation Check'}
    else:
        choices={f'{a}:{s}':f'{name} ({s})' for a,name in [('INT','Intelligence'),('WIS','Wisdom'),('CHA','Charisma')]
            for s in ('Arcana','Insight','Investigation','Medicine')}
    from ..carry import carrying_of,holds
    subject=ctx.damage_cache.get('reading_subject')
    data=facts(ctx.engine,subject) if subject else {}
    tools=data.get('trace.tools' if source==TRACE else 'vessel.tools',{}).get('value',{})
    normalize=lambda name:str(name).replace('’',"'").casefold()
    carried=(carrying_of(ctx.engine,ctx.actor.entity_id) or {}).get('items',[])
    for item in carried:
        name=item.get('name','');key=item.get('key')
        rank=ctx.typed.get('reading_tool_proficiencies',{}).get(normalize(name),0)
        if not key or not holds(ctx.engine,ctx.actor,key):
            continue
        if source==TRACE and normalize(name) not in {"calligrapher's supplies","painter's supplies"}:
            continue
        if source==VESSEL and not rank:
            continue
        for ability in tools.get(key,[]):
            choices[ability+':'+name]=ability+' ('+name+')'
    picked=choice(ctx,'check',list(choices),labels=choices,prompt=ctx.action.display_name+': choose the printed check you use.')
    key=picked[0] if picked else next(iter(choices))
    if key=='cultivation':
        return {'kind':'cultivation','label':'Cultivation Check'}
    ability,skill=key.split(':',1)
    ctx.damage_cache['reading_check']={'ability':ability,'skill':skill}
    return {'kind':'ability','ability':ability,'skill':skill,'label':choices[key]}


@hook('check_bonus')
def hunger_steady_bonus(ctx,subject):
    if source_of(ctx.action)==QI and subject is ctx.actor:
        return int(ctx.damage_cache.get('hunger_steady',0))
    return None


@hook('check_bonus')
def chosen_check_proficiency(ctx, subject):
    selected=ctx.damage_cache.get('reading_check')
    if not selected or subject is not ctx.actor or source_of(ctx.action) not in {TRACE,VESSEL}:
        return None
    ability,skill=selected['ability'],selected['skill']
    modifiers=ctx.numbers.get('ability_mods',{})
    bundle=next((b for b in ctx.engine.typed_bundle_documents if b['actor_id']==subject.entity_id),{})
    standard={'Arcana':'INT','Investigation':'INT','Insight':'WIS','Medicine':'WIS'}
    if skill in (bundle.get('skills') or {}):
        return int(modifiers.get(ability,0))-int(modifiers.get(standard.get(skill,ability),0))
    name=skill.replace('’',"'").casefold()
    rank=ctx.typed.get('reading_tool_proficiencies',{}).get(name,0)
    return int(ctx.numbers.get('pb',subject.proficiency_bonus))*rank if skill not in standard else None


@hook('check_dc')
def reading_dc(ctx, target, spec):
    if spec.get('of')=='information_source_dc':
        return int(spec['value'])
    return None


def answer(ctx, subject, selected, *, failed=False):
    from ..observer_information import publish
    from .effect_durations import token
    source=source_of(ctx.action)
    data=facts(ctx.engine,subject)
    answers={}
    for key in selected:
        native=native_fact(ctx,subject,key)
        fact=data.get(key,{})
        if failed and key!='qi.fallback':
            answers[LABELS.get(key,key)]='Unknown: this reading has not been resolved.'
            continue
        access=fact.get('access','surface')
        if native is not None:
            value=native
        elif access=='internal' and not ctx.typed.get('reading_internal') or access=='concealed' and source not in {TRACE,VESSEL} and not ctx.damage_cache.get('reading_overcame_concealment'):
            value='Unknown'
        elif key in {'qi.suitable','metal.suitable'}:
            from ..alternative_payments import owned
            from .source_eligibility import stored_power
            values=fact.get('value',{})
            value={(stored_power(ctx.engine,talent) or ({},''))[0].get('name','Known talent'):result
                for talent,result in values.items() if owned(ctx.engine,ctx.actor,talent)} or 'Unknown: no known talent has a suitability fact.'
        else:
            value=fact.get('value','Unknown')
        answers[LABELS.get(key,key)]=value
    expiry=token('end',ctx.actor.entity_id,ctx.actor.turns_started+1) if source==QI else 'UNTIL_REMOVED'
    publish(ctx.engine,ctx.actor,ctx.action.source_definition_id,ctx.actor,'answer',
        {'ability':ctx.action.display_name,'subject_id':subject,'subject_name':ctx.target_display(),'answers':answers,'check_failed':int(failed and selected==['qi.fallback']),'resolution':'unresolved' if failed and selected!=['qi.fallback'] else 'failed' if failed else 'success'},expiry)


def resolve(ctx, subject):
    source=source_of(ctx.action)
    ctx.damage_cache['reading_subject']=subject
    if not eligible(ctx.engine,ctx.actor,ctx.action,subject):
        raise ValueError('This examination is no longer available.')
    data=facts(ctx.engine,subject)
    if source==TRACE and subject in ctx.engine.state.actors:
        from ..typed_executor import mark_condition_id
        from ..observer_information import source_numbers
        for mark in ctx.engine.state.actors[subject].conditions.values():
            if mark.condition_id!=mark_condition_id('Ink Mark',mark.source_actor_id):
                continue
            numbers=source_numbers(ctx.engine,mark.source_definition_id,mark.source_actor_id)
            if higher_realm(numbers.get('cl'),ctx.numbers.get('cl')):
                data={**data,'trace.high_realm':{'value':True}}
                if numbers.get('save_dc') is not None:
                    data.setdefault('trace.dc',{'value':numbers['save_dc']})
    count=2 if source==VESSEL else int(ctx.typed.get('reading_count',1))
    selected=choice(ctx,'questions',questions_for(source,subject_kind(ctx.engine,subject)),count=count,target_id=subject)
    if len(selected)!=count:
        return
    if source==QI and subject in ctx.engine.state.actors:
        target=ctx.engine.state.actors[subject]
        declarations={'open':'I am willing and not actively concealing my nature',
            'unwilling_open':'I am unwilling, but not actively concealing my nature',
            'willing_concealed':'I am willing, while actively concealing my nature',
            'unwilling_concealed':'I am unwilling and actively concealing my nature'}
        from ..fact_consent_admission import admit_choice
        from .effect_durations import token
        declared=admit_choice(ctx,target,ctx.source,'qi_nature',ctx.intent.intent_id+':'+subject,
            list(declarations),labels=declarations,
            prompt=f'{ctx.actor.display_name} uses Taste the Qi on {target.display_name}. Declare your own willingness and active concealment; your nature is not disclosed.',
            expires_on=token('end',ctx.actor.entity_id,ctx.actor.turns_started+1),readers=[ctx.actor.entity_id])
        if declared is None:
            answer(ctx,subject,selected,failed=True)
            return
        key=declared['value']
        data={**data,'qi.unwilling':{'value':key in {'unwilling_open','unwilling_concealed'}},
              'qi.concealing':{'value':key in {'willing_concealed','unwilling_concealed'}}}
    if source in {TRACE,VESSEL,QI}:
        contested=source==QI and data.get('qi.unwilling',{}).get('value') is True and data.get('qi.concealing',{}).get('value') is True
        need=source==VESSEL or source==TRACE and (any(data.get('trace.'+k,{}).get('value') is True for k in ('concealed','hostile','high_realm')) or any(data.get(k,{}).get('access')=='concealed' or higher_realm(data.get(k,{}).get('cl'),ctx.numbers.get('cl')) for k in selected))
        if contested or need:
            from ..typed_executor import resolve_opposed_check
            target=ctx.engine.state.actors.get(subject) or ctx.actor
            if contested:
                defense=data.get('qi.defense',{}).get('value')
                if defense not in ('CHA','CON') or subject not in ctx.engine.state.actors:
                    answer(ctx,subject,['qi.fallback'],failed=True)
                    return
                against={'kind':'save','ability':defense}
            else:
                dc=data.get('trace.dc' if source==TRACE else 'vessel.dc',{}).get('value')
                if dc is None:
                    creator=next((data[k].get('creator_id') for k in selected if data.get(k,{}).get('creator_id')),None)
                    if creator in ctx.engine.state.actors:
                        from .needle import save_dc
                        dc=save_dc(ctx.engine,ctx.engine.state.actors[creator])
                if dc is None:
                    # No invented DC or success. The source must specify one.
                    answer(ctx,subject,selected,failed=True)
                    return
                against={'kind':'dc','dc':dc}
            result=resolve_opposed_check(ctx,target,check_spec(ctx,source),against)
            ctx.damage_cache['reading_check_total']=result.actor.total
            if result.success and contested:
                ctx.damage_cache['reading_overcame_concealment']=1
            if not result.success:
                if source==QI:
                    answer(ctx,subject,['qi.fallback'],failed=True)
                else:
                    from ..observer_information import publish
                    publish(ctx.engine,ctx.actor,ctx.action.source_definition_id,ctx.actor,'answer',
                        {'ability':ctx.action.display_name,'subject_id':subject,'answers':{},'check_failed':1},'UNTIL_REMOVED')
                return
    if source==VENOM:
        selected=['poison.present',*selected]
    answer(ctx,subject,selected)
    exceptional=data.get('vessel.exceptional_threshold',{}).get('value')
    if source==VESSEL and exceptional is not None and ctx.damage_cache.get('reading_check_total',-1)>=exceptional:
        extra=data.get('vessel.exceptional_facts',{}).get('value',{})
        if extra:
            from ..observer_information import publish
            publish(ctx.engine,ctx.actor,ctx.action.source_definition_id,ctx.actor,'answer',
                {'ability':'Read the Vessel — exceptional result','subject_id':subject,
                 'answers':{k.replace('_',' ').title():v for k,v in extra.items()}},'UNTIL_REMOVED')
    if source==VENOM:
        present=data.get('poison.present',{}).get('value') is True or subject_kind(ctx.engine,subject)=='sample' or native_fact(ctx,subject,'poison.poisoned') is True
        if present and choice(ctx,'profile',['create'],optional=True,labels={'create':'Create an Antidote Profile'},target_id=subject):
            from ..antidote_profiles import create
            create(ctx,subject)
