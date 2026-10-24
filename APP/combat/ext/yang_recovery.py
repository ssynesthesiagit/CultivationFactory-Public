"""Recovery checkpoints shared by Yang's completing responses.

TEMP_HP_GRANTED with a real gain offers ``temp_hp_gained``; a positive gain in one of the three core CP pools offers
``cp_restored``. The existing ``healed`` checkpoint also covers regeneration that actually restores HP.
``recovery_bonus`` adds to Temporary HP when answering that grant, otherwise uses the ordinary healing block. This
keeps Complete Breath's PB + key bonus in the same kind of recovery as its trigger, rather than healing a temp-HP grant.
The transient event context is restored in finally; persistent state changes use ordinary engine events.

AUTO35 completes additional Yang rules through existing documented hooks:
``yang_completing`` passive rows own Complete Aim and Furnace Backlash. Aim uses
attack_bonus/save, asks the mark owner, and shares the printed round limit with
the other responses. A save chooses one recipient, not every area recipient.
Furnace Backlash uses mark_spent, quotes/pays 1 CP and applies only its failed-save
Reaction denial. It neither deals damage nor consumes a second mark.
``yang_kindled_pair`` chooses two distinct willing allies/self within 60 feet;
``yang_optional_self_mark`` runs only after Twofold Rising's successful hit.
Kindle the Wounded Breath's candidate_allowed hook refuses 0-HP targets; its
existing typed healing, CP payment and shared target_limits ledger own the rest.
``complete_aim_exception`` is shared with yang_sun_marks: Dawn's accepted response
uses Aim's normal implementation only after its qualifying hit/failed save.
No ownership row or no eligible owned mark means no changed state or RNG.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from . import kindled_responses as family

CP = {"resource:core.qi", "resource:core.stamina", "resource:core.resonance"}


@effect("recovery_bonus")
def bonus(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, block_healing

    event = getattr(ctx.engine, "_yang_recovery_event", None) or {}
    if event.get("kind") != "temp_hp_gained":
        block_healing(ctx, {**row, "type": "healing"})
        return
    amount = int(ctx.numbers.get("pb") or 0) + int(ctx.numbers.get("key_mod") or 0)
    for subject in _default_subject(ctx, row, harmful=False):
        if subject.entity_id == event.get("subject"):
            ctx.engine._grant_temp_hp(subject, max(0, subject.temporary_hp + amount), ctx.source, ctx.actor.entity_id)


@hook("event")
def recovery(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "TEMP_HP_GRANTED" and int(payload.get("after") or 0) > int(payload.get("before") or 0):
        kind = "temp_hp_gained"
        targets = kwargs.get("target_ids") or ()
    elif event_type == "RESOURCE_GAINED" and payload.get("resource_id") in CP and int(payload.get("gained") or 0) > 0:
        kind, targets = "cp_restored", [kwargs.get("actor_id")]
    else:
        return
    from .. import typed_reactions

    prior = getattr(engine, "_yang_recovery_event", None)
    try:
        for target_id in targets:
            subject = engine.state.actors.get(target_id)
            if subject is None or not subject.active:
                continue
            engine._yang_recovery_event = {"kind": kind, "subject": target_id}
            typed_reactions.on_creature_event(engine, subject, kind)
    finally:
        engine._yang_recovery_event = prior


# Round 2: extend the existing Yang checkpoint owner, rather than a second implementation.
AIM = 'TAL_YANG_KINDLED_RESPONSES#complete_aim'
FURNACE = 'TAL_YANG_FURNACE_BACKLASH'
WOUNDED = 'TAL_YANG_KINDLE_THE_WOUNDED_BREATH'
TWOFOLD = 'TAL_YANG_TWOFOLD_RISING'
ROUND = family.ROUND_KEY  # one shared once-per-round slot for the whole Kindled Responses family
BLOCK = 'yang_completing'


@hook('compile_block')
def completing_block(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': spec['kind'], 'numbers': dict(numbers), 'cw2r2': True}]


def _inner(ctx, owner, subject, source, name, numbers):
    from .states import context
    inner = context(ctx.engine, owner, source, [subject], numbers)
    inner.action = inner.action.model_copy(update={'source_definition_id': source, 'display_name': name})
    inner.intent = ctx.intent
    return inner


def _aim_save_targets(ctx):
    """Use the pending save's declared roster and its exclusion/size/immunity gates."""
    from .. import typed_executor as te
    from . import any_false

    effect = ctx.damage_cache.get('yang_pending_save')
    if effect is None:
        return []
    out = []
    for target in te.save_subjects(ctx, effect):
        if not target.active or (effect.get('skip_if_immune') and te.condition_immune(ctx.engine, target, effect['skip_if_immune'])):
            continue
        if any_false('save_gate', ctx, target):
            continue
        width = te.size_width(ctx, target, 'subject', effect)
        mine = te.size_width(ctx, ctx.actor, 'actor', effect)
        if effect.get('max_size_larger') is not None and width > mine + int(effect['max_size_larger']):
            continue
        if effect.get('max_size_cells') and width > int(effect['max_size_cells']):
            continue
        if effect.get('min_size_larger') is not None and width < mine + int(effect['min_size_larger']):
            continue
        out.append(target)
    return out


@hook('save_choice')
def aim_pending_save(ctx, subject, effect, options):
    from .passive_rows import row_of
    if any((row_of(ctx.engine, owner.entity_id, BLOCK, 'aim') or {}).get('cw2r2')
           for owner in ctx.engine.state.actors.values()):
        ctx.damage_cache['yang_pending_save'] = effect
    return None


