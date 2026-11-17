"""Shadowed Mien: recipient Meld, observer-qualified checks and optional HP.

Uses the existing Meld recipient consent/lifetime contract and ordinary opposed
check mode query. Temporary HP track their accepted native grant receipt, so
ending this Meld cannot erase an unrelated larger or later replacement pool.
"""
from . import hook, effect

MIEN = 'TAL_DARK_SHADOWED_MIEN'
MELD = 'TAL_DARK_MELD'
CLEAR = 'TAL_DARK_CLEARSIGHT'
POOL = 'condition:typed.shadowed_mien_hp'


@hook('compile_actions')
def actions(info):
    if MIEN not in info['owned_ids'] or MELD not in info['owned_ids']:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition
    persistent = 'TAL_DARK_PERSISTENT_MELD' in info['owned_ids']
    result = []
    for lasting in ([False, True] if persistent else [False]):
        for hp in [False, True]:
            duration = {'kind': 'hours', 'amount': 1, 'concentration': not lasting}
            cost = (2 if lasting else 0) + int(hp)
            name = 'Meld: Shadowed Mien' + (' (Persistent)' if lasting else '') + (' (1 CP: Temporary HP)' if hp else '')
            effects = [{'type': 'meld_set', 'talent': MIEN, 'name': 'Shadowed Mien',
                        'concentration': not lasting, 'duration': duration}]
            if hp:
                effects.append({'type': 'shadowed_mien_hp'})
            result.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mien.{int(lasting)}.{int(hp)}",
                display_name=name, owner_id=info['actor_id'], economy='ACTION', resolution_kind='TYPED',
                target_kind='ANY_CREATURE', range_ft=5, concentration=not lasting,
                costs=((RESOURCE_IDS[info['primary']], cost),) if cost else (),
                parameters={'meld_talent': MIEN, 'meld_runtime': 2,
                    'meld_upgrades': {'persistent': lasting, 'temporary_hp': int(info['numbers']['cl']) if hp else 0},
                    'typed': {'source': MIEN, 'numbers': info['numbers'], 'effects': effects, 'duration': duration, 'riders': []},
                    'description': 'Touch a creature to cloak its appearance, subtle movements and intentions in shadow. '
                        'It sees outward normally. It has Advantage on Deception and Intimidation; observers have Disadvantage '
                        'on Insight to discern its intentions. Clearsight or sight through supernatural Darkness reveals it '
                        'and suppresses these benefits for that observer; ordinary Darkvision does not. '
                        f'Cost: {cost} cultivation points. Up to 1 hour' + (' without Concentration. ' if lasting else ', Concentration. ')
                        + ('Also grant Temporary HP equal to your Cultivation Level while this Meld lasts. Losing them does not end the Meld. ' if hp else '')
                        + 'An unwilling creature may resist with a Wisdom save.'}))
    return result


def grant(engine, holder):
    from .. import senses, concentration
    from .effect_durations import due
    return next((c for c in holder.conditions.values() if c.condition_id == senses.MELD
        and c.data.get('talent') == MIEN and not due(engine, c.data.get('end_clock'))
        and (not c.data.get('concentration') or concentration.concentrating_on(
             engine.state.actors.get(c.source_actor_id, holder), c.source_definition_id))), None)


def revealed(engine, holder, observer):
    """Only Clearsight or an in-range sight sense piercing supernatural Darkness."""
    from .. import senses
    if not senses.physical_sight(engine, observer, holder):
        return False
    if CLEAR in senses.melds_of(engine, observer):
        return True
    kinds = senses.rules().get('kinds') or {}
    return any(sense != 'darkvision' and 'darkness' in kinds.get(sense, {}).get('through', [])
        and engine._distance_actor_to_actor(observer, holder) <= senses.reach(engine, observer, sense, holder)
        for sense in senses.perception_senses(engine, observer, sight_only=True))


