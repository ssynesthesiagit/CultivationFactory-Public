"""Tears Like Pearls: evented attack/harm exception without ending its charm.

Only sealed exception rows opt in. Repeat saves and the original deadline remain.
An explicit free declaration covers player commands the table cannot infer.
"""
from . import hook, effect
ID = 'tianxia.talent.beauty.tears_like_pearls'


def held_by(target, owner):
    return [(iid, c) for iid, c in target.conditions.items()
            if c.condition_id == 'condition:typed.charmed' and c.source_actor_id == owner.entity_id
            and c.data.get('beauty_tears_exception') == 1 and not c.data.get('allows_harming_source')]


def lift(engine, target, owner):
    for iid, held in held_by(target, owner):
        del target.conditions[iid]
        engine._append_event('CONDITION_REMOVED', held.source_definition_id, actor_id=owner.entity_id,
            target_ids=(target.entity_id,), payload={'instance_id': iid, 'condition_id': held.condition_id})
        engine._apply_condition(target, held.condition_id, held.source_definition_id, held.source_actor_id,
            expires_on=held.expires_on, data={**held.data, 'allows_harming_source': True})


@hook('event', nested=True)
def harm(engine, event_type, kwargs):
    if event_type not in ('ATTACK_ROLLED', 'ATTACK_FORCED_MISS', 'DAMAGE_COMMITTED'):
        return
    if event_type == 'DAMAGE_COMMITTED':
        p = kwargs.get('payload') or {}
        # The committed packet is the contract; temporary HP absorption still counts.
        if int(p.get('reduced_to') or 0) <= 0:
            return
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None:
        return
    for aid in kwargs.get('target_ids') or []:
        target = engine.state.actors.get(aid)
        if target:
            lift(engine, target, owner)


@hook('compile_actions')
def command_action(info):
    row = info['mechanics'].get(ID) or {}
    if ID not in info['owned_ids'] or not any(
            (e.get('condition_data') or {}).get('beauty_tears_exception') == 1
            for save in row.get('effects') or [] for e in save.get('on_fail') or []):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.beauty_tears_command_harm",
        display_name='Tears Like Pearls: command harm', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'player_only': True, 'expected_damage': 0,
        'description': 'Declare that you command harm against a creature Charmed by your Tears Like Pearls. It may then attack you; its charm and repeat saves continue. No action or CP cost.',
        'typed': {'source': ID, 'numbers': info['numbers'], 'effects': [{'type': 'beauty_tears_command'}],
                  'duration': {'kind': 'instant'}, 'riders': []}})]


@hook('candidate_allowed')
def command_available(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if not any(e.get('type') == 'beauty_tears_command' for e in typed.get('effects') or []):
        return None
    return None if any(held_by(a, actor) for a in engine.state.actors.values()) else False


@effect('beauty_tears_command')
def command(ctx, effect):
    from . import needle
    targets = [a for a in ctx.engine.state.actors.values() if held_by(a, ctx.actor)]
    ids = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'TEARS_COMMAND_HARM', ctx.source),
        ctx.actor, 'choice:needle.tears_command_harm', [a.entity_id for a in targets],
        labels={a.entity_id: a.display_name for a in targets}, automatic=False, allow_decline=True,
        name='Tears Like Pearls', prompt='Tears Like Pearls: whom did you command harm against? That creature may attack you; no action or CP cost.')
    for aid in ids:
        lift(ctx.engine, ctx.engine.state.actors[aid], ctx.actor)