def pay_complete_aim_slot(engine, owner, marked) -> None:
    """Pay the normal round slot only after Complete Aim is accepted.

    Dawn's first-occurrence response is dispatched separately after the hit/save
    and never calls this normal payment path.
    """
    owner.turn_flags[ROUND] = int(engine.state.round_number)


def complete_aim_exception(ctx, marked, target, owner, *, saving_throw=False):
    """Accepted Dawn response, shared with yang_sun_marks at a confirmed hit/failed save.

    Uses the same mark-spending, die and Noon path as ordinary Complete Aim,
    but the occurrence's exception pays instead of the owner's round slot.
    """
    return _aim(ctx, marked, subject=target if saving_throw else None,
                target=target, exception_owner=owner.entity_id)


def _aim(ctx, marked, subject=None, *, target=None, new_only=False, single_subject=False, exception_owner=None):
    from .. import stealth, typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    from . import needle
    from .passive_rows import row_of

    bonus = 0
    for owner in ctx.engine.state.actors.values():
        row = row_of(ctx.engine, owner.entity_id, BLOCK, 'aim')
        if row is None or (new_only and not row.get('cw2r2')) or not owner.active or needle.incapacitated(owner):
            continue
        if exception_owner is not None and owner.entity_id != exception_owner:
            continue
        if owner.turn_flags.get(ROUND) == ctx.engine.state.round_number and exception_owner is None:
            continue  # Dawn's exception is offered only at its confirmed hit/failed save.
        if not te.bears_mark(marked, owner.entity_id, 'Kindled Mark'):
            continue
        from ..target_knowledge import located
        perceives = located if row.get('cw2r2') else stealth.sees
        if owner is not marked and not perceives(ctx.engine, owner, marked):
            continue
        # One chosen recipient for an area save: the selection is resolution-local,
        # while actual mark spending and round limits are evented fight state.
        if exception_owner is not None:
            pass  # The bearer already selected Complete Aim at the qualifying occurrence.
        elif subject is not None:
            cache = ctx.damage_cache.setdefault('yang_aim_targets', {})
            if owner.entity_id not in cache:
                # A native save has no typed roster to read: the rolling creature is itself
                # the one target the printed "choose one target" clause resolves to.
                targets = [subject] if single_subject else (
                    _aim_save_targets(ctx) if row.get('cw2r2') else [a for a in ctx.targets if a.active])
                if not targets:
                    continue
                cache[owner.entity_id] = needle.ask(
                    ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'yang_aim_save', marked.entity_id), owner,
                    'choice:needle.yang_aim_save', [a.entity_id for a in targets],
                    labels={a.entity_id: f'Reduce {a.display_name}\'s saving throw by 1d{6 if row["numbers"]["cl"] >= 11 else 4}' for a in targets},
                    allow_decline=True, target_id=marked.entity_id, name='Complete Aim', feature_id=AIM,
                    prompt=f'Complete Aim: {marked.display_name} uses {ctx.action.display_name}. Spend its Kindled Mark to reduce one target\'s saving throw? No action or CP cost.')
            if subject.entity_id not in cache[owner.entity_id]:
                continue
        else:
            # Saves are separate decisions and must never erase their parent attack's answer.
            family.forget(ctx.engine, owner)
            die_sides = 6 if int(row['numbers']['cl']) >= 11 else 4
            # One Kindled Mark buys exactly one Kindled Response. Complete Force -- and anything
            # else this same attack still arms -- answers after the roll, so the earlier checkpoint
            # must not silently take the mark. kindled_responses builds the one menu that offers Aim
            # alongside those armed rivals and resolves the choice for the whole family, for the
            # creature actually attacking and the creature actually attacked; with no rival armed it
            # is the ordinary "use Aim / decline" question. The answer, decline included, is carried
            # to the later checkpoints of this same attack so no other member spends the mark after
            # the player said no.
            from .trigger_occurrence import current_strike
            strike = current_strike(ctx.engine)
            aimed_at = target if target is not None else (strike['target'] if strike else ctx.target)
            choice = family.choose(ctx.engine, ctx.intent, owner, marked, ctx.action.display_name,
                                   mine=('use', f'Complete Aim: adds 1d{die_sides} to {marked.display_name}\'s '
                                                 f'attack roll ({family.mark_cost("nothing else")}; no Action and no CP cost)'),
                                   choice_id='choice:needle.yang_aim_attack',
                                   checkpoint=needle.checkpoint_id(ctx.engine, 'yang_aim_attack', marked.entity_id),
                                   feature_id=AIM, name='Complete Aim',
                                   subjects=[aimed_at] if aimed_at is not None else None)
            if choice != 'use':
                continue
        from .yang_sun_marks import roll_response_die
        if exception_owner is None:
            pay_complete_aim_slot(ctx.engine, owner, marked)
        inner = _inner(ctx, owner, marked, AIM, 'Complete Aim', row['numbers'])
        te.block_spend_mark(inner, {'mark': 'Kindled Mark', 'applies_to': 'target'})
        die = DiceSpec(count=1, sides=6 if int(row['numbers']['cl']) >= 11 else 4)
        roll = roll_response_die(ctx.engine, owner, die, 'COMPLETE_AIM:' + AIM)
        ctx.engine._record_roll(roll)
        ctx.engine._append_event('CHECK_ROLLED', AIM, actor_id=owner.entity_id, target_ids=(marked.entity_id,),
                                 payload={**roll.model_dump(mode='json'), 'purpose': 'Complete Aim bonus'})
        bonus += int(roll.total)
        remember_sunlit(ctx, owner, marked, subject, target)
    return bonus or None


