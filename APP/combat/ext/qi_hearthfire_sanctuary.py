"""Hearthfire's sanctuary and recovery consumers.

The existing zone, choice, damage and elapsed-journey contracts own delivery.
Every query requires a live source-scoped field; no field means no behavior.
Public helpers are shared with qi_hearthfire and qi_hearthfire_camp.
"""
from dataclasses import replace
from . import hook, effect
from ..relations import relation, ALLY, ENEMY
from .qi_hearthfire import BASE, HEARTH, RECOVERY, hearths, aura_contains
from .needle import ask, CHOICE, checkpoint_id
from .retained_updates import record_zone_update
from .placed import context, note

PAVILION = BASE + 'hearthward_pavilion'
WELCOME = BASE + 'flame_that_welcomes_all'
RECOVERED = 'condition:typed.homefire_recovered'
FEAR = 'condition:typed.homefire_courage'
THRESHOLD = 'condition:typed.hospitality_threshold'
RECOVERY_LABELS = {
    'heal': 'Regain Hit Points equal to twice the Hearth cultivator’s Proficiency Bonus',
    'temp_hp': 'Gain Temporary Hit Points equal to twice the Hearth cultivator’s Proficiency Bonus',
    'fear': 'Advantage on your next save against Frightened before the end of the next scene',
}
CAUSES = ('travel','hunger','thirst','exposure','ordinary_smoke','environmental_hardship')
PENALTIES = ('cold','rain','smoke','altitude','poor_shelter','damp')


def sanctuary_fields(engine, subject, kind=None):
    """Live authorized 3D fields containing this recipient, never a team-wide buff."""
    for z in engine.state.zones.values():
        p = z.trigger_profile.get('profile') or {}
        if not z.active or not (p.get('pavilion') or p.get('welcome')) or kind and not p.get(kind):
            continue
        owner = engine.state.actors.get(z.owner_id)
        if owner is None:continue
        chosen=subject.entity_id in p.get('chosen_recipients',())
        side=relation(engine,owner,subject)
        if p.get('welcome') and not (chosen and side==ALLY):continue
        if p.get('pavilion') and not (side==ALLY or chosen):continue
        if p.get('hearth_zone'):
            parent=engine.state.zones.get(p['hearth_zone'])
            obj=engine.state.objects.get((parent.trigger_profile.get('profile') or {}).get('hearth_object','')) if parent else None
            if parent is None or not parent.active or obj is None or obj.destroyed or obj.suppressed or not obj.current_hp:
                continue
        if aura_contains(engine, z, subject):
            yield z


def recovery_options(subject):
    options = dict(RECOVERY_LABELS)
    for c in subject.conditions.values():
        provenance = c.data.get('environmental_cause')
        if provenance in CAUSES and c.condition_id=='condition:typed.exhaustion':
            options['exhaustion:'+c.instance_id] = 'End one level of Exhaustion caused by '+provenance.replace('_',' ')
        if provenance in PENALTIES and c.data.get('ordinary') == 1:
            options['penalty:'+c.instance_id] = 'End the ordinary '+provenance.replace('_',' ')+' penalty'
    return options


def homefire_recovery(ctx, subject):
    """One recipient-owned selection; cadence survives field destruction/recreation."""
    if any(c.condition_id == RECOVERED for c in subject.conditions.values()):
        return
    options = recovery_options(subject)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'homefire_recovery', subject.entity_id), subject,
        CHOICE+'homefire_recovery', list(options), labels=options, preferred=['heal' if subject.current_hp<subject.maximum_hp else 'temp_hp'], allow_decline=True,
        name='Homefire Recovery', feature_id=RECOVERY, target_id=subject.entity_id,
        prompt=f'Homefire Recovery: {subject.display_name} may choose one recovery benefit, once per long rest. No action or Qi cost.')
    if not picked:
        return
    choice = picked[0]
    from ..typed_executor import run_effects
    sub = replace(ctx, target=subject, targets=[subject], damage_cache={})
    if choice in ('heal','temp_hp'):
        run_effects(sub, [{'type':'healing' if choice=='heal' else 'temp_hp', 'applies_to':'target', 'flat':2*int(ctx.numbers['pb'])}])
    elif choice == 'fear':
        ctx.engine._apply_condition(subject, FEAR, RECOVERY, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                                    data={'through_next_scene':1, 'label':'Homefire Recovery: next Frightened save has Advantage'})
    else:
        iid = choice.split(':',1)[1]
        condition = subject.conditions.get(iid)
        if condition is None:
            raise ValueError('That environmental penalty has ended; choose again.')
        from .condition_ownership import remove_instance
        if choice.startswith('exhaustion:'):
            from .forged_exhaustion import set_level, level
            set_level(ctx.engine,subject,max(0,level(subject)-1),RECOVERY)
        else:
            remove_instance(ctx.engine, subject, iid, RECOVERY)
    ctx.engine._apply_condition(subject, RECOVERED, RECOVERY, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                                data={'label':'Homefire Recovery received; available after a long rest'})


