"""Dream-Mirror Soul Anchor foundation conversions (lane A2R01).

Mirror Trace conversions and their riders: Reflection Cut (a paid hit
and failed-save rider that adds PB Psychic or Force damage),
True-Name Witness (a paid rider that adds PB to a check or save
roll), their Perfected riders (Dream-Reflection Counter's penalty
and Truth Behind the Mask's second PB and symbolic truth), the
Mirror Trace fade clock, and the Perfected Dream-Mirror Domain
emanation. Every handler returns early unless the acting character
owns its row, so characters without the foundation are untouched.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..typed_executor import clock_expiry, run_effects
from . import effect, hook
from .choice_costs import Payment
from .choice_prompt import action_context
from .foundation_combat import hostile
from .needle import (CHOICE, ask, checkpoint_id, numbers_of, timed_condition)

P = 'condition:typed.dream_mirror_'
TRACE = 'resource:foundation.mirror_trace'
GENERATE_MIRROR_TRACE = 'foundation.dream_mirror_soul_anchor_v0_2B.generate_mirror_trace'
FALSE_IMAGE_GUARD = 'foundation.dream_mirror_soul_anchor_v0_2B.false_image_guard'
REFLECTION_CUT = 'foundation.dream_mirror_soul_anchor_v0_2B.reflection_cut'
DREAM_REFLECTION_COUNTER = 'foundation.dream_mirror_soul_anchor_v0_2B.dream_reflection_counter'
TRUE_NAME_WITNESS = 'foundation.dream_mirror_soul_anchor_v0_2B.true_name_witness'
TRUTH_BEHIND_THE_MASK = 'foundation.dream_mirror_soul_anchor_v0_2B.truth_behind_the_mask'
DREAM_MIRROR_DOMAIN = 'foundation.dream_mirror_soul_anchor_v0_2B.dream_mirror_domain'
DOMAIN_CONDITION = P + 'domain'
COUNTER_CONDITION = P + 'reflection_counter'
DOMAIN_RANGE_FT = 30

# Truth Behind the Mask's families: illusion, dream, disguise, memory,
# charm, possession or identity manipulation. The roll's named
# conditions and skill carry them when the table can see them.
_MASK_FAMILIES = ('illusion', 'dream', 'disguise', 'memory', 'charm',
                  'possession', 'identity', 'mask', 'false face')


def _owns(engine: Any, actor: Any, mechanic_id: str) -> bool:
    """The actor's compiled bundle lists this foundation feature.

    The compiler files a record wherever its shape compiles: a rider or
    typed modifier under ``modifiers``, a passive block under
    ``typed_passives``, a generic reaction under ``typed_reactions``.
    The Dream-Mirror records use all three (Reflection Cut and
    Dream-Mirror Domain are passives, Generate Mirror Trace and False-Image
    Guard generic reactions), so ownership reads every row store."""
    if actor is None:
        return False
    for document in getattr(engine, 'typed_bundle_documents', None) or ():
        if (document.get('actor_id') or '') != actor.entity_id:
            continue
        if any(row.get('id') == mechanic_id for row in document.get('modifiers') or ()):
            return True
        if any(row.get('feature_id') == mechanic_id
               for row in (document.get('typed_passives') or ())
               + (document.get('typed_reactions') or ())):
            return True
    return False


def _numbers(engine: Any, actor: Any) -> tuple[int, int]:
    values = numbers_of(engine, actor) or {}
    return int(values.get('pb', 0)), int(values.get('key_mod', 0))


def _manual(engine: Any, actor: Any) -> bool:
    from . import ai_controlled
    return not ai_controlled(engine, actor)


def _note(engine: Any, actor: Any, text: str) -> None:
    """One plain log line for the table's history."""
    from . import note
    note(engine, DREAM_MIRROR_DOMAIN, actor, text)


def _domain_active(engine: Any, actor: Any) -> bool:
    return any(c.condition_id == DOMAIN_CONDITION for c in (actor.conditions or {}).values())


def _in_domain(engine: Any, holder: Any, other: Any) -> bool:
    return engine._distance_actor_to_actor(holder, other) <= DOMAIN_RANGE_FT


def _domain_bonus(engine: Any, actor: Any) -> int:
    """Dream-Mirror Domain: once per round, a spent Mirror Trace's numeric
    benefit grows by PB. The first conversion to spend in a round takes it."""
    if not _domain_active(engine, actor):
        return 0
    clock = actor.turn_flags.setdefault('dream_mirror_round_domain_bonus', {})
    if clock.get('round') == engine.state.round_number:
        return 0
    clock['round'] = engine.state.round_number
    return _numbers(engine, actor)[0]


