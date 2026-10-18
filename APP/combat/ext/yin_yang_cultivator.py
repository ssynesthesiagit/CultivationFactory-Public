"""Balanced Flow currents and Restorative Palm from the printed Qi Subpath.

Current selection uses the turn-start owner choice, retained on a condition.
Damage and healing bonuses share one actual-turn clock, including reactions.
Yin applies to one selected damaged or failed-save creature; player decisions
ride the ordinary owner choice transport, with damaged recipients only.
"""
from . import hook, effect
from .passive_rows import row_of

PREFIX = 'tianxia.subpath.qi.yin_yang_cultivator.feature.'
FLOW = PREFIX + 'balanced_flow'
CURRENT = 'condition:typed.yin_yang_current'
BLOCK = 'yin_yang_cultivator'
QI = 'resource:core.qi'


def _flow(engine, actor):
    return row_of(engine, actor.entity_id, BLOCK, 'balanced_flow')


def _current(actor):
    return next((c.data.get('current') for c in actor.conditions.values() if c.condition_id == CURRENT), None)


def _stamp(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}'


def _qi(ctx):
    if type(ctx.typed.get('qi_powered')) is bool:
        return ctx.typed['qi_powered']
    source = str(ctx.typed.get('option_of') or ctx.typed.get('source') or '')
    return (any(pool == QI for pool, _ in ctx.action.costs)
            or source.startswith(('tianxia.subpath.qi.', 'tianxia.path.qi_cultivation.'))
            or ctx.typed.get('qi_powered') is True)


@hook('compile_block')
def flow_block(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'numbers': dict(numbers), 'choice_owner': True}]
    return None


@hook('compile_actions')
def flow_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    if FLOW not in info['owned_ids']:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.yin_yang.restorative_palm",
        display_name='Restorative Palm', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5, costs=((QI, 2),),
        parameters={'typed': {'source': FLOW, 'numbers': dict(info['numbers']),
            'duration': {'kind': 'instant'}, 'riders': [],
            'effects': [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                         'formula': 'key_ability_modifier'}, {'type': 'yin_yang_palm'}]},
            'expected_damage': 0, 'description': 'Touch one creature as an Action and spend 2 Qi. '
            'It regains 2d8 plus your Qi key ability modifier HP. Yin Current also grants your Proficiency Bonus in '
            'Temporary HP; Yang Current lets that creature choose a 5-foot move without provoking Opportunity Attacks.'})]


@hook('compile_action')
def qi_sphere_power(action, info):
    from copy import deepcopy
    if FLOW not in info['owned_ids']:
        return None
    stats = (info.get('owner_sheet') or {}).get('ability_scores_and_statistics') or {}
    qi = str((stats.get('primary_resource') or {}).get('name') or 'Qi').lower() == 'qi'
    typed = (action.parameters or {}).get('typed') or {}
    if qi and typed.get('sphere') and not typed.get('attack_action'):
        parameters = deepcopy(action.parameters)
        parameters['typed']['qi_powered'] = True
        return action.model_copy(update={'parameters': parameters})
    return None


@hook('turn_start_choice')
def flow_choice(engine, actor):
    if not _flow(engine, actor) or not actor.active:
        return
    from .rider_choices import pick
    selected = pick(engine, actor, 'balanced_flow', 'Balanced Flow', ['yin', 'yang'], subject=actor,
        labels={'yin': 'Yin Current: once per turn, reduce one affected creature’s Speed by 10 feet until the start of your next turn',
                'yang': f'Yang Current: once per turn, add your Proficiency Bonus ({int(actor.proficiency_bonus or 2)}) to one damage or healing roll'},
        preferred=[_current(actor) or 'yin'], optional=False,
        prompt=f'Balanced Flow: choose the current for {actor.display_name} until its next turn starts.')
    if selected:
        engine._remove_condition(actor, CURRENT, FLOW)
        engine._apply_condition(actor, CURRENT, FLOW, actor.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN',
            data={'current': selected[0], 'label':
                ('Yin Current: once per turn, reduce one affected creature’s Speed by 10 feet until the start of your next turn'
                 if selected[0] == 'yin' else
                 f'Yang Current: once per turn, add your Proficiency Bonus ({int(actor.proficiency_bonus or 2)}) to one damage or healing roll')})


