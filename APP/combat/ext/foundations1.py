"""Foundation conversions with objective combat triggers.

Dragon-Wind counts native willing path distance controlled by its owner. Completed
attacks generate Momentum after all hit riders; pressure owns cap/round/expiry.
The speed passive is compiled as a normal motion row. Named conversions are
ordinary no-action choices, paid by the catalog before their effect executes.
No affinity-sphere approximation is used to invent Fixed Foundation Scope.
"""
from . import effect, hook, note

BLOCK = 'foundations1_conversion'
DISTANCE = 'foundations1_dragon_moved_ft'
MARROW = 'foundation.dragon_wind_vessel_v0_2E.dragon_marrow_drive'
SOVEREIGN = 'foundation.dragon_wind_vessel_v0_2E.sovereign_momentum'
STORM_MARROW = 'foundation.dragon_wind_vessel_v0_2E.storm_marrow_guard'
WIND_BODY_STEP = 'foundation.dragon_wind_vessel_v0_2E.wind_body_step'
DRIVE_SLOT = 'momentum_drive_added_damage'
WALK_STEP = 'condition:typed.foundations1_walk_step'
WIND_STEP = 'condition:typed.foundations1_wind_body_step'
POOL = 'resource:foundation.dragon_wind_momentum'


def _owns(engine, actor, mechanic_id):
    """True when this fighter's own compiled bundle lists the foundation mechanic."""
    if actor is None:
        return False
    for bundle in (getattr(engine, 'typed_bundle_documents', None) or ()):
        if (bundle.get('actor_id') or '') != actor.entity_id:
            continue
        if any(row.get('id') == mechanic_id for row in bundle.get('modifiers') or ()):
            return True
    return False


def _moved_twenty(actor):
    """The Dragon-Marrow Drive precondition: at least 20 feet of native willing movement this turn."""
    return int(actor.turn_flags.get(DISTANCE, 0)) >= 20


@hook('compile_block')
def compile_conversion(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': spec['kind'], 'pb': int(numbers['pb']),
             'key_mod': int(numbers['key_mod'])}]


@hook('compile_actions')
def conversions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    made = []
    for row in info['passives']:
        if row.get('block') != BLOCK or row.get('kind') not in ('momentum_step', 'banked_coals') or not row.get('resource_id'):
            continue
        name = info['mechanics'][row['feature_id']]['name']
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{row['kind']}",
            display_name=name, owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', costs=((row['resource_id'], 1),),
            parameters={'typed': {'source': row['feature_id'], 'numbers': info['numbers'],
                'effects': [{'type': 'foundations1_conversion', 'kind': row['kind']}],
                'riders': [], 'duration': {'kind': 'instant'}},
                'expected_temp_hp': row['pb'] + row['key_mod'] if row['kind'] == 'banked_coals' else 0}))
    return made


@effect('foundations1_conversion', harmful=False)
def conversion(ctx, eff):
    from .. import typed_executor
    if eff['kind'] == 'momentum_step':
        from .. import flight
        from .needle import ask, CHOICE, checkpoint_id, timed_condition
        # Wind-Body Step (Refined rider): the increase becomes 15 ft instead of 10 ft.
        step = 15 if _owns(ctx.engine, ctx.actor, WIND_BODY_STEP) else 10
        options = ['walk']
        if flight.profile(ctx.engine, ctx.actor).speed_ft > 0:
            options.append('fly')
        selected = options[0]
        if len(options) > 1:
            chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'momentum_speed', ctx.actor.entity_id),
                ctx.actor, CHOICE + 'momentum_speed', options, minimum=1, maximum=1, preferred=['walk'],
                name='Momentum Step', target_id=ctx.actor.entity_id, labels={'walk': f'Walking speed (+{step} feet until this turn ends)', 'fly': f'Flying speed (+{step} feet until this turn ends)'},
                prompt=f'Momentum Step: spend 1 Dragon-Wind Momentum to increase one of your existing speeds by {step} feet until this turn ends. Choose walking or flying.')
            selected = chosen[0]
        if selected == 'fly':
            ctx.engine._apply_condition(ctx.actor, 'condition:typed.foundations1_fly_step', ctx.source,
                ctx.actor.entity_id, expires_on='END_OF_CURRENT_TURN',
                data={'fly_speed_bonus_ft': step, 'label': f'Momentum Step: flying speed +{step} feet'})
        else:
            # Walking: +step feet to the walking speed until this turn ends, credited to
            # the movement allowance the way Complete Step credits its own boost, so the
            # feet are usable this turn and the speed itself reads higher for every other
            # consumer (Dash, stands, carries). The shared pool does not distinguish spent
            # base feet from Dash or separate grants, so only the improvement over an
            # earlier Step is credited (lead direction 2026-10-12).
            existing = [c for c in ctx.actor.conditions.values() if c.condition_id == WALK_STEP]
            previous = max((int((c.data or {}).get('speed_delta') or 0) for c in existing), default=0)
            increase = max(0, step - previous)
            if increase:
                from .condition_ownership import remove_instance
                for held in existing:
                    remove_instance(ctx.engine, ctx.actor, held.instance_id, 'foundations1_walk_step')
                extra = increase * (1 + flight.dash_count(ctx.actor))
                ctx.actor.movement_remaining_ft += extra
                ctx.actor.turn_flags['movement_allowance_adjustment_ft'] = int(
                    ctx.actor.turn_flags.get('movement_allowance_adjustment_ft', 0) + extra)
                ctx.engine._apply_condition(ctx.actor, WALK_STEP, ctx.source, ctx.actor.entity_id,
                    expires_on='END_OF_CURRENT_TURN',
                    data={'speed_delta': step, 'label': f'Momentum Step: walking speed +{step} feet'})
        # Wind-Body Step's second half: advantage on the next Athletics or Acrobatics
        # check before end of turn, to keep footing, pass through pressure, avoid
        # falling, resist forced movement or maintain legal movement.
        if step == 15:
            timed_condition(ctx.engine, ctx.actor, WIND_STEP, ctx.source, ctx.actor.entity_id,
                            'END_OF_CURRENT_TURN',
                            {'label': 'Wind-Body Step: Advantage on your next Athletics or Acrobatics check this turn'})
        return
    else:
        amount = int(ctx.numbers['pb']) + int(ctx.numbers['key_mod'])
        rows = ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, [])
        if any(r.get('block') == BLOCK and r.get('kind') == 'heart_cauldron_body' for r in rows):
            flag = 'foundations1_round_cauldron'
            if ctx.actor.turn_flags.get(flag) != ctx.engine.state.round_number:
                ctx.actor.turn_flags[flag] = ctx.engine.state.round_number
                amount += int(ctx.numbers['pb'])
        typed_executor.run_effects(ctx, [{'type': 'temp_hp', 'flat': max(0, amount), 'applies_to': 'self'}])


