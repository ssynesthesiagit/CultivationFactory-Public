"""Shared Saber Wound ledger and its printed Medicine Action.

Saber-Line Pressure and other Sabers providers call apply_wound after their own
actual trigger and owner choice. A wound grants no damage, vulnerability or
blood control. Each creator has a separate two-wound cap on each creature.
"""
from . import effect, hook

PREFIX = 'condition:typed.sabers.wound:'
TREAT = 'system:combat.treat_saber_wound'
BIND = 'system:combat.bind_saber_wound'
SOURCE = 'tianxia.sphere.sabers'
TOOLS = 'wound_binding_tools'


def wounds(actor):
    """Actual retained wounds; declarations and ordinary injuries grant none."""
    return [c for c in actor.conditions.values() if c.condition_id.startswith(PREFIX)
        and type(c.data.get('count')) is int and 1 <= c.data['count'] <= 2]


def apply_wound(ctx, target):
    """Add one wound from this source owner, capped at two, with its actual DC."""
    owner = ctx.actor
    condition_id = PREFIX + owner.entity_id
    old = next((c for c in wounds(target) if c.condition_id == condition_id), None)
    count = min(2, 1 + (old.data['count'] if old else 0))
    if old and count == old.data['count']:
        return
    data = {'count': count, 'save_dc': int(ctx.numbers['save_dc']),
        'label': f'{count} Saber Wound' + ('s' if count > 1 else '')
            + ': qi-aggravated slashes. Magical healing, a successful Medicine Action, '
              'or an Action binding with GM-approved tools removes one. No damage by itself.'}
    if old:
        from .retained_updates import record_instance_update
        old.data.update(data)
        record_instance_update(ctx.engine, target, 'condition', old.instance_id, old)
    else:
        ctx.engine._apply_condition(target, condition_id, ctx.source, owner.entity_id,
            expires_on='UNTIL_REMOVED', data=data)


def remove_one(engine, actor, wound, source):
    """Remove exactly one retained wound, preserving any second wound."""
    if wound not in wounds(actor):
        raise ValueError('Choose a current Saber Wound.')
    if wound.data['count'] == 1:
        engine._remove_condition_instance(actor, wound.instance_id, source)
    else:
        from .retained_updates import record_instance_update
        wound.data['count'] = 1
        wound.data['label'] = '1 Saber Wound: qi-aggravated slash; no damage by itself.'
        record_instance_update(engine, actor, 'condition', wound.instance_id, wound)


def medicine_bonus(engine, actor):
    from ..ability_checks import ordinary_check_bonus
    return ordinary_check_bonus(engine, actor, 'WIS', 'Medicine')


@hook('match_start')
def treatment_action(engine):
    if not any(row.get('block') == 'saber_line_pressure'
            for rows in engine.typed_passive_rows.values() for row in rows):
        return
    from ..gate2_runtime_models import ActionDefinition
    engine.action_catalog[TREAT] = ActionDefinition(source_definition_id=TREAT,
        display_name='Treat one Saber Wound (Medicine Action)', owner_id='*',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'effects': [{'type': 'saber_wound_medicine'}], 'numbers': {}, 'riders': []},
            'description': 'Use your Action to make a Wisdom (Medicine) check against the wound creator’s '
                'Sabers save DC. Success removes one of your Saber Wounds. No Qi or Stamina cost.'})
    engine.action_catalog[BIND] = ActionDefinition(source_definition_id=BIND,
        display_name='Bind one Saber Wound (approved tools, Action)', owner_id='*',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'effects': [{'type': 'saber_wound_bind'}], 'numbers': {}, 'riders': []},
            'description': 'Use your Action and one of your tools the GM has judged appropriate for binding '
                'these slashes. Remove one of your Saber Wounds. No check or Qi/Stamina cost.'})


@hook('additional_actions')
def offer_treatment(engine, actor):
    if not wounds(actor):
        return []
    return ([TREAT] if TREAT in engine.action_catalog and medicine_bonus(engine, actor) is not None else []) + (
        [BIND] if BIND in engine.action_catalog and approved_tools(engine, actor) else [])


@hook('candidate_allowed')
def treatment_allowed(engine, actor, candidate, action):
    if action is not None and action.source_definition_id == TREAT:
        return bool(wounds(actor)) and medicine_bonus(engine, actor) is not None
    if action is not None and action.source_definition_id == BIND:
        return bool(wounds(actor)) and bool(approved_tools(engine, actor))
    return None