def _yang(ctx, roll_kind, effect=None, targets=None):
    if not _flow(ctx.engine, ctx.actor) or _current(ctx.actor) != 'yang' or not _qi(ctx):
        return None
    key = '_round_balanced_yang'
    if ctx.actor.turn_flags.get(key) == _stamp(ctx.engine):
        return None
    from .rider_choices import pick
    from .choice_prompt import action_context
    from ..typed_executor import effect_subjects
    affected = list(targets) if targets is not None else (
        effect_subjects(ctx, effect, harmful=(roll_kind == 'damage')) if effect is not None else [])
    # Damage effects roll once for an area, before delivery to each creature.
    # Keep the choice attached to a real recipient while naming the whole batch
    # in display context; never imply the off-turn zone's current actor caused it.
    affected = [creature for creature in affected if creature is not None]
    subject = affected[0] if affected else ctx.target or ctx.actor
    names = ', '.join(creature.display_name for creature in affected) or subject.display_name
    context = action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, subject, action=ctx.action)
    if len(affected) > 1:
        # prompt_context is display-only; a group label avoids presenting the
        # first member as the sole recipient of one shared roll.
        context['affected_id'] = names
    action_name = str(ctx.action.display_name or 'the action')
    source_name = ctx.actor.display_name
    trigger = f"the {roll_kind} roll from {action_name} by {source_name}, affecting {names}"
    selected = pick(ctx.engine, ctx.actor, 'balanced_yang', 'Yang Current', ['increase', 'save'],
        subject=subject,
        labels={'increase': f'Add your Proficiency Bonus ({int(ctx.actor.proficiency_bonus or 2)}) to this roll; spend Yang Current for this turn',
                'save': 'Keep Yang Current available for a later damage or healing roll'},
        preferred=['increase'], optional=True, automatic=True,
        prompt_context=context,
        prompt=f'Yang Current: add your Proficiency Bonus ({int(ctx.actor.proficiency_bonus or 2)}) to {trigger}? You can choose one roll per turn.')
    if not selected or selected[0] != 'increase':
        return None
    ctx.actor.turn_flags[key] = _stamp(ctx.engine)
    return int(ctx.actor.proficiency_bonus or 2)


@hook('damage_roll_bonus')
def yang_damage(ctx, eff, kinds):
    # Attack construction asks this before the hit is known. The hit-only
    # confirmed-hit damage_packet_selection seam below owns those packets.
    return _yang(ctx, 'damage', eff) if eff is not None else None


@hook('damage_packet_selection')
def yang_attack(ctx, target, packet_kinds):
    # This documented callback receives the mutable spec after a confirmed hit,
    # including defensive reactions. Construction and misses spend no use.
    spec=ctx.attack_defense_spec
    dice=spec.get('damage') if spec else None
    if dice is None or dice.count<=0 or dice.sides<2 or spec.get('fixed_damage') is not None:
        return
    bonus=_yang(ctx, 'damage', targets=[target])
    if bonus:
        spec['damage']=dice.model_copy(update={'modifier':dice.modifier+bonus})


@hook('healing_roll_bonus')
def yang_healing(ctx, eff):
    from ..typed_amounts import effect_dice
    from ..gate2_runtime_models import DiceSpec
    dice=ctx.dice(effect_dice(eff,ctx.numbers))
    return _yang(ctx, 'healing', eff) if isinstance(dice,DiceSpec) and dice.count>0 and dice.sides>=2 else None


def _yin(ctx, target):
    if (target is None or not target.active or not _flow(ctx.engine, ctx.actor)
            or _current(ctx.actor) != 'yin' or not _qi(ctx)
            or ctx.actor.turn_flags.get('_round_balanced_yin') == _stamp(ctx.engine)):
        return
    from . import ai_controlled
    if ai_controlled(ctx.engine, ctx.actor) and target.team_id == ctx.actor.team_id:
        return
    from .rider_choices import pick
    selected = pick(ctx.engine, ctx.actor, 'balanced_yin', 'Yin Current', [target.entity_id], subject=target,
        labels={target.entity_id: f"Reduce {target.display_name}'s Speed by 10 feet"}, intent=ctx.intent,
        optional=True, preferred=[target.entity_id] if target.team_id != ctx.actor.team_id else [],
        automatic=target.team_id != ctx.actor.team_id)
    if not selected:
        return
    ctx.actor.turn_flags['_round_balanced_yin'] = _stamp(ctx.engine)
    from ..typed_executor import run_effects
    run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache=ctx.damage_cache),
        [{'type': 'speed', 'applies_to': 'target', 'flat': -10, 'duration': 'until_start_of_your_next_turn',
          'evidence': 'Yin Current: reduce Speed by 10 feet until the start of your next turn.'}])


@hook('damage_dealt')
def yin_damage(ctx, target, amount):
    if amount > 0:
        _yin(ctx, target)


@hook('after_save_resolved')
def yin_save(ctx, target, ability, named, failed):
    if failed:
        _yin(ctx, target)


@effect('yin_yang_palm')
def palm_current(ctx, eff):
    from ..typed_executor import run_effects
    target = ctx.target or ctx.actor
    if _current(ctx.actor) == 'yin':
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'flat': int(ctx.actor.proficiency_bonus or 2)}])
    elif _current(ctx.actor) == 'yang':
        from .rider_choices import step
        step(ctx.engine, target, 'restorative_palm_step', 'Restorative Palm', target, 5, ctx.source, ctx.intent,
             trigger='Yang Current heals you', ignored_oa=[a.entity_id for a in ctx.engine.state.actors.values()])


@hook('ai_candidate_allowed')
def palm_ai_recipient(engine, actor, candidate, action):
    if (getattr(action,'parameters',None) or {}).get('typed',{}).get('source') == FLOW:
        return all(engine.state.actors[t].team_id == actor.team_id for t in candidate.target_ids)
    return None
