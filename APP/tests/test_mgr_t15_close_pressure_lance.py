"""Native Pressure Lance acceptance diagnostics; known gaps remain visible.

Only portable source-shaped sheets, real map/service intents and cold replay.
No scripted roll, fixture action, installed Soaked state or private capture.
"""
import json
import zipfile
from pathlib import Path
import pytest
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService

APP = Path(__file__).resolve().parents[1]
LANCE = 'TAL_WATER_PRESSURE_LANCE'
OWNER, WET, DRY, MISS, SIDE = ['actor:factory.' + n for n in ('00000001', '00000002', '00000003', '00000004', '00000005')]
DEPENDENCIES = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
                'combat/rules/feature_blocks.d/a2_water.json', 'combat/rules/objects.json')


def document(name, owned, ac):
    # Qi R19: INT key, CL1 * key modifier = 2 Qi; d8 + CON = 10 HP.
    # Other combatants deliberately provide durable low/high AC test controls.
    return {'identity': {'name': name, 'display_name': name, 'cultivation_level': 1,
                        'proficiency_bonus': 2, 'path': 'Qi Cultivation', 'key_ability': 'INT'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 2}, 'armor_class': {'base_value': 12 if name == 'Lancer' else ac},
            'hit_points': {'maximum': 10 if name == 'Lancer' else 200}, 'speed': {'walking_ft': 30},
            'technique_save_dc': 12, 'technique_attack_bonus': 4},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
            'learned_talent_record_ids': [LANCE if owned else 'TAL_WATER_WATER_WHIP'],
            'automatic_sphere_component_record_ids': [
                'WATER_BASE_WATER_INITIATION', 'WATER_BASE_WATER_LASH', 'WATER_BASE_SHAPE_CURRENT']}}


def settle(send):
    answers = []
    for _ in range(30):
        result = send(answers)
        if result['status'] == 'COMMITTED': return
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        area = p['context'].get('reaction_source_id') == 'choice:needle.area_recipients'
        answers.append({**p['context'], 'selection': 'USE' if area else 'DECLINE',
                        'option_ids': [o['id'] for o in p['choice']['options']] if area else []})
    raise AssertionError('native action did not settle')


def end(table, mid):
    state = table.state(mid); menu = state['menu']
    settle(lambda a: table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'], a))


def turn(table, mid):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == OWNER: return
        end(table, mid)
    raise AssertionError('lancer turn unavailable')


def native(tmp_path, owned=True, blocked=False):
    for path in DEPENDENCIES: assert (APP / path).is_file()
    for pid, name in zip(('00000001', '00000002', '00000003', '00000004', '00000005'), ('Lancer', 'Wet', 'Dry', 'Miss', 'Side')):
        folder = tmp_path / 'portable_characters' / pid; folder.mkdir(parents=True)
        d = document(name, pid == '00000001' and owned, 1000 if pid == '00000004' else 1)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(d))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, set())
    combat = CombatService(APP, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Pressure Lance acceptance',
        'width_squares': 17, 'height_squares': 9,
        'starts': {'team1': [[1, 3], [5, 3]], 'team2': [[3, 3], [13, 3], [5, 4]]},
        'walls': ([{'shape': 'line', 'points': [[11, 2], [11, 5]], 'blocks': 'sight_and_movement'}] if blocked else []),
        'objects': [{'id': 81, 'kind': 'crate', 'x': 9, 'y': 3, 'blocks': False,
                     'hp': 100, 'ac': 1, 'unattended': True}]})
    mid = combat.create_factory_match(project_ids=['00000001', '00000003'], opponent_actor_ids=[WET, MISS, SIDE],
        control_modes={a: 'MANUAL' for a in (OWNER, WET, DRY, MISS, SIDE)},
        arena_id='battlefield:map.' + arena['map_id'], match_seed='pressure-lance-native')['match_id']
    table = TabletopService(combat, tmp_path); turn(table, mid)
    return combat, table, mid


def cold(tmp_path, mid):
    combat = CombatService(APP, tmp_path); session = combat._load_session(mid)
    assert session.verify()['canonical_state_sha256'] == session.mechanical.replay()['canonical_state_sha256']
    return combat, TabletopService(combat, tmp_path), session.engine


def act(combat, table, mid, lance=True, target=None, aim=(13, 3)):
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == ('Water Lash + Pressure Lance' if lance else 'Water Lash')
            and (target is None or target in c.target_ids)]
    if lance: rows = [c for c in rows if c.destination and (c.destination.x, c.destination.y) == aim]
    assert rows, {'error': 'native selected Water Lash direction/target intent missing',
                  'actions': [(a.display_name, a.target_kind, a.parameters.get('typed', {}).get('area'))
                              for a in engine.action_catalog.values() if a.owner_id == OWNER and 'Water Lash' in a.display_name]}
    c = rows[0]
    settle(lambda a: table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], a))


