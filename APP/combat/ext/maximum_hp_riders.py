"""Iron-Bone Stew and the single Modify Characteristics critical-hit decision.

Prepared food and Analyze discoveries are external facts: ask the owner to confirm
them, defaulting to no benefit. This does not cook meals in combat or invent known
characteristics. Shared characteristic effects live in riders14_research.

``max_hp_loss(engine, target, amount, source, name=..., key=...)`` is the shared
"reduce a creature's current and maximum Hit Points by N until you finish a Long
Rest" step. A fight contains no rest (combat/ext/d20_rewrite.py: "once per long rest
or scene" is once per fight), so the reduction is keyed on its own condition and
lasts the rest of the fight; the printed Long Rest is what ends it between fights.
Used by combat/ext/unmaking_forms.py (The Moment Nothing Answers) and
combat/ext/unmaking_channels.py (the printed prices that cost maximum Hit Points).
"""
from . import hook
from .needle import ask, checkpoint_id
from .. import maximum_hp
from ..alternative_payments import owned
import re

MEAL = 'tianxia.subpath.qi.culinary_cultivator.feature.body_tempering_meal'
MODIFY = 'TAL_THE_HIDDEN_EYE_MODIFY_CHARACTERISTICS'
FOCUS = 'resource:core.martial_focus'
STEW = 'condition:typed.iron_bone_stew'
MODIFIED = 'condition:typed.modified_maximum_hp'
LOST = 'condition:typed.maximum_hp_lost'


def max_hp_loss(engine, target, amount, source, *, name='', key='', label=''):
    """Reduce current and maximum Hit Points by ``amount`` under a keyed condition; returns the max-HP delta.

    ``amount`` is this payment; the keyed condition carries the total paid so far, so paying twice takes 20 off the
    maximum (not 10 twice over) and takes 20 off current Hit Points (not 10, then 10 again from an unchanged total). One
    key therefore stacks into one reduction. A living target never drops to 0 by this: the printed reduction is a lasting
    wound, and combat/maximum_hp.py never revives anyone at 0. ``key`` must be stable across processes (it becomes part of
    the saved condition id). Only the new payment reaches current Hit Points; removing the condition restores the maximum
    it reduced and heals nothing, so the earlier payments are not charged twice. A condition saved before the running
    total was added (2026-10-05) keeps its earlier payments too: its stored ``amount`` is read as the total paid. The
    returned delta is this payment's own
    share of the loss (``-amount``), which is what the caller logs; the 1-HP floor in combat/maximum_hp.py can leave the
    maximum higher than that on a creature that is already at it.
    """
    amount = int(amount or 0)
    if amount <= 0 or target is None or not target.active or target.current_hp <= 0:
        return 0
    text = label or f'{name or "This"}: {amount} fewer maximum Hit Points until you finish a Long Rest'
    slug = re.sub(r'[^a-z0-9]+', '_', f'{key or source}:{text}'.lower()).strip('_')[:48]
    condition_id = f'{LOST}.{slug}'
    held = next((c for c in target.conditions.values() if c.condition_id == condition_id), None)
    prior = dict((held.data if held is not None else None) or {})
    # A fight saved before the running total existed (2026-10-05) holds `amount` = everything paid so far and no `lost`,
    # with that total already sitting in the creature's maximum-HP adjustment. Read that as the amount paid so far, so
    # the next payment stacks onto it instead of dropping the earlier ones and restoring their reduction.
    paid = int(prior['lost'] if 'lost' in prior else (prior.get('amount') or 0))
    total = paid + amount
    engine._remove_condition(target, condition_id, source)
    engine._apply_condition(target, condition_id, source, target.entity_id, expires_on='UNTIL_REMOVED',
                            data={'label': text, 'amount': amount, 'lost': total})
    condition = next(c for c in reversed(list(target.conditions.values())) if c.condition_id == condition_id)
    maximum_hp.bind(engine, target, condition, -total, label=text, current_delta=-amount, current_floor=1)
    return -(total - paid)


@hook('compile_block')
def maximum_hp_block(block, spec, row, numbers):
    if block == 'maximum_hp_rider':
        return [{**row, 'block': block}]


@hook('fight_setup_tasks')
def meal_tasks(engine):
    return [{'actor_id': actor.entity_id, 'source_id': MEAL}
            for actor in engine.state.actors.values() if owned(engine, actor, MEAL)] or None


@hook('fight_setup')
def prepared_stew(engine, cook, source, intent):
    if source != MEAL:
        return None
    allies = [a for a in engine.state.actors.values() if a.active and a.current_hp > 0 and a.team_id == cook.team_id]
    selected = ask(engine, intent, checkpoint_id(engine, 'prepared_stew', cook.entity_id), cook,
        'choice:needle.prepared_stew', [a.entity_id for a in allies],
        labels={a.entity_id: a.display_name for a in allies}, minimum=0,
        maximum=1 + 2 * cook.proficiency_bonus, allow_decline=True, default='decline', automatic=False,
        prompt=f'Iron-Bone Stew is a prepared meal benefit: +{2 * cook.proficiency_bonus} maximum and current Hit Points '
               'until the eater finishes their next Long Rest or another meal benefit replaces it. '
               'Choose only willing creatures who already ate it before this fight. Confirm that you learned this recipe, '
               'completed its 1-hour ritual, paid 1 Qi and one day of food per eater, and served one meal portion each. '
               'This confirms earlier preparation; it does not cook or pay for food now. Choose none otherwise.',
        name='Prepared Iron-Bone Stew', feature_id=MEAL)
    if len([aid for aid in selected if aid != cook.entity_id]) > 2 * cook.proficiency_bonus:
        raise ValueError('Iron-Bone Stew permits the cook and at most twice Proficiency Bonus other creatures')
    for aid in selected:
        target = engine.state.actors[aid]
        engine._remove_condition(target, STEW, MEAL)
        engine._apply_condition(target, STEW, MEAL, cook.entity_id, expires_on='UNTIL_REMOVED',
            data={'label': 'Iron-Bone Stew: until the end of your next Long Rest; another Course replaces it'})
        condition = next(c for c in target.conditions.values() if c.condition_id == STEW)
        amount = 2 * cook.proficiency_bonus
        maximum_hp.bind(engine, target, condition, amount, label='Iron-Bone Stew', current_delta=amount,
                        expiry_current_delta=-amount, current_floor=1)
    return True


