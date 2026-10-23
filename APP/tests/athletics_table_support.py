"""Small table/action helpers used by Athletics tests, without historical fights.

worker2_support and the Close Quarters/Scale Foe regressions use these helpers
so compiling fresh characters does not require unrelated retained archives.
"""
from combat.gate2_runtime_models import ActionDefinition, EconomyKind

# The compiler discovers these inputs dynamically. Declare the actual files so
# a public test snapshot retains the same Athletics rows as the local compiler.
ATHLETICS_INPUTS = (
    'combat/rules/feature_blocks.d/auto8-athletics.json',
    'combat/rules/feature_blocks.d/athletics-second-pass.json',
    'combat/rules/feature_blocks.d/bodyb.json',
    'combat/rules/feature_blocks.d/auto_lane3.json',
    'combat/rules/feature_blocks.d/foundations3.json',
)


def act(table, mid, cid, answers=()):
    menu = table.state(mid)['menu']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))


def end_turn(table, mid):
    result = act(table, mid, table.state(mid)['menu']['end_turn'])
    assert result['status'] == 'COMMITTED'
    return result


def add_action(bundle, name, effects):
    source = 'action:test.ath2.' + name.replace(' ', '_')
    action = ActionDefinition(
        source_definition_id=source, display_name=name, owner_id=bundle['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED',
        target_kind='HOSTILE_ENTITY' if name == 'Climb check' else 'SELF',
        range_ft=5 if name == 'Climb check' else None,
        parameters={'free_primary': True, 'typed': {'effects': effects,
                    'numbers': {'save_dc': 12}, 'riders': [], 'duration': {'kind': 'instant'}}})
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)