SUNLIT = 'TAL_YANG_SUNLIT_OPENING'
SUNLIT_CONDITION = 'condition:typed.sunlit_opening'


@hook('compile_passives')
def sunlit_ownership(passives, info):
    """Fresh compiled ownership only; old saved catalogs gain no new behavior."""
    if SUNLIT not in info.get('owned_ids', []):
        return passives
    return [*passives, {'block': BLOCK, 'kind': 'sunlit', 'feature_id': SUNLIT,
                       'numbers': dict(info['numbers'])}]


def sunlit_resolution(engine):
    """Resolution-local Aim receipts and settled save outcomes, never persisted."""
    from .trigger_occurrence import resolution
    key = resolution(engine)
    records = getattr(engine, '_yang_sunlit', None)
    if records is None or records['resolution'] != key:
        records = {'resolution': key, 'pending': [], 'failures': {}}
        engine._yang_sunlit = records
    return records


def remember_sunlit(ctx, owner, marked, subject, target):
    from .passive_rows import row_of
    from .trigger_occurrence import current_strike
    if row_of(ctx.engine, owner.entity_id, BLOCK, 'sunlit') is None:
        return
    strike = current_strike(ctx.engine)
    actual = target or (strike['target'] if strike else ctx.target)
    affected = []
    if subject is not None:
        affected = [a.entity_id for a in _aim_save_targets(ctx)] if ctx.targets else [subject.entity_id]
        # Native area actions declare their roster on the accepted intent. A
        # zone/other off-turn source instead saves only its present recipient;
        # never borrow the unrelated mover's or attacker's declared targets.
        if ctx.action.resolution_kind != 'TYPED' and ctx.intent is not None and ctx.intent.actor_id == marked.entity_id:
            affected = list(ctx.intent.target_ids) or affected
    sunlit_resolution(ctx.engine)['pending'].append({
        'owner': owner.entity_id, 'marked': marked.entity_id,
        'source': ctx.action.source_definition_id, 'kind': 'save' if subject else 'attack',
        'target': actual.entity_id if actual is not None else '',
        'trigger': ctx.action.display_name,
        'affected': affected,
    })


def offer_sunlit(engine, receipt, affected, intent):
    """The owner chooses an ally and one affected target after the settled result."""
    from . import needle
    from .effect_durations import token
    from .passive_rows import row_of
    from ..target_knowledge import located
    owner = engine.state.actors.get(receipt['owner'])
    marked = engine.state.actors.get(receipt['marked'])
    if owner is None or marked is None or not owner.active or needle.incapacitated(owner):
        return
    if row_of(engine, owner.entity_id, BLOCK, 'sunlit') is None:
        return
    allies = sorted((a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id
                     and engine._distance_actor_to_actor(marked, a) <= 30
                     and (needle.answerable(engine, owner) or a is owner or located(engine, owner, a))),
                    key=lambda a: a.entity_id)
    targets = [engine.state.actors[t] for t in sorted(set(affected))
               if t in engine.state.actors and engine.state.actors[t].active
               and (needle.answerable(engine, owner) or t == owner.entity_id
                    or located(engine, owner, engine.state.actors[t]))]
    if not allies or not targets:
        return
    options = {f'{a.entity_id}|{t.entity_id}': (a, t) for a in allies for t in targets}
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'sunlit_opening',
                       receipt['owner'] + ':' + receipt['marked'] + ':' + receipt['source']), owner,
                       'choice:needle.sunlit_opening', list(options), allow_decline=True,
                       labels={k: f'{a.display_name}: Advantage on its next attack against {t.display_name} '
                               'before your next turn; no extra cost' for k, (a, t) in options.items()},
                       name='Sunlit Opening', feature_id=SUNLIT, target_id=marked.entity_id,
                       prompt=f'Sunlit Opening: Complete Aim helped {marked.display_name}\'s {receipt["trigger"]}. '
                              'Choose an ally within 30 feet of it and an affected target. The ally gains Advantage '
                              'on its next attack against that target before your next turn. No extra action or resource cost.')
    if not picked:
        return
    ally, target = options[picked[0]]
    expiry = token('start', owner.entity_id, owner.turns_started + 1)
    # The native convenience method attributes modifiers to the current actor.
    # This off-turn grant belongs to the Yang owner, so record it explicitly.
    from ..gate2_runtime_models import ModifierInstance
    mid = f'modifier:{SUNLIT}:{ally.entity_id}:{engine.state.event_sequence + 1}'
    ally.modifiers[mid] = ModifierInstance(modifier_id=mid, source_definition_id=SUNLIT,
        source_actor_id=owner.entity_id, target_id=ally.entity_id, target_field='attack_mode_vs',
        operation='SET', value=f'ADVANTAGE:{target.entity_id}', applies_to='NEXT_ATTACK', expires_on=expiry)
    engine._append_event('MODIFIER_APPLIED', SUNLIT, actor_id=owner.entity_id, target_ids=(ally.entity_id,),
        payload={'modifier_id': mid, 'target_field': 'attack_mode_vs', 'operation': 'SET',
                 'value': f'ADVANTAGE:{target.entity_id}', 'expires_on': expiry})
    engine._apply_condition(ally, SUNLIT_CONDITION + '.' + mid, SUNLIT, owner.entity_id,
                            expires_on=expiry, data={'modifier_id': mid, 'target': target.entity_id,
                            'label': f'Sunlit Opening: next attack against {target.display_name} has Advantage'})


