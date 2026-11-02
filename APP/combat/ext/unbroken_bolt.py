"""Body of the Unbroken Bolt's missed-melee-attack Charge, for all attack paths.

The shared normal gain limit is read from the event journal, so it survives a
reload and also counts gains from other normal generators. Bone's exceptional
gain does not consume that limit. No marker, patch or extra state is needed.
"""
from copy import deepcopy

from . import effect, hook

PREFIX = 'tianxia.subpath.body.adamant_thunderbolt_body.feature.'
FEATURE = PREFIX + 'body_of_the_unbroken_bolt'
BONE = PREFIX + 'thunder_runs_through_bone'
POOL = 'resource:named.thunder_charge'
PENDING = 'condition:typed.adamant_bone_pending'
AFTERGLOW = 'condition:typed.adamant_descent_resistance'
DESCENT = PREFIX + 'adamantine_descent'
BODY = 'tianxia.path.body_refining'
STAMINA_GUARD = BODY + '.feature.stamina_guard'


@hook('compile_bundle')
def family_profile(bundle, info):
    """Consume the owning-Path contract; never borrow another Path's level/PB."""
    from .path_profiles import path_numbers
    rows = [*bundle.get('typed_passives', []), *bundle.get('typed_reactions', [])]
    sources = [str(r.get('feature_id') or '').removeprefix('reaction:typed.') for r in rows]
    sources += [str((a.get('parameters', {}).get('typed') or {}).get('source') or '')
                for a in bundle.get('action_catalog', [])]
    owned = next((source for source in sources if source.startswith(PREFIX)), None)
    if owned is None:
        return bundle
    numbers = path_numbers(info, BODY)
    for row in rows:
        if str(row.get('feature_id') or '').removeprefix('reaction:typed.').startswith(PREFIX):
            row.update(cl=int(numbers['cl']), pb=int(numbers['pb']))
            if 'numbers' in row:
                row['numbers'] = {**row['numbers'], **numbers}
    for action in bundle.get('action_catalog', []):
        typed = action.get('parameters', {}).get('typed') or {}
        if str(typed.get('source') or '').startswith(PREFIX):
            typed['numbers'] = {**typed.get('numbers', {}), **numbers}
    for pool in bundle['actor_template']['resources']:
        if pool['resource_id'] == POOL:
            pool['maximum'] = int(numbers['pb'])
            pool['initial'] = min(int(pool['initial']), pool['maximum'])
    # One profile row per bundle, however many times a transform re-runs compile_bundle:
    # charge_limit reads it, so a duplicate would keep a stale Proficiency Bonus.
    profile = {'block': 'adamant_thunderbolt_profile', 'feature_id': owned,
               'cl': int(numbers['cl']), 'pb': int(numbers['pb'])}
    passes = bundle['typed_passives']
    for index, row in enumerate(passes):
        if row.get('block') == 'adamant_thunderbolt_profile':
            passes[index] = profile
            break
    else:
        passes.append(profile)
    return bundle


def owns(engine, actor):
    return any(row.get('feature_id') == FEATURE and int(row.get('cl') or (row.get('numbers') or {}).get('cl') or 0) >= 14
               for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, []))


def owns_family(engine, actor):
    """A compiled member grants the common pool before the CL14 miss producer."""
    return any(str(row.get('feature_id') or '').startswith(PREFIX)
               for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, [])) or any(
        action.owner_id == actor.entity_id and str((action.parameters.get('typed') or {}).get('source') or '').startswith(PREFIX)
        for action in engine.action_catalog.values()) or any(
        str(row.get('feature_id') or '').removeprefix('reaction:typed.').startswith(PREFIX)
        for row in getattr(engine, 'typed_reaction_rows', {}).get(actor.entity_id, []))


