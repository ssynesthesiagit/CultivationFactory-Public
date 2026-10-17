"""Committed Hundred-Venom states continue through native elapsed table scenes.

Uses the existing source-state, snapshot, pre-genesis and scene-window contracts.
No damage, saves, choices or poison onset are simulated by a travel time skip.
A player can open the ordinary native scene and resolve those actual turns;
expiry, Blood damage, reactions and delayed Poisoned use the same provider and
journal as combat. The terminal encounter remains immutable.
"""
from copy import deepcopy
from fractions import Fraction
import json
from . import hook
from .hundred_venom import PREFIX, VENOMS, SWALLOW, ADAPTED, VENOM, BLOOD, DELAYED, CARRIED_POISON
from .hundred_venom_sources import FAMILY, owns
from ..journey import require
from ..canonical import canonical_sha256

KEY='hundred_venom_continuation'
SOURCES={PREFIX+'venom_furnace',VENOMS,SWALLOW,PREFIX+'poisoned_body_poisoned_world'}
CLOCK='hundred_venom_native_clock'


def feature_owned(engine, source, owner):
    b=next((b for b in engine.typed_bundle_documents if b['actor_id']==owner),None)
    if b and any(r.get('feature_id')==source for r in b.get('typed_passives',())):
        return True
    if b and source==SWALLOW and any(r.get('feature_id')==SWALLOW for r in b.get('typed_reactions',())):
        return True
    return any(any(p.get('feature',p['source'])==source and p.get('ability_owner',p['owner'])==owner for p in b.get(KEY,{}).get('proofs',()))
               for b in engine.typed_bundle_documents)


def parts(engine, creature):
    from .suppressed_effects import lifetime,alive
    from .benefit_suppression import SUPPRESSED
    from .body_modes_scene_resources import AUTHORITY
    from .effect_durations import due
    result={'conditions':[],'modifiers':[],'proofs':[],
            'turn_counts':{aid:a.turns_started for aid,a in engine.state.actors.items()},
            'round':engine.state.round_number}
    def valid(item):
        delayed=getattr(item,"condition_id",None)==DELAYED
        swallowed=(getattr(item,'condition_id',None)=='condition:typed.poisoned' and any(
            c.condition_id==CARRIED_POISON and c.source_actor_id==creature.entity_id
            and c.data.get('source')==item.source_definition_id and c.data.get('source_actor')==item.source_actor_id
            for c in creature.conditions.values()))
        binding=getattr(item,'data',{}).get('resume_when') if getattr(item,'condition_id',None)==SUPPRESSED and item.source_definition_id==AUTHORITY else None
        feature=binding['feature'] if binding else SWALLOW if swallowed else item.source_definition_id
        ability_owner=binding['owner'] if binding else creature.entity_id if delayed or swallowed else item.source_actor_id
        if feature not in SOURCES or not feature_owned(engine,feature,ability_owner):
            return False
        proof={'source':item.source_definition_id,'owner':item.source_actor_id,
               'feature':feature,'ability_owner':ability_owner}
        if proof not in result['proofs']:result['proofs'].append(proof)
        return True
    for c in creature.conditions.values():
        dormant=c.condition_id==SUPPRESSED and c.source_definition_id==AUTHORITY and c.data.get('until')=='source_available'
        if (dormant and alive(engine,c.data['lifetime']) or c.expires_on not in (None,"UNTIL_REMOVED") and not due(engine,c.expires_on)) and valid(c):
            row=c.model_dump(mode='json');row['expires_on']=lifetime(engine,creature,c)['expiry']
            result['conditions'].append(json.dumps(row,sort_keys=True))
    for m in creature.modifiers.values():
        if valid(m) and not m.consumed and not due(engine,m.expires_on):
            row=m.model_dump(mode='json');row['expires_on']=lifetime(engine,creature,m)['expiry']
            result['modifiers'].append(json.dumps(row,sort_keys=True))
    return result if result['conditions'] or result['modifiers'] else None


