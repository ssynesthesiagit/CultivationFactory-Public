"""Exact printed Ink Insights and the recipient-limited correcting stroke.

Shared ``owned`` lookup lets ink_riders describe the writer's mark lifetime.
"""
from . import hook

BLOCK = 'ink_second_pass'
MASTER = 'insight.master-calligrapher'
GUARD = 'insight.brush-armed-guard'
SHIELD = 'tianxia.talent.ink.brushstroke_shield'
CORRECTION = 'tianxia.talent.ink.vermilion_correction'


@hook('compile_block')
def compile_ink(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': spec['kind'], 'numbers': {
        key: int(numbers[key]) for key in ('pb', 'cl', 'key_mod')}}]


def owned(engine, actor, kind):
    return next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                 if r.get('block') == BLOCK and r.get('kind') == kind), None)


@hook('compile_passives')
def ink_capacity(passives, info):
    # The sphere chassis prints PB + key modifier, minimum 1. A fresh writer's
    # ordinary Press Mark supplies that chassis without suppressing its action.
    if 'INK_BASE_PRESS_MARK' not in info['owned_ids']:
        return passives
    n = info['numbers']
    passives = [{**r, 'numbers': dict(n)} if r.get('block') == BLOCK else r for r in passives]
    return [*passives, {'block': 'mark_caps', 'feature_id': 'INK_BASE_PRESS_MARK',
                       'caps': {'ink_mark': max(1, int(n['pb']) + int(n['key_mod']))}}]


@hook('mark_cap')
def master_capacity(ctx, name):
    if name.lower() == 'ink_mark' and owned(ctx.engine, ctx.actor, 'master'):
        return {'add': 2}
    return None


@hook('mark_duration')
def master_duration(ctx, name, kind):
    if name.lower() == 'ink_mark' and kind == 'hours' and owned(ctx.engine, ctx.actor, 'master'):
        # One hour is the chassis lifetime; shorter talented marks retain their
        # own minute/turn/Concentration duration and longer marks are not cut.
        return {'kind': 'hours', 'amount': 8, 'minimum': True}
    return None


def guarded_mark(engine, owner, attacker, intent):
    from ..typed_reactions import triggered_context
    from .needle import ask, checkpoint_id
    from ..target_knowledge import can_see
    from .choice_prompt import action_context
    row = owned(engine, owner, 'guard')
    if not row or not owner.active or not attacker or not attacker.active:
        return
    if engine._distance_actor_to_actor(owner, attacker) > 60 or not can_see(engine, owner, attacker):
        return
    attack_context = engine.d20_context() or {}
    attack_source = str(attack_context.get('source_id') or getattr(engine, '_active_action_source_id', '') or '')
    prompt_context = action_context(engine, attacker, attack_source, attacker)
    pick = ask(engine, intent, checkpoint_id(engine, 'ink_guard', attacker.entity_id), owner,
        'choice:needle.ink_guard', ['mark'], allow_decline=True,
        default='first' if attacker.team_id != owner.team_id else 'decline',
        name='Brush-Armed Guard', target_id=attacker.entity_id,
        labels={'mark': 'Place an Ink Mark; unwilling attacker makes a Dexterity save'},
        prompt=f'Brush-Armed Guard: Brushstroke Shield stopped all damage from {attacker.display_name}. Place an Ink Mark on them? The mark lets you target them with Ink abilities that require your mark, and lasts 1 hour (8 hours for Master Calligrapher). No extra cost or Reaction; an unwilling creature makes a Dexterity save.',
        prompt_context=prompt_context)
    if not pick:
        return
    ctx = triggered_context(engine, owner, attacker,
        {**row, 'name': 'Brush-Armed Guard', 'prompt_context': prompt_context}, intent)
    # Consent belongs to the recipient, exactly as for Press Mark; this also
    # supplies mark capacity, master lifetime and source-owner attribution.
    from .ink_riders import press_mark
    press_mark(ctx, {'guard': True, 'prompt_context': prompt_context})


@hook('hit_absorbed')
def shield_absorbed(engine, protected, attacker, reducers):
    if SHIELD not in reducers or attacker is None:
        return
    from .attack_reduction import follow_up_scope
    # The accepted guard receipt lies after this strike's ATTACK_ROLLED. A
    # different attack, nested packet or a shield on another target cannot lend
    # its owner or optional Insight to this reduction.
    for event in reversed(engine.events):
        if event.event_type == 'ATTACK_ROLLED':
            break
        if (event.event_type == 'REACTION_RESOLVED' and event.source_definition_id == SHIELD
                and attacker.entity_id in event.target_ids
                and event.payload.get('protects', event.actor_id) == protected.entity_id):
            owner = engine.state.actors.get(event.actor_id)
            if owner:
                with follow_up_scope(engine, protected, attacker.entity_id, SHIELD):
                    guarded_mark(engine, owner, attacker, getattr(engine, '_active_intent', None))
            return