# --------------------------------------------------------------------- Reflection Cut

@hook('compile_block')
def compile_mirror_conversion(block: str, spec: dict, row: dict, numbers: dict) -> list | None:
    """Mark ownership without producing a second upfront attack modifier."""
    if block != 'dream_mirror_conversion':
        return None
    return [{**row, 'kind': spec['kind']}]

def _offer_cut(ctx: Any, subject: Any) -> tuple[str, Payment] | None:
    """The Reflection Cut menu: spend 1 Mirror Trace, choose the damage type."""
    engine, actor = ctx.engine, ctx.actor
    if int(actor.resources.get(TRACE, 0)) < 1:
        return None
    payment = Payment(TRACE, 1)
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'dream_mirror_round_cut', actor.entity_id),
                 actor, CHOICE + 'dream_mirror_round_cut', ['psychic', 'force'],
                 labels={'psychic': 'Psychic damage', 'force': 'Force damage'},
                 prompt=f'Reflection Cut: spend 1 Mirror Trace to add your proficiency bonus '
                        f'as Psychic or Force damage to {ctx.action.display_name} affecting '
                        f'{subject.display_name}. Choose the damage type.',
                 preferred=['force'], allow_decline=True, automatic=not _manual(engine, actor),
                 name='Reflection Cut', feature_id=REFLECTION_CUT,
                 target_id=subject.entity_id, payment=payment,
                 prompt_context=action_context(engine, actor, ctx.action.source_definition_id,
                                               subject, action=ctx.action))
    if not chosen:
        return None
    return chosen[0], payment


def _cut_spent(ctx: Any, subject: Any, damage_type: str) -> None:
    """The Cut's damage rider, plus Dream-Reflection Counter's penalty rider."""
    engine, actor = ctx.engine, ctx.actor
    pb = _numbers(engine, actor)[0] + _domain_bonus(engine, actor)
    run_effects(replace(ctx, targets=[subject], target=subject), [
        {'type': 'extra_damage', 'applies_to': 'target', 'flat': pb, 'damage_types': [damage_type]}])
    _reflection_counter(ctx, subject)
    _note(engine, actor, f'{actor.display_name} spends 1 Mirror Trace: Reflection Cut adds {pb} '
                         f'{damage_type.title()} damage to the effect hitting {subject.display_name}.')


@hook('after_hit_choice')
def reflection_cut(ctx: Any, target: Any, kind: Any) -> None:
    """Reflection Cut's hit half: after you hit a creature,
    spend 1 Mirror Trace to add PB Psychic or Force damage to the hit."""
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _owns(engine, actor, REFLECTION_CUT):
        return
    offered = _offer_cut(ctx, target)
    if offered is None:
        return
    damage_type, payment = offered
    payment.pay(engine, actor, REFLECTION_CUT)
    _cut_spent(ctx, target, damage_type)


