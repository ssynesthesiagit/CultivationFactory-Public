"""Spirit Bow's source-owned producer and five native progression consumers.

Ownership is sealed at compilation. Manifestation, declaration and fate receipts
are ordinary evented conditions, never inferred from weapon names or narration.
Projected arrows are instantaneous weapon packets, not inventory or Assets.
Real bows keep their physical identity, ammunition and printed weapon properties.
The public acquisition/continuation and observer contracts belong to their
respective interface owners; this module implements only this Open School.
"""
from copy import deepcopy
import hashlib
import json
from . import effect, hook

PARENT = 'tianxia.subpath.qi.spirit_bow_cultivator'
PREFIX = PARENT + '.feature.'
KINDS = ('spirit_bow','seeking_arrow','piercing_shot','arrow_of_fate','heaven_sundering_arrow')
LEVELS = dict(zip(KINDS,(3,6,10,14,18)))
BOW, SEEK, PIERCE, FATE, HEAVEN = [PREFIX+k for k in KINDS]
QI = 'resource:core.qi'
ACTIVE = 'condition:typed.spirit_bow_manifestation'
SEAL = 'condition:typed.spirit_bow_fate'
REVEAL = 'condition:typed.spirit_bow_revealed'
BOUND = 'condition:typed.spirit_bow_bound'
FORMS = {'far':'Far-Seeking Arrow','cover':'Cover-Piercing Arrow','blood':'Blood-Seeking Arrow',
         'revealing':'Revealing Arrow','curving':'Curving Arrow'}
FATES = {'recovery':'Severed Recovery — no healing or Temporary Hit Points',
    'journey':'Weighted Journey — halve Speed and stop willing teleportation; success reduces Speed by 10 feet',
    'resistance':'Broken Resistance — remove one damage Resistance; Immunity remains',
    'thread':"Hunter’s Thread — direction and distance within 1 mile; cannot Hide from you or gain Invisible’s attack Advantage against you"}
FORM_RULES={'far':'Attacking at long range does not impose Disadvantage.',
    'cover':'Ignore Half Cover and Three-Quarters Cover, while Total Cover remains.',
    'blood':'Gain Advantage only if this target took damage since your previous turn began.',
    'revealing':'On hit, Invisible and ordinary visual concealment do not protect the target against you until your next turn starts.',
    'curving':'Go around the selected obstacle no wider than 10 feet along a clear continuous route; measure range along that route. Total Cover from every point still blocks it.'}
OUTCOMES = {'push':'Knock Prone and push 30 feet','stop':'Speed 0 until the end of your next turn',
    'reactions':'No Reactions until the end of your next turn','recovery':'No healing or Temporary Hit Points until the end of your next turn',
    'save':'Disadvantage on its next saving throw before the end of your next turn'}


@effect('spirit_bow_native',harmful=False)
def native_marker(ctx,row):
    return None


def typed(action):
    return (getattr(action,'parameters',None) or {}).get('typed') or {}


def ownership(engine, actor, kind='spirit_bow'):
    return next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,())
        if r.get('block')=='spirit_bow_native' and r.get('kind')==kind),None)


def held(actor, cid=ACTIVE, owner=None):
    return [c for c in actor.conditions.values() if c.condition_id==cid and
        (owner is None or c.source_actor_id==owner.entity_id)]


def remove(engine, actor, cid, source, owner=None):
    from .condition_ownership import remove_instance
    for c in held(actor,cid,owner):
        remove_instance(engine,actor,c.instance_id,source)


@hook('compile_passives')
def seal_ownership(rows, info):
    own=set(info['owned_ids']);cl=int(info['numbers'].get('cl') or 1)
    return [*rows,*[{'block':'spirit_bow_native','kind':kind,'feature_id':PREFIX+kind,
        'trigger_owner':'spirit_bow_native','numbers':dict(info['numbers'])}
        for kind in KINDS if PREFIX+kind in own and cl>=LEVELS[kind]]]


def bow_profiles(info):
    """Public family profiles: projected plus genuinely proficient real bows.

    Consumers: manifestation choices, native Attack/Seeking/Heaven compilers.
    No feature ownership means no profiles; original actions are never edited.
    """
    if BOW not in info['owned_ids'] or int(info['numbers'].get('cl') or 1)<3:return []
    if not any(r.get('type')=='spirit_bow_native' for r in info.get('mechanics',{}).get(BOW,{}).get('effects',[])):return []
    from ..gate2_runtime_models import ActionDefinition
    from .weapon_actions import weapon_attacks
    n=dict(info['numbers']); key=str((info['owner_sheet'].get('identity') or {}).get('key_ability') or 'INT').upper()[:3]
    # The Qi Path can choose Intelligence or Charisma; another Path's key never
    # changes this source. The installed Qi attainment may explicitly name it.
    qi=next((p for p in info['owner_sheet'].get('path_and_subpath',{}).get('paths',[]) if p.get('path_id')=='tianxia.path.qi_cultivation'),{})
    key=str(qi.get('key_ability') or (key if key in ('INT','CHA') else 'INT')).upper()[:3]
    modifier=int(info['mods'].get(key,0));original_key=int(n.get('key_mod') or 0);n['key_mod']=modifier
    level=qi.get('effective_cl',qi.get('attainment'))
    if type(level) is int:n['cl']=min(int(n['cl']),level)
    # An explicitly committed Qi formula applies independently of suppression.
    # Otherwise retain native sourced bonuses while replacing another Path's key.
    fallback_attack=int(n.get('attack_bonus') or int(n['pb'])+original_key)-original_key+modifier
    fallback_dc=int(n.get('save_dc') or 8+int(n['pb'])+original_key)-original_key+modifier
    if type(qi.get('effective_cl')) is int:
        fallback_attack=int(n['pb'])+modifier;fallback_dc=8+fallback_attack
    n['attack_bonus']=int(qi.get('cultivation_attack_modifier',qi.get('attack_bonus',fallback_attack)))
    n['save_dc']=int(qi.get('cultivation_save_dc',qi.get('save_dc',fallback_dc)))
    if int(n['cl'])<3:return []
    projected=ActionDefinition(source_definition_id=f"action:typed.{info['short']}.spirit_bow.projected",
        display_name='Spirit Bow attack',owner_id=info['actor_id'],economy='ACTION',resolution_kind='TYPED',
        target_kind='HOSTILE_ENTITY',range_ft=480,parameters={'expected_damage':5+modifier,'typed':{
        'source':BOW,'numbers':n,'duration':{'kind':'instant'},'riders':[], 'proficient':True,
        'weapon':{'native_profile':1,'proficiency':'simple','damage':{'count':1,'sides':8,'modifier':modifier},'damage_type':'force','damage_types':['force','piercing'],
            'ability':key,'ability_modifier':modifier,'properties':'Two-Handed','weapon_family':'Bow','attack_delivery':'ranged'},
        'range_ft':120,'long_range_ft':480,'strike_penalty_provenance':1,
        'qi_powered':True,'spirit_bow_profile':'projected','effects':[{'type':'attack','attack_kind':'weapon','count':max([1,*[int(r.get('attacks') or 1) for r in info.get('passives',[]) if r.get('block')=='extra_attack']]),
            'on_hit':[{'type':'damage','weapon_damage':True}]}]}})
    out=[('projected',projected)]
    from factory_authoring.starting_kits import item_definition
    for base,t,attack,kind in weapon_attacks(info['actions'],info['actor_id']):
        item=item_definition(str(t.get('source') or '')) or {}
        if kind!='ranged' or not t.get('proficient') or not (str(item.get('weapon_family') or '').lower() in ('bow','bows','projectile / bow proficiency') or item.get('srd_name') in ('Shortbow','Longbow')):continue
        copied=deepcopy(t);copied.update(spirit_bow_profile=base.source_definition_id,weapon_source_id=base.source_definition_id,
            variant_of=base.source_definition_id,strike_penalty_provenance=1,qi_powered=True)
        out.append((base.source_definition_id,base.model_copy(update={'source_definition_id':base.source_definition_id+'.spirit_bow',
            'display_name':'Spirit Bow: '+base.display_name,'parameters':{**base.parameters,'typed':copied}})))
    return out


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    profiles=bow_profiles(info)
    if not profiles:return None
    own={sid for sid in info['owned_ids'] if not sid.startswith(PREFIX) or any(r.get('type')=='spirit_bow_native' for r in info.get('mechanics',{}).get(sid,{}).get('effects',[]))};n=typed(profiles[0][1])['numbers'];key_ability=typed(profiles[0][1])['weapon']['ability'];cl=int(n.get('cl') or 1);out=[]
    def make(suffix,label,source,economy,effects,target='SELF',range_ft=None,cost=0,**params):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.spirit_bow.{suffix}",display_name=label,
            owner_id=info['actor_id'],economy=economy,resolution_kind='TYPED',target_kind=target,range_ft=range_ft,
            costs=((QI,cost),) if cost else (),parameters={'typed':{'source':source,'numbers':dict(n),'effects':effects,
            'riders':[],'duration':{'kind':'instant'}},'expected_damage':0,'spirit_bow_key_ability':key_ability,**params})
    for identity,base in profiles:
        name='Projected Spirit Bow' if identity=='projected' else base.display_name.removeprefix('Spirit Bow: ')
        key=hashlib.sha256(identity.encode()).hexdigest()[:12]
        out.append(make('manifest.'+key,'Manifest Spirit Bow: '+name,BOW,'BONUS_ACTION',
            [{'type':'spirit_bow_manifest','profile':identity}],cost=1,spirit_bow_manifest=identity,
            description='Bonus Action, 1 Qi: manifest a projected bow or empower this proficient, wielded real bow for 1 hour. Replaces your previous Spirit Bow. Projected bow: 120/480 feet, 1d8 Force or Piercing plus your Qi key ability, Two-Handed, no physical ammunition.'))
        for form in ('',*FORMS) if SEEK in own and cl>=6 else ('',):
            row=deepcopy(typed(base));row['seeking_form']=form
            # Preserve the real Attack action's Extra Attack; only the first gets Seeking.
            params={**base.parameters,'typed':row,'spirit_bow_attack':1,
                'description':'Action: one Spirit Bow attack using the manifested profile.'+(' Spend 1 Qi for '+FORMS[form]+'; once per turn, before rolling. '+FORM_RULES[form] if form else '')}
            out.append(base.model_copy(update={'source_definition_id':base.source_definition_id+('.seek.'+form if form else ''),
                'display_name':base.display_name+(' + '+FORMS[form] if form else ''),
                'costs':tuple(base.costs)+(((QI,1),) if form else ()), 'parameters':params}))
        if HEAVEN in own and cl>=18:
            row=deepcopy(typed(base));row.update(source=HEAVEN,heaven_sundering=1,seeking_form='',range_ft=max(300,int(row.get('range_ft') or 0)),
                long_range_ft=max(300,int(row.get('range_ft') or 0)))
            attack=row['effects'][0];attack['count']=1
            attack['on_hit'] += [{'type':'damage','applies_to':'target','dice':{'count':10,'sides':10},'damage_types':['force']},
                {'type':'save','ability':'CON','on_fail':[{'type':'spirit_bow_heaven_outcome'}],
                'on_success':[{'type':'condition','condition':'spirit_bow_heaven','expires_on':'START_OF_TARGET_NEXT_TURN',
                    'applies_to':'target','condition_data':{'rule':{'no_reactions':True},'label':'Heaven-Sundering Arrow: no Reactions until your next turn starts'}}]}]
            out.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'.heaven',
                'display_name':'Heaven-Sundering Arrow: '+name,'range_ft':row['long_range_ft'], 'costs':((QI,8),),
                'parameters':{**base.parameters,'typed':row,'spirit_bow_attack':1,'description':'Action, 8 Qi, once per scene: one Spirit Bow attack. Ignore partial cover, long-range Disadvantage and ordinary Force/Piercing Resistance. On hit add 10d10 Force, then a Constitution save and a chosen consequence. Immunity and permanent artifact defenses remain.'}}))
        if identity!='projected' and cl>=9 and 'tianxia.path.qi_cultivation.feature.domain_armament' in own:
            domain=deepcopy(typed(base));weapon=domain['weapon'];count=3 if cl>=17 else 2 if cl>=13 else 1
            if count*8>int(weapon['damage'].get('count') or 1)*int(weapon['damage'].get('sides') or 1):
                weapon['damage'].update(count=count,sides=8)
            weapon.update(ability=key_ability,ability_modifier=int(n['key_mod']),attack_delivery='melee')
            weapon['damage']['modifier']=int(n['key_mod'])+int(domain.get('magic_bonus') or 0)
            domain.update(source='tianxia.path.qi_cultivation.feature.domain_armament',numbers={**n,'attack_bonus':int(n['attack_bonus'])+int(domain.get('magic_bonus') or 0)},range_ft=5,long_range_ft=None)
            domain['effects'][0]['count']=1
            out.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'.domain_armament',
                'display_name':'Domain Armament: Bound Spirit Bow Attack','economy':'BONUS_ACTION','range_ft':5,
                'parameters':{**base.parameters,'typed':domain,'spirit_bow_attack':1,'spirit_bow_domain_attack':identity,
                    'description':'Bonus Action: the floating bound bow in Assault Mode attacks a creature within 5 feet, using the greater of its normal dice or your Domain Armament dice, your Qi key ability and its printed item bonuses.'}}))
    if SEEK in own and cl>=6:
        out.append(make('curving.obstacle','Curving Arrow: Choose Obstacle',SEEK,'NONE',
            [{'type':'spirit_bow_obstacle'}],target='CELL',range_ft=480,spirit_bow_obstacle=1,
            ai_requires_perceived_destination=True,
            description='Choose the mapped obstacle for Curving Arrow before attacking, no action or Qi cost. It must be at most 10 feet wide. The later paid arrow needs a clear continuous path, measured along the route, and cannot cross sealed barriers or Total Cover.'))
    if cl>=9 and 'tianxia.path.qi_cultivation.feature.domain_armament' in own:
        for mode,cost in (('manifest',1),('release',0)):
            out.append(make('bound.'+mode,('Manifest' if mode=='manifest' else 'Release')+' Bound Spirit Bow',BOW,'BONUS_ACTION',
                [{'type':'spirit_bow_release','mode':mode}],target='CELL',range_ft=30 if mode=='manifest' else 60,cost=cost,
                spirit_bow_release=mode,description='Bonus Action: move the same bound real bow from your hands to a legal floating point. Manifesting costs 1 Qi for 1 hour; later release retains that clock. Requires a clear physical path and Domain Armament control.'))
        out.append(make('bound.call','Call Bound Spirit Bow',BOW,'BONUS_ACTION',[{'type':'spirit_bow_call'}],
            spirit_bow_call=1,description='Bonus Action: call your floating bound bow into two free hands along a clear physical path. The bond and original one-hour manifestation clock remain.'))
    if PIERCE in own and cl>=10:
        for kind in ('force','piercing'):
            damage={'type':'damage','applies_to':'target','dice':{'count':6,'sides':8},'damage_types':[kind]}
            a=make('piercing.'+kind,'Piercing Shot: '+kind.title(),PIERCE,'ACTION',
                [{'type':'piercing_area','ignore_partial_cover':True,'double_object_kinds':['unattended','temporary_barrier','vehicle','structure','formation_anchor'],'effects':[{'type':'save','ability':'DEX',
                 'on_fail':[damage],'on_success':[{'type':'half_damage','applies_to':'target','damage_types':[kind]}]}]}],
                target='CELL',range_ft=120,cost=4,spirit_bow_piercing=1,
                description='Action, 4 Qi: 120-foot-long, 5-foot-wide line; Dexterity save, 6d8 damage or half. Ignores partial cover, passes through creatures, doubles object damage and stops at a surviving barrier. This is a technique, not a weapon attack.')
            t=typed(a);t['area']={'shape':'line','size_ft':120,'width_ft':5};t['area_recipient']='all'
            out.append(a)
    return out