def test_decline_preserves_ordinary_lash_cost_and_cold_replay(tmp_path):
    combat, table, mid = native(tmp_path)
    combat, table, before = cold(tmp_path, mid)
    act(combat, table, mid, lance=False, target=WET)
    _, _, after = cold(tmp_path, mid)
    assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources
    assert len([e for e in after.events if e.event_type == 'ATTACK_ROLLED']) == 1
    assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in after.state.actors[WET].conditions.values())


def test_nonowner_has_no_pressure_lance_choice(tmp_path):
    combat, _, mid = native(tmp_path, owned=False)
    assert not any('Pressure Lance' in c.display_name for c in combat._load_session(mid).engine.legal_candidates())
    cold(tmp_path, mid)


def test_one_roll_independent_ac_line_length_and_width(tmp_path):
    combat, table, mid = native(tmp_path)
    combat, table, before = cold(tmp_path, mid)
    act(combat, table, mid)
    _, _, after = cold(tmp_path, mid)
    rolls = [e for e in after.events[len(before.events):] if e.event_type == 'ATTACK_ROLLED']
    assert len(rolls) == 1, [(e.target_ids, e.payload) for e in rolls]
    assert before.state.actors[OWNER].resources['resource:core.qi'] - after.state.actors[OWNER].resources['resource:core.qi'] == 1
    assert after.state.actors[WET].current_hp < before.state.actors[WET].current_hp
    assert after.state.actors[DRY].current_hp < before.state.actors[DRY].current_hp
    assert after.state.actors[MISS].current_hp == before.state.actors[MISS].current_hp
    assert after.state.actors[SIDE].current_hp == before.state.actors[SIDE].current_hp


def test_extra_die_from_prior_native_lash_pre_soaked_state(tmp_path):
    combat, table, mid = native(tmp_path)
    act(combat, table, mid, lance=False, target=WET)
    end(table, mid); turn(table, mid)
    combat, table, before = cold(tmp_path, mid)
    assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in before.state.actors[WET].conditions.values())
    assert not any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in before.state.actors[DRY].conditions.values())
    act(combat, table, mid)
    _, _, after = cold(tmp_path, mid)
    damage = [e for e in after.events[len(before.events):] if e.event_type == 'DAMAGE_ROLLED']
    for target, count in ((WET, 2), (DRY, 1)):
        packets = [e for e in damage if target in e.target_ids]
        assert len(packets) == 1, [e.payload for e in packets]
        packet = packets[0].payload
        expected = count * (2 if packet.get('critical') else 1)
        assert packet['expression'] == f'{expected}d8+2', packet


def test_recorded_line_object_takes_normal_native_damage(tmp_path):
    combat, table, mid = native(tmp_path)
    combat, table, before = cold(tmp_path, mid)
    obj = before.state.objects['object:map.81']
    act(combat, table, mid)
    _, _, after = cold(tmp_path, mid)
    updates = [e for e in after.events[len(before.events):] if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage')]
    assert updates, 'Pressure Lance damaged creatures but delivered no real object damage packet'
    assert after.state.objects[obj.object_id].current_hp < obj.current_hp


def test_payment_once_and_insufficient_after_real_native_uses(tmp_path):
    combat, table, mid = native(tmp_path)
    combat, table, before = cold(tmp_path, mid)
    assert before.state.actors[OWNER].resources['resource:core.qi'] == 2
    for remaining in (1, 0):
        act(combat, table, mid)
        combat, table, engine = cold(tmp_path, mid)
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == remaining
        end(table, mid); turn(table, mid)
        combat, table, engine = cold(tmp_path, mid)
    assert not any('Pressure Lance' in c.display_name for c in engine.legal_candidates())
    assert any(c.display_name == 'Water Lash' for c in engine.legal_candidates())


@pytest.mark.parametrize('blocked', [False, True], ids=['clear', 'total-cover'])
def test_native_line_all_creatures_length_width_and_cover(tmp_path, blocked):
    combat, table, mid = native(tmp_path, blocked=blocked)
    combat, table, before = cold(tmp_path, mid)
    act(combat, table, mid, aim=(8, 3))
    _, _, after = cold(tmp_path, mid)
    rolls = [e for e in after.events[len(before.events):] if e.event_type == 'ATTACK_ROLLED']
    recipients = {tid for e in rolls for tid in e.target_ids}
    assert {WET, DRY} <= recipients, recipients
    assert (MISS in recipients) is (not blocked), recipients
    assert SIDE not in recipients, recipients
    # Dry is a friend in the line: printed "each creature" is not enemy-only.
    assert after.state.actors[DRY].team_id == after.state.actors[OWNER].team_id
    assert after.state.actors[DRY].current_hp < before.state.actors[DRY].current_hp
    assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in after.state.actors[DRY].conditions.values())
