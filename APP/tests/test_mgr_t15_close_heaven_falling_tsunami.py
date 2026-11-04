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


def document(name, *, owned=False, cl=15, key_mod=5, save=-100):
    return {'identity': {'name': name, 'display_name': name, 'cultivation_level': cl,
                        'proficiency_bonus': 5, 'path': 'Qi Cultivation', 'key_ability': 'INT'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 10 + 2 * key_mod if a == 'INT' else 14,
                          'modifier': key_mod if a == 'INT' else 2}
                         for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'saving_throws': {'STR': save},
            'primary_resource': {'name': 'Qi', 'maximum': key_mod * cl},
            'armor_class': {'base_value': 12}, 'hit_points': {'maximum': 200},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 13 + key_mod, 'technique_attack_bonus': 5 + key_mod},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
            'learned_talent_record_ids': ['TAL_WATER_FLOWING_STEP', *([SOURCE] if owned else [])],
            'automatic_sphere_component_record_ids': [
                'WATER_BASE_WATER_INITIATION', 'WATER_BASE_WATER_LASH', 'WATER_BASE_SHAPE_CURRENT']}}


def _objects(patch):
    rows = [{'id': 81, 'kind': 'crate', 'x': 7, 'y': 6, 'blocks': False, 'hp': 200, 'ac': 12, 'unattended': True},
            {'id': 82, 'kind': 'wall_section', 'x': 10, 'y': 6, 'blocks': False, 'hp': 200, 'ac': 12, 'threshold': 1, 'unattended': True},
            {'id': 83, 'kind': 'crate', 'x': 7, 'y': 11, 'blocks': False, 'hp': 200, 'ac': 12, 'unattended': True},
            *[{'id': oid, 'kind': 'crate', 'x': x, 'y': 6, 'blocks': False, 'hp': 200, 'ac': 12, 'unattended': True}
              for oid, x in ((84, 26), (85, 27), (86, 14), (87, 15))]]
    return [{**row, **(patch or {}).get(row['id'], {})} for row in rows]


def setup(tmp_path, *, owned=True, cl=15, key_mod=5, save=-100, wall=False, journey=False, patch=None):
    for path in RUNTIME_DEPENDENCIES:
        assert (APP / path).is_file(), path
    for pid, name in zip(('00000011', '00000012', '00000013'), ('Tidecaller', 'Recipient', 'Excluded')):
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(
                name, owned=owned and pid == '00000011', cl=cl, key_mod=key_mod, save=save)))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, set())
    combat = CombatService(APP, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Tsunami acceptance',
        'width_squares': 30, 'height_squares': 13,
        'starts': {'team1': [[2, 6]], 'team2': [[6, 6], [6, 7]]},
        'walls': ([{'shape': 'line', 'points': [[8, 4], [8, 9]], 'blocks': 'sight_and_movement'}] if wall else []),
        'objects': _objects(patch)})
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


def cast(combat, table, mid, shape='line', distance='30', recipients=None, erosion=None):
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
         'choice:needle.displacement_distance': [distance],
         **({'choice:needle.scouring_erosion': [erosion]} if erosion else {})})


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
    assert after.state.objects['object:map.82'].component['structure']
    assert 200 - after.state.objects['object:map.82'].current_hp == object_damage
    assert after.state.objects['object:map.83'].current_hp == 200
    assert (after.state.objects['object:map.84'].current_hp < 200) is (shape == 'line')
    assert after.state.objects['object:map.85'].current_hp == 200
    assert after.state.objects['object:map.86'].current_hp < 200
    assert (after.state.objects['object:map.87'].current_hp < 200) is (shape == 'line')
    assert not [c for c in after.legal_candidates() if c.source_definition_id in {a.source_definition_id for a in actions(after)}]
    assert {(a.parameters['typed']['area']['shape'], a.parameters['typed']['area']['size_ft'])
            for a in actions(after)} == {('line', 120), ('cone', 60)}
    if save < 0:
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.displacement_distance')
        assert {str(i) for i in range(0, 61, 5)} == {o['id'] for o in prompt['choice']['options']}
        assert 'Heaven-Falling Tsunami' in str(prompt) and 'Recipient' in str(prompt)
        pressure = [c for c in b.conditions.values() if c.condition_id.startswith('condition:typed.mark.drowning_pressure.')]
        assert pressure and pressure[0].expires_on == 'END_OF_HOLDER_NEXT_TURN'
        turn(table, mid, B); end(table, mid)
        _, _, expired = cold(tmp_path, mid)
        assert not any(c.condition_id.startswith('condition:typed.mark.drowning_pressure.') for c in expired.state.actors[B].conditions.values())
    if save >= 0:
        end(table, mid)
    turn(table, mid, A)
    _, _, later = cold(tmp_path, mid)
    ids = {a.source_definition_id for a in actions(later)}
    assert later.state.actors[A].action_available
    assert not any(c.source_definition_id in ids for c in later.legal_candidates()), 'Both shapes spent the same use'


