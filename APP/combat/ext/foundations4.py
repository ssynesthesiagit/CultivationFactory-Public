"""Objective base conversions for Sword Bones, Blackblood and Weak Reed.

Generation happens after settled hostile events; pressure owns capacity, round
limits, refresh and expiry. Existing payment guards prevent same-event spends.
Sword Bones numeric improvements use the public foundation_conversion_bonus
quote/settlement provider. Refined owners publish their distinct selected rows;
Perfected Bone-Deep Severance owns one shared once-per-round increase.
"""
from . import effect, hook, note

BLOCK = 'foundations4'
DISTANCE = 'foundations4_round_reed_distance'


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': spec['kind'], 'pb': int(numbers['pb']),
             'key_mod': int(numbers['key_mod']), 'trigger_owner': 'foundations4',
             **({'refined_expression': str(spec['refined_expression'])} if spec.get('refined_expression') else {})}]


def rows(engine, actor, kinds):
    return [r for r in engine.typed_passive_rows.get(actor.entity_id, [])
            if r.get('block') == BLOCK and r.get('kind') in kinds]


def conversion_evolution_pb(engine, actor, row):
    """Shared public helper (combat/ext/__init__.py): the additional PB the
    actor's selected Refined expression adds to one compiled foundations4
    conversion row's numeric benefit.

    Every Foundation conversion family's Refined rider reads this one
    helper on its own compiled row. A selected expression and a Perfected
    improvement stack at the same numeric point of the same conversion --
    the same actual spend, Reaction and damage packet, never a second
    Reaction or resource spend. The Perfected term is settled by
    foundation_conversion_bonus.settle_conversion_bonus and this helper
    adds only the Refined term. Returns 0 for a row that names no Refined
    expression, an actor that has not selected exactly that expression, or
    a vetoing foundation_expression_selected reply. An actor selects the
    expression only when a hook explicitly answers True; absent replies and
    vetoes both leave the base benefit alone."""
    expression = str(row.get('refined_expression') or '')
    if not expression:
        return 0
    from . import run_strict
    answers = run_strict('foundation_expression_selected', engine, actor, expression)
    return int(row['pb']) if True in answers and False not in answers else 0


def refined_expression_name(row):
    """Printed leaf name of the Refined expression sealed on a compiled row."""
    leaf = str(row.get('refined_expression') or '').rsplit('.', 1)[-1]
    return leaf.removeprefix('refined_').replace('_', ' ').title()


def holds(engine, actor, row):
    from ..typed_reactions import _holds
    return actor.active and actor.current_hp > 0 and _holds(engine, actor, row['resource_id'], 1)


def pay(engine, actor, row, checkpoint, *, reaction=False, other=None, trigger=None):
    from ..typed_reactions import _consent, can_use_reaction, open_reaction
    from ..activation_payments import reaction_completed
    if not holds(engine, actor, row) or (reaction and not can_use_reaction(engine, actor, other, row)):
        return False
    if not _consent(engine, {'feature_id': row['feature_id'], 'ask': True}, actor, checkpoint, trigger=trigger):
        return False
    engine._spend_resource(actor, row['resource_id'], 1, row['feature_id'])
    if reaction:
        if not reaction_completed(engine, actor, row['feature_id']):
            return False
        open_reaction(engine, row, actor, (actor.entity_id,), checkpoint)
    return True


def damage_conversion(ctx, target, kind):
    if target.team_id == ctx.actor.team_id:
        return
    from .. import typed_executor
    from .foundation_resources import hit_damage_type
    from .foundation_conversion_bonus import conversion_bonus, settle_conversion_bonus
    for row in rows(ctx.engine, ctx.actor, {'cut', 'return'}):
        amount = row['pb'] + conversion_bonus(ctx.engine, ctx.actor, row['kind'])
        trigger = {'actor_id': ctx.actor.entity_id, 'target_id': target.entity_id,
                   'affected_id': target.entity_id, 'source_id': ctx.action.source_definition_id,
                   'action_name': ctx.action.display_name, 'damage_amount': int(amount)}
        if not pay(ctx.engine, ctx.actor, row, 'FOUNDATION_SPEND', trigger=trigger):
            continue
        payment = next(e for e in reversed(ctx.engine.events) if e.event_type == 'RESOURCE_SPENT'
                       and e.actor_id == ctx.actor.entity_id and e.source_definition_id == row['feature_id'])
        amount = row['pb'] + settle_conversion_bonus(ctx.engine, ctx.actor, row['kind'],
                    str(payment.sequence), row['feature_id'])
        typed_executor.run_effects(typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent,
            ctx.typed, [target], target, {}), [{'type': 'extra_damage', 'applies_to': 'target',
            'flat': amount, 'damage_types': [hit_damage_type(ctx.engine, ctx.actor, target) or 'UNTYPED'],
            'evidence': 'Spend a pre-existing Foundation resource to add PB damage to the hit.'}])
        note(ctx.engine, row['feature_id'], ctx.actor,
             f"{ctx.actor.display_name} uses {row['feature_id'].rsplit('.', 1)[-1].replace('_', ' ').title()}, spending 1 {row['resource_id'].rsplit('.', 1)[-1].replace('_', ' ')} and adding {amount} damage.", (target,))


