"""Synthetic action builder shared by Athletics and cover-transfer table tests.

Keep this helper independent of test modules so focused checks do not import
unrelated scenarios or their external fixture assets.
"""
from combat.gate2_runtime_models import ActionDefinition, EconomyKind


def add_action(bundle, name, effects):
    source = 'action:test.ath2.' + name.replace(' ', '_')
    action = ActionDefinition(
        source_definition_id=source, display_name=name, owner_id=bundle['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED',
        target_kind='HOSTILE_ENTITY' if name == 'Climb check' else 'SELF',
        range_ft=5 if name == 'Climb check' else None,
        parameters={'free_primary': True, 'typed': {'effects': effects,
            'numbers': {'save_dc': 12}, 'riders': [], 'duration': {'kind': 'instant'}}},
    )
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)
