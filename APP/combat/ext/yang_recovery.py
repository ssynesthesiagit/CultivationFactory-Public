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


def _aim(ctx, marked, subject=None, *, target=None, new_only=False, single_subject=False):
    from .. import stealth, typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    from . import needle
    from .passive_rows import row_of

    bonus = 0
    for owner in ctx.engine.state.actors.values():
        row = row_of(ctx.engine, owner.entity_id, BLOCK, 'aim')
        if row is None or (new_only and not row.get('cw2r2')) or not owner.active or needle.incapacitated(owner):
            continue
        if owner.turn_flags.get(ROUND) == ctx.engine.state.round_number or not te.bears_mark(marked, owner.entity_id, 'Kindled Mark'):
            continue
        from ..target_knowledge import located
        perceives = located if row.get('cw2r2') else stealth.sees
        if owner is not marked and not perceives(ctx.engine, owner, marked):
            continue
        # One chosen recipient for an area save: the selection is resolution-local,
        # while actual mark spending and round limits are evented fight state.
        if subject is not None:
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
        owner.turn_flags[ROUND] = int(ctx.engine.state.round_number)
        inner = _inner(ctx, owner, marked, AIM, 'Complete Aim', row['numbers'])
        te.block_spend_mark(inner, {'mark': 'Kindled Mark', 'applies_to': 'target'})
        die = DiceSpec(count=1, sides=6 if int(row['numbers']['cl']) >= 11 else 4)
        roll = ctx.engine.roller.roll(die, actor_id=owner.entity_id, reason='COMPLETE_AIM:' + AIM)
        ctx.engine._record_roll(roll)
        ctx.engine._append_event('CHECK_ROLLED', AIM, actor_id=owner.entity_id, target_ids=(marked.entity_id,),
                                 payload={**roll.model_dump(mode='json'), 'purpose': 'Complete Aim bonus'})
        bonus += int(roll.total)
    return bonus or None


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
