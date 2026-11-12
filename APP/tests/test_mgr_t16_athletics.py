"""MGR-T16 row regressions: real table transactions and fresh-service reloads.

No browser or model server is used. The map is authored and sealed at creation;
tests never replace a live engine's geometry or bypass movement admission.
"""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import athletics
from tests.auto8f1_table_support import OWNER, FOE, reload_identical
from tests.h1_support import ROOT, sheet

GLIDE = 'TAL_ATHLETICS_TERRAIN_GLIDE'
SHARK = 'TAL_ATHLETICS_SHARK_SWIM'
MULTIPLE = 'TAL_ATHLETICS_MULTIPLE_MOTIONS'
AFTERIMAGE = 'TAL_ATHLETICS_AFTERIMAGE'
MOVING = 'TAL_ATHLETICS_MOVING_TARGET'
MOBILITY = 'TAL_ATHLETICS_MOBILITY'
FOCUS = 'resource:core.martial_focus'


def game(tmp_path, talents, *, material=None, sealed=False, mode='MANUAL', focus=1, height_ft=None, zone_terrain=None, ask=True, prepare=None, floor_material=None, arena_update=None, starting_z=0):
    bundles = []
    for aid, known in ((OWNER, talents), (FOE, [])):
        doc = sheet(known, cl=17, primary='Stamina')
        doc['identity']['display_name'] = 'Swimmer' if aid == OWNER else 'Observer'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 400
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={'ask': ask})
        if aid == OWNER:
            for resource in bundle['actor_template']['resources']:
                if resource['resource_id'] == FOCUS:
                    resource['initial'] = focus
        bundles.append(bundle)
    if prepare:
        prepare(bundles)
    service = CombatService(ROOT, tmp_path)
    arena = dict(service.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena.update(terrain_regions=[], map_terrain=[])
    if floor_material:
        arena['terrain_regions'] = [{'region_id': 'floor', 'terrain_type': 'OPEN',
            'material_only': True, 'material': floor_material,
            'cells': [{'x': x, 'y': y} for x in range(16) for y in range(14)]}]
    if zone_terrain:
        arena['map_terrain'] = [{'terrain': zone_terrain, 'cells': [[4, 6]]}]
    if material is not None:
        # A complete band cannot be routed around. Sight remains blocked.
        arena['terrain_regions'] = [{'region_id': 'earth', 'terrain_type': 'BLOCKED',
            'cells': [{'x': 4, 'y': y} for y in range(14)], 'movement_cost': 0,
            'material': material, 'sealed': sealed, 'description': 'Authored medium'}]
        if height_ft is not None:
            arena['terrain_regions'][0]['height_ft'] = height_ft
    if arena_update:
        arena.update(arena_update)
    mid = service._finish_factory_match(bundles, [OWNER, FOE], {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6, 'z': starting_z}, FOE: {'x': 15, 'y': 6}}, arena, [OWNER], [FOE],
        control_modes={OWNER: mode, FOE: 'MANUAL'}, match_seed='MGR-T16',
        display_name='MGR-T16 regression', maximum_rounds=10)['match_id']
    table = TabletopService(service, tmp_path)
    for _ in range(10):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == OWNER:
            break
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])['status'] == 'COMMITTED'
    return service, table, mid


def commit(table, mid, move, choose=None):
    answers, prompts = [], []
    for _ in range(15):
        menu = table.state(mid)['menu']
        result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        options = choose(prompt) if choose else []
        answer = {**prompt['context'], 'selection': 'USE' if options else 'DECLINE'}
        if options:
            answer['option_ids'] = options
        answers.append(answer)
    raise AssertionError('Movement never committed')


def move_at(table, mid, x, y=6, mode=None, z=0):
    return next(move for move in table.state(mid)['menu']['moves']
                if move['destination']['x'] == x and move['destination']['y'] == y
                and move['destination'].get('z', 0) == z
                and (mode is None or move['movement_mode'] == mode))


