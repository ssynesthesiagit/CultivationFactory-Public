"""Human table declarations of actual scene boundaries; never an AI tactic.

Any reviewed feature may opt into scene_tracking. The normal table action and
choice journal preserve the declaration and all expiration consumers on replay.
"""
from . import effect, hook, ai_controlled, note


@hook('compile_actions')
def scene_action(info):
    if not any((info['mechanics'].get(mid) or {}).get('scene_tracking') for mid in info['owned_ids']):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    actions = [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.record_scene_boundary",
        display_name='Record a scene boundary', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'effects': [{'type': 'record_scene_boundary'}],
        'numbers': info['numbers'], 'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0,
        'description': 'Table record: confirm that the current scene actually ended. No Action or resource cost. Resolves scene costs, expirations and once-per-scene limits.'})]
    paths = {((info['mechanics'].get(mid) or {}).get('acquisition') or {}).get('path_id') for mid in info['owned_ids']}
    for index, path in enumerate(sorted(p for p in paths if p)):
        actions.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.record_effective_level.{index}",
            display_name='Record cultivation suppression', owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'effects': [
                {'type': 'record_effective_level', 'path_id': path, 'maximum': int(info['numbers']['cl'])}],
                'numbers': info['numbers'], 'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0,
                'description': 'Table record of an established suppression. Features above effective Cultivation Level become unavailable. No Action or resource cost; this cannot grant levels.'}))
    actions.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.record_favorable_coincidence",
        display_name='Record an ordinary favorable coincidence', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'effects': [{'type': 'record_favorable_coincidence'}],
        'numbers': info['numbers'], 'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0,
        'description': 'Table record: an established ordinary coincidence from narrative positioning would remove a current obstacle without a check. This grants no new fact, ability or item.'}))
    return actions


@effect('record_favorable_coincidence', harmful=False)
def record_coincidence(ctx, row):
    if ai_controlled(ctx.engine, ctx.actor):
        return
    from . import needle
    selected = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'FAVORABLE_COINCIDENCE', ctx.actor.entity_id), ctx.actor,
        'choice:needle.favorable_coincidence', ['unknown', 'established'],
        labels={'unknown': 'No established coincidence', 'established': 'An ordinary narrative coincidence would remove a current obstacle without a check'},
        preferred=['unknown'], name='Record an ordinary favorable coincidence',
        prompt='Record only an established ordinary coincidence from narrative positioning. This does not create a fact, grant an ability or remove an obstacle by itself.')
    if selected == ['established']:
        from ..ordinary_events import favorable_coincidence
        allowed = favorable_coincidence(ctx.engine, ctx.actor, ctx.source)
        note(ctx.engine, ctx.source, ctx.actor, 'The established coincidence may resolve normally.' if allowed
             else 'The ordinary favorable coincidence fails; the current obstacle remains.')


@effect('record_effective_level', harmful=False)
def record_level(ctx, row):
    if ai_controlled(ctx.engine, ctx.actor):
        return
    from . import needle
    from ..feature_access import EFFECTIVE_LEVEL, effective_cl
    from .spirit_traditions import remove
    levels = [str(level) for level in range(1, int(row['maximum']) + 1)]
    current = effective_cl(ctx.actor, int(row['maximum']), row['path_id'])
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'EFFECTIVE_LEVEL', row['path_id']), ctx.actor,
        'choice:needle.effective_level', levels, labels={level: f'Effective Cultivation Level {level}' for level in levels},
        preferred=[str(current)], name='Record cultivation suppression',
        prompt='Record the established effective Cultivation Level under suppression. Features above that level become unavailable. This cannot grant levels and costs no Action or resources.')
    if not chosen:
        return
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id == EFFECTIVE_LEVEL and held.data.get('path_id') == row['path_id']:
            remove(ctx.engine, ctx.actor, held, 'REPLACED')
    if int(chosen[0]) < int(row['maximum']):
        ctx.engine._apply_condition(ctx.actor, EFFECTIVE_LEVEL, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'path_id': row['path_id'], 'cl': int(chosen[0]), 'label': f'Cultivation suppressed to effective CL {chosen[0]}'})


@effect('record_scene_boundary', harmful=False)
def record_boundary(ctx, row):
    if ai_controlled(ctx.engine, ctx.actor):
        return
    from . import needle
    choice = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'SCENE_BOUNDARY', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.scene_boundary', ['continue', 'ended'],
        labels={'continue': 'The current scene continues', 'ended': 'Record that the current scene ended'},
        preferred=['continue'], name='Record a scene boundary',
        prompt='Has the scene actually ended? This table declaration costs no Action or resources. It resolves scene costs and expirations and resets once-per-scene limits.')
    if choice == ['ended']:
        from ..scene_boundaries import end_scene
        note(ctx.engine, ctx.source, ctx.actor, f'{ctx.actor.display_name} records that the current scene ended.')
        end_scene(ctx.engine)
