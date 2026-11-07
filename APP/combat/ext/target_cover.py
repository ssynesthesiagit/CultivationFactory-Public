"""Target-specific ordinary cover bypass, carried by an explicit reviewed row.

target_cover_ignored saves the chooser and optional sphere restriction on the
recipient. cover_reduction reads the current scoped action; unrelated attacks,
other casters, absent records and Total Cover retain their normal defenses.
No global terrain, sight or line-of-effect policy changes.
"""
from . import effect, hook

CONDITION = 'condition:typed.target_cover_ignored'


@effect('target_cover_ignored')
def apply(ctx, row):
    from ..typed_executor import effect_expiry, effect_subjects
    for target in effect_subjects(ctx, row, harmful=True):
        expiry = effect_expiry(ctx, row, target, condition=True)
        deadline = f" Until the start of {ctx.actor.display_name}'s next turn." if expiry == "START_OF_SOURCE_NEXT_TURN" else ""
        ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=expiry,
            data={'by_sphere': row.get('by_sphere') or '',
                  'label': f'{ctx.actor.display_name} ignores Half and Three-Quarters Cover when using '
                           f'{str(row.get("by_sphere") or "").rsplit(".", 1)[-1].title() or "their"} talents against {target.display_name}.{deadline}'})


@hook('cover_reduction')
def reduction(engine, attacker, target, cover):
    from ..shot_geometry import action
    current = action(engine, attacker)
    if current is None or cover > 5:
        return None
    return covered_levels(attacker, target, current, cover)


def covered_levels(attacker, target, current, cover):
    """Pure shared query for attack and spatial-save cover consumers."""
    if attacker is None or current is None or cover > 5:
        return None
    sphere = (current.parameters.get('typed') or {}).get('sphere')
    for condition in target.conditions.values():
        if (condition.condition_id == CONDITION and condition.source_actor_id == attacker.entity_id
                and (not condition.data.get('by_sphere') or condition.data['by_sphere'] == sphere)):
            return 2
    return None


@hook('save_cover_reduction')
def save_reduction(engine, target, ability, source_id, cover):
    if ability != 'DEX':
        return None
    context = engine.d20_context() or {}
    attacker = engine.state.actors.get(context.get('source_actor_id'))
    current = engine.action_catalog.get(source_id)
    return covered_levels(attacker, target, current, cover)