@pytest.mark.parametrize('material', ['soil', 'snow', 'loose earth', 'sand'])
def test_each_glide_medium_is_on_move_picker_and_commits_after_reload(tmp_path, material):
    service, table, mid = game(tmp_path, [SHARK, GLIDE], material=material)
    move = move_at(table, mid, 5, mode='swim')
    assert move['cost_ft'] == 15
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert cold.grid.materials_at((4, 6, 0))[0]['material'] == material
    assert not cold.grid.line_of_sight(cold.state.actors[OWNER].position, cold.state.actors[FOE].position)
    commit(table, mid, move)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].position.x == 5
    receipt = next(e for e in reversed(fresh.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    assert receipt.payload['cost_ft'] == 15 and receipt.payload['movement_mode'] == 'swim'
    reload_identical(service, mid, tmp_path)


def test_difficult_medium_consumes_double_and_can_end_inside_it(tmp_path):
    service, table, mid = game(tmp_path, [SHARK, GLIDE], material='soil')
    move = move_at(table, mid, 4, mode='swim')
    assert move['cost_ft'] == 10
    before = service._load_session(mid).engine.state.actors[OWNER].movement_remaining_ft
    commit(table, mid, move)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].movement_remaining_ft == before - 10
    assert fresh.state.actors[OWNER].position.x == 4
    reload_identical(service, mid, tmp_path)


@pytest.mark.parametrize('material,sealed,owns', [('stone', False, True), ('worked stone', False, True),
    ('metal', False, True), ('wood', False, True), ('soil', True, True), ('soil', False, False), ('', False, True)])
def test_unowned_and_excluded_barriers_remain_blocking(tmp_path, material, sealed, owns):
    _, table, mid = game(tmp_path, [SHARK, GLIDE] if owns else [], material=material, sealed=sealed)
    assert all(move['destination']['x'] < 4 for move in table.state(mid)['menu']['moves'])


def test_one_focus_binds_two_motions_to_one_sequence_and_both_apply(tmp_path):
    service, table, mid = game(tmp_path, [MULTIPLE, AFTERIMAGE, MOVING, MOBILITY])
    prompts = commit(table, mid, move_at(table, mid, 8), lambda p:
                     ['two'] if 'motion_count' in p['context']['reaction_source_id'] else [AFTERIMAGE, MOVING])
    assert len(prompts) == 2
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    owner = fresh.state.actors[OWNER]
    assert owner.resources[FOCUS] == 0
    assert any(c.condition_id == 'condition:typed.afterimage' for c in owner.conditions.values())
    assert athletics._moving_target(fresh, owner) == 2
    receipt = next(e for e in reversed(fresh.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    assert receipt.payload['movement_selections']['motion'] == [AFTERIMAGE, MOVING]
    assert not hasattr(fresh, '_movement_sequence') or fresh._movement_sequence is None
    reload_identical(service, mid, tmp_path)


def test_player_composition_prompt_lists_all_owned_motions_and_single_is_free(tmp_path):
    service, table, mid = game(tmp_path, [MULTIPLE, AFTERIMAGE, MOVING, MOBILITY])
    def choose(prompt):
        assert 'Multiple Motions' in str(prompt) and 'Martial Focus' in str(prompt)
        if 'motion_count' in prompt['context']['reaction_source_id']:
            return ['one']
        assert {o['id'] for o in prompt['choice']['options']} == {AFTERIMAGE, MOVING, MOBILITY}
        return [MOBILITY]
    prompts = commit(table, mid, move_at(table, mid, 8), choose)
    assert len(prompts) == 2
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    owner = fresh.state.actors[OWNER]
    assert owner.resources[FOCUS] == 1
    assert not any(c.condition_id == 'condition:typed.afterimage' for c in owner.conditions.values())
    assert athletics._moving_target(fresh, owner) == 0
    reload_identical(service, mid, tmp_path)


def test_no_focus_only_offers_one_motion_and_does_not_spend(tmp_path):
    service, table, mid = game(tmp_path, [MULTIPLE, AFTERIMAGE, MOVING], focus=0)
    prompts = commit(table, mid, move_at(table, mid, 8), lambda p: [MOVING])
    assert len(prompts) == 1
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].resources[FOCUS] == 0
    assert athletics._moving_target(fresh, fresh.state.actors[OWNER]) == 2
    assert not any(c.condition_id == 'condition:typed.afterimage'
                   for c in fresh.state.actors[OWNER].conditions.values())
    reload_identical(service, mid, tmp_path)


def test_material_route_preview_and_commit_use_same_law(tmp_path):
    service, table, mid = game(tmp_path, [SHARK, GLIDE], material='sand')
    menu = table.state(mid)['menu']
    path = [{'x': 3, 'y': 6}, {'x': 4, 'y': 6}]
    quoted = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], OWNER, path, 'swim')
    assert quoted['candidate']['movement_cost_ft'] == 10
    result = table.commit_move_path(mid, quoted['candidate']['candidate_id'], menu['decision_id'],
                                   menu['state_version'], OWNER, path, movement_mode='swim')
    assert result['status'] == 'COMMITTED'
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER].position.x == 4
    reload_identical(service, mid, tmp_path)


