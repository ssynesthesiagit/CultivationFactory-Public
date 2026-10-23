"""Portable Appraise acceptance: acquired sphere -> table choices -> cold replay.

Scenario actions produce ordinary mechanical conditions, never appraisal results.
Sealed encounter sources describe physical material, not diagnostic answers.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
             'authority/typed_mechanics/rules_text.json',
             'catalog_authority/cat1/data/canonical_talents.v1.json',
             'catalog_authority/cat1/data/prerequisite_projection.v1.json')
SOURCE = 'POISON_BASE_APPRAISE_THE_VENOM'
ME, FRIEND, FOE = ('actor:factory.venom-' + n for n in ('wren', 'tobin', 'mara'))
POOL = 'resource:core.qi'
PREFIX = 'choice:needle.venom_'
FACTS = ['classification', 'poisoned', 'dose_marks', 'burden', 'ingrained',
         'danger', 'antidote', 'handling', 'sphere']


@pytest.fixture(autouse=True)
def offline_ranking(monkeypatch):
    from combat import menu_rank, embedding_rank
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(
        transport=lambda url, body, timeout: {'data': []}))


def sheet(name, sphere=True, extra=(), primary='Qi'):
    authority = json.loads((ROOT / RESOURCES[0]).read_text())['mechanics']
    spheres = ['tianxia.sphere.poison'] if sphere else []
    if extra:
        spheres += sorted({authority[k]['sphere_id'] for k in extra if authority[k].get('sphere_id')})
    doc = {'identity': {'name': name, 'cultivation_level': 15, 'proficiency_bonus': 5,
                         'path': 'Qi Cultivation', 'path_ids': ['tianxia.path.qi_cultivation'], 'key_ability': 'CON'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                              for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'primary_resource': {'name': primary, 'maximum': 8},
                'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 60},
                'speed': {'walking_ft': 30}, 'technique_save_dc': 100, 'technique_attack_bonus': 100},
            'spheres_and_talents': {}}
    from combat import table_advance
    # The same learning projection used by real table advancement supplies the
    # automatic base rows. No test plants Appraise ownership or a passive flag.
    for sphere_id in dict.fromkeys(spheres):
        assert table_advance.sphere_status(sphere_id, table_advance.known(doc))['legal']
        doc = table_advance.apply(doc, {'spheres': [{'id': sphere_id}]}, authority)
    return table_advance.apply(doc, {'talents': [{'id': key} for key in extra]}, authority)


def material(kind, **binding):
    return {'medium': 'poison', 'kind': kind, 'source_key': 'scenario:' + kind,
            **binding, 'contents': [{'toxin_id': 'PRIVATE-TOXIN-42',
                'classification': 'alchemical', 'onset': 'delayed',
                'routes': ['contact'], 'antidote_scope': 'ordinary',
                'spheres': ['Alchemy'],
                'formula': 'SECRET-FORMULA', 'creator': 'SECRET-CREATOR',
                'history': 'SECRET-HISTORY', 'rare_recipe': 'SECRET-RECIPE'}], 'sealed': 1, 'obvious': 1}


def setup(path, *, owned=True, extra=(), sources=None, feet=15, primary='Qi', effects=None,
          cl=15, inventory=False, friend_poison=False, stone=False, owner_path=None, friend_enemy=False,
          sight_only=False, resource_json=False):
    docs = [sheet('Wren', owned, extra, primary), sheet('Tobin', friend_poison), sheet('Mara', False)]
    if cl != 15:
        docs[0]['identity'].update(cultivation_level=cl, proficiency_bonus=2 + (cl - 1) // 4)
    if owner_path:
        docs[0]['identity'].update(path=owner_path, path_ids=[{
            'Body Refining': 'tianxia.path.body_refining', 'Spirit Awakening': 'tianxia.path.spirit_awakening'
        }[owner_path]])
    if resource_json:
        stats = docs[0]['ability_scores_and_statistics']
        stats['primary_resource'] = json.dumps(stats['primary_resource'])
    if inventory:
        docs[0]['equipment'] = [{'starting_kit': {'items': [{
            'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou (Dagger)', 'quantity': 1}]}}]
    if stone:
        feature = 'tianxia.subpath.qi.mountain_core_cultivator.feature.stone_sense'
        docs[0]['path_and_subpath'] = {
            'path_record_ids': ['tianxia.path.qi_cultivation'],
            'paths': [{'path_id': 'tianxia.path.qi_cultivation', 'attainment': 15,
                       'subpath_or_tradition_id': 'tianxia.subpath.qi.mountain_core_cultivator'}],
            'earned_feature_occurrences': [{'feature_id': feature, 'acquired_cl': 3,
                                          'owning_path_id': 'tianxia.path.qi_cultivation'}]}
    bundles = []
    for aid, doc in zip((ME, FRIEND, FOE), docs):
        folder = path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': True}))
    if sight_only:
        # Negative control for the shared explicit-sight contract on an owned
        # compiled variant. It grants no feature, sense, location or finding.
        for action in bundles[0]['action_catalog']:
            typed = action.get('parameters', {}).get('typed') or {}
            if typed.get('source') == SOURCE:
                typed['requires_seen_target'] = True
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    if effects:
        a = ActionDefinition(source_definition_id='action:test.venom_scene', display_name='Scenario exposure',
            owner_id=ME, economy='NONE', resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60,
            parameters={'free_primary': True, 'typed': {'source': 'test:venom_scene',
                'numbers': {'pb': 5, 'save_dc': 100}, 'effects': effects, 'riders': []}})
        bundles[0]['action_catalog'].append(a.model_dump(mode='json'))
        bundles[0]['actor_template']['action_ids'].append(a.source_definition_id)
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat = CombatService(ROOT, path)
    table = TabletopService(combat, path)
    arena = dict(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    # Open native floor: the 30/35-foot boundary subjects must not spawn in
    # Pillar Arena's blocked center cells (9,6 and 10,6).
    arena['terrain_regions'] = []
    arena['map_objects'] = [{'id': 800 + n, 'kind': 'custom', 'x': 4, 'y': 7,
                            'name': kind, 'size': 'tiny', 'hp': 5, 'blocks': False}
                           for n, kind in enumerate(('corpse', 'object', 'food', 'drink', 'weapon', 'sample'))]
    arena['map_terrain'] = [{'terrain': 'loose rubble', 'cells': [[4, 8]]}]
    arena['sensory_sources'] = sources if sources is not None else [
        material('creature', entity_id=FOE),
        *[material(kind, object_id='object:map.' + str(800 + n))
          for n, kind in enumerate(('corpse', 'object', 'food', 'drink', 'weapon', 'sample'))],
        material('terrain', position={'x': 4, 'y': 8}, zone_id='zone:map:1'),
        material('contamination', position={'x': 5, 'y': 8}, label='visible spill')]
    mid = combat._finish_factory_match(bundles, [ME, FRIEND, FOE],
        {ME: 'team:a', FRIEND: 'team:b' if friend_enemy else 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, FRIEND: {'x': 3, 'y': 7}, FOE: {'x': 3 + feet // 5, 'y': 6}},
        arena, [ME, FRIEND], [FOE], control_modes={a: 'MANUAL' for a in (ME, FRIEND, FOE)},
        match_seed='VENOM-APPRAISE', display_name='Appraise the Venom', maximum_rounds=20)['match_id']
    turn(table, mid, ME)
    return combat, table, mid


def cold(path, mid):
    service = CombatService(ROOT, path)
    session = service._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return service, session.engine


def candidate(combat, mid, name='Appraise the Venom', target=None):
    e = combat._load_session(mid).engine
    return next(c.candidate_id for c in e.legal_candidates()
                if getattr(e.action_catalog.get(c.source_definition_id), 'display_name', '') == name
                and (target is None or c.target_ids == (target,)))


def send(table, mid, cid, answers):
    menu = table.state(mid)['menu']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)


def settle(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(15):
        result = send(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        key = p['context']['reaction_source_id']
        options = (p.get('choice') or {}).get('options', [])
        choice = (picks or {}).get(key, options[0]['id'] if options else None)
        if callable(choice):
            choice = choice(options)
        answer = {**p['context'], 'selection': 'DECLINE' if choice is None else 'USE'}
        if choice is not None and options:
            answer['option_ids'] = choice if isinstance(choice, list) else [choice]
        answers.append(answer)
    raise AssertionError('Choices did not settle')


def turn(table, mid, who):
    for _ in range(15):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == who:
            return
        settle(table, mid, menu['end_turn'])
    raise AssertionError('No turn')


def readings(table, mid, observer=ME):
    return table.state(mid, fog=True, fog_view='own', fog_actor_ids=(observer,)).get(
        'observer_information', {}).get(observer, {})


def appraise(combat, table, mid, subject=FOE, facts=('classification',), profile=False):
    return settle(table, mid, candidate(combat, mid), {
        PREFIX + 'subject': subject, PREFIX + 'detail': 'three' if len(facts) == 3 else None,
        PREFIX + 'facts': list(facts), PREFIX + 'profile': 'create' if profile else None})


@pytest.mark.parametrize('fact,expected', [
    ('classification', 'alchemical'), ('poisoned', 'not Poisoned'), ('dose_marks', 'none of your Dose Marks'),
    ('burden', 'no Toxin Burden'), ('ingrained', 'no Ingrained Toxin'), ('danger', 'delayed'),
    ('antidote', 'ordinary antidote might help'), ('handling', 'sealed'), ('sphere', 'Alchemy')])
def test_nine_actual_facts_and_free_native_acquisition(tmp_path, fact, expected):
    combat, table, mid = setup(tmp_path)
    before = combat._load_session(mid).engine.state.actors[ME].resources.copy()
    prompts = appraise(combat, table, mid, facts=(fact,))
    facts_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == PREFIX + 'facts')
    assert {o['id'] for o in facts_prompt['choice']['options']} == set(FACTS)
    combat, e = cold(tmp_path, mid)
    assert e.state.actors[ME].resources == before and not e.state.actors[ME].action_available
    result = readings(TabletopService(combat, tmp_path), mid)
    assert 'poison is present' in str(result).lower() and expected in str(result)
    assert not any(r['kind'] == 'antidote_profile' for r in result['information'])


@pytest.mark.parametrize('kind,subject', [
    ('creature', FOE), *[(k, 'object:map.' + str(800 + n))
        for n, k in enumerate(('corpse', 'object', 'food', 'drink', 'weapon', 'sample'))],
    ('terrain', 'zone:map:1'), ('contamination', 'scene:scenario:contamination')])
def test_every_native_subject_delivers_paid_facts_and_private_profile(tmp_path, kind, subject):
    combat, table, mid = setup(tmp_path)
    prompts = appraise(combat, table, mid, subject, ('classification', 'danger', 'handling'), True)
    assert any(p['context']['reaction_source_id'] == PREFIX + 'profile' for p in prompts)
    combat, e = cold(tmp_path, mid)
    assert e.state.actors[ME].resources[POOL] == 7
    paid = [x for x in e.events if x.event_type == 'RESOURCE_SPENT']
    assert [x.payload['amount'] for x in paid] == [1]
    table = TabletopService(combat, tmp_path)
    info = readings(table, mid)
    profile = next(r for r in info['information'] if r['kind'] == 'antidote_profile')
    assert len(profile['facts']) == 3 and 'alchemical' in str(profile)
    assert not readings(table, mid, FRIEND) and not readings(table, mid, FOE)
    feed = table.events(mid, 0)
    for secret in ('SECRET-', 'PRIVATE-TOXIN'):
        assert secret not in str(info) and secret not in str(feed)
    # Protocol source_definition_id fields identify every action. Player prose
    # and learned findings must use its readable name, never that identifier.
    assert SOURCE not in str(info)
    assert SOURCE not in str([r['summary'] for r in feed['events']])
    from combat.target_knowledge import recent_events
    assert 'PRIVATE-TOXIN' not in str(recent_events(e, e.state.actors[FRIEND], e.events))
    assert 'PRIVATE-TOXIN' not in str(recent_events(e, e.state.actors[ME], e.events))
    turn(table, mid, FOE); turn(table, mid, ME)
    assert readings(table, mid)['information'] == info['information']


def test_mechanical_conditions_marks_wound_and_other_owner_privacy(tmp_path):
    effects = [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}},
               {'type': 'condition', 'condition': 'bleeding', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}},
               {'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}},
               {'type': 'mark', 'mark': 'Toxin Burden', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}]
    combat, table, mid = setup(tmp_path, effects=effects, sources=[])
    settle(table, mid, candidate(combat, mid, 'Scenario exposure', FOE))
    prompts = appraise(combat, table, mid, facts=('poisoned', 'dose_marks', 'burden'))
    assert 'Poisoned' in str(readings(table, mid)) and '1 of your Dose Marks' in str(readings(table, mid))
    assert 'Toxin Burden' in str(readings(table, mid))
    turn(table, mid, FOE); turn(table, mid, ME)
    e = combat._load_session(mid).engine
    wound = next(c.instance_id for c in e.state.actors[FOE].conditions.values() if c.condition_id == 'condition:typed.bleeding')
    appraise(combat, table, mid, 'wound:' + FOE + ':' + wound)
    cold(tmp_path, mid)


def test_unknown_input_never_becomes_poison_free_and_no_profile(tmp_path):
    combat, table, mid = setup(tmp_path, sources=[])
    appraise(combat, table, mid, facts=('classification',))
    text = str(readings(table, mid)).lower()
    assert 'unknown' in text and 'poison is absent' not in text
    assert 'antidote_profile' not in text
    cold(tmp_path, mid)


@pytest.mark.parametrize('feet,allowed', [(5, True), (10, True), (30, True), (35, False)])
def test_real_subject_perception_and_range(tmp_path, feet, allowed):
    combat, table, mid = setup(tmp_path, feet=feet)
    result = send(table, mid, candidate(combat, mid), [])
    assert result['status'] == 'REACTION_REQUIRED'
    options = result['reaction']['choice']['options']
    assert (FOE in {o['id'] for o in options}) == allowed
    assert combat._load_session(mid).engine.state.actors[ME].action_available


def test_cancel_invalid_choices_and_no_cp_are_atomic(tmp_path):
    combat, table, mid = setup(tmp_path)
    e = combat._load_session(mid).engine
    before = e.state.model_dump(mode='json')
    cid = candidate(combat, mid)
    pause = send(table, mid, cid, [])
    assert pause['status'] == 'REACTION_REQUIRED'
    answer = {**pause['reaction']['context'], 'selection': 'USE', 'option_ids': ['missing-subject']}
    with pytest.raises(Exception):
        send(table, mid, cid, [answer])
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    assert not readings(table, mid)


def test_wrong_owner_has_no_appraise(tmp_path):
    combat, table, mid = setup(tmp_path, owned=False)
    e = combat._load_session(mid).engine
    assert not any(a.display_name == 'Appraise the Venom' for a in e.action_catalog.values())
    assert not readings(table, mid)
