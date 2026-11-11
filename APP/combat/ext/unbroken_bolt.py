"""Body of the Unbroken Bolt's missed-melee-attack Charge, for all attack paths.

The shared normal gain limit is read from the event journal, so it survives a
reload and also counts gains from other normal generators. Bone's exceptional
gain does not consume that limit. No marker, patch or extra state is needed.
"""
from . import hook

PREFIX = 'tianxia.subpath.body.adamant_thunderbolt_body.feature.'
FEATURE = PREFIX + 'body_of_the_unbroken_bolt'
BONE = PREFIX + 'thunder_runs_through_bone'
POOL = 'resource:named.thunder_charge'


def owns(engine, actor):
    return any(row.get('feature_id') == FEATURE
               for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, []))


def exceptional(source):
    return source == BONE or source == 'reaction:' + BONE


def normal_gain_used(engine, actor):
    for event in reversed(engine.events):
        if event.event_type == 'ROUND_STARTED':
            break
        if (event.event_type == 'RESOURCE_GAINED' and event.actor_id == actor.entity_id
                and event.payload.get('resource_id') == POOL and event.payload.get('gained', 0) > 0
                and not exceptional(event.source_definition_id)):
            return True
    return False


@hook('resource_gain_allowed')
def charge_limit(engine, actor, resource_id, amount, source_id):
    if resource_id != POOL or amount <= 0 or not owns(engine, actor):
        return None
    # Older bundles can have an unbounded maximum. Preserve their held Charges,
    # but do not allow the newly implemented generator to exceed the printed cap.
    if actor.resources.get(POOL, 0) >= actor.proficiency_bonus:
        return False
    if not exceptional(source_id) and normal_gain_used(engine, actor):
        return False
    return None


@hook('after_miss')
def missed_melee(ctx, target):
    engine, attacker = ctx.engine, ctx.actor
    if (not target.active or not owns(engine, target) or attacker.team_id == target.team_id
            or POOL not in target.resources):
        return
    notice = ctx.attack_notice
    melee = notice.melee if notice is not None else not ctx.typed.get('range_ft')
    if not melee:
        return
    # Reach does not disappear when the defender has already spent its Reaction.
    rows = getattr(engine, 'typed_reaction_rows', {}).get(target.entity_id, [])
    reach = max([5, *(int(row.get('reach_ft') or 5) for row in rows if row.get('block') == 'opportunity')])
    if engine._distance_actor_to_actor(target, attacker) > reach:
        return
    if charge_limit(engine, target, POOL, 1, FEATURE) is False:
        return
    engine._gain_resource(target, POOL, 1, FEATURE)
