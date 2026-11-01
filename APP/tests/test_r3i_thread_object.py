"""Known-weight Thread movement uses real table choices and evented object replay."""
import pytest
from types import SimpleNamespace

from combat.ext import needle
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield, battlefield_as_map
from combat.tabletop_service import TabletopService
from tests.test_auto_lane1 import ROOT
from tests import test_sys_placed_effects as P
from tests import test_sysv2_objects as O


def _sheet():
    return P._sheet(P.PUPPET[3], cl=5)


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('destination', [(5, 6), (4, 6)])
def test_thread_object_table_choice_commit_reload(tmp_path, mode, destination):
    owner, foe = P.ME, 'actor:factory.thread-foe'
    documents = [_sheet(), _sheet()]
    documents[1]['spheres_and_talents'] = {}
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask': True})
               for d, a in zip(documents, [owner, foe])]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = to_battlefield(normalize_map({'display_name': 'Thread yard', 'width_squares': 20,
        'height_squares': 14, 'objects': [
            {'id': 1, 'kind': 'custom', 'name': 'Wooden bell', 'x': 4, 'y': 6, 'weight_lb': 10, 'blocks': False},
            {'id': 2, 'kind': 'custom', 'x': 4, 'y': 7, 'weight_lb': 11, 'blocks': False},
            {'id': 3, 'kind': 'custom', 'x': 5, 'y': 7, 'blocks': False},
            {'id': 4, 'kind': 'custom', 'x': 6, 'y': 7, 'weight_lb': 1, 'unattended': False, 'blocks': False}]}))
    mid = combat._finish_factory_match(bundles, [owner, foe], {owner: 'team:a', foe: 'team:b'},
        {owner: {'x': 3, 'y': 6}, foe: {'x': 6, 'y': 6}}, arena, [owner], [foe],
        control_modes={owner: mode, foe: 'LOCAL_AUTO'}, match_seed='R3I-THREAD',
        display_name='Thread yard', maximum_rounds=5)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    for _ in range(2):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == owner:
            break
        assert act(menu['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates() if c.display_name == 'Thread the Object: move object']
    assert {c.target_ids for c in candidates} == {('object:map.1',)}
    candidate = candidates[0]
    before = engine.state.model_dump(mode='json')
    result = act(candidate.candidate_id)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == owner
    assert 'Thread the Object' in prompt['moment'] and 'Wooden bell' in prompt['moment']
    ids = {o['id'] for o in prompt['choice']['options']}
    assert needle.cell_id(Position(x=4, y=6)) in ids  # zero feet remains optional
    chosen = needle.cell_id(Position(x=destination[0], y=destination[1]))
    assert chosen in ids
    assert needle.cell_id(Position(x=6, y=6)) not in ids  # occupied by a creature
    assert needle.cell_id(Position(x=4, y=7)) not in ids  # another owner's object remains
    assert needle.cell_id(Position(x=7, y=6)) not in ids  # over ten feet
    assert act(candidate.candidate_id)['reaction'] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [chosen]}
    assert act(candidate.candidate_id, [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.objects['object:map.1'].position == Position(x=destination[0], y=destination[1])
    assert loaded.engine.state.objects['object:map.1'].component['weight_lb'] == 10
    assert len([e for e in loaded.engine.events if e.event_type == 'OBJECT_UPDATED'
                and e.source_definition_id == candidate.source_definition_id]) == int(destination != (4, 6))
    for actor in [owner, foe]:
        assert loaded.engine.state.actors[actor].movement_remaining_ft == before['actors'][actor]['movement_remaining_ft']
        assert loaded.engine.state.actors[actor].resources == before['actors'][actor]['resources']
    for oid in ['object:map.2', 'object:map.3', 'object:map.4']:
        assert loaded.engine.state.objects[oid].model_dump(mode='json') == before['objects'][oid]
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('weight', [None, -1, 10.5, True, '10'])
def test_invalid_or_unknown_weight_never_establishes_eligibility(weight):
    document = normalize_map({'objects': [{'id': 1, 'kind': 'custom', 'x': 4, 'y': 6,
                                          'weight_lb': weight, 'blocks': False}]})
    assert 'weight_lb' not in document['objects'][0]
    assert 'weight_lb' not in battlefield_as_map(to_battlefield(document))['objects'][0]
    engine = O.fight(compile_character(_sheet(), actor_id=O.ME), objects=document['objects'])
    assert not O.candidates(engine, 'Thread the Object: move object')


def test_nonowners_and_blocking_objects_remain_inert():
    rows = [{'id': 1, 'kind': 'door', 'x': 4, 'y': 6, 'weight_lb': 1}]
    assert not O.candidates(O.fight(compile_character(_sheet(), actor_id=O.ME), objects=rows), 'Thread the Object: move object')
    assert not O.candidates(O.fight(O.build(None, []), objects=rows), 'Thread the Object: move object')


def test_automatic_owner_resolves_without_prompt_or_creature_movement(tmp_path):
    engine = O.fight(compile_character(_sheet(), actor_id=O.ME), objects=[
        {'id': 1, 'kind': 'custom', 'x': 4, 'y': 6, 'weight_lb': 1, 'blocks': False}])
    candidate = O.candidates(engine, 'Thread the Object: move object')[0][1]
    intent = ActionIntent(intent_id='auto-thread', actor_id=candidate.actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, target_ids=candidate.target_ids)
    before = engine.state.model_dump(mode='json')
    result = CombatService(ROOT, tmp_path)._run_preview(
        SimpleNamespace(engine=engine, match_id=engine.state.match_id),
        {'participant_control_modes': {a: 'LOCAL_AUTO' for a in engine.state.actors}}, intent, ())
    assert any('Thread the Object moves' in e['payload'].get('log', '') for e in result['events'])
    assert not any(e['event_type'] in ('OBJECT_UPDATED', 'MOVEMENT_COMMITTED') for e in result['events'])
    assert engine.state.model_dump(mode='json') == before


def test_body_refining_movement_button_is_touch_range():
    sheet = _sheet()
    sheet['path_and_subpath'] = {'path_record_ids': ['tianxia.path.body_refining']}
    bundle = compile_character(sheet, actor_id=O.ME)
    row = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Thread the Object: move object')
    assert row['range_ft'] == 5
