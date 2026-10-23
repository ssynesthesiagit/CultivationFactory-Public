"""Essence Rot: a paid trigger on committed owned Poison damage to a Poison-Touched creature.

Printed (Tianxia Qi Cultivation Subpath Compendium R19, Poison Cultivator CL14):
"Trigger: You deal Poison damage to a creature currently affected by Poison Touch. Cost: 4 Qi.
Limit: Once per target per scene. Saving Throw: Constitution. Failed Save: Reduce Hit Point
maximum by 3d8 + key modifier. Successful Save: Reduce it by 1d8 until the start of your next
turn. ... Multiple reductions from you do not stack; reapplication replaces the old amount only
if higher. Essence Rot cannot reduce maximum below 1."

The typed record (authority/typed_mechanics/reviewed_final.d/mgr_t14_poison_features.json)
carries the two save outcomes as ``essence_rot`` rows. This module is their one consumer:

  * ``compile_actions`` publishes the record as an owned trigger resolver (economy NONE). It is
    never offered as a usable action (``candidate_allowed``), exactly like Poison Touch's own
    resolver, so the printed trigger stays the only way to use it.
  * ``damage_dealt`` raises the question after an owned Poison packet lands on a creature that
    bears Poison Touch, charges the printed 4 Qi (or the 2 Qi Decaying Presence override), and
    enforces once per target per fight.
  * ``essence_rot`` applies the Hit Point maximum reduction through combat/maximum_hp.py, keyed
    on one condition per owner so a lower reapplication never replaces a higher amount and a
    temporary success reduction is restored at the start of the owner's next turn. The printed
    "Immunity to maximum-HP reduction applies" is the general defence channel
    ``max_hp_reduction`` (combat/maximum_hp.immune): a protected target is not offered the paid
    trigger and its maximum is never lowered, by this feature or any other reducer.

Every hook returns early unless the actor owns the row and a qualifying packet landed, so
nothing changes for other characters, for non-Poison damage, or for a creature without
Poison Touch. Stored state is integers and strings only (condition data and turn flags), so a
table commit and cold reload keep it.
"""
from __future__ import annotations

import re
from copy import deepcopy

from . import effect, hook

FEATURE = 'tianxia.subpath.qi.poison_cultivator.feature.essence_rot'
PRESENCE = 'tianxia.subpath.qi.poison_cultivator.feature.lord_of_decay'
POISON_TOUCH = 'condition:typed.poison_touch'
BLOCK = 'essence_rot'
NAME = 'Essence Rot'
QI = 'resource:core.qi'
USED = 'essence_rot_targets'
CONDITION = 'condition:typed.essence_rot'


def _resolver(engine, actor):
    for action_id in getattr(actor, 'action_ids', ()):
        action = engine.action_catalog.get(action_id)
        if action is not None and (action.parameters or {}).get('essence_rot_resolver'):
            return action
    return None


def _cost(actor, action):
    """The printed 4 Qi, replaced by the active Decaying Presence override (2 Qi)."""
    printed = int((action.parameters.get('typed') or {}).get('cost') or 0)
    from .feature_state import override_for

    return int(override_for(actor, FEATURE, source_feature=PRESENCE).get('cost', printed))


def _touched(ctx, target):
    """The creature was already affected by Poison Touch when this activation began.

    "Currently affected by Poison Touch" is the state before the poison packet
    lands. A carrier this same use just applied (Poison Touch's own rider) is not
    that state, so the activation's own journal window is excluded: only a
    condition already applied before ``ctx.technique_event_start`` counts.
    """
    held = [condition for condition in target.conditions.values()
            if condition.condition_id == POISON_TOUCH]
    if not held:
        return False
    start = getattr(ctx, 'technique_event_start', None)
    if start is None:
        return True
    prior = {str((event.payload or {}).get('condition_id') or '')
             for event in ctx.engine.events[:int(start)]
             if event.event_type == 'CONDITION_APPLIED' and target.entity_id in event.target_ids}
    return POISON_TOUCH in prior


def _poison_landed(ctx):
    return any(str(packet.get('damage_type') or '').upper() == 'POISON'
               and int(packet.get('hp_damage') or 0) + int(packet.get('temporary_hp_absorbed') or 0) > 0
               for packet in ctx.damage_packets)


def _used(actor):
    return dict(actor.turn_flags.get(USED) or {})


def _apply(engine, owner, target, amount, *, lasting):
    """Set this owner's reduction, replacing the old amount only when the new one is higher."""
    if amount <= 0 or not target.active or target.current_hp <= 0:
        return 0
    from .. import maximum_hp

    if maximum_hp.immune(engine, target):  # "Immunity to maximum-HP reduction applies"
        return 0
    condition_id = f'{CONDITION}.{_slug(owner.entity_id)}'
    held = [condition for condition in target.conditions.values()
            if condition.condition_id == condition_id and condition.source_actor_id == owner.entity_id]
    previous = max((int(condition.data.get('amount') or 0) for condition in held), default=0)
    if amount <= previous:
        return 0
    for condition in held:
        engine._remove_condition(target, condition.condition_id, condition.source_definition_id)
    expires = 'UNTIL_REMOVED' if lasting else 'START_OF_SOURCE_NEXT_TURN'
    label = (f'{NAME}: {target.display_name} has {amount} fewer maximum Hit Points for the rest of the fight'
             if lasting else
             f'{NAME}: {target.display_name} has {amount} fewer maximum Hit Points until the start of your next turn')
    engine._apply_condition(target, condition_id, FEATURE, owner.entity_id, expires_on=expires,
                            data={'amount': int(amount), 'lasting': 1 if lasting else 0, 'label': label})
    condition = next(condition for condition in reversed(list(target.conditions.values()))
                     if condition.condition_id == condition_id)
    maximum_hp.bind(engine, target, condition, -int(amount), label=label)
    engine._append_event('PASSIVE_TRIGGERED', FEATURE, actor_id=owner.entity_id,
                         target_ids=(target.entity_id,),
                         payload={'feature_id': FEATURE, 'essence_rot': int(amount),
                                  'lasting': 1 if lasting else 0, 'log': label})
    return int(amount)


