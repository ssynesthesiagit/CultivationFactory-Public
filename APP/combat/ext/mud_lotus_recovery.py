"""Lotus Recovery Field map, chosen allies and settled recovery delivery.

mud_lotus_native supplies source-declared injury/corruption and hostile-roll
consumers; this remains the sole map/recovery provider for the ability.
"""
import json
from . import effect, hook
from ..recovery_sources import recovery_origin

FIELD = 'foundation.mud_lotus_dantian_v0_2A.lotus_recovery_field'
CONDITION = 'condition:typed.mud_lotus_recovery_field'
CHOICE = 'choice:needle.mud_lotus_field_allies'
SAVE_SCOPE = frozenset({'poison', 'poisoned', 'disease', 'rot', 'polluted_water',
                        'sickness_exhaustion', 'terrain_contamination'})
REWARD_SCOPE = frozenset({'poison', 'poisoned', 'disease', 'rot'})
OFFER = 'mud_lotus_field_offer_pending'


def tags(named):
    """Normalize the native save dispatch's explicit consequence categories."""
    return {str(t).lower().removeprefix('category:').removeprefix('damage:')
            for t in named or ()}


def fields(engine, subject, *, any_creature=False):
    """Yield owned, live fields that actually contain this chosen ally."""
    from .. import zones
    from ..relations import relation, ALLY
    for owner in engine.state.actors.values():
        condition = next((c for c in owner.conditions.values() if c.condition_id == CONDITION), None)
        if condition is None or (not any_creature and relation(engine, owner, subject) != ALLY):
            continue
        from .mud_lotus_native import ownership
        if ownership(engine, owner, FIELD) is None:
            continue
        if not any(engine.action_catalog[aid].parameters.get('typed', {}).get('source') == FIELD
                   for aid in owner.action_ids if aid in engine.action_catalog):
            continue
        data = condition.data
        if not any_creature and subject.entity_id not in str(data.get('chosen', '')).split('\n'):
            continue
        zone = engine.state.zones.get(data.get('zone_id'))
        if zone is not None and zone.active and zones.actor_inside_zone(engine, subject, zone):
            yield owner, condition


@effect('mud_lotus_recovery_field', harmful=False)
def manifest(ctx, eff):
    if ctx.typed.get('source') != FIELD:
        return
    from .. import zones
    from ..typed_executor import effect_expiry
    from .needle import ask, checkpoint_id
    zone = zones.create(ctx, {'shape': 'emanation', 'size_ft': 20,
        'name': 'Lotus Recovery Field', 'centered_on_self': True,
        'follows_owner': True, 'include_origin': True, 'duration': {'kind': 'one_minute'}})
    if zone is None:
        return
    from ..relations import relation, ALLY
    allies = [a for a in ctx.engine.state.actors.values()
              if a.active and relation(ctx.engine, a, ctx.actor) == ALLY
              and zones.actor_inside_zone(ctx.engine, a, zone)]
    chosen = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'MUD_LOTUS_FIELD_ALLIES', ctx.actor.entity_id),
        ctx.actor, CHOICE, [a.entity_id for a in allies],
        minimum=0, maximum=len(allies), allow_decline=True, default='all',
        labels={a.entity_id: a.display_name for a in allies},
        name='Lotus Recovery Field', feature_id=FIELD,
        prompt='Lotus Recovery Field: choose allies in your 20-foot field. '
               'For 1 minute while inside, they have Advantage on poison, disease, '
               'rot, sickness exhaustion, polluted water and terrain contamination saves. '
               'Once per round, one qualifying recovery gains your Proficiency Bonus '
               'in temporary Hit Points. This Bonus Action costs 2 cultivation points '
               '(your Path resource) and your once-per-long-rest use.')
    ctx.engine._apply_condition(ctx.actor, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {'duration': {'kind': 'one_minute'}}, ctx.actor, condition=True),
        data={'zone_id': zone.zone_id, 'chosen': '\n'.join(chosen),
              'pb': int(ctx.numbers['pb']), 'used_round': -1,
              'label': 'Lotus Recovery Field: chosen allies within 20 feet; 1 minute. '
                       'Scoped saving throw Advantage and once-per-round recovery support.'})


@hook('save_mode')
def field_save(engine, subject, ability, dc, source_id, context):
    if tags(context.get('named') or context.get('conditions')) & SAVE_SCOPE:
        if next(fields(engine, subject), None) is not None:
            return 'ADVANTAGE'
    return None


@hook('save_roll_tags')
def field_save_tags(ctx, subject, ability, named):
    if next(fields(ctx.engine, subject), None) is not None:
        return sorted(named)
    return None


