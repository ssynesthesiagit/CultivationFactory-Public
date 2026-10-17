"""Regressions for the three GATEPICK1 Sol review findings."""
from pathlib import Path
import subprocess

import pytest

from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from tests import test_riders_c7 as C7


def test_table_rejects_two_gate_selections_for_the_same_slot(tmp_path):
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
    options = prompt['choice']['options']
    labels = {option['id']: option['label'] for option in options}
    rows = prompt['choice']['map_pick']['placements']['options']
    east_west = next(key for key, row in rows.items() if row['slot'] == 0 and row['orientation'] == 'east_west')
    north_south = next(key for key, row in rows.items() if row['slot'] == 0 and row['orientation'] == 'north_south')
    assert 'east to west' in labels[east_west]
    assert 'north to south' in labels[north_south]
    slot_zero = [key for key, row in rows.items() if row['slot'] == 0]
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': slot_zero[:2]}
    with pytest.raises(CombatServiceError):
        table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [answer])
    loaded = CombatService(C7.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == before


def test_narrow_map_rotation_keeps_displayed_and_confirmed_line_in_sync():
    script = Path(__file__).resolve().parents[1] / 'static/tabletop/tabletop_map_pick.test.mjs'
    result = subprocess.run(['node', '--test', '--test-isolation=none', str(script)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
