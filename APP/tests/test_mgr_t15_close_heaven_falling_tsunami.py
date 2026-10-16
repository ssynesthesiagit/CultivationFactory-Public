"""Tsunami through portable import, legal table intents, cold verification and replay.

Source-shaped initial Nascent Soul Qi cultivator; opponent saves are explicit
low/high controls. No installed benefit, receipt, runtime patch or private fixture.
The source's unresolved pressure options and GM erosion authority are not guessed.
"""
import json
import zipfile
from pathlib import Path

import pytest
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService

APP = Path(__file__).resolve().parents[1]
SOURCE = 'TAL_WATER_HEAVEN_FALLING_TSUNAMI'
A, B, C = ['actor:factory.' + p for p in ('00000011', '00000012', '00000013')]
RUNTIME_DEPENDENCIES = (
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/Tianxia_Forged_Technique_Authority_R1.json',
    'catalog_authority/cat3/generated/catalog_authority.v1.json',
    'combat/rules/feature_blocks.d/sysv2_objects.json',
    'combat/rules/feature_blocks.d/a2_water.json',
    'combat/rules/objects.json',
)


def document(name, *, owned=False, cl=15, cp=None, save=-100):
    return {'identity': {'name': name, 'display_name': name, 'cultivation_level': cl,
                        'proficiency_bonus': 5, 'path': 'Qi Cultivation', 'key_ability': 'INT'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 20 if a == 'INT' else 14,
                          'modifier': 5 if a == 'INT' else 2}
                         for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'saving_throws': {'STR': save},
            'primary_resource': {'name': 'Qi', 'maximum': 5 * cl if cp is None else cp},
            'armor_class': {'base_value': 12}, 'hit_points': {'maximum': 200},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 18, 'technique_attack_bonus': 10},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
            'learned_talent_record_ids': ['TAL_WATER_FLOWING_STEP', *([SOURCE] if owned else [])],
            'automatic_sphere_component_record_ids': [
                'WATER_BASE_WATER_INITIATION', 'WATER_BASE_WATER_LASH', 'WATER_BASE_SHAPE_CURRENT']}}


def setup(tmp_path, *, owned=True, cl=15, cp=None, save=-100, wall=False, journey=False):
    for path in RUNTIME_DEPENDENCIES:
        assert (APP / path).is_file(), path
    for pid, name in zip(('00000011', '00000012', '00000013'), ('Tidecaller', 'Recipient', 'Excluded')):
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(
                name, owned=owned and pid == '00000011', cl=cl, cp=cp, save=save)))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, set())
    combat = CombatService(APP, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Tsunami acceptance',
        'width_squares': 30, 'height_squares': 13,
        'starts': {'team1': [[2, 6]], 'team2': [[6, 6], [6, 7]]},
        'walls': ([{'shape': 'line', 'points': [[8, 4], [8, 9]], 'blocks': 'sight_and_movement'}] if wall else []),
        'objects': [{'id': 81, 'kind': 'crate', 'x': 7, 'y': 6, 'blocks': False, 'hp': 200, 'ac': 12,
                     'unattended': True},
                    {'id': 82, 'kind': 'crate', 'x': 10, 'y': 6, 'blocks': False, 'hp': 200, 'ac': 12,
                     'unattended': True},
                    {'id': 83, 'kind': 'crate', 'x': 7, 'y': 11, 'blocks': False, 'hp': 200, 'ac': 12,
                     'unattended': True}]})
    arena_id = 'battlefield:map.' + arena['map_id']
    if journey:
        state = combat.create_journey(project_ids=['00000011', '00000012', '00000013'], arena_id=arena_id,
            positions={A: {'x': 2, 'y': 6}, B: {'x': 6, 'y': 6}, C: {'x': 6, 'y': 7}},
            base_paces={a: 5 for a in (A, B, C)}, control_modes={a: 'MANUAL' for a in (A, B, C)})
        return state['journey_id']
    mid = combat.create_factory_match(project_ids=['00000011'], opponent_actor_ids=[B, C],
        control_modes={a: 'MANUAL' for a in (A, B, C)}, arena_id=arena_id,
        match_seed='tsunami-native')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, A)
    return combat, table, mid


def settle(send, picks=None):
    answers, prompts = [], []
    for _ in range(30):
        result = send(answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        chosen = (picks or {}).get(rid)
        answers.append({**p['context'], 'selection': 'USE' if chosen is not None else 'DECLINE',
                        'option_ids': chosen or []})
    raise AssertionError('Tsunami did not commit')


def end(table, mid):
    state = table.state(mid); menu = state['menu']
    settle(lambda a: table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'], a))


def turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor: return
        end(table, mid)
    raise AssertionError('turn unavailable')


def cold(tmp_path, mid):
    combat = CombatService(APP, tmp_path)
    loaded = combat._load_session(mid)
    replay = loaded.mechanical.replay()
    assert replay['status'] == 'PASS'
    assert loaded.verify()['canonical_state_sha256'] == replay['canonical_state_sha256']
    return combat, TabletopService(combat, tmp_path), loaded.engine


def actions(engine):
    return [a for a in engine.action_catalog.values()
            if a.owner_id == A and a.parameters.get('typed', {}).get('source') == SOURCE]


def cast(combat, table, mid, shape='line', distance='30', recipients=None):
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    aids = {a.source_definition_id for a in actions(engine)
            if a.parameters['typed']['area']['shape'] == shape}
    rows = [c for c in engine.legal_candidates() if c.source_definition_id in aids and c.destination
            and (c.destination.x, c.destination.y) == (14, 6)]
    assert rows, f'No legal Tsunami {shape} at chosen aim'
    c = rows[0]
    return settle(lambda a: table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], a),
        {'choice:needle.area_recipients': [B] if recipients is None else recipients,
         'choice:needle.displacement_distance': [distance]})