@hook('attack_completed')
def sunlit_hit(engine, notice, intent):
    from .trigger_occurrence import resolution
    records = getattr(engine, '_yang_sunlit', None)
    if records is None or records['resolution'] != resolution(engine):
        return
    for receipt in list(records['pending']):
        if (receipt['kind'] == 'attack' and receipt['marked'] == notice.attacker_id
                and receipt['source'] == notice.source_id):
            records['pending'].remove(receipt)
            if notice.hit:
                offer_sunlit(engine, receipt, [notice.target_id], intent)


def sunlit_save_outcome(engine, caster, source, subject, failed, intent):
    from .passive_rows import row_of
    from .trigger_occurrence import resolution
    from ..typed_executor import bears_mark
    current = getattr(engine, '_yang_sunlit', None)
    pending = (current['pending'] if current and current['resolution'] == resolution(engine) else [])
    marked = engine.state.actors.get(caster)
    if not any(r['kind'] == 'save' and (r['marked'], r['source']) == (caster, source) for r in pending):
        if marked is None or not any(row_of(engine, owner.entity_id, BLOCK, 'sunlit') is not None
                                     and bears_mark(marked, owner.entity_id, 'Kindled Mark')
                                     for owner in engine.state.actors.values()):
            return
    records = sunlit_resolution(engine)
    key = (caster, source)
    failures = records['failures'].setdefault(key, [])
    if failed and subject not in failures:
        failures.append(subject)
    for receipt in list(records['pending']):
        if receipt['kind'] == 'save' and (receipt['marked'], receipt['source']) == key and failures:
            records['pending'].remove(receipt)
            offer_sunlit(engine, receipt, receipt['affected'] or failures, intent)


@hook('save_final')
def sunlit_typed_save(ctx, subject, ability, named, failed):
    sunlit_save_outcome(ctx.engine, ctx.actor.entity_id, ctx.action.source_definition_id,
                        subject.entity_id, failed, ctx.intent)


@hook('event', nested=True)
def sunlit_native_and_consumption(engine, event_type, kwargs):
    if event_type == 'INTENT_ACCEPTED':
        # A prompted transaction can retry with the same id after rollback.
        # Its earlier transient outcomes must not leak into that traversal.
        if hasattr(engine, '_yang_sunlit'):
            delattr(engine, '_yang_sunlit')
    elif event_type == 'SAVE_ROLLED':
        frame = engine.d20_context() or {}
        action = engine.action_catalog.get(frame.get('source_id'))
        if action is not None and action.resolution_kind != 'TYPED' and frame.get('source_actor_id'):
            sunlit_save_outcome(engine, frame['source_actor_id'], action.source_definition_id,
                                kwargs.get('actor_id'), not (kwargs.get('payload') or {}).get('success'),
                                getattr(engine, '_active_intent', None))
    elif event_type == 'ATTACK_ROLLED':
        actor = engine.state.actors.get(kwargs.get('actor_id'))
        if actor is None:
            return
        targets = kwargs.get('target_ids') or ()
        for condition in list(actor.conditions.values()):
            if not condition.condition_id.startswith(SUNLIT_CONDITION + '.') or condition.data.get('target') not in targets:
                continue
            mid = condition.data['modifier_id']
            if actor.modifiers.pop(mid, None) is not None:
                engine._append_event('MODIFIER_REMOVED', SUNLIT, actor_id=actor.entity_id,
                                     target_ids=(actor.entity_id,), payload={'modifier_id': mid, 'reason': 'CONSUMED'})
            engine._remove_condition(actor, condition.condition_id, SUNLIT)


@hook('attack_bonus')
def complete_aim_attack(ctx, actor):
    return _aim(ctx, actor)


@hook('save')
def complete_aim_save(ctx, subject, ability, named):
    amount = _aim(ctx, ctx.actor, subject)
    return {'bonus': -amount} if amount else None


@hook('d20_bonus')
def complete_aim_native_attack(engine, roll, intent):
    """The shared native d20 checkpoint also reaches legacy attack and save catalogs.

    Typed techniques are left to the typed ``save``/``attack_bonus`` hooks so one save is
    never improved twice.
    """
    if intent is None:
        return None
    context = engine.d20_context(roll) or {}
    kind = context.get('kind')
    if kind not in ('attack', 'save'):
        return None
    action = engine.action_catalog.get(context.get('source_id'))
    if action is None or action.resolution_kind == 'TYPED':
        return None
    if kind == 'save':
        # "the marked subject ... forces one or more creatures to make a saving throw": the marked
        # creature is the one forcing the save, and the roller is the chosen target. The forcing
        # creature comes from the d20 frame's own ``source_actor_id`` -- published by
        # gate2_engine._roll_save -- and never from ``intent.actor_id``: a save can be forced while
        # somebody else is acting (a marked creature walking through someone else's Blackwater
        # saves against the zone's owner), and the current intent is that other creature.
        # With no forcing creature in the frame this trigger is simply not eligible; returning
        # inert is right, because treating the roller as the caster would let a marked creature
        # lower its own saving throw.
        caster = engine.state.actors.get(context.get('source_actor_id') or '')
        roller = engine.state.actors.get(roll.actor_id)
        if caster is None or roller is None or caster is roller:
            return None
        from ..typed_executor import Context
        ctx = Context(engine, caster, action, intent, {}, [], None, {})
        amount = _aim(ctx, caster, roller, new_only=True, single_subject=True)
        return {'source_id': AIM, 'bonus': -amount} if amount else None
    marked = engine.state.actors.get(roll.actor_id)
    if marked is None:
        return None
    from ..typed_executor import Context
    ctx = Context(engine, marked, action, intent, {}, [], None, {})
    amount = _aim(ctx, marked, new_only=True, target=engine.state.actors.get(context.get('target_id') or ''))
    return {'source_id': AIM, 'bonus': amount} if amount else None


