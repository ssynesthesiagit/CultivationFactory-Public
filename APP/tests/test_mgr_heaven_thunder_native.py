"""Persisted rare acquisition -> native table intents -> cold mechanical replay.

No hand-built feature ownership, source events, seals or Sparks are admission
evidence. Combat resources and seals must come from the actual native actions.
"""
from copy import deepcopy

import pytest

from app.core import Database, Settings
from combat.factory_compiler import compile_character
from combat import flight
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


def advance(table, mid, actor):
    """Pass intervening turns, declining Thunder Road so a gained Spark is not spent."""
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'],
               picks={'choice:needle.heaven_thunder_thunder_road': None})
    raise AssertionError('No turn')


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


def test_recursing_cloud_core_replaces_the_field_instead_of_stacking(tmp_path, acquired):
    """A second Tribulation Cloud Core replaces the first field instead of leaving two.

    The plug-in installs its own centred field after removing the compiler's provisional area; the same
    replacement must drop the earlier cloud (one printed field), not stack a second one."""
    combat, table, mid = scenario(tmp_path, acquired, 10)
    settle(table, mid, candidate(combat, mid, 'Tribulation Cloud Core').candidate_id, choices={
        'choice:needle.heaven_thunder_cloud_center': 'cell:6,6'})
    first = storm.clouds(reload(tmp_path, mid))
    assert len(first) == 1
    # End the casting turn first: the Bonus Action is spent there, so the next cast needs a new turn.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Tribulation Cloud Core').candidate_id, choices={
        'choice:needle.heaven_thunder_cloud_center': 'cell:7,6'})
    after = storm.clouds(reload(tmp_path, mid))
    assert len(after) == 1 and after[0].zone_id != first[0].zone_id


def test_living_activation_native_turn_spark_judgment_and_scene_limit(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    before = reload(tmp_path, mid)
    qi = before.state.actors[OWNER].resources[storm.QI]
    living = candidate(combat, mid, 'Living Heavenly Tribulation')
    settle(table, mid, living.candidate_id)
    after = reload(tmp_path, mid)
    assert storm.living(after, after.state.actors[OWNER])
    assert len(storm.clouds(after)) == 1
    assert after.state.actors[OWNER].concentration is None
    # The printed 8 Qi is paid by this activation; other committed passives
    # (for example Golden Core efficiency) may return a point afterwards.
    paid = [e for e in after.events
            if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == living.source_definition_id
            and e.payload.get('resource_id') == storm.QI]
    assert [int(e.payload['amount']) for e in paid] == [8]
    assert after.state.actors[OWNER].resources[storm.QI] <= qi - 7
    advance(table, mid, FOE)
    advance(table, mid, OWNER)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[storm.SPARK] >= 1
    assert not any(after.action_catalog.get(c.source_definition_id) and after.action_catalog[c.source_definition_id].display_name == 'Living Heavenly Tribulation' for c in after.legal_candidates())


def test_living_activation_grants_sixty_foot_hover_flight_and_keeps_walking_speed(tmp_path, acquired):
    """Regression for F5R fix 1: the printed Fly Speed 60 and Hover are granted by the plug-in's
    living activation for the one-minute duration, and walking Speed is unchanged.
    Without the general_flight grant in activate(), flight.profile reports no flight and this fails."""
    combat, table, mid = scenario(tmp_path, acquired, 18)
    before = reload(tmp_path, mid)
    walking_before = before._effective_speed(before.state.actors[OWNER])
    assert flight.profile(before, before.state.actors[OWNER]).speed_ft == 0
    living = candidate(combat, mid, 'Living Heavenly Tribulation')
    settle(table, mid, living.candidate_id)
    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    profile = flight.profile(after, actor)
    assert profile.speed_ft == 60
    assert profile.hover
    flying = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.general_flight']
    assert len(flying) == 1
    assert flying[0].source_actor_id == OWNER
    assert flying[0].data['fly_speed_ft'] == 60 and int(flying[0].data['flight_hover']) == 1
    # F6R fix 2: the grant is bounded by the printed one-minute clock, the same counted expiry as the
    # Living condition itself -- a whole-fight (UNTIL_REMOVED) grant would not equal it.
    active = storm.living(after, actor)
    assert active is not None and flying[0].expires_on == active.expires_on
    assert after._effective_speed(actor) == walking_before
    assert flight.profile(after, after.state.actors[FOE]).speed_ft == 0


def advance_judgment(table, mid, actor, kind):
    """Advance to ``actor``'s next turn, answering the Living judgment with ``kind``."""
    picks = {'choice:needle.heaven_thunder_thunder_road': None,
             'choice:needle.heaven_thunder_judgment': kind,
             'choice:needle.heaven_thunder_judgment_lightning_point': 'cell:6,6'}
    settle(table, mid, table.state(mid)['menu']['end_turn'], picks=picks)
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=picks)
    raise AssertionError('No turn')