@hook('damage_response_reduction')
def guard(engine, target, amount, damage_type, source_id, source_actor_id):
    if amount <= 0:
        return None
    source = engine.state.actors.get(source_actor_id)
    source_action = engine.action_catalog.get(source_id)
    from .foundation_conversion_bonus import settle_conversion_bonus
    for row in rows(engine, target, {'sheath', 'blackblood_guard', 'reed_guard'}):
        trigger = {'actor_id': source_actor_id, 'target_id': target.entity_id,
                   'source_id': source_id, 'action_name': (source_action.display_name if source_action else 'a harmful effect'),
                   'damage_amount': int(amount), 'damaged_target_id': target.entity_id,
                   'damage_type': str(damage_type or 'untyped')}
        if pay(engine, target, row, 'FOUNDATION_GUARD', reaction=True, other=source, trigger=trigger):
            payment = next(e for e in reversed(engine.events) if e.event_type == 'RESOURCE_SPENT'
                           and e.actor_id == target.entity_id and e.source_definition_id == row['feature_id'])
            bonus = settle_conversion_bonus(engine, target, row['kind'], str(payment.sequence), row['feature_id'])
            reduction = max(0, row['pb'] + (0 if row['kind'] == 'reed_guard' else row['key_mod'])
                            + bonus + conversion_evolution_pb(engine, target, row))
            reduction = min(amount, reduction)
            note(engine, row['feature_id'], target,
                 f"{target.display_name} uses {row['feature_id'].rsplit('.', 1)[-1].replace('_', ' ').title()}, spending 1 {row['resource_id'].rsplit('.', 1)[-1].replace('_', ' ')} and a Reaction to reduce damage by {reduction}.")
            return reduction
    return None


def generates(engine, actor, reason):
    return any(r.get('block') == 'generate' and reason in r.get('on', [])
               for r in engine.typed_passive_rows.get(actor.entity_id, []))


@hook('attack_completed')
def severance_and_reed(engine, notice, intent):
    from .. import pressure
    actor = engine.state.actors.get(notice.attacker_id)
    target = engine.state.actors.get(notice.target_id)
    if actor is None or target is None:
        return
    if notice.hit and target.active:
        from ..typed_executor import Context
        action = engine.action_catalog.get(notice.source_id)
        if action is not None:
            typed = action.parameters.get('typed') or {}
            damage_conversion(Context(engine, actor, action, intent, typed, [target], target, {}), target, notice.kind)
    if notice.hit and notice.kind == 'weapon':
        pressure.generate(engine, actor, 'severance_hit')
    elif not notice.hit and actor.team_id != target.team_id:
        if int(target.turn_flags.get(DISTANCE, 0)) >= 10:
            pressure.generate(engine, target, 'reed_missed')


