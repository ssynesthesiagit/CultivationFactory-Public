"""Survivor Cinder Breath: recipient consent and one source-scoped save.

Uses the public save_categories contract: only the pending save's sealed
categories/consequences qualify, never the source's name, team or damage type.
The source's next-start clock and native Temporary HP grant own expiry/stacking.
"""
from . import effect, hook
from .ability_source import mechanic_of
from .needle import ask, checkpoint_id, CHOICE

SOURCE = 'foundation.ash_born_remnant_core_v0_2B.survivor_cinder_breath'
STATUS = 'condition:typed.survivor_cinder_breath'
CONSENT = CHOICE + 'survivor_cinder_consent'
SCOPES = frozenset({'frightened', 'fear', 'despair', 'remnant_possession',
                    'battlefield_horror', 'grief_control', 'grief_based_control',
                    'ash_contamination', 'death_pressure', 'fire_aftermath_backlash'})
READING = ('Advantage on your next saving throw against fear, despair, remnant '
           'possession, battlefield horror, grief-based control, ash contamination, '
           'death pressure or fire-aftermath backlash')


def qualifies(named):
    """Read established per-save facts; absent source qualification is unknown."""
    return bool({str(tag).lower().removeprefix('category:').removeprefix('condition:typed.')
                 for tag in named or ()} & SCOPES)


@hook('choice_reactors')
def recipients(engine):
    if any(mechanic_of(engine.action_catalog[sid]) == SOURCE
           for actor in engine.state.actors.values() for sid in actor.action_ids
           if sid in engine.action_catalog):
        return tuple(a.entity_id for a in engine.state.actors.values() if a.active)
    return None


@hook('technique_declared')
def consent(engine, owner, action, candidate, intent):
    if mechanic_of(action) != SOURCE or not candidate.target_ids:
        return None
    target = engine.state.actors.get(candidate.target_ids[0])
    if target is owner:
        return None
    if target is None:
        return {'cancel': True, 'source_id': SOURCE, 'label': 'Choose one willing creature within 30 feet.'}
    numbers = (action.parameters.get('typed') or {}).get('numbers') or {}
    amount = int(numbers.get('pb', 0)) + int(numbers.get('key_mod', 0))
    willing = ask(engine, intent, checkpoint_id(engine, 'survivor_cinder_consent', target.entity_id),
        target, CONSENT, ['accept'], allow_decline=True, name='Survivor Cinder Breath',
        feature_id=SOURCE, target_id=target.entity_id, automatic=True, default='decline',
        labels={'accept': f'Accept {max(0, amount)} temporary Hit Points and Advantage on the next eligible save'},
        prompt=f'Survivor Cinder Breath: {owner.display_name} offers {target.display_name} {max(0, amount)} temporary Hit Points (keep your existing temporary Hit Points if higher). {READING}, until the start of {owner.display_name}’s next turn. Accept? {owner.display_name} spends a Bonus Action and 1 Remnant Cinder only if you accept.',
        prompt_context={'source_definition_id': action.source_definition_id,
                        'action_name': action.display_name, 'action_actor_id': owner.entity_id,
                        'affected_id': target.entity_id})
    if not willing:
        return {'cancel': True, 'source_id': SOURCE,
                'label': f'{target.display_name} declines Survivor Cinder Breath; no Bonus Action or Remnant Cinder is spent.'}
    return None


@effect('survivor_cinder_breath', harmful=False)
def breath(ctx, eff):
    from ..typed_executor import block_temp_hp
    if mechanic_of(ctx.action) != SOURCE:
        return
    target = ctx.target or ctx.actor
    amount = int(ctx.numbers['pb']) + int(ctx.numbers['key_mod'])
    block_temp_hp(ctx, {'type': 'temp_hp', 'flat': amount, 'applies_to': 'target'})
    cid = STATUS + '.' + ctx.actor.entity_id
    ctx.engine._remove_condition(target, cid, ctx.source)
    ctx.engine._apply_condition(target, cid, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN',
        data={'label': f'Survivor Cinder Breath: {READING}; expires at the start of {ctx.actor.display_name}’s next turn.'})


@hook('save_roll_tags')
def tags(ctx, subject, ability, named):
    if any(c.condition_id.startswith(STATUS + '.') for c in subject.conditions.values()):
        return sorted(named)
    return None


@hook('save_mode')
def mode(engine, subject, ability, dc, source_id, context):
    if (any(c.condition_id.startswith(STATUS + '.') for c in subject.conditions.values())
            and qualifies(context.get('named') or context.get('conditions'))):
        return 'ADVANTAGE'
    return None


@hook('event', nested=True)
def consume(engine, event_type, kw):
    if event_type != 'SAVE_ROLLED':
        return
    subject = engine.state.actors.get(kw.get('actor_id'))
    context = engine.d20_context() or {}
    # Direct hazard/legacy receipts may run inside another source's pending
    # save. Only this actual save's own facts can spend the recipient's grant.
    if (subject is None or context.get('kind') != 'save'
            or context.get('actor_id') != subject.entity_id
            or context.get('source_id') != kw.get('source_definition_id')
            or not qualifies(context.get('named') or context.get('conditions'))):
        return
    for condition in list(subject.conditions.values()):
        if condition.condition_id.startswith(STATUS + '.'):
            engine._remove_condition(subject, condition.condition_id, condition.source_definition_id)
