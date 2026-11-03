"""Recipient Melds, Blindfold's sense band and Feed on Darkness.

Uses sense_rows/sense_range_divisor (pure), turn_start/nominal_slot_boundary,
movement_step and event hooks. Stored clocks and grant identities are primitives.
A Feed pool belongs to its accepted TEMP_HP_GRANTED receipt, never its last offer.
Departure starts one full round; returning before expiry cancels that clock.
"""
from typing import Any

from . import hook

FEED = 'TAL_DARK_FEED_ON_DARKNESS'
DARKVISION = 'TAL_DARK_DARKVISION'
BLINDFOLD = 'TAL_DARK_BLINDFOLD'
POOL = 'condition:typed.dark_feed_pool'


def _markers(engine, actor):
    from .. import senses, concentration
    from .effect_durations import due
    return [c for c in actor.conditions.values() if c.condition_id == senses.MELD
            and not due(engine, c.data.get('end_clock'))
            and (not c.data.get('concentration') or concentration.concentrating_on(
                engine.state.actors.get(c.data.get('caster_id'), actor), c.data.get('source')))]


@hook('sense_rows')
def meld_sense_rows(engine: Any, actor: Any, rows: list[dict]) -> list[dict] | None:
    """Substitute the active granted Darkvision, preserving ordinary independent senses."""
    grants = [c for c in _markers(engine, actor) if c.data.get('talent') == DARKVISION]
    if not grants:
        return None
    enhanced = any(c.data.get('enhanced_darkvision') for c in grants)
    # Re-granting the same Meld replaces it; a pre-fight Meld is not an extra stacking sense.
    result = [dict(r) for r in rows if r.get('feature_id') != DARKVISION]
    result.append({'sense': 'darkvision', 'range_ft': 120 if enhanced else 60,
                   'or_add_ft': 60 if enhanced else 30, 'when': 'active'})
    return result


@hook('sense_range_divisor')
def blindfold_sense_divisor(engine: Any, actor: Any, sense: str) -> int | None:
    from .ability_source import mechanic_of
    for c in actor.conditions.values():
        action = engine.action_catalog.get(c.source_definition_id)
        if c.condition_id == 'condition:typed.blinded' and action is not None and mechanic_of(action) == BLINDFOLD:
            return 2
    return None


def _inside(engine, holder, caster_id):
    from .. import zones
    return any(z.owner_id == caster_id and (z.trigger_profile.get('visual') or {}).get('darkness')
               and zones._inside(engine, holder, z) for z in zones.typed_zones(engine))


def _drop(engine, actor, key, condition):
    actor.conditions.pop(key, None)
    engine._append_event('CONDITION_REMOVED', condition.source_definition_id,
                         actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                         payload={'condition_id': condition.condition_id, 'instance_id': key, 'reason': 'ENDED'})


def _sync_pools(engine):
    from .effect_durations import due, round_token
    from .temp_hp_grants import held_grant
    for actor in engine.state.actors.values():
        for key, c in list(actor.conditions.items()):
            if c.condition_id != POOL:
                continue
            grant = held_grant(engine.events, actor.entity_id)
            if not grant or grant[2] != c.data.get('grant_sequence') or actor.temporary_hp <= 0:
                _drop(engine, actor, key, c)
                continue
            inside = _inside(engine, actor, c.data.get('caster_id'))
            data = dict(c.data)
            if inside and data.get('left_clock'):
                data.pop('left_clock')
            elif not inside and not data.get('left_clock'):
                data['left_clock'] = round_token(engine, 1)
            if data != c.data:
                # A changed condition is a recorded replacement, so Gate 3 and
                # a cold service reload observe the same primitive clock.
                _drop(engine, actor, key, c)
                engine._apply_condition(actor, POOL, c.source_definition_id, c.source_actor_id,
                                        expires_on='UNTIL_REMOVED', data=data)
            elif not inside and due(engine, c.data.get('left_clock')):
                before = actor.temporary_hp
                actor.temporary_hp = 0
                engine._append_event('TEMP_HP_GRANTED', c.source_definition_id,
                                     actor_id=c.source_actor_id, target_ids=(actor.entity_id,),
                                     payload={'offered': 0, 'before': before, 'after': 0,
                                              'removed_by': 'Feed on Darkness: one round outside your Darkness'})
                _drop(engine, actor, key, c)


@hook('movement_step')
def feed_departure(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> None:
    _sync_pools(engine)


@hook('event', nested=True)
def feed_area_change(engine: Any, event_type: str, kwargs: dict) -> None:
    if event_type in ('ZONE_REMOVED', 'ZONE_CREATED', 'ZONE_EXPIRED', 'MOVEMENT_COMMITTED'):
        _sync_pools(engine)


@hook('nominal_slot_boundary')
def meld_clocks(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint != 'START_OF_TURN':
        return
    from .. import senses
    from .effect_durations import due
    for holder in engine.state.actors.values():
        for key, c in list(holder.conditions.items()):
            if c.condition_id == senses.MELD and due(engine, c.data.get('end_clock')):
                _drop(engine, holder, key, c)
    _sync_pools(engine)


@hook('turn_start')
def feed_turn(engine: Any, actor: Any) -> None:
    from .temp_hp_grants import held_grant
    meld_clocks(engine, actor, 'START_OF_TURN')
    for c in _markers(engine, actor):
        if c.data.get('talent') != FEED or not _inside(engine, actor, c.data.get('caster_id')):
            continue
        engine._grant_temp_hp(actor, max(0, int((c.data.get('numbers') or {}).get('key_mod') or 0)),
                              c.source_definition_id, c.source_actor_id)
        grant = held_grant(engine.events, actor.entity_id)
        if not grant or grant[0] != c.source_definition_id or actor.temporary_hp <= 0:
            continue
        for key, old in list(actor.conditions.items()):
            if old.condition_id == POOL:
                _drop(engine, actor, key, old)
        engine._apply_condition(actor, POOL, c.source_definition_id, c.source_actor_id,
                                expires_on='UNTIL_REMOVED', data={'caster_id': c.data.get('caster_id'),
                                    'grant_sequence': grant[2], 'label': 'Feed on Darkness: Temporary HP'})
