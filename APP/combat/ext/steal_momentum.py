"""Steal Momentum interrupts voluntary native/granted movement after five feet.

Reaction and Martial Focus are chosen before the Scoundrel check. The immediate
follow-up movement uses the same native step resolver, with a separate allowance.
Teleports and exceptional supernatural movement remain separate rider lanes.
"""
from . import hook

FEATURE = 'TAL_SCOUNDREL_STEAL_MOMENTUM'
BLOCK = 'steal_momentum'
FLAG = 'once_per_round:steal_momentum'


@hook('compile_block')
def compile_momentum(block, spec, row, numbers):
    return [{**row,'block':BLOCK}] if block==BLOCK else None


@hook('movement_step')
def interrupt(engine,mover,previous,nxt,intent):
    from ..movement_steps import context
    from ..target_knowledge import located
    from ..typed_executor import Context, condition_rules
    from . import needle
    from .tabik_scoundrel import check_against_dc
    from .end_effect import cultivation_dc
    from .rider_step import step
    frame = context(engine,mover)
    if frame.get('travelled_ft') != 5:
        return None
    # The checkpoint is after entry/payment, but the printed trigger is a
    # perceived creature within range beginning its movement. Project its
    # previous footprint without changing actual state or remembered locations.
    starting = mover.model_copy(update={'position': previous})
    for reactor in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
        owned = any(r.get('block')==BLOCK and not r.get('held_back') for r in getattr(engine,'typed_passive_rows',{}).get(reactor.entity_id,[]))
        if not owned or reactor is mover or not reactor.active or reactor.life_state is not None or not reactor.reaction_available:
            continue
        if reactor.turn_flags.get(FLAG)==engine.state.round_number or needle.focus(reactor)<1 or any(r.get('no_reactions') for r in condition_rules(reactor)):
            continue
        if engine._distance_actor_to_actor(reactor,starting)>60 or not located(engine,reactor,starting):
            continue
        if not needle.ask(engine,intent,needle.checkpoint_id(engine,'STEAL_MOMENTUM',reactor.entity_id,mover.entity_id),
            reactor,needle.CHOICE+'steal_momentum',['use'],labels={'use':'Spend your Reaction and Martial Focus'},
            allow_decline=True,name='Steal Momentum',feature_id=FEATURE,target_id=mover.entity_id,
            automatic=reactor.team_id!=mover.team_id,
            prompt=f'{mover.display_name} moves 5 feet. Spend your Reaction and Martial Focus to try to stop this movement, then move without provoking Opportunity Attacks?'):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, reactor, FEATURE, independent=True):
            needle.spend_focus(engine,reactor,FEATURE,'Steal Momentum')
            reactor.reaction_available=False
            reactor.turn_flags[FLAG]=engine.state.round_number
            engine._append_event('REACTION_RESOLVED',FEATURE,actor_id=reactor.entity_id,target_ids=(mover.entity_id,),
                payload={'checkpoint':'MOVEMENT_STEP','ability':'Steal Momentum','log':f'{reactor.display_name} spends their Reaction and Martial Focus to interrupt {mover.display_name}.'})
            success=check_against_dc(engine,reactor,mover,FEATURE,cultivation_dc(engine,mover))
            feet=int(frame.get('remaining_ft',0)) if success else 10
            from ..gate2_runtime_models import ActionDefinition, EconomyKind
            action=ActionDefinition(source_definition_id=FEATURE,display_name='Steal Momentum',owner_id=reactor.entity_id,
                economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='SELF')
            ctx=Context(engine,reactor,action,intent,{'numbers':{}},[reactor],reactor,{})
            step(ctx,{'distance_ft':feet,'no_oa':True})
            if success:
                return {'stop':True,'source_id':FEATURE,'label':f'Steal Momentum stops {mover.display_name} after the first 5 feet.'}
    return None
