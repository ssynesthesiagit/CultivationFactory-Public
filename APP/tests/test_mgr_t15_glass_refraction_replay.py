"""Glass Heart Refraction: the turn-start scene answer must agree with its real-engine replay.

Synthetic table fixtures only: no live models, private inputs or GUI.
"""
import pytest

from combat.ext.foundation_combat import held
from combat.ext.glass_heart_refraction import CHOICE
from tests.glass_refraction_support import _asked, _glass_fight, _to_next_owner_turn, available
from tests.test_a2_foundations_two import use
from tests.worker2_support import OWNER, reload


@pytest.mark.parametrize('match_seed', [None, 'GLASS-TURN-0'])
def test_turn_start_major_combat_is_offered_after_cold_replay(tmp_path, match_seed):
    # Script 1: the bearer's turn-start answer "Major combat" must be offered on that
    # same turn after a cold reload that replays the saved fight.
    combat, table, mid = _glass_fight(tmp_path, match_seed=match_seed)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert len(_asked(prompts)) == 1
    assert reload(tmp_path, mid).state.current_actor_id == OWNER
    assert available(reload(tmp_path, mid)), \
        'a Major combat answer on the bearer turn start must be offered after the replay'
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    assert held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')


@pytest.mark.parametrize('match_seed', [None, 'GLASS-TURN-0'])
def test_neither_turn_start_answer_is_not_offered_after_cold_replay(tmp_path, match_seed):
    # Script 2: the same replay path must keep a Neither answer unavailable.
    combat, table, mid = _glass_fight(tmp_path, match_seed=match_seed)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Neither']})
    assert len(_asked(prompts)) == 1
    assert not available(reload(tmp_path, mid)), 'a Neither answer must not offer the paid state'
