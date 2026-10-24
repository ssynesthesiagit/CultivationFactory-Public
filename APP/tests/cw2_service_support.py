"""Sealed synthetic setup actions, never replacements for production mechanics.

Worker review and sphere tests use these to prepare wounds, concealment and
other triggers through actual table transactions before exercising shipped rows.
"""
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition
from hashlib import sha256


def add_action(bundle, name, effects, *, target='ANY_CREATURE', typed=None):
    owner = sha256(bundle['actor_id'].encode()).hexdigest()[:10]
    source = 'action:test.cw2.' + owner + '.' + name.lower().replace(' ', '_')
    action = ActionDefinition(source_definition_id=source, display_name=name,
        owner_id=bundle['actor_id'], economy='NONE', resolution_kind='TYPED',
        target_kind=target, range_ft=120,
        parameters={'typed': {'source': source, 'effects': effects,
            'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 16, 'cl': 15},
            'duration': {'kind': 'instant'}, 'riders': [], **(typed or {})},
            'player_only': True, 'free_primary': True})  # Explicit scenario-only free setup activation.
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def seal(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
