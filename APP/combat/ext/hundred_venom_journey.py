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
from .hundred_venom import PREFIX, VENOMS, SWALLOW, ADAPTED, VENOM, BLOOD, DELAYED
from .hundred_venom_sources import FAMILY, owns
from ..journey import require
from ..canonical import canonical_sha256

KEY='hundred_venom_continuation'
SOURCES={PREFIX+'venom_furnace',VENOMS,SWALLOW}
CLOCK='hundred_venom_native_clock'


def feature_owned(engine, source, owner):
    b=next((b for b in engine.typed_bundle_documents if b['actor_id']==owner),None)
    if b and any(r.get('feature_id')==source for r in b.get('typed_passives',())):
        return True
    if b and source==SWALLOW and any(r.get('feature_id')==SWALLOW for r in b.get('typed_reactions',())):
        return True
    return any(any(p=={'source':source,'owner':owner} for p in b.get(KEY,{}).get('proofs',()))
               for b in engine.typed_bundle_documents)


def parts(engine, creature):
    from .suppressed_effects import lifetime
    from .effect_durations import due
    result={'conditions':[],'modifiers':[],'proofs':[],
            'turn_counts':{aid:a.turns_started for aid,a in engine.state.actors.items()},
            'round':engine.state.round_number}
    def valid(item):
        if item.source_definition_id not in SOURCES or not feature_owned(engine,item.source_definition_id,item.source_actor_id):
            return False
        proof={'source':item.source_definition_id,'owner':item.source_actor_id}
        if proof not in result['proofs']:result['proofs'].append(proof)
        return True
    for c in creature.conditions.values():
        if valid(c) and not due(engine,c.expires_on):
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
    if held or 'native_effects' in previous:
        state=actor.setdefault('source_states',{}).setdefault(FAMILY,{})
        state.pop('native_effects',None)
        if held:state['native_effects']=held
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
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance
    for b in engine.typed_bundle_documents:
        held=b.get(KEY)
        if not held:continue
        actor=engine.state.actors.get(b['actor_id'])
        if actor is None:continue
        ids={};markers=[]
        for raw in held['conditions']:
            c=ConditionInstance.model_validate_json(raw)
            require(c.target_id==actor.entity_id and c.source_definition_id in SOURCES
                    and feature_owned(engine,c.source_definition_id,c.source_actor_id),
                    'The carried Venom has no committed source ownership.')
            data=deepcopy(c.data)
            if c.condition_id==DELAYED:data['expires_on']=rebase(engine,data['expires_on'],held)
            before=set(actor.conditions)
            engine._apply_condition(actor,c.condition_id,c.source_definition_id,c.source_actor_id,
                                    expires_on=rebase(engine,c.expires_on,held),data=data)
            fresh=next((x for iid,x in actor.conditions.items() if iid not in before),None)
            if fresh:
                ids[c.instance_id]=fresh.instance_id
                if c.condition_id==VENOM:markers.append(fresh)
        for raw in held['modifiers']:
            m=ModifierInstance.model_validate_json(raw)
            require(m.target_id==actor.entity_id and m.source_definition_id in SOURCES
                    and feature_owned(engine,m.source_definition_id,m.source_actor_id) and not m.consumed,
                    'The carried Venom modifier has no committed source ownership.')
            mid=engine._add_modifier(actor,m.source_definition_id,m.target_field,m.operation,m.value,m.applies_to,
                expires_on=rebase(engine,m.expires_on,held),source_actor_id=m.source_actor_id,application_id=m.application_id)
            ids[m.modifier_id]=mid
        for marker in markers:
            engine._update_condition_data(actor,marker,{**marker.data,
                'condition_ids':[ids[i] for i in marker.data.get('condition_ids',()) if i in ids],
                'modifier_ids':[ids[i] for i in marker.data.get('modifier_ids',()) if i in ids]},VENOMS)


@hook('journey_options')
def scene_options(session, aid):
    if not any(owns(a) or a.get('source_states',{}).get(FAMILY,{}).get('native_effects') for a in session.state['actors'].values()):
        return None
    return [{'id':'hundred_venom.native_scene','kind':'open_scene','auto_select':0,
             'payload':{'teams':{a:'team:journey.party' for a in session.state['actors']}},
             'label':'Open a six-second table scene with these creatures as allies. Resolve unarmed strikes, poison saves, reactions, Blood Venom and delayed Poisoned with normal costs and choices.'}]


@hook('journey_before_command')
def native_timing(session, aid, kind, payload):
    if kind not in ('wait','move','long_rest','finish','activity_start','activity_complete'):
        return
    require(not any(a.get('source_states',{}).get(FAMILY,{}).get('native_effects') for a in session.state['actors'].values()),
            'A Venom or delayed Poisoned is pending. Open the six-second table scene and resolve its actual turns before advancing travel time.')