@hook('event', nested=True)
def distance_and_blackblood(engine, event_type, kwargs):
    from .. import pressure
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    payload = kwargs.get('payload') or {}
    if event_type == 'MOVEMENT_COMMITTED':
        if actor is None or not generates(engine, actor, 'reed_missed') or payload.get('forced') or payload.get('dragged_by') or payload.get('teleport'):
            return
        actor.turn_flags[DISTANCE] = int(actor.turn_flags.get(DISTANCE, 0)) + max(0, len(payload.get('path') or []) - 1) * engine.grid.square_size_ft
    elif event_type == 'DAMAGE_COMMITTED' and actor is not None:
        if int(payload.get('hp_damage', 0)) + int(payload.get('temporary_hp_absorbed', 0)) <= 0:
            return
        for tid in kwargs.get('target_ids') or ():
            target = engine.state.actors.get(tid)
            if (target is not None and actor.team_id != target.team_id and target.life_state is None
                    and not any(c.condition_id in {'condition:typed.unconscious', 'condition:typed.life_unconscious', 'condition:typed.asleep'} for c in target.conditions.values())
                    and 0 < target.current_hp <= target.maximum_hp // 2):
                pressure.generate(engine, target, 'blackblood_damaged')


@hook('turn_start')
def reset_reed_distance(engine, actor):
    if generates(engine, actor, 'reed_missed'):
        actor.turn_flags[DISTANCE] = 0


@effect('foundations4_recovery', harmful=False)
def light_body_recovery(ctx, eff):
    from .. import posture, typed_executor
    from .needle import ask, CHOICE, checkpoint_id
    amount = max(0, int(ctx.numbers['pb']) + int(ctx.numbers['key_mod']))
    typed_executor.run_effects(ctx, [{'type': 'temp_hp', 'flat': amount, 'applies_to': 'self'}])
    if posture.standing_cost(ctx.engine, ctx.actor, cost=0) is None:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'light_body_stand', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'light_body_stand', ['stand'], minimum=1, maximum=1, allow_decline=True,
        name='Light-Body Recovery', target_id=ctx.actor.entity_id, labels={'stand': 'Stand up without spending movement'},
        prompt='Light-Body Recovery: you gained temporary Hit Points. Stand up now without spending movement?')
    if selected:
        posture.stand_up(ctx.engine, ctx.actor, source_id=ctx.source, cost=0)


SUPPORT = 'condition:typed.foundations4_support'
SUPPORT_SCOPES = {
    'moon': frozenset({'damage:cold', 'poisoned', 'damage:poison', 'necrotic_drain', 'life_drain',
                       'corpse_qi', 'hostile_stillness', 'fear_darkness', 'fear_death', 'fear_cold'}),
    'spring': frozenset({'poisoned', 'damage:poison', 'disease', 'rot', 'withering',
                         'anti_healing', 'spiritual_depletion'}),
}


@effect('foundations4_support', harmful=False)
def support_breath(ctx, eff):
    from ..typed_executor import block_temp_hp, effect_expiry
    target = ctx.target or ctx.actor
    # Beneficial automatic recipients are allies. One selected target only.
    if target.team_id != ctx.actor.team_id:
        return
    amount = max(0, int(ctx.numbers['pb']) + int(ctx.numbers['key_mod']))
    block_temp_hp(ctx, {'type':'temp_hp', 'flat':amount, 'applies_to':'target'})
    for condition in list(target.conditions.values()):
        if condition.condition_id == SUPPORT and condition.source_actor_id == ctx.actor.entity_id:
            target.conditions.pop(condition.instance_id)
            ctx.engine._append_event('CONDITION_REMOVED', condition.source_definition_id,
                actor_id=target.entity_id, target_ids=(target.entity_id,),
                payload={'condition_id':SUPPORT, 'instance_id':condition.instance_id, 'reason':'REPLACED'})
    ctx.engine._apply_condition(target, SUPPORT, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {'duration':{'kind':'until_start_of_next_turn'}}, target, condition=True),
        data={'kind':eff['kind'], 'label':ctx.action.display_name,
              'reading': ('Advantage on your next saving throw against cold, necrotic drain, poison, fear caused by darkness, death or cold, corpse-qi contamination, or hostile stillness'
                          if eff['kind'] == 'moon' else
                          'Advantage on your next saving throw against poison, disease, rot, withering, anti-healing pressure or spiritual depletion')
                         + f" until {ctx.actor.display_name}’s next turn."})


@hook('save')
def support_save(ctx, subject, ability, named):
    named = set(named or ())
    if subject.team_id != ctx.actor.team_id and 'spiritual_stillness' in named:
        named.add('hostile_stillness')
    used = [c for c in subject.conditions.values() if c.condition_id == SUPPORT
            and set(named or ()) & SUPPORT_SCOPES.get(c.data.get('kind'), frozenset())]
    for condition in used:
        subject.conditions.pop(condition.instance_id)
        ctx.engine._append_event('CONDITION_REMOVED', condition.source_definition_id,
            actor_id=subject.entity_id, target_ids=(subject.entity_id,),
            payload={'condition_id':SUPPORT, 'instance_id':condition.instance_id, 'reason':'CONSUMED'})
    return {'bonus':0, 'modes':['ADVANTAGE']} if used else None