@hook('journey_snapshot_actor')
def snapshot(creature, session, aid, engine):
    held=parts(engine,creature)
    limits=[iid for iid,c in creature.conditions.items() if c.condition_id==
            'condition:typed.path_hit_limit.'+PREFIX+'venom_furnace']
    if not held and not limits:
        return None
    copy=creature.model_copy(deep=True)
    for raw in (held or {}).get('conditions',()):copy.conditions.pop(json.loads(raw)['instance_id'],None)
    for raw in (held or {}).get('modifiers',()):copy.modifiers.pop(json.loads(raw)['modifier_id'],None)
    for iid in limits:copy.conditions.pop(iid,None)
    return copy


@hook('journey_encounter_settled')
def settled(session, aid, engine, creature):
    held=parts(engine,creature)
    actor=session.state['actors'][aid]
    previous=actor.get('source_states',{}).get(FAMILY,{})
    uses={key:int(value) for key,value in creature.turn_flags.items()
          if key in ('_round_poisoned_world','once_per_round:typed.'+SWALLOW)
          and value==engine.state.round_number}
    if held or uses or 'native_effects' in previous:
        state=actor.setdefault('source_states',{}).setdefault(FAMILY,{})
        state.pop('native_effects',None)
        if held:state['native_effects']=held
        state['round_uses']=uses
        base=next((b[CLOCK] for b in engine.typed_bundle_documents if CLOCK in b),None)
        if uses and base:
            deadline=Fraction(base['num'],base['den'])+engine.state.round_number*6
            state['round_use_deadline_num']=deadline.numerator
            state['round_use_deadline_den']=deadline.denominator
            state['round_use_epoch']=session.state['journey_id']
            remaining=max(Fraction(0),deadline-session.clock())
            state['round_use_remaining_num']=remaining.numerator
            state['round_use_remaining_den']=remaining.denominator
    # A source enrollment opts into the same actual elapsed-round clock. A
    # shared owner may already have advanced it; never advance or rewind twice.
    clock=next((b[CLOCK] for b in engine.typed_bundle_documents if CLOCK in b),None)
    if clock is not None and session.state.get('hundred_venom_clock_match')!=engine.state.match_id:
        deadline=Fraction(clock['num'],clock['den'])+max(0,engine.state.round_number-1)*6
        delta=max(Fraction(0),deadline-session.clock())
        session.tick(delta)
        session.state['hundred_venom_clock_match']=engine.state.match_id
        session.emit('HUNDRED_VENOM_NATIVE_TIME_ELAPSED',aid,seconds_num=delta.numerator,seconds_den=delta.denominator)


@hook('journey_combat_bundle')
def project(bundle, session, aid):
    actor=session.state['actors'][aid]
    held=actor.get('source_states',{}).get(FAMILY,{}).get('native_effects')
    if not held and not owns(actor) and 'hundred_venom_exposures' not in bundle:
        return None
    b=deepcopy(bundle)
    if held:b[KEY]=deepcopy(held)
    uses=actor.get('source_states',{}).get(FAMILY,{}).get('round_uses',{})
    state=actor.get('source_states',{}).get(FAMILY,{})
    deadline=Fraction(state.get('round_use_deadline_num',0),state.get('round_use_deadline_den',1))
    if uses and session.clock()<deadline:b['hundred_venom_round_uses']=list(uses)
    now=session.clock();b[CLOCK]={'num':now.numerator,'den':now.denominator}
    b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    return b


def rebase(engine, expiry, held):
    from .effect_durations import parse,parse_round,token
    turn=parse(expiry)
    if turn:
        edge,aid,deadline=turn
        if aid not in engine.state.actors:
            return f'START_OF_SLOT_AT:{engine.state.round_number+1}:0'
        remaining=max(0,deadline-int(held['turn_counts'].get(aid,0)))
        return token(edge,aid,engine.state.actors[aid].turns_started+remaining)
    slot=parse_round(expiry)
    if slot:
        round_number,index=slot
        return f'START_OF_SLOT_AT:{engine.state.round_number+max(0,round_number-held["round"])}:{min(index,len(engine.state.initiative_order)-1)}'
    return expiry