@hook('event')
def controlled_distance(engine, event_type, kwargs):
    if event_type != 'MOVEMENT_COMMITTED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    payload = kwargs.get('payload') or {}
    if actor is None or payload.get('forced') or payload.get('dragged_by') or payload.get('teleport'):
        return
    if not any(r.get('block') == 'generate' and 'dragon_wind_hit' in r.get('on', [])
               for r in engine.typed_passive_rows.get(actor.entity_id, [])):
        return
    # Only actual walked path edges count. Teleport arrivals have no walked path.
    distance = max(0, len(payload.get('path') or []) - 1) * engine.grid.square_size_ft
    actor.turn_flags[DISTANCE] = int(actor.turn_flags.get(DISTANCE, 0)) + distance


@hook('attack_completed')
def momentum_after_hit(engine, notice, intent):
    actor = engine.state.actors.get(notice.attacker_id)
    if actor is None or not notice.hit or int(actor.turn_flags.get(DISTANCE, 0)) < 20:
        return
    from .. import pressure
    if pressure.generate(engine, actor, 'dragon_wind_hit'):
        note(engine, notice.source_id, actor, f'{actor.display_name} gains Dragon-Wind Momentum after the hit resolves.')


@hook('effect_allowed')
def marrow_drive_needs_the_move(ctx, effect):
    """Dragon-Marrow Drive rides Momentum Drive only after 20 feet of movement this turn.

    The printed precondition ("after moving at least 20 ft this turn") is
    free text the compiler only prints; this gate answers for the whole
    Dragon-Marrow packet -- its 1d4+PB damage and its Strength/Dexterity
    save -- keyed on the packet's source_modifier, so neither half lands
    without the move. Inert for anyone who does not own Dragon-Marrow Drive.
    """
    if effect.get('source_modifier') != MARROW:
        return None
    if not _owns(ctx.engine, ctx.actor, MARROW):
        return None
    return _moved_twenty(ctx.actor)


@hook('effect_allowed')
def marrow_drive_replaces_the_drive_damage(ctx, effect):
    """Dragon-Marrow Drive REPLACES Momentum Drive's added damage (1d4+PB, not 1d4+2PB).

    Momentum Drive's own added damage carries effect_slot
    "momentum_drive_added_damage". When the Dragon-Marrow precondition
    holds, that slot is vetoed and the rider's 1d4+PB lands instead --
    exactly "the added damage becomes 1d4 + PB". Without the move the
    rider's own effects are vetoed (marrow_drive_needs_the_move) and the
    plain PB lands unchanged. Inert for anyone who does not own it.
    """
    if effect.get('effect_slot') != DRIVE_SLOT:
        return None
    if not _owns(ctx.engine, ctx.actor, MARROW):
        return None
    return not _moved_twenty(ctx.actor)


@effect('dragon_marrow_oa_lock', harmful=True)
def dragon_marrow_oa_lock(ctx, eff):
    """On a failed Dragon-Marrow save, prevent only OAs against the mover this turn."""
    for target in ctx.targets:
        ctx.engine._apply_condition(
            target, 'condition:typed.no_opportunity_attacks', ctx.source,
            ctx.actor.entity_id, expires_on='END_OF_CURRENT_TURN',
            data={'against': ctx.actor.entity_id,
                  'label': f'Dragon-Marrow Drive: no Opportunity Attacks against {ctx.actor.display_name} this turn'})


