"""Native non-attack Ignore the Fool delivery, before the committed effect's saves.

Uses the shared harmful-effect classification, exact Foil mark, owned reaction
rows, checkpoint_response/commit_checkpoint_response and native choice transport.
No target, narrative, team, Charm immunity or missing metadata fabricates a
Proposition. Attack-roll triggers remain with the existing attack provider.
"""
from . import hook
from .jester import foil_mark
WATCH='condition:typed.jester_harmful_punchline'
BASE='JESTER_BASE_DELIVER_THE_PUNCHLINE'
_OBSOLETE_IGNORE_RIDERS={
    "The +2 to one saving throw against a triggering harmful effect (instead of an attack roll) is not run: only the Foil's attack rolls at another creature fulfil Ignore the Fool here.",
    "Only the Foil's attack rolls at another creature fulfil Ignore the Fool here; a harmful effect that fails against the ally is not watched.",
}


@hook('compile_passives')
def seal_punchline_base_access(passives,info):
    """Source ownership is compiled once; historical sealed packets stay valid."""
    owned=set(info.get('owned_ids') or ())
    if BASE not in owned and not any(key.startswith('tianxia.talent.jester.') for key in owned):
        return passives
    return [*passives,{'feature_id':'system:jester.punchline_base_access','block':'jester_base_access','allowed':int(BASE in owned)}]


@hook('row_allowed')
def owned_punchline_base(engine,owner,row):
    if row.get('requires_mark') not in {foil_mark(p) for p in ('Come Closer','Strike the Fool','Ignore the Fool','Show Your Hand')}:
        return None
    access=next((r for r in getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,[])
                 if r.get('block')=='jester_base_access'),None)
    return None if access is None else bool(access.get('allowed'))


@hook('before_target_reactions')
def harmful_proposition(ctx):
    from ..effect_harm import rows, classify_effect
    from ..typed_executor import bears_mark, run_effects
    from ..typed_reactions import checkpoint_response, commit_checkpoint_response, triggered_context
    from ..stealth import sees
    from ..speech import can_hear_from
    from .needle import ask, checkpoint_id, CHOICE
    effects=list(rows(ctx.typed.get('effects') or []))
    if any(row.get('type')=='attack' for row in effects):
        return
    if not any(classify_effect(row,ignore_self=True,numbers=ctx.numbers) is True for row in effects):
        return
    engine,foil=ctx.engine,ctx.actor
    for owner in engine.state.actors.values():
        if not owner.active or owner.entity_id==foil.entity_id:
            continue
        if not bears_mark(foil,owner.entity_id,foil_mark('Ignore the Fool')):
            continue
        if not (sees(engine,foil,owner) or can_hear_from(engine,owner,foil,BASE)):
            continue
        eligible={}
        for target in ctx.targets:
            if target.entity_id==owner.entity_id:
                continue
            for row in [*getattr(engine,'typed_reaction_rows',{}).get(owner.entity_id,[]),
                        *getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,[])]:
                if row.get('block')!='generic' or row.get('requires_mark')!=foil_mark('Ignore the Fool'):
                    continue
                feature=row.get('feature_id')
                # A sibling talent's printed ally gate remains its own gate.
                if feature=='tianxia.talent.jester.the_audience_chooses_the_hero' and target.team_id!=owner.team_id:
                    continue
                native=checkpoint_response(engine,owner,target,foil,feature,'JESTER_HARMFUL_PROPOSITION')
                if native is not None:
                    eligible[feature+'|'+target.entity_id]=(target,native)
        if not eligible:
            continue
        chosen=ask(engine,ctx.intent,checkpoint_id(engine,'JESTER_HARMFUL_PROPOSITION',owner.entity_id,ctx.source),
            owner,CHOICE+'jester_harmful_punchline',list(eligible),
            labels={key:f"{row.get('name','Punchline')}: protect {target.display_name}" for key,(target,row) in eligible.items()},
            prompt=f'{foil.display_name} commits to {ctx.action.display_name}, a harmful effect targeting another creature. Deliver one compatible Punchline?',
            name='Deliver the Punchline',feature_id=BASE,allow_decline=True)
        if not chosen:
            continue
        target,row=eligible[chosen[0]]
        commit_checkpoint_response(engine,owner,foil,row,'JESTER_HARMFUL_PROPOSITION')
        punch=triggered_context(engine,owner,foil,row,ctx.intent)
        punch.typed['protects']=target.entity_id
        pending=[]
        for effect in row.get('effects') or []:
            if effect.get('type')=='jester_applause':
                # Applaud chooses one save; Audience's ordinary ongoing AC,
                # DEX advantage and temp HP retain their own compiled effects.
                save_bonus=2 if row.get('feature_id')=='tianxia.talent.jester.applaud_the_master' else 0
                engine._apply_condition(target,WATCH,row['feature_id'],owner.entity_id,
                    expires_on='END_OF_CURRENT_TURN',data={'incoming':ctx.source,
                    'intent':ctx.intent.intent_id,'foil':foil.entity_id,'bonus':save_bonus,'used':0,
                    'numbers':dict(row.get('numbers') or {}),
                    'label':f"{row.get('name','Punchline')}: protects against {ctx.action.display_name}'s next saving throw"})
            else:
                pending.append(effect)
        run_effects(punch,pending)