@hook('mark_spent')
def furnace_backlash(ctx, name, subject):
    if name.strip().lower() != 'overkindled mark' or not ctx.source.endswith('#overheat_force'):
        return
    from .passive_rows import row_of
    row = row_of(ctx.engine, ctx.actor.entity_id, BLOCK, 'furnace')
    if row is None:
        return
    from .cp_pools import of
    from .choice_costs import payable
    from . import needle, run
    payment = payable(ctx.actor, of(ctx.actor, at_least=1) or '', 1)
    if payment is None or any(r is False for r in run('cost_available', ctx.engine, ctx.actor, payment.pool, 1, {})):
        return
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'furnace_backlash', subject.entity_id), ctx.actor,
                        'choice:needle.furnace_backlash', ['use'], allow_decline=True, target_id=subject.entity_id,
                        labels={'use': f'{subject.display_name} makes a Constitution save; failure prevents Reactions until its next turn ({payment.quote()})'},
                        payment=payment, name='Furnace Backlash', feature_id=FURNACE,
                        prompt=f'Furnace Backlash: Overheat Force spent your mark on {subject.display_name}. Pay {payment.quote()} for a Constitution save against losing Reactions?')
    if not picked:
        return
    payment.pay(ctx.engine, ctx.actor, FURNACE)
    from .. import typed_executor as te
    inner = _inner(ctx, ctx.actor, subject, FURNACE, 'Furnace Backlash', row['numbers'])
    # Compile_block does not receive DC; seal it from this owner's real catalog.
    inner.typed['numbers']['save_dc'] = needle.numbers_of(ctx.engine, ctx.actor).get('save_dc', 10)
    te.run_effects(inner, [{'type': 'save', 'ability': 'con', 'dc': 'technique_save_dc',
                          'on_fail': [{'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
                          'on_success': []}])


@hook('candidate_allowed')
def wounded_breath_living_target(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    source = typed.get('source')
    if source == WOUNDED and typed.get('auto35_wounded'):
        return all(engine.state.actors[t].current_hp >= 1 for t in candidate.target_ids)
    if any(e.get('type') == 'yang_kindled_pair' for e in typed.get('effects') or []):
        return len(_pair_targets(engine, actor)) >= 2
    return None


@hook('compile_action')
def wounded_breath_any_creature(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != WOUNDED:
        return None
    return action.model_copy(update={'target_kind': 'ANY_CREATURE',
                                     'parameters': {**action.parameters, 'typed': {**typed, 'auto35_wounded': True}}})


def _pair_targets(engine, actor):
    from .. import stealth
    return sorted((a for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id
                   and engine._distance_actor_to_actor(actor, a) <= 60
                   and (a is actor or stealth.sees(engine, actor, a))), key=lambda a: a.entity_id)


@effect('yang_kindled_pair')
def kindled_pair(ctx, row):
    from .. import typed_executor as te
    from . import needle
    from dataclasses import replace
    eligible = _pair_targets(ctx.engine, ctx.actor)
    if len(eligible) < 2:
        return
    # The printed "2 CP" is the price of the Twofold Rising action itself, and that action has
    # already paid it (combat/gate2_engine.py's action payment, before these effects run). This
    # effect only places marks, so it charges nothing more: the quote is the action's own price in
    # the sheet's shared cost wording, and asking with a second Payment on top of it would tell the
    # player to pay 2 CP to answer a choice that costs nothing.
    price = needle.riding_cost(ctx.engine, ctx.actor)
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'twofold_kindled', ctx.actor.entity_id), ctx.actor,
                        'choice:needle.twofold_kindled', [a.entity_id for a in eligible], minimum=2, maximum=2,
                        labels={a.entity_id: f'Give {a.display_name} a Kindled Mark until the end of your next turn' for a in eligible},
                        preferred=[a.entity_id for a in eligible[:2]], name='Twofold Rising', feature_id=TWOFOLD,
                        prompt=('Twofold Rising (Bonus Action): choose two different willing creatures within 60 feet. '
                                'Each gains a Kindled Mark until the end of your next turn. A Kindled Mark lets that '
                                'creature\'s owner spend it on one Kindled Response -- extra damage, a better attack roll, '
                                'a reduced saving throw, or better healing. Choosing costs nothing more'
                                + (f'; Twofold Rising itself costs {price}' if price else '') + '.'))
    for aid in picked:
        target = ctx.engine.state.actors[aid]
        te.block_mark(replace(ctx, targets=[target], target=target), {'mark': 'Kindled Mark', 'applies_to': 'target', 'duration': {'kind': 'until_end_of_your_next_turn'}})


@effect('yang_optional_self_mark')
def optional_self_mark(ctx, row):
    from . import needle
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'twofold_self', ctx.actor.entity_id), ctx.actor,
                        'choice:needle.twofold_self', ['use'], allow_decline=True, name='Twofold Rising', feature_id=TWOFOLD,
                        labels={'use': 'Also give yourself a Kindled Mark until the end of your next turn (no extra cost)'},
                        prompt=('Twofold Rising hit and gave the target an Overkindled Mark. Also give yourself a '
                                'Kindled Mark until the end of your next turn? A Kindled Mark lets you spend it on one '
                                'Kindled Response -- extra damage, a better attack roll, a reduced saving throw, or '
                                'better healing. This costs nothing more.'))
    if picked:
        from ..typed_executor import block_mark
        block_mark(ctx, {'mark': 'Kindled Mark', 'applies_to': 'self', 'duration': {'kind': 'until_end_of_your_next_turn'}})