@effect('qi_welcome', harmful=False)
def welcome(ctx, spec):
    from .qi_hearthfire import require_feature
    require_feature(ctx,WELCOME)
    from .. import zones
    active = hearths(ctx.engine, ctx.actor)
    centers = {'self':ctx.actor.position}
    if active:
        centers['hearth'] = active[0].center
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'welcoming_center',ctx.actor.entity_id), ctx.actor,
        CHOICE+'welcoming_center', list(centers), labels={'self':'Yourself','hearth':'Your active Kindled Hearth'},
        allow_decline=False, preferred=['self'], name='Flame That Welcomes All', feature_id=WELCOME,
        prompt='Flame That Welcomes All: center the 40-foot sanctuary on yourself or your active Hearth for 1 minute with Concentration; 8 Qi, once per scene.')
    allies = [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine,ctx.actor,a)==ALLY]
    from . import ai_controlled
    from ..target_knowledge import located
    if ai_controlled(ctx.engine, ctx.actor):
        allies = [a for a in allies if a is ctx.actor or located(ctx.engine, ctx.actor, a)]
    ids = [a.entity_id for a in allies]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'welcoming_allies',ctx.actor.entity_id), ctx.actor,
        CHOICE+'welcoming_allies', ids, labels={a.entity_id:a.display_name for a in allies}, minimum=0, maximum=len(ids),
        allow_decline=True, default='all', preferred=ids, name='Flame That Welcomes All', feature_id=WELCOME,
        prompt='Flame That Welcomes All: choose the allies protected inside the 40-foot sanctuary for 1 minute.')
    center = centers[picked[0]]
    intent = ctx.intent.model_copy(update={'destination':center})
    zone = zones.create(replace(ctx,intent=intent), {'name':'Flame That Welcomes All','shape':'cylinder', 'size_ft':40,'height_ft':40,
        'duration':{'kind':'minutes','amount':1,'concentration':True},'follows_owner':picked[0]=='self', 'profile':{'welcome':1,'chosen_recipients':chosen,
            'center_actor':ctx.actor.entity_id if picked[0]=='self' else '',
            'hearth_zone':active[0].zone_id if picked[0]=='hearth' else ''}, 'inside':[], 'triggers':[]})
    for a in allies:
        if a.entity_id in chosen and aura_contains(ctx.engine,zone,a):
            homefire_recovery(ctx,a)


@hook('ac')
def sanctuary_ac(engine, actor):
    # Different named fields each grant +1; same-name fields never stack.
    return len({('welcome' if z.trigger_profile['profile'].get('welcome') else 'pavilion')
                for z in sanctuary_fields(engine,actor)}) or None


@hook('damage_defenses')
def welcome_resistance(engine,target,damage_type,typed,source_actor_id):
    if damage_type in ('FIRE','COLD') and any(sanctuary_fields(engine,target,'welcome')):
        return [{'kind':'resistance','damage_types':[damage_type]}]


@hook('save_effects')
def sanctuary_saves(ctx, subject, ability, fail_effects, success_effects, categories):
    from ..typed_executor import _walk_rows
    names = {str(e.get('condition','')).lower() for e in _walk_rows(fail_effects)}
    tags = set(categories)
    for z in sanctuary_fields(ctx.engine,subject):
        p = z.trigger_profile['profile']
        if names & {'charmed','frightened'} or tags & {'environmental_cold','environmental_smoke','environmental_exposure'} or p.get('welcome') and (tags & {'possession'} or any(t.startswith('environmental_') for t in tags)):
            return {'modes':['ADVANTAGE']}
    if 'frightened' in names and any(c.condition_id==FEAR for c in subject.conditions.values()):
        return {'modes':['ADVANTAGE']}


