"""Persisted rare acquisition -> native table intents -> cold mechanical replay.

No hand-built feature ownership, source events, seals or Sparks are admission
evidence. Combat resources and seals must come from the actual native actions.
"""
from copy import deepcopy

import pytest

from app.core import Database, Settings
from combat.factory_compiler import compile_character
from combat.ext import mgr_reserve_heaven_thunder_storm_soul_tribulation_scarred_meridians as storm
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, commit_authority_event
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

QI = 'tianxia.path.qi_cultivation'
LASH = 'TAL_LIGHTNING_LIGHTNING_LASH'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('storm-acquisition'))
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    authority = NonSphereAuthorityService(db)
    install_authority_test_pack(db, authority)
    bundles = {}
    for level in (3, 6, 10, 14, 18):
        project = 'heaven-thunder-' + str(level)
        insert_project(db, project, target_cl=level)
        authority.initialize_for_project(project, target_cl=level, path_ids=[QI],
            path_attainment_by_id={QI: level}, method_id='METHOD-001')
        access = commit_authority_event(db, authority, project, 'subpath_access', {'selection_id': storm.SUBPATH})
        authority.select_subpath(project, QI, storm.SUBPATH, access_source_records=[access])
        authority.set_resource(project, QI, current=100, maximum=100)
        native = NonSphereAuthorityService(db)
        document = sheet([LASH], cl=level, dc=100, score=40, name='Heaven-Thunder cultivator')
        document['identity']['proficiency_bonus'] = 2 + (level - 1)//4
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        bundles[level] = native.compile_combat_character(project, document,
            actor_id=OWNER, reaction_plan={'ask': True})
    return bundles


def scenario(tmp_path, acquired, level):
    foe = sheet(['FIRE_BASE_IGNITE'], cl=level, name='Hostile cultivator')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    return fixture(tmp_path, [], cl=level, named=True, foe_sheet=foe,
        owner_bundle=deepcopy(acquired[level]), seed='HEAVEN-THUNDER-NATIVE-' + str(level),
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 10}, FOE: {'x': 6, 'y': 6}})


def source_candidate(combat, mid, source, target=FOE):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if (((getattr(engine.action_catalog.get(c.source_definition_id), 'parameters', None) or {}).get('typed') or {}).get('option_of')
                or ((getattr(engine.action_catalog.get(c.source_definition_id), 'parameters', None) or {}).get('typed') or {}).get('source')) == source
            and (not c.target_ids or target in c.target_ids)]
    assert rows, source
    return rows[0]


@pytest.mark.parametrize('level,tiers', [(3, 1), (6, 2), (10, 3), (14, 4), (18, 5)])
def test_native_rare_acquisition_grants_only_attained_variant_progression(tmp_path, acquired, level, tiers):
    combat, table, mid = scenario(tmp_path, acquired, level)
    engine = reload(tmp_path, mid)
    own = engine.state.actors[OWNER]
    assert {r['feature_id'] for r in engine.typed_passive_rows[OWNER] if r.get('block') == storm.BLOCK} == set(storm.FEATURES[:tiers])
    assert own.resources[storm.SPARK] == 0
    assert own.resource_maximums[storm.SPARK] == int(storm.numbers(engine, own)['pb']) * (2 if level >= 14 else 1)
    assert not any('storm_soul_cultivator.feature.' in str(r.get('feature_id')) for r in engine.typed_passive_rows[OWNER])
    assert storm.SPARK not in engine.state.actors[FOE].resources
    assert not any(storm.BLOCK == r.get('block') for r in engine.typed_passive_rows[FOE])


def test_first_seal_uses_real_qi_damage_and_round_resource_consumer(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 6)
    cast = source_candidate(combat, mid, LASH)
    settle(table, mid, cast.candidate_id)
    after = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids for e in after.events)
    assert storm.seal_count(after, after.state.actors[OWNER], after.state.actors[FOE]) == 1
    turn(table, mid, FOE)
    # An actual hostile Qi payment, bearing a native Thunder Seal, generates the
    # shared Spark and asks Reprisal on this other creature's turn.
    paid = candidate(combat, mid, 'Conflagration', at=(3, 6))
    prompts = settle(table, mid, paid.candidate_id, choices={
        'choice:needle.heaven_thunder_reprisal': 'qi'})
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[storm.SPARK] == 1
    assert any(p['context']['reaction_source_id'] == 'choice:needle.heaven_thunder_reprisal' for p in prompts)
    assert not after.state.actors[OWNER].reaction_available
    assert storm.seal_count(after, after.state.actors[OWNER], after.state.actors[FOE]) >= 2


