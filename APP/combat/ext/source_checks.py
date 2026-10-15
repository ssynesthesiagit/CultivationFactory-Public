"""General source-scoped ability checks.

Authored source_check offers skill/ability pairs and typed purposes. The acting
controller declares the purpose; AI is offered only explicitly known purposes.
Context is local to the actual roll and its receipt, never inferred from damage
or a skill name. Consumers query current() for this exact engine and actor.
No source_check effect means unchanged checks. Used by Adorn and Thread Listen.
"""
from contextvars import ContextVar
from . import effect, hook
_FRAME = ContextVar('source_check_frame', default=None)


def current(engine, actor):
    value = _FRAME.get()
    return value if value and value['engine'] is engine and value['actor_id'] == actor.entity_id else None


@effect('source_check', harmful=False)
def resolve(ctx, row):
    from .needle import ask, checkpoint_id
    from ..typed_executor import check_modes
    from .ability_source import combine_modes
    from ..ext.ability_source import mechanic_of
    checks = row['checks']; purposes = row['purposes']
    pick = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'source_check',ctx.source),ctx.actor,
        'choice:needle.source_check',list(checks),labels={k:k for k in checks},
        name=ctx.action.display_name,prompt='Choose the ability check you are actually making.',automatic_options=[])
    if not pick: return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'source_check_purpose',ctx.source),ctx.actor,
        'choice:needle.source_check_purpose',list(purposes),labels=purposes,
        name=ctx.action.display_name,prompt='Declare what this check concerns. Only the chosen purpose can receive a source benefit.',automatic_options=[])
    if not selected: return
    subjects = [ctx.target.entity_id] if ctx.target is not None else [ctx.actor.entity_id]
    # Sources can supply a precise active line or a previously observed subject.
    from . import run_strict
    for values in run_strict('source_check_subjects',ctx,row):
        if values is not None: subjects = list(values)
    if not subjects: return
    choice = ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'source_check_subject',ctx.source),ctx.actor,
        'choice:needle.source_check_subject',subjects,
        labels={k:ctx.engine.state.actors[k].display_name if k in ctx.engine.state.actors else 'Connected object' for k in subjects},
        name=ctx.action.display_name,prompt='Choose the creature or object this check concerns.',automatic_options=[])
    if not choice:return
    skill=pick[0]; ability=checks[skill]; purpose=selected[0]; subject=choice[0]
    token=_FRAME.set({'engine':ctx.engine,'actor_id':ctx.actor.entity_id,'subject':subject,'purpose':purpose,'skill':skill,'ability':ability,'source':mechanic_of(ctx.action)})
    try:
        # Bonuses are sealed by the compiler, never supplied by a declaration.
        bonus=int(row['bonuses'][skill])
        modes=check_modes(ctx.actor,ability,skill,engine=ctx.engine)
        from . import run_strict
        modes.update(m for m in run_strict('source_check_mode',ctx.engine,ctx.actor,ability,skill,current(ctx.engine,ctx.actor)) if m in ('ADVANTAGE','DISADVANTAGE'))
        with ctx.engine.d20_scope({'kind':'check','actor_id':ctx.actor.entity_id,'target_id':subject,
                'source_id':ctx.source,'source_actor_id':ctx.actor.entity_id,'skill':skill,'ability':ability}):
            roll=ctx.engine.roller.d20(modifier=bonus,actor_id=ctx.actor.entity_id,reason='CHECK:'+ctx.source,mode=combine_modes(modes))
        ctx.engine._record_roll(roll)
        ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(subject,),
            payload={'actor':roll.model_dump(mode='json'),'skill':skill,'ability':ability,'purpose':purpose,'subject':subject})
    finally:_FRAME.reset(token)


def check_action(info, source, label, checks, purposes):
    """Build a native check action from sealed sheet bonuses and authored scope."""
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    from ..factory_compiler import _skill_bonus
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.source_check.{source}",
        display_name=label,owner_id=info['actor_id'],economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='SELF',
        parameters={'player_only':True,'description':'Make the chosen ability check for its declared purpose; Action, no CP.',
            'typed':{'source':source,'numbers':dict(info['numbers']),'riders':[],
                'effects':[{'type':'source_check','checks':checks,'purposes':purposes,
                    'bonuses':{skill:_skill_bonus(info['owner_sheet'],skill,info['mods'].get(ability,0)) for skill,ability in checks.items()}}]}})


@hook('presentation_hidden_conditions')
def private_source_records(engine,actor):
    return [iid for iid,c in actor.conditions.items() if c.condition_id in
        ('condition:information.reading','condition:typed.thread_listen','condition:typed.adorn_memory')]
