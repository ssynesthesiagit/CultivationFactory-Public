"""Pure creature-recipient contract for native menus and attack declaration queries.

Activation (economy, resources, readiness, available weapons) is deliberately a
separate question. Pair and other ability-specific restrictions live in plug-ins.
"""
from . import ext
from .relations import relation, ALLY, ENEMY
from .read_queries import pure


@pure
def allowed(engine, actor, target, action, *, allow_remembered=False):
    """Creature eligibility; candidate builders may explicitly bind a remembered aim.

    A rider's ordinary creature query never treats a remembered square as proof
    that the creature is there. Only a validated location candidate opts in.
    """
    from .target_knowledge import knowledge
    from .action_legality import deny, plugin_denial
    def reject(code, reason):
        deny(action.source_definition_id, code, reason, stage=1)
        return False
    for reply in ext.run_strict('target_eligibility', engine, actor, target, action):
        if type(reply) is not bool:
            raise ValueError('target_eligibility must return None or a boolean')
        if not reply:
            plugin_denial('target_unavailability', engine, actor, action, target)
            return False
    from .targeting import reason as targeting_reason
    denial = targeting_reason(engine, actor, target, action)
    if denial:
        return reject('TARGET_SIGHT_OR_EFFECT', denial)
    known = knowledge(engine, actor, target, action)
    if known is None:
        return reject('TARGET_UNKNOWN', 'No known eligible target is available for this action.')
    remembered = known.mode == 'LAST_OBSERVED'
    if (remembered and not allow_remembered) or (not target.active and not remembered):
        return reject('TARGET_INACTIVE', 'This action requires an active, currently observed target.')
    kind = action.target_kind
    hostile = kind in {'HOSTILE_ENTITY', 'HOSTILE_ENTITY_OR_SELF'}
    if hostile:
        if relation(engine, actor, target) != ENEMY and not (kind == 'HOSTILE_ENTITY_OR_SELF' and target is actor):
            return reject('TARGET_RELATION', 'This action requires an enemy target.')
    elif kind == 'ALLY_OR_SELF':
        if relation(engine, actor, target) != ALLY:
            return reject('TARGET_RELATION', 'This action requires you or an ally as its target.')
    elif kind == 'ANY_CREATURE':
        pass  # team-neutral printed creature domain; ordinary restrictions still apply
    elif kind in {'SELF', 'SELF_OR_CELL'}:
        if target is not actor:
            return reject('SELF_ONLY', 'This action affects only you.')
    else:
        return False  # cells, patterns and objects use their own targeting contracts
    from .targeting import in_range
    if not in_range(engine, actor, target, action, known):
        from .action_legality import explaining, range_reason
        plain = range_reason(engine, actor, action) if explaining() else None
        return reject('TARGET_RANGE', plain or 'No eligible target is within the action’s current reach or clear path.')
    harmful = hostile or action.parameters.get('harmful') is True
    if harmful and any(c.condition_id == 'condition:typed.charmed' and c.source_actor_id == target.entity_id
                       and (c.data or {}).get('allows_harming_source') is not True
                       for c in actor.conditions.values()):
        return reject('CHARMED', 'You cannot use this harmful action against the creature charming you.')
    needs = action.parameters.get('target_requires_condition')
    if needs and not engine._has_condition(target, needs):
        return reject('TARGET_CONDITION', 'The target does not have the effect required by this action.')
    if (action.parameters.get('typed') or {}).get('requires_hearing'):
        from .speech import can_hear_from
        if not can_hear_from(engine, actor, target, action.source_definition_id):
            return reject('TARGET_HEARING', 'This action requires a target that can hear it.')
    for reply in ext.run_strict('recipient_allowed', engine, actor, target, action):
        if type(reply) is not bool:
            raise ValueError('recipient_allowed must return None or a boolean')
        if not reply:
            plugin_denial('recipient_unavailability', engine, actor, action, target)
            return False
    return True