@hook('save_final')
def reflection_cut_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Reflection Cut's failed-save half: after a creature
    fails a save against your damaging effect, spend 1 Mirror Trace to add
    PB Psychic or Force damage to it."""
    engine, actor = ctx.engine, ctx.actor
    if not failed or subject is None or subject.entity_id == actor.entity_id:
        return
    if 'damaging_save' not in (named or ()):
        return
    # The generic tag describes either save outcome; this failed outcome
    # itself must deal damage. The executor supplies the exact save packet.
    from .save_damage import has_damage
    if ctx.save_effect is not None and not has_damage(ctx.save_effect.get('on_fail') or []):
        return
    if not _owns(engine, actor, REFLECTION_CUT) or not hostile(actor, subject):
        return
    if ctx.save_result is not None and (actor.turn_flags.get('dream_mirror_round_trace') or {}).get(
            'generated_roll_id') == ctx.save_result.roll_id:
        return
    offered = _offer_cut(ctx, subject)
    if offered is None:
        return
    damage_type, payment = offered
    payment.pay(engine, actor, REFLECTION_CUT)
    _cut_spent(ctx, subject, damage_type)


def _reflection_counter(ctx: Any, target: Any) -> None:
    """Dream-Reflection Counter: the Cut's target takes PB off its next
    Insight, Perception or attack roll against the anchor, before the end
    of its next turn."""
    engine, actor = ctx.engine, ctx.actor
    if not _owns(engine, actor, DREAM_REFLECTION_COUNTER):
        return
    timed_condition(engine, target, COUNTER_CONDITION, REFLECTION_CUT, actor.entity_id,
                    'END_OF_HOLDER_NEXT_TURN',
                    data={'label': f'Dream-Reflection Counter: -{_numbers(engine, actor)[0]} to the next Insight, Perception, '
                                   f'or attack roll against {actor.display_name}, until the end of your next turn',
                          'source_id': actor.entity_id,
                          'penalty': _numbers(engine, actor)[0]})


@hook('d20_bonus')
def dream_reflection_counter(engine: Any, roll: Any, intent: Any) -> dict | None:
    """Dream-Reflection Counter's penalty: the marked creature's next
    Insight, Perception or attack roll against the anchor is PB worse."""
    roller = engine.state.actors.get(roll.actor_id)
    if roller is None:
        return None
    for condition in (roller.conditions or {}).values():
        if condition.condition_id != COUNTER_CONDITION:
            continue
        data = condition.data or {}
        anchor = engine.state.actors.get(str(data.get('source_id') or ''))
        if anchor is None:
            continue
        context = engine.d20_context(roll) or {}
        kind = context.get('kind')
        if kind == 'attack':
            if context.get('target_id') != anchor.entity_id:
                continue
        elif kind == 'check':
            if str(context.get('skill') or '').lower() not in ('insight', 'perception'):
                continue
            if context.get('target_id') != anchor.entity_id:
                continue
        else:
            continue
        engine._remove_condition(roller, COUNTER_CONDITION, DREAM_REFLECTION_COUNTER)
        return {'source_id': DREAM_REFLECTION_COUNTER, 'bonus': -int(data.get('penalty', 0)),
                'user_id': roller.entity_id}
    return None


# --------------------------------------------------------------------- True-Name Witness

def _mask_family(context: dict) -> bool:
    named = {str(n or '').lower() for n in (context.get('named') or ())}
    named.add(str(context.get('skill') or '').lower())
    return any(family in token for token in named for family in _MASK_FAMILIES)


@hook('d20_bonus')
def true_name_witness(engine: Any, roll: Any, intent: Any) -> dict | None:
    """True-Name Witness: after you roll a Fixed
    Dream-Mirror Scope check or saving throw and before the outcome is
    known, spend 1 Mirror Trace to add PB to the roll. The scope cannot
    be sealed, so every own check and save is offered."""
    owner = engine.state.actors.get(roll.actor_id)
    if owner is None or not _owns(engine, owner, TRUE_NAME_WITNESS):
        return None
    context = engine.d20_context(roll) or {}
    if context.get('kind') not in ('check', 'save'):
        return None
    if int(owner.resources.get(TRACE, 0)) < 1:
        return None
    clock = owner.turn_flags.setdefault('dream_mirror_round_witness', {})
    if clock.get('spent_roll_id') == roll.roll_id:
        return None
    source_id = str(context.get('source_id') or '')
    action = engine.action_catalog.get(source_id)
    action_name = action.display_name if action else str(context.get('skill') or 'saving throw')
    source_actor = engine.state.actors.get(context.get('source_actor_id'))
    payment = Payment(TRACE, 1)
    chosen = ask(engine, intent, checkpoint_id(engine, 'dream_mirror_round_witness', owner.entity_id),
                 owner, CHOICE + 'dream_mirror_round_witness', ['use'],
                 labels={'use': 'Add your proficiency bonus to this roll'},
                 prompt=f'True-Name Witness: spend 1 Mirror Trace to add your proficiency bonus '
                        f'to the roll {owner.display_name} makes for {action_name}.',
                 preferred=['use'], allow_decline=True, automatic=not _manual(engine, owner),
                 name='True-Name Witness', feature_id=TRUE_NAME_WITNESS,
                 target_id=owner.entity_id, payment=payment,
                 prompt_context=action_context(engine, source_actor, source_id, owner))
    if not chosen:
        return None
    clock['spent_roll_id'] = roll.roll_id
    payment.pay(engine, owner, TRUE_NAME_WITNESS)
    bonus = _numbers(engine, owner)[0] + _domain_bonus(engine, owner)
    masked = _owns(engine, owner, TRUTH_BEHIND_THE_MASK) and _mask_family(context)
    if masked:
        bonus += _numbers(engine, owner)[0]
        owner.turn_flags.setdefault('dream_mirror_round_witness', {})['roll_id'] = roll.roll_id
    _note(engine, owner, f'{owner.display_name} spends 1 Mirror Trace: True-Name Witness adds {bonus} to the roll.')
    return {'source_id': TRUE_NAME_WITNESS, 'bonus': bonus, 'user_id': owner.entity_id}


@hook('event')
def truth_behind_the_mask(engine: Any, event_type: str, kwargs: dict) -> None:
    """Truth Behind the Mask: a witnessed roll against illusion, dream,
    disguise, memory, charm, possession or identity manipulation adds
    another PB, and on success the witness learns one symbolic truth
    about the source."""
    if event_type not in ('SAVE_ROLLED', 'CHECK_ROLLED'):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or not _owns(engine, actor, TRUTH_BEHIND_THE_MASK):
        return
    clock = actor.turn_flags.get('dream_mirror_round_witness') or {}
    payload = kwargs.get('payload') or {}
    rolled = payload.get('roll_id') or (payload.get('actor') or {}).get('roll_id')
    if clock.get('roll_id') is None or rolled != clock.get('roll_id'):
        return
    clock.pop('roll_id', None)
    if not payload.get('success'):
        return
    _note(engine, actor, f'{actor.display_name} sees the truth behind the mask: one symbolic truth '
                         f'about the source is learned.')


# --------------------------------------------------------------------- Mirror Trace clock

@hook('event')
def mirror_trace_clock(engine: Any, event_type: str, kwargs: dict) -> None:
    """Generated Mirror Trace fades at the end of its holder's next turn
    (the printed expiry). Gained on the holder's own turn it survives
    that turn's end and fades at the next one. The generation round is
    shared with the Dream-Mirror Domain's ally coverage, and a
    False-Image Guard spend consumes the domain's once-per-round +PB."""
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    source = str(kwargs.get('source_definition_id') or '')
    payload = kwargs.get('payload') or {}
    if event_type == 'RESOURCE_GAINED':
        if str(payload.get('resource_id') or '') != TRACE or source != GENERATE_MIRROR_TRACE:
            return
        own_turn = engine.state.current_actor_id == actor.entity_id
        clock = actor.turn_flags.setdefault('dream_mirror_round_trace', {})
        clock['generated_round'] = engine.state.round_number
        clock['ends_left'] = 2 if own_turn else 1
        latest = next((e for e in reversed(engine.events) if e.event_type in ('SAVE_ROLLED', 'ATTACK_ROLLED')), None)
        clock['generated_roll_id'] = str((latest.payload or {}).get('roll_id') or '') if latest else ''
    elif event_type == 'RESOURCE_SPENT':
        if str(payload.get('resource_id') or '') != TRACE or source != FALSE_IMAGE_GUARD:
            return
        # The guard's spend is the conversion the domain amplifies:
        # it consumes the shared once-per-round clock. The reduction
        # itself was already computed with the +PB by
        # domain_guard_bonus; a declined guard never spends, so its
        # amplification is preserved for the next conversion.
        actor.turn_flags.setdefault('dream_mirror_round_domain_bonus', {})['round'] = engine.state.round_number