@hook('match_initialize')
def restore(engine):
    from .body_modes_scene_resources import retained_effect_batch
    with retained_effect_batch(engine):return restore_retained(engine)


def restore_retained(engine):
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance
    initialized=False
    for b in engine.typed_bundle_documents:
        actor=engine.state.actors.get(b['actor_id'])
        if actor is None:continue
        for key in b.get('hundred_venom_round_uses',()):
            actor.turn_flags[key]=engine.state.round_number
        held=b.get(KEY)
        if not held:continue
        initialized=True
        ids={};markers=[];hidden=[]
        for raw in held['conditions']:
            c=ConditionInstance.model_validate_json(raw)
            proof=next((p for p in held['proofs'] if p['source']==c.source_definition_id and p['owner']==c.source_actor_id),None)
            require(c.target_id==actor.entity_id and proof is not None
                    and feature_owned(engine,proof['feature'],proof['ability_owner']),
                    'The carried Venom has no committed source ownership.')
            data=deepcopy(c.data)
            if c.condition_id==DELAYED:data['expires_on']=rebase(engine,data['expires_on'],held)
            if data.get('until')=='source_available' and 'lifetime' in data:
                data['lifetime']['expiry']=rebase(engine,data['lifetime']['expiry'],held)
                # Dormant Venoms retain operation counters as well as expiry
                # tokens. Rebase Blood's next-turn operation from the saved
                # holder count, otherwise a later-scene target can miss it.
                model=data.get('model')
                if isinstance(model,dict) and model.get('condition_id')==BLOOD:
                    source_turns=int(held['turn_counts'].get(actor.entity_id,0))
                    remaining=max(0,int(model.get('data',{}).get('next_turn_at',source_turns))-source_turns)
                    model.setdefault('data',{})['next_turn_at']=int(actor.turns_started)+remaining
            if c.condition_id==BLOOD and 'next_turn_at' in data:
                source_turns=int(held['turn_counts'].get(actor.entity_id,0))
                remaining=max(0,int(data['next_turn_at'])-source_turns)
                data['next_turn_at']=int(actor.turns_started)+remaining
            before=set(actor.conditions)
            engine._apply_condition(actor,c.condition_id,c.source_definition_id,c.source_actor_id,
                                    expires_on=rebase(engine,c.expires_on,held),data=data)
            fresh=next((x for iid,x in actor.conditions.items() if iid not in before),None)
            if fresh:
                ids[c.instance_id]=fresh.instance_id
                if c.condition_id==VENOM:markers.append(fresh)
                if data.get('until')=='source_available':hidden.append(fresh)
        for raw in held['modifiers']:
            m=ModifierInstance.model_validate_json(raw)
            proof=next((p for p in held['proofs'] if p['source']==m.source_definition_id and p['owner']==m.source_actor_id),None)
            require(m.target_id==actor.entity_id and proof is not None
                    and feature_owned(engine,proof['feature'],proof['ability_owner']) and not m.consumed,
                    'The carried Venom modifier has no committed source ownership.')
            mid=engine._add_modifier(actor,m.source_definition_id,m.target_field,m.operation,m.value,m.applies_to,
                expires_on=rebase(engine,m.expires_on,held),source_actor_id=m.source_actor_id,application_id=m.application_id)
            ids[m.modifier_id]=mid
        # Reserve identities inside each freshly restored native marker.
        # Related components keep exact references without colliding with a
        # new encounter's ordinary sequence-based condition/modifier IDs.
        hidden_ids={}
        for outer in hidden:
            model=outer.data['model'];field='instance_id' if outer.data['kind']=='condition' else 'modifier_id'
            hidden_ids[model[field]]=outer.instance_id+':retained'
        for outer in hidden:
            data=deepcopy(outer.data);model=data['model'];field='instance_id' if data['kind']=='condition' else 'modifier_id'
            model[field]=hidden_ids[model[field]]
            model['expires_on']=data['lifetime']['expiry'];model['expires_turn_count']=None;model['expires_actor_id']=None
            if model.get('condition_id')==VENOM:
                for key in ('condition_ids','modifier_ids'):
                    model['data'][key]=[hidden_ids.get(i,ids.get(i,i)) for i in model['data'].get(key,())]
            engine._update_condition_data(actor,outer,data,outer.source_definition_id)
        for marker in markers:
            engine._update_condition_data(actor,marker,{**marker.data,
                'condition_ids':[ids[i] for i in marker.data.get('condition_ids',()) if i in ids],
                'modifier_ids':[ids[i] for i in marker.data.get('modifier_ids',()) if i in ids]},VENOMS)

    return True if initialized else None


