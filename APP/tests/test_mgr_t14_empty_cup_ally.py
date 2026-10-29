"""Empty Cup is available against a teammate's Falling Fist on the table."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests.test_riders_c7 import ROOT, sheet
CUP = 'tianxia.subpath.body.drunken_fist.feature.empty_cup'
FIST = 'tianxia.subpath.body.drunken_fist.feature.falling_fist'


def acquire(db, cl):
    from character_builder import CharacterBuilderService
    from non_sphere_authority import NonSphereAuthorityService
    from character_creation.path_attainment import native_path_progressions

    body = 'tianxia.path.body_refining'
    parent = 'tianxia.subpath.body.drunken_fist'
    project = CharacterBuilderService(db).create_project(
        working_name='Drunken student', concept='Open School footwork', target_cl=cl,
        power_band='standard', source_reference=None, creation_mode='detailed',
        ability_scores={}, selections={'path_choice': [body], 'subpath_choice': [parent]})
    authority = NonSphereAuthorityService(db)
    path = next(r for r in authority.get_state(project['project_id'])['paths'] if r['path_id'] == body)
    features = [fid for level in range(1, cl + 1)
                for fid in native_path_progressions([authority.project_locked_path_catalog_record(body)], level)[0]['automatic_feature_record_ids']]
    doc = sheet(features, cl=path['attainment'], dc=100, name='Drunken student', spheres={})
    doc['path_and_subpath']['subpath_record_ids'] = [path['subpath_or_tradition_id']]
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    return doc


def cold(root, mid):
    session = CombatService(ROOT, root)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine

from tests.worker2_support import fixture, prompt_turn, settle, OWNER, ALLY, FOE


@pytest.mark.parametrize("accept", [False, True])
def test_same_team_falling_fist_prompts_and_replays(tmp_path, catalog_environment, accept):
    defender = acquire(catalog_environment['db'], 14)
    attacker = acquire(catalog_environment['db'], 6)
    defender['ability_scores_and_statistics']['armor_class']['base_value'] = 1

    def bundles(rows):
        rows[0] = compile_character(defender, actor_id=OWNER, reaction_plan={'ask': True})
        rows[2] = compile_character(attacker, actor_id=FOE, reaction_plan={'ask': True})

    combat, table, mid = fixture(tmp_path, [], bundle_transform=bundles,
        team_overrides={FOE: 'team:factory', ALLY: 'team:opponents'},
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, ALLY: {'x': 7, 'y': 6}})
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    prompt_turn(table, mid, FOE)
    before = cold(tmp_path, mid)
    assert before.state.actors[OWNER].team_id == before.state.actors[FOE].team_id
    stamina = before.state.actors[OWNER].resources['resource:core.stamina']
    n = len(before.events)
    candidate = next(g['options'][0]['candidate_id'] for g in table.state(mid)['menu']['actions']
                     if g['label'] == 'Fall Prone intentionally')
    prompts = settle(table, mid, candidate, {
        'reaction:typed.' + FIST: [OWNER],
        'reaction:typed.' + CUP: 'use' if accept else None,
        'reaction:typed.tianxia.path.body_refining.feature.stamina_guard': None,
        'choice:needle.empty_cup_posture': ['stay'],
        'choice:needle.empty_cup_move': ['stay'],
        'choice:needle.path_results.falling_fist': ['Prevent Reactions'],
    })
    assert any(p['context']['reaction_source_id'] == 'reaction:typed.' + CUP for p in prompts)
    after = cold(tmp_path, mid)
    actor = after.state.actors[OWNER]
    assert actor.resources['resource:core.stamina'] == stamina - (2 if accept else 0)
    rewritten = [e for e in after.events[n:] if e.event_type == 'D20_REWRITTEN']
    assert bool(rewritten) == accept
    if accept:
        assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == CUP for e in after.events[n:])