@hook('turn_end')
def mirror_trace_fade(engine: Any, actor: Any) -> None:
    """The generated Mirror Trace's printed expiry: it fades at the end
    of its holder's next turn."""
    clock = actor.turn_flags.get('dream_mirror_round_trace') or {}
    if not clock:
        return
    ends_left = int(clock.get('ends_left', 0)) - 1
    if ends_left > 0:
        actor.turn_flags['dream_mirror_round_trace'] = {**clock, 'ends_left': ends_left}
        return
    actor.turn_flags['dream_mirror_round_trace'] = {}
    held = int(actor.resources.get(TRACE, 0))
    if held > 0:
        engine._spend_resource(actor, TRACE, held, GENERATE_MIRROR_TRACE)
        _note(engine, actor, f'{actor.display_name}\'s Mirror Trace fades at the end of the turn.')


# --------------------------------------------------------------------- Dream-Mirror Domain

@hook('compile_block')
def compile_domain(block: str, spec: dict, row: dict, numbers: dict) -> list | None:
    if block != 'dream_mirror_domain':
        return None
    return [{**row, 'kind': spec['kind'], 'pb': int(numbers['pb']), 'key_mod': int(numbers['key_mod'])}]


@hook('compile_actions')
def domain_action(info: dict) -> list:
    """Dream-Mirror Domain: the Perfected bonus action button. It costs
    1 Mirror Trace and 2 of the owner's Path pool."""
    from ..factory_compiler import RESOURCE_IDS
    if not any(row.get('block') == 'dream_mirror_domain' and row.get('kind') == 'dream_mirror_domain'
               for row in (info.get('passives') or [])):
        return []
    numbers = info.get('numbers') or {}
    primary = RESOURCE_IDS.get(info.get('primary') or 'qi', 'resource:core.qi')
    return [ActionDefinition(
        source_definition_id='action:typed.%s.dream_mirror_domain' % info['short'],
        display_name='Dream-Mirror Domain',
        owner_id=info['actor_id'],
        economy=EconomyKind.BONUS_ACTION,
        resolution_kind='TYPED',
        target_kind='SELF',
        costs=((TRACE, 1), (primary, 2)),
        parameters={'typed': {'effects': [{'type': 'dream_mirror_domain'}], 'numbers': numbers,
                              'duration': {'kind': 'instant'}, 'riders': []},
                    'expected_damage': 0})]