@hook('ability_check_mode')
def check_mode(engine, actor, ability, skill, opponent):
    skill = str(skill or '').lower()
    if skill in ('deception', 'intimidation') and str(ability).upper() == 'CHA':
        if grant(engine, actor) and not revealed(engine, actor, opponent):
            return 'ADVANTAGE'
    elif skill == 'insight' and str(ability).upper() == 'WIS':
        if grant(engine, opponent) and not revealed(engine, opponent, actor):
            return 'DISADVANTAGE'
    return None


@effect('shadowed_mien_hp', harmful=False)
def temporary_hp(ctx, row):
    from .temp_hp_grants import held_grant
    target = ctx.target or ctx.actor
    meld = grant(ctx.engine, target)
    if meld is None or meld.source_definition_id != ctx.source or meld.source_actor_id != ctx.actor.entity_id:
        return
    if not any(e.event_type == 'CONDITION_APPLIED' and e.payload.get('instance_id') == meld.instance_id
               for e in ctx.engine.events[getattr(ctx, 'technique_event_start', len(ctx.engine.events)):]):
        return
    before = held_grant(ctx.engine.events, target.entity_id)
    ctx.engine._grant_temp_hp(target, int(ctx.numbers['cl']), ctx.source, ctx.actor.entity_id)
    receipt = held_grant(ctx.engine.events, target.entity_id)
    if receipt and receipt != before and receipt[0] == ctx.source:
        ctx.engine._apply_condition(target, POOL, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'meld_instance': meld.instance_id, 'grant_sequence': receipt[2],
                  'label': 'Shadowed Mien Temporary HP: end with this Meld; losing them does not end the shadow cloak'})


def sync_hp(engine):
    from .temp_hp_grants import held_grant
    from .condition_ownership import remove_instance
    for holder in engine.state.actors.values():
        for held in list(holder.conditions.values()):
            if held.condition_id != POOL:
                continue
            receipt = held_grant(engine.events, holder.entity_id)
            owns = bool(receipt and receipt[2] == held.data.get('grant_sequence') and holder.temporary_hp > 0)
            current = grant(engine, holder)
            live = bool(current and current.instance_id == held.data.get('meld_instance'))
            if owns and not live:
                before = holder.temporary_hp
                holder.temporary_hp = 0
                engine._append_event('TEMP_HP_GRANTED', held.source_definition_id, actor_id=held.source_actor_id,
                    target_ids=(holder.entity_id,), payload={'offered': 0, 'before': before, 'after': 0,
                        'removed_by': 'Shadowed Mien ended'})
            if not owns or not live:
                remove_instance(engine, holder, held.instance_id, held.source_definition_id)


@hook('event', nested=True)
def ending(engine, event_type, kwargs):
    if event_type in ('CONDITION_REMOVED', 'CONCENTRATION_ENDED', 'TEMP_HP_GRANTED', 'DAMAGE_COMMITTED'):
        sync_hp(engine)


@hook('turn_start')
def expiry(engine, actor):
    sync_hp(engine)


@hook('status_description')
def status(engine, holder, row, data):
    from .. import senses
    if row.get('condition_id') == senses.MELD and data.get('talent') == MIEN:
        return {'text': 'Shadowed Mien cloaks your appearance, subtle movements and intentions while you see outward normally. '
            'You have Advantage on Deception and Intimidation; an observer has Disadvantage on Insight to discern your intentions. '
            'Clearsight or sight through supernatural Darkness reveals you and removes these benefits for that observer. '
            'Ordinary Darkvision does not penetrate this cloak. Lasts up to 1 hour'
            + (' while the caster keeps Concentration.' if data.get('concentration') else ' without Concentration.'),
            'source_ability': 'Shadowed Mien'}
    if row.get('condition_id') == POOL:
        return {'text': 'The optional Shadowed Mien augment costs 1 cultivation point and grants Temporary HP equal to the caster’s Cultivation Level. '
            'These HP end with this Meld; losing them does not end the cloak.', 'source_ability': 'Shadowed Mien'}
    return None
