"""Printed recovery cadence through native journey intents and cold replay."""
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.h1_support import ROOT, sheet

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH, RECOVERY = BASE + 'kindled_hearth', BASE + 'homefire_recovery'
A, B = (FACTORY_ACTOR_PREFIX + n for n in ('hearthkeeper', 'guest'))


def game(tmp_path, monkeypatch, *, owned=True, probes=False, features=(HEARTH, RECOVERY)):
    if probes:
        import combat.factory_compiler as compiler
        from combat.canonical import canonical_sha256
        original = compiler.compile_character
        def compile_with_probes(*args, **kwargs):
            bundle = original(*args, **kwargs)
            aid = bundle['actor_id']
            for name, effects in {
                'Exposure test': [{'type': 'exhaustion', 'applies_to': 'target', 'amount': 2}],
                'Smoke penalty': [{'type': 'condition', 'applies_to': 'target', 'condition': 'mark.smoke_penalty',
                    'expires_on': 'UNTIL_REMOVED', 'condition_data': {'speed_delta': -5, 'label': 'Smoke: movement reduced by 5 feet'}}],
                'Injury test': [{'type': 'damage', 'applies_to': 'target', 'flat': 10, 'damage_types': ['force']}],
                'Fear test': [{'type': 'save', 'applies_to': 'target', 'ability': 'wis', 'on_fail': [
                    {'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}], 'on_success': []}],
            }.items():
                sid = 'action:hearth-probe.' + aid + '.' + name.replace(' ', '_')
                bundle['action_catalog'].append({'source_definition_id': sid, 'display_name': name, 'owner_id': aid,
                    'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE', 'range_ft': 60,
                    'parameters': {'free_primary': True, 'typed': {'source': sid, 'numbers': {'save_dc': 50},
                                    'duration': {'kind': 'instant'}, 'effects': effects}}})
                bundle['actor_template']['action_ids'].append(sid)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
            return bundle
        monkeypatch.setattr(compiler, 'compile_character', compile_with_probes)
    def document(self, pid):
        doc = sheet([], cl=18, name=pid)
        doc['identity']['proficiency_bonus'] = 6
        doc['path_and_subpath'] = {'path_feature_record_ids': list(features) if owned and pid == 'hearthkeeper' else []}
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        return doc
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', document)
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': {
        'stable_id': 'journey:hearth', 'display_name': 'Open hearth recovery scene',
        'width_squares': 20, 'height_squares': 6,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}})
    def cold():
        return CombatService(ROOT, tmp_path)
    initial = cold().create_journey(project_ids=['hearthkeeper', 'guest'], arena_id='scene',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 2, 'y': 1}}, base_paces={A: 18000, B: 18000})
    jid = initial['journey_id']
    def act(kind, payload=None, aid=A):
        old = cold().journey_state(jid)
        state = cold().journey_act(jid, old['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == state
        assert cold().journey_replay(jid)['status'] == 'PASS'
        return state
    return cold, jid, act


def kindle(act):
    return act('hearth_kindle', {'position': {'x': 1, 'y': 2}, 'recipients': [A, B]})


def recover(act, benefit='exhaustion'):
    return act('hearth_short_rest', {'owner_id': A, 'benefit': benefit}, B)


def test_travel_exhaustion_recovery_consumes_current_levels_not_historical_exposure(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    act('travel_exhaustion', {'levels': 2, 'ordinary': True}, B)
    kindle(act)
    first = recover(act)
    assert first['actors'][B]['exhaustion'] == 1
    assert first['seconds'] == 3606
    # A second pulse is unavailable, including after leaving and reentering.
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='long rest'):
        recover(act)
    assert cold().journey_state(jid) == before
    act('long_rest', aid=B)
    kindle(act)
    assert recover(act)['actors'][B]['exhaustion'] == 0
    act('long_rest', aid=B)
    kindle(act)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='Exhaustion'):
        recover(act)
    assert cold().journey_state(jid) == before
    # A new exposure, unlike old receipts, is recoverable.
    act('travel_exhaustion', {'levels': 1, 'ordinary': True}, B)
    assert recover(act)['actors'][B]['exhaustion'] == 0


def test_recovery_recipient_chooses_and_cadence_survives_new_journey(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    kindle(act)
    state = recover(act, 'temp_hp')
    assert state['actors'][B]['encounter_snapshot']['temporary_hp'] == 12
    act('finish')
    fresh = cold().create_journey(project_ids=['hearthkeeper', 'guest'], arena_id='scene',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 2, 'y': 1}}, base_paces={A: 18000, B: 18000})
    jid2 = fresh['journey_id']
    cold().journey_act(jid2, 0, A, 'hearth_kindle', {'position': {'x': 1, 'y': 2}, 'recipients': [B]})
    with pytest.raises(ValueError, match='long rest'):
        cold().journey_act(jid2, 1, B, 'hearth_short_rest', {'owner_id': A, 'benefit': 'temp_hp'})