def test_editor_materials_are_preserved_and_never_relabel_overlapping_walls():
    from combat.gate2_grid import SquareGrid
    from combat.tabletop import normalize_map, to_battlefield, table_section
    document = normalize_map({'display_name': 'Materials', 'width_squares': 16, 'height_squares': 10,
        'materials': [{'material': 'floor:sand', 'cells': [[4, 4]]},
                      {'material': 'terrain:mundane snow', 'cells': [[5, 4]]}],
        'terrain': [{'type': 'DIFFICULT', 'material': 'loose-earth', 'sealed': True, 'cells': [[6, 4]]}],
        'walls': [{'shape': 'rect', 'points': [[4, 4], [5, 5]], 'filled': True}]})
    grid = SquareGrid(to_battlefield(document))
    assert {'', 'sand'} <= {row['material'] for row in grid.materials_at((4, 4, 0))}
    assert 'snow' in {row['material'] for row in grid.materials_at((5, 4, 0))}
    terrain = table_section(document)['terrain'][0]
    assert terrain['material'] == 'loose earth' and terrain['sealed'] is True
    # A matter annotation must not make ordinary difficult ground cheaper.
    document['materials'].append({'material': 'floor:sand', 'cells': [[6, 4]]})
    assert SquareGrid(to_battlefield(document)).base_movement_cost[(6, 4)] == 2
    annotated = to_battlefield(document)
    annotated['terrain_regions'].append({'region_id': 'annotation', 'terrain_type': 'BLOCKED',
        'material_only': True, 'material': 'soil', 'movement_cost': 0, 'cells': [{'x': 7, 'y': 4}]})
    assert (7, 4) not in SquareGrid(annotated).blocked
    from combat.gate2_runtime_models import Position
    assert SquareGrid(annotated).line_of_sight(Position(x=7, y=3), Position(x=7, y=5))


def test_named_terrain_zone_material_query_and_traversal_survive_reload(tmp_path):
    from combat.terrain_materials import query
    service, table, mid = game(tmp_path, [SHARK, GLIDE], material='soil', zone_terrain='mundane snow')
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert {'soil', 'snow'} <= {row['material'] for row in query(engine, (4, 6, 0))}
    commit(table, mid, move_at(table, mid, 4, mode='swim'))
    reload_identical(service, mid, tmp_path)