@hook('save')
def protect_save(ctx,subject,ability,named):
    for held in subject.conditions.values():
        data=held.data or {}
        if (held.condition_id==WATCH and data.get('incoming')==ctx.source
                and ctx.intent is not None and data.get('intent')==ctx.intent.intent_id and not data.get('used')):
            ctx.engine._update_condition_data(subject,held,{**data,'used':1},held.source_definition_id)
            return {'bonus':int(data.get('bonus') or 0),'modes':[]}
    return None


@hook('save_final')
def protected_outcome(ctx,subject,ability,named,failed):
    from ..typed_reactions import triggered_context
    from ..typed_executor import run_effects
    for held in list(subject.conditions.values()):
        data=held.data or {}
        if (held.condition_id!=WATCH or data.get('incoming')!=ctx.source or ctx.intent is None
                or data.get('intent')!=ctx.intent.intent_id or not data.get('used')):
            continue
        if not failed:
            owner=ctx.engine.state.actors.get(held.source_actor_id)
            foil=ctx.engine.state.actors.get(data.get('foil'))
            if owner is not None and foil is not None:
                punch=triggered_context(ctx.engine,owner,foil,{'feature_id':held.source_definition_id,
                    'name':'Deliver the Punchline','numbers':data.get('numbers') or {},'effects':[]},ctx.intent)
                run_effects(punch,[{'type':'flustered','applies_to':'target'}])
        ctx.engine._remove_condition(subject,WATCH,held.source_definition_id)


@hook('reaction_rows')
def printed_attack_recipients(engine,actor_id,block,rows):
    if block!='generic' or not any(row.get('requires_mark')==foil_mark('Ignore the Fool') for row in rows):
        return None
    # Applaud and Thrown Slipper name a creature targeted by the Foil; Audience
    # alone retains its printed ally restriction. Existing attack delivery can
    # already handle any_subject without a new core reaction dispatcher.
    result=[]
    for row in rows:
        if row.get('requires_mark')!=foil_mark('Ignore the Fool'):
            result.append(row)
            continue
        updated={**row,'riders':[text for text in row.get('riders') or [] if text not in _OBSOLETE_IGNORE_RIDERS]}
        if row.get('feature_id')!='tianxia.talent.jester.the_audience_chooses_the_hero':
            updated['any_subject']=True
        result.append(updated)
    return result


@hook('reaction_subject_allowed')
def foil_perceives_invitation(engine,owner,foil,row):
    if row.get('requires_mark')!=foil_mark('Ignore the Fool') or foil is None:
        return None
    from ..stealth import sees
    from ..speech import can_hear_from
    return sees(engine,foil,owner) or can_hear_from(engine,owner,foil,BASE)


@hook('fact_admission_schema')
def activation_nature_schema(session,source,subject,kind):
    if session is not None or source!=BASE or not subject.startswith('map-context:') or kind!='activation_nature':
        return None
    def validate(value):
        return (set(value)=={'actor_id','action_source','nature','readers'}
            and all(type(value[k]) is str and value[k] for k in ('actor_id','action_source','nature'))
            and value['nature'] in {'mundane','supernatural','magic_action'}
            and isinstance(value['readers'],list) and all(type(reader) is str and reader for reader in value['readers'])
            and len(value['readers'])==len(set(value['readers'])))
    return {'authority':'gm:map','value_type':'document','validate':validate,
            'description':'Explicit source nature of one native actor’s exact action, with named readers'}


@hook('reaction_subject_allowed')
def show_your_hand_source(engine,owner,foil,row):
    if row.get('requires_mark')!=foil_mark('Show Your Hand') or foil is None:
        return None
    source=getattr(engine,'_active_action_source_id',None)
    action=engine.action_catalog.get(source)
    if action is None or action.owner_id not in {foil.entity_id,'*'}:
        return False
    typed=(action.parameters or {}).get('typed') or {}
    if (action.parameters or {}).get('magic_action') is True or typed.get('magic_action') is True:
        return True
    from .area_suppression import effect_mundane
    classified=effect_mundane(engine,source,foil.entity_id)
    if classified is not None:
        return classified is False
    from ..fact_consent_admission import context_fact
    declared=context_fact(engine,owner,foil,BASE,'activation_nature',action_source=source)
    return bool(declared and declared.get('action_source')==source
                and declared.get('nature') in {'supernatural','magic_action'})