@hook('save_roll_tags')
def foundation_save_roll_tags(ctx, subject, ability, named):
    """Expose only explicitly established hazard tags for owned base benefits."""
    tags = set(named or ())
    owned = [row for row in ctx.engine.typed_passive_rows.get(subject.entity_id, [])
             if row.get('block') == 'd20_rewrite'
             and row.get('kind') in {'foundations4_reed_recovery', 'foundations4_blackblood_refusal'}]
    forwarded = set()
    if any(row['kind'] == 'foundations4_reed_recovery' for row in owned):
        forwarded |= tags & {'forced_movement'}
    if any(row['kind'] == 'foundations4_blackblood_refusal' for row in owned):
        forwarded |= tags & {'damage:poison'}
    return sorted(forwarded) or None


@hook('decision_text')
def guard_prompt(engine, context, printed_rules):
    source = str(context.get('reaction_source_id') or '').removeprefix('reaction:typed.')
    if not source.startswith('foundation.') or not source.endswith(('.sheath_bone_guard', '.blackblood_guard', '.bend_without_breaking_guard')):
        return None
    trigger = context.get('choice_trigger') or {}
    actor = engine.state.actors.get(trigger.get('actor_id'))
    target = engine.state.actors.get(trigger.get('target_id'))
    attacker = actor.display_name if actor else 'A creature'
    protected = target.display_name if target else 'you'
    action = trigger.get('action_name') or 'a harmful effect'
    amount = trigger.get('damage_amount')
    feature = source.rsplit('.', 1)[-1].replace('_', ' ').title()
    reactor = engine.state.actors.get(context.get('reactor_id'))
    row = next((item for item in rows(engine, reactor, {'sheath', 'blackblood_guard', 'reed_guard'})
                if item.get('feature_id') == source), None) if reactor else None
    resource_name = (row or {}).get('resource_id', 'Foundation resource').rsplit('.', 1)[-1].replace('_', ' ')
    amount_text = f" {amount}" if amount is not None else ""
    from .foundation_conversion_bonus import conversion_bonus, conversion_consent_note
    increase = conversion_bonus(engine, reactor, row['kind']) if reactor and row else 0
    extra = conversion_evolution_pb(engine, reactor, row) if reactor is not None and row is not None else 0
    value = int(row['pb']) + (0 if row['kind'] == 'reed_guard' else int(row['key_mod'])) + increase + extra if row else 0
    return {'summary': f"{attacker}'s {action} would deal{amount_text} damage to {protected}. Use {feature} to reduce it?",
            'table_note': f"Using this spends 1 {resource_name} and your Reaction." +
                (f" Reduce this damage by up to {value}, including your Severance Edge evolution bonus." if increase else '') +
                (f" Your selected Refined expression {refined_expression_name(row)} adds {extra} to the reduction." if extra else '') +
                (conversion_consent_note(engine, reactor, row['kind']) if row else '') +
                " Declining spends nothing."}


@hook('decision_text')
def conversion_prompt(engine, context, printed_rules):
    source = str(context.get('reaction_source_id') or '').removeprefix('reaction:typed.')
    if not source.startswith('foundation.') or not source.endswith(('.sword_bone_cut', '.blackblood_return')):
        return None
    trigger = context.get('choice_trigger') or {}
    attacker = engine.state.actors.get(trigger.get('actor_id'))
    target = engine.state.actors.get(trigger.get('affected_id') or trigger.get('target_id'))
    if attacker is None or target is None:
        return None
    row = next((item for item in rows(engine, attacker, {'cut', 'return'})
                if item.get('feature_id') == source), None)
    if row is None:
        return None
    action = str(trigger.get('action_name') or 'attack')
    ability = source.rsplit('.', 1)[-1].replace('_', ' ').title()
    resource = row['resource_id'].rsplit('.', 1)[-1].replace('_', ' ')
    amount = int(trigger.get('damage_amount', row['pb']))
    from .foundation_conversion_bonus import conversion_consent_note
    return {'summary': f"Your {action} hit {target.display_name}. Add {amount} damage to that hit with {ability}?",
            'table_note': f"Using this spends 1 {resource}. It adds {amount} damage to {target.display_name}; declining spends nothing." +
                conversion_consent_note(engine, attacker, row['kind'])}