def exceptional(source):
    return source in (BONE, 'reaction:' + BONE, 'reaction:typed.' + BONE)


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
    if resource_id != POOL or amount <= 0 or not owns_family(engine, actor):
        return None
    profile = next((r for r in engine.typed_passive_rows.get(actor.entity_id, [])
                    if r.get('block') == 'adamant_thunderbolt_profile'), None)
    if profile is not None and profile['cl'] < 3:
        return False
    # Older bundles can have an unbounded maximum. Preserve their held Charges,
    # but do not allow the newly implemented generator to exceed the printed cap.
    if actor.resources.get(POOL, 0) >= (profile['pb'] if profile else actor.proficiency_bonus):
        return False
    if source_id == STAMINA_GUARD:
        if not _stamina_guard_reduced(engine, actor, profile['pb'] if profile else actor.proficiency_bonus):
            return False
    if not exceptional(source_id) and normal_gain_used(engine, actor):
        return False
    return None


def _stamina_guard_reduced(engine, actor, pb):
    """Whether Stamina Guard's own receipt for this packet cut it by at least ``pb``.

    The reduction and this gain are separate events, so anything the engine journals
    in between (a damage-defended notice, a follow-up) must not hide the receipt:
    read it inside this packet's window instead of trusting the last event.
    """
    from ..pending_damage import current
    packet = current(engine)
    window = next((event for event in reversed(engine.events)
                   if event.event_type == 'REACTION_WINDOW_OPENED'
                   and event.payload.get('checkpoint') == 'DAMAGE_APPLICATION'
                   and actor.entity_id in (event.target_ids or ())), None)
    if packet is None or not packet.hostile or window is None:
        return False
    for event in reversed(engine.events):
        if event.sequence <= window.sequence:
            break
        if (event.event_type == 'REACTION_RESOLVED' and event.actor_id == actor.entity_id
                and event.source_definition_id == STAMINA_GUARD):
            return int(event.payload.get('pending_before') or 0) - int(event.payload.get('pending_after') or 0) >= pb
    return False


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
    # Query current native reach, including dynamic grants, independently of
    # whether the defender has a Reaction left.
    from ..typed_reactions import attack_reaches
    if not attack_reaches(engine, target, attacker, {'type': 'attack', 'attack_kind': 'unarmed'}):
        return
    if charge_limit(engine, target, POOL, 1, FEATURE) is False:
        return
    engine._gain_resource(target, POOL, 1, FEATURE)


@hook('reaction_rows')
def bone_settlement(engine, actor_id, block, rows):
    """Defer this family's zero-damage follow-up until HP application settles."""
    if not any(exceptional(row.get('feature_id')) for row in rows):
        return None
    result = deepcopy(rows)
    for row in result:
        if not exceptional(row.get('feature_id')):
            continue
        effects = row.get('effects') or []
        if any(e.get('only_if_zero') for e in effects):
            row['effects'] = [e for e in effects if not e.get('only_if_zero')] + [
                {'type': 'adamant_bone_pending'}]
    return result


@effect('adamant_bone_pending')
def bone_pending(ctx, row):
    window = next((e for e in reversed(ctx.engine.events)
        if e.event_type == 'REACTION_WINDOW_OPENED' and ctx.actor.entity_id in e.target_ids
        and e.payload.get('checkpoint') == 'DAMAGE_APPLICATION'), None)
    if window is None:
        return
    ctx.engine._apply_condition(ctx.actor, PENDING, BONE, ctx.actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'window': window.sequence,
            'attacker': window.actor_id or '', 'source': window.source_definition_id,
            'label': 'Thunder Runs Through Bone: waiting for this damage to resolve'})


@hook('state_event')
def bone_settled(engine, event):
    if event.event_type != 'DAMAGE_COMMITTED':
        return
    kwargs = {'actor_id': event.actor_id, 'target_ids': event.target_ids,
              'source_definition_id': event.source_definition_id, 'payload': event.payload}
    from ..typed_reactions import triggered_context
    from ..typed_executor import run_effects
    from .path_riders import remove_held
    from .thunder_charges import gain

    payload = kwargs.get('payload') or {}
    for target_id in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(target_id)
        if actor is None:
            continue
        held = next((c for c in actor.conditions.values() if c.condition_id == PENDING
            and c.data['source'] == event.source_definition_id
            and c.data['attacker'] == (kwargs.get('actor_id') or '')), None)
        if held is None:
            continue
        qualifying = any(e.sequence > held.data['window'] and e.event_type == 'REACTION_RESOLVED'
            and e.actor_id == target_id and exceptional(e.source_definition_id)
            and int(e.payload.get('reduction') or 0) > 0 for e in engine.events)
        remove_held(engine, actor, held)
        if not qualifying or int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0):
            continue
        gain(engine, actor, BONE, normal=False)
        row = next((r for r in engine.typed_reaction_rows.get(target_id, []) if exceptional(r.get('feature_id'))), None)
        if row is None:
            continue
        ctx = triggered_context(engine, actor, engine.state.actors.get(kwargs.get('actor_id')), row,
                                getattr(engine, '_active_intent', None))
        run_effects(ctx, [{'type': 'path_reaction_step', 'distance_ft': 10},
                          {'type': 'path_unarmed_advantage'}])