@effect('dream_mirror_domain')
def dream_mirror_domain(ctx: Any, effect: dict) -> None:
    """Dream-Mirror Domain: a 30-foot emanation that holds for 1 minute.
    While it holds, your Mirror Trace trigger can come from hostile
    misses and failed saves against you or an ally in it, and once per
    round a spent Mirror Trace's benefit grows by PB."""
    engine, actor = ctx.engine, ctx.actor
    timed_condition(engine, actor, DOMAIN_CONDITION, ctx.source, actor.entity_id,
                    clock_expiry(engine, 'one_minute') or 'UNTIL_REMOVED',
                    data={'label': 'Dream-Mirror Domain', 'range_ft': DOMAIN_RANGE_FT})
    _note(engine, actor, f'{actor.display_name} activates Dream-Mirror Domain: a {DOMAIN_RANGE_FT}-foot '
                         f'emanation for 1 minute.')


def _domain_generate(engine: Any, ally: Any) -> None:
    """The domain's ally coverage: a hostile miss or failed save against
    an ally in the emanation generates the holder's Mirror Trace."""
    for holder in engine.state.actors.values():
        if not holder.active or holder.team_id != ally.team_id or holder.entity_id == ally.entity_id:
            continue
        if not _owns(engine, holder, DREAM_MIRROR_DOMAIN) or not _domain_active(engine, holder):
            continue
        if not _in_domain(engine, holder, ally):
            continue
        trace = holder.turn_flags.get('dream_mirror_round_trace') or {}
        if int(holder.resources.get(TRACE, 0)) >= 1:
            continue  # the trace caps at 1; a held one keeps its own expiry
        if trace.get('generated_round') == engine.state.round_number:
            continue  # once per round, shared with the anchor's own triggers
        holder.turn_flags['dream_mirror_round_trace'] = {**trace, 'generated_round': engine.state.round_number,
                                                   'ends_left': 2 if engine.state.current_actor_id == holder.entity_id else 1}
        engine._gain_resource(holder, TRACE, 1, GENERATE_MIRROR_TRACE)
        _note(engine, holder, f'{holder.display_name} gains 1 Mirror Trace: the Dream-Mirror Domain '
                              f'covers {ally.display_name}.')


@hook('attack_result')
def domain_ally_missed(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Dream-Mirror Domain: a hostile attack that misses an ally within
    30 feet of the emanation's holder generates the holder's Mirror
    Trace (the anchor's own misses already carry the compiled trigger)."""
    if hit or target is None:
        return
    engine, actor = ctx.engine, ctx.actor
    if not hostile(actor, target):
        return
    _domain_generate(engine, target)


@hook('save_final')
def domain_ally_save_failed(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Dream-Mirror Domain: a failed save against the holder's effect by
    an ally within 30 feet of the emanation generates the holder's
    Mirror Trace (the anchor's own failed saves already carry the
    compiled trigger)."""
    if not failed or subject is None or subject.entity_id == ctx.actor.entity_id:
        return
    if not hostile(ctx.actor, subject):
        return
    _domain_generate(ctx.engine, subject)


@hook('damage_reduction_bonus')
def domain_guard_bonus(engine: Any, owner: Any, protected: Any, attacker: Any,
                       reaction_row: dict[str, Any]) -> int | None:
    """Dream-Mirror Domain: once per round, a spent Mirror Trace's
    numeric benefit grows by PB -- False-Image Guard's damage
    reduction included.

    The guard's reduction is computed before its own resource
    spend, so this provider answers for the spend it sees being
    paid (the row is the guard's own). It does not consume the
    shared once-per-round clock: the spend's RESOURCE_SPENT event
    (mirror_trace_clock) consumes it, so a declined or failed
    guard preserves the round's amplification for the next
    conversion. Inert without the active emanation."""
    if protected is None or str((reaction_row or {}).get('feature_id') or '') != FALSE_IMAGE_GUARD:
        return None
    if not _owns(engine, protected, DREAM_MIRROR_DOMAIN) or not _domain_active(engine, protected):
        return None
    clock = protected.turn_flags.setdefault('dream_mirror_round_domain_bonus', {})
    if clock.get('round') == engine.state.round_number:
        return None
    return _numbers(engine, protected)[0]