def finish_encounter(cold, jid, mid, tmp_path):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import settle
    table = TabletopService(cold(), tmp_path)
    for _ in range(5):
        if cold()._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert cold()._load_session(mid).engine.state.terminal_result is not None
    state = cold().journey_state(jid)
    return cold().journey_resume(jid, state['revision'])


def test_classified_current_levels_survive_real_combat_resume_and_are_not_rehealed(tmp_path, monkeypatch):
    from combat.fact_consent_admission import digest
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn
    cold, jid, act = game(tmp_path, monkeypatch, probes=True)
    result = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=1)
    mid = result['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    settle(table, mid, candidate(cold(), mid, 'Exposure test', target=B).candidate_id)
    engine = cold()._load_session(mid).engine
    held = next(c for c in engine.state.actors[B].conditions.values() if c.condition_id.endswith('.exhaustion'))
    cold().world_fact(mid, engine.state.state_version, {
        'source': RECOVERY, 'subject': B, 'kind': 'exhaustion_cause',
        'scope': digest([mid, held.instance_id]), 'value': {'condition_instance_id': held.instance_id, 'cause': ['travel', 'unknown']},
        'expires_at': 1000, 'readers': [B]})
    finish_encounter(cold, jid, mid, tmp_path)
    kindle(act)
    state = recover(act)
    assert state['actors'][B]['exhaustion'] == 1
    act('long_rest', aid=B)
    kindle(act)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='Exhaustion'):
        recover(act)
    assert cold().journey_state(jid) == before