def real_ready(engine, actor, identity, *, floated=False):
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed
    action=available_weapons(engine,actor).get(identity)
    return action is not None and (floated or weapon_allowed(engine,actor,action) is not False)


@hook('candidate_allowed')
def candidates(engine,actor,candidate,action):
    if action is None:return None
    p=action.parameters;t=typed(action);identity=p.get('spirit_bow_manifest')
    if identity:return identity=='projected' or real_ready(engine,actor,identity)
    if p.get('spirit_bow_release'):
        from ..terrain_occlusion import segment_clear
        from .qi_path import armament_condition
        b=held(actor,BOUND)
        if not b or candidate.destination is None or held(actor,'condition:typed.spirit_bow_floating'):return False
        window=held(actor,'condition:typed.spirit_bow_domain_lifetime')
        if (p['spirit_bow_release']=='manifest')==bool(window):return False
        point=candidate.destination
        return real_ready(engine,actor,b[0].data['profile']) and point!=actor.position and not any(
            point in [a.position] for a in engine.state.actors.values() if a.active) and engine.grid.volume_legal(point) and segment_clear(engine.grid,actor.position,point,physical=True)
    if p.get('spirit_bow_call'):
        from .hand_occupancy import free_hands
        from .qi_path import armament_point
        from ..terrain_occlusion import segment_clear
        from ..gate2_runtime_models import Position
        return bool(held(actor,'condition:typed.spirit_bow_floating') and len(free_hands(engine,actor))>=2 and segment_clear(engine.grid,Position(x=armament_point(actor)[0],y=armament_point(actor)[1]),actor.position,physical=True))
    if p.get('spirit_bow_obstacle'):return bool(candidate.destination and obstacle(engine,candidate.destination))
    if p.get('armament')=='attack' and held(actor,'condition:typed.spirit_bow_floating'):return False
    if not p.get('spirit_bow_attack'):return None
    if p.get('spirit_bow_domain_attack') and not candidate.metadata.get('effect_origin'):return False
    active=held(actor)
    if not active or active[0].data['profile']!=t.get('spirit_bow_profile'):return False
    if t.get('seeking_form') and actor.turn_flags.get('spirit_bow_seeking'):return False
    if t.get('seeking_form')=='curving':
        from ..shot_geometry import route
        target=engine.state.actors.get(next(iter(candidate.target_ids),''))
        if target is None:return False
        from ..target_knowledge import knowledge
        known=knowledge(engine,actor,target,action)
        if known is None:return False
        aim=target if known.mode=='DIRECT' else target.model_copy(update={'position':known.position})
        if not route(engine,actor,aim,action):return False
    if t.get('heaven_sundering') and held(actor,'condition:typed.spirit_bow_scene_use'):return False
    if t.get('heaven_sundering') and held(actor,'condition:typed.spirit_bow_floating') and not candidate.metadata.get('effect_origin'):return False
    identity=t['spirit_bow_profile']
    if identity=='projected':
        from .hand_occupancy import free_hands
        return len(free_hands(engine,actor))>=2
    return real_ready(engine,actor,identity,floated=bool(floating(engine,actor,action)))


@effect('spirit_bow_manifest',harmful=False)
def manifest(ctx,row):
    from .effect_durations import round_token
    remove(ctx.engine,ctx.actor,ACTIVE,ctx.source)
    ctx.engine._apply_condition(ctx.actor,ACTIVE,ctx.source,ctx.actor.entity_id,expires_on=round_token(ctx.engine,600),
        data={'profile':row['profile'],'source_cl':int(ctx.numbers.get('cl') or 1),'label':'Spirit Bow: manifested for 1 hour; one bow at a time'})


@hook('weapon_attack_ability')
def empowered_ability(ctx,attack):
    from .weapon_hits import weapon_identity
    active=held(ctx.actor)
    if not ownership(ctx.engine,ctx.actor) or not active or active[0].data['profile']=='projected':return None
    if weapon_identity(ctx)!=active[0].data['profile']:return None
    profile=next((a for a in ctx.engine.action_catalog.values() if a.owner_id==ctx.actor.entity_id and a.parameters.get('spirit_bow_manifest')),None)
    if profile is None:return None
    return {'ability':profile.parameters['spirit_bow_key_ability'],'modifier':int(typed(profile)['numbers'].get('key_mod') or 0)}