@hook('fact_admission_schema')
def binding_schema(context, source, subject, kind):
    if source != SOURCE or kind != TOOLS:
        return None
    actor = context.engine.state.actors.get(subject) if getattr(context, 'is_combat_fact_context', False) else None
    if actor is None or not wounds(actor):
        return None
    return {'value_type': 'document', 'authority': 'table_owner', 'combat': True,
        'validate_value': True, 'maximum_seconds': 86400,
        'description': 'Saber Wound: identify an actual carried tool and whether the GM permits using it '
            'to bind these qi-aggravated slashes. This permission does not perform treatment or grant tools.'}


@hook('fact_admission_value')
def binding_value(context, payload):
    if payload.get('source') != SOURCE or payload.get('kind') != TOOLS:
        return None
    if not getattr(context, 'is_combat_fact_context', False):
        return False
    from ..item_uses import possessions
    actor = context.engine.state.actors.get(payload.get('subject'))
    value = payload.get('value')
    return (actor is not None and bool(wounds(actor)) and isinstance(value, dict)
        and set(value) == {'item_identity', 'purpose', 'permitted'}
        and type(value['item_identity']) is str and payload.get('scope') == value['item_identity']
        and value['purpose'] == 'bind_saber_wound' and type(value['permitted']) is int
        and value['permitted'] in (0, 1)
        and any(item['object'] == value['item_identity'] for item in possessions(context.engine, actor)))


def approved_tools(engine, actor):
    """Latest, live, private GM permission for the actor's actual tool identities."""
    from ..fact_consent_admission import combat_records
    from ..item_uses import possessions
    allowed = {record['value']['item_identity'] for record in combat_records(engine, actor, source=SOURCE, kind=TOOLS)
        if record['subject'] == actor.entity_id and record.get('authority') == 'table_owner'
        and record['value']['permitted'] == 1 and record['value']['purpose'] == 'bind_saber_wound'}
    return [item for item in possessions(engine, actor) if item['object'] in allowed]


@effect('saber_wound_bind')
def bind_wound(ctx, row):
    from .needle import ask, checkpoint_id
    from ..item_uses import resolve
    tools, pool = approved_tools(ctx.engine, ctx.actor), wounds(ctx.actor)
    if not tools or not pool:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SABER_WOUND_TOOLS', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.saber_wound_tools', [item['object'] for item in tools],
        labels={item['object']: 'Bind the slash with ' + str(item.get('name') or 'your approved tools') for item in tools},
        preferred=[tools[0]['object']], name='Bind a Saber Wound',
        prompt='Bind a Saber Wound: choose your GM-approved tools. Spend your Action to remove one wound; '
            'no check or Qi/Stamina cost.')
    if not selected:
        return
    wound_ids = [c.instance_id for c in pool]
    wound = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SABER_WOUND_BIND', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.saber_wound_bind', wound_ids,
        labels={c.instance_id: f'Wound group {i + 1}: bind one of its {c.data["count"]} slashes'
            for i, c in enumerate(pool)}, preferred=wound_ids[:1], name='Bind a Saber Wound',
        prompt='Choose one Saber Wound to bind with your approved tools. This uses the same Action.')
    if wound:
        target = next(c for c in pool if c.instance_id == wound[0])
        resolve(ctx, selected[0], 'bind_saber_wound',
            lambda item: remove_one(ctx.engine, ctx.actor, target, ctx.source))


@effect('saber_wound_medicine')
def treat(ctx, row):
    from .needle import ask, checkpoint_id
    from .escape_checks import resolve_escape_check
    pool = wounds(ctx.actor)
    bonus = medicine_bonus(ctx.engine, ctx.actor)
    if not pool or bonus is None:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SABER_WOUND_MEDICINE', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.saber_wound_medicine', [c.instance_id for c in pool],
        labels={c.instance_id: f'Wound group {i + 1}: remove one on a successful Medicine check (DC {c.data["save_dc"]})'
            for i, c in enumerate(pool)}, preferred=[pool[0].instance_id], name='Treat a Saber Wound',
        prompt='Treat a Saber Wound: choose one wound group. Spend your Action on a Wisdom (Medicine) check '
            'against its creator’s Sabers save DC; success removes one wound. No extra resource cost.')
    if not selected:
        return
    wound = next(c for c in pool if c.instance_id == selected[0])
    if resolve_escape_check(ctx, {'bonus': bonus}, wound.data['save_dc'], [],
            check_ability='WIS', check_skill='Medicine', check_name='Treat a Saber Wound',
            source_id=wound.source_definition_id, source_actor_id=wound.source_actor_id, escape_hooks=False):
        remove_one(ctx.engine, ctx.actor, wound, ctx.source)