@hook('ability_check_mode')
def wind_body_step_mode(engine, owner, ability, skill, other):
    """Wind-Body Step: Advantage on the next Athletics or Acrobatics check before end of turn.

    The printed check families (keep footing, pass through pressure, avoid
    falling, resist forced movement, maintain legal movement) are the two
    physical skills; the condition is consumed by the first check it covers,
    so the Advantage is spent exactly once. Inert without the condition.
    """
    held = [c for c in owner.conditions.values() if c.condition_id == WIND_STEP]
    if not held or str(skill).lower() not in ('athletics', 'acrobatics'):
        return None
    return 'ADVANTAGE'


@hook('escape_check_mode')
def wind_body_step_escape_mode(engine, escaper, grips, ability, skill):
    """Apply Wind-Body Step's check mode to hold escapes as well as ordinary checks."""
    if not any(c.condition_id == WIND_STEP for c in escaper.conditions.values()):
        return None
    return 'ADVANTAGE' if str(skill or '').lower() in ('athletics', 'acrobatics') else None


@hook('escape_roll_resolved')
def spend_wind_body_step_escape(engine, escaper, grips, success, kind, source):
    """Consume the one-check Wind-Body benefit only after a qualifying escape is rolled."""
    if kind != 'check':
        return
    for condition in list(escaper.conditions.values()):
        if condition.condition_id == WIND_STEP:
            engine._remove_condition(escaper, WIND_STEP, condition.source_definition_id or 'foundations1_wind_body_step')


@hook('escape_check_choice_required')
def wind_body_escape_skill_choice(ctx, effect, dc, grips, hazards):
    if any(c.condition_id == WIND_STEP for c in ctx.actor.conditions.values()):
        return {'name': 'Wind-Body Step', 'feature_id': WIND_BODY_STEP}
    return None


@hook('event')
def spend_wind_body_step_check(engine, event_type, kwargs):
    """Consume Wind-Body Step after its first qualifying ordinary check resolves."""
    if event_type != 'CHECK_ROLLED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or str((kwargs.get('payload') or {}).get('skill') or '').lower() not in ('athletics', 'acrobatics'):
        return
    for condition in list(actor.conditions.values()):
        if condition.condition_id == WIND_STEP:
            engine._remove_condition(actor, WIND_STEP, condition.source_definition_id or 'foundations1_wind_body_step')


@hook('event')
def sovereign_second_conversion(engine, event_type, kwargs):
    """Resolve a distinct second conversion within the triggering spend.

    Drive and Guard already own the triggering hit/damage; neither is legal
    on a standalone Step. During the owner's turn, Step is legal alongside
    either. Persist the first/second choice, never refund a spend or carry
    buying power to an unrelated event. A declined pair keeps the round use.
    """
    if event_type != 'RESOURCE_SPENT':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    payload = kwargs.get('payload') or {}
    if actor is None or not actor.active or str(payload.get('resource_id') or '') != POOL:
        return
    if not _owns(engine, actor, SOVEREIGN) or not _moved_twenty(actor):
        return
    first = str(kwargs.get('source_definition_id') or '')
    prefix = 'foundation.dragon_wind_vessel_v0_2E.'
    if first not in (prefix + 'momentum_drive', prefix + 'momentum_guard'):
        return
    if engine.state.current_actor_id != actor.entity_id:
        return
    step = next((a for a in engine.action_catalog.values()
                 if a.owner_id == actor.entity_id and
                 (a.parameters.get('typed') or {}).get('source') == prefix + 'momentum_step'), None)
    if step is None:
        return
    clock = actor.turn_flags.setdefault('foundations1_sovereign', {})
    if clock.get('round') == engine.state.round_number:
        return
    from .needle import ask, CHOICE, checkpoint_id
    intent = getattr(engine, '_active_intent', None)
    selected = ask(engine, intent, checkpoint_id(engine, 'sovereign_second', actor.entity_id, first),
                   actor, CHOICE + 'sovereign_second', ['momentum_step'],
                   labels={'momentum_step': 'Momentum Step: increase an existing speed until this turn ends'},
                   prompt=f'Sovereign Momentum: {actor.display_name} may also choose Momentum Step '
                          f'for this {first.rsplit(".", 1)[-1].replace("_", " ").title()} spend, '
                          'with no second Momentum cost. Increase one existing speed until this turn ends?',
                   name='Sovereign Momentum', feature_id=SOVEREIGN,
                   target_id=actor.entity_id, allow_decline=True, preferred=['momentum_step'])
    if not selected:
        return
    clock['round'] = engine.state.round_number
    clock['first'] = first
    clock['second'] = prefix + selected[0]
    from ..typed_executor import Context
    conversion(Context(engine, actor, step, intent, step.parameters['typed'], [actor], actor),
               {'kind': 'momentum_step'})
    note(engine, SOVEREIGN, actor,
         f'{actor.display_name} uses Sovereign Momentum: Momentum Step joins this spend without a second Momentum cost.')