@hook('attack_mode_removed')
def mode_removal(engine,actor,target,ranged):
    from .attack_scope import current
    frame=current(engine);out=[]
    if frame and frame['actor_id']==actor.entity_id:
        t=typed(engine.action_catalog.get(frame['source']))
        if t.get('spirit_bow_profile') and (t.get('seeking_form')=='far' and not actor.turn_flags.get('spirit_bow_seeking') or t.get('heaven_sundering')):out.append('DISADVANTAGE:long_range')
    if held(target,REVEAL,actor):out+=['DISADVANTAGE:invisible','DISADVANTAGE:obscured']
    return out or None


@hook('cover_reduction')
def cover_reduction(engine,actor,target,cover):
    from ..shot_geometry import action
    t=typed(action(engine,actor))
    return 2 if cover<=5 and t.get('spirit_bow_profile') and (t.get('seeking_form')=='cover' and not actor.turn_flags.get('spirit_bow_seeking') or t.get('heaven_sundering')) else None


@hook('attack_mode')
def blood_and_declaration(ctx,target):
    if not ctx.typed.get('spirit_bow_profile'):return None
    from .rider_choices import pick
    cache=ctx.damage_cache
    if 'spirit_bow_declared_fate' not in cache:
        choice=[]
        if ownership(ctx.engine,ctx.actor,'arrow_of_fate') and not ctx.actor.turn_flags.get('spirit_bow_fate') and ctx.actor.resources.get(QI,0)>=3:
            choice=pick(ctx.engine,ctx.actor,'spirit_bow_fate','Arrow of Fate',list(FATES),subject=target,intent=ctx.intent,
                labels=FATES,prompt=f'Arrow of Fate: declare a Fate Seal before {ctx.action.display_name} against {target.display_name}. Pay 3 Qi only on a hit; once per turn. Failed Charisma save: 1 minute with end-turn saves; success: until your next turn starts. Or decline.')
        cache['spirit_bow_declared_fate']=choice[0] if choice else ''
    if ctx.typed.get('seeking_form')=='blood' and not ctx.actor.turn_flags.get('spirit_bow_seeking'):
        turns=[e.sequence for e in ctx.engine.events if e.event_type=='TURN_STARTED' and e.actor_id==ctx.actor.entity_id]
        cutoff=turns[-2] if len(turns)>=2 else -1
        if any(e.event_type=='DAMAGE_COMMITTED' and e.sequence>cutoff and target.entity_id in e.target_ids and int(e.payload.get('hp_damage') or 0)+int(e.payload.get('temporary_hp_absorbed') or 0)>0 for e in ctx.engine.events):return 'ADVANTAGE'
    return None


@hook('attack_roll_finished')
def spent_arrow(ctx,target,attack,roll_id):
    if not roll_id or not ctx.typed.get('spirit_bow_profile'):return
    ctx.damage_cache['spirit_bow_roll_count']=int(ctx.damage_cache.get('spirit_bow_roll_count',0))+1
    if ctx.typed.get('seeking_form'):ctx.actor.turn_flags['spirit_bow_seeking']=1
    if ctx.typed.get('heaven_sundering') and not held(ctx.actor,'condition:typed.spirit_bow_scene_use'):
        ctx.engine._apply_condition(ctx.actor,'condition:typed.spirit_bow_scene_use',HEAVEN,ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED',data={'label':'Heaven-Sundering Arrow used in this scene'})


@hook('attack_result')
def arrow_hit(ctx,target,hit,critical):
    if not ctx.typed.get('spirit_bow_profile'):return
    if not hit:
        # Native concealment misses are qualifying attacks even when the
        # concealment gate prevents a d20. Canceled aims never reach this hook.
        if ctx.typed.get('seeking_form'):ctx.actor.turn_flags['spirit_bow_seeking']=1
        ctx.damage_cache['spirit_bow_declared_fate']=''
        return
    if ctx.typed.get('seeking_form')=='revealing' and ctx.damage_cache.get('spirit_bow_roll_count')==1:
        ctx.engine._apply_condition(target,REVEAL,ctx.source,ctx.actor.entity_id,expires_on='START_OF_SOURCE_NEXT_TURN',
            data={'label':f'Revealing Arrow: Invisible and ordinary visual concealment do not protect you against {ctx.actor.display_name} until their next turn starts'})


@hook('after_hit_effects')
def fate_after_packets(ctx,target,kind):
    # The chosen type must actually have been dealt by this hit, including
    # explicitly attached packets such as Heaven-Sundering's extra Force.
    if not ctx.typed.get('spirit_bow_profile'):return
    seal=ctx.damage_cache.get('spirit_bow_declared_fate')
    if not seal or ctx.actor.turn_flags.get('spirit_bow_fate') or ctx.actor.resources.get(QI,0)<3:return
    from .. import typed_executor as te
    from .rider_choices import pick
    damage_types=[]
    for event in reversed(ctx.engine.events):
        if event.event_type=='ATTACK_ROLLED' and event.actor_id==ctx.actor.entity_id:break
        if event.event_type in ('DAMAGE_ROLLED','DAMAGE_COMMITTED') and event.actor_id==ctx.actor.entity_id and target.entity_id in event.target_ids:
            kind=event.payload.get('damage_type')
            if kind:damage_types.append(kind)
    if not damage_types:
        damage_types=[str((ctx.typed.get('weapon') or {}).get('damage_type') or 'force')]
    kind=''
    if seal=='resistance':
        kinds=sorted({str(k).lower() for k in damage_types})
        picked=pick(ctx.engine,ctx.actor,'spirit_bow_fate_type','Broken Resistance',kinds,labels={k:k.title() for k in kinds},
            subject=target,optional=False,intent=ctx.intent,prompt=f'Broken Resistance: choose one damage type dealt by the Spirit Bow hit on {target.display_name}. Immunity is unchanged.')
        kind=picked[0]
    ctx.engine._spend_resource(ctx.actor,QI,3,FATE);ctx.actor.turn_flags['spirit_bow_fate']=1
    sub=te.Context(ctx.engine,ctx.actor,ctx.action,ctx.intent,{**ctx.typed,'source':FATE},[target],target,ctx.damage_cache)
    te.run_effects(sub,[{'type':'save','ability':'CHA','on_fail':[{'type':'spirit_bow_fate_apply','seal':seal,'damage_type':kind,'failed':1}],
        'on_success':[{'type':'spirit_bow_fate_apply','seal':seal,'damage_type':kind,'failed':0}]}])


@effect('spirit_bow_fate_apply',harmful=True)
def fate_apply(ctx,row):
    from .effect_durations import round_token
    target=ctx.target
    if target is None:return
    seal=row['seal'];failed=bool(row['failed']);rule={}
    if seal=='recovery':rule={'healing_denied':True,'temp_hp_denied':True}
    if seal=='journey':rule={'speed_halved':True} if failed else {}
    remove(ctx.engine,target,SEAL,FATE,ctx.actor)
    data={'seal':seal,'damage_type':row.get('damage_type',''),'rule':rule,
        'label':FATES[seal]+(': 1 minute, repeat Charisma save at each turn end' if failed else ': until the source’s next turn starts'),
        'source_cl':int(ctx.numbers.get('cl') or 1)}
    if seal=='journey' and not failed:data.update(speed_penalty_group='spirit_bow_weighted_journey',speed_penalty_ft=10)
    if failed:data['repeat_save']={'ability':'CHA','dc':int(ctx.numbers.get('save_dc') or 10),'when':'end'}
    ctx.engine._apply_condition(target,SEAL,FATE,ctx.actor.entity_id,
        expires_on=round_token(ctx.engine,10) if failed else 'START_OF_SOURCE_NEXT_TURN',data=data)
    if seal=='journey' and failed:
        condition=held(target,SEAL,ctx.actor)[-1]
        ctx.engine._add_modifier(target,FATE,'speed_halved','ADD',1,'SELF',expires_on='UNTIL_REMOVED',source_actor_id=ctx.actor.entity_id,application_id=condition.instance_id)


@hook('resistance_ignored')
def resistance(engine,kind,t,owner_id,target):
    if target is None:return None
    if any(c.data.get('seal')=='resistance' and c.data.get('damage_type','').upper()==str(kind).upper() for c in held(target,SEAL)):return True
    if t.get('heaven_sundering') and str(kind).upper() in ('FORCE','PIERCING') and not permanent_artifact_resistance(engine,target,kind):return True
    return None


@effect('spirit_bow_heaven_outcome',harmful=True)
def heaven_outcome(ctx,row):
    from .. import typed_executor as te
    from .rider_choices import pick
    chosen=pick(ctx.engine,ctx.actor,'spirit_bow_heaven','Heaven-Sundering Arrow',list(OUTCOMES),labels=OUTCOMES,
        subject=ctx.target,optional=False,intent=ctx.intent,prompt=f'Heaven-Sundering Arrow: {ctx.target.display_name} failed the Constitution save. Choose one consequence; no additional Qi cost.')
    choice=chosen[0];duration='until_end_of_your_next_turn'
    if choice=='push':
        te.run_effects(ctx,[{'type':'condition','condition':'prone','applies_to':'target'},
            {'type':'movement','applies_to':'target','distance_ft':30,'direction':'away'}]);return
    if choice=='stop':rule={'speed_zero':True}
    elif choice=='reactions':rule={'no_reactions':True}
    elif choice=='recovery':rule={'healing_denied':True,'temp_hp_denied':True}
    else:rule={}
    te.run_effects(ctx,[{'type':'condition','condition':'spirit_bow_heaven','applies_to':'target','duration':duration,
        'condition_data':{'rule':rule,'next_save':int(choice=='save'),'label':'Heaven-Sundering Arrow: '+OUTCOMES[choice]}}])


@hook('save')
def next_save(ctx,target,ability,named):
    return {'modes':['DISADVANTAGE']} if any(c.data.get('next_save') for c in held(target,'condition:typed.spirit_bow_heaven')) else None


@hook('save_final')
def consume_next_save(ctx,target,ability,named,failed):
    from .condition_ownership import remove_instance
    for c in held(target,'condition:typed.spirit_bow_heaven'):
        if c.data.get('next_save'):remove_instance(ctx.engine,target,c.instance_id,ctx.source)


@hook('masked_conditions')
def scoped_masks(engine,viewer,target):
    reveal=held(target,REVEAL,viewer)
    thread=any(c.data.get('seal')=='thread' for c in held(target,SEAL,viewer))
    result={}
    if reveal or thread:
        result[target.entity_id]={iid for iid,c in target.conditions.items() if c.condition_id in
            (('condition:typed.invisible','condition:typed.hidden') if reveal else ('condition:typed.hidden',))}
    if any(c.data.get('seal')=='thread' for c in held(viewer,SEAL,target)):
        result[viewer.entity_id]={iid for iid,c in viewer.conditions.items() if c.condition_id=='condition:typed.invisible'}
    return result or None


@hook('observer_information_rows')
def hunters_information(engine,viewer):
    from ..observer_information import direction
    out=[]
    for target in engine.state.actors.values():
        if any(c.data.get('seal')=='thread' for c in held(target,SEAL,viewer)) and engine._distance_actor_to_actor(viewer,target)<=5280:
            out.append({'kind':'direction','source_id':FATE,'viewer_id':viewer.entity_id,
                'details':{'target':target.display_name,'direction':direction(viewer.position,target.position),
                    'distance_ft':engine._distance_actor_to_actor(viewer,target)}})
    return out or None


def floating(engine,actor,action):
    from .qi_path import armament_condition,armament_point
    b=held(actor,BOUND);arm=armament_condition(actor)
    if not b or arm is None or not held(actor,'condition:typed.spirit_bow_floating'):return None
    if typed(action).get('heaven_sundering'):
        if typed(action).get('spirit_bow_profile')!=b[0].data['profile'] or arm.data.get('mode')!='assault':return None
    if action.parameters.get('spirit_bow_domain_attack') and (action.parameters['spirit_bow_domain_attack']!=b[0].data['profile'] or arm.data.get('mode')!='assault'):return None
    if not (typed(action).get('heaven_sundering') or action.parameters.get('spirit_bow_piercing') or action.parameters.get('spirit_bow_domain_attack')):return None
    from ..alternative_payments import owned
    if action.parameters.get('spirit_bow_piercing') and not owned(engine,actor,'tianxia.path.qi_cultivation.feature.domain_armament_link'):return None
    if not real_ready(engine,actor,b[0].data['profile'],floated=True):return None
    from ..gate2_runtime_models import Position
    x,y=armament_point(actor);position=Position(x=x,y=y)
    from .qi_path import armament_control_range
    from ..terrain_occlusion import segment_clear
    if engine.grid.distance_ft(actor.position,position)>armament_control_range(engine,actor):return None
    if not segment_clear(engine.grid,actor.position,position,physical=True):return None
    from .. import zones
    ours=int((ownership(engine,actor) or {}).get('numbers',{}).get('cl') or 1)
    for zone in zones.typed_zones(engine):
        rules=zone.trigger_profile.get('rule') or {}
        if not (rules.get('no_teleport') or rules.get('no_extradimensional_movement') or rules.get('no_qi_transmission')):continue
        if int((zone.trigger_profile.get('numbers') or {}).get('cl') or 0)>=ours and zones.actor_inside_zone(engine,actor,zone)!=zones.actor_inside_zone(engine,actor,zone,position):return None
    return position


@hook('effect_origins')
def remote_origin(engine,actor,action):
    p=floating(engine,actor,action)
    return [{'id':'spirit_bow.bound','label':'Floating bound Spirit Bow','position':p.model_dump(mode='json')}] if p else None


# Native Open School acquisition: this source has no restricted-access price.
# The caller supplies only the source ID; attainment comes from the installed
# Path ledger and the compiler publishes only the earned five-row progression.
def source_state(session,actor_id):
    return session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{})


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,sheet):
    if source!=PARENT:return None
    from ..journey import require,integer
    actor=session.state['actors'][actor_id];paths=deepcopy(sheet.get('path_and_subpath') or {})
    require(payload=={},'Spirit Bow is an Open School: choose this school without supplying feature grants or a replacement progression.')
    require(not actor['incapacitated'],'An incapacitated creature cannot acquire this school.')
    qi=next((p for p in paths.get('paths',[]) if p.get('path_id')=='tianxia.path.qi_cultivation'),{})
    level=next((qi[k] for k in ('attainment','owning_path_level','effective_cl') if integer(qi.get(k),1)),None)
    require(level is not None and 3<=level<=int(sheet.get('identity',{}).get('cultivation_level') or 0),
        'Spirit Bow requires actual Qi Path attainment of at least 3 in the installed Path ledger.')
    selections=set(paths.get('subpath_record_ids') or [])
    if paths.get('subpath_record_id'):selections.add(paths['subpath_record_id'])
    qi_selections={s for s in selections if s.startswith('tianxia.subpath.qi.')}
    ids=set(paths.get('path_feature_record_ids') or [])|set(paths.get('source_granted_subpath_feature_record_ids') or [])
    require(qi_selections<={PARENT} and not any(s.startswith('tianxia.subpath.qi.') and not s.startswith(PREFIX) for s in ids),
        'Spirit Bow cannot coexist with another Qi Subpath or its replacement progression.')
    earned=[PREFIX+k for k in KINDS if LEVELS[k]<=level]
    old=source_state(session,actor_id)
    require(earned!=old.get('earned'),'This exact Spirit Bow progression was already acquired; limits and clocks remain spent.')
    paths['subpath_record_ids']=sorted(selections|{PARENT})
    paths['subpath_record_id']=PARENT
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        paths[key]=list(dict.fromkeys([*paths.get(key,[]),*earned]))
    paths['bindings']=[b for b in paths.get('bindings',[]) if b.get('path_id')!='tianxia.path.qi_cultivation']+[
        {'path_id':'tianxia.path.qi_cultivation','subpath_id':PARENT}]
    result=deepcopy(sheet);result['path_and_subpath']=paths
    receipt=hashlib.sha256(json.dumps({'actor':actor_id,'source':source,'level':level,'earned':earned,'clock':int(session.clock())},sort_keys=True).encode()).hexdigest()
    actor.setdefault('source_states',{})[PARENT]={**old,'earned':earned,'acquisition_id':receipt,
        'clock_journey':session.state['journey_id'],'clock_checkpoint':int(session.clock())}
    session.emit('SOURCE_ACQUIRED',actor_id,source=source,acquisition_id=receipt,path_attainment=level,earned=earned)
    return {'sheet':result,'acquisition_id':receipt}