def _slug(value):
    return re.sub(r'[^a-z0-9]+', '_', str(value).lower()).strip('_')[-40:]


@hook('compile_block')
def owned_row(block, spec, row, numbers):
    """The feature block marker (combat/rules/feature_blocks.d) records ownership.

    This ability is a trigger, not a passive benefit of its own: the row exists so
    the feature is not reported as a Game Master ruling, and every hook above still
    gates on the compiled resolver plus a qualifying committed packet.
    """
    if block == BLOCK:
        return [{**row, 'choice_owner': True}]
    return None


@hook('compile_actions')
def resolver(info):
    """The record's own trigger resolver, owned and hidden; never a usable action."""
    if FEATURE not in (info.get('owned_ids') or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .path_numbers import numbers_for

    numbers = numbers_for(info, 'tianxia.path.qi_cultivation')
    if int(numbers['cl']) < 14:
        return None
    record = (info.get('mechanics') or {}).get(FEATURE)
    if not record:
        return None
    printed = sum(int(row.get('amount') or 0) for row in next(iter(record.get('cost') or ()), ())
                  if str(row.get('resource') or '').strip().lower() in ('qi', 'resource:core.qi'))
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.{FEATURE}",
        display_name=NAME, owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='ANY_CREATURE',
        parameters={'essence_rot_resolver': True,
                    'typed': {'source': FEATURE, 'numbers': numbers,
                              'effects': deepcopy(record['effects']), 'riders': [],
                              'duration': {'kind': 'instant'}, 'cost': printed}})]


@hook('candidate_allowed')
def triggered_only(engine, actor, candidate, action):
    """The trigger is the only way to use Essence Rot."""
    if action is not None and (action.parameters or {}).get('essence_rot_resolver'):
        return False
    return None


@hook('damage_dealt')
def essence_rot(ctx, target, amount):
    """Ask, charge and resolve after the qualifying Poison packet has landed."""
    if target is None or not target.active or target.current_hp <= 0 or int(amount or 0) <= 0:
        return
    if target.entity_id == ctx.actor.entity_id or not _poison_landed(ctx) or not _touched(ctx, target):
        return
    action = _resolver(ctx.engine, ctx.actor)
    if action is None:
        return
    used = _used(ctx.actor)
    if target.entity_id in used:
        return
    from .. import maximum_hp

    if maximum_hp.immune(ctx.engine, target):
        ctx.rider(f'{NAME}: {target.display_name} is immune to Hit Point maximum reduction, '
                  f'so {NAME} is not offered.')
        return
    cost = _cost(ctx.actor, action)
    if int(ctx.actor.resources.get(QI, 0)) < cost:
        return
    from .choice_costs import Payment
    from .rider_choices import pick

    payment = Payment(QI, cost)
    price = f'Spend {cost} Qi' if cost else 'Use at no Qi cost'
    selected = pick(ctx.engine, ctx.actor, 'essence_rot', NAME, ['apply'], subject=target, intent=ctx.intent,
                    labels={'apply': f'{price}: Constitution save; on a failure its Hit Point maximum falls '
                                     f'by 3d8 + your Key Ability modifier, or by 1d8 until your next turn on a success'},
                    preferred=['apply'], prompt_context=payment.context(), automatic_options=['apply'],
                    prompt=f'{NAME}: {ctx.action.display_name} dealt Poison damage to {target.display_name}, '
                           f'which is affected by your Poison Touch. {price}, once per target per scene? '
                           f'It makes a Constitution save: on a failure its Hit Point maximum falls by '
                           f'3d8 + your Key Ability modifier; on a success by 1d8 until the start of your next turn. '
                           f'A lower repeat never replaces a higher reduction.')
    if not selected:
        return
    typed = action.parameters['typed']
    used[target.entity_id] = 1
    ctx.actor.turn_flags[USED] = used
    from ..typed_executor import Context, run_effects

    run_effects(Context(ctx.engine, ctx.actor, action, ctx.intent, typed, [target], target, {}), typed['effects'])
    payment.pay(ctx.engine, ctx.actor, action.source_definition_id)


@effect(BLOCK)
def reduce_maximum(ctx, row):
    """Roll this outcome's reduction and apply it through the shared maximum-HP seam."""
    target = ctx.target or next(iter(ctx.targets or []), None)
    if target is None:
        return
    from ..typed_executor import _effect_dice, _roll

    amount = _roll(ctx, ctx.dice(_effect_dice(ctx, row), flat=int(row.get('flat') or 0),
                                 formula=row.get('formula')), 'ESSENCE_ROT')
    _apply(ctx.engine, ctx.actor, target, int(amount), lasting=bool(row.get('lasting')))