@hook('event')
def ink_reaction_receipts(engine, event_type, kwargs):
    if event_type != 'REACTION_RESOLVED':
        return
    source = kwargs.get('source_definition_id')
    if not source:
        source = engine.events[-1].source_definition_id
    payload = kwargs.get('payload') or {}
    targets = kwargs.get('target_ids') or ()
    if (source == SHIELD and payload.get('checkpoint') == 'DAMAGE_APPLICATION'
            and payload.get('pending_before', 0) > 0 and payload.get('pending_after') == 0):
        owner = engine.state.actors.get(kwargs.get('actor_id'))
        attacker = engine.state.actors.get(next(iter(targets), ''))
        if owner:
            guarded_mark(engine, owner, attacker, getattr(engine, '_active_intent', None))


@hook('d20_bonus')
def vermilion_correction(engine, roll, intent):
    from ..typed_reactions import can_use_reaction, open_reaction, spend_reaction
    from ..activation_payments import reaction_completed
    from ..gate2_runtime_models import DiceSpec
    from .choice_costs import payable
    from . import cp_pools
    from .needle import ask, checkpoint_id
    from ..target_knowledge import located
    from ..typed_executor import bears_mark
    context = engine.d20_context(roll)
    subject = engine.state.actors.get(roll.actor_id)
    if (not context or context['kind'] != 'check' or subject is None or not subject.active
            or subject.turn_flags.get('_round_ink_correction') == engine.state.round_number):
        return None
    from .choice_prompt import action_context
    check_source = str(context.get('source_id') or '')
    from .d20_rewrite import check_source_id
    resolved_source = check_source_id(engine, 'CHECK:' + check_source)
    check_action = engine.action_catalog.get(resolved_source)
    if check_action:
        check_name = str(check_action.display_name)
    else:
        from types import SimpleNamespace
        from .d20_rewrite import roll_source_name
        check_name = roll_source_name(engine, SimpleNamespace(kind='check', source_id=check_source, source_name=None))
    prompt_context = action_context(engine, subject, resolved_source if check_action else '', subject, action=check_action)
    for owner in engine.state.actors.values():
        row = owned(engine, owner, 'correction')
        if not row or not can_use_reaction(engine, owner, subject, row):
            continue
        if (engine._distance_actor_to_actor(owner, subject) > 30
                or not bears_mark(subject, owner.entity_id, 'ink_mark') or not located(engine, owner, subject)):
            continue
        pool = cp_pools.of(owner, at_least=1)
        price = payable(owner, pool, 1) if pool else None
        if not price:
            continue
        preferred = 'add' if owner.team_id == subject.team_id else 'subtract'
        picks = ask(engine, intent, checkpoint_id(engine, 'ink_correction', subject.entity_id), owner,
            'choice:needle.ink_correction', ['add', 'subtract'], allow_decline=True,
            preferred=[preferred], payment=price,
            labels={'add': f'Add 1d4 to {check_name}', 'subtract': f'Subtract 1d4 from {check_name}'},
            name='Vermilion Correction', target_id=subject.entity_id,
            prompt=f"Vermilion Correction: add or subtract 1d4 from {subject.display_name}'s {check_name} before its result. Spend {price.quote()} and your Reaction; this creature can be corrected once this round.",
            prompt_context=prompt_context)
        if not picks:
            continue
        # Reserve the recipient before payment can open any nested checkpoint.
        subject.turn_flags['_round_ink_correction'] = int(engine.state.round_number)
        open_reaction(engine, row, owner, (subject.entity_id,), 'D20_PENDING')
        spend_reaction(engine, owner, row)
        price.pay(engine, owner, CORRECTION)
        if not reaction_completed(engine, owner, CORRECTION):
            return None
        die = engine.roller.roll(DiceSpec(count=1, sides=4, modifier=0),
                                 actor_id=owner.entity_id, reason='REACTION_DIE')
        engine._record_roll(die)
        bonus = die.total if picks == ['add'] else -die.total
        engine._append_event('REACTION_RESOLVED', CORRECTION, actor_id=owner.entity_id,
            target_ids=(subject.entity_id,), payload={'checkpoint': 'D20_PENDING', 'roll': 'check', 'bonus': bonus})
        return {'bonus': bonus, 'source_id': CORRECTION, 'user_id': owner.entity_id}
    return None


@hook('choice_reactors')
def ink_choice_owners(engine):
    return tuple(owner.entity_id for owner in engine.state.actors.values()
                 if owned(engine, owner, 'guard') or owned(engine, owner, 'correction')) or None