@hook('journey_source_sheet')
def acquired_overlay(sheet,session,actor_id):
    state=source_state(session,actor_id)
    if not state.get('earned'):return None
    current=sheet.get('path_and_subpath') or {}
    selected=set(current.get('subpath_record_ids') or [])
    if current.get('subpath_record_id'):selected.add(current['subpath_record_id'])
    # A current native replacement build supersedes this old acquisition.
    # Continuing a journey may not re-grant the replaced parent progression.
    if any(s.startswith('tianxia.subpath.qi.') and s!=PARENT for s in selected):return None
    result=deepcopy(sheet);p=result.setdefault('path_and_subpath',{})
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        p[key]=list(dict.fromkeys([*p.get(key,[]),*state['earned']]))
    p['subpath_record_ids']=list(dict.fromkeys([*p.get('subpath_record_ids',[]),PARENT]))
    p['subpath_record_id']=PARENT
    return result


@hook('journey_options')
def journey_options(session,actor_id):
    state=source_state(session,actor_id);actor=session.state['actors'][actor_id]
    if BOW not in state.get('earned',[]) or actor['incapacitated'] or not any(r.get('block')=='spirit_bow_native' and r.get('kind')=='spirit_bow' for r in actor['bundle'].get('typed_passives',[])):return None
    return [{'id':'spirit_bow.manifest','kind':'spirit_bow_manifest','label':'Manifest projected Spirit Bow (1 Qi, 1 hour)',
        'payload':{'profile':'projected'},'auto_select':0}]


@hook('journey_command')
def journey_manifest(session,actor_id,kind,payload):
    if kind!='spirit_bow_manifest':return None
    from ..journey import require
    actor=session.state['actors'][actor_id];state=source_state(session,actor_id)
    require(BOW in state.get('earned',[]) and not actor['incapacitated'],'This creature has not acquired Spirit Bow or cannot act.')
    profiles={typed_action.get('parameters',{}).get('spirit_bow_manifest') for typed_action in actor['bundle']['action_catalog']}
    require(set(payload)=={'profile'} and payload['profile'] in profiles,'Choose an acquired Spirit Bow profile.')
    require(payload['profile']=='projected' or state.get('wielded')==payload['profile'] and payload['profile'] in journey_real_profiles(actor),'Empowerment requires a currently possessed, wielded real bow.')
    require(actor['resources'].get(QI,0)>=1,'Manifest Spirit Bow costs 1 Qi.')
    actor['resources'][QI]-=1;state['manifestation']={'profile':payload['profile'],'expires_at':int(session.clock())+3600}
    # A Bonus Action outside combat is a committed six-second activity, never
    # an unlimited free out-of-combat resource manipulation.
    session.tick(6)
    session.emit('SPIRIT_BOW_MANIFESTED',actor_id,profile=payload['profile'],expires_at=state['manifestation']['expires_at'],cost=1)
    return True


@hook('journey_elapsed')
def elapsed(session,actor_id,previous,seconds,moving):
    state=source_state(session,actor_id)
    if state:state.update(clock_journey=session.state['journey_id'],clock_checkpoint=int(session.clock()))
    if state.get('manifestation') and session.clock()>=state['manifestation']['expires_at']:
        state.pop('manifestation');session.emit('SPIRIT_BOW_EXPIRED',actor_id)
    f=state.get('floating')
    if f and session.clock()>=f['expires_at']:
        from ..gate2_runtime_models import RuntimeObjectState
        packed=[]
        for row in state.get('bow_objects',[]):
            obj=RuntimeObjectState.model_validate_json(row)
            if not obj.destroyed:obj=obj.model_copy(update={'unattended':True})
            packed.append(obj.model_dump_json())
        state['bow_objects']=packed;state.pop('floating');state.pop('wielded',None)
        session.emit('SPIRIT_BOW_LANDED',actor_id,item=f['profile'],reason='Domain Armament duration expired')


