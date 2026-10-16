"""Witness uses bound provenance for opaque forged checks at the table."""
import pytest

from combat.gate5_service import CombatService
from tests import test_a2r11_foundations as f
from tests.test_a2r03_fix_round import _add_companion, _prepare_pressure, COMPANION
from tests.test_a2r03_review_repairs import _action


@pytest.mark.parametrize('roller', [f.FIGHTER, COMPANION])
@pytest.mark.parametrize('check', [{'kind': 'check', 'ability': 'STR'}, {'kind': 'cultivation'}],
                         ids=['strength', 'cultivation'])
@pytest.mark.parametrize('key,lineage,qualifies', [
    ('source', 'TAL_ATHLETICS_SURE_GRIP', True),
    ('option_of', 'TAL_ATHLETICS_SURE_GRIP', True),
    ('forged_from', 'TAL_BRUTE_MOUNTAIN_MOVING_PALM', True),
    ('forged_from', 'TAL_DESTRUCTION_BLAST', False),
])
def test_bound_witness_check_commits_payment_and_bonus_after_reload(
        tmp_path, monkeypatch, roller, check, key, lineage, qualifies):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        _add_companion(bundles)
        row = _action(bundles, 'Beast Blood Hunger in title only', [{
            'type': 'contest_against', 'harmful': True, 'applies_to': 'target',
            'actor_check': check, 'target_check': check,
            'on_success': [], 'on_fail': [],
        }], source='forged:719a8bc2')
        row['range_ft'] = 120
        row['parameters']['typed'].update({key: lineage, 'typing_status': 'forged'})

    _, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE, ally=True,
        foe_creature_types=('Humanoid',), prepare=prepare,
        positions={f.FIGHTER: {'x': 4, 'y': 7}})
    # Read through a fresh service before and after the committed action.
    before = f._engine(CombatService(f.ROOT, tmp_path), mid)
    assert before.state.actors[f.SERVICE_FOE].creature_types == ('Humanoid',)
    _, prompts = f._play(table, mid, f._candidate(
        table, mid, 'Beast Blood Hunger in title only', roller), answer='USE')
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    witness = [p for p in prompts if 'Beast-Sense Witness' in p['reaction']]
    assert bool(witness) is qualifies
    assert cold.state.actors[f.FIGHTER].resources[f.ECHO] == 1 - int(qualifies)
    assert cold.state.actors[f.FIGHTER].reaction_available is True
    benefits = [e for e in cold.events if e.event_type == 'PASSIVE_TRIGGERED'
                and roller in e.target_ids and 'uses Beast-Sense Witness' in e.payload.get('log', '')]
    assert bool(benefits) is qualifies
    if qualifies:
        bonus = cold.state.actors[f.FIGHTER].proficiency_bonus * (2 if roller == COMPANION else 1)
        assert any(f'add {bonus}' in str(p) for p in witness)
        assert any(f'adds {bonus}' in e.payload['log'] for e in benefits)