@hook('save_final')
def consume_courage(ctx,subject,ability,named,failed):
    from ..typed_executor import _walk_rows
    if ctx.damage_cache.pop(('homefire_frightened',subject.entity_id),False):
        ctx.engine._remove_condition(subject,FEAR,RECOVERY)


@hook('save_effects')
def courage_binding(ctx,subject,ability,fail_effects,success_effects,categories):
    from ..typed_executor import _walk_rows
    if any(e.get('condition')=='frightened' for e in _walk_rows(fail_effects)) and any(c.condition_id==FEAR for c in subject.conditions.values()):
        ctx.damage_cache[('homefire_frightened',subject.entity_id)]=True


def hearthward_reduction(engine,target,amount,damage_type,source_id,source_actor_id,intent):
    stamp='welcome_reduction_round_use'
    if amount<=0 or target.turn_flags.get(stamp)==engine.state.round_number:return
    fields=list(sanctuary_fields(engine,target,'welcome'))
    if not fields:return
    # Same-named overlapping bonuses do not stack. Select the largest actual
    # source PB, and retain this ally's first-damage cadence across field changes.
    z=max(fields,key=lambda w:(int(w.trigger_profile['numbers']['pb']),w.zone_id))
    pb=int(z.trigger_profile['numbers']['pb'])
    def settle(applied):
        target.turn_flags[stamp]=engine.state.round_number
        z.per_turn_triggered['welcome_reduction:'+target.entity_id]=engine.state.round_number
        record_zone_update(engine,z)
    return {'reduction':min(amount,pb),'settle':settle}


def native_source_action(engine,owner,source):
    from ..gate2_runtime_models import ActionDefinition
    action=engine.action_catalog.get(source)
    if action is None:
        action=next((a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id and (a.parameters.get('typed') or {}).get('source')==source),None)
    return action or ActionDefinition(source_definition_id=source,display_name='Hearthward Pavilion',owner_id=owner.entity_id,
        economy='NONE',resolution_kind='TYPED',target_kind='SELF',parameters={'typed':{'source':source,'effects':[]}})


def field_context(engine,z,targets=()):
    owner=engine.state.actors[z.owner_id]
    return context(engine,owner,z.source_definition_id,z.trigger_profile['numbers'],targets,
                   action=native_source_action(engine,owner,z.source_definition_id))


@effect('qi_hospitality',harmful=True)
def hospitality(ctx,spec):
    subject=ctx.target
    if subject is None:
        return
    z=ctx.engine.state.zones[spec['zone_id']]
    ctx.engine._apply_condition(subject,THRESHOLD,WELCOME,ctx.actor.entity_id,
        expires_on='START_OF_TARGET_NEXT_TURN',data={'zone_id':z.zone_id,'failed':int(spec.get('failed',0)),
            'rule':{'no_reactions':True} if spec.get('failed') else {},
            'label':'Threshold of Hospitality: cannot possess a creature inside'+('; cannot approach the center or take Reactions' if spec.get('failed') else '')})


@hook('turn_start')
def sanctuary_turn(engine,actor):
    from ..typed_executor import run_effects
    from ..gate2_runtime_models import DiceSpec
    from .creature_kinds import matches
    for z in list(engine.state.zones.values()):
        if not z.active or not (z.trigger_profile.get('profile') or {}).get('welcome'):
            continue
        owner=engine.state.actors.get(z.owner_id)
        if owner is None:
            continue
        if actor is owner:
            recipients=[a for a in engine.state.actors.values() if a.active and any(x.zone_id==z.zone_id for x in sanctuary_fields(engine,a,'welcome'))]
            from . import ai_controlled
            from ..target_knowledge import located
            if ai_controlled(engine,owner):
                recipients=[a for a in recipients if a is owner or located(engine,owner,a)]
            recipients.sort(key=lambda a:(a.current_hp>=a.maximum_hp,a.current_hp-a.maximum_hp,a.entity_id))
            ids=[a.entity_id for a in recipients]
            picked=ask(engine,getattr(engine,'_active_intent',None),checkpoint_id(engine,'hearth_feed',z.zone_id,actor.turns_started),owner,
                CHOICE+'hearth_feed',ids,labels={a.entity_id:a.display_name for a in recipients},allow_decline=True,
                preferred=ids[:1],name='Feed the Living Flame',feature_id=WELCOME,
                prompt='Feed the Living Flame: choose one ally inside to regain 2d8 + your key modifier Hit Points, with no action or Qi cost.') if ids else []
            if picked:
                r=engine.roller.roll(DiceSpec(count=2,sides=8,modifier=int(z.trigger_profile['numbers']['key_mod'])),actor_id=owner.entity_id,reason='HEARTH_FEED')
                engine._record_roll(r)
                run_effects(field_context(engine,z,[engine.state.actors[picked[0]]]),[{'type':'healing','applies_to':'target','flat':max(0,r.total)}])
        if relation(engine,owner,actor)==ENEMY and aura_contains(engine,z,actor) and matches(actor,['Daemonic','Demon','Fiend','Incorporeal','Possessing Entity','Undead','Hostile Spirit']):
            run_effects(field_context(engine,z,[actor]),[{'type':'save','applies_to':'target','ability':'cha',
                'on_fail':[{'type':'qi_hospitality','zone_id':z.zone_id,'failed':1}],
                'on_success':[{'type':'qi_hospitality','zone_id':z.zone_id,'failed':0}]}])