def test_living_judgments_commit_their_printed_damage_type(tmp_path, acquired):
    """Regression for the F6R damage-type fix: bolt()'s kinds reach the committed damage, so the Thunder
    judgment commits THUNDER and the Lightning judgment LIGHTNING. damage_row() used to always list both
    types, so the executor's hardest-type pick could commit Lightning for the printed Thunder judgment."""
    combat, table, mid = scenario(tmp_path, acquired, 18)
    settle(table, mid, candidate(combat, mid, 'Living Heavenly Tribulation').candidate_id)
    advance(table, mid, FOE)
    for kind, damage_type in (('thunder', 'THUNDER'), ('lightning', 'LIGHTNING')):
        mark = len(reload(tmp_path, mid).events)
        advance_judgment(table, mid, OWNER, kind)
        after = reload(tmp_path, mid)
        # The Living field's own per-turn pulse also damages the foe inside these windows, committed from
        # the cloud's source; only the judgment's own commits (LIVING) are asserted.
        hits = [e for e in after.events[mark:] if e.event_type == 'DAMAGE_COMMITTED'
                and FOE in (e.target_ids or ()) and e.source_definition_id == storm.LIVING]
        assert hits and {e.payload.get('damage_type') for e in hits} == {damage_type}


def test_copied_leaf_does_not_grant_variant_progression_or_common_resource(tmp_path):
    """A copied feature row alone is not the Rare Variant's recorded Subpath acquisition.

    This is the intentional difference from main's typed leaf: main created the
    Spark pool and a per-use Living counter from the leaf itself. The printed
    record is a Subpath feature, so its resource engine begins only through the
    committed subpath selection (test_native_rare_acquisition_* covers that side).
    """
    combat, table, mid = fixture(tmp_path, [], owner_features=[storm.MERIDIANS, storm.LIVING], cl=18,
                                 seed='HEAVEN-THUNDER-COPIED-LEAF')
    engine = reload(tmp_path, mid)
    own = engine.state.actors[OWNER]
    assert storm.SPARK not in own.resources
    assert not any('tribulation_spark' in str(resource) for resource in own.resources)
    assert not any('heaven_thunder_living' in str(resource) for resource in own.resources)
    assert not any(r.get('block') == storm.BLOCK for r in engine.typed_passive_rows[OWNER])
    assert not any(action.display_name == 'Living Heavenly Tribulation'
                   for action in engine.action_catalog.values())


def test_sentence_consumes_native_seals_and_qi_and_persists_named_suppression(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 14)
    # One Qi-powered Lightning hit per round places the once-per-turn First
    # Thunder Seal. The foe spends Qi in the first round only (its Reprisal
    # adds a Seal); later rounds skip its actions so the five-Seal Seal
    # Escalation cannot suppress its Fire sphere before Sentence.
    for round_number in range(3):
        settle(table, mid, source_candidate(combat, mid, LASH).candidate_id)
        advance(table, mid, FOE)
        if round_number == 0:
            settle(table, mid, candidate(combat, mid, 'Conflagration', at=(3, 6)).candidate_id,
                   choices={'choice:needle.heaven_thunder_reprisal': 'qi'})
        advance(table, mid, OWNER)
    before = reload(tmp_path, mid)
    previous = storm.seal_count(before, before.state.actors[OWNER], before.state.actors[FOE])
    assert previous >= 3
    qi = before.state.actors[OWNER].resources[storm.QI]
    sentence = candidate(combat, mid, 'Sentence the Core', target=FOE)
    settle(table, mid, sentence.candidate_id, choices={
        'choice:needle.heaven_thunder_sentence_seals': '3',
        'choice:needle.heaven_thunder_suppressed_system': 'first'})
    after = reload(tmp_path, mid)
    assert storm.seal_count(after, after.state.actors[OWNER], after.state.actors[FOE]) == previous - 3
    spent = [int(e.payload['amount']) for e in after.events
             if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == sentence.source_definition_id
             and e.payload.get('resource_id') == storm.QI]
    assert spent == [4]
    # The printed 4 Qi is paid; a once-per-turn refund passive may return one point.
    assert qi - after.state.actors[OWNER].resources[storm.QI] in (3, 4)
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
    advance(table, mid, FOE)
    # Answer the Reprisal reaction but decline the optional Thunder Edge: the
    # enemy's payment must leave the Spark that Ninefold Flash then spends.
    settle(table, mid, candidate(combat, mid, 'Conflagration', at=(3, 6)).candidate_id,
           choices={'choice:needle.heaven_thunder_reprisal': 'qi'})
    advance(table, mid, OWNER)
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