@pytest.mark.parametrize('case', ['no-owner', 'below-realm'])
def test_admission_boundaries(tmp_path, case):
    combat, _, mid = setup(tmp_path, owned=case != 'no-owner',
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
    jid = setup(tmp_path, journey=True, key_mod=1)
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
    # A legal CL15 cultivator with INT12 starts with 15 Qi. Three real
    # five-Qi activations spend it; Long Rests here recover only this use.
    state = finish(mid)
    state = service().journey_act(jid, state['revision'], A, 'long_rest', {})
    combat, table, mid = fight()
    cast(combat, table, mid, recipients=[])
    state = finish(mid)
    assert state['actors'][A]['resources']['resource:core.qi'] == 0
    state = service().journey_act(jid, state['revision'], A, 'long_rest', {})
    combat, table, mid = fight()
    _, _, empty = cold(tmp_path, mid)
    ids = {a.source_definition_id for a in actions(empty)}
    assert not any(c.source_definition_id in ids for c in empty.legal_candidates()), 'A restored use still requires five Qi'


@pytest.mark.parametrize('equal', [True, False], ids=['equals-dc-succeeds', 'one-below-dc-fails'])
def test_actual_save_threshold(tmp_path, equal):
    # Determine this seed's native d20 in a separate source-shaped initial fight,
    # then import the save-total control that puts exactly that roll on the edge.
    # No roller or saved fight state is edited.
    combat, table, mid = setup(tmp_path / 'reference', save=0)
    cast(combat, table, mid, distance='0')
    _, _, reference = cold(tmp_path / 'reference', mid)
    rolled = next(e for e in reference.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == B)
    natural = rolled.payload['natural_result']
    modifier = 18 - natural - (0 if equal else 1)
    combat, table, mid = setup(tmp_path / 'boundary', save=modifier)
    cast(combat, table, mid, distance='0')
    _, _, engine = cold(tmp_path / 'boundary', mid)
    rolled = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == B)
    assert rolled.payload['natural_result'] == natural
    assert rolled.payload['total'] == (18 if equal else 17)
    assert rolled.payload['success'] is equal
    assert any(c.condition_id.startswith('condition:typed.mark.drowning_pressure.')
               for c in engine.state.actors[B].conditions.values()) is (not equal)


def test_failure_push_stops_at_actual_wall(tmp_path):
    combat, table, mid = setup(tmp_path, wall=True)
    cast(combat, table, mid, distance='60')
    _, _, engine = cold(tmp_path, mid)
    target = engine.state.actors[B]
    assert 6 < target.position.x < 8 and target.position.y == 6
    assert not any(e.event_type == 'OPPORTUNITY_ATTACK' for e in engine.events)


def test_scouring_erosion_is_offered_to_gm_for_qualified_objects_only(tmp_path):
    combat, table, mid = setup(tmp_path)
    prompts = cast(combat, table, mid)
    offered = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.scouring_erosion']
    assert offered, 'GM Scouring Erosion choice missing for struck qualified objects'
    assert all('Scouring Erosion' in str(p) for p in offered)
    assert 'object:map.81' not in offered[0]['moment']
    assert 'Crate' in offered[0]['moment']
    assert {o['id'] for o in offered[0]['choice']['options']} == {'bypass', 'double'}
    _, _, engine = cold(tmp_path, mid)
    assert engine.state.objects['object:map.83'].current_hp == 200


def test_gm_declined_erosion_leaves_ordinary_object_damage(tmp_path):
    combat, table, mid = setup(tmp_path)
    prompts = cast(combat, table, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.scouring_erosion' for p in prompts)
    _, _, declined = cold(tmp_path, mid)
    base_hp = declined.state.objects['object:map.81'].current_hp
    assert 200 - base_hp >= 8


def test_gm_approved_double_erosion_doubles_once_and_survives_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    cast(combat, table, mid)
    _, _, declined = cold(tmp_path, mid)
    declined_damage = 200 - declined.state.objects['object:map.81'].current_hp

    root = tmp_path / 'approved'; root.mkdir()
    combat2, table2, mid2 = setup(root)
    prompts = cast(combat2, table2, mid2, erosion='double')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.scouring_erosion' for p in prompts)
    _, _, approved = cold(root, mid2)
    approved_damage = 200 - approved.state.objects['object:map.81'].current_hp
    assert approved_damage == 2 * declined_damage
    assert approved.state.objects['object:map.83'].current_hp == 200



def test_runtime_authority_carries_reviewed_tsunami_shapes_and_optional_push():
    row = json.loads((APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][SOURCE]
    assert row['min_cl'] == 15
    assert {o['area']['shape'] for o in row['options']} == {'line', 'cone'}
    assert '"optional_distance_ft": true' in json.dumps(row['options'])


@pytest.mark.parametrize('material', ['clay', 'mud', 'salt', 'ash'])
def test_printed_erosion_materials_reach_the_gm(tmp_path, material):
    combat, table, mid = setup(tmp_path, patch={81: {'material': material, 'name': f'Test {material.title()} Object'}})
    loaded = combat._load_session(mid).engine.state.objects['object:map.81']
    assert loaded.component['material'] == material
    prompts = cast(combat, table, mid)
    offered = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.scouring_erosion']
    assert any(f'mundane {material} object' in p['moment'] for p in offered), offered


def test_mundane_fragile_barrier_reaches_the_gm(tmp_path):
    combat, table, mid = setup(tmp_path, patch={82: {'material': 'glass', 'name': 'Test Glass Barrier', 'fragile': True}})
    loaded = combat._load_session(mid).engine.state.objects['object:map.82']
    assert loaded.component['material'] == 'glass' and loaded.component['structure']
    prompts = cast(combat, table, mid)
    offered = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.scouring_erosion']
    assert any('Test Glass Barrier' in p['moment'] and 'mundane glass object' in p['moment'] for p in offered), offered