@hook('journey_scene_end')
def new_scene(session,previous,current):
    for actor_id in session.state['actors']:
        state=source_state(session,actor_id)
        if state:state.pop('heaven_used',None)


@hook('journey_combat_bundle')
def combat_bundle(bundle,session,actor_id):
    state=source_state(session,actor_id)
    if not state:return None
    result=deepcopy(bundle);result['spirit_bow_continuation']={
        'manifestation':deepcopy(state.get('manifestation') or {}),
        'seconds':int(session.clock()),'heaven_used':int(state.get('heaven_used',0)),
        'bound':str(state.get('bound') or ''),'bound_profile':str(state.get('bound_profile') or ''),'wielded':str(state.get('wielded') or ''),
        'floating':deepcopy(state.get('floating') or {}),'bow_objects':list(state.get('bow_objects') or []),
        'scene_id':str(session.state.get('scene_id',session.state['journey_id']))}
    return result


@hook('match_initialize')
def initialize(engine):
    from .effect_durations import round_token
    for bundle in getattr(engine,'typed_bundle_documents',()):
        data=bundle.get('spirit_bow_continuation');actor=engine.state.actors.get(bundle['actor_id'])
        if not data or actor is None or not ownership(engine,actor):continue
        if data.get('wielded') and not data.get('floating'):
            from .equipment_hands import set_weapon_readiness
            if data['wielded'] in engine.action_catalog:set_weapon_readiness(engine,actor,data['wielded'],True,source=BOW,source_actor_id=actor.entity_id)
        if data.get('bound'):
            engine._apply_condition(actor,BOUND,BOW,actor.entity_id,expires_on='UNTIL_REMOVED',data={'profile':data['bound'],'object_profile':data.get('bound_profile',''),'label':'Bound real Spirit Bow: same physical item'})
        m=data['manifestation'];remaining=int(m.get('expires_at',0))-data['seconds']
        if remaining>0:
            engine._apply_condition(actor,ACTIVE,BOW,actor.entity_id,expires_on=round_token(engine,(remaining+5)//6),
                data={'profile':m['profile'],'label':'Spirit Bow: continuing its original 1-hour duration'})
        # These are snapshots of the same physical item, never new inventory.
        from ..gate2_runtime_models import RuntimeObjectState
        for packed in data.get('bow_objects',[]):
            obj=RuntimeObjectState.model_validate_json(packed)
            engine._update_object(obj,BOW,actor.entity_id)
            if not obj.destroyed and not (obj.component or {}).get('in_inventory') and (obj.component or {}).get('real_bow') in engine.action_catalog:
                from .equipment_hands import set_weapon_readiness
                set_weapon_readiness(engine,actor,obj.component['real_bow'],False,source=BOW,source_actor_id=actor.entity_id)
        f=data.get('floating') or {}
        if f and int(f.get('expires_at',0))>data['seconds']:
            from .qi_path import ARMED
            for cid,cdata in ((ARMED,json.loads(f['armament'])),('condition:typed.spirit_bow_floating',{'profile':f['profile']})):
                engine._apply_condition(actor,cid,BOW,actor.entity_id,expires_on='UNTIL_REMOVED',data=cdata)
            engine._apply_condition(actor,'condition:typed.spirit_bow_domain_lifetime',BOW,actor.entity_id,
                expires_on=round_token(engine,(int(f['expires_at'])-data['seconds']+5)//6),data={'profile':f['profile']})
        if data['heaven_used']:
            engine._apply_condition(actor,'condition:typed.spirit_bow_scene_use',HEAVEN,actor.entity_id,
                expires_on='UNTIL_REMOVED',data={'label':'Heaven-Sundering Arrow used in this scene'})
    return None


@hook('journey_snapshot_actor')
def continuation_snapshot(actor,session,actor_id,engine):
    if not ownership(engine,actor):return None
    result=actor.model_copy(deep=True)
    stripped={ACTIVE,BOUND,'condition:typed.spirit_bow_scene_use','condition:typed.spirit_bow_domain_lifetime'}
    if held(actor,'condition:typed.spirit_bow_floating'):
        from .qi_path import ARMED
        stripped.update((ARMED,'condition:typed.spirit_bow_floating'))
    result.conditions={iid:c for iid,c in result.conditions.items() if c.condition_id not in stripped}
    return result


@hook('journey_encounter_settled')
def encounter_settled(session,actor_id,engine,actor):
    if not ownership(engine,actor):return
    state=session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(PARENT,{})
    state.update(clock_journey=session.state['journey_id'],clock_checkpoint=int(session.clock()))
    state['heaven_used']=int(bool(held(actor,'condition:typed.spirit_bow_scene_use')))
    from .qi_path import armament_condition
    from .hand_occupancy import weapon_grips
    bond=held(actor,BOUND);state['bound']=bond[0].data['profile'] if bond else ''
    grips=weapon_grips(engine,actor)
    real_profiles={a.parameters.get('spirit_bow_manifest') for a in engine.action_catalog.values() if a.owner_id==actor.entity_id}
    state['wielded']=next((identity for identity in grips if identity in real_profiles),'')
    arm=armament_condition(actor);floated=held(actor,'condition:typed.spirit_bow_floating')
    lifetime=held(actor,'condition:typed.spirit_bow_domain_lifetime')
    if floated and arm and lifetime:
        state['floating']={'profile':floated[0].data['profile'],'armament':json.dumps(arm.data,sort_keys=True),
            'expires_at':int(session.clock())+remaining_seconds(engine,lifetime[0])}
        state.pop('wielded',None)
    else:state.pop('floating',None)
    state['bow_objects']=[o.model_dump_json() for o in engine.state.objects.values() if o.owner_id==actor.entity_id and (o.component or {}).get('real_bow')]
    # A round is six seconds. The encounter advances the original source clock,
    # regardless of how many creatures took a turn or whether the bow was used.
    rounds=max(0,int(engine.state.round_number)-1)
    m=state.get('manifestation')
    if m:
        m['expires_at']-=rounds*6
        if not held(actor):state.pop('manifestation',None)


@hook('event')
def seal_speed_ended(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED' or kwargs.get('payload',{}).get('condition_id')!=SEAL:return
    iid=kwargs['payload'].get('instance_id')
    for target in engine.state.actors.values():
        for mid,m in list(target.modifiers.items()):
            if m.source_definition_id==FATE and m.application_id==iid:
                engine._remove_modifier_instance(target,mid,FATE)


def obstacle(engine,position):
    """Connected mapped solid/opaque footprint, at most two five-foot cells wide."""
    cells=set(engine.grid.blocked)|set(engine.grid.opaque)
    start=(position.x,position.y)
    if start not in cells:
        adjacent=sorted(p for p in cells if max(abs(p[0]-start[0]),abs(p[1]-start[1]))<=1)
        if not adjacent:return ()
        start=adjacent[0]
    connected={start};todo=[start]
    while todo:
        x,y=todo.pop()
        for adjacent in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if adjacent in cells and adjacent not in connected:
                connected.add(adjacent);todo.append(adjacent)
                if max(p[0] for p in connected)-min(p[0] for p in connected)>1 or max(p[1] for p in connected)-min(p[1] for p in connected)>1:return ()
    return tuple(sorted(connected))


@effect('spirit_bow_obstacle',harmful=False)
def select_obstacle(ctx,row):
    from ..journey import require
    cells=obstacle(ctx.engine,ctx.destination)
    require(bool(cells),'Choose one mapped obstacle no wider than 10 feet.')
    remove(ctx.engine,ctx.actor,'condition:typed.spirit_bow_obstacle',ctx.source)
    ctx.engine._apply_condition(ctx.actor,'condition:typed.spirit_bow_obstacle',ctx.source,ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED',data={'cells':[list(p) for p in cells],
            'label':'Curving Arrow: selected one mapped obstacle no wider than 10 feet'})


@hook('sight_path')
def curved_route(engine,actor,target):
    from ..shot_geometry import action,valid,length
    from ..gate2_runtime_models import Position
    from ..action_geometry import point
    current=action(engine,actor)
    if typed(current).get('seeking_form')!='curving' or actor.turn_flags.get('spirit_bow_seeking'):return None
    selected=held(actor,'condition:typed.spirit_bow_obstacle')
    if not selected:return None
    cells=[tuple(p) for p in selected[0].data['cells']]
    if set(obstacle(engine,Position(x=cells[0][0],y=cells[0][1])))!=set(cells):return None
    ring={Position(x=x+dx,y=y+dy,z=actor.position.z) for x,y in cells for dx in (-1,0,1) for dy in (-1,0,1)
        if engine.grid.in_bounds((x+dx,y+dy)) and (x+dx,y+dy) not in cells}
    ring=sorted(ring,key=lambda p:(p.y,p.x));origin=point(engine,actor);routes=[]
    for middle in [(p,) for p in ring]+[(p,q) for p in ring for q in ring if p!=q]:
        row={'source_id':SEEK,'label':'Curving Arrow around the selected 10-foot-or-smaller obstacle',
            'path':[p.model_dump(mode='json') for p in (origin,*middle,target.position)]}
        if valid(engine,actor,target,row):routes.append(row)
    return min(routes,key=lambda r:(length(engine,r),str(r['path']))) if routes else None


@hook('zone_obscuration_ignored')
def revealed_visual_concealment(engine,zone,viewer,target):
    if not held(target,REVEAL,viewer):return None
    profile=zone.trigger_profile
    source_cl=int((profile.get('numbers') or {}).get('cl') or 0)
    ours=ownership(engine,viewer)
    if not ours or source_cl>int(ours['numbers'].get('cl') or 1):return None
    # The authored ordinary visual scope is explicit. A named superior
    # protection, sealed boundary or solid wall never becomes transparent.
    if profile.get('authority') in ('artifact','immortal','secret','absolute') or profile.get('no_extradimensional_movement') or profile.get('blocks_movement'):return None
    if profile.get('obscured') or (profile.get('wall') or {}).get('obscures'):return True
    return None


@hook('object_damage_admission')
def piercing_authority(engine,actor,obj,packets,source,*,area_scope_resolved=False):
    action=engine.action_catalog.get(source)
    if typed(action).get('source')!=PIERCE:return None
    from ..asset_anchor_runtime import source_profile
    from .ability_source import cultivation_check
    profile=source_profile(engine,obj);ours=int(typed(action).get('numbers',{}).get('cl') or 1)
    theirs=profile['source_cl']
    if theirs<ours+3:return None
    owner=engine.state.actors.get(profile['owner'])
    from .ability_source import numbers_of
    dc=int(numbers_of(engine,owner).get('save_dc') or 10+theirs//2) if owner is not None else 10+theirs//2
    return cultivation_check(engine,actor,typed(action)['numbers'],dc,source,'Piercing Shot against the higher-authority barrier')


@hook('effect_resolution_scope')
def remote_payment(ctx,row):
    from contextlib import contextmanager
    from ..action_geometry import record_for
    if not ctx.action.parameters.get('spirit_bow_piercing') or not record_for(ctx.engine,ctx.actor,ctx.source):return None
    @contextmanager
    def paid():
        key='spirit_bow_remote_paid'
        if not ctx.damage_cache.get(key):
            if ctx.actor.resources.get(QI,0)<1:raise ValueError('Domain Armament Link requires 1 additional Qi.')
            ctx.engine._spend_resource(ctx.actor,QI,1,'tianxia.path.qi_cultivation.feature.domain_armament_link')
            ctx.damage_cache[key]=1
        yield
    return paid()


@hook('fact_admission_schema')
def item_binding_facts(session,source,subject,kind):
    if source!=PARENT or kind!='bond_requirements' or BOW not in source_state(session,subject).get('earned',[]):return None
    return {'value_type':'document','maximum_seconds':3600,'authority':'table_owner',
        'description':'The native item owner confirms lawful possession or permission, attunement/prerequisites, sentient-item consent, any external Domain Armament bond, and object_profile (material, size and any printed durability overrides). This declaration grants no item or proficiency.'}


def journey_real_profiles(actor):
    # Actual disarm/theft/breakage receipts survive travel. An inventory entry
    # alone cannot silently recover an item or place a floating bow in hand.
    blocked={}
    for packed in actor.get('encounter_snapshot',{}).get('conditions',{}).values():
        row=json.loads(packed);data=row.get('data') or {}
        if data.get('disables_action'):blocked[data['disables_action']]=1
    state=actor.get('source_states',{}).get(PARENT,{})
    for packed in state.get('bow_objects',[]):
        obj=json.loads(packed);c=obj.get('component') or {}
        if not c.get('in_inventory') and c.get('real_bow'):blocked[c['real_bow']]=1
    return {a['parameters']['spirit_bow_manifest']:a['display_name'].removeprefix('Manifest Spirit Bow: ')
        for a in actor['bundle']['action_catalog'] if a.get('parameters',{}).get('spirit_bow_manifest') not in (None,'projected')
        and a['parameters']['spirit_bow_manifest'] not in blocked}



@hook('journey_options')
def real_item_options(session,actor_id):
    actor=session.state['actors'][actor_id];state=source_state(session,actor_id)
    if BOW not in state.get('earned',[]) or actor['incapacitated'] or not any(r.get('block')=='spirit_bow_native' and r.get('kind')=='spirit_bow' for r in actor['bundle'].get('typed_passives',[])):return None
    out=[]
    for identity,name in journey_real_profiles(actor).items():
        out.append({'id':'spirit_bow.wield.'+identity,'kind':'spirit_bow_wield','label':'Wield '+name,
            'payload':{'profile':identity},'auto_select':0})
        if state.get('wielded')==identity:
            out.append({'id':'spirit_bow.empower.'+identity,'kind':'spirit_bow_manifest','label':'Empower '+name+' (1 Qi, 1 hour)',
                'payload':{'profile':identity},'auto_select':0})
        if state.get('manifestation',{}).get('profile')==identity:
            out.append({'id':'spirit_bow.bind.'+identity,'kind':'spirit_bow_bind','label':'Bind '+name+' (10 uninterrupted minutes; item permission required)',
                'payload':{'profile':identity,'scope':identity},'auto_select':0})
    return out or None


@hook('journey_command')
def real_item_command(session,actor_id,kind,payload):
    if kind not in ('spirit_bow_wield','spirit_bow_bind'):return None
    from ..journey import require
    from ..fact_consent_admission import read
    actor=session.state['actors'][actor_id];state=source_state(session,actor_id)
    require(BOW in state.get('earned',[]) and not actor['incapacitated'],'This creature cannot use Spirit Bow.')
    identity=payload.get('profile');profiles=journey_real_profiles(actor)
    require(identity in profiles,'Choose a proficient real bow from this creature’s actual installed inventory.')
    require(set(payload)==({'profile'} if kind=='spirit_bow_wield' else {'profile','scope'}),'Choose this item and its source-scoped binding declaration.')
    if kind=='spirit_bow_wield':
        # The actual inventory choice is a native ready-item command, never a
        # claim that owning the feature creates or grants a real weapon.
        state['wielded']=identity;session.tick(6)
        session.emit('SPIRIT_BOW_ITEM_WIELDED',actor_id,item=identity)
        return True
    require(state.get('wielded')==identity and state.get('manifestation',{}).get('profile')==identity,
        'Binding requires touching your currently empowered, wielded real Spirit Bow.')
    access=read(session,PARENT,actor_id,'bond_requirements',payload['scope'],actor_id)
    require(access is not None,'The native item owner must record this item’s binding requirements first.')
    value=access['value']
    require(set(value)=={'item','lawful_access','attunement_ready','sentient_consent','unbound','object_profile'} and value['item']==identity
        and all(type(value[k]) is int and value[k]==1 for k in ('lawful_access','attunement_ready','sentient_consent','unbound')),
        'Binding requires this actual item, lawful ownership or permission, met attunement/prerequisites, sentient consent, and no other Domain Armament bond.')
    require(not any(source_state(session,aid).get('bound')==identity for aid in session.state['actors'] if aid!=actor_id),
        'This actual item is already bound to another creature.')
    require(any(a['parameters'].get('armament')=='manifest' for a in actor['bundle']['action_catalog']),
        'Binding requires the attained CL9 Domain Armament feature.')
    require(access['expires_at']>=int(session.clock())+600,'Binding permission must remain valid throughout the ten-minute procedure.')
    body=value['object_profile']
    from ..object_rules import rules,stats
    table=rules()
    require(isinstance(body,dict) and {'material','size'}<=set(body)<=
        {'material','size','resilient','ac','hp','threshold','immune','resist','vulnerable','source_cl'},
        'The item owner must provide its material, size and optional printed object statistics.')
    require(body['material'] in table['materials'] and body['size'] in table['sizes'],'Choose native object material and size entries.')
    require(all(type(body[k]) is int and body[k]>=0 for k in ('ac','hp','threshold','source_cl') if k in body) and
        all(k not in body or isinstance(body[k],list) and all(type(v) is str for v in body[k]) for k in ('immune','resist','vulnerable')),
        'Object statistics require nonnegative integers and explicit damage-type lists.')
    stats({'kind':'custom',**body})  # validate through the existing native rules reader
    session.tick(600);state['bound']=identity;state['bound_profile']=json.dumps(body,sort_keys=True)
    session.emit('SPIRIT_BOW_ITEM_BOUND',actor_id,item=identity,source_rule=BOW,declaration=access['receipt_id'],seconds=600)
    return True


@effect('spirit_bow_release',harmful=False)
def release_bound(ctx,row):
    from .qi_path import ARMED
    from .effect_durations import round_token
    from .equipment_hands import set_weapon_readiness
    b=held(ctx.actor,BOUND)[0];point=ctx.destination
    if row['mode']=='manifest':
        ctx.engine._apply_condition(ctx.actor,'condition:typed.spirit_bow_domain_lifetime',BOW,ctx.actor.entity_id,
            expires_on=round_token(ctx.engine,600),data={'profile':b.data['profile'],'label':'Bound Spirit Bow Domain Armament: original 1-hour clock'})
    remove(ctx.engine,ctx.actor,ARMED,ctx.source)
    ctx.engine._apply_condition(ctx.actor,ARMED,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'mode':'assault','item_identity':b.data['profile'],'ax':point.x,'ay':point.y,'reach_ft':60 if any(a.owner_id==ctx.actor.entity_id and a.parameters.get('armament_control_ft')==60 for a in ctx.engine.action_catalog.values()) else 30,
            'label':'Floating bound Spirit Bow (same real item)'})
    set_weapon_readiness(ctx.engine,ctx.actor,b.data['profile'],False,source=ctx.source,source_actor_id=ctx.actor.entity_id)
    ctx.engine._apply_condition(ctx.actor,'condition:typed.spirit_bow_floating',BOW,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'profile':b.data['profile'],'label':'Real Spirit Bow floating; not also in hand'})
    publish_real_bow_object(ctx.engine,ctx.actor,b.data['profile'],point,ctx.source)


@effect('spirit_bow_call',harmful=False)
def call_bound(ctx,row):
    from .equipment_hands import set_weapon_readiness
    from .qi_path import ARMED
    b=held(ctx.actor,BOUND)[0]
    carry_real_bow_object(ctx.engine,ctx.actor,b.data['profile'],ctx.source)
    remove(ctx.engine,ctx.actor,'condition:typed.spirit_bow_floating',ctx.source)
    remove(ctx.engine,ctx.actor,ARMED,ctx.source)
    set_weapon_readiness(ctx.engine,ctx.actor,b.data['profile'],True,source=ctx.source,source_actor_id=ctx.actor.entity_id)


@hook('weapon_remote_control')
def remote_weapon(engine,actor,action,identity):
    if (typed(action).get('heaven_sundering') or action.parameters.get('spirit_bow_domain_attack')) and floating(engine,actor,action) is not None:
        return bool(held(actor,BOUND) and held(actor,BOUND)[0].data['profile']==identity)
    return None


@hook('candidate_allowed')
def remote_funds(engine,actor,candidate,action):
    if action is None or not action.parameters.get('spirit_bow_piercing'):return None
    if candidate.metadata.get('effect_origin'):
        return actor.resources.get(QI,0)>=5
    return None


@hook('event')
def domain_window_expired(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED' or kwargs.get('payload',{}).get('condition_id')!='condition:typed.spirit_bow_domain_lifetime':return
    for aid in kwargs.get('target_ids',()):
        actor=engine.state.actors.get(aid)
        if actor is not None:land_bound_item(engine,actor,BOW)


RECEIVED=(SEAL,REVEAL,'condition:typed.spirit_bow_heaven')


def remaining_seconds(engine,condition):
    """Normalize this source's existing native deadline at encounter settlement."""
    from .effect_durations import parse_round,parse
    clock=parse_round(condition.expires_on)
    if clock:return max(1,clock[0]-int(engine.state.round_number))*6
    turn=parse(condition.expires_on)
    if turn:
        owner=engine.state.actors.get(turn[1])
        return max(1,turn[2]-int(owner.turns_started if owner else 0))*6
    return 6  # native source/holder-next-turn names are one normalized round


@hook('journey_snapshot_actor')
def received_snapshot(actor,session,actor_id,engine):
    rows=[c for c in actor.conditions.values() if c.condition_id in RECEIVED]
    if not rows:return None
    result=actor.model_copy(deep=True);instances={c.instance_id for c in rows}
    result.conditions={iid:c for iid,c in result.conditions.items() if iid not in instances}
    result.modifiers={mid:m for mid,m in result.modifiers.items() if not (m.source_definition_id==FATE and m.application_id in instances)}
    return result


@hook('journey_encounter_settled')
def settle_received(session,actor_id,engine,actor):
    rows=[]
    for condition in actor.conditions.values():
        if condition.condition_id not in RECEIVED:continue
        remaining=remaining_seconds(engine,condition)
        if remaining:
            rows.append({'payload':json.dumps({'condition':condition.condition_id,'source':condition.source_definition_id,
                'owner':condition.source_actor_id,'data':condition.data},sort_keys=True),
                'expires_at':int(session.clock())+remaining})
    if not rows and not ownership(engine,actor) and not source_state(session,actor_id):return
    state=session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(PARENT,{})
    if rows:state['received']=rows
    else:state.pop('received',None)
    if ownership(engine,actor):
        active=held(actor)
        if active:
            state['manifestation']={'profile':active[0].data['profile'],
                'expires_at':int(session.clock())+remaining_seconds(engine,active[0])}
        else:state.pop('manifestation',None)


@hook('journey_combat_bundle')
def received_bundle(bundle,session,actor_id):
    records=[r for r in source_state(session,actor_id).get('received',[]) if r['expires_at']>session.clock()]
    if not records:return None
    result=deepcopy(bundle);result['spirit_bow_received']=[{**r,'remaining':r['expires_at']-int(session.clock())} for r in records]
    return result


@hook('match_initialize')
def initialize_received(engine):
    from .effect_durations import round_token
    for bundle in getattr(engine,'typed_bundle_documents',()):
        target=engine.state.actors.get(bundle['actor_id'])
        if target is None:continue
        for record in bundle.get('spirit_bow_received',[]):
            row=json.loads(record['payload']);seconds=record['remaining']
            if seconds<=0:continue
            engine._apply_condition(target,row['condition'],row['source'],row['owner'],
                expires_on=round_token(engine,(seconds+5)//6),data=row['data'])
            if row['condition']==SEAL and row['data'].get('seal')=='journey' and row['data'].get('repeat_save'):
                condition=next(c for c in reversed(list(target.conditions.values())) if c.condition_id==SEAL and c.source_actor_id==row['owner'])
                engine._add_modifier(target,FATE,'speed_halved','ADD',1,'SELF',expires_on='UNTIL_REMOVED',
                    source_actor_id=row['owner'],application_id=condition.instance_id)


@hook('journey_elapsed')
def received_elapsed(session,actor_id,previous,seconds,moving):
    state=source_state(session,actor_id)
    if 'received' in state:
        old=state['received'];state['received']=[r for r in old if r['expires_at']>session.clock()]
        if len(old)!=len(state['received']):session.emit('SPIRIT_BOW_CONSEQUENCE_EXPIRED',actor_id)


@hook('journey_properties')
def received_properties(session,actor_id):
    state=source_state(session,actor_id);rows=[]
    for r in state.get('received',[]):
        if r['expires_at']>session.clock():rows.append((r,json.loads(r['payload'])))
    journey=[(r,d) for r,d in rows if d['condition']==SEAL and d['data'].get('seal')=='journey']
    result={}
    if journey:
        strong=any(d['data'].get('repeat_save') for _,d in journey)
        result.update(pace_divisor=2 if strong else 3,pace_multiplier=1 if strong else 2)
        deadline=min(r['expires_at'] for r,_ in journey)
        result.update(expiry_num=deadline,expiry_den=1)
    information=[]
    from ..gate2_runtime_models import Position
    from ..observer_information import direction
    viewer=Position(**session.state['actors'][actor_id]['position'])
    for aid,a in session.state['actors'].items():
        for record in source_state(session,aid).get('received',[]):
            data=json.loads(record['payload'])
            if record['expires_at']<=session.clock() or data['owner']!=actor_id or data['condition']!=SEAL or data['data'].get('seal')!='thread':continue
            target=Position(**a['position']);distance=session.grid.distance_ft(viewer,target)
            if distance<=5280:information.append({'target':a['name'],'direction':direction(viewer,target),'distance_ft':distance})
    if information:result['information']=information
    return result or None


def permanent_artifact_resistance(engine,target,kind):
    """Read actual represented Resistance source authority; never infer from a name."""
    from ..typed_executor import condition_rule_instances
    from .source_eligibility import catalog_action,printed_text,protected_power
    kind=str(kind).upper()
    for condition,rule in condition_rule_instances(target,engine=engine):
        if not ({kind,'ALL'} & {str(k).upper() for k in rule.get('damage_resistances',[])}):continue
        profile=condition.data.get('information_profile') or {}
        if profile.get('authority')=='artifact' and profile.get('permanent'):return True
        action=catalog_action(engine,condition.source_definition_id)
        if action is not None and condition.expires_on in (None,'UNTIL_REMOVED') and protected_power(typed(action),printed_text(typed(action).get('source'))):return True
    for row in getattr(engine,'typed_passive_rows',{}).get(target.entity_id,[]):
        if row.get('block')!='defense' or row.get('kind','resistance')!='resistance':continue
        if not ({kind,'ALL'} & {str(k).upper() for k in row.get('damage_types',[])}):continue
        if protected_power(row,printed_text(row.get('feature_id'))):return True
    return False


@hook('teleport_context_check')
def weighted_willing_teleport(engine,actor,start,destination,movement_context):
    if movement_context=='WILLING' and any(c.data.get('seal')=='journey' and c.data.get('repeat_save') for c in held(actor,SEAL)):
        return False
    return None


@hook('candidate_allowed')
def weighted_self_teleport_menu(engine,actor,candidate,action):
    if action is None or not any(c.data.get('seal')=='journey' and c.data.get('repeat_save') for c in held(actor,SEAL)):return None
    def teleports(rows):
        for row in rows:
            if (row.get('type')=='teleport' or row.get('type')=='movement' and row.get('mode')=='teleport') and row.get('applies_to','self')=='self':return True
            if any(teleports(row.get(key) or []) for key in ('on_hit','on_fail','on_success','effects')):return True
        return False
    return False if teleports(typed(action).get('effects') or []) else None


@hook('sight_path')
def revealed_attack_route(engine,actor,target):
    from ..shot_geometry import action
    if action(engine,actor) is None or not held(target,REVEAL,actor):return None
    from ..action_geometry import point
    from ..terrain_occlusion import segment_clear
    origin=point(engine,actor)
    if not segment_clear(engine.grid,origin,target.position,physical=True):return None
    from .. import zones
    for zone in zones.typed_zones(engine):
        if zones.hidden_from(engine,actor,target) and not revealed_visual_concealment(engine,zone,actor,target):
            # Only a represented higher-authority visual obstruction refuses
            # this source exception; unrelated nonvisual zones do not matter.
            profile=zone.trigger_profile
            if (profile.get('obscured') or (profile.get('wall') or {}).get('obscures')) and int((profile.get('numbers') or {}).get('cl') or 0)>int((ownership(engine,actor) or {}).get('numbers',{}).get('cl') or 1):return None
    return {'source_id':SEEK,'label':'Revealing Arrow: ordinary visual concealment is ignored against its source owner',
        'path':[p.model_dump(mode='json') for p in (origin,target.position)],'ignore_sight':True}


@hook('damage_type_choice')
def projected_damage_choice(ctx,kinds,targets):
    if ctx.typed.get('spirit_bow_profile')!='projected' or len(kinds)<=1:return None
    from .rider_choices import pick
    available=[str(k) for k in kinds if str(k).upper() in ('FORCE','PIERCING')]
    if not available:return None
    picked=pick(ctx.engine,ctx.actor,'spirit_bow_damage','Spirit Bow',available,
        subject=ctx.target or ctx.actor,optional=False,intent=ctx.intent,
        labels={k:k.title() for k in available},
        prompt='Spirit Bow: choose Force or Piercing damage for this projected bow attack; no extra Qi or ammunition cost.')
    return picked[0]


@hook('attack_allowed')
def recheck_bow(ctx,target,attack):
    profile=ctx.typed.get('spirit_bow_profile')
    if not profile:return None
    if not held(ctx.actor) or held(ctx.actor)[0].data['profile']!=profile:return False
    if profile=='projected':
        from .hand_occupancy import free_hands
        return len(free_hands(ctx.engine,ctx.actor))>=2
    return real_ready(ctx.engine,ctx.actor,profile,floated=bool(floating(ctx.engine,ctx.actor,ctx.action)))


@hook('effect_resolution_scope')
def ordinary_empowered_attack(ctx,row):
    if row.get('type')!='attack' or ctx.typed.get('spirit_bow_profile'):return None
    active=held(ctx.actor)
    if not active or active[0].data['profile']=='projected':return None
    from .weapon_hits import weapon_identity
    if weapon_identity(ctx)!=active[0].data['profile']:return None
    from contextlib import contextmanager
    @contextmanager
    def empowered():
        previous=ctx.typed
        ctx.typed={**previous,'spirit_bow_profile':active[0].data['profile'],'qi_powered':True}
        try:yield
        finally:ctx.typed=previous
    return empowered()


@hook('compile_bundle')
def delivered_seeking_actions(bundle,info):
    """Extend the actual real-bow delivery catalog; preserve its original source."""
    markers={r.get('kind') for r in bundle.get('typed_passives',[]) if r.get('block')=='spirit_bow_native'}
    if 'seeking_arrow' not in markers:return None
    real={a['parameters']['spirit_bow_manifest'] for a in bundle['action_catalog'] if a.get('parameters',{}).get('spirit_bow_manifest') not in (None,'projected')}
    from ..weapon_delivery import weapon_identity
    result=deepcopy(bundle);extra=[]
    for action in bundle['action_catalog']:
        params=action.get('parameters') or {};t=params.get('typed') or {}
        special=t.get('heaven_sundering') or params.get('spirit_bow_domain_attack')
        if (t.get('spirit_bow_profile') and not special) or t.get('seeking_form') or not t.get('weapon') or not any(r.get('type')=='attack' for r in t.get('effects',[])):continue
        if action.get('target_kind')!='HOSTILE_ENTITY':continue
        identity=t.get('spirit_bow_profile') or weapon_identity(None,action['source_definition_id'],t,params,owner_id=bundle['actor_id'])
        if identity not in real and not (identity=='projected' and t.get('heaven_sundering')):continue
        for form,label in FORMS.items():
            row=deepcopy(action);data=row['parameters']['typed']
            data.update(spirit_bow_profile=identity,seeking_form=form,strike_penalty_provenance=1,qi_powered=True)
            row['source_definition_id']+='.spirit_bow.seek.'+form
            row['display_name']+=' + '+label
            row['costs']=[*row.get('costs',[]),[QI,1]]
            row['parameters'].update(spirit_bow_attack=1,description='Spend 1 additional Qi for '+label+' before this attack; once per turn, first qualifying attack only. '+FORM_RULES[form])
            extra.append(row)
    if not extra:return None
    result['action_catalog'].extend(extra);result['actor_template']['action_ids'].extend(a['source_definition_id'] for a in extra)
    return result


def bow_object_id(actor,identity):
    return 'object:spirit_bow.'+hashlib.sha256((actor.entity_id+'|'+identity).encode()).hexdigest()[:24]


def publish_real_bow_object(engine,actor,identity,position,source):
    """The same inventory item receives a targetable physical-world position."""
    from ..gate2_runtime_models import RuntimeObjectState
    from ..object_rules import stats
    from ..journey import require
    action=engine.action_catalog[identity];bond=held(actor,BOUND)[0]
    require(bool(bond.data.get('object_profile')),'The native item owner must declare this bow’s physical object profile before release.')
    durability=json.loads(bond.data['object_profile'])
    profile=stats({'kind':'custom','name':action.display_name.removesuffix(' attack'),**durability,'blocks':False,'unattended':False})
    oid=bow_object_id(actor,identity);old=engine.state.objects.get(oid)
    if old is not None:
        component={**(old.component or {}),'in_inventory':0}
        engine._update_object(old.model_copy(update={'position':position,'destroyed':False,'component':component}),source,actor.entity_id)
        return
    engine._update_object(RuntimeObjectState(object_id=oid,object_kind='bound_weapon',owner_id=actor.entity_id,
        position=position,unattended=False,flammable=profile['flammable'],ac=profile['ac'],
        current_hp=profile['hp'],maximum_hp=profile['hp'],damage_immunities=tuple(profile['immune']),
        damage_threshold=profile['threshold'],destroyed=False,
        component={'name':profile['name'],'material':profile['material'],'size':profile['size'],
            'blocks':False,'structure':False,'real_bow':identity,'in_inventory':0,
            'resist':profile['resist'],'vulnerable':profile['vulnerable'],
            'source_cl':int(durability.get('source_cl') or 0),'source_rule':BOW}),source,actor.entity_id)


def carry_real_bow_object(engine,actor,identity,source):
    obj=engine.state.objects.get(bow_object_id(actor,identity))
    if obj is not None and not obj.destroyed:
        # Calling the same real item never publishes a destruction receipt.
        # Its physical body remains attended at the carrier, with unchanged HP.
        engine._update_object(obj.model_copy(update={'position':actor.position,'unattended':False,
            'component':{**(obj.component or {}),'in_inventory':1}}),source,actor.entity_id)


def land_bound_item(engine,actor,source):
    from .qi_path import ARMED,armament_point
    from ..gate2_runtime_models import Position
    floating=held(actor,'condition:typed.spirit_bow_floating')
    if not floating:return
    identity=floating[0].data['profile'];x,y=armament_point(actor)
    remove(engine,actor,'condition:typed.spirit_bow_floating',source)
    remove(engine,actor,ARMED,source)
    obj=engine.state.objects.get(bow_object_id(actor,identity))
    if obj is not None and not obj.destroyed:
        engine._update_object(obj.model_copy(update={'position':Position(x=x,y=y),'unattended':True}),source,actor.entity_id)
    engine._apply_condition(actor,'condition:typed.disarmed',source,actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'disables_action':identity,'dropped_at':{'x':x,'y':y,'z':0},'label':'Real Spirit Bow landed; the bond remains'})


@hook('event',nested=True,priority=-10)
def real_item_state(engine,event_type,kwargs):
    payload=kwargs.get('payload') or {}
    if event_type=='MOVEMENT_COMMITTED':
        from .qi_path import armament_control_range,armament_point
        actor=engine.state.actors.get(kwargs.get('actor_id'))
        if actor:
            for obj in list(engine.state.objects.values()):
                if obj.owner_id==actor.entity_id and not obj.destroyed and (obj.component or {}).get('real_bow') and obj.component.get('in_inventory'):
                    engine._update_object(obj.model_copy(update={'position':actor.position}),BOW,actor.entity_id)
        if actor and held(actor,'condition:typed.spirit_bow_floating') and engine.grid.distance_ft(actor.position,armament_point(actor))>armament_control_range(engine,actor):
            land_bound_item(engine,actor,BOW)
        return
    if event_type=='CONDITION_APPLIED' and payload.get('condition_id')=='condition:typed.unconscious':
        for aid in kwargs.get('target_ids',()):
            actor=engine.state.actors.get(aid)
            if actor and held(actor,'condition:typed.spirit_bow_floating'):land_bound_item(engine,actor,BOW)
        return
    if event_type=='CONDITION_APPLIED' and payload.get('condition_id')=='condition:typed.domain_armament':
        from .qi_path import armament_point
        from ..gate2_runtime_models import Position
        for aid in kwargs.get('target_ids',()):
            actor=engine.state.actors.get(aid);f=held(actor,'condition:typed.spirit_bow_floating') if actor else []
            if f:
                obj=engine.state.objects.get(bow_object_id(actor,f[0].data['profile']))
                if obj and not obj.destroyed:
                    x,y=armament_point(actor)
                    engine._update_object(obj.model_copy(update={'position':Position(x=x,y=y)}),BOW,aid)
        return
    if event_type!='OBJECT_UPDATED':return
    record=payload.get('object') or {};c=record.get('component') or {};identity=c.get('real_bow')
    if not identity:return
    actor=engine.state.actors.get(record.get('owner_id'))
    if actor is None:return
    if record.get('destroyed') and record.get('current_hp')==0:
        land_bound_item(engine,actor,BOW)
        remove(engine,actor,BOUND,BOW)
        if not held(actor,'condition:typed.spirit_bow_broken'):
            engine._apply_condition(actor,'condition:typed.spirit_bow_broken',BOW,actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'disables_action':identity,'label':'Real Spirit Bow broken; ordinary repair is required'})
    elif record.get('current_hp',0)>0:
        remove(engine,actor,'condition:typed.spirit_bow_broken',BOW)


@hook('journey_initialize')
def initialize_installed_progression(session,actor_id):
    actor=session.state['actors'][actor_id]
    earned=[r['feature_id'] for r in actor['bundle'].get('typed_passives',[]) if r.get('block')=='spirit_bow_native']
    if not earned or source_state(session,actor_id).get('earned'):return
    actor.setdefault('source_states',{}).setdefault(PARENT,{})['earned']=list(dict.fromkeys(earned))
    session.emit('SPIRIT_BOW_INSTALLED_PROGRESSION',actor_id,source=PARENT,earned=list(dict.fromkeys(earned)))


@hook('compile_bundle')
def owning_path_gates(bundle,info):
    qi=next((p for p in info['owner_sheet'].get('path_and_subpath',{}).get('paths',[]) if p.get('path_id')=='tianxia.path.qi_cultivation'),{})
    level=qi.get('effective_cl',qi.get('attainment'))
    if type(level) is not int or not any(r.get('block')=='spirit_bow_native' for r in bundle.get('typed_passives',[])):return None
    result=deepcopy(bundle)
    result['typed_passives']=[{**r,'numbers':{**r['numbers'],'cl':min(int(r['numbers']['cl']),level)}} if r.get('block')=='spirit_bow_native' else r
        for r in result['typed_passives'] if r.get('block')!='spirit_bow_native' or level>=LEVELS[r['kind']]]
    return result


@hook('journey_initialize',priority=-10)
def rebase_source_clock(session,actor_id):
    state=source_state(session,actor_id)
    if not state:return
    if state.get('clock_journey') and state['clock_journey']!=session.state['journey_id']:
        prior=int(state.get('clock_checkpoint') or 0)
        shift=int(session.clock())-prior
        for key in ('manifestation','floating'):
            if state.get(key):state[key]['expires_at']+=shift
        for row in state.get('received',[]):row['expires_at']+=shift
        session.emit('SPIRIT_BOW_CLOCK_CONTINUED',actor_id,previous_journey=state['clock_journey'],remaining_clock_shift=shift)
    state.update(clock_journey=session.state['journey_id'],clock_checkpoint=int(session.clock()))
