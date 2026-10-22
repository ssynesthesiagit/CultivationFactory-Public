"""Source-owned Saber-Line Pressure profiles and guard-wrap declarations.

The printed method names ordinary saber profiles and assigns ambiguous weapons
to the GM. A guard wrap is a declared blade movement around a guard, not a hit,
an armor bypass or a granted attack. Typed GM inputs bind those subjective facts
to actual possessions and one actor/action/target/turn; native attacks still
own legality, payment, rolls and Pressure's once-turn benefit.
"""
from . import hook, run_strict

SOURCE = 'tianxia.sphere.sabers'
OWNER = 'SABERS_BASE_SABER_LINE_PRESSURE'
PROFILE = 'saber_profile'
WRAP = 'guard_wrap'
STANDARD = frozenset(('tianxia.mortal.weapon.dao', 'tianxia.mortal.weapon.duan_dao',
    'tianxia.mortal.weapon.hu_die_dao'))


def owns(engine, actor):
    from .ability_source import compiled_feature_rows
    return any(row.get('block') == 'saber_line_pressure'
        for row in compiled_feature_rows(engine, actor.entity_id, OWNER))


def qualifies(ctx, kind):
    """Actual personal physical profile, or an explicit owned feature exception."""
    if not owns(ctx.engine, ctx.actor):
        return False
    exceptions = run_strict('saber_pressure_attack_exception', ctx, kind)
    if any(type(value) is not bool for value in exceptions):
        raise ValueError('Saber Pressure attack exceptions return bool or None.')
    if True in exceptions:
        return True
    if (kind != 'weapon' or getattr(ctx.actor, 'owner_id', None) not in (None, '', ctx.actor.entity_id)
            or ctx.typed.get('sphere') == 'tianxia.sphere.formations'):
        return False
    from ..item_use_checkpoint import attack_item
    from .weapon_hits import weapon_item, weapon_identity
    from .hand_occupancy import weapon_allowed
    item = attack_item(ctx)
    weapon = ctx.engine.action_catalog.get(weapon_identity(ctx))
    if item is None or weapon is None or weapon_allowed(ctx.engine, ctx.actor, weapon) is False:
        return False
    if weapon_item(ctx).get('item_id') in STANDARD:
        return True
    from ..fact_consent_admission import combat_records
    return any(record['subject'] == ctx.actor.entity_id and record.get('authority') == 'table_owner'
        and record['value']['classification'] == 'qualifying_saber'
        and record['value']['weapon_source_id'] == weapon.source_definition_id
        for record in combat_records(ctx.engine, ctx.actor, source=SOURCE, kind=PROFILE, scope=item['object']))


def wrap_scope(source, target_id, turn):
    return source + '|' + target_id + '|' + str(turn)


def delivery_identity(ctx):
    from ..item_use_checkpoint import attack_item
    item = attack_item(ctx)
    return item['object'] if item is not None else ctx.actor.entity_id


def wrapped(ctx, target):
    """A current exact-action/target/item/turn declaration, after a real hit."""
    from ..fact_consent_admission import combat_records
    scope = wrap_scope(ctx.action.source_definition_id, target.entity_id, ctx.actor.turns_started)
    return any(record['subject'] == ctx.actor.entity_id and record.get('authority') == 'table_owner'
        and record['value']['adjudication'] == 'cuts_around_guard'
        and record['value']['delivery_identity'] == delivery_identity(ctx)
        for record in combat_records(ctx.engine, ctx.actor, source=SOURCE, kind=WRAP, scope=scope))


@hook('fact_admission_schema')
def schema(context, source, subject, kind):
    if source != SOURCE or kind not in (PROFILE, WRAP):
        return None
    if not getattr(context, 'is_combat_fact_context', False):
        return None
    actor = context.engine.state.actors.get(subject)
    if actor is None or not owns(context.engine, actor):
        return None
    return {'value_type': 'document', 'authority': 'table_owner', 'combat': True,
        'validate_value': True, 'maximum_seconds': 6 if kind == WRAP else 86400,
        'description': ('Saber-Line Pressure: identify an actual carried weapon and record whether the GM '
            'classifies its ambiguous curved/chopping profile as a qualifying saber.' if kind == PROFILE else
            'Saber-Line Pressure: describe this turn’s actual saber attack carrying the blade around the '
            'target’s guard and returning through the opening. Record the GM’s choreography ruling. '
            'The declaration costs no Action or resource; the actual attack keeps its normal costs and roll.')}


@hook('fact_admission_value')
def value(context, payload):
    if payload.get('source') != SOURCE or payload.get('kind') not in (PROFILE, WRAP):
        return None
    if not getattr(context, 'is_combat_fact_context', False):
        return False
    engine = context.engine
    actor = engine.state.actors.get(payload.get('subject'))
    data = payload.get('value')
    if actor is None or not owns(engine, actor) or not isinstance(data, dict):
        return False
    if payload['kind'] == PROFILE:
        if (set(data) != {'item_identity', 'weapon_source_id', 'classification', 'basis'}
                or data.get('classification') not in ('qualifying_saber', 'other_weapon')
                or type(data.get('basis')) is not str or not 1 <= len(data['basis'].strip()) <= 1000
                or payload.get('scope') != data.get('item_identity')):
            return False
        from ..item_use_checkpoint import possessions
        from .weapon_hits import weapon_item
        from ..typed_executor import Context
        action = engine.action_catalog.get(data.get('weapon_source_id'))
        if action is None:
            return False
        ctx = Context(engine, actor, action, None, action.parameters.get('typed') or {}, [], None)
        if weapon_item(ctx).get('item_id') in STANDARD:
            return False  # Printed standard profiles need no ambiguous-weapon ruling.
        return any(item['object'] == data.get('item_identity')
            and item.get('weapon_action') == action.source_definition_id
            for item in possessions(engine, actor))
    if (set(data) != {'attack_source_id', 'target_id', 'delivery_identity', 'turn', 'description', 'adjudication'}
            or data.get('adjudication') not in ('cuts_around_guard', 'does_not_cut_around_guard')
            or type(data.get('description')) is not str or not 1 <= len(data['description'].strip()) <= 1000
            or type(data.get('turn')) is not int or data['turn'] != actor.turns_started
            or engine.state.current_actor_id != actor.entity_id):
        return False
    target = engine.state.actors.get(data.get('target_id'))
    action = engine.action_catalog.get(data.get('attack_source_id'))
    if (target is None or not target.active or action is None or action.owner_id != actor.entity_id
            or payload.get('scope') != wrap_scope(action.source_definition_id, target.entity_id, actor.turns_started)):
        return False
    typed = action.parameters.get('typed') or {}
    attack = next((row for row in typed.get('effects', ()) if row.get('type') == 'attack'), None)
    if attack is None:
        return False
    from ..typed_executor import Context
    from ..weapon_delivery import delivery_kind
    from ..attack_declaration import can_target
    ctx = Context(engine, actor, action, None, typed, [target], target)
    kind = delivery_kind(typed, attack, action.parameters)
    return (qualifies(ctx, kind) and data.get('delivery_identity') == delivery_identity(ctx)
        and can_target(engine, actor, target, action.source_definition_id, action=action, effect=attack))