def test_material_grants_union_without_losing_another_providers_permission(monkeypatch):
    from types import SimpleNamespace
    from combat import ext, terrain_materials
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'material_traversal', [
        lambda *a: {'mode': 'swim', 'materials': ['soil'], 'difficult_materials': ['soil']},
        lambda *a: {'mode': 'swim', 'materials': ['soil', 'sand'], 'difficult_materials': ['sand']},
    ])
    profile = terrain_materials.profile(SimpleNamespace(), SimpleNamespace(entity_id=OWNER), 'swim')
    assert set(profile['materials']) == {'soil', 'sand'}
    assert profile['difficult_materials'] == ('sand',)


def test_swimming_within_a_raised_medium_does_not_grant_flight_or_fall(tmp_path):
    service, table, mid = game(tmp_path, [SHARK, GLIDE], material='soil')
    moves = table.state(mid)['menu']['moves']
    raised = next(m for m in moves if m['destination'] == {'x': 4, 'y': 6, 'z': 1}
                  and m['movement_mode'] == 'swim')
    assert not any(m['destination'] == {'x': 3, 'y': 6, 'z': 1} and m['movement_mode'] == 'swim' for m in moves)
    commit(table, mid, raised)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].position.z == 1
    reload_identical(service, mid, tmp_path)


def test_material_mode_does_not_grant_a_free_climb_onto_stone(tmp_path):
    _, table, mid = game(tmp_path, [SHARK, GLIDE], material='stone', height_ft=5)
    assert not any(m['destination'].get('z', 0) for m in table.state(mid)['menu']['moves']
                   if m['movement_mode'] == 'swim')


def test_ai_policy_composes_and_persists_without_a_player_answer(tmp_path):
    from combat.gate4_context import build_reaction_context
    from combat.gate2_runtime_models import ActionIntent
    service, _, mid = game(tmp_path, [MULTIPLE, AFTERIMAGE, MOVING], mode='LOCAL_AUTO')
    session = service._load_session(mid)
    engine = session.engine
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                     and c.destination.x == 8 and c.destination.y == 6)
    decisions = []
    def policy(request):
        actor_policy, _ = session.persistence.policy_library.for_actor(request['reactor_id'])
        context = build_reaction_context(engine, actor_policy, request)
        chosen = session.persistence.local_controller.choose_reaction(context)
        decisions.append(chosen.decision)
        return chosen.decision, chosen.record.model_dump(mode='json', by_alias=True)
    intent = ActionIntent(intent_id='mgr-t16-ai-move', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=OWNER, destination=candidate.destination)
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=policy)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    owner = fresh.state.actors[OWNER]
    assert len(decisions) == 2 and owner.resources[FOCUS] == 0
    assert athletics._moving_target(fresh, owner) == 2
    assert any(c.condition_id == 'condition:typed.afterimage' for c in owner.conditions.values())
    reload_identical(service, mid, tmp_path)


def test_manual_composition_is_asked_on_another_actors_turn_without_a_reaction_plan(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    service, table, mid = game(tmp_path, [MULTIPLE, AFTERIMAGE, MOVING], ask=False)
    menu = table.state(mid)['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])['status'] == 'COMMITTED'
    menu = table.state(mid)['menu']
    assert menu['actor_id'] == FOE
    def grant(engine, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == FOE:
            owner = engine.state.actors[OWNER]
            engine.grant_movement(owner, (owner.position, owner.position.model_copy(update={'x': 4})),
                                  'test:granted-step', feet=5, intent=engine._active_intent)
    install(monkeypatch, 'event', grant)
    candidate = next(c for c in service._load_session(mid).engine.legal_candidates() if c.kind == 'HOLD_POSITION')
    prompts = commit(table, mid, {'candidate_id': candidate.candidate_id}, lambda p:
                     ['two'] if 'motion_count' in p['context']['reaction_source_id'] else [AFTERIMAGE, MOVING])
    assert len(prompts) == 2
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.current_actor_id == FOE
    assert fresh.state.actors[OWNER].position.x == 4 and fresh.state.actors[OWNER].resources[FOCUS] == 0
    reload_identical(service, mid, tmp_path)