@effect('adamant_descent_resistance')
def descent_resistance(ctx, row):
    ctx.engine._apply_condition(ctx.actor, AFTERGLOW, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN', data={
            'label': 'Adamantine Descent: Resistance to damage except Psychic and Void until your next turn'})


@effect('adamant_descent_declare')
def descent_declare(ctx, row):
    from .needle import ask, checkpoint_id
    from .pool_spend import spent_units
    choice = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'adamant_descent_type', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.adamant_descent_type', ['FORCE', 'THUNDER'],
        labels={'FORCE': 'Force', 'THUNDER': 'Thunder'},
        prompt=f"Adamantine Descent: {ctx.actor.display_name}, all {spent_units(ctx)} "
               'Thunder Charges have been spent. Choose Force or Thunder damage for this impact.')
    ctx.damage_cache['_adamant_descent_damage_type'] = choice[0]


@hook('damage_type_override')
def descent_damage_type(ctx, kinds, targets):
    chosen = ctx.damage_cache.get('_adamant_descent_damage_type')
    return chosen if ctx.typed.get('source') == DESCENT and chosen in kinds else None


@hook('damage_defenses')
def descent_defenses(engine, actor, damage_type, typed, source_actor_id):
    if str(damage_type).upper() not in ('PSYCHIC', 'VOID') and any(
            c.condition_id == AFTERGLOW for c in actor.conditions.values()):
        return [{'kind': 'resistance', 'damage_types': [str(damage_type).upper()]}]
    return None


@hook('repeat_save_final')
def charge_after_repeat_save(engine, resolution):
    actor = engine.state.actors.get(resolution['holder_id'])
    source = engine.state.actors.get(resolution.get('source_actor_id'))
    if (actor is None or source is None or not owns_family(engine, actor)
            or source.team_id == actor.team_id or not resolution['success']
            or str(resolution['ability']).upper() not in ('STR', 'CON')):
        return
    from .thunder_charges import gain
    gain(engine, actor, 'system:subpath_pool')


@hook('object_hit')
def charge_after_object_hit(ctx, target, kind):
    if not owns_family(ctx.engine, ctx.actor):
        return
    from .subpath_pools import moved_on_foot
    from .thunder_charges import gain
    if moved_on_foot(ctx.engine, ctx.actor, current_turn=True) >= 10:
        gain(ctx.engine, ctx.actor, 'system:subpath_pool')


@hook('journey_state_changed')
def scene_ended(session, actor_id):
    """Consume the existing explicit scene finish, never combat entry or rest."""
    if session.state['phase'] != 'finished':
        return
    actor = session.state['actors'][actor_id]
    bundle = actor['bundle']
    if not any(r.get('block') == 'adamant_thunderbolt_profile' for r in bundle.get('typed_passives', [])):
        return
    lost = int(actor['resources'].get(POOL, 0))
    actor['resources'][POOL] = 0
    refreshed = 0
    for action in bundle.get('action_catalog', []):
        if (action.get('parameters', {}).get('typed') or {}).get('source') != DESCENT:
            continue
        for resource, amount in action.get('costs') or []:
            if resource.startswith('resource:uses.'):
                actor['resources'][resource] = 1
                refreshed = 1
    session.emit('ADAMANT_THUNDERBOLT_SCENE_ENDED', actor_id, lost_charges=lost,
        refreshed_descent=refreshed,
        text=f"{actor['name']}: unused Thunder Charges end with this scene."
             + (" Adamantine Descent's scene use refreshes." if refreshed else ''))