# Second pass: follow-ups attach to the actual spent response, never another mark.
TRAIL = 'TAL_YANG_OVERBRIGHT_TRAIL'
WARMTH = 'TAL_YANG_SEAL_BREAKING_WARMTH'
THREAD = 'TAL_YANG_APPLYING_A_RISING_MARK#rising_thread'
TRAIL_CONDITION = 'condition:typed.yang_overbright_trail'
STEP = 'TAL_YANG_KINDLED_RESPONSES#complete_step'
SURPLUS = 'TAL_YANG_SURPLUS_STEP'
STEP_CONDITION = 'condition:typed.yang_complete_step'
SURPLUS_CONDITION = 'condition:typed.yang_surplus_step'
FOLLOWUPS = {TRAIL: 'trail', WARMTH: 'warmth', STEP: 'step', SURPLUS: 'surplus'}


@hook('compile_passives')
def followup_ownership(passives, info):
    return [*passives, *[{'block': BLOCK, 'kind': kind, 'feature_id': source,
                         'numbers': dict(info['numbers'])}
                        for source, kind in FOLLOWUPS.items() if source in info.get('owned_ids', [])]]


@hook('mark_spent')
def overbright_trail(ctx, name, subject):
    from .passive_rows import row_of
    from .effect_durations import token
    if (name.lower() != 'overkindled mark'
            or ctx.source not in ('TAL_YANG_OVERKINDLED_RESPONSES#overexpose',
                                  'TAL_YANG_OVERKINDLED_RESPONSES#overcommit_step')
            or row_of(ctx.engine, ctx.actor.entity_id, BLOCK, 'trail') is None):
        return
    from .condition_ownership import refresh_owned
    refresh_owned(ctx.engine, subject, TRAIL_CONDITION, ctx.actor.entity_id, TRAIL)
    ctx.engine._apply_condition(subject, TRAIL_CONDITION, TRAIL, ctx.actor.entity_id,
        expires_on=token('start', ctx.actor.entity_id, ctx.actor.turns_started + 1),
        data={'label': f'Overbright Trail: nonmagical concealment cannot hide this creature from '
                       f'{ctx.actor.display_name} within 60 feet; solid barriers still block sight'})


@hook('obscurement_ignored')
def trail_sight(engine, zone, viewer, seen):
    from .darkness_scope import scope
    if (scope(engine, zone) != 'ordinary'
            or engine._distance_actor_to_actor(viewer, seen) > 60):
        return None
    return True if any(c.condition_id == TRAIL_CONDITION and c.source_actor_id == viewer.entity_id
                       for c in seen.conditions.values()) else None


def warmth_conditions(engine, owner, subject):
    """Only represented ordinary save-imposed suppression; unknown provenance stays unaltered."""
    from .repeat_saves import save_of
    from .passive_rows import known_level
    from .source_eligibility import catalog_action, ordinary_source, printed_power, protected_power
    from ..typed_executor import condition_rules
    own_level = known_level(engine, owner)
    out = []
    for iid, condition in subject.conditions.items():
        if save_of(condition) is None:
            continue
        source = catalog_action(engine, condition.source_definition_id)
        typed = (source.parameters or {}).get('typed') or {} if source else {}
        origin = engine.state.actors.get(condition.source_actor_id)
        level = known_level(engine, origin) if origin else None
        if own_level is None or level is None or level > own_level or not ordinary_source(source):
            continue
        # Warmth has narrower exclusions than Unweave: every Formation,
        # Curse and narrative seal is protected, not only formation projects.
        power = printed_power(source)
        if power is None or protected_power(*power, extra_categories=("curse", "formation", "narrative seal")):
            continue
        # Excluded sources require an explicit ruling, even if they used an ordinary save.
        source_name = str(typed.get('source') or condition.source_definition_id).lower()
        if (any(word in source_name for word in ('curse', 'formation', 'artifact', 'inheritance', 'narrative_seal'))
                or str(typed.get('tier') or typed.get('rarity') or '').lower() in ('secret', 'legendary', 'artifact')
                or any((condition.data or {}).get(k) for k in ('secret', 'artifact', 'curse', 'superior'))):
            continue
        names = {'restrained', 'paralyzed', 'stunned'}
        qualifies = condition.condition_id.rsplit('.', 1)[-1] in names
        # Some save-imposed slows are stored as a flat delta rather than a
        # named condition or a rule multiplier (for example, a leg wound).
        qualifies = qualifies or int((condition.data or {}).get('speed_delta') or 0) < 0
        # Read only this condition's rule, not another suppression on the bearer.
        single = subject.model_copy(update={'conditions': {iid: condition}})
        qualifies = qualifies or any(r.get('speed_zero') or r.get('no_reactions') or r.get('cant_move')
                                     or r.get('speed_multiplier', 1) < 1 for r in condition_rules(single))
        if qualifies:
            out.append((iid, condition))
    return sorted(out, key=lambda pair: (int(save_of(pair[1])['dc']), pair[0]))


