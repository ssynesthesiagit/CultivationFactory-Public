"""Source-owned Sumo queries shared by sumo and sumo_native.

Contact derives from native floor/roof/column or a current physical climbing
hold; a carried creature has no independent support. No narration or creature
name establishes contact. Counts-as size never changes occupied geometry.
"""
PREFIX = 'tianxia.subpath.body.sumo.feature.'
ROOTED = 'condition:typed.stance.rooted_stance'
DECLINED = 'condition:typed.sumo_rooting_declined'
LEVELS = dict(zip(('rooted_stance','sumo_strike','ring_breaker','yokozuna_presence','immovable_god'), (3,6,10,14,18)))


def level(engine, actor):
    from .ext.ability_source import numbers_of
    return int(numbers_of(engine, actor).get('cl') or 0)


def owns(engine, actor, slug):
    if actor is None or level(engine, actor) < LEVELS[slug]:
        return False
    feature = PREFIX + slug
    return any((a.parameters.get('typed') or {}).get('source') == feature
               or (a.parameters.get('typed') or {}).get('option_of') == feature
               for a in engine.action_catalog.values() if a.owner_id == actor.entity_id) or any(
        r.get('feature_id') == feature for r in (getattr(engine,'typed_passive_rows',{}) or {}).get(actor.entity_id,()))


def conscious(actor):
    return actor.active and actor.current_hp > 0 and not any(
        c.condition_id in ('condition:typed.unconscious','condition:core.unconscious') for c in actor.conditions.values())


def touching(engine, actor):
    if any((c.data or {}).get('carried_by') or (c.data or {}).get('mounted_on') for c in actor.conditions.values()):
        return False
    from .falling import supported
    if supported(engine, actor):
        return True
    from .roof_movement import can_hold
    return bool(can_hold(engine, actor))


def rooted(engine, actor):
    return actor is not None and owns(engine,actor,'rooted_stance') and conscious(actor) and touching(engine,actor) and any(
        c.condition_id == ROOTED for c in actor.conditions.values())