def test_cloud_is_persisted_native_field_not_an_immediate_save(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 10)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Tribulation Cloud Core').candidate_id, choices={
        'choice:needle.heaven_thunder_cloud_center': 'cell:6,6'})
    after = reload(tmp_path, mid)
    assert len(storm.clouds(after)) == 1
    assert after.state.actors[FOE].current_hp == before
    assert after.state.actors[OWNER].concentration is not None
    turn(table, mid, FOE)
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp < before
    assert storm.seal_count(after, after.state.actors[OWNER], after.state.actors[FOE]) >= 1


def test_living_activation_native_turn_spark_judgment_and_scene_limit(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    settle(table, mid, candidate(combat, mid, 'Living Heavenly Tribulation').candidate_id)
    after = reload(tmp_path, mid)
    assert storm.living(after, after.state.actors[OWNER])
    assert len(storm.clouds(after)) == 1
    assert after.state.actors[OWNER].concentration is None
    assert after.state.actors[OWNER].resources[storm.QI] == 92
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[storm.SPARK] >= 1
    assert not any(after.action_catalog.get(c.source_definition_id) and after.action_catalog[c.source_definition_id].display_name == 'Living Heavenly Tribulation' for c in after.legal_candidates())


def test_copied_leaf_does_not_grant_variant_progression_or_common_resource(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_features=[storm.MERIDIANS], cl=18,
                                 seed='HEAVEN-THUNDER-COPIED-LEAF')
    engine = reload(tmp_path, mid)
    assert storm.SPARK not in engine.state.actors[OWNER].resources
    assert not any(r.get('block') == storm.BLOCK for r in engine.typed_passive_rows[OWNER])


def test_sentence_consumes_native_seals_and_qi_and_persists_named_suppression(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 14)
    for _ in range(3):
        settle(table, mid, source_candidate(combat, mid, LASH).candidate_id)
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Conflagration', at=(3, 6)).candidate_id)
        turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    previous = storm.seal_count(before, before.state.actors[OWNER], before.state.actors[FOE])
    assert previous >= 3
    qi = before.state.actors[OWNER].resources[storm.QI]
    settle(table, mid, candidate(combat, mid, 'Sentence the Core', target=FOE).candidate_id,
           choices={'choice:needle.heaven_thunder_sentence_seals': '3'})
    after = reload(tmp_path, mid)
    assert storm.seal_count(after, after.state.actors[OWNER], after.state.actors[FOE]) == previous - 3
    assert after.state.actors[OWNER].resources[storm.QI] == qi - 4
    restrictions = [c for c in after.state.actors[FOE].conditions.values()
                    if c.condition_id == 'condition:typed.cultivation_suppression']
    assert restrictions
    assert all(c.source_actor_id == OWNER and c.data['suppressed_sources'] for c in restrictions)
    assert not any(c.condition_id == 'condition:typed.cultivation_suppression'
                   for c in after.state.actors[ALLY].conditions.values())


def test_ninefold_flash_is_a_native_spark_consumer_after_real_enemy_payment(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 14)
    # The native source DC is deliberately raised through its actual ability
    # score profile in the acquired fixture, rather than a fabricated save receipt.
    settle(table, mid, candidate(combat, mid, 'Tribulation Cloud Core').candidate_id,
           choices={'choice:needle.heaven_thunder_cloud_center': 'cell:6,6'})
    settle(table, mid, source_candidate(combat, mid, LASH).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Conflagration', at=(3, 6)).candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[storm.SPARK] >= 1
    spent = before.state.actors[OWNER].resources[storm.SPARK]
    settle(table, mid, candidate(combat, mid, 'Ninefold Flash').candidate_id, choices={
        'choice:needle.heaven_thunder_flash_cost': '1',
        'choice:needle.heaven_thunder_flash_arrival_0': 'cell:5,6',
        'choice:needle.heaven_thunder_flash_target_0': FOE})
    after = reload(tmp_path, mid)
    assert (after.state.actors[OWNER].position.x, after.state.actors[OWNER].position.y) == (5, 6)
    assert after.state.actors[OWNER].resources[storm.SPARK] == spent - 1
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER and e.payload.get('teleport') for e in after.events)