@hook('mark_spent')
def seal_breaking_warmth(ctx, name, subject):
    if name.lower() != 'kindled mark' or ctx.source not in (
            'TAL_YANG_KINDLED_RESPONSES#complete_resolve', 'TAL_YANG_KINDLED_RESPONSES#complete_step'):
        return
    from .passive_rows import row_of
    row = row_of(ctx.engine, ctx.actor.entity_id, BLOCK, 'warmth')
    if row is None:
        return
    eligible = warmth_conditions(ctx.engine, ctx.actor, subject)
    from .cp_pools import of
    from .choice_costs import payable
    from . import needle, run
    trigger = 'Complete Resolve' if ctx.source.endswith('#complete_resolve') else 'Complete Step'
    payment = payable(ctx.actor, of(ctx.actor, at_least=2) or '', 2)
    if not eligible or payment is None or any(r is False for r in
            run('cost_available', ctx.engine, ctx.actor, payment.pool, 2, {})):
        return
    offer = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'seal_warmth', subject.entity_id),
        ctx.actor, 'choice:needle.seal_warmth', ['use'], allow_decline=True,
        labels={'use': f'After {trigger}, pay {payment.quote()}: {subject.display_name} may repeat one suppression save'},
        payment=payment, name='Seal-Breaking Warmth', feature_id=WARMTH, target_id=subject.entity_id,
        prompt=f'After {trigger}, Seal-Breaking Warmth: pay {payment.quote()} to let {subject.display_name} immediately '
               'repeat one saving throw against an ordinary movement or action restriction. '
               'Success ends that effect; failure grants your Proficiency Bonus plus Key Ability modifier in Temporary HP.')
    if not offer:
        return
    # The mark owner pays; the marked creature chooses whether and what to repeat.
    picks = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'seal_warmth_repeat', subject.entity_id),
        subject, 'choice:needle.seal_warmth_repeat', [iid for iid, c in eligible], allow_decline=True,
        labels={iid: 'Repeat the save against ' + c.condition_id.rsplit('.', 1)[-1].replace('_', ' ').title()
                for iid, c in eligible}, name='Seal-Breaking Warmth', feature_id=WARMTH,
        target_id=subject.entity_id,
        prompt=f'After {trigger}, Seal-Breaking Warmth: {ctx.actor.display_name} offers {subject.display_name} a repeat saving throw. '
               'Choose one effect to try to end, or decline. No Reaction or resource cost for you.')
    payment.pay(ctx.engine, ctx.actor, WARMTH)
    if not picks:
        return
    iid, condition = next(pair for pair in eligible if pair[0] == picks[0])
    from .repeat_saves import save_of
    from .condition_ownership import remove_instance
    save = save_of(condition)
    roll = ctx.engine._roll_save(subject, str(save['ability']).upper(), int(save['dc']), WARMTH,
        roll_context={'source_actor_id': condition.source_actor_id,
                      'named': [condition.condition_id.rsplit('.', 1)[-1]]})
    if roll is None:
        return
    if roll.total >= int(save['dc']):
        remove_instance(ctx.engine, subject, iid, WARMTH)
    else:
        ctx.engine._grant_temp_hp(subject, max(0, int(row['numbers'].get('pb') or 0)
            + int(row['numbers'].get('key_mod') or 0)), WARMTH, ctx.actor.entity_id)


@hook('attack_damage_type_choice')
def rising_thread_type(ctx, attack, target, kinds, attack_index):
    if ctx.typed.get('source') not in (THREAD, TWOFOLD) or not ctx.typed.get('yang_thread_choice'):
        return None
    from . import needle
    # A default must not inspect the target's undisclosed resistance/immunity.
    # Players choose explicitly; automation uses the first printed option.
    preferred = kinds[0]
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'rising_thread_type',
                       target.entity_id, str(attack_index)), ctx.actor,
        'choice:needle.rising_thread_type', list(kinds), allow_decline=False, preferred=[preferred],
        labels={kind: kind.title() + ' damage' for kind in kinds}, name='Rising Thread', feature_id=THREAD,
        target_id=target.entity_id, prompt=f'Rising Thread: choose Fire, Radiant, or Force damage for '
        f'your attack against {target.display_name}. Choose before the attack roll; the mark is applied only on a hit.')
    return picked[0] if picked else None


