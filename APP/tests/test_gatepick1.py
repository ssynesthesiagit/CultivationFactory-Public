"""Guarded Threshold: one map checkpoint for one or two independent lines."""
from pathlib import Path
import subprocess

import pytest

from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from combat.ext import vermilion_gate as gate
from tests import test_riders_c7 as C7


@pytest.mark.parametrize('count', [1, 2])
def test_combined_table_answer_cold_reload_and_replay(tmp_path, count):
    owner, foe = C7.ME, C7.FOE
    features = ['guardian_at_the_gate'] + (['twin_guardian_posts'] if count == 2 else [])
    bundles = [C7.bundle([C7.GATE_IDS + feature for feature in features]), C7.bundle([], actor_id=foe)]
    combat = CombatService(C7.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [owner, foe], {owner: 'team:a', foe: 'team:b'},
        {owner: {'x': 3, 'y': 6}, foe: {'x': 8, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [owner], [foe],
        control_modes={owner: 'MANUAL', foe: 'MANUAL'}, match_seed='GATEPICK1',
        display_name='Gate placement', maximum_rounds=6)['match_id']
    # Genesis defaults do not ask. Advancing back to the owner's turn must ask once.
    for _ in range(3):
        menu = table.state(mid)['menu']
        result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])
        if result['status'] == 'REACTION_REQUIRED':
            break
        assert result['status'] == 'COMMITTED'
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.threshold_placements'
    placement = prompt['choice']['map_pick']['placements']
    assert len(placement['defaults']) == count
    rows = placement['options']
    option_labels = {option['id']: option['label'] for option in prompt['choice']['options']}
    east_west = next(key for key, row in rows.items() if row['slot'] == 0 and row['orientation'] == 'east_west')
    north_south = next(key for key, row in rows.items() if row['slot'] == 0 and row['orientation'] == 'north_south')
    assert 'east to west' in option_labels[east_west]
    assert 'north to south' in option_labels[north_south]
    selected = []
    for slot in range(count):
        candidates = [key for key, row in rows.items() if row['slot'] == slot
                      and row['orientation'] == ('east_west' if slot == 0 else 'diagonal_up')]
        selected.append(candidates[-1])
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    # Reload the paused action from disk before answering; checkpoint + legal pool are stable.
    cold = CombatService(C7.ROOT, tmp_path)
    cold_table = TabletopService(cold, tmp_path)
    again = cold_table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])
    assert again['reaction'] == prompt
    assert cold._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': selected}
    committed = cold_table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [answer])
    assert committed['status'] == 'COMMITTED', committed
    loaded = CombatService(C7.ROOT, tmp_path)._load_session(mid)
    lines = loaded.engine.state.actors[owner].turn_flags[gate.THRESHOLDS]
    expected = [[row['area'][0]['x'], row['area'][0]['y'], row['area'][-1]['x'], row['area'][-1]['y']]
                for row in (rows[key] for key in selected)]
    assert lines == expected
    zones = [z for z in loaded.engine.state.zones.values() if z.active and z.trigger_profile.get('gate_threshold')]
    assert len(zones) == count
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_duplicate_slot_answer_is_rejected_by_table_without_committing(tmp_path):
    owner, foe = C7.ME, C7.FOE
    bundles = [C7.bundle([C7.GATE_IDS + 'guardian_at_the_gate', C7.GATE_IDS + 'twin_guardian_posts']),
               C7.bundle([], actor_id=foe)]
    combat = CombatService(C7.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [owner, foe], {owner: 'team:a', foe: 'team:b'},
        {owner: {'x': 3, 'y': 6}, foe: {'x': 8, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [owner], [foe],
        control_modes={owner: 'MANUAL', foe: 'MANUAL'}, match_seed='GATEPICK1-invalid-slot',
        display_name='Gate placement validation', maximum_rounds=6)['match_id']
    for _ in range(3):
        menu = table.state(mid)['menu']
        result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])
        if result['status'] == 'REACTION_REQUIRED':
            break
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    slot_zero = [key for key, row in prompt['choice']['map_pick']['placements']['options'].items()
                 if row['slot'] == 0]
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': slot_zero[:2]}
    with pytest.raises(CombatServiceError) as rejected:
        table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [answer])
    assert rejected.value.diagnostic.code == 'COMBAT_AI_INTENT_INVALID'
    assert rejected.value.diagnostic.details['reason'] == 'Guarded Threshold requires one legal placement for each gate'
    loaded = CombatService(C7.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == before


def test_all_candidate_lines_and_defaults_preserved():
    engine, owner, _ = C7._gate(['twin_guardian_posts'])
    options, defaults = gate._placements(engine, owner, 2)
    for slot in range(2):
        for orientation in gate.ORIENTATIONS:
            assert {key.split('|')[2]: line for key, line in options.items()
                    if key.startswith(f'{slot}|{orientation}|')} == gate._candidates(engine, owner, orientation)
    assert [options[key] for key in defaults] == [[4, 5, 4, 7], [4, 5, 4, 7]]


@pytest.mark.parametrize('control_mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_twin_keeps_existing_choices_and_default_lines(control_mode):
    from combat.gate2_runtime_models import ReactionDecision

    engine, owner, _ = C7._gate(['twin_guardian_posts'])
    engine.typed_control_modes = {owner.entity_id: control_mode}
    asked = []

    def choose(request):
        # A turn helper without an active intent silently uses Needle's fallback
        # and never exercises automatic decisions. Require the real End Turn route.
        assert engine._active_intent is not None
        assert engine._active_intent.actor_id == C7.FOE
        assert request['reactor_id'] == owner.entity_id
        asked.append(request['reaction_source_id'])
        spec = request['extension_choice']
        return ReactionDecision(**{key: request[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                                selection='USE', option_ids=tuple(spec['preferred_option_ids'])), None

    engine.set_reaction_provider(choose)
    assert engine.state.current_actor_id == C7.FOE
    C7.use(engine, 'End turn', actor_id=C7.FOE)
    assert engine.state.current_actor_id == owner.entity_id
    assert asked == ['choice:needle.threshold_orientation', 'choice:needle.threshold_center'] * 2
    assert owner.turn_flags[gate.THRESHOLDS] == [[4, 5, 4, 7], [4, 5, 4, 7]]


def test_narrow_map_keeps_legal_rotations_when_default_orientation_does_not_fit():
    from types import SimpleNamespace
    from combat.gate2_runtime_models import Position

    owner = SimpleNamespace(entity_id='owner', active=True, team_id='a', position=Position(x=0, y=2))
    foe = SimpleNamespace(entity_id='foe', active=True, team_id='b', position=Position(x=0, y=4))
    distance = lambda a, p: max(abs(a.position.x - p.x), abs(a.position.y - p.y)) * 5
    engine = SimpleNamespace(state=SimpleNamespace(actors={'owner': owner, 'foe': foe}),
                             grid=SimpleNamespace(width=1, height=5, square_size_ft=5,
                                                  in_bounds=lambda cell: cell[0] == 0 and 0 <= cell[1] < 5),
                             _distance_actor_to_actor=lambda a, b: distance(a, b.position),
                             _distance_actor_to_cell=distance)
    assert gate._default_orientation(engine, owner)[0] == 'east_west'
    assert gate._candidates(engine, owner, 'east_west') == {}
    options, defaults = gate._placements(engine, owner, 2)
    assert len(defaults) == 2
    assert all('|north_south|' in key for key in defaults)
    for slot in range(2):
        assert {key.split('|')[2]: line for key, line in options.items() if key.startswith(f'{slot}|north_south|')} \
            == gate._candidates(engine, owner, 'north_south')


@pytest.mark.parametrize('name', [
    'test_guarded_threshold_is_placed_and_guardian_at_the_gate_stops_a_crossing',
    'test_a_missed_guardian_strike_lets_the_crossing_finish',
    'test_twin_guardian_posts_two_lines_and_an_extra_result',
    'test_threshold_between_worlds_checks_teleports_and_gives_half_cover',
    'test_shelter_behind_the_gate_cuts_a_push_on_an_ally_near_the_threshold',
    'test_heavens_closed_gate_stops_a_hostile_crossing_and_shelters_those_inside',
])
def test_existing_vermilion_gate_regressions(name):
    getattr(C7, name)()


def test_combined_grid_dom_and_existing_picker():
    script = Path(__file__).resolve().parents[1] / 'static/tabletop/tabletop_map_pick.test.mjs'
    result = subprocess.run(['node', '--test', '--test-isolation=none', str(script)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
