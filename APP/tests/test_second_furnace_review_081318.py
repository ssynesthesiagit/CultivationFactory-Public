"""Regressions for the 081318 Sol review: Journey Furnace payments, Motion choices and scene boundaries.

Each test goes through CombatService and the saved Journey store, so it fails without the fix.
"""
from tests.test_second_furnace_native import game, OWNER, f


def _set_resources(cold, jid, values):
    service = cold()
    session = service.journeys.load(jid)
    session.state['actors'][OWNER]['resources'].update(values)
    service.journeys.save(session)


def _payment(cold, jid, payment):
    menu = cold().journey_menu(jid, OWNER)
    option = next(row for row in menu['options'] if row['kind'] == 'furnace_engine' and row['payload']['payment'] == payment)
    return menu, option


def test_scene_end_runs_furnace_cleanup_and_commits_with_real_owner(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-scene-end')
    _set_resources(cold, jid, {f.QI: 8, f.DEVIL: 3})
    menu, option = _payment(cold, jid, 'ordinary')
    state = cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    assert state['actors'][OWNER]['source_states'][f.PARENT]['scene_engine_used'] == 1
    state = cold().journey_end_scene(jid, state['revision'], 'The scene has ended.')
    reloaded = cold().journey_state(jid)
    actor = reloaded['actors'][OWNER]
    assert actor['source_states'][f.PARENT]['scene_engine_used'] == 0
    assert actor['resources'][f.DEVIL] == 0
    assert any(row['kind'] == 'SCENE_ENDED' for row in reloaded['events'])


def test_core_payment_offers_temp_hp_and_legal_move_then_applies_chosen_benefit(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-core-motion')
    _set_resources(cold, jid, {f.DEVIL: 2, f.QI: 8})
    menu, option = _payment(cold, jid, 'core:2')
    state = cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    menu = cold().journey_menu(jid, OWNER)
    motions = [row for row in menu['options'] if row['kind'] == 'furnace_core_motion']
    assert {row['payload']['benefit'] for row in motions} == {'temp_hp', 'move'}, motions
    move = next(row for row in motions if row['payload']['benefit'] == 'move')
    state = cold().journey_act(jid, menu['revision'], OWNER, move['kind'], move['payload'])
    reloaded = cold().journey_state(jid)
    actor = reloaded['actors'][OWNER]
    assert {'x': actor['position']['x'], 'y': actor['position']['y']} == move['payload']['destination']
    assert not actor['source_states'][f.PARENT].get('core_motion_pending')
    assert any(row['kind'] == 'FURNACE_MOTION' and row['benefit'] == 'move' for row in reloaded['events'])


def test_core_temp_hp_motion_is_doubled_while_engine_is_active(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-core-temp')
    _set_resources(cold, jid, {f.DEVIL: 2, f.QI: 8})
    menu, option = _payment(cold, jid, 'core:2')
    cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    menu = cold().journey_menu(jid, OWNER)
    temp = next(row for row in menu['options'] if row['kind'] == 'furnace_core_motion' and row['payload']['benefit'] == 'temp_hp')
    assert 'Gain 8 Temporary Hit Points' in temp['label']
    state = cold().journey_act(jid, menu['revision'], OWNER, temp['kind'], temp['payload'])
    assert state['actors'][OWNER]['encounter_snapshot']['temporary_hp'] == 8


def test_seed_overdraw_grants_corruption_trigger_devil_qi_and_its_own(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-seed-devil')
    _set_resources(cold, jid, {f.QI: 8, f.DEVIL: 0, f.CORRUPTION: 0})
    menu, option = _payment(cold, jid, 'seed')
    state = cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    actor = state['actors'][OWNER]
    assert actor['resources'][f.CORRUPTION] == 1
    assert actor['resources'][f.DEVIL] == 2


def test_seed_reinforcement_temp_hp_is_doubled_while_engine_is_active(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-seed-temp')
    _set_resources(cold, jid, {f.QI: 8, f.DEVIL: 0, f.CORRUPTION: 0})
    menu, option = _payment(cold, jid, 'seed')
    state = cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    menu = cold().journey_menu(jid, OWNER)
    temp = next(row for row in menu['options'] if row['kind'] == 'furnace_seed_reinforcement' and row['payload']['benefit'] == 'temp_hp')
    assert 'Gain 8 Temporary Hit Points' in temp['label']
    state = cold().journey_act(jid, menu['revision'], OWNER, temp['kind'], temp['payload'])
    assert state['actors'][OWNER]['encounter_snapshot']['temporary_hp'] == 8


def test_seed_overdraw_devil_pool_above_cap_is_not_lowered(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-seed-cap')
    _set_resources(cold, jid, {f.QI: 8, f.DEVIL: 10, f.CORRUPTION: 0})
    menu, option = _payment(cold, jid, 'seed')
    state = cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    assert state['actors'][OWNER]['resources'][f.DEVIL] >= 10


def test_seed_reinforcement_label_matches_granted_devil_qi(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='review-seed-label')
    _set_resources(cold, jid, {f.QI: 8, f.DEVIL: 0, f.CORRUPTION: 0})
    menu, option = _payment(cold, jid, 'seed')
    cold().journey_act(jid, menu['revision'], OWNER, option['kind'], option['payload'])
    menu = cold().journey_menu(jid, OWNER)
    labels = [row['label'] for row in menu['options'] if row['kind'] == 'furnace_seed_reinforcement']
    assert labels and all('grants 1 Devil Qi' not in label for label in labels), labels


def test_subpath_authority_keeps_documented_overdraw_seam():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/reviewed_final.d/subpaths.json'
    record = json.loads(path.read_text(encoding='utf-8'))['mechanics'][f.PREFIX + 'demon_seed_overdraw']
    assert record['reviewed_by'] == 'subpaths 2026-09-28'
    # Typed printed price and after-resolution gain must stay (F13R: they were dropped).
    assert [(e['type'], e['flat'], e['evidence']) for e in record['effects']] == [
        ('gain_resource', 1, 'Price: Gain 1 Corruption'),
        ('gain_resource', 1, 'After resolving the activation, gain 1 Devil Qi.')]
    assert any('Automated by combat/ext/devil_heart_second_furnace.py' in row for row in record['riders'])
    assert any('GM-adjudicated' in row for row in record['riders'])


def test_combat_service_exposes_journey_world_fact_and_end_scene_boundaries():
    # Regression: a447dba8 (merge of main) dropped these wrappers; native tests and the
    # scene-end cleanup call them through CombatService.
    from combat.gate5_service import CombatService
    assert callable(getattr(CombatService, 'journey_world_fact', None))
    assert callable(getattr(CombatService, 'journey_end_scene', None))