@pytest.mark.parametrize('shape', ['line', 'cone'])
@pytest.mark.parametrize('save', [-100, 100], ids=['failure', 'success'])
def test_both_areas_save_branches_objects_choice_payment_and_replay(tmp_path, shape, save):
    combat, table, mid = setup(tmp_path, save=save)
    _, _, before = cold(tmp_path, mid)
    prompts = cast(combat, table, mid, shape=shape)
    _, table, after = cold(tmp_path, mid)
    a, b, c = [after.state.actors[x] for x in (A, B, C)]
    assert before.state.actors[A].resources['resource:core.qi'] - a.resources['resource:core.qi'] == 5
    assert not a.action_available
    assert c.current_hp == before.state.actors[C].current_hp
    saves = [e for e in after.events[len(before.events):] if e.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and saves[0].actor_id == B
    assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in b.conditions.values())
    assert any(c.condition_id == 'prone' or c.condition_id.endswith('.prone') for c in b.conditions.values()) is (save < 0)
    damage = before.state.actors[B].current_hp - b.current_hp
    object_damage = 200 - after.state.objects['object:map.81'].current_hp
    assert 8 <= object_damage <= 64
    assert damage == (object_damage if save < 0 else object_damage // 2)
    assert b.position.x == (12 if save < 0 else 9) and b.position.y == 6
    assert after.state.objects['object:map.83'].current_hp == 200
    assert not [c for c in after.legal_candidates() if c.source_definition_id in {a.source_definition_id for a in actions(after)}]
    if save < 0:
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.displacement_distance')
        assert {str(i) for i in range(0, 61, 5)} == {o['id'] for o in prompt['choice']['options']}
        assert 'Heaven-Falling Tsunami' in str(prompt) and 'Recipient' in str(prompt)
        pressure = [c for c in b.conditions.values() if c.condition_id.startswith('condition:typed.mark.drowning_pressure.')]
        assert pressure and pressure[0].expires_on == 'END_OF_HOLDER_NEXT_TURN'
        turn(table, mid, B); end(table, mid)
        _, _, expired = cold(tmp_path, mid)
        assert not any(c.condition_id.startswith('condition:typed.mark.drowning_pressure.') for c in expired.state.actors[B].conditions.values())


@pytest.mark.parametrize('case', ['no-owner', 'not-enough-cp', 'below-realm'])
def test_admission_boundaries(tmp_path, case):
    combat, _, mid = setup(tmp_path, owned=case != 'no-owner', cp=4 if case == 'not-enough-cp' else None,
                          cl=14 if case == 'below-realm' else 15)
    _, _, engine = cold(tmp_path, mid)
    ids = {a.source_definition_id for a in actions(engine)}
    assert not any(c.source_definition_id in ids for c in engine.legal_candidates())


def test_decline_creatures_still_damages_objects_and_wall_blocks_delivery(tmp_path):
    combat, table, mid = setup(tmp_path, wall=True)
    cast(combat, table, mid, recipients=[])
    _, _, engine = cold(tmp_path, mid)
    assert all(engine.state.actors[a].current_hp == 200 for a in (A, B, C))
    assert engine.state.objects['object:map.81'].current_hp < 200
    assert engine.state.objects['object:map.82'].current_hp == 200


def test_optional_zero_push(tmp_path):
    combat, table, mid = setup(tmp_path)
    cast(combat, table, mid, distance='0')
    _, _, engine = cold(tmp_path, mid)
    assert engine.state.actors[B].position.x == 6


def test_real_long_rest_recharges_shared_shape_use_after_two_encounters(tmp_path):
    jid = setup(tmp_path, journey=True)
    def service(): return CombatService(APP, tmp_path)
    def fight():
        state = service().journey_state(jid)
        mid = service().journey_start_combat(jid, state['revision'], {A: 'a', B: 'b', C: 'b'}, maximum_rounds=2,
            positions={A: {'x': 2, 'y': 6}, B: {'x': 6, 'y': 6}, C: {'x': 6, 'y': 7}})['match_id']
        combat, table, _ = cold(tmp_path, mid); turn(table, mid, A)
        return combat, table, mid
    def finish(mid):
        for _ in range(12):
            combat, table, engine = cold(tmp_path, mid)
            if engine.state.terminal_result is not None: break
            end(table, mid)
        assert engine.state.terminal_result is not None
        state = service().journey_state(jid)
        return service().journey_resume(jid, state['revision'])
    combat, table, mid = fight()
    cast(combat, table, mid, recipients=[])
    state = finish(mid)
    combat, table, mid = fight()
    _, _, engine = cold(tmp_path, mid)
    ids = {a.source_definition_id for a in actions(engine)}
    assert not any(c.source_definition_id in ids for c in engine.legal_candidates()), 'A new fight is not a Long Rest'
    state = finish(mid)
    prior = state['actors'][A]['resources'].copy()
    state = service().journey_act(jid, state['revision'], A, 'long_rest', {})
    assert state['seconds'] == 28800 and state['actors'][A]['long_rests'] == 1
    assert state['actors'][A]['resources']['resource:core.qi'] == prior['resource:core.qi'], 'Use recovery invents no CP'
    combat, table, mid = fight()
    cast(combat, table, mid, shape='cone', recipients=[])
    cold(tmp_path, mid)