@hook('journey_options')
def scene_options(session, aid):
    if not any(owns(a) or a.get('source_states',{}).get(FAMILY,{}).get('native_effects') for a in session.state['actors'].values()):
        return None
    return [{'id':'hundred_venom.native_scene','kind':'open_scene','auto_select':0,
             'payload':{'teams':{a:'team:journey.party' for a in session.state['actors']}},
             'label':'Open a six-second table scene with these creatures as allies. Resolve unarmed strikes, poison saves, reactions, Blood Venom and delayed Poisoned with normal costs and choices.'}]


@hook('journey_before_command')
def native_timing(session, aid, kind, payload):
    if kind not in ('wait','move','long_rest','activity_start','activity_complete','body_recover_stamina'):
        return
    require(not any(a.get('source_states',{}).get(FAMILY,{}).get('native_effects') for a in session.state['actors'].values()),
            'A Venom or delayed Poisoned is pending. Open the six-second table scene and resolve its actual turns before advancing travel time.')


@hook('journey_initialize')
def reanchor_uses(session, aid):
    state=session.state['actors'][aid].get('source_states',{}).get(FAMILY,{})
    if state.get('round_uses') and state.get('round_use_epoch')!=session.state['journey_id']:
        remaining=Fraction(state.get('round_use_remaining_num',0),state.get('round_use_remaining_den',1))
        deadline=session.clock()+remaining
        state['round_use_deadline_num']=deadline.numerator;state['round_use_deadline_den']=deadline.denominator
        state['round_use_epoch']=session.state['journey_id']


@hook('journey_elapsed')
def expire_uses(session, aid, before, seconds, moving):
    state=session.state['actors'][aid].get('source_states',{}).get(FAMILY,{})
    if not state.get('round_uses'):return
    remaining=max(Fraction(0),Fraction(state['round_use_deadline_num'],state['round_use_deadline_den'])-session.clock())
    state['round_use_remaining_num']=remaining.numerator;state['round_use_remaining_den']=remaining.denominator
    if remaining==0:state['round_uses']={}


@hook('fight_setup_tasks')
def initial_blood_task(engine):
    """A carried first-turn damage packet keeps real human defense choices."""
    actor=engine.state.actors.get(engine.state.current_actor_id)
    if actor is None:return
    return [{'actor_id':actor.entity_id,'source_id':VENOMS,'effect_instance_id':c.instance_id}
            for c in actor.conditions.values() if c.condition_id==BLOOD and c.source_definition_id==VENOMS
            and feature_owned(engine,VENOMS,c.source_actor_id)] or None


@hook('fight_setup')
def finish_initial_blood_setup(engine,actor,source,intent):
    if source!=VENOMS:return
    if any(c.condition_id==BLOOD and c.source_definition_id==VENOMS and feature_owned(engine,VENOMS,c.source_actor_id)
           for c in actor.conditions.values()):return True