@hook('compile_action')
def thread_choice_opt_in(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') not in (THREAD, TWOFOLD):
        return None
    return action.model_copy(update={'parameters': {**action.parameters,
                                                   'typed': {**typed, 'yang_thread_choice': True}}})


@hook('movement_begin')
def complete_step(engine, subject, candidate, intent, granted_ft):
    """The accepted willing route begins; off-turn and forced paths cannot use this response."""
    if engine.state.current_actor_id != subject.entity_id or engine._effective_speed(subject) <= 0:
        return
    from .passive_rows import row_of
    from . import needle
    from .. import flight, posture
    from ..target_knowledge import located
    from ..typed_executor import bears_mark, block_spend_mark
    from .effect_durations import token
    from .states import context
    for owner in engine.state.actors.values():
        row = row_of(engine, owner.entity_id, BLOCK, 'step')
        if (row is None or not owner.active or needle.incapacitated(owner) or family.used_round(engine, owner)
                or not bears_mark(subject, owner.entity_id, 'Kindled Mark')
                or subject is not owner and not located(engine, owner, subject)):
            continue
        boost = 20 if row['numbers']['cl'] >= 11 else 10
        options = ['walk']
        if flight.profile(engine, subject).speed_ft > 0:
            options.append('fly')
        if posture.standing_cost(engine, subject, cost=0) is not None:
            options.append('stand')
        picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'complete_step', subject.entity_id),
            owner, 'choice:needle.complete_step', options, allow_decline=True,
            labels={'walk': f'Increase Walking Speed by {boost} feet until this turn ends',
                    'fly': f'Increase Fly Speed by {boost} feet until this turn ends',
                    'stand': 'Stand from Prone without spending movement'},
            name='Complete Step', feature_id=STEP, target_id=subject.entity_id,
            prompt=f'Complete Step: {subject.display_name} begins moving. Spend its Kindled Mark to '
                   f'increase one Speed by {boost} feet until this turn ends, or let it stand from Prone '
                   'without spending movement. No Action, Reaction or CP cost; shares your once-per-round response. '
                   'Complete Step increases to the same Speed do not add together.')
        if not picked:
            continue
        family.reserve_round(engine, owner)
        inner = context(engine, owner, STEP, [subject], row['numbers'])
        inner.action = inner.action.model_copy(update={'source_definition_id': STEP, 'display_name': 'Complete Step'})
        inner.intent = intent
        block_spend_mark(inner, {'mark': 'Kindled Mark', 'applies_to': 'target'})
        expiry = token('end', subject.entity_id, subject.turns_started)
        chosen = picked[0]
        if chosen == 'stand':
            posture.stand_up(engine, subject, source_id=STEP, cost=0)
        else:
            # Multiple mark owners can answer the same start of movement;
            # the same named response does not add its bonus to itself.
            key = 'fly_speed_bonus_ft' if chosen == 'fly' else 'speed_delta'
            existing = [c for c in subject.conditions.values()
                        if c.condition_id == STEP_CONDITION and key in c.data]
            previous = max((int(c.data[key]) for c in existing), default=0)
            increase = max(0, boost - previous)
            if increase:
                from .condition_ownership import remove_instance
                for held in existing:
                    remove_instance(engine, subject, held.instance_id, STEP)
                data = {key: boost, 'label': f'Complete Step: +{boost} feet to '
                        + ('Fly Speed' if chosen == 'fly' else 'Walking Speed')}
                if chosen == 'walk':
                    # Preserve the shared walking/flying allowance basis.
                    # Credit only the improvement over an earlier Step.
                    extra = increase * (1 + flight.dash_count(subject))
                    subject.movement_remaining_ft += extra
                    subject.turn_flags['movement_allowance_adjustment_ft'] = int(
                        subject.turn_flags.get('movement_allowance_adjustment_ft', 0)) + extra
                engine._apply_condition(subject, STEP_CONDITION, STEP, owner.entity_id,
                                        expires_on=expiry, data=data)
        needle.say(engine, STEP, owner, f'Complete Step helps {subject.display_name}: {chosen}.', (subject.entity_id,))


@hook('mark_spent')
def surplus_step(ctx, name, subject):
    from .passive_rows import row_of
    if (name.lower() != 'kindled mark' or ctx.source != STEP
            or row_of(ctx.engine, ctx.actor.entity_id, BLOCK, 'surplus') is None):
        return
    from .effect_durations import token
    from .condition_ownership import refresh_owned
    refresh_owned(ctx.engine, subject, SURPLUS_CONDITION, ctx.actor.entity_id, SURPLUS)
    ctx.engine._apply_condition(subject, SURPLUS_CONDITION, SURPLUS, ctx.actor.entity_id,
        expires_on=token('end', subject.entity_id, subject.turns_started),
        data={'rule': {'ignore_difficult': True}, 'pb': int(ctx.numbers.get('pb') or 0),
              'rewarded': False, 'label': 'Surplus Step: ignore nonmagical Difficult Terrain this turn; '
                                        'moving 20 feet grants the Yang owner’s Proficiency Bonus in Temporary HP'})


@hook('after_move')
def surplus_recovery(engine, subject, moved_ft):
    if engine.state.current_actor_id != subject.entity_id:
        return
    grants = [c for c in subject.conditions.values() if c.condition_id == SURPLUS_CONDITION
              and not (c.data or {}).get('rewarded')]
    if not grants:
        return
    # Count actual willing path segments in this turn, including movement before
    # the response was chosen. Terrain payment, forced movement and teleportation
    # are different quantities and never inflate these twenty feet.
    distance = 0
    for event in reversed(engine.events):
        if event.actor_id != subject.entity_id:
            continue
        if event.event_type == 'TURN_STARTED':
            break
        if event.event_type != 'MOVEMENT_COMMITTED' or event.payload.get('forced') or event.payload.get('teleport'):
            continue
        distance += max(0, len(event.payload.get('path') or []) - 1) * engine.grid.square_size_ft
    if distance < 20:
        return
    from .condition_ownership import remove_instance
    for condition in grants:
        data = {**condition.data, 'rewarded': True}
        remove_instance(engine, subject, condition.instance_id, SURPLUS)
        engine._apply_condition(subject, SURPLUS_CONDITION, SURPLUS, condition.source_actor_id,
                                expires_on=condition.expires_on, data=data)
        engine._grant_temp_hp(subject, int(data['pb']), SURPLUS, condition.source_actor_id)
