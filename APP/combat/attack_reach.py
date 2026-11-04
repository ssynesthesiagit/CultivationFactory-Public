"""Pure condition-bound reach shared by native menus, attacks and reactions.

Providers implement attack_reach_bonus(engine, actor, action, opportunity).
Their required condition_id names an existing instance on actor; its source and
expiry govern the bonus. Same-source/group increases use max; independent
sources add. No catalog rewriting, query cache or new saved schema is needed.
"""
from . import ext


def melee(action):
    typed = action.parameters.get('typed') or {}
    attacks = [row for row in typed.get('effects') or [] if row.get('type') == 'attack']
    if attacks:
        return not any('ranged' in str(row.get('attack_kind')) or 'thrown' in str(row.get('attack_kind'))
                       for row in attacks) and not typed.get('range_ft')
    return action.resolution_kind == 'ATTACK' and action.range_ft is None


def bonus(engine, actor, action, *, opportunity=False):
    """Active additions, or zero without a provider; never writes state/events."""
    if not melee(action) or not ext.has('attack_reach_bonus'):
        return 0
    from .ext.effect_durations import due
    opportunity = opportunity or getattr(engine, '_typed_oa_attacker', None) == actor.entity_id
    groups = {}
    for row in ext.run_strict('attack_reach_bonus', engine, actor, action, opportunity):
        if not isinstance(row, dict) or set(row) - {'source_id', 'feet', 'condition_id', 'stacking_group'}:
            raise ValueError('attack_reach_bonus requires a condition-bound reach contribution')
        if type(row.get('feet')) is not int or row['feet'] < 0:
            raise ValueError('attack_reach_bonus feet must be a nonnegative integer')
        if any(not isinstance(row.get(k), str) or not row[k] for k in ('source_id', 'condition_id')):
            raise ValueError('attack_reach_bonus requires source and condition instance IDs')
        group = row.get('stacking_group', row['source_id'])
        if not isinstance(group, str) or not group:
            raise ValueError('attack_reach_bonus stacking_group must be a name')
        condition = actor.conditions.get(row['condition_id'])
        if condition is None or condition.source_definition_id != row['source_id'] or due(engine, condition.expires_on):
            continue
        groups[group] = max(groups.get(group, 0), row['feet'])
    return sum(groups.values())


def maximum(engine, actor, action, *, base=None, opportunity=False):
    """Current attack range/reach in feet; None retains an unbounded base query."""
    bound = action.parameters.get("range_from_action")
    if bound:
        # A harmless reach-based technique may use a particular held weapon's
        # current reach without pretending to be an attack itself.
        linked = engine.action_catalog.get(str(bound))
        if linked is None or linked.owner_id != actor.entity_id or linked.parameters.get("range_from_action"):
            raise ValueError("range_from_action requires an owned, direct action binding")
        from .ext.reach_bonus import current_reach
        return current_reach(engine, actor, linked, opportunity=opportunity) + bonus(engine, actor, linked, opportunity=opportunity)
    if base is None:
        base = action.range_ft if action.range_ft is not None else action.reach_ft
    return None if base is None else int(base) + bonus(engine, actor, action, opportunity=opportunity)


def opportunity_distance(engine, actor, row):
    """Reach of the bound OA attack, independent of whether Reaction is available."""
    action = engine.action_catalog.get(row.get('action_id'))
    if action is None:
        return int(row.get('reach_ft') or 5)
    return maximum(engine, actor, action, base=int(row.get('reach_ft') or 5), opportunity=True)


def spec_maximum(engine, actor, source, spec):
    """Current reach during declaration and after reactions; never cache totals."""
    base = int(spec.get('range_ft') or spec.get('reach_ft') or 5)
    action = spec.get('reach_action') or engine.action_catalog.get(source)
    return base if action is None else maximum(engine, actor, action, base=base)
