"""Prepared traps resolve before turn one through persisted manual/AI tables."""
import json
import zipfile

import pytest

from combat.ext import placed
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT
from tests.test_hunt25_mantle_setup import send

OWNER, FOE = 'actor:factory.h35-trap', 'actor:factory.h35-foe'
ROUTE = 'TAL_TRAP_THE_ROUTE_WAS_CHOSEN_ALREADY'
ROAD = 'TAL_TRAP_THE_EMPTY_ROAD_WAS_NEVER_EMPTY'


def fixture(tmp_path, ability, ai=False, ask=True, enclosed=False):
    docs = [sheet([ability] if isinstance(ability, str) else ability, cl=20, kit={'starting_kit': KIT}),
            sheet([], cl=20, kit={'starting_kit': KIT})]
    bundles = []
    for aid, doc in zip((OWNER, FOE), docs):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': ask}))
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    if enclosed:
        combat.tabletop_maps.save({'display_name': 'Prepared trap island', 'width_squares': 14, 'height_squares': 14,
            'walls': [{'shape': 'rect', 'points': points, 'filled': True} for points in
                      ([[5, 2], [8, 3]], [[5, 4], [8, 5]], [[5, 3], [6, 4]], [[7, 3], [8, 4]])],
            'starts': {'team1': [[3, 6]], 'team2': [[8, 6]]}})
        arena = combat.factory_arenas()['battlefield:map.prepared-trap-island']
    mid = combat._finish_factory_match(bundles, [OWNER, FOE], {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8, 'y': 6}},
        arena, [OWNER], [FOE],
        control_modes={OWNER: 'LOCAL_AUTO' if ai else 'MANUAL', FOE: 'LOCAL_AUTO'},
        match_seed='HUNT35-TRAP', maximum_rounds=5, display_name='Prepared traps regression')['match_id']
    return combat, TabletopService(combat, tmp_path), mid


@pytest.mark.parametrize('ability', [ROUTE, ROAD])
@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('decline', [False, True])
def test_prepared_traps_choose_or_decline_before_first_turn_and_reload(tmp_path, ability, ai, decline):
    if ai and decline:
        pytest.skip('AI automatically chooses its legal preparations')
    combat, table, mid = fixture(tmp_path, ability, ai)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert before.get('setup_tasks'), 'initiative placement must be a persisted setup task'
    assert not placed.of(combat._load_session(mid).engine, 'trap')
    answers, chosen = [], None
    for _ in range(5):
        response = send(table, mid, answers)
        if response['status'] == 'COMMITTED':
            break
        assert not ai and response['status'] == 'REACTION_REQUIRED', response
        prompt = response['reaction']
        assert prompt['context']['reactor_id'] == OWNER
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        assert send(table, mid, answers)['reaction'] == prompt
        options = prompt.get('choice', {}).get('options') or []
        if options:
            selected = [o['id'] for o in options if o['id'].startswith('cell:')]
            assert selected
            count = 1 if ability == ROUTE else 4
            chosen = selected[-count:]
            assert '60 feet' in prompt['moment']
        answer = {**prompt['context'], 'selection': 'DECLINE' if decline else 'USE',
                  'option_ids': [] if decline or not options else chosen}
        answers.append(answer)
    else:
        pytest.fail('setup never committed')
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    traps = placed.of(engine, 'trap', owner_id=OWNER)
    assert len(traps) == (4 if ai or ability == ROAD and not decline else 0 if decline else 1)
    if chosen and not decline:
        assert {f'cell:{z.center.x},{z.center.y}' for z in traps} == set(chosen)
    assert not engine.state.setup_tasks
    assert type(engine.state.actors[OWNER].turn_flags['trap_setup_round_done']) is int
    if traps:
        first_trap = next(i for i, e in enumerate(engine.events) if e.event_type == 'ZONE_CREATED')
        first_turn = next(i for i, e in enumerate(engine.events) if e.event_type == 'TURN_STARTED')
        assert first_trap < first_turn
    if ability == ROAD:
        resource = 'resource:uses.reaction:typed.' + ROAD
        assert engine.state.actors[OWNER].resources[resource] == (1 if decline else 0)
    else:
        assert engine.state.actors[OWNER].resources == before['actors'][OWNER]['resources']
    if ability == ROUTE and not decline:
        assert all(FOE not in placed.data(z).get('aware', []) for z in traps)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    # No repeated initiative prompt after starting/ending the first turn.
    state = table.state(mid)
    # End the current turn rather than let AI movement trigger a legitimate
    # off-turn Road relocation decision, which is a separate choice.
    combat.set_controller_mode(mid, actor_id=state['menu']['actor_id'], controller_mode='MANUAL')
    state = table.state(mid)
    menu = state['menu']
    result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()['status'] == 'PASS'


@pytest.mark.parametrize('ability', [ROUTE, ROAD])
def test_manual_placement_is_asked_without_ask_me_reactions(tmp_path, ability):
    combat, table, mid = fixture(tmp_path, ability, ask=False)
    response = send(table, mid)
    assert response['status'] == 'REACTION_REQUIRED'
    prompt = response['reaction']
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['choice']['options'][0]['id'].startswith('cell:')
    # Previewing automatic activation must not spend its Reaction or use.
    if ability == ROAD:
        owner = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
        assert owner.reaction_available
        assert owner.resources['resource:uses.reaction:typed.' + ROAD] == 1


def test_route_preparation_excludes_physically_unreachable_spaces(tmp_path):
    combat, table, mid = fixture(tmp_path, ROUTE, enclosed=True)
    engine = combat._load_session(mid).engine
    from combat.gate2_runtime_models import Position
    island = Position(x=6, y=3)
    assert (6, 3) not in engine.grid.blocked
    assert engine.grid.distance_ft(engine.state.actors[OWNER].position, island) <= 60
    prompt = send(table, mid)['reaction']
    options = {o['id'] for o in prompt['choice']['options']}
    assert 'cell:6,3' not in options
    assert 'cell:4,6' in options


def test_both_preparations_share_one_task_without_duplicate_placement(tmp_path):
    combat, table, mid = fixture(tmp_path, [ROUTE, ROAD], ai=True)
    assert len(combat._load_session(mid).engine.state.setup_tasks) == 1
    assert send(table, mid)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    traps = placed.of(loaded.engine, 'trap', owner_id=OWNER)
    assert len(traps) == 8  # Road raises the active limit by PB before its four placements.
    assert len({(z.center.x, z.center.y) for z in traps}) == 8
    assert loaded.engine.state.actors[OWNER].resources['resource:uses.reaction:typed.' + ROAD] == 0
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