@hook('hit_snapshot')
def modification_eligibility(engine, owner, target, attack, intent):
    from .mind_hidden_eye import analyzed_by, known_characteristic
    from .riders14_research import modification_options
    from .life_state import is_deceased
    if not attack.critical or not owned(engine, owner, MODIFY) or not analyzed_by(target, owner.entity_id) or is_deceased(target):
        return None
    return {'maximum_hp_riders': {'eligible': True,
                                 'characteristics': modification_options(owner, target),
                                 'known_maximum_hp': known_characteristic(target, owner.entity_id, 'maximum_hp')}}


@hook('hit_final')
def modify_maximum(ctx, target, kind):
    from .mind_hidden_eye import record_characteristic
    from .life_state import is_deceased
    attack = ctx.attack_damage_context
    owner, engine = ctx.actor, ctx.engine
    receipt = ctx.hit_snapshots.get('maximum_hp_riders') or {}
    if (attack is None or not attack.critical or not receipt.get('eligible') or is_deceased(target)
            or owner.resources.get(FOCUS, 0) < 1):
        return
    known = bool(receipt.get('known_maximum_hp'))
    characteristics = list(receipt.get('characteristics') or [])
    options = [*characteristics, 'maximum_hp']
    def detail(name):
        if name == 'Armor Class': return 'reduce Armor Class by 2'
        if name == 'Walking Speed': return 'reduce walking Speed by 10 feet'
        if name.endswith(' saving throw'): return 'reduce that saving throw bonus by 2'
        if name.endswith(' Resistance'): return 'suppress that damage Resistance'
        if name.endswith(' Sense'): return 'reduce that sense range by 10 feet'
        return 'modify this previously learned characteristic'
    labels = {name: f'{name}: {detail(name)} for one hour; costs 1 Martial Focus' for name in characteristics}
    labels['maximum_hp'] = 'Maximum Hit Points: spend 1 Martial Focus to reduce the maximum by 10 (minimum 1)'
    selected = ask(engine, ctx.intent, checkpoint_id(engine, 'modify_maximum', attack.roll_id), owner,
        'choice:needle.modify_maximum', options, labels=labels,
        allow_decline=True, default='decline', automatic=known or bool(characteristics),
        prompt=f'Modify Characteristics: {ctx.action.display_name} scored a Critical Hit against {target.display_name}. '
        'Choose one previously learned characteristic to change for one hour, spending 1 Martial Focus. '
        'The maximum Hit Points choice reduces its maximum by 10 (minimum 1) and caps current Hit Points; it never heals a creature at 0. '
        + ('Your earlier knowledge of this characteristic is recorded.' if known else
           'Choose maximum Hit Points only if you previously learned that value; being Analyzed alone is not enough.'),
        name='Modify Characteristics', feature_id=MODIFY)
    if not selected:
        return
    from .riders14_research import clear_modification, apply_modification
    clear_modification(engine, owner, target)
    engine._spend_resource(owner, FOCUS, 1, MODIFY)
    # This owner's previous modification is replaced, not another Eye's.
    for iid, old in list(target.conditions.items()):
        if old.condition_id == MODIFIED and old.source_actor_id == owner.entity_id:
            del target.conditions[iid]
            engine._append_event('CONDITION_REMOVED', MODIFY, actor_id=owner.entity_id,
                target_ids=(target.entity_id,), payload={'instance_id': iid, 'condition_id': MODIFIED})
    if selected[0] != 'maximum_hp':
        apply_modification(ctx, target, selected[0])
        return
    record_characteristic(engine, owner, target, 'maximum_hp', MODIFY, newly_learned=False)
    engine._apply_condition(target, MODIFIED, MODIFY, owner.entity_id, expires_on='UNTIL_REMOVED',
        data={'label': 'Modify Characteristics: maximum Hit Points reduced by 10 for one hour',
              'maximum_hp_expires_round': engine.state.round_number + 600})
    condition = next(c for c in reversed(list(target.conditions.values()))
                     if c.condition_id == MODIFIED and c.source_actor_id == owner.entity_id)
    maximum_hp.bind(engine, target, condition, -10, label='Modify Characteristics')


@hook('turn_start')
def hour_expiry(engine, actor):
    for target in engine.state.actors.values():
        for iid, condition in list(target.conditions.items()):
            expiry = condition.data.get('maximum_hp_expires_round')
            if expiry is not None and engine.state.round_number >= expiry:
                del target.conditions[iid]
                engine._append_event('CONDITION_REMOVED', condition.source_definition_id,
                    actor_id=actor.entity_id, target_ids=(target.entity_id,),
                    payload={'instance_id': iid, 'condition_id': condition.condition_id})