def approach_blocked(engine,actor,start,end):
    for c in actor.conditions.values():
        if c.condition_id!=THRESHOLD or not c.data.get('failed'):
            continue
        z=engine.state.zones.get(c.data['zone_id'])
        if z and engine.grid.distance_ft(end,z.center)<engine.grid.distance_ft(start,z.center):
            return True
    return False


@hook('candidate_allowed')
def threshold_candidate(engine,actor,candidate,action):
    if getattr(candidate.kind,'value',candidate.kind)=='MOVE' and candidate.destination is not None and approach_blocked(engine,actor,actor.position,candidate.destination):
        return False


@hook('movement_attempt')
def threshold_step(engine,actor,start,end,intent):
    if approach_blocked(engine,actor,start,end):
        return {'stop':True,'source_id':WELCOME,'label':'Threshold of Hospitality prevents willingly approaching the sanctuary center.'}


@hook('teleport_context_check')
def threshold_teleport(engine,actor,start,end,movement_context):
    if movement_context=='WILLING' and approach_blocked(engine,actor,start,end):
        return False


@hook('effect_allowed')
def threshold_possession(ctx,row):
    if 'possession' not in row.get('spiritual_categories',()) and row.get('type') not in ('possess','possession','attempt_possession') and row.get('category')!='possession':
        return
    for c in ctx.actor.conditions.values():
        if c.condition_id==THRESHOLD:
            z=ctx.engine.state.zones.get(c.data['zone_id'])
            if z and any(aura_contains(ctx.engine,z,t) for t in ctx.targets):
                return False


@hook('event',nested=True)
def prepare_no_guest(engine,event_type,kwargs):
    if event_type!='DAMAGE_COMMITTED':
        return
    from .life_state import massive
    payload=kwargs.get('payload') or {}
    for aid in kwargs.get('target_ids') or ():
        target=engine.state.actors.get(aid)
        if target is None or target.current_hp!=0 or payload.get('hp_before',0)<=0 or payload.get('hp_damage',0)-payload['hp_before']>=massive(engine,target):
            continue
        for z in sanctuary_fields(engine,target,'welcome'):
            key='welcome_saved:'+target.entity_id
            if z.per_turn_triggered.get(key):
                continue
            z.per_turn_triggered[key]=1
            record_zone_update(engine,z)
            engine._apply_condition(target,'condition:typed.welcome_rescue',WELCOME,z.owner_id,expires_on='UNTIL_REMOVED',
                data={'pb':int(z.trigger_profile['numbers']['pb']),'zone_id':z.zone_id,'label':'No Guest Dies Alone'})
            break


@hook('zero_hp')
def no_guest_dies(engine,target,source_id,intent):
    # Arm at the committed HP transition, before damage-related Concentration
    # can end the field. This instantaneous rescue survives loss of its origin.
    if any(c.condition_id=='condition:typed.welcome_rescue' for c in target.conditions.values()):
        return 'STABLE'