def test_short_rest_ends_exact_classified_ordinary_penalty_after_combat_resume(tmp_path, monkeypatch):
    import json
    from combat.fact_consent_admission import digest
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn
    cold, jid, act = game(tmp_path, monkeypatch, probes=True)
    result = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=1)
    mid = result['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    settle(table, mid, candidate(cold(), mid, 'Smoke penalty', target=B).candidate_id)
    engine = cold()._load_session(mid).engine
    held = next(c for c in engine.state.actors[B].conditions.values() if c.condition_id.endswith('smoke_penalty'))
    cold().world_fact(mid, engine.state.state_version, {
        'source': RECOVERY, 'subject': B, 'kind': 'ordinary_environmental_penalty',
        'scope': digest([mid, held.instance_id]), 'value': {'condition_instance_id': held.instance_id, 'cause': 'smoke'},
        'expires_at': 1000, 'readers': [B]})
    finish_encounter(cold, jid, mid, tmp_path)
    kindle(act)
    state = recover(act, 'penalty:' + held.instance_id)
    conditions = state['actors'][B]['encounter_snapshot']['conditions']
    assert held.instance_id not in conditions
    assert any(json.loads(raw)['condition_id'] == 'condition:typed.fact_consent_admission' for raw in conditions.values())


def test_short_rest_hp_recovery_is_additional_and_survives_combat_resume(tmp_path, monkeypatch):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn
    cold, jid, act = game(tmp_path, monkeypatch, probes=True)
    result = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=1)
    mid = result['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    settle(table, mid, candidate(cold(), mid, 'Injury test', target=B).candidate_id)
    state = finish_encounter(cold, jid, mid, tmp_path)
    assert state['actors'][B]['encounter_snapshot']['current_hp'] == 50
    kindle(act)
    assert recover(act, 'hp')['actors'][B]['encounter_snapshot']['current_hp'] == 60


def test_short_rest_courage_survives_cold_combat_entry_and_consumes_only_next_fear_save(tmp_path, monkeypatch):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn
    cold, jid, act = game(tmp_path, monkeypatch, probes=True)
    kindle(act)
    state = recover(act, 'fear')
    result = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'})
    mid = result['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    for mode in ('ADVANTAGE', 'NORMAL'):
        settle(table, mid, candidate(cold(), mid, 'Fear test', target=B).candidate_id)
        session = cold()._load_session(mid)
        assert session.mechanical.replay()['status'] == 'PASS'
        roll = [e for e in session.engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == B][-1]
        assert roll.payload['mode'] == mode


def test_unused_courage_expires_at_end_of_next_scene_after_commit_and_reload(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    kindle(act)
    recover(act, 'fear')
    for scenes_left in (1, 0):
        state = cold().journey_state(jid)
        result = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1)
        state = finish_encounter(cold, jid, result['match_id'], tmp_path)
        import json
        courage = [json.loads(raw) for raw in state['actors'][B]['encounter_snapshot']['conditions'].values()
                   if json.loads(raw)['condition_id'] == 'condition:typed.homefire_courage']
        if scenes_left:
            assert len(courage) == 1 and courage[0]['data']['remaining_scenes'] == scenes_left
        else:
            assert courage == []


def test_kindled_hearth_crosses_into_the_combat_it_opens(tmp_path, monkeypatch):
    """The eight-hour Hearth is a real asset: it is present from the first combat menu."""
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn
    cold, jid, act = game(tmp_path, monkeypatch,
                          features=(HEARTH, RECOVERY, BASE + 'flame_that_welcomes_all'))
    kindle(act)
    held = cold().journey_state(jid)['actors'][A]['travel_effects'][HEARTH]
    state = cold().journey_state(jid)
    result = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'})
    mid = result['match_id']
    engine = cold()._load_session(mid).engine
    zone = next(z for z in engine.state.zones.values()
                if z.active and (z.trigger_profile.get('profile') or {}).get('hearth_object'))
    profile = zone.trigger_profile['profile']
    obj = engine.state.objects[profile['hearth_object']]
    assert zone.owner_id == A
    assert (zone.center.x, zone.center.y) == (held['position']['x'], held['position']['y'])
    assert sorted(profile['chosen_recipients']) == sorted(held['recipients']) == [A, B]
    assert obj.current_hp == obj.maximum_hp == held['current_hp'] and not obj.destroyed
    # The remaining eight hours cross as combat rounds (the activation already
    # spent its 6 seconds; the journey clock is still there).
    assert held['expires_at'] - state['seconds'] == 28800
    assert zone.duration_rounds == 28800 // 6
    # Flame That Welcomes All can center on the Hearth that crossed with its owner.
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    settle(table, mid, candidate(cold(), mid, 'Flame That Welcomes All').candidate_id,
           choices={'choice:needle.welcome_center': zone.zone_id,
                    'choice:needle.welcome_recipients': [A, B]})
    engine = cold()._load_session(mid).engine
    flame = next(z for z in engine.state.zones.values()
                 if z.active and (z.trigger_profile.get('profile') or {}).get('welcoming_flame'))
    assert (flame.center.x, flame.center.y) == (zone.center.x, zone.center.y)


def test_current_travel_exhaustion_causes_enter_combat_once_on_cold_reload(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    state = act('travel_exhaustion', {'levels': 2, 'ordinary': True}, B)
    result = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'})
    for _ in range(2):
        session = cold()._load_session(result['match_id'])
        assert session.verify()['status'] == 'PASS'
        assert session.mechanical.replay()['status'] == 'PASS'
        held = next(c for c in session.engine.state.actors[B].conditions.values()
                    if c.condition_id == 'condition:typed.exhaustion')
        assert held.data['level'] == 2 and held.data['causes'] == ['travel', 'travel']


def test_short_rest_outside_or_after_hearth_expiry_rolls_back(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    kindle(act)
    act('move', {'path': [{'x': x, 'y': 1} for x in range(3, 8)]}, B)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='inside'):
        recover(act, 'temp_hp')
    assert cold().journey_state(jid) == before
    act('move', {'path': [{'x': x, 'y': 1} for x in range(6, 1, -1)]}, B)
    act('wait', {'seconds': 26000})
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='expired'):
        recover(act, 'temp_hp')
    assert cold().journey_state(jid) == before


def test_short_rest_recovery_is_for_any_creature_in_aura_not_only_designated_allies(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    act('hearth_kindle', {'position': {'x': 1, 'y': 2}, 'recipients': [A]})
    assert recover(act, 'temp_hp')['actors'][B]['encounter_snapshot']['temporary_hp'] == 12


def test_wrong_owner_cannot_grant_recovery(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, owned=False)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        kindle(act)
    assert cold().journey_state(jid) == before
    assert not any(o['kind'].startswith('hearth_') for o in cold().journey_menu(jid, A)['options'])