def reward(engine, subject, *, extra_base=None):
    """A settled HP/save event grants PB temp HP under ordinary nonstacking rules."""
    eligible = [(owner, c) for owner, c in fields(engine, subject)
                if c.data['used_round'] != engine.state.round_number]
    if extra_base is not None and eligible:
        owner, best = max(eligible, key=lambda pair: (int(pair[1].data['pb']), pair[1].applied_sequence))
        for grantor, condition in eligible:
            engine._update_condition_data(grantor, condition,
                {**condition.data, 'used_round': engine.state.round_number}, FIELD)
        engine._grant_temp_hp(subject, extra_base + int(best.data['pb']), FIELD, owner.entity_id)
        return
    for owner, condition in eligible:
        if condition.data['used_round'] == engine.state.round_number:
            continue
        engine._update_condition_data(owner, condition,
            {**condition.data, 'used_round': engine.state.round_number}, FIELD)
        engine._grant_temp_hp(subject, int(condition.data['pb']), FIELD, owner.entity_id)


@hook('save_final')
def field_save_recovery(ctx, subject, ability, named, failed):
    if not failed and tags(named) & REWARD_SCOPE:
        with recovery_origin(ctx.engine, ctx.actor.entity_id, ctx.source, subject.entity_id):
            reward(ctx.engine, subject)


@hook('temp_hp_offered_bonus')
def field_temp_hp(engine, subject, amount, source_id, source_actor_id, *, consume):
    # The committed receipt below spends the round allowance, not a preview or
    # a rejected offer. The field's own save/healing reward cannot trigger itself.
    if source_id == FIELD or amount <= 0:
        return None
    eligible = [(owner, c) for owner, c in fields(engine, subject)
                if c.data['used_round'] != engine.state.round_number]
    if not eligible:
        return None
    owner, best = max(eligible, key=lambda pair: (int(pair[1].data['pb']), pair[1].applied_sequence))
    bonus = int(best.data['pb'])
    if consume and bonus > 0:
        pending = json.loads(subject.turn_flags.get(OFFER) or '[]')
        pending.append({'source_id': source_id, 'source_actor_id': source_actor_id or '',
            'round': int(engine.state.round_number), 'bonus': bonus,
            'provider': owner.entity_id, 'condition': best.instance_id,
            'fields': [[a.entity_id, c.instance_id] for a, c in eligible]})
        subject.turn_flags[OFFER] = json.dumps(pending)
    return bonus or None


@hook('state_event')
def field_recovery(engine, event):
    event_type = event.event_type
    if event_type not in ('HEALING_APPLIED', 'TEMP_HP_GRANTED') or event.source_definition_id == FIELD:
        return
    payload = event.payload
    before, after = payload.get('before'), payload.get('after')
    for aid in event.target_ids:
        subject = engine.state.actors.get(aid)
        if subject is None:
            continue
        quote = None
        if event_type == 'TEMP_HP_GRANTED':
            pending = json.loads(subject.turn_flags.get(OFFER) or '[]')
            index = next((i for i in range(len(pending) - 1, -1, -1)
                          if pending[i]['source_id'] == event.source_definition_id
                          and pending[i]['source_actor_id'] == (event.actor_id or '')), None)
            if index is not None:
                quote = pending.pop(index)
                if pending:
                    subject.turn_flags[OFFER] = json.dumps(pending)
                else:
                    subject.turn_flags.pop(OFFER, None)
        if type(before) is not int or type(after) is not int or after <= before:
            continue
        with recovery_origin(engine, event.actor_id, event.source_definition_id, aid):
            if event_type == 'HEALING_APPLIED':
                reward(engine, subject)
            elif quote is None:
                reward(engine, subject, extra_base=after)
            else:
                current = {(a.entity_id, c.instance_id): (a, c) for a, c in fields(engine, subject)}
                for key in quote['fields']:
                    if tuple(key) not in current:
                        continue
                    owner, condition = current[tuple(key)]
                    engine._update_condition_data(owner, condition,
                        {**condition.data, 'used_round': engine.state.round_number,
                         'last_recovery_event': int(event.sequence), 'last_recovery_target': aid,
                         'last_quoted_bonus': int(quote['bonus']),
                         'last_native_gain': int(after - before)}, FIELD)
                provider = current.get((quote['provider'], quote['condition']))
                if provider is not None and quote['bonus'] > 0:
                    from .mud_lotus_native import field_recovery_receipt
                    field_recovery_receipt(engine, provider[0], subject, event)