@hook('event',nested=True)
def rescue_after_stable(engine,event_type,kwargs):
    if event_type!='LIFE_STATE_CHANGED' or (kwargs.get('payload') or {}).get('life_state')!='STABLE':
        return
    target=engine.state.actors.get(kwargs.get('actor_id'))
    if target is None:
        return
    marker=next((c for c in target.conditions.values() if c.condition_id=='condition:typed.welcome_rescue'),None)
    if marker is None:
        return
    from ..typed_executor import run_effects
    z=engine.state.zones[marker.data['zone_id']]
    run_effects(field_context(engine,z,[target]),[{'type':'temp_hp','applies_to':'target','flat':2*marker.data['pb']}])
    engine._remove_condition(target,marker.condition_id,WELCOME)
    from ..granted_movement import candidates, Route
    from .granted_moves import commit
    intent=getattr(engine,'_active_intent',None)
    rows=candidates(engine,target,5,intent,WELCOME) if intent else {}
    picked=ask(engine,intent,checkpoint_id(engine,'hearth_rescue_move',z.zone_id,target.entity_id),target,
        CHOICE+'hearth_rescue_move',list(rows),labels={k:'Move 5 feet without Opportunity Attacks' for k in rows},
        allow_decline=True,name='No Guest Dies Alone',feature_id=WELCOME,target_id=target.entity_id,default='decline',
        prompt=f'No Guest Dies Alone: {target.display_name} is Stable and gains {2*marker.data["pb"]} Temporary Hit Points. Move up to 5 feet without provoking?') if rows else []
    if picked:
        row=rows[picked[0]]
        commit(engine,target,Route(tuple(row.canonical_path),row.metadata.get('movement_mode','walk')),WELCOME,budget_ft=5,provokes=False,intent=intent)
    from .life_state import UNCONSCIOUS
    engine._apply_condition(target,UNCONSCIOUS,WELCOME,z.owner_id,expires_on='UNTIL_REMOVED',data={'label':'Unconscious and Stable at 0 Hit Points'})


def sync_sanctuaries(engine):
    """Carry moves supernatural wards, retaining each fixed civic shelter site."""
    from .. import zones
    for z in list(engine.state.zones.values()):
        p=z.trigger_profile.get('profile') or {}
        if not z.active or not p.get('hearth_zone'):
            continue
        parent=engine.state.zones.get(p.get('hearth_zone',''))
        owner=engine.state.actors.get(z.owner_id)
        obj=engine.state.objects.get((parent.trigger_profile.get('profile') or {}).get('hearth_object','')) if parent else None
        if parent is None or owner is None or not parent.active or obj is None or obj.destroyed or not obj.current_hp:
            if z.concentration_link and owner is not None and owner.concentration is not None and owner.concentration.zone_id==z.zone_id:
                engine._end_concentration(owner,'HEARTH_DESTROYED')
            else:
                zones.remove(engine,z,'HEARTH_DESTROYED')
            continue
        if not (p.get('pavilion') or p.get('welcome')):continue
        carry=(parent.trigger_profile.get('profile') or {}).get('hearth_carrier')
        from ..gate2_runtime_models import Position
        center=parent.center if carry or p.get('welcome') else Position.model_validate(p['civic_center'])
        if z.center!=center:
            z.center=center
            z.affected_cells=zones.prospective_zone(field_context(engine,z),z.trigger_profile,z.center).affected_cells
            record_zone_update(engine,z)


@hook('movement_landed')
def carried_pavilion_step(engine,mover,previous,nxt,intent,forced):
    sync_sanctuaries(engine)


@hook('event',nested=True)
def anchored_pavilion(engine,event_type,kwargs):
    if event_type in ('OBJECT_UPDATED','ZONE_REMOVED','MOVEMENT_COMMITTED','TELEPORT_COMMITTED'):
        sync_sanctuaries(engine)


@hook('effect_subject_allowed')
def sanctuary_environment(engine_ctx,row,subject):
    """Only explicit ordinary environmental deliveries qualify, never damage names."""
    profile=row.get('environment')
    if not isinstance(profile,dict) or profile.get('ordinary') is not True:
        return
    phenomenon=profile.get('phenomenon')
    for z in sanctuary_fields(engine_ctx.engine,subject):
        p=z.trigger_profile['profile']
        if p.get('welcome') and phenomenon in ('smoke','rain','snow','wind','heat','cold','weather','exposure'):
            return False
        if p.get('pavilion') and phenomenon in ('cold','rain','snow','wind','damp','weather_discomfort') and row.get('type')=='environmental_discomfort':
            return False
    if row.get('type')=='environmental_discomfort' and phenomenon in ('cold','rain','damp'):
        for owner in engine_ctx.engine.state.actors.values():
            for z in hearths(engine_ctx.engine,owner):
                if relation(engine_ctx.engine,owner,subject)==ALLY and subject.entity_id in z.trigger_profile['profile'].get('chosen_recipients',()) and aura_contains(engine_ctx.engine,z,subject):
                    return False
