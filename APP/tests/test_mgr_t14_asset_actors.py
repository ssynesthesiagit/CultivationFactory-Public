"""Native table guards for source-profiled actor runtime. No models or browser."""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import fixture, candidate, settle, reload, OWNER
from combat.ext.asset_actor_policy import basic_action_name
from combat.gate2_runtime_models import ActionDefinition
from combat.activation_settlement import path_numbers

PAPER = 'tianxia.subpath.qi.paper_cultivator.feature.'


@pytest.mark.parametrize('feature,group,hp', [
    ('paper_dragon', 'paper_dragon', 90), ('paper_clone', 'paper_clone', 1),
    ('folded_familiar', 'paper_familiar_crane', 36)])
def test_owned_profiles_are_separate_and_cannot_borrow_features(feature, group, hp):
    doc = sheet([], cl=18)
    doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [PAPER + feature]
    bundle = compile_character(doc, actor_id=OWNER)
    actor = next(c for c in bundle['summons'] if c['summon']['group'] == group)
    assert actor['actor_template']['maximum_hp'] == hp
    assert actor['actor_template']['owner_id'] == OWNER
    assert not actor['actor_template']['resources']
    assert not actor['actor_template']['primary_combatant']
    assert actor['summon']['actor_policy']
    for action in actor['action_catalog']:
        assert action['owner_id'] == actor['actor_id']
        assert not action.get('costs')


def test_asset_basic_menu_uses_mechanical_action_ids_not_display_names():
    def action(source_id, display):
        return ActionDefinition(source_definition_id=source_id, display_name=display,
            owner_id='*', economy='ACTION', resolution_kind='TYPED', target_kind='SELF')

    for key, label in [('help', 'Help'), ('hide', 'Hide'), ('search', 'Search')]:
        assert basic_action_name(action('action:typed.actor.' + key, 'renamed label')) == label
    assert basic_action_name(action('action:typed.actor.special', 'Help')) is None


def test_owning_path_explicit_zero_proficiency_is_preserved():
    info = {'numbers': {'cl': 1, 'pb': 2, 'save_dc': 11},
            'owner_sheet': {'path_and_subpath': {'paths': [
                {'path_id': 'tianxia.path.qi_cultivation', 'effective_cl': 1,
                 'proficiency_bonus': 0, 'key_ability': 'WIS'}]},
                'ability_scores_and_statistics': {'abilities': [{'ability': 'WIS', 'score': 10}]}}}
    assert path_numbers(info, 'tianxia.path.qi_cultivation')['pb'] == 0


def test_unimplemented_asset_commands_are_not_published():
    for feature, hidden in [('folded_familiar', {'Crane View', 'Ink Trail'}),
                            ('paper_dragon', {'Carry a willing creature'})]:
        doc = sheet([], cl=18)
        doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [PAPER + feature]
        bundle = compile_character(doc, actor_id=OWNER)
        labels = {a['display_name'] for body in bundle['summons'] for a in body.get('action_catalog', [])}
        assert not (labels & hidden)


def test_no_owned_source_is_default_inert():
    bundle = compile_character(sheet([], cl=18), actor_id=OWNER)
    assert not any(c['summon']['source'].startswith(PAPER) for c in bundle.get('summons', ()))


@pytest.mark.parametrize('feature,name,group', [
    ('paper_dragon', 'Paper Dragon', 'paper_dragon'),
    ('paper_clone', 'Paper Clone', 'paper_clone')])
def test_native_creation_table_commit_and_cold_replay(tmp_path, feature, name, group):
    combat, table, mid = fixture(tmp_path, [], owner_features=[PAPER + feature], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    choice = candidate(combat, mid, name)
    settle(table, mid, choice.candidate_id)
    engine = reload(tmp_path, mid)
    body = next(a for a in engine.state.actors.values() if (a.summon or {}).get('group') == group)
    assert body.active
    assert before-engine.state.actors[OWNER].resources['resource:core.qi'] == 5
    assert engine.grid.distance_ft(engine.state.actors[OWNER].position, body.position) <= 30
    assert body.summon['expires_on']
