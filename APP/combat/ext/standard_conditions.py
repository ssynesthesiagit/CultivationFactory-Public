"""Shared condition helpers for check, critical, defense and lifecycle readers.

source_visible is shared with condition_rules. Data-defined damage defenses use
the normal resistance/penetration path for Factory and native actors alike.
"""
from typing import Any
from . import hook
from ..target_knowledge import can_see
from ..typed_executor import condition_rules


def source_visible(engine: Any, actor: Any, source_id: str | None, condition=None) -> bool:
    """Whether the condition bearer can currently see its recorded source."""
    source = engine.state.actors.get(source_id)
    if condition is not None:
        from ..condition_origins import source_actor
        source = source_actor(engine, actor, condition)
    return source is not None and can_see(engine, actor, source)


@hook('damage_defenses')
def condition_defenses(engine, target, damage_type, typed, source_actor_id):
    rows = []
    for rule in condition_rules(target):
        kinds = [str(kind).upper() for kind in rule.get('damage_resistances') or ()]
        if 'ALL' in kinds or damage_type in kinds:
            rows.append({'kind': 'resistance', 'damage_types': [damage_type]})
    return rows


@hook('attack_critical_qualification')
def critical_condition(engine, attacker, target, spec, roll, intent):
    distances = [rule.get('critical_hit_within_ft') for rule in condition_rules(target)]
    return any(type(distance) is int and distance >= 0 and
               engine._distance_actor_to_actor(attacker, target) <= distance for distance in distances)


@hook('state_event')
def lost_benefits(engine, event):
    """Permanently forfeit flagged conditions after evented incapacitation/Speed 0."""
    for actor in engine.state.actors.values():
        rules = condition_rules(actor)
        if not any(row.get('disabled_if_incapacitated_or_speed_zero') for row in rules):
            continue
        if engine._effective_speed(actor) > 0 and not any(row.get('no_actions') for row in rules):
            continue
        from ..typed_executor import CONDITION_PREFIX, rules as rule_table
        for condition in list(actor.conditions.values()):
            name = (rule_table().get('condition_id_aliases') or {}).get(condition.condition_id, condition.condition_id.removeprefix(CONDITION_PREFIX))
            name = (rule_table().get('condition_aliases') or {}).get(name, name)
            row = {**rule_table()['conditions'].get(name, {}), **((condition.data or {}).get('rule') or {})}
            if row.get('disabled_if_incapacitated_or_speed_zero'):
                engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)


def roll_rules(engine, actor, *, with_sources=False):
    """Pure eligibility; event delivery records forfeiture.

    with_sources returns eligible (condition, row) pairs for roll receipts and
    standing displays. Both forms apply the same Dodge eligibility filter.
    """
    from ..typed_executor import condition_rule_instances
    instances = condition_rule_instances(actor, engine=engine) if with_sources else None
    rows = [row for _, row in instances] if with_sources else condition_rules(actor, engine=engine)
    if any(row.get('disabled_if_incapacitated_or_speed_zero') for row in rows):
        if engine._effective_speed(actor) <= 0 or any(row.get('no_actions') for row in rows):
            if with_sources:
                return [(condition, row) for condition, row in instances if not row.get('disabled_if_incapacitated_or_speed_zero')]
            return [row for row in rows if not row.get('disabled_if_incapacitated_or_speed_zero')]
    return instances if with_sources else rows
